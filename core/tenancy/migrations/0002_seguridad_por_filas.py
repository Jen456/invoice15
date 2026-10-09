"""Seguridad por filas (RLS) de PostgreSQL en todas las tablas de datos de empresa.

Segunda barrera tras el filtro del ORM: aunque una consulta olvidara filtrar,
PostgreSQL solo devuelve y acepta filas de la empresa fijada en
`app.company_id`. `app.platform = on` (panel de plataforma, migraciones y
volcados) ve todas. FORCE aplica las políticas también al dueño de las tablas,
que es el rol con el que conecta la aplicación.
En SQLite (desarrollo) no hace nada.
"""
from django.db import migrations

from core.pos.migrations import TENANT_MODELS_FOR_RLS

CONDITION = ("current_setting('app.platform', true) = 'on' "
             "OR company_id = NULLIF(current_setting('app.company_id', true), '')::integer")


def tables(apps):
    return [apps.get_model('pos', name)._meta.db_table for name in TENANT_MODELS_FOR_RLS]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    qn = schema_editor.quote_name
    for table in tables(apps):
        schema_editor.execute(f'ALTER TABLE {qn(table)} ENABLE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {qn(table)} FORCE ROW LEVEL SECURITY')
        schema_editor.execute(f'CREATE POLICY fpa_empresa ON {qn(table)} USING ({CONDITION}) WITH CHECK ({CONDITION})')


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    qn = schema_editor.quote_name
    for table in tables(apps):
        schema_editor.execute(f'DROP POLICY IF EXISTS fpa_empresa ON {qn(table)}')
        schema_editor.execute(f'ALTER TABLE {qn(table)} NO FORCE ROW LEVEL SECURITY')
        schema_editor.execute(f'ALTER TABLE {qn(table)} DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):

    dependencies = [
        ('tenancy', '0001_multiempresa_esquema'),
        ('pos', '0005_multiempresa_obligatoria'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
