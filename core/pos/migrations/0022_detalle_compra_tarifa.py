"""Líneas de compra: de gasto (sin producto, con descripción y tipo de gasto) y con tarifa de IVA por línea; las
existentes quedan sin tarifa (codigo_porcentaje vacío, total e IVA NULL) (espec-etapa2-compras §1.4).

Reversa: falla si ya hay líneas sin producto.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0021_compra_datos_ats'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='purchasedetail',
            options={'default_permissions': (), 'ordering': ('id',), 'verbose_name': 'Detalle de Compra', 'verbose_name_plural': 'Detalle de Compras'},
        ),
        migrations.AddField(
            model_name='purchasedetail',
            name='codigo_porcentaje',
            field=models.CharField(blank=True, default='', max_length=2, verbose_name='Tarifa de IVA (código)'),
        ),
        migrations.AddField(
            model_name='purchasedetail',
            name='codigo_proveedor',
            field=models.CharField(blank=True, default='', max_length=25, verbose_name='Código del proveedor'),
        ),
        migrations.AddField(
            model_name='purchasedetail',
            name='descripcion',
            field=models.CharField(blank=True, default='', max_length=300, verbose_name='Descripción'),
        ),
        migrations.AddField(
            model_name='purchasedetail',
            name='tarifa',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, verbose_name='Tarifa de IVA aplicada (%)'),
        ),
        migrations.AddField(
            model_name='purchasedetail',
            name='total',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Base de la línea'),
        ),
        migrations.AddField(
            model_name='purchasedetail',
            name='total_dscto',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=9, verbose_name='Descuento'),
        ),
        migrations.AddField(
            model_name='purchasedetail',
            name='total_ice',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='ICE de la línea'),
        ),
        migrations.AddField(
            model_name='purchasedetail',
            name='total_iva',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='IVA de la línea'),
        ),
        migrations.AddField(
            model_name='purchasedetail',
            name='type_expense',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='pos.typeexpense', verbose_name='Tipo de gasto'),
        ),
        migrations.AlterField(
            model_name='purchasedetail',
            name='product',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='pos.product'),
        ),
        migrations.AddConstraint(
            model_name='purchasedetail',
            constraint=models.CheckConstraint(condition=models.Q(('product__isnull', False), models.Q(('descripcion', ''), _negated=True), _connector='OR'), name='detalle_compra_producto_o_descripcion'),
        ),
    ]
