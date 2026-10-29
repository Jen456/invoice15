"""Seguridad por filas de PostgreSQL en las tablas de proformas (misma política que comprobantes 0012)."""
from django.db import migrations

CONDITION = ("current_setting('app.platform', true) = 'on' "
             "OR company_id = NULLIF(current_setting('app.company_id', true), '')::integer")
TABLAS = ('proformas_contadorproforma', 'proformas_proforma', 'proformas_proformadetalle')


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

    dependencies = [('proformas', '0001_inicial')]

    operations = [migrations.RunPython(forwards, backwards)]
