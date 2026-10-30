import json

from django.http import HttpResponse
from django.views.generic import FormView

from core.pos import consultas
from core.reports.forms import ReportForm
from core.security.mixins import GroupModuleMixin


class SaleReportView(GroupModuleMixin, FormView):
    template_name = 'sale_report/report.html'
    form_class = ReportForm

    def post(self, request, *args, **kwargs):
        action = request.POST['action']
        data = {}
        try:
            if action == 'search_report':
                # Etapa 2 (O2): alcance (por defecto, autorizadas en producción por fecha de emisión); 'todos' = como antes.
                data = []
                start_date = request.POST['start_date']
                end_date = request.POST['end_date']
                alcance = request.POST.get('alcance') or 'declarables'
                queryset = consultas.ventas(alcance, start_date or None, end_date or None)
                for i in queryset.select_related('company', 'client__user', 'receipt__emission_point__establishment', 'employee'):
                    item = i.toJSON()
                    fecha = getattr(i, 'fecha_efectiva', None) or i.emission_date or i.authorization_date or i.date_joined
                    item['fecha_emision_efectiva'] = fecha.strftime('%Y-%m-%d')
                    item['fecha_emision_origen'] = consultas.origen_fecha(i)
                    data.append(item)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data = {'error': str(e)}   # data puede ser ya una lista (antes fallaba con TypeError)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Reporte de Ventas'
        return context
