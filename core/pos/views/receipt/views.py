import json

from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView, TemplateView

from core.pos.forms import Receipt, ReceiptForm
from core.security.mixins import GroupPermissionMixin


class ReceiptListView(GroupPermissionMixin, TemplateView):
    template_name = 'receipt/list.html'
    permission_required = 'view_receipt'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                for i in Receipt.objects.filter():
                    data.append(i.toJSON())
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Comprobantes'
        context['create_url'] = reverse_lazy('receipt_create')
        return context


class ReceiptCreateView(GroupPermissionMixin, CreateView):
    model = Receipt
    template_name = 'receipt/create.html'
    form_class = ReceiptForm
    success_url = reverse_lazy('receipt_list')
    permission_required = 'add_receipt'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'add':
                data = self.get_form().save()
            elif action == 'validate_data':
                data = {'valid': True}
                queryset = Receipt.objects.all()
                voucher_type = request.POST['voucher_type']
                establishment_code = request.POST['establishment_code']
                issuing_point_code = request.POST['issuing_point_code']
                if len(voucher_type) and len(issuing_point_code) and len(establishment_code):
                    data['valid'] = not queryset.filter(voucher_type=voucher_type, establishment_code=establishment_code, issuing_point_code=issuing_point_code).exists()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Nuevo registro de un Comprobante'
        context['list_url'] = self.success_url
        context['action'] = 'add'
        return context


class ReceiptUpdateView(GroupPermissionMixin, UpdateView):
    model = Receipt
    template_name = 'receipt/create.html'
    form_class = ReceiptForm
    success_url = reverse_lazy('receipt_list')
    permission_required = 'change_receipt'

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'edit':
                data = self.get_form().save()
            elif action == 'validate_data':
                data = {'valid': True}
                queryset = Receipt.objects.all().exclude(id=self.object.id)
                voucher_type = request.POST['voucher_type']
                establishment_code = request.POST['establishment_code']
                issuing_point_code = request.POST['issuing_point_code']
                if len(voucher_type) and len(issuing_point_code) and len(establishment_code):
                    data['valid'] = not queryset.filter(voucher_type=voucher_type, establishment_code=establishment_code, issuing_point_code=issuing_point_code).exists()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Edición de un Comprobante'
        context['list_url'] = self.success_url
        context['action'] = 'edit'
        return context


class ReceiptDeleteView(GroupPermissionMixin, DeleteView):
    model = Receipt
    template_name = 'delete.html'
    success_url = reverse_lazy('receipt_list')
    permission_required = 'delete_receipt'

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
