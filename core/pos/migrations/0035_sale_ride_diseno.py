"""Copia del diseño de factura en cada factura nueva (Sale.ride_diseno, aditiva y nula: las históricas quedan sin copia y
conservan el RIDE original). La fija core/pos/emision.preparar() en la primera firma; no entra en el XML ni en la firma.
Vuelta: `migrate pos 0034_cliente_nacimiento_opcional` (pierde las copias; los PDF ya guardados no cambian)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0034_cliente_nacimiento_opcional'),
    ]

    operations = [
        migrations.AddField(
            model_name='sale',
            name='ride_diseno',
            field=models.JSONField(blank=True, editable=False, null=True, verbose_name='Diseño del RIDE'),
        ),
    ]
