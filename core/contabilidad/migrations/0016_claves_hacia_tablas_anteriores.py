"""Las 26 claves foráneas de las tablas del libro (0011) y de la apertura (0012) hacia tablas que ya existían antes del
bloque 2 (hallazgo C2E-1): `pos_company` (las 19 tablas), `contabilidad_cuenta` (seis: `lineaasiento.cuenta`,
`saldocuentames.cuenta`, `contabilizacion.tesoreria_cuenta`, `auxiliarapertura.cuenta`,
`aplicacionauxiliar.cuenta_contrapartida` y `lineaapertura.cuenta`) y `contabilidad_movimientomanual` (una,
`auxiliarapertura.movimiento_kardex`).

0011 y 0012 crean sus tablas sin ellas (`AplazarClaves`, su última operación) y esta migración, sola y al final del
corte, las crea con el nombre y la definición que les daba Django (diferidas, sin acción al borrar). Es la única del
corte que toma un bloqueo que choca con las escrituras de la versión publicada (`ShareRowExclusiveLock` sobre
`pos_company` y `contabilidad_movimientomanual`; también sobre `contabilidad_cuenta`, del bloque 1), y solo mientras
duran 26 ALTER TABLE sobre tablas vacías, en intentos que esperan el bloqueo como mucho 1 s, como 0009. Hacia atrás
las quita (`AccessExclusiveLock` sobre esas tres, con los mismos intentos), y así la vuelta de 0012 y 0011 borra sus
tablas sin tocarlas. En SQLite no hace nada. Detalle y medidas: core/contabilidad/migrations/_claves_aplazadas.py."""
from django.db import migrations

from core.contabilidad.migrations._claves_aplazadas import CrearClavesAplazadas

# (modelo, campo): las de 0011 y después las de 0012, en el orden de sus `AplazarClaves`.
CLAVES = (
    ('asiento', 'company'), ('ejerciciocontable', 'company'), ('iniciocontable', 'company'), ('lineaasiento', 'company'),
    ('lineaasiento', 'cuenta'), ('periodocontable', 'company'), ('registroclave', 'company'),
    ('saldocuentames', 'company'), ('saldocuentames', 'cuenta'), ('contabilizacion', 'company'),
    ('contabilizacion', 'tesoreria_cuenta'),
    ('apertura', 'company'), ('ajusteapertura', 'company'), ('auxiliarapertura', 'company'),
    ('auxiliarapertura', 'cuenta'), ('auxiliarapertura', 'movimiento_kardex'), ('aplicacionauxiliar', 'company'),
    ('aplicacionauxiliar', 'cuenta_contrapartida'), ('coberturaperiodo', 'company'), ('eventoapertura', 'company'),
    ('importacionapertura', 'company'), ('lineaapertura', 'company'), ('lineaapertura', 'cuenta'),
    ('partidabancoapertura', 'company'), ('respaldoapertura', 'company'), ('vinculohistorico', 'company'),
)


class Migration(migrations.Migration):

    dependencies = [('contabilidad', '0015_permisos_apertura')]

    operations = [CrearClavesAplazadas(claves=CLAVES)]
