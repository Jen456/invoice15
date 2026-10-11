"""Mejora Plan 1000 → ilimitado por $35 con IVA incluido, con al menos un mes de vigencia restante.

Conserva el vencimiento y el consumo del período en curso; no inicia otro año.
Editable en /plataforma/ (Mejoras de plan). No sobrescribe una regla ya editada.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Plan = apps.get_model('suscripciones', 'Plan')
    PlanUpgrade = apps.get_model('suscripciones', 'PlanUpgrade')
    desde = Plan.objects.filter(code='plan-1000').first()
    hacia = Plan.objects.filter(code='ilimitado').first()
    if desde and hacia:
        PlanUpgrade.objects.get_or_create(from_plan=desde, to_plan=hacia,
                                          defaults={'price_cents': 3500, 'min_months': 1, 'is_active': True})


class Migration(migrations.Migration):

    dependencies = [
        ('suscripciones', '0003_mejora_por_diferencia'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
