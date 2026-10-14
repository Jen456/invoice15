"""Liquidación de compra (03) emitida sobre una compra: reglas en el servidor.

- Procede cuando el vendedor no puede emitir factura (RCV art. 13): personas naturales sin RUC o con RUC suspendido,
  no residentes. Con RUC activo, la liquidación no sustenta crédito ni gasto: el usuario lo confirma expresamente.
- Datos del proveedor tomados de la compra (copiados al emitir). Tipo de identificación 07 no permitido.
- Las líneas son las de la compra (cantidad × precio); el emisor elige la tarifa de IVA de cada una. IVA de línea =
  base × tarifa (HALF_UP) y el total por tarifa es la suma de las líneas, como en las facturas.
- Una compra tiene a lo sumo una liquidación vigente (las devueltas o no autorizadas no cuentan).
"""
import re
from decimal import Decimal

from django.utils import timezone

from core.comprobantes.models import LiquidacionCompra, LiquidacionDetalle, redondear
from core.login.identificacion import cedula_valida, ruc_valido

NO_CUENTAN = ('returned', 'not_authorized', 'sequential_registered_error')
TIPO_LIQUIDACION = '03'
TARIFAS = (Decimal('15.00'), Decimal('5.00'), Decimal('0.00'))


class ErrorLiquidacion(Exception):
    """Mensaje para el usuario."""


def tipo_sugerido(identificacion):
    numero = re.sub(r'\s', '', identificacion or '')
    if re.fullmatch(r'\d{13}', numero):
        return '04'
    if re.fullmatch(r'\d{10}', numero):
        return '05'
    return '06'


def validar_identificacion(tipo, identificacion):
    numero = re.sub(r'\s', '', identificacion or '')
    if tipo == '05' and not cedula_valida(numero):
        raise ErrorLiquidacion('La cédula del proveedor no es válida. Corrígela en Proveedores antes de emitir.')
    if tipo == '04' and not ruc_valido(numero):
        raise ErrorLiquidacion('El RUC del proveedor no es válido. Corrígelo en Proveedores antes de emitir.')
    if tipo in ('06', '08') and not 3 <= len(numero) <= 20:
        raise ErrorLiquidacion('La identificación del proveedor debe tener entre 3 y 20 caracteres.')
    return numero


def liquidacion_vigente(compra):
    return LiquidacionCompra.objects.filter(purchase=compra).exclude(status__in=NO_CUENTAN).first()


def lineas_de_compra(compra):
    """Líneas de la compra con la tarifa sugerida (15 % si el producto cobra impuesto, 0 % si no)."""
    return [{'detalle': d.pk, 'codigo': (d.product.code or '')[:25], 'descripcion': d.product.name[:300],
             'cantidad': Decimal(d.cant), 'precio_unitario': Decimal(d.price),
             'tarifa': TARIFAS[0] if d.product.with_tax else TARIFAS[2]}
            for d in compra.purchasedetail_set.select_related('product').order_by('pk')]


def calcular(compra, datos, elegidas):
    """Valida y calcula sin guardar. elegidas: {id de detalle de compra: (tarifa, descripción o '')}.

    Devuelve (documento normalizado, [detalle calculado], totales).
    """
    proveedor = compra.provider
    tipo = datos.get('tipo_identificacion') or tipo_sugerido(proveedor.ruc)
    if tipo == '04' and not datos.get('confirma_sin_ruc'):
        raise ErrorLiquidacion('El proveedor tiene RUC. Solo emite una liquidación si su RUC está suspendido: con RUC activo debe '
                               'entregarte una factura y la liquidación no sustenta crédito tributario ni gasto.')
    doc = {'tipo_identificacion': tipo, 'identificacion': validar_identificacion(tipo, proveedor.ruc),
           'razon_social': ' '.join(proveedor.name.split())[:300],
           'direccion': ' '.join((datos.get('direccion') or proveedor.address or '').split())[:300],
           'forma_pago': datos.get('forma_pago') or '01', 'concepto': ' '.join((datos.get('concepto') or '').split())[:300]}
    lineas = lineas_de_compra(compra)
    if not lineas:
        raise ErrorLiquidacion('La compra no tiene productos: registra lo que compraste antes de emitir la liquidación.')
    detalle = []
    for linea in lineas:
        tarifa, descripcion = elegidas.get(linea['detalle'], (linea['tarifa'], ''))
        tarifa = Decimal(str(tarifa))
        if tarifa not in TARIFAS:
            raise ErrorLiquidacion('Elige una tarifa de IVA válida (15 %, 5 % o 0 %) en cada línea.')
        base = redondear(linea['cantidad'] * linea['precio_unitario'])
        if base <= 0:
            raise ErrorLiquidacion(f'La línea «{linea["descripcion"]}» no tiene valor: revisa la cantidad y el precio de la compra.')
        detalle.append({**linea, 'descripcion': ' '.join((descripcion or linea['descripcion']).split())[:300], 'tarifa': tarifa,
                        'descuento': Decimal('0.00'), 'base': base, 'iva': redondear(base * tarifa / 100)})
    total_sin_impuestos = redondear(sum(d['base'] for d in detalle))
    total_iva = redondear(sum(d['iva'] for d in detalle))
    grupos = {}
    for d in detalle:
        base, iva = grupos.get(d['tarifa'], (Decimal('0'), Decimal('0')))
        grupos[d['tarifa']] = (base + d['base'], iva + d['iva'])
    totales = {'total_sin_impuestos': total_sin_impuestos, 'total_descuento': Decimal('0.00'), 'total_iva': total_iva,
               'importe_total': redondear(total_sin_impuestos + total_iva),
               'por_tarifa': [(t, redondear(b), redondear(v)) for t, (b, v) in sorted(grupos.items(), reverse=True)]}
    return doc, detalle, totales


def crear(company, usuario, compra, datos, elegidas):
    """Liquidación guardada (aún sin firmar) para `compra`. Llamar dentro de una transacción; la vista firma después."""
    from core.configuracion.servicios import receipt_para_emitir
    from core.pos.models import Purchase
    compra = Purchase.objects.select_for_update().select_related('provider').get(pk=compra.pk)   # una liquidación a la vez
    vigente = liquidacion_vigente(compra)
    if vigente is not None:
        raise ErrorLiquidacion(f'Esta compra ya tiene la liquidación {vigente.voucher_number_full} ({vigente.get_status_display()}).')
    doc, detalle, totales = calcular(compra, datos, elegidas)
    proveedor = compra.provider
    receipt = receipt_para_emitir(company, TIPO_LIQUIDACION, electronica=True)
    numero = receipt.reservar_numero()
    liq = LiquidacionCompra(
        company=company, receipt=receipt, voucher_number=numero,
        voucher_number_full=f'{receipt.establishment_code}-{receipt.issuing_point_code}-{numero}',
        employee=usuario, environment_type=company.environment_type, date_joined=timezone.localdate(),
        purchase=compra, provider=proveedor, correo=(proveedor.email or '').strip() if '@' in (proveedor.email or '') else '',
        total_sin_impuestos=totales['total_sin_impuestos'], total_descuento=totales['total_descuento'],
        total_iva=totales['total_iva'], importe_total=totales['importe_total'], **doc)
    liq.save()
    for d in detalle:
        LiquidacionDetalle.objects.create(liquidacion=liq, codigo=d['codigo'], descripcion=d['descripcion'], cantidad=d['cantidad'],
                                          precio_unitario=d['precio_unitario'], descuento=d['descuento'],
                                          precio_total_sin_impuesto=d['base'], tarifa_iva=d['tarifa'], valor_iva=d['iva'])
    return liq
