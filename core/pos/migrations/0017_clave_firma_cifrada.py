"""La clave de la firma electrónica (.p12) se guarda cifrada (core/tenancy/cifrado.py, llave FPA_CLAVES_CIFRADO).
Cifra las claves existentes; al revertir, las vuelve a dejar en claro (para volver al código anterior)."""
from django.db import migrations

import core.tenancy.cifrado
from core.tenancy.cifrado import SecretoIlegible


def cifrar(apps, schema_editor):
    Company = apps.get_model('pos', 'Company')
    for empresa in Company.objects.exclude(electronic_signature_key='').only('pk', 'electronic_signature_key'):
        empresa.save(update_fields=['electronic_signature_key'])   # se lee en claro y se guarda cifrada


def descifrar(apps, schema_editor):
    Company = apps.get_model('pos', 'Company')
    with schema_editor.connection.cursor() as cursor:
        for empresa in Company.objects.exclude(electronic_signature_key='').only('pk', 'electronic_signature_key'):
            if isinstance(empresa.electronic_signature_key, SecretoIlegible):
                raise RuntimeError(f'La clave de la empresa {empresa.pk} no se puede descifrar con FPA_CLAVES_CIFRADO.')
            cursor.execute(f'UPDATE {Company._meta.db_table} SET electronic_signature_key = %s WHERE id = %s',
                           [empresa.electronic_signature_key, empresa.pk])


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0016_tarifa_iva_existentes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='company',
            name='electronic_signature_key',
            field=core.tenancy.cifrado.ClaveCifrada(verbose_name='Clave de firma electrónica'),
        ),
        migrations.RunPython(cifrar, descifrar),
    ]
