"""Bloqueos de las migraciones del corte 1 del bloque 2 sobre las tablas de la versión publicada, en PostgreSQL (hallazgo
C2E-1 y core/contabilidad/migrations/_claves_aplazadas.py).

En el ensayo con e0f2902 atendiendo, 0011 y 0012 retenían `ShareRowExclusiveLock` sobre `pos_company` 6 y 12 s (y 0012
también sobre `contabilidad_movimientomanual`, 8 s): sus claves foráneas hacia esas tablas iban entre los índices que
Django deja para el final de la migración. Ahora 0011 y 0012 las aplazan y las crea 0016, sola. Estas pruebas recorren
la vuelta del corte (hasta `contabilidad 0009`, el final del bloque 1) y otra ida y anotan, tras cada sentencia de
`migrate`, qué bloqueos de modo Share o más fuerte tiene su transacción (pg_locks de su propio proceso: no depende de
muestrear a tiempo). Solo 0016 puede tener uno sobre una tabla de lo publicado, y solo para sus ALTER TABLE.

Después, 0016 con `pos_company` ocupada desde otra conexión: espera en intentos cortos, como contabilidad 0009 (las
escrituras en `pos_company` hacen cola como mucho un intento), y si no consigue el bloqueo se rinde sin cambiar nada.

Transaccionales (`transaction=True`: cada migración confirma, como en `migrate`) y al final de la suite (`test_zz_*`);
al terminar, la base queda migrada hasta las hojas del grafo pase lo que pase. Marca `tiempos`: los márgenes son
holgados porque la máquina es compartida."""
import importlib
import threading
import time

import pytest
from django.db import connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder

from tests import ayudas_contables as ac
from tests import helpers

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
    pytest.mark.tiempos,
]

FINAL_DEL_BLOQUE_1 = '0009_anular_autores_en_la_base'
ANTERIOR, CORTA = '0015_permisos_apertura', '0016_claves_hacia_tablas_anteriores'
# Lo publicado (e0f2902): la última migración de cada app propia. Sus tablas son las que la versión publicada lee y
# escribe mientras `migrate` corre. Al publicar otra versión, se pone al día.
PUBLICADO = {'adjuntos': '0006_modulo_capturas', 'cobros': '0003_permisos_cobros',
             'comprobantes': '0023_modulo_retenciones_recibidas', 'configuracion': '0006_personalizacion_factura',
             'contabilidad': '0003_modulo_kardex', 'importacion': '0007_lotes_de_claves', 'pos': '0035_sale_ride_diseno',
             'proformas': '0003_modulo_proformas', 'security': '0003_orden_menu', 'suscripciones': '0006_plan_multiempresa',
             'tenancy': '0012_accion_diseno_factura', 'tributario': '0003_modulo_libros',
             'user': '0002_celular_y_confirmacion_de_correo'}
FUERTES = ['ShareLock', 'ShareRowExclusiveLock', 'ExclusiveLock', 'AccessExclusiveLock']
VENTANA = 1.0   # segundos: lo que puede durar, con la máquina tranquila, la retención de 0016
HOLGURA = 1.5   # segundos de más: la máquina está cargada


def tablas_publicadas():
    loader = MigrationLoader(None, ignore_no_migrations=True)
    estado = loader.project_state([(app, PUBLICADO.get(app, nombre)) for app, nombre in loader.graph.leaf_nodes()])
    return {modelo._meta.db_table for modelo in estado.apps.get_models()}


DEL_CORTE = {modelo._meta.db_table for modelo in ac.MODELOS_DEL_BLOQUE}   # las 19 tablas de 0011 y 0012


def hacia(destino):
    """Las claves foráneas de las 19 tablas del corte hacia `destino`."""
    return {clave: fila for clave, fila in claves_foraneas().items() if clave[0] in DEL_CORTE and fila[0] == destino}


def claves_foraneas():
    """{(tabla, columna): (destino, nombre, acción al borrar, diferible, diferida, validada)} de las tablas de contabilidad."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text, c.conname, c.confdeltype,
                   c.condeferrable, c.condeferred, c.convalidated
            FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
            WHERE c.contype = 'f' AND c.conrelid::regclass::text LIKE 'contabilidad\\_%%'""")
        return {(tabla, columna): tuple(resto) for tabla, columna, *resto in cursor.fetchall()}


class Registro:
    """Tras cada sentencia de `migrate` en `connection`, los bloqueos fuertes de su transacción, y en qué migración va."""

    def __init__(self):
        self.actual, self.sentencias, self.fin = None, [], {}

    def paso(self, accion, migracion=None, fake=False):
        if accion in ('apply_start', 'unapply_start'):
            self.actual = (accion.split('_')[0], migracion.app_label, migracion.name)
        elif accion in ('apply_success', 'unapply_success'):
            self.fin[self.actual] = time.monotonic()

    def __call__(self, execute, sql, params, many, context):
        inicio = time.monotonic()
        resultado = execute(sql, params, many, context)
        with connection.connection.cursor() as cursor:   # cursor de psycopg: no pasa por los envoltorios
            cursor.execute("SELECT c.relname, l.mode FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
                           "WHERE l.pid = pg_backend_pid() AND l.granted AND l.locktype = 'relation' AND l.mode = ANY (%s)",
                           [FUERTES])
            self.sentencias.append((self.actual, inicio, ' '.join(str(sql).split())[:400], set(cursor.fetchall())))
        return resultado

    def migrar(self, destinos):
        with connection.execute_wrapper(self):
            ejecutor = MigrationExecutor(connection, progress_callback=self.paso)
            ejecutor.migrate(destinos or ejecutor.loader.graph.leaf_nodes())

    def retenciones(self, tablas):
        """{migración: [(inicio, sentencia, bloqueos sobre `tablas`)] desde la primera sentencia que tiene uno}."""
        salida = {}
        for migracion, inicio, sql, bloqueos in self.sentencias:
            sobre = {(tabla, modo) for tabla, modo in bloqueos if tabla in tablas}
            if sobre or migracion in salida:
                salida.setdefault(migracion, []).append((inicio, sql, sobre))
        return salida


@pytest.fixture
def hojas_al_terminar():
    try:
        yield
    finally:
        ejecutor = MigrationExecutor(connection)
        ejecutor.migrate(ejecutor.loader.graph.leaf_nodes())
        assert MigrationRecorder(connection).migration_qs.filter(app='contabilidad', name=CORTA).exists()


def test_en_la_ida_y_en_la_vuelta_del_corte_solo_0016_bloquea_lo_publicado(hojas_al_terminar):
    publicadas = tablas_publicadas()
    assert {'pos_company', 'contabilidad_movimientomanual', 'user_user'} <= publicadas
    assert 'contabilidad_cuenta' not in publicadas and 'contabilidad_asiento' not in publicadas
    antes = claves_foraneas()
    vuelta, ida = Registro(), Registro()
    vuelta.migrar([('contabilidad', FINAL_DEL_BLOQUE_1)])
    assert not any(tabla.startswith('contabilidad_asiento') for tabla in connection.introspection.table_names())
    ida.migrar(None)
    corta = ('contabilidad', CORTA)
    for sentido, registro, modo, verbo in (('unapply', vuelta, 'AccessExclusiveLock', 'DROP CONSTRAINT'),
                                           ('apply', ida, 'ShareRowExclusiveLock', 'FOREIGN KEY')):
        retenciones = registro.retenciones(publicadas)
        assert set(retenciones) == {(sentido, *corta)}, sorted(retenciones)   # ni 0011 ni 0012, ni a la ida ni a la vuelta
        tramo = retenciones[(sentido, *corta)]
        # Retiene `pos_company` y `contabilidad_movimientomanual` (y nada más de lo publicado) solo para sus 26 ALTER TABLE.
        assert tramo[0][1].startswith('LOCK TABLE') and tramo[0][2] == {('pos_company', modo),
                                                                       ('contabilidad_movimientomanual', modo)}
        cuerpo = [sql for _, sql, _ in tramo[1:]]
        assert sum(verbo in sql for sql in cuerpo) == 26, cuerpo
        # Además, solo lo que hace `migrate` al terminar cada migración: soltar el punto de guardado, mirar el catálogo
        # (MigrationRecorder.ensure_schema) y anotarla en django_migrations.
        otras = [sql for sql in cuerpo if verbo not in sql and not sql.startswith((
            'RELEASE SAVEPOINT', 'SELECT', 'INSERT INTO "django_migrations"', 'DELETE FROM "django_migrations"'))]
        assert not otras, otras
        duracion = registro.fin[(sentido, *corta)] - tramo[0][0]
        print(f'{sentido} {CORTA}: {len(tramo)} sentencias con lo publicado bloqueado, {duracion:.2f} s hasta confirmar')
        assert duracion < VENTANA + HOLGURA
    # Las mismas claves que antes, con el mismo nombre, destino y definición (diferidas, sin acción al borrar).
    despues = claves_foraneas()
    assert despues == antes
    hacia_lo_anterior = {clave: fila for clave, fila in despues.items() if clave[0] in DEL_CORTE
                         and fila[0] in ('pos_company', 'contabilidad_cuenta', 'contabilidad_movimientomanual')}
    assert len(hacia_lo_anterior) == 26 and len(hacia('pos_company')) == 19
    assert {fila[2:] for fila in hacia_lo_anterior.values()} == {('a', True, True, True)}


class Ocupada:
    """Otra conexión abre una transacción, actualiza la empresa A (su `RowExclusiveLock` sobre `pos_company` dura hasta el
    final) y la mantiene hasta `segundos` después de ver a 0016 pidiendo su bloqueo, o hasta `soltar()`. Una tercera
    conexión escribe en la empresa B sin parar, cada escritura en su propia transacción, como una petición de la versión
    publicada, y anota cuánto tarda cada una."""

    def __init__(self, segundos, empresa_a, empresa_b):
        self.segundos, self.a, self.b = segundos, empresa_a, empresa_b
        self.tomada, self.suelta, self.parar = threading.Event(), threading.Event(), threading.Event()
        self.escrituras, self.errores, self.pedida, self.soltada = [], [], None, None
        self.hilos = [threading.Thread(target=self.retener), threading.Thread(target=self.escribir)]

    def actualizar(self, cursor, empresa):
        cursor.execute('UPDATE pos_company SET tradename = tradename WHERE id = %s', [empresa])

    def retener(self):
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                self.actualizar(cursor, self.a)
                self.tomada.set()
                limite = time.monotonic() + 300
                while self.pedida is None and not self.suelta.is_set() and time.monotonic() < limite:
                    cursor.execute("SELECT count(*) FROM pg_locks WHERE relation = 'pos_company'::regclass AND NOT granted "
                                   "AND mode = 'ShareRowExclusiveLock'")
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

    def escribir(self):
        try:
            with connection.cursor() as cursor:
                while not self.parar.is_set():
                    inicio = time.monotonic()
                    self.actualizar(cursor, self.b)
                    self.escrituras.append(time.monotonic() - inicio)
                    time.sleep(0.05)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            self.errores.append(e)
        finally:
            connections.close_all()

    def __enter__(self):
        for hilo in self.hilos:
            hilo.start()
        assert self.tomada.wait(60)
        time.sleep(0.3)
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


@pytest.fixture
def sin_0016(hojas_al_terminar):
    MigrationExecutor(connection).migrate([('contabilidad', ANTERIOR)])
    assert not hacia('pos_company') and not hacia('contabilidad_movimientomanual')
    return [helpers.crear_empresa(f'OCUPADA {letra}', plan=None).pk for letra in 'AB']


def aplicada():
    return MigrationRecorder(connection).migration_qs.filter(app='contabilidad', name=CORTA).exists()


def test_pos_company_ocupada_mas_que_un_intento_0016_termina_y_las_escrituras_esperan_como_mucho_un_intento(sin_0016):
    modulo = importlib.import_module('core.contabilidad.migrations._claves_aplazadas')
    intento, retencion_s = modulo.ESPERA_POR_INTENTO, 3.5
    assert intento < retencion_s < modulo.INTENTOS * intento + (modulo.INTENTOS - 1) * modulo.PAUSA
    with Ocupada(retencion_s, *sin_0016) as ocupada:
        MigrationExecutor(connection).migrate([('contabilidad', CORTA)])
        fin = time.monotonic()
    assert aplicada() and ocupada.pedida and fin >= ocupada.soltada   # no pudo antes de que se soltara
    assert len(hacia('pos_company')) == 19 and len(hacia('contabilidad_movimientomanual')) == 1
    print(f'0016 con pos_company ocupada {retencion_s} s: bien a los {fin - ocupada.pedida:.2f} s del primer intento; '
          f'escritura más lenta {max(ocupada.escrituras):.2f} s de {len(ocupada.escrituras)}')   # se ve con -rP
    assert 0.5 <= max(ocupada.escrituras) < intento + HOLGURA


def test_pos_company_ocupada_mas_que_todos_los_intentos_0016_falla_limpio(sin_0016, monkeypatch):
    modulo = importlib.import_module('core.contabilidad.migrations._claves_aplazadas')
    monkeypatch.setattr(modulo, 'INTENTOS', 3)
    intento = modulo.ESPERA_POR_INTENTO
    antes = claves_foraneas()
    with Ocupada(300, *sin_0016) as ocupada:
        with pytest.raises(RuntimeError) as fallo:
            MigrationExecutor(connection).migrate([('contabilidad', CORTA)])
        duracion = time.monotonic() - ocupada.pedida
        ocupada.soltar()
    mensaje = str(fallo.value)
    print(f'0016 con pos_company ocupada hasta rendirse: falla a los {duracion:.2f} s; escritura más lenta '
          f'{max(ocupada.escrituras):.2f} s de {len(ocupada.escrituras)}; {mensaje}')   # se ve con -rP
    assert 'pos_company' in mensaje and '3 intentos' in mensaje and 'No se cambió nada' in mensaje and 'migrate' in mensaje
    assert duracion >= 3 * intento * 0.9 + 2 * modulo.PAUSA
    assert not aplicada() and claves_foraneas() == antes
    assert 0.5 <= max(ocupada.escrituras) < intento + HOLGURA
