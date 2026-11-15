"""Claves foráneas de tablas nuevas hacia tablas que ya existían, creadas al final en una migración corta (hallazgo C2E-1
del cierre del bloque 2, corte 1). Las usan `0011_libro_diario`, `0012_apertura` y `0016_claves_hacia_tablas_anteriores`.

En PostgreSQL, Django crea las claves foráneas de un `CreateModel` al final de la migración (`deferred_sql`, mezcladas
con los índices de esas columnas), y cada una toma `ShareRowExclusiveLock` sobre la tabla a la que apunta: choca con
toda escritura en ella y dura hasta que la migración confirma. Con la versión publicada atendiendo, 0011 y 0012
retenían así `pos_company` 6 y 12 s y `contabilidad_movimientomanual` 8 s (ensayo del corte, máquina cargada), porque
detrás de la primera clave hacia la empresa iban todavía decenas de índices y de claves. Quitar una de esas claves, o
borrar la tabla que la tiene, toma `AccessExclusiveLock` sobre la tabla a la que apunta (también contra las lecturas):
la vuelta de 0012 y 0011 paraba así todas las lecturas de `pos_company` mientras duraba.

- `AplazarClaves`, la última operación de 0011 y 0012, quita de `deferred_sql` las claves que nombra, y solo esas (si
  Django no las generó tal cual, falla sin migrar). El estado de Django no cambia: el modelo y la migración siguen
  diciendo que la clave existe, y existe en cuanto se aplica 0016.
- `CrearClavesAplazadas`, sola en 0016, las crea con el SQL y el nombre que Django les habría dado (`_create_fk_sql`,
  con su mismo sufijo): `DEFERRABLE INITIALLY DEFERRED` y sin acción al borrar. Como contabilidad 0009 con `user_user`,
  en intentos cortos: cada intento va en su propio punto de guardado, toma de una vez las tablas a las que apuntan las
  claves y espera ese bloqueo como mucho ESPERA_POR_INTENTO (`lock_timeout`); si no lo consigue (o hay un
  interbloqueo), vuelve al punto de guardado, espera PAUSA sin retener nada y lo intenta de nuevo, hasta INTENTOS
  veces. Con el bloqueo tomado solo quedan los ALTER TABLE sobre tablas recién creadas y vacías: milisegundos hasta que
  `migrate` confirma. Las claves que ya estén (en una base migrada con el corte de antes de este cambio, que las creaba
  en 0011 y 0012) no se repiten.
- Hacia atrás, 0016 las quita con los mismos intentos (`AccessExclusiveLock`), y la vuelta de 0012 y 0011 ya no toca
  `pos_company`, `contabilidad_cuenta` ni `contabilidad_movimientomanual`.

En SQLite las dos no hacen nada: allí la clave va dentro de CREATE TABLE, como antes, y nadie más escribe mientras se
migra. Ninguna de las dos se elide al aplastar migraciones."""
import time

from django.db import OperationalError, transaction
from django.db.backends.ddl_references import Statement
from django.db.migrations.operations.base import Operation

SUFIJO = '_fk_%(to_table)s_%(to_column)s'   # el que usa Django al crear una tabla o una columna con clave foránea
ESPERA_POR_INTENTO = 1.0   # segundos que cada intento espera el bloqueo, como mucho (`lock_timeout`)
PAUSA = 2.0                # segundos entre un intento y el siguiente, sin retener nada
INTENTOS = 8
# Lo que corta un intento: `lock_timeout` (lock_not_available) o un interbloqueo (deadlock_detected).
CORTES = {'55P03', '40P01'}


def _codigo(error):
    causa = error.__cause__
    return getattr(causa, 'sqlstate', None) or getattr(causa, 'pgcode', None)


def _campos(app_label, state, claves):
    """[(modelo, campo)] de `claves` ((nombre del modelo, nombre del campo)) en el estado dado."""
    salida = []
    for modelo, campo in claves:
        model = state.apps.get_model(app_label, modelo)
        salida.append((model, model._meta.get_field(campo)))
    return salida


def _destino(campo):
    return campo.target_field.model._meta.db_table


def _existentes(schema_editor, campos):
    """{(tabla, columna, tabla de destino): nombre} de las claves foráneas que ya hay en la base sobre esas tablas."""
    tablas = sorted({model._meta.db_table for model, _ in campos})
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            'SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text, c.conname FROM pg_constraint c '
            'JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) '
            "WHERE c.contype = 'f' AND c.conrelid = ANY (%s::regclass[])", [tablas])
        return {(tabla, columna, destino): nombre for tabla, columna, destino, nombre in cursor.fetchall()}


class AplazarClaves(Operation):
    """Última operación de una migración que crea tablas: quita de `deferred_sql` (PostgreSQL) las claves foráneas de
    `claves` ((modelo, campo) de un `CreateModel` de la misma migración), que crea después `CrearClavesAplazadas`."""

    reduces_to_sql = True
    reversible = True

    def __init__(self, claves):
        self.claves = tuple((modelo, campo) for modelo, campo in claves)

    def state_forwards(self, app_label, state):
        pass

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != 'postgresql':
            return
        esperadas = {(model._meta.db_table, campo.column) for model, campo in _campos(app_label, to_state, self.claves)}
        quitadas = set()
        for sql in list(schema_editor.deferred_sql):
            if not (isinstance(sql, Statement) and sql.template == schema_editor.sql_create_fk):
                continue
            columnas = sql.parts['column'].columns
            clave = (sql.parts['table'].table, columnas[0] if len(columnas) == 1 else tuple(columnas))
            if clave in esperadas:
                schema_editor.deferred_sql.remove(sql)
                quitadas.add(clave)
        if quitadas != esperadas:
            raise RuntimeError(f'AplazarClaves: Django no dejó para el final estas claves foráneas: '
                               f'{sorted(esperadas - quitadas)}. No se aplazó nada.')

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        pass   # la vuelta del CreateModel borra la tabla; la de 0016 ya quitó sus claves hacia lo anterior

    def describe(self):
        return f'Deja para el final {len(self.claves)} claves foráneas hacia tablas que ya existían'


class CrearClavesAplazadas(Operation):
    """Sola en su migración: crea (y, hacia atrás, quita) las claves foráneas de `claves` ((modelo, campo)), con el SQL
    y el nombre de Django, en intentos cortos (ver el docstring del módulo)."""

    reduces_to_sql = True
    reversible = True

    def __init__(self, claves):
        self.claves = tuple((modelo, campo) for modelo, campo in claves)

    def state_forwards(self, app_label, state):
        pass

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != 'postgresql':
            return
        campos = _campos(app_label, to_state, self.claves)
        hay = {} if schema_editor.collect_sql else _existentes(schema_editor, campos)
        sentencias = [schema_editor._create_fk_sql(model, campo, SUFIJO) for model, campo in campos
                      if (model._meta.db_table, campo.column, _destino(campo)) not in hay]
        self._en_intentos(app_label, schema_editor, campos, sentencias, 'SHARE ROW EXCLUSIVE', 'crear')

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != 'postgresql':
            return
        campos = _campos(app_label, from_state, self.claves)
        if schema_editor.collect_sql:
            nombres = [(model, schema_editor._fk_constraint_name(model, campo, SUFIJO)) for model, campo in campos]
        else:
            hay = _existentes(schema_editor, campos)
            nombres = [(model, hay[clave]) for model, campo in campos
                       if (clave := (model._meta.db_table, campo.column, _destino(campo))) in hay]
        sentencias = [schema_editor._delete_fk_sql(model, nombre) for model, nombre in nombres]
        self._en_intentos(app_label, schema_editor, campos, sentencias, 'ACCESS EXCLUSIVE', 'quitar')

    def _en_intentos(self, app_label, schema_editor, campos, sentencias, modo, verbo):
        if not sentencias:
            return
        conexion = schema_editor.connection
        nuevas = {model._meta.db_table for model, _ in campos}
        anteriores = sorted({_destino(campo) for _, campo in campos} - nuevas)
        bloqueo = f'LOCK TABLE {", ".join(map(schema_editor.quote_name, anteriores))} IN {modo} MODE'
        espera = f"SET LOCAL lock_timeout = '{round(ESPERA_POR_INTENTO * 1000)}ms'"
        if schema_editor.collect_sql:   # sqlmigrate: lo que ejecuta cada intento
            for sql in (espera, bloqueo, *sentencias):
                schema_editor.execute(sql, None)
            return
        # Para toda la transacción de la migración: un punto de guardado deshecho desharía también el SET LOCAL.
        schema_editor.execute(espera, None)
        corte = None
        for intento in range(1, INTENTOS + 1):
            if intento > 1:
                time.sleep(PAUSA)
            try:
                with transaction.atomic(using=conexion.alias):   # punto de guardado
                    schema_editor.execute(bloqueo, None)
                    for sql in sentencias:
                        schema_editor.execute(sql, None)
                return
            except OperationalError as error:
                if _codigo(error) not in CORTES:
                    raise
                corte = error
        raise RuntimeError(
            f'{app_label}, claves foráneas aplazadas: en {INTENTOS} intentos de {ESPERA_POR_INTENTO:g} s no se '
            f'consiguió el bloqueo de {", ".join(anteriores)} para {verbo} sus claves foráneas, porque otra transacción '
            f'lo retiene. No se cambió nada: repite `migrate` (o el despliegue), mejor con poco tráfico.') from corte

    def describe(self):
        return f'Crea al final, en intentos cortos, {len(self.claves)} claves foráneas hacia tablas que ya existían'
