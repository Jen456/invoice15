import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.management import call_command

from core.tenancy.models import ROLE_OWNER
from tests import helpers


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker, tmp_path_factory):
    """Instalación base (módulos, roles y administrador de plataforma) una vez por sesión."""
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
def grupo_cliente(db):
    return Group.objects.get(name='Cliente')


@pytest.fixture
def empresa(db):
    return helpers.crear_empresa('EMPRESA A')


@pytest.fixture
def empresa_b(db):
    return helpers.crear_empresa('EMPRESA B')


@pytest.fixture
def admin(db, empresa):
    """Propietario de la empresa A (no es superusuario)."""
    return helpers.crear_usuario('propietario.a', empresa, ROLE_OWNER)


@pytest.fixture
def superusuario(db):
    return helpers.crear_usuario('plataforma', superusuario=True)
