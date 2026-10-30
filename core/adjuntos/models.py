"""Comprobantes de pago adjuntos a los documentos de tesorería: facturas emitidas, compras, gastos, cobros y pagos.

Conceptos tomados de erpnext (solo el diseño; erpnext es GPL-3.0 y no se copia código): cualquier documento lleva
archivos adjuntos privados con la huella de su contenido (doctype `File`), y el pago (`Payment Entry`) guarda la
referencia y la fecha del comprobante (`reference_no`, `reference_date`) con las que después se concilia contra el
extracto (`Bank Transaction`, `Bank Clearance`). Aquí:

- el adjunto cuelga de su documento por (tipo, id) y pertenece a la empresa (RLS en PostgreSQL, migración 0002);
- el archivo vive bajo `privado/` (la descarga general de /media/ no lo entrega) y solo sale por la vista propia, con el
  permiso de ver el documento;
- nunca se borra: se marca eliminado (quién, cuándo y por qué), como los abonos automáticos de las cuentas por cobrar;
- referencia, fecha e importe del comprobante son los datos con los que la Etapa 3 (Bancos) sugerirá la conciliación.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from core.importacion.models import RutaPrivada
from core.tenancy.models_base import TenantModel

TIPOS_DOCUMENTO = (
    ('venta', 'Factura emitida'),
    ('compra', 'Compra'),
    ('gasto', 'Gasto'),
    ('cobro', 'Cobro de cuenta por cobrar'),
    ('pago', 'Pago de cuenta por pagar'),
)
CLASES = (
    ('transferencia', 'Comprobante de transferencia'),
    ('deposito', 'Papeleta de depósito'),
    ('cheque', 'Cheque'),
    ('voucher', 'Voucher de tarjeta'),
    ('recibo', 'Recibo'),
    ('estado_cuenta', 'Estado de cuenta'),
    ('otro', 'Otro'),
)
# Clase sugerida según el medio de pago del documento (MEDIOS_DE_PAGO de core/pos/choices.py y PAYMENT_METHOD del SRI).
CLASE_POR_MEDIO = {'transferencia': 'transferencia', 'deposito': 'deposito', 'cheque': 'cheque', 'tarjeta_debito': 'voucher',
                   'tarjeta_credito': 'voucher', 'efectivo': 'recibo', 'compensacion': 'otro', 'otro': 'otro',
                   '01': 'recibo', '16': 'voucher', '19': 'voucher', '20': 'transferencia'}
FORMATOS = {'application/pdf': 'pdf', 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}


class Adjunto(TenantModel):
    documento_tipo = models.CharField(max_length=10, choices=TIPOS_DOCUMENTO, verbose_name='Tipo de documento')
    documento_id = models.PositiveBigIntegerField(verbose_name='Id del documento')
    clase = models.CharField(max_length=15, choices=CLASES, default='transferencia', verbose_name='Clase de comprobante')
    archivo = models.FileField(upload_to=RutaPrivada('comprobantes-pago'), max_length=255, verbose_name='Archivo')
    nombre = models.CharField(max_length=150, verbose_name='Nombre original del archivo')
    tipo_mime = models.CharField(max_length=30, verbose_name='Tipo de contenido')
    tamano = models.PositiveIntegerField(verbose_name='Tamaño en bytes')
    sha256 = models.CharField(max_length=64, db_index=True, verbose_name='SHA-256 del contenido')
    referencia = models.CharField(max_length=100, blank=True, default='',
                                  verbose_name='Referencia (n.º de transferencia, cheque o comprobante)')
    fecha = models.DateField(null=True, blank=True, verbose_name='Fecha del comprobante')
    importe = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Importe del comprobante')
    descripcion = models.CharField(max_length=300, blank=True, default='', verbose_name='Descripción')
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                   verbose_name='Subido por')
    subido_en = models.DateTimeField(default=timezone.now, verbose_name='Subido el')
    eliminado_en = models.DateTimeField(null=True, blank=True, verbose_name='Quitado el')
    eliminado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name='+', verbose_name='Quitado por')
    eliminado_motivo = models.CharField(max_length=300, blank=True, default='', verbose_name='Motivo')

    class Meta:
        verbose_name = 'Comprobante de pago adjunto'
        verbose_name_plural = 'Comprobantes de pago adjuntos'
        ordering = ('id',)
        default_permissions = ()
        permissions = (
            ('view_adjunto', 'Puede ver los comprobantes de pago adjuntos'),
            ('add_adjunto', 'Puede adjuntar comprobantes de pago'),
            ('delete_adjunto', 'Puede quitar comprobantes de pago adjuntos'),
        )
        indexes = [models.Index(fields=['company', 'documento_tipo', 'documento_id'], name='adjunto_por_documento')]

    def __str__(self):
        return f'{self.get_clase_display()} · {self.nombre}'

    @property
    def vigente(self):
        return self.eliminado_en is None

    @property
    def extension(self):
        return FORMATOS.get(self.tipo_mime, 'bin')
