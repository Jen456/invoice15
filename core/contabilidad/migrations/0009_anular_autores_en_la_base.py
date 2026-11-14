"""Al borrar un usuario, la base anula quién creó, editó, subió o confirmó cuentas y lotes del plan (solo PostgreSQL).

El modelo ya pide `SET_NULL`, pero Django lo hace con un UPDATE antes del borrado y, con la seguridad por filas forzada, ese
UPDATE solo alcanza a la empresa activa: quitar de su última empresa a un usuario que había creado cuentas en otra fallaba
al confirmar, porque la clave foránea diferida seguía viendo esas cuentas (ensayo del bloque 1). Una versión del código
que no conoce estas tablas, como la publicada (e0f2902), ni siquiera lo intenta. Con `ON DELETE SET NULL` lo hace la
base, que no aplica la seguridad por filas a sus acciones referenciales. Las claves siguen `DEFERRABLE INITIALLY
DEFERRED`, como las crea Django, y con el mismo nombre.

Cambiar la acción es quitar la restricción y volver a crearla, y quitarla toma un bloqueo exclusivo de `user_user` (medido:
`AccessExclusiveLock`; crearla toma `ShareRowExclusiveLock`): mientras dura, ninguna petición con sesión lee su usuario.
Al publicar dura milisegundos, porque las dos tablas se acaban de crear y están vacías; `lock_timeout` corta la espera
para conseguirlo si otra transacción tiene `user_user` ocupado, y entonces `migrate` falla sin haber cambiado nada (basta
repetirlo). Hacia atrás no hace nada: la base solo hace lo que el modelo ya pide, y deshacerlo volvería a bloquear
`user_user`. Si se deshace también 0007 o 0004, las restricciones se van con sus tablas.

Quien cambie más adelante una de estas cuatro claves con `AlterField` tiene que volver a poner la acción: Django 5.2 no
la conoce y recrearía la restricción sin ella. SQLite no tiene seguridad por filas y allí Django anula todas las filas."""
from django.conf import settings
from django.db import migrations

CLAVES = (('cuenta', ('creada_por', 'actualizada_por')), ('importacioncuentas', ('creado_por', 'confirmado_por')))
ESPERA_MAXIMA = '5s'


def anular_en_la_base(apps, schema_editor):
    conexion = schema_editor.connection
    if conexion.vendor != 'postgresql':
        return
    usuario = apps.get_model(settings.AUTH_USER_MODEL)._meta
    nombre = schema_editor.quote_name
    with conexion.cursor() as cursor:
        cursor.execute(f"SET LOCAL lock_timeout = '{ESPERA_MAXIMA}'")
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
            cursor.execute(f'ALTER TABLE {nombre(meta.db_table)} ' + ', '.join(cambios))


class Migration(migrations.Migration):

    dependencies = [
        ('contabilidad', '0008_seguridad_por_filas_importacion'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(anular_en_la_base, migrations.RunPython.noop, elidable=False),
    ]
