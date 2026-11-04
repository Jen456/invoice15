"""Usar como base: lecturas autorizadas sin reservar números y alta normal con otra secuencia.

Reutiliza las acciones existentes; el SRI, los correos y la firma son los dobles ficticios de las pruebas.
"""
from decimal import Decimal

import pytest

from core.pos.models import Product, Receipt, Sale, SaleDetail
from core.tenancy.context import company_context
from tests import helpers
from tests.test_emision_sri import VENTAS, comprador, dueno, empresa, leer, p12, sri, web  # noqa: F401
from tests.test_factura_lineas import datos, linea

pytestmark = pytest.mark.django_db


@pytest.fixture
def origen(web, empresa, comprador, sri):
    producto = helpers.crear_producto(empresa, 'BASE-DEMO', pvp='10.00')
    sri.respuestas_autorizacion = ['AUTORIZADO']
    resultado = web.post(f'{VENTAS}add/', datos(comprador, [linea(producto, cant=3, precio='8.50', dscto=5)])).json()
    assert resultado.get('resp') is True, resultado
    return leer(empresa, lambda: Sale.objects.latest('pk'))


def estado(empresa):
    return leer(empresa, lambda: (
        list(Sale.objects.values('id', 'client_id', 'voucher_number_full', 'access_code', 'status', 'total')),
        list(Receipt.objects.values_list('id', 'sequence').order_by('id')),
        list(Product.objects.values_list('id', 'stock', 'pvp').order_by('id')),
    ))


def test_cargar_y_reintentar_no_crea_factura_ni_reserva_numero(web, empresa, origen):
    antes = estado(empresa)
    for _ in range(2):
        pagina = web.get(f'{VENTAS}add/?base={origen.pk}&empresa={empresa.pk}')
        assert pagina.status_code == 200
        detalle = web.post(VENTAS, {'action': 'search_detail_products', 'id': origen.pk}).json()
        assert [(d['cant'], d['price'], d['dscto']) for d in detalle] == [(3, 8.5, 5)]
        assert detalle[0]['product']['price_current'] == 10
        numero = web.post(f'{VENTAS}add/', {'action': 'search_voucher_number', 'receipt': '01'}).json()
        assert numero['voucher_number'] != origen.voucher_number
    assert estado(empresa) == antes


def test_origen_de_otra_empresa_y_sin_permiso_no_entrega_lineas(web, empresa, origen):
    otra = helpers.crear_empresa('OTRA FICTICIA')
    usuario = helpers.crear_usuario('otro.dueno.base', otra)
    helpers.iniciar_sesion(web, usuario, empresa=otra)
    assert web.post(VENTAS, {'action': 'search_detail_products', 'id': origen.pk}).json() == []
    grupo = helpers.crear_grupo('BASE SOLO CREAR', ['add_sale'])
    usuario = helpers.crear_usuario('base.sin.lectura', empresa, grupo)
    helpers.iniciar_sesion(web, usuario, empresa=empresa)
    assert web.post(VENTAS, {'action': 'search_detail_products', 'id': origen.pk}).status_code == 403


def test_nueva_factura_con_otro_cliente_respeta_secuencia_y_original(web, empresa, origen, sri):
    cliente = helpers.crear_cliente('otro.comprador.base', empresa, '0997777777001', '0990000000')
    original = estado(empresa)[0]
    detalle = web.post(VENTAS, {'action': 'search_detail_products', 'id': origen.pk}).json()
    # La interfaz manda únicamente datos editables al alta normal, nunca duplica la fila Sale.
    productos = [{'id': d['product']['id'], 'cant': d['cant'], 'price_current': d['price'], 'dscto': d['dscto']}
                 for d in detalle]
    for _ in range(2):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        respuesta = web.post(f'{VENTAS}add/', datos(cliente, productos, voucher_number=origen.voucher_number)).json()
        assert respuesta.get('resp') is True, respuesta
    with company_context(empresa):
        nuevas = list(Sale.objects.exclude(pk=origen.pk).order_by('pk'))
        assert [int(v.voucher_number) for v in nuevas] == [int(origen.voucher_number) + 1, int(origen.voucher_number) + 2]
        assert all(v.client_id == cliente.pk and v.receipt_id == origen.receipt_id for v in nuevas)
        assert len({origen.access_code, *(v.access_code for v in nuevas)}) == 3
        assert list(SaleDetail.objects.filter(sale__in=nuevas).values_list('price', flat=True)) == [Decimal('8.50')] * 2
        assert Product.objects.get(pk=productos[0]['id']).pvp == Decimal('10.00')
    assert [fila for fila in estado(empresa)[0] if fila['id'] == origen.pk] == original


def test_opcion_exige_permiso_de_crear(web, empresa):
    pagina = web.get(VENTAS).content.decode()
    assert '"add_sale": true' in pagina
    grupo = helpers.crear_grupo('BASE SOLO CONSULTAR', ['view_sale'])
    usuario = helpers.crear_usuario('base.solo.consulta', empresa, grupo)
    helpers.iniciar_sesion(web, usuario, empresa=empresa)
    pagina = web.get(VENTAS).content.decode()
    assert '"add_sale": false' in pagina
    assert web.get(f'{VENTAS}add/?base=1&empresa={empresa.pk}').status_code == 302


def test_descuentos_que_en_coma_flotante_no_dan_enteros(web, empresa, comprador, sri):  # noqa: F811
    """0.07 × 100 = 7.000000000000001 en coma flotante: el detalle entrega el porcentaje exacto que base.js exige entero."""
    producto = helpers.crear_producto(empresa, 'BASE-DSCTO-7', pvp='10.00')
    otro = helpers.crear_producto(empresa, 'BASE-DSCTO-29', pvp='4.00')
    sri.respuestas_autorizacion = ['AUTORIZADO']
    r = web.post(f'{VENTAS}add/', datos(comprador, [linea(producto, dscto=7), linea(otro, dscto=29)])).json()
    assert r.get('resp') is True, r
    venta = leer(empresa, lambda: Sale.objects.latest('pk'))
    detalle = web.post(VENTAS, {'action': 'search_detail_products', 'id': venta.pk}).json()
    assert [d['dscto'] for d in detalle] == [7, 29] and all(float(d['dscto']).is_integer() for d in detalle)
