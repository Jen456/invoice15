import json

from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import FormView, DeleteView

from core.pos.models import VoucherErrors
from core.reports.forms import ReportForm
from core.security.mixins import GroupPermissionMixin


class VoucherErrorsListView(GroupPermissionMixin, FormView):
    template_name = 'voucher_errors/list.html'
    form_class = ReportForm
    permission_required = 'view_voucher_errors'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                start_date = request.POST['start_date']
                end_date = request.POST['end_date']
                receipt = request.POST['receipt']
                queryset = VoucherErrors.objects.filter()
                if len(start_date) and len(end_date):
                    queryset = queryset.filter(date_joined__range=[start_date, end_date])
                if len(receipt):
                    queryset = queryset.filter(receipt_id=receipt)
                for i in queryset:
                    data.append(i.toJSON())
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Errores de los Comprobantes'
        return context


class VoucherErrorsDeleteView(GroupPermissionMixin, DeleteView):
    model = VoucherErrors
    template_name = 'delete.html'
    success_url = reverse_lazy('voucher_errors_list')
    permission_required = 'delete_voucher_errors'

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
