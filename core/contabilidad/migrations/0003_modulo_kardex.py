"""Módulos «Kardex por producto» e «Inventario valorizado» (/contabilidad/…) en el grupo «Contabilidad» del menú, con sus
permisos, para instalaciones existentes (las nuevas lo crea start_installation). Mismo patrón que tributario 0003:
organizar_menu solo crea el módulo si la app ya está migrada y sync_roles reparte (roles.py): Propietario, Administrador y
Contador ven y registran movimientos manuales; Consulta solo ve; Vendedor y Cliente no. La vuelta quita los dos módulos, los
permisos de la app en los grupos y el grupo «Contabilidad» si queda vacío."""
from django.db import migrations

URLS = ('/contabilidad/kardex/', '/contabilidad/inventario/')


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions

    from core.security.menu import organizar_menu
    from core.tenancy.roles import sync_roles
    config = apps.get_app_config('contabilidad')
    anterior = getattr(config, 'models_module', None)
    config.models_module = True
    try:
        create_permissions(config, apps=apps, verbosity=0)
    finally:
        config.models_module = anterior
    Module = apps.get_model('security', 'Module')
    if not Module.objects.exists():
        return   # base nueva: lo hará start_installation
    organizar_menu(apps.get_model('security', 'ModuleType'), Module, apps.get_model('auth', 'Permission'), apps=apps)
    sync_roles(apps.get_model('auth', 'Group'), Module, apps.get_model('security', 'GroupModule'))


def backwards(apps, schema_editor):
    Module = apps.get_model('security', 'Module')
    Module.objects.filter(url__in=URLS).delete()   # sus GroupModule caen en cascada
    Group = apps.get_model('auth', 'Group')
    Group.permissions.through.objects.filter(permission__content_type__app_label='contabilidad').delete()
    for tipo in apps.get_model('security', 'ModuleType').objects.filter(name='Contabilidad'):
        if not Module.objects.filter(module_type=tipo).exists():
            tipo.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('contabilidad', '0002_seguridad_por_filas'),
        ('security', '0003_orden_menu'),
        ('importacion', '0004_menu_con_guias'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
