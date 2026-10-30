"""Etapa 2 · ventas y empresa (O2): datos de origen de ventas.

- Empresa: tipo de contribuyente y periodicidad del IVA, en '' («Sin indicar») para las existentes: no se infiere nada.
- Factura y nota de crédito: marca «Anulado en el SRI» (vacía en las existentes), permiso para marcarla e índice por fecha
  de emisión.
- Nota de crédito: ajuste de la cuenta por cobrar. Las existentes quedan en 'no_aplica' (AddField con ese valor, que
  rellena las filas) y las nuevas en 'pendiente' (AlterField): lo histórico no se recalcula.
- Abonos: tipo ('cobro' en los existentes: hoy su único origen es el formulario de cobros), medio de pago y referencia
  vacíos («Sin dato»: no se inventan), registro y anulación vacíos.

Sin RunPython sobre datos de negocio.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0024_permiso_completar_compras'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='creditnote',
            options={'default_permissions': (), 'permissions': (('view_credit_note', 'Can view Nota de Credito'), ('add_credit_note', 'Can add Nota de Credito'), ('delete_credit_note', 'Can delete Nota de Credito'), ('view_credit_note_client', 'Can view_credit_note_client Nota de Credito'), ('change_anulado_sri_creditnote', 'Puede marcar notas de crédito como anuladas en el SRI')), 'verbose_name': 'Nota de Credito', 'verbose_name_plural': 'Notas de Credito'},
        ),
        migrations.AlterModelOptions(
            name='sale',
            options={'default_permissions': (), 'permissions': (('view_sale', 'Can view Venta'), ('add_sale', 'Can add Venta'), ('delete_sale', 'Can delete Venta'), ('view_sale_client', 'Can view_sale_client Venta'), ('change_anulado_sri_sale', 'Puede marcar facturas como anuladas en el SRI')), 'verbose_name': 'Venta', 'verbose_name_plural': 'Ventas'},
        ),
        migrations.AddField(
            model_name='company',
            name='periodicidad_iva',
            field=models.CharField(blank=True, choices=[('mensual', 'Mensual'), ('semestral', 'Semestral')], default='', help_text='Mensual. Semestral solo si vendes únicamente con tarifa 0 %, te retienen todo el IVA o estás en el RIMPE.', max_length=10, verbose_name='Declaración del IVA'),
        ),
        migrations.AddField(
            model_name='company',
            name='tipo_contribuyente',
            field=models.CharField(blank=True, choices=[('sociedad', 'Sociedad'), ('pn_obligada', 'Persona natural obligada a llevar contabilidad'), ('pn_no_obligada', 'Persona natural no obligada a llevar contabilidad')], default='', help_text='Sociedad o persona natural, obligada o no a llevar contabilidad. Define tus formularios y anexos.', max_length=20, verbose_name='Tipo de contribuyente'),
        ),
        migrations.AddField(
            model_name='creditnote',
            name='abono_cxc',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='nota_credito', to='pos.paymentsctacollect', verbose_name='Abono en la cuenta por cobrar'),
        ),
        migrations.AddField(
            model_name='creditnote',
            name='anulado_sri_fecha',
            field=models.DateField(blank=True, null=True, verbose_name='Anulado en el SRI el'),
        ),
        migrations.AddField(
            model_name='creditnote',
            name='anulado_sri_motivo',
            field=models.CharField(blank=True, default='', max_length=300, verbose_name='Motivo de la anulación'),
        ),
        migrations.AddField(
            model_name='creditnote',
            name='anulado_sri_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Marcado por'),
        ),
        migrations.AddField(
            model_name='creditnote',
            name='anulado_sri_registrado_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Marcado en el sistema el'),
        ),
        migrations.AddField(
            model_name='creditnote',
            name='anulado_sri_stock',
            field=models.BooleanField(default=False, verbose_name='Se ajustó el inventario al anular'),
        ),
        # Las notas existentes quedan en 'no_aplica'; las nuevas, en 'pendiente'.
        migrations.AddField(
            model_name='creditnote',
            name='cxc_ajuste',
            field=models.CharField(choices=[('no_aplica', 'Anterior a la regla: no ajusta la cuenta por cobrar'), ('pendiente', 'Se aplica al autorizarse'), ('aplicada', 'Aplicada a la cuenta por cobrar'), ('parcial', 'Aplicada en parte: el resto excede el saldo'), ('sin_cxc', 'Venta de contado: sin cuenta por cobrar'), ('sin_saldo', 'La cuenta por cobrar ya estaba saldada'), ('revertida', 'Revertida al anular el comprobante')], default='no_aplica', max_length=12, verbose_name='Ajuste de la cuenta por cobrar'),
        ),
        migrations.AlterField(
            model_name='creditnote',
            name='cxc_ajuste',
            field=models.CharField(choices=[('no_aplica', 'Anterior a la regla: no ajusta la cuenta por cobrar'), ('pendiente', 'Se aplica al autorizarse'), ('aplicada', 'Aplicada a la cuenta por cobrar'), ('parcial', 'Aplicada en parte: el resto excede el saldo'), ('sin_cxc', 'Venta de contado: sin cuenta por cobrar'), ('sin_saldo', 'La cuenta por cobrar ya estaba saldada'), ('revertida', 'Revertida al anular el comprobante')], default='pendiente', max_length=12, verbose_name='Ajuste de la cuenta por cobrar'),
        ),
        migrations.AddField(
            model_name='paymentsctacollect',
            name='anulado_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Abono anulado el'),
        ),
        migrations.AddField(
            model_name='paymentsctacollect',
            name='anulado_motivo',
            field=models.CharField(blank=True, default='', max_length=300, verbose_name='Motivo de la anulación del abono'),
        ),
        migrations.AddField(
            model_name='paymentsctacollect',
            name='medio_pago',
            field=models.CharField(blank=True, choices=[('efectivo', 'Efectivo'), ('transferencia', 'Transferencia'), ('deposito', 'Depósito'), ('cheque', 'Cheque'), ('tarjeta_debito', 'Tarjeta de débito'), ('tarjeta_credito', 'Tarjeta de crédito'), ('compensacion', 'Compensación de deudas'), ('otro', 'Otro')], default='', max_length=15, verbose_name='Medio de pago'),
        ),
        migrations.AddField(
            model_name='paymentsctacollect',
            name='referencia',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='Referencia (n.º de transferencia, cheque o comprobante)'),
        ),
        migrations.AddField(
            model_name='paymentsctacollect',
            name='registrado_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Registrado el'),
        ),
        migrations.AddField(
            model_name='paymentsctacollect',
            name='registrado_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Registrado por'),
        ),
        migrations.AddField(
            model_name='paymentsctacollect',
            name='tipo',
            field=models.CharField(choices=[('cobro', 'Cobro registrado'), ('nota_credito', 'Nota de crédito'), ('retencion', 'Retención recibida'), ('anulacion', 'Anulación en el SRI')], default='cobro', max_length=15, verbose_name='Tipo de abono'),
        ),
        migrations.AddField(
            model_name='sale',
            name='anulado_sri_fecha',
            field=models.DateField(blank=True, null=True, verbose_name='Anulado en el SRI el'),
        ),
        migrations.AddField(
            model_name='sale',
            name='anulado_sri_motivo',
            field=models.CharField(blank=True, default='', max_length=300, verbose_name='Motivo de la anulación'),
        ),
        migrations.AddField(
            model_name='sale',
            name='anulado_sri_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Marcado por'),
        ),
        migrations.AddField(
            model_name='sale',
            name='anulado_sri_registrado_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Marcado en el sistema el'),
        ),
        migrations.AddField(
            model_name='sale',
            name='anulado_sri_stock',
            field=models.BooleanField(default=False, verbose_name='Se ajustó el inventario al anular'),
        ),
        migrations.AddIndex(
            model_name='creditnote',
            index=models.Index(fields=['company', 'emission_date'], name='nc_emision'),
        ),
        migrations.AddIndex(
            model_name='sale',
            index=models.Index(fields=['company', 'emission_date'], name='venta_emision'),
        ),
    ]
