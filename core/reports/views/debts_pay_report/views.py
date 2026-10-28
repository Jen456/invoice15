import json

from django.http import HttpResponse
from django.views.generic import FormView

from core.pos.models import DebtsPay
from core.reports.forms import ReportForm
from core.security.mixins import GroupModuleMixin


class DebtsPayReportView(GroupModuleMixin, FormView):
    """Reporte de cuentas por pagar con su base de cálculo, lo pagado, lo abonado (retenciones y notas de crédito) y el
    saldo. Sin consultas por fila: pagado anotado (DebtsPay.con_pagado) y select_related del proveedor."""
    template_name = 'debts_pay_report/report.html'
    form_class = ReportForm

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', '')
        data = {}
        try:
            if action == 'search_report':
                start_date = request.POST.get('start_date', '')
                end_date = request.POST.get('end_date', '')
                queryset = DebtsPay.con_pagado(DebtsPay.objects.select_related('purchase__provider'))
                if len(start_date) and len(end_date):
                    queryset = queryset.filter(date_joined__range=[start_date, end_date])
                data = [deuda.toJSON() for deuda in queryset.order_by('date_joined', 'id')]
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data = {'error': str(e)}
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Reporte de Cuentas por Pagar'
        return context
