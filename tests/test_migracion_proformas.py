"""proformas 0003 (módulo «Proformas» en el grupo «Cotizaciones») sobre una base que ya tiene menú, el caso de producción:
en proceso con el registro real (SQLite y PostgreSQL) y por subproceso con SQLite en archivo (`migrate proformas zero` y
`migrate` sobre una instalación hecha con start_installation)."""
import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from django.apps import apps as registro
from django.contrib.auth.models import Group

from core.security.models import GroupModule, Module, ModuleType
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER

RAIZ = Path(__file__).resolve().parent.parent
MIGRACION = importlib.import_module('core.proformas.migrations.0003_modulo_proformas')
TODOS = ['add_proforma', 'change_proforma', 'delete_proforma', 'view_proforma']
ESPERADOS = {ROLE_OWNER: TODOS, ROLE_ADMIN: TODOS, ROLE_SELLER: ['add_proforma', 'change_proforma', 'view_proforma'],
             ROLE_ACCOUNTANT: ['view_proforma'], ROLE_READONLY: ['view_proforma'], ROLE_CLIENT: []}


def permisos(rol):
    return sorted(Group.objects.get(name=rol).permissions.filter(content_type__app_label='proformas')
                  .values_list('codename', flat=True))


def resto_del_menu():
    return (sorted(Module.objects.exclude(url='/proformas/').values_list('url', 'name', 'orden', 'module_type__name')),
            sorted(ModuleType.objects.exclude(name='Cotizaciones').values_list('name', 'icon', 'orden')),
            {rol: (sorted(Group.objects.get(name=rol).groupmodule_set.exclude(module__url='/proformas/')
                          .values_list('module__url', flat=True)),
                   sorted(Group.objects.get(name=rol).permissions.exclude(content_type__app_label='proformas')
                          .values_list('codename', flat=True))) for rol in ESPERADOS})


def conteos():
    return Module.objects.count(), ModuleType.objects.count(), GroupModule.objects.count()


@pytest.mark.django_db
def test_0003_backwards_y_forwards_con_el_registro_real():
    resto, antes = resto_del_menu(), conteos()
    assert {rol: permisos(rol) for rol in ESPERADOS} == ESPERADOS
    MIGRACION.backwards(registro, None)
    assert not Module.objects.filter(url='/proformas/').exists()
    assert not ModuleType.objects.filter(name='Cotizaciones').exists()
    assert not GroupModule.objects.filter(module__url='/proformas/').exists()
    assert all(permisos(rol) == [] for rol in ESPERADOS)
    assert resto_del_menu() == resto
    MIGRACION.forwards(registro, None)
    modulo = Module.objects.select_related('module_type').get(url='/proformas/')
    assert (modulo.module_type.name, modulo.module_type.orden, modulo.orden, modulo.name) == ('Cotizaciones', 15, 1, 'Proformas')
    assert sorted(modulo.permissions.values_list('codename', flat=True)) == TODOS
    assert {rol: permisos(rol) for rol in ESPERADOS} == ESPERADOS
    assert conteos() == antes and resto_del_menu() == resto
    MIGRACION.forwards(registro, None)   # otra vez: no duplica nada
    assert conteos() == antes and Module.objects.filter(url='/proformas/').count() == 1
    assert registro.get_app_config('proformas').models_module is importlib.import_module('core.proformas.models')


def manage(env, *args, stdin=None):
    resultado = subprocess.run([sys.executable, 'manage.py', *args], cwd=RAIZ, env=env, input=stdin,
                               capture_output=True, text=True, timeout=900)
    assert resultado.returncode == 0, resultado.stderr[-3000:]
    return resultado.stdout


def verificar(env):
    salida = manage(env, 'shell', stdin=(RAIZ / 'tests/escenarios/proformas_menu_verificar.py').read_text())
    return json.loads(salida.split('RESULTADO=')[1])


def test_0003_en_una_instalacion_existente(tmp_path):
    # La base va en memoria compartida si existe: start_installation hace miles de escrituras y, con SQLite en disco,
    # cada una espera al disco (unos 200 s frente a unos 40 s).
    memoria = '/dev/shm' if os.path.isdir('/dev/shm') and os.access('/dev/shm', os.W_OK) else None
    with tempfile.TemporaryDirectory(prefix='fpa-proformas-menu-', dir=memoria) as base:
        instalar_y_migrar(tmp_path, Path(base) / 'menu.db')


def instalar_y_migrar(tmp_path, base):
    # Variables explícitas, como en test_migracion_empresa_inicial: el proceso de pytest ya tiene DATABASE_URL.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('FPA_', 'DATABASE_URL', 'SECRET_KEY', 'DEBUG'))}
    env.update({'FPA_ENV_FILE': os.devnull, 'DJANGO_SETTINGS_MODULE': 'config.settings', 'SECRET_KEY': 'proformas-menu',
                'DEBUG': 'True', 'DATABASE_URL': f'sqlite:///{base}', 'FPA_ARCHIVOS': str(tmp_path / 'media')})
    manage(env, 'migrate', '-v', '0')   # base nueva: la 0003 no hace nada (Module vacío)
    manage(env, 'start_installation', '--admin-correo', 'admin@example.com',
           '--archivo-credenciales', str(tmp_path / 'admin.txt'))
    inicial = verificar(env)
    assert inicial['modulo'] == {'nombre': 'Proformas', 'icono': 'fas fa-file-contract', 'orden': 1, 'grupo': 'Cotizaciones',
                                 'orden_grupo': 15, 'permisos': TODOS}
    assert inicial['permisos'] == ESPERADOS and inicial['grupo'] is True
    assert inicial['en_menu'] == {rol: rol != ROLE_CLIENT for rol in ESPERADOS}
    manage(env, 'migrate', 'proformas', 'zero', '-v', '0')
    sin_app = verificar(env)
    assert sin_app['modulo'] is None and sin_app['grupo'] is False
    assert all(not v for v in sin_app['permisos'].values()) and not any(sin_app['en_menu'].values())
    assert sin_app['resto'] == inicial['resto']
    manage(env, 'migrate', '-v', '0')   # el camino de producción: la app se instala sobre una base con menú
    assert verificar(env) == inicial
