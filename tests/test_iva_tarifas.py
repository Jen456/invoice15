"""IVA por producto: cada producto con su tarifa (15 %, 5 %, 0 %, exento o no objeto, tabla 17 del SRI) y una factura que
mezcla tarifas. La línea guarda la tarifa con la que se vendió; el XML agrupa <totalConImpuestos> por código de porcentaje
y la nota de crédito usa la tarifa de la línea que acredita."""
import importlib
import json
from decimal import Decimal

import pytest
from django.apps import apps
from django.template.loader import render_to_string
from lxml import etree

from core.comprobantes import liquidaciones
from core.pos.forms import ProductForm
from core.pos.models import CreditNote, Product, Sale, SaleDetail, impuestos_por_tarifa
from core.pos.views.product.views import tarifa_desde_excel
from core.tenancy.context import company_context
from tests import helpers
from tests.test_emision_sri import VENTAS, comprador, dueno, empresa, leer, p12, sri, venta_de, web  # noqa: F401
from tests.test_liquidaciones import nueva_compra
from tests.test_rimpe import XSD, validar

pytestmark = pytest.mark.django_db

# (código, tarifa, precio, cantidad): 15 % → 20,00 + 3,00; 5 % → 9,99 + 0,50 (0,4995 redondeado); 0 % 4,00; exento 2,50; no objeto 1,00
LINEAS = (('4', 'P15', '10.00', 2), ('5', 'P05', '3.33', 3), ('0', 'P00', '4.00', 1), ('7', 'PEX', '2.50', 1), ('6', 'PNO', '1.00', 1))


def producto(empresa, tarifa, codigo, pvp):  # noqa: F811
    with company_context(empresa):
        p = helpers.crear_producto(empresa, codigo, pvp=pvp)
        p.tarifa_iva = tarifa
        p.save()
        return p


@pytest.fixture
def productos(empresa):  # noqa: F811
    return {tarifa: (producto(empresa, tarifa, codigo, pvp), cantidad) for tarifa, codigo, pvp, cantidad in LINEAS}


@pytest.fixture
def factura(web, empresa, comprador, productos, sri):  # noqa: F811
    sri.respuestas_autorizacion = ['AUTORIZADO']
    lineas = [{'id': p.pk, 'cant': cantidad, 'price_current': str(p.pvp), 'dscto': 0} for p, cantidad in productos.values()]
    r = web.post(f'{VENTAS}add/', {'action': 'add', 'receipt': '01', 'client': comprador.pk, 'payment_type': 'efectivo',
                                   'date_joined': '2026-10-11', 'cash': '100', 'change': '0', 'time_limit': '0',
                                   'payment_method': '01', 'additional_info': '[]', 'products': json.dumps(lineas)}).json()
    assert r.get('resp') is True, r
    return venta_de(empresa, 271)


def impuestos(nodo):
    return [(i.findtext('codigoPorcentaje'), i.findtext('baseImponible'), i.findtext('valor'))
            for i in nodo.findall('infoFactura/totalConImpuestos/totalImpuesto') + nodo.findall('infoNotaCredito/totalConImpuestos/totalImpuesto')]


class TestFacturaConVariasTarifas:

    def test_totales(self, factura):
        assert (factura.subtotal_12, factura.subtotal_0, factura.total_iva, factura.total) == (
            Decimal('29.99'), Decimal('7.50'), Decimal('3.50'), Decimal('40.99'))

    def test_xml_valido_contra_el_xsd_y_agrupado_por_tarifa(self, factura):
        ok, errores, documento = validar(factura.xml_signed, XSD / 'factura' / 'factura_V1.0.0.xsd')
        assert ok, errores
        assert impuestos(documento) == [('4', '20.00', '3.00'), ('5', '9.99', '0.50'), ('0', '4.00', '0.00'),
                                        ('6', '1.00', '0.00'), ('7', '2.50', '0.00')]
        lineas = [(d.findtext('impuestos/impuesto/codigoPorcentaje'), d.findtext('impuestos/impuesto/tarifa'),
                   d.findtext('impuestos/impuesto/valor')) for d in documento.findall('detalles/detalle')]
        assert lineas == [('4', '15.00', '3.00'), ('5', '5.00', '0.50'), ('0', '0.00', '0.00'), ('7', '0.00', '0.00'), ('6', '0.00', '0.00')]
        assert documento.findtext('infoFactura/totalSinImpuestos') == '37.49' and documento.findtext('infoFactura/importeTotal') == '40.99'

    def test_la_linea_conserva_su_tarifa_si_el_producto_cambia(self, empresa, factura, productos):  # noqa: F811
        p5, _ = productos['5']
        with company_context(empresa):
            p5.tarifa_iva = '4'
            p5.save()
            venta = Sale.objects.get(pk=factura.pk)
            venta.calculate_detail()
            venta.calculate_invoice()
            assert SaleDetail.objects.get(sale=venta, product=p5).codigo_porcentaje == '5'
            assert venta.total == Decimal('40.99')

    def test_ride_con_una_fila_por_tarifa(self, empresa, factura):  # noqa: F811
        with company_context(empresa):
            venta = Sale.objects.get(pk=factura.pk)
            html = render_to_string('sale/format/invoice.html', {'sale': venta, 'company': venta.company})
        for texto in ('Subtotal 15 %', 'Subtotal 5 %', 'Subtotal 0 %', 'Subtotal exento de IVA', 'Subtotal no objeto de IVA',
                      'IVA 15 %', 'IVA 5 %'):
            assert texto in html, texto
        assert 'IVA 0 %' not in html and 'IVA exento' not in html

    def test_nota_de_credito_sobre_la_linea_del_5(self, web, empresa, factura, productos, sri):  # noqa: F811
        p5, _ = productos['5']
        detalle = leer(empresa, lambda: SaleDetail.objects.get(sale=factura, product=p5))
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = web.post('/pos/credit/note/admin/add/', {'action': 'add', 'sale': factura.pk, 'motive': 'Devolución', 'create_electronic_invoice': 'on',
                                                     'products': json.dumps([{'id': detalle.pk, 'quantity': 2, 'price': '0.01', 'dscto': 0}])}).json()
        assert r.get('resp') is True, r
        nota = leer(empresa, lambda: CreditNote.objects.get(sale=factura))
        ok, errores, documento = validar(nota.xml_signed, XSD / 'notacredito' / 'NotaCredito_V1.1.0.xsd')
        assert ok, errores
        assert impuestos(documento) == [('5', '6.66', '0.33')] and nota.total == Decimal('6.99')
        assert documento.findtext('detalles/detalle/impuestos/impuesto/tarifa') == '5.00'


class TestProducto:

    def test_la_tarifa_manda_sobre_se_cobra_impuesto(self, empresa):  # noqa: F811
        assert [producto(empresa, t, f'T{t}', '1.00').with_tax for t in ('4', '5', '0', '7', '6')] == [True, True, False, False, False]

    def test_productos_anteriores_toman_su_tarifa(self, empresa):  # noqa: F811
        with company_context(empresa):
            sin_iva = helpers.crear_producto(empresa, 'VIEJO0', con_iva=False)
            con_iva = helpers.crear_producto(empresa, 'VIEJO15', con_iva=True)
            assert (sin_iva.tarifa_iva, con_iva.tarifa_iva) == ('0', '4')
            assert sin_iva.toJSON()['tarifa'] == 0 and con_iva.toJSON()['tarifa'] == 15 and con_iva.toJSON()['nombre_tarifa'] == '15 %'

    def test_formulario_con_tarifa(self, web, empresa):  # noqa: F811
        html = web.get('/pos/product/add/').content.decode()
        assert 'name="tarifa_iva"' in html and 'No objeto de IVA' in html and 'name="with_tax"' not in html
        with company_context(empresa):
            categoria = helpers.crear_producto(empresa, 'CAT').category
        r = web.post('/pos/product/add/', {'action': 'add', 'name': 'MEDICINA', 'code': 'MED-1', 'category': categoria.pk,
                                           'price': '1.00', 'pvp': '2.00', 'inventoried': 'on', 'tarifa_iva': '5'}).json()
        assert 'error' not in r, r
        with company_context(empresa):
            nuevo = Product.objects.get(code='MED-1')
        assert (nuevo.tarifa_iva, nuevo.with_tax) == ('5', True)
        with company_context(empresa):
            assert ProductForm(instance=helpers.crear_producto(empresa, 'SIN', con_iva=False)).initial['tarifa_iva'] == '0'

    @pytest.mark.parametrize('valor, codigo', [('15 %', '4'), (15, '4'), (0.15, '4'), ('5%', '5'), (5.0, '5'), ('0 %', '0'), (0, '0'),
                                               ('Exento', '7'), ('exento de IVA', '7'), ('No objeto', '6'), (None, ''), ('12', ''), ('si', '')])
    def test_columna_tarifa_del_excel(self, valor, codigo):
        assert tarifa_desde_excel(valor) == codigo

    def test_liquidacion_sugiere_la_tarifa_del_producto(self, empresa):  # noqa: F811
        compra = nueva_compra(empresa, lineas=(('ARROZ', 'Arroz', True, 1, '10.00'), ('ABONO', 'Abono', True, 1, '10.00'),
                                               ('LIBRO', 'Libro', False, 1, '10.00')))
        with company_context(empresa):
            Product.objects.filter(code='ABONO-501').update(tarifa_iva='5')
            Product.objects.filter(code='LIBRO-501').update(tarifa_iva='7')
            assert [l['tarifa'] for l in liquidaciones.lineas_de_compra(compra)] == [Decimal('15.00'), Decimal('5.00'), Decimal('0.00')]


class TestDatosAnteriores:

    def test_lineas_antiguas_sin_impuesto_no_suman_iva(self, empresa):  # noqa: F811
        # Antes, la línea de un producto sin impuesto guardaba un IVA calculado que la factura no cobraba.
        with company_context(empresa):
            p = helpers.crear_producto(empresa, 'ANT', con_iva=False)
            linea = SaleDetail(product=p, total=Decimal('10.00'), total_iva=Decimal('1.50'), codigo_porcentaje='')
            assert impuestos_por_tarifa([linea]) == [{'codigo': '0', 'nombre': '0 %', 'tarifa': Decimal('0'),
                                                      'base': Decimal('10.00'), 'valor': Decimal('0.00')}]

    def test_migracion_asigna_tarifas(self, empresa, dueno, comprador):  # noqa: F811
        migracion = importlib.import_module('core.pos.migrations.0016_tarifa_iva_existentes')
        con_iva, sin_iva = helpers.crear_producto(empresa, 'M15'), helpers.crear_producto(empresa, 'M00', con_iva=False)
        venta_12 = helpers.crear_venta(empresa, comprador, dueno, con_iva)
        venta_15 = helpers.crear_venta(empresa, comprador, dueno, sin_iva)
        with company_context(empresa):
            Sale.objects.filter(pk=venta_12.pk).update(iva=Decimal('0.12'))
            Sale.objects.filter(pk=venta_15.pk).update(iva=Decimal('0.15'))
            for v in (venta_12, venta_15):
                SaleDetail.objects.create(sale=v, product=con_iva, cant=1, price=Decimal('1'))
            Product.objects.filter(pk__in=(con_iva.pk, sin_iva.pk)).update(tarifa_iva='')
            SaleDetail.objects.filter(sale__in=(venta_12, venta_15)).update(codigo_porcentaje='')
            migracion.poblar(apps, None)
            assert dict(Product.objects.filter(pk__in=(con_iva.pk, sin_iva.pk)).values_list('code', 'tarifa_iva')) == {'M15': '4', 'M00': '0'}
            codigos = sorted(SaleDetail.objects.filter(sale__in=(venta_12, venta_15)).values_list('sale_id', 'product__code', 'codigo_porcentaje'))
        assert codigos == sorted([(venta_12.pk, 'M15', '2'), (venta_12.pk, 'M15', '2'), (venta_15.pk, 'M00', '0'), (venta_15.pk, 'M15', '4')])
