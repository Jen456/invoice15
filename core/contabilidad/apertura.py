"""Apertura contable en preparación (Parte B de contable/bloque-2-especificacion.md; C6-A): crearla, cambiar su encabezado,
fijar sus líneas (captura directa del conjunto completo o desde un lote importado), sus respaldos y descartarla. Todo
ocurre en borrador. Validar, enviar a revisión, devolver y confirmar son de la parte siguiente del corte 1; ajustar,
sustituir, reversar y los auxiliares, del corte 2.

Estados: `borrador → en_revision → confirmada → sustituida | reversada`, `en_revision → borrador` y
`borrador | en_revision → descartada`. Solo el borrador se edita. Como mucho una confirmada y una en preparación por empresa
(lo garantizan además dos UNIQUE parciales).

Reglas de las líneas (regla 4):

- una línea es una cuenta de movimiento activa de la empresa, con un solo lado mayor que cero o los dos nulos
  (desconocido: nunca cero). `detalle` es la copia de `cuenta.auxiliar` al escribir la línea;
- dos filas de la fuente hacia la misma cuenta se suman solo con `agrupar` (quedan en `filas_origen`); una fila de subtotal
  se omite solo con `omitir` y su motivo; un PDF respalda, nunca alimenta líneas;
- las líneas no se borran: mapear concilia el conjunto enviado con el que ya existe por `cuenta_id` (alta de las nuevas,
  cambio de las que siguen, retiro de las que ya no vienen) conservando el id; las que no tienen cuenta se emparejan por
  orden. Una línea retirada (importes nulos) queda fuera de totales y vuelve a usarse si su cuenta vuelve. Quitar una
  línea con auxiliares vigentes → 409 `linea_con_auxiliares`.

Cada cambio bloquea la fila `Apertura`, exige `version` (la que leyó quien edita; si ya no es la vigente, 409 `version`) y la
sube, deja su `EventoApertura` y su auditoría en la misma transacción (existe el rastro si y solo si existe el efecto). Lo que
cambia la configuración (crear, mover el corte) toma antes el candado del libro (inicio_contable.libro), en el orden global
de bloqueos de la decisión común 4: candado → apertura → auxiliares. Negativas en el orden de la decisión común 6: permiso
→ datos por completar → clave → versión → estado → conflicto → validación."""
import hashlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.utils import timezone

from core.contabilidad import api, cobertura, inicio_contable, lotes, respaldos
from core.contabilidad import capacidades as cap
from core.contabilidad.modelos_apertura import (ANULADO, BORRADOR, CON_CONFIRMACION, CONFIRMADA, DESCARTADA, EN_PREPARACION,
                                                EN_REVISION, FUENTES, MODOS_INVENTARIO, RESULTADOS_EJERCICIO, VIGENTE)
from core.contabilidad.models import (AjusteApertura, Apertura, AuxiliarApertura, Cuenta, EventoApertura, ImportacionApertura,
                                      InicioContable, LineaApertura, RespaldoApertura)
from core.tenancy.models import audit

VER, PREPARAR, CONFIRMAR, COBRAR = 'view_apertura', 'add_apertura', 'change_confirmacion_apertura', 'add_aplicacionauxiliar'
CERO = Decimal('0')
CENTAVO = Decimal('0.01')
RUIDO = Decimal('0.000001')        # lo que separa un importe de dos decimales de su lectura como número de coma flotante
IMPORTE_MAX = Decimal('1000000000000')   # 14 cifras, dos decimales
MAX_LINEAS = 5000
FUENTE_DETALLE_MAX, MOTIVO_MAX, RUBRO_MAX, NOTA_AMBITO_MAX, DESCRIPCION_MAX = 300, 300, 200, 300, 200
INICIO_ACTIVIDADES = 'inicio_actividades'
VALORES_FUENTE = tuple(f for f, _ in FUENTES)
VALORES_RESULTADO = tuple(r for r, _ in RESULTADOS_EJERCICIO)
VALORES_INVENTARIO = tuple(m for m, _ in MODOS_INVENTARIO)
MOTIVO_DESCARTE_AUXILIAR = 'apertura descartada'

TEXTOS = {
    'no_existe': 'La apertura no existe o es de otra empresa.',
    'cuenta_no_existe': 'La cuenta no existe o es de otra empresa.',
    'respaldo_no_existe': 'El respaldo no existe o es de otra empresa.',
    'apertura_existente': 'Ya hay una apertura en preparación: continúa con ella o descártala antes de crear otra.',
    'clave_usada': 'Esta clave ya se usó para otro envío: vuelve a cargar la página e inténtalo de nuevo.',
    'version_falta': 'Falta la versión de la apertura que estás editando: vuelve a cargarla e inténtalo de nuevo.',
    'version': 'Otra persona cambió la apertura mientras la editabas: revisa cómo quedó y vuelve a intentarlo.',
    'estado': 'La apertura ya no está en borrador: solo un borrador se edita.',
    'estado_preparacion': 'La apertura ya no está en preparación.',
    'linea_con_auxiliares': 'La línea tiene auxiliares vigentes: anúlalos o muévelos antes de quitarla o de cambiar su cuenta.',
    'ya_anulado': 'Este respaldo ya está anulado.',
    'fuente': 'Elige la fuente de los saldos.',
    'fuente_detalle_largo': f'El detalle de la fuente admite hasta {FUENTE_DETALLE_MAX} caracteres.',
    'sin_saldos': 'Indica si la empresa empieza sin saldos: verdadero o falso.',
    'sin_saldos_fuente': 'Empezar sin saldos es una declaración de inicio de actividades: elige esa fuente.',
    'sin_saldos_detalle': 'Explica en el detalle de la fuente por qué la empresa empieza sin saldos.',
    'fijo': 'No se cambia en un borrador: descarta esta apertura y crea otra.',
    'resultado_ejercicio': 'Elige cómo está el resultado del ejercicio: no aplica, en cuentas de resultados o en patrimonio.',
    'resultado_acumulado': 'Escribe el resultado acumulado con dos decimales, o déjalo vacío.',
    'inventario_modo': 'Elige el modo del inventario inicial: solo conciliar o reiniciar el kardex.',
    'ambitos': 'Envía los ámbitos que no aplican como una lista de {ambito, nota}.',
    'ambito': 'Elige un ámbito: clientes, proveedores, inventario, bancos, activos o tributario.',
    'ambito_repetido': 'Ese ámbito ya está en la lista.',
    'ambito_con_cuentas': 'Hay cuentas con ese detalle en la apertura: no puede declararse que no aplica.',
    'nota_ambito': 'Escribe por qué no aplica.',
    'nota_ambito_larga': f'La nota admite hasta {NOTA_AMBITO_MAX} caracteres.',
    'motivo': 'Escribe el motivo.',
    'motivo_largo': f'El motivo admite hasta {MOTIVO_MAX} caracteres.',
    'descripcion_larga': f'La descripción admite hasta {DESCRIPCION_MAX} caracteres.',
    'archivo': 'Elige el archivo de respaldo.',
    # líneas
    'lineas': 'Envía las líneas como una lista.',
    'lineas_y_lote': 'Envía las líneas o el lote, no los dos.',
    'demasiadas_lineas': f'La apertura admite hasta {MAX_LINEAS:,} líneas.'.replace(',', ' '),
    'linea': 'Cada línea es un objeto con su cuenta y sus importes.',
    'cuenta_id': 'Elige una cuenta del plan.',
    'cuenta_de_grupo': 'La cuenta {codigo} es un grupo: elige una cuenta de movimiento.',
    'cuenta_inactiva': 'La cuenta {codigo} está inactiva.',
    'cuenta_repetida': 'La cuenta {codigo} ya está en la línea {posicion}.',   # contada desde 1, como la lee una persona
    'cuenta_no_aplica': 'La apertura declara que no aplica el detalle de {ambito}: quita esa declaración antes de incluir '
                        'la cuenta {codigo}.',
    'rubro_largo': f'El rubro admite hasta {RUBRO_MAX} caracteres.',
    'es_resultado': 'Indica si es el resultado del ejercicio: verdadero o falso.',
    'resultado_patrimonio': 'Solo una cuenta de patrimonio lleva el resultado del ejercicio.',
    # importes
    'importe': 'Escribe un importe válido.',
    'decimales': 'Usa dos decimales.',
    'negativo': 'El importe no puede ser negativo.',
    'grande': 'El importe es demasiado grande.',
    'dos_lados': 'La línea lleva saldo en un solo lado: deja el otro en cero o vacío.',
    'cero': 'El saldo debe ser mayor que cero; si no lo conoces, déjalo vacío.',
}


def _error(codigo, http=400, texto=None, **extra):
    return api.ErrorApi(codigo, texto or TEXTOS[codigo], http, **extra)


def rechazo_de_estado(apertura, permitidos, texto=None):
    """409 `estado` con la forma de la decisión común 7: `{"error", "codigo": "estado", "estado": actual, "permitidos": […]}`.
    Va ya armado (api.Rechazo): en ErrorApi y en api.error, `estado` es el código HTTP y no puede viajar en el cuerpo."""
    return api.Rechazo(JsonResponse({'error': texto or TEXTOS['estado'], 'codigo': 'estado', 'estado': apertura.estado,
                                     'permitidos': list(permitidos)}, status=409))


# ---------------------------------------------------------------- historia

def evento(request, apertura, accion, de_estado='', a_estado='', detalle=None):
    """Inserta el `EventoApertura` (historia de solo inserción) con el autor de la petición."""
    usuario_id, usuario_nombre = inicio_contable.autor(request)
    return EventoApertura.objects.create(apertura=apertura, accion=accion, de_estado=de_estado, a_estado=a_estado,
                                         detalle=detalle or {}, usuario_id=usuario_id, usuario_nombre=usuario_nombre)


# ---------------------------------------------------------------- campos de un envío

def _texto(valor):
    """El texto sin espacios sobrantes; '' si no vino y None si no es texto."""
    if valor is None:
        return ''
    if not isinstance(valor, str):
        return None
    return ' '.join(valor.split())


ID_MAX = 2 ** 63 - 1


def _entero(valor):
    """Un id o una versión: entero mayor que cero como número o como texto de cifras; None si no lo es (tampoco un
    booleano, ni un número que no cabe en un id). La misma regla que los ids del plan de cuentas (cuentas.py)."""
    if isinstance(valor, str):
        valor = valor.strip()
        if not (valor.isascii() and valor.isdigit() and len(valor) <= 19):
            return None
        valor = int(valor)
    if not isinstance(valor, int) or isinstance(valor, bool) or not 0 < valor <= ID_MAX:
        return None
    return valor


def _booleano(datos, campo, errores, texto, por_defecto=False, clave=None):
    """Verdadero o falso: un booleano de JSON o, en un formulario, «true»/«false»/«1»/«0»/«on». El error va en `clave`
    (o en el campo)."""
    valor = datos.get(campo, por_defecto)
    if isinstance(valor, str) and valor.strip().lower() in ('true', 'false', '1', '0', 'on', ''):
        return valor.strip().lower() in ('true', '1', 'on')
    if not isinstance(valor, bool):
        errores.agregar(clave or campo, texto)
        return por_defecto
    return valor


def _version(datos, errores):
    version = _entero(datos.get('version'))
    if version is None:
        errores.agregar('version', TEXTOS['version_falta'])
    return version


def _motivo(datos, errores, campo='motivo'):
    motivo = _texto(datos.get(campo))
    if not motivo:
        errores.agregar(campo, TEXTOS['motivo'])
    elif len(motivo) > MOTIVO_MAX:
        errores.agregar(campo, TEXTOS['motivo_largo'])
    return motivo or ''


def leer_importe(valor):
    """Un importe escrito (texto o número) → Decimal con dos decimales, o None si viene vacío. ValueError con el texto
    si no es un importe: «1.234,56», «1,234.56» y «1234,56» valen; más de dos decimales no, salvo el ruido de una celda
    numérica de la hoja de cálculo (1234.5600000000002), que se redondea. El signo se devuelve: quien llama decide."""
    if valor is None or valor == '':
        return None
    if isinstance(valor, bool):
        raise ValueError(TEXTOS['importe'])
    if isinstance(valor, int):
        numero = Decimal(valor)
    elif isinstance(valor, float):
        numero = Decimal(repr(valor))
    elif isinstance(valor, str):
        texto = valor.strip().replace('$', '').replace(' ', '').replace(' ', '')
        if not texto:
            return None
        if ',' in texto and '.' in texto:
            texto = texto.replace('.', '').replace(',', '.') if texto.rfind(',') > texto.rfind('.') else texto.replace(',', '')
        elif ',' in texto:
            texto = texto.replace(',', '.')
        try:
            numero = Decimal(texto)
        except InvalidOperation:
            raise ValueError(TEXTOS['importe']) from None
    else:
        raise ValueError(TEXTOS['importe'])
    if not numero.is_finite():
        raise ValueError(TEXTOS['importe'])
    redondo = numero.quantize(CENTAVO)
    if redondo != numero and abs(redondo - numero) > RUIDO:
        raise ValueError(TEXTOS['decimales'])
    if abs(redondo) >= IMPORTE_MAX:
        raise ValueError(TEXTOS['grande'])
    return redondo


def saldos(debe, haber, errores, prefijo, saldo=None, con_saldo=False):
    """`(debe, haber)` de una línea a partir de lo escrito, con sus errores en `{prefijo}.debe` / `.haber` / `.saldo`.
    Los dos vacíos = desconocido (None, None). Un lado mayor que cero: el otro queda en cero (no es desconocido: el saldo
    de una cuenta está en un solo lado). Con `con_saldo` se lee una sola columna con signo (positivo = deudor)."""
    if con_saldo:
        try:
            valor = leer_importe(saldo)
        except ValueError as e:
            errores.agregar(f'{prefijo}.saldo', str(e))
            return None, None
        if valor is None:
            return None, None
        if valor == 0:
            errores.agregar(f'{prefijo}.saldo', TEXTOS['cero'])
            return None, None
        return (valor, CERO) if valor > 0 else (CERO, -valor)
    leidos, ilegible = {}, False
    for lado, escrito in (('debe', debe), ('haber', haber)):
        try:
            leidos[lado] = leer_importe(escrito)
        except ValueError as e:
            errores.agregar(f'{prefijo}.{lado}', str(e))
            ilegible = True
            continue
        if leidos[lado] is not None and leidos[lado] < 0:
            errores.agregar(f'{prefijo}.{lado}', TEXTOS['negativo'])
            ilegible = True
    if ilegible:
        return None, None
    d, h = leidos['debe'], leidos['haber']
    if d is None and h is None:
        return None, None
    if d and h:
        errores.agregar(f'{prefijo}.haber', TEXTOS['dos_lados'])
        return None, None
    if not d and not h:
        errores.agregar(f'{prefijo}.debe', TEXTOS['cero'])
        return None, None
    return (d, CERO) if d else (CERO, h)


# ---------------------------------------------------------------- lectura

def importe_texto(valor):
    return f'{valor:.2f}' if valor is not None else None


def _instante(valor):
    return valor.isoformat() if valor is not None else None


def _nombre(valor):
    return valor or None


def obtener(pk, bloqueada=False):
    """La apertura de la empresa activa (404 `no_existe` si no existe o es de otra). `bloqueada`: dentro de una
    transacción, con su fila bloqueada (`select_for_update(of=('self',))`, sin `select_related`: decisión común 4)."""
    consulta = Apertura.objects.select_for_update(of=('self',)) if bloqueada else Apertura.objects
    apertura = consulta.filter(pk=pk).first() if _entero(pk) is not None else None
    if apertura is None:
        raise _error('no_existe', 404)
    return apertura


def actuales():
    """`(en_preparacion, vigente)` de la empresa: la de `borrador | en_revision` y la confirmada, cada una o None. Una
    consulta."""
    en_preparacion = vigente = None
    for apertura in Apertura.objects.filter(estado__in=(*EN_PREPARACION, CONFIRMADA)).select_related('asiento'):
        if apertura.estado == CONFIRMADA:
            vigente = apertura
        else:
            en_preparacion = apertura
    return en_preparacion, vigente


def resumen(apertura):
    """Totales y pendientes de las líneas no retiradas, con una consulta agregada. Con algún importe pendiente los totales
    son desconocidos (null): una suma parcial no se presenta como el total."""
    r = LineaApertura.objects.filter(apertura=apertura, retirada=False).aggregate(
        lineas=Count('id'), suma_debe=Sum('debe'), suma_haber=Sum('haber'),   # sin el nombre del campo: lo usan los filtros
        sin_cuenta=Count('id', filter=Q(cuenta__isnull=True)),
        importe_pendiente=Count('id', filter=Q(debe__isnull=True) | Q(haber__isnull=True)),
        de_grupo=Count('id', filter=Q(cuenta__tipo='grupo')),
        sin_clase=Count('id', filter=Q(cuenta__clase='')))
    pendientes = {'sin_cuenta': r['sin_cuenta'], 'importe_pendiente': r['importe_pendiente'], 'de_grupo': r['de_grupo'],
                  'sin_clase': r['sin_clase']}
    if apertura.estado in CON_CONFIRMACION:
        debe, haber = apertura.total_debe, apertura.total_haber
    elif r['importe_pendiente']:
        debe = haber = None
    else:
        debe, haber = r['suma_debe'] or CERO, r['suma_haber'] or CERO
    diferencia = debe - haber if debe is not None and haber is not None else None
    return {'lineas': r['lineas'], 'debe': debe, 'haber': haber, 'diferencia': diferencia, 'pendientes': pendientes}


def dict_asiento(asiento):
    if asiento is None:
        return None
    return {'id': asiento.pk, 'numero': asiento.numero_completo, 'fecha': asiento.fecha.isoformat(),
            'debe': importe_texto(asiento.total_debe), 'haber': importe_texto(asiento.total_haber)}


def dict_corto(apertura, datos):
    """La apertura como la devuelve `mapear`: lo que cambia al mapear."""
    return {'id': apertura.pk, 'version': apertura.version, 'estado': apertura.estado, 'debe': importe_texto(datos['debe']),
            'haber': importe_texto(datos['haber']), 'diferencia': importe_texto(datos['diferencia']),
            'pendientes': datos['pendientes']}


def dict_apertura(apertura, datos=None, ajustes=None):
    """La apertura con la forma de GET /contabilidad/api/apertura/ (especificación, Parte B). `datos`: su `resumen` (si no
    se pasa, se calcula); `ajustes`: cuántos tiene (si no se pasa y pasó por confirmar, se cuentan)."""
    datos = datos or resumen(apertura)
    if ajustes is None:
        ajustes = AjusteApertura.objects.filter(apertura=apertura).count() if apertura.estado in CON_CONFIRMACION else 0
    return {
        'id': apertura.pk, 'version': apertura.version, 'estado': apertura.estado, 'fuente': apertura.fuente,
        'fuente_detalle': apertura.fuente_detalle, 'sin_saldos': apertura.sin_saldos,
        'fecha_corte': apertura.fecha_corte.isoformat(), 'moneda': apertura.moneda,
        'debe': importe_texto(datos['debe']), 'haber': importe_texto(datos['haber']),
        'diferencia': importe_texto(datos['diferencia']), 'lineas': datos['lineas'], 'pendientes': datos['pendientes'],
        'resultado_ejercicio': apertura.resultado_ejercicio, 'resultado_acumulado': importe_texto(apertura.resultado_acumulado),
        'inventario_modo': apertura.inventario_modo, 'ambitos_no_aplican': list(apertura.ambitos_no_aplican or []),
        'sustituye': apertura.sustituye_id, 'ajustes': ajustes,
        'asiento': dict_asiento(apertura.asiento) if apertura.asiento_id is not None else None,
        'enviado_por': _nombre(apertura.enviado_por_nombre), 'enviado_en': _instante(apertura.enviado_en),
        'revisado_por': _nombre(apertura.revisado_por_nombre), 'confirmado_por': _nombre(apertura.confirmado_por_nombre),
        'confirmado_en': _instante(apertura.confirmado_en),
        # Además de la forma de la especificación: quién la creó y, si se cerró (descartada…), por qué.
        'creado_por': _nombre(apertura.creado_por_nombre), 'creado_en': _instante(apertura.creado_en),
        'motivo': apertura.motivo,
    }


def dict_vigente(apertura):
    if apertura is None:
        return None
    return {'id': apertura.pk, 'version': apertura.version, 'fecha_corte': apertura.fecha_corte.isoformat(),
            'confirmado_en': _instante(apertura.confirmado_en),
            'asiento': dict_asiento(apertura.asiento) if apertura.asiento_id is not None else None}


def detallado_por_linea(apertura):
    """`{linea_id: (Σ saldo_inicial de sus auxiliares vigentes, cuántos)}`: una consulta agregada."""
    return {fila['linea']: (fila['total'], fila['filas']) for fila in AuxiliarApertura.objects.filter(
        apertura=apertura, estado=VIGENTE).values('linea').annotate(total=Sum('saldo_inicial'), filas=Count('id')).order_by()}


def estado_auxiliares(linea, detallado, filas):
    """`sin_declarar` (la cuenta no declara auxiliar: no es «no aplica»), `sin_detalle`, `incompleto`, `conciliada` o,
    si el detalle suma más que la línea, `no_concilia` (bloquea al validar: `auxiliar_no_concilia`)."""
    if not linea.detalle:
        return 'sin_declarar'
    if not filas:
        return 'sin_detalle'
    importe = cobertura.importe_de(linea.debe, linea.haber)
    if importe is None or detallado < importe:
        return 'incompleto'
    return 'conciliada' if detallado == importe else 'no_concilia'


def dict_linea(linea, detallado):
    total, filas = detallado.get(linea.pk, (CERO, 0))
    cuenta = linea.cuenta
    return {'id': linea.pk, 'orden': linea.orden,
            'cuenta': {'id': cuenta.pk, 'codigo': cuenta.codigo, 'nombre': cuenta.nombre, 'clase': cuenta.clase}
            if cuenta is not None else None,
            'rubro': linea.rubro_origen, 'codigo_origen': linea.codigo_origen, 'debe': importe_texto(linea.debe),
            'haber': importe_texto(linea.haber), 'detalle': linea.detalle, 'es_resultado_ejercicio': linea.es_resultado_ejercicio,
            'retirada': linea.retirada,
            'auxiliares': {'estado': estado_auxiliares(linea, total, filas), 'detallado': importe_texto(total), 'filas': filas},
            'filas_origen': linea.filas_origen}


def lineas(apertura, desde=0, hasta=None):
    """Las líneas de la apertura (también las retiradas) por orden, de `desde` a `hasta`: una consulta para las líneas con
    su cuenta y otra para lo detallado."""
    consulta = LineaApertura.objects.filter(apertura=apertura).select_related('cuenta').order_by('orden')
    filas = list(consulta[desde:hasta] if hasta is not None else consulta[desde:])
    detallado = detallado_por_linea(apertura) if filas else {}
    return [dict_linea(linea, detallado) for linea in filas]


def historial(apertura):
    return [{'accion': e.accion, 'de_estado': e.de_estado, 'a_estado': e.a_estado, 'usuario': _nombre(e.usuario_nombre),
             'fecha': e.creado_en.isoformat(), 'detalle': e.detalle}
            for e in EventoApertura.objects.filter(apertura=apertura).order_by('id')]


def dict_respaldo(respaldo):
    return {'id': respaldo.pk, 'nombre': respaldo.nombre, 'tipo': respaldo.tipo_mime, 'tamano': respaldo.tamano,
            'sha256': respaldo.sha256, 'descripcion': respaldo.descripcion, 'subido_por': _nombre(respaldo.subido_por_nombre),
            'subido_en': _instante(respaldo.subido_en),
            'estado': ANULADO if respaldo.anulado_en is not None else VIGENTE,
            'anulado_por': _nombre(respaldo.anulado_por_nombre), 'anulado_en': _instante(respaldo.anulado_en),
            'motivo_anulacion': respaldo.motivo_anulacion,
            # Sin página propia: la descarga es una ruta de API (decisión común 7).
            'url': None, 'recurso': {'tipo': 'respaldo_apertura', 'id': respaldo.pk,
                                     'api': f'/contabilidad/api/apertura/respaldos/{respaldo.pk}/descargar/'}}


def archivos(apertura):
    """Los lotes importados y los respaldos de la apertura, con su huella, del más reciente al más antiguo. Dos consultas
    (sin leer las filas de los lotes, que pueden pesar megas)."""
    lotes_ = [{'clase': 'importacion', 'id': lote['id'], 'nombre': lote['nombre'], 'tipo': lote['tipo'],
               'tamano': lote['tamano'], 'sha256': lote['sha256'], 'estado': lote['estado'],
               'subido_por': _nombre(lote['creado_por_nombre']), 'subido_en': _instante(lote['creado_en']),
               'url': None, 'recurso': {'tipo': 'importacion_apertura', 'id': lote['id'],
                                        'api': f'/contabilidad/api/apertura/importar/{lote["id"]}/'}}
              for lote in ImportacionApertura.objects.filter(apertura=apertura).values(
                  'id', 'nombre', 'tipo', 'tamano', 'sha256', 'estado', 'creado_por_nombre', 'creado_en')]
    respaldos_ = [{'clase': 'respaldo', **dict_respaldo(r)} for r in RespaldoApertura.objects.filter(apertura=apertura)]
    return sorted(lotes_ + respaldos_, key=lambda a: (a['subido_en'] or '', a['clase'], a['id']), reverse=True)


# ---------------------------------------------------------------- capacidades de la apertura

# acción → (permiso, estados en que se puede, sobre qué apertura: la mostrada o la vigente).
REGLAS_CAPACIDAD = {
    'editar': (PREPARAR, (BORRADOR,), 'apertura'),
    'validar': (PREPARAR, EN_PREPARACION, 'apertura'),
    'enviar': (PREPARAR, (BORRADOR,), 'apertura'),
    'devolver': (CONFIRMAR, (EN_REVISION,), 'apertura'),
    'confirmar': (CONFIRMAR, (EN_REVISION,), 'apertura'),
    'descartar': (PREPARAR, EN_PREPARACION, 'apertura'),
    'sustituir': (CONFIRMAR, (CONFIRMADA,), 'vigente'),
    'ajustar': (CONFIRMAR, (CONFIRMADA,), 'vigente'),
    'reversar': (CONFIRMAR, (CONFIRMADA,), 'vigente'),
    'cobrar': (COBRAR, (CONFIRMADA,), 'vigente'),
}
# PUNTO DE UNIÓN con la parte siguiente: acciones cuya ruta todavía no existe en esta rama. Responden falso aunque el rol,
# el estado y la licencia las permitan (nada se anuncia sin su ruta, como capacidades.Funcion). Quien publique la ruta
# quita aquí su acción: validar, enviar, devolver y confirmar la parte siguiente del corte 1; el resto, el corte 2.
# tests/test_apertura_preparar.py::test_capacidades_solo_con_su_ruta lo vigila.
SIN_CONSTRUIR = frozenset({'validar', 'enviar', 'devolver', 'confirmar', 'sustituir', 'ajustar', 'reversar', 'cobrar'})


def capacidades_de(request, apertura, vigente=None):
    """`{accion: bool}` = permiso ∧ estado ∧ licencia (con el plan vencido, todo falso: solo consulta)."""
    solo_consulta = cap.licencia(request)['solo_consulta']
    resultado = {}
    for accion, (permiso, estados, sobre) in REGLAS_CAPACIDAD.items():
        objeto = apertura if sobre == 'apertura' else vigente
        resultado[accion] = (accion not in SIN_CONSTRUIR and not solo_consulta and objeto is not None
                             and objeto.estado in estados and cap.tiene(request, permiso))
    return resultado


def datos_de_la_empresa(request):
    """El cuerpo de GET /contabilidad/api/apertura/: configuración, la apertura en preparación (o, si no la hay, la
    confirmada), la vigente, la cobertura, las capacidades y el acceso. Sin inicio contable responde igual (200), con todo
    en null y la cobertura pendiente."""
    inicio = InicioContable.objects.first()
    en_preparacion, vigente = actuales()
    mostrada = en_preparacion or vigente
    return {
        'empresa': cap.empresa_de(request),
        'configuracion': inicio_contable.dict_configuracion(inicio),
        'modalidad': inicio.modalidad if inicio is not None else None,
        'fecha_corte': inicio.fecha_corte.isoformat() if inicio is not None else None,
        'operaciones_desde': inicio.operaciones_desde.isoformat() if inicio is not None else None,
        'apertura': dict_apertura(mostrada) if mostrada is not None else None,
        'vigente': dict_vigente(vigente),
        'cobertura': cobertura.de_la_empresa(inicio, vigente, en_preparacion, inicio_contable.hoy()),
        'capacidades': capacidades_de(request, mostrada, vigente),
        'acceso': cap.capacidades(request),
    }


def detalle(request, pk):
    """El cuerpo de GET /contabilidad/api/apertura/<id>/."""
    apertura = Apertura.objects.select_related('asiento').filter(pk=pk).first() if _entero(pk) is not None else None
    if apertura is None:
        raise _error('no_existe', 404)
    ajustes = [{'id': a.pk, 'numero': a.numero, 'fecha': a.fecha.isoformat(), 'motivo': a.motivo, 'estado': a.estado,
                'asiento': {'id': a.asiento_id, 'numero': a.asiento.numero_completo}}
               for a in AjusteApertura.objects.filter(apertura=apertura).select_related('asiento').order_by('numero')]
    vigente = apertura if apertura.estado == CONFIRMADA else None
    return {'apertura': dict_apertura(apertura, ajustes=len(ajustes)), 'archivos': archivos(apertura), 'ajustes': ajustes,
            'historial': historial(apertura), 'capacidades': capacidades_de(request, apertura, vigente)}


# ---------------------------------------------------------------- crear

def _encabezado(datos, errores):
    """`fuente`, `fuente_detalle` y `sin_saldos` de la creación."""
    fuente = datos.get('fuente')
    if fuente not in VALORES_FUENTE:
        errores.agregar('fuente', TEXTOS['fuente'])
    detalle_ = _texto(datos.get('fuente_detalle'))
    if detalle_ is None:
        errores.agregar('fuente_detalle', TEXTOS['fuente_detalle_largo'])
        detalle_ = ''
    elif len(detalle_) > FUENTE_DETALLE_MAX:
        errores.agregar('fuente_detalle', TEXTOS['fuente_detalle_largo'])
    sin_saldos = _booleano(datos, 'sin_saldos', errores, TEXTOS['sin_saldos'])
    if sin_saldos and fuente in VALORES_FUENTE and fuente != INICIO_ACTIVIDADES:
        errores.agregar('sin_saldos', TEXTOS['sin_saldos_fuente'])
    if sin_saldos and not detalle_:
        errores.agregar('fuente_detalle', TEXTOS['sin_saldos_detalle'])
    return {'fuente': fuente, 'fuente_detalle': detalle_, 'sin_saldos': sin_saldos}


def _repetida(apertura, config, encabezado):
    """El envío con la misma clave: el mismo contenido devuelve la apertura (`repetido`); otro, 409 `clave_usada`. Se
    compara con la apertura y la configuración como están ahora."""
    inicio = InicioContable.objects.first()
    igual = (config is not None and inicio is not None and all(getattr(inicio, c) == config[c] for c in inicio_contable.CAMPOS)
             and apertura.fecha_corte == config['fecha_corte']
             and all(getattr(apertura, c) == v for c, v in encabezado.items()))
    if not igual:
        raise _error('clave_usada', 409, apertura=dict_apertura(apertura))
    return inicio, apertura, True


def _exigir_sin_otra_en_preparacion():
    otra = Apertura.objects.filter(estado__in=EN_PREPARACION).first()
    if otra is not None:
        raise _error('apertura_existente', 409, apertura=dict_apertura(otra))


def crear(request, datos):
    """POST /contabilidad/api/apertura/: crea o actualiza la configuración y crea el borrador, en una transacción con el
    candado del libro. `{clave, modalidad, fecha_corte | (historial_desde, historial_hasta), fuente, fuente_detalle,
    sin_saldos?}`. Devuelve `(inicio, apertura, repetido)`."""
    api.exigir_permiso(request, PREPARAR)
    faltan = cap.faltantes(request, 'apertura')   # plan de cuentas sin ninguna cuenta de movimiento activa
    if faltan:
        raise api.Rechazo(cap.rechazo_datos(faltan))
    clave = api.clave_de(datos)
    errores = api.Errores()
    config = inicio_contable.leer(datos, errores)
    encabezado = _encabezado(datos, errores)
    existente = Apertura.objects.filter(clave=clave).first()
    if existente is not None:
        return _repetida(existente, config, encabezado)
    if errores:
        # Nada se va a escribir: sin candado. Lo que lo habría impedido aunque estuviera bien escrito va antes.
        if inicio_contable.hay_confirmada():
            raise _error('apertura_confirmada', 409, texto=inicio_contable.TEXTOS['apertura_confirmada'])
        _exigir_sin_otra_en_preparacion()
        errores.comprobar()
    ahora = timezone.now()
    try:
        with inicio_contable.libro(crear=inicio_contable.fila_nueva(request, config, ahora)) as inicio:
            existente = Apertura.objects.filter(clave=clave).first()   # el mismo envío, que entró antes en el candado
            if existente is not None:
                return _repetida(existente, config, encabezado)
            nueva = inicio_contable.creada(inicio, ahora)
            if not nueva:
                if inicio_contable.hay_confirmada():
                    raise _error('apertura_confirmada', 409, texto=inicio_contable.TEXTOS['apertura_confirmada'])
                _exigir_sin_otra_en_preparacion()
            inicio_contable.exigir_configurable(None, config)   # aunque la fila sea nueva: rango_solapado
            por_id, por_nombre = inicio_contable.autor(request)
            apertura = Apertura(company=request.company, clave=clave, fecha_corte=config['fecha_corte'],
                                creado_por_id=por_id, creado_por_nombre=por_nombre, **encabezado)
            apertura.save()
            inicio_contable.guardar(request, inicio, config, nueva=nueva, apertura=apertura)
            evento(request, apertura, 'creada', a_estado=BORRADOR,
                   detalle={'fuente': apertura.fuente, 'sin_saldos': apertura.sin_saldos,
                            'fecha_corte': apertura.fecha_corte.isoformat(), 'modalidad': inicio.modalidad})
            audit(request, 'apertura_creada', company=request.company, apertura=apertura.pk, inicio=inicio.pk,
                  modalidad=inicio.modalidad, fecha_corte=apertura.fecha_corte.isoformat(), fuente=apertura.fuente,
                  sin_saldos=apertura.sin_saldos)
            return inicio, apertura, False
    except IntegrityError:
        # Quien escribió sin pasar por el candado ganó la carrera (la clave o la única en preparación): decide la base.
        existente = Apertura.objects.filter(clave=clave).first()
        if existente is not None:
            return _repetida(existente, config, encabezado)
        _exigir_sin_otra_en_preparacion()
        raise


# ---------------------------------------------------------------- editar el encabezado

def _ambitos_no_aplican(apertura, valor, errores):
    """La declaración `[{ambito, nota}]`: ámbito conocido y sin repetir, nota obligatoria, y ningún ámbito con cuentas de
    ese detalle en la apertura (una consulta)."""
    if not isinstance(valor, list):
        errores.agregar('ambitos_no_aplican', TEXTOS['ambitos'])
        return None
    con_cuentas = set(LineaApertura.objects.filter(apertura=apertura, retirada=False).exclude(detalle='')
                      .values_list('detalle', flat=True).distinct())
    limpios, vistos = [], set()
    for i, declarado in enumerate(valor):
        prefijo = f'ambitos_no_aplican.{i}'
        if not isinstance(declarado, dict):
            errores.agregar(prefijo, TEXTOS['ambitos'])
            continue
        ambito, nota = declarado.get('ambito'), _texto(declarado.get('nota'))
        if ambito not in cobertura.AMBITOS_DECLARABLES:
            errores.agregar(f'{prefijo}.ambito', TEXTOS['ambito'])
        elif ambito in vistos:
            errores.agregar(f'{prefijo}.ambito', TEXTOS['ambito_repetido'])
        elif cobertura.DETALLE_DE[ambito] in con_cuentas:
            errores.agregar(f'{prefijo}.ambito', TEXTOS['ambito_con_cuentas'])
        if not nota:
            errores.agregar(f'{prefijo}.nota', TEXTOS['nota_ambito'])
        elif len(nota) > NOTA_AMBITO_MAX:
            errores.agregar(f'{prefijo}.nota', TEXTOS['nota_ambito_larga'])
        vistos.add(ambito)
        limpios.append({'ambito': ambito, 'nota': nota})
    return limpios


def _cambios(apertura, datos, errores):
    """`{campo: valor nuevo}` de lo que el envío cambia del encabezado (solo lo que viene y es distinto)."""
    cambios = {}
    for campo in ('modalidad', 'sin_saldos', 'historial_desde'):
        if campo in datos:
            errores.agregar(campo, TEXTOS['fijo'])
    fuente, detalle_ = apertura.fuente, apertura.fuente_detalle
    if 'fuente' in datos:
        if datos['fuente'] not in VALORES_FUENTE:
            errores.agregar('fuente', TEXTOS['fuente'])
        else:
            fuente = datos['fuente']
    if 'fuente_detalle' in datos:
        detalle_ = _texto(datos['fuente_detalle'])
        if detalle_ is None or len(detalle_) > FUENTE_DETALLE_MAX:
            errores.agregar('fuente_detalle', TEXTOS['fuente_detalle_largo'])
            detalle_ = apertura.fuente_detalle
    if apertura.sin_saldos and fuente != INICIO_ACTIVIDADES:
        errores.agregar('fuente', TEXTOS['sin_saldos_fuente'])
    if apertura.sin_saldos and not detalle_:
        errores.agregar('fuente_detalle', TEXTOS['sin_saldos_detalle'])
    if 'resultado_ejercicio' in datos:
        if datos['resultado_ejercicio'] not in VALORES_RESULTADO:
            errores.agregar('resultado_ejercicio', TEXTOS['resultado_ejercicio'])
        else:
            cambios['resultado_ejercicio'] = datos['resultado_ejercicio']
    if 'resultado_acumulado' in datos:
        try:
            cambios['resultado_acumulado'] = leer_importe(datos['resultado_acumulado'])   # puede ser negativo (pérdida)
        except ValueError:
            errores.agregar('resultado_acumulado', TEXTOS['resultado_acumulado'])
    if 'inventario_modo' in datos:
        if datos['inventario_modo'] not in VALORES_INVENTARIO:
            errores.agregar('inventario_modo', TEXTOS['inventario_modo'])
        else:
            cambios['inventario_modo'] = datos['inventario_modo']
    if 'ambitos_no_aplican' in datos:
        ambitos = _ambitos_no_aplican(apertura, datos['ambitos_no_aplican'], errores)
        if ambitos is not None:
            cambios['ambitos_no_aplican'] = ambitos
    cambios.update(fuente=fuente, fuente_detalle=detalle_)
    return {campo: valor for campo, valor in cambios.items() if getattr(apertura, campo) != valor}


def editar(request, pk, datos):
    """PATCH /contabilidad/api/apertura/<id>/ (solo borrador): `{version, fecha_corte?, historial_hasta?, fuente?,
    fuente_detalle?, resultado_ejercicio?, resultado_acumulado?, inventario_modo?, ambitos_no_aplican?}`. Mover el corte
    cambia la configuración: entonces toma antes el candado. Devuelve `(apertura, inicio)`. Si nada cambia, no sube la
    versión ni deja registro."""
    api.exigir_permiso(request, PREPARAR)
    toca_configuracion = 'fecha_corte' in datos or 'historial_hasta' in datos
    with (inicio_contable.libro() if toca_configuracion else _sin_candado()) as inicio:
        apertura = obtener(pk, bloqueada=True)
        errores = api.Errores()
        version = _version(datos, errores)
        if version is not None and version != apertura.version:
            raise _error('version', 409, apertura=dict_apertura(apertura))
        if apertura.estado != BORRADOR:
            raise rechazo_de_estado(apertura, [BORRADOR])
        config = inicio_contable.cambiar(inicio, datos, errores) if toca_configuracion else None
        if config is not None and all(getattr(inicio, c) == config[c] for c in inicio_contable.CAMPOS):
            config = None   # el mismo corte: no hay nada que comprobar ni que guardar
        if config is not None:
            inicio_contable.exigir_configurable(inicio, config)
        cambios = _cambios(apertura, datos, errores)
        errores.comprobar()
        if config is not None:
            cambios['fecha_corte'] = config['fecha_corte']
            inicio_contable.guardar(request, inicio, config, apertura=apertura)
        cambios = {c: v for c, v in cambios.items() if getattr(apertura, c) != v}
        if cambios:
            antes = {c: getattr(apertura, c) for c in cambios}
            for campo, valor in cambios.items():
                setattr(apertura, campo, valor)
            apertura.version += 1
            apertura.save(update_fields=[*cambios, 'version'])
            evento(request, apertura, 'modificada', detalle={'version': apertura.version, 'cambios': {
                c: [_json(antes[c]), _json(cambios[c])] for c in cambios}})
            audit(request, 'apertura_modificada', company=request.company, apertura=apertura.pk, version=apertura.version,
                  campos=sorted(cambios))
    return apertura, inicio


@contextmanager
def _sin_candado():
    """Lo que cambia solo la apertura (no la configuración) no toma el candado del libro: una transacción y la fila del
    inicio, sin bloquear."""
    with transaction.atomic():
        yield InicioContable.objects.first()


def _json(valor):
    if isinstance(valor, Decimal):
        return importe_texto(valor)
    return valor.isoformat() if hasattr(valor, 'isoformat') else valor


# ---------------------------------------------------------------- mapear

@dataclass
class Pedida:
    """Una línea del conjunto que se envía a `mapear` (de la captura directa o de las filas de un lote)."""
    cuenta_id: int | None
    debe: Decimal | None
    haber: Decimal | None
    rubro: str | None = None            # None: se conserva el de la línea (captura directa sin rubro)
    es_resultado_ejercicio: bool = False
    codigo: str = ''
    lote_id: int | None = None
    filas_origen: list = field(default_factory=list)
    desde_lote: bool = False            # la fuente es el lote: su procedencia (lote, filas, código) se escribe


def cuentas_de_la_empresa():
    """`{id: {...}}` de todas las cuentas de la empresa activa, con lo que el mapeo necesita: una consulta (también con
    5 000 cuentas) en lugar de una por línea."""
    return {c['id']: c for c in Cuenta.objects.order_by().values('id', 'codigo', 'codigo_norm', 'nombre', 'tipo', 'activa',
                                                                   'clase', 'auxiliar')}


def comprobar_cuenta(cuenta, prefijo, errores, no_aplican):
    """La cuenta (ya de la empresa) admite una línea: de movimiento, activa y con un detalle que la apertura no haya
    declarado «no aplica». Devuelve True si es un grupo (la respuesta lleva entonces el código `cuenta_de_grupo`)."""
    if cuenta['tipo'] != 'movimiento':
        errores.agregar(prefijo, TEXTOS['cuenta_de_grupo'].format(codigo=cuenta['codigo']))
        return True
    if not cuenta['activa']:
        errores.agregar(prefijo, TEXTOS['cuenta_inactiva'].format(codigo=cuenta['codigo']))
    ambito = next((a for a, d in cobertura.DETALLE_DE.items() if d == cuenta['auxiliar']), None)
    if ambito is not None and ambito in no_aplican:
        errores.agregar(prefijo, TEXTOS['cuenta_no_aplica'].format(ambito=cobertura.NOMBRE[ambito], codigo=cuenta['codigo']))
    return False


def no_aplican_de(apertura):
    return {d.get('ambito') for d in apertura.ambitos_no_aplican or [] if isinstance(d, dict)}


def _capturadas(apertura, datos, cuentas, errores):
    """Las líneas de la captura directa: `[{cuenta_id | null, rubro, debe | null, haber | null, es_resultado_ejercicio?}]`
    (el conjunto completo). Devuelve `(pedidas, ajenas, de_grupo)`: `ajenas` son las posiciones con una cuenta que no es de
    la empresa (404)."""
    enviadas = datos.get('lineas')
    if not isinstance(enviadas, list):
        errores.agregar('lineas', TEXTOS['lineas'])
        return [], {}, False
    if len(enviadas) > MAX_LINEAS:
        errores.agregar('lineas', TEXTOS['demasiadas_lineas'])
        return [], {}, False
    no_aplican = no_aplican_de(apertura)
    pedidas, ajenas, usadas, de_grupo = [], {}, {}, False
    for i, enviada in enumerate(enviadas):
        prefijo = f'lineas.{i}'
        if not isinstance(enviada, dict):
            errores.agregar(prefijo, TEXTOS['linea'])
            continue
        cuenta_id, cuenta = None, None
        if enviada.get('cuenta_id') not in (None, ''):
            cuenta_id = _entero(enviada.get('cuenta_id'))
            if cuenta_id is None:
                errores.agregar(f'{prefijo}.cuenta_id', TEXTOS['cuenta_id'])
            elif cuenta_id not in cuentas:
                ajenas[f'{prefijo}.cuenta_id'] = [TEXTOS['cuenta_no_existe']]
                cuenta_id = None
            else:
                cuenta = cuentas[cuenta_id]
                de_grupo |= comprobar_cuenta(cuenta, f'{prefijo}.cuenta_id', errores, no_aplican)
                if cuenta_id in usadas:
                    errores.agregar(f'{prefijo}.cuenta_id', TEXTOS['cuenta_repetida'].format(codigo=cuenta['codigo'],
                                                                                            posicion=usadas[cuenta_id] + 1))
                usadas.setdefault(cuenta_id, i)
        rubro = None
        if 'rubro' in enviada:
            rubro = _texto(enviada.get('rubro'))
            if rubro is None or len(rubro) > RUBRO_MAX:
                errores.agregar(f'{prefijo}.rubro', TEXTOS['rubro_largo'])
                rubro = None
        debe, haber = saldos(enviada.get('debe'), enviada.get('haber'), errores, prefijo)
        es_resultado = _booleano(enviada, 'es_resultado_ejercicio', errores, TEXTOS['es_resultado'],
                                 clave=f'{prefijo}.es_resultado_ejercicio')
        if es_resultado and cuenta is not None and cuenta['clase'] != 'patrimonio':
            errores.agregar(f'{prefijo}.es_resultado_ejercicio', TEXTOS['resultado_patrimonio'])
        if es_resultado and cuenta is None and cuenta_id is None:
            errores.agregar(f'{prefijo}.es_resultado_ejercicio', TEXTOS['resultado_patrimonio'])
        pedidas.append(Pedida(cuenta_id=cuenta_id, debe=debe, haber=haber, rubro=rubro, es_resultado_ejercicio=es_resultado))
    return pedidas, ajenas, de_grupo


CAMPOS_DE_LINEA = ('debe', 'haber', 'rubro_origen', 'codigo_origen', 'detalle', 'es_resultado_ejercicio', 'retirada', 'lote',
                   'filas_origen')


def _escribir(linea, pedida, cuentas):
    """Fija en `linea` lo que dice `pedida`. True si algo cambió."""
    antes = tuple(getattr(linea, c if c != 'lote' else 'lote_id') for c in CAMPOS_DE_LINEA)
    linea.debe, linea.haber, linea.retirada = pedida.debe, pedida.haber, False
    linea.es_resultado_ejercicio = pedida.es_resultado_ejercicio
    linea.detalle = cuentas[pedida.cuenta_id]['auxiliar'] if pedida.cuenta_id is not None else ''
    if pedida.rubro is not None:
        linea.rubro_origen = pedida.rubro
    if pedida.desde_lote:
        linea.lote_id, linea.filas_origen, linea.codigo_origen = pedida.lote_id, pedida.filas_origen, pedida.codigo
    return antes != tuple(getattr(linea, c if c != 'lote' else 'lote_id') for c in CAMPOS_DE_LINEA)


def _conciliar(apertura, pedidas, cuentas):
    """Concilia el conjunto pedido con las líneas que ya existen (también las retiradas), sin borrar ninguna:
    `(altas, cambiadas, retiradas)`. Por `cuenta_id`; las que no tienen cuenta, por orden. Una consulta."""
    existentes = list(LineaApertura.objects.filter(apertura=apertura).order_by('orden'))
    por_cuenta = {linea.cuenta_id: linea for linea in existentes if linea.cuenta_id is not None}
    sin_cuenta = iter([linea for linea in existentes if linea.cuenta_id is None])
    siguiente = max((linea.orden for linea in existentes), default=0) + 1
    usadas, altas, cambiadas = set(), [], []
    for pedida in pedidas:
        linea = por_cuenta.get(pedida.cuenta_id) if pedida.cuenta_id is not None else next(sin_cuenta, None)
        if linea is None:
            linea = LineaApertura(company_id=apertura.company_id, apertura=apertura, orden=siguiente, cuenta_id=pedida.cuenta_id)
            siguiente += 1
            _escribir(linea, pedida, cuentas)
            altas.append(linea)
            continue
        usadas.add(linea.pk)
        if _escribir(linea, pedida, cuentas):
            cambiadas.append(linea)
    retiradas = [linea for linea in existentes if linea.pk not in usadas and not linea.retirada]
    return altas, cambiadas, retiradas


def _exigir_sin_auxiliares(retiradas):
    """Una línea que se quita con auxiliares vigentes → 409 (primero se anulan o se mueven). Una consulta agregada."""
    if not retiradas:
        return
    con_auxiliares = (AuxiliarApertura.objects.filter(linea__in=[linea.pk for linea in retiradas], estado=VIGENTE)
                      .values('linea').annotate(n=Count('id')).order_by('linea').first())
    if con_auxiliares is not None:
        raise _error('linea_con_auxiliares', 409, linea_id=con_auxiliares['linea'], auxiliares=con_auxiliares['n'])


def mapear(request, pk, datos):
    """POST /contabilidad/api/apertura/<id>/mapear/: fija las líneas del borrador, con la captura directa del conjunto
    completo (`{version, lineas: [...]}`) o desde un lote (`{version, lote_id, columnas, decisiones}`). Devuelve
    `(apertura, resumen, retiradas)`. Nada se confirma: la diferencia se calcula en el servidor."""
    from core.contabilidad import apertura_importar   # usa este módulo: se importa al usarlo
    api.exigir_permiso(request, PREPARAR)
    errores = api.Errores()
    desde_lote = datos.get('lote_id') not in (None, '')
    with transaction.atomic():
        apertura = obtener(pk, bloqueada=True)
        version = _version(datos, errores)
        if version is not None and version != apertura.version:
            raise _error('version', 409, apertura=dict_apertura(apertura))
        if apertura.estado != BORRADOR:
            raise rechazo_de_estado(apertura, [BORRADOR])
        if desde_lote and 'lineas' in datos:   # no se sabe cuál de los dos conjuntos se quería: nada más que revisar
            errores.agregar('lineas', TEXTOS['lineas_y_lote'])
            errores.comprobar()
        cuentas = cuentas_de_la_empresa()
        lote = None
        if desde_lote:
            lote = apertura_importar.lote_de(apertura, datos.get('lote_id'), bloqueado=True)
            pedidas, ajenas, de_grupo, resumen_lote = apertura_importar.pedidas_del_lote(apertura, lote, datos, cuentas, errores)
        else:
            pedidas, ajenas, de_grupo = _capturadas(apertura, datos, cuentas, errores)
            resumen_lote = None
        if ajenas:
            raise _error('no_existe', 404, texto=TEXTOS['cuenta_no_existe'], errores=ajenas)
        altas, cambiadas, retiradas = _conciliar(apertura, pedidas, cuentas)
        _exigir_sin_auxiliares(retiradas)
        if errores:
            raise api.ErrorApi('cuenta_de_grupo' if de_grupo else 'validacion', api.TEXTOS['validacion'], errores=dict(errores))
        lote_aplicado = lote is not None and (lote.estado != 'aplicado' or lote.mapeo != resumen_lote['mapeo'])
        if altas or cambiadas or retiradas or lote_aplicado:
            ahora = timezone.now()
            LineaApertura.objects.bulk_create(altas, batch_size=lotes.TAMANO_LOTE)
            LineaApertura.objects.bulk_update(cambiadas, CAMPOS_DE_LINEA, batch_size=lotes.TAMANO_LOTE)
            ids = [linea.pk for linea in retiradas]
            for desde in range(0, len(ids), lotes.TAMANO_LOTE):
                LineaApertura.objects.filter(pk__in=ids[desde:desde + lotes.TAMANO_LOTE]).update(retirada=True, debe=None,
                                                                                                    haber=None)
            if lote is not None:
                lote.estado, lote.mapeo = 'aplicado', resumen_lote['mapeo']
                lote.aplicado_por_id, lote.aplicado_por_nombre = inicio_contable.autor(request)
                lote.aplicado_en = ahora
                lote.save(update_fields=['estado', 'mapeo', 'aplicado_por_id', 'aplicado_por_nombre', 'aplicado_en'])
            apertura.version += 1
            apertura.save(update_fields=['version'])
            conteos = {'altas': len(altas), 'cambios': len(cambiadas), 'retiradas': len(retiradas),
                       'lote_id': lote.pk if lote is not None else None}
            if resumen_lote is not None:
                conteos.update(omitidas=resumen_lote['omitidas'], agrupadas=resumen_lote['agrupadas'])
            evento(request, apertura, 'mapeada', detalle={'version': apertura.version, **conteos})
            audit(request, 'apertura_modificada', company=request.company, apertura=apertura.pk, version=apertura.version,
                  accion='mapear', **conteos)
        return apertura, resumen(apertura), len(retiradas)


# ---------------------------------------------------------------- descartar

def descartar(request, pk, datos):
    """POST /contabilidad/api/apertura/<id>/descartar/ (`borrador | en_revision`): `{version, motivo}` → `descartada`.
    Nada se borra; anula además los auxiliares vigentes del borrador (para que una nueva sustitución pueda volver a copiar
    los de la vigente) y libera el lugar de la apertura en preparación."""
    api.exigir_permiso(request, PREPARAR)
    errores = api.Errores()
    with transaction.atomic():
        apertura = obtener(pk, bloqueada=True)
        version = _version(datos, errores)
        if version is not None and version != apertura.version:
            raise _error('version', 409, apertura=dict_apertura(apertura))
        if apertura.estado not in EN_PREPARACION:
            raise rechazo_de_estado(apertura, EN_PREPARACION, TEXTOS['estado_preparacion'])
        motivo = _motivo(datos, errores)
        errores.comprobar()
        ahora = timezone.now()
        por_id, por_nombre = inicio_contable.autor(request)
        # Orden global de bloqueos: la apertura y después sus auxiliares, por id.
        auxiliares = list(AuxiliarApertura.objects.select_for_update(of=('self',)).filter(apertura=apertura, estado=VIGENTE)
                          .order_by('id').values_list('id', flat=True))
        for desde in range(0, len(auxiliares), lotes.TAMANO_LOTE):
            AuxiliarApertura.objects.filter(pk__in=auxiliares[desde:desde + lotes.TAMANO_LOTE]).update(
                estado=ANULADO, anulado_en=ahora, anulado_por_id=por_id, anulado_por_nombre=por_nombre,
                motivo_anulacion=MOTIVO_DESCARTE_AUXILIAR)
        anterior = apertura.estado
        apertura.estado, apertura.motivo = DESCARTADA, motivo
        apertura.cerrado_por_id, apertura.cerrado_por_nombre, apertura.cerrado_en = por_id, por_nombre, ahora
        apertura.version += 1
        apertura.save(update_fields=['estado', 'motivo', 'cerrado_por_id', 'cerrado_por_nombre', 'cerrado_en', 'version'])
        evento(request, apertura, 'descartada', de_estado=anterior, a_estado=DESCARTADA,
               detalle={'version': apertura.version, 'motivo': motivo, 'auxiliares_anulados': len(auxiliares)})
        audit(request, 'apertura_descartada', company=request.company, apertura=apertura.pk, version=apertura.version,
              motivo=motivo, auxiliares_anulados=len(auxiliares))
    return apertura


# ---------------------------------------------------------------- respaldos

def _respaldo_repetido(existente, sha256, descripcion):
    if existente.sha256 == sha256 and existente.descripcion == descripcion:
        return existente, True
    raise _error('clave_usada', 409, respaldo=dict_respaldo(existente))


def subir_respaldo(request, pk, archivo, datos):
    """POST /contabilidad/api/apertura/<id>/respaldos/ (multipart `archivo`, `descripcion`, `clave`): un PDF, JPG, PNG, XLSX
    o CSV de hasta 8 MB validado por su contenido (respaldos.validar). Solo con la apertura en preparación. Devuelve
    `(respaldo, repetido)`. El archivo se conserva siempre (también al anularlo)."""
    api.exigir_permiso(request, PREPARAR)
    clave = api.clave_de(datos)
    errores = api.Errores()
    if archivo is None:
        errores.agregar('archivo', TEXTOS['archivo'])
        contenido = b''
    elif archivo.size > respaldos.MAX_BYTES:   # antes de leerlo: no se carga en memoria lo que no se va a aceptar
        raise api.ErrorApi('archivo_grande', f'El archivo pesa más de {respaldos.MAX_BYTES // respaldos.MB} MB.',
                           errores={'archivo': [f'El archivo pesa más de {respaldos.MAX_BYTES // respaldos.MB} MB.']})
    else:
        contenido = archivo.read()
    descripcion = _texto(datos.get('descripcion'))
    if descripcion is None or len(descripcion) > DESCRIPCION_MAX:
        errores.agregar('descripcion', TEXTOS['descripcion_larga'])
        descripcion = ''
    validado = None
    if archivo is not None:
        try:
            validado = respaldos.validar(getattr(archivo, 'name', ''), contenido)
        except respaldos.ArchivoInvalido as e:
            errores.agregar('archivo', str(e))
    sha256 = hashlib.sha256(contenido).hexdigest()
    existente = RespaldoApertura.objects.filter(clave=clave).first()
    if existente is not None:
        return _respaldo_repetido(existente, sha256, descripcion)
    guardado = None
    try:
        with transaction.atomic():
            apertura = obtener(pk, bloqueada=True)
            if apertura.estado not in EN_PREPARACION:
                raise rechazo_de_estado(apertura, EN_PREPARACION, TEXTOS['estado_preparacion'])
            errores.comprobar()
            nombre, tipo_mime, sha256 = validado
            por_id, por_nombre = inicio_contable.autor(request)
            respaldo = RespaldoApertura(company=request.company, apertura=apertura, nombre=nombre, tipo_mime=tipo_mime,
                                        tamano=len(contenido), sha256=sha256, descripcion=descripcion, clave=clave,
                                        subido_por_id=por_id, subido_por_nombre=por_nombre)
            respaldo.archivo.save(f'respaldo.{nombre.rsplit(".", 1)[-1]}', ContentFile(contenido), save=False)
            guardado = respaldo.archivo.name
            respaldo.save()
            evento(request, apertura, 'respaldo_subido', detalle={'respaldo_id': respaldo.pk, 'nombre': nombre,
                                                                  'sha256': sha256, 'tamano': len(contenido)})
            audit(request, 'apertura_respaldo', company=request.company, apertura=apertura.pk, respaldo=respaldo.pk,
                  accion='subido', sha256=sha256, tamano=len(contenido))
        return respaldo, False
    except IntegrityError:
        if guardado:
            respaldo.archivo.storage.delete(guardado)
        existente = RespaldoApertura.objects.filter(clave=clave).first()
        if existente is None:
            raise
        return _respaldo_repetido(existente, sha256, descripcion)
    except Exception:
        if guardado:   # la transacción se deshizo: el archivo no queda huérfano en el disco
            respaldo.archivo.storage.delete(guardado)
        raise


def obtener_respaldo(pk):
    """El respaldo de la empresa activa (404 si no existe o es de otra)."""
    encontrado = RespaldoApertura.objects.filter(pk=pk).first() if _entero(pk) is not None else None
    if encontrado is None:
        raise _error('no_existe', 404, texto=TEXTOS['respaldo_no_existe'])
    return encontrado


def anular_respaldo(request, pk, datos):
    """POST /contabilidad/api/apertura/respaldos/<id>/anular/ `{motivo}`: lo marca anulado (con autor, fecha y motivo); el
    archivo se conserva. Solo con la apertura en preparación."""
    api.exigir_permiso(request, PREPARAR)
    errores = api.Errores()
    with transaction.atomic():
        apertura_id = obtener_respaldo(pk).apertura_id
        apertura = obtener(apertura_id, bloqueada=True)   # la apertura antes que lo que cuelga de ella
        anulado = RespaldoApertura.objects.select_for_update(of=('self',)).get(pk=pk)
        if anulado.anulado_en is not None:
            raise _error('ya_anulado', 409, respaldo=dict_respaldo(anulado))
        if apertura.estado not in EN_PREPARACION:
            raise rechazo_de_estado(apertura, EN_PREPARACION, TEXTOS['estado_preparacion'])
        motivo = _motivo(datos, errores)
        errores.comprobar()
        anulado.anulado_por_id, anulado.anulado_por_nombre = inicio_contable.autor(request)
        anulado.anulado_en, anulado.motivo_anulacion = timezone.now(), motivo
        anulado.save(update_fields=['anulado_por_id', 'anulado_por_nombre', 'anulado_en', 'motivo_anulacion'])
        evento(request, apertura, 'respaldo_anulado', detalle={'respaldo_id': anulado.pk, 'motivo': motivo})
        audit(request, 'apertura_respaldo', company=request.company, apertura=apertura.pk, respaldo=anulado.pk,
              accion='anulado', motivo=motivo)
    return anulado
