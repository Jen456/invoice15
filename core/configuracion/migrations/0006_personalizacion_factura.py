from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('configuracion', '0005_modulo_diseno_factura')]

    operations = [
        migrations.AddField(
            model_name='disenofactura',
            name='fuente',
            field=models.CharField(choices=[
                ('original', 'Original del sistema'),
                ('liberation-serif', 'Liberation Serif'),
                ('dejavu-sans', 'DejaVu Sans'),
                ('dejavu-serif', 'DejaVu Serif'),
            ], default='original', max_length=20, verbose_name='Tipografía'),
        ),
        migrations.AddField(
            model_name='disenofactura',
            name='encabezado',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='Encabezado comercial'),
        ),
        migrations.AddField(
            model_name='disenofactura',
            name='pie_comercial',
            field=models.CharField(blank=True, default='', max_length=180, verbose_name='Pie comercial'),
        ),
    ]
