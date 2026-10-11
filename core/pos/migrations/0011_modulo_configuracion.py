"""Módulo «Configuración de facturación» para instalaciones existentes (las nuevas lo crea start_installation)."""
from django.db import migrations


def forwards(apps, schema_editor):
    from core.tenancy.roles import sync_roles
    Module = apps.get_model('security', 'Module')
    if Module.objects.exists() and not Module.objects.filter(url='/configuracion/facturacion/').exists():
        Module.objects.create(url='/configuracion/facturacion/', name='Configuración de facturación', icon='fas fa-list-check',
                              description='Asistente para configurar establecimiento, punto de emisión, numeración, firma y ambiente')
        sync_roles(apps.get_model('auth', 'Group'), Module, apps.get_model('security', 'GroupModule'))


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0010_rls_configuracion'),
        ('security', '0002_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('suscripciones', '0005_mejora_por_dias'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
