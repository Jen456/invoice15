"""Etapa 2 · ventas y empresa (O2): retenciones recibidas de clientes (07 sobre una factura de la empresa), con sus
restricciones de unicidad condicionales (se puede registrar de nuevo tras anular) y la de idempotencia del 07 importado."""
import django.db.models.deletion
import django.db.models.manager
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('comprobantes', '0020_anulado_sri_y_cxc_nota_debito'),
        ('importacion', '0004_menu_con_guias'),
        ('pos', '0030_cxc_abonos_anulados_empresa'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='RetencionRecibida',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('emisor_identificacion', models.CharField(max_length=13, verbose_name='RUC del agente de retención')),
                ('emisor_razon_social', models.CharField(max_length=300, verbose_name='Agente de retención')),
                ('establecimiento', models.CharField(max_length=3, verbose_name='Establecimiento')),
                ('punto_emision', models.CharField(max_length=3, verbose_name='Punto de emisión')),
                ('secuencial', models.CharField(max_length=9, verbose_name='Secuencial')),
                ('numero', models.CharField(max_length=17, verbose_name='Número')),
                ('autorizacion', models.CharField(max_length=49, verbose_name='Autorización')),
                ('clave_acceso', models.CharField(blank=True, default='', max_length=49, verbose_name='Clave de acceso')),
                ('fecha_emision', models.DateField(verbose_name='Fecha de emisión')),
                ('periodo_fiscal', models.CharField(max_length=7, verbose_name='Período fiscal')),
                ('ambiente', models.PositiveSmallIntegerField(choices=[(1, 'PRUEBAS'), (2, 'PRODUCCIÓN')], verbose_name='Ambiente')),
                ('cod_doc_sustento', models.CharField(default='01', max_length=2, verbose_name='Tipo de documento sustento')),
                ('num_doc_sustento', models.CharField(max_length=15, verbose_name='Número del documento sustento')),
                ('fecha_doc_sustento', models.DateField(verbose_name='Fecha del documento sustento')),
                ('total_renta', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Retenido de renta')),
                ('total_iva', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Retenido de IVA')),
                ('total_retenido', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Total retenido')),
                ('origen', models.CharField(choices=[('manual', 'Registro manual'), ('importado', 'Importado desde XML')], default='manual', max_length=10, verbose_name='Origen')),
                ('verificacion', models.CharField(choices=[('sin_verificar', 'Registrada a mano, sin verificar en el SRI'), ('declarada_en_archivo', 'Autorización declarada en el archivo (sin verificar)'), ('verificada_sri', 'Verificada en el SRI')], default='sin_verificar', max_length=25, verbose_name='Verificación')),
                ('estado', models.CharField(choices=[('registrada', 'Registrada'), ('anulada', 'Anulada')], default='registrada', max_length=10, verbose_name='Estado')),
                ('cxc_estado', models.CharField(blank=True, choices=[('aplicada', 'Abonada a la cuenta por cobrar'), ('parcial', 'Abonada en parte: el resto excede el saldo'), ('sin_cxc', 'Venta de contado: sin cuenta por cobrar'), ('sin_saldo', 'La cuenta por cobrar ya estaba saldada'), ('revertida', 'Abono revertido al anular')], default='', max_length=10, verbose_name='Cuenta por cobrar')),
                ('advertencias', models.JSONField(blank=True, default=list)),
                ('notas', models.CharField(blank=True, default='', max_length=300, verbose_name='Notas')),
                ('registrado_en', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Registrado el')),
                ('anulado_sri_fecha', models.DateField(blank=True, null=True, verbose_name='Anulada el')),
                ('anulado_sri_motivo', models.CharField(blank=True, default='', max_length=300, verbose_name='Motivo de la anulación')),
                ('anulado_sri_registrado_en', models.DateTimeField(blank=True, null=True)),
                ('abono', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='retencion_recibida', to='pos.paymentsctacollect', verbose_name='Abono en la cuenta por cobrar')),
                ('anulado_sri_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('cliente', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='pos.client', verbose_name='Cliente (agente de retención)')),
                ('company', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='pos.company', verbose_name='Empresa')),
                ('documento_importado', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='retenciones_recibidas', to='importacion.documentoimportado', verbose_name='Documento importado')),
                ('registrado_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Registrado por')),
                ('venta', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='retenciones_recibidas', to='pos.sale', verbose_name='Factura (documento sustento)')),
            ],
            options={
                'verbose_name': 'Retención recibida',
                'verbose_name_plural': 'Retenciones recibidas',
                'ordering': ('-fecha_emision', '-id'),
                'permissions': (('view_retencionrecibida', 'Puede ver retenciones recibidas'), ('add_retencionrecibida', 'Puede registrar retenciones recibidas'), ('change_retencionrecibida', 'Puede anular el registro de una retención recibida')),
                'default_permissions': (),
            },
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_companies', django.db.models.manager.Manager()),
            ],
        ),
        migrations.CreateModel(
            name='RetencionRecibidaDetalle',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('impuesto', models.CharField(choices=[('1', 'Renta'), ('2', 'IVA')], max_length=1, verbose_name='Impuesto')),
                ('codigo', models.CharField(max_length=5, verbose_name='Código')),
                ('concepto', models.CharField(blank=True, default='', max_length=300, verbose_name='Concepto')),
                ('base_imponible', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='Base imponible')),
                ('porcentaje', models.DecimalField(decimal_places=2, max_digits=5, verbose_name='Porcentaje')),
                ('valor_retenido', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='Valor retenido')),
                ('company', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='pos.company', verbose_name='Empresa')),
                ('retencion', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='detalles', to='comprobantes.retencionrecibida')),
            ],
            options={
                'verbose_name': 'Detalle de retención recibida',
                'verbose_name_plural': 'Detalles de retención recibida',
                'ordering': ('impuesto', 'id'),
                'default_permissions': (),
            },
            managers=[
                ('objects', django.db.models.manager.Manager()),
                ('all_companies', django.db.models.manager.Manager()),
            ],
        ),
        migrations.AddIndex(
            model_name='retencionrecibida',
            index=models.Index(fields=['company', 'fecha_emision'], name='retrec_fecha'),
        ),
        migrations.AddIndex(
            model_name='retencionrecibida',
            index=models.Index(fields=['company', 'venta'], name='retrec_venta'),
        ),
        migrations.AddConstraint(
            model_name='retencionrecibida',
            constraint=models.UniqueConstraint(condition=models.Q(('estado', 'registrada')), fields=('company', 'emisor_identificacion', 'establecimiento', 'punto_emision', 'secuencial', 'venta'), name='retencion_recibida_unica'),
        ),
        migrations.AddConstraint(
            model_name='retencionrecibida',
            constraint=models.UniqueConstraint(condition=models.Q(('estado', 'registrada'), models.Q(('clave_acceso', ''), _negated=True)), fields=('company', 'clave_acceso', 'venta'), name='retencion_recibida_clave_unica'),
        ),
        migrations.AddConstraint(
            model_name='retencionrecibida',
            constraint=models.UniqueConstraint(condition=models.Q(('estado', 'registrada'), ('documento_importado__isnull', False)), fields=('company', 'documento_importado', 'venta'), name='retencion_recibida_documento_unica'),
        ),
        migrations.AddConstraint(
            model_name='retencionrecibida',
            constraint=models.CheckConstraint(condition=models.Q(('total_retenido__gte', 0), ('total_renta__gte', 0), ('total_iva__gte', 0)), name='retencion_recibida_totales_no_negativos'),
        ),
        migrations.AddConstraint(
            model_name='retencionrecibidadetalle',
            constraint=models.CheckConstraint(condition=models.Q(('base_imponible__gt', 0), ('porcentaje__gte', 0), ('porcentaje__lte', 100), ('valor_retenido__gte', 0)), name='retencion_recibida_detalle_valido'),
        ),
    ]
