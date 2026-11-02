from django.contrib import admin

from core.adjuntos.models import Adjunto, Captura
from core.tenancy.admin import plataforma


class SoloLectura(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Adjunto, site=plataforma)
class AdjuntoAdmin(SoloLectura):
    list_display = ('id', 'company', 'documento_tipo', 'documento_id', 'clase', 'nombre', 'tamano', 'captura', 'subido_por', 'subido_en',
                    'eliminado_en')
    list_filter = ('documento_tipo', 'clase')
    search_fields = ('nombre', 'sha256', 'referencia')
    readonly_fields = [f.name for f in Adjunto._meta.fields]

    def get_queryset(self, request):
        return Adjunto.all_companies.select_related('company', 'subido_por')


@admin.register(Captura, site=plataforma)
class CapturaAdmin(SoloLectura):
    list_display = ('id', 'company', 'estado', 'nombre', 'tamano', 'documento_tipo', 'documento_id', 'creado_por', 'creado_en')
    list_filter = ('estado',)
    search_fields = ('nombre', 'sha256', 'clave')
    readonly_fields = [f.name for f in Captura._meta.fields]

    def get_queryset(self, request):
        return Captura.all_companies.select_related('company', 'creado_por')
