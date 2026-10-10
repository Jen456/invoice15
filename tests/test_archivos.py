import os

import pytest
from django.conf import settings as dj_settings

from tests import helpers

pytestmark = pytest.mark.django_db


def escribir(relativa):
    completa = os.path.join(dj_settings.MEDIA_ROOT, relativa)
    os.makedirs(os.path.dirname(completa), exist_ok=True)
    with open(completa, 'wb') as f:
        f.write(b'contenido')
    return relativa


@pytest.fixture
def archivos(empresa, empresa_b):
    a, b = f'empresas/{empresa.uuid}', f'empresas/{empresa_b.uuid}'
    return {
        'imagen': escribir(f'{a}/productos/2026/10/foto.png'),
        'firma': escribir(f'{a}/firma/2026/10/firma.p12'),
        'respaldo': escribir('backup/2026/10/08/base.backup'),
        'legado': escribir('product/2026/10/08/antiguo.png'),
        'svg': escribir(f'{a}/logo/2026/10/logo.svg'),
        'global': escribir('users/2026/10/08/avatar.png'),
        'otra_empresa': escribir(f'{b}/productos/2026/10/foto.png'),
    }


def test_requiere_sesion(client, archivos):
    respuesta = client.get('/media/' + archivos['imagen'])
    assert respuesta.status_code == 302 and '/login/' in respuesta['Location']


def test_entrega_archivos_de_la_empresa_activa(client, admin, archivos):
    helpers.iniciar_sesion(client, admin)
    respuesta = client.get('/media/' + archivos['imagen'])
    assert respuesta.status_code == 200
    assert b''.join(respuesta.streaming_content) == b'contenido'
    assert client.get('/media/' + archivos['global']).status_code == 200


@pytest.mark.parametrize('clave', ['firma', 'respaldo', 'legado', 'otra_empresa'])
def test_nunca_entrega_firmas_respaldos_ni_archivos_ajenos(client, admin, archivos, clave):
    helpers.iniciar_sesion(client, admin)
    assert client.get('/media/' + archivos[clave]).status_code == 404


def test_no_permite_salir_de_la_carpeta(client, admin, archivos):
    helpers.iniciar_sesion(client, admin)
    assert client.get('/media/users/../../../etc/passwd').status_code == 404
    assert client.get('/media/%2e%2e/%2e%2e/etc/passwd').status_code == 404


def test_x_accel_redirect_opcional(client, admin, archivos, settings):
    settings.FPA_X_ACCEL_PREFIX = '/_privado'
    helpers.iniciar_sesion(client, admin)
    respuesta = client.get('/media/' + archivos['imagen'])
    assert respuesta['X-Accel-Redirect'] == '/_privado/' + archivos['imagen']
    assert respuesta.content == b''


def test_svg_aislado_con_csp(client, admin, archivos):
    helpers.iniciar_sesion(client, admin)
    assert 'sandbox' in client.get('/media/' + archivos['svg'])['Content-Security-Policy']


def test_las_subidas_van_a_la_carpeta_de_su_empresa(empresa):
    producto = helpers.crear_producto(empresa, 'CON-CODIGO')
    assert producto.barcode.name.startswith(f'empresas/{empresa.uuid}/codigos/')
