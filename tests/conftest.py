import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.management import call_command

from tests import helpers


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker, tmp_path_factory):
    """Instalación base (módulos, perfiles y administrador) una sola vez por sesión."""
    credenciales = tmp_path_factory.mktemp('cred') / 'admin.txt'
    with django_db_blocker.unblock():
        call_command('start_installation', admin_correo='admin@example.com', archivo_credenciales=str(credenciales))


@pytest.fixture(autouse=True)
def limpiar_cache(request):
    if 'django_db' not in request.keywords and 'db' not in request.fixturenames:
        yield
        return
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def grupo_admin(db):
    return Group.objects.get(name='Administrador')


@pytest.fixture
def grupo_cliente(db):
    return Group.objects.get(name='Cliente')


@pytest.fixture
def admin(db, grupo_admin):
    return helpers.crear_usuario('admin.pruebas', grupos=[grupo_admin], superusuario=True)


@pytest.fixture
def empresa(db):
    return helpers.crear_empresa()
