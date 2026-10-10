"""Planes anuales, pagos con PayPhone, períodos de suscripción y cupo de comprobantes.

Importes en centavos enteros (nunca en coma flotante). El precio publicado es
el total con IVA incluido; el desglose se calcula con la tarifa vigente y se
congela en cada pago.
"""
import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Plan(models.Model):
    code = models.SlugField(unique=True, verbose_name='Código')
    name = models.CharField(max_length=60, verbose_name='Nombre')
    description = models.CharField(max_length=200, blank=True, verbose_name='Descripción')
    price_cents = models.PositiveIntegerField(default=0, verbose_name='Precio anual con IVA (centavos)')
    document_limit = models.PositiveIntegerField(null=True, blank=True, verbose_name='Documentos por período (vacío = ilimitado)')
    months = models.PositiveSmallIntegerField(default=12, verbose_name='Duración (meses)')
    includes_billing = models.BooleanField(default=True, verbose_name='Incluye facturación y ventas')
    product_limit = models.PositiveIntegerField(null=True, blank=True, verbose_name='Límite de productos (solo gratuito)')
    provider_limit = models.PositiveIntegerField(null=True, blank=True, verbose_name='Límite de proveedores (solo gratuito)')
    purchase_limit_month = models.PositiveIntegerField(null=True, blank=True, verbose_name='Límite de compras por mes (solo gratuito)')
    is_active = models.BooleanField(default=True, verbose_name='Disponible para contratar')
    order = models.PositiveSmallIntegerField(default=0, verbose_name='Orden')

    class Meta:
        verbose_name = 'Plan'
        verbose_name_plural = 'Planes'
        ordering = ('order', 'price_cents')

    def __str__(self):
        return self.name

    @property
    def unlimited(self):
        return self.document_limit is None

    @property
    def price(self):
        return Decimal(self.price_cents) / 100


class IvaRate(models.Model):
    rate = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='Tarifa (%)')
    valid_from = models.DateField(verbose_name='Vigente desde')
    legal_reference = models.CharField(max_length=200, verbose_name='Referencia legal')

    class Meta:
        verbose_name = 'Tarifa de IVA'
        verbose_name_plural = 'Tarifas de IVA'
        ordering = ('-valid_from',)

    def __str__(self):
        return f'{self.rate} % desde {self.valid_from}'

    @classmethod
    def current(cls, day=None):
        day = day or timezone.localdate()
        return cls.objects.filter(valid_from__lte=day).order_by('-valid_from').first()

    @staticmethod
    def breakdown(total_cents, rate):
        """(base, iva) en centavos de un total con IVA incluido; base + iva == total siempre."""
        base = (Decimal(total_cents) / (1 + Decimal(rate) / 100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        return int(base), int(total_cents - base)


class Payment(models.Model):
    STATUS = (
        ('creado', 'Creado'),
        ('redirigido', 'En PayPhone'),
        ('aprobado', 'Aprobado'),
        ('cancelado', 'Cancelado'),
        ('rechazado', 'Rechazado'),
        ('expirado', 'Expirado sin confirmar'),
        ('error_comunicacion', 'Pendiente de conciliación'),
        ('en_revision', 'En revisión'),
        ('reversado', 'Reversado'),
    )
    FINAL = ('aprobado', 'cancelado', 'rechazado', 'expirado', 'en_revision', 'reversado')
    MODES = (('inmediato', 'Empieza al confirmar el pago'), ('programado', 'Empieza al terminar el período actual'))
    METHODS = (('payphone', 'PayPhone'), ('manual', 'Registro manual de la plataforma'))

    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    company = models.ForeignKey('pos.Company', on_delete=models.PROTECT, related_name='payments', verbose_name='Empresa')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, verbose_name='Plan')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', verbose_name='Usuario')
    method = models.CharField(max_length=20, choices=METHODS, default='payphone', verbose_name='Medio')
    mode = models.CharField(max_length=20, choices=MODES, default='inmediato', verbose_name='Inicio del período')
    client_tx_id = models.CharField(max_length=50, unique=True, verbose_name='Referencia interna')
    amount_cents = models.PositiveIntegerField(verbose_name='Total (centavos)')
    base_cents = models.PositiveIntegerField(verbose_name='Base imponible (centavos)')
    iva_cents = models.PositiveIntegerField(verbose_name='IVA (centavos)')
    iva_rate = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='Tarifa de IVA aplicada (%)')
    currency = models.CharField(max_length=3, default='USD', verbose_name='Moneda')
    status = models.CharField(max_length=30, choices=STATUS, default='creado', db_index=True, verbose_name='Estado')
    payphone_payment_id = models.CharField(max_length=60, blank=True, verbose_name='Id de preparación PayPhone')
    payphone_transaction_id = models.CharField(max_length=60, null=True, blank=True, unique=True, verbose_name='Transacción PayPhone')
    authorization_code = models.CharField(max_length=60, blank=True, verbose_name='Código de autorización')
    card_brand = models.CharField(max_length=40, blank=True, verbose_name='Tarjeta')
    last_digits = models.CharField(max_length=4, blank=True, verbose_name='Últimos dígitos')
    note = models.CharField(max_length=300, blank=True, verbose_name='Observación')
    created_at = models.DateTimeField(default=timezone.now, verbose_name='Creado')
    redirected_at = models.DateTimeField(null=True, blank=True, verbose_name='Enviado a PayPhone')
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name='Confirmado')
    invoice_requested = models.BooleanField(default=False, verbose_name='Factura solicitada')
    invoice_data = models.JSONField(default=dict, blank=True, verbose_name='Datos para la factura')
    invoice_number = models.CharField(max_length=30, blank=True, verbose_name='Número de factura emitida')

    class Meta:
        verbose_name = 'Pago'
        verbose_name_plural = 'Pagos'
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.client_tx_id} · {self.plan} · {self.get_status_display()}'

    @property
    def amount(self):
        return Decimal(self.amount_cents) / 100

    @property
    def base(self):
        return Decimal(self.base_cents) / 100

    @property
    def iva(self):
        return Decimal(self.iva_cents) / 100


class PaymentEvent(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='events')
    kind = models.CharField(max_length=40, verbose_name='Evento')
    detail = models.JSONField(default=dict, blank=True, verbose_name='Detalle (saneado)')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ('created_at',)
        verbose_name = 'Evento de pago'
        verbose_name_plural = 'Eventos de pago'


class SubscriptionPeriod(models.Model):
    STATUS = (('programada', 'Programada'), ('activa', 'Activa'), ('reemplazada', 'Reemplazada'), ('anulada', 'Anulada'))

    company = models.ForeignKey('pos.Company', on_delete=models.PROTECT, related_name='subscription_periods', verbose_name='Empresa')
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, verbose_name='Plan')
    payment = models.OneToOneField(Payment, null=True, blank=True, on_delete=models.PROTECT, related_name='period', verbose_name='Pago')
    status = models.CharField(max_length=20, choices=STATUS, default='activa', db_index=True, verbose_name='Estado')
    starts_at = models.DateTimeField(verbose_name='Inicio')
    ends_at = models.DateTimeField(verbose_name='Fin')
    document_limit = models.PositiveIntegerField(null=True, blank=True, verbose_name='Límite de documentos')
    documents_used = models.PositiveIntegerField(default=0, verbose_name='Documentos autorizados')
    documents_reserved = models.PositiveIntegerField(default=0, verbose_name='Documentos en proceso')
    note = models.CharField(max_length=300, blank=True, verbose_name='Observación')
    created_at = models.DateTimeField(default=timezone.now)
    replaced_at = models.DateTimeField(null=True, blank=True, verbose_name='Reemplazada el')

    class Meta:
        verbose_name = 'Período de suscripción'
        verbose_name_plural = 'Períodos de suscripción'
        ordering = ('-starts_at',)

    def __str__(self):
        return f'{self.company} · {self.plan} · {self.starts_at:%Y-%m-%d} → {self.ends_at:%Y-%m-%d}'

    @property
    def available(self):
        if self.document_limit is None:
            return None
        return max(self.document_limit - self.documents_used - self.documents_reserved, 0)


class QuotaReservation(models.Model):
    STATUS = (('reservada', 'En proceso'), ('consumida', 'Autorizada (consumida)'), ('liberada', 'Liberada'))

    company = models.ForeignKey('pos.Company', on_delete=models.CASCADE, related_name='+', verbose_name='Empresa')
    period = models.ForeignKey(SubscriptionPeriod, on_delete=models.PROTECT, related_name='reservations', verbose_name='Período')
    voucher_model = models.CharField(max_length=30, verbose_name='Tipo de comprobante')
    voucher_id = models.PositiveIntegerField(verbose_name='Id del comprobante')
    voucher_label = models.CharField(max_length=40, blank=True, verbose_name='Número')
    status = models.CharField(max_length=20, choices=STATUS, default='reservada', verbose_name='Estado')
    created_at = models.DateTimeField(default=timezone.now)
    consumed_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Uso de cupo'
        verbose_name_plural = 'Usos de cupo'
        constraints = [models.UniqueConstraint(fields=['company', 'voucher_model', 'voucher_id'], name='cupo_un_registro_por_comprobante')]
