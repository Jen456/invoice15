"""Módulos de la importación con sus permisos y la nueva organización del menú (grupos, nombres y orden), para
instalaciones existentes. Las instalaciones nuevas lo hacen en start_installation con la misma función
(core/security/menu.py). Las URL de los módulos existentes no cambian."""
from django.db import migrations


def forwards(apps, schema_editor):
    from django.contrib.auth.management import create_permissions
    from core.security.menu import organizar_menu
    from core.tenancy.roles import sync_roles
    config = apps.get_app_config("importacion")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    config.models_module = None
    Module = apps.get_model("security", "Module")
    if not Module.objects.exists():
        return   # base vacía: start_installation lo hará
    organizar_menu(apps.get_model("security", "ModuleType"), Module, apps.get_model("auth", "Permission"))
    sync_roles(apps.get_model("auth", "Group"), Module, apps.get_model("security", "GroupModule"))


class Migration(migrations.Migration):

    dependencies = [
        ("importacion", "0002_seguridad_por_filas"),
        ("security", "0003_orden_menu"),
        ("comprobantes", "0010_modulo_notas_debito"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
