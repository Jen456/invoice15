"""Cobertura de la contabilidad de la empresa (Parte B, regla 2, y Parte C, regla 8, de contable/bloque-2-especificacion.md):
qué está cubierto por la apertura y qué no, por ámbito. Se calcula, no se guarda (salvo lo declarado por mes, que es
`CoberturaPeriodo`). Estados: `pendiente | parcial | conciliada`, `no_aplica` solo por declaración expresa y, por mes,
además `sin_cobertura`. No es licencia ni autorización fiscal.

En este corte (Partes A y B) solo lo que GET /contabilidad/api/apertura/ necesita, sin auxiliares propios:

- `contabilidad`: `pendiente` sin inicio (`inicio_sin_configurar`) o sin apertura confirmada (`apertura_sin_confirmar`; en
  historial, `saldo_anterior_sin_confirmar`): sin saldo anterior no se supone cero. Esas tres causas salen del registro de
  provisionalidad (reportes.provisionalidad, decisión común 17), con su código y su texto: la cobertura no mantiene una
  lista paralela. `parcial` si se confirmó con detalle incompleto aceptado; si no, `conciliada`;
- clientes, proveedores, inventario, bancos y activos: `no_aplica` si la apertura lo declara (`ambitos_no_aplican`, con su
  nota). Sin declaración y sin ninguna línea con ese detalle, `pendiente` con `sin_cuenta_declarada`: `Cuenta.auxiliar`
  solo existe si alguien lo marca y no marcarla no prueba que no haya cartera. Con líneas: `pendiente` mientras su saldo
  no tenga detalle, `parcial` con detalle incompleto (o que excede la cuenta, o con importes pendientes) y `conciliada`
  cuando el detalle explica el saldo de cada línea. Los vínculos rotos, los que no concilian y los saldos iniciales del
  kardex los añade el corte 2 (Parte C) aquí mismo;
- `tributario`: `saldos_anteriores` es la suma de los auxiliares tributarios vigentes o `null` si no hay ninguno (nunca
  `"0.00"`); `conciliada` la decide el bloque 5;
- `periodos`: lo declarado en cada mes del año en curso desde `contabilidad_desde` (`sin_cobertura` si no hay fila). Sus
  hechos calculados (`cobertura.hechos`) son del corte 2.

Se mira la apertura vigente (confirmada) y, si no la hay, la que está en preparación: así quien prepara ve lo que su
borrador cubriría, mientras `contabilidad` sigue `pendiente` hasta confirmar. Consultas: una de líneas, una de auxiliares
por línea y una de los meses declarados."""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Sum

from core.contabilidad import reportes
from core.contabilidad.modelos_apertura import AMBITOS, VIGENTE
from core.contabilidad.models import AuxiliarApertura, CoberturaPeriodo, LineaApertura

PENDIENTE, PARCIAL, CONCILIADA, NO_APLICA, SIN_COBERTURA = 'pendiente', 'parcial', 'conciliada', 'no_aplica', 'sin_cobertura'
CERO = Decimal('0')
# Ámbito de la apertura que puede declararse «no aplica» → el `detalle` (Cuenta.auxiliar) de sus líneas.
DETALLE_DE = {'clientes': 'cliente', 'proveedores': 'proveedor', 'inventario': 'inventario', 'bancos': 'banco',
              'activos': 'activo', 'tributario': 'tributario'}
AMBITOS_DECLARABLES = tuple(DETALLE_DE)
NOMBRE = {'clientes': 'clientes', 'proveedores': 'proveedores', 'inventario': 'inventario', 'bancos': 'bancos',
          'activos': 'activos fijos', 'tributario': 'saldos tributarios'}
AMBITOS_POR_MES = tuple(ambito for ambito, _ in AMBITOS)

# Causas de la cobertura de contabilidad que son las del registro de provisionalidad (mismo código y mismo texto).
DEL_REGISTRO = ('inicio_sin_configurar', 'apertura_sin_confirmar', 'saldo_anterior_sin_confirmar')
TEXTOS = {
    **{codigo: reportes.CAUSAS[codigo].texto for codigo in DEL_REGISTRO},
    'detalle_incompleto_aceptado': 'La apertura se confirmó aceptando el detalle incompleto de {n} cuenta(s).',
    'sin_cuenta_declarada': 'Ninguna cuenta de la apertura está declarada como de {nombre}.',
    'sin_detalle': 'El saldo de {nombre} en la apertura todavía no tiene su detalle.',
    'detalle_incompleto': 'El detalle de {nombre} no explica todo el saldo de {n} cuenta(s).',
    'detalle_excede': 'El detalle de {nombre} suma más que el saldo de {n} cuenta(s).',
    'importe_pendiente': 'El saldo de {n} cuenta(s) de {nombre} está pendiente.',
    'tributario_sin_saldos': 'No hay saldos tributarios anteriores registrados: sus arrastres quedan sin dato.',
    'tributario_por_revisar': 'Los saldos tributarios anteriores están registrados; su uso en el 104 se revisa en la '
                              'preparación tributaria.',
}


def _causa(codigo, cantidad=None, **datos):
    texto = TEXTOS[codigo].format(**datos)
    causa = {'codigo': codigo, 'texto': texto}
    if cantidad is not None:
        causa['cantidad'] = cantidad
    return causa


def _ambito(estado, causas, **extra):
    return {'estado': estado, 'causas': [c['texto'] for c in causas], 'causas_detalle': causas, **extra}


def _importe(valor):
    return f'{valor:.2f}' if valor is not None else None


def importe_de(debe, haber):
    """El saldo de una línea (su único lado mayor que cero), o None si es desconocido."""
    if debe is None or haber is None:
        return None
    return debe if debe > 0 else haber


def _lineas_con_detalle(apertura):
    """Por detalle: las líneas (no retiradas) de la apertura con su saldo y lo detallado de cada una."""
    if apertura is None:
        return {}
    lineas = list(LineaApertura.objects.filter(apertura=apertura, retirada=False).exclude(detalle='')
                  .values('id', 'detalle', 'debe', 'haber', 'incompleto_aceptado'))
    detallado = {fila['linea']: fila for fila in AuxiliarApertura.objects.filter(apertura=apertura, estado=VIGENTE)
                 .values('linea').annotate(total=Sum('saldo_inicial'), filas=Count('id')).order_by()}
    por_detalle = defaultdict(list)
    for linea in lineas:
        aux = detallado.get(linea['id'], {})
        por_detalle[linea['detalle']].append((importe_de(linea['debe'], linea['haber']), aux.get('total') or CERO,
                                              aux.get('filas', 0)))
    return por_detalle


def _de_detalle(ambito, lineas):
    """Estado de un ámbito con detalle a partir de sus líneas `[(importe | None, detallado, filas)]`."""
    nombre = NOMBRE[ambito]
    if not lineas:
        return _ambito(PENDIENTE, [_causa('sin_cuenta_declarada', nombre=nombre)], cuenta=None, detallado=None, filas=0)
    pendientes = sum(1 for importe, _, _ in lineas if importe is None)
    excede = sum(1 for importe, a, _ in lineas if importe is not None and a > importe)
    incompletas = sum(1 for importe, a, _ in lineas if importe is not None and a < importe)
    conocido = sum((importe for importe, _, _ in lineas if importe is not None), CERO)
    detallado = sum((a for _, a, _ in lineas), CERO)
    filas = sum(f for _, _, f in lineas)
    causas = []
    if pendientes:
        causas.append(_causa('importe_pendiente', pendientes, n=pendientes, nombre=nombre))
    if not detallado:
        causas.append(_causa('sin_detalle', len(lineas), nombre=nombre))
        estado = PENDIENTE
    else:
        if incompletas:
            causas.append(_causa('detalle_incompleto', incompletas, n=incompletas, nombre=nombre))
        if excede:
            causas.append(_causa('detalle_excede', excede, n=excede, nombre=nombre))
        estado = PARCIAL if causas else CONCILIADA
    # `cuenta` es desconocida si el saldo de alguna línea lo es: una suma parcial no se presenta como el saldo.
    return _ambito(estado, causas, cuenta=None if pendientes else _importe(conocido), detallado=_importe(detallado),
                   filas=filas)


def _contabilidad(inicio, vigente, aceptadas):
    """La cobertura de lo anterior al corte: el rango que termina en la fecha de corte, con las causas del registro de
    provisionalidad que hablan del inicio y de la apertura (las demás, como `motor_pendiente`, son de lo posterior al corte
    y van en los períodos y en cada reporte)."""
    hasta = inicio.fecha_corte if inicio is not None else None
    _, _, causas = reportes.provisionalidad('cobertura', None, hasta, solo=DEL_REGISTRO, inicio=inicio, apertura=vigente)
    if causas or vigente is None:
        return _ambito(PENDIENTE, causas)
    if aceptadas:
        return _ambito(PARCIAL, [_causa('detalle_incompleto_aceptado', aceptadas, n=aceptadas)])
    return _ambito(CONCILIADA, [])


def _periodos(inicio, hoy):
    """Los meses del año en curso desde `contabilidad_desde`, con lo declarado de cada ámbito o `sin_cobertura`."""
    if inicio is None or inicio.contabilidad_desde > hoy:
        return []
    desde = inicio.contabilidad_desde.month if inicio.contabilidad_desde.year == hoy.year else 1
    declarados = {(c.mes, c.ambito): c for c in CoberturaPeriodo.objects.filter(anio=hoy.year, mes__gte=desde)}
    periodos = []
    for mes in range(desde, hoy.month + 1):
        ambitos = {}
        for ambito in AMBITOS_POR_MES:
            fila = declarados.get((mes, ambito))
            ambitos[ambito] = {'estado': fila.estado if fila is not None else SIN_COBERTURA,
                               'fuente_tipo': fila.fuente_tipo if fila is not None else None,
                               'declarado_por': fila.declarado_por_nombre or None if fila is not None else None,
                               'declarado_en': fila.declarado_en.isoformat() if fila is not None else None}
        periodos.append({'mes': f'{hoy.year}-{mes:02d}', 'ambitos': ambitos})
    return periodos


def vinculos_rotos(apertura_id):
    """Ids de los auxiliares vigentes de la apertura enlazados a una cuenta por cobrar o por pagar, o a un documento
    importado, que ya no existe (Parte C, regla 4: el borrado de la operación no toca la contabilidad y el vínculo queda
    roto, visible). Una consulta por tipo de vínculo, y ninguna si la apertura no tiene auxiliares vinculados."""
    from core.importacion.models import DocumentoImportado
    from core.pos.models import CtasCollect, DebtsPay
    vigentes = AuxiliarApertura.objects.filter(apertura_id=apertura_id, estado=VIGENTE)
    rotos = set()
    for campo, modelo in (('cxc_id', CtasCollect), ('cxp_id', DebtsPay), ('documento_importado_id', DocumentoImportado)):
        rotos.update(vigentes.filter(**{f'{campo}__isnull': False}).exclude(**{f'{campo}__in': modelo.objects.values('pk')})
                     .values_list('id', flat=True))
    return sorted(rotos)


def de_la_empresa(inicio, vigente, en_preparacion, hoy, base=None):
    """`cobertura` de GET /contabilidad/api/apertura/ (forma de la especificación, Parte B). `base`: la apertura cuyos
    ámbitos se miran (validar la pasa: es la que se valida); por defecto, la vigente o, si no la hay, la que está en
    preparación."""
    base = base or vigente or en_preparacion
    no_aplican = {d['ambito'] for d in (base.ambitos_no_aplican if base is not None else []) if isinstance(d, dict)}
    por_detalle = _lineas_con_detalle(base)
    aceptadas = (LineaApertura.objects.filter(apertura=vigente, retirada=False, incompleto_aceptado=True).count()
                 if vigente is not None else 0)

    def ambito(nombre):
        if nombre in no_aplican:
            return _ambito(NO_APLICA, [], cuenta=None, detallado=None, filas=0)
        return _de_detalle(nombre, por_detalle.get(DETALLE_DE[nombre], []))

    clientes, proveedores = ambito('clientes'), ambito('proveedores')
    cartera_causas = clientes['causas_detalle'] + proveedores['causas_detalle']
    estados = {clientes['estado'], proveedores['estado']} - {NO_APLICA}
    cartera_estado = (NO_APLICA if not estados else PENDIENTE if PENDIENTE in estados
                      else PARCIAL if PARCIAL in estados else CONCILIADA)

    def cartera_de(datos):
        return {'estado': datos['estado'], 'cuenta': datos['cuenta'], 'detallado': datos['detallado'],
                'documentos': datos['filas']}

    tributario = AuxiliarApertura.objects.filter(apertura=base, naturaleza='tributario', estado=VIGENTE).aggregate(
        total=Sum('saldo_inicial'))['total'] if base is not None and 'tributario' not in no_aplican else None
    if 'tributario' in no_aplican:
        tributario_ambito = _ambito(NO_APLICA, [], saldos_anteriores=None)
    elif tributario is None:
        tributario_ambito = _ambito(PENDIENTE, [_causa('tributario_sin_saldos')], saldos_anteriores=None)
    else:
        tributario_ambito = _ambito(PARCIAL, [_causa('tributario_por_revisar')], saldos_anteriores=_importe(tributario))
    return {
        'contabilidad': _contabilidad(inicio, vigente, aceptadas),
        'cartera': {**_ambito(cartera_estado, cartera_causas), 'clientes': cartera_de(clientes),
                    'proveedores': cartera_de(proveedores)},
        'inventario': ambito('inventario'),
        'bancos': ambito('bancos'),
        'activos': ambito('activos'),
        'tributario': tributario_ambito,
        'periodos': _periodos(inicio, hoy),
    }
