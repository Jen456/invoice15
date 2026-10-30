import json

from django.http import HttpResponse
from django.views.generic import FormView

from core.pos import compras
from core.pos.models import Purchase
from core.reports.forms import ReportForm
from core.security.mixins import GroupModuleMixin


class PurchaseReportView(GroupModuleMixin, FormView):
    """Reporte de compras con los datos del comprobante (espec-etapa2-compras §6.I). El pie separa el total con IVA de las
    compras completas (las notas de crédito del proveedor restan) del subtotal registrado de las incompletas
    (compras.totales_listado, con subtotal_con_signo)."""
    template_name = 'purchase_report/report.html'
    form_class = ReportForm

    def compras_filtradas(self):
        post = self.request.POST
        return compras.filtrar_listado(Purchase.objects.select_related('provider'), inicio=post.get('start_date', ''),
                                       fin=post.get('end_date', ''), fecha=post.get('fecha') or 'registro')

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', '')
        data = {}
        try:
            if action == 'search_report':
                data = [compra.toJSON() for compra in self.compras_filtradas().order_by('date_joined', 'id')]
            elif action == 'totales':
                data = compras.totales_listado(self.compras_filtradas())
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data = {'error': str(e)}
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Reporte de Compras'
        return context
