"""Kardex con costo promedio ponderado (entrega F, la parte que no depende de D5, D6 ni D7; D3 decidido: «automático
con datos completos y completable a mano»).

El kardex se calcula desde los documentos (core/contabilidad/kardex.py). Aquí solo se guarda lo que no está en ningún
documento: los ajustes de stock (antes sobrescribían el número sin dejar rastro) y los movimientos manuales con los que el
contador completa lo que no se registró en el sistema (saldo inicial, entradas y salidas con su documento de respaldo).
Los movimientos manuales no cambian el stock del producto: explican su historia."""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.tenancy.models_base import TenantModel

TIPOS_MANUALES = (('saldo_inicial', 'Saldo inicial'), ('entrada', 'Entrada manual'), ('salida', 'Salida manual'))
CON_COSTO = ('saldo_inicial', 'entrada')
ORIGENES_AJUSTE = (('ajuste', 'Ajuste de stock'), ('importacion', 'Importación de productos desde Excel'))
DOCUMENTO_MAX, NOTA_MAX, MOTIVO_MAX = 120, 300, 300


class MovimientoManual(TenantModel):
    clave = models.CharField(max_length=40, verbose_name='Clave del envío')
    producto = models.ForeignKey('pos.Product', on_delete=models.PROTECT, related_name='+', verbose_name='Producto')
    tipo = models.CharField(max_length=14, choices=TIPOS_MANUALES, verbose_name='Tipo')
    fecha = models.DateField(verbose_name='Fecha')
    cantidad = models.PositiveIntegerField(verbose_name='Cantidad')
    costo_unitario = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True, verbose_name='Costo unitario')
    documento = models.CharField(max_length=DOCUMENTO_MAX, verbose_name='Documento de respaldo')
    nota = models.CharField(max_length=NOTA_MAX, blank=True, default='', verbose_name='Nota')
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                   verbose_name='Registrado por')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Registrado el')
    anulado_en = models.DateTimeField(null=True, blank=True, verbose_name='Anulado el')
    anulado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                    verbose_name='Anulado por')
    motivo_anulacion = models.CharField(max_length=MOTIVO_MAX, blank=True, default='', verbose_name='Motivo de la anulación')

    class Meta:
        verbose_name = 'Movimiento manual del kardex'
        verbose_name_plural = 'Movimientos manuales del kardex'
        ordering = ('fecha', 'id')
        default_permissions = ('add', 'change')
        permissions = (('view_kardex', 'Puede ver el kardex y el inventario valorizado'),)
        constraints = [
            models.UniqueConstraint(fields=('company', 'clave'), name='kardex_movimiento_clave_unica'),
            models.CheckConstraint(condition=Q(cantidad__gt=0), name='kardex_movimiento_cantidad_positiva'),
            models.CheckConstraint(condition=(Q(tipo__in=CON_COSTO, costo_unitario__isnull=False, costo_unitario__gte=0)
                                              | Q(tipo='salida', costo_unitario__isnull=True)),
                                   name='kardex_movimiento_costo_segun_tipo'),
        ]
        indexes = [models.Index(fields=('company', 'producto', 'fecha'), name='kardex_movimiento_producto')]

    def __str__(self):
        return f'{self.get_tipo_display()} {self.cantidad} × {self.producto_id} ({self.fecha:%d/%m/%Y})'


class AjusteInventario(TenantModel):
    producto = models.ForeignKey('pos.Product', on_delete=models.PROTECT, related_name='+', verbose_name='Producto')
    fecha = models.DateField(default=timezone.localdate, verbose_name='Fecha')
    anterior = models.IntegerField(verbose_name='Stock anterior')
    nuevo = models.IntegerField(verbose_name='Stock nuevo')
    origen = models.CharField(max_length=12, choices=ORIGENES_AJUSTE, default='ajuste', verbose_name='Origen')
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                   verbose_name='Registrado por')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Registrado el')

    class Meta:
        verbose_name = 'Ajuste de stock'
        verbose_name_plural = 'Ajustes de stock'
        ordering = ('fecha', 'id')
        default_permissions = ()
        indexes = [models.Index(fields=('company', 'producto', 'fecha'), name='kardex_ajuste_producto')]

    @property
    def diferencia(self):
        return self.nuevo - self.anterior

    def __str__(self):
        return f'Ajuste {self.anterior} → {self.nuevo} de {self.producto_id} ({self.fecha:%d/%m/%Y})'
