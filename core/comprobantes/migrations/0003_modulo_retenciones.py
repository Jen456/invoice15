"""Módulo «Retenciones» (menú Facturación) con sus permisos, para instalaciones existentes.

Las instalaciones nuevas lo crea start_installation. Los permisos de los modelos nuevos se crean aquí mismo
(normalmente se crean al terminar todas las migraciones).
"""
from django.db import migrations

URL = '/comprobantes/retenciones/'


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from core.tenancy.roles import sync_roles
    config = apps.get_app_config('comprobantes')
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    config.models_module = None
    Module = apps.get_model('security', 'Module')
    if not Module.objects.exists() or Module.objects.filter(url=URL).exists():
        return
    tipo = apps.get_model('security', 'ModuleType').objects.filter(name='Facturación').first()
    modulo = Module.objects.create(url=URL, name='Retenciones', icon='fas fa-file-invoice-dollar', module_type=tipo,
                                   description='Comprobantes de retención electrónicos emitidos desde Compras')
    Permission = apps.get_model('auth', 'Permission')
    modulo.permissions.set(Permission.objects.filter(content_type__app_label='comprobantes', content_type__model='retencion'))
    sync_roles(apps.get_model('auth', 'Group'), Module, apps.get_model('security', 'GroupModule'))


class Migration(migrations.Migration):

    dependencies = [
        ('comprobantes', '0002_seguridad_por_filas'),
        ('security', '0002_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('pos', '0013_tipos_comprobante_adicionales'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
