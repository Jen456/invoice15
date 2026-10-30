"""Vigencias en el catálogo de retenciones (D0, Fase A): solo esquema, sin tocar datos.

Una fila por vigencia de cada código: vigente_desde (NULL = inicio no documentado), vigente_hasta (NULL = abierta) y la
ayuda que ve el emisor. La unicidad (impuesto, código) pasa a ser por vigencia, con una sola fila abierta y una sola sin
inicio por código. RetencionDetalle anota la fila usada (codigo_catalogo), vacía en los detalles anteriores.
Reversible: revertida la 0015 queda una fila por código y aquí vuelve la unicidad de 0004.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('comprobantes', '0013_modulo_guias'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='codigoretencion',
            name='codigo_retencion_unico',
        ),
        migrations.AddField(
            model_name='codigoretencion',
            name='ayuda',
            field=models.CharField(blank=True, help_text='Texto que ve el emisor al elegir el código.', max_length=500, verbose_name='Ayuda'),
        ),
        migrations.AddField(
            model_name='codigoretencion',
            name='vigente_desde',
            field=models.DateField(blank=True, help_text='Vacío: inicio no documentado en esta revisión del catálogo (no se inventa una fecha).', null=True, verbose_name='Vigente desde'),
        ),
        migrations.AddField(
            model_name='codigoretencion',
            name='vigente_hasta',
            field=models.DateField(blank=True, help_text='Vacío: vigencia abierta.', null=True, verbose_name='Vigente hasta'),
        ),
        migrations.AddField(
            model_name='retenciondetalle',
            name='codigo_catalogo',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='comprobantes.codigoretencion', verbose_name='Fila del catálogo'),
        ),
        migrations.AddConstraint(
            model_name='codigoretencion',
            constraint=models.UniqueConstraint(fields=('impuesto', 'codigo', 'vigente_desde'), name='codigo_retencion_vigencia_unica'),
        ),
        migrations.AddConstraint(
            model_name='codigoretencion',
            constraint=models.UniqueConstraint(condition=models.Q(('vigente_hasta__isnull', True)), fields=('impuesto', 'codigo'), name='codigo_retencion_una_abierta'),
        ),
        migrations.AddConstraint(
            model_name='codigoretencion',
            constraint=models.UniqueConstraint(condition=models.Q(('vigente_desde__isnull', True)), fields=('impuesto', 'codigo'), name='codigo_retencion_un_inicio_nulo'),
        ),
        migrations.AddConstraint(
            model_name='codigoretencion',
            constraint=models.CheckConstraint(condition=models.Q(('vigente_desde__isnull', True), ('vigente_hasta__isnull', True), ('vigente_hasta__gte', models.F('vigente_desde')), _connector='OR'), name='codigo_retencion_hasta_no_antes_de_desde'),
        ),
    ]
