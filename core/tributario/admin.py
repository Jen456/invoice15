from django.contrib import admin

from core.tenancy.admin import plataforma
from core.tributario.models import ExportacionLibro


@admin.register(ExportacionLibro, site=plataforma)
class ExportacionLibroAdmin(admin.ModelAdmin):
    list_display = ('id', 'company', 'libro', 'mes', 'formato', 'filas', 'generado_por', 'generado_en')
    list_filter = ('libro', 'formato')
    readonly_fields = [f.name for f in ExportacionLibro._meta.fields]

    def get_queryset(self, request):
        return ExportacionLibro.all_companies.select_related('company', 'generado_por')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
