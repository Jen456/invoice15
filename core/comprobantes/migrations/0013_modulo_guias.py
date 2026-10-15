"""Módulo «Guías de remisión» (menú Comprobantes Electrónicos) con sus permisos, para instalaciones existentes.

Las instalaciones nuevas lo crea start_installation. Los permisos de los modelos nuevos se crean aquí mismo
(normalmente se crean al terminar todas las migraciones).
"""
from django.db import migrations

URL = '/comprobantes/guias/'


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
    tipo = apps.get_model('security', 'ModuleType').objects.filter(name__in=('Comprobantes Electrónicos', 'Facturación')).first()
    modulo = Module.objects.create(url=URL, name='Guías de remisión', icon='fas fa-truck', module_type=tipo,
                                   description='Guías de remisión electrónicas del traslado de lo vendido, emitidas desde las facturas')
    Permission = apps.get_model('auth', 'Permission')
    modulo.permissions.set(Permission.objects.filter(content_type__app_label='comprobantes', content_type__model='guiaremision'))
    sync_roles(apps.get_model('auth', 'Group'), Module, apps.get_model('security', 'GroupModule'))


class Migration(migrations.Migration):

    dependencies = [
        ('comprobantes', '0012_seguridad_por_filas_guia'),
        ('security', '0002_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('pos', '0013_tipos_comprobante_adicionales'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
