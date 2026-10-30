"""Proveedor: identificación de hasta 20 caracteres y datos del ATS (tipo de identificación, tipo de sujeto, parte
relacionada), vacíos en los existentes = sin indicar (espec-etapa2-compras §1.2).

Reversa: falla si algún proveedor ya tiene una identificación de más de 13 caracteres.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0019_orden_de_las_lineas'),
    ]

    operations = [
        migrations.AddField(
            model_name='provider',
            name='parte_relacionada',
            field=models.BooleanField(blank=True, default=None, null=True, verbose_name='Parte relacionada'),
        ),
        migrations.AddField(
            model_name='provider',
            name='tipo_identificacion',
            field=models.CharField(blank=True, choices=[('04', 'RUC'), ('05', 'Cédula'), ('06', 'Pasaporte'), ('08', 'Identificación del exterior')], default='', max_length=2, verbose_name='Tipo de identificación'),
        ),
        migrations.AddField(
            model_name='provider',
            name='tipo_sujeto',
            field=models.CharField(blank=True, choices=[('01', 'Persona natural'), ('02', 'Sociedad')], default='', max_length=2, verbose_name='Tipo de sujeto'),
        ),
        migrations.AlterField(
            model_name='provider',
            name='ruc',
            field=models.CharField(max_length=20, verbose_name='Identificación'),
        ),
    ]
