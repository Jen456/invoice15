"""Comprobantes de pago adjuntos (compras, gastos y pagos a proveedores) y la consulta mensual común con los respaldos de
cobros (core/cobros) y los recibos por completar (capturas): permisos y plan, alta (archivo o nota), baja lógica, listado,
resumen del mes y ZIP.

Opción A (DECISION-ENTREGA-COMERCIAL-2026-10-31.md): las facturas emitidas al contado y los cobros de cuentas por cobrar se
respaldan en core/cobros (nota o archivo, revisión, historial e idempotencia); aquí quedan los documentos de egreso. La
consulta del mes y el ZIP recogen ambos orígenes sin copiar ni duplicar: cada fila dice de dónde viene (`origen`), si su
respaldo es un archivo o una nota, y su estado de revisión; una nota válida no cuenta como falta de respaldo; el importe
del abono y el de su respaldo no se suman dos veces. Los permisos son los de cada documento: quien no puede ver ventas o
cobros no ve esas filas. Los recibos pendientes de completar van aparte (`resumen.capturas`): no son documentos.
"""
import csv
import io
import re
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core.adjuntos import archivos
from core.adjuntos.documentos import DOCUMENTOS, SIN_COMPROBANTE_ESPERADO, TIPOS_EN_COBROS, describir
from core.adjuntos.models import CLASE_NOTA, CLASES, CLASE_POR_MEDIO, NOTA_MAX, Adjunto
from core.pos.models import Expenses, PaymentsCtaCollect, PaymentsDebtsPay, Purchase, Sale
from core.security.session import get_group
from core.suscripciones import reglas
from core.suscripciones.servicios import estado_de_peticion

MAX_ZIP_BYTES = 250 * archivos.MB
VENTAS_CON_COMPROBANTE = ('authorized', 'authorized_and_sent_by_email')
# Lo que exige ver cada fila de cobros en la consulta del mes (además de view_adjunto para la página).
PERMISOS_COBROS = {'venta': ('view_respaldocobro', 'view_sale'), 'cobro': ('view_respaldocobro', 'view_ctas_collect')}
CARPETAS_COBROS = {'venta': 'facturas-emitidas', 'cobro': 'cobros'}
CARPETA_CAPTURAS = 'recibos-por-completar'

# Textos exactos (documentados en HANDOFF para el frontend).
RESPALDO_REQUERIDO = 'Adjunta el recibo o escribe una nota (o ambos).'
NOTA_LARGA = f'La nota o descripción admite hasta {NOTA_MAX} caracteres.'
NOTA_DUPLICADA = 'Esta nota ya está registrada en este documento.'
ARCHIVO_DUPLICADO = 'Este archivo ya está adjunto a este documento.'


class ErrorAdjunto(Exception):
    def __init__(self, mensaje, codigo='invalido', estado=400):
        super().__init__(mensaje)
        self.codigo, self.estado = codigo, estado


# ------------------------------------------------------------------ permisos y plan

def _codigos(request):
    grupo = get_group(request)
    return set(grupo.permissions.values_list('codename', flat=True)) if grupo is not None else set()


def permisos(request, tipo):
    """{'ver', 'subir', 'quitar', 'bloqueo'} del rol activo para los adjuntos de un tipo de documento.

    Hereda la regla de plan del módulo del documento: con el plan gratuito, los módulos de pago no se ven; con el plan
    vencido se consulta, pero no se sube ni se quita (como el PlanMiddleware con esas pantallas)."""
    doc = DOCUMENTOS[tipo]
    codigos = _codigos(request)
    ver = doc.ver in codigos
    subir = ver and ('add_adjunto' in codigos or any(c in codigos for c in doc.escribir))
    quitar = ver and ('delete_adjunto' in codigos or any(c in codigos for c in doc.borrar))
    bloqueo = None
    if ver and reglas.requiere_plan(doc.modulo):
        from core.suscripciones.middleware import mensaje_de_bloqueo
        estado = estado_de_peticion(request)
        if estado.gratuito:
            ver = subir = quitar = False
            bloqueo = mensaje_de_bloqueo(estado)
        elif estado.vencido:
            subir = quitar = False
            bloqueo = mensaje_de_bloqueo(estado)
    return {'ver': ver, 'subir': subir, 'quitar': quitar, 'bloqueo': bloqueo}


def tipos_visibles(request):
    """Tipos de documento cuyas filas puede ver el usuario en la consulta del mes (todos si no hay petición)."""
    if request is None:
        return set(DOCUMENTOS) | set(TIPOS_EN_COBROS)
    codigos = _codigos(request)
    visibles = {t for t in DOCUMENTOS if permisos(request, t)['ver']}
    visibles |= {t for t, necesarios in PERMISOS_COBROS.items() if all(c in codigos for c in necesarios)}
    return visibles


# ------------------------------------------------------------------ alta y baja

def listar(tipo, documento_id, eliminados=False):
    consulta = Adjunto.objects.filter(documento_tipo=tipo, documento_id=documento_id).select_related('subido_por', 'eliminado_por')
    return consulta if eliminados else consulta.filter(eliminado_en__isnull=True)


def clase_sugerida(tipo, documento):
    medio = describir(tipo, documento)['medio_id']
    return CLASE_POR_MEDIO.get(medio, 'transferencia')


def _fecha(valor):
    if valor in (None, ''):
        return None
    if isinstance(valor, date):
        fecha = valor
    else:
        try:
            fecha = date.fromisoformat(str(valor).strip())
        except ValueError:
            raise ErrorAdjunto('La fecha del comprobante no es válida (AAAA-MM-DD).', 'fecha')
    if fecha > timezone.localdate():
        raise ErrorAdjunto('La fecha del comprobante no puede ser futura.', 'fecha')
    return fecha


def _importe(valor):
    if valor in (None, ''):
        return None
    try:
        importe = Decimal(str(valor).strip()).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        raise ErrorAdjunto('El importe del comprobante no es un número.', 'importe')
    if not importe.is_finite() or importe <= 0 or importe >= Decimal('10000000000'):
        raise ErrorAdjunto('El importe del comprobante debe ser mayor que cero.', 'importe')
    return importe


def texto(valor, maximo=NOTA_MAX, codigo='nota_larga', mensaje=NOTA_LARGA):
    """Texto de una nota o descripción con los espacios normalizados; más largo que `maximo` → error (no se recorta)."""
    valor = ' '.join((valor or '').split())
    if len(valor) > maximo:
        raise ErrorAdjunto(mensaje, codigo)
    return valor


def bloquear_documento(tipo, documento_id):
    """El documento de la empresa activa con su fila bloqueada hasta el final de la transacción (serializa altas de
    adjuntos sobre el mismo documento: duplicados y límite por documento), o ErrorAdjunto 404."""
    documento = DOCUMENTOS[tipo].modelo.objects.select_for_update(of=('self',)).filter(pk=documento_id).first()
    if documento is None:
        raise ErrorAdjunto('El documento no existe o es de otra empresa.', 'documento', 404)
    return documento


def comprobar_cupo(tipo, documento_id, nuevos=1):
    if listar(tipo, documento_id).count() + nuevos > archivos.MAX_POR_DOCUMENTO:
        raise ErrorAdjunto(f'Un documento admite hasta {archivos.MAX_POR_DOCUMENTO} comprobantes (archivos y notas).', 'limite')


def crear_nota(company, usuario, tipo, documento_id, nota, *, captura=None, subido_por=None, subido_en=None):
    """Nota de respaldo sin archivo (dentro de la transacción y con el documento ya bloqueado por quien llama)."""
    if listar(tipo, documento_id).filter(archivo='', descripcion=nota).exists():
        raise ErrorAdjunto(NOTA_DUPLICADA, 'duplicado', 409)
    comprobar_cupo(tipo, documento_id)
    autor = subido_por if subido_por is not None else (usuario if getattr(usuario, 'pk', None) else None)
    return Adjunto.objects.create(company=company, documento_tipo=tipo, documento_id=documento_id, clase=CLASE_NOTA, descripcion=nota,
                                  captura=captura, subido_por=autor, subido_en=subido_en or timezone.now())


def adjuntar(company, usuario, tipo, documento, archivo=None, *, clase='', referencia='', fecha=None, importe=None,
             descripcion='', nota=''):
    """Guarda un respaldo del documento (ya comprobados los permisos): un archivo (UploadedFile o bytes) con su descripción,
    o una nota sin archivo. Con archivo, `nota` sirve de descripción si no llega otra. Sin archivo ni nota: error."""
    if tipo not in DOCUMENTOS:
        raise ErrorAdjunto('Este documento se respalda desde el cobro (core/cobros), no con un adjunto genérico.', 'tipo', 404)
    nota, descripcion = texto(nota), texto(descripcion)
    if archivo is None:
        if not nota:
            raise ErrorAdjunto(RESPALDO_REQUERIDO, 'respaldo_requerido')
        with transaction.atomic():
            bloquear_documento(tipo, documento.pk)
            return crear_nota(company, usuario, tipo, documento.pk, nota)
    if hasattr(archivo, 'size') and archivo.size > archivos.MAX_BYTES:
        raise ErrorAdjunto(f'El archivo pesa más de {archivos.MAX_BYTES // archivos.MB} MB. Comprime el PDF o reduce la foto.', 'tamano')
    contenido = archivo.read() if hasattr(archivo, 'read') else bytes(archivo)
    try:
        nombre, tipo_mime, sha256 = archivos.validar(getattr(archivo, 'name', ''), contenido)
    except archivos.ArchivoInvalido as e:
        raise ErrorAdjunto(str(e), 'archivo')
    if clase not in dict(CLASES):   # la nota no es una clase de archivo
        clase = clase_sugerida(tipo, documento)
    datos = dict(clase=clase, referencia=' '.join((referencia or '').split())[:100], fecha=_fecha(fecha), importe=_importe(importe),
                 descripcion=descripcion or nota)
    with transaction.atomic():
        bloquear_documento(tipo, documento.pk)
        vigentes = listar(tipo, documento.pk)
        if vigentes.filter(sha256=sha256).exists():
            raise ErrorAdjunto(ARCHIVO_DUPLICADO, 'duplicado', 409)
        comprobar_cupo(tipo, documento.pk)
        adjunto = Adjunto(company=company, documento_tipo=tipo, documento_id=documento.pk, nombre=nombre, tipo_mime=tipo_mime,
                          tamano=len(contenido), sha256=sha256, subido_por=usuario if getattr(usuario, 'pk', None) else None, **datos)
        adjunto.archivo.save(f'comprobante.{adjunto.extension}', ContentFile(contenido), save=False)
        try:
            adjunto.save()
        except Exception:
            adjunto.archivo.storage.delete(adjunto.archivo.name)
            raise
    return adjunto


def tambien_en(adjunto, limite=5):
    """Otros documentos de la empresa con el mismo archivo vigente (una transferencia que paga varias compras)."""
    if not adjunto.sha256:
        return []
    otros = (Adjunto.objects.filter(sha256=adjunto.sha256, eliminado_en__isnull=True).exclude(pk=adjunto.pk)
             .exclude(documento_tipo=adjunto.documento_tipo, documento_id=adjunto.documento_id).order_by('id')[:limite])
    resultado = []
    for otro in otros:
        from core.adjuntos.documentos import obtener
        if otro.documento_tipo not in DOCUMENTOS:   # adjuntos anteriores a la opción A sobre ventas o cobros
            continue
        documento = obtener(otro.documento_tipo, otro.documento_id)
        if documento is not None:
            resultado.append({'tipo': otro.documento_tipo, 'id': otro.documento_id, 'titulo': describir(otro.documento_tipo, documento)['titulo']})
    return resultado


def quitar(usuario, adjunto, motivo=''):
    """Baja lógica: el registro y el archivo se conservan (auditoría); deja de contar y de mostrarse como vigente."""
    if adjunto.eliminado_en is not None:
        raise ErrorAdjunto('Este comprobante ya se había quitado: actualiza la página.', 'ya_quitado')
    adjunto.eliminado_en = timezone.now()
    adjunto.eliminado_por = usuario if getattr(usuario, 'pk', None) else None
    adjunto.eliminado_motivo = ' '.join((motivo or '').split())[:300]
    adjunto.save(update_fields=['eliminado_en', 'eliminado_por', 'eliminado_motivo'])
    return adjunto


def al_eliminar_documento(tipo, documento_id, usuario=None, request=None, titulo=''):
    """Lo llaman, dentro de su transacción y antes de borrar, la eliminación de un gasto, de una compra
    (compras.eliminar_compra) y de un pago a proveedor (cuentas_por_pagar.eliminar_pago): sus adjuntos vigentes quedan
    quitados (baja lógica: registro y archivo se conservan) y los recibos que se completaron o vincularon con ese documento
    vuelven a estar pendientes, para no perder el respaldo (auditado: captura_liberada)."""
    autor = usuario if getattr(usuario, 'pk', None) else None
    motivo = f'{titulo or DOCUMENTOS[tipo].nombre} eliminado'[:300]
    Adjunto.objects.filter(documento_tipo=tipo, documento_id=documento_id, eliminado_en__isnull=True).update(
        eliminado_en=timezone.now(), eliminado_por=autor, eliminado_motivo=motivo)
    from core.adjuntos import capturas
    capturas.liberar(tipo, documento_id, autor, request)


# ------------------------------------------------------------------ serialización

def _texto_tamano(tamano):
    if tamano >= archivos.MB:
        return f'{tamano / archivos.MB:.1f} MB'
    return f'{max(tamano // 1024, 1)} KB'


def dict_adjunto(adjunto):
    """Un adjunto: archivo (con `url`) o nota de respaldo (`nota: true`, sin `url` ni datos de archivo)."""
    archivo = bool(adjunto.archivo)
    url = reverse('adjunto_archivo', args=[adjunto.pk]) if archivo else ''
    return {
        'id': adjunto.pk, 'origen': 'adjuntos', 'clase': {'id': adjunto.clase, 'name': adjunto.get_clase_display()}, 'nombre': adjunto.nombre,
        'tipo_mime': adjunto.tipo_mime, 'extension': adjunto.extension, 'tamano': adjunto.tamano,
        'tamano_texto': _texto_tamano(adjunto.tamano) if archivo else '',
        'sha256': adjunto.sha256, 'referencia': adjunto.referencia, 'fecha': adjunto.fecha.isoformat() if adjunto.fecha else '',
        'importe': f'{adjunto.importe:.2f}' if adjunto.importe is not None else '', 'descripcion': adjunto.descripcion,
        'subido_por': adjunto.subido_por.username if adjunto.subido_por_id else '',
        'subido_en': timezone.localtime(adjunto.subido_en).strftime('%Y-%m-%d %H:%M'),
        'url': url, 'url_descarga': url + '?descargar=1' if archivo else '',
        'nota': not archivo, 'revision': None, 'captura': adjunto.captura_id,
        'eliminado': adjunto.eliminado_en is not None,
        'eliminado_en': timezone.localtime(adjunto.eliminado_en).strftime('%Y-%m-%d %H:%M') if adjunto.eliminado_en else '',
        'eliminado_por': adjunto.eliminado_por.username if adjunto.eliminado_por_id else '', 'eliminado_motivo': adjunto.eliminado_motivo,
    }


def dict_documento(tipo, documento):
    datos = describir(tipo, documento)
    datos['fecha'] = datos['fecha'].isoformat() if datos['fecha'] else ''
    datos['importe'] = f'{datos["importe"]:.2f}' if datos['importe'] is not None else ''
    datos['clase_sugerida'] = CLASE_POR_MEDIO.get(datos['medio_id'], 'transferencia')
    return datos


# ------------------------------------------------------------------ respaldos de cobros (core/cobros) en la consulta común

def dict_respaldo_cobro(respaldo):
    """Un respaldo de core/cobros con las mismas claves que un adjunto: `url` vacío cuando es solo nota."""
    archivo = bool(respaldo.archivo)
    return {
        'id': respaldo.pk, 'origen': 'cobros',
        'clase': {'id': 'archivo' if archivo else 'nota', 'name': 'Comprobante del cobro' if archivo else 'Nota interna'},
        'nombre': respaldo.archivo_nombre, 'tipo_mime': {'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'png': 'image/png'}.get(respaldo.archivo_tipo, ''),
        'extension': respaldo.archivo_tipo, 'tamano': respaldo.archivo_bytes, 'tamano_texto': _texto_tamano(respaldo.archivo_bytes) if archivo else '',
        'sha256': respaldo.archivo_sha256, 'referencia': respaldo.referencia,
        'fecha': timezone.localtime(respaldo.registrado_en).date().isoformat(), 'importe': f'{respaldo.importe:.2f}',
        'descripcion': respaldo.nota, 'subido_por': respaldo.registrado_por.username if respaldo.registrado_por_id else '',
        'subido_en': timezone.localtime(respaldo.registrado_en).strftime('%Y-%m-%d %H:%M'),
        'url': f'/cobros/respaldo/{respaldo.pk}/archivo/' if archivo else '',
        'url_descarga': f'/cobros/respaldo/{respaldo.pk}/archivo/?descargar=1' if archivo else '',
        'nota': bool(respaldo.nota) and not archivo,
        'revision': {'id': respaldo.estado, 'name': respaldo.get_estado_display(), 'por': respaldo.revisado_por.username if respaldo.revisado_por_id else '',
                     'motivo': respaldo.motivo_revision},
        'captura': None,
        'eliminado': False, 'eliminado_en': '', 'eliminado_por': '', 'eliminado_motivo': '',
    }


def _fila_cobros(tipo, obj, respaldos):
    if tipo == 'venta':
        medio_id = obj.medio_cobro
        datos = dict(numero=obj.voucher_number_full, tercero=obj.client.user.names, identificacion=obj.client.dni, fecha=obj.date_joined,
                     importe=Decimal(obj.total), medio_id=medio_id, medio=obj.get_medio_cobro_display() if medio_id else 'Sin dato',
                     contado=True, titulo=f'Factura {obj.voucher_number_full}', url_cobros=f'/cobros/factura/{obj.pk}/')
    else:
        cuenta = obj.ctas_collect
        medio_id = obj.medio_pago
        datos = dict(numero=cuenta.documento()['numero'], tercero=cuenta.sale.client.user.names, identificacion=cuenta.sale.client.dni,
                     fecha=obj.date_joined, importe=Decimal(obj.valor), medio_id=medio_id,
                     medio=obj.get_medio_pago_display() if medio_id else 'Sin dato', contado=True,
                     titulo=f'Cobro de {cuenta.documento()["numero"]}', url_cobros=f'/cobros/factura/{cuenta.sale_id}/', abono=obj.tipo)
    datos.update(tipo=tipo, id=obj.pk, tipo_nombre=TIPOS_EN_COBROS[tipo], origen='cobros', pendiente_completar=False)
    datos['fecha'] = datos['fecha'].isoformat() if datos['fecha'] else ''
    datos['importe'] = f'{datos["importe"]:.2f}'
    datos['clase_sugerida'] = CLASE_POR_MEDIO.get(medio_id, 'transferencia')
    datos['requiere'] = medio_id not in SIN_COMPROBANTE_ESPERADO
    datos['adjuntos'] = [dict_respaldo_cobro(r) for r in respaldos]
    datos['_respaldos'] = respaldos
    datos['falta'] = datos['requiere'] and not respaldos          # una nota válida sí es respaldo
    datos['con_nota'] = any(a['nota'] for a in datos['adjuntos'])
    datos['pendientes_revision'] = sum(1 for r in respaldos if r.estado == 'pendiente')
    datos['rechazados'] = sum(1 for r in respaldos if r.estado == 'rechazado')
    return datos


def _ventas_y_cobros_del_mes(inicio):
    """Facturas al contado autorizadas y cobros vigentes del mes (empresa activa), con sus respaldos de core/cobros."""
    from core.cobros.models import RespaldoCobro
    fin = _siguiente_mes(inicio)
    ventas = list(Sale.objects.select_related('client__user').filter(status__in=VENTAS_CON_COMPROBANTE, anulado_sri_fecha__isnull=True,
                                                                    payment_type='efectivo', date_joined__gte=inicio, date_joined__lt=fin)
                  .order_by('date_joined', 'id'))
    cobros = list(PaymentsCtaCollect.objects.select_related('ctas_collect__sale__client__user')
                  .filter(tipo='cobro', anulado_en__isnull=True, date_joined__gte=inicio, date_joined__lt=fin).order_by('date_joined', 'id'))
    respaldos = (RespaldoCobro.objects.filter(Q(sale_id__in=[v.pk for v in ventas], origen='contado') | Q(abono_id__in=[c.pk for c in cobros]))
                 .select_related('registrado_por', 'revisado_por').order_by('id'))
    de_venta, de_cobro = {}, {}
    for r in respaldos:
        if r.abono_id is not None:
            de_cobro.setdefault(r.abono_id, []).append(r)
        else:
            de_venta.setdefault(r.sale_id, []).append(r)
    return ([_fila_cobros('venta', v, de_venta.get(v.pk, [])) for v in ventas],
            [_fila_cobros('cobro', c, de_cobro.get(c.pk, [])) for c in cobros])


# ------------------------------------------------------------------ resumen del mes

def primer_dia(mes):
    """'AAAA-MM' → primer día del mes, o ValueError."""
    partes = re.fullmatch(r'(\d{4})-(\d{2})', (mes or '').strip())
    if not partes:
        raise ValueError('mes')
    return date(int(partes.group(1)), int(partes.group(2)), 1)


def _siguiente_mes(inicio):
    return date(inicio.year + (inicio.month == 12), inicio.month % 12 + 1, 1)


def _documentos_del_mes(inicio):
    """Documentos de egreso de la empresa activa cuya fecha cae en el mes, por tipo."""
    fin = _siguiente_mes(inicio)
    en_mes = lambda campo: {f'{campo}__gte': inicio, f'{campo}__lt': fin}   # noqa: E731
    return {
        'compra': list(Purchase.objects.select_related('provider')
                       .filter(Q(**en_mes('fecha_emision')) | Q(fecha_emision__isnull=True, **en_mes('date_joined')))
                       .exclude(tipo_comprobante__in=('04', '05')).order_by('date_joined', 'id')),
        'gasto': list(Expenses.objects.select_related('type_expense').filter(**en_mes('date_joined')).order_by('date_joined', 'id')),
        'pago': list(PaymentsDebtsPay.objects.select_related('debts_pay__purchase__provider').filter(**en_mes('date_joined'))
                     .order_by('date_joined', 'id')),
    }


def resumen_mes(inicio, request=None):
    """Documentos del mes de ambos orígenes con sus respaldos vigentes y los que deberían tener uno y no lo tienen (medio no
    efectivo), más los recibos pendientes de completar guardados en el mes. Con `request`, solo lo que ese rol puede ver.
    Nunca copia ni crea nada."""
    from core.adjuntos import capturas
    visibles = tipos_visibles(request)
    documentos = _documentos_del_mes(inicio)
    filas = []
    for tipo, objetos in documentos.items():
        if tipo not in visibles or not objetos:
            continue
        adjuntos = {}
        for adjunto in (Adjunto.objects.filter(documento_tipo=tipo, documento_id__in=[o.pk for o in objetos], eliminado_en__isnull=True)
                        .select_related('subido_por').order_by('id')):
            adjuntos.setdefault(adjunto.documento_id, []).append(adjunto)
        for objeto in objetos:
            fila = dict_documento(tipo, objeto)
            fila['adjuntos'] = [dict_adjunto(a) for a in adjuntos.get(objeto.pk, [])]
            fila['_adjuntos'] = adjuntos.get(objeto.pk, [])
            fila['falta'] = fila['requiere'] and not fila['adjuntos']      # una nota de respaldo también cuenta
            fila.update(con_nota=any(a['nota'] for a in fila['adjuntos']), pendientes_revision=0, rechazados=0, url_cobros='',
                        pendiente_completar=False)
            filas.append(fila)
    ventas, cobros = _ventas_y_cobros_del_mes(inicio) if visibles & set(TIPOS_EN_COBROS) else ([], [])
    filas += [f for f in ventas if 'venta' in visibles] + [f for f in cobros if 'cobro' in visibles]
    filas.sort(key=lambda f: (f['fecha'], f['tipo'], f['id']))
    recibos = capturas.filas_del_mes(inicio, request)
    totales = {'documentos': len(filas), 'con_comprobante': 0, 'sin_comprobante': 0, 'adjuntos': 0, 'notas': 0, 'pendientes_revision': 0,
               'rechazados': 0, 'bytes': 0, 'capturas_del_mes': len(recibos), 'capturas_pendientes': capturas.contar_pendientes(request)}
    for fila in filas:
        archivos_ = [a for a in fila['adjuntos'] if a['url']]
        totales['adjuntos'] += len(archivos_)
        totales['notas'] += sum(1 for a in fila['adjuntos'] if a['nota'])
        totales['bytes'] += sum(a['tamano'] or 0 for a in archivos_)
        totales['pendientes_revision'] += fila['pendientes_revision']
        totales['rechazados'] += fila['rechazados']
        if fila['adjuntos']:
            totales['con_comprobante'] += 1
        elif fila['falta']:
            totales['sin_comprobante'] += 1
    totales['bytes'] += sum(r['_captura'].tamano for r in recibos if r['_captura'].archivo)
    totales['bytes_texto'] = _texto_tamano(totales['bytes']) if totales['bytes'] else '0 KB'
    return {'mes': inicio, 'filas': filas, 'totales': totales, 'tipos_visibles': sorted(visibles), 'capturas': recibos,
            'faltantes': [f for f in filas if f['falta']], 'con_adjuntos': [f for f in filas if f['adjuntos']]}


def _nombre_seguro(texto_):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', texto_).strip('_')[:60] or 'documento'


def _objetos_con_archivo(fila):
    """[(objeto, dict)] de los respaldos con archivo de la fila, del origen que sea (las notas no tienen archivo)."""
    if fila['origen'] == 'cobros':
        return [(r, d) for r, d in zip(fila['_respaldos'], fila['adjuntos']) if r.archivo]
    return [(a, d) for a, d in zip(fila['_adjuntos'], fila['adjuntos']) if a.archivo]


def zip_mes(inicio, resumen=None, request=None):
    """ZIP con los comprobantes del mes por tipo de documento, los recibos pendientes de completar y `indice.csv` (para el
    contador y la conciliación). Solo entran archivos que el rol puede ver; las notas, los estados de revisión y los recibos
    pendientes van en el índice, nunca rutas del disco."""
    resumen = resumen or resumen_mes(inicio, request)
    if resumen['totales']['bytes'] > MAX_ZIP_BYTES:
        raise ErrorAdjunto(f'Los comprobantes del mes pesan más de {MAX_ZIP_BYTES // archivos.MB} MB: descárgalos por documento.', 'zip')
    salida = io.BytesIO()
    indice = io.StringIO()
    escritor = csv.writer(indice, delimiter=';')
    escritor.writerow(['tipo', 'documento', 'tercero', 'identificacion', 'fecha_documento', 'importe_documento', 'medio_de_pago', 'clase',
                       'referencia', 'fecha_comprobante', 'importe_comprobante', 'descripcion', 'archivo', 'sha256', 'subido_por', 'subido_el',
                       'origen', 'respaldo', 'revision'])
    carpeta_mes = f'{inicio:%Y-%m}'

    def escribir(zf, ruta, objeto):
        try:
            with objeto.archivo.open('rb') as f:
                zf.writestr(ruta, f.read())
            return ruta
        except (FileNotFoundError, OSError, ValueError):
            return 'ARCHIVO NO ENCONTRADO'

    with zipfile.ZipFile(salida, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fila in resumen['con_adjuntos']:
            carpeta = CARPETAS_COBROS.get(fila['tipo']) or DOCUMENTOS[fila['tipo']].carpeta
            n = 0
            for objeto, datos in _objetos_con_archivo(fila):
                n += 1
                ruta = escribir(zf, f'{carpeta_mes}/{carpeta}/{_nombre_seguro(fila["numero"])}_{n}.{datos["extension"]}', objeto)
                revision = datos['revision']['name'] if datos['revision'] else ''
                escritor.writerow([fila['tipo_nombre'], fila['numero'], fila['tercero'], fila['identificacion'], fila['fecha'], fila['importe'],
                                   fila['medio'], datos['clase']['name'], datos['referencia'], datos['fecha'], datos['importe'],
                                   datos['descripcion'], ruta, datos['sha256'], datos['subido_por'], datos['subido_en'],
                                   fila['origen'], 'archivo', revision])
            for datos in fila['adjuntos']:
                if datos['nota']:
                    escritor.writerow([fila['tipo_nombre'], fila['numero'], fila['tercero'], fila['identificacion'], fila['fecha'], fila['importe'],
                                       fila['medio'], datos['clase']['name'], datos['referencia'], datos['fecha'], datos['importe'],
                                       datos['descripcion'], '', '', datos['subido_por'], datos['subido_en'],
                                       fila['origen'], 'nota', datos['revision']['name'] if datos['revision'] else ''])
        for fila in resumen['faltantes']:
            escritor.writerow([fila['tipo_nombre'], fila['numero'], fila['tercero'], fila['identificacion'], fila['fecha'], fila['importe'],
                               fila['medio'], 'SIN COMPROBANTE', '', '', '', '', '', '', '', '', fila['origen'], '', ''])
        for fila in resumen['capturas']:
            captura, datos = fila['_captura'], fila['adjuntos'][0]
            ruta = ''
            if captura.archivo:
                ruta = escribir(zf, f'{carpeta_mes}/{CARPETA_CAPTURAS}/{fila["numero"]}.{captura.extension}', captura)
            escritor.writerow([fila['tipo_nombre'], fila['numero'], '', '', fila['fecha'], '', fila['medio'], datos['clase']['name'], '', '', '',
                               datos['descripcion'], ruta, datos['sha256'], datos['subido_por'], datos['subido_en'],
                               'adjuntos', 'archivo' if captura.archivo else 'nota', ''])
        zf.writestr(f'{carpeta_mes}/indice.csv', '﻿' + indice.getvalue())
    return salida.getvalue()
