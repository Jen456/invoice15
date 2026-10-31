"""Módulo «Locales y puntos de emisión» (menú Configuración) para instalaciones existentes.

Las instalaciones nuevas lo reciben de start_installation (organizar_menu). El módulo lo crea organizar_menu desde
MODULOS_NUEVOS y ESTRUCTURA (core/security/menu.py), nunca a mano; sus permisos son los de PuntoAutorizado y se crean aquí
mismo (normalmente se crean al terminar todas las migraciones). sync_roles lo reparte: Propietario y Administrador lo
tienen; Consulta, Contador y Vendedor no (core/tenancy/roles.py).
"""
from django.db import migrations

URL = '/configuracion/puntos/'


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from core.security.menu import organizar_menu
    from core.tenancy.roles import sync_roles
    config = apps.get_app_config('configuracion')
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    config.models_module = None
    Module = apps.get_model('security', 'Module')
    if not Module.objects.exists():
        return   # base sin instalar: lo hará start_installation
    Permission = apps.get_model('auth', 'Permission')
    organizar_menu(apps.get_model('security', 'ModuleType'), Module, Permission)
    sync_roles(apps.get_model('auth', 'Group'), Module, apps.get_model('security', 'GroupModule'))


def backwards(apps, schema_editor):
    Module = apps.get_model('security', 'Module')
    if not Module.objects.exists():
        return
    Module.objects.filter(url=URL).delete()   # sus GroupModule caen en cascada
    Permission = apps.get_model('auth', 'Permission')
    # Lo que haría sync_roles sin el módulo, por ids en la tabla intermedia (como comprobantes 0023). Los Permission se dejan.
    quitar = list(Permission.objects.filter(content_type__app_label='configuracion').values_list('pk', flat=True))
    apps.get_model('auth', 'Group').permissions.through.objects.filter(permission_id__in=quitar).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('configuracion', '0002_rls_puntos'),
        ('security', '0003_orden_menu'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
