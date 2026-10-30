"""Módulo «Proformas» en el grupo «Cotizaciones» del menú, con sus permisos, para instalaciones existentes.

Las instalaciones nuevas lo crea start_installation (llama a organizar_menu antes de sync_roles). Los permisos de la app
se crean aquí mismo (normalmente se crean al terminar todas las migraciones). organizar_menu es idempotente y solo crea
el módulo si la app ya tiene sus permisos, así que esta migración no depende de otras migraciones de menú: la que corra
última deja el menú completo. forwards y backwards no usan schema_editor (las pruebas las llaman con None).
"""
from django.db import migrations

URL = '/proformas/'
GRUPO = 'Cotizaciones'


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions

    from core.security.menu import organizar_menu
    from core.tenancy.roles import sync_roles
    config = apps.get_app_config('proformas')
    anterior = getattr(config, 'models_module', None)   # el AppConfigStub de un estado histórico no lo tiene
    config.models_module = True   # create_permissions omite las apps sin módulo de modelos
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
    apps.get_model('security', 'ModuleType').objects.filter(name=GRUPO, module__isnull=True).delete()
    # Lo que haría sync_roles sin el módulo: ningún grupo conserva permisos de proformas. No se llama a sync_roles porque
    # en un `migrate proformas zero` los modelos históricos de auth.Group quedan desfasados respecto de GroupModule
    # (ValueError «Must be "Group" instance»); estas consultas no mezclan instancias. Los Permission se dejan.
    Group = apps.get_model('auth', 'Group')
    Group.permissions.through.objects.filter(permission__content_type__app_label='proformas').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('proformas', '0002_seguridad_por_filas'),
        ('security', '0003_orden_menu'),
        ('importacion', '0004_menu_con_guias'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
