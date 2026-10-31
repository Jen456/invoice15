"""Contrato del alta contextual: reutiliza los endpoints con permisos y empresa activa."""
import pytest
from django.db import transaction
from tests import helpers
from core.pos.models import Category, Product, Sale, Receipt
from core.tenancy.context import company_context

pytestmark = pytest.mark.django_db


def test_alta_y_recuperacion_no_emiten_ni_consumen_numeracion(client, empresa, admin):
    helpers.configurar_facturacion(empresa)
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    with company_context(empresa):
        category = Category.objects.create(name='SERVICIOS FICTICIOS')
        numbers = list(Receipt.objects.values_list('pk', 'sequence'))
        count = Sale.objects.count()
    html = client.get('/pos/sale/admin/add/').content.decode()
    assert 'Crear producto aquí' in html and 'fp-product-dialog' in html
    product_form = client.get('/pos/product/add/').content.decode()
    assert f'data-company="{empresa.pk}"' in product_form
    assert 'csrfmiddlewaretoken' in product_form
    data = {'action':'add', 'name':'Servicio ficticio', 'code':'RAPIDO-01', 'category':category.pk,
            'pvp':'10.00', 'price':'0.00', 'tarifa_iva':'4'}
    assert client.post('/pos/product/add/', data).json() == {}
    result = client.post('/pos/sale/admin/add/', {'action':'search_product_code', 'code':'RAPIDO-01'}).json()
    assert result['code'] == 'RAPIDO-01' and result['price_current'] == 10.0 and result['tarifa'] == 15.0
    assert not result['inventoried']
    # Aísla el rechazo SQL en el savepoint de esta petición de prueba.
    with transaction.atomic():
        duplicate = client.post('/pos/product/add/', data).json()
    assert 'error' in duplicate
    with company_context(empresa):
        assert Product.objects.filter(code='RAPIDO-01').count() == 1
        assert Sale.objects.count() == count
        assert list(Receipt.objects.values_list('pk', 'sequence')) == numbers


def test_sin_permiso_de_producto_no_hay_alta_contextual(client, empresa):
    role = helpers.crear_grupo('VENTA SIN ALTA FICTICIA', ['add_sale'])
    user = helpers.crear_usuario('venta.sin.alta', empresa, rol=role)
    helpers.configurar_facturacion(empresa)
    helpers.iniciar_sesion(client, user, empresa=empresa)
    html = client.get('/pos/sale/admin/add/').content.decode()
    assert 'data-product-url=' not in html
    response = client.post('/pos/product/add/', {'action':'add'})
    assert response.status_code == 403


def test_recuperar_codigo_respeta_empresa_activa(client, empresa, empresa_b, admin):
    helpers.configurar_facturacion(empresa)
    producto = helpers.crear_producto(empresa_b, codigo='AJENO-01')
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    result = client.post('/pos/sale/admin/add/', {'action':'search_product_code', 'code':producto.code}).json()
    assert result == {}
