"""Permisos del respaldo de cobros en los módulos «Facturas emitidas» y «Cuentas por cobrar», para instalaciones
existentes (las nuevas los reciben de start_installation). Los permisos del modelo se crean aquí mismo (normalmente se
crean al terminar todas las migraciones). sync_roles los reparte: Propietario y Administrador todo; Vendedor registra
(add_respaldocobro, en SELLER_WRITE); Contador y Consulta solo ven (core/tenancy/roles.py)."""
from django.db import migrations

MODULOS = ('/pos/sale/admin/', '/pos/ctas/collect/')
CODIGOS = ('view_respaldocobro', 'add_respaldocobro', 'change_respaldocobro', 'change_revision_respaldocobro')


def _permisos(Permission):
    return list(Permission.objects.filter(content_type__app_label='cobros', content_type__model='respaldocobro', codename__in=CODIGOS))


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from core.tenancy.roles import sync_roles
    config = apps.get_app_config('cobros')
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    config.models_module = None
    Module = apps.get_model('security', 'Module')
    if not Module.objects.exists():
        return   # base sin instalar: lo hará start_installation
    permisos = _permisos(apps.get_model('auth', 'Permission'))
    for modulo in Module.objects.filter(url__in=MODULOS):
        modulo.permissions.add(*permisos)
    sync_roles(apps.get_model('auth', 'Group'), Module, apps.get_model('security', 'GroupModule'))


def backwards(apps, schema_editor):
    Module = apps.get_model('security', 'Module')
    if not Module.objects.exists():
        return
    ids = [p.pk for p in _permisos(apps.get_model('auth', 'Permission'))]
    Module.permissions.through.objects.filter(module__url__in=MODULOS, permission_id__in=ids).delete()
    # Lo que haría sync_roles sin esos permisos, por ids (como comprobantes 0023). Los Permission se dejan.
    apps.get_model('auth', 'Group').permissions.through.objects.filter(permission_id__in=ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('cobros', '0002_rls_cobros'),
        ('security', '0003_orden_menu'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
