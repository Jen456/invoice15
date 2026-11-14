"""Permisos del plan de cuentas (`view_cuenta`, `add_cuenta`, `change_cuenta`) para instalaciones existentes (las nuevas los
reciben de start_installation). El plan de cuentas todavía no tiene pantalla ni módulo propios y un rol solo recibe
permisos a través de un módulo, así que cuelgan del módulo «Kardex por producto» (su tupla en core/security/menu.py).
Mismo patrón que contabilidad 0003: se crean los permisos de la app, organizar_menu los pone en el módulo y sync_roles
reparte (core/tenancy/roles.py): Propietario y Administrador ven, crean y editan; Contador también (ACCOUNTANT_WRITE);
Consulta solo ve; Vendedor y Cliente, nada. No crea módulos ni cambia el menú.

La vuelta quita esos tres permisos del módulo y de los roles (por ids en las tablas intermedias, como cobros 0003); el
módulo del kardex queda con los suyos. Los Permission se dejan."""
from django.db import migrations

URL = '/contabilidad/kardex/'
CODIGOS = ('view_cuenta', 'add_cuenta', 'change_cuenta')


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
    ids = list(apps.get_model('auth', 'Permission').objects.filter(
        content_type__app_label='contabilidad', content_type__model='cuenta', codename__in=CODIGOS).values_list('pk', flat=True))
    Module = apps.get_model('security', 'Module')
    Module.permissions.through.objects.filter(module__url=URL, permission_id__in=ids).delete()
    # Lo que haría sync_roles sin esos permisos en el módulo.
    apps.get_model('auth', 'Group').permissions.through.objects.filter(permission_id__in=ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('contabilidad', '0005_seguridad_por_filas_cuentas'),
        ('security', '0003_orden_menu'),
        ('importacion', '0004_menu_con_guias'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
