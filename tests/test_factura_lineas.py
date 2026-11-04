"""Líneas de la factura validadas en el servidor (core/pos/lineas_venta.py) y precio particular de la línea.

- El precio de una línea es de la factura: se guarda en SaleDetail y va al XML, pero nunca cambia Product.
- Cambiarlo exige `change_product` (quien ya fija precios en el catálogo); una factura que sale de una proforma conserva
  el precio de la proforma aunque la emita el Vendedor. El resto factura al precio vigente del catálogo.
- Cantidad entera de 1 a 999999, precio de 0 a 999999,99 con 2 decimales, descuento entero de 0 a 100, sin productos
  repetidos ni de otra empresa: un error no crea la venta, no consume número y no toca el stock.
- El stock baja con F() y solo si alcanza; la condición y la forma de pago se validan contra sus opciones.
- Alta de cliente desde la factura con su permiso y con los errores de los dos formularios; código de producto repetido
  con mensaje claro."""
import json
from decimal import Decimal

import pytest
from django.test import Client as ClienteWeb

from core.pos import lineas_venta, notas_credito
from core.pos.forms import ProductForm
from core.pos.models import Category, Product, Receipt, Sale, SaleDetail
from core.pos.views.sale.views import PLAZO_CREDITO
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_SELLER
from tests import helpers
from tests.test_emision_sri import VENTAS, comprador, dueno, empresa, leer, p12, sri, web  # noqa: F401
from tests.test_proformas_conversion import aceptada, emitir, precarga, productos  # noqa: F401

pytestmark = pytest.mark.django_db


def datos(cliente, lineas, **extra):
    base = {'action': 'add', 'receipt': '01', 'client': cliente.pk, 'payment_type': 'efectivo', 'date_joined': '2026-10-11',
            'cash': '1000', 'change': '0', 'time_limit': '0', 'payment_method': '01', 'additional_info': '[]',
            'products': json.dumps(lineas) if not isinstance(lineas, str) else lineas}
    base.update(extra)
    return base


def linea(producto, cant=1, precio=None, dscto=0):
    return {'id': producto.pk, 'cant': cant, 'price_current': str(producto.pvp if precio is None else precio), 'dscto': dscto}


@pytest.fixture
def producto(empresa):
    return helpers.crear_producto(empresa, 'PRC1', pvp='10.00')   # inventariado, stock 100


def foto(empresa, producto):
    """Lo que un error no debe cambiar: ventas, secuencias y stock."""
    return leer(empresa, lambda: (Sale.objects.count(), sorted(Receipt.objects.values_list('pk', 'sequence')),
                                  Product.objects.get(pk=producto.pk).stock))


def sesion(client, empresa, usuario):
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    return client


class TestPrecioDeLaLinea:

    def test_precio_particular_no_cambia_el_catalogo(self, web, empresa, comprador, producto, sri):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = web.post(f'{VENTAS}add/', datos(comprador, [linea(producto, cant=2, precio='8.75', dscto=10)])).json()
        assert r.get('resp') is True, r
        venta = leer(empresa, lambda: Sale.objects.latest('id'))
        d = leer(empresa, lambda: SaleDetail.objects.get(sale=venta))
        assert (d.price, d.subtotal, d.total_dscto, d.total) == (Decimal('8.75'), Decimal('17.50'), Decimal('1.75'), Decimal('15.75'))
        assert venta.total == Decimal('18.11')   # 15,75 + 15 % (2,3625 → 2,36)
        assert '<precioUnitario>8.75</precioUnitario>' in venta.xml_signed and '<descuento>1.75</descuento>' in venta.xml_signed
        catalogo = leer(empresa, lambda: Product.objects.get(pk=producto.pk))
        assert (catalogo.pvp, catalogo.stock) == (Decimal('10.00'), 98)

    def test_precio_cero_se_admite(self, web, empresa, comprador, producto, sri):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = web.post(f'{VENTAS}add/', datos(comprador, [linea(producto, precio='0'), ], cash='0')).json()
        assert r.get('resp') is True, r
        assert leer(empresa, lambda: SaleDetail.objects.get().price) == Decimal('0.00')

    def test_sin_permiso_se_factura_al_precio_del_catalogo(self, client, empresa, comprador, producto, sri):
        vendedor = helpers.crear_usuario('vendedor.precio', empresa, ROLE_SELLER)
        web_v = sesion(client, empresa, vendedor)
        antes = foto(empresa, producto)
        r = web_v.post(f'{VENTAS}add/', datos(comprador, [linea(producto, precio='7.00')])).json()
        assert r['error'] == lineas_venta.PRECIO_SIN_PERMISO.format(nombre=producto.name, catalogo='10.00')
        assert foto(empresa, producto) == antes
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert web_v.post(f'{VENTAS}add/', datos(comprador, [linea(producto)])).json().get('resp') is True

    def test_la_proforma_conserva_su_precio_aunque_la_emita_el_vendedor(self, client, empresa, comprador, aceptada, sri):
        vendedor = helpers.crear_usuario('vendedor.proforma', empresa, ROLE_SELLER)
        web_v = sesion(client, empresa, vendedor)
        datos_pf = precarga(web_v, aceptada)
        with company_context(empresa):   # el catálogo cambió después de la proforma: la factura respeta su precio
            Product.objects.filter(code=datos_pf['lineas'][0]['code']).update(pvp=Decimal('99.00'))
        otro = json.loads(json.dumps(datos_pf))
        otro['lineas'][0]['price_current'] = 1.23   # ni el de la proforma ni el del catálogo: necesita el permiso
        assert 'no coincide con el del catálogo' in emitir(web_v, aceptada, comprador, otro)['error']
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = emitir(web_v, aceptada, comprador, datos_pf)
        assert r.get('resp') is True, r

    def test_la_pantalla_ofrece_el_campo_solo_con_permiso(self, web, client, empresa):
        assert 'data-precio-editable="1"' in web.get(f'{VENTAS}add/').content.decode()
        vendedor = helpers.crear_usuario('vendedor.pantalla', empresa, ROLE_SELLER)
        pagina = sesion(client, empresa, vendedor).get(f'{VENTAS}add/').content.decode()
        assert 'data-precio-editable="0"' in pagina


class TestLineasInvalidas:

    @pytest.mark.parametrize('cambio, texto', [
        ({'price_current': '-1'}, 'El precio va de 0 a 999999,99'),
        ({'price_current': '10.005'}, 'El precio va de 0 a 999999,99'),
        ({'price_current': 'NaN'}, 'El precio va de 0 a 999999,99'),
        ({'price_current': '1000000'}, 'El precio va de 0 a 999999,99'),
        ({'cant': 0}, 'La cantidad es un número entero'),
        ({'cant': -2}, 'La cantidad es un número entero'),
        ({'cant': '1.5'}, 'La cantidad es un número entero'),
        ({'dscto': '12.5'}, 'El descuento es un porcentaje entero'),
        ({'dscto': 150}, 'El descuento es un porcentaje entero'),
    ])
    def test_rechazo_sin_efectos(self, web, empresa, comprador, producto, cambio, texto):
        antes = foto(empresa, producto)
        r = web.post(f'{VENTAS}add/', datos(comprador, [{**linea(producto), **cambio}])).json()
        assert texto in r['error'] and r['error'].startswith('Línea 1')
        assert foto(empresa, producto) == antes

    def test_lista_vacia_repetidos_y_de_otra_empresa(self, web, empresa, empresa_b, comprador, producto):
        antes = foto(empresa, producto)
        assert web.post(f'{VENTAS}add/', datos(comprador, [])).json()['error'] == lineas_venta.SIN_LINEAS
        assert web.post(f'{VENTAS}add/', datos(comprador, 'no es json')).json()['error'] == lineas_venta.SIN_LINEAS
        repetido = web.post(f'{VENTAS}add/', datos(comprador, [linea(producto), linea(producto)])).json()
        assert 'repetido' in repetido['error']
        ajeno = helpers.crear_producto(empresa_b, 'AJENO', pvp='5.00')
        assert web.post(f'{VENTAS}add/', datos(comprador, [linea(ajeno)])).json()['error'] == 'Línea 1: El producto no existe.'
        assert foto(empresa, producto) == antes

    def test_stock_insuficiente_y_justo(self, web, empresa, comprador, producto, sri):
        with company_context(empresa):
            Product.objects.filter(pk=producto.pk).update(stock=3)
        antes = foto(empresa, producto)
        r = web.post(f'{VENTAS}add/', datos(comprador, [linea(producto, cant=5)])).json()
        assert r['error'] == lineas_venta.SIN_STOCK.format(nombre=producto.name, stock=3)
        assert foto(empresa, producto) == antes
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert web.post(f'{VENTAS}add/', datos(comprador, [linea(producto, cant=3)])).json().get('resp') is True
        assert leer(empresa, lambda: Product.objects.get(pk=producto.pk).stock) == 0

    def test_condicion_y_forma_de_pago_validas(self, web, empresa, comprador, producto):
        antes = foto(empresa, producto)
        r = web.post(f'{VENTAS}add/', datos(comprador, [linea(producto)], payment_type='trueque')).json()
        assert r['error'] == 'Elige la condición de pago: contado o crédito.'
        r = web.post(f'{VENTAS}add/', datos(comprador, [linea(producto)], payment_method='99')).json()
        assert r['error'] == 'Elige la forma de pago del SRI.'
        assert foto(empresa, producto) == antes

    @pytest.mark.parametrize('plazo', ['', 'mañana', '2026-02-30'])
    def test_credito_exige_fecha_de_plazo(self, web, empresa, comprador, producto, plazo):
        antes = foto(empresa, producto)
        r = web.post(f'{VENTAS}add/', datos(comprador, [linea(producto)], payment_type='credito', end_credit=plazo, cash='0')).json()
        assert r['error'] == PLAZO_CREDITO
        assert foto(empresa, producto) == antes


class TestAltasDesdeLaFactura:

    def test_cliente_exige_su_permiso_y_junta_los_errores(self, web, empresa):
        grupo = helpers.crear_grupo('CAJERO SIN CLIENTES', ['add_sale', 'view_sale'])
        cajero = helpers.crear_usuario('cajero.sin.clientes', empresa, grupo)
        web_c = sesion(ClienteWeb(), empresa, cajero)
        assert web_c.post(f'{VENTAS}add/', {'action': 'create_client', 'names': 'X', 'dni': '0912345670', 'empresa': empresa.pk}).json() == \
            {'error': 'Tu perfil no puede crear clientes.'}
        errores = web.post(f'{VENTAS}add/', {'action': 'create_client', 'email': 'no-es-correo', 'empresa': empresa.pk}).json()['error']
        assert 'email' in errores and 'dni' in errores   # los de ClientUserForm y los de ClientForm juntos

    def test_codigo_repetido_con_mensaje_claro(self, web, empresa, producto, monkeypatch):
        categoria = leer(empresa, lambda: Category.objects.first())
        datos_p = {'action': 'add', 'name': 'OTRO', 'code': producto.code.lower(), 'category': categoria.pk, 'price': '1.00',
                   'pvp': '2.00', 'tarifa_iva': '4', 'inventoried': 'on'}
        r = web.post('/pos/product/add/', datos_p).json()
        assert r['error']['code'] == ['Ya existe un producto con este código en tu empresa: búscalo en el catálogo.']
        monkeypatch.setattr(ProductForm, 'clean_code', lambda self: self.cleaned_data['code'])   # otra pestaña lo creó a la vez
        r = web.post('/pos/product/add/', {**datos_p, 'code': producto.code}).json()
        assert r == {'error': 'Ya existe un producto con ese código o nombre en esta empresa: búscalo en el catálogo.'}
        assert leer(empresa, lambda: Product.objects.filter(code__iexact=producto.code).count()) == 1


def test_la_venta_solo_baja_el_stock(web, empresa, comprador, producto, sri):
    """La venta baja el stock con una actualización (F) y no reescribe el resto del producto."""
    with company_context(empresa):
        Product.objects.filter(pk=producto.pk).update(name='NOMBRE EDITADO')
    sri.respuestas_autorizacion = ['AUTORIZADO']
    assert web.post(f'{VENTAS}add/', datos(comprador, [linea(producto)])).json().get('resp') is True
    catalogo = leer(empresa, lambda: Product.objects.get(pk=producto.pk))
    assert (catalogo.name, catalogo.pvp, catalogo.stock) == ('NOMBRE EDITADO', Decimal('10.00'), 99)


def test_editar_un_producto_con_codigo_tomado_a_la_vez(web, empresa, producto, monkeypatch):
    otro = helpers.crear_producto(empresa, 'PRC2', pvp='3.00')
    categoria = leer(empresa, lambda: Category.objects.first())
    monkeypatch.setattr(ProductForm, 'clean_code', lambda self: self.cleaned_data['code'])   # la otra pestaña ganó la carrera
    r = web.post(f'/pos/product/update/{otro.pk}/', {'action': 'edit', 'name': otro.name, 'code': producto.code, 'category': categoria.pk,
                                                     'price': '1.00', 'pvp': '3.00', 'tarifa_iva': '4', 'inventoried': 'on'}).json()
    assert r == {'error': 'Ya existe un producto con ese código o nombre en esta empresa: búscalo en el catálogo.'}
    assert leer(empresa, lambda: Product.objects.get(pk=otro.pk).code) == 'PRC2'


def test_la_nota_de_credito_devuelve_stock_sin_pisar_otra_venta(empresa, comprador, dueno, producto, monkeypatch):
    """Entre la lectura del producto y la devolución, otra venta baja 3 unidades: la nota suma con F() y no las pierde."""
    from django.db import transaction
    from django.db.models import F

    from core.configuracion import servicios as cfg
    from tests.ayudas_ventas import factura_autorizada
    venta = factura_autorizada(empresa, comprador, dueno, producto, cantidad=5)          # stock 100 → 95
    original = cfg.receipt_para_emitir

    def con_otra_venta(*args, **kwargs):
        Product.objects.filter(pk=producto.pk).update(stock=F('stock') - 3)               # venta simultánea: 95 → 92
        return original(*args, **kwargs)
    monkeypatch.setattr(cfg, 'receipt_para_emitir', con_otra_venta)
    with company_context(empresa):
        with transaction.atomic():
            notas_credito.crear(empresa, venta.pk, None, 'Devolución de prueba')        # devuelve 5: 92 → 97
    assert leer(empresa, lambda: Product.objects.get(pk=producto.pk).stock) == 97
