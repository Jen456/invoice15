"""Las líneas de la factura y de la nota de crédito salen en el orden en que se ingresaron (XML, RIDE y ticket), también
después de modificar una línea. Sin ORDER BY, PostgreSQL devuelve las filas en su orden físico, que un UPDATE puede
cambiar; ese desorden no se puede forzar en una prueba, así que además se comprueba que la consulta ordene por id."""
from decimal import Decimal

import pytest
from django.db import connection
from django.template.loader import render_to_string
from django.test.utils import CaptureQueriesContext
from lxml import etree

from core.pos.models import CreditNote, CreditNoteDetail, Product, SaleDetail
from core.tenancy.context import company_context
from tests import helpers
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, producto  # noqa: F401

pytestmark = pytest.mark.django_db
CODIGOS = ['L-A', 'L-B', 'L-C']


def ordena_por_id(consulta, tabla):
    with CaptureQueriesContext(connection) as capturadas:
        list(consulta)
    return f'ORDER BY "{tabla}"."id" ASC' in capturadas.captured_queries[-1]['sql']


@pytest.fixture
def venta(empresa, comprador, dueno):  # noqa: F811
    with company_context(empresa):
        base = helpers.crear_producto(empresa, 'L-A')
        venta = helpers.crear_venta(empresa, comprador, dueno, base, cantidad=1)
        for codigo in CODIGOS[1:]:
            p = Product.objects.create(name=f'PRODUCTO {codigo}', code=codigo, category=base.category, price=Decimal('1'), pvp=Decimal('2'))
            SaleDetail.objects.create(sale=venta, product=p, cant=1, price=Decimal('2'))
        primera = SaleDetail.objects.filter(sale=venta).order_by('pk').first()
        primera.cant = 3
        primera.save()                      # la primera línea, modificada después de crear las otras
        venta.calculate_detail()            # y todas recalculadas (más UPDATE)
        venta.calculate_invoice()
        return venta


def test_factura_xml_y_ride_en_orden_de_ingreso(empresa, venta):  # noqa: F811
    with company_context(empresa):
        assert [d.product.code for d in venta.saledetail_set.all()] == CODIGOS
        assert ordena_por_id(venta.saledetail_set.all(), 'pos_saledetail')
        xml, _ = venta.generate_xml()
        html = render_to_string('sale/format/invoice.html', {'sale': venta, 'company': venta.company})
    assert [d.findtext('codigoPrincipal') for d in etree.fromstring(xml.encode()).iterfind('detalles/detalle')] == CODIGOS
    assert html.index('L-A') < html.index('L-B') < html.index('L-C')


def test_nota_de_credito_en_orden_de_ingreso(empresa, venta):  # noqa: F811
    with company_context(empresa):
        nota = CreditNote.objects.create(sale=venta, company=empresa, receipt=venta.receipt, voucher_number='000000001',
                                         voucher_number_full='001-001-000000001', motive='Prueba de orden')
        for detalle in reversed(list(venta.saledetail_set.all())):   # ingresadas al revés: C, B, A
            CreditNoteDetail.objects.create(credit_note=nota, sale_detail=detalle, product=detalle.product, cant=1, price=detalle.price)
        nota.calculate_detail()
        assert [d.product.code for d in nota.creditnotedetail_set.all()] == list(reversed(CODIGOS))
        assert ordena_por_id(nota.creditnotedetail_set.all(), 'pos_creditnotedetail')
