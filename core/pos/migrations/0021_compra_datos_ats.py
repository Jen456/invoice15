"""Compra: datos del comprobante (ATS), importes por base y marca de datos incompletos (espec-etapa2-compras §1.3).

Las compras existentes quedan con version_datos=1, datos_incompletos=True, fuera_plazo_ats=False y los importes NULL
(desconocidos) por los valores por defecto de AddField, sin RunPython (DC1, DC2). Se quita la unicidad por número y se
añade la unicidad condicional del comprobante por proveedor (las existentes tienen secuencial vacío: no entran).

Reversa: volver a añadir purchase_number_por_empresa falla si ya hay compras nuevas con el mismo número (p. ej. vacío).
"""

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0020_proveedor_datos_ats'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='purchase',
            options={'default_permissions': (), 'permissions': (('view_purchase', 'Can view Compra'), ('add_purchase', 'Can add Compra'), ('change_purchase', 'Can change Compra'), ('delete_purchase', 'Can delete Compra')), 'verbose_name': 'Compra', 'verbose_name_plural': 'Compras'},
        ),
        migrations.RemoveConstraint(
            model_name='purchase',
            name='purchase_number_por_empresa',
        ),
        migrations.AddField(
            model_name='purchase',
            name='aut_doc_modificado',
            field=models.CharField(blank=True, default='', max_length=49, verbose_name='Autorización del documento modificado'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='autorizacion',
            field=models.CharField(blank=True, default='', max_length=49, verbose_name='Autorización'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='base_0',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Base 0 %'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='base_5',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Base 5 %'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='base_exenta',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Base exenta de IVA'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='base_gravada',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Base gravada'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='base_no_objeto',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Base no objeto de IVA'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='cod_sustento',
            field=models.CharField(blank=True, choices=[('01', 'Crédito tributario para declaración de IVA (servicios y bienes distintos de inventarios y activos fijos)'), ('02', 'Costo o gasto para declaración de IR (servicios y bienes distintos de inventarios y activos fijos)'), ('03', 'Activo fijo - Crédito tributario para declaración de IVA'), ('04', 'Activo fijo - Costo o gasto para declaración de IR'), ('05', 'Liquidación de gastos de viaje, hospedaje y alimentación, gastos IR (a nombre de empleados y no de la empresa)'), ('06', 'Inventario - Crédito tributario para declaración de IVA'), ('07', 'Inventario - Costo o gasto para declaración de IR'), ('08', 'Valor pagado para solicitar reembolso de gasto (intermediario)'), ('09', 'Reembolso por siniestros'), ('10', 'Distribución de dividendos, beneficios o utilidades'), ('11', 'Convenios de débito o recaudación para IFIs'), ('13', 'Valores reconocidos por entidades del sector público a favor de sujetos pasivos'), ('14', 'Valores facturados por socios a operadoras de transporte (que no constituyen gasto de dicha operadora)'), ('15', 'Pagos efectuados por consumos propios y de terceros de servicios digitales')], default='', max_length=2, verbose_name='Sustento tributario'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='completada_en',
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Datos completados el'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='completada_por',
            field=models.ForeignKey(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='Datos completados por'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='compra_modificada',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='ajustes', to='pos.purchase', verbose_name='Compra que modifica'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='datos_incompletos',
            field=models.BooleanField(default=True, verbose_name='Datos incompletos'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='estab',
            field=models.CharField(blank=True, default='', max_length=3, validators=[django.core.validators.RegexValidator('^(?!000)\\d{3}$', 'Usa tres dígitos, por ejemplo 001 (000 no es válido).')], verbose_name='Establecimiento'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='fecha_doc_modificado',
            field=models.DateField(blank=True, null=True, verbose_name='Fecha del documento modificado'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='fecha_emision',
            field=models.DateField(blank=True, null=True, verbose_name='Fecha de emisión del comprobante'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='forma_pago',
            field=models.CharField(blank=True, choices=[('01', 'SIN UTILIZACION DEL SISTEMA FINANCIERO'), ('15', 'COMPENSACIÓN DE DEUDAS'), ('16', 'TARJETA DE DÉBITO'), ('17', 'DINERO ELECTRÓNICO'), ('18', 'TARJETA PREPAGO'), ('19', 'TARJETA DE CRÉDITO'), ('20', 'OTROS CON UTILIZACION DEL SISTEMA FINANCIERO'), ('21', 'ENDOSO DE TÍTULOS')], default='', max_length=2, verbose_name='Forma de pago (ATS)'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='fuera_plazo_ats',
            field=models.BooleanField(default=False, verbose_name='Registrada fuera del plazo del ATS'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='num_doc_modificado',
            field=models.CharField(blank=True, default='', max_length=15, verbose_name='Número del documento modificado'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='origen',
            field=models.CharField(choices=[('manual', 'Registrada a mano'), ('importacion', 'Creada desde un XML importado')], default='manual', max_length=12, verbose_name='Origen'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='pago_loc_ext',
            field=models.CharField(blank=True, choices=[('01', 'Pago a residente / establecimiento permanente'), ('02', 'Pago a no residente')], default='', max_length=2, verbose_name='Pago a residente o no residente'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='parte_relacionada',
            field=models.BooleanField(blank=True, default=None, null=True, verbose_name='Parte relacionada'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='propina',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Propina'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='pto_emi',
            field=models.CharField(blank=True, default='', max_length=3, validators=[django.core.validators.RegexValidator('^(?!000)\\d{3}$', 'Usa tres dígitos, por ejemplo 001 (000 no es válido).')], verbose_name='Punto de emisión'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='secuencial',
            field=models.CharField(blank=True, default='', max_length=9, verbose_name='Secuencial'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='tipo_comprobante',
            field=models.CharField(blank=True, choices=[('01', 'Factura'), ('02', 'Nota o boleta de venta'), ('03', 'Liquidación de compra de bienes o prestación de servicios'), ('04', 'Nota de crédito'), ('05', 'Nota de débito'), ('09', 'Tiquetes o vales emitidos por máquinas registradoras'), ('11', 'Pasajes expedidos por empresas de aviación'), ('12', 'Documentos emitidos por instituciones financieras'), ('15', 'Comprobante de venta emitido en el exterior'), ('19', 'Comprobantes de pago de cuotas o aportes'), ('20', 'Documentos por servicios administrativos emitidos por instituciones del Estado'), ('21', 'Carta de porte aéreo')], default='', max_length=3, verbose_name='Tipo de comprobante'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='tipo_doc_modificado',
            field=models.CharField(blank=True, choices=[('01', 'Factura'), ('02', 'Nota o boleta de venta'), ('03', 'Liquidación de compra de bienes o prestación de servicios'), ('04', 'Nota de crédito'), ('05', 'Nota de débito'), ('09', 'Tiquetes o vales emitidos por máquinas registradoras'), ('11', 'Pasajes expedidos por empresas de aviación'), ('12', 'Documentos emitidos por instituciones financieras'), ('15', 'Comprobante de venta emitido en el exterior'), ('19', 'Comprobantes de pago de cuotas o aportes'), ('20', 'Documentos por servicios administrativos emitidos por instituciones del Estado'), ('21', 'Carta de porte aéreo')], default='', max_length=3, verbose_name='Tipo del documento modificado'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='total',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Total'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='total_descuento',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='Total descuento'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='total_ice',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='ICE'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='total_irbpnr',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='IRBPNR'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='total_iva',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name='IVA'),
        ),
        migrations.AddField(
            model_name='purchase',
            name='version_datos',
            field=models.PositiveSmallIntegerField(choices=[(1, 'Solo subtotal (sin impuestos por línea)'), (2, 'Con impuestos por línea')], default=1, verbose_name='Versión de los datos'),
        ),
        migrations.AlterField(
            model_name='purchase',
            name='number',
            field=models.CharField(blank=True, default='', max_length=20, verbose_name='Número del comprobante'),
        ),
        migrations.AddIndex(
            model_name='purchase',
            index=models.Index(fields=['company', 'datos_incompletos'], name='compra_incompleta'),
        ),
        migrations.AddIndex(
            model_name='purchase',
            index=models.Index(fields=['company', 'fecha_emision'], name='compra_fecha_emision'),
        ),
        migrations.AddConstraint(
            model_name='purchase',
            constraint=models.UniqueConstraint(condition=models.Q(('secuencial', ''), _negated=True), fields=('company', 'provider', 'tipo_comprobante', 'estab', 'pto_emi', 'secuencial'), name='compra_comprobante_unico_por_proveedor'),
        ),
        migrations.AddConstraint(
            model_name='purchase',
            constraint=models.CheckConstraint(condition=models.Q(('total__isnull', True), ('total__gte', 0), _connector='OR'), name='compra_total_no_negativo'),
        ),
        migrations.AddConstraint(
            model_name='purchase',
            constraint=models.CheckConstraint(condition=models.Q(('datos_incompletos', True), ('total__isnull', False), _connector='OR'), name='compra_completa_con_totales'),
        ),
        migrations.AddConstraint(
            model_name='purchase',
            constraint=models.CheckConstraint(condition=models.Q(('version_datos', 1), ('total__isnull', False), _connector='OR'), name='compra_v2_con_totales'),
        ),
    ]
