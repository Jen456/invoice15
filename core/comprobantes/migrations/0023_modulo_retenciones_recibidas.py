"""Módulo «Retenciones recibidas» (menú Administrativo) y permisos «Anulado en el SRI» de los cuatro comprobantes
adicionales, para instalaciones existentes.

Las instalaciones nuevas los reciben de start_installation (todos los permisos de cada modelo y organizar_menu). El
módulo lo crea organizar_menu desde MODULOS_NUEVOS y ESTRUCTURA (core/security/menu.py), nunca a mano. Los permisos de
los modelos nuevos se crean aquí mismo (normalmente se crean al terminar todas las migraciones).
"""
from django.db import migrations

URL = '/comprobantes/retenciones-recibidas/'
ANULADO = (('/comprobantes/retenciones/', 'retencion'), ('/comprobantes/liquidaciones/', 'liquidacioncompra'),
           ('/comprobantes/notas-debito/', 'notadebito'), ('/comprobantes/guias/', 'guiaremision'))


def _permiso(Permission, modelo):
    return Permission.objects.filter(content_type__app_label='comprobantes', content_type__model=modelo,
                                     codename=f'change_anulado_sri_{modelo}').first()


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from core.security.menu import organizar_menu
    from core.tenancy.roles import sync_roles
    config = apps.get_app_config('comprobantes')
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    config.models_module = None
    Module = apps.get_model('security', 'Module')
    if not Module.objects.exists():
        return   # base sin instalar: lo hará start_installation
    Permission = apps.get_model('auth', 'Permission')
    for url, modelo in ANULADO:
        permiso = _permiso(Permission, modelo)
        for modulo in Module.objects.filter(url=url):
            modulo.permissions.add(permiso)
    organizar_menu(apps.get_model('security', 'ModuleType'), Module, Permission)
    sync_roles(apps.get_model('auth', 'Group'), Module, apps.get_model('security', 'GroupModule'))


def backwards(apps, schema_editor):
    from core.tenancy.roles import sync_roles
    Module = apps.get_model('security', 'Module')
    if not Module.objects.exists():
        return
    Module.objects.filter(url=URL).delete()   # sus GroupModule caen en cascada
    Permission = apps.get_model('auth', 'Permission')
    for url, modelo in ANULADO:
        permiso = _permiso(Permission, modelo)
        if permiso is not None:
            for modulo in Module.objects.filter(url=url):
                modulo.permissions.remove(permiso)
    sync_roles(apps.get_model('auth', 'Group'), Module, apps.get_model('security', 'GroupModule'))


class Migration(migrations.Migration):

    dependencies = [
        ('comprobantes', '0022_seguridad_por_filas_retencion_recibida'),
        ('security', '0003_orden_menu'),
        ('importacion', '0004_menu_con_guias'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('pos', '0031_permisos_anulado_sri'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
