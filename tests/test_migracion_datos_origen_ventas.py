"""Las migraciones de la Etapa 2 · ventas (pos 0030–0031, comprobantes 0020–0023) conservan los registros de antes y no
recalculan nada: cobros como 'cobro' sin medio de pago («Sin dato»), NC y ND en 'no_aplica', sin abonos nuevos, saldo intacto
y empresa con el tipo de contribuyente sin indicar. Son reversibles (hacia atrás y otra vez hacia adelante)."""
import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ANTES = (('comprobantes', '0013_modulo_guias'), ('pos', '0019_orden_de_las_lineas'))


def manage(env, *args, stdin=None):
    resultado = subprocess.run([sys.executable, 'manage.py', *args], cwd=RAIZ, env=env, input=stdin,
                               capture_output=True, text=True, timeout=600)
    assert resultado.returncode == 0, resultado.stderr[-3000:]
    return resultado.stdout


def verificar(env):
    salida = manage(env, 'shell', stdin=(RAIZ / 'tests/escenarios/ventas_legado_verificar.py').read_text())
    return json.loads(salida.split('RESULTADO=')[1])


def test_registros_de_antes_intactos_y_migraciones_reversibles(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('FPA_', 'DATABASE_URL', 'SECRET_KEY', 'DEBUG'))}
    env.update({'FPA_ENV_FILE': os.devnull, 'DJANGO_SETTINGS_MODULE': 'config.settings', 'SECRET_KEY': 'legado-ventas',
                'DEBUG': 'True', 'DATABASE_URL': f'sqlite:///{tmp_path}/legado_ventas.db', 'FPA_ARCHIVOS': str(tmp_path / 'media')})
    for app, migracion in reversed(ANTES):
        manage(env, 'migrate', app, migracion, '-v', '0')
    manage(env, 'shell', stdin=(RAIZ / 'tests/escenarios/ventas_legado_cargar.py').read_text())
    manage(env, 'migrate', '-v', '0')
    esperado = {
        'empresa': ['', '', ''],
        'abonos': [['cobro', '', '', '10.00', 'Abono']],
        'abonos_registro': [[None, None, None]],
        'cxc': [1, '23.00', '13.00', True],
        'notas_credito': [['no_aplica', None, None]],
        'notas_debito': [['no_aplica', None, None]],
        'venta': [[None, 'authorized', None, False]],
    }
    assert verificar(env) == esperado
    for app, migracion in ANTES:                       # hacia atrás: primero comprobantes (depende de pos 0030)
        manage(env, 'migrate', app, migracion, '-v', '0')
    manage(env, 'migrate', '-v', '0')
    assert verificar(env) == esperado
