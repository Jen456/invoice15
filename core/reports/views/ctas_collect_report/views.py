import json

from django.http import HttpResponse
from django.views.generic import FormView

from core.pos import consultas
from core.reports.forms import ReportForm
from core.security.mixins import GroupModuleMixin


class CtasCollectReportView(GroupModuleMixin, FormView):
    template_name = 'ctas_collect_report/report.html'
    form_class = ReportForm

    def post(self, request, *args, **kwargs):
        action = request.POST['action']
        data = {}
        try:
            if action == 'search_report':
                # Etapa 2 (O2): alcance según el documento de cada CxC (la factura o la nota de débito); 'todos' = como antes.
                data = []
                start_date = request.POST['start_date']
                end_date = request.POST['end_date']
                alcance = request.POST.get('alcance') or 'declarables'
                for i in consultas.cuentas_por_cobrar(alcance, start_date or None, end_date or None):
                    item = i.toJSON()
                    fecha = getattr(i, 'fecha_efectiva', None)
                    if fecha is None:   # alcance 'todos': la de la nota de débito es la fecha de su CxC
                        venta = i.sale
                        fecha = i.date_joined if i.nd_id else (venta.emission_date or venta.authorization_date
                                                                or venta.date_joined)
                    item['fecha_emision_efectiva'] = fecha.strftime('%Y-%m-%d')
                    data.append(item)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data = {'error': str(e)}   # data puede ser ya una lista (antes fallaba con TypeError)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Reporte de Cuentas por Cobrar'
        return context
