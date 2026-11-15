"""Seguridad por filas de PostgreSQL en las 19 tablas del bloque 2 (como contabilidad 0002, 0005 y 0008): cada empresa solo
ve y solo escribe sus filas del libro y de la apertura, también en una consulta sin filtro o en un INSERT por SQL."""
from django.db import migrations

CONDITION = ("current_setting('app.platform', true) = 'on' "
             "OR company_id = NULLIF(current_setting('app.company_id', true), '')::integer")
TABLAS = (
    # Libro (contabilidad 0011)
    'contabilidad_iniciocontable', 'contabilidad_ejerciciocontable', 'contabilidad_periodocontable', 'contabilidad_asiento',
    'contabilidad_lineaasiento', 'contabilidad_saldocuentames', 'contabilidad_contabilizacion', 'contabilidad_registroclave',
    # Apertura (contabilidad 0012)
    'contabilidad_apertura', 'contabilidad_lineaapertura', 'contabilidad_importacionapertura', 'contabilidad_respaldoapertura',
    'contabilidad_ajusteapertura', 'contabilidad_auxiliarapertura', 'contabilidad_partidabancoapertura',
    'contabilidad_aplicacionauxiliar', 'contabilidad_vinculohistorico', 'contabilidad_coberturaperiodo',
    'contabilidad_eventoapertura',
)


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

    dependencies = [('contabilidad', '0012_apertura')]

    operations = [migrations.RunPython(forwards, backwards)]
