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
commit trae `salud-falla` responde 500 a /login/."""
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
    'sleep': 'exit 0',
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

PYTHON = '''#!/bin/bash
[ "$1" = manage.py ] || exit 2
shift
echo "$(basename "$PWD") $*" >> "$SIM/registro"
case "$1" in
  migrate) if [ -e "$SIM/migrate-falla" ]; then
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
        return [self.version(r) for r in sorted(carpeta.iterdir())] if carpeta.exists() else []

    def version(self, carpeta):
        revision = (Path(carpeta) / 'REVISION').read_text().strip()
        return next(nombre for nombre, commit in self.commits.items() if commit == revision)

    @property
    def activa(self):
        return self.version(os.path.realpath(self.base / 'current'))

    @property
    def ejecutando(self):
        return self.version((self.sim / 'ejecutando').read_text().strip())


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
