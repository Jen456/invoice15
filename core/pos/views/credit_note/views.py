import json

from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, FormView

from core.pos.forms import CreditNoteForm, CreditNote, CreditNoteDetail, Company, Sale, Receipt, SaleDetail, VOUCHER_TYPE, INVOICE_STATUS, IDENTIFICATION_TYPE
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
                with transaction.atomic():
                    company = Company.objects.first()
                    iva = float(company.iva) / 100
                    credit_note = CreditNote()
                    credit_note.sale_id = int(request.POST['sale'])
                    credit_note.motive = request.POST['motive']
                    credit_note.company = company
                    credit_note.environment_type = credit_note.company.environment_type
                    credit_note.receipt = Receipt.objects.get(voucher_type=VOUCHER_TYPE[1][0], establishment_code=credit_note.company.establishment_code, issuing_point_code=credit_note.company.issuing_point_code)
                    credit_note.voucher_number = credit_note.generate_voucher_number()
                    credit_note.voucher_number_full = credit_note.get_voucher_number_full()
                    credit_note.iva = iva
                    credit_note.create_electronic_invoice = 'create_electronic_invoice' in request.POST
                    credit_note.save()
                    for i in json.loads(request.POST['products']):
                        sale_detail = SaleDetail.objects.get(id=i['id'])
                        detail = CreditNoteDetail()
                        detail.credit_note_id = credit_note.id
                        detail.sale_detail_id = sale_detail.id
                        detail.product_id = sale_detail.product_id
                        detail.cant = int(i['quantity'])
                        detail.price = float(i['price'])
                        detail.dscto = float(i['dscto']) / 100
                        detail.save()
                        credit_note.calculate_detail()
                        detail.product.stock += detail.cant
                        detail.product.save()
                    credit_note.calculate_invoice()
                    if credit_note.create_electronic_invoice:
                        data = credit_note.generate_electronic_invoice()
                        if not data['resp']:
                            transaction.set_rollback(True)
                        else:
                            credit_note.sale.status = INVOICE_STATUS[3][0]
                            credit_note.sale.save()
                if 'error' in data:
                    SRI().create_voucher_errors(credit_note, data)
            elif action == 'search_sale':
                data = []
                term = request.POST['term']
                for i in Sale.objects.filter(status__in=[INVOICE_STATUS[1][0], INVOICE_STATUS[2][0]]).filter(Q(voucher_number_full__icontains=term) | Q(voucher_number__icontains=term) | Q(client__user__names__icontains=term) | Q(client__dni__icontains=term)).exclude(client__identification_type=IDENTIFICATION_TYPE[-2][0]).order_by('voucher_number')[0:10]:
                    item = i.toJSON()
                    item['text'] = i.get_full_name()
                    item['detail'] = [d.toJSON({'quantity': d.cant, 'state': 0, 'total': 0.00}) for d in i.saledetail_set.all()]
                    data.append(item)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = f'Nuevo registro de una Nota de Credito - {CreditNote().generate_voucher_number_full()}'
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
            self.get_object().delete()
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
