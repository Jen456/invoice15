"""Respaldo del cobro: comprobante adjunto (PDF, JPG o PNG) o nota interna de quien cobró, con revisión aparte.

- Un respaldo pertenece a una factura y, si la factura es a crédito, al abono (PaymentsCtaCollect) que registró ese cobro;
  al contado, respalda el cobro de la propia factura (origen 'contado'). Importe, medio y referencia del cobro quedan
  aquí; el abono conserva los suyos (description, medio_pago, referencia, registrado_por, registrado_en).
- La condición de pago de la factura (Sale.payment_type: contado 'efectivo' / 'credito', valores históricos) es otra
  cosa que el medio con que se cobró (Sale.medio_cobro y RespaldoCobro.medio: MEDIOS_DE_PAGO). «Efectivo recibido» y
  «Cambio» solo existen cuando el medio es efectivo.
- Autor, empresa y fecha salen del servidor. La revisión (pendiente / revisado / rechazado, con responsable, fecha y
  motivo) no cambia el saldo de la factura: el saldo lo mueven los abonos (core/pos/cxc.py); adjuntar un archivo no
  confirma un pago ni genera otro abono.
- Nota y archivo son internos: no entran en additional_info, XML, RIDE ni correos. El archivo se guarda bajo privado/
  (la entrega general de MEDIA no lo sirve) y solo sale por la vista de descarga con permiso y empresa activa.
- Cada cambio (nota, archivo, referencia, revisión, cobro eliminado) deja una fila en RespaldoCobroCambio con lo
  anterior; el archivo reemplazado no se borra.
- `clave` (la genera el navegador por formulario) hace idempotente el registro: un doble clic, un reintento o una
  respuesta perdida devuelven el mismo respaldo (y el mismo abono) en vez de duplicarlos.
"""
import os
import uuid

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone
from django.utils.deconstruct import deconstructible

from core.pos.choices import MEDIOS_DE_PAGO
from core.tenancy.context import require_company
from core.tenancy.models_base import TenantModel

CARPETA_PRIVADA = 'privado'
ESTADOS = (('pendiente', 'Pendiente de revisión'), ('revisado', 'Revisado'), ('rechazado', 'Rechazado'))
ORIGENES = (('contado', 'Cobro al contado (al emitir la factura)'), ('abono', 'Abono a la cuenta por cobrar'))
ACCIONES_CAMBIO = (('registro', 'Registro'), ('nota', 'Cambio de la nota'), ('archivo', 'Cambio del archivo'),
                   ('referencia', 'Cambio de la referencia'), ('revision', 'Revisión'), ('cobro_eliminado', 'Cobro eliminado'))


@deconstructible
class RutaPrivadaCobro:
    """privado/empresas/<uuid de la empresa>/cobros/<año>/<mes>/<aleatorio>.<ext>: la entrega general de archivos
    (core.security.views.files) no sirve nada bajo «privado/»; estos archivos solo salen por core/cobros/views.py."""

    def __call__(self, instance, filename):
        extension = os.path.splitext(filename)[1].lower()[:10]
        company = instance.company if instance.company_id else require_company()   # antes del primer save()
        return (f'{CARPETA_PRIVADA}/empresas/{company.uuid}/cobros/{timezone.now():%Y/%m}/'
                f'{uuid.uuid4().hex}{extension}')

    def __eq__(self, other):
        return isinstance(other, RutaPrivadaCobro)


class RespaldoCobro(TenantModel):
    sale = models.ForeignKey('pos.Sale', on_delete=models.PROTECT, related_name='respaldos_cobro', verbose_name='Factura')
    abono = models.ForeignKey('pos.PaymentsCtaCollect', null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='respaldos', verbose_name='Abono')
    origen = models.CharField(max_length=10, choices=ORIGENES, verbose_name='Origen del cobro')
    clave = models.CharField(max_length=40, verbose_name='Clave del envío (idempotencia)')
    importe = models.DecimalField(max_digits=9, decimal_places=2, verbose_name='Importe cobrado')
    medio = models.CharField(max_length=15, choices=MEDIOS_DE_PAGO, verbose_name='Medio de cobro')
    referencia = models.CharField(max_length=100, blank=True, default='', verbose_name='Referencia')
    nota = models.TextField(blank=True, default='', verbose_name='Nota interna')
    archivo = models.FileField(upload_to=RutaPrivadaCobro(), max_length=255, null=True, blank=True, verbose_name='Comprobante')
    archivo_nombre = models.CharField(max_length=150, blank=True, default='', verbose_name='Nombre original del archivo')
    archivo_tipo = models.CharField(max_length=5, blank=True, default='', verbose_name='Tipo (pdf, jpg, png)')
    archivo_bytes = models.PositiveIntegerField(default=0, verbose_name='Tamaño en bytes')
    archivo_sha256 = models.CharField(max_length=64, blank=True, default='', verbose_name='SHA-256 del archivo')
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name='+', verbose_name='Registrado por')
    registrado_en = models.DateTimeField(default=timezone.now, editable=False, verbose_name='Registrado el')
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name='Última modificación')
    estado = models.CharField(max_length=10, choices=ESTADOS, default='pendiente', verbose_name='Revisión')
    revisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='+', verbose_name='Revisado por')
    revisado_en = models.DateTimeField(null=True, blank=True, verbose_name='Revisado el')
    motivo_revision = models.CharField(max_length=300, blank=True, default='', verbose_name='Motivo de la revisión')

    class Meta:
        verbose_name = 'Respaldo de cobro'
        verbose_name_plural = 'Respaldos de cobro'
        ordering = ('-registrado_en', '-id')
        constraints = [models.UniqueConstraint(fields=['company', 'clave'], name='respaldo_cobro_clave_unica')]
        default_permissions = ('view', 'add', 'change')
        permissions = (('change_revision_respaldocobro', 'Can review Respaldo de cobro'),)

    def __str__(self):
        return f'Respaldo {self.pk} de {self.sale.voucher_number_full} ({self.get_estado_display()})'

    @property
    def tiene_archivo(self):
        return bool(self.archivo)


class RespaldoCobroCambio(TenantModel):
    respaldo = models.ForeignKey(RespaldoCobro, on_delete=models.CASCADE, related_name='cambios', verbose_name='Respaldo')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+', verbose_name='Usuario')
    fecha = models.DateTimeField(default=timezone.now, editable=False, verbose_name='Fecha')
    accion = models.CharField(max_length=20, choices=ACCIONES_CAMBIO, verbose_name='Acción')
    detalle = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder, verbose_name='Detalle (antes y después)')

    class Meta:
        verbose_name = 'Cambio de un respaldo de cobro'
        verbose_name_plural = 'Cambios de respaldos de cobro'
        ordering = ('fecha', 'id')
        default_permissions = ()

    def __str__(self):
        return f'{self.get_accion_display()} · respaldo {self.respaldo_id} · {self.fecha:%Y-%m-%d %H:%M}'
