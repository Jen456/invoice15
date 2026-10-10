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
    empresa = Company.objects.get(ruc='0990000000001')
    assert not empresa.electronic_signature
    assert empresa.electronic_signature_key == '' and empresa.email_host_password == ''
    assert not User.objects.filter(email__iregex=r'davila|gmail').exists()


@pytest.mark.django_db
def test_instalacion_crea_los_roles_de_empresa():
    from django.contrib.auth.models import Group
    from core.tenancy.models import COMPANY_ROLES
    nombres = set(Group.objects.values_list('name', flat=True))
    assert set(COMPANY_ROLES) <= nombres
    propietario = Group.objects.get(name='Propietario')
    urls = set(propietario.groupmodule_set.values_list('module__url', flat=True))
    assert '/pos/sale/admin/' in urls and '/security/group/' not in urls
    consulta = Group.objects.get(name='Consulta')
    assert not consulta.permissions.filter(codename__startswith='delete_').exists()


@pytest.mark.django_db
def test_demo_crea_membresias_de_cliente_por_empresa():
    from core.tenancy.models import Membership
    call_command('insert_test_data', confirmar_datos_ficticios=True, ruc='0990000000001')
    call_command('insert_test_data', confirmar_datos_ficticios=True, ruc='0990000002001', nombre='OTRA DEMO')
    consumidor = User.objects.get(username='9999999999999')
    assert Membership.objects.filter(user=consumidor).count() == 2


@pytest.mark.django_db
def test_demo_con_propietario_para_revisar_pantallas(tmp_path):
    from core.tenancy.models import Membership
    ruta = tmp_path / 'propietario.txt'
    call_command('insert_test_data', confirmar_datos_ficticios=True, propietario='dueno.demo', archivo_credenciales=str(ruta))
    assert stat.S_IMODE(os.stat(ruta).st_mode) == 0o600
    assert Membership.objects.get(user__username='dueno.demo').group.name == 'Propietario'
