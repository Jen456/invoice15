"""Comprobantes de pago adjuntos a los documentos de egreso (compras, gastos y pagos a proveedores) y recibos o notas
guardados para completar después (capturas). Las facturas emitidas y sus cobros se respaldan en core/cobros.

Conceptos tomados de erpnext (solo el diseño; erpnext es GPL-3.0 y no se copia código): cualquier documento lleva
archivos adjuntos privados con la huella de su contenido (doctype `File`), y el pago (`Payment Entry`) guarda la
referencia y la fecha del comprobante (`reference_no`, `reference_date`) con las que después se concilia contra el
extracto (`Bank Transaction`, `Bank Clearance`). Aquí:

- el adjunto cuelga de su documento por (tipo, id) y pertenece a la empresa (RLS en PostgreSQL, migraciones 0002 y 0005);
- un adjunto es un archivo (con su descripción) o una nota de respaldo sin archivo (`clase='nota'`: texto, autor y fecha
  del servidor). La descripción de un gasto (`Expenses.description`) no es un respaldo: no se convierte en nota;
- el archivo vive bajo `privado/` (la descarga general de /media/ no lo entrega) y solo sale por la vista propia, con el
  permiso de ver el documento;
- nunca se borra: se marca eliminado (quién, cuándo y por qué), como los abonos automáticos de las cuentas por cobrar;
- referencia, fecha e importe del comprobante son los datos con los que la Etapa 3 (Bancos) sugerirá la conciliación;
- una captura (`Captura`) guarda un recibo y/o una nota sin importe, categoría, proveedor ni medio de pago: no crea gasto,
  compra, pago, asiento ni crédito tributario. Al completarla (gasto o compra nuevos) o vincularla a un documento existente
  nace el adjunto con el MISMO archivo físico (no se copia ni se vuelve a subir). Ese archivo es compartido entre la
  captura y su adjunto: nadie lo borra.
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
# Clases de archivo que se eligen al adjuntar (selectores del modal y de los formularios).
CLASES = (
    ('transferencia', 'Comprobante de transferencia'),
    ('deposito', 'Papeleta de depósito'),
    ('cheque', 'Cheque'),
    ('voucher', 'Voucher de tarjeta'),
    ('recibo', 'Recibo'),
    ('estado_cuenta', 'Estado de cuenta'),
    ('otro', 'Otro'),
)
# La nota de respaldo no es una clase de archivo: la fija el servidor cuando no hay archivo.
CLASE_NOTA = 'nota'
CLASES_ADJUNTO = CLASES + ((CLASE_NOTA, 'Nota de respaldo'),)
# Clase sugerida según el medio de pago del documento (MEDIOS_DE_PAGO de core/pos/choices.py y PAYMENT_METHOD del SRI).
CLASE_POR_MEDIO = {'transferencia': 'transferencia', 'deposito': 'deposito', 'cheque': 'cheque', 'tarjeta_debito': 'voucher',
                   'tarjeta_credito': 'voucher', 'efectivo': 'recibo', 'compensacion': 'otro', 'otro': 'otro',
                   '01': 'recibo', '16': 'voucher', '19': 'voucher', '20': 'transferencia'}
FORMATOS = {'application/pdf': 'pdf', 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}
NOTA_MAX = 500            # nota de respaldo, nota de una captura y descripción de un archivo
MOTIVO_MAX = 300
ESTADOS_CAPTURA = (
    ('pendiente', 'Pendiente de completar'),
    ('completada', 'Completada: registró el documento'),
    ('vinculada', 'Vinculada a un documento existente'),
    ('descartada', 'Descartada'),
)


class Captura(TenantModel):
    """Recibo (PDF o foto) y/o nota guardados ahora para completar después como gasto o compra, o para vincular a un
    documento existente. Sin efectos contables mientras está pendiente."""
    clave = models.CharField(max_length=40, verbose_name='Clave del envío (idempotencia)')
    archivo = models.FileField(upload_to=RutaPrivada('comprobantes-pago'), max_length=255, blank=True, verbose_name='Archivo')
    nombre = models.CharField(max_length=150, blank=True, default='', verbose_name='Nombre original del archivo')
    tipo_mime = models.CharField(max_length=30, blank=True, default='', verbose_name='Tipo de contenido')
    tamano = models.PositiveIntegerField(default=0, verbose_name='Tamaño en bytes')
    sha256 = models.CharField(max_length=64, blank=True, default='', db_index=True, verbose_name='SHA-256 del contenido')
    nota = models.TextField(blank=True, default='', verbose_name='Nota')
    estado = models.CharField(max_length=12, choices=ESTADOS_CAPTURA, default='pendiente', verbose_name='Estado')
    documento_tipo = models.CharField(max_length=10, choices=TIPOS_DOCUMENTO, blank=True, default='',
                                      verbose_name='Tipo del documento registrado o vinculado')
    documento_id = models.PositiveBigIntegerField(null=True, blank=True, verbose_name='Id del documento')
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                   verbose_name='Guardado por')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Guardado el')
    completado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name='+', verbose_name='Completado, vinculado o descartado por')
    completado_en = models.DateTimeField(null=True, blank=True, verbose_name='Completado, vinculado o descartado el')
    motivo = models.CharField(max_length=MOTIVO_MAX, blank=True, default='', verbose_name='Motivo del descarte')

    class Meta:
        verbose_name = 'Recibo o nota por completar'
        verbose_name_plural = 'Recibos y notas por completar'
        ordering = ('-creado_en', '-id')
        default_permissions = ()
        permissions = (
            ('view_captura', 'Puede ver los recibos y notas por completar'),
            ('add_captura', 'Puede guardar recibos y notas para completar después'),
            ('change_captura', 'Puede completar, vincular o descartar recibos y notas'),
        )
        constraints = [models.UniqueConstraint(fields=['company', 'clave'], name='captura_clave_unica')]
        indexes = [models.Index(fields=['company', 'estado'], name='captura_por_estado')]

    def __str__(self):
        return f'Recibo C-{self.pk} ({self.get_estado_display()})'

    @property
    def extension(self):
        return FORMATOS.get(self.tipo_mime, 'bin') if self.archivo else ''


class Adjunto(TenantModel):
    documento_tipo = models.CharField(max_length=10, choices=TIPOS_DOCUMENTO, verbose_name='Tipo de documento')
    documento_id = models.PositiveBigIntegerField(verbose_name='Id del documento')
    clase = models.CharField(max_length=15, choices=CLASES_ADJUNTO, default='transferencia', verbose_name='Clase de comprobante')
    archivo = models.FileField(upload_to=RutaPrivada('comprobantes-pago'), max_length=255, blank=True, verbose_name='Archivo')
    nombre = models.CharField(max_length=150, blank=True, default='', verbose_name='Nombre original del archivo')
    tipo_mime = models.CharField(max_length=30, blank=True, default='', verbose_name='Tipo de contenido')
    tamano = models.PositiveIntegerField(default=0, verbose_name='Tamaño en bytes')
    sha256 = models.CharField(max_length=64, blank=True, default='', db_index=True, verbose_name='SHA-256 del contenido')
    referencia = models.CharField(max_length=100, blank=True, default='',
                                  verbose_name='Referencia (n.º de transferencia, cheque o comprobante)')
    fecha = models.DateField(null=True, blank=True, verbose_name='Fecha del comprobante')
    importe = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Importe del comprobante')
    descripcion = models.CharField(max_length=NOTA_MAX, blank=True, default='', verbose_name='Descripción o texto de la nota')
    captura = models.ForeignKey(Captura, null=True, blank=True, on_delete=models.PROTECT, related_name='adjuntos',
                                verbose_name='Recibo de origen')
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                   verbose_name='Subido por')
    subido_en = models.DateTimeField(default=timezone.now, verbose_name='Subido el')
    eliminado_en = models.DateTimeField(null=True, blank=True, verbose_name='Quitado el')
    eliminado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name='+', verbose_name='Quitado por')
    eliminado_motivo = models.CharField(max_length=MOTIVO_MAX, blank=True, default='', verbose_name='Motivo')

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
        return f'{self.get_clase_display()} · {self.nombre or self.descripcion[:40]}'

    @property
    def vigente(self):
        return self.eliminado_en is None

    @property
    def es_nota(self):
        return not self.archivo

    @property
    def extension(self):
        return FORMATOS.get(self.tipo_mime, 'bin') if self.archivo else ''
