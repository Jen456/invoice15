"""Equivalencias «código del proveedor → producto» que el usuario decide recordar (espec-etapa2-compras §1.7, DC8)."""

import django.db.models.deletion
import django.db.models.manager
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('importacion', '0004_menu_con_guias'),
        ('pos', '0022_detalle_compra_tarifa'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EquivalenciaProducto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codigo_proveedor', models.CharField(max_length=25, verbose_name='Código del proveedor')),
                ('creado', models.DateTimeField(default=django.utils.timezone.now)),
                ('actualizado', models.DateTimeField(auto_now=True)),
                ('company', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='pos.company', verbose_name='Empresa')),
                ('creado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('producto', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='pos.product')),
                ('proveedor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='pos.provider')),
            ],
            options={
                'verbose_name': 'Equivalencia de producto del proveedor',
                'verbose_name_plural': 'Equivalencias de productos de proveedores',
                'ordering': ('proveedor', 'codigo_proveedor'),
                'default_permissions': (),
                'constraints': [models.UniqueConstraint(fields=('company', 'proveedor', 'codigo_proveedor'), name='equivalencia_producto_unica')],
            },
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_companies', django.db.models.manager.Manager()),
            ],
        ),
    ]
