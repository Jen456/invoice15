"""Registro propio de empresas, confirmación del correo e ingreso con varios identificadores."""
import re
from datetime import timedelta

import pytest
import time_machine
from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from core.login.identificacion import cedula_valida, normalizar_celular, ruc_valido
from core.pos.models import Company
from core.tenancy.models import ROLE_OWNER, AuditLog, Membership
from core.user.models import User
from tests import helpers


def cedula(base9):
    total = 0
    for d, k in zip(base9, (2, 1, 2, 1, 2, 1, 2, 1, 2)):
        p = int(d) * k
        total += p - 9 if p > 9 else p
    return base9 + str((10 - total % 10) % 10)


CEDULA = cedula('171003406')
CLAVE = 'Clave-segura-2026'


def datos(**extra):
    base = {'nombre': 'Ferretería La Esquina', 'identificacion': CEDULA, 'email': 'duena@example.com',
            'celular': '+593 99 123 4567', 'username': 'laesquina', 'password': CLAVE, 'password2': CLAVE,
            'acepto': 'on', 'sitio_web': ''}
    base.update(extra)
    return base


def enlace(correo):
    return re.search(r'https?://[^\s"]+/registro/confirmar/[^\s"/]+/', correo.body).group(0)


class TestIdentificacion:
    def test_cedula(self):
        assert cedula_valida(CEDULA)
        assert not cedula_valida(CEDULA[:9] + str((int(CEDULA[9]) + 1) % 10))
        assert not cedula_valida('25' + CEDULA[2:]) and not cedula_valida('176' + CEDULA[3:])

    def test_ruc(self):
        assert ruc_valido(CEDULA + '001') and not ruc_valido(CEDULA + '000')
        assert ruc_valido('1790012345001') and ruc_valido('1760001230001')
        assert not ruc_valido('1780012345001') and not ruc_valido('17900123450')

    def test_celular(self):
        assert normalizar_celular('+593 99 123 4567') == '0991234567'
        assert normalizar_celular('099-123-4567') == '0991234567'
        assert normalizar_celular('022345678') is None


@pytest.mark.django_db
class TestRegistro:

    def test_alta_completa(self, client):
        respuesta = client.post('/registro/', datos())
        assert respuesta.status_code == 302 and respuesta['Location'] == '/registro/enviado/'
        user = User.objects.get(username='laesquina')
        assert not user.is_active and user.email_verified_at is None and user.phone == '0991234567'
        empresa = Company.objects.get(ruc=CEDULA)
        assert empresa.tradename == 'Ferretería La Esquina'
        assert Membership.objects.get(user=user, company=empresa).group.name == ROLE_OWNER
        assert AuditLog.objects.filter(user=user, action='signup', company=empresa).exists()
        assert len(mail.outbox) == 1 and mail.outbox[0].to == ['duena@example.com']
        assert '/registro/confirmar/' in mail.outbox[0].body
        assert 'd•••@example.com' in client.get('/registro/enviado/').content.decode()

    @pytest.mark.parametrize('cambio, campo', [
        ({'identificacion': '1710034060'}, 'identificacion'),
        ({'celular': '022345678'}, 'celular'),
        ({'password2': 'Otra-clave-2026'}, 'password2'),
        ({'password': '1234567890', 'password2': '1234567890'}, 'password'),
        ({'username': '1234'}, 'username'),
        ({'acepto': ''}, 'acepto'),
    ])
    def test_errores_de_validacion(self, client, cambio, campo):
        respuesta = client.post('/registro/', datos(**cambio))
        assert respuesta.status_code == 200
        assert campo in respuesta.context['form'].errors
        assert not User.objects.filter(username='laesquina').exists()

    def test_duplicados(self, client, admin, empresa):
        User.objects.filter(pk=helpers.crear_usuario('existente').pk).update(email='Duena@Example.com')
        errores = client.post('/registro/', datos(username='PROPIETARIO.A', identificacion=empresa.ruc)).context['form'].errors
        assert {'email', 'username', 'identificacion'} <= set(errores)

    def test_campo_trampa(self, client):
        respuesta = client.post('/registro/', datos(sitio_web='http://spam.example'))
        assert respuesta.status_code == 200 and not User.objects.filter(username='laesquina').exists()

    def test_limite_por_ip(self, client, settings):
        settings.FPA_REGISTRO_MAX_POR_HORA = 2
        for i in range(2):
            client.post('/registro/', datos(username=f'usuario{i}x', email=f'u{i}@example.com',
                                            identificacion=cedula(f'17100340{i}')))
        respuesta = client.post('/registro/', datos())
        assert 'límite de registros' in respuesta.content.decode()


@pytest.mark.django_db
class TestConfirmacionEIngreso:

    @pytest.fixture
    def registrado(self, client):
        client.post('/registro/', datos())
        return User.objects.get(username='laesquina'), enlace(mail.outbox[0])

    def test_no_entra_sin_confirmar(self, client, registrado):
        html = client.post('/login/', {'username': 'laesquina', 'password': CLAVE}).content.decode()
        assert 'aún no está confirmada' in html and '/registro/reenviar/' in html
        assert '_auth_user_id' not in client.session

    def test_confirmar_y_entrar_con_cada_identificador(self, client, registrado):
        user, url = registrado
        assert 'correo está confirmado' in client.get(url).content.decode()
        user.refresh_from_db()
        assert user.is_active and user.email_verified_at is not None
        assert 'no es válido' in client.get(url).content.decode()  # un solo uso
        for identificador in ('laesquina', 'DUENA@example.com', CEDULA):
            client.logout()
            client.post('/login/', {'username': identificador, 'password': CLAVE})
            assert int(client.session['_auth_user_id']) == user.id, identificador
            client.get('/dashboard/')
            assert client.session['company_id'] == Company.objects.get(ruc=CEDULA).id

    def test_enlace_manipulado_o_caducado(self, client, registrado):
        _, url = registrado
        assert 'no es válido' in client.get(url[:-3] + 'xx/').content.decode()
        with time_machine.travel(timezone.now() + timedelta(hours=73)):
            assert 'no es válido' in client.get(url).content.decode()

    def test_correo_ambiguo_no_sirve_para_entrar(self, client, admin):
        otro = helpers.crear_usuario('otro')
        User.objects.filter(pk__in=[admin.pk, otro.pk]).update(email='compartido@example.com')
        client.post('/login/', {'username': 'compartido@example.com', 'password': helpers.CLAVE})
        assert '_auth_user_id' not in client.session

    def test_ruc_con_dos_propietarios_no_sirve_para_entrar(self, client, admin, empresa):
        helpers.crear_usuario('segundo', empresa, ROLE_OWNER)
        client.post('/login/', {'username': empresa.ruc, 'password': helpers.CLAVE})
        assert '_auth_user_id' not in client.session

    def test_reenviar_no_revela_cuentas(self, client, registrado):
        mail.outbox.clear()
        a = client.post('/registro/reenviar/', {'email': 'duena@example.com'}).content.decode()
        b = client.post('/registro/reenviar/', {'email': 'nadie@example.com'}).content.decode()
        assert 'Si hay una cuenta pendiente' in a and 'Si hay una cuenta pendiente' in b
        assert len(mail.outbox) == 1 and mail.outbox[0].to == ['duena@example.com']

    def test_limpieza_de_registros_abandonados(self, client, registrado):
        user, _ = registrado
        call_command('limpiar_registros_pendientes', horas=1)
        assert User.objects.filter(pk=user.pk).exists()  # aún dentro del plazo
        User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(hours=200))
        call_command('limpiar_registros_pendientes', horas=144)
        assert not User.objects.filter(pk=user.pk).exists() and not Company.objects.filter(ruc=CEDULA).exists()

    def test_el_login_ofrece_crear_cuenta(self, client):
        html = client.get('/login/').content.decode()
        assert 'Crea tu cuenta' in html and 'href="/registro/"' in html
