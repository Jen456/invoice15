"""Diseño de factura por empresa (DisenoFactura, aditiva) con la seguridad por filas de configuracion 0002.

Depende de pos 0019 (como configuracion 0001), no de la última de pos: la tabla solo apunta a Company y User, y así la vuelta
de la fase contable (test_migracion_vuelta_fase: pos → 0019) no la arrastra. Vuelta: `migrate configuracion 0003_modulo_puntos`
borra la tabla (y los diseños guardados) después de que 0005 quite el módulo del menú."""

import django.core.validators
import django.db.models.deletion
import django.db.models.manager
from django.conf import settings
from django.db import migrations, models

CONDITION = ("current_setting('app.platform', true) = 'on' "
             "OR company_id = NULLIF(current_setting('app.company_id', true), '')::integer")
TABLA = 'configuracion_disenofactura'


def rls(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    qn = schema_editor.quote_name
    schema_editor.execute(f'ALTER TABLE {qn(TABLA)} ENABLE ROW LEVEL SECURITY')
    schema_editor.execute(f'ALTER TABLE {qn(TABLA)} FORCE ROW LEVEL SECURITY')
    schema_editor.execute(f'CREATE POLICY fpa_empresa ON {qn(TABLA)} USING ({CONDITION}) WITH CHECK ({CONDITION})')


def sin_rls(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    qn = schema_editor.quote_name
    schema_editor.execute(f'DROP POLICY IF EXISTS fpa_empresa ON {qn(TABLA)}')
    schema_editor.execute(f'ALTER TABLE {qn(TABLA)} NO FORCE ROW LEVEL SECURITY')
    schema_editor.execute(f'ALTER TABLE {qn(TABLA)} DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):

    dependencies = [
        ('configuracion', '0003_modulo_puntos'),
        ('pos', '0019_orden_de_las_lineas'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DisenoFactura',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('estilo', models.CharField(choices=[('clasico', 'Clásico'), ('corporativo', 'Corporativo'), ('minimalista', 'Minimalista'), ('banda', 'Banda de marca'), ('compacto', 'Compacto')], max_length=20, verbose_name='Estilo')),
                ('color_principal', models.CharField(max_length=7, validators=[django.core.validators.RegexValidator('^#[0-9A-F]{6}\\Z', 'Escribe el color en formato #RRGGBB (seis dígitos hexadecimales).')], verbose_name='Color principal')),
                ('color_secundario', models.CharField(max_length=7, validators=[django.core.validators.RegexValidator('^#[0-9A-F]{6}\\Z', 'Escribe el color en formato #RRGGBB (seis dígitos hexadecimales).')], verbose_name='Color secundario')),
                ('version', models.PositiveSmallIntegerField(default=1, verbose_name='Versión del estilo')),
                ('actualizado_en', models.DateTimeField(auto_now=True, verbose_name='Actualizado el')),
                ('actualizado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Actualizado por')),
                ('company', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='pos.company', verbose_name='Empresa')),
            ],
            options={
                'verbose_name': 'Diseño de factura',
                'verbose_name_plural': 'Diseños de factura',
                'constraints': [models.UniqueConstraint(fields=('company',), name='un_diseno_factura_por_empresa')],
            },
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_companies', django.db.models.manager.Manager()),
            ],
        ),
        migrations.RunPython(rls, sin_rls),
    ]
