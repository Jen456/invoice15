"""Líneas de la factura que llegan del navegador (acciones `add` y `guardar_borrador` de la venta).

Formato (contrato común «precios con IVA», §3): `products` es una lista JSON en el orden en que se ven las filas (ese orden
es el de las líneas en el XML, el RIDE, el ticket y al volver a abrir):

    {"id": <producto>, "cant": 2, "precio_con_iva": "1000.00", "dscto": 0, "descripcion": "texto ≤ 300",
     "codigo_porcentaje": "4"   (solo en la factura en borrador de una proforma)}

Sin `precio_con_iva` (una página anterior abierta durante la publicación) se rechaza con PANTALLA_CAMBIO: nunca se
interpreta `price_current` (sin IVA) como precio con IVA.

El servidor valida cada línea con las reglas de las proformas (core/proformas/servicios.py: cantidad entera de 1 a
999999, precio con IVA de 0 a 999999,99 con hasta 2 decimales, descuento entero de 0 a 100, sin productos repetidos) y la
descripción (sin espacios de más; vacía → nombre del producto; hasta 300 caracteres y sin caracteres de control). Los
importes salen de core/pos/precios_iva.py (enteros, mitad hacia arriba). El precio y la descripción de la línea son de la
factura: nunca cambian el producto del catálogo.

Cambiar el precio no amplía facultades: lo puede hacer quien ya puede fijar precios en el catálogo (`change_product`), y
una factura que sale de una proforma conserva el precio de esa proforma (como hasta ahora). El resto factura al precio con
IVA vigente del catálogo (el de la promoción, si la hay). La descripción la puede cambiar quien puede vender.

Tarifa de IVA por línea: solo en la factura en borrador de una proforma (`tarifas=True`; core/proformas). La línea guarda
la tarifa elegida (SaleDetail.codigo_porcentaje) y de ella salen el XML, el RIDE y los totales; el producto no cambia.
Una tarifa distinta de la del catálogo exige el mismo permiso que el precio (`change_product`) o ser la que ya quedó
guardada en el borrador. En la venta de siempre la tarifa es la del producto, como hasta ahora (lo que envíe el navegador
se ignora).
"""
import json
from decimal import Decimal

from core.pos import precios_iva
from core.pos.choices import NOMBRE_TARIFA_IVA, TARIFAS_IVA
from core.proformas.servicios import (CENTAVO, LINEAS, MAX_CANTIDAD, MAX_IMPORTE, MAX_PRECIO, _decimal, _entero,
                                      _hasta_dos_decimales, tarifa_de_producto)

SIN_LINEAS = 'Agrega al menos un producto.'
PANTALLA_CAMBIO = precios_iva.PANTALLA_CAMBIO
PRECIO_SIN_PERMISO = ('El precio de {nombre} no coincide con el del catálogo ({catalogo}) y tu perfil no puede cambiarlo: quita la '
                      'línea y vuelve a agregarla, o factura desde una proforma.')
SIN_STOCK = 'No hay stock suficiente de {nombre}: quedan {stock}. Revisa la cantidad.'
PERMISO_PRECIO = 'change_product'
TARIFA_INVALIDA = 'La tarifa de IVA no es válida: elige 15 %, 5 %, 0 %, exento o no objeto de IVA.'
TARIFA_SIN_PERMISO = ('La tarifa de IVA de {nombre} ({tarifa}) no es la del catálogo ({catalogo}) y tu perfil no puede '
                      'cambiarla: pide a quien administra el catálogo que revise esta factura.')
IMPORTE_MAXIMO = 'El importe de la línea supera USD 9.999.999,99: revisa la cantidad y el precio.'
TOTAL_MAXIMO = 'El total de la factura supera USD 9.999.999,99.'


class ErrorLineas(ValueError):
    pass


def validar(crudas, tarifas=False):
    """[{producto, cant, precio_con_iva, dscto (fracción), descripcion, catalogo (con IVA), tarifa}] o ErrorLineas con el
    primer problema (número de línea y motivo). `crudas` es la lista del POS (JSON o lista) en el formato del contrato §3:
    {id, cant, precio_con_iva, dscto (porcentaje), descripcion} y, con `tarifas=True` (factura en borrador de una proforma),
    `codigo_porcentaje`; sin él, la del catálogo. Con tarifas=False `tarifa` es None y la venta usa la del producto, como
    siempre. Una lista sin `precio_con_iva` (página anterior) se rechaza entera con PANTALLA_CAMBIO."""
    from core.pos.models import Product
    if isinstance(crudas, str):
        try:
            crudas = json.loads(crudas) if crudas.strip() else []
        except ValueError:
            crudas = None
    if not isinstance(crudas, list) or not crudas:
        raise ErrorLineas(SIN_LINEAS)
    if any(isinstance(c, dict) and 'precio_con_iva' not in c for c in crudas):
        raise ErrorLineas(PANTALLA_CAMBIO)
    ids = [_entero(c.get('id')) for c in crudas if isinstance(c, dict)]
    productos = {p.pk: p for p in Product.objects.filter(pk__in=[i for i in ids if i is not None])}   # solo de la empresa activa
    lineas, vistos, total = [], set(), Decimal('0')
    for n, cruda in enumerate(crudas, start=1):
        cruda = cruda if isinstance(cruda, dict) else {}
        producto = productos.get(_entero(cruda.get('id')))
        if producto is None:
            raise ErrorLineas(f'Línea {n}: {LINEAS["product"]}')
        if producto.pk in vistos:
            raise ErrorLineas(f'Línea {n}: {LINEAS["product_repetido"].format(nombre=producto.name)}')
        vistos.add(producto.pk)
        cant = _entero(cruda.get('cant'))
        if cant is None or not 1 <= cant <= MAX_CANTIDAD:
            raise ErrorLineas(f'Línea {n} ({producto.name}): {LINEAS["cant"]}')
        precio = _decimal(cruda.get('precio_con_iva'))
        if precio is None or not Decimal('0') <= precio <= MAX_PRECIO or not _hasta_dos_decimales(precio):
            raise ErrorLineas(f'Línea {n} ({producto.name}): {LINEAS["price"]}')
        dscto = _decimal(cruda.get('dscto') if cruda.get('dscto') not in ('', None) else 0)
        if dscto is None or dscto != dscto.to_integral_value() or not 0 <= dscto <= 100:
            raise ErrorLineas(f'Línea {n} ({producto.name}): {LINEAS["dscto"]}')
        descripcion, error = precios_iva.limpiar_descripcion(cruda.get('descripcion'), producto.name)
        if error:
            raise ErrorLineas(f'Línea {n} ({producto.name}): {error}')
        tarifa = None
        if tarifas:
            tarifa = str(cruda.get('codigo_porcentaje') or '').strip() or tarifa_de_producto(producto)
            if tarifa not in dict(TARIFAS_IVA):
                raise ErrorLineas(f'Línea {n} ({producto.name}): {TARIFA_INVALIDA}')
        # Ningún importe desborda DecimalField(9, 2) de la línea ni de la venta (antes: error de la base al guardar).
        calculo = precios_iva.calcular(precio, cant, int(dscto), precios_iva.tarifa_de_codigo(tarifa or tarifa_de_producto(producto)))
        if calculo.bruto > MAX_IMPORTE:
            raise ErrorLineas(f'Línea {n} ({producto.name}): {IMPORTE_MAXIMO}')
        total += calculo.total_con_iva
        lineas.append({'producto': producto, 'cant': cant, 'precio_con_iva': precio.quantize(CENTAVO),
                       'dscto': (dscto / 100).quantize(CENTAVO), 'descripcion': descripcion,
                       'catalogo': producto.precio_con_iva_actual(), 'tarifa': tarifa})
    if total > MAX_IMPORTE:
        raise ErrorLineas(TOTAL_MAXIMO)
    return lineas


def puede_cambiar_precio(request):
    from core.security.session import get_group
    grupo = get_group(request)
    return grupo is not None and grupo.permissions.filter(codename=PERMISO_PRECIO).exists()


def precios_de_proforma(proforma):
    """{producto: {precios con IVA}} que una factura puede tomar de la proforma `proforma` sin el permiso del precio: el
    de cada línea con precio con IVA; en las anteriores (precio sin IVA), el que calculó la proforma y el de ese precio con
    la tarifa actual del producto (el que lleva la conversión: core/proformas/servicios.py)."""
    precios = {}
    for d in proforma.detalles.select_related('product'):
        if d.precio_con_iva is not None:
            precios.setdefault(d.product_id, set()).add(Decimal(str(d.precio_con_iva)).quantize(CENTAVO))
            continue
        propios = precios.setdefault(d.product_id, set())
        propios.add(Decimal(str(d.price_with_vat)).quantize(CENTAVO))
        if d.product_id:
            propios.add(precios_iva.con_iva(Decimal(str(d.price)).quantize(CENTAVO), d.product.tarifa_porcentaje()))
    return precios


def comprobar_precios(request, lineas, proforma=None):
    """Un precio con IVA distinto del catálogo con IVA exige el permiso o venir de la proforma que se factura (mismo producto
    y precio)."""
    if all(l['precio_con_iva'] == l['catalogo'] for l in lineas) or puede_cambiar_precio(request):
        return
    de_proforma = precios_de_proforma(proforma) if proforma is not None else {}
    for l in lineas:
        if l['precio_con_iva'] != l['catalogo'] and l['precio_con_iva'] not in de_proforma.get(l['producto'].pk, set()):
            raise ErrorLineas(PRECIO_SIN_PERMISO.format(nombre=l['producto'].name, catalogo=f'{l["catalogo"]:.2f}'))


def comprobar_tarifas(request, lineas, guardadas=None):
    """Una tarifa distinta de la del catálogo exige `change_product` o ser la que ya quedó guardada en la factura en
    borrador para ese producto (`guardadas`: {producto: tarifa}). Nunca cambia el producto."""
    distintas = [l for l in lineas if l.get('tarifa') and l['tarifa'] != tarifa_de_producto(l['producto'])]
    if not distintas or puede_cambiar_precio(request):
        return
    guardadas = guardadas or {}
    for l in distintas:
        if guardadas.get(l['producto'].pk) != l['tarifa']:
            catalogo = tarifa_de_producto(l['producto'])
            raise ErrorLineas(TARIFA_SIN_PERMISO.format(nombre=l['producto'].name,
                                                        tarifa=NOMBRE_TARIFA_IVA.get(l['tarifa'], l['tarifa']),
                                                        catalogo=NOMBRE_TARIFA_IVA.get(catalogo, catalogo)))


def descontar_stock(linea):
    """Baja el stock de un producto inventariado sin pisar otra venta ni el catálogo (F y condición de stock suficiente)."""
    from django.db.models import F

    from core.pos.models import Product
    producto = linea['producto']
    if not producto.inventoried:
        return
    if not Product.objects.filter(pk=producto.pk, inventoried=True, stock__gte=linea['cant']).update(stock=F('stock') - linea['cant']):
        actual = Product.objects.filter(pk=producto.pk).values_list('stock', flat=True).first()
        raise ErrorLineas(SIN_STOCK.format(nombre=producto.name, stock=actual if actual is not None else 0))
