"""Comprobantes electrónicos adicionales: retención (07) y, en etapas siguientes, liquidación de compra (03),
nota de débito (05) y guía de remisión (06).

Todos comparten la emisión en dos fases de core/pos/emision.py (fecha y clave fijadas una vez, XML firmado
guardado antes de enviarlo, consulta por clave) y descuentan 1 del cupo del plan cuando el SRI los autoriza.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.pos.choices import ENVIRONMENT_TYPE, INVOICE_STATUS
from core.tenancy.models_base import TenantModel
from core.tenancy.storage import CompanyPath

CENTAVO = Decimal('0.01')


def redondear(valor):
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


class CodigoRetencion(models.Model):
    """Catálogo de la plataforma (no es de una empresa): códigos y porcentajes vigentes del SRI."""
    IMPUESTOS = (('1', 'Renta'), ('2', 'IVA'))

    impuesto = models.CharField(max_length=1, choices=IMPUESTOS, verbose_name='Impuesto')
    codigo = models.CharField(max_length=5, verbose_name='Código de retención')
    concepto = models.CharField(max_length=300, verbose_name='Concepto')
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='Porcentaje')
    porcentaje_editable = models.BooleanField(default=False, verbose_name='Porcentaje variable',
                                              help_text='El emisor puede escribir el porcentaje (códigos de % variable).')
    comun = models.BooleanField(default=False, verbose_name='De uso común')
    activo = models.BooleanField(default=True, verbose_name='Disponible')
    fuente = models.CharField(max_length=300, blank=True, verbose_name='Fuente (resolución o tabla del SRI)')
    orden = models.PositiveSmallIntegerField(default=0, verbose_name='Orden')

    class Meta:
        verbose_name = 'Código de retención'
        verbose_name_plural = 'Códigos de retención'
        ordering = ('impuesto', '-comun', 'orden', 'codigo')
        constraints = [models.UniqueConstraint(fields=['impuesto', 'codigo'], name='codigo_retencion_unico')]

    def __str__(self):
        return f'{self.codigo} · {self.concepto} ({self.porcentaje}%)'


class ComprobanteElectronico(TenantModel):
    """Campos y comportamiento comunes de un comprobante electrónico emitido por la empresa."""
    receipt = models.ForeignKey('pos.Receipt', on_delete=models.PROTECT, verbose_name='Secuencia')
    voucher_number = models.CharField(max_length=9, verbose_name='Secuencial')
    voucher_number_full = models.CharField(max_length=20, verbose_name='Número')
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+', verbose_name='Emitido por')
    date_joined = models.DateField(default=timezone.localdate, verbose_name='Fecha de registro')
    creation_date = models.DateTimeField(default=timezone.now, verbose_name='Registrado el')
    environment_type = models.PositiveIntegerField(choices=ENVIRONMENT_TYPE, verbose_name='Ambiente')
    create_electronic_invoice = models.BooleanField(default=True, editable=False)
    status = models.CharField(max_length=50, choices=INVOICE_STATUS, default=INVOICE_STATUS[0][0], verbose_name='Estado')
    access_code = models.CharField(max_length=49, null=True, blank=True, verbose_name='Clave de acceso')
    emission_date = models.DateField(null=True, blank=True, verbose_name='Fecha de emisión (SRI)')
    xml_signed = models.TextField(null=True, blank=True, verbose_name='XML firmado')
    signed_at = models.DateTimeField(null=True, blank=True, verbose_name='Firmado el')
    sri_sent_at = models.DateTimeField(null=True, blank=True, verbose_name='Enviado al SRI el')
    authorization_date = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de autorización')
    xml_authorized = models.FileField(upload_to=CompanyPath('comprobantes/xml'), null=True, blank=True, verbose_name='XML autorizado')
    pdf_authorized = models.FileField(upload_to=CompanyPath('comprobantes/pdf'), null=True, blank=True, verbose_name='RIDE')

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        nuevo = self.pk is None
        super().save(*args, **kwargs)
        if nuevo:
            self.receipt.registrar_usado(self.voucher_number)

    def get_xml_authorized(self):
        return f'{settings.MEDIA_URL}{self.xml_authorized}' if self.xml_authorized else None

    def get_pdf_authorized(self):
        return f'{settings.MEDIA_URL}{self.pdf_authorized}' if self.pdf_authorized else None

    def get_proveedor(self):
        from core.pos.emision import datos_proveedor
        return datos_proveedor()

    def generate_electronic_invoice(self):
        from core.pos import emision
        return emision.emitir(self)

    def get_destinatario(self):
        """(nombre, correo, enviar) de quien recibe el comprobante por correo."""
        raise NotImplementedError


class Retencion(ComprobanteElectronico):
    """Comprobante de retención (codDoc 07, XML 2.0.0) sobre una factura de proveedor registrada en Compras."""
    TIPO_IDENTIFICACION = (('04', 'RUC'), ('05', 'Cédula'), ('06', 'Pasaporte'), ('08', 'Identificación del exterior'))
    TIPO_SUJETO = (('01', 'Persona natural'), ('02', 'Sociedad'))

    purchase = models.ForeignKey('pos.Purchase', on_delete=models.PROTECT, related_name='retenciones', verbose_name='Compra')
    provider = models.ForeignKey('pos.Provider', on_delete=models.PROTECT, related_name='retenciones', verbose_name='Proveedor')
    # Sujeto retenido (copia al emitir: el XML no cambia si luego se edita el proveedor)
    tipo_identificacion = models.CharField(max_length=2, choices=TIPO_IDENTIFICACION, verbose_name='Tipo de identificación')
    identificacion = models.CharField(max_length=20, verbose_name='Identificación')
    razon_social = models.CharField(max_length=300, verbose_name='Razón social')
    tipo_sujeto = models.CharField(max_length=2, choices=TIPO_SUJETO, blank=True, verbose_name='Tipo de sujeto')
    parte_relacionada = models.BooleanField(default=False, verbose_name='Parte relacionada')
    correo = models.CharField(max_length=254, blank=True, verbose_name='Correo del proveedor')
    # Documento sustento (factura del proveedor)
    cod_sustento = models.CharField(max_length=2, default='01', verbose_name='Sustento tributario')
    cod_doc_sustento = models.CharField(max_length=3, default='01', verbose_name='Tipo de documento sustento')
    num_doc_sustento = models.CharField(max_length=15, verbose_name='Número del documento sustento')
    fecha_doc_sustento = models.DateField(verbose_name='Fecha de emisión del documento sustento')
    aut_doc_sustento = models.CharField(max_length=49, verbose_name='Autorización del documento sustento')
    base_0 = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Base 0 %')
    base_iva = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Base gravada con IVA')
    tarifa_iva = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('15.00'), verbose_name='Tarifa de IVA')
    valor_iva = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Valor del IVA')
    forma_pago = models.CharField(max_length=2, default='20', verbose_name='Forma de pago')
    total_retenido = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Total retenido')

    class Meta:
        verbose_name = 'Comprobante de retención'
        verbose_name_plural = 'Comprobantes de retención'
        ordering = ('-id',)
        default_permissions = ()
        permissions = (('view_retencion', 'Puede ver retenciones'), ('add_retencion', 'Puede emitir retenciones'),
                       ('delete_retencion', 'Puede eliminar retenciones no enviadas'))
        constraints = [models.UniqueConstraint(fields=['receipt', 'voucher_number'], name='retencion_numero_unico_por_secuencia')]

    def __str__(self):
        return f'Retención {self.voucher_number_full} · {self.razon_social}'

    @property
    def total_sin_impuestos(self):
        return redondear(self.base_0 + self.base_iva)

    @property
    def importe_total(self):
        return redondear(self.total_sin_impuestos + self.valor_iva)

    @property
    def periodo_fiscal(self):
        fecha = self.emission_date or self.date_joined
        return f'{fecha:%m/%Y}'

    @property
    def num_doc_sustento_formato(self):
        n = self.num_doc_sustento
        return f'{n[:3]}-{n[3:6]}-{n[6:]}' if len(n) == 15 else n

    def get_destinatario(self):
        return self.razon_social, self.correo, bool(self.correo)

    def generate_xml(self):
        from core.comprobantes.xml_retencion import generar_xml
        return generar_xml(self)

    def generate_pdf_authorized(self):
        from core.comprobantes.ride import guardar_ride
        guardar_ride(self, 'comprobantes/retencion/ride.html')

    def toJSON(self):
        return {
            'id': self.pk, 'numero': self.voucher_number_full, 'fecha': (self.emission_date or self.date_joined).strftime('%Y-%m-%d'),
            'proveedor': self.razon_social, 'identificacion': self.identificacion, 'documento': self.num_doc_sustento_formato,
            'total_retenido': float(self.total_retenido), 'ambiente': self.get_environment_type_display(),
            'status': {'id': self.status, 'name': self.get_status_display()}, 'clave': self.access_code or '',
            'pdf': self.get_pdf_authorized(), 'xml': self.get_xml_authorized(),
        }


class RetencionDetalle(TenantModel):
    retencion = models.ForeignKey(Retencion, on_delete=models.CASCADE, related_name='detalles')
    impuesto = models.CharField(max_length=1, choices=CodigoRetencion.IMPUESTOS, verbose_name='Impuesto')
    codigo = models.CharField(max_length=5, verbose_name='Código')
    concepto = models.CharField(max_length=300, verbose_name='Concepto')
    base_imponible = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Base imponible')
    porcentaje = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='Porcentaje')
    valor_retenido = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Valor retenido')

    class Meta:
        verbose_name = 'Detalle de retención'
        verbose_name_plural = 'Detalles de retención'
        ordering = ('impuesto', 'id')
        default_permissions = ()


class LiquidacionCompra(ComprobanteElectronico):
    """Liquidación de compra de bienes y prestación de servicios (codDoc 03, XML 1.1.0) sobre una compra registrada.

    La emite el comprador cuando el vendedor no puede emitir factura (sin RUC, RUC suspendido o no residente).
    """
    TIPO_IDENTIFICACION = (('05', 'Cédula'), ('06', 'Pasaporte'), ('08', 'Identificación del exterior'), ('04', 'RUC (suspendido)'))

    purchase = models.ForeignKey('pos.Purchase', on_delete=models.PROTECT, related_name='liquidaciones', verbose_name='Compra')
    provider = models.ForeignKey('pos.Provider', on_delete=models.PROTECT, related_name='liquidaciones', verbose_name='Proveedor')
    # Proveedor (copia al emitir: el XML no cambia si luego se edita el proveedor)
    tipo_identificacion = models.CharField(max_length=2, choices=TIPO_IDENTIFICACION, verbose_name='Tipo de identificación')
    identificacion = models.CharField(max_length=20, verbose_name='Identificación')
    razon_social = models.CharField(max_length=300, verbose_name='Nombres o razón social')
    direccion = models.CharField(max_length=300, blank=True, verbose_name='Dirección del proveedor')
    correo = models.CharField(max_length=254, blank=True, verbose_name='Correo del proveedor')
    forma_pago = models.CharField(max_length=2, default='01', verbose_name='Forma de pago')
    concepto = models.CharField(max_length=300, blank=True, verbose_name='Concepto')
    total_sin_impuestos = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Total sin impuestos')
    total_descuento = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Total descuento')
    total_iva = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='IVA')
    importe_total = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Importe total')

    class Meta:
        verbose_name = 'Liquidación de compra'
        verbose_name_plural = 'Liquidaciones de compra'
        ordering = ('-id',)
        default_permissions = ()
        permissions = (('view_liquidacioncompra', 'Puede ver liquidaciones de compra'),
                       ('add_liquidacioncompra', 'Puede emitir liquidaciones de compra'),
                       ('delete_liquidacioncompra', 'Puede eliminar liquidaciones de compra no enviadas'))
        constraints = [models.UniqueConstraint(fields=['receipt', 'voucher_number'], name='liquidacion_numero_unico_por_secuencia')]

    def __str__(self):
        return f'Liquidación de compra {self.voucher_number_full} · {self.razon_social}'

    @property
    def total(self):
        """Importe del correo de envío (core/pos/utilities/sri.py)."""
        return self.importe_total

    def impuestos_por_tarifa(self):
        """[(tarifa, base, iva)] ordenado por tarifa: totalConImpuestos del XML y subtotales del RIDE."""
        grupos = {}
        for d in self.detalles.all():
            base, iva = grupos.get(d.tarifa_iva, (Decimal('0'), Decimal('0')))
            grupos[d.tarifa_iva] = (base + d.precio_total_sin_impuesto, iva + d.valor_iva)
        return [(t, redondear(b), redondear(v)) for t, (b, v) in sorted(grupos.items())]

    def get_destinatario(self):
        return self.razon_social, self.correo, bool(self.correo)

    def generate_xml(self):
        from core.comprobantes.xml_liquidacion import generar_xml
        return generar_xml(self)

    def generate_pdf_authorized(self):
        from core.comprobantes.ride import guardar_ride
        guardar_ride(self, 'comprobantes/liquidacion/ride.html')


class LiquidacionDetalle(TenantModel):
    liquidacion = models.ForeignKey(LiquidacionCompra, on_delete=models.CASCADE, related_name='detalles')
    codigo = models.CharField(max_length=25, blank=True, verbose_name='Código')
    descripcion = models.CharField(max_length=300, verbose_name='Descripción')
    cantidad = models.DecimalField(max_digits=18, decimal_places=6, verbose_name='Cantidad')
    precio_unitario = models.DecimalField(max_digits=18, decimal_places=6, verbose_name='Precio unitario')
    descuento = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Descuento')
    precio_total_sin_impuesto = models.DecimalField(max_digits=14, decimal_places=2, verbose_name='Precio total sin impuesto')
    tarifa_iva = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='Tarifa de IVA')
    valor_iva = models.DecimalField(max_digits=14, decimal_places=2, verbose_name='Valor del IVA')

    class Meta:
        verbose_name = 'Detalle de liquidación de compra'
        verbose_name_plural = 'Detalles de liquidación de compra'
        ordering = ('id',)
        default_permissions = ()


class NotaDebito(ComprobanteElectronico):
    """Nota de débito (codDoc 05, XML 1.0.0) sobre una factura autorizada: intereses de mora, gastos de cobranza u otros
    cargos posteriores. La tarifa de IVA es la de la fecha de la factura (nota de la ficha técnica)."""
    sale = models.ForeignKey('pos.Sale', on_delete=models.PROTECT, related_name='notas_debito', verbose_name='Factura')
    # Comprador (copia al emitir: el XML no cambia si luego se edita el cliente)
    tipo_identificacion = models.CharField(max_length=2, verbose_name='Tipo de identificación')
    identificacion = models.CharField(max_length=20, verbose_name='Identificación')
    razon_social = models.CharField(max_length=300, verbose_name='Razón social')
    direccion = models.CharField(max_length=300, blank=True, verbose_name='Dirección')
    correo = models.CharField(max_length=254, blank=True, verbose_name='Correo')
    enviar_correo = models.BooleanField(default=True, verbose_name='Enviar por correo')
    # Comprobante que se modifica
    cod_doc_modificado = models.CharField(max_length=2, default='01', verbose_name='Tipo de comprobante modificado')
    num_doc_modificado = models.CharField(max_length=17, verbose_name='Número del comprobante modificado')
    fecha_doc_sustento = models.DateField(verbose_name='Fecha de emisión del comprobante modificado')
    tarifa_iva = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='Tarifa de IVA')
    total_sin_impuestos = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Total sin impuestos')
    valor_iva = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='IVA')
    valor_total = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Valor total')
    forma_pago = models.CharField(max_length=2, default='20', verbose_name='Forma de pago')

    class Meta:
        verbose_name = 'Nota de débito'
        verbose_name_plural = 'Notas de débito'
        ordering = ('-id',)
        default_permissions = ()
        permissions = (('view_notadebito', 'Puede ver notas de débito'), ('add_notadebito', 'Puede emitir notas de débito'),
                       ('delete_notadebito', 'Puede eliminar notas de débito no enviadas'))
        constraints = [models.UniqueConstraint(fields=['receipt', 'voucher_number'], name='nota_debito_numero_unico_por_secuencia')]

    def __str__(self):
        return f'Nota de débito {self.voucher_number_full} · {self.razon_social}'

    @property
    def total(self):
        """Importe del correo de envío (core/pos/utilities/sri.py)."""
        return self.valor_total

    def get_destinatario(self):
        return self.razon_social, self.correo, bool(self.correo) and self.enviar_correo

    def generate_xml(self):
        from core.comprobantes.xml_nota_debito import generar_xml
        return generar_xml(self)

    def generate_pdf_authorized(self):
        from core.comprobantes.ride import guardar_ride
        guardar_ride(self, 'comprobantes/notadebito/ride.html')


class NotaDebitoMotivo(TenantModel):
    nota = models.ForeignKey(NotaDebito, on_delete=models.CASCADE, related_name='motivos')
    razon = models.CharField(max_length=300, verbose_name='Razón de la modificación')
    valor = models.DecimalField(max_digits=14, decimal_places=2, verbose_name='Valor')

    class Meta:
        verbose_name = 'Motivo de nota de débito'
        verbose_name_plural = 'Motivos de nota de débito'
        ordering = ('id',)
        default_permissions = ()
