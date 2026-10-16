"""Tarifa de los productos y de las líneas ya vendidas, a partir de «¿Se cobra impuesto?» y del IVA de cada venta."""
from decimal import Decimal

from django.db import migrations

# IVA de la venta (fracción) → código de porcentaje (tabla 17 del SRI).
CODIGO_POR_IVA = {Decimal('0.15'): '4', Decimal('0.12'): '2', Decimal('0.14'): '3', Decimal('0.13'): '10', Decimal('0.05'): '5'}


def poblar(apps, schema_editor):
    Product = apps.get_model('pos', 'Product')
    SaleDetail = apps.get_model('pos', 'SaleDetail')
    CreditNoteDetail = apps.get_model('pos', 'CreditNoteDetail')
    Product.objects.filter(tarifa_iva='', with_tax=True).update(tarifa_iva='4')
    Product.objects.filter(tarifa_iva='').update(tarifa_iva='0')
    SaleDetail.objects.filter(codigo_porcentaje='', product__with_tax=False).update(codigo_porcentaje='0')
    for iva, codigo in CODIGO_POR_IVA.items():
        SaleDetail.objects.filter(codigo_porcentaje='', sale__iva=iva).update(codigo_porcentaje=codigo)
    SaleDetail.objects.filter(codigo_porcentaje='').update(codigo_porcentaje='4')
    for detalle in CreditNoteDetail.objects.filter(codigo_porcentaje='').select_related('sale_detail').iterator():
        detalle.codigo_porcentaje = detalle.sale_detail.codigo_porcentaje
        detalle.save(update_fields=['codigo_porcentaje'])


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0015_tarifa_iva_por_producto'),
    ]

    operations = [
        migrations.RunPython(poblar, migrations.RunPython.noop),
    ]
