"""Planes publicados, IVA vigente y módulo «Plan y pagos».

Precios con IVA incluido, en centavos: Plan 1000 $50 y Plan ilimitado $85.
El plan «gratuito» solo fija los límites del inventario sin plan pagado; se
pueden ajustar en /plataforma/. No sobrescribe planes ya editados.
"""
from datetime import date

from django.db import migrations

PLANES = [
    dict(code='gratuito', name='Plan gratuito', description='Inventario con límites, sin facturación electrónica ni ventas',
         price_cents=0, document_limit=0, includes_billing=False, product_limit=50, provider_limit=10,
         purchase_limit_month=30, order=0),
    dict(code='plan-1000', name='Plan 1000', description='Hasta 1000 comprobantes electrónicos autorizados durante un año',
         price_cents=5000, document_limit=1000, includes_billing=True, order=1),
    dict(code='ilimitado', name='Plan ilimitado', description='Comprobantes electrónicos sin límite durante un año',
         price_cents=8500, document_limit=None, includes_billing=True, order=2),
]


def forwards(apps, schema_editor):
    from core.tenancy.roles import sync_roles

    Plan = apps.get_model('suscripciones', 'Plan')
    IvaRate = apps.get_model('suscripciones', 'IvaRate')
    for datos in PLANES:
        Plan.objects.get_or_create(code=datos['code'], defaults=datos)
    IvaRate.objects.get_or_create(rate='15.00', valid_from=date(2024, 4, 1), defaults={
        'legal_reference': 'Decreto Ejecutivo 198: tarifa general del IVA del 15 % desde el 1 de abril de 2024'})

    # Instalaciones existentes: el módulo se crea aquí. Las nuevas lo crea start_installation.
    Module = apps.get_model('security', 'Module')
    if Module.objects.exists() and not Module.objects.filter(url='/suscripcion/').exists():
        Module.objects.create(url='/suscripcion/', name='Plan y pagos', icon='fas fa-credit-card',
                              description='Permite ver el plan de la empresa y pagarlo con PayPhone')
        sync_roles(apps.get_model('auth', 'Group'), Module, apps.get_model('security', 'GroupModule'))


class Migration(migrations.Migration):

    dependencies = [
        ('suscripciones', '0001_initial'),
        ('security', '0002_initial'),
        ('tenancy', '0004_alter_auditlog_action'),
        ('pos', '0007_purchase_created_at'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
