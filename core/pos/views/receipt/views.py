"""Comprobantes: consulta de las secuencias. Se configuran solo en el asistente (/configuracion/facturacion/)."""
import json

from django.contrib import messages
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView, TemplateView

from core.pos.forms import Receipt, ReceiptForm
from core.security.mixins import GroupPermissionMixin

AVISO_ASISTENTE = ('La numeración de comprobantes se configura en «Configuración de facturación» (paso 3), '
                   'para que establecimiento, punto de emisión, ambiente y secuencias no se contradigan.')


class SoloAsistenteMixin:
    """Crear, editar o borrar secuencias desde aquí podría reiniciarlas o duplicarlas: se redirige al asistente."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if request.method == 'GET':
            messages.warning(request, AVISO_ASISTENTE, extra_tags='configuracion')
            return HttpResponseRedirect('/configuracion/facturacion/paso/3/')
        return JsonResponse({'error': AVISO_ASISTENTE}, status=403)


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
        context['config_url'] = '/configuracion/facturacion/paso/3/'
        return context


class ReceiptCreateView(SoloAsistenteMixin, GroupPermissionMixin, CreateView):
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


class ReceiptUpdateView(SoloAsistenteMixin, GroupPermissionMixin, UpdateView):
    model = Receipt
    template_name = 'receipt/create.html'
    form_class = ReceiptForm
    success_url = reverse_lazy('receipt_list')
    permission_required = 'change_receipt'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:   # sin sesión, el mixin lleva al login (antes: error 500)
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


class ReceiptDeleteView(SoloAsistenteMixin, GroupPermissionMixin, DeleteView):
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
