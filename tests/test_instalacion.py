import os
import stat

import pytest
from django.core.management import CommandError, call_command

import config.settings as config_settings
from core.security.management.commands.start_installation import Command as StartInstallation
from core.user.models import User


@pytest.mark.django_db
def test_administrador_sin_clave_predeterminada():
    admin = User.objects.get(username='admin')
    assert admin.is_superuser
    assert not admin.check_password('hacker94')
    assert admin.email == 'admin@example.com'


@pytest.mark.django_db
def test_la_instalacion_no_se_repite(tmp_path):
    with pytest.raises(CommandError):
        call_command('start_installation', admin_correo='x@example.com', archivo_credenciales=str(tmp_path / 'c.txt'))
    assert not (tmp_path / 'c.txt').exists()


def test_credenciales_en_archivo_0600_y_sin_sobrescribir(tmp_path):
    ruta = tmp_path / 'cred.txt'
    StartInstallation().write_credentials(str(ruta), 'admin', 'secreto')
    assert stat.S_IMODE(os.stat(ruta).st_mode) == 0o600
    with pytest.raises(FileExistsError):
        StartInstallation().write_credentials(str(ruta), 'admin', 'otro')


@pytest.mark.django_db
def test_datos_ficticios_exigen_confirmacion():
    with pytest.raises(CommandError):
        call_command('insert_test_data')


@pytest.mark.django_db
def test_datos_ficticios_prohibidos_en_produccion(monkeypatch):
    monkeypatch.setattr(config_settings, 'FPA_ENTORNO', 'produccion')
    with pytest.raises(CommandError):
        call_command('insert_test_data', confirmar_datos_ficticios=True)


@pytest.mark.django_db
def test_datos_ficticios_sin_secretos_de_terceros():
    call_command('insert_test_data', confirmar_datos_ficticios=True)
    from core.pos.models import Company
    empresa = Company.objects.get()
    assert empresa.ruc == '0990000000001'
    assert not empresa.electronic_signature
    assert empresa.electronic_signature_key == '' and empresa.email_host_password == ''
    assert not User.objects.filter(email__iregex=r'davila|gmail').exists()
