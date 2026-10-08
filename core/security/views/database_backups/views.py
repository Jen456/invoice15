import json

from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import DeleteView, TemplateView, FormView

from core.reports.forms import ReportForm
from core.security.mixins import GroupPermissionMixin
from core.security.models import DatabaseBackups


class DatabaseBackupsListView(GroupPermissionMixin, FormView):
    template_name = 'database_backups/list.html'
    form_class = ReportForm
    permission_required = 'view_database_backups'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                queryset = DatabaseBackups.objects.filter()
                start_date = request.POST['start_date']
                end_date = request.POST['end_date']
                if len(start_date) and len(end_date):
                    queryset = queryset.filter(date_joined__range=[start_date, end_date])
                for i in queryset:
                    data.append(i.toJSON())
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de respaldos de la base de datos'
        context['create_url'] = reverse_lazy('database_backups_create')
        return context


class DatabaseBackupsCreateView(GroupPermissionMixin, TemplateView):
    """Desactivado: los respaldos los hace el servidor (respaldo de Hestia y copia
    nocturna cifrada). El volcado desde la aplicación ejecutaba órdenes de shell y
    dejaba la base completa dentro de los archivos subidos."""
    template_name = 'database_backups/create.html'
    success_url = reverse_lazy('database_backups_list')
    permission_required = 'add_database_backups'

    def post(self, request, *args, **kwargs):
        data = {'error': 'Los respaldos de la base de datos los realiza el servidor automáticamente cada noche.'}
        return HttpResponse(json.dumps(data), content_type='application/json')


class DatabaseBackupsDeleteView(GroupPermissionMixin, DeleteView):
    model = DatabaseBackups
    template_name = 'delete.html'
    success_url = reverse_lazy('database_backups_list')
    permission_required = 'delete_database_backups'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            self.get_object().delete()
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Notificación de eliminación'
        context['list_url'] = self.success_url
        return context
