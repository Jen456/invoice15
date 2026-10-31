"""Módulo «Comprobantes de pago» (/adjuntos/) en el grupo «Administrativo» del menú, con sus permisos, para instalaciones
existentes. Mismo patrón que proformas 0003: las instalaciones nuevas lo crea start_installation; aquí se crean los
permisos de la app (normalmente se crean al terminar todas las migraciones) y organizar_menu solo crea el módulo si la
app ya está migrada (modelos históricos). No depende de las migraciones de módulo de las otras apps (proformas 0003,
comprobantes 0023): organizar_menu es idempotente y cada una crea solo su módulo, así que el orden entre ellas no importa
y deshacer una no arrastra a esta.
"""
from django.db import migrations

URL = '/adjuntos/'


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
    # Lo que haría sync_roles sin el módulo: ningún grupo conserva permisos de adjuntos. Por ids en la tabla intermedia,
    # como proformas 0003 (los modelos históricos de auth.Group quedan desfasados en una vuelta). Los Permission se dejan.
    Group = apps.get_model('auth', 'Group')
    Group.permissions.through.objects.filter(permission__content_type__app_label='adjuntos').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('adjuntos', '0002_seguridad_por_filas'),
        ('security', '0003_orden_menu'),
        ('importacion', '0004_menu_con_guias'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
