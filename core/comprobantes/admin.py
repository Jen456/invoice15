"""Catálogo de retenciones en el panel de la plataforma (los porcentajes cambian por resolución del SRI)."""
from django.contrib import admin

from core.comprobantes.models import CodigoRetencion
from core.tenancy.admin import plataforma


@admin.register(CodigoRetencion, site=plataforma)
class CodigoRetencionAdmin(admin.ModelAdmin):
    list_display = ('impuesto', 'codigo', 'concepto', 'porcentaje', 'porcentaje_editable', 'comun', 'activo')
    list_filter = ('impuesto', 'activo', 'comun')
    list_editable = ('porcentaje', 'activo', 'comun')
    search_fields = ('codigo', 'concepto')

    def has_delete_permission(self, request, obj=None):
        return False   # se desactiva (activo = no) para conservar el histórico de lo ya emitido
