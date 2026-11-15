"""Importación de los saldos de la apertura con vista previa (Parte B de contable/bloque-2-especificacion.md): subir el
archivo, ver qué pasaría con cada fila y, con `mapear` (apertura.py), llevar las filas a las líneas. Nada se escribe en las
líneas hasta mapear.

- `subir`: lee el CSV (`;` o `,`, con o sin BOM) o el XLSX con el lector tabular del bloque 1 (lectura_tabular.py: las
  mismas defensas y los mismos límites, 2 MB y 5 000 filas), lo guarda en la carpeta privada de la empresa con su huella y
  deja el lote `ImportacionApertura` con los encabezados, las filas leídas y las columnas elegidas por su encabezado (sin
  tildes ni mayúsculas): código (`codigo`, `cuenta`), rubro (`nombre`, `rubro`, `descripcion`, `detalle` y, si «cuenta» ya
  no es el código, `cuenta`), `debe`, `haber`, o una sola `saldo` (positivo = deudor);
- `vista_previa` (recalcular): cada fila contra las cuentas de la empresa de ese momento y las decisiones del usuario. Cada
  fila queda `valida`, `sin_cuenta` (su código no está en el plan: se llevaría como línea sin mapear), `de_grupo` (su
  código es un grupo: elegir otra cuenta u omitirla, si es un subtotal), `duplicada` (otra fila anterior ya llega a esa
  cuenta: se suma solo con `agrupar`), `omitida` (decisión expresa con su motivo) o `error` (importe ilegible, dos lados,
  cuenta inactiva…). No se guarda: dice siempre lo que pasaría si se mapeara ahora;
- `pedidas_del_lote`: lo que `mapear` lleva a las líneas, con todos los errores por fila (`filas.<n>.<campo>`, la de
  encabezados es la 1) y por decisión (`decisiones.<i>.<campo>`).

Sin duplicados: la subida lleva su `clave` (repetida con el mismo archivo devuelve el mismo lote; con otro, 409
`clave_usada`). Solo se importa a una apertura en borrador. El archivo se conserva siempre (el lote no se borra)."""
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction

from core.contabilidad import api, apertura as servicio, inicio_contable, lectura_tabular
from core.contabilidad.modelos_apertura import BORRADOR
from core.contabilidad.models import ImportacionApertura, limpiar_codigo, norma_codigo
from core.importacion.reporte_sri import normalizar_encabezado
from core.tenancy.models import audit

MB = 1024 * 1024
SALDOS, AUXILIARES = 'saldos', 'auxiliares'
VISTA_PREVIA, APLICADO = 'vista_previa', 'aplicado'
VALIDA, SIN_CUENTA, DE_GRUPO, DUPLICADA, OMITIDA, ERROR = 'valida', 'sin_cuenta', 'de_grupo', 'duplicada', 'omitida', 'error'
COLUMNAS = ('codigo', 'rubro', 'debe', 'haber', 'saldo')
# Por orden de preferencia; una columna sirve para un solo dato. «Cuenta» es el código salvo que otra columna ya lo sea.
SINONIMOS = {
    'codigo': ('CODIGO', 'CUENTA'),
    'rubro': ('NOMBRE', 'RUBRO', 'DESCRIPCION', 'DETALLE', 'CUENTA'),
    'debe': ('DEBE', 'SALDO_DEUDOR', 'DEUDOR'),
    'haber': ('HABER', 'SALDO_ACREEDOR', 'ACREEDOR'),
    'saldo': ('SALDO', 'SALDO_FINAL'),
}
MUESTRA = 5
CODIGO_MAX, RUBRO_MAX = 60, 200

# Los textos del lector de C3 que hablan del plan de cuentas, dichos para los saldos de la apertura.
TEXTOS_LECTOR = {
    'archivo_grande': f'El archivo pesa más de {lectura_tabular.MAX_BYTES // MB} MB: deja solo la hoja de los saldos o '
                      'divídelo.',
    'descomprimido': 'El XLSX ocupa demasiado al abrirlo: copia los saldos a un libro nuevo y sube ese.',
    'demasiadas_celdas': 'El archivo tiene demasiadas celdas fuera de la tabla de saldos: copia solo la tabla a un archivo '
                         'nuevo y sube ese.',
    'demasiadas_filas': f'El archivo tiene más de {lectura_tabular.MAX_FILAS:,} filas de saldos: una apertura admite hasta '
                        'esa cantidad de cuentas.'.replace(',', ' '),
    'demasiadas_columnas': 'El archivo tiene demasiadas columnas: deja solo las de los saldos (código, rubro, debe y haber).',
    'demasiado_texto': 'El archivo trae demasiado texto para una tabla de saldos: deja solo sus columnas (código, rubro, '
                       'debe y haber) y súbelo de nuevo.',
    'sin_filas': 'El archivo solo tiene la fila de encabezados: no trae ningún saldo.',
}
TEXTOS = {
    'archivo': 'Elige el archivo de los saldos (CSV o XLSX).',
    'tipo': 'Elige qué se importa: los saldos de la apertura.',
    'tipo_auxiliares': 'La importación del detalle (auxiliares) todavía no está disponible: por ahora se importan los saldos.',
    'clave_usada': 'Esta clave ya se usó para subir otro archivo: vuelve a cargar la página e inténtalo de nuevo.',
    'lote': 'El lote no existe o es de otra apertura.',
    'columnas': 'Envía las columnas como un objeto {codigo, rubro, debe, haber, saldo}.',
    'columna': 'Esa columna no está en el archivo.',
    'columna_repetida': 'Esa columna ya está elegida para otro dato.',
    'faltan_importes': 'Elige qué columna trae el debe y cuál el haber, o la columna del saldo.',
    'importes_dobles': 'Elige el debe y el haber, o una sola columna de saldo: no las dos cosas.',
    'faltan_cuentas': 'Elige qué columna trae el código o el rubro de cada cuenta.',
    'decisiones': 'Envía las decisiones como una lista de {fila, cuenta_id?, omitir?, motivo?, agrupar?}.',
    'decision': 'Cada decisión es un objeto con su fila.',
    'fila': 'Esa fila no está en el archivo.',
    'fila_repetida': 'Ya hay otra decisión para la fila {fila}.',
    'omitir': 'Indica si se omite la fila: verdadero o falso.',
    'agrupar': 'Indica si se agrupa la fila: verdadero o falso.',
    'motivo_omitir': 'Escribe por qué se omite la fila (por ejemplo, «subtotal del grupo»).',
    # de cada fila
    'sobran': 'La fila tiene más celdas que columnas el encabezado: revisa si un texto con el separador va sin comillas.',
    'alterada': 'La hoja de cálculo guardó el importe como fecha: escríbelo como número.',
    'de_grupo': 'La cuenta {codigo} es un grupo: elige una cuenta de movimiento u omite la fila (si es un subtotal) con su '
                'motivo.',
    'duplicada': 'La cuenta {codigo} ya recibe la fila {fila}: marca «agrupar» para sumar ambas.',
    'agrupada_cero': 'Las filas agrupadas en la cuenta {codigo} suman cero: omítelas o corrige la fuente.',
}


# ---------------------------------------------------------------- columnas

def detectar(encabezados):
    """Qué columna trae cada dato, por su encabezado: `{campo: encabezado o None}`. Si hay debe o haber, el saldo no se
    elige (serían dos lecturas del mismo importe)."""
    normales = [normalizar_encabezado(e) for e in encabezados]
    mapeo, usadas = {}, set()
    for campo in COLUMNAS:
        mapeo[campo] = None
        for sinonimo in SINONIMOS[campo]:
            columna = next((i for i, normal in enumerate(normales) if normal == sinonimo and i not in usadas), None)
            if columna is not None:
                mapeo[campo] = encabezados[columna]
                usadas.add(columna)
                break
    if mapeo['debe'] or mapeo['haber']:
        mapeo['saldo'] = None
    return mapeo


def faltan_columnas(mapeo):
    """Los textos de lo que falta elegir para poder leer las filas (lista vacía: nada)."""
    faltan = []
    if mapeo.get('saldo') and (mapeo.get('debe') or mapeo.get('haber')):
        faltan.append(TEXTOS['importes_dobles'])
    elif not (mapeo.get('saldo') or mapeo.get('debe') or mapeo.get('haber')):
        faltan.append(TEXTOS['faltan_importes'])
    if not (mapeo.get('codigo') or mapeo.get('rubro')):
        faltan.append(TEXTOS['faltan_cuentas'])
    return faltan


def _columnas(valor, lote, errores):
    if not isinstance(valor, dict):
        errores.agregar('columnas', TEXTOS['columnas'])
        return None
    mapeo = {}
    for campo in COLUMNAS:
        pedido = valor.get(campo)
        mapeo[campo] = None
        if pedido in (None, ''):
            continue
        if not isinstance(pedido, str) or pedido not in lote.encabezados:
            errores.agregar(f'columnas.{campo}', TEXTOS['columna'])
        elif pedido in mapeo.values():
            errores.agregar(f'columnas.{campo}', TEXTOS['columna_repetida'])
        else:
            mapeo[campo] = pedido
    for texto in faltan_columnas(mapeo):
        errores.agregar('columnas', texto)
    return mapeo


# ---------------------------------------------------------------- decisiones

def _decisiones(valor, lote, cuentas, errores):
    """`{fila: {cuenta_id, omitir, motivo, agrupar, es_resultado_ejercicio, posicion}}` de las decisiones enviadas, con sus
    errores por posición, y `ajenas` (posiciones con una cuenta que no es de la empresa: 404)."""
    if valor is None:
        return {}, {}
    if not isinstance(valor, list):
        errores.agregar('decisiones', TEXTOS['decisiones'])
        return {}, {}
    numeros = {fila['n'] for fila in lote.filas}
    decisiones, ajenas = {}, {}
    for i, enviada in enumerate(valor):
        prefijo = f'decisiones.{i}'
        if not isinstance(enviada, dict):
            errores.agregar(prefijo, TEXTOS['decision'])
            continue
        fila = servicio._entero(enviada.get('fila'))
        if fila is None or fila not in numeros:
            errores.agregar(f'{prefijo}.fila', TEXTOS['fila'])
            continue
        if fila in decisiones:
            errores.agregar(f'{prefijo}.fila', TEXTOS['fila_repetida'].format(fila=fila))
            continue
        cuenta_id = None
        if enviada.get('cuenta_id') not in (None, ''):
            cuenta_id = servicio._entero(enviada.get('cuenta_id'))
            if cuenta_id is None:
                errores.agregar(f'{prefijo}.cuenta_id', servicio.TEXTOS['cuenta_id'])
            elif cuenta_id not in cuentas:
                ajenas[f'{prefijo}.cuenta_id'] = [servicio.TEXTOS['cuenta_no_existe']]
                cuenta_id = None
        omitir = servicio._booleano(enviada, 'omitir', errores, TEXTOS['omitir'], clave=f'{prefijo}.omitir')
        agrupar = servicio._booleano(enviada, 'agrupar', errores, TEXTOS['agrupar'], clave=f'{prefijo}.agrupar')
        es_resultado = servicio._booleano(enviada, 'es_resultado_ejercicio', errores, servicio.TEXTOS['es_resultado'],
                                          clave=f'{prefijo}.es_resultado_ejercicio')
        motivo = servicio._texto(enviada.get('motivo')) or ''
        if omitir and not motivo:
            errores.agregar(f'{prefijo}.motivo', TEXTOS['motivo_omitir'])
        elif len(motivo) > servicio.MOTIVO_MAX:
            errores.agregar(f'{prefijo}.motivo', servicio.TEXTOS['motivo_largo'])
        elif servicio.con_control(motivo):   # se guardaría en el mapeo del lote (en PostgreSQL, un NUL era un 500)
            errores.agregar(f'{prefijo}.motivo', servicio.TEXTOS['caracteres_de_control'])
        decisiones[fila] = {'fila': fila, 'cuenta_id': cuenta_id, 'omitir': omitir, 'motivo': motivo, 'agrupar': agrupar,
                            'es_resultado_ejercicio': es_resultado, 'posicion': i}
    return decisiones, ajenas


def _guardables(decisiones):
    """Las decisiones como se guardan en el lote (sin la posición del envío), por fila."""
    return [{c: d[c] for c in ('fila', 'cuenta_id', 'omitir', 'motivo', 'agrupar', 'es_resultado_ejercicio')}
            for _, d in sorted(decisiones.items())]


# ---------------------------------------------------------------- vista previa

@dataclass
class Fila:
    numero: int
    codigo: str
    rubro: str
    debe: Decimal | None = None
    haber: Decimal | None = None
    cuenta: dict | None = None
    estado: str = VALIDA
    errores: object = field(default_factory=api.Errores)
    decision: dict | None = None
    primera: int | None = None    # en una agrupada o duplicada: la fila que recibió antes la cuenta

    def dict(self):
        cuenta = self.cuenta
        return {'fila': self.numero, 'codigo': self.codigo, 'rubro': self.rubro, 'debe': servicio.importe_texto(self.debe),
                'haber': servicio.importe_texto(self.haber),
                'cuenta': {'id': cuenta['id'], 'codigo': cuenta['codigo'], 'nombre': cuenta['nombre'], 'tipo': cuenta['tipo']}
                if cuenta is not None else None,
                'estado': self.estado, 'errores': [t for textos in self.errores.values() for t in textos]}


def evaluar(lote, mapeo, decisiones, cuentas, no_aplican=()):
    """Las filas del lote revisadas contra `cuentas` (servicio.cuentas_de_la_empresa) con el mapeo y las decisiones dados.
    Sin columnas suficientes, ninguna fila (lo dice `faltan_columnas`). No escribe nada."""
    if faltan_columnas(mapeo):
        return []
    por_norma = {c['codigo_norm']: c for c in cuentas.values()}
    columna = {campo: lote.encabezados.index(mapeo[campo]) if mapeo.get(campo) in lote.encabezados else None
               for campo in COLUMNAS}
    con_saldo = columna['saldo'] is not None
    recibidas, filas = {}, []
    for cruda in lote.filas:
        celdas, alteradas = cruda['c'], set(cruda.get('f', ()))

        def celda(campo):
            return celdas[columna[campo]] if columna[campo] is not None else ''
        n = cruda['n']
        fila = Fila(numero=n, codigo=limpiar_codigo(celda('codigo'))[:CODIGO_MAX], rubro=' '.join(celda('rubro').split()),
                    decision=decisiones.get(n))
        filas.append(fila)
        if fila.decision is not None and fila.decision['omitir']:
            fila.estado = OMITIDA
            continue
        if cruda.get('s'):
            fila.errores.agregar(f'filas.{n}', TEXTOS['sobran'])
        for campo in ('debe', 'haber', 'saldo'):
            if columna[campo] is not None and columna[campo] in alteradas:
                fila.errores.agregar(f'filas.{n}.{campo}', TEXTOS['alterada'])
        if not fila.errores:
            fila.debe, fila.haber = servicio.saldos(celda('debe'), celda('haber'), fila.errores, f'filas.{n}',
                                                    saldo=celda('saldo'), con_saldo=con_saldo)
        elegida = fila.decision['cuenta_id'] if fila.decision is not None else None
        if elegida is not None:
            fila.cuenta = cuentas.get(elegida)
        elif fila.codigo:
            fila.cuenta = por_norma.get(norma_codigo(fila.codigo))
        campo_cuenta = f'decisiones.{fila.decision["posicion"]}.cuenta_id' if elegida is not None else f'filas.{n}.cuenta'
        if fila.cuenta is not None:
            if fila.cuenta['tipo'] != 'movimiento':
                fila.estado = DE_GRUPO
                fila.errores.agregar(campo_cuenta, TEXTOS['de_grupo'].format(codigo=fila.cuenta['codigo']))
                continue
            servicio.comprobar_cuenta(fila.cuenta, campo_cuenta, fila.errores, no_aplican)
        if (fila.decision is not None and fila.decision['es_resultado_ejercicio']
                and (fila.cuenta is None or fila.cuenta['clase'] != 'patrimonio')):
            fila.errores.agregar(f'decisiones.{fila.decision["posicion"]}.es_resultado_ejercicio',
                                 servicio.TEXTOS['resultado_patrimonio'])
        if fila.errores:
            fila.estado = ERROR
            continue
        if fila.cuenta is None:
            fila.estado = SIN_CUENTA
            continue
        primera = recibidas.setdefault(fila.cuenta['id'], n)
        if primera != n:
            fila.primera = primera
            if fila.decision is None or not fila.decision['agrupar']:
                fila.estado = DUPLICADA
                fila.errores.agregar(campo_cuenta, TEXTOS['duplicada'].format(codigo=fila.cuenta['codigo'], fila=primera))
    return filas


def resumen_de(filas, mapeo):
    """Cuántas filas hay en cada estado y la suma de las que llegarían a las líneas (válidas, sin cuenta y duplicadas; los
    grupos se dejan fuera porque suelen ser subtotales). Con algún importe desconocido la suma también lo es (null)."""
    cuenta = {estado: sum(1 for f in filas if f.estado == estado) for estado in (VALIDA, SIN_CUENTA, DE_GRUPO, DUPLICADA,
                                                                                  OMITIDA, ERROR)}
    sumadas = [f for f in filas if f.estado in (VALIDA, SIN_CUENTA, DUPLICADA)]
    desconocido = any(f.debe is None or f.haber is None for f in sumadas)
    debe = None if desconocido else sum((f.debe for f in sumadas), servicio.CERO)
    haber = None if desconocido else sum((f.haber for f in sumadas), servicio.CERO)
    faltan = faltan_columnas(mapeo)
    return {'validas': cuenta[VALIDA], 'sin_cuenta': cuenta[SIN_CUENTA], 'de_grupo': cuenta[DE_GRUPO],
            'duplicadas': cuenta[DUPLICADA], 'con_error': cuenta[ERROR], 'omitidas': cuenta[OMITIDA],
            'debe': servicio.importe_texto(debe), 'haber': servicio.importe_texto(haber),
            'diferencia': servicio.importe_texto(debe - haber) if not desconocido else None,
            'faltan_columnas': faltan}


def _mapeo_guardado(lote):
    mapeo = lote.mapeo or {}
    return mapeo.get('columnas') or {campo: None for campo in COLUMNAS}, {d['fila']: {**d, 'posicion': i}
                                                                             for i, d in enumerate(mapeo.get('decisiones') or [])}


def dict_lote(lote, cuentas=None):
    """El lote como lo devuelve la API, con su vista previa de ahora (contra las cuentas de la empresa de este momento)."""
    columnas, decisiones = _mapeo_guardado(lote)
    filas = evaluar(lote, columnas, decisiones, cuentas if cuentas is not None else servicio.cuentas_de_la_empresa())
    return {'id': lote.pk, 'apertura_id': lote.apertura_id, 'estado': lote.estado, 'tipo': lote.tipo, 'archivo': lote.nombre,
            'tamano': lote.tamano, 'sha256': lote.sha256, 'encabezados': lote.encabezados, 'columnas': columnas,
            'decisiones': _guardables(decisiones),
            # Las primeras filas tal como se leyeron: para elegir las columnas viendo qué trae cada una.
            'muestra': [fila['c'] for fila in lote.filas[:MUESTRA]],
            'filas': [f.dict() for f in filas], 'resumen': resumen_de(filas, columnas),
            'subido_por': lote.creado_por_nombre or None, 'subido_en': lote.creado_en.isoformat(),
            'aplicado_por': lote.aplicado_por_nombre or None,
            'aplicado_en': lote.aplicado_en.isoformat() if lote.aplicado_en is not None else None}


# ---------------------------------------------------------------- el lote

def lote_de(apertura, lote_id, bloqueado=False):
    """El lote de saldos de esa apertura (404 si no existe, es de otra apertura o de otra empresa)."""
    lote_id = servicio._entero(lote_id)
    consulta = ImportacionApertura.objects.select_for_update(of=('self',)) if bloqueado else ImportacionApertura.objects
    lote = consulta.filter(pk=lote_id, apertura=apertura, tipo=SALDOS).first() if lote_id is not None else None
    if lote is None:
        raise api.ErrorApi('no_existe', TEXTOS['lote'], 404)
    return lote


def consultar(request, pk):
    """GET /contabilidad/api/apertura/importar/<lote>/: el lote de la empresa activa con su vista previa recalculada."""
    lote = ImportacionApertura.objects.filter(pk=pk).first() if servicio._entero(pk) is not None else None
    if lote is None:
        raise api.ErrorApi('no_existe', TEXTOS['lote'], 404)
    return lote


def pedidas_del_lote(apertura, lote, datos, cuentas, errores):
    """Lo que `mapear` lleva a las líneas desde el lote: `(pedidas, ajenas, de_grupo, resumen)`. Las columnas y las
    decisiones del envío (si no vienen, las guardadas en el lote) se validan y se evalúan todas las filas; sus errores van
    a `errores` con su fila o su decisión. Las filas válidas que llegan a la misma cuenta (con `agrupar`) se suman en una
    línea, con todas en `filas_origen`; las sin cuenta van cada una a una línea sin mapear."""
    guardadas, decisiones_guardadas = _mapeo_guardado(lote)
    columnas = _columnas(datos['columnas'], lote, errores) if 'columnas' in datos else guardadas
    if 'decisiones' in datos:
        decisiones, ajenas = _decisiones(datos['decisiones'], lote, cuentas, errores)
    else:
        decisiones, ajenas = decisiones_guardadas, {}
    resumen = {'mapeo': {'columnas': columnas, 'decisiones': _guardables(decisiones)}, 'omitidas': 0, 'agrupadas': 0}
    if columnas is None or faltan_columnas(columnas):
        if columnas is not None and 'columnas' not in datos:
            for texto in faltan_columnas(columnas):
                errores.agregar('columnas', texto)
        return [], ajenas, False, resumen
    filas = evaluar(lote, columnas, decisiones, cuentas, servicio.no_aplican_de(apertura))
    de_grupo = False
    for fila in filas:
        for campo, textos in fila.errores.items():
            for texto in textos:
                errores.agregar(campo, texto)
        de_grupo |= fila.estado == DE_GRUPO
    resumen['omitidas'] = sum(1 for f in filas if f.estado == OMITIDA)
    grupos, pedidas = {}, []
    for fila in filas:
        if fila.estado == SIN_CUENTA:
            pedidas.append(_pedida(lote, [fila]))
        elif fila.estado == VALIDA:
            if fila.cuenta['id'] in grupos:
                grupos[fila.cuenta['id']].append(fila)
                resumen['agrupadas'] += 1
            else:
                grupos[fila.cuenta['id']] = [fila]
                pedidas.append(grupos[fila.cuenta['id']])
    resultado = []
    for pedida in pedidas:
        if not isinstance(pedida, list):
            resultado.append(pedida)
            continue
        agrupada = _pedida(lote, pedida, cuenta_id=pedida[0].cuenta['id'])
        if agrupada.debe is not None and agrupada.debe == agrupada.haber == 0:
            errores.agregar(f'filas.{pedida[0].numero}.cuenta', TEXTOS['agrupada_cero'].format(codigo=pedida[0].cuenta['codigo']))
        resultado.append(agrupada)
    return resultado, ajenas, de_grupo, resumen


def _pedida(lote, filas, cuenta_id=None):
    """Una línea pedida desde una o varias filas: el saldo neto (desconocido si alguna lo es) y su procedencia."""
    if any(f.debe is None or f.haber is None for f in filas):
        debe = haber = None
    else:
        neto = sum((f.debe - f.haber for f in filas), servicio.CERO)
        debe, haber = (neto, servicio.CERO) if neto >= 0 else (servicio.CERO, -neto)
    primera = filas[0]
    return servicio.Pedida(
        cuenta_id=cuenta_id, debe=debe, haber=haber, rubro=primera.rubro[:RUBRO_MAX], codigo=primera.codigo,
        es_resultado_ejercicio=any(f.decision is not None and f.decision['es_resultado_ejercicio'] for f in filas),
        lote_id=lote.pk, desde_lote=True,
        filas_origen=[{'fila': f.numero, 'codigo': f.codigo, 'rubro': f.rubro[:RUBRO_MAX],
                       'debe': servicio.importe_texto(f.debe), 'haber': servicio.importe_texto(f.haber)} for f in filas])


# ---------------------------------------------------------------- subir

def _repetido(existente, apertura_id, sha256):
    if existente.sha256 == sha256 and existente.apertura_id == apertura_id:
        return existente, True
    raise api.ErrorApi('clave_usada', TEXTOS['clave_usada'], 409)


def subir(request, pk, archivo, datos):
    """POST /contabilidad/api/apertura/<id>/importar/ (multipart `archivo`, `clave`, `tipo`): lee el archivo y deja el lote
    en vista previa. Devuelve `(lote, repetido)`. No escribe ninguna línea."""
    api.exigir_permiso(request, servicio.PREPARAR)
    clave = api.clave_de(datos)
    errores = api.Errores()
    tipo = datos.get('tipo')
    if tipo == AUXILIARES:   # Parte C (corte 2)
        errores.agregar('tipo', TEXTOS['tipo_auxiliares'])
    elif tipo != SALDOS:
        errores.agregar('tipo', TEXTOS['tipo'])
    if archivo is None:
        errores.agregar('archivo', TEXTOS['archivo'])
        contenido = b''
    elif archivo.size > lectura_tabular.MAX_BYTES:   # antes de leerlo: no se carga en memoria lo que no se va a aceptar
        raise api.ErrorApi('archivo_grande', TEXTOS_LECTOR['archivo_grande'])
    else:
        contenido = archivo.read()
    sha256 = hashlib.sha256(contenido).hexdigest()
    existente = ImportacionApertura.objects.filter(clave=clave).first()
    if existente is not None:
        return _repetido(existente, servicio._entero(pk), sha256)
    guardado = lote = None
    try:
        with transaction.atomic():
            apertura = servicio.obtener(pk, bloqueada=True)
            if apertura.estado != BORRADOR:
                raise servicio.rechazo_de_estado(apertura, [BORRADOR])
            errores.comprobar()
            extension, encabezados, filas = lectura_tabular.leer(contenido, TEXTOS_LECTOR)
            columnas = detectar(encabezados)
            por_id, por_nombre = inicio_contable.autor(request)
            lote = ImportacionApertura(company=request.company, apertura=apertura, tipo=SALDOS,
                                       nombre=_nombre_original(archivo, extension), tamano=len(contenido), sha256=sha256,
                                       encabezados=encabezados, filas=filas, mapeo={'columnas': columnas, 'decisiones': []},
                                       clave=clave, creado_por_id=por_id, creado_por_nombre=por_nombre)
            previa = evaluar(lote, columnas, {}, servicio.cuentas_de_la_empresa())
            lote.resumen = resumen_de(previa, columnas)   # lo que se vio al subirlo; la vista previa se recalcula al leerlo
            lote.archivo.save(f'saldos.{extension}', ContentFile(contenido), save=False)
            guardado = lote.archivo.name
            lote.save()
            servicio.evento(request, apertura, 'importada', detalle={'lote_id': lote.pk, 'nombre': lote.nombre,
                                                                     'sha256': sha256, 'filas': len(filas)})
            audit(request, 'apertura_importada', company=request.company, apertura=apertura.pk, lote=lote.pk,
                  archivo=lote.nombre, sha256=sha256, filas=len(filas))
        return lote, False
    except IntegrityError:
        if guardado:
            lote.archivo.storage.delete(guardado)
        existente = ImportacionApertura.objects.filter(clave=clave).first()
        if existente is None:
            raise
        return _repetido(existente, servicio._entero(pk), sha256)
    except Exception:
        if guardado:   # la transacción se deshizo: el archivo no queda huérfano en el disco
            lote.archivo.storage.delete(guardado)
        raise


def _nombre_original(archivo, extension):
    nombre = ''.join(c for c in str(getattr(archivo, 'name', '') or '') if c.isprintable()).strip()
    return nombre[-255:] or f'saldos.{extension}'
