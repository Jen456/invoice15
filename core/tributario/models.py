"""Libros mensuales (entrega B; después, revisión del mes, ATS y hojas del 104/103): se calculan desde los documentos, no
se guardan. Aquí solo queda el registro de cada exportación: qué libro y mes, en qué formato, cuántas filas, sus totales y
la huella del archivo entregado, con quién y cuándo (trazabilidad de lo que se pasó al contador)."""
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone

from core.tenancy.models_base import TenantModel


class ExportacionLibro(TenantModel):
    LIBROS = (('ventas', 'Libro de ventas'), ('compras', 'Libro de compras'), ('retenciones_efectuadas', 'Retenciones efectuadas'),
              ('retenciones_recibidas', 'Retenciones recibidas'), ('todos', 'Los cuatro libros'), ('ats', 'ATS del mes'),
              ('f104', 'Borrador del 104'), ('f103', 'Borrador del 103'))
    FORMATOS = (('xlsx', 'XLSX'), ('csv', 'CSV'), ('zip', 'ZIP'))
    libro = models.CharField(max_length=25, choices=LIBROS, verbose_name='Libro')
    mes = models.DateField(verbose_name='Mes (primer día)')
    formato = models.CharField(max_length=4, choices=FORMATOS, verbose_name='Formato')
    filas = models.PositiveIntegerField(default=0, verbose_name='Filas')
    totales = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder, verbose_name='Totales')
    sha256 = models.CharField(max_length=64, verbose_name='SHA-256 del archivo')
    generado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                     verbose_name='Generado por')
    generado_en = models.DateTimeField(default=timezone.now, verbose_name='Generado el')

    class Meta:
        verbose_name = 'Exportación de un libro mensual'
        verbose_name_plural = 'Exportaciones de libros mensuales'
        ordering = ('-generado_en', '-id')
        default_permissions = ()
        permissions = (('view_libros', 'Puede ver y exportar los libros mensuales'),
                       ('view_revision', 'Puede ver la revisión del mes y el resumen de sus empresas'))

    def __str__(self):
        return f'{self.get_libro_display()} {self.mes:%Y-%m} ({self.formato})'
