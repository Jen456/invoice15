"""Precios con IVA incluido (entregas/facturaporaqui/CONTRATO-PRECIOS-CON-IVA.md). Solo AGREGA columnas, todas aditivas:

- Product.precio_con_iva (NULL): el precio de venta con IVA del catálogo. Lo llena pos 0037; mientras sea NULL (o si una
  versión anterior cambia pvp) el código lo deriva de pvp.
- SaleDetail y CreditNoteDetail: precio_con_iva y precio_unitario (NULL) y descripcion ('' con db_default). Las líneas
  existentes quedan NULL / '' y siguen calculándose como siempre (calcular_linea_iva): nada de lo emitido cambia.

Con la versión publicada (e0f2902) y la del PR #1 (e0d7c38) funcionando sobre este esquema durante la publicación: sus
INSERT no nombran estas columnas y valen (NULL, o el DEFAULT '' de la base); sus lecturas no las ven. En PostgreSQL cada
ADD COLUMN es un cambio de catálogo (sin reescribir la tabla); lock_timeout de 5 s: si otra transacción retiene la tabla,
la migración falla sin cambiar nada (el despliegue se detiene con la versión anterior en servicio) en lugar de dejar en
cola a las demás consultas.

Vuelta: `migrate pos 0035_sale_ride_diseno` quita las columnas (las facturas emitidas con precios con IVA conservan sus
importes, su XML firmado y su RIDE; pierden la descripción y el precio con IVA de la línea, que solo usa este código).
"""
import django.core.validators
from decimal import Decimal
from django.db import migrations, models


def limite_de_espera(apps, schema_editor):
    """PostgreSQL: no esperar más de 5 s por el bloqueo de una tabla (dura solo esta transacción)."""
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("SET LOCAL lock_timeout = '5s'")


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0035_sale_ride_diseno'),
    ]

    operations = [
        migrations.RunPython(limite_de_espera, migrations.RunPython.noop),
        migrations.AddField(
            model_name='creditnotedetail',
            name='descripcion',
            field=models.CharField(blank=True, db_default='', default='', max_length=300, verbose_name='Descripción'),
        ),
        migrations.AddField(
            model_name='creditnotedetail',
            name='precio_con_iva',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=9, null=True, verbose_name='Precio unitario con IVA'),
        ),
        migrations.AddField(
            model_name='creditnotedetail',
            name='precio_unitario',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=14, null=True, verbose_name='Precio unitario sin IVA (XML, 6 decimales)'),
        ),
        migrations.AddField(
            model_name='product',
            name='precio_con_iva',
            field=models.DecimalField(decimal_places=2, max_digits=9, null=True, validators=[django.core.validators.MinValueValidator(Decimal('0')), django.core.validators.MaxValueValidator(Decimal('999999.99'))], verbose_name='Precio de venta (con IVA)'),
        ),
        migrations.AddField(
            model_name='saledetail',
            name='descripcion',
            field=models.CharField(blank=True, db_default='', default='', max_length=300, verbose_name='Descripción'),
        ),
        migrations.AddField(
            model_name='saledetail',
            name='precio_con_iva',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=9, null=True, verbose_name='Precio unitario con IVA'),
        ),
        migrations.AddField(
            model_name='saledetail',
            name='precio_unitario',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=14, null=True, verbose_name='Precio unitario sin IVA (XML, 6 decimales)'),
        ),
    ]
