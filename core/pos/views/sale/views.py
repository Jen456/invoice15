import json
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse_lazy
from django.views import View
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, FormView

from config import settings
from core.pos.forms import SaleForm, ClientForm, ClientUserForm, Sale, SaleDetail, Client, Product, Company, Receipt, CreditNote, CreditNoteDetail, CtasCollect, INVOICE_STATUS, PAYMENT_TYPE, VOUCHER_TYPE
from core.pos.choices import MEDIOS_DE_PAGO
from core.cobros import servicios as cobros
from core.configuracion import puntos as pt
from core.configuracion.servicios import requisitos_de_emision, secuencia_configurada
from core.pos import emision
from core.pos.clientes import consumidor_final, unir_correos, usuario_de_cliente
from core.pos.notas_credito import crear as crear_nota_credito, es_consumidor_final
from core.pos.utilities import printer
from core.pos.utilities.access import can_print_voucher
from core.pos.utilities.sri import SRI
from core.reports.forms import ReportForm
from core.security.mixins import GroupPermissionMixin
from core.security.session import get_group


logger = logging.getLogger(__name__)


class SaleListView(GroupPermissionMixin, FormView):
    template_name = 'sale/admin/list.html'
    form_class = ReportForm
    permission_required = 'view_sale'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                start_date = request.POST['start_date']
                end_date = request.POST['end_date']
                queryset = Sale.objects.select_related('receipt__emission_point__establishment')
                if len(start_date) and len(end_date):
                    queryset = queryset.filter(date_joined__range=[start_date, end_date])
                if request.POST.get('punto'):   # filtro por punto de emisión (id de EmissionPoint)
                    queryset = queryset.filter(receipt__emission_point_id=request.POST['punto'])
                for i in queryset:
                    data.append(i.toJSON())
            elif action == 'search_detail_products':
                data = []
                for i in SaleDetail.objects.filter(sale_id=request.POST['id']):
                    data.append(i.toJSON())
            elif action == 'generate_invoice':
                sale = Sale.objects.get(pk=request.POST['id'])
                data = sale.generate_electronic_invoice()
            elif action == 'create_credit_note':
                # Nota de crédito por todo lo pendiente de la factura: mismo permiso que la pantalla de notas.
                group = get_group(request)
                if group is None or not group.permissions.filter(codename='add_credit_note').exists():
                    data['error'] = 'Tu perfil no puede emitir notas de crédito.'
                else:
                    sale = Sale.objects.get(pk=request.POST['id'])
                    # Sin formulario: la nota sale del punto activo del usuario (o del `punto` enviado, validado).
                    punto = pt.punto_del_formulario(request.user, request.company, request.POST.get('punto'))
                    with transaction.atomic():
                        credit_note = crear_nota_credito(request.company, sale.pk, None,
                                                         f'DEVOLUCIÓN TOTAL DE LA FACTURA {sale.voucher_number_full}', punto=punto)
                        emision.preparar(credit_note)
                    data = credit_note.generate_electronic_invoice()
            elif action == 'send_invoice_by_email':
                sale = Sale.objects.get(pk=request.POST['id'])
                xml_electronic_signature = SRI()
                data = xml_electronic_signature.notify_by_email(instance=sale, company=sale.company, client=sale.client)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Ventas'
        context['create_url'] = reverse_lazy('sale_admin_create')
        return context


class SaleCreateView(GroupPermissionMixin, CreateView):
    model = Sale
    template_name = 'sale/admin/create.html'
    form_class = SaleForm
    success_url = reverse_lazy('sale_admin_list')
    permission_required = 'add_sale'

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if self.request.company.environment_type == emision.PRODUCCION:
            # El ticket de venta no es comprobante del SRI: en Producción solo se emiten facturas.
            form.fields['receipt'].choices = [(c, n) for c, n in form.fields['receipt'].choices if c != VOUCHER_TYPE[2][0]]
        return form

    def get(self, request, *args, **kwargs):
        # Facturar una proforma (?proforma=<id>): la pantalla se abre precargada y no guarda nada (core/proformas).
        self.precarga = None
        if 'proforma' in request.GET:
            from core.proformas import servicios as proformas
            if 'change_proforma' not in proformas.permisos_de(request):
                messages.error(request, proformas.MENSAJES['facturar_sin_permiso'])
                return HttpResponseRedirect(proformas.URL_LISTA)
            try:
                self.precarga = proformas.precarga_para_venta(request.GET['proforma'])
            except proformas.ErrorProforma as e:
                messages.error(request, e.mensaje)
                return HttpResponseRedirect(e.url or proformas.URL_LISTA)
        return super().get(request, *args, **kwargs)

    def get_first_final_consumer(self):
        return consumidor_final(self.request.company).toJSON()

    def validar_consumidor_final(self, sale):
        if not es_consumidor_final(sale.client):
            return
        if sale.client.dni != '9999999999999' or sale.client.identification_type != '07':
            raise ValueError('El consumidor final usa el tipo «Venta a consumidor final» y la identificación 9999999999999.')
        if Decimal(str(round(float(sale.total), 2))) > Decimal('50.00'):
            raise ValueError('Una factura a consumidor final no puede superar USD 50,00 (ficha técnica del SRI, 9.10). '
                             'Registra los datos del comprador.')

    def post(self, request, *args, **kwargs):
        action = request.POST['action']
        data = {}
        try:
            if action == 'add':
                if request.POST['receipt'] == VOUCHER_TYPE[2][0] and request.company.environment_type == emision.PRODUCCION:
                    raise ValueError('El ticket de venta no está disponible en Producción: emite una factura.')
                proforma_id, proforma = (request.POST.get('proforma_id') or '').strip(), None
                with transaction.atomic():
                    if proforma_id:
                        # Factura de una proforma: se bloquea ANTES de reservar el número (orden fijo proforma → secuencia).
                        from core.proformas import servicios as proformas
                        if 'change_proforma' not in proformas.permisos_de(request):
                            raise ValueError(proformas.MENSAJES['facturar_sin_permiso'])
                        proforma = proformas.bloquear_para_facturar(proforma_id, request.POST['receipt'])
                    sale = Sale()
                    sale.date_joined = timezone.localdate()   # la fecha de emisión es la de hoy; no se elige
                    sale.company = request.company
                    sale.environment_type = sale.company.environment_type
                    # Toda factura es electrónica y se transmite al emitirla (Res. NAC-DGERCGC25-00000014).
                    electronica = request.POST['receipt'] == VOUCHER_TYPE[0][0]
                    # Punto de emisión fijado al formulario (`punto`), validado otra vez para este usuario; sin él, su punto activo.
                    sale.receipt = pt.receipt_para_emitir(request, request.POST['receipt'], electronica, request.POST.get('punto'))
                    sale.voucher_number = sale.generate_voucher_number()
                    sale.voucher_number_full = sale.get_voucher_number_full()
                    sale.employee_id = request.user.id
                    sale.client_id = int(request.POST['client'])
                    sale.payment_type = request.POST['payment_type']
                    additional_info = [
                        {'name': 'Dirección', 'value': sale.client.address},
                        {'name': 'Teléfono', 'value': sale.client.mobile},
                        {'name': 'Email', 'value': unir_correos(sale.client.correos(), 300)}
                    ]
                    additional_info_json = json.loads(request.POST['additional_info'])
                    if len(additional_info_json):
                        additional_info.extend(additional_info_json)
                    sale.additional_info = additional_info
                    sale.iva = float(sale.company.iva) / 100
                    sale.create_electronic_invoice = False
                    if sale.receipt.voucher_type == VOUCHER_TYPE[0][0]:
                        sale.time_limit = int(request.POST['time_limit'])
                        sale.payment_method = request.POST['payment_method']
                        sale.create_electronic_invoice = True
                    # Condición de pago (contado 'efectivo' / crédito) aparte del medio de cobro (core/cobros). Sin el campo
                    # medio_cobro (formularios anteriores) se asume efectivo; con él vacío o inválido, se rechaza.
                    contado = sale.payment_type == PAYMENT_TYPE[0][0]
                    medio_cobro = request.POST['medio_cobro'] if 'medio_cobro' in request.POST else 'efectivo'
                    nota_cobro = ' '.join((request.POST.get('nota_cobro') or '').split())
                    referencia_cobro = request.POST.get('referencia_cobro', '')
                    respaldo = request.FILES.get('respaldo')
                    sale.cash, sale.change = Decimal('0.00'), Decimal('0.00')
                    if contado:
                        if medio_cobro not in dict(MEDIOS_DE_PAGO):
                            raise ValueError('Elige el medio de cobro.')
                        sale.medio_cobro = medio_cobro
                        if medio_cobro == 'efectivo':
                            sale.cash = cobros.efectivo_recibido(request.POST.get('cash'))   # el cambio se calcula abajo
                    elif sale.payment_type == PAYMENT_TYPE[1][0]:
                        if nota_cobro or respaldo is not None:
                            raise ValueError(cobros.MENSAJES['credito_sin_abono'])
                        sale.end_credit = request.POST['end_credit']
                    sale.save()
                    for i in json.loads(request.POST['products']):
                        product = Product.objects.get(pk=i['id'])
                        detail = SaleDetail()
                        detail.sale_id = sale.id
                        detail.product_id = product.id
                        detail.cant = int(i['cant'])
                        detail.price = float(i['price_current'])
                        detail.dscto = float(i['dscto']) / 100
                        detail.save()
                        if detail.product.inventoried:
                            detail.product.stock -= detail.cant
                            detail.product.save()
                    sale.calculate_detail()
                    sale.calculate_invoice()
                    if sale.create_electronic_invoice:
                        self.validar_consumidor_final(sale)
                    if contado:
                        if sale.medio_cobro == 'efectivo':
                            # «Efectivo recibido» y «Cambio» solo para efectivo, y el cambio lo calcula el servidor.
                            sale.change = cobros.cambio(sale.cash, sale.total)
                            sale.save(update_fields=['cash', 'change'])
                        if sale.medio_cobro != 'efectivo' or nota_cobro or respaldo is not None:
                            # Respaldo del cobro al contado: obligatorio salvo en efectivo (comprobante, nota o ambos).
                            cobros.registrar_al_emitir(request, sale, sale.medio_cobro, referencia_cobro, nota_cobro, respaldo)
                    if sale.payment_type == PAYMENT_TYPE[1][0]:
                        ctas_collect = CtasCollect()
                        ctas_collect.sale_id = sale.id
                        ctas_collect.date_joined = sale.date_joined
                        ctas_collect.end_date = sale.end_credit
                        ctas_collect.debt = sale.total
                        ctas_collect.saldo = sale.total
                        ctas_collect.save()
                    data = {'print_url': str(reverse_lazy('sale_admin_print_invoice', kwargs={'pk': sale.id}))}
                    if sale.create_electronic_invoice:
                        # Firma y guarda el XML con su fecha y clave. Si falla, la venta se deshace: nada salió al SRI.
                        emision.preparar(sale)
                    if proforma is not None:
                        # UPDATE condicional: si otra conversión ganó, ErrorProforma deshace toda esta venta.
                        proformas.marcar_facturada(proforma, sale, request.user, request)
                if sale.create_electronic_invoice:
                    # Ya confirmada la venta: un fallo desde aquí nunca la borra ni libera su número.
                    data = sale.generate_electronic_invoice()
            elif action == 'search_product':
                ids = json.loads(request.POST['ids'])
                data = []
                term = request.POST['term']
                queryset = Product.objects.filter(Q(stock__gt=0) | Q(inventoried=False)).exclude(id__in=ids).order_by('name')
                if len(term):
                    queryset = queryset.filter(Q(name__icontains=term) | Q(code__icontains=term))
                    queryset = queryset[:10]
                for i in queryset:
                    item = i.toJSON()
                    item['pvp'] = float(i.pvp)
                    item['value'] = i.get_full_name()
                    item['dscto'] = 0.00
                    item['total_dscto'] = 0.00
                    data.append(item)
            elif action == 'search_product_code':
                data = {}
                code = request.POST['code']
                if len(code):
                    product = Product.objects.filter(code=code).first()
                    if product:
                        data = product.toJSON()
                        data['dscto'] = 0.00
                        data['total_dscto'] = 0.00
            elif action == 'search_client':
                data = []
                term = request.POST['term']
                for i in Client.objects.filter(Q(user__names__icontains=term) | Q(dni__icontains=term)).order_by('user__names')[0:10]:
                    data.append(i.toJSON())
            elif action == 'search_voucher_number':
                # Número del próximo documento del punto fijado al formulario (sin reservarlo) o lo que falta configurar.
                company = request.company
                data['voucher_number'] = ''
                try:
                    punto = pt.punto_del_formulario(request.user, company, request.POST.get('punto'))
                except pt.ErrorPunto as e:
                    data['pending'] = {'codigo': 'punto', 'mensaje': str(e), 'url': pt.URL}
                else:
                    receipt = secuencia_configurada(company, request.POST['receipt'], punto=punto)
                    if receipt:
                        data['voucher_number'] = f'{receipt.next_number:09d}'
                        data['voucher_number_full'] = receipt.next_number_full()
                        data['punto'] = pt.punto_json(punto)
                    else:
                        faltan = requisitos_de_emision(company, request.POST['receipt'], electronica=False, punto=punto)
                        data['pending'] = faltan[0] if faltan else None
            elif action == 'validate_client':
                data = {'valid': True}
                pattern = request.POST['pattern']
                parameter = request.POST['parameter'].strip()
                queryset = Client.objects.all()
                if pattern == 'dni':
                    data['valid'] = not queryset.filter(dni=parameter).exists()
                elif pattern == 'mobile':
                    data['valid'] = not queryset.filter(mobile=parameter).exists()
                elif pattern == 'email':
                    data['valid'] = not queryset.filter(user__email=parameter).exists()
            elif action == 'create_client':
                with transaction.atomic():
                    form1 = ClientUserForm(self.request.POST, self.request.FILES)
                    form2 = ClientForm(request.POST)
                    if form1.is_valid() and form2.is_valid():
                        user = usuario_de_cliente(form1, form2.cleaned_data['dni'])
                        form_client = form2.save(commit=False)
                        form_client.user = user
                        form_client.save()
                        data = Client.objects.get(pk=form_client.id).toJSON()
                    else:
                        if not form1.is_valid():
                            data['error'] = form1.errors
                        elif not form2.is_valid():
                            data['error'] = form2.errors
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = f'Nuevo registro de una Venta'
        context['frmClient'] = ClientForm()
        context['list_url'] = self.success_url
        context['action'] = 'add'
        context['frmUser'] = ClientUserForm()
        context['final_consumer'] = json.dumps(self.get_first_final_consumer())
        # Punto de emisión fijado a este formulario (configuracion/_punto_emision.html); el servidor lo revalida al emitir.
        context.update(pt.contexto_formulario(self.request, VOUCHER_TYPE[0][0]))
        precarga = getattr(self, 'precarga', None)
        if precarga:
            context['title'] = f"Facturar la proforma {precarga['proforma']['numero']}"
            context['proforma_precarga'] = precarga
            context['proforma_facturar'] = precarga['proforma']
            context['proforma_avisos'] = precarga['avisos']
        return context


class SaleDeleteView(GroupPermissionMixin, DeleteView):
    model = Sale
    template_name = 'delete.html'
    success_url = reverse_lazy('sale_admin_list')
    permission_required = 'delete_sale'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            with transaction.atomic():
                # Con la venta bloqueada, un borrado doble o una emisión a la vez no devuelven el stock dos veces.
                sale = Sale.objects.select_for_update(of=('self',)).get(pk=self.get_object().pk)
                if sale.status in emision.BLOQUEAN_BORRADO:
                    data['error'] = ('Esta factura ya fue enviada al SRI y no se puede eliminar. Para dejarla sin efecto, anúlala en '
                                     '«SRI en línea» (hasta el día 7 del mes siguiente) o emite una nota de crédito.')
                else:
                    cuentas = list(sale.ctascollect_set.select_for_update(of=('self',)))
                    if any(cuenta.paymentsctacollect_set.exists() for cuenta in cuentas):
                        # Antes de tocar el stock: con cobros registrados no se borra nada.
                        data['error'] = ('Esta venta a crédito tiene cobros registrados en «Cuentas por cobrar». Elimina '
                                         'esos cobros antes de eliminar la venta.')
                    else:
                        for cuenta in cuentas:   # la cuenta por cobrar (sin abonos) protege a la venta: se borra con ella
                            cuenta.delete()
                        sale.delete()
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Notificación de eliminación'
        context['list_url'] = self.success_url
        return context


class SalePrintInvoiceView(LoginRequiredMixin, View):
    success_url = reverse_lazy('sale_admin_list')

    def get_success_url(self):
        if self.request.user.is_client():
            return reverse_lazy('sale_client_list')
        return self.success_url

    def get(self, request, *args, **kwargs):
        try:
            sale = Sale.objects.filter(id=self.kwargs['pk']).first()
            if sale and not can_print_voucher(request, sale):
                sale = None
            if sale:
                # Papel continuo: el alto sale del contenido (printer.create_pdf_continuo), no de una estimación por líneas.
                pdf_file = printer.create_pdf_continuo(context={'sale': sale}, template_name='sale/format/ticket.html')
                return HttpResponse(pdf_file, content_type='application/pdf')
        except Exception:
            logger.exception('No se pudo generar el PDF de la venta %s', self.kwargs['pk'])
        return HttpResponseRedirect(self.get_success_url())


class SalePrintA4View(LoginRequiredMixin, View):
    """RIDE A4 (versión completa) de una factura autorizada, también si después se anuló con una nota de crédito: el PDF
    guardado al autorizarse. Si faltara (falló al generarse), se genera esa única vez con los datos actuales; nunca
    reemplaza uno existente. Antes de la autorización no hay RIDE."""
    success_url = reverse_lazy('sale_admin_list')
    ESTADOS = emision.AUTORIZADOS + (emision.ANULADA,)

    def get_success_url(self):
        if self.request.user.is_client():
            return reverse_lazy('sale_client_list')
        return self.success_url

    @staticmethod
    def tiene_ride(sale):
        return bool(sale.pdf_authorized) and sale.pdf_authorized.storage.exists(sale.pdf_authorized.name)

    @staticmethod
    def generar_ride(sale):
        sale.generate_pdf_authorized()   # escribe el archivo; solo se guarda ese campo, no la venta completa
        try:
            Sale.objects.filter(pk=sale.pk).update(pdf_authorized=sale.pdf_authorized.name)
        except Exception:
            sale.pdf_authorized.storage.delete(sale.pdf_authorized.name)
            raise

    def get(self, request, *args, **kwargs):
        try:
            sale = Sale.objects.select_related('receipt').filter(id=self.kwargs['pk']).first()
            if sale and can_print_voucher(request, sale) and sale.status in self.ESTADOS \
                    and sale.receipt.voucher_type == VOUCHER_TYPE[0][0]:
                if not self.tiene_ride(sale):
                    with transaction.atomic():
                        sale = Sale.objects.select_for_update().get(pk=sale.pk)
                        if not self.tiene_ride(sale):
                            self.generar_ride(sale)
                return HttpResponseRedirect(sale.get_pdf_authorized())
        except Exception:
            logger.exception('No se pudo abrir el RIDE A4 de la venta %s', self.kwargs['pk'])
        return HttpResponseRedirect(self.get_success_url())


class SaleClientListView(GroupPermissionMixin, FormView):
    template_name = 'sale/client/list.html'
    form_class = ReportForm
    permission_required = 'view_sale_client'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                start_date = request.POST['start_date']
                end_date = request.POST['end_date']
                queryset = Sale.objects.filter(client__user_id=request.user.id)
                if len(start_date) and len(end_date):
                    queryset = queryset.filter(date_joined__range=[start_date, end_date])
                for i in queryset:
                    data.append(i.toJSON())
            elif action == 'search_detail_products':
                data = []
                for i in SaleDetail.objects.filter(sale_id=request.POST['id']):
                    data.append(i.toJSON())
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Ventas'
        return context
