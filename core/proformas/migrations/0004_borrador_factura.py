"""Primera entrega · «Convertir en factura» (primera-entrega/convertir-en-factura.md). Solo agrega:

- Proforma.medio_pago_sugerido («Transferencia bancaria»…; al facturar da la forma de pago del SRI) y
  Proforma.ocultar_vendedor (solo el PDF), los dos con db_default: las filas existentes quedan '' y False, y un INSERT que
  no los nombre sigue valiendo;
- la tabla BorradorFactura (una por proforma), con la misma seguridad por filas que las demás tablas de proformas. Guarda
  también el plazo (`time_limit`, días) y el vencimiento (`end_credit`) del crédito, opcionales.

Vuelta: `migrate proformas 0003_modulo_proformas` borra los borradores (no son comprobantes: nada salió al SRI) y
las dos columnas; las proformas, sus facturas y su vínculo no cambian. No depende de la última migración de pos (Client
ya existía en pos 0019, de la que cuelga proformas 0001): así la vuelta del diseño de factura (pos 0034) no la arrastra.
"""
import django.db.models.deletion
import django.db.models.manager
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

CONDITION = ("current_setting('app.platform', true) = 'on' "
             "OR company_id = NULLIF(current_setting('app.company_id', true), '')::integer")
TABLA = 'proformas_borradorfactura'


def rls_forwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    qn = schema_editor.quote_name
    schema_editor.execute(f'ALTER TABLE {qn(TABLA)} ENABLE ROW LEVEL SECURITY')
    schema_editor.execute(f'ALTER TABLE {qn(TABLA)} FORCE ROW LEVEL SECURITY')
    schema_editor.execute(f'CREATE POLICY fpa_empresa ON {qn(TABLA)} USING ({CONDITION}) WITH CHECK ({CONDITION})')


def rls_backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    qn = schema_editor.quote_name
    schema_editor.execute(f'DROP POLICY IF EXISTS fpa_empresa ON {qn(TABLA)}')
    schema_editor.execute(f'ALTER TABLE {qn(TABLA)} NO FORCE ROW LEVEL SECURITY')
    schema_editor.execute(f'ALTER TABLE {qn(TABLA)} DISABLE ROW LEVEL SECURITY')


class Migration(migrations.Migration):

    dependencies = [
        ('proformas', '0003_modulo_proformas'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='proforma',
            name='medio_pago_sugerido',
            field=models.CharField(blank=True, choices=[('efectivo', 'Efectivo'), ('transferencia', 'Transferencia bancaria'), ('deposito', 'Depósito bancario'), ('cheque', 'Cheque'), ('tarjeta_debito', 'Tarjeta de débito'), ('tarjeta_credito', 'Tarjeta de crédito'), ('compensacion', 'Compensación de deudas'), ('otro', 'Otro')], db_default='', default='', max_length=15, verbose_name='Medio de pago sugerido'),
        ),
        migrations.AddField(
            model_name='proforma',
            name='ocultar_vendedor',
            field=models.BooleanField(db_default=False, default=False, verbose_name='Ocultar el vendedor en el PDF'),
        ),
        migrations.CreateModel(
            name='BorradorFactura',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('payment_type', models.CharField(choices=[('efectivo', 'Contado'), ('credito', 'Crédito')], default='efectivo', max_length=10, verbose_name='Condición de pago')),
                ('payment_method', models.CharField(blank=True, choices=[('01', 'SIN UTILIZACION DEL SISTEMA FINANCIERO'), ('15', 'COMPENSACIÓN DE DEUDAS'), ('16', 'TARJETA DE DÉBITO'), ('17', 'DINERO ELECTRÓNICO'), ('18', 'TARJETA PREPAGO'), ('19', 'TARJETA DE CRÉDITO'), ('20', 'OTROS CON UTILIZACION DEL SISTEMA FINANCIERO'), ('21', 'ENDOSO DE TÍTULOS')], default='', max_length=2, verbose_name='Forma de pago del SRI')),
                ('medio_cobro', models.CharField(blank=True, choices=[('efectivo', 'Efectivo'), ('transferencia', 'Transferencia bancaria'), ('deposito', 'Depósito bancario'), ('cheque', 'Cheque'), ('tarjeta_debito', 'Tarjeta de débito'), ('tarjeta_credito', 'Tarjeta de crédito'), ('compensacion', 'Compensación de deudas'), ('otro', 'Otro')], default='', max_length=15, verbose_name='Medio de cobro')),
                ('time_limit', models.PositiveIntegerField(blank=True, null=True, verbose_name='Plazo (días)')),
                ('end_credit', models.DateField(blank=True, null=True, verbose_name='Fecha de plazo del crédito')),
                ('lineas', models.JSONField(default=list, verbose_name='Líneas')),
                ('info_adicional', models.JSONField(default=list, verbose_name='Información adicional')),
                ('avisos', models.JSONField(default=list, verbose_name='Avisos de la conversión')),
                ('creado_en', models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name='Creado el')),
                ('actualizado_en', models.DateTimeField(auto_now=True, verbose_name='Actualizado el')),
                ('actualizado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Actualizado por')),
                ('cliente', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='pos.client', verbose_name='Cliente')),
                ('company', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='pos.company', verbose_name='Empresa')),
                ('creado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Creado por')),
                ('proforma', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='borrador_factura', to='proformas.proforma', verbose_name='Proforma')),
            ],
            options={
                'verbose_name': 'Borrador de factura',
                'verbose_name_plural': 'Borradores de factura',
                'default_permissions': (),
            },
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_companies', django.db.models.manager.Manager()),
            ],
        ),
        migrations.RunPython(rls_forwards, rls_backwards),
    ]
