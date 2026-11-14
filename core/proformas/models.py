"""Proformas (cotizaciones sin validez tributaria) con numeración propia PRO-000001 por empresa.

No usan Receipt, reservar_numero, cupo, stock, cuentas por cobrar ni el SRI. Las líneas usan los nombres de campo de
SaleDetail para reutilizar calcular_linea_iva, impuestos_por_tarifa y totales_de_lineas (core/pos/models.py): la factura
que nace de una proforma calcula los mismos importes.

«Convertir en factura» crea (o reabre) un BorradorFactura: la factura en borrador de esa proforma, con cliente, líneas,
tarifa de IVA por línea, pago e información adicional. Tampoco usa número, cupo, stock ni el SRI: todo eso ocurre solo al
pulsar «Emitir factura» en la venta (core/pos/views/sale/views.py). Ver primera-entrega/convertir-en-factura.md.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.pos.choices import NOMBRE_TARIFA_IVA, PAYMENT_METHOD, PAYMENT_TYPE
from core.tenancy.models_base import TenantModel


# Medio de pago sugerido, como lo lee el cliente en la proforma. Mismos códigos que MEDIOS_DE_PAGO (core/pos/choices.py):
# al facturar pasa a Sale.medio_cobro y su forma de pago del SRI sale de FORMA_PAGO_SRI_DE_MEDIO (transferencia → 20).
MEDIOS_PAGO_PROFORMA = (
    ('efectivo', 'Efectivo'), ('transferencia', 'Transferencia bancaria'), ('deposito', 'Depósito bancario'),
    ('cheque', 'Cheque'), ('tarjeta_debito', 'Tarjeta de débito'), ('tarjeta_credito', 'Tarjeta de crédito'),
    ('compensacion', 'Compensación de deudas'), ('otro', 'Otro'),
)


class ContadorProforma(TenantModel):
    ultimo = models.PositiveIntegerField(default=0, verbose_name='Último número utilizado')

    class Meta:
        verbose_name = 'Contador de proformas'
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['company'], name='un_contador_de_proformas_por_empresa')]

    def __str__(self):
        return f'PRO-{self.ultimo:06d}'


class Proforma(TenantModel):
    ESTADOS = (('borrador', 'Borrador'), ('enviada', 'Enviada'), ('aceptada', 'Aceptada'),
               ('rechazada', 'Rechazada'), ('facturada', 'Facturada'), ('anulada', 'Anulada'))
    # Orden de la maqueta de Codex; «vencida» solo se calcula (borrador o enviada con la validez ya pasada).
    ESTADOS_VISIBLES = ESTADOS[:4] + (('vencida', 'Vencida'),) + ESTADOS[4:]
    PUEDEN_VENCER = ('borrador', 'enviada')

    numero = models.PositiveIntegerField(editable=False, verbose_name='Número')
    numero_completo = models.CharField(max_length=20, editable=False, verbose_name='Número completo')
    cliente = models.ForeignKey('pos.Client', on_delete=models.SET_NULL, null=True, blank=True, related_name='proformas',
                                verbose_name='Cliente')
    cliente_nombre = models.CharField(max_length=300, verbose_name='Nombre del cliente')
    cliente_identificacion = models.CharField(max_length=20, blank=True, default='', verbose_name='Identificación')
    cliente_correo = models.CharField(max_length=500, blank=True, default='', verbose_name='Correos')
    cliente_telefono = models.CharField(max_length=20, blank=True, default='', verbose_name='Teléfono')
    cliente_direccion = models.CharField(max_length=500, blank=True, default='', verbose_name='Dirección')
    fecha = models.DateField(default=timezone.localdate, verbose_name='Fecha')
    valida_hasta = models.DateField(verbose_name='Válida hasta')
    vendedor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='+', verbose_name='Vendedor')
    condiciones = models.TextField(blank=True, default='', verbose_name='Condiciones')
    forma_pago_sugerida = models.CharField(max_length=2, choices=PAYMENT_METHOD, blank=True, default='',
                                           verbose_name='Forma de pago sugerida')
    # db_default: las inserciones que no nombran la columna (SQL directo, migraciones antiguas) siguen funcionando.
    medio_pago_sugerido = models.CharField(max_length=15, choices=MEDIOS_PAGO_PROFORMA, blank=True, default='', db_default='',
                                           verbose_name='Medio de pago sugerido')
    # Solo el PDF (y su copia por correo): `vendedor` y `creada_por` se guardan igual y se ven en la ficha y la auditoría.
    ocultar_vendedor = models.BooleanField(default=False, db_default=False, verbose_name='Ocultar el vendedor en el PDF')
    subtotal_gravado = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'),
                                           verbose_name='Subtotal gravado')
    subtotal_cero = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'),
                                        verbose_name='Subtotal 0 %, no objeto y exento')
    total_descuento = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'), verbose_name='Descuento')
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'), verbose_name='IVA')
    total = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'), verbose_name='Total')
    estado = models.CharField(max_length=12, choices=ESTADOS, default='borrador', verbose_name='Estado')
    venta = models.OneToOneField('pos.Sale', on_delete=models.SET_NULL, null=True, blank=True, related_name='proforma',
                                 verbose_name='Factura')
    origen = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='copias',
                               verbose_name='Duplicada de')
    motivo = models.CharField(max_length=300, blank=True, default='', verbose_name='Motivo')
    enviada_a = models.CharField(max_length=500, blank=True, default='', verbose_name='Enviada a')
    envios = models.PositiveSmallIntegerField(default=0, verbose_name='Correos enviados')
    creada_en = models.DateTimeField(default=timezone.now, editable=False, verbose_name='Creada el')
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', verbose_name='Creada por')
    actualizada_en = models.DateTimeField(auto_now=True, verbose_name='Actualizada el')
    enviada_en = models.DateTimeField(null=True, blank=True, verbose_name='Enviada el')
    aceptada_en = models.DateTimeField(null=True, blank=True, verbose_name='Aceptada el')
    rechazada_en = models.DateTimeField(null=True, blank=True, verbose_name='Rechazada el')
    anulada_en = models.DateTimeField(null=True, blank=True, verbose_name='Anulada el')
    facturada_en = models.DateTimeField(null=True, blank=True, verbose_name='Facturada el')
    facturada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='+', verbose_name='Facturada por')

    class Meta:
        verbose_name = 'Proforma'
        verbose_name_plural = 'Proformas'
        ordering = ('-id',)
        default_permissions = ()
        permissions = (('view_proforma', 'Puede ver proformas y descargar su PDF'),
                       ('add_proforma', 'Puede crear y duplicar proformas'),
                       ('change_proforma', 'Puede editar, enviar, aceptar, rechazar, anular y facturar proformas'),
                       ('delete_proforma', 'Puede eliminar borradores de proformas nunca enviados'))
        constraints = [
            models.UniqueConstraint(fields=['company', 'numero'], name='proforma_numero_unico_por_empresa'),
            models.CheckConstraint(condition=models.Q(valida_hasta__gte=models.F('fecha')), name='proforma_vigencia_coherente'),
            models.CheckConstraint(condition=(models.Q(estado='facturada', venta__isnull=False)
                                              | (~models.Q(estado='facturada') & models.Q(venta__isnull=True))),
                                   name='proforma_facturada_con_venta'),
            models.CheckConstraint(condition=models.Q(total__gte=0), name='proforma_total_no_negativo'),
        ]
        indexes = [models.Index(fields=['company', 'estado', 'valida_hasta'], name='proforma_estado_idx'),
                   models.Index(fields=['company', 'fecha'], name='proforma_fecha_idx')]

    def __str__(self):
        return f'{self.numero_completo} · {self.cliente_nombre}'

    @property
    def es_prospecto(self):
        return self.cliente_id is None

    def correos(self):
        from core.pos.clientes import separar_correos
        return separar_correos(self.cliente_correo)

    def esta_vencida(self, hoy=None):
        return self.estado in self.PUEDEN_VENCER and self.valida_hasta < (hoy or timezone.localdate())

    def estado_visible(self, hoy=None):
        return 'vencida' if self.esta_vencida(hoy) else self.estado

    def nombre_estado(self, hoy=None):
        return dict(self.ESTADOS_VISIBLES)[self.estado_visible(hoy)]


class ProformaDetalle(TenantModel):
    proforma = models.ForeignKey(Proforma, on_delete=models.CASCADE, related_name='detalles', verbose_name='Proforma')
    product = models.ForeignKey('pos.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                verbose_name='Producto')
    codigo = models.CharField(max_length=20, blank=True, default='', verbose_name='Código')
    descripcion = models.CharField(max_length=300, verbose_name='Descripción')
    cant = models.IntegerField(default=1, verbose_name='Cantidad')
    price = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'), verbose_name='Precio unitario')
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0.00'), verbose_name='Descuento (fracción)')
    codigo_porcentaje = models.CharField(max_length=2, verbose_name='Tarifa de IVA (código)')
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0, verbose_name='Tarifa de IVA (fracción)')
    price_with_vat = models.DecimalField(max_digits=9, decimal_places=2, default=0, verbose_name='Precio con IVA')
    subtotal = models.DecimalField(max_digits=9, decimal_places=2, default=0, verbose_name='Subtotal')
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0, verbose_name='Valor del descuento')
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0, verbose_name='Total')
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0, verbose_name='IVA')

    class Meta:
        verbose_name = 'Línea de proforma'
        verbose_name_plural = 'Líneas de proforma'
        ordering = ('id',)   # orden de ingreso (las líneas se recrean al editar, en el orden recibido)
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=models.Q(cant__gte=1), name='proforma_detalle_cant_positiva'),
            models.CheckConstraint(condition=models.Q(price__gte=0), name='proforma_detalle_precio_no_negativo'),
            models.CheckConstraint(condition=models.Q(dscto__gte=0) & models.Q(dscto__lte=1),
                                   name='proforma_detalle_descuento_valido'),
            models.UniqueConstraint(fields=['proforma', 'product'], condition=models.Q(product__isnull=False),
                                    name='proforma_detalle_producto_unico'),
        ]

    def __str__(self):
        return f'{self.cant} × {self.descripcion}'

    @property
    def nombre_tarifa(self):
        return NOMBRE_TARIFA_IVA.get(self.codigo_porcentaje, self.codigo_porcentaje)


class BorradorFactura(TenantModel):
    """Factura en borrador de una proforma («Convertir en factura»). Una por proforma (OneToOne): convertir otra vez o con
    doble clic reabre la misma. No tiene número, cupo, stock, cuenta por cobrar ni XML: se emite solo con «Emitir factura»
    en la venta, que lo borra en su misma transacción (marcar_facturada). Descartarlo deja la proforma como estaba.

    `lineas`: [{product, nombre, cant, price ("10.00"), dscto (porcentaje entero), codigo_porcentaje}] en el orden de la
    factura. `codigo_porcentaje` es la tarifa de IVA elegida para ESTA operación (tabla 17); nunca cambia el producto."""
    proforma = models.OneToOneField(Proforma, on_delete=models.CASCADE, related_name='borrador_factura',
                                    verbose_name='Proforma')
    cliente = models.ForeignKey('pos.Client', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                verbose_name='Cliente')
    payment_type = models.CharField(max_length=10, choices=PAYMENT_TYPE, default=PAYMENT_TYPE[0][0],
                                    verbose_name='Condición de pago')
    payment_method = models.CharField(max_length=2, choices=PAYMENT_METHOD, blank=True, default='',
                                      verbose_name='Forma de pago del SRI')
    medio_cobro = models.CharField(max_length=15, choices=MEDIOS_PAGO_PROFORMA, blank=True, default='',
                                   verbose_name='Medio de cobro')
    # Lo que la venta lleva a crédito: el plazo en días (<plazo> del XML) y la fecha de vencimiento, tal como se guardaron.
    time_limit = models.PositiveIntegerField(null=True, blank=True, verbose_name='Plazo (días)')
    end_credit = models.DateField(null=True, blank=True, verbose_name='Fecha de plazo del crédito')
    lineas = models.JSONField(default=list, verbose_name='Líneas')
    info_adicional = models.JSONField(default=list, verbose_name='Información adicional')
    avisos = models.JSONField(default=list, verbose_name='Avisos de la conversión')
    creado_en = models.DateTimeField(default=timezone.now, editable=False, verbose_name='Creado el')
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', verbose_name='Creado por')
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name='Actualizado el')
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name='+', verbose_name='Actualizado por')

    class Meta:
        verbose_name = 'Borrador de factura'
        verbose_name_plural = 'Borradores de factura'
        default_permissions = ()

    def __str__(self):
        return f'Borrador de factura de {self.proforma_id}'
