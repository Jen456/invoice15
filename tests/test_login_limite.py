import pytest

from tests import helpers

pytestmark = pytest.mark.django_db


def test_bloqueo_tras_intentos_fallidos_aun_con_clave_correcta(client, admin, settings):
    for _ in range(settings.FPA_LOGIN_MAX_INTENTOS):
        client.post('/login/', {'username': admin.username, 'password': 'incorrecta'})
    respuesta = client.post('/login/', {'username': admin.username, 'password': helpers.CLAVE})
    assert '_auth_user_id' not in client.session
    assert 'Demasiados intentos' in respuesta.content.decode()


def test_el_bloqueo_es_por_ip(client, admin, settings):
    for _ in range(settings.FPA_LOGIN_MAX_INTENTOS):
        client.post('/login/', {'username': admin.username, 'password': 'incorrecta'}, HTTP_X_REAL_IP='203.0.113.1')
    client.post('/login/', {'username': admin.username, 'password': helpers.CLAVE}, HTTP_X_REAL_IP='203.0.113.2')
    assert '_auth_user_id' in client.session


def test_un_inicio_correcto_reinicia_el_contador(client, admin, settings):
    for _ in range(settings.FPA_LOGIN_MAX_INTENTOS - 1):
        client.post('/login/', {'username': admin.username, 'password': 'incorrecta'})
    helpers.iniciar_sesion(client, admin)
    client.logout()
    client.post('/login/', {'username': admin.username, 'password': 'incorrecta'})
    helpers.iniciar_sesion(client, admin)


def test_limite_en_recuperacion_de_clave(client, settings):
    for _ in range(settings.FPA_LOGIN_MAX_INTENTOS):
        client.post('/login/reset/password/', {'username': 'nadie'})
    respuesta = client.post('/login/reset/password/', {'username': 'nadie'})
    assert 'Demasiados intentos' in respuesta.json()['error']
