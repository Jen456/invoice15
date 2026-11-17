"""Precios con IVA incluido (entregas/facturaporaqui/CONTRATO-PRECIOS-CON-IVA.md y precios-iva/contrato-comun.md).

- Cálculo de la línea (contrato §1): el total con IVA escrito es exacto; base e IVA se derivan con enteros y mitad hacia
  arriba; el precio unitario sin IVA de 6 decimales cumple cantidad × precioUnitario − descuento = precioTotalSinImpuesto.
- Catálogo con IVA: pvp se deriva; cambiar la tarifa conserva el precio con IVA; quien escribe solo pvp (versión anterior,
  importación) manda; promociones con IVA.
- Venta: formato nuevo de la pantalla (§3), formato viejo rechazado, descripción de la línea, permiso del precio, orden
  de las líneas en el XML, el RIDE, el ticket y al volver a abrir; sin efectivo ni cambio.
- XML 1.1.0 de la factura y de la nota de crédito (total y parcial), RIDE fiel al XML con 6 decimales; las facturas
  anteriores generan su XML de siempre, byte a byte.
- Proforma → borrador → factura conserva precio, descripción y orden. Migración del catálogo, ida y vuelta.
SRI, firma y correo son los dobles ficticios de las pruebas. Datos ficticios."""
import importlib
import json
import os
import random
import subprocess
import sys
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from xml.etree import ElementTree

import pytest
from django.apps import apps
from django.template.loader import render_to_string
from django.utils import timezone
from lxml import etree

from core.comprobantes.fidelidad import diferencias
from core.pos import lineas_venta, precios_iva
from core.pos.models import (CreditNote, CreditNoteDetail, Product, Promotions, PromotionsDetail, Sale, SaleDetail,
                             info_tributaria_final, informacion_adicional, xml_impuesto_de_linea, xml_total_con_impuestos)
from core.pos.utilities.sri import SRI
from core.proformas import servicios
from core.proformas.models import BorradorFactura
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_SELLER
from tests import helpers
from tests.ayudas_precios import validar_factura_110
from tests.ayudas_proformas import crear_proforma, datos_ejemplo, productos_por_tarifa
from tests.test_emision_sri import VENTAS, comprador, dueno, empresa, leer, p12, sri, venta_de, web  # noqa: F401
from tests.test_proformas import texto_pdf
from tests.test_rimpe import XSD, validar

pytestmark = pytest.mark.django_db
D = Decimal
CENTAVO = D('0.01')
RAIZ = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- ayudas

def linea(producto, cant=1, precio=None, dscto=0, descripcion=None):
    item = {'id': producto.pk, 'cant': cant, 'dscto': dscto,
            'precio_con_iva': f'{producto.precio_con_iva:.2f}' if precio is None else precio}
    if descripcion is not None:
        item['descripcion'] = descripcion
    return item


def post_venta(cliente, lineas, **extra):
    datos = {'action': 'add', 'receipt': '01', 'client': cliente.pk, 'payment_type': 'efectivo', 'medio_cobro': 'efectivo',
             'time_limit': '0', 'payment_method': '01', 'additional_info': '[]',
             'products': json.dumps(lineas) if not isinstance(lineas, str) else lineas}
    datos.update(extra)
    return datos


def vender(web, cliente, lineas, sri=None, **extra):  # noqa: F811
    if sri is not None:
        sri.respuestas_autorizacion = ['AUTORIZADO']
    return web.post(f'{VENTAS}add/', post_venta(cliente, lineas, **extra)).json()


def producto_con(empresa, codigo, precio, tarifa='4', stock=1000):  # noqa: F811
    with company_context(empresa):
        p = helpers.crear_producto(empresa, codigo)
        p.precio_con_iva, p.tarifa_iva, p.stock = D(precio), tarifa, stock
        p.save()
        return p


def ultima_venta(empresa):  # noqa: F811
    return leer(empresa, lambda: Sale.objects.latest('pk'))


def detalles_xml(xml):
    raiz = etree.fromstring(xml.encode())
    return raiz, [{c.tag: c.text for c in d if c.tag != 'impuestos'} | {
        'base': d.findtext('impuestos/impuesto/baseImponible'), 'valor': d.findtext('impuestos/impuesto/valor')}
        for d in raiz.iterfind('detalles/detalle')]


def cuadra(detalle):
    """cantidad × precioUnitario − descuento = precioTotalSinImpuesto, al centavo (mitad hacia arriba)."""
    bruto = (D(detalle['cantidad']) * D(detalle['precioUnitario'])).quantize(CENTAVO, ROUND_HALF_UP)
    return bruto - D(detalle['descuento']) == D(detalle['precioTotalSinImpuesto'])


# ---------------------------------------------------------------- 1. cálculo de la línea (contrato §1)

class TestCalculo:

    @pytest.mark.parametrize('precio, cant, dscto, tarifa, total, base, iva, subtotal, descuento, unitario', [
        ('1000.00', 1, 0, 15, '1000.00', '869.57', '130.43', '869.57', '0.00', '869.570000'),
        ('1000.00', 1, 10, 15, '900.00', '782.61', '117.39', '869.57', '86.96', '869.570000'),
        ('1000.00', 3, 0, 15, '3000.00', '2608.70', '391.30', '2608.70', '0.00', '869.566667'),
        ('1000.00', 1, 0, 0, '1000.00', '1000.00', '0.00', '1000.00', '0.00', '1000.000000'),
        ('1000.00', 1, 0, 5, '1000.00', '952.38', '47.62', '952.38', '0.00', '952.380000'),
        ('0.01', 1, 0, 15, '0.01', '0.01', '0.00', '0.01', '0.00', '0.010000'),
        ('999999.99', 1, 0, 15, '999999.99', '869565.21', '130434.78', '869565.21', '0.00', '869565.210000'),
        ('11.50', 2, 0, 15, '23.00', '20.00', '3.00', '20.00', '0.00', '10.000000'),
        ('10.06', 2, 10, 15, '18.11', '15.75', '2.36', '17.50', '1.75', '8.750000'),
    ])
    def test_casos(self, precio, cant, dscto, tarifa, total, base, iva, subtotal, descuento, unitario):
        l = precios_iva.calcular(precio, cant, dscto, tarifa)
        assert (l.total_con_iva, l.base, l.iva, l.subtotal_sin_iva, l.descuento_sin_iva, l.precio_unitario) == (
            D(total), D(base), D(iva), D(subtotal), D(descuento), D(unitario))
        assert l.exacto and l.base + l.iva == l.total_con_iva
        assert cuadra({'cantidad': cant, 'precioUnitario': l.precio_unitario, 'descuento': l.descuento_sin_iva,
                       'precioTotalSinImpuesto': l.base})

    def test_medio_arriba_con_enteros(self):
        assert [precios_iva.medio_arriba(a, 2) for a in (0, 1, 2, 3, 5)] == [0, 1, 1, 2, 3]   # 0,5 → 1; 1,5 → 2; 2,5 → 3
        assert precios_iva.medio_arriba(86957 * 115, 115) == 86957

    def test_propiedades_en_muchas_lineas(self):
        """IVA = T − base con |iva − base × t| ≤ 0,01; descuento sin IVA ≥ 0; con cantidad ≤ 10 000 el precio unitario de
        6 decimales siempre cuadra al centavo."""
        azar = random.Random(20261116)
        for _ in range(4000):
            q = azar.choice([1, 2, 3, 7, 13, 99, 1000, 9999, 10000, azar.randint(1, 10000)])
            p, d, t = azar.randint(0, 99999999), azar.randint(0, 100), azar.choice([0, 5, 15])
            l = precios_iva.calcular(precios_iva.de_centavos(p), q, d, t)
            assert l.base + l.iva == l.total_con_iva and l.descuento_sin_iva >= 0
            assert abs(l.iva - l.base * t / 100) <= D('0.01')
            assert l.exacto and cuadra({'cantidad': q, 'precioUnitario': l.precio_unitario, 'descuento': l.descuento_sin_iva,
                                        'precioTotalSinImpuesto': l.base})

    def test_cantidad_grande_sin_precio_unitario_exacto_toma_el_mas_cercano(self):
        """999 999 × 9,99 con IVA: ningún precio de 6 decimales da el subtotal sin IVA (8 686 947,83) al centavo. Se toma el
        más cercano a subtotal / cantidad (caso documentado; la diferencia es de 0,48)."""
        l = precios_iva.calcular('9.99', 999999, 0, 15)
        assert (l.total_con_iva, l.base, l.iva, l.subtotal_sin_iva) == (D('9989990.01'), D('8686947.83'), D('1303042.18'), D('8686947.83'))
        assert not l.exacto and l.precio_unitario == D('8.686957')
        exacto = D('8686947.83') / 999999
        for vecino in (l.precio_unitario - precios_iva.MICRO, l.precio_unitario + precios_iva.MICRO):
            assert (vecino * 999999).quantize(CENTAVO, ROUND_HALF_UP) != D('8686947.83')
            assert abs(vecino - exacto) >= abs(l.precio_unitario - exacto)
        assert (l.precio_unitario * 999999).quantize(CENTAVO, ROUND_HALF_UP) == D('8686948.31')

    def test_cantidad_grande_con_precio_unitario_exacto(self):
        l = precios_iva.calcular('1.15', 999999, 0, 15)
        assert l.exacto and (l.base, l.precio_unitario) == (D('999999.00'), D('1.000000'))

    def test_texto_del_xml(self):
        assert [precios_iva.texto_decimal(v) for v in (D('869.570000'), D('869.566667'), 3, D('0.010000'), D('8.686957'))] == [
            '869.57', '869.566667', '3.00', '0.01', '8.686957']

    def test_catalogo_ida_y_vuelta(self):
        azar = random.Random(7)
        for _ in range(3000):
            pvp, t = precios_iva.de_centavos(azar.randint(0, 99999999)), azar.choice([0, 5, 12, 13, 14, 15])
            assert precios_iva.base_unitaria(precios_iva.con_iva(pvp, t), t) == pvp

    @pytest.mark.parametrize('texto, esperado', [
        ('  Servicio   de   diseño ', ('Servicio de diseño', None)),
        ('', ('PRODUCTO X', None)), (None, ('PRODUCTO X', None)), ('   ', ('PRODUCTO X', None)),
        ('Ñandú «café» ✓ 😀', ('Ñandú «café» ✓ 😀', None)),
        ('a' * 300, ('a' * 300, None)),
        ('a' * 301, (None, precios_iva.DESCRIPCION_LARGA)),
        ('línea\nnueva', (None, precios_iva.DESCRIPCION_CONTROL)), ('tab\tulador', (None, precios_iva.DESCRIPCION_CONTROL)),
        ('nulo\x00', (None, precios_iva.DESCRIPCION_CONTROL)), ('sep arador', (None, precios_iva.DESCRIPCION_CONTROL)),
        ('borrar\x7f', (None, precios_iva.DESCRIPCION_CONTROL)), (12, (None, precios_iva.DESCRIPCION_INVALIDA)),
    ])
    def test_descripcion(self, texto, esperado):
        assert precios_iva.limpiar_descripcion(texto, 'PRODUCTO X') == esperado


# ---------------------------------------------------------------- 2. catálogo con IVA

class TestCatalogo:

    def test_pvp_se_deriva_y_la_tarifa_conserva_el_precio_con_iva(self, empresa):  # noqa: F811
        p = producto_con(empresa, 'MIL', '1000.00')
        assert (p.precio_con_iva, p.pvp) == (D('1000.00'), D('869.57'))
        with company_context(empresa):
            p.tarifa_iva = '5'
            p.save()
            p = Product.objects.get(pk=p.pk)
        assert (p.precio_con_iva, p.pvp, p.precio_con_iva_catalogo()) == (D('1000.00'), D('952.38'), D('1000.00'))

    def test_quien_escribe_solo_pvp_manda(self, empresa):  # noqa: F811
        p = producto_con(empresa, 'PVP', '11.50')
        with company_context(empresa):
            p.pvp = D('20.00')   # importación del Excel o del facturero, versión anterior
            p.save()
            p = Product.objects.get(pk=p.pk)
            assert (p.pvp, p.precio_con_iva) == (D('20.00'), D('23.00'))
            nuevo = helpers.crear_producto(empresa, 'SOLO-PVP', pvp='3.33')   # alta con pvp: con IVA = 3,8295 → 3,83
            assert (nuevo.pvp, nuevo.precio_con_iva) == (D('3.33'), D('3.83'))

    def test_fila_de_otra_version_se_lee_con_el_precio_de_su_pvp(self, empresa):  # noqa: F811
        p = producto_con(empresa, 'OTRA', '11.50')
        with company_context(empresa):
            Product.objects.filter(pk=p.pk).update(pvp=D('30.00'))                  # versión anterior edita pvp
            assert Product.objects.get(pk=p.pk).precio_con_iva_catalogo() == D('34.50')
            Product.objects.filter(pk=p.pk).update(precio_con_iva=None)             # alta de la versión anterior
            p = Product.objects.get(pk=p.pk)
            assert p.precio_con_iva_catalogo() == D('34.50') and p.toJSON()['precio_con_iva'] == '34.50'
            p.save()                                                                # se repara al guardar
            assert Product.objects.filter(pk=p.pk).values_list('pvp', 'precio_con_iva').get() == (D('30.00'), D('34.50'))

    def test_formulario_pide_el_precio_con_iva(self, web, empresa):  # noqa: F811
        html = web.get('/pos/product/add/').content.decode()
        assert 'name="precio_con_iva"' in html and 'Precio de venta (con IVA)' in html and 'name="pvp"' not in html
        categoria = helpers.crear_producto(empresa, 'CAT-F').category
        r = web.post('/pos/product/add/', {'action': 'add', 'name': 'SERVICIO MIL', 'code': 'MIL-F', 'category': categoria.pk,
                                           'price': '0.00', 'precio_con_iva': '1000.00', 'tarifa_iva': '4'}).json()
        assert r == {}, r
        p = leer(empresa, lambda: Product.objects.get(code='MIL-F'))
        assert (p.precio_con_iva, p.pvp) == (D('1000.00'), D('869.57'))
        r = web.post('/pos/product/add/', {'action': 'add', 'name': 'SIN PRECIO', 'code': 'SIN-F', 'category': categoria.pk,
                                           'price': '0.00', 'pvp': '10.00', 'tarifa_iva': '4'}).json()
        assert 'precio_con_iva' in r['error']   # el formulario ya no acepta pvp en su lugar

    def test_promocion_con_iva(self, empresa):  # noqa: F811
        p = producto_con(empresa, 'PROMO', '11.50')
        with company_context(empresa):
            promo = Promotions.objects.create(start_date=date(2026, 11, 1), end_date=date(2026, 12, 31), state=True)
            PromotionsDetail.objects.create(promotion=promo, product=p, price_current=p.pvp, dscto=D('0.10'),
                                            total_dscto=D('1.00'), price_final=D('9.00'))
            p = Product.objects.get(pk=p.pk)
            datos = p.toJSON()
        assert (datos['precio_con_iva'], datos['precio_con_iva_catalogo'], datos['price_current']) == ('10.35', '11.50', 9.0)


# ---------------------------------------------------------------- 3. venta

class TestVenta:

    def test_mil_dolares_con_iva_exactos(self, web, empresa, comprador, sri):  # noqa: F811
        p = producto_con(empresa, 'MIL', '1000.00')
        r = vender(web, comprador, [linea(p)], sri)
        assert r.get('resp') is True, r
        venta = ultima_venta(empresa)
        assert (venta.subtotal_12, venta.subtotal_0, venta.total_iva, venta.total_dscto, venta.total) == (
            D('869.57'), D('0.00'), D('130.43'), D('0.00'), D('1000.00'))
        assert (venta.cash, venta.change) == (D('0.00'), D('0.00'))
        raiz, [d] = detalles_xml(venta.xml_signed)
        assert raiz.get('version') == '1.1.0'
        assert d == {'codigoPrincipal': 'MIL', 'descripcion': 'PRODUCTO MIL', 'cantidad': '1.00', 'precioUnitario': '869.57',
                     'descuento': '0.00', 'precioTotalSinImpuesto': '869.57', 'base': '869.57', 'valor': '130.43'}
        info = raiz.find('infoFactura')
        assert (info.findtext('totalSinImpuestos'), info.findtext('totalDescuento'), info.findtext('importeTotal'),
                info.findtext('pagos/pago/total')) == ('869.57', '0.00', '1000.00', '1000.00')
        assert [(t.findtext('codigoPorcentaje'), t.findtext('baseImponible'), t.findtext('valor'))
                for t in info.iterfind('totalConImpuestos/totalImpuesto')] == [('4', '869.57', '130.43')]
        ok, errores, _ = validar_factura_110(venta.xml_signed)
        assert ok, errores

    def test_descuento_cantidad_y_tarifas(self, web, empresa, comprador, sri):  # noqa: F811
        a, b = producto_con(empresa, 'DSC', '1000.00'), producto_con(empresa, 'TRES', '1000.00')
        c, e = producto_con(empresa, 'CERO', '1000.00', tarifa='0'), producto_con(empresa, 'CINCO', '1000.00', tarifa='5')
        r = vender(web, comprador, [linea(a, dscto=10), linea(b, cant=3), linea(c), linea(e)], sri)
        assert r.get('resp') is True, r
        venta = ultima_venta(empresa)
        _, detalles = detalles_xml(venta.xml_signed)
        assert [(d['precioUnitario'], d['descuento'], d['precioTotalSinImpuesto'], d['valor']) for d in detalles] == [
            ('869.57', '86.96', '782.61', '117.39'), ('869.566667', '0.00', '2608.70', '391.30'),
            ('1000.00', '0.00', '1000.00', '0.00'), ('952.38', '0.00', '952.38', '47.62')]
        assert all(cuadra(d) for d in detalles)
        assert venta.total == D('900.00') + D('3000.00') + D('1000.00') + D('1000.00')
        assert (venta.subtotal_12, venta.subtotal_0, venta.total_iva, venta.total_dscto) == (
            D('782.61') + D('2608.70') + D('952.38'), D('1000.00'), D('117.39') + D('391.30') + D('47.62'), D('86.96'))
        ok, errores, _ = validar_factura_110(venta.xml_signed)
        assert ok, errores

    def test_diez_lineas_de_mil_en_el_orden_recibido(self, web, empresa, comprador, sri):  # noqa: F811
        productos = [producto_con(empresa, f'L{n:02d}', '1000.00') for n in range(10)]
        orden = [productos[i] for i in (7, 2, 9, 0, 5, 1, 8, 3, 6, 4)]   # ni por id ni por nombre
        lineas = [linea(p, descripcion=f'Fila {n}') for n, p in enumerate(orden, start=1)]
        r = vender(web, comprador, lineas, sri)
        assert r.get('resp') is True, r
        venta = ultima_venta(empresa)
        assert (venta.subtotal_12, venta.total_iva, venta.total) == (D('8695.70'), D('1304.30'), D('10000.00'))
        _, detalles = detalles_xml(venta.xml_signed)
        assert [(d['codigoPrincipal'], d['descripcion']) for d in detalles] == [(p.code, f'Fila {n}') for n, p in enumerate(orden, 1)]
        # Al volver a abrir («Usar como base», listado) y en el RIDE y el ticket, el mismo orden.
        reabierta = web.post(VENTAS, {'action': 'search_detail_products', 'id': venta.pk}).json()
        assert [(l['product']['code'], l['descripcion'], l['precio_con_iva'], l['total_con_iva']) for l in reabierta] == [
            (p.code, f'Fila {n}', '1000.00', '1000.00') for n, p in enumerate(orden, 1)]
        with company_context(empresa):
            ride = render_to_string('sale/format/invoice.html', {'sale': venta})
            ticket = render_to_string('sale/format/ticket.html', {'sale': venta})
        for html in (ride, ticket):
            posiciones = [html.index(f'Fila {n}<') for n in range(1, 11)]
            assert posiciones == sorted(posiciones)

    def test_formato_viejo_rechazado_sin_efectos(self, web, empresa, comprador):  # noqa: F811
        p = producto_con(empresa, 'VIEJO', '11.50')
        antes = leer(empresa, lambda: (Sale.objects.count(), Product.objects.get(pk=p.pk).stock))
        viejo = [{'id': p.pk, 'cant': 1, 'price_current': '10.00', 'dscto': 0}]
        assert vender(web, comprador, viejo)['error'] == precios_iva.PANTALLA_CAMBIO == (
            'La pantalla de venta cambió: recarga la página y vuelve a intentarlo.')
        assert leer(empresa, lambda: (Sale.objects.count(), Product.objects.get(pk=p.pk).stock)) == antes

    def test_descripcion_de_la_linea(self, web, empresa, comprador, sri):  # noqa: F811
        p, q = producto_con(empresa, 'DES', '11.50'), producto_con(empresa, 'VACIA', '2.30')
        r = vender(web, comprador, [linea(p, descripcion='  Servicio   de diseño, noviembre '), linea(q, descripcion='')], sri)
        assert r.get('resp') is True, r
        venta = ultima_venta(empresa)
        _, detalles = detalles_xml(venta.xml_signed)
        assert [d['descripcion'] for d in detalles] == ['Servicio de diseño, noviembre', 'PRODUCTO VACIA']
        assert leer(empresa, lambda: Product.objects.get(pk=p.pk).name) == 'PRODUCTO DES'   # el catálogo no cambia
        antes = leer(empresa, lambda: Sale.objects.count())
        for texto, error in (('x' * 301, precios_iva.DESCRIPCION_LARGA), ('dos\nlíneas', precios_iva.DESCRIPCION_CONTROL)):
            r = vender(web, comprador, [linea(p), linea(q, descripcion=texto)])
            assert r['error'] == f'Línea 2 ({q.name}): {error}'
        assert leer(empresa, lambda: Sale.objects.count()) == antes

    def test_permiso_del_precio_con_iva(self, client, empresa, comprador, sri):  # noqa: F811
        p = producto_con(empresa, 'PERM', '11.50')
        vendedor = helpers.crear_usuario('vendedor.iva', empresa, ROLE_SELLER)
        helpers.iniciar_sesion(client, vendedor, empresa=empresa)
        r = vender(client, comprador, [linea(p, precio='10.00')])
        assert r['error'] == lineas_venta.PRECIO_SIN_PERMISO.format(nombre=p.name, catalogo='11.50')
        r = vender(client, comprador, [linea(p, descripcion='El vendedor sí cambia la descripción')], sri)
        assert r.get('resp') is True, r

    def test_importe_que_no_cabe(self, web, empresa, comprador):  # noqa: F811
        p = producto_con(empresa, 'ALTO', '999999.99')
        r = vender(web, comprador, [linea(p, cant=999999)])
        assert r['error'] == f'Línea 1 ({p.name}): {lineas_venta.IMPORTE_MAXIMO}'
        r = vender(web, comprador, [linea(p, cant=10), linea(producto_con(empresa, 'ALTO2', '1.00'))])
        assert r['error'] == lineas_venta.TOTAL_MAXIMO

    def test_cantidad_grande_y_precio_alto(self, web, empresa, comprador, sri):  # noqa: F811
        caro, mucho = producto_con(empresa, 'CARO', '999999.99'), producto_con(empresa, 'MUCHO', '9.99', stock=1000000)
        r = vender(web, comprador, [linea(caro, cant=9)], sri)
        assert r.get('resp') is True, r
        _, [d] = detalles_xml(ultima_venta(empresa).xml_signed)
        assert (d['precioUnitario'], d['precioTotalSinImpuesto']) == ('869565.208889', '7826086.88') and cuadra(d)
        r = vender(web, comprador, [linea(mucho, cant=999999)], sri)   # caso documentado: sin precio unitario exacto
        assert r.get('resp') is True, r
        venta = ultima_venta(empresa)
        _, [d] = detalles_xml(venta.xml_signed)
        assert (d['cantidad'], d['precioUnitario'], d['precioTotalSinImpuesto']) == ('999999.00', '8.686957', '8686947.83')
        assert venta.total == D('9989990.01')

    def test_precio_minimo(self, web, empresa, comprador, sri):  # noqa: F811
        p = producto_con(empresa, 'CENT', '0.01')
        assert vender(web, comprador, [linea(p)], sri).get('resp') is True
        venta = ultima_venta(empresa)
        assert (venta.subtotal_12, venta.total_iva, venta.total) == (D('0.01'), D('0.00'), D('0.01'))


# ---------------------------------------------------------------- 4. RIDE, ticket y fidelidad

class TestImpresos:

    def test_ride_fiel_al_xml_con_seis_decimales(self, web, empresa, comprador, sri):  # noqa: F811
        p = producto_con(empresa, 'RIDE6', '1000.00')
        assert vender(web, comprador, [linea(p, cant=3, descripcion='Servicio trimestral')], sri).get('resp') is True
        venta = ultima_venta(empresa)
        with venta.xml_authorized.open('rb') as x, venta.pdf_authorized.open('rb') as f:
            xml, pdf = x.read(), f.read()
        assert '<precioUnitario>869.566667</precioUnitario>' in xml.decode()
        assert diferencias(pdf, xml) == []
        with company_context(empresa):
            html = render_to_string('sale/format/invoice.html', {'sale': venta})
        assert '<td>Servicio trimestral</td>' in html and '869,566667' in html

    def test_ticket_con_iva_y_sin_efectivo_ni_cambio(self, web, empresa, comprador, sri):  # noqa: F811
        p = producto_con(empresa, 'TCK', '1000.00')
        assert vender(web, comprador, [linea(p, cant=2, dscto=10, descripcion='Mantenimiento')], sri).get('resp') is True
        venta = ultima_venta(empresa)
        with company_context(empresa):
            html = render_to_string('sale/format/ticket.html', {'sale': venta})
        assert 'Mantenimiento' in html and '$1000,00' in html and '$1800,00' in html and 'Descuento (10 %): $200,00' in html
        assert 'Efectivo:' not in html and 'Cambio:' not in html and '<strong>Pago:</strong> Efectivo' in html
        # Una venta anterior con efectivo y cambio los conserva.
        with company_context(empresa):
            Sale.objects.filter(pk=venta.pk).update(cash=D('2000.00'), change=D('200.00'))
            html = render_to_string('sale/format/ticket.html', {'sale': Sale.objects.get(pk=venta.pk)})
        assert '<strong>Efectivo:</strong> $2000,00' in html and '<strong>Cambio:</strong> $200,00' in html


# ---------------------------------------------------------------- 5. nota de crédito

class TestNotaCredito:

    def acreditar(self, web, venta, cantidades, sri):  # noqa: F811
        sri.respuestas_autorizacion = ['AUTORIZADO']
        detalles = leer(venta.company, lambda: list(venta.saledetail_set.all()))
        productos = [{'id': d.pk, 'quantity': cantidades[n]} for n, d in enumerate(detalles) if cantidades[n]]
        r = web.post('/pos/credit/note/admin/add/', {'action': 'add', 'sale': venta.pk, 'motive': 'Devolución ficticia',
                                                     'products': json.dumps(productos)}).json()
        assert r.get('resp') is True, r
        return leer(venta.company, lambda: CreditNote.objects.filter(sale=venta).latest('pk'))

    def test_total_y_parcial_con_el_calculo_de_la_factura(self, web, empresa, comprador, sri):  # noqa: F811
        a, b = producto_con(empresa, 'NC-A', '1000.00'), producto_con(empresa, 'NC-B', '57.35', tarifa='5')
        assert vender(web, comprador, [linea(a, cant=3, dscto=10, descripcion='Equipo A'), linea(b, cant=2)], sri)['resp']
        venta = ultima_venta(empresa)
        parcial = self.acreditar(web, venta, [1, 0], sri)                         # 1 de 3: el mismo cálculo con cantidad 1
        esperado = precios_iva.calcular('1000.00', 1, 10, 15)
        [d] = leer(empresa, lambda: list(parcial.creditnotedetail_set.all()))
        assert (d.precio_con_iva, d.descripcion, d.total, d.total_iva, d.total_dscto) == (
            D('1000.00'), 'Equipo A', esperado.base, esperado.iva, esperado.descuento_sin_iva)
        assert parcial.total == esperado.total_con_iva == D('900.00')
        ok, errores, documento = validar(parcial.xml_signed, XSD / 'notacredito' / 'NotaCredito_V1.1.0.xsd')
        assert ok, errores
        detalle = {c.tag: c.text for c in documento.find('detalles/detalle') if c.tag != 'impuestos'}
        assert detalle == {'codigoInterno': 'NC-A', 'descripcion': 'Equipo A', 'cantidad': '1.00', 'precioUnitario': '869.57',
                           'descuento': '86.96', 'precioTotalSinImpuesto': '782.61'} and cuadra(detalle)
        resto = self.acreditar(web, venta, [2, 2], sri)                           # el resto: 2 de A y las 2 de B
        _, detalles = detalles_xml(resto.xml_signed)
        assert [(d['cantidad'], d['precioUnitario'], d['descuento'], d['precioTotalSinImpuesto']) for d in detalles] == [
            ('2.00', '869.565', '173.91', '1565.22'), ('2.00', '54.62', '0.00', '109.24')]
        assert all(cuadra(d) for d in detalles)
        b_total = precios_iva.calcular('57.35', 2, 0, 5)
        assert resto.total == precios_iva.calcular('1000.00', 2, 10, 15).total_con_iva + b_total.total_con_iva
        ok, errores, _ = validar(resto.xml_signed, XSD / 'notacredito' / 'NotaCredito_V1.1.0.xsd')
        assert ok, errores

    def test_nota_total_desde_el_listado(self, web, empresa, comprador, sri):  # noqa: F811
        p = producto_con(empresa, 'NC-T', '1000.00')
        assert vender(web, comprador, [linea(p, cant=3)], sri)['resp']
        venta = ultima_venta(empresa)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = web.post(VENTAS, {'action': 'create_credit_note', 'id': venta.pk}).json()
        assert r.get('resp') is True, r
        nota = leer(empresa, lambda: CreditNote.objects.get(sale=venta))
        assert (nota.subtotal_12, nota.total_iva, nota.total) == (venta.subtotal_12, venta.total_iva, venta.total)
        _, [d] = detalles_xml(nota.xml_signed)
        assert (d['precioUnitario'], d['precioTotalSinImpuesto']) == ('869.566667', '2608.70') and cuadra(d)
        assert leer(empresa, lambda: Sale.objects.get(pk=venta.pk).status) == 'canceled'


# ---------------------------------------------------------------- 6. facturas anteriores: el mismo XML byte a byte

def xml_factura_e0d7c38(self):
    """Sale.generate_xml tal como estaba en e0d7c38 (copia literal del cuerpo, para comparar)."""
    fecha_emision = self.emission_date or timezone.localdate()
    access_key = self.access_code or SRI().create_access_key(self, fecha_emision)
    root = ElementTree.Element('factura', id="comprobante", version="1.0.0")
    xml_tax_info = ElementTree.SubElement(root, 'infoTributaria')
    ElementTree.SubElement(xml_tax_info, 'ambiente').text = str(self.environment_type)
    ElementTree.SubElement(xml_tax_info, 'tipoEmision').text = str(self.company.emission_type)
    ElementTree.SubElement(xml_tax_info, 'razonSocial').text = self.company.business_name
    ElementTree.SubElement(xml_tax_info, 'nombreComercial').text = self.company.tradename
    ElementTree.SubElement(xml_tax_info, 'ruc').text = self.company.ruc
    ElementTree.SubElement(xml_tax_info, 'claveAcceso').text = access_key
    ElementTree.SubElement(xml_tax_info, 'codDoc').text = self.receipt.voucher_type
    ElementTree.SubElement(xml_tax_info, 'estab').text = self.receipt.establishment_code
    ElementTree.SubElement(xml_tax_info, 'ptoEmi').text = self.receipt.issuing_point_code
    ElementTree.SubElement(xml_tax_info, 'secuencial').text = self.voucher_number
    ElementTree.SubElement(xml_tax_info, 'dirMatriz').text = self.company.main_address
    info_tributaria_final(self.company, xml_tax_info)
    xml_info_invoice = ElementTree.SubElement(root, 'infoFactura')
    ElementTree.SubElement(xml_info_invoice, 'fechaEmision').text = fecha_emision.strftime('%d/%m/%Y')
    ElementTree.SubElement(xml_info_invoice, 'dirEstablecimiento').text = self.receipt.establishment_address() or self.company.establishment_address
    ElementTree.SubElement(xml_info_invoice, 'obligadoContabilidad').text = self.company.obligated_accounting
    ElementTree.SubElement(xml_info_invoice, 'tipoIdentificacionComprador').text = self.client.identification_type
    ElementTree.SubElement(xml_info_invoice, 'razonSocialComprador').text = self.client.user.names
    ElementTree.SubElement(xml_info_invoice, 'identificacionComprador').text = self.client.dni
    ElementTree.SubElement(xml_info_invoice, 'direccionComprador').text = self.client.address
    ElementTree.SubElement(xml_info_invoice, 'totalSinImpuestos').text = f'{self.get_full_subtotal():.2f}'
    ElementTree.SubElement(xml_info_invoice, 'totalDescuento').text = f'{self.total_dscto:.2f}'
    xml_total_con_impuestos(ElementTree.SubElement(xml_info_invoice, 'totalConImpuestos'), self.saledetail_set.select_related('product'))
    ElementTree.SubElement(xml_info_invoice, 'propina').text = '0.00'
    ElementTree.SubElement(xml_info_invoice, 'importeTotal').text = f'{self.total:.2f}'
    ElementTree.SubElement(xml_info_invoice, 'moneda').text = 'DOLAR'
    xml_payments = ElementTree.SubElement(xml_info_invoice, 'pagos')
    xml_payment = ElementTree.SubElement(xml_payments, 'pago')
    ElementTree.SubElement(xml_payment, 'formaPago').text = self.payment_method
    ElementTree.SubElement(xml_payment, 'total').text = f'{self.total:.2f}'
    ElementTree.SubElement(xml_payment, 'plazo').text = str(self.time_limit)
    ElementTree.SubElement(xml_payment, 'unidadTiempo').text = 'dias'
    xml_details = ElementTree.SubElement(root, 'detalles')
    for detail in self.saledetail_set.select_related('product'):
        xml_detail = ElementTree.SubElement(xml_details, 'detalle')
        ElementTree.SubElement(xml_detail, 'codigoPrincipal').text = detail.product.code
        ElementTree.SubElement(xml_detail, 'descripcion').text = detail.product.name
        ElementTree.SubElement(xml_detail, 'cantidad').text = f'{detail.cant:.2f}'
        ElementTree.SubElement(xml_detail, 'precioUnitario').text = f'{detail.price:.2f}'
        ElementTree.SubElement(xml_detail, 'descuento').text = f'{detail.total_dscto:.2f}'
        ElementTree.SubElement(xml_detail, 'precioTotalSinImpuesto').text = f'{detail.total:.2f}'
        xml_impuesto_de_linea(xml_detail, detail)
    informacion_adicional(root, [(i.get('name'), i.get('value')) for i in (self.additional_info or [])])
    return '<?xml version="1.0" encoding="UTF-8"?>' + ElementTree.tostring(root, encoding='unicode'), access_key


def detalles_nc_e0d7c38(nota):
    """Los <detalle> de CreditNote.generate_xml en e0d7c38."""
    nodo = ElementTree.Element('detalles')
    for detail in nota.creditnotedetail_set.select_related('product', 'sale_detail__product'):
        xml_detail = ElementTree.SubElement(nodo, 'detalle')
        ElementTree.SubElement(xml_detail, 'codigoInterno').text = detail.product.code
        ElementTree.SubElement(xml_detail, 'descripcion').text = detail.product.name
        ElementTree.SubElement(xml_detail, 'cantidad').text = f'{detail.cant:.2f}'
        ElementTree.SubElement(xml_detail, 'precioUnitario').text = f'{detail.price:.2f}'
        ElementTree.SubElement(xml_detail, 'descuento').text = f'{detail.total_dscto:.2f}'
        ElementTree.SubElement(xml_detail, 'precioTotalSinImpuesto').text = f'{detail.total:.2f}'
        xml_impuesto_de_linea(xml_detail, detail)
    return ElementTree.tostring(nodo, encoding='unicode')


class TestAnteriores:

    def venta_antigua(self, empresa, comprador, dueno):  # noqa: F811
        """Venta guardada antes del cambio: líneas sin precio con IVA (precio sin IVA, descuento y tarifas mezcladas)."""
        with company_context(empresa):
            p15, p5 = helpers.crear_producto(empresa, 'ANT15', pvp='8.75'), helpers.crear_producto(empresa, 'ANT5', pvp='3.33')
            Product.objects.filter(pk=p5.pk).update(tarifa_iva='5')
            venta = helpers.crear_venta(empresa, comprador, dueno, p15, cantidad=2)
            SaleDetail.objects.filter(sale=venta).update(dscto=D('0.10'))
            SaleDetail.objects.create(sale=venta, product=p5, cant=3, price=D('3.33'), codigo_porcentaje='5')
            venta.calculate_detail()
            venta.calculate_invoice()
            Sale.objects.filter(pk=venta.pk).update(access_code='1' * 49, emission_date=date(2026, 11, 10))
            return Sale.objects.get(pk=venta.pk)

    def test_xml_de_una_factura_anterior_igual_byte_a_byte(self, empresa, comprador, dueno):  # noqa: F811
        venta = self.venta_antigua(empresa, comprador, dueno)
        with company_context(empresa):
            assert not any(d.precio_con_iva for d in venta.saledetail_set.all())
            nuevo, antiguo = venta.generate_xml(), xml_factura_e0d7c38(venta)
        assert nuevo == antiguo and 'version="1.0.0"' in nuevo[0] and '<precioUnitario>8.75</precioUnitario>' in nuevo[0]
        assert (venta.total_iva, venta.total) == (D('2.86'), D('28.60'))   # 15,75 + 2,36 y 9,99 + 0,50 de siempre

    def test_nota_de_credito_sobre_factura_anterior_igual(self, empresa, comprador, dueno):  # noqa: F811
        venta = self.venta_antigua(empresa, comprador, dueno)
        with company_context(empresa):
            nota = CreditNote.objects.create(sale=venta, company=empresa, receipt=venta.receipt, voucher_number='000000009',
                                             voucher_number_full='001-001-000000009', motive='Anterior')
            for d in venta.saledetail_set.all():
                CreditNoteDetail.objects.create(credit_note=nota, sale_detail=d, product=d.product, cant=1, price=d.price,
                                                dscto=d.dscto)
            nota.calculate_detail()
            nota.calculate_invoice()
            xml, _ = nota.generate_xml()
            nodo = etree.fromstring(xml.encode()).find('detalles')
            assert etree.tostring(nodo, encoding='unicode') == detalles_nc_e0d7c38(nota)
        assert nota.total == D('12.55')   # 7,87 + 1,18 (15 %) y 3,33 + 0,17 (5 %), como antes

    def test_ride_y_ticket_de_una_factura_anterior_como_antes(self, empresa, comprador, dueno):  # noqa: F811
        """Con líneas sin precio con IVA, las plantillas dan el mismo HTML que las de e0d7c38 (las condiciones nuevas no
        escriben nada: se comparan contra la plantilla con cada {% if detail.con_iva_incluido %} reducido a su rama anterior)."""
        import re
        from django.template import engines
        venta = self.venta_antigua(empresa, comprador, dueno)
        for nombre in ('sale/format/invoice.html', 'sale/format/ticket.html'):
            fuente = Path(apps.get_app_config('pos').path, 'templates', nombre).read_text(encoding='utf-8')
            anterior = re.sub(r'\{% if detail\.con_iva_incluido %\}.*?\{% else %\}(.*?)\{% endif %\}', r'\1', fuente, flags=re.S)
            anterior = re.sub(r"\{% elif sale\.payment_type == 'efectivo' and not sale\.cash and not sale\.change %\}.*?(?=\{% elif)",
                              '', anterior, flags=re.S)
            with company_context(empresa):
                Sale.objects.filter(pk=venta.pk).update(cash=D('50.00'), change=D('21.39'))
                v = Sale.objects.get(pk=venta.pk)
                assert render_to_string(nombre, {'sale': v}) == engines['django'].from_string(anterior).render({'sale': v})


# ---------------------------------------------------------------- 7. proforma → factura

class TestProforma:

    def test_proforma_borrador_y_factura_conservan_precio_descripcion_y_orden(self, web, empresa, dueno, comprador, sri):  # noqa: F811
        productos = productos_por_tarifa(empresa)
        lineas = [{'product': productos['0'].pk, 'cant': 1, 'precio_con_iva': '1000.00', 'dscto': 0, 'descripcion': 'Primera: asesoría'},
                  {'product': productos['4'].pk, 'cant': 3, 'precio_con_iva': '1000.00', 'dscto': 10, 'descripcion': 'Segunda: equipo'},
                  {'product': productos['5'].pk, 'cant': 2, 'precio_con_iva': '12.97', 'dscto': 0, 'descripcion': ''}]
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador, lineas=lineas), estado='aceptada')
        with company_context(empresa):
            guardadas = list(p.detalles.all())
            assert [(l.descripcion, l.precio_con_iva, l.total_con_iva) for l in guardadas] == [
                ('Primera: asesoría', D('1000.00'), D('1000.00')), ('Segunda: equipo', D('1000.00'), D('2700.00')),
                ('PRODUCTO P5', D('12.97'), D('25.94'))]
            assert p.total == D('3725.94')
            pdf = servicios.contexto_pdf(p)
            assert pdf['precios_con_iva'] is True
        texto = texto_pdf(web.get(f'/proformas/pdf/{p.pk}/').content)   # el PDF muestra los precios con IVA de las líneas
        assert 'P. unit. con IVA' in texto and 'Primera: asesoría' in texto and '2700,00' in texto and '3725,94' in texto
        r = web.post('/proformas/', {'action': 'convertir', 'id': p.pk}).json()
        b = leer(empresa, lambda: BorradorFactura.objects.get(proforma=p))
        assert [(l['product'], l['precio_con_iva'], l['descripcion']) for l in b.lineas] == [
            (productos['0'].pk, '1000.00', 'Primera: asesoría'), (productos['4'].pk, '1000.00', 'Segunda: equipo'),
            (productos['5'].pk, '12.97', 'PRODUCTO P5')]
        datos = web.get(r['url']).context['proforma_precarga']
        assert [(l['code'], l['precio_con_iva'], l['descripcion']) for l in datos['lineas']] == [
            ('P0', '1000.00', 'Primera: asesoría'), ('P15', '1000.00', 'Segunda: equipo'), ('P5', '12.97', 'PRODUCTO P5')]
        assert datos['borrador']['totales']['total'] == '3725.94'
        sri.respuestas_autorizacion = ['AUTORIZADO']
        envio = [{'id': l['id'], 'cant': l['cant'], 'precio_con_iva': l['precio_con_iva'], 'dscto': l['dscto'],
                  'descripcion': l['descripcion'], 'codigo_porcentaje': l['codigo_porcentaje']} for l in datos['lineas']]
        r = web.post(f'{VENTAS}add/', post_venta(comprador, envio, proforma_id=str(p.pk), borrador_id=str(datos['borrador']['id']),
                                                 additional_info=json.dumps(datos['info_adicional']))).json()
        assert r.get('resp') is True, r
        venta = ultima_venta(empresa)
        assert venta.total == D('3725.94')
        _, detalles = detalles_xml(venta.xml_signed)
        assert [(d['codigoPrincipal'], d['descripcion']) for d in detalles] == [
            ('P0', 'Primera: asesoría'), ('P15', 'Segunda: equipo'), ('P5', 'PRODUCTO P5')]
        assert all(cuadra(d) for d in detalles)

    def test_editor_viejo_rechazado(self, empresa, dueno):  # noqa: F811
        productos = productos_por_tarifa(empresa)
        viejo = [{'product': productos['4'].pk, 'cant': 1, 'price': '10.00', 'dscto': 0, 'descripcion': ''}]
        with pytest.raises(servicios.ErrorProforma) as error:
            crear_proforma(empresa, dueno, datos_ejemplo(productos, lineas=viejo))
        assert error.value.mensaje == precios_iva.PANTALLA_CAMBIO_PROFORMA and error.value.estado_http == 409

    def test_descripcion_con_controles_en_la_proforma(self, empresa, dueno):  # noqa: F811
        productos = productos_por_tarifa(empresa)
        malas = [{'product': productos['4'].pk, 'cant': 1, 'precio_con_iva': '11.50', 'dscto': 0, 'descripcion': 'a\tb'}]
        with pytest.raises(servicios.ErrorProforma) as error:
            crear_proforma(empresa, dueno, datos_ejemplo(productos, lineas=malas))
        assert error.value.campos['lineas'] == [{'indice': 0, 'campo': 'descripcion', 'texto': precios_iva.DESCRIPCION_CONTROL}]


# ---------------------------------------------------------------- 8. migración del catálogo

class TestMigracion:

    def test_poblar_con_la_tarifa_de_cada_producto(self, empresa):  # noqa: F811
        migracion = importlib.import_module('core.pos.migrations.0037_precio_con_iva_del_catalogo')
        casos = {'M15': ('8.75', '4', True, '10.06'), 'M05': ('3.33', '5', True, '3.50'), 'M00': ('4.00', '0', False, '4.00'),
                 'MSIN': ('10.00', '', True, '11.50'), 'MEX': ('2.50', '7', False, '2.50'), 'MRED': ('0.03', '4', True, '0.03')}
        with company_context(empresa):
            for codigo, (pvp, tarifa, con_iva, _) in casos.items():
                helpers.crear_producto(empresa, codigo, pvp=pvp)
                Product.objects.filter(code=codigo).update(tarifa_iva=tarifa, with_tax=con_iva, precio_con_iva=None)
            migracion.poblar(apps, None)
            filas = dict((c, (pvp, p)) for c, pvp, p in Product.objects.filter(code__in=casos).values_list('code', 'pvp', 'precio_con_iva'))
        assert filas == {c: (D(pvp), D(esperado)) for c, (pvp, _, _, esperado) in casos.items()}

    def test_ida_y_vuelta(self, tmp_path):
        """Subproceso con SQLite en archivo: ida completa, vuelta a pos 0035 (sin las columnas) e ida otra vez."""
        env = {k: v for k, v in os.environ.items() if not k.startswith(('FPA_', 'DATABASE_URL', 'SECRET_KEY', 'DEBUG'))}
        base = '/dev/shm' if os.path.isdir('/dev/shm') and os.access('/dev/shm', os.W_OK) else str(tmp_path)
        archivo = Path(base) / f'precios-iva-{os.getpid()}.db'
        env.update({'FPA_ENV_FILE': os.devnull, 'DJANGO_SETTINGS_MODULE': 'config.settings', 'SECRET_KEY': 'precios-iva',
                    'DEBUG': 'True', 'DATABASE_URL': f'sqlite:///{archivo}'})

        def manage(*args, stdin=None):
            r = subprocess.run([sys.executable, 'manage.py', *args], cwd=RAIZ, env=env, input=stdin, capture_output=True,
                               text=True, timeout=900)
            assert r.returncode == 0, r.stderr[-3000:]
            return r.stdout

        crear = ("from decimal import Decimal\nfrom tests import helpers\nfrom core.pos.models import Product\n"
                 "e = helpers.crear_empresa('MIGRACION FICTICIA')\n"
                 "for codigo, pvp, tarifa in (('A', '10.00', '4'), ('B', '3.33', '5'), ('C', '4.00', '0')):\n"
                 "    p = helpers.crear_producto(e, codigo, pvp=pvp)\n"
                 "    Product.all_companies.filter(pk=p.pk).update(tarifa_iva=tarifa, precio_con_iva=None)\n")
        leer_sql = ("from django.db import connection\nc = connection.cursor()\n"
                    "c.execute('SELECT code, pvp, precio_con_iva FROM pos_product ORDER BY code')\n"
                    "import json\nfrom decimal import Decimal\n"
                    "print('RESULTADO=' + json.dumps([[a, f'{Decimal(str(b)):.2f}', f'{Decimal(str(p)):.2f}'] for a, b, p in c.fetchall()]))\n")
        columnas = ("from django.db import connection\nc = connection.cursor()\n"
                    "import json\nprint('RESULTADO=' + json.dumps(sorted(col.name for col in connection.introspection.get_table_description(c, 'pos_saledetail'))))\n")
        try:
            manage('migrate', '-v', '0')
            manage('shell', stdin=crear)
            manage('migrate', 'pos', '0036', '-v', '0')          # vuelta de la migración de datos (no hace nada)
            manage('migrate', 'pos', '-v', '0')                  # ida: puebla las filas NULL
            esperado = [['A', '10.00', '11.50'], ['B', '3.33', '3.50'], ['C', '4.00', '4.00']]
            assert json.loads(manage('shell', stdin=leer_sql).split('RESULTADO=')[1]) == esperado
            manage('migrate', 'pos', '0035', '-v', '0')          # vuelta: sin las columnas nuevas
            sin = json.loads(manage('shell', stdin=columnas).split('RESULTADO=')[1])
            assert not {'precio_con_iva', 'precio_unitario', 'descripcion'} & set(sin)
            manage('migrate', '-v', '0')                         # ida otra vez
            assert json.loads(manage('shell', stdin=leer_sql).split('RESULTADO=')[1]) == esperado
            con = json.loads(manage('shell', stdin=columnas).split('RESULTADO=')[1])
            assert {'precio_con_iva', 'precio_unitario', 'descripcion'} <= set(con)
        finally:
            archivo.unlink(missing_ok=True)


# ---------------------------------------------------------------- 9. convivencia con la versión anterior durante la publicación

class TestConvivencia:
    """La versión publicada (e0f2902) y la del PR #1 (e0d7c38) escriben sin nombrar las columnas nuevas: sus INSERT valen
    sobre el esquema nuevo (NULL o el DEFAULT '' de la base) y esas filas se leen como «anteriores»."""
    NUEVAS = {'precio_con_iva', 'precio_unitario', 'descripcion'}

    def copiar_sin_columnas_nuevas(self, modelo, pk, cambio=None):
        from django.db import connection
        tabla = connection.ops.quote_name(modelo._meta.db_table)
        columnas = [f.column for f in modelo._meta.concrete_fields if not f.primary_key and f.name not in self.NUEVAS]
        origen = [cambio.get(c, connection.ops.quote_name(c)) if cambio else connection.ops.quote_name(c) for c in columnas]
        with connection.cursor() as cursor:
            cursor.execute(f'INSERT INTO {tabla} ({", ".join(connection.ops.quote_name(c) for c in columnas)}) '
                           f'SELECT {", ".join(origen)} FROM {tabla} WHERE id = %s', [pk])
        return modelo.all_companies.order_by('-pk').first()

    def test_insert_de_la_version_anterior(self, web, empresa, comprador, sri):  # noqa: F811
        p = producto_con(empresa, 'CONV', '11.50')
        assert vender(web, comprador, [linea(p, cant=2)], sri)['resp']
        venta = ultima_venta(empresa)
        with company_context(empresa):
            detalle = venta.saledetail_set.get()
            copia = self.copiar_sin_columnas_nuevas(SaleDetail, detalle.pk)
            assert (copia.precio_con_iva, copia.precio_unitario, copia.descripcion) == (None, None, '')
            assert not copia.con_iva_incluido and copia.descripcion_linea == 'PRODUCTO CONV'
            nuevo = self.copiar_sin_columnas_nuevas(Product, p.pk, {'code': "'CONV-ANT'", 'name': "'PRODUCTO ANTERIOR'"})
            assert nuevo.precio_con_iva is None and nuevo.precio_con_iva_catalogo() == D('11.50')
