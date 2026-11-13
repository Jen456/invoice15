"""Vuelta completa de las 19 migraciones de la fase contable (más las de adjuntos, que dependen de ellas, y las de tributario) sobre una instalación con menú (start_installation), con los
destinos y el orden de MIGRACIONES-FASE-CONTABLE.md, y otra ida: el menú, los módulos y los roles quedan como antes.

Por subproceso con SQLite en archivo, como test_migracion_proformas: `migrate pos 0019` deshace varias migraciones en un
mismo plan, y ahí los modelos históricos de Permission quedan desfasados respecto de Module y Group (la vuelta de pos 0031
fallaba con ValueError «Must be "Permission" instance»). Llamar a forwards/backwards de una en una no lo reproduce.

Después, otra vuelta y dos idas parciales: la vuelta deja las filas de Permission y ContentType, y organizar_menu solo
debe crear el módulo de una app que esté migrada (antes, `migrate proformas` creaba «Retenciones recibidas» sin sus tablas
y `migrate comprobantes` creaba «Proformas»). La primera ida completa aplica las 19 en un solo plan, como desplegar.sh;
la última, lo que dejan pendiente las idas parciales.

Aparte, la vuelta documentada del diseño de factura (DISENO-FACTURA.md) y otra pasada por configuracion 0003: con sus
filas de Permission aún en la base, 0003 no debe volver a crear «Diseño de factura» sin la tabla de configuracion 0004."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
VUELTA = (('contabilidad', 'zero'), ('tributario', 'zero'), ('adjuntos', 'zero'), ('proformas', 'zero'), ('comprobantes', '0013_modulo_guias'), ('pos', '0019_orden_de_las_lineas'),
          ('importacion', '0004_menu_con_guias'), ('tenancy', '0006_accion_empresa_agregada'))
NUEVOS = {'/proformas/', '/comprobantes/retenciones-recibidas/', '/adjuntos/', '/adjuntos/capturas/', '/importacion/claves/',
          '/tributario/libros/',
          '/tributario/revision/', '/tributario/empresas/', '/tributario/ats/', '/tributario/formularios/',
          '/contabilidad/kardex/', '/contabilidad/inventario/'}
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


def instalar(tmp_path, base):
    """Entorno del subproceso (SQLite en archivo bajo `base`) con todo migrado y start_installation."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(('FPA_', 'DATABASE_URL', 'SECRET_KEY', 'DEBUG'))}
    env.update({'FPA_ENV_FILE': os.devnull, 'DJANGO_SETTINGS_MODULE': 'config.settings', 'SECRET_KEY': 'vuelta-fase',
                'DEBUG': 'True', 'DATABASE_URL': f'sqlite:///{Path(base) / "fase.db"}',
                'FPA_ARCHIVOS': str(tmp_path / 'media')})
    manage(env, 'migrate', '-v', '0')
    manage(env, 'start_installation', '--admin-correo', 'admin@example.com',
           '--archivo-credenciales', str(tmp_path / 'admin.txt'))
    return env


def memoria():
    return '/dev/shm' if os.path.isdir('/dev/shm') and os.access('/dev/shm', os.W_OK) else None


def test_vuelta_documentada_y_otra_ida_sobre_una_instalacion_con_menu(tmp_path):
    with tempfile.TemporaryDirectory(prefix='fpa-vuelta-fase-', dir=memoria()) as base:
        env = instalar(tmp_path, base)
        instalado = estado(env)
        assert NUEVOS <= {m[0] for m in instalado['modulos']}

        def vuelta():
            for app, destino in VUELTA:
                manage(env, 'migrate', app, destino, '--noinput', '-v', '0')
            # 19 de la fase + tenancy 0008/0009 (acciones de locales/puntos y de cobros, sobre tenancy 0007) + pos 0032/0033/0034
            # (medio de cobro, etiquetas de condición de pago y nacimiento opcional, sobre pos 0031: una app tiene una sola hoja)
            # + importacion 0007-0009 (lotes de claves, fuera de rango del SRI y último intento de la verificación, sobre 0006:
            # la vuelta a importacion 0004 las deshace). Las tablas de locales y
            # puntos (configuracion 0001-0003) y de respaldos (cobros 0001-0003) cuelgan de pos 0019 y no se deshacen con la
            # fase. Las 6 de adjuntos (sobre pos 0031; 0004-0006 = recibos por completar) y tenancy 0010 (acciones de los
            # recibos) sí. Las 3 de tributario (libros, revisión, ATS y borradores) cuelgan de pos 0019 e importacion 0004:
            # la vuelta empieza por `tributario zero`. Las 3 de contabilidad (kardex) cuelgan de pos 0019: antes,
            # `contabilidad zero`; tenancy 0011 (acciones del kardex) cae con la vuelta a tenancy 0006. Diseño de factura:
            # pos 0035 (copia en la factura, sobre pos 0034) y tenancy 0012 (acción de auditoría, sobre 0011) caen con sus
            # apps; configuracion 0004-0005 (tabla y módulo) cuelgan de pos 0019, como 0001-0003, y no se deshacen. «Convertir en
            # factura» (primera entrega): proformas 0004 (borrador de factura) cae con `proformas zero` y tenancy 0013 (sus dos
            # acciones de auditoría, sobre 0012) con la vuelta a tenancy 0006. 45 en total.
            assert len(pendientes(env)) == 45
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
        assert not {u for u in urls if u.startswith(('/tributario/', '/contabilidad/'))}   # ni tributario ni kardex sin migrar
        ida_completa()


def test_vuelta_del_diseno_y_otra_pasada_por_configuracion_0003(tmp_path):
    diseno = '/configuracion/diseno-factura/'
    with tempfile.TemporaryDirectory(prefix='fpa-vuelta-diseno-', dir=memoria()) as base:
        env = instalar(tmp_path, base)
        instalado = estado(env)
        assert diseno in {m[0] for m in instalado['modulos']}
        for app, destino in (('configuracion', '0003_modulo_puntos'), ('pos', '0034_cliente_nacimiento_opcional'),
                             ('tenancy', '0011_acciones_kardex')):   # la vuelta de DISENO-FACTURA.md
            manage(env, 'migrate', app, destino, '--noinput', '-v', '0')
        # tenancy 0013 (acciones del borrador de factura) va sobre 0012: la vuelta a tenancy 0011 la deshace también.
        sin_diseno = ['configuracion.0004_diseno_factura', 'configuracion.0005_modulo_diseno_factura',
                      'configuracion.0006_personalizacion_factura', 'pos.0035_sale_ride_diseno',
                      'tenancy.0012_accion_diseno_factura', 'tenancy.0013_acciones_borrador_factura']
        assert sorted(pendientes(env)) == sin_diseno
        assert diseno not in {m[0] for m in estado(env)['modulos']}
        # Otra pasada por 0003 (quita y vuelve a crear «Locales y puntos»): sin la tabla de 0004, ningún módulo del diseño
        # ni rol con él, aunque sus filas de Permission sigan en la base.
        manage(env, 'migrate', 'configuracion', '0002_rls_puntos', '--noinput', '-v', '0')
        manage(env, 'migrate', 'configuracion', '0003_modulo_puntos', '--noinput', '-v', '0')
        assert sorted(pendientes(env)) == sin_diseno
        tras = estado(env)
        assert '/configuracion/puntos/' in {m[0] for m in tras['modulos']}
        assert diseno not in {m[0] for m in tras['modulos']}
        assert not any(diseno in urls for urls, _ in tras['roles'].values())
        manage(env, 'migrate', '--noinput', '-v', '0')
        assert pendientes(env) == []
        assert estado(env) == instalado
