"""Cuentas por pagar con base de cálculo (subtotal en las existentes: sin abonos automáticos), pagos y gastos con medio de
pago y referencia (MEDIOS_DE_PAGO, vacío = sin dato) y tipos de gasto con cuenta contable y sustento sin indicar
(espec-etapa2-compras §1.5 y §1.6). Reversible.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0022_detalle_compra_tarifa'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='paymentsdebtspay',
            options={'default_permissions': (), 'ordering': ('id',), 'verbose_name': 'Det. Cuenta por pagar', 'verbose_name_plural': 'Det. Cuentas por pagar'},
        ),
        migrations.AddField(
            model_name='debtspay',
            name='base_calculo',
            field=models.CharField(choices=[('subtotal', 'Subtotal sin IVA (sin abonos automáticos)'), ('total', 'Total con IVA')], default='subtotal', max_length=10, verbose_name='Base de cálculo'),
        ),
        migrations.AddField(
            model_name='expenses',
            name='medio_pago',
            field=models.CharField(blank=True, choices=[('efectivo', 'Efectivo'), ('transferencia', 'Transferencia'), ('deposito', 'Depósito'), ('cheque', 'Cheque'), ('tarjeta_debito', 'Tarjeta de débito'), ('tarjeta_credito', 'Tarjeta de crédito'), ('compensacion', 'Compensación de deudas'), ('otro', 'Otro')], default='', max_length=15, verbose_name='Medio de pago'),
        ),
        migrations.AddField(
            model_name='expenses',
            name='referencia',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='Referencia (n.º de transferencia, cheque o comprobante)'),
        ),
        migrations.AddField(
            model_name='paymentsdebtspay',
            name='medio_pago',
            field=models.CharField(blank=True, choices=[('efectivo', 'Efectivo'), ('transferencia', 'Transferencia'), ('deposito', 'Depósito'), ('cheque', 'Cheque'), ('tarjeta_debito', 'Tarjeta de débito'), ('tarjeta_credito', 'Tarjeta de crédito'), ('compensacion', 'Compensación de deudas'), ('otro', 'Otro')], default='', max_length=15, verbose_name='Medio de pago'),
        ),
        migrations.AddField(
            model_name='paymentsdebtspay',
            name='referencia',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='Referencia (n.º de transferencia, cheque o comprobante)'),
        ),
        migrations.AddField(
            model_name='paymentsdebtspay',
            name='registrado_en',
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Registrado el'),
        ),
        migrations.AddField(
            model_name='paymentsdebtspay',
            name='registrado_por',
            field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Registrado por'),
        ),
        migrations.AddField(
            model_name='typeexpense',
            name='cod_sustento',
            field=models.CharField(blank=True, choices=[('01', 'Crédito tributario para declaración de IVA (servicios y bienes distintos de inventarios y activos fijos)'), ('02', 'Costo o gasto para declaración de IR (servicios y bienes distintos de inventarios y activos fijos)'), ('03', 'Activo fijo - Crédito tributario para declaración de IVA'), ('04', 'Activo fijo - Costo o gasto para declaración de IR'), ('05', 'Liquidación de gastos de viaje, hospedaje y alimentación, gastos IR (a nombre de empleados y no de la empresa)'), ('06', 'Inventario - Crédito tributario para declaración de IVA'), ('07', 'Inventario - Costo o gasto para declaración de IR'), ('08', 'Valor pagado para solicitar reembolso de gasto (intermediario)'), ('09', 'Reembolso por siniestros'), ('10', 'Distribución de dividendos, beneficios o utilidades'), ('11', 'Convenios de débito o recaudación para IFIs'), ('13', 'Valores reconocidos por entidades del sector público a favor de sujetos pasivos'), ('14', 'Valores facturados por socios a operadoras de transporte (que no constituyen gasto de dicha operadora)'), ('15', 'Pagos efectuados por consumos propios y de terceros de servicios digitales')], default='', max_length=2, verbose_name='Sustento tributario del tipo de gasto'),
        ),
        migrations.AddField(
            model_name='typeexpense',
            name='cuenta_contable',
            field=models.CharField(blank=True, default='', max_length=30, verbose_name='Cuenta contable'),
        ),
    ]
