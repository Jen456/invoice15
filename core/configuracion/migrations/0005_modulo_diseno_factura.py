"""Módulo «Diseño de factura» (menú Configuración, después de «Facturación y numeración») para instalaciones existentes.

Las instalaciones nuevas lo reciben de start_installation (organizar_menu). Mismo patrón que configuracion 0003 y
contabilidad 0003: los permisos de DisenoFactura se crean aquí mismo, organizar_menu crea el módulo desde MODULOS_NUEVOS y
ESTRUCTURA (core/security/menu.py) solo si la app ya está migrada, y sync_roles lo reparte: Propietario y Administrador lo
tienen; Consulta, Contador y Vendedor no (core/tenancy/roles.py). Aunque el rol lo tenga, el menú lo oculta y sus URL no
abren fuera del piloto (FPA_DISENO_FACTURA_PILOTO). La vuelta quita el módulo y SOLO los permisos de DisenoFactura de los
grupos (los de los puntos de emisión siguen como estaban); las filas de Permission se dejan, como hace Django.
"""
from django.db import migrations

URL = '/configuracion/diseno-factura/'


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions

    from core.security.menu import organizar_menu
    from core.tenancy.roles import sync_roles
    config = apps.get_app_config('configuracion')
    anterior = getattr(config, 'models_module', None)
    config.models_module = True
    try:
        create_permissions(config, apps=apps, verbosity=0)
    finally:
        config.models_module = anterior
    Module = apps.get_model('security', 'Module')
    if not Module.objects.exists():
        return   # base sin instalar: lo hará start_installation
    organizar_menu(apps.get_model('security', 'ModuleType'), Module, apps.get_model('auth', 'Permission'), apps=apps)
    sync_roles(apps.get_model('auth', 'Group'), Module, apps.get_model('security', 'GroupModule'))


def backwards(apps, schema_editor):
    Module = apps.get_model('security', 'Module')
    Module.objects.filter(url=URL).delete()   # sus GroupModule caen en cascada
    Permission = apps.get_model('auth', 'Permission')
    quitar = list(Permission.objects.filter(content_type__app_label='configuracion', content_type__model='disenofactura')
                  .values_list('pk', flat=True))
    apps.get_model('auth', 'Group').permissions.through.objects.filter(permission_id__in=quitar).delete()
    # Orden del menú sin el módulo (como antes de 0005): «Locales y puntos» vuelve a 3 y los siguientes, uno menos.
    for url, orden in (('/configuracion/puntos/', 3), ('/importacion/reglas/', 4), ('/pos/receipt/', 5)):
        Module.objects.filter(url=url).update(orden=orden)


class Migration(migrations.Migration):

    dependencies = [
        ('configuracion', '0004_diseno_factura'),
        ('security', '0003_orden_menu'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
