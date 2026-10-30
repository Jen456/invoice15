from django.contrib import admin

from core.adjuntos.models import Adjunto
from core.tenancy.admin import plataforma


@admin.register(Adjunto, site=plataforma)
class AdjuntoAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'documento_tipo', 'documento_id', 'clase', 'nombre', 'tamano', 'subido_por', 'subido_en', 'eliminado_en')
    list_filter = ('documento_tipo', 'clase')
    search_fields = ('nombre', 'sha256', 'referencia')
    readonly_fields = [f.name for f in Adjunto._meta.fields]

    def get_queryset(self, request):
        return Adjunto.all_companies.select_related('company', 'subido_por')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
