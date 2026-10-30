import json

from django.contrib import messages

from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseRedirect, HttpResponse
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, FormView

from core.pos.forms import CreditNoteForm, CreditNote, CreditNoteDetail, Company, Sale, Receipt, SaleDetail, VOUCHER_TYPE, INVOICE_STATUS, IDENTIFICATION_TYPE
from core.configuracion.servicios import receipt_para_emitir, requisitos_de_emision
from core.pos import emision
from core.pos.notas_credito import AUTORIZADOS, acreditado_por_detalle, crear as crear_nota_credito
from core.pos.utilities.sri import SRI
from core.reports.forms import ReportForm
from core.security.mixins import GroupPermissionMixin


class CreditNoteListView(GroupPermissionMixin, FormView):
    template_name = 'credit_note/admin/list.html'
    form_class = ReportForm
    permission_required = 'view_credit_note'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                start_date = request.POST['start_date']
                end_date = request.POST['end_date']
                queryset = CreditNote.objects.filter()
                if len(start_date) and len(end_date):
                    queryset = queryset.filter(date_joined__range=[start_date, end_date])
                for i in queryset:
                    data.append(i.toJSON())
            elif action == 'search_detail_products':
                data = []
                for i in CreditNoteDetail.objects.filter(credit_note_id=request.POST['id']):
                    data.append(i.toJSON())
            elif action == 'generate_invoice':
                credit_note = CreditNote.objects.get(pk=request.POST['id'])
                data = credit_note.generate_electronic_invoice()
            elif action == 'send_invoice_by_email':
                credit_note = CreditNote.objects.get(pk=request.POST['id'])
                xml_electronic_signature = SRI()
                data = xml_electronic_signature.notify_by_email(instance=credit_note, company=credit_note.company, client=credit_note.sale.client)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Notas de Credito'
        context['create_url'] = reverse_lazy('credit_note_admin_create')
        return context


class CreditNoteCreateView(GroupPermissionMixin, CreateView):
    model = CreditNote
    template_name = 'credit_note/admin/create.html'
    form_class = CreditNoteForm
    success_url = reverse_lazy('credit_note_admin_list')
    permission_required = 'add_credit_note'

    def post(self, request, *args, **kwargs):
        action = request.POST['action']
        data = {}
        try:
            if action == 'add':
                # Reglas en el servidor (core/pos/notas_credito.py): cantidades, precios y tarifa salen de la factura.
                lineas = [(i['id'], i['quantity']) for i in json.loads(request.POST['products'])]
                with transaction.atomic():
                    credit_note = crear_nota_credito(request.company, request.POST['sale'], lineas, request.POST.get('motive'))
                    emision.preparar(credit_note)   # si la firma falla, la nota se deshace: nada salió al SRI
                data = credit_note.generate_electronic_invoice()
            elif action == 'search_sale':
                data = []
                term = request.POST['term']
                ventas = (Sale.objects.filter(status__in=AUTORIZADOS, environment_type=request.company.environment_type)
                          .filter(anulado_sri_fecha__isnull=True)
                          .filter(Q(voucher_number_full__icontains=term) | Q(voucher_number__icontains=term) | Q(client__user__names__icontains=term) | Q(client__dni__icontains=term))
                          .exclude(client__identification_type=IDENTIFICATION_TYPE[-2][0]).exclude(client__dni='9999999999999')
                          .order_by('voucher_number')[0:10])
                for i in ventas:
                    acreditado = acreditado_por_detalle(i)
                    item = i.toJSON()
                    item['text'] = i.get_full_name()
                    # Cantidad que aún se puede acreditar en cada línea.
                    item['detail'] = [d.toJSON({'quantity': d.cant - acreditado.get(d.pk, 0), 'state': 0, 'total': 0.00})
                                      for d in i.saledetail_set.all() if d.cant - acreditado.get(d.pk, 0) > 0]
                    data.append(item)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get(self, request, *args, **kwargs):
        self.voucher_number_full = CreditNote().generate_voucher_number_full()
        if not self.voucher_number_full:
            faltan = requisitos_de_emision(request.company, VOUCHER_TYPE[1][0], electronica=False)
            messages.error(request, faltan[0]['mensaje'] if faltan else 'Configura la numeración de notas de crédito.')
            return HttpResponseRedirect(self.success_url)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = f'Nuevo registro de una Nota de Credito - {self.voucher_number_full}'
        context['list_url'] = self.success_url
        context['action'] = 'add'
        return context


class CreditNoteDeleteView(GroupPermissionMixin, DeleteView):
    model = CreditNote
    template_name = 'delete.html'
    success_url = reverse_lazy('credit_note_admin_list')
    permission_required = 'delete_credit_note'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            credit_note = self.get_object()
            if credit_note.status in emision.BLOQUEAN_BORRADO:
                data['error'] = ('Esta nota de crédito ya fue enviada al SRI y no se puede eliminar. Para dejarla sin efecto, '
                                 'anúlala en «SRI en línea» (requiere la aceptación del comprador).')
            else:
                credit_note.delete()
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Notificación de eliminación'
        context['list_url'] = self.success_url
        return context


class CreditNoteClientListView(GroupPermissionMixin, FormView):
    template_name = 'credit_note/client/list.html'
    form_class = ReportForm
    permission_required = 'view_credit_note_client'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                start_date = request.POST['start_date']
                end_date = request.POST['end_date']
                queryset = CreditNote.objects.filter(sale__client__user_id=request.user.id)
                if len(start_date) and len(end_date):
                    queryset = queryset.filter(date_joined__range=[start_date, end_date])
                for i in queryset:
                    data.append(i.toJSON())
            elif action == 'search_detail_products':
                data = []
                for i in CreditNoteDetail.objects.filter(credit_note_id=request.POST['id']):
                    data.append(i.toJSON())
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Notas de Credito'
        return context
