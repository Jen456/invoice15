import json

import pytest

from core.user.models import User
from tests import helpers

pytestmark = pytest.mark.django_db


def test_la_sesion_guarda_identificadores(client, admin, grupo_admin):
    helpers.iniciar_sesion(client, admin)
    assert client.session['group_id'] == grupo_admin.id
    assert 'group' not in client.session
    json.dumps(dict(client.session.items()))


def test_no_se_puede_elegir_un_perfil_ajeno(client, grupo_admin):
    grupo = helpers.crear_grupo('Solo categorías', ['view_category'])
    user = helpers.crear_usuario('vendedor', grupos=[grupo])
    helpers.iniciar_sesion(client, user)
    client.get(f'/user/choose/profile/{grupo_admin.id}/')
    assert client.session['group_id'] == grupo.id


def test_un_id_de_grupo_manipulado_no_da_acceso(client, grupo_admin):
    grupo = helpers.crear_grupo('Solo categorías', ['view_category'])
    user = helpers.crear_usuario('vendedor', grupos=[grupo])
    helpers.iniciar_sesion(client, user)
    session = client.session
    session['group_id'] = grupo_admin.id
    session.save()
    respuesta = client.post('/user/', {'action': 'search'})
    assert respuesta.status_code == 403


def test_post_sin_permiso_devuelve_403_y_get_redirige(client):
    grupo = helpers.crear_grupo('Solo categorías', ['view_category'])
    user = helpers.crear_usuario('vendedor', grupos=[grupo])
    helpers.iniciar_sesion(client, user)
    assert client.post('/user/', {'action': 'search'}).status_code == 403
    assert client.get('/user/').status_code == 302
    assert client.post('/pos/category/', {'action': 'search'}).status_code == 200


def test_entrar_como_otro_usuario_solo_superusuario(client, admin, grupo_admin):
    personal = helpers.crear_usuario('personal', grupos=[grupo_admin])
    helpers.iniciar_sesion(client, personal)
    respuesta = client.post('/user/', {'action': 'login_with_user', 'id': admin.id})
    assert respuesta.status_code == 403
    assert int(client.session['_auth_user_id']) == personal.id


def test_superusuario_puede_entrar_como_otro_usuario(client, admin, grupo_admin):
    otro = helpers.crear_usuario('otro', grupos=[grupo_admin])
    helpers.iniciar_sesion(client, admin)
    respuesta = client.post('/user/', {'action': 'login_with_user', 'id': otro.id})
    assert respuesta.status_code == 200
    assert int(client.session['_auth_user_id']) == otro.id


def test_restablecer_clave_exige_permiso_de_cambio(client, admin):
    grupo = helpers.crear_grupo('Consulta de usuarios', ['view_user'])
    user = helpers.crear_usuario('consulta', grupos=[grupo])
    helpers.iniciar_sesion(client, user)
    respuesta = client.post('/user/', {'action': 'reset_password', 'id': admin.id})
    assert respuesta.status_code == 403
    admin.refresh_from_db()
    assert not admin.check_password(admin.username)


def test_un_cliente_no_ve_datos_del_dashboard(client, grupo_cliente):
    cliente = helpers.crear_cliente('cliente1', grupo_cliente, '0900000001', '0990000001')
    helpers.iniciar_sesion(client, cliente.user)
    respuesta = client.post('/dashboard/', {'action': 'get_graph_purchase_vs_sale'})
    assert respuesta.status_code == 403


class TestImpresionDeVentas:

    @pytest.fixture
    def escenario(self, empresa, admin, grupo_cliente):
        cliente_a = helpers.crear_cliente('cliente.a', grupo_cliente, '0900000001', '0990000001')
        cliente_b = helpers.crear_cliente('cliente.b', grupo_cliente, '0900000002', '0990000002')
        venta_b = helpers.crear_venta(empresa, cliente_b, admin, helpers.crear_producto())
        return cliente_a, cliente_b, venta_b

    def test_un_cliente_no_imprime_ventas_ajenas(self, client, escenario):
        cliente_a, _, venta_b = escenario
        helpers.iniciar_sesion(client, cliente_a.user)
        respuesta = client.get(f'/pos/sale/client/print/invoice/{venta_b.id}/')
        assert respuesta.status_code == 302

    def test_un_cliente_imprime_sus_ventas(self, client, escenario):
        _, cliente_b, venta_b = escenario
        helpers.iniciar_sesion(client, cliente_b.user)
        respuesta = client.get(f'/pos/sale/client/print/invoice/{venta_b.id}/')
        assert respuesta['Content-Type'] == 'application/pdf'

    def test_personal_sin_permiso_de_ventas_no_imprime(self, client, escenario):
        _, _, venta_b = escenario
        grupo = helpers.crear_grupo('Solo categorías', ['view_category'])
        user = helpers.crear_usuario('vendedor', grupos=[grupo])
        helpers.iniciar_sesion(client, user)
        respuesta = client.get(f'/pos/sale/admin/print/invoice/{venta_b.id}/')
        assert respuesta.status_code == 302
