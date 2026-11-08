"""Puntos de emisión por usuario: desde qué puntos puede emitir cada usuario en la empresa y desde cuál emite ahora.

Reutiliza Establishment, EmissionPoint y Receipt (core/pos/models.py); aquí solo se guarda la relación con el usuario.
- PuntoAutorizado: puntos desde los que un usuario puede emitir. Sin filas para un usuario en la empresa, puede usar
  todos los puntos activos (como hasta ahora, cuando todos emitían desde el punto predeterminado); Propietario y
  Administrador usan todos siempre.
- PuntoSeleccionado: preferencia por usuario y empresa. Cambiarla no mueve el punto predeterminado de la empresa ni la
  selección de otros usuarios, y un formulario ya abierto conserva el punto con el que se abrió (lo envía en `punto` y
  el servidor lo vuelve a validar al emitir). Reglas en core/configuracion/puntos.py.

Diseño de factura (piloto, core/configuracion/diseno.py):
- DisenoFactura: estilo y colores del RIDE de factura de la empresa, uno por empresa. Sin fila = sin personalización (RIDE
  original). Solo cambia la presentación de las facturas NUEVAS: al firmarse por primera vez, cada factura guarda su copia
  (Sale.ride_diseno) y el RIDE se arma siempre desde esa copia.
"""
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from core.comprobantes import ride_styles
from core.pos.models import EmissionPoint
from core.tenancy.models_base import TenantModel


class PuntoAutorizado(TenantModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='puntos_autorizados',
                             verbose_name='Usuario')
    emission_point = models.ForeignKey(EmissionPoint, on_delete=models.CASCADE, related_name='autorizaciones',
                                       verbose_name='Punto de emisión')
    created_at = models.DateTimeField(default=timezone.now, editable=False, verbose_name='Autorizado el')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name='Autorizado por')

    class Meta:
        verbose_name = 'Punto de emisión autorizado'
        verbose_name_plural = 'Puntos de emisión autorizados'
        ordering = ('emission_point__establishment__code', 'emission_point__code')
        constraints = [models.UniqueConstraint(fields=['user', 'emission_point'], name='punto_autorizado_unico')]

    def __str__(self):
        return f'{self.user} → {self.emission_point}'


class PuntoSeleccionado(TenantModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='puntos_seleccionados',
                             verbose_name='Usuario')
    emission_point = models.ForeignKey(EmissionPoint, on_delete=models.CASCADE, related_name='selecciones',
                                       verbose_name='Punto de emisión')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Elegido el')

    class Meta:
        verbose_name = 'Punto de emisión elegido'
        verbose_name_plural = 'Puntos de emisión elegidos'
        constraints = [models.UniqueConstraint(fields=['company', 'user'], name='una_seleccion_por_usuario_y_empresa')]

    def __str__(self):
        return f'{self.user} emite desde {self.emission_point}'


COLOR_HEX = RegexValidator(r'^#[0-9A-F]{6}\Z', 'Escribe el color en formato #RRGGBB (seis dígitos hexadecimales).')


class DisenoFactura(TenantModel):
    estilo = models.CharField(max_length=20, choices=ride_styles.choices(), verbose_name='Estilo')
    color_principal = models.CharField(max_length=7, validators=[COLOR_HEX], verbose_name='Color principal')
    color_secundario = models.CharField(max_length=7, validators=[COLOR_HEX], verbose_name='Color secundario')
    version = models.PositiveSmallIntegerField(default=1, verbose_name='Versión del estilo')
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                        related_name='+', verbose_name='Actualizado por')
    actualizado_en = models.DateTimeField(auto_now=True, verbose_name='Actualizado el')

    class Meta:
        verbose_name = 'Diseño de factura'
        verbose_name_plural = 'Diseños de factura'
        constraints = [models.UniqueConstraint(fields=['company'], name='un_diseno_factura_por_empresa')]

    def __str__(self):
        return f'{self.get_estilo_display()} {self.color_principal}/{self.color_secundario}'
