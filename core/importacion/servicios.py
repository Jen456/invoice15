"""Flujo de importación (siempre dentro de la empresa activa, que decide el servidor por membresía).

1. Importación: crear_lote guarda cada archivo una sola vez por empresa (SHA-256) y crea una entrada por archivo;
   crear_lote_de_claves crea una entrada por clave de acceso (lista pegada o reporte del portal del SRI: reporte_sri).
2. Validación: procesar_entrada analiza XML (xml_sri), PDF (ride_pdf → clave → XML del SRI) o una clave (→ XML del SRI).
3. Verificación: verificar_en_sri compara el documento con lo que el SRI tiene autorizado.
4. Clasificación: emitido / recibido / ajeno / revisión manual, por coincidencia EXACTA del RUC de la empresa.
5. Revisión y vinculación: revisar(...) aprueba, descarta, clasifica a mano o vincula con una compra o venta existente.
6. Propuesta contable: revisable; nunca se marca como contabilizado (no hay libro mayor).
7. Incorporación en lote (importación masiva): plan_incorporacion muestra qué se puede incorporar y por qué no, e
   incorporar_lote crea las compras (agrupadas por tarifa, con los datos tributarios pendientes de revisión), registra las
   retenciones recibidas o vincula ventas, documento por documento y reutilizando los servicios de cada acción.

La idempotencia la garantizan restricciones de base de datos (archivo por empresa+hash, documento por
empresa+ambiente+clave): si dos importaciones chocan, la que pierde reutiliza lo que guardó la otra.
"""
import hashlib
import logging
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.importacion import clave_acceso, limites, reporte_sri
from core.importacion.models import (ArchivoImportado, DocumentoImportado, EntradaLote, EventoImportacion, ImpuestoImportado,
                                     LoteImportacion, ReglaImportacion)
from core.importacion.ride_pdf import procesar_ride_pdf
from core.importacion.sri_autorizacion import consultar_autorizacion
from core.importacion.xml_sri import MENSAJE_NO_SOPORTADO, NOMBRES, SOPORTADOS, procesar_xml_sri

PENDIENTES = ('en_cola', 'procesando')
ORIGEN_DOCUMENTO = {'claves': 'lista', 'reporte': 'reporte'}   # origen del lote → origen del documento registrado por su clave
REINTENTABLES = ('sri_no_disponible', 'en_proceso_sri', 'no_encontrada_sri')   # el SRI puede responder más tarde
REINTENTABLES_AUTOMATICOS = ('sri_no_disponible', 'en_proceso_sri')             # la tarea programada reintenta solo estos
CAMPOS_VERIFICADOS = ('emisor_ruc', 'receptor_identificacion', 'fecha_emision', 'numero', 'total_sin_impuestos', 'total_iva',
                      'importe_total')


class ErrorImportacion(Exception):
    """Mensaje para el usuario. `codigo` identifica el caso (p. ej. confirmar_sin_verificar o un error de Ventas)."""

    def __init__(self, mensaje, codigo=''):
        super().__init__(mensaje)
        self.codigo = codigo


def evento(tipo, mensaje, documento=None, lote=None, entrada=None, usuario=None, **datos):
    return EventoImportacion.objects.create(tipo=tipo, mensaje=mensaje[:500], documento=documento, lote=lote, entrada=entrada,
                                            usuario=usuario, datos=datos)


def reglas_de(company):
    regla = ReglaImportacion.objects.filter(company=company).first()
    if regla is None:
        try:
            with transaction.atomic():
                regla = ReglaImportacion.objects.create(company=company)
        except IntegrityError:
            regla = ReglaImportacion.objects.get(company=company)
    return regla


# ------------------------------------------------------------------ 1. importación

def detectar_tipo(datos):
    """Por el contenido, no por la extensión ni el MIME."""
    cuerpo = datos.lstrip(b'\xef\xbb\xbf\x00\t\r\n ')
    if cuerpo.startswith(b'%PDF-'):
        return 'pdf'
    if cuerpo.startswith(b'<'):
        return 'xml'
    return 'desconocido'


def guardar_archivo(company, usuario, nombre, datos, tipo, origen='subido'):
    """(ArchivoImportado, nuevo). El mismo contenido se guarda una sola vez por empresa."""
    sha = hashlib.sha256(datos).hexdigest()
    existente = ArchivoImportado.objects.filter(sha256=sha).first()
    if existente:
        return existente, False
    archivo = ArchivoImportado(company=company, sha256=sha, tipo=tipo, origen=origen, tamano=len(datos),
                               nombre_original=(nombre or '')[:255], subido_por=usuario)
    archivo.archivo.save(f'{sha[:16]}.{tipo}', ContentFile(datos), save=False)
    try:
        with transaction.atomic():
            archivo.save()
        return archivo, True
    except IntegrityError:   # otra importación simultánea guardó el mismo archivo: se reutiliza el suyo
        archivo.archivo.delete(save=False)
        return ArchivoImportado.objects.get(sha256=sha), False


def crear_lote(company, usuario, archivos):
    """archivos: [(nombre, bytes)]. Crea el lote y agrega los archivos (ver agregar_archivos)."""
    _validar_peticion(archivos, 0, 0)
    lote = LoteImportacion.objects.create(company=company, usuario=usuario, total_archivos=0)
    evento('lote_creado', 'Lote creado', lote=lote, usuario=usuario)
    return agregar_archivos(lote, usuario, archivos)


def _validar_peticion(archivos, ya_en_lote, bytes_en_lote):
    if not archivos:
        raise ErrorImportacion('Selecciona al menos un archivo XML o PDF.')
    if ya_en_lote + len(archivos) > limites.MAX_ARCHIVOS_POR_LOTE:
        raise ErrorImportacion(f'Un lote admite hasta {limites.MAX_ARCHIVOS_POR_LOTE} archivos.')
    tamano = sum(len(d) for _, d in archivos)
    if tamano > limites.MAX_BYTES_POR_PETICION:
        raise ErrorImportacion(f'Sube como máximo {limites.MAX_BYTES_POR_PETICION // limites.MB} MB por vez (puedes agregar más al lote).')
    if bytes_en_lote + tamano > limites.MAX_BYTES_POR_LOTE:
        raise ErrorImportacion(f'El lote supera {limites.MAX_BYTES_POR_LOTE // limites.MB} MB en total.')


def agregar_archivos(lote, usuario, archivos):
    """Guarda cada archivo (una vez por empresa) con su entrada y procesa de inmediato los XML (rápidos).

    Los PDF quedan en cola: los procesa procesar_lote (lo llama el navegador o la tarea programada).
    """
    from django.db.models import Max, Sum
    company = lote.company
    with transaction.atomic():
        lote = LoteImportacion.objects.select_for_update().get(pk=lote.pk)
        resumen = lote.entradas.aggregate(n=Max('orden'), bytes=Sum('tamano'))
        _validar_peticion(archivos, lote.entradas.count(), resumen['bytes'] or 0)
        inicio = (resumen['n'] + 1) if resumen['n'] is not None else 0
        LoteImportacion.objects.filter(pk=lote.pk).update(total_archivos=lote.entradas.count() + len(archivos), estado='procesando',
                                                          terminado=None)
    lote.refresh_from_db()
    for orden, (nombre, datos) in enumerate(archivos, start=inicio):
        tipo = detectar_tipo(datos)
        entrada = EntradaLote(company=company, lote=lote, nombre=(nombre or f'archivo-{orden + 1}')[:255], tamano=len(datos),
                              tipo=tipo, orden=orden)
        limite = {'xml': limites.MAX_XML_BYTES, 'pdf': limites.MAX_PDF_BYTES}.get(tipo)
        if limite is None:
            entrada.estado, entrada.errores = 'rechazado', [{'codigo': 'tipo_archivo', 'texto': 'Solo se admiten XML del SRI y RIDE en PDF (se revisa el contenido, no la extensión).'}]
        elif len(datos) > limite:
            entrada.estado, entrada.errores = 'rechazado', [{'codigo': 'archivo_grande', 'texto': f'El archivo supera {limite // limites.MB} MB.'}]
        else:
            entrada.archivo, _ = guardar_archivo(company, usuario, nombre, datos, tipo)
        entrada.save()
    evento('archivos_agregados', f'{len(archivos)} archivos agregados', lote=lote, usuario=usuario)
    for entrada in lote.entradas.filter(estado='en_cola', tipo='xml'):
        procesar_entrada(entrada, usuario)
    actualizar_estado_lote(lote)
    return lote


def actualizar_estado_lote(lote):
    if lote.entradas.filter(estado__in=PENDIENTES).exists():
        estado = 'procesando'
    elif lote.entradas.filter(estado='rechazado').exists():
        estado = 'con_errores'
    else:
        estado = 'terminado'
    cambios = {'estado': estado, 'terminado': timezone.now() if estado != 'procesando' and lote.terminado is None else lote.terminado}
    LoteImportacion.objects.filter(pk=lote.pk).update(**cambios)
    lote.estado, lote.terminado = cambios['estado'], cambios['terminado']
    return lote


def procesar_lote(lote, usuario, maximo=limites.PROCESAR_POR_PETICION, presupuesto=limites.PRESUPUESTO_PETICION_SEGUNDOS):
    """Procesa hasta `maximo` entradas en cola (cada llamada avanza; dos llamadas a la vez no toman la misma entrada).

    No empieza otra entrada ni otra verificación cuando ya pasaron `presupuesto` segundos (presupuesto=None: sin límite,
    para la tarea programada): la petición web termina antes del corte de gunicorn y la siguiente llamada continúa.
    """
    import time
    inicio = time.monotonic()

    def queda_tiempo():
        return presupuesto is None or time.monotonic() - inicio < presupuesto

    procesadas = 0
    while procesadas < maximo and (procesadas == 0 or queda_tiempo()):
        with transaction.atomic():
            entrada = (EntradaLote.objects.select_for_update(skip_locked=True).filter(lote=lote, estado='en_cola')
                       .order_by('orden', 'id').first())
            if entrada is None:
                break
            EntradaLote.objects.filter(pk=entrada.pk).update(estado='procesando', intentos=entrada.intentos + 1)
        procesar_entrada(EntradaLote.objects.get(pk=entrada.pk), usuario)
        procesadas += 1
    if lote.entradas.filter(estado__in=PENDIENTES).count() == 0 and reglas_de(lote.company).verificar_con_sri:
        for documento in lote.documentos.filter(estado_procesamiento='procesado', verificado_en__isnull=True)[:maximo]:
            if not queda_tiempo():
                break
            verificar_en_sri(documento, usuario)
    return actualizar_estado_lote(lote)


# ------------------------------------------------------------------ 2. validación

def _mensajes(lista):
    return [{'codigo': m.codigo, 'texto': m.texto} for m in lista]


def procesar_entrada(entrada, usuario):
    """Analiza el archivo o la clave de la entrada. Nunca lanza por el contenido: el resultado queda en la entrada."""
    entrada.estado = 'procesando'
    try:
        if entrada.tipo == 'clave':
            _entrada_clave(entrada, usuario)
        else:
            with entrada.archivo.archivo.open('rb') as archivo:
                datos = archivo.read()
            if entrada.tipo == 'xml':
                _entrada_xml(entrada, usuario, datos)
            else:
                _entrada_pdf(entrada, usuario, datos)
    except ErrorImportacion as e:
        entrada.estado = 'rechazado'
        entrada.errores = entrada.errores + [{'codigo': 'error', 'texto': str(e)}]
    except Exception as e:   # nunca dejar la entrada en «procesando» para siempre (el lote quedaría eterno)
        logging.getLogger(__name__).exception('Entrada %s del lote %s sin procesar', entrada.pk, entrada.lote_id)
        entrada.estado = 'rechazado'
        entrada.errores = entrada.errores + [{'codigo': 'error_interno',
                                             'texto': f'No se pudo procesar ({e.__class__.__name__}); vuelve a intentarlo o avisa a soporte.'}]
    entrada.procesado_en = timezone.now()
    entrada.save()
    return entrada


def _entrada_xml(entrada, usuario, datos):
    resultado = procesar_xml_sri(datos)
    entrada.errores, entrada.advertencias = _mensajes(resultado.errores), _mensajes(resultado.advertencias)
    if not resultado.aceptado:
        entrada.estado = 'rechazado'
        evento('rechazado', '; '.join(e['texto'] for e in entrada.errores)[:500], lote=entrada.lote, entrada=entrada, usuario=usuario)
        return
    documento, duplicado = registrar_xml(entrada.company, usuario, resultado, entrada.archivo, entrada.lote, origen='xml')
    entrada.documento = documento
    entrada.estado = 'duplicado' if duplicado else 'procesado'


def _entrada_pdf(entrada, usuario, datos):
    resultado = procesar_ride_pdf(datos)
    entrada.errores, entrada.advertencias = _mensajes(resultado.errores), _mensajes(resultado.advertencias)
    entrada.candidatas = resultado.candidatas
    if resultado.estado in ('sin_clave', 'ambigua'):
        entrada.estado = 'pendiente_clave'
        return
    if not resultado.aceptado:
        entrada.estado = 'rechazado'
        return
    documento, duplicado = registrar_clave(entrada.company, usuario, resultado.clave, origen='pdf', archivo_pdf=entrada.archivo,
                                           lote=entrada.lote)
    entrada.documento = documento
    if duplicado:
        entrada.estado = 'duplicado'
    elif documento.estado_procesamiento == 'pendiente_xml':
        recuperar_xml(documento, usuario)
        entrada.estado = 'procesado' if documento.estado_procesamiento == 'procesado' else 'pendiente_xml'
    else:
        entrada.estado = 'procesado'


def usar_clave_manual(entrada, usuario, clave):
    """El usuario escribe (o elige entre las candidatas) la clave de un PDF que no se pudo leer."""
    try:
        clave_acceso.analizar(clave)
    except clave_acceso.ClaveInvalida as e:
        raise ErrorImportacion(str(e))
    documento, duplicado = registrar_clave(entrada.company, usuario, clave.strip(), origen='manual', archivo_pdf=entrada.archivo,
                                           lote=entrada.lote)
    entrada.documento = documento
    if not duplicado and documento.estado_procesamiento == 'pendiente_xml':
        recuperar_xml(documento, usuario)
    entrada.estado = 'duplicado' if duplicado else ('procesado' if documento.estado_procesamiento == 'procesado' else 'pendiente_xml')
    entrada.errores = []
    entrada.procesado_en = timezone.now()
    entrada.save()
    actualizar_estado_lote(entrada.lote)
    return entrada


# ------------------------------------------------------------------ 1b. importación masiva por claves (lista o reporte del SRI)

def crear_lote_de_claves(company, usuario, lista, origen, reporte=None):
    """Lote con una entrada por clave (`lista`: reporte_sri.Lista). Antes de consultar al SRI rechaza lo que no hace falta
    consultar: claves mal formadas o alteradas, tipos no soportados y filas cuyo receptor (según el reporte) es otra empresa.
    Las claves repetidas en la misma lista quedan como duplicado sin consulta. El resto queda en cola: procesar_lote las
    consulta al SRI por partes."""
    if origen not in ORIGEN_DOCUMENTO:
        raise ErrorImportacion('Origen del lote no válido.')
    if not lista.filas:
        raise ErrorImportacion('No se encontró ninguna clave de acceso.' if lista.formato == 'texto'
                               else 'El reporte no trae filas con clave de acceso.')
    if len(lista.filas) > limites.MAX_CLAVES_POR_LOTE:
        raise ErrorImportacion(f'Un lote admite hasta {limites.MAX_CLAVES_POR_LOTE} claves: divide la lista.')
    ruc = (company.ruc or '').strip()
    lote = LoteImportacion.objects.create(company=company, usuario=usuario, origen=origen, reporte=reporte, total_archivos=len(lista.filas))
    evento('lote_creado', f'Lote de {len(lista.filas)} claves ({lote.get_origen_display().lower()})', lote=lote, usuario=usuario,
           resumen=lista.resumen())
    vistas = {}
    for fila in lista.filas:
        entrada = EntradaLote(company=company, lote=lote, nombre=(fila.clave or fila.texto or f'fila-{fila.orden + 1}')[:255],
                              tipo='clave', clave=fila.clave, orden=fila.orden, sugerencias=dict(fila.sugerencias),
                              errores=list(fila.errores), advertencias=list(fila.advertencias))
        if fila.errores:
            entrada.estado = 'rechazado'
        else:
            datos = clave_acceso.analizar(fila.clave)
            receptor = (fila.sugerencias.get('receptor_identificacion') or '').strip()
            if datos.cod_doc not in SOPORTADOS:
                entrada.estado = 'rechazado'
                entrada.errores = [{'codigo': 'tipo_no_soportado',
                                    'texto': f'{NOMBRES.get(datos.cod_doc, "Comprobante " + datos.cod_doc)} ({datos.cod_doc}): {MENSAJE_NO_SOPORTADO}'}]
            elif receptor and receptor != ruc and datos.ruc != ruc:
                entrada.estado = 'rechazado'
                entrada.errores = [{'codigo': 'otra_empresa', 'texto': 'Según el reporte, el receptor de este comprobante no es '
                                                                       'esta empresa: no se consulta ni se importa.'}]
            elif fila.clave in vistas:
                entrada.estado = 'duplicado'
                entrada.advertencias = entrada.advertencias + [{'codigo': 'repetida_en_lista',
                                                                'texto': f'Repetida en la lista (fila {vistas[fila.clave] + 1}).'}]
            else:
                vistas[fila.clave] = fila.orden
                if datos.ambiente == 1:   # los comprobantes recibidos reales son de producción, sea cual sea el ambiente propio
                    entrada.advertencias = entrada.advertencias + [{
                        'codigo': 'ambiente_pruebas',
                        'texto': 'Clave del ambiente de PRUEBAS del SRI: se importa para revisarla, pero no sustenta una compra.'}]
                entrada.estado = 'en_cola'
        entrada.save()
    return actualizar_estado_lote(lote)


def _entrada_clave(entrada, usuario):
    """Registra la clave (o encuentra el documento que ya la tenía) y pide el XML al SRI. Sin XML queda pendiente con el motivo."""
    documento, duplicado = registrar_clave(entrada.company, usuario, entrada.clave, origen=ORIGEN_DOCUMENTO[entrada.lote.origen],
                                           lote=entrada.lote)
    entrada.documento = documento
    if duplicado:
        entrada.estado = 'duplicado'
        entrada.advertencias = entrada.advertencias + [{'codigo': 'ya_importada', 'texto': f'{documento.numero} ya estaba importada.'}]
        _anotar_comparacion(entrada, documento)
        return
    if documento.estado_procesamiento == 'pendiente_xml':
        recuperar_xml(documento, usuario)
    if documento.estado_procesamiento == 'procesado':
        entrada.estado = 'procesado'
        entrada.errores = []
        _anotar_comparacion(entrada, documento)
    else:
        entrada.estado = 'pendiente_xml'
        motivo = documento.get_estado_verificacion_display()
        entrada.errores = [{'codigo': documento.estado_verificacion, 'texto': f'Sin XML autorizado: {motivo.lower()}.'}]


def _anotar_comparacion(entrada, documento):
    """Guarda en la entrada la comparación entre lo que decía el reporte y el XML, y avisa si el documento no es de la empresa."""
    if documento.estado_procesamiento != 'procesado':
        return
    if entrada.sugerencias:
        entrada.sugerencias = {**entrada.sugerencias, 'comparacion': reporte_sri.comparar_con_documento(entrada.sugerencias, documento)}
    if documento.clasificacion == 'ajeno':
        entrada.advertencias = entrada.advertencias + [{'codigo': 'ajeno', 'texto': 'El XML no es emitido ni recibido por esta '
                                                                                 'empresa: no se incorpora.'}]
    elif documento.clasificacion == 'emitido':
        entrada.advertencias = entrada.advertencias + [{'codigo': 'emitido', 'texto': 'Es un comprobante emitido por la empresa, '
                                                                                   'no recibido.'}]


def reintentables(lote):
    return EntradaLote.objects.filter(lote=lote, estado='pendiente_xml', tipo='clave', documento__estado_procesamiento='pendiente_xml',
                                      documento__estado_verificacion__in=REINTENTABLES).count()


def reencolar_pendientes(lote):
    """Vuelve a poner en cola las entradas de clave sin XML cuyo documento sigue esperándolo por un motivo reintentable (el SRI
    no respondió o aún no tenía la clave). Devuelve cuántas; procesar_lote las consulta otra vez."""
    pendientes = (EntradaLote.objects.filter(lote=lote, estado='pendiente_xml', tipo='clave', documento__estado_procesamiento='pendiente_xml',
                                              documento__estado_verificacion__in=REINTENTABLES))
    return pendientes.update(estado='en_cola')


def _datos_documento(resultado):
    c = resultado.comprobante
    return dict(cod_doc=c.cod_doc, version=c.version, ambiente=c.ambiente, estab=c.estab, pto_emi=c.pto_emi, secuencial=c.secuencial,
                numero=c.numero, fecha_emision=c.fecha_emision, numero_autorizacion=resultado.numero_autorizacion[:49],
                fecha_autorizacion=resultado.fecha_autorizacion, emisor_ruc=c.emisor_ruc, emisor_razon_social=c.emisor_razon_social[:300],
                emisor_nombre_comercial=c.emisor_nombre_comercial[:300], receptor_tipo_identificacion=c.receptor_tipo_identificacion[:2],
                receptor_identificacion=c.receptor_identificacion[:20], receptor_razon_social=c.receptor_razon_social[:300],
                moneda=c.moneda[:15], total_sin_impuestos=c.total_sin_impuestos, total_descuento=c.total_descuento, propina=c.propina,
                total_iva=c.total_iva, total_ice=c.total_ice, total_irbpnr=c.total_irbpnr, importe_total=c.importe_total,
                datos=resultado.to_dict(), advertencias=_mensajes(resultado.advertencias), errores=[])


def _completar(documento, resultado, origen, archivo):
    for campo, valor in _datos_documento(resultado).items():
        setattr(documento, campo, valor)
    documento.estado_procesamiento = 'procesado'
    if origen == 'sri':
        documento.estado_verificacion, documento.verificado_en = 'verificada_sri', timezone.now()
        documento.archivo_xml = documento.archivo_xml or archivo
    else:
        documento.estado_verificacion = resultado.verificacion
        documento.archivo_xml = archivo
    documento.clasificacion = clasificar(documento.company, documento.emisor_ruc, documento.receptor_identificacion)
    documento.save()
    documento.impuestos.all().delete()
    for i in resultado.comprobante.impuestos:
        ImpuestoImportado.objects.create(documento=documento, codigo=i.codigo, codigo_porcentaje=i.codigo_porcentaje,
                                         impuesto=i.impuesto, categoria=i.categoria, tarifa=i.tarifa, base_imponible=i.base_imponible,
                                         valor=i.valor, descuento_adicional=i.descuento_adicional,
                                         valor_devolucion_iva=i.valor_devolucion_iva)
    asignar_contraparte(documento)


def registrar_xml(company, usuario, resultado, archivo, lote, origen):
    """(documento, duplicado). Un documento por empresa+ambiente+clave; completa uno que esperaba su XML."""
    c = resultado.comprobante
    with transaction.atomic():
        existente = DocumentoImportado.objects.select_for_update().filter(ambiente=c.ambiente, clave_acceso=c.clave_acceso).first()
        if existente is None:
            documento = DocumentoImportado(company=company, importado_por=usuario, lote=lote, origen=origen, clave_acceso=c.clave_acceso,
                                           ambiente=c.ambiente)
            try:
                with transaction.atomic():
                    _completar(documento, resultado, origen, archivo)
            except IntegrityError:   # importación simultánea de la misma clave
                existente = DocumentoImportado.objects.select_for_update().get(ambiente=c.ambiente, clave_acceso=c.clave_acceso)
            else:
                evento('procesado', f'{NOMBRES[c.cod_doc]} {c.numero} importada ({documento.get_clasificacion_display()}).',
                       documento=documento, lote=lote, usuario=usuario, sha256=resultado.sha256)
                return documento, False
        if existente.estado_procesamiento == 'pendiente_xml':
            _completar(existente, resultado, origen, archivo)
            evento('xml_recibido', f'Se obtuvo el XML de {c.numero}.', documento=existente, lote=lote, usuario=usuario, origen=origen)
            return existente, False
        if existente.archivo_xml_id is None and archivo is not None:
            DocumentoImportado.objects.filter(pk=existente.pk).update(archivo_xml=archivo)
        evento('duplicado', f'{c.numero} ya estaba importada; no se duplica.', documento=existente, lote=lote, usuario=usuario,
               sha256=resultado.sha256)
        return existente, True


def registrar_clave(company, usuario, clave, origen, archivo_pdf=None, lote=None):
    """(documento, duplicado) a partir solo de la clave (RIDE): queda pendiente del XML autorizado."""
    datos = clave_acceso.analizar(clave)
    if datos.cod_doc not in SOPORTADOS:
        raise ErrorImportacion(f'{NOMBRES.get(datos.cod_doc, "Comprobante " + datos.cod_doc)} ({datos.cod_doc}): {MENSAJE_NO_SOPORTADO}')
    with transaction.atomic():
        existente = DocumentoImportado.objects.select_for_update().filter(ambiente=datos.ambiente, clave_acceso=clave).first()
        if existente is not None:
            if existente.archivo_pdf_id is None and archivo_pdf is not None:
                DocumentoImportado.objects.filter(pk=existente.pk).update(archivo_pdf=archivo_pdf)
                existente.archivo_pdf = archivo_pdf
            if existente.estado_procesamiento == 'procesado':
                evento('duplicado', f'{existente.numero} ya estaba importada; se adjunta el RIDE.', documento=existente, lote=lote,
                       usuario=usuario)
                return existente, True
            return existente, False
        documento = DocumentoImportado(company=company, importado_por=usuario, lote=lote, origen=origen, archivo_pdf=archivo_pdf,
                                       clave_acceso=clave, cod_doc=datos.cod_doc, ambiente=datos.ambiente, estab=datos.estab,
                                       pto_emi=datos.pto_emi, secuencial=datos.secuencial, numero=datos.numero,
                                       fecha_emision=datos.fecha_emision, emisor_ruc=datos.ruc, estado_procesamiento='pendiente_xml',
                                       clasificacion=clasificar(company, datos.ruc, ''))
        try:
            with transaction.atomic():
                documento.save()
        except IntegrityError:
            return DocumentoImportado.objects.get(ambiente=datos.ambiente, clave_acceso=clave), False
    evento('clave_registrada', f'Clave de {datos.numero} registrada desde el {"RIDE" if origen == "pdf" else "ingreso manual"}.',
           documento=documento, lote=lote, usuario=usuario)
    return documento, False


# ------------------------------------------------------------------ 3. verificación en el SRI

MOTIVOS_SRI = {'sin_resultados': ('no_encontrada_sri', 'El SRI no tiene un comprobante autorizado con esa clave.'),
               'no_autorizado': ('no_autorizada_sri', 'El SRI responde que la clave NO está autorizada.'),
               'no_disponible': ('sri_no_disponible', 'El SRI no respondió; se puede reintentar más tarde.'),
               'en_proceso': ('en_proceso_sri', 'El SRI todavía está procesando el comprobante; se reintenta más tarde.'),
               'clave_invalida': ('no_encontrada_sri', 'La clave no es válida.')}


def recuperar_xml(documento, usuario):
    """Pide al SRI el XML autorizado de un documento que solo tiene la clave. Sin XML, queda pendiente con el motivo."""
    consulta = consultar_autorizacion(documento.clave_acceso)
    if consulta.estado == 'autorizado':
        resultado = procesar_xml_sri(consulta.xml)
        if resultado.aceptado and resultado.comprobante.clave_acceso == documento.clave_acceso:
            archivo, _ = guardar_archivo(documento.company, usuario, f'{documento.clave_acceso}.xml', consulta.xml, 'xml', origen='sri')
            registrar_xml(documento.company, usuario, resultado, archivo, documento.lote, origen='sri')
            documento.refresh_from_db()
            # las entradas que esperaban este XML (RIDE, clave manual o clave en lote) quedan procesadas
            for entrada in EntradaLote.objects.filter(documento=documento, estado='pendiente_xml'):
                entrada.estado, entrada.errores, entrada.procesado_en = 'procesado', [], timezone.now()
                _anotar_comparacion(entrada, documento)
                entrada.save()
                actualizar_estado_lote(entrada.lote)
            return documento
        motivo = ('discrepancia_sri', 'El SRI devolvió un XML que no se pudo validar: ' +
                  '; '.join(e.texto for e in resultado.errores)[:300])
    else:
        motivo = MOTIVOS_SRI[consulta.estado]
    DocumentoImportado.objects.filter(pk=documento.pk).update(estado_verificacion=motivo[0], verificado_en=timezone.now())
    documento.refresh_from_db()
    evento('xml_no_recuperado', motivo[1], documento=documento, usuario=usuario, intentos=consulta.intentos, mensajes=consulta.mensajes)
    return documento


def verificar_en_sri(documento, usuario):
    """Compara el documento importado con lo que el SRI tiene autorizado para su clave."""
    if documento.estado_procesamiento == 'pendiente_xml':
        return recuperar_xml(documento, usuario)
    consulta = consultar_autorizacion(documento.clave_acceso)
    diferencias = []
    if consulta.estado == 'autorizado':
        resultado = procesar_xml_sri(consulta.xml)
        if not resultado.aceptado:
            estado, mensaje = 'discrepancia_sri', 'El XML que devolvió el SRI no se pudo validar.'
        else:
            oficial = _datos_documento(resultado)
            diferencias = [c for c in CAMPOS_VERIFICADOS if getattr(documento, c) != oficial[c]]
            if diferencias:
                estado, mensaje = 'discrepancia_sri', 'El archivo importado difiere de lo autorizado en el SRI: ' + ', '.join(diferencias) + '.'
            else:
                estado, mensaje = 'verificada_sri', 'Coincide con el comprobante autorizado en el SRI.'
                if documento.archivo_xml_id is None:
                    archivo, _ = guardar_archivo(documento.company, usuario, f'{documento.clave_acceso}.xml', consulta.xml, 'xml', origen='sri')
                    DocumentoImportado.objects.filter(pk=documento.pk).update(archivo_xml=archivo)
    else:
        estado, mensaje = MOTIVOS_SRI[consulta.estado]
    cambios = {'estado_verificacion': estado, 'verificado_en': timezone.now()}
    if estado == 'discrepancia_sri' and documento.clasificacion in ('emitido', 'recibido'):
        cambios['clasificacion'] = 'revision_manual'
    DocumentoImportado.objects.filter(pk=documento.pk).update(**cambios)
    documento.refresh_from_db()
    evento('verificacion', mensaje, documento=documento, usuario=usuario, estado=estado, diferencias=diferencias,
           intentos=consulta.intentos)
    return documento


# ------------------------------------------------------------------ 4. clasificación y contraparte

def clasificar(company, emisor_ruc, receptor_identificacion):
    """Coincidencia exacta con el RUC de la empresa activa (sin recortar cédulas ni RUC)."""
    ruc = (company.ruc or '').strip()
    emite, recibe = emisor_ruc == ruc, bool(receptor_identificacion) and receptor_identificacion == ruc
    if emite and recibe:
        return 'revision_manual'
    if emite:
        return 'emitido'
    if recibe:
        return 'recibido'
    return 'ajeno' if receptor_identificacion else 'pendiente'


def asignar_contraparte(documento):
    """Proveedor o cliente existente con la identificación exacta (no se crean automáticamente)."""
    from core.pos.models import Client, Provider
    proveedor = cliente = None
    if documento.clasificacion == 'recibido':
        proveedor = Provider.objects.filter(ruc=documento.emisor_ruc).first()
    elif documento.clasificacion == 'emitido' and documento.receptor_identificacion:
        cliente = Client.objects.filter(dni=documento.receptor_identificacion).first()
    DocumentoImportado.objects.filter(pk=documento.pk).update(proveedor=proveedor, cliente=cliente)
    documento.proveedor, documento.cliente = proveedor, cliente


def candidatos_conciliacion(documento):
    """Registros existentes que podrían ser este mismo documento (para vincular en lugar de duplicar)."""
    from core.pos.models import Purchase, Sale
    candidatos = []
    if documento.clasificacion == 'recibido':
        # Compras con los datos del comprobante (Etapa 2): solo el mismo comprobante (RUC, tipo, establecimiento, punto y
        # secuencial). Las anteriores, sin secuencial, siguen con la heurística de número, subtotal y fecha.
        exactas = (Purchase.objects.filter(provider__ruc=documento.emisor_ruc, tipo_comprobante=documento.cod_doc,
                                           estab=documento.estab, pto_emi=documento.pto_emi, secuencial=documento.secuencial)
                   .exclude(secuencial='').order_by('pk')[:5])
        for compra in exactas:
            candidatos.append({'tipo': 'compra', 'id': compra.pk, 'numero': compra.number, 'fecha': compra.date_joined.isoformat(),
                               'subtotal': format(Decimal(compra.subtotal), '.2f'), 'razones': ['mismo comprobante'],
                               'exacto': True})
        compras = (Purchase.objects.select_related('provider').filter(provider__ruc=documento.emisor_ruc, secuencial='')
                   .order_by('-date_joined')[:50])
        for compra in compras:
            razones = []
            numero = compra.number.lstrip('0')
            if numero and numero in (documento.secuencial.lstrip('0'), documento.numero.replace('-', '').lstrip('0')):
                razones.append('mismo número')
            if abs(Decimal(compra.subtotal) - documento.total_sin_impuestos) <= Decimal('0.02'):
                razones.append('mismo subtotal')
            if documento.fecha_emision and abs((compra.date_joined - documento.fecha_emision).days) <= 31:
                razones.append('fecha cercana')
            if razones:
                candidatos.append({'tipo': 'compra', 'id': compra.pk, 'numero': compra.number, 'fecha': compra.date_joined.isoformat(),
                                   'subtotal': format(Decimal(compra.subtotal), '.2f'), 'razones': razones,
                                   'exacto': 'mismo número' in razones and 'mismo subtotal' in razones})
    elif documento.clasificacion == 'emitido':
        for venta in Sale.objects.filter(access_code=documento.clave_acceso)[:5]:
            candidatos.append({'tipo': 'venta', 'id': venta.pk, 'numero': venta.voucher_number_full, 'razones': ['misma clave de acceso'],
                               'total': format(Decimal(venta.total), '.2f'), 'exacto': True})
        if not candidatos:
            for venta in Sale.objects.filter(voucher_number_full=documento.numero, receipt__voucher_type='01')[:5]:
                candidatos.append({'tipo': 'venta', 'id': venta.pk, 'numero': venta.voucher_number_full, 'razones': ['mismo número'],
                                   'total': format(Decimal(venta.total), '.2f'), 'exacto': False})
    return sorted(candidatos, key=lambda c: (not c['exacto'], -len(c['razones'])))


def retenciones_relacionadas(documento):
    from core.comprobantes.models import Retencion
    return list(Retencion.objects.filter(aut_doc_sustento=documento.clave_acceso).exclude(
        status__in=('returned', 'not_authorized', 'sequential_registered_error')))


# ------------------------------------------------------------------ 5. revisión y vinculación

def revisar(documento, usuario, accion, datos=None):
    datos = datos or {}
    regla = reglas_de(documento.company)
    with transaction.atomic():
        documento = DocumentoImportado.objects.select_for_update().get(pk=documento.pk)
        if documento.estado_procesamiento != 'procesado' and accion != 'descartar':
            raise ErrorImportacion('Este documento todavía no tiene su XML autorizado: no se puede revisar.')
        if accion == 'clasificar':
            nueva = datos.get('clasificacion')
            if nueva not in ('emitido', 'recibido', 'ajeno'):
                raise ErrorImportacion('Clasificación no válida.')
            if nueva == 'emitido' and documento.emisor_ruc != documento.company.ruc:
                raise ErrorImportacion('Solo es «emitido» si el RUC del emisor es el de la empresa.')
            if nueva == 'recibido' and documento.receptor_identificacion != documento.company.ruc:
                raise ErrorImportacion('Solo es «recibido» si la identificación del receptor es el RUC de la empresa.')
            documento.clasificacion = nueva
            mensaje = f'Clasificado a mano como {documento.get_clasificacion_display()}.'
        elif accion == 'aprobar':
            _exigir_revisable(documento, regla, datos)
            documento.estado_revision = 'aprobado'
            mensaje = 'Aprobado: queda registrado como documento ' + ('recibido.' if documento.clasificacion == 'recibido' else 'emitido.')
            if documento.cod_doc == '07':
                mensaje += ' ' + AVISO_RETENCION
        elif accion in ('vincular_compra', 'vincular_venta'):
            if accion == 'vincular_compra' and documento.cod_doc not in ('01', '04', '05'):
                raise ErrorImportacion('Un comprobante de retención no se vincula con una compra: regístralo en «Registrar '
                                       'retención recibida».')
            if accion == 'vincular_venta' and documento.cod_doc != '01':
                raise ErrorImportacion('Solo una factura emitida se vincula con una venta.')
            _exigir_revisable(documento, regla, datos)
            mensaje = _vincular(documento, accion, datos.get('id'))
            documento.estado_revision = 'vinculado'
        elif accion == 'descartar':
            documento.estado_revision = 'descartado'
            documento.nota_revision = (datos.get('motivo') or '')[:300]
            mensaje = 'Descartado' + (f': {documento.nota_revision}' if documento.nota_revision else '.')
        elif accion == 'reabrir':
            if documento.estado_revision == 'pendiente':
                raise ErrorImportacion('El documento ya está pendiente de revisión.')
            motivo = motivo_sin_reabrir(documento)
            if motivo:
                raise ErrorImportacion(motivo)
            documento.estado_revision, documento.compra, documento.venta = 'pendiente', None, None
            documento.estado_contable, documento.propuesta_contable = 'sin_propuesta', None
            mensaje = 'Reabierto para revisión.'
        elif accion == 'crear_proveedor':
            mensaje = _crear_proveedor(documento, datos)
        else:
            raise ErrorImportacion('Acción no válida.')
        if accion in ('aprobar', 'vincular_compra', 'vincular_venta'):
            documento.propuesta_contable = propuesta_contable(documento, regla)
            documento.estado_contable = 'propuesta' if documento.propuesta_contable else 'sin_propuesta'
        documento.revisado_por, documento.revisado_en = usuario, timezone.now()
        documento.save()
        evento(accion, mensaje, documento=documento, usuario=usuario, datos={k: v for k, v in datos.items() if k != 'csrfmiddlewaretoken'})
    return documento


def _exigir_revisable(documento, regla, datos):
    if documento.clasificacion not in ('emitido', 'recibido'):
        raise ErrorImportacion('Solo se incorporan documentos emitidos o recibidos por la empresa '
                               f'(este está como «{documento.get_clasificacion_display()}»).')
    if documento.estado_revision not in ('pendiente',):
        raise ErrorImportacion(f'El documento ya está «{documento.get_estado_revision_display()}». Reábrelo para cambiarlo.')
    if documento.estado_verificacion in ('no_autorizada_sri', 'no_encontrada_sri', 'discrepancia_sri'):
        raise ErrorImportacion(f'No se puede incorporar: {documento.get_estado_verificacion_display().lower()}.')
    if documento.estado_verificacion != 'verificada_sri' and regla.exigir_verificacion and not datos.get('confirmar_sin_verificar'):
        raise ErrorImportacion('El documento no está verificado en el SRI. Verifícalo o confirma que lo incorporas sin verificar.')


def _vincular(documento, accion, registro_id):
    from core.pos.models import Purchase, Sale
    if accion == 'vincular_compra':
        if documento.clasificacion != 'recibido':
            raise ErrorImportacion('Solo un documento recibido se vincula con una compra.')
        compra = Purchase.objects.select_related('provider').filter(pk=registro_id).first()   # solo compras de la empresa activa
        if compra is None:
            raise ErrorImportacion('La compra no existe.')
        if compra.provider.ruc != documento.emisor_ruc:
            raise ErrorImportacion('La compra es de otro proveedor (el RUC no coincide).')
        if compra.version_datos == 2 and compra.tipo_comprobante != documento.cod_doc:
            raise ErrorImportacion('La compra es de otro tipo de comprobante '
                                   f'({compra.get_tipo_comprobante_display() or "sin tipo"}): no es este documento.')
        if documento.cod_doc in ('04', '05') and compra.purchasedetail_set.filter(product__isnull=False).exists():
            raise ErrorImportacion(f'La compra #{compra.pk} tiene productos y movió el stock: una nota del proveedor no se vincula con '
                                   'ella. Regístrala desde el XML (con líneas de gasto) y revisa el inventario con tu contador.')
        if DocumentoImportado.objects.filter(compra=compra).exclude(pk=documento.pk).exists():
            raise ErrorImportacion('Esa compra ya está vinculada con otro documento importado.')
        documento.compra, documento.proveedor = compra, compra.provider
        return f'Vinculado con la compra #{compra.pk}.'
    if documento.clasificacion != 'emitido':
        raise ErrorImportacion('Solo un documento emitido se vincula con una venta.')
    venta = Sale.objects.select_related('client').filter(pk=registro_id).first()
    if venta is None:
        raise ErrorImportacion('La venta no existe.')
    if venta.access_code and venta.access_code != documento.clave_acceso:
        raise ErrorImportacion('La venta tiene otra clave de acceso.')
    if DocumentoImportado.objects.filter(venta=venta).exclude(pk=documento.pk).exists():
        raise ErrorImportacion('Esa venta ya está vinculada con otro documento importado.')
    documento.venta, documento.cliente = venta, venta.client
    return f'Vinculado con la venta {venta.voucher_number_full}.'


def _crear_proveedor(documento, datos):
    from core.pos.models import Provider
    if documento.clasificacion != 'recibido':
        raise ErrorImportacion('Solo se crea el proveedor de un documento recibido.')
    if documento.cod_doc == '07':
        raise ErrorImportacion('El emisor de un comprobante de retención es tu cliente (agente de retención), no un proveedor.')
    if Provider.objects.filter(ruc=documento.emisor_ruc).exists():
        documento.proveedor = Provider.objects.get(ruc=documento.emisor_ruc)
        return 'El proveedor ya existía: se asignó.'
    documento.proveedor = crear_proveedor_de_documento(documento, datos)
    return f'Proveedor {documento.proveedor.name} creado.'


def crear_proveedor_de_documento(documento, datos):
    """Proveedor del emisor del documento: RUC (tipo 04: el emisor de un comprobante electrónico siempre lo tiene), tipo de
    sujeto según el RUC y parte relacionada solo si se indica («si»/«no»; sin indicar queda NULL y el proveedor queda
    incompleto, DC12). Celular y correo son obligatorios en Proveedores."""
    from core.pos.models import Provider
    from core.pos.proveedores import _parte_relacionada, sujeto_de_ruc
    movil, correo = (datos.get('mobile') or '').strip(), (datos.get('email') or '').strip()
    if not movil or not correo or '@' not in correo:
        raise ErrorImportacion('Para crear el proveedor escribe su celular y su correo (son obligatorios en Proveedores).')
    try:
        with transaction.atomic():
            return Provider.objects.create(name=(documento.emisor_razon_social or documento.emisor_ruc)[:100],
                                           ruc=documento.emisor_ruc, mobile=movil[:10], email=correo[:50], tipo_identificacion='04',
                                           tipo_sujeto=sujeto_de_ruc(documento.emisor_ruc),
                                           parte_relacionada=_parte_relacionada(datos.get('parte_relacionada')))
    except IntegrityError:
        # otra petición creó el mismo proveedor al mismo tiempo: se reutiliza; si lo que choca es el nombre, celular o correo
        # con OTRO proveedor, se informa sin crear nada
        existente = Provider.objects.filter(ruc=documento.emisor_ruc).first()
        if existente is not None:
            return existente
        raise ErrorImportacion('Ya existe un proveedor con ese nombre, celular o correo.')


AVISO_RETENCION = 'La retención se contabiliza con la retención recibida.'


def motivo_sin_reabrir(documento):
    """Texto por el que el documento no se reabre aquí (o ''): la compra se creó desde él (se elimina en Compras), o es un
    07 registrado como retención recibida (se anula allí y el documento vuelve a pendiente)."""
    if documento.estado_revision == 'vinculado' and documento.cod_doc == '07':
        return 'Se incorporó como retención recibida: anula allí el registro de la retención para reabrir el documento.'
    if documento.compra_id and documento.compra.origen == 'importacion':
        return f'La compra #{documento.compra_id} se creó desde este documento: elimínala en Compras para reabrirlo.'
    return ''


# ------------------------------------------------------------------ 6. propuesta contable (no contabiliza)

def propuesta_contable(documento, regla):
    """Asiento propuesto y revisable. No hay libro mayor: no se registra ni se marca como contabilizado."""
    cero = Decimal('0.00')
    lineas, avisos = [], []

    def linea(cuenta, descripcion, debe=cero, haber=cero, etiqueta=''):
        if debe or haber:
            if not cuenta:
                avisos.append(f'Falta la cuenta de {etiqueta or descripcion.lower()} en «Reglas de importación y contabilización».')
            lineas.append({'cuenta': cuenta or '', 'descripcion': descripcion, 'debe': format(debe, '.2f'), 'haber': format(haber, '.2f')})

    otros_impuestos = documento.total_ice + documento.total_irbpnr
    if documento.cod_doc == '07':
        return None     # la retención se contabiliza con la retención recibida (o emitida), no aquí
    reverso = documento.cod_doc == '04'    # nota de crédito: reverso del comprobante que modifica (debe ↔ haber)
    if reverso:
        directa = linea

        def linea(cuenta, descripcion, debe=cero, haber=cero, etiqueta=''):
            directa(cuenta, descripcion, debe=haber, haber=debe, etiqueta=etiqueta)

    if documento.clasificacion == 'recibido':
        cuenta = {'gasto': regla.cuenta_gasto, 'inventario': regla.cuenta_inventario, 'activo_fijo': regla.cuenta_activo_fijo}[regla.naturaleza_compra]
        base = documento.total_sin_impuestos + otros_impuestos + documento.propina
        iva_credito = documento.total_iva if regla.tratamiento_iva == 'credito_tributario' else cero
        if not iva_credito:
            base += documento.total_iva
        linea(cuenta, f'{regla.get_naturaleza_compra_display()} · {documento.emisor_razon_social}', debe=base,
              etiqueta=regla.get_naturaleza_compra_display().lower())
        linea(regla.cuenta_iva_compras, 'IVA en compras (crédito tributario)', debe=iva_credito, etiqueta='IVA en compras')
        renta = iva_ret = cero
        for ret in ([] if reverso else retenciones_relacionadas(documento)):
            for d in ret.detalles.all():
                if d.impuesto == '1':
                    renta += d.valor_retenido
                else:
                    iva_ret += d.valor_retenido
        linea(regla.cuenta_retencion_renta, 'Retención de renta por pagar', haber=renta, etiqueta='retenciones de renta')
        linea(regla.cuenta_retencion_iva, 'Retención de IVA por pagar', haber=iva_ret, etiqueta='retenciones de IVA')
        linea(regla.cuenta_proveedores, f'Proveedor {documento.emisor_razon_social}', haber=documento.importe_total - renta - iva_ret,
              etiqueta='proveedores')
    elif documento.clasificacion == 'emitido':
        linea(regla.cuenta_clientes, f'Cliente {documento.receptor_razon_social}', debe=documento.importe_total, etiqueta='clientes')
        linea(regla.cuenta_ventas, 'Ventas', haber=documento.total_sin_impuestos + otros_impuestos + documento.propina, etiqueta='ventas')
        linea(regla.cuenta_iva_ventas, 'IVA en ventas', haber=documento.total_iva, etiqueta='IVA en ventas')
    else:
        return None
    debe = sum((Decimal(x['debe']) for x in lineas), cero)
    haber = sum((Decimal(x['haber']) for x in lineas), cero)
    if documento.clasificacion == 'emitido' and documento.venta_id:
        avisos.append('La venta ya existe en el sistema: no registres esta venta otra vez, solo concilia el asiento.')
    if reverso:
        avisos.append('Nota de crédito: la propuesta es el reverso del comprobante que modifica.')
    return {'estado': 'propuesta', 'contabilizado': False, 'cuadra': debe == haber, 'debe': format(debe, '.2f'),
            'haber': format(haber, '.2f'), 'lineas': lineas, 'avisos': avisos,
            'nota': 'Propuesta para revisión del contador. FacturaPorAquí aún no lleva libro mayor: no se ha contabilizado.'}


# ------------------------------------------------------------------ 7. incorporación en lote (importación masiva)

CONFIRMACIONES = ('confirmar_plazo_ats', 'confirmar_sin_verificar', 'confirmar_no_duplicada')
ESTADOS_INCORPORACION = {'listo': 'Listo para incorporar', 'requiere_datos': 'Requiere datos o confirmación',
                         'bloqueado': 'No se puede incorporar', 'ya_incorporado': 'Ya incorporado', 'sin_xml': 'Sin XML autorizado',
                         'no_aplica': 'Se revisa a mano', 'rechazado': 'Rechazado', 'duplicado': 'Duplicado'}


def _permisos(request):
    from core.security.session import get_group
    grupo = get_group(request) if request is not None else None
    if grupo is None:
        return set()
    return set(grupo.permissions.values_list('codename', flat=True))


def _accion_de(documento):
    """Qué haría la incorporación en lote con este documento (o None: se revisa a mano en su ficha)."""
    from core.importacion.compras import CODIGOS_DE_COMPRA
    if documento.estado_procesamiento != 'procesado':
        return None
    if documento.clasificacion == 'recibido':
        if documento.cod_doc in CODIGOS_DE_COMPRA:
            return 'crear_compra'
        if documento.cod_doc == '07':
            return 'registrar_retencion'
    elif documento.clasificacion == 'emitido' and documento.cod_doc == '01':
        return 'vincular_venta'
    return None


def _pendientes_de_revision(documento, propuesta):
    """Datos tributarios que la incorporación en lote deja sin decidir (quedan en la compra como datos incompletos)."""
    pendientes = [{'codigo': 'cod_sustento', 'texto': 'Sustento tributario'}]
    if not propuesta.get('forma_pago_del_xml'):
        pendientes.append({'codigo': 'forma_pago', 'texto': 'Forma de pago (el XML no la trae)'})
    if propuesta.get('parte_relacionada') is None:
        pendientes.append({'codigo': 'parte_relacionada', 'texto': 'Parte relacionada'})
    return pendientes


def _plan_documento(entrada, documento, permisos):
    from core.importacion import compras as desde_xml, recibidos
    item = {'entrada_id': entrada.pk, 'orden': entrada.orden, 'clave': entrada.clave or (documento.clave_acceso if documento else ''),
            'documento_id': documento.pk if documento else None, 'entrada_estado': entrada.estado, 'sugerencias': entrada.sugerencias,
            'errores': entrada.errores, 'advertencias': entrada.advertencias, 'accion': None, 'estado': 'rechazado',
            'bloqueos': [], 'confirmaciones': [], 'pendientes_revision': [], 'proveedor': None, 'proveedor_nuevo': None,
            'venta_id': None, 'permiso': True}
    if documento is None:
        item['estado'] = 'duplicado' if entrada.estado == 'duplicado' else 'rechazado'
        return item
    item.update({'numero': documento.numero, 'cod_doc': documento.cod_doc, 'tipo_documento': documento.get_cod_doc_display(),
                 'emisor': {'ruc': documento.emisor_ruc, 'razon_social': documento.emisor_razon_social},
                 'fecha_emision': documento.fecha_emision.isoformat() if documento.fecha_emision else None,
                 'importe_total': f'{documento.importe_total:.2f}', 'clasificacion': documento.clasificacion,
                 'clasificacion_nombre': documento.get_clasificacion_display(),
                 'verificacion': documento.estado_verificacion, 'verificacion_nombre': documento.get_estado_verificacion_display(),
                 'revision': documento.estado_revision,
                 'compra_id': documento.compra_id, 'venta_vinculada_id': documento.venta_id})
    if documento.estado_procesamiento != 'procesado':
        item['estado'] = 'sin_xml'
        return item
    if documento.compra_id or documento.estado_revision == 'vinculado':
        item['estado'] = 'ya_incorporado'
        return item
    accion = _accion_de(documento)
    item['accion'] = accion
    if accion is None:
        item['estado'] = 'no_aplica'
        return item
    if accion == 'crear_compra':
        propuesta = desde_xml.propuesta_compra(documento)
        item['bloqueos'] = propuesta['bloqueos']
        item['confirmaciones'] = list(propuesta['confirmaciones'])
        if propuesta['exige_confirmar_sin_verificar']:
            item['confirmaciones'].append('confirmar_sin_verificar')
        item['pendientes_revision'] = _pendientes_de_revision(documento, propuesta)
        item['proveedor'] = propuesta['proveedor']
        if propuesta['proveedor'] is None:
            item['proveedor_nuevo'] = {'ruc': documento.emisor_ruc, 'razon_social': documento.emisor_razon_social,
                                       'requiere': ['mobile', 'email']}
        item['permiso'] = {'change_documentoimportado', 'add_purchase'} <= permisos
    elif accion == 'registrar_retencion':
        item['bloqueos'] = recibidos.bloqueos_retencion(documento)
        if recibidos.exige_confirmar_sin_verificar(documento):
            item['confirmaciones'] = ['confirmar_sin_verificar']
        item['permiso'] = {'change_documentoimportado', 'add_retencionrecibida'} <= permisos
    else:   # vincular_venta: solo con la venta de la misma clave de acceso (coincidencia exacta)
        exactas = [c for c in candidatos_conciliacion(documento) if c['tipo'] == 'venta' and 'misma clave de acceso' in c['razones']]
        if len(exactas) == 1:
            item['venta_id'] = exactas[0]['id']
        else:
            item['bloqueos'] = [{'codigo': 'sin_venta', 'texto': 'No hay una venta con esta clave de acceso: revísalo en la ficha.'}]
        if documento.estado_revision != 'pendiente':
            item['bloqueos'].append({'codigo': 'revisado', 'texto': f'El documento ya está «{documento.get_estado_revision_display()}».'})
        if documento.estado_verificacion != 'verificada_sri' and reglas_de(documento.company).exigir_verificacion:
            item['confirmaciones'] = ['confirmar_sin_verificar']
        item['permiso'] = 'change_documentoimportado' in permisos
    if not item['permiso']:   # la vista previa no ofrece lo que el rol no puede incorporar
        item['bloqueos'].append({'codigo': 'sin_permiso', 'texto': 'Tu perfil no puede incorporar este documento.'})
    if item['bloqueos']:
        item['estado'] = 'bloqueado'
    elif item['confirmaciones'] or item['proveedor_nuevo']:
        item['estado'] = 'requiere_datos'
    else:
        item['estado'] = 'listo'
    return item


def plan_incorporacion(lote, request=None):
    """Qué se puede incorporar del lote y qué falta para cada documento (vista previa de la confirmación en lote)."""
    permisos = _permisos(request)
    items = [_plan_documento(e, e.documento, permisos)
             for e in lote.entradas.select_related('documento__proveedor').order_by('orden', 'id')]
    proveedores = {}
    for item in items:
        nuevo = item.get('proveedor_nuevo')
        if nuevo:
            registro = proveedores.setdefault(nuevo['ruc'], {**nuevo, 'documentos': 0})
            registro['documentos'] += 1
    conteo = {}
    for item in items:
        conteo[item['estado']] = conteo.get(item['estado'], 0) + 1
    return {'lote_id': lote.pk, 'items': items, 'proveedores_nuevos': sorted(proveedores.values(), key=lambda p: p['ruc']),
            'resumen': {'por_estado': conteo, 'estados': ESTADOS_INCORPORACION, 'total': len(items),
                        'incorporables': sum(1 for i in items if i['estado'] in ('listo', 'requiere_datos'))},
            'confirmaciones': CONFIRMACIONES}


def _si(valor):
    return str(valor).strip().lower() in ('1', 'true', 'on', 'si', 'sí')


def incorporar_lote(lote, usuario, request, documentos, opciones=None, proveedores=None, maximo=limites.INCORPORAR_POR_PETICION,
                    presupuesto=limites.PRESUPUESTO_PETICION_SEGUNDOS):
    """Incorpora, uno por uno y cada uno en su transacción, los documentos elegidos del lote: compra agrupada por tarifa con
    los importes del XML y los datos tributarios pendientes de revisión (sustento, parte relacionada y forma de pago solo
    si el XML la trae), retención recibida (07) o vínculo con la venta de la misma clave. Reutiliza los servicios de cada
    acción, que ya son idempotentes (bloqueo del documento y actualización condicionada): repetir la confirmación no crea
    otra compra, otro proveedor ni otro movimiento. `opciones`: confirmaciones globales, type_expense y date_joined;
    `proveedores`: {ruc: {mobile, email, parte_relacionada}} para los emisores sin proveedor. Devuelve los resultados y
    cuántos quedaron sin tratar por el presupuesto de tiempo (el navegador vuelve a llamar)."""
    import time
    from core.importacion import compras as desde_xml, recibidos
    inicio = time.monotonic()
    opciones, proveedores, permisos = dict(opciones or {}), dict(proveedores or {}), _permisos(request)
    try:
        ids = [int(d) for d in documentos]
    except (TypeError, ValueError):
        raise ErrorImportacion('Los documentos elegidos no tienen un formato válido.')
    if not ids:
        raise ErrorImportacion('Elige al menos un documento.')
    del_lote = {d.pk: d for d in DocumentoImportado.objects.filter(pk__in=ids, entradas__lote=lote).distinct()}
    if len(del_lote) != len(set(ids)):
        raise ErrorImportacion('Alguno de los documentos elegidos no pertenece a este lote.')
    confirmaciones = {c: _si(opciones.get(c, '')) for c in CONFIRMACIONES}
    resultados, tratados = [], 0
    for documento_id in ids:
        if tratados >= maximo or (tratados and presupuesto is not None and time.monotonic() - inicio >= presupuesto):
            break
        tratados += 1
        documento = del_lote[documento_id]
        resultado = {'documento_id': documento_id, 'numero': documento.numero}
        try:
            resultado.update(_incorporar_documento(documento, usuario, permisos, confirmaciones, opciones, proveedores))
        except ErrorImportacion as e:
            if e.codigo == 'ya_vinculado':
                resultado.update(resultado='ya_incorporado', mensaje=str(e))
            else:
                resultado.update(resultado='error', codigo=e.codigo or 'error', mensaje=str(e))
        resultados.append(resultado)
    evento('incorporacion_en_lote', f'{sum(1 for r in resultados if r["resultado"] not in ("error",))} de {len(resultados)} documentos '
           'incorporados o ya incorporados', lote=lote, usuario=usuario,
           resultados={str(r['documento_id']): r['resultado'] for r in resultados})
    return {'resultados': resultados, 'restantes': ids[tratados:], 'tratados': tratados}


def _incorporar_documento(documento, usuario, permisos, confirmaciones, opciones, proveedores):
    from core.importacion import compras as desde_xml, recibidos
    accion = _accion_de(documento)
    if accion is None:
        raise ErrorImportacion('Este documento se revisa a mano en su ficha.', 'no_aplica')
    if accion == 'crear_compra':
        if not {'change_documentoimportado', 'add_purchase'} <= permisos:
            raise ErrorImportacion('Tu perfil no puede crear compras.', 'sin_permiso')
        datos = {'agrupar_por_tarifa': True, 'datos_pendientes': 'si', **{c: 'si' for c, v in confirmaciones.items() if v}}
        for campo in ('type_expense', 'date_joined'):
            if opciones.get(campo) not in (None, ''):
                datos[campo] = opciones[campo]
        nuevo = proveedores.get(documento.emisor_ruc) or {}
        if nuevo:
            datos['proveedor_nuevo'] = {'mobile': nuevo.get('mobile', ''), 'email': nuevo.get('email', ''),
                                        'parte_relacionada': nuevo.get('parte_relacionada')}
        compra = desde_xml.crear_compra_desde_documento(documento, usuario, datos)
        return {'resultado': 'compra_creada', 'compra_id': compra.pk, 'mensaje': f'Compra #{compra.pk} creada con los importes del XML.',
                'datos_incompletos': compra.datos_incompletos}
    if accion == 'registrar_retencion':
        if not {'change_documentoimportado', 'add_retencionrecibida'} <= permisos:
            raise ErrorImportacion('Tu perfil no puede registrar retenciones recibidas.', 'sin_permiso')
        registradas = recibidos.registrar_en_retenciones_recibidas(documento.company, usuario, documento,
                                                                   confirmar_sin_verificar=confirmaciones['confirmar_sin_verificar'])
        return {'resultado': 'retencion_registrada', 'retenciones': [getattr(r, 'pk', r) for r in (registradas or [])],
                'mensaje': f'Retención recibida registrada ({len(registradas or [])} documentos sustento).'}
    if 'change_documentoimportado' not in permisos:
        raise ErrorImportacion('Tu perfil no puede revisar documentos.', 'sin_permiso')
    exactas = [c for c in candidatos_conciliacion(documento) if c['tipo'] == 'venta' and 'misma clave de acceso' in c['razones']]
    if len(exactas) != 1:
        raise ErrorImportacion('No hay una venta con esta clave de acceso: revísalo en la ficha.', 'sin_venta')
    revisar(documento, usuario, 'vincular_venta', {'id': exactas[0]['id'],
                                                   'confirmar_sin_verificar': 'si' if confirmaciones['confirmar_sin_verificar'] else ''})
    return {'resultado': 'venta_vinculada', 'venta_id': exactas[0]['id'], 'mensaje': f'Vinculado con la venta {exactas[0]["numero"]}.'}
