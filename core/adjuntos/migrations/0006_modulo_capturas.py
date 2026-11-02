"""Módulo «Recibos por completar» (/adjuntos/capturas/) en el grupo «Compras y gastos» del menú, con sus permisos, para
instalaciones existentes (las nuevas lo crea start_installation). Mismo patrón que adjuntos 0003: se crean los permisos de
la app, organizar_menu solo crea el módulo si la app ya está migrada y sync_roles reparte (roles.py): Propietario y
Administrador todo; Contador y Vendedor ver, guardar y completar (el Vendedor solo los recibos que guardó); Consulta ver.
"""
from django.db import migrations

URL = '/adjuntos/capturas/'
CODIGOS = ('view_captura', 'add_captura', 'change_captura')


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions

    from core.security.menu import organizar_menu
    from core.tenancy.roles import sync_roles
    config = apps.get_app_config('adjuntos')
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
    apps.get_model('security', 'Module').objects.filter(url=URL).delete()   # sus GroupModule caen en cascada
    # Lo que haría sync_roles sin el módulo: ningún grupo conserva los permisos de capturas (por ids en la tabla intermedia,
    # como adjuntos 0003). Los Permission se dejan.
    Group = apps.get_model('auth', 'Group')
    Group.permissions.through.objects.filter(permission__content_type__app_label='adjuntos',
                                             permission__codename__in=CODIGOS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('adjuntos', '0005_rls_capturas'),
        ('security', '0003_orden_menu'),
        ('importacion', '0004_menu_con_guias'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
