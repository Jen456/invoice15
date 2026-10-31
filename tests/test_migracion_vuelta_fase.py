"""Vuelta completa de las 19 migraciones de la fase contable sobre una instalación con menú (start_installation), con los
destinos y el orden de MIGRACIONES-FASE-CONTABLE.md, y otra ida: el menú, los módulos y los roles quedan como antes.

Por subproceso con SQLite en archivo, como test_migracion_proformas: `migrate pos 0019` deshace varias migraciones en un
mismo plan, y ahí los modelos históricos de Permission quedan desfasados respecto de Module y Group (la vuelta de pos 0031
fallaba con ValueError «Must be "Permission" instance»). Llamar a forwards/backwards de una en una no lo reproduce.

Después, otra vuelta y dos idas parciales: la vuelta deja las filas de Permission y ContentType, y organizar_menu solo
debe crear el módulo de una app que esté migrada (antes, `migrate proformas` creaba «Retenciones recibidas» sin sus tablas
y `migrate comprobantes` creaba «Proformas»). La primera ida completa aplica las 19 en un solo plan, como desplegar.sh;
la última, lo que dejan pendiente las idas parciales."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
VUELTA = (('proformas', 'zero'), ('comprobantes', '0013_modulo_guias'), ('pos', '0019_orden_de_las_lineas'),
          ('importacion', '0004_menu_con_guias'), ('tenancy', '0006_accion_empresa_agregada'))
NUEVOS = {'/proformas/', '/comprobantes/retenciones-recibidas/'}
VERIFICAR = """
import json
from django.contrib.auth.models import Group
from core.security.models import Module
modulos = sorted([m.url, m.name, m.orden, m.module_type.name if m.module_type_id else None,
                  sorted(m.permissions.values_list('codename', flat=True))] for m in Module.objects.select_related('module_type'))
roles = {g.name: [sorted(g.groupmodule_set.values_list('module__url', flat=True)),
                  sorted(g.permissions.values_list('codename', flat=True))] for g in Group.objects.order_by('name')}
print('RESULTADO=' + json.dumps({'modulos': modulos, 'roles': roles}))
"""


def manage(env, *args, stdin=None):
    resultado = subprocess.run([sys.executable, 'manage.py', *args], cwd=RAIZ, env=env, input=stdin,
                               capture_output=True, text=True, timeout=900)
    assert resultado.returncode == 0, f'manage.py {" ".join(args)}:\n{resultado.stderr[-8000:]}'
    return resultado.stdout


def estado(env):
    return json.loads(manage(env, 'shell', stdin=VERIFICAR).split('RESULTADO=')[1])


def pendientes(env):
    return [linea.split()[-1] for linea in manage(env, 'showmigrations', '--plan').splitlines() if linea.startswith('[ ]')]


def test_vuelta_documentada_y_otra_ida_sobre_una_instalacion_con_menu(tmp_path):
    memoria = '/dev/shm' if os.path.isdir('/dev/shm') and os.access('/dev/shm', os.W_OK) else None
    with tempfile.TemporaryDirectory(prefix='fpa-vuelta-fase-', dir=memoria) as base:
        env = {k: v for k, v in os.environ.items() if not k.startswith(('FPA_', 'DATABASE_URL', 'SECRET_KEY', 'DEBUG'))}
        env.update({'FPA_ENV_FILE': os.devnull, 'DJANGO_SETTINGS_MODULE': 'config.settings', 'SECRET_KEY': 'vuelta-fase',
                    'DEBUG': 'True', 'DATABASE_URL': f'sqlite:///{Path(base) / "fase.db"}',
                    'FPA_ARCHIVOS': str(tmp_path / 'media')})
        manage(env, 'migrate', '-v', '0')
        manage(env, 'start_installation', '--admin-correo', 'admin@example.com',
               '--archivo-credenciales', str(tmp_path / 'admin.txt'))
        instalado = estado(env)
        assert NUEVOS <= {m[0] for m in instalado['modulos']}

        def vuelta():
            for app, destino in VUELTA:
                manage(env, 'migrate', app, destino, '--noinput', '-v', '0')
            # 19 de la fase + tenancy 0008/0009 (acciones de locales/puntos y de cobros, sobre tenancy 0007) + pos 0032/0033
            # (medio de cobro y etiquetas de condición de pago, sobre pos 0031: una app tiene una sola hoja). Las tablas
            # de locales y puntos (configuracion 0001-0003) y de respaldos (cobros 0001-0003) cuelgan de pos 0019 y no se
            # deshacen con la fase.
            assert len(pendientes(env)) == 23
            sin_fase = estado(env)
            assert not NUEVOS & {m[0] for m in sin_fase['modulos']}
            assert not any(c.startswith('change_anulado_sri_') for _, codigos in sin_fase['roles'].values() for c in codigos)
            assert not any(c.startswith('change_anulado_sri_') for m in sin_fase['modulos'] for c in m[4])

        def ida_completa():   # migrate sin destino, como desplegar.sh (justo tras la vuelta: las 19 en un solo plan)
            manage(env, 'migrate', '--noinput', '-v', '0')
            assert pendientes(env) == []
            assert estado(env) == instalado

        vuelta()
        ida_completa()
        vuelta()
        manage(env, 'migrate', 'proformas', '--noinput', '-v', '0')   # ida parcial: solo Proformas
        urls = {m[0] for m in estado(env)['modulos']}
        assert '/proformas/' in urls and '/comprobantes/retenciones-recibidas/' not in urls
        manage(env, 'migrate', 'proformas', 'zero', '--noinput', '-v', '0')
        manage(env, 'migrate', 'comprobantes', '--noinput', '-v', '0')   # ida parcial: pos y comprobantes, sin Proformas
        urls = {m[0] for m in estado(env)['modulos']}
        assert '/comprobantes/retenciones-recibidas/' in urls and '/proformas/' not in urls
        ida_completa()
