"""contabilidad 0009 con `user_user` ocupado, en PostgreSQL (MIGRACIONES-FASE-CONTABLE.md, «Por qué 0009»).

Para poner `ON DELETE SET NULL`, 0009 quita y vuelve a crear las cuatro claves hacia el usuario, y quitarlas pide
`AccessExclusiveLock` sobre `user_user`. Mientras lo espera, toda lectura nueva de `user_user` (cada petición con sesión)
hace cola detrás. Con una sola espera de 5 s, una transacción que solo había leído `user_user` paraba esas lecturas hasta
5 s y, si duraba más, `migrate` fallaba (revisión de la segunda ronda: retención de 2 s, lectura parada 1,66 s; de 8 s,
lectura parada 5,07 s y `lock_timeout` a los 5,59 s). Ahora cada intento espera como mucho `ESPERA_POR_INTENTO`, en su
propio punto de guardado, y entre intentos no retiene nada.

Las pruebas vuelven a 0008 (hacia atrás 0009 no hace nada), dejan las cuatro claves como las crea Django (sin acción,
diferidas y con su nombre), retienen `user_user` desde otra conexión, aplican 0009 y miden lo que esperan las lecturas
de otra conexión. Son transaccionales (`transaction=True`: la migración confirma su transacción, como en `migrate`) y
van al final (`test_zz_*`), y al terminar la base queda migrada y con las claves de 0009 pase lo que pase. Los márgenes
son holgados porque la máquina es compartida: una espera de hasta `ESPERA_POR_INTENTO` + 1,5 s pasa; la de antes, de
toda la retención, no. Marca `tiempos`: mide esperas reales."""
import importlib
import threading
import time

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
    pytest.mark.tiempos,
]

ANTERIOR, MIGRACION = '0008_seguridad_por_filas_importacion', '0009_anular_autores_en_la_base'
modulo = importlib.import_module(f'core.contabilidad.migrations.{MIGRACION}')
CLAVES = {('contabilidad_cuenta', 'creada_por_id'), ('contabilidad_cuenta', 'actualizada_por_id'),
          ('contabilidad_importacioncuentas', 'creado_por_id'), ('contabilidad_importacioncuentas', 'confirmado_por_id')}
HOLGURA = 1.5   # segundos sobre un intento: la máquina está cargada


def usuarios():
    return get_user_model()._meta.db_table


def claves():
    """{(tabla, columna): (nombre, acción al borrar, diferible, diferida)} de las cuatro claves hacia el usuario."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT c.conrelid::regclass::text, a.attname, c.conname, c.confdeltype, c.condeferrable, c.condeferred
            FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
            WHERE c.contype = 'f' AND c.confrelid = %s::regclass
              AND c.conrelid::regclass::text IN ('contabilidad_cuenta', 'contabilidad_importacioncuentas')""",
                       [usuarios()])
        filas = cursor.fetchall()
    assert len(filas) == 4
    return {(tabla, columna): tuple(resto) for tabla, columna, *resto in filas}


def aplicada():
    return MigrationRecorder(connection).migration_qs.filter(app='contabilidad', name=MIGRACION).exists()


def migrar(destino):
    MigrationExecutor(connection).migrate([('contabilidad', destino)])


def como_antes_de_0009():
    """Vuelve a 0008 y deja las cuatro claves como las crea Django: sin acción al borrar, diferidas, con su nombre."""
    migrar(ANTERIOR)
    assert not aplicada()
    with connection.cursor() as cursor:
        for (tabla, columna), (nombre, *_) in claves().items():
            cursor.execute(f'ALTER TABLE {tabla} DROP CONSTRAINT {nombre}, ADD CONSTRAINT {nombre} FOREIGN KEY ({columna}) '
                           f'REFERENCES {usuarios()} (id) DEFERRABLE INITIALLY DEFERRED')
    antes = claves()
    assert {fila[1:] for fila in antes.values()} == {('a', True, True)}
    return antes


@pytest.fixture
def antes_de_0009():
    """Las claves como antes de 0009; al terminar, 0009 aplicada sin nadie que retenga nada, como en el resto de la suite."""
    try:
        yield como_antes_de_0009()
    finally:
        if not aplicada():
            migrar(MIGRACION)
        assert aplicada() and {fila[1:] for fila in claves().values()} == {('n', True, True)}


class Retencion:
    """Otra conexión abre una transacción, lee `user_user` (su `AccessShareLock` dura hasta el final de la transacción) y
    la mantiene abierta hasta `segundos` después de ver a 0009 pidiendo su bloqueo exclusivo de `user_user`, o hasta
    `soltar()`: así la retención se cuenta desde el primer intento, no desde que empieza `migrate`, que antes arma el
    estado de todas las migraciones. Una tercera conexión lee `user_user` sin parar, cada lectura en su propia
    transacción, como una petición con sesión, y anota cuánto tarda cada una."""

    def __init__(self, segundos):
        self.segundos, self.tomada, self.suelta, self.parar = segundos, threading.Event(), threading.Event(), threading.Event()
        self.lecturas, self.errores, self.pedida, self.soltada = [], [], None, None
        self.hilos = [threading.Thread(target=self.retener), threading.Thread(target=self.leer)]

    def retener(self):
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(f'SELECT count(*) FROM {usuarios()}')
                self.tomada.set()
                limite = time.monotonic() + 300
                while self.pedida is None and not self.suelta.is_set() and time.monotonic() < limite:
                    cursor.execute("SELECT count(*) FROM pg_locks WHERE relation = %s::regclass AND mode = 'AccessExclusiveLock' "
                                   "AND NOT granted AND database = (SELECT oid FROM pg_database WHERE datname = current_database())",
                                   [usuarios()])
                    if cursor.fetchone()[0]:
                        self.pedida = time.monotonic()
                    else:
                        time.sleep(0.02)
                self.suelta.wait(self.segundos)
            self.soltada = time.monotonic()
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            self.errores.append(e)
        finally:
            self.tomada.set()
            connections.close_all()

    def leer(self):
        try:
            with connection.cursor() as cursor:
                while not self.parar.is_set():
                    inicio = time.monotonic()
                    cursor.execute(f'SELECT count(*) FROM {usuarios()}')
                    self.lecturas.append(time.monotonic() - inicio)
                    time.sleep(0.05)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            self.errores.append(e)
        finally:
            connections.close_all()

    def __enter__(self):
        for hilo in self.hilos:
            hilo.start()
        assert self.tomada.wait(60)
        time.sleep(0.3)   # unas lecturas antes de empezar
        return self

    def soltar(self):
        self.suelta.set()

    def __exit__(self, *error):
        self.soltar()
        self.parar.set()
        for hilo in self.hilos:
            hilo.join(timeout=120)
        assert not any(hilo.is_alive() for hilo in self.hilos)
        assert not self.errores, self.errores

    @property
    def mayor_espera(self):
        return max(self.lecturas)


def test_retenido_mas_que_un_intento_0009_termina_y_las_lecturas_esperan_como_mucho_un_intento(antes_de_0009):
    """`user_user` retenido 3,5 s desde el primer intento: más que un intento y menos que todos. 0009 termina en cuanto se
    suelta, conserva el nombre y el diferido de las cuatro claves, y ninguna lectura espera más que un intento (con la
    espera única de antes, toda la retención)."""
    intento = modulo.ESPERA_POR_INTENTO
    retencion_s = 3.5
    assert intento < retencion_s < modulo.INTENTOS * intento + (modulo.INTENTOS - 1) * modulo.PAUSA
    with Retencion(retencion_s) as retencion:
        migrar(MIGRACION)
        fin = time.monotonic()
    assert aplicada()
    assert retencion.pedida and fin >= retencion.soltada   # no pudo antes de que se soltara: hubo más de un intento
    duracion = fin - retencion.pedida
    despues = claves()
    assert {clave: fila[0] for clave, fila in despues.items()} == {clave: fila[0] for clave, fila in antes_de_0009.items()}
    assert set(despues) == CLAVES and {fila[1:] for fila in despues.values()} == {('n', True, True)}
    print(f'0009 retenida {retencion_s} s: bien a los {duracion:.2f} s del primer intento; lectura más lenta '
          f'{retencion.mayor_espera:.2f} s de {len(retencion.lecturas)}')   # se ve con -rP
    # Alguna lectura hizo cola detrás de un intento (el escenario es real), pero ninguna más que un intento y la holgura.
    assert 0.5 <= retencion.mayor_espera < intento + HOLGURA, (retencion.mayor_espera, duracion)


def test_retenido_mas_que_todos_los_intentos_0009_falla_limpio(antes_de_0009, monkeypatch):
    """`user_user` retenido hasta que 0009 se rinde (tres intentos, para no alargar la prueba). Falla con un mensaje que
    dice qué tabla y qué hacer, no se anota como aplicada, las cuatro claves quedan como estaban y ninguna lectura espera
    más que un intento."""
    monkeypatch.setattr(modulo, 'INTENTOS', 3)
    intento = modulo.ESPERA_POR_INTENTO
    with Retencion(300) as retencion:
        with pytest.raises(RuntimeError) as fallo:
            migrar(MIGRACION)
        duracion = time.monotonic() - retencion.pedida
        retencion.soltar()
    mensaje = str(fallo.value)
    print(f'0009 retenida hasta rendirse: falla a los {duracion:.2f} s del primer intento; lectura más lenta '
          f'{retencion.mayor_espera:.2f} s de {len(retencion.lecturas)}; {mensaje}')   # se ve con -rP
    assert usuarios() in mensaje and '3 intentos' in mensaje and 'migrate' in mensaje and 'No se cambió nada' in mensaje
    assert duracion >= 3 * intento * 0.9 + 2 * modulo.PAUSA   # los tres intentos y sus pausas
    assert not aplicada()
    assert claves() == antes_de_0009
    assert 0.5 <= retencion.mayor_espera < intento + HOLGURA, (retencion.mayor_espera, duracion)
