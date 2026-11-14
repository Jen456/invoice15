"""Al borrar un usuario, la base anula quién creó, editó, subió o confirmó cuentas y lotes del plan (solo PostgreSQL).

El modelo ya pide `SET_NULL`, pero Django lo hace con un UPDATE antes del borrado y, con la seguridad por filas forzada, ese
UPDATE solo alcanza a la empresa activa: quitar de su última empresa a un usuario que había creado cuentas en otra fallaba
al confirmar, porque la clave foránea diferida seguía viendo esas cuentas (ensayo del bloque 1). Una versión del código
que no conoce estas tablas, como la publicada (e0f2902), ni siquiera lo intenta. Con `ON DELETE SET NULL` lo hace la
base, que no aplica la seguridad por filas a sus acciones referenciales. Las claves siguen `DEFERRABLE INITIALLY
DEFERRED`, como las crea Django, y con el mismo nombre.

Cambiar la acción es quitar la restricción y volver a crearla, y quitarla toma un bloqueo exclusivo de `user_user` (medido:
`AccessExclusiveLock`; crearla toma `ShareRowExclusiveLock`). Mientras la migración espera ese bloqueo, toda lectura nueva
de `user_user` (cada petición con sesión) hace cola detrás de ella, y mientras lo tiene, también. Por eso lo pide en
intentos cortos. Cada intento va en su propio punto de guardado, toma primero las dos tablas del plan y al final
`user_user`, y espera cada bloqueo como mucho ESPERA_POR_INTENTO (`lock_timeout`). Si no lo consigue, vuelve al punto de
guardado (suelta lo que había tomado y las lecturas en cola pasan), espera PAUSA sin retener nada y lo intenta de nuevo,
hasta INTENTOS veces. Con `user_user` ya tomado no queda ningún bloqueo que esperar: los dos ALTER TABLE (uno por tabla,
con sus dos claves) van sobre tablas recién creadas y vacías y duran milisegundos, hasta que `migrate` confirma.

Peor caso, con los valores de abajo: las lecturas de `user_user` se paran como mucho 1 s por intento, en como mucho ocho
intentos separados por 2 s sin bloqueo (unos 22 s en total). Las de las tablas del plan, que la versión publicada no
conoce, se paran durante todo el intento (hasta tres esperas). Si se agotan los intentos, porque otra transacción retiene
`user_user` todo ese tiempo, `migrate` falla sin haber cambiado nada y el mensaje dice qué hacer: repetirlo, mejor con
poco tráfico. Un interbloqueo (una transacción que ya leyó `user_user` y quiere leer una tabla del plan que el intento ya
tomó) cuenta como un intento fallido: lo detecta primero la espera de la migración, que empezó antes.

Hacia atrás no hace nada: la base solo hace lo que el modelo ya pide, y deshacerlo volvería a bloquear `user_user`. Si se
deshace también 0007 o 0004, las restricciones se van con sus tablas.

Quien cambie más adelante una de estas cuatro claves con `AlterField` tiene que volver a poner la acción: Django 5.2 no
la conoce y recrearía la restricción sin ella. SQLite no tiene seguridad por filas y allí Django anula todas las filas."""
import time

from django.conf import settings
from django.db import OperationalError, migrations, transaction

CLAVES = (('cuenta', ('creada_por', 'actualizada_por')), ('importacioncuentas', ('creado_por', 'confirmado_por')))
ESPERA_POR_INTENTO = 1.0   # segundos que cada intento espera cada bloqueo, como mucho (`lock_timeout`)
PAUSA = 2.0                # segundos entre un intento y el siguiente, sin retener nada
INTENTOS = 8
# Lo que corta un intento: `lock_timeout` (lock_not_available) o un interbloqueo (deadlock_detected).
CORTES = {'55P03', '40P01'}


def _codigo(error):
    causa = error.__cause__
    return getattr(causa, 'sqlstate', None) or getattr(causa, 'pgcode', None)


def anular_en_la_base(apps, schema_editor):
    conexion = schema_editor.connection
    if conexion.vendor != 'postgresql':
        return
    usuario = apps.get_model(settings.AUTH_USER_MODEL)._meta
    nombre = schema_editor.quote_name
    tablas, alteraciones = [], []
    with conexion.cursor() as cursor:
        for modelo, campos in CLAVES:
            meta = apps.get_model('contabilidad', modelo)._meta
            cambios = []
            for campo in campos:
                columna = meta.get_field(campo).column
                cursor.execute(
                    'SELECT c.conname FROM pg_constraint c '
                    'JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) '
                    "WHERE c.contype = 'f' AND c.conrelid = %s::regclass AND c.confrelid = %s::regclass AND a.attname = %s",
                    [meta.db_table, usuario.db_table, columna])
                restricciones = [fila[0] for fila in cursor.fetchall()]
                if len(restricciones) != 1:
                    raise RuntimeError(f'{meta.db_table}.{columna}: se esperaba una clave foránea hacia {usuario.db_table} '
                                       f'y hay {len(restricciones)}')
                cambios += [f'DROP CONSTRAINT {nombre(restricciones[0])}',
                            f'ADD CONSTRAINT {nombre(restricciones[0])} FOREIGN KEY ({nombre(columna)}) '
                            f'REFERENCES {nombre(usuario.db_table)} ({nombre(usuario.pk.column)}) '
                            'ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED']
            tablas.append(nombre(meta.db_table))
            alteraciones.append(f'ALTER TABLE {nombre(meta.db_table)} ' + ', '.join(cambios))
        # Para toda la transacción de la migración: un punto de guardado deshecho desharía también el SET LOCAL.
        cursor.execute(f"SET LOCAL lock_timeout = '{round(ESPERA_POR_INTENTO * 1000)}ms'")
    corte = None
    for intento in range(1, INTENTOS + 1):
        if intento > 1:
            time.sleep(PAUSA)
        esperando = 'las tablas del plan de cuentas'
        try:
            with transaction.atomic(using=conexion.alias), conexion.cursor() as cursor:   # punto de guardado
                cursor.execute(f'LOCK TABLE {", ".join(tablas)} IN ACCESS EXCLUSIVE MODE')
                esperando = usuario.db_table
                cursor.execute(f'LOCK TABLE {nombre(usuario.db_table)} IN ACCESS EXCLUSIVE MODE')   # el último
                for alteracion in alteraciones:
                    cursor.execute(alteracion)
            return
        except OperationalError as error:
            if _codigo(error) not in CORTES:
                raise
            corte = error
    raise RuntimeError(
        f'contabilidad 0009: en {INTENTOS} intentos de {ESPERA_POR_INTENTO:g} s no se consiguió el bloqueo de {esperando}, '
        f'que retiene otra transacción. No se cambió nada: repite `migrate` (o el despliegue), mejor con poco tráfico.'
    ) from corte


class Migration(migrations.Migration):

    dependencies = [
        ('contabilidad', '0008_seguridad_por_filas_importacion'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(anular_en_la_base, migrations.RunPython.noop, elidable=False),
    ]
