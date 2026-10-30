"""Vuelve a ordenar el menú ahora que existe «Guías de remisión» (core/security/menu.py). Mismas reglas que 0003."""
from django.db import migrations


def forwards(apps, schema_editor):
    from core.security.menu import organizar_menu
    from core.tenancy.roles import sync_roles
    Module = apps.get_model("security", "Module")
    if not Module.objects.exists():
        return
    organizar_menu(apps.get_model("security", "ModuleType"), Module, apps.get_model("auth", "Permission"), apps=apps)
    sync_roles(apps.get_model("auth", "Group"), Module, apps.get_model("security", "GroupModule"))


class Migration(migrations.Migration):

    dependencies = [
        ("importacion", "0003_menu_y_modulos"),
        ("comprobantes", "0013_modulo_guias"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
