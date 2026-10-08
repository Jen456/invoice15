import os

import pytest
from django.conf import settings as dj_settings

from tests import helpers

pytestmark = pytest.mark.django_db


@pytest.fixture
def archivos():
    raiz = dj_settings.MEDIA_ROOT
    rutas = {
        'imagen': 'product/2026/10/08/foto.png',
        'firma': 'company/2026/10/08/firma.p12',
        'respaldo': 'backup/2026/10/08/base.backup',
        'svg': 'company/2026/10/08/logo.svg',
    }
    for relativa in rutas.values():
        completa = os.path.join(raiz, relativa)
        os.makedirs(os.path.dirname(completa), exist_ok=True)
        with open(completa, 'wb') as f:
            f.write(b'contenido')
    return rutas


def test_requiere_sesion(client, archivos):
    respuesta = client.get('/media/' + archivos['imagen'])
    assert respuesta.status_code == 302 and '/login/' in respuesta['Location']


def test_entrega_a_usuario_autenticado(client, admin, archivos):
    helpers.iniciar_sesion(client, admin)
    respuesta = client.get('/media/' + archivos['imagen'])
    assert respuesta.status_code == 200
    assert b''.join(respuesta.streaming_content) == b'contenido'


@pytest.mark.parametrize('clave', ['firma', 'respaldo'])
def test_firmas_y_respaldos_nunca_se_entregan(client, admin, archivos, clave):
    helpers.iniciar_sesion(client, admin)
    assert client.get('/media/' + archivos[clave]).status_code == 404


def test_no_permite_salir_de_la_carpeta(client, admin, archivos):
    helpers.iniciar_sesion(client, admin)
    assert client.get('/media/product/../../../etc/passwd').status_code == 404
    assert client.get('/media/%2e%2e/%2e%2e/etc/passwd').status_code == 404


def test_x_accel_redirect_en_servidor(client, admin, archivos, settings):
    settings.FPA_X_ACCEL_PREFIX = '/_privado'
    helpers.iniciar_sesion(client, admin)
    respuesta = client.get('/media/' + archivos['imagen'])
    assert respuesta['X-Accel-Redirect'] == '/_privado/' + archivos['imagen']
    assert respuesta.content == b''


def test_svg_aislado_con_csp(client, admin, archivos):
    helpers.iniciar_sesion(client, admin)
    respuesta = client.get('/media/' + archivos['svg'])
    assert 'sandbox' in respuesta['Content-Security-Policy']
