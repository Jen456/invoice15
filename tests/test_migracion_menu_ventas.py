"""Migraciones de menú y permisos de la Etapa 2 · ventas (O2) con los modelos históricos y el registro real, sobre la base
instalada de las pruebas (con módulos): pos 0031 (anulado en el SRI de factura y NC) y comprobantes 0023 (módulo
«Retenciones recibidas» por organizar_menu y anulado de los cuatro comprobantes adicionales), hacia adelante y hacia
atrás; y sobre una base sin módulos, la 0023 no crea nada."""
import importlib

import pytest
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from core.security import menu
from core.security.models import GroupModule, Module, ModuleType
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER
from tests.test_b0_contratos import estado_menu

pytestmark = pytest.mark.django_db
URL = '/comprobantes/retenciones-recibidas/'
ANULADO = {'/pos/sale/admin/': 'change_anulado_sri_sale', '/pos/credit/note/admin/': 'change_anulado_sri_creditnote',
           '/comprobantes/retenciones/': 'change_anulado_sri_retencion',
           '/comprobantes/liquidaciones/': 'change_anulado_sri_liquidacioncompra',
           '/comprobantes/notas-debito/': 'change_anulado_sri_notadebito', '/comprobantes/guias/': 'change_anulado_sri_guiaremision'}
MIGRACIONES = (('pos', '0031_permisos_anulado_sri'), ('comprobantes', '0023_modulo_retenciones_recibidas'))


def ejecutar(sentido, migraciones=MIGRACIONES):
    loader = MigrationExecutor(connection).loader
    for app, nombre in (migraciones if sentido == 'forwards' else reversed(migraciones)):
        modulo = importlib.import_module(f'core.{app}.migrations.{nombre}')
        getattr(modulo, sentido)(loader.project_state((app, nombre)).apps, None)   # modelos históricos


def codigos_de(rol):
    return set(Group.objects.get(name=rol).permissions.values_list('codename', flat=True))


def test_hacia_adelante_y_hacia_atras_con_modulos():
    instalado = estado_menu()
    # En la instalación de pruebas (start_installation) ya está todo: es el estado esperado tras migrar.
    modulo = Module.objects.get(url=URL)
    assert (modulo.module_type.name, modulo.orden, modulo.name) == ('Administrativo', 3, 'Retenciones recibidas')
    assert set(modulo.permissions.values_list('codename', flat=True)) == {
        'view_retencionrecibida', 'add_retencionrecibida', 'change_retencionrecibida'}
    for url, codigo in ANULADO.items():
        assert Module.objects.get(url=url).permissions.filter(codename=codigo).exists(), url
    ejecutar('backwards')
    tipos, modulos, grupos = estado_menu()
    assert URL not in modulos
    assert all(codigo not in [p[1] for p in modulos[url][5]] for url, codigo in ANULADO.items())
    for rol, (urls, codigos) in grupos.items():
        assert URL not in urls and not (set(ANULADO.values()) | {'view_retencionrecibida'}) & set(codigos), rol
    # El resto del menú queda igual
    sin_o2 = {u: (*m[:5], [p for p in m[5] if p[1] not in ANULADO.values()]) for u, m in instalado[1].items() if u != URL}
    assert modulos == sin_o2 and tipos == instalado[0]
    ejecutar('forwards')
    assert estado_menu() == instalado
    assert Module.objects.filter(url=URL).count() == 1
    menu.organizar_menu(ModuleType, Module, Permission)                    # repetir no duplica
    assert Module.objects.filter(url=URL).count() == 1 and estado_menu() == instalado


def test_permisos_por_rol():
    for rol in (ROLE_OWNER, ROLE_ADMIN):
        assert {'view_retencionrecibida', 'add_retencionrecibida', 'change_retencionrecibida'} | set(ANULADO.values()) \
            <= codigos_de(rol)
    for rol in (ROLE_ACCOUNTANT, ROLE_READONLY):
        assert URL in Group.objects.get(name=rol).groupmodule_set.values_list('module__url', flat=True)
        codigos = codigos_de(rol)
        assert 'view_retencionrecibida' in codigos and not {'add_retencionrecibida', 'change_retencionrecibida'} & codigos
        assert not set(ANULADO.values()) & codigos
    vendedor = Group.objects.get(name=ROLE_SELLER)
    assert URL not in vendedor.groupmodule_set.values_list('module__url', flat=True)
    assert not set(ANULADO.values()) & codigos_de(ROLE_SELLER)


def test_sin_modulos_no_crea_nada():
    GroupModule.objects.all().delete()
    Module.objects.all().delete()
    ejecutar('forwards')
    assert not Module.objects.exists()
    ejecutar('backwards')
    assert not Module.objects.exists()
