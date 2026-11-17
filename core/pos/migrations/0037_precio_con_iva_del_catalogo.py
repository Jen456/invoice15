"""Precio de venta con IVA de los productos existentes: el precio final con que salen hoy, pvp × (1 + tarifa) a centavos con
mitad hacia arriba (decisión de la propietaria del 16/11/2026; la usuaria puede corregirlo después). Con la tarifa del
producto (tarifa_iva o, sin ella, «¿Se cobra impuesto?»). pvp no cambia: medio_arriba(P × 100, 100 + t) vuelve a dar
exactamente el pvp de partida para todo pvp y t ≥ 0.

Solo las filas con precio_con_iva NULL (se puede repetir). En PostgreSQL corre con app.platform=on (desplegar.sh) para ver
todas las empresas; sin él no actualiza nada y el código lo deriva igual de pvp. Bloquea solo las filas de pos_product que
actualiza (UPDATE por lotes de 500), no la tabla.

Vuelta: no hace nada (la columna la quita la vuelta de pos 0036).
"""
from decimal import Decimal

from django.db import migrations

PORCENTAJE = {'0': 0, '2': 12, '3': 14, '4': 15, '5': 5, '6': 0, '7': 0, '10': 13}   # PORCENTAJE_IVA de core/pos/choices.py


def medio_arriba(a, b):
    return (2 * a + b) // (2 * b)


def con_iva(pvp, tarifa):
    centavos = int((Decimal(pvp) * 100).to_integral_value())   # pvp es DecimalField(9, 2): siempre entero en centavos
    return (Decimal(medio_arriba(centavos * (100 + tarifa), 100)) / 100).quantize(Decimal('0.01'))


def poblar(apps, schema_editor):
    Product = apps.get_model('pos', 'Product')
    pendientes = Product.objects.filter(precio_con_iva__isnull=True).only('pk', 'pvp', 'tarifa_iva', 'with_tax').order_by('pk')
    lote = []
    for producto in pendientes.iterator(chunk_size=500):
        tarifa = PORCENTAJE.get(producto.tarifa_iva or ('4' if producto.with_tax else '0'), 0)
        producto.precio_con_iva = con_iva(producto.pvp, tarifa)
        lote.append(producto)
        if len(lote) == 500:
            Product.objects.bulk_update(lote, ['precio_con_iva'])
            lote = []
    if lote:
        Product.objects.bulk_update(lote, ['precio_con_iva'])


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0036_precios_con_iva'),
    ]

    operations = [
        migrations.RunPython(poblar, migrations.RunPython.noop),
    ]
