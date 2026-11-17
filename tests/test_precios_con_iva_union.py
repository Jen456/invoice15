"""Unión del servidor y la pantalla de «precios con IVA incluido» (entregas/facturaporaqui/CONTRATO-PRECIOS-CON-IVA.md).

Lo que el servidor manda de verdad a las pantallas que la unión ajustó, y que esas pantallas lo leen:

- Modal «Detalle» del listado de ventas (y el del portal del cliente y los de notas de crédito): la acción
  `search_detail_products` manda `descripcion`, `precio_con_iva`, `total_con_iva` y `con_iva_incluido`; una factura
  anterior al cambio sigue mandando lo que el modal mostraba (precio, descuento y total guardados). El pintado está en
  tests/frontend/detalle_lineas.test.cjs.
- Nota de crédito: las líneas que recibe la pantalla (`search_sale`) dicen si la factura lleva precio con IVA, y la nota
  parcial da el total con IVA de la cantidad devuelta (lo que la pantalla enseña antes de emitir:
  tests/frontend/nota_credito_importes.test.cjs).
- Listado de productos: el precio de venta y el de la promoción con IVA.
SRI, firma y correo son los dobles ficticios de las pruebas. Datos ficticios."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from core.pos import precios_iva
from core.pos.models import CreditNote, Product, Promotions, PromotionsDetail, Sale
from core.tenancy.context import company_context
from tests import test_precios_con_iva as base
from tests.test_emision_sri import VENTAS, comprador, dueno, empresa, leer, p12, sri, web  # noqa: F401
from tests.test_precios_con_iva import linea, producto_con, ultima_venta, vender

pytestmark = pytest.mark.django_db
D = Decimal
RAIZ = Path(__file__).resolve().parent.parent
NOTAS = '/pos/credit/note/admin/'
# plantilla del listado → (su list.js, el campo que «P./Unitario» mostraba antes del cambio)
MODALES = {
    'core/pos/templates/sale/admin/list.html': ('sale/admin/js/list.js', 'price'),
    'core/pos/templates/sale/client/list.html': ('sale/client/js/list.js', 'price'),
    'core/pos/templates/credit_note/admin/list.html': ('credit_note/admin/js/list.js', 'price_with_vat'),
    'core/pos/templates/credit_note/client/list.html': ('credit_note/client/js/list.js', 'price_with_vat'),
}


def venta_anterior(empresa, comprador, dueno, autorizada=False):  # noqa: F811
    """Factura guardada antes del cambio (líneas sin precio con IVA): 2 × 8,75 al 15 % con 10 % y 3 × 3,33 al 5 %."""
    venta = base.TestAnteriores().venta_antigua(empresa, comprador, dueno)
    if autorizada:
        leer(empresa, lambda: Sale.objects.filter(pk=venta.pk).update(status='authorized',
                                                                      environment_type=empresa.environment_type))
    return venta


# ---------------------------------------------------------------- modal «Detalle» de los listados

class TestDetalleDelListado:

    def test_factura_con_precios_con_iva(self, web, empresa, comprador, sri):  # noqa: F811
        a, b = producto_con(empresa, 'UN-A', '1000.00'), producto_con(empresa, 'UN-B', '25.00', tarifa='0')
        assert vender(web, comprador, [linea(a, dscto=10, descripcion='Servicio de diseño'), linea(b, cant=3)], sri)['resp']
        venta = ultima_venta(empresa)
        r = web.post(VENTAS, {'action': 'search_detail_products', 'id': venta.pk}).json()
        assert [(d['descripcion'], d['precio_con_iva'], d['cant'], d['total_con_iva'], d['con_iva_incluido']) for d in r] == [
            ('Servicio de diseño', '1000.00', 1, '900.00', True), ('PRODUCTO UN-B', '25.00', 3, '75.00', True)]
        # Lo que mostraba el modal antes (sin IVA) sigue en la respuesta, pero ya no es lo que se pinta.
        assert (r[0]['price'], r[0]['total_dscto'], r[0]['total'], r[0]['total_iva']) == (869.57, 86.96, 782.61, 117.39)
        assert r[0]['product']['name'] == 'PRODUCTO UN-A' and r[0]['product']['short_name'].startswith('PRODUCTO UN-A (')
        # La suma de lo que pinta el modal es el total de la factura (lo que pagó el cliente).
        assert sum(D(d['total_con_iva']) for d in r) == venta.total == D('975.00')

    def test_factura_anterior_al_cambio(self, web, empresa, comprador, dueno):  # noqa: F811
        venta = venta_anterior(empresa, comprador, dueno)
        r = web.post(VENTAS, {'action': 'search_detail_products', 'id': venta.pk}).json()
        assert [d['con_iva_incluido'] for d in r] == [False, False]
        # Lo que el modal mostraba y sigue mostrando: nombre del producto y precio, descuento y total guardados (sin IVA).
        assert [(d['product']['short_name'].split(' (')[0], d['price'], d['cant'], d['total_dscto'], d['total']) for d in r] == [
            ('PRODUCTO ANT15', 8.75, 2, 1.75, 15.75), ('PRODUCTO ANT5', 3.33, 3, 0.0, 9.99)]
        assert [d['descripcion'] for d in r] == ['PRODUCTO ANT15', 'PRODUCTO ANT5']

    def test_nota_de_credito_con_precios_con_iva(self, web, empresa, comprador, sri):  # noqa: F811
        p = producto_con(empresa, 'UN-NC', '1000.00')
        assert vender(web, comprador, [linea(p, cant=3, dscto=10, descripcion='Equipo')], sri)['resp']
        venta = ultima_venta(empresa)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        detalle = leer(empresa, lambda: venta.saledetail_set.get())
        r = web.post(f'{NOTAS}add/', {'action': 'add', 'sale': venta.pk, 'motive': 'Devolución ficticia',
                                      'products': json.dumps([{'id': detalle.pk, 'quantity': 2}])}).json()
        assert r.get('resp') is True, r
        nota = leer(empresa, lambda: CreditNote.objects.get(sale=venta))
        [d] = web.post(NOTAS, {'action': 'search_detail_products', 'id': nota.pk}).json()
        assert (d['descripcion'], d['precio_con_iva'], d['cant'], d['total_con_iva'], d['con_iva_incluido']) == (
            'Equipo', '1000.00', 2, '1800.00', True)
        assert D(d['total_con_iva']) == nota.total

    @pytest.mark.parametrize('plantilla', sorted(MODALES))
    def test_el_modal_pinta_con_el_modulo_comun(self, plantilla):
        guion, precio_anterior = MODALES[plantilla]
        html = RAIZ.joinpath(plantilla).read_text(encoding='utf-8')
        assert 0 < html.index("{% static 'js/fp-detalle-lineas.js' %}") < html.index("{% static '" + guion + "' %}")
        js = RAIZ.joinpath('core/pos/static', guion).read_text(encoding='utf-8')
        modal = js[js.index('a[rel="detail"]'):]
        modal = modal[:modal.index("$('#myModalDetails').modal('show')")]
        assert f"fpDetalleLineas.opciones('#tblProducts', {{" in modal and f"}}, '{precio_anterior}'));" in modal
        assert "'action': 'search_detail_products'" in modal and 'columns' not in modal and 'toFixed' not in modal
        # Las líneas se pintan en el orden guardado (el del comprobante), no ordenadas por nombre.
        assert 'order: [],' in RAIZ.joinpath('static/js/fp-detalle-lineas.js').read_text(encoding='utf-8')

    def test_los_listados_cargan_el_modulo(self, web):  # noqa: F811
        for url in (VENTAS, NOTAS):
            html = web.get(url).content.decode()
            assert 'js/fp-detalle-lineas.js' in html and html.index('js/fp-detalle-lineas.js') < html.index('/js/list.js'), url


# ---------------------------------------------------------------- nota de crédito: lo que recibe la pantalla

class TestLineasDeLaNotaDeCredito:

    def buscar(self, web, venta):  # noqa: F811
        [fila] = web.post(f'{NOTAS}add/', {'action': 'search_sale', 'term': venta.voucher_number_full}).json()
        return fila['detail']

    def test_factura_con_precios_con_iva_y_nota_parcial(self, web, empresa, comprador, sri):  # noqa: F811
        p = producto_con(empresa, 'UN-P', '1000.00')
        assert vender(web, comprador, [linea(p, cant=3, descripcion='Equipo')], sri)['resp']
        venta = ultima_venta(empresa)
        [d] = self.buscar(web, venta)
        assert (d['con_iva_incluido'], d['precio_con_iva'], d['descripcion'], d['cant'], d['quantity'], d['dscto'], d['tarifa'],
                d['state']) == (True, '1000.00', 'Equipo', 3, 3, 0.0, 15.0, 0)
        assert d['price'] == 869.57   # con el precio sin IVA de 2 decimales, 2 unidades darían 2000,01: la pantalla no lo usa
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = web.post(f'{NOTAS}add/', {'action': 'add', 'sale': venta.pk, 'motive': 'Devolución parcial ficticia',
                                      'products': json.dumps([{'id': d['id'], 'quantity': 2, 'dscto': 50}])}).json()
        assert r.get('resp') is True, r
        nota = leer(empresa, lambda: CreditNote.objects.get(sale=venta))
        esperado = precios_iva.calcular('1000.00', 2, 0, 15)   # el descuento que envíe la pantalla no cuenta: es el de la factura
        assert (nota.total, nota.subtotal_12, nota.total_iva) == (D('2000.00'), esperado.base, esperado.iva) == (
            D('2000.00'), D('1739.13'), D('260.87'))
        [d] = self.buscar(web, venta)
        assert (d['cant'], d['quantity']) == (3, 1)   # queda una unidad por acreditar

    def test_una_linea_sin_marcar_no_se_acredita(self, web, empresa, comprador, sri):  # noqa: F811
        a, b = producto_con(empresa, 'UN-M1', '1000.00'), producto_con(empresa, 'UN-M2', '25.00', tarifa='0')
        assert vender(web, comprador, [linea(a), linea(b, cant=3)], sri)['resp']
        venta = ultima_venta(empresa)
        lineas = self.buscar(web, venta)
        lineas[0]['state'], lineas[1]['state'] = 0, 1          # como las envía la pantalla: la primera, sin marcar
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = web.post(f'{NOTAS}add/', {'action': 'add', 'sale': venta.pk, 'motive': 'Solo la segunda línea',
                                      'products': json.dumps(lineas)}).json()
        assert r.get('resp') is True, r
        nota = leer(empresa, lambda: CreditNote.objects.get(sale=venta))
        acreditadas = leer(empresa, lambda: [(d.product.code, d.cant) for d in nota.creditnotedetail_set.all()])
        assert acreditadas == [('UN-M2', 3)] and nota.total == D('75.00')
        ninguna = [dict(d, state=0) for d in self.buscar(web, venta)]
        r = web.post(f'{NOTAS}add/', {'action': 'add', 'sale': venta.pk, 'motive': 'Ninguna', 'products': json.dumps(ninguna)}).json()
        assert 'error' in r and leer(empresa, lambda: CreditNote.objects.filter(sale=venta).count()) == 1
        js = RAIZ.joinpath('core/pos/static/credit_note/admin/js/form.js').read_text(encoding='utf-8')
        assert "JSON.stringify(credit_note.detail.products.filter(value => value.state === 1))" in js

    def test_factura_anterior_al_cambio(self, web, empresa, comprador, dueno):  # noqa: F811
        venta = venta_anterior(empresa, comprador, dueno, autorizada=True)
        lineas = self.buscar(web, venta)
        assert [(d['con_iva_incluido'], d['price'], d['dscto'], d['tarifa'], d['quantity']) for d in lineas] == [
            (False, 8.75, 10.0, 15.0, 2), (False, 3.33, 0.0, 5.0, 3)]

    def test_la_pantalla_calcula_con_el_modulo_de_importes(self, web):  # noqa: F811
        html = web.get(f'{NOTAS}add/').content.decode()
        assert 0 < html.index('js/fp-importes.js') < html.index('credit_note/admin/js/form.js')
        assert 'P. unitario con IVA' in html and 'Total con IVA' in html and 'id="fp-nc-rotulo-dscto"' in html
        js = RAIZ.joinpath('core/pos/static/credit_note/admin/js/form.js').read_text(encoding='utf-8')
        assert 'fpImportes.lineaSegura({precio_con_iva: linea.precio_con_iva, cant: linea.quantity' in js
        assert 'name="dscto_unitary"' not in js   # el descuento es el de la factura: se muestra, no se edita


# ---------------------------------------------------------------- catálogo

class TestListadoDeProductos:

    def test_precio_de_venta_y_de_promocion_con_iva(self, web, empresa):  # noqa: F811
        p = producto_con(empresa, 'UN-CAT', '1000.00')
        q = producto_con(empresa, 'UN-PROMO', '11.50')
        with company_context(empresa):
            promo = Promotions.objects.create(start_date='2026-11-01', end_date='2026-12-31', state=True)
            PromotionsDetail.objects.create(promotion=promo, product=q, price_current=q.pvp, dscto=D('0.10'),
                                            total_dscto=D('1.00'), price_final=D('9.00'))
        filas = {f['code']: f for f in web.post('/pos/product/', {'action': 'search'}).json()}
        assert (filas['UN-CAT']['precio_con_iva_catalogo'], filas['UN-CAT']['pvp'], filas['UN-CAT']['price_promotion']) == (
            '1000.00', 869.57, 0.0)
        assert (filas['UN-PROMO']['precio_con_iva_catalogo'], filas['UN-PROMO']['precio_con_iva'],
                filas['UN-PROMO']['price_promotion']) == ('11.50', '10.35', 9.0)
        html = web.get('/pos/product/').content.decode()
        assert 'P./Venta <small>con IVA</small>' in html and 'P./Promoción <small>con IVA</small>' in html
        js = RAIZ.joinpath('core/pos/static/product/js/list.js').read_text(encoding='utf-8')
        assert '{data: "precio_con_iva_catalogo"}' in js and '{data: "pvp"}' not in js
        assert leer(empresa, lambda: Product.objects.get(pk=p.pk).pvp) == D('869.57')   # pvp sigue derivándose
