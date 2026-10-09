"""Migración controlada a multiempresa: conserva todos los datos existentes.

- Da un UUID propio a cada empresa.
- Si hay datos sin empresa, los asigna a la primera empresa registrada (o a una
  "EMPRESA INICIAL" provisional si no existe ninguna). No borra ni reemplaza nada.
- Crea los roles de empresa y una membresía para cada usuario existente:
  clientes → Cliente; superusuarios → Propietario; personal → su mismo grupo
  (Administrador u otro creado por la empresa).
Con una base vacía solo crea los roles (si ya hay módulos).
"""
import uuid

from django.db import migrations

TENANT_MODELS = ['Provider', 'Category', 'Product', 'Purchase', 'PurchaseDetail', 'Client', 'Receipt', 'Sale',
                 'SaleDetail', 'CtasCollect', 'PaymentsCtaCollect', 'DebtsPay', 'PaymentsDebtsPay', 'TypeExpense',
                 'Expenses', 'Promotions', 'PromotionsDetail', 'VoucherErrors', 'CreditNote', 'CreditNoteDetail']


def forwards(apps, schema_editor):
    from core.tenancy.roles import strip_platform_modules, sync_roles

    Company = apps.get_model('pos', 'Company')
    Client = apps.get_model('pos', 'Client')
    Group = apps.get_model('auth', 'Group')
    User = apps.get_model('user', 'User')
    Membership = apps.get_model('tenancy', 'Membership')
    Module = apps.get_model('security', 'Module')
    GroupModule = apps.get_model('security', 'GroupModule')

    for company in Company.objects.filter(uuid__isnull=True):
        company.uuid = uuid.uuid4()
        company.save(update_fields=['uuid'])

    if Module.objects.exists():
        sync_roles(Group, Module, GroupModule)
        strip_platform_modules(Group, GroupModule)

    pending = [apps.get_model('pos', name) for name in TENANT_MODELS]
    has_orphans = any(model.objects.filter(company__isnull=True).exists() for model in pending)
    initial = Company.objects.order_by('id').first()
    if initial is None and not has_orphans and not User.objects.filter(is_superuser=False).exists():
        return
    if initial is None:
        initial = Company.objects.create(
            ruc='9999999999999', business_name='EMPRESA INICIAL', tradename='EMPRESA INICIAL',
            main_address='PENDIENTE', establishment_address='PENDIENTE', establishment_code='001',
            issuing_point_code='001', special_taxpayer='000', mobile='0000000000', phone='000000000',
            email='pendiente@example.com', website='', electronic_signature_key='', email_host_user='',
            email_host_password='', uuid=uuid.uuid4())

    for model in pending:
        model.objects.filter(company__isnull=True).update(company=initial)

    def role(name):
        return Group.objects.get_or_create(name=name)[0]

    client_user_ids = set(Client.objects.values_list('user_id', flat=True))
    for user in User.objects.all():
        if user.id in client_user_ids:
            group = role('Cliente')
        elif user.is_superuser:
            group = role('Propietario')
        else:
            group = user.groups.exclude(name='Cliente').order_by('id').first()
            if group is None:
                continue
        Membership.objects.get_or_create(user=user, company=initial, defaults={'group': group})


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0003_multiempresa_esquema'),
        ('tenancy', '0001_multiempresa_esquema'),
        ('security', '0002_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
