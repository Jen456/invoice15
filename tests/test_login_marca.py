"""Pantalla de acceso con la marca FacturaPorAquí: textos, CSRF, next y errores."""
import pytest

from tests import helpers

pytestmark = pytest.mark.django_db


def test_textos_y_marca(client):
    html = client.get('/login/').content.decode()
    for texto in ('FacturaPorAquí', 'Tu negocio, en orden', 'Bienvenido de nuevo', '>Usuario<', '>Contraseña<',
                  '>Ingresar<', 'Recuperar acceso', 'fpa-auth.css', 'lang="es"'):
        assert texto in html, texto
    assert 'name="csrfmiddlewaretoken"' in html
    assert 'autocomplete="current-password"' in html and 'autocomplete="username"' in html


def test_conserva_el_parametro_next(client, admin):
    html = client.get('/login/?next=/pos/product/').content.decode()
    assert 'name="next" value="/pos/product/"' in html
    respuesta = client.post('/login/?next=/pos/product/', {'username': admin.username, 'password': helpers.CLAVE,
                                                          'next': '/pos/product/'})
    assert respuesta.status_code == 302 and respuesta['Location'] == '/pos/product/'


def test_next_externo_no_se_sigue(client, admin):
    respuesta = client.post('/login/', {'username': admin.username, 'password': helpers.CLAVE,
                                        'next': 'https://sitio-ajeno.example/'})
    assert respuesta['Location'] == '/dashboard/'


def test_error_de_credenciales_dentro_de_la_tarjeta(client, admin):
    html = client.post('/login/', {'username': admin.username, 'password': 'incorrecta'}).content.decode()
    assert 'class="fpa-alert" role="alert"' in html
    assert '_auth_user_id' not in client.session


def test_recuperar_acceso_con_la_marca(client):
    html = client.get('/login/reset/password/').content.decode()
    assert 'Recuperar acceso' in html and 'Enviar enlace' in html and 'name="csrfmiddlewaretoken"' in html


def test_nueva_clave_aplica_las_reglas_de_contrasena(client, admin):
    admin.is_change_password = True
    admin.email_reset_token = 'token-prueba'
    admin.save()
    datos = client.post('/login/update/password/token-prueba/', {'password': '123', 'confirm_password': '123'}).json()
    assert 'error' in datos
    admin.refresh_from_db()
    assert admin.check_password(helpers.CLAVE)
