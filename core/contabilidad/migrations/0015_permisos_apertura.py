"""Permisos del libro y de la apertura que el bloque 2 reparte, para instalaciones existentes (las nuevas los reciben de
start_installation): `view_asiento` y `view_apertura` (ver), `add_apertura` (configurar, crear, importar, mapear,
auxiliares, validar, enviar, descartar, destinar históricos), `change_confirmacion_apertura` (devolver, confirmar,
ajustar, sustituir, reversar, declarar `conciliada`, activar la guarda) y `add_aplicacionauxiliar` /
`change_aplicacionauxiliar` (cobros, pagos y descargos sobre saldos iniciales).

Como el plan de cuentas (contabilidad 0006), no hay pantalla ni módulo nuevos: cuelgan del módulo «Kardex por producto»
(su tupla en core/security/menu.py) y sync_roles reparte (core/tenancy/roles.py): Propietario y Administrador, todos;
Contador también (ACCOUNTANT_WRITE: los cuatro de escritura, ninguno de compras ni de importación); Consulta solo los
de ver; Vendedor y Cliente, nada. Los permisos declarados para bloques posteriores (`add_asiento`, `change_asiento`,
`change_reverso_asiento`, los del período y del ejercicio) se crean pero no cuelgan de ningún módulo: nadie los recibe.

La vuelta quita solo estos seis del módulo y de los roles (por ids en las tablas intermedias, como 0006 y cobros 0003);
el módulo del kardex queda con los suyos y con los del plan de cuentas. Los Permission se dejan."""
from django.db import migrations

URL = '/contabilidad/kardex/'
# (modelo, codename)
PERMISOS = (('asiento', 'view_asiento'), ('apertura', 'view_apertura'), ('apertura', 'add_apertura'),
            ('apertura', 'change_confirmacion_apertura'), ('aplicacionauxiliar', 'add_aplicacionauxiliar'),
            ('aplicacionauxiliar', 'change_aplicacionauxiliar'))
CODIGOS = tuple(codigo for _, codigo in PERMISOS)


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions

    from core.security.menu import organizar_menu
    from core.tenancy.roles import sync_roles
    config = apps.get_app_config('contabilidad')
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
    Permission = apps.get_model('auth', 'Permission')
    ids = [p.pk for p in Permission.objects.filter(content_type__app_label='contabilidad', codename__in=CODIGOS)
           .select_related('content_type') if (p.content_type.model, p.codename) in PERMISOS]
    Module = apps.get_model('security', 'Module')
    Module.permissions.through.objects.filter(module__url=URL, permission_id__in=ids).delete()
    # Lo que haría sync_roles sin esos permisos en el módulo.
    apps.get_model('auth', 'Group').permissions.through.objects.filter(permission_id__in=ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('contabilidad', '0014_libro_inmutable'),
        ('security', '0003_orden_menu'),
        ('importacion', '0004_menu_con_guias'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
