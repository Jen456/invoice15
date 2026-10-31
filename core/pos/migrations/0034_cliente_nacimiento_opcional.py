"""Fecha de nacimiento del cliente opcional: antes era obligatoria y el formulario la precargaba con la fecha de hoy, también
para empresas con RUC (hallazgo de Codex, 30/10/2026). Los valores guardados no se tocan."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0033_condicion_de_pago'),
    ]

    operations = [
        migrations.AlterField(
            model_name='client',
            name='birthdate',
            field=models.DateField(blank=True, null=True, verbose_name='Fecha de nacimiento'),
        ),
    ]
