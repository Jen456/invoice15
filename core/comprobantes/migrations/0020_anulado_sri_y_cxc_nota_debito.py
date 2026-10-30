"""Etapa 2 · ventas y empresa (O2): marca «Anulado en el SRI» en retención, liquidación, nota de débito y guía (vacía en
las existentes, con su permiso), y cuenta por cobrar propia de la nota de débito.

La nota de débito crea su cuenta por cobrar al autorizarse: las existentes quedan en 'no_aplica' (AddField con ese valor) y
las nuevas en 'pendiente' (AlterField); lo histórico no se recalcula. Sin RunPython sobre datos de negocio.

Encadenamiento: depende de comprobantes 0013 mientras D0 no esté en plataforma; el integrador la re-encadena a la última
de D0.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('comprobantes', '0015_vigencias_res_28'),
        ('pos', '0030_cxc_abonos_anulados_empresa'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='guiaremision',
            options={'default_permissions': (), 'ordering': ('-id',), 'permissions': (('view_guiaremision', 'Puede ver guías de remisión'), ('add_guiaremision', 'Puede emitir guías de remisión'), ('delete_guiaremision', 'Puede eliminar guías de remisión no enviadas'), ('change_anulado_sri_guiaremision', 'Puede marcar guías de remisión como anuladas en el SRI')), 'verbose_name': 'Guía de remisión', 'verbose_name_plural': 'Guías de remisión'},
        ),
        migrations.AlterModelOptions(
            name='liquidacioncompra',
            options={'default_permissions': (), 'ordering': ('-id',), 'permissions': (('view_liquidacioncompra', 'Puede ver liquidaciones de compra'), ('add_liquidacioncompra', 'Puede emitir liquidaciones de compra'), ('delete_liquidacioncompra', 'Puede eliminar liquidaciones de compra no enviadas'), ('change_anulado_sri_liquidacioncompra', 'Puede marcar liquidaciones de compra como anuladas en el SRI')), 'verbose_name': 'Liquidación de compra', 'verbose_name_plural': 'Liquidaciones de compra'},
        ),
        migrations.AlterModelOptions(
            name='notadebito',
            options={'default_permissions': (), 'ordering': ('-id',), 'permissions': (('view_notadebito', 'Puede ver notas de débito'), ('add_notadebito', 'Puede emitir notas de débito'), ('delete_notadebito', 'Puede eliminar notas de débito no enviadas'), ('change_anulado_sri_notadebito', 'Puede marcar notas de débito como anuladas en el SRI')), 'verbose_name': 'Nota de débito', 'verbose_name_plural': 'Notas de débito'},
        ),
        migrations.AlterModelOptions(
            name='retencion',
            options={'default_permissions': (), 'ordering': ('-id',), 'permissions': (('view_retencion', 'Puede ver retenciones'), ('add_retencion', 'Puede emitir retenciones'), ('delete_retencion', 'Puede eliminar retenciones no enviadas'), ('change_anulado_sri_retencion', 'Puede marcar retenciones como anuladas en el SRI')), 'verbose_name': 'Comprobante de retención', 'verbose_name_plural': 'Comprobantes de retención'},
        ),
        migrations.AddField(
            model_name='guiaremision',
            name='anulado_sri_fecha',
            field=models.DateField(blank=True, null=True, verbose_name='Anulado en el SRI el'),
        ),
        migrations.AddField(
            model_name='guiaremision',
            name='anulado_sri_motivo',
            field=models.CharField(blank=True, default='', max_length=300, verbose_name='Motivo de la anulación'),
        ),
        migrations.AddField(
            model_name='guiaremision',
            name='anulado_sri_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Marcado por'),
        ),
        migrations.AddField(
            model_name='guiaremision',
            name='anulado_sri_registrado_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Marcado en el sistema el'),
        ),
        migrations.AddField(
            model_name='liquidacioncompra',
            name='anulado_sri_fecha',
            field=models.DateField(blank=True, null=True, verbose_name='Anulado en el SRI el'),
        ),
        migrations.AddField(
            model_name='liquidacioncompra',
            name='anulado_sri_motivo',
            field=models.CharField(blank=True, default='', max_length=300, verbose_name='Motivo de la anulación'),
        ),
        migrations.AddField(
            model_name='liquidacioncompra',
            name='anulado_sri_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Marcado por'),
        ),
        migrations.AddField(
            model_name='liquidacioncompra',
            name='anulado_sri_registrado_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Marcado en el sistema el'),
        ),
        migrations.AddField(
            model_name='notadebito',
            name='anulado_sri_fecha',
            field=models.DateField(blank=True, null=True, verbose_name='Anulado en el SRI el'),
        ),
        migrations.AddField(
            model_name='notadebito',
            name='anulado_sri_motivo',
            field=models.CharField(blank=True, default='', max_length=300, verbose_name='Motivo de la anulación'),
        ),
        migrations.AddField(
            model_name='notadebito',
            name='anulado_sri_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Marcado por'),
        ),
        migrations.AddField(
            model_name='notadebito',
            name='anulado_sri_registrado_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Marcado en el sistema el'),
        ),
        migrations.AddField(
            model_name='notadebito',
            name='cuenta_por_cobrar',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='nota_debito', to='pos.ctascollect', verbose_name='Cuenta por cobrar creada'),
        ),
        # Las notas de débito existentes quedan en 'no_aplica'; las nuevas, en 'pendiente'.
        migrations.AddField(
            model_name='notadebito',
            name='cxc_ajuste',
            field=models.CharField(choices=[('no_aplica', 'Anterior a la regla: no ajusta la cuenta por cobrar'), ('pendiente', 'Se aplica al autorizarse'), ('aplicada', 'Aplicada a la cuenta por cobrar'), ('parcial', 'Aplicada en parte: el resto excede el saldo'), ('sin_cxc', 'Venta de contado: sin cuenta por cobrar'), ('sin_saldo', 'La cuenta por cobrar ya estaba saldada'), ('revertida', 'Revertida al anular el comprobante')], default='no_aplica', max_length=12, verbose_name='Cuenta por cobrar'),
        ),
        migrations.AlterField(
            model_name='notadebito',
            name='cxc_ajuste',
            field=models.CharField(choices=[('no_aplica', 'Anterior a la regla: no ajusta la cuenta por cobrar'), ('pendiente', 'Se aplica al autorizarse'), ('aplicada', 'Aplicada a la cuenta por cobrar'), ('parcial', 'Aplicada en parte: el resto excede el saldo'), ('sin_cxc', 'Venta de contado: sin cuenta por cobrar'), ('sin_saldo', 'La cuenta por cobrar ya estaba saldada'), ('revertida', 'Revertida al anular el comprobante')], default='pendiente', max_length=12, verbose_name='Cuenta por cobrar'),
        ),
        migrations.AddField(
            model_name='retencion',
            name='anulado_sri_fecha',
            field=models.DateField(blank=True, null=True, verbose_name='Anulado en el SRI el'),
        ),
        migrations.AddField(
            model_name='retencion',
            name='anulado_sri_motivo',
            field=models.CharField(blank=True, default='', max_length=300, verbose_name='Motivo de la anulación'),
        ),
        migrations.AddField(
            model_name='retencion',
            name='anulado_sri_por',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Marcado por'),
        ),
        migrations.AddField(
            model_name='retencion',
            name='anulado_sri_registrado_en',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Marcado en el sistema el'),
        ),
    ]
