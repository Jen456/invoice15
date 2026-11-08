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
def complemento_en_revision(settings):
    """Las pruebas abren el Complemento Contable con «*» (solo vale en local y en pruebas automáticas);
    tests/test_complemento_contable.py comprueba el cierre por defecto y la lista de revisión."""
    settings.FPA_COMPLEMENTO_CONTABLE_REVISION = ['*']


@pytest.fixture(autouse=True)
def diseno_piloto_apagado(settings):
    """Diseño de factura fuera del piloto aunque el entorno exporte FPA_DISENO_FACTURA_PILOTO (FPA_ENV_FILE=/dev/null solo
    anula el archivo .env); las pruebas que lo necesitan lo encienden con el fixture `piloto` de test_diseno_factura."""
    settings.FPA_DISENO_FACTURA_PILOTO = []


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
