"""Libro diario (Parte A de contable/bloque-2-especificacion.md): el único módulo que escribe en `Asiento` y `LineaAsiento`
(lo vigila una prueba ast) y quien mantiene `SaldoCuentaMes`.

- `contabilizar(...)` registra un asiento: valida todo antes de escribir nada, y escribe en este orden (el que exigen las
  guardas de core/contabilidad/modelos_libro.py y los disparadores de la migración `libro_inmutable`): el asiento sin
  sellar, sus líneas en un `bulk_create`, el sello, los acumulados por cuenta y mes y el último número del ejercicio.
- `reversar(...)` registra el asiento espejo y marca el original con `reversado_por`/`reversado_en` en una sola sentencia
  (la otra actualización, con el sello, que admite el libro).
- `verificar(anio)` comprueba el libro con consultas agregadas (GET /contabilidad/api/integridad/ y la orden
  `verificar_libro`).

Las dos escrituras exigen el candado del libro (`candado.libro()`): sin él lanzan `candado.SinCandado`, un error de
programación. Con el candado no hay otro escritor del libro de la empresa: el número siguiente sale sin huecos ni
repeticiones y los acumulados no se pisan. Cualquier rechazo es un `ErrorDiario(codigo)` y no deja nada escrito ni consume
número: todo se comprueba antes de escribir, y lo escrito va en un punto de guardado propio.

Precedencia de los rechazos (decisión común 6): primero lo que es un fallo de quien llama (tipo, autor, fecha que no es
una fecha); después la clave ya usada; después el conflicto con otros datos (409: fecha anterior al corte, período o
ejercicio cerrado, hecho ya contabilizado); al final la validación (400: concepto, motivo, origen, líneas, cuadre, fecha
futura).

`diario.py` no audita (decisión común 11): el asiento ya guarda autor, fecha, origen y huella; audita quien tiene la
petición (confirmar la apertura, el cobro, el asiento manual…), con el asiento en su detalle.

Fechas (decisión común 15). Un asiento ordinario va en fecha ≥ `contabilidad_desde` (si no, `anterior_al_corte`) y en un
período abierto. Las únicas excepciones, que no pasan por la comprobación del período (los meses ≤ corte no se gestionan):
la `apertura`, que lleva exactamente `fecha_corte`; el `cierre` del ejercicio del corte cuando el corte es 31/12 (origen
`('ejercicio', año del corte, 'cierre_resultados')`), también en `fecha_corte`; y el reverso de cualquiera de los dos
fechado hasta el corte. Ningún asiento con fecha futura.

Huella (`huella`): SHA-256 del contenido canónico `v1` del asiento, un JSON con claves ordenadas y sin espacios:
`{"v": 1, "empresa", "anio", "numero", "fecha", "tipo", "origen": [tipo, id, evento], "lineas": [[orden, cuenta_id, debe,
haber, tercero_tipo, tercero_id, documento_tipo, documento_id], …]}`, importes con dos decimales y líneas por su orden.
No hay cadena de huellas entre asientos: la numeración sin huecos, la huella de cada uno y los disparadores ya detectan un
borrado o una alteración, y una cadena se rompería con cualquier corrección documentada."""
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Count, DecimalField, Max, Min, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.contabilidad import api, candado, lotes, periodos
from core.contabilidad.modelos_apertura import CONFIRMADA
from core.contabilidad.modelos_libro import (CERRADO, TIPOS_ASIENTO, TIPOS_CON_MOTIVO, TIPOS_CON_ORIGEN, TIPOS_TERCERO,
                                             escritura_interna)
from core.contabilidad.models import Apertura, Asiento, Cuenta, EjercicioContable, LineaAsiento, SaldoCuentaMes

TIPOS = tuple(tipo for tipo, _ in TIPOS_ASIENTO)
TERCEROS = tuple(tipo for tipo, _ in TIPOS_TERCERO if tipo)
REVERSO, APERTURA, CIERRE = 'reverso', 'apertura', 'cierre'
# Asientos cuyas líneas se acumulan además en columnas propias de SaldoCuentaMes (y las de sus reversos, en las mismas).
CON_COLUMNA_PROPIA = (APERTURA, CIERRE)
ORIGEN_CIERRE_DEL_CORTE = ('ejercicio', 'cierre_resultados')   # con el año del corte como id
CERO, CENTAVO = Decimal('0'), Decimal('0.01')
IMPORTE_MAX = Decimal(10) ** 12   # lo que cabe en un importe (14, 2)
TOTAL_MAX = Decimal(10) ** 14     # y en un total o un acumulado (16, 2)
ANIO_MIN, ANIO_MAX = 2000, 2100   # CHECK ejercicio_anio_valido
VERSION_HUELLA = 1
DETALLE_MAX = 100                 # entradas de `detalle` por comprobación en `verificar`

TEXTOS = {
    'tipo': 'Tipo de asiento no reconocido.',
    'reverso_directo': 'Un reverso se registra con diario.reversar, que deja marcado el asiento original.',
    'autor': 'Falta quién registra el asiento.',
    'fecha': 'Escribe una fecha válida (AAAA-MM-DD) entre los años 2000 y 2100.',
    'fecha_futura': 'La fecha del asiento no puede ser futura.',
    'fecha_de_corte': 'Este asiento va en la fecha de corte de la empresa ({fecha:%d/%m/%Y}).',
    'anterior_al_corte': 'La fecha es anterior al inicio de la contabilidad ({desde:%d/%m/%Y}): lo anterior al corte va en '
                         'la apertura.',
    'periodo_cerrado': 'El período {periodo} está cerrado: usa una fecha de un período abierto.',
    'ejercicio_cerrado': 'El ejercicio {anio} está cerrado.',
    'concepto': 'Escribe el concepto del asiento (hasta 300 caracteres).',
    'motivo': 'Indica el motivo (hasta 300 caracteres).',
    'origen': 'Falta el hecho del que sale el asiento: su tipo, su id y su evento.',
    'lineas_insuficientes': 'Un asiento tiene al menos dos líneas.',
    'importe': 'Revisa los importes de las líneas marcadas.',
    'cuenta_no_existe': 'Revisa las cuentas de las líneas marcadas: alguna no existe o es de otra empresa.',
    'cuenta_de_grupo': 'Revisa las cuentas de las líneas marcadas: una cuenta de grupo no recibe movimientos.',
    'cuenta_inactiva': 'Revisa las cuentas de las líneas marcadas: alguna está desactivada.',
    'linea': 'Revisa los datos de las líneas marcadas.',
    'asiento_descuadrado': 'El asiento no cuadra: el debe suma {debe} y el haber {haber}.',
    'clave': 'La clave del envío no es válida.',
    'clave_usada': 'Esta clave ya se usó para otro asiento.',
    'origen_ya_contabilizado': 'Ese hecho ya tiene su asiento vigente: para cambiarlo hay que reversarlo primero.',
    'apertura_ya_contabilizada': 'La empresa ya tiene un asiento de apertura vigente.',
    'no_existe': 'El asiento no existe o es de otra empresa.',
    'ya_reversado': 'Este asiento ya está reversado.',
    'no_reversable': 'Un reverso no se reversa: si hace falta, el asiento se registra de nuevo.',
    'fecha_del_reverso': 'El reverso no puede ser anterior al asiento que reversa ({fecha:%d/%m/%Y}).',
}
# Por línea (`lineas.N.campo`)
LINEA = {
    'importe_un_lado': 'Escribe un importe mayor que cero en el debe o en el haber, no en los dos.',
    'importe_formato': 'Escribe el importe con dos decimales como máximo.',
    'importe_negativo': 'El importe no puede ser negativo.',
    'importe_grande': 'El importe es demasiado grande.',
    'cuenta_no_existe': 'La cuenta no existe o es de otra empresa.',
    'cuenta_de_grupo': 'Es una cuenta de grupo: no recibe movimientos.',
    'cuenta_inactiva': 'La cuenta está desactivada.',
    'linea': 'Cada línea es un objeto con su cuenta y su importe.',
    'concepto': 'El concepto de la línea admite hasta 200 caracteres.',
    'tercero': 'El tercero lleva su tipo (cliente, proveedor u otro), y su identificación y su nombre caben en 20 y 200 '
               'caracteres.',
    'documento': 'El documento lleva su tipo (hasta 30 caracteres) y su número cabe en 60.',
    'componente': 'El componente admite hasta 40 caracteres y el concepto tributario hasta 30.',
    'total': 'El total del asiento es demasiado grande.',
}
CONFLICTOS = {'clave_usada', 'fecha_de_corte', 'anterior_al_corte', 'periodo_cerrado', 'ejercicio_cerrado',
              'origen_ya_contabilizado', 'apertura_ya_contabilizada', 'ya_reversado', 'no_reversable'}
# Si hay errores en varias líneas, el código de la respuesta es el primero de esta lista (los demás van en `errores`).
PRECEDENCIA_DE_LINEAS = ('importe', 'cuenta_no_existe', 'cuenta_de_grupo', 'cuenta_inactiva', 'linea')


class ErrorDiario(api.ErrorApi):
    """Rechazo del diario con su código estable. Es un `ErrorApi`: una vista que lo deja salir responde su JSON (409 los
    conflictos con otros datos, 404 un asiento que no existe, 400 lo demás). `detalle` viaja en el cuerpo."""

    def __init__(self, codigo, texto=None, errores=None, **detalle):
        estado = 404 if codigo == 'no_existe' else 409 if codigo in CONFLICTOS else 400
        super().__init__(codigo, texto or TEXTOS[codigo], estado, errores, **detalle)
        self.detalle = detalle


# ---------------------------------------------------------------- forma de las respuestas

def importe(valor):
    """Importe como lo muestra el contrato: texto con dos decimales; desconocido = None, nunca "0.00"."""
    return None if valor is None else f'{Decimal(valor):.2f}'


def referencia(asiento):
    """`{"id", "numero": "2025-000001"}`."""
    return {'id': asiento.pk, 'numero': asiento.numero_completo}


def resumen(asiento):
    """`{"id", "numero", "fecha", "debe", "haber"}`: como lo citan la apertura y los demás recursos."""
    return {**referencia(asiento), 'fecha': asiento.fecha.isoformat(), 'debe': importe(asiento.total_debe),
            'haber': importe(asiento.total_haber)}


# ---------------------------------------------------------------- huella canónica v1

def huella(company_id, anio, numero, fecha, tipo, origen_tipo, origen_id, evento, lineas):
    """SHA-256 del contenido canónico v1. `lineas`: `[(orden, cuenta_id, debe, haber, tercero_tipo, tercero_id,
    documento_tipo, documento_id)]` en cualquier orden (se ordenan por `orden`)."""
    contenido = {
        'v': VERSION_HUELLA, 'empresa': company_id, 'anio': anio, 'numero': numero, 'fecha': fecha.isoformat(), 'tipo': tipo,
        'origen': [origen_tipo, origen_id, evento],
        'lineas': [[orden, cuenta_id, importe(debe), importe(haber), tercero_tipo, tercero_id, documento_tipo, documento_id]
                   for orden, cuenta_id, debe, haber, tercero_tipo, tercero_id, documento_tipo, documento_id
                   in sorted(lineas, key=lambda linea: linea[0])],
    }
    texto = json.dumps(contenido, separators=(',', ':'), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(texto.encode('ascii')).hexdigest()


def _clave_de_huella(linea):
    return (linea['orden'], linea['cuenta_id'], linea['debe'], linea['haber'], linea['tercero_tipo'], linea['tercero_id'],
            linea['documento_tipo'], linea['documento_id'])


# ---------------------------------------------------------------- validación

def _importe(valor):
    """`(Decimal, None)` con dos decimales o `(None, falla)`. Vacío = 0 (el lado que no se usa). Un float no se acepta: ya
    perdió los centavos exactos."""
    if valor is None or valor == '':
        return CERO, None
    if isinstance(valor, (bool, float)):
        return None, 'importe_formato'
    try:
        numero = valor if isinstance(valor, Decimal) else Decimal(str(valor).strip())
    except (InvalidOperation, ValueError):
        return None, 'importe_formato'
    if not numero.is_finite():
        return None, 'importe_formato'
    if numero < 0:
        return None, 'importe_negativo'
    if numero >= IMPORTE_MAX:
        return None, 'importe_grande'
    if numero != numero.quantize(CENTAVO):
        return None, 'importe_formato'
    return numero.quantize(CENTAVO), None


def _entero(valor):
    """Un id (entero > 0) o None si no lo es."""
    if isinstance(valor, bool) or not isinstance(valor, int):
        return None
    return valor if 0 < valor < 2 ** 63 else None


def _texto(valor, maximo):
    """El texto sin espacios sobrantes, o None si no es texto o no cabe."""
    if valor is None:
        return ''
    if not isinstance(valor, str):
        return None
    valor = ' '.join(valor.split())
    return valor if len(valor) <= maximo else None


def _tercero(datos):
    """`(tipo, id, identificacion, nombre)` o None si no vale. Sin tercero: `('', None, '', '')`. Su existencia no se
    comprueba aquí: la valida quien arma la línea desde una fila de la operación, y un reverso copia la del original
    aunque esa fila ya no exista (decisión común 16)."""
    if datos is None:
        return '', None, '', ''
    if not isinstance(datos, dict) or datos.get('tipo') not in TERCEROS:
        return None
    identificador = datos.get('id')
    if identificador is not None and _entero(identificador) is None:
        return None
    identificacion, nombre = _texto(datos.get('identificacion'), 20), _texto(datos.get('nombre'), 200)
    if identificacion is None or nombre is None:
        return None
    return datos['tipo'], identificador, identificacion, nombre


def _documento(datos):
    """`(tipo, id, numero)` o None si no vale. Sin documento: `('', None, '')`."""
    if datos is None:
        return '', None, ''
    if not isinstance(datos, dict):
        return None
    tipo, numero, identificador = _texto(datos.get('tipo'), 30), _texto(datos.get('numero'), 60), datos.get('id')
    if not tipo or numero is None or (identificador is not None and _entero(identificador) is None):
        return None
    return tipo, identificador, numero


def _lineas(lineas, admite_inactivas):
    """Las líneas limpias (`[{orden, cuenta_id, debe, haber, concepto, tercero_*, documento_*, componente,
    concepto_tributario}]`) o el ErrorDiario con todos los errores por posición (`lineas.N.campo`, base 0)."""
    if not isinstance(lineas, (list, tuple)) or len(lineas) < 2:
        raise ErrorDiario('lineas_insuficientes', errores={'lineas': [TEXTOS['lineas_insuficientes']]})
    errores, codigos, limpias, posiciones = api.Errores(), set(), [], []

    def falla(posicion, campo, codigo, texto):
        errores.agregar(f'lineas.{posicion}.{campo}' if campo else f'lineas.{posicion}', texto)
        codigos.add(codigo)

    for posicion, linea in enumerate(lineas):
        if not isinstance(linea, dict):
            falla(posicion, '', 'linea', LINEA['linea'])
            continue
        debe, falla_debe = _importe(linea.get('debe'))
        haber, falla_haber = _importe(linea.get('haber'))
        for campo, motivo in (('debe', falla_debe), ('haber', falla_haber)):
            if motivo:
                falla(posicion, campo, 'importe', LINEA[motivo])
        if not falla_debe and not falla_haber and (debe > 0) == (haber > 0):
            falla(posicion, 'debe', 'importe', LINEA['importe_un_lado'])
        cuenta_id = _entero(linea.get('cuenta_id'))
        if cuenta_id is None:
            falla(posicion, 'cuenta_id', 'cuenta_no_existe', LINEA['cuenta_no_existe'])
        concepto = _texto(linea.get('concepto'), 200)
        if concepto is None:
            falla(posicion, 'concepto', 'linea', LINEA['concepto'])
        tercero, documento = _tercero(linea.get('tercero')), _documento(linea.get('documento'))
        if tercero is None:
            falla(posicion, 'tercero', 'linea', LINEA['tercero'])
        if documento is None:
            falla(posicion, 'documento', 'linea', LINEA['documento'])
        componente, tributario = _texto(linea.get('componente'), 40), _texto(linea.get('concepto_tributario'), 30)
        if componente is None or tributario is None:
            falla(posicion, 'componente', 'linea', LINEA['componente'])
        posiciones.append(posicion)
        limpias.append({
            'orden': posicion + 1, 'cuenta_id': cuenta_id, 'debe': debe, 'haber': haber, 'concepto': concepto or '',
            'tercero_tipo': (tercero or ('',))[0], 'tercero_id': tercero[1] if tercero else None,
            'tercero_identificacion': tercero[2] if tercero else '', 'tercero_nombre': tercero[3] if tercero else '',
            'documento_tipo': (documento or ('',))[0], 'documento_id': documento[1] if documento else None,
            'documento_numero': documento[2] if documento else '', 'componente': componente or '',
            'concepto_tributario': tributario or ''})

    # Las cuentas, en una consulta: `objects` solo ve las de la empresa activa (otra empresa = no existe).
    pedidas = {linea['cuenta_id'] for linea in limpias if linea['cuenta_id'] is not None}
    cuentas = {c['id']: c for c in Cuenta.objects.filter(pk__in=pedidas).values('id', 'tipo', 'activa')}
    for posicion, linea in zip(posiciones, limpias):
        if linea['cuenta_id'] is None:
            continue
        cuenta = cuentas.get(linea['cuenta_id'])
        if cuenta is None:
            falla(posicion, 'cuenta_id', 'cuenta_no_existe', LINEA['cuenta_no_existe'])
        elif cuenta['tipo'] != 'movimiento':
            falla(posicion, 'cuenta_id', 'cuenta_de_grupo', LINEA['cuenta_de_grupo'])
        elif not cuenta['activa'] and not admite_inactivas:
            falla(posicion, 'cuenta_id', 'cuenta_inactiva', LINEA['cuenta_inactiva'])
    if errores:
        codigo = next(c for c in PRECEDENCIA_DE_LINEAS if c in codigos)
        raise ErrorDiario(codigo, errores=dict(errores))
    debe, haber = sum(linea['debe'] for linea in limpias), sum(linea['haber'] for linea in limpias)
    if debe >= TOTAL_MAX or haber >= TOTAL_MAX:
        raise ErrorDiario('importe', errores={'lineas': [LINEA['total']]})
    if debe != haber:
        raise ErrorDiario('asiento_descuadrado', TEXTOS['asiento_descuadrado'].format(debe=importe(debe), haber=importe(haber)),
                          debe=importe(debe), haber=importe(haber), diferencia=importe(abs(debe - haber)))
    return limpias, debe


def _origen(origen):
    """`(tipo, id, evento, numero, fecha)` de `(tipo, id, evento[, numero[, fecha]])` o de un dict con esas claves; None
    si no vale. Sin origen: `('', None, '', '', None)`."""
    if origen is None:
        return '', None, '', '', None
    if isinstance(origen, dict):
        origen = (origen.get('tipo'), origen.get('id'), origen.get('evento'), origen.get('numero'), origen.get('fecha'))
    if not isinstance(origen, (list, tuple)) or not 3 <= len(origen) <= 5:
        return None
    tipo, identificador, evento, numero, fecha = (*origen, None, None)[:5]
    tipo, evento, numero = _texto(tipo, 30), _texto(evento, 30), _texto(numero, 60)
    if not tipo or not evento or numero is None:
        return None
    if identificador is not None and _entero(identificador) is None:
        return None
    if fecha is not None and (not isinstance(fecha, date) or isinstance(fecha, datetime)):
        return None
    return tipo, identificador, evento, numero, fecha


def _es_cierre_del_corte(inicio, fecha, origen):
    corte = inicio.fecha_corte
    return ((corte.month, corte.day) == (12, 31) and fecha == corte
            and (origen[0], origen[1], origen[2]) == (ORIGEN_CIERRE_DEL_CORTE[0], corte.year, ORIGEN_CIERRE_DEL_CORTE[1]))


def _reversa_lo_anterior_al_corte(inicio, fecha, reversa_de):
    """El reverso de la apertura o del cierre del ejercicio del corte, fechado hasta el corte: tampoco es ordinario."""
    return (reversa_de is not None and reversa_de.tipo in CON_COLUMNA_PROPIA and reversa_de.fecha < inicio.contabilidad_desde
            and fecha <= inicio.fecha_corte)


def _exigir_fecha(inicio, tipo, fecha, origen, reversa_de):
    """La fecha frente al corte y a los períodos (409). La fecha futura es validación y va después."""
    if tipo == APERTURA:
        if fecha != inicio.fecha_corte:
            raise ErrorDiario('fecha_de_corte', TEXTOS['fecha_de_corte'].format(fecha=inicio.fecha_corte),
                              fecha_corte=inicio.fecha_corte.isoformat())
        return
    if tipo == CIERRE and _es_cierre_del_corte(inicio, fecha, origen):
        return
    if tipo == REVERSO and _reversa_lo_anterior_al_corte(inicio, fecha, reversa_de):
        return
    if fecha < inicio.contabilidad_desde:
        raise ErrorDiario('anterior_al_corte', TEXTOS['anterior_al_corte'].format(desde=inicio.contabilidad_desde),
                          fecha_corte=inicio.fecha_corte.isoformat(), contabilidad_desde=inicio.contabilidad_desde.isoformat())
    periodos.exigir_abierto(fecha)


def _ejercicio_cerrado(anio):
    if EjercicioContable.objects.filter(anio=anio, estado=CERRADO).exists():
        raise ErrorDiario('ejercicio_cerrado', TEXTOS['ejercicio_cerrado'].format(anio=anio), ejercicios=[anio])


def _vigente_del_origen(origen_tipo, origen_id, evento):
    return (Asiento.objects.filter(origen_tipo=origen_tipo, origen_id=origen_id, evento=evento, reversado_por__isnull=True,
                                   reversa_de__isnull=True).first())


# ---------------------------------------------------------------- escritura

def _bloquear_ejercicio(anio):
    """El ejercicio del año, bloqueado (paso 6 del orden de bloqueos); si no existe, se crea (patrón de carrera de
    `reglas_de`: con el candado no debería haber carrera, pero la restricción única es la que decide)."""
    ejercicio = EjercicioContable.objects.select_for_update(of=('self',)).filter(anio=anio).first()
    if ejercicio is not None:
        return ejercicio
    try:
        with transaction.atomic():
            ejercicio = EjercicioContable(anio=anio)
            ejercicio.save()
            return ejercicio
    except IntegrityError:
        return EjercicioContable.objects.select_for_update(of=('self',)).get(anio=anio)


def _acumular(company_id, anio, mes, lineas, columna):
    """Suma las líneas en `SaldoCuentaMes` de su cuenta y mes (paso 8 del orden de bloqueos: las filas se leen bloqueadas,
    por cuenta), creando las que falten. `columna` ('apertura', 'cierre' o None): además en sus columnas propias."""
    por_cuenta = defaultdict(lambda: [CERO, CERO])
    for linea in lineas:
        por_cuenta[linea['cuenta_id']][0] += linea['debe']
        por_cuenta[linea['cuenta_id']][1] += linea['haber']
    existentes = {s.cuenta_id: s for s in SaldoCuentaMes.objects.select_for_update(of=('self',)).filter(
        cuenta_id__in=list(por_cuenta), anio=anio, mes=mes).order_by('cuenta_id')}
    campos = ['debe', 'haber'] + ([f'{columna}_debe', f'{columna}_haber'] if columna else [])
    nuevos, cambiados = [], []
    for cuenta_id in sorted(por_cuenta):
        debe, haber = por_cuenta[cuenta_id]
        saldo = existentes.get(cuenta_id)
        if saldo is None:
            saldo = SaldoCuentaMes(company_id=company_id, cuenta_id=cuenta_id, anio=anio, mes=mes, debe=CERO, haber=CERO,
                                   apertura_debe=CERO, apertura_haber=CERO, cierre_debe=CERO, cierre_haber=CERO)
            nuevos.append(saldo)
        else:
            cambiados.append(saldo)
        for campo, suma in zip(campos, (debe, haber) * 2):
            setattr(saldo, campo, getattr(saldo, campo) + suma)
    if nuevos:
        SaldoCuentaMes.objects.bulk_create(nuevos, batch_size=lotes.TAMANO_LOTE)
    if cambiados:
        SaldoCuentaMes.objects.bulk_update(cambiados, campos, batch_size=lotes.TAMANO_LOTE)


def _registrar(*, tipo, fecha, concepto, lineas, origen, autor, motivo, clave, reversa_de):
    inicio = candado.exigir()
    # 1. Lo que es un fallo de quien llama.
    if tipo not in TIPOS:
        raise ErrorDiario('tipo')
    autor_id, autor_nombre = (autor if isinstance(autor, (list, tuple)) and len(autor) == 2 else (None, None))
    autor_nombre = _texto(autor_nombre, 150)
    if not autor_nombre or (autor_id is not None and _entero(autor_id) is None):
        raise ErrorDiario('autor')
    if not isinstance(fecha, date) or isinstance(fecha, datetime) or not ANIO_MIN <= fecha.year <= ANIO_MAX:
        raise ErrorDiario('fecha')
    if clave is not None and (not isinstance(clave, str) or not 0 < len(clave) <= 40):
        raise ErrorDiario('clave')
    limpio = _origen(origen)

    # 2. La clave ya usada.
    if clave is not None:
        con_clave = Asiento.objects.filter(clave=clave).first()
        if con_clave is not None:
            raise ErrorDiario('clave_usada', asiento=referencia(con_clave))

    # 3. Conflictos con otros datos (409).
    if limpio is not None:
        _exigir_fecha(inicio, tipo, fecha, limpio, reversa_de)
    elif tipo not in TIPOS_CON_ORIGEN:   # sin un origen válido, las excepciones de fecha no aplican
        _exigir_fecha(inicio, tipo, fecha, ('', None, ''), reversa_de)
    _ejercicio_cerrado(fecha.year)
    if limpio is not None and limpio[1] is not None and tipo != REVERSO:
        vigente = _vigente_del_origen(*limpio[:3])
        if vigente is not None:
            raise ErrorDiario('origen_ya_contabilizado', asiento=referencia(vigente))
    if tipo == APERTURA:
        vigente = Asiento.objects.filter(tipo=APERTURA, reversado_por__isnull=True).first()
        if vigente is not None:
            raise ErrorDiario('apertura_ya_contabilizada', asiento=referencia(vigente))
    if tipo == REVERSO and reversa_de.tipo == REVERSO:
        raise ErrorDiario('no_reversable', asiento=referencia(reversa_de))

    # 4. Validación (400).
    concepto = _texto(concepto, 300)
    if not concepto:
        raise ErrorDiario('concepto')
    motivo = _texto(motivo, 300)
    if motivo is None or (tipo in TIPOS_CON_MOTIVO and not motivo):
        raise ErrorDiario('motivo')
    if limpio is None or (tipo in TIPOS_CON_ORIGEN and (not limpio[0] or limpio[1] is None)):
        raise ErrorDiario('origen')
    lineas, total = _lineas(lineas, admite_inactivas=tipo == REVERSO)
    if fecha > timezone.localdate():
        raise ErrorDiario('fecha_futura')

    # 5. Escritura, en un punto de guardado propio: si algo falla, nada queda y el número no se consume.
    origen_tipo, origen_id, evento, origen_numero, origen_fecha = limpio
    columna = tipo if tipo in CON_COLUMNA_PROPIA else (reversa_de.tipo if tipo == REVERSO and reversa_de.tipo
                                                       in CON_COLUMNA_PROPIA else None)
    with transaction.atomic():
        ejercicio = _bloquear_ejercicio(fecha.year)
        numero = ejercicio.ultimo_numero + 1
        asiento = Asiento(
            company_id=inicio.company_id, ejercicio=ejercicio, anio=fecha.year, mes=fecha.month, numero=numero, fecha=fecha,
            tipo=tipo, concepto=concepto, origen_tipo=origen_tipo, origen_id=origen_id, evento=evento,
            origen_numero=origen_numero, origen_fecha=origen_fecha, reversa_de=reversa_de, total_debe=total, total_haber=total,
            lineas_n=len(lineas), sellado=False, motivo=motivo, clave=clave, creado_por_id=autor_id,
            creado_por_nombre=autor_nombre, creado_en=timezone.now(),
            huella=huella(inicio.company_id, fecha.year, numero, fecha, tipo, origen_tipo, origen_id, evento,
                          [_clave_de_huella(linea) for linea in lineas]))
        asiento.save()
        # Las cuentas ya se validaron con `objects` (empresa activa); `company_id` va fijado en cada fila.
        LineaAsiento.objects.bulk_create(
            [LineaAsiento(company_id=inicio.company_id, asiento_id=asiento.pk, fecha=fecha, anio=fecha.year, mes=fecha.month,
                          **linea) for linea in lineas], batch_size=lotes.TAMANO_LOTE)
        with escritura_interna():
            Asiento.objects.filter(pk=asiento.pk).update(sellado=True)
        asiento.sellado = True
        _acumular(inicio.company_id, fecha.year, fecha.month, lineas, columna)
        EjercicioContable.objects.filter(pk=ejercicio.pk).update(ultimo_numero=numero)
    return asiento


def contabilizar(*, tipo, fecha, concepto, lineas, origen=None, autor, motivo='', clave=None, reversa_de=None):
    """Registra un asiento y lo devuelve. Exige el candado.

    - `tipo`: `apertura | origen | manual | ajuste | cierre | historico` (el reverso es de `reversar`).
    - `lineas`: `[{"cuenta_id", "debe": Decimal, "haber": Decimal, "concepto"?, "tercero"?: {"tipo", "id", "identificacion",
      "nombre"}, "documento"?: {"tipo", "id", "numero"}, "componente"?, "concepto_tributario"?}]`, al menos dos, cada una
      con un solo lado mayor que cero y dos decimales; Σ debe = Σ haber. Cuentas de movimiento, activas, de la empresa.
    - `origen`: `(tipo, id, evento[, numero[, fecha]])`, obligatorio en `apertura`, `origen` y `cierre`.
    - `autor`: `(id del usuario, nombre de usuario)`; `motivo`, obligatorio en `manual` y `ajuste`.
    - `clave`: la del envío que lo pide (UNIQUE por empresa). Repetida → 409 `clave_usada` con el asiento: quien quiera
      devolver «repetido» lo busca antes (`por_clave`).

    Cualquier rechazo es `ErrorDiario` sin nada escrito."""
    candado.exigir()
    if tipo == REVERSO or reversa_de is not None:   # un reverso suelto dejaría el original sin marcar
        raise ErrorDiario('tipo', TEXTOS['reverso_directo'])
    return _registrar(tipo=tipo, fecha=fecha, concepto=concepto, lineas=lineas, origen=origen, autor=autor, motivo=motivo,
                      clave=clave, reversa_de=reversa_de)


def por_clave(clave):
    """El asiento registrado con esa clave, o None."""
    return Asiento.objects.filter(clave=clave).first() if clave else None


def _espejo(original):
    """Las líneas del original con los lados cambiados (todo lo demás igual)."""
    campos = ('cuenta_id', 'debe', 'haber', 'concepto', 'tercero_tipo', 'tercero_id', 'tercero_identificacion', 'tercero_nombre',
              'documento_tipo', 'documento_id', 'documento_numero', 'componente', 'concepto_tributario')
    lineas = []
    for linea in LineaAsiento.objects.filter(asiento_id=original.pk).order_by('orden').values(*campos):
        lineas.append({
            'cuenta_id': linea['cuenta_id'], 'debe': linea['haber'], 'haber': linea['debe'], 'concepto': linea['concepto'],
            'tercero': {'tipo': linea['tercero_tipo'], 'id': linea['tercero_id'], 'identificacion': linea['tercero_identificacion'],
                        'nombre': linea['tercero_nombre']} if linea['tercero_tipo'] else None,
            'documento': {'tipo': linea['documento_tipo'], 'id': linea['documento_id'], 'numero': linea['documento_numero']}
            if linea['documento_tipo'] else None,
            'componente': linea['componente'], 'concepto_tributario': linea['concepto_tributario']})
    return lineas


def reversar(asiento_id, *, fecha=None, motivo, autor, clave=None):
    """Reversa un asiento y devuelve `(reverso, repetido)`. Exige el candado.

    Bloquea el original (paso 5 del orden de bloqueos). Ya reversado con la misma `clave` → el mismo reverso y `repetido`;
    con otra → 409 `ya_reversado`. Un reverso → 409 `no_reversable`. `fecha` (decisión común 15): sin ella, la del
    original, que vale si su período sigue abierto; si no, la que indique quien reversa: no anterior al original, en un
    período abierto y no futura. El reverso lleva las líneas espejo y el mismo origen; las cuentas hoy desactivadas se
    admiten. Después, en una sola sentencia, el original recibe `reversado_por` y `reversado_en`."""
    candado.exigir()
    original = Asiento.objects.select_for_update(of=('self',)).filter(pk=asiento_id).first()
    if original is None:
        raise ErrorDiario('no_existe')
    if clave is not None:
        con_clave = Asiento.objects.filter(clave=clave).first()
        if con_clave is not None:
            if con_clave.reversa_de_id == original.pk:
                return con_clave, True
            raise ErrorDiario('clave_usada', asiento=referencia(con_clave))
    if original.reversado_por_id is not None:
        raise ErrorDiario('ya_reversado', reverso=referencia(Asiento.objects.get(pk=original.reversado_por_id)))
    if original.tipo == REVERSO:
        raise ErrorDiario('no_reversable', asiento=referencia(original))
    fecha = original.fecha if fecha is None else fecha
    if isinstance(fecha, date) and not isinstance(fecha, datetime) and fecha < original.fecha:
        raise ErrorDiario('fecha_del_reverso', TEXTOS['fecha_del_reverso'].format(fecha=original.fecha))
    origen = ((original.origen_tipo, original.origen_id, original.evento, original.origen_numero, original.origen_fecha)
              if original.origen_tipo else None)
    with transaction.atomic():
        reverso = _registrar(tipo=REVERSO, fecha=fecha, concepto=f'Reverso del asiento {original.numero_completo}: '
                             f'{original.concepto}'[:300], lineas=_espejo(original), origen=origen, autor=autor, motivo=motivo,
                             clave=clave, reversa_de=original)
        with escritura_interna():
            Asiento.objects.filter(pk=original.pk).update(reversado_por=reverso, reversado_en=timezone.now())
    return reverso, False


# ---------------------------------------------------------------- verificación

def _comprobacion(codigo, detalle):
    return {'codigo': codigo, 'ok': not detalle, 'detalle': detalle[:DETALLE_MAX]}


def _decimal(expresion):
    return Coalesce(expresion, Value(CERO), output_field=DecimalField(max_digits=16, decimal_places=2))


def _cuadre(asientos):
    """Cada asiento: sus líneas suman sus totales, el debe iguala al haber y son tantas como `lineas_n`. Una consulta
    agregada por asiento; la comparación se hace aquí y no en la base, porque SQLite suma los importes como coma flotante
    (lo que llega ya está redondeado a dos decimales)."""
    filas = (asientos.annotate(n=Count('lineas'), d=_decimal(Sum('lineas__debe')), h=_decimal(Sum('lineas__haber')))
             .order_by('numero').values('id', 'anio', 'numero', 'total_debe', 'total_haber', 'lineas_n', 'n', 'd', 'h'))
    malos = [m for m in filas.iterator(chunk_size=2000)
             if (m['n'], m['d'], m['h']) != (m['lineas_n'], m['total_debe'], m['total_haber']) or m['total_debe'] != m['total_haber']]
    return _comprobacion('cuadre', [{'asiento': {'id': m['id'], 'numero': f'{m["anio"]}-{m["numero"]:06d}'},
                                     'totales': {'debe': importe(m['total_debe']), 'haber': importe(m['total_haber'])},
                                     'lineas': {'n': m['n'], 'esperadas': m['lineas_n'], 'debe': importe(m['d']),
                                                'haber': importe(m['h'])}} for m in malos[:DETALLE_MAX]])


def _numeracion(anio, asientos):
    """Del 1 al último número del ejercicio, sin huecos ni repetidos."""
    datos = asientos.aggregate(n=Count('id'), distintos=Count('numero', distinct=True), minimo=Min('numero'), maximo=Max('numero'))
    ultimo = EjercicioContable.objects.filter(anio=anio).values_list('ultimo_numero', flat=True).first() or 0
    n, maximo = datos['n'], datos['maximo'] or 0
    if n == datos['distintos'] == maximo == ultimo and (n == 0 or datos['minimo'] == 1):
        return _comprobacion('numeracion', [])
    numeros = list(asientos.order_by('numero').values_list('numero', flat=True))
    vistos, repetidos = set(), []
    for numero in numeros:
        if numero in vistos:
            repetidos.append(numero)
        vistos.add(numero)
    faltantes = [numero for numero in range(1, max(maximo, ultimo) + 1) if numero not in vistos]
    return _comprobacion('numeracion', [{'ultimo_numero': ultimo, 'maximo': maximo, 'asientos': n,
                                         'faltantes': faltantes[:DETALLE_MAX], 'repetidos': repetidos[:DETALLE_MAX]}])


def _huellas(asientos):
    """La huella guardada de cada asiento es la de su contenido de hoy (dos consultas: asientos y líneas)."""
    cabeceras = {a['id']: a for a in asientos.values('id', 'company_id', 'anio', 'numero', 'fecha', 'tipo', 'origen_tipo',
                                                      'origen_id', 'evento', 'huella')}
    lineas = defaultdict(list)
    for linea in (LineaAsiento.objects.filter(asiento_id__in=asientos.values('id')).order_by('asiento_id', 'orden')
                  .values_list('asiento_id', 'orden', 'cuenta_id', 'debe', 'haber', 'tercero_tipo', 'tercero_id',
                               'documento_tipo', 'documento_id').iterator(chunk_size=2000)):
        lineas[linea[0]].append(linea[1:])
    malas = []
    for pk, a in sorted(cabeceras.items(), key=lambda par: par[1]['numero']):
        calculada = huella(a['company_id'], a['anio'], a['numero'], a['fecha'], a['tipo'], a['origen_tipo'], a['origen_id'],
                           a['evento'], lineas.get(pk, []))
        if calculada != a['huella']:
            malas.append({'asiento': {'id': pk, 'numero': f'{a["anio"]}-{a["numero"]:06d}'}, 'guardada': a['huella'],
                          'calculada': calculada})
    return _comprobacion('huellas', malas)


def _diferencias(codigo, de_lineas, de_acumulados, anio):
    """Compara `{(cuenta, mes): (debe, haber)}` calculado de las líneas con lo guardado en SaldoCuentaMes."""
    malas = []
    for clave in sorted(set(de_lineas) | set(de_acumulados)):
        esperado, guardado = de_lineas.get(clave, (CERO, CERO)), de_acumulados.get(clave, (CERO, CERO))
        if tuple(esperado) != tuple(guardado):
            malas.append({'cuenta_id': clave[0], 'mes': f'{anio}-{clave[1]:02d}',
                          'lineas': {'debe': importe(esperado[0]), 'haber': importe(esperado[1])},
                          'acumulado': {'debe': importe(guardado[0]), 'haber': importe(guardado[1])}})
    return _comprobacion(codigo, malas)


def _acumulados(anio):
    """SaldoCuentaMes (debe y haber) = Σ de las líneas por cuenta y mes."""
    de_lineas = {(f['cuenta_id'], f['mes']): (f['d'], f['h']) for f in LineaAsiento.objects.filter(anio=anio).values(
        'cuenta_id', 'mes').annotate(d=_decimal(Sum('debe')), h=_decimal(Sum('haber'))).order_by()}
    guardados = {(f['cuenta_id'], f['mes']): (f['debe'], f['haber']) for f in SaldoCuentaMes.objects.filter(anio=anio).values(
        'cuenta_id', 'mes', 'debe', 'haber')}
    # Una fila de acumulados en cero no contradice a «sin líneas».
    guardados = {k: v for k, v in guardados.items() if k in de_lineas or v != (CERO, CERO)}
    return _diferencias('acumulados', de_lineas, guardados, anio)


def _acumulados_por_tipo(anio):
    """Las columnas de apertura y de cierre = Σ de las líneas de esos asientos y de sus reversos."""
    malas = []
    for columna in CON_COLUMNA_PROPIA:
        del_tipo = Q(asiento__tipo=columna) | Q(asiento__tipo=REVERSO, asiento__reversa_de__tipo=columna)
        de_lineas = {(f['cuenta_id'], f['mes']): (f['d'], f['h']) for f in LineaAsiento.objects.filter(del_tipo, anio=anio)
                     .values('cuenta_id', 'mes').annotate(d=_decimal(Sum('debe')), h=_decimal(Sum('haber'))).order_by()}
        guardados = {(f['cuenta_id'], f['mes']): (f[f'{columna}_debe'], f[f'{columna}_haber'])
                     for f in SaldoCuentaMes.objects.filter(anio=anio).values('cuenta_id', 'mes', f'{columna}_debe',
                                                                                f'{columna}_haber')}
        guardados = {k: v for k, v in guardados.items() if k in de_lineas or v != (CERO, CERO)}
        malas += [{'columna': columna, **mala} for mala in _diferencias('', de_lineas, guardados, anio)['detalle']]
    return _comprobacion('acumulados_por_tipo', malas)


def _apertura_unica():
    """Como mucho un asiento de apertura vigente en la empresa, y es el de la apertura confirmada (ninguno si no hay o si
    se confirmó sin saldos)."""
    vigentes = list(Asiento.objects.filter(tipo=APERTURA, reversado_por__isnull=True).order_by('id').values_list('id', flat=True))
    confirmada = Apertura.objects.filter(estado=CONFIRMADA).values_list('asiento_id', flat=True).first()
    esperados = [confirmada] if confirmada is not None else []
    if vigentes == esperados:
        return _comprobacion('apertura_unica', [])
    return _comprobacion('apertura_unica', [{'vigentes': vigentes, 'de_la_apertura_confirmada': confirmada}])


def _sellados(asientos):
    abiertos = asientos.filter(sellado=False).order_by('numero').values('id', 'anio', 'numero')
    return _comprobacion('sellados', [{'asiento': {'id': a['id'], 'numero': f'{a["anio"]}-{a["numero"]:06d}'}}
                                      for a in abiertos[:DETALLE_MAX]])


def verificar(anio):
    """`{"anio", "asientos": n, "comprobaciones": [{"codigo", "ok", "detalle": […]}]}` del ejercicio, en la empresa activa:
    `cuadre`, `numeracion`, `huellas`, `acumulados`, `acumulados_por_tipo`, `apertura_unica` (de toda la empresa) y
    `sellados`. Solo lee; `detalle` lleva como mucho DETALLE_MAX entradas por comprobación."""
    asientos = Asiento.objects.filter(anio=anio)
    return {'anio': anio, 'asientos': asientos.count(),
            'comprobaciones': [_cuadre(asientos), _numeracion(anio, asientos), _huellas(asientos), _acumulados(anio),
                               _acumulados_por_tipo(anio), _apertura_unica(), _sellados(asientos)]}
