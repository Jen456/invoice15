"""Libros mensuales: ventas, compras, retenciones efectuadas y retenciones recibidas (entrega B).

Reglas (PLAN-PROFORMAS-BANCOS-CONTABILIDAD.md §2 y §3.6, NORMA-CONTABLE-TRIBUTARIA-2026-10.md):
- Solo comprobantes electrónicos AUTORIZADOS en PRODUCCIÓN (ambiente 2), por fecha de emisión (la de registro si no la
  tienen). Los de PRUEBAS y los que el SRI no autorizó no entran: se cuentan aparte en `excluidos`, para contrastar.
- Las compras (documentos de terceros) entran por su fecha de REGISTRO, la «fechaRegistro» del ATS (el DIMM no admite
  registros a más de un año de la emisión: Etapa 2, compras.cat.PLAZO_ATS_DIAS).
- Cada fila lleva su documento (id y enlace) y su estado. Lo marcado «Anulado en el SRI» se lista con ese estado y NO suma.
  Las notas de crédito restan (signo −1) y las de débito suman: es el signo que usan los reportes de la aplicación; el
  tratamiento en cada casillero del 104 se decide en la etapa del formulario, con el contador.
- Bases e IVA por tarifa con la misma agrupación que el XML autorizado (impuestos_por_tarifa); en compras, la de
  compras.resumen_por_tarifa: las compras antiguas sin tarifa van aparte («sin tarifa»), sin IVA calculado (no se recalculan).
- Importes Decimal a 2 decimales; cada total es la suma exacta de las filas que cuentan.
- Nada de esto es una declaración ni la presenta: es el detalle con el que el contador prepara el 104, el 103 y el ATS.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Q

from core.pos.choices import NOMBRE_TARIFA_IVA, PORCENTAJE_IVA

CERO = Decimal('0.00')
PRODUCCION = 2
AUTORIZADOS = ('authorized', 'authorized_and_sent_by_email')
LIBROS = OrderedDict([
    ('ventas', 'Libro de ventas'),
    ('compras', 'Libro de compras'),
    ('retenciones_efectuadas', 'Retenciones efectuadas'),
    ('retenciones_recibidas', 'Retenciones recibidas'),
])
# Tarifas en columnas fijas (orden del RIDE); las antiguas o poco usadas aparecen solo si hay importes en el mes.
TARIFAS_FIJAS = ('4', '5', '0', '6', '7')
TARIFAS_OCASIONALES = ('2', '3', '10', '8')
NOMBRES_TARIFA = {**NOMBRE_TARIFA_IVA, '8': 'IVA diferenciado', '6': 'no objeto de IVA', '7': 'exento de IVA'}
IMPUESTOS = {'1': 'Renta', '2': 'IVA'}


def _d(valor):
    return (Decimal(str(valor)) if valor is not None else CERO).quantize(Decimal('0.01'))


def siguiente_mes(inicio):
    return date(inicio.year + (inicio.month == 12), inicio.month % 12 + 1, 1)


def _en_mes(inicio, campo, respaldo=None):
    """Q del mes por `campo` y, si está vacío, por `respaldo`."""
    fin = siguiente_mes(inicio)
    filtro = Q(**{f'{campo}__gte': inicio, f'{campo}__lt': fin})
    if respaldo:
        filtro |= Q(**{f'{campo}__isnull': True, f'{respaldo}__gte': inicio, f'{respaldo}__lt': fin})
    return filtro


def _fecha(*valores):
    for valor in valores:
        if valor:
            return valor.isoformat() if hasattr(valor, 'isoformat') else str(valor)
    return ''


def codigo_de_tarifa(porcentaje):
    """Código de porcentaje (tabla 17) de una tarifa de IVA en %, para los documentos que guardan la tarifa y no el código."""
    porcentaje = Decimal(str(porcentaje or 0))
    if porcentaje == 0:
        return '0'
    for codigo, valor in PORCENTAJE_IVA.items():
        if valor == porcentaje and codigo not in ('6', '7'):
            return codigo
    return '8'


@dataclass
class Libro:
    clave: str
    mes: date
    filas: list = field(default_factory=list)
    excluidos: dict = field(default_factory=dict)
    advertencias: list = field(default_factory=list)

    @property
    def nombre(self):
        return LIBROS[self.clave]


# ---------------------------------------------------------------- filas con bases por tarifa

def _fila_tarifas(fila, grupos, signo=1):
    """Pone en la fila `bases`/`ivas` por código desde [{codigo, base, valor}] y los totales sin y con impuestos."""
    bases, ivas = {}, {}
    for g in grupos:
        codigo = g['codigo'] or 'sin_tarifa'
        bases[codigo] = bases.get(codigo, CERO) + _d(g['base'])
        if g.get('valor') is not None and (codigo not in ('0', '6', '7', 'sin_tarifa')):
            ivas[codigo] = ivas.get(codigo, CERO) + _d(g['valor'])
    fila.update(bases=bases, ivas=ivas, base_total=sum(bases.values(), CERO), iva_total=sum(ivas.values(), CERO), signo=signo)
    return fila


def _cliente(venta):
    cliente = venta.client
    return {'identificacion': cliente.dni, 'tipo_identificacion': cliente.get_identification_type_display(),
            'nombre': cliente.user.names if cliente.user_id else ''}


def libro_ventas(inicio):
    """Facturas (01), notas de crédito (04) y notas de débito (05) autorizadas en producción, por fecha de emisión."""
    from core.comprobantes.models import NotaDebito
    from core.pos.models import CreditNote, Sale
    libro = Libro('ventas', inicio)
    mes = _en_mes(inicio, 'emission_date', 'date_joined')

    def excluir(consulta, nombre):
        fuera = consulta.filter(mes).exclude(environment_type=PRODUCCION, status__in=AUTORIZADOS)
        pruebas = fuera.exclude(environment_type=PRODUCCION).count()
        sin_autorizar = fuera.filter(environment_type=PRODUCCION).count()
        if pruebas or sin_autorizar:
            libro.excluidos[nombre] = {'pruebas': pruebas, 'sin_autorizar': sin_autorizar}

    facturas = Sale.objects.select_related('client__user', 'receipt').filter(receipt__voucher_type='01')
    excluir(facturas, 'facturas')
    for venta in facturas.filter(mes, environment_type=PRODUCCION, status__in=AUTORIZADOS).order_by('emission_date', 'date_joined', 'id'):
        anulada = venta.anulado_sri_fecha is not None
        fila = {'id': venta.pk, 'tipo': 'factura', 'tipo_nombre': 'Factura', 'numero': venta.voucher_number_full,
                'fecha': _fecha(venta.emission_date, venta.date_joined), 'clave_acceso': venta.access_code or '', **_cliente(venta),
                'condicion': venta.get_payment_type_display(), 'forma_pago': venta.get_payment_method_display(),
                'documento_modificado': '', 'estado': 'anulado' if anulada else 'autorizado',
                'estado_nombre': 'Anulado en el SRI' if anulada else 'Autorizado', 'cuenta': not anulada,
                'total': _d(venta.total), 'url': f'/pos/sale/admin/print/a4/{venta.pk}/'}
        libro.filas.append(_fila_tarifas(fila, venta.impuestos_por_tarifa()))
    notas = CreditNote.objects.select_related('sale__client__user', 'receipt')
    excluir(notas, 'notas_credito')
    for nota in notas.filter(mes, environment_type=PRODUCCION, status__in=AUTORIZADOS).order_by('emission_date', 'date_joined', 'id'):
        anulada = nota.anulado_sri_fecha is not None
        fila = {'id': nota.pk, 'tipo': 'nota_credito', 'tipo_nombre': 'Nota de crédito', 'numero': nota.voucher_number_full,
                'fecha': _fecha(nota.emission_date, nota.date_joined), 'clave_acceso': nota.access_code or '', **_cliente(nota.sale),
                'condicion': '', 'forma_pago': '', 'documento_modificado': nota.sale.voucher_number_full,
                'estado': 'anulado' if anulada else 'autorizado', 'estado_nombre': 'Anulado en el SRI' if anulada else 'Autorizado',
                'cuenta': not anulada, 'total': _d(nota.total), 'url': '/pos/credit/note/admin/'}
        libro.filas.append(_fila_tarifas(fila, nota.impuestos_por_tarifa(), signo=-1))
    debitos = NotaDebito.objects.select_related('sale')
    excluir(debitos, 'notas_debito')
    for nota in debitos.filter(mes, environment_type=PRODUCCION, status__in=AUTORIZADOS).order_by('emission_date', 'date_joined', 'id'):
        anulada = nota.anulado_sri_fecha is not None
        codigo = codigo_de_tarifa(nota.tarifa_iva)
        fila = {'id': nota.pk, 'tipo': 'nota_debito', 'tipo_nombre': 'Nota de débito', 'numero': nota.voucher_number_full,
                'fecha': _fecha(nota.emission_date, nota.date_joined), 'clave_acceso': nota.access_code or '',
                'identificacion': nota.identificacion, 'tipo_identificacion': nota.get_tipo_identificacion_display()
                if hasattr(nota, 'get_tipo_identificacion_display') else nota.tipo_identificacion, 'nombre': nota.razon_social,
                'condicion': '', 'forma_pago': '', 'documento_modificado': nota.num_doc_modificado,
                'estado': 'anulado' if anulada else 'autorizado', 'estado_nombre': 'Anulado en el SRI' if anulada else 'Autorizado',
                'cuenta': not anulada, 'total': _d(nota.valor_total), 'url': '/comprobantes/notas-debito/'}
        libro.filas.append(_fila_tarifas(fila, [{'codigo': codigo, 'base': nota.total_sin_impuestos, 'valor': nota.valor_iva}]))
    libro.filas.sort(key=lambda f: (f['fecha'], f['tipo'], f['numero']))
    return libro


def libro_compras(inicio):
    """Compras REGISTRADAS en el mes (fecha de registro, la «fechaRegistro» del ATS), de todas sus clases de comprobante; las
    notas de crédito del proveedor restan."""
    from core.pos.compras import resumen_por_tarifa
    from core.pos.models import Purchase
    libro = Libro('compras', inicio)
    compras = (Purchase.objects.select_related('provider').prefetch_related('purchasedetail_set', 'retenciones', 'liquidaciones')
               .filter(_en_mes(inicio, 'date_joined')).order_by('date_joined', 'fecha_emision', 'id'))
    incompletas = sin_tarifa = 0
    for compra in compras:
        grupos = resumen_por_tarifa(list(compra.purchasedetail_set.all()))
        if not grupos:   # compra antigua sin líneas: su subtotal va «sin tarifa», sin IVA calculado (no se recalcula)
            grupos = [{'codigo': '', 'base': compra.subtotal, 'valor': None}]
        retenciones = [r.voucher_number_full for r in compra.retenciones.all()
                       if r.environment_type == PRODUCCION and r.status in AUTORIZADOS and r.anulado_sri_fecha is None]
        liquidaciones = [li.voucher_number_full for li in compra.liquidaciones.all()
                         if li.environment_type == PRODUCCION and li.status in AUTORIZADOS and li.anulado_sri_fecha is None]
        total = compra.total if compra.total is not None else compra.subtotal
        fila = {'id': compra.pk, 'tipo': compra.tipo_comprobante or '', 'tipo_nombre': compra.get_tipo_comprobante_display() or 'Sin tipo',
                'numero': compra.numero_comprobante, 'fecha': _fecha(compra.fecha_emision, compra.date_joined),
                'fecha_registro': _fecha(compra.date_joined), 'autorizacion': compra.autorizacion,
                'identificacion': compra.provider.ruc, 'nombre': compra.provider.name,
                'sustento': compra.get_cod_sustento_display() if compra.cod_sustento else '',
                'cod_sustento': compra.cod_sustento or '',
                'parte_relacionada': {True: 'Sí', False: 'No'}.get(compra.parte_relacionada, ''),
                'forma_pago': compra.get_forma_pago_display() if compra.forma_pago else '',
                'documento_modificado': compra.num_doc_modificado, 'retenciones': ', '.join(retenciones),
                'liquidacion': ', '.join(liquidaciones), 'ice': _d(compra.total_ice), 'total': _d(total),
                'datos_incompletos': bool(compra.datos_incompletos), 'origen': compra.get_origen_display(),
                'estado': 'incompleta' if compra.datos_incompletos else 'completa',
                'estado_nombre': 'Datos por completar' if compra.datos_incompletos else 'Completa', 'cuenta': True,
                'url': f'/pos/purchase/complete/{compra.pk}/'}
        _fila_tarifas(fila, grupos, signo=compra.signo)
        if fila['datos_incompletos']:
            incompletas += 1
        if 'sin_tarifa' in fila['bases']:
            sin_tarifa += 1
        libro.filas.append(fila)
    if incompletas:
        libro.advertencias.append({'codigo': 'compras_incompletas', 'texto': f'{incompletas} compras tienen datos por completar '
                                   '(sustento, forma de pago, parte relacionada o comprobante): revísalas antes de declarar.'})
    if sin_tarifa:
        libro.advertencias.append({'codigo': 'compras_sin_tarifa', 'texto': f'{sin_tarifa} compras antiguas no tienen la tarifa de IVA '
                                   'de sus líneas: su base va en «sin tarifa» y su IVA no se calcula (no se recalculan).'})
    return libro


def _filas_retencion(libro, comprobante, detalles, comun, cuenta):
    for d in detalles:
        libro.filas.append({**comun, 'detalle_id': d.pk, 'impuesto': IMPUESTOS.get(d.impuesto, d.impuesto), 'impuesto_id': d.impuesto,
                            'codigo': d.codigo, 'concepto': d.concepto, 'base': _d(d.base_imponible),
                            'porcentaje': Decimal(str(d.porcentaje)).quantize(Decimal('0.01')), 'valor': _d(d.valor_retenido),
                            'cuenta': cuenta, 'signo': 1})


def libro_retenciones_efectuadas(inicio):
    """Comprobantes de retención emitidos por la empresa (autorizados en producción), una fila por impuesto retenido."""
    from core.comprobantes.models import Retencion
    libro = Libro('retenciones_efectuadas', inicio)
    mes = _en_mes(inicio, 'emission_date', 'date_joined')
    todas = Retencion.objects.filter(mes)
    fuera = todas.exclude(environment_type=PRODUCCION, status__in=AUTORIZADOS)
    pruebas, sin_autorizar = fuera.exclude(environment_type=PRODUCCION).count(), fuera.filter(environment_type=PRODUCCION).count()
    if pruebas or sin_autorizar:
        libro.excluidos['retenciones'] = {'pruebas': pruebas, 'sin_autorizar': sin_autorizar}
    for retencion in (todas.filter(environment_type=PRODUCCION, status__in=AUTORIZADOS).prefetch_related('detalles')
                      .order_by('emission_date', 'date_joined', 'id')):
        anulada = retencion.anulado_sri_fecha is not None
        comun = {'id': retencion.pk, 'numero': retencion.voucher_number_full, 'fecha': _fecha(retencion.emission_date, retencion.date_joined),
                 'clave_acceso': retencion.access_code or '', 'identificacion': retencion.identificacion, 'nombre': retencion.razon_social,
                 'documento_sustento': f'{retencion.cod_doc_sustento} {retencion.num_doc_sustento}'.strip(),
                 'fecha_sustento': _fecha(retencion.fecha_doc_sustento), 'estado': 'anulado' if anulada else 'autorizado',
                 'estado_nombre': 'Anulado en el SRI' if anulada else 'Autorizado', 'url': '/comprobantes/retenciones/'}
        _filas_retencion(libro, retencion, retencion.detalles.all().order_by('impuesto', 'id'), comun, not anulada)
    return libro


def libro_retenciones_recibidas(inicio):
    """Retenciones que te hicieron tus clientes (registradas, de producción), por su fecha de emisión."""
    from core.comprobantes.models import RetencionRecibida
    libro = Libro('retenciones_recibidas', inicio)
    todas = RetencionRecibida.objects.select_related('venta').filter(_en_mes(inicio, 'fecha_emision'))
    pruebas = todas.exclude(ambiente=PRODUCCION).count()
    if pruebas:
        libro.excluidos['retenciones_recibidas'] = {'pruebas': pruebas, 'sin_autorizar': 0}
    for retencion in todas.filter(ambiente=PRODUCCION).prefetch_related('detalles').order_by('fecha_emision', 'id'):
        anulada = retencion.estado == 'anulada' or retencion.anulado_sri_fecha is not None
        comun = {'id': retencion.pk, 'numero': retencion.numero, 'fecha': _fecha(retencion.fecha_emision),
                 'clave_acceso': retencion.clave_acceso or retencion.autorizacion, 'identificacion': retencion.emisor_identificacion,
                 'nombre': retencion.emisor_razon_social, 'periodo_fiscal': retencion.periodo_fiscal,
                 'documento_sustento': f'{retencion.cod_doc_sustento} {retencion.num_doc_sustento}'.strip(),
                 'fecha_sustento': _fecha(retencion.fecha_doc_sustento), 'verificacion': retencion.get_verificacion_display(),
                 'estado': 'anulado' if anulada else 'registrado', 'estado_nombre': 'Anulada' if anulada else 'Registrada',
                 'url': f'/comprobantes/retenciones-recibidas/{retencion.pk}/'}
        _filas_retencion(libro, retencion, retencion.detalles.all().order_by('impuesto', 'id'), comun, not anulada)
    return libro


CONSTRUCTORES = {'ventas': libro_ventas, 'compras': libro_compras, 'retenciones_efectuadas': libro_retenciones_efectuadas,
                 'retenciones_recibidas': libro_retenciones_recibidas}


# ---------------------------------------------------------------- totales y columnas

def totales(libro):
    """Totales de las filas que cuentan (con su signo), más conteos por estado. Retenciones: por impuesto y código."""
    cuentan = [f for f in libro.filas if f['cuenta']]
    resultado = {'documentos': len({(f.get('tipo', ''), f['id']) for f in libro.filas}),
                 'cuentan': len({(f.get('tipo', ''), f['id']) for f in cuentan}),
                 'no_cuentan': len({(f.get('tipo', ''), f['id']) for f in libro.filas if not f['cuenta']})}
    if libro.clave in ('ventas', 'compras'):
        bases, ivas = {}, {}
        for f in cuentan:
            for codigo, valor in f['bases'].items():
                bases[codigo] = bases.get(codigo, CERO) + f['signo'] * valor
            for codigo, valor in f['ivas'].items():
                ivas[codigo] = ivas.get(codigo, CERO) + f['signo'] * valor
        resultado.update(bases=bases, ivas=ivas, base_total=sum(bases.values(), CERO), iva_total=sum(ivas.values(), CERO),
                         total=sum((f['signo'] * f['total'] for f in cuentan), CERO))
        por_tipo = {}
        for f in libro.filas:
            t = por_tipo.setdefault(f['tipo_nombre'], {'documentos': 0, 'cuentan': 0, 'total': CERO})
            t['documentos'] += 1
            if f['cuenta']:
                t['cuentan'] += 1
                t['total'] += f['signo'] * f['total']
        resultado['por_tipo'] = por_tipo
    else:
        por_codigo = {}
        for f in cuentan:
            g = por_codigo.setdefault(f'{f["impuesto"]} {f["codigo"]} ({f["porcentaje"]:f} %)',
                                      {'impuesto': f['impuesto'], 'codigo': f['codigo'], 'porcentaje': f['porcentaje'],
                                       'base': CERO, 'valor': CERO, 'lineas': 0})
            g['base'] += f['base']
            g['valor'] += f['valor']
            g['lineas'] += 1
        resultado.update(por_codigo=por_codigo,
                         renta=sum((f['valor'] for f in cuentan if f['impuesto_id'] == '1'), CERO),
                         iva=sum((f['valor'] for f in cuentan if f['impuesto_id'] == '2'), CERO))
        resultado['total'] = resultado['renta'] + resultado['iva']
    return resultado


def tarifas_presentes(libro):
    """Códigos de tarifa con columna: los fijos y los ocasionales con importes en el mes (y «sin tarifa» en compras)."""
    presentes = {c for f in libro.filas for c in list(f.get('bases', {})) + list(f.get('ivas', {}))}
    codigos = list(TARIFAS_FIJAS) + [c for c in TARIFAS_OCASIONALES if c in presentes]
    if 'sin_tarifa' in presentes:
        codigos.append('sin_tarifa')
    return codigos


def columnas(libro):
    """[(clave, encabezado, tipo)] del libro; tipo 'texto' | 'importe' | 'porcentaje'. Las de tarifa se aplanan como
    base_<código> e iva_<código>."""
    if libro.clave in ('ventas', 'compras'):
        comunes = [('tipo_nombre', 'Tipo', 'texto'), ('numero', 'Número', 'texto'), ('fecha', 'Fecha de emisión', 'texto')]
        if libro.clave == 'ventas':
            comunes += [('identificacion', 'Identificación del cliente', 'texto'), ('tipo_identificacion', 'Tipo de identificación', 'texto'),
                        ('nombre', 'Cliente', 'texto'), ('condicion', 'Condición', 'texto'), ('forma_pago', 'Forma de pago (SRI)', 'texto'),
                        ('documento_modificado', 'Documento modificado', 'texto'), ('clave_acceso', 'Clave de acceso', 'texto')]
        else:
            comunes += [('fecha_registro', 'Fecha de registro', 'texto'), ('identificacion', 'RUC o identificación del proveedor', 'texto'),
                        ('nombre', 'Proveedor', 'texto'), ('sustento', 'Sustento tributario', 'texto'),
                        ('parte_relacionada', 'Parte relacionada', 'texto'), ('forma_pago', 'Forma de pago (SRI)', 'texto'),
                        ('documento_modificado', 'Documento modificado', 'texto'), ('autorizacion', 'Autorización', 'texto'),
                        ('retenciones', 'Retenciones emitidas', 'texto'), ('liquidacion', 'Liquidación de compra', 'texto'),
                        ('origen', 'Origen del registro', 'texto')]
        tarifas = []
        for codigo in tarifas_presentes(libro):
            nombre = 'sin tarifa registrada' if codigo == 'sin_tarifa' else NOMBRES_TARIFA.get(codigo, codigo)
            tarifas.append((f'base_{codigo}', f'Base {nombre}', 'importe'))
            if codigo not in ('0', '6', '7', 'sin_tarifa'):
                tarifas.append((f'iva_{codigo}', f'IVA {nombre}', 'importe'))
        cola = [('base_total', 'Base total', 'importe'), ('iva_total', 'IVA total', 'importe')]
        if libro.clave == 'compras':
            cola.append(('ice', 'ICE', 'importe'))
        cola += [('total', 'Total del documento', 'importe'), ('signo', 'Signo en los totales', 'texto'),
                 ('estado_nombre', 'Estado', 'texto'), ('url', 'Enlace', 'texto')]
        return comunes + tarifas + cola
    comunes = [('numero', 'Número', 'texto'), ('fecha', 'Fecha de emisión', 'texto'), ('clave_acceso', 'Clave de acceso o autorización', 'texto'),
               ('identificacion', 'Identificación', 'texto'),
               ('nombre', 'Proveedor' if libro.clave == 'retenciones_efectuadas' else 'Agente de retención (cliente)', 'texto')]
    if libro.clave == 'retenciones_recibidas':
        comunes += [('periodo_fiscal', 'Período fiscal', 'texto'), ('verificacion', 'Verificación', 'texto')]
    return comunes + [('documento_sustento', 'Documento sustento', 'texto'), ('fecha_sustento', 'Fecha del sustento', 'texto'),
                      ('impuesto', 'Impuesto', 'texto'), ('codigo', 'Código', 'texto'), ('concepto', 'Concepto', 'texto'),
                      ('base', 'Base imponible', 'importe'), ('porcentaje', 'Porcentaje', 'porcentaje'),
                      ('valor', 'Valor retenido', 'importe'), ('estado_nombre', 'Estado', 'texto'), ('url', 'Enlace', 'texto')]


def valor(fila, clave):
    """Valor de una columna (las de tarifa salen de bases/ivas; vacías = 0.00)."""
    if clave.startswith('base_') and clave != 'base_total':
        return fila.get('bases', {}).get(clave[5:], CERO)
    if clave.startswith('iva_') and clave != 'iva_total':
        return fila.get('ivas', {}).get(clave[4:], CERO)
    if clave == 'signo':
        return 'resta' if fila.get('signo') == -1 else ('no suma' if not fila.get('cuenta') else 'suma')
    return fila.get(clave, '')


def construir(clave, inicio):
    libro = CONSTRUCTORES[clave](inicio)
    return libro, totales(libro), columnas(libro)


def resumen(inicio):
    """Los cuatro libros del mes con sus totales (para la página y la revisión del mes)."""
    return OrderedDict((clave, construir(clave, inicio)) for clave in LIBROS)
