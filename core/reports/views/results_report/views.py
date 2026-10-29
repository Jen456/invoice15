import json

from django.db.models import Sum, FloatField
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.views.generic import FormView

from core.pos import consultas
from core.pos.models import Purchase, Sale, Expenses
from core.reports.forms import ReportForm
from core.security.mixins import GroupModuleMixin


def ventas_menos_notas(alcance, desde, hasta):
    """«Ventas» de Resultados (Etapa 2, O2): Σ total de las facturas del alcance − Σ total de sus notas de crédito del
    mismo alcance. Una factura cubierta por NC ('canceled') ya no infla las ventas. En Decimal; float solo para el JSON."""
    from decimal import Decimal
    ventas = consultas.ventas(alcance, desde, hasta).order_by().aggregate(total=Sum('total'))['total'] or Decimal('0')
    notas = consultas.notas_credito(alcance, desde, hasta).order_by().aggregate(total=Sum('total'))['total'] or Decimal('0')
    return float(Decimal(ventas) - Decimal(notas))


class ResultsReportView(GroupModuleMixin, FormView):
    template_name = 'results_report/report.html'
    form_class = ReportForm

    def post(self, request, *args, **kwargs):
        action = request.POST['action']
        data = {}
        try:
            if action == 'search_report':
                data = []
                start_date = request.POST['start_date']
                end_date = request.POST['end_date']
                alcance = request.POST.get('alcance') or 'declarables'   # Etapa 2 (O2)
                if alcance not in dict(consultas.ALCANCES):
                    raise ValueError(consultas.MENSAJE_ALCANCE)

                purchase = Purchase.objects.all()
                if len(start_date) and len(end_date):
                    purchase = purchase.filter(date_joined__range=[start_date, end_date])
                purchase = float(purchase.aggregate(result=Coalesce(Sum('subtotal'), 0.00, output_field=FloatField()))['result'])

                if alcance == 'todos':
                    sale = Sale.objects.all()
                    if len(start_date) and len(end_date):
                        sale = sale.filter(date_joined__range=[start_date, end_date])
                    sale = float(sale.aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField()))['result'])
                else:
                    # Etapa 2 (O2): facturas del alcance menos sus notas de crédito (por la fecha efectiva de cada una).
                    sale = ventas_menos_notas(alcance, start_date or None, end_date or None)

                expenses = Expenses.objects.all()
                if len(start_date) and len(end_date):
                    expenses = expenses.filter(date_joined__range=[start_date, end_date])
                expenses = float(expenses.aggregate(result=Coalesce(Sum('valor'), 0.00, output_field=FloatField()))['result'])

                data.append({'name': 'Compras', 'y': purchase})
                data.append({'name': 'Ventas', 'y': sale})
                data.append({'name': 'Gastos', 'y': expenses})
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data = {'error': str(e)}   # data puede ser ya una lista (antes fallaba con TypeError)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Reporte de Resultados'
        return context
