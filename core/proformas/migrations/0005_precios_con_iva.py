"""Precios con IVA incluido en las líneas de proforma (entregas/facturaporaqui/CONTRATO-PRECIOS-CON-IVA.md). Solo agrega
ProformaDetalle.precio_con_iva y precio_unitario, NULL en las líneas existentes, que siguen con su precio sin IVA y
calcular_linea_iva. Una versión anterior que inserte líneas sin estas columnas sigue funcionando (quedan NULL).

Vuelta: `migrate proformas 0004_borrador_factura` quita las dos columnas; las proformas creadas con precios con IVA
conservan sus importes (price, subtotal, total, total_iva) calculados.
"""
from django.db import migrations, models


def limite_de_espera(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("SET LOCAL lock_timeout = '5s'")


class Migration(migrations.Migration):

    dependencies = [
        ('proformas', '0004_borrador_factura'),
    ]

    operations = [
        migrations.RunPython(limite_de_espera, migrations.RunPython.noop),
        migrations.AddField(
            model_name='proformadetalle',
            name='precio_con_iva',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=9, null=True, verbose_name='Precio unitario con IVA'),
        ),
        migrations.AddField(
            model_name='proformadetalle',
            name='precio_unitario',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=14, null=True, verbose_name='Precio unitario sin IVA (6 decimales)'),
        ),
    ]
