import json

from django.http import HttpResponse
from django.views.generic import FormView

from core.pos.models import Expenses
from core.reports.forms import ReportForm
from core.security.mixins import GroupModuleMixin


class ExpensesReportView(GroupModuleMixin, FormView):
    """Reporte de gastos sin comprobante, con su medio de pago («Sin dato» en los anteriores) y referencia."""
    template_name = 'expenses_report/report.html'
    form_class = ReportForm

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', '')
        data = {}
        try:
            if action == 'search_report':
                start_date = request.POST.get('start_date', '')
                end_date = request.POST.get('end_date', '')
                queryset = Expenses.objects.select_related('type_expense')
                if len(start_date) and len(end_date):
                    queryset = queryset.filter(date_joined__range=[start_date, end_date])
                data = [gasto.toJSON() for gasto in queryset.order_by('date_joined', 'id')]
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data = {'error': str(e)}
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Reporte de Gastos'
        return context
