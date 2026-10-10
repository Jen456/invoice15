import json

import pytest

from core.pos.models import Product
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ADMIN, ROLE_OWNER
from tests import helpers

pytestmark = pytest.mark.django_db


def test_la_sesion_solo_guarda_identificadores(client, admin, empresa):
    helpers.iniciar_sesion(client, admin)
    client.get('/dashboard/')  # con una sola empresa, el middleware la selecciona
    assert client.session['company_id'] == empresa.id
    assert 'group' not in client.session and 'group_id' not in client.session
    json.dumps(dict(client.session.items()))


def test_no_se_puede_cambiar_a_una_empresa_sin_membresia(client, admin, empresa, empresa_b):
    helpers.iniciar_sesion(client, admin)
    assert client.post('/empresas/cambiar/', {'company': empresa_b.id}).status_code == 404
    assert client.session['company_id'] == empresa.id


def test_un_company_id_manipulado_en_la_sesion_no_da_acceso(client, admin, empresa, empresa_b):
    helpers.crear_producto(empresa, 'A-1')
    helpers.crear_producto(empresa_b, 'B-1')
    helpers.iniciar_sesion(client, admin)
    session = client.session
    session['company_id'] = empresa_b.id
    session.save()
    datos = client.post('/pos/product/', {'action': 'search'}).json()
    assert [p['code'] for p in datos] == ['A-1']
    assert client.session['company_id'] == empresa.id


def test_post_sin_permiso_devuelve_403_y_get_redirige(client, empresa):
    grupo = helpers.crear_grupo('Solo categorías', ['view_category'])
    user = helpers.crear_usuario('vendedor', empresa, grupo)
    helpers.iniciar_sesion(client, user)
    assert client.post('/user/', {'action': 'search'}).status_code == 403
    assert client.get('/user/').status_code == 302
    assert client.post('/pos/category/', {'action': 'search'}).status_code == 200


def test_entrar_como_otro_usuario_solo_superusuario(client, admin, empresa):
    personal = helpers.crear_usuario('personal', empresa, ROLE_ADMIN)
    helpers.iniciar_sesion(client, personal)
    respuesta = client.post('/user/', {'action': 'login_with_user', 'id': admin.id})
    assert respuesta.status_code == 403
    assert int(client.session['_auth_user_id']) == personal.id


def test_superusuario_entra_en_una_empresa_y_como_otro_usuario(client, superusuario, empresa):
    otro = helpers.crear_usuario('otro', empresa, ROLE_ADMIN)
    helpers.iniciar_sesion(client, superusuario, empresa=empresa)
    respuesta = client.post('/user/', {'action': 'login_with_user', 'id': otro.id})
    assert respuesta.status_code == 200
    assert int(client.session['_auth_user_id']) == otro.id


def test_restablecer_clave_exige_permiso_de_cambio(client, admin, empresa):
    grupo = helpers.crear_grupo('Consulta de usuarios', ['view_user'])
    user = helpers.crear_usuario('consulta', empresa, grupo)
    helpers.iniciar_sesion(client, user)
    assert client.post('/user/', {'action': 'reset_password', 'id': admin.id}).status_code == 403
    admin.refresh_from_db()
    assert not admin.check_password(admin.username)


def test_un_cliente_no_ve_datos_del_dashboard(client, empresa):
    cliente = helpers.crear_cliente('cliente1', empresa, '0900000001', '0990000001')
    helpers.iniciar_sesion(client, cliente.user)
    assert client.post('/dashboard/', {'action': 'get_graph_purchase_vs_sale'}).status_code == 403


def test_rutas_de_la_plataforma_solo_superusuario(client, admin):
    helpers.iniciar_sesion(client, admin)
    assert client.post('/security/group/', {'action': 'search'}).status_code == 403
    assert client.get('/plataforma/').status_code == 302


class TestImpresionDeVentas:

    @pytest.fixture
    def escenario(self, empresa, admin):
        cliente_a = helpers.crear_cliente('cliente.a', empresa, '0900000001', '0990000001')
        cliente_b = helpers.crear_cliente('cliente.b', empresa, '0900000002', '0990000002')
        venta_b = helpers.crear_venta(empresa, cliente_b, admin, helpers.crear_producto(empresa))
        return cliente_a, cliente_b, venta_b

    def test_un_cliente_no_imprime_ventas_ajenas(self, client, escenario):
        cliente_a, _, venta_b = escenario
        helpers.iniciar_sesion(client, cliente_a.user)
        assert client.get(f'/pos/sale/client/print/invoice/{venta_b.id}/').status_code == 302

    def test_un_cliente_imprime_sus_ventas(self, client, escenario):
        _, cliente_b, venta_b = escenario
        helpers.iniciar_sesion(client, cliente_b.user)
        respuesta = client.get(f'/pos/sale/client/print/invoice/{venta_b.id}/')
        assert respuesta['Content-Type'] == 'application/pdf'

    def test_personal_sin_permiso_de_ventas_no_imprime(self, client, escenario, empresa):
        _, _, venta_b = escenario
        user = helpers.crear_usuario('vendedor', empresa, helpers.crear_grupo('Solo categorías', ['view_category']))
        helpers.iniciar_sesion(client, user)
        assert client.get(f'/pos/sale/admin/print/invoice/{venta_b.id}/').status_code == 302


def test_cantidad_de_productos_por_empresa(empresa, empresa_b):
    helpers.crear_producto(empresa, 'A-1')
    with company_context(empresa_b):
        assert Product.objects.count() == 0
