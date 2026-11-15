"""deploy/scripts/desplegar.sh: una versión que no queda activa no se queda en releases/ (MIGRACIONES-FASE-CONTABLE.md,
plan de recuperación del bloque 1, puntos 1 y 3).

Cuando `migrate` falla (contabilidad 0009 agota sus intentos, por diseño) o la versión nueva no pasa la salud y el
script vuelve a la anterior, `desplegar.sh` sale con 1. Antes, la carpeta de esa versión se quedaba en releases/:
`--revertir`, que elige por fecha la más reciente que no es `current`, activaba la fallida (en el ensayo con 0009, el
mismo 6b7ccbf) y, repetido, alternaba entre las dos carpetas de 6b7ccbf sin volver nunca a la publicada; y la limpieza
(se conservan 5) las contaba, así que unas cuantas fallidas bastaban para borrar la versión anterior.

Se copia el script real a tmp_path y solo se cambian sus rutas fijas (BASE, ENVF y RESPALDOS; además CRED_DIR, para
que la primera instalación no escriba en la carpeta real de credenciales, y UV, para que no se instalen dependencias).
Las órdenes que tocarían el sistema (systemctl, journalctl, curl, pg_dump, runuser, chown, install con dueño, sleep y
la fecha que nombra cada carpeta) van simuladas en PATH; el `manage.py` de cada versión es un guion que falla en `migrate`
mientras exista `migrate-falla`, como 0009 con `user_user` retenido. La salud es propiedad del código: la versión cuyo
commit trae `salud-falla` responde 500 a /login/.

C2E-3 (cierre del corte 1 del bloque 2): `migrate` va con `lock_timeout=5s` y se repite, hasta 3 intentos, solo si acaba
por lock_timeout (55P03) o por un interbloqueo (40P01). Las marcas `migrate-bloqueo-luego-bien` (falla la primera vez),
`migrate-bloqueo-siempre` y `migrate-otro-error` hacen que el `manage.py` simulado imprima la salida de un `migrate`
real cortado (Django 5.2 con psycopg 3 y PostgreSQL 16, recortada a sus primeros marcos): la del archivo de la marca."""
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SCRIPT = RAIZ / 'deploy' / 'scripts' / 'desplegar.sh'

pytestmark = [
    pytest.mark.skipif(shutil.which('bash') is None or shutil.which('git') is None, reason='Hacen falta bash y git'),
    pytest.mark.skipif(not sys.platform.startswith('linux'), reason='desplegar.sh usa GNU coreutils (mv -T, readlink)'),
]

# Las únicas líneas del script que cambian: sus rutas fijas.
RUTAS = {
    'BASE=/opt/facturaporaqui/$ENTORNO': 'BASE={raiz}/instalacion/$ENTORNO',
    'ENVF=/etc/facturaporaqui/$ENTORNO.env': 'ENVF={raiz}/config/$ENTORNO.env',
    'RESPALDOS=/home/$USUARIO/datos/$ENTORNO/respaldos': 'RESPALDOS={raiz}/respaldos/$ENTORNO',
    'CRED_DIR=/root/invoice15/credenciales': 'CRED_DIR={raiz}/credenciales',
    'UV=/root/.local/bin/uv': 'UV={raiz}/bin/uv',
}

SIMULADAS = {
    # systemctl restart: «arranca» la versión a la que apunta current
    'systemctl': '[ "$1" = restart ] && readlink -f "$SIM_BASE/current" > "$SIM/ejecutando"\nexit 0',
    'journalctl': 'exit 0',
    'sleep': 'echo "$*" >> "$SIM/pausas"\nexit 0',
    'chown': 'exit 0',
    # /login/ responde 200 salvo que el código de la versión que se ejecuta traiga salud-falla
    'curl': 'v=$(cat "$SIM/ejecutando" 2>/dev/null || true)\n'
            'if [ -n "$v" ] && [ ! -e "$v/salud-falla" ]; then printf 200; else printf 500; fi',
    'pg_dump': 'for a; do case "$a" in --file=*) echo volcado > "${a#--file=}";; esac; done',
    'runuser': '[ "$1" = -u ] && shift 2\n[ "$1" = -- ] && shift\nexec "$@"',
    'install': 'args=()\nwhile [ $# -gt 0 ]; do case "$1" in -o|-g) shift 2;; *) args+=("$1"); shift;; esac; done\n'
               'exec {install} "${{args[@]}}"',
    # la fecha que nombra cada carpeta avanza un segundo por despliegue; las demás, la real
    'date': 'if [ "$1" = "+%Y%m%d-%H%M%S" ]; then\n'
            '  n=$(( $(cat "$SIM/reloj" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$SIM/reloj"\n'
            '  printf "20261115-%06d\\n" "$n"\nelse exec {date} "$@"; fi',
    # uv venv … <carpeta>: su bin/python es el manage.py simulado; uv pip sync: nada
    'uv': 'if [ "$1" = venv ]; then d="${@: -1}"; mkdir -p "$d/bin"; cp "$SIM/python" "$d/bin/python"; fi\n'
          'exit 0',
}

# Salida de `migrate` cortado: «  Applying …» por la salida normal y, en la misma línea, la traza encadenada por la de
# errores, como la imprime Python al salir de manage.py. Cada excepción de la cadena es un argumento (con sus líneas de
# DETAIL o HINT); la primera es la de la base y cada una es causa directa de la siguiente.
TRAZA = r'''cortado() {
  local migracion="$1" primera=1 excepcion; shift
  printf '  Applying %s...' "$migracion"
  for excepcion; do
    [ -n "$primera" ] || printf '\nThe above exception was the direct cause of the following exception:\n\n' >&2
    primera=
    printf 'Traceback (most recent call last):\n  File "%s", line 103, in _execute\n' \
      "$PWD/.venv/lib/python3.12/site-packages/django/db/backends/utils.py" >&2
    printf '    return self.cursor.execute(sql)\n           ^^^^^^^^^^^^^^^^^^^^^^^^\n%s\n' "$excepcion" >&2
  done
}
error_de_migrate() {
  local lock='canceling statement due to lock timeout'
  local deadlock='deadlock detected
DETAIL:  Process 3004752 waits for AccessExclusiveLock on relation 1977162 of database 1970226; blocked by process 3004.
Process 3004 waits for AccessExclusiveLock on relation 1977159 of database 1970226; blocked by process 3004752.
HINT:  See server log for query details.'
  local statement='canceling statement due to statement timeout'
  case "$1" in
    LockNotAvailable) cortado contabilidad.0010_clases_de_cuenta "psycopg.errors.LockNotAvailable: $lock" \
                        "django.db.utils.OperationalError: $lock" ;;
    DeadlockDetected) cortado contabilidad.0011_libro_diario "psycopg.errors.DeadlockDetected: $deadlock" \
                        "django.db.utils.OperationalError: $deadlock" ;;
    statement_timeout) cortado contabilidad.0012_apertura "psycopg.errors.QueryCanceled: $statement" \
                         "django.db.utils.OperationalError: $statement" ;;
    0009) cortado contabilidad.0009_anular_autores_en_la_base "psycopg.errors.LockNotAvailable: $lock" \
            "django.db.utils.OperationalError: $lock" \
            "RuntimeError: contabilidad 0009: en 8 intentos de 1 s no se consiguió el bloqueo de user_user, que retiene\
 otra transacción. No se cambió nada: repite \`migrate\` (o el despliegue), mejor con poco tráfico." ;;
    *) exit 3 ;;
  esac
  exit 1
}
'''

PYTHON = '''#!/bin/bash
[ "$1" = manage.py ] || exit 2
shift
echo "$(basename "$PWD") $*" >> "$SIM/registro"
''' + TRAZA + '''case "$1" in
  migrate) echo "migrate con PGOPTIONS=$PGOPTIONS" >> "$SIM/registro"
           if [ -e "$SIM/migrate-bloqueo-luego-bien" ] && [ ! -e "$SIM/migrate-bloqueo-hecho" ]; then
             touch "$SIM/migrate-bloqueo-hecho"; error_de_migrate "$(cat "$SIM/migrate-bloqueo-luego-bien")"
           fi
           [ -e "$SIM/migrate-bloqueo-siempre" ] && error_de_migrate "$(cat "$SIM/migrate-bloqueo-siempre")"
           [ -e "$SIM/migrate-otro-error" ] && error_de_migrate "$(cat "$SIM/migrate-otro-error")"
           if [ -e "$SIM/migrate-lento" ]; then
             echo "migrate empieza" >> "$SIM/registro"; /bin/sleep 2; echo "migrate termina" >> "$SIM/registro"
             [ -d "$PWD" ] && echo "su carpeta sigue" >> "$SIM/registro"
           fi
           if [ -e "$SIM/migrate-ocupa" ]; then
             (exec /bin/sleep 30) &   # un proceso que se queda trabajando dentro de la carpeta de la versión
             echo $! > "$SIM/ocupante"
           fi
           if [ -e "$SIM/migrate-falla" ]; then
             echo "RuntimeError: contabilidad 0009: no se consiguió el bloqueo de user_user (simulado)" >&2
             exit 1
           fi ;;
  start_installation) while [ $# -gt 0 ]; do [ "$1" = --archivo-credenciales ] && echo simulado > "$2"; shift; done ;;
esac
exit 0
'''


def ejecutable(ruta, texto):
    ruta.write_text(texto)
    ruta.chmod(ruta.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class Entorno:
    """Un entorno «pruebas» completo en tmp_path: repositorio con cuatro versiones, desplegar.sh con sus rutas y las
    órdenes simuladas."""

    def __init__(self, raiz, script=SCRIPT):
        self.raiz = raiz
        self.base = raiz / 'instalacion' / 'pruebas'
        self.sim = raiz / 'sim'
        for carpeta in ('bin', 'config', 'sim', 'static', 'repo', 'tmp', 'instalacion'):
            (raiz / carpeta).mkdir(exist_ok=True)
        reales = {'install': shutil.which('install'), 'date': shutil.which('date')}
        for nombre, cuerpo in SIMULADAS.items():
            cuerpo = cuerpo.format(**reales) if nombre in reales else cuerpo
            ejecutable(raiz / 'bin' / nombre, f'#!/bin/bash\n{cuerpo}\n')
        ejecutable(self.sim / 'python', PYTHON)
        (raiz / 'config' / 'pruebas.env').write_text(
            f'FPA_PUERTO=8999\nALLOWED_HOSTS=pruebas.example.test\nDATABASE_URL=postgresql://simulada/simulada\n'
            f'STATIC_ROOT={raiz}/static\n')

        texto = script.read_text()
        for original, nueva in RUTAS.items():
            assert texto.count(f'\n{original}\n') == 1, original
            texto = texto.replace(f'\n{original}\n', f'\n{nueva.format(raiz=raiz)}\n')
        resto = texto.replace(str(raiz), '<tmp>')
        assert '/opt/' not in resto and '/etc/' not in resto and '/home/' not in resto
        assert [linea for linea in resto.splitlines() if '/root/' in linea and not linea.startswith('#')] == [
            'REPO="${FPA_REPO:-/root/invoice15/src}"', 'STATIC_LIB="${FPA_STATIC_LIB:-/root/invoice15/static-lib}"']
        self.script = raiz / 'desplegar.sh'
        self.script.write_text(texto)

        self.env = {
            'PATH': f'{raiz}/bin:{os.environ.get("PATH", "/usr/bin:/bin")}', 'HOME': str(raiz), 'LC_ALL': 'C',
            'TMPDIR': str(raiz / 'tmp'), 'SIM': str(self.sim), 'SIM_BASE': str(self.base),
            'FPA_REPO': str(raiz / 'repo'), 'FPA_STATIC_LIB': str(raiz / 'sin-static-lib'),
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
        }
        self.commits = {}
        self.git('init', '-q')
        for nombre, archivos in (('anterior', {}), ('publicada', {}), ('nueva', {}), ('sin-salud', {'salud-falla': ''})):
            for archivo, contenido in {'requirements/base.txt': f'# {nombre}\n', 'manage.py': '', **archivos}.items():
                (raiz / 'repo' / archivo).parent.mkdir(parents=True, exist_ok=True)
                (raiz / 'repo' / archivo).write_text(contenido)
            self.git('add', '-A')
            self.git('-c', 'user.name=Pruebas', '-c', 'user.email=pruebas@example.test', '-c', 'commit.gpgsign=false',
                     'commit', '-q', '-m', nombre)
            self.commits[nombre] = self.git('rev-parse', 'HEAD').strip()
            (raiz / 'repo' / 'salud-falla').unlink(missing_ok=True)

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.raiz / 'repo'), *args], env=self.env, check=True,
                              capture_output=True, text=True).stdout

    def desplegar(self, *args):
        time.sleep(0.05)   # carpetas con fechas de modificación distintas: --revertir y la limpieza ordenan por ellas
        hecho = subprocess.run(['bash', str(self.script), 'pruebas', *args], env=self.env, capture_output=True,
                               text=True, timeout=120)
        hecho.salida = hecho.stdout + hecho.stderr
        return hecho

    def migrate_falla(self, falla):
        marca = self.sim / 'migrate-falla'
        marca.touch() if falla else marca.unlink(missing_ok=True)

    def releases(self):
        """Commit de cada carpeta de releases/, por nombre (que es por orden de despliegue)."""
        carpeta = self.base / 'releases'
        return [self.version(r) for r in sorted(carpeta.iterdir()) if not r.name.startswith('.')] if carpeta.exists() else []

    def version(self, carpeta):
        revision = (Path(carpeta) / 'REVISION').read_text().strip()
        return next(nombre for nombre, commit in self.commits.items() if commit == revision)

    @property
    def activa(self):
        return self.version(os.path.realpath(self.base / 'current'))

    @property
    def ejecutando(self):
        return self.version((self.sim / 'ejecutando').read_text().strip())

    def migrates(self):
        """El PGOPTIONS de cada `migrate` simulado, en orden, de todos los despliegues de la prueba."""
        registro = self.sim / 'registro'
        lineas = registro.read_text().splitlines() if registro.exists() else []
        return [linea.split('=', 1)[1] for linea in lineas if linea.startswith('migrate con PGOPTIONS=')]

    def pausas(self):
        pausas = self.sim / 'pausas'
        return pausas.read_text().split() if pausas.exists() else []

    def registro_de_migrate(self):
        """La salida de `migrate` del último despliegue, en registros/ (fuera de releases/: queda aunque la versión se
        borre). Comprueba que la carpeta solo la lee root."""
        carpeta = self.base / 'registros'
        assert stat.S_IMODE(carpeta.stat().st_mode) == 0o700
        return sorted(carpeta.glob('migrate-*.log'))[-1]


@pytest.fixture
def entorno(tmp_path):
    return Entorno(tmp_path)


def bien(entorno, ref, *extra):
    hecho = entorno.desplegar(entorno.commits[ref], *extra)
    assert hecho.returncode == 0, hecho.salida
    assert 'se borra' not in hecho.salida
    return hecho


def test_migrate_que_falla_no_deja_su_version_y_revertir_vuelve_a_la_publicada(entorno):
    """B: el despliegue falla en migrate dos veces; su carpeta no se queda, la publicada sigue activa y atendiendo, el
    tercer intento sale bien y --revertir vuelve a la publicada (antes: a la carpeta fallida del mismo commit)."""
    bien(entorno, 'publicada')
    entorno.migrate_falla(True)
    for _ in range(2):
        hecho = entorno.desplegar(entorno.commits['nueva'])
        assert hecho.returncode == 1, hecho.salida
        assert 'contabilidad 0009' in hecho.salida
        assert entorno.releases() == ['publicada']
        assert entorno.activa == entorno.ejecutando == 'publicada'
        assert 'no quedó activa' in hecho.salida
    entorno.migrate_falla(False)
    bien(entorno, 'nueva')
    assert entorno.releases() == ['publicada', 'nueva'] and entorno.activa == entorno.ejecutando == 'nueva'

    hecho = entorno.desplegar('--revertir')
    assert hecho.returncode == 0, hecho.salida
    assert entorno.activa == entorno.ejecutando == 'publicada'
    assert entorno.releases() == ['publicada', 'nueva']


def test_la_version_anterior_sobrevive_a_la_limpieza_tras_varios_fallos(entorno):
    """C: cinco despliegues que fallan en migrate y uno bueno. La limpieza conserva 5 carpetas; con las fallidas dentro,
    la de la publicada se borraba y --revertir no tenía a dónde volver."""
    bien(entorno, 'anterior')
    bien(entorno, 'publicada')
    entorno.migrate_falla(True)
    for _ in range(5):
        hecho = entorno.desplegar(entorno.commits['nueva'])
        assert hecho.returncode == 1, hecho.salida
        assert entorno.activa == 'publicada'
    entorno.migrate_falla(False)
    bien(entorno, 'nueva')
    assert entorno.releases() == ['anterior', 'publicada', 'nueva']

    assert entorno.desplegar('--revertir').returncode == 0
    assert entorno.activa == entorno.ejecutando == 'publicada'


def test_salud_fallida_vuelve_a_la_anterior_y_borra_la_nueva(entorno):
    """F: la versión nueva se activa y no pasa la salud; el script vuelve a la publicada, sale con 1 y borra la carpeta
    de la nueva, así que --revertir va a la anterior de verdad y no a la que no arranca."""
    bien(entorno, 'anterior')
    bien(entorno, 'publicada')
    hecho = entorno.desplegar(entorno.commits['sin-salud'])
    assert hecho.returncode == 1, hecho.salida
    assert 'FALLO de salud' in hecho.salida
    assert entorno.releases() == ['anterior', 'publicada']
    assert entorno.activa == entorno.ejecutando == 'publicada'
    assert 'no quedó activa' in hecho.salida

    assert entorno.desplegar('--revertir').returncode == 0
    assert entorno.activa == entorno.ejecutando == 'anterior'


def test_primera_instalacion_con_salud_fallida_conserva_su_version(entorno):
    """Sin `current` no hay a qué volver: la versión se queda activa aunque no pase la salud, el script sale con 1 y su
    carpeta no se borra. Antes, `readlink -f` de un `current` que no existe daba su propia ruta, la vuelta «a la
    anterior» la activaba y `current` quedaba apuntando a sí mismo."""
    hecho = entorno.desplegar(entorno.commits['sin-salud'], '--primera-instalacion', 'admin@example.test')
    assert hecho.returncode == 1, hecho.salida
    assert 'FALLO de salud' in hecho.salida and 'se borra' not in hecho.salida
    assert os.readlink(entorno.base / 'current') != str(entorno.base / 'current'), 'current apunta a sí mismo'
    assert entorno.releases() == ['sin-salud'] and entorno.activa == 'sin-salud'
    assert len(list((entorno.raiz / 'credenciales').glob('admin-pruebas-*.txt'))) == 1


def test_primera_instalacion_que_falla_en_migrate_no_toca_nada(entorno):
    """Sin `current`, un fallo antes de activar tampoco borra: sale con 1 y la carpeta queda para revisarla."""
    entorno.migrate_falla(True)
    hecho = entorno.desplegar(entorno.commits['publicada'], '--primera-instalacion', 'admin@example.test')
    assert hecho.returncode == 1, hecho.salida
    assert 'se borra' not in hecho.salida
    assert entorno.releases() == ['publicada'] and not (entorno.base / 'current').exists()


def test_despliegue_bueno_con_la_base_detras_de_un_enlace_conserva_su_version(tmp_path):
    """La guarda compara rutas resueltas: si /opt/facturaporaqui (o una carpeta de encima) fuera un enlace,
    `readlink -f current` no coincidiría letra a letra con la ruta de la versión y se borraría la que acaba de
    activarse."""
    (tmp_path / 'instalacion-real').mkdir()
    (tmp_path / 'instalacion').symlink_to(tmp_path / 'instalacion-real')
    entorno = Entorno(tmp_path)
    bien(entorno, 'publicada')
    bien(entorno, 'nueva')
    assert entorno.releases() == ['publicada', 'nueva'] and entorno.activa == entorno.ejecutando == 'nueva'


def test_matar_el_script_durante_migrate_espera_a_migrate_y_despues_limpia(entorno):
    """Un kill (SIGTERM solo al bash del script) mientras migrate corre: el script espera a que migrate termine, sale con
    143 y solo entonces borra la carpeta; antes la borraba al momento con migrate todavía trabajando dentro."""
    bien(entorno, 'publicada')
    (entorno.sim / 'migrate-lento').touch()
    proceso = subprocess.Popen(['bash', str(entorno.script), 'pruebas', entorno.commits['nueva']], env=entorno.env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    registro = entorno.sim / 'registro'
    limite = time.monotonic() + 60
    while 'migrate empieza' not in (registro.read_text() if registro.exists() else ''):
        assert time.monotonic() < limite and proceso.poll() is None, 'migrate no llegó a empezar'
        time.sleep(0.05)
    proceso.terminate()
    salida, _ = proceso.communicate(timeout=60)
    assert proceso.returncode == 143, salida
    texto = registro.read_text()
    assert 'migrate termina' in texto and 'su carpeta sigue' in texto, texto
    assert 'no quedó activa' in salida
    assert entorno.releases() == ['publicada'] and entorno.activa == entorno.ejecutando == 'publicada'


def test_una_version_que_no_quedo_activa_y_aun_se_usa_se_aparta_sin_borrarla(entorno):
    """Si al salir un proceso sigue trabajando dentro de la carpeta, no se borra: se aparta con un nombre oculto, que
    --revertir y la limpieza no ven, así que la vuelta sigue yendo a la publicada."""
    bien(entorno, 'publicada')
    entorno.migrate_falla(True)
    (entorno.sim / 'migrate-ocupa').touch()
    try:
        hecho = entorno.desplegar(entorno.commits['nueva'])
        assert hecho.returncode == 1, hecho.salida
        assert 'aún la usa un proceso' in hecho.salida and 'se borra' not in hecho.salida
        apartadas = [r for r in (entorno.base / 'releases').iterdir() if r.name.startswith('.no-activa-')]
        assert len(apartadas) == 1 and entorno.version(apartadas[0]) == 'nueva'
        assert entorno.releases() == ['publicada'] and entorno.activa == 'publicada'
    finally:
        ocupante = entorno.sim / 'ocupante'
        if ocupante.exists():
            try:
                os.kill(int(ocupante.read_text()), 15)
            except ProcessLookupError:
                pass
    (entorno.sim / 'migrate-ocupa').unlink()
    entorno.migrate_falla(False)
    bien(entorno, 'nueva')
    assert entorno.desplegar('--revertir').returncode == 0
    assert entorno.activa == entorno.ejecutando == 'publicada'


CON_LOCK_TIMEOUT = '-c app.platform=on -c lock_timeout=5s'


@pytest.mark.parametrize('error', ['LockNotAvailable', 'DeadlockDetected'])
def test_migrate_que_no_consigue_un_bloqueo_se_repite_y_publica(entorno, error):
    """C2E-3: migrate va con lock_timeout=5s y, si el primer intento acaba por lock_timeout (55P03) o por un
    interbloqueo (40P01), se repite tras una pausa y el despliegue sigue y publica. Antes migrate iba sin lock_timeout
    ni reintento: un fallo así paraba el despliegue. La salida de cada intento queda en registros/, sin la URL de la
    base."""
    bien(entorno, 'publicada')
    antes = len(entorno.migrates())
    (entorno.sim / 'migrate-bloqueo-luego-bien').write_text(error)
    hecho = entorno.desplegar(entorno.commits['nueva'])
    assert hecho.returncode == 0, hecho.salida
    assert entorno.migrates()[antes:] == [CON_LOCK_TIMEOUT] * 2
    assert entorno.pausas() == ['10']
    assert 'se repite migrate en 10 s (intento 2 de 3)' in hecho.salida
    assert 'migrate: bien en el intento 2 de 3' in hecho.salida and 'se borra' not in hecho.salida
    assert f'psycopg.errors.{error}' in hecho.salida   # la salida de migrate también se ve
    assert entorno.releases() == ['publicada', 'nueva'] and entorno.activa == entorno.ejecutando == 'nueva'
    registro = entorno.registro_de_migrate()
    assert str(registro) in hecho.salida
    texto = registro.read_text()
    assert texto.count('== intento ') == 2 and '== intento 2 de 3, lock_timeout=5s' in texto
    migracion = {'LockNotAvailable': '0010_clases_de_cuenta', 'DeadlockDetected': '0011_libro_diario'}[error]
    assert f'  Applying contabilidad.{migracion}...Traceback (most recent call last):\n' in texto
    assert 'postgresql://' not in texto


def test_migrate_que_nunca_consigue_el_bloqueo_agota_los_intentos_y_no_publica(entorno):
    """C2E-3: si los tres intentos acaban por lock_timeout, el despliegue se detiene con un mensaje que dice cuántos
    intentos hubo y qué hacer; la versión nueva se borra al salir y la publicada sigue activa y atendiendo, así que
    --revertir después de un despliegue bueno vuelve a ella."""
    bien(entorno, 'publicada')
    antes = len(entorno.migrates())
    (entorno.sim / 'migrate-bloqueo-siempre').write_text('LockNotAvailable')
    hecho = entorno.desplegar(entorno.commits['nueva'])
    assert hecho.returncode == 1, hecho.salida
    assert entorno.migrates()[antes:] == [CON_LOCK_TIMEOUT] * 3
    assert entorno.pausas() == ['10', '10']
    assert 'FALLO de migrate: en los 3 intentos' in hecho.salida and 'pg_stat_activity' in hecho.salida
    assert 'repite el despliegue' in hecho.salida
    assert 'no quedó activa' in hecho.salida
    assert entorno.releases() == ['publicada'] and entorno.activa == entorno.ejecutando == 'publicada'
    registro = entorno.registro_de_migrate()
    assert str(registro) in hecho.salida and registro.read_text().count('== intento ') == 3

    (entorno.sim / 'migrate-bloqueo-siempre').unlink()
    bien(entorno, 'nueva')
    assert entorno.desplegar('--revertir').returncode == 0
    assert entorno.activa == entorno.ejecutando == 'publicada'


@pytest.mark.parametrize('error', ['statement_timeout', '0009'])
def test_migrate_con_otro_error_no_se_repite(entorno, error):
    """C2E-3: cualquier otro fallo para el despliegue al primer intento, como antes. statement_timeout también es un
    OperationalError que empieza por «canceling statement»; 0009 cuando agota sus propios intentos acaba en
    RuntimeError, aunque su causa sea un lock_timeout: ya repitió ocho veces y su mensaje dice qué hacer."""
    bien(entorno, 'publicada')
    antes = len(entorno.migrates())
    (entorno.sim / 'migrate-otro-error').write_text(error)
    hecho = entorno.desplegar(entorno.commits['nueva'])
    assert hecho.returncode == 1, hecho.salida
    assert entorno.migrates()[antes:] == [CON_LOCK_TIMEOUT]
    assert entorno.pausas() == [] and 'se repite migrate' not in hecho.salida
    assert 'FALLO de migrate en el intento 1 de 3; no se repite' in hecho.salida
    assert 'no quedó activa' in hecho.salida
    assert entorno.releases() == ['publicada'] and entorno.activa == entorno.ejecutando == 'publicada'
    registro = entorno.registro_de_migrate()
    final = {'statement_timeout': 'django.db.utils.OperationalError: canceling statement due to statement timeout',
             '0009': 'RuntimeError: contabilidad 0009: en 8 intentos'}[error]
    assert final in hecho.salida and final in registro.read_text()
    assert registro.read_text().count('== intento ') == 1
