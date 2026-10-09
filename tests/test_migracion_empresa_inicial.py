"""Una base creada con el código original migra conservando todos sus datos."""
import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def manage(env, *args, stdin=None):
    resultado = subprocess.run([sys.executable, 'manage.py', *args], cwd=RAIZ, env=env, input=stdin,
                               capture_output=True, text=True, timeout=600)
    assert resultado.returncode == 0, resultado.stderr[-3000:]
    return resultado.stdout


def test_datos_del_codigo_original_pasan_a_la_empresa_inicial(tmp_path):
    # Variables explícitas: el proceso de pytest ya tiene DATABASE_URL (en memoria) y
    # read_env no sobrescribe las existentes.
    env = {k: v for k, v in os.environ.items() if not k.startswith(('FPA_', 'DATABASE_URL', 'SECRET_KEY', 'DEBUG'))}
    env.update({'FPA_ENV_FILE': os.devnull, 'DJANGO_SETTINGS_MODULE': 'config.settings', 'SECRET_KEY': 'legado',
                'DEBUG': 'True', 'DATABASE_URL': f'sqlite:///{tmp_path}/legado.db',
                'FPA_ARCHIVOS': str(tmp_path / 'media')})
    manage(env, 'migrate', 'pos', '0002_initial', '-v', '0')
    manage(env, 'migrate', 'security', '0002_initial', '-v', '0')
    manage(env, 'shell', stdin=(RAIZ / 'tests/escenarios/legado_cargar.py').read_text())
    manage(env, 'migrate', '-v', '0')
    salida = manage(env, 'shell', stdin=(RAIZ / 'tests/escenarios/legado_verificar.py').read_text())
    resultado = json.loads(salida.split('RESULTADO=')[1])
    assert resultado['empresas'] == 1 and resultado['uuid']
    assert resultado['productos_en_empresa'] == 1
    assert resultado['categorias_en_empresa'] == 1
    assert resultado['clientes_en_empresa'] == 1
    assert resultado['roles'] == ['0912345678:Cliente', 'admin.local:Administrador', 'cajero:Cajero',
                                  'jefe:Propietario']
