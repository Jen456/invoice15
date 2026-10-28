"""Permiso «Completar datos de una compra» (change_purchase) en el módulo Compras, para instalaciones existentes.

Patrón de comprobantes/0013_modulo_guias.py: los permisos del modelo se crean aquí mismo (normalmente se crean al terminar
todas las migraciones), se añade change_purchase al módulo «/pos/purchase/» si existe y se vuelven a sincronizar los roles:
sync_roles lo reparte solo a los roles con escritura (Propietario y Administrador), no a Contador ni a Consulta.
Las instalaciones nuevas lo reciben de start_installation (asigna al módulo todos los permisos del modelo purchase).
"""
from django.db import migrations

URL = '/pos/purchase/'


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from core.tenancy.roles import sync_roles
    config = apps.get_app_config('pos')
    anterior = getattr(config, 'models_module', None)
    config.models_module = anterior or True   # create_permissions no hace nada si la app «no tiene modelos»
    try:
        create_permissions(config, apps=apps, verbosity=0)
    finally:
        config.models_module = anterior       # con el registro real (pruebas) no se puede dejar en None
    Module = apps.get_model('security', 'Module')
    modulo = Module.objects.filter(url=URL).first()
    if modulo is None:
        return
    Permission = apps.get_model('auth', 'Permission')
    permiso = Permission.objects.filter(content_type__app_label='pos', content_type__model='purchase',
                                        codename='change_purchase').first()
    if permiso is not None:
        modulo.permissions.add(permiso)
    sync_roles(apps.get_model('auth', 'Group'), Module, apps.get_model('security', 'GroupModule'))


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0023_pagos_y_gastos'),
        ('security', '0003_orden_menu'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
