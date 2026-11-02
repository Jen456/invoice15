"""Kardex por producto con costo promedio ponderado (D3) e inventario valorizado a una fecha.

Se calcula desde los documentos cada vez que se consulta; no se guarda. Así, un documento corregido o borrado con fecha
anterior recalcula todo lo posterior sin una orden de reconstrucción. Sigue las mismas reglas con las que hoy cambia el
stock, para que el saldo del kardex se pueda comparar con el stock del producto:

- Compras (cualquier tipo de comprobante) con productos inventariados: entrada al costo de la línea sin IVA (base de la
  línea / cantidad). Si la compra no da crédito tributario, el IVA sería parte del costo: criterio por confirmar (D7).
- Ventas: salida al costo promedio del momento.
- Notas de crédito con productos inventariados: reingreso al costo con que salió esa línea de la venta.
- Factura anulada en el SRI con ajuste de inventario: reingreso al costo de su venta (mismas cantidades que
  core/pos/anulados._stock_factura). Nota de crédito anulada con ajuste: salida al costo con que reingresó.
- Ajustes de stock registrados desde esta entrega (AjusteInventario): la diferencia entra o sale al costo promedio.
- Movimientos manuales del contador: saldo inicial (reinicia el kardex en su fecha: lo anterior no cuenta), entradas con su
  costo y salidas al promedio.

El mismo día van primero el saldo inicial, después las entradas, los ajustes que suman, las salidas, y al final las
devoluciones y anulaciones (que toman el costo de un documento anterior). Si una salida deja el saldo en negativo o entra
algo sin costo conocido, el costo queda «desconocido» hasta que el saldo vuelve a cero o se registra un saldo inicial: no se
inventa un costo.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.utils import timezone

CERO = Decimal('0')
SEIS = Decimal('0.000001')
DOS = Decimal('0.01')
CUATRO = Decimal('0.0001')

# tipo: (nombre, prioridad del día, sentido)
TIPOS = {
    'saldo_inicial': ('Saldo inicial', 0, 0),
    'compra': ('Compra', 1, 1),
    'entrada_manual': ('Entrada manual', 1, 1),
    'ajuste_entrada': ('Ajuste de stock (suma)', 2, 1),
    'venta': ('Venta', 3, -1),
    'salida_manual': ('Salida manual', 3, -1),
    'ajuste_salida': ('Ajuste de stock (resta)', 3, -1),
    'devolucion': ('Devolución en nota de crédito', 4, 1),
    'anulacion_venta': ('Factura anulada en el SRI: vuelve al inventario', 4, 1),
    'anulacion_nota': ('Nota de crédito anulada en el SRI: sale del inventario', 5, -1),
}
NC_PROVEEDOR = ('Nota de crédito del proveedor: hoy suma al stock como una compra. Si fue una devolución, el inventario '
                'debería bajar: revísalo con tu contador.')


def _d(valor):
    return Decimal(str(valor)) if valor is not None else None


def _doc(tipo, id_, numero, url):
    return {'tipo': tipo, 'id': id_, 'numero': numero, 'url': url}


def _mov(tipo, fecha, producto_id, cantidad, documento, desempate, costo=None, costo_de=None, clave=None, observacion=''):
    return {'tipo': tipo, 'fecha': fecha, 'producto_id': producto_id, 'cantidad': int(cantidad), 'costo': costo,
            'costo_de': costo_de, 'clave': clave, 'documento': documento, 'desempate': desempate, 'observacion': observacion}


def cargar(productos_ids, hasta):
    """{producto_id: [movimiento]} de los productos indicados hasta la fecha (incluida), dentro de la empresa activa."""
    from core.contabilidad.models import AjusteInventario, MovimientoManual
    from core.pos.anulados import _stock_factura, _stock_nota
    from core.pos.models import CreditNote, CreditNoteDetail, PurchaseDetail, Sale, SaleDetail
    ids = set(productos_ids)
    movs = defaultdict(list)
    if not ids:
        return movs
    for linea in (PurchaseDetail.objects.filter(product_id__in=ids, product__inventoried=True, purchase__date_joined__lte=hasta)
                  .select_related('purchase').order_by('purchase_id', 'id')):
        if linea.cant <= 0:
            continue
        compra = linea.purchase
        base = _d(linea.total) if linea.total is not None else _d(linea.subtotal) - _d(linea.total_dscto or 0)
        movs[linea.product_id].append(_mov(
            'compra', compra.date_joined, linea.product_id, linea.cant,
            _doc('compra', compra.pk, compra.numero_comprobante or f'#{compra.pk}', f'/pos/purchase/complete/{compra.pk}/'),
            (compra.pk, linea.pk), costo=(base / linea.cant).quantize(SEIS),
            observacion=NC_PROVEEDOR if compra.tipo_comprobante == '04' else ''))
    for linea in (SaleDetail.objects.filter(product_id__in=ids, product__inventoried=True, sale__date_joined__lte=hasta)
                  .select_related('sale').order_by('sale_id', 'id')):
        venta = linea.sale
        movs[linea.product_id].append(_mov(
            'venta', venta.date_joined, linea.product_id, linea.cant,
            _doc('venta', venta.pk, venta.voucher_number_full or f'#{venta.pk}', f'/pos/sale/admin/print/a4/{venta.pk}/'),
            (venta.pk, linea.pk), clave=('venta', linea.pk)))
    for linea in (CreditNoteDetail.objects.filter(product_id__in=ids, product__inventoried=True, credit_note__date_joined__lte=hasta)
                  .select_related('credit_note').order_by('credit_note_id', 'id')):
        nota = linea.credit_note
        movs[linea.product_id].append(_mov(
            'devolucion', nota.date_joined, linea.product_id, linea.cant,
            _doc('nota_credito', nota.pk, nota.voucher_number_full or f'#{nota.pk}', '/pos/credit/note/admin/'),
            (nota.pk, linea.pk), costo_de=('venta', linea.sale_detail_id), clave=('nota', linea.pk)))
    for venta in (Sale.objects.filter(anulado_sri_stock=True, anulado_sri_fecha__lte=hasta, saledetail__product_id__in=ids)
                  .distinct().order_by('id')):
        primera = {}
        for linea in venta.saledetail_set.filter(product__inventoried=True).order_by('id'):
            primera.setdefault(linea.product_id, linea.pk)
        for producto, cantidad in _stock_factura(venta):
            if producto.pk in ids:
                movs[producto.pk].append(_mov(
                    'anulacion_venta', venta.anulado_sri_fecha, producto.pk, cantidad,
                    _doc('venta', venta.pk, venta.voucher_number_full or f'#{venta.pk}', f'/pos/sale/admin/print/a4/{venta.pk}/'),
                    (venta.pk, 0), costo_de=('venta', primera.get(producto.pk))))
    for nota in (CreditNote.objects.filter(anulado_sri_stock=True, anulado_sri_fecha__lte=hasta, creditnotedetail__product_id__in=ids)
                 .distinct().order_by('id')):
        primera = {}
        for linea in nota.creditnotedetail_set.filter(product__inventoried=True).order_by('id'):
            primera.setdefault(linea.product_id, linea.pk)
        for producto, cantidad in _stock_nota(nota):
            if producto.pk in ids:
                movs[producto.pk].append(_mov(
                    'anulacion_nota', nota.anulado_sri_fecha, producto.pk, cantidad,
                    _doc('nota_credito', nota.pk, nota.voucher_number_full or f'#{nota.pk}', '/pos/credit/note/admin/'),
                    (nota.pk, 0), costo_de=('nota', primera.get(producto.pk))))
    for ajuste in AjusteInventario.objects.filter(producto_id__in=ids, fecha__lte=hasta).order_by('fecha', 'id'):
        if ajuste.diferencia == 0:
            continue
        movs[ajuste.producto_id].append(_mov(
            'ajuste_entrada' if ajuste.diferencia > 0 else 'ajuste_salida', ajuste.fecha, ajuste.producto_id, abs(ajuste.diferencia),
            _doc('ajuste', ajuste.pk, f'{ajuste.get_origen_display()}: {ajuste.anterior} → {ajuste.nuevo}', '/pos/product/stock/adjustment/'),
            (ajuste.pk, 0)))
    for manual in MovimientoManual.objects.filter(producto_id__in=ids, fecha__lte=hasta, anulado_en__isnull=True).order_by('fecha', 'id'):
        tipo = {'saldo_inicial': 'saldo_inicial', 'entrada': 'entrada_manual', 'salida': 'salida_manual'}[manual.tipo]
        movs[manual.producto_id].append(_mov(
            tipo, manual.fecha, manual.producto_id, manual.cantidad,
            _doc('manual', manual.pk, manual.documento, f'/contabilidad/kardex/?producto={manual.producto_id}#manual-{manual.pk}'),
            (manual.pk, 0), costo=manual.costo_unitario, observacion=manual.nota))
    return movs


def _orden(m):
    return (m['fecha'], TIPOS[m['tipo']][1], m['desempate'])


def calcular(movimientos):
    """Aplica el promedio ponderado. Devuelve (filas, estado final, advertencias). Cada fila lleva el saldo después de ella."""
    movs = sorted(movimientos, key=_orden)
    saldos = [m for m in movs if m['tipo'] == 'saldo_inicial']
    if saldos:   # el último saldo inicial reinicia el kardex en su fecha: lo anterior (y los saldos anteriores) no cuenta
        ultimo = saldos[-1]
        movs = [m for m in movs if m is ultimo or (m['tipo'] != 'saldo_inicial' and m['fecha'] >= ultimo['fecha'])]
    cantidad, valor, conocido = 0, CERO, True
    costos, filas, advertencias = {}, [], []
    negativo_avisado = desconocido_avisado = False
    for m in movs:
        nombre, _, sentido = TIPOS[m['tipo']]
        if m['tipo'] == 'saldo_inicial':
            costo = m['costo']
            cantidad, valor, conocido = m['cantidad'], m['cantidad'] * costo, True
        else:
            costo = m['costo']
            if costo is None and m['costo_de'] is not None:
                costo = costos.get(m['costo_de'])
            if costo is None and sentido < 0 or (costo is None and m['tipo'] in ('ajuste_entrada', 'devolucion', 'anulacion_venta',
                                                                                    'anulacion_nota')):
                costo = (valor / cantidad).quantize(SEIS) if conocido and cantidad > 0 else None
            if costo is None:
                conocido = False
            else:
                valor += sentido * m['cantidad'] * costo
            cantidad += sentido * m['cantidad']
        if cantidad == 0:
            valor, conocido = CERO, True
        elif cantidad < 0:
            conocido = False
            if not negativo_avisado:
                advertencias.append({'codigo': 'saldo_negativo', 'fecha': m['fecha'].isoformat(),
                                     'texto': f'El {m["fecha"]:%d/%m/%Y} el saldo quedó en negativo: faltan entradas anteriores. '
                                              'Registra el saldo inicial o la compra que falta.'})
                negativo_avisado = True
        if not conocido and not desconocido_avisado:
            advertencias.append({'codigo': 'costo_desconocido', 'fecha': m['fecha'].isoformat(),
                                 'texto': f'Desde el {m["fecha"]:%d/%m/%Y} el costo es desconocido (salida sin saldo o entrada '
                                          'sin costo): registra el saldo inicial con su costo para completarlo.'})
            desconocido_avisado = True
        if m['clave'] is not None:
            costos[m['clave']] = costo
        promedio = (valor / cantidad).quantize(SEIS) if conocido and cantidad > 0 else None
        filas.append({'fecha': m['fecha'], 'tipo': m['tipo'], 'tipo_nombre': nombre, 'documento': m['documento'],
                      'entrada': m['cantidad'] if sentido > 0 or m['tipo'] == 'saldo_inicial' else 0,
                      'salida': m['cantidad'] if sentido < 0 else 0,
                      'costo_unitario': costo, 'costo_total': (m['cantidad'] * costo).quantize(DOS) if costo is not None else None,
                      'saldo_cantidad': cantidad, 'saldo_valor': valor.quantize(DOS) if conocido else None,
                      'costo_promedio': promedio, 'conocido': conocido, 'observacion': m['observacion']})
        if m['observacion'] == NC_PROVEEDOR and not any(a['codigo'] == 'nc_proveedor' for a in advertencias):
            advertencias.append({'codigo': 'nc_proveedor', 'fecha': m['fecha'].isoformat(), 'texto': NC_PROVEEDOR})
    estado = {'cantidad': cantidad, 'valor': valor.quantize(DOS) if conocido else None,
              'costo_promedio': (valor / cantidad).quantize(SEIS) if conocido and cantidad > 0 else None, 'conocido': conocido}
    return filas, estado, advertencias


def kardex(producto, desde, hasta):
    """Kardex de un producto entre dos fechas: saldo anterior, movimientos del período y saldo final, con el stock actual."""
    filas, final, advertencias = calcular(cargar([producto.pk], hasta)[producto.pk])
    anteriores = [f for f in filas if f['fecha'] < desde]
    anterior = ({'cantidad': anteriores[-1]['saldo_cantidad'], 'valor': anteriores[-1]['saldo_valor'],
                 'costo_promedio': anteriores[-1]['costo_promedio'], 'conocido': anteriores[-1]['conocido']}
                if anteriores else {'cantidad': 0, 'valor': CERO.quantize(DOS), 'costo_promedio': None, 'conocido': True})
    hoy = timezone.localdate()
    resultado = {'producto': {'id': producto.pk, 'codigo': producto.code, 'nombre': producto.name, 'stock_actual': producto.stock},
                 'desde': desde, 'hasta': hasta, 'saldo_anterior': anterior, 'movimientos': [f for f in filas if f['fecha'] >= desde],
                 'saldo_final': final, 'advertencias': advertencias, 'diferencia_stock': None}
    if hasta >= hoy:
        resultado['diferencia_stock'] = producto.stock - final['cantidad']
        if resultado['diferencia_stock']:
            advertencias.append({'codigo': 'diferencia_stock', 'fecha': hoy.isoformat(),
                                 'texto': f'El stock del producto ({producto.stock}) no coincide con el saldo del kardex '
                                          f'({final["cantidad"]}): hay movimientos anteriores a los registrados o hechos fuera del '
                                          'sistema. Registra el saldo inicial para completarlo.'})
    return resultado


def inventario(fecha):
    """Inventario valorizado a una fecha: un renglón por producto inventariado con saldo o stock, y los totales."""
    from core.pos.models import Product
    productos = list(Product.objects.filter(inventoried=True).order_by('name', 'id'))
    movimientos = cargar([p.pk for p in productos], fecha)
    hoy = timezone.localdate()
    filas = []
    for p in productos:
        _, estado, advertencias = calcular(movimientos.get(p.pk, []))
        if estado['cantidad'] == 0 and (fecha < hoy or p.stock == 0):
            continue
        filas.append({'producto': {'id': p.pk, 'codigo': p.code, 'nombre': p.name}, 'cantidad': estado['cantidad'],
                      'costo_promedio': estado['costo_promedio'], 'valor': estado['valor'], 'conocido': estado['conocido'],
                      'stock_actual': p.stock if fecha >= hoy else None,
                      'diferencia_stock': p.stock - estado['cantidad'] if fecha >= hoy else None,
                      'advertencias': [a['codigo'] for a in advertencias]})
    conocidos = [f for f in filas if f['conocido']]
    return {'fecha': fecha, 'filas': filas,
            'totales': {'productos': len(filas), 'valor_conocido': sum((f['valor'] for f in conocidos), CERO).quantize(DOS),
                        'sin_costo': len(filas) - len(conocidos),
                        'con_diferencia': sum(1 for f in filas if f['diferencia_stock'])}}


def fecha_de(texto, defecto=None):
    """'AAAA-MM-DD' → date; vacío, inválido o futuro → el defecto (hoy si no se indica)."""
    hoy = timezone.localdate()
    try:
        valor = date.fromisoformat((texto or '').strip())
    except ValueError:
        return defecto or hoy, False
    if valor > hoy or valor.year < 2000:
        return defecto or hoy, False
    return valor, True
