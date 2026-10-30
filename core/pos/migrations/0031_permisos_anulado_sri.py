"""Permisos «Anulado en el SRI» de la factura y de la nota de crédito en sus módulos, para instalaciones existentes.

Las instalaciones nuevas los reciben de start_installation (todos los permisos de Venta y de Nota de crédito). Empiezan
con change_: sync_roles no los da a Contador, Consulta ni Vendedor.
"""
from django.db import migrations

PERMISOS = (('/pos/sale/admin/', 'sale', 'change_anulado_sri_sale'),
            ('/pos/credit/note/admin/', 'creditnote', 'change_anulado_sri_creditnote'))


def _permiso(Permission, modelo, codigo):
    return Permission.objects.filter(content_type__app_label='pos', content_type__model=modelo, codename=codigo).first()


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from core.tenancy.roles import sync_roles
    config = apps.get_app_config('pos')
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    config.models_module = None
    Module = apps.get_model('security', 'Module')
    if not Module.objects.exists():
        return   # base sin instalar: lo hará start_installation
    Permission = apps.get_model('auth', 'Permission')
    for url, modelo, codigo in PERMISOS:
        permiso = _permiso(Permission, modelo, codigo)
        for modulo in Module.objects.filter(url=url):
            modulo.permissions.add(permiso)
    sync_roles(apps.get_model('auth', 'Group'), Module, apps.get_model('security', 'GroupModule'))


def backwards(apps, schema_editor):
    Module = apps.get_model('security', 'Module')
    if not Module.objects.exists():
        return
    Permission = apps.get_model('auth', 'Permission')
    quitar = []
    for url, modelo, codigo in PERMISOS:
        permiso = _permiso(Permission, modelo, codigo)
        if permiso is not None:
            quitar.append(permiso.pk)
            Module.permissions.through.objects.filter(module__url=url, permission_id=permiso.pk).delete()
    # Lo que haría sync_roles sin esos permisos en los módulos, como en comprobantes 0023. Todo va por ids en las tablas
    # intermedias: al deshacer junto con otras migraciones (migrate pos 0019), los modelos históricos de Permission quedan
    # desfasados respecto de Module y Group (ValueError «Must be "Permission" instance»). Los Permission se dejan.
    apps.get_model('auth', 'Group').permissions.through.objects.filter(permission_id__in=quitar).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0030_cxc_abonos_anulados_empresa'),
        ('security', '0003_orden_menu'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
