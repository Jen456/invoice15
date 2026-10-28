"""Migraciones de Compras (pos 0020–0024): las compras, pagos y gastos anteriores conservan sus datos y quedan marcados como
incompletos sin inventar impuestos (DC1, DC2, DC6); el permiso «Completar datos» llega a Propietario y Administrador."""
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.apps import apps as registro
from django.contrib.auth.models import Group, Permission

from core.security.models import Module
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER

RAIZ = Path(__file__).resolve().parent.parent
NULOS = [None] * 11


def manage(env, *args, stdin=None):
    resultado = subprocess.run([sys.executable, 'manage.py', *args], cwd=RAIZ, env=env, input=stdin,
                               capture_output=True, text=True, timeout=900)
    assert resultado.returncode == 0, resultado.stderr[-3000:]
    return resultado.stdout


def test_compras_anteriores_migran_sin_cambios_y_marcadas(tmp_path):
    # Variables explícitas: el proceso de pytest ya tiene DATABASE_URL y read_env no sobrescribe las existentes.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('FPA_', 'DATABASE_URL', 'SECRET_KEY', 'DEBUG'))}
    env.update({'FPA_ENV_FILE': os.devnull, 'DJANGO_SETTINGS_MODULE': 'config.settings', 'SECRET_KEY': 'compras-antes',
                'DEBUG': 'True', 'DATABASE_URL': f'sqlite:///{tmp_path}/compras.db', 'FPA_ARCHIVOS': str(tmp_path / 'media')})
    manage(env, 'migrate', 'pos', '0019_orden_de_las_lineas', '-v', '0')
    manage(env, 'shell', stdin=(RAIZ / 'tests/escenarios/compras_antes_cargar.py').read_text())
    manage(env, 'migrate', '-v', '0')
    salida = manage(env, 'shell', stdin=(RAIZ / 'tests/escenarios/compras_antes_verificar.py').read_text())
    r = json.loads(salida.split('RESULTADO=')[1])
    assert r['conteos'] == [2, 2, 1, 1, 1, 1, 1]
    # version_datos=1, datos_incompletos=True, fuera_plazo_ats=False, origen manual, cabecera vacía y totales NULL (no 0)
    assert r['compras'] == [['00000123', '50.00', 'efectivo', 1, True, False, 'manual', '', '', '', None] + NULOS,
                            ['00000124', '100.00', 'credito', 1, True, False, 'manual', '', '', '', None] + NULOS]
    assert r['lineas'] == [[5, '10.00', '50.00', True, '', None, None, None, '0.00', ''],
                           [10, '10.00', '100.00', True, '', None, None, None, '0.00', '']]
    assert r['deudas'] == [['100.00', '60.00', True, 'subtotal']]          # deuda y saldo intactos, sin abonos automáticos
    assert r['pagos'] == [['40.00', '', '', None, None]]                   # medio de pago «Sin dato»
    assert r['gastos'] == [['25.50', '', '']]
    assert r['tipos_gasto'] == [['LUZ ELÉCTRICA', '', '']]                 # sustento sin indicar: nada de oficio
    assert r['proveedores'] == [['0990000001001', '', '', None]]
    assert r['stock'] == 7


@pytest.mark.django_db
def test_0024_devuelve_completar_datos_al_modulo_y_a_los_roles_con_escritura():
    modulo = Module.objects.get(url='/pos/purchase/')
    permiso = Permission.objects.get(content_type__app_label='pos', codename='change_purchase')
    modulo.permissions.remove(permiso)
    for grupo in Group.objects.filter(permissions=permiso):
        grupo.permissions.remove(permiso)
    migracion = importlib.import_module('core.pos.migrations.0024_permiso_completar_compras')
    migracion.forwards(registro, None)
    assert modulo.permissions.filter(pk=permiso.pk).exists()
    con_permiso = set(Group.objects.filter(permissions=permiso).values_list('name', flat=True))
    assert {ROLE_OWNER, ROLE_ADMIN} <= con_permiso
    assert not con_permiso & {ROLE_ACCOUNTANT, ROLE_READONLY, ROLE_SELLER}
    assert registro.get_app_config('pos').models_module is not None     # el registro real queda intacto
