"""Seguridad por filas de PostgreSQL en los movimientos manuales y los ajustes de stock del kardex (como tributario 0002)."""
from django.db import migrations

CONDITION = ("current_setting('app.platform', true) = 'on' "
             "OR company_id = NULLIF(current_setting('app.company_id', true), '')::integer")
TABLAS = ('contabilidad_movimientomanual', 'contabilidad_ajusteinventario')


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    qn = schema_editor.quote_name
    for tabla in TABLAS:
        schema_editor.execute(f'ALTER TABLE {qn(tabla)} ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {qn(tabla)} FORCE ROW LEVEL SECURITY')
        schema_editor.execute(f'CREATE POLICY fpa_empresa ON {qn(tabla)} USING ({CONDITION}) WITH CHECK ({CONDITION})')


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    qn = schema_editor.quote_name
    for tabla in TABLAS:
        schema_editor.execute(f'DROP POLICY IF EXISTS fpa_empresa ON {qn(tabla)}')
        schema_editor.execute(f'ALTER TABLE {qn(tabla)} NO FORCE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {qn(tabla)} DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):

    dependencies = [('contabilidad', '0001_kardex')]

    operations = [migrations.RunPython(forwards, backwards)]
