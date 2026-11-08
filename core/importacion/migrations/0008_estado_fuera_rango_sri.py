from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('importacion', '0007_lotes_de_claves')]

    operations = [
        migrations.AlterField(
            model_name='documentoimportado',
            name='estado_verificacion',
            field=models.CharField(
                choices=[
                    ('sin_autorizacion', 'El archivo no trae autorización'),
                    ('declarada_en_archivo', 'Autorización declarada en el archivo (sin verificar)'),
                    ('verificada_sri', 'Verificada en el SRI'),
                    ('discrepancia_sri', 'Difiere de lo autorizado en el SRI'),
                    ('no_autorizada_sri', 'El SRI no la autoriza'),
                    ('no_encontrada_sri', 'El SRI no tiene esa clave'),
                    ('sri_no_disponible', 'No se pudo confirmar con el SRI'),
                    ('fuera_rango_sri', 'Fecha fuera del rango del SRI'),
                    ('en_proceso_sri', 'El SRI todavía la está procesando'),
                ],
                default='sin_autorizacion',
                max_length=25,
                verbose_name='Verificación',
            ),
        ),
    ]
