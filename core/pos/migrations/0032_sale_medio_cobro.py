"""Medio con que se cobró una factura al contado (core/cobros): efectivo, transferencia, depósito, cheque, tarjeta…
Separado de la condición de pago (payment_type: contado 'efectivo' / 'credito', valores históricos). Las ventas
anteriores quedan sin dato (''): no se reclasifican."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0031_permisos_anulado_sri'),
    ]

    operations = [
        migrations.AddField(
            model_name='sale',
            name='medio_cobro',
            field=models.CharField(blank=True, choices=[('efectivo', 'Efectivo'), ('transferencia', 'Transferencia'), ('deposito', 'Depósito'), ('cheque', 'Cheque'), ('tarjeta_debito', 'Tarjeta de débito'), ('tarjeta_credito', 'Tarjeta de crédito'), ('compensacion', 'Compensación de deudas'), ('otro', 'Otro')], default='', max_length=15, verbose_name='Medio de cobro'),
        ),
    ]
