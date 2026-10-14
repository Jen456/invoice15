"""Plan y pagos: estado del plan, contratación con PayPhone, retorno y comprobantes."""
from django import forms
from django.contrib import messages
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView

from django.conf import settings
from core.login.identificacion import solo_digitos, tipo_identificacion
from core.security.mixins import SessionGroupMixin
from core.suscripciones import payphone
from core.suscripciones.models import Payment, Plan
from core.suscripciones.reglas import URL_SUSCRIPCION
from core.suscripciones.servicios import (ReglaPlan, agregar_empresa, cancelar_por_usuario, confirmar_pago,
                                          cotizar_mejora, empresas_del_plan, empresas_vinculables, estado_empresa,
                                          fechas_del_nuevo_periodo, iniciar_pago_payphone, limites_gratuito,
                                          modos_de_pago, planes_de_pago, solicitar_factura, vencer_pendientes,
                                          vincular_empresa)
from core.tenancy.models import ROLE_OWNER, Membership, audit


class PlanAccessMixin(SessionGroupMixin):
    """Solo los roles con el módulo «Plan y pagos» (Propietario y Administrador)."""

    def get_group_module(self, group):
        return group.groupmodule_set.filter(module__url=URL_SUSCRIPCION).first()

    def has_access(self, group):
        return self.get_group_module(group) is not None


def _uso_gratuito(company):
    from core.pos.models import Product, Provider, Purchase
    inicio_mes = timezone.localtime().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    limites = limites_gratuito()
    return [
        ('Productos', Product.all_companies.filter(company=company).count(), limites['product_limit']),
        ('Proveedores', Provider.all_companies.filter(company=company).count(), limites['provider_limit']),
        ('Compras este mes', Purchase.all_companies.filter(company=company, created_at__gte=inicio_mes).count(),
         limites['purchase_limit_month']),
    ]


class PlanView(PlanAccessMixin, TemplateView):
    template_name = 'suscripciones/plan.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.company
        vencer_pendientes()
        estado = estado_empresa(company)
        opciones = []
        bloqueo = None
        cubierta = estado.titular is not None and estado.periodo is not None   # adicional de un plan multiempresa
        for plan in ([] if cubierta else planes_de_pago()):
            try:
                modos = modos_de_pago(company, plan)
            except ReglaPlan as e:
                modos, bloqueo = [], str(e)
            cotizacion = cotizar_mejora(company, plan, estado=estado)
            opciones.append({
                'plan': plan,
                'modos': [(m, *fechas_del_nuevo_periodo(company, plan, m)) for m in modos],
                'actual': estado.periodo is not None and estado.periodo.plan_id == plan.pk,
                # Contrato con el frontend (HANDOFF): importe y vencimiento calculados en el servidor.
                'mejora': {k: cotizacion[k] for k in ('disponible', 'amount_cents', 'ends_at', 'renovacion', 'motivo')},
                # Hay una mejora por diferencia definida (Plan 1000 → ilimitado); el multiempresa no la tiene.
                'es_mejora': cotizacion['regla'] is not None,
                # Pasar de un plan de un RUC al multiempresa: año nuevo desde el pago, sin prorrateo.
                'cambio_multiempresa': plan.multiempresa and estado.periodo is not None and not estado.periodo.plan.multiempresa,
            })
        multiempresa = None
        if estado.periodo is not None and estado.periodo.plan.multiempresa and estado.titular is None:
            _, adicionales = empresas_del_plan(company)
            multiempresa = {'usados': 1 + len(adicionales), 'limite': estado.periodo.plan.company_limit}
        context.update({
            'title': 'Plan y pagos',
            'mejora_destacada': next((o for o in opciones if o['mejora']['disponible']), None),
            'estado': estado,
            'opciones': opciones,
            'bloqueo': bloqueo,
            'cubierta': cubierta,
            'multiempresa': multiempresa,
            'payphone_listo': payphone.configurado(),
            'uso_gratuito': _uso_gratuito(company) if not estado.pagado else None,
            'pagos': Payment.objects.filter(company=company).select_related('plan')[:20],
        })
        return context


class EmpresaAdicionalForm(forms.Form):
    ruc = forms.CharField(label='RUC', max_length=13, widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'off'}))
    business_name = forms.CharField(label='Razón social', max_length=50)
    tradename = forms.CharField(label='Nombre comercial (opcional)', max_length=50, required=False)
    main_address = forms.CharField(label='Dirección matriz', max_length=200)
    email = forms.EmailField(label='Correo de la empresa', max_length=50)
    mobile = forms.CharField(label='Celular', max_length=10)

    def clean_ruc(self):
        from core.login.identificacion import ruc_valido
        ruc = solo_digitos(self.cleaned_data['ruc'])
        if not ruc_valido(ruc):
            raise forms.ValidationError('Escribe un RUC válido de 13 dígitos.')
        return ruc


class EmpresasPlanView(PlanAccessMixin, TemplateView):
    """Plan multiempresa: empresas cubiertas y alta de RUC adicionales (solo el Propietario de la titular)."""
    template_name = 'suscripciones/empresas.html'

    def es_propietario(self):
        membresia = getattr(self.request, 'membership', None)
        return self.request.user.is_superuser or (membresia is not None and membresia.group.name == ROLE_OWNER)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.company
        estado = estado_empresa(company)
        periodo, adicionales = empresas_del_plan(company)
        context.update({
            'title': 'Empresas del plan multiempresa', 'estado': estado, 'periodo': periodo, 'adicionales': adicionales,
            'multiempresa': periodo is not None and periodo.plan.multiempresa and estado.titular is None,
            'usados': 1 + len(adicionales), 'propietario': self.es_propietario(),
            'form': kwargs.get('form') or EmpresaAdicionalForm(),
            'vinculables': empresas_vinculables(company, self.request.user) if self.es_propietario() else [],
        })
        return context

    def post(self, request, *args, **kwargs):
        company = request.company
        if not self.es_propietario():
            messages.error(request, 'Solo el Propietario de la empresa titular puede agregar RUC al plan.')
            return HttpResponseRedirect(reverse('suscripcion_empresas'))
        try:
            if request.POST.get('accion') == 'vincular':
                empresa = get_object_or_404(empresas_vinculables(company, request.user), pk=request.POST.get('empresa'))
                vincular_empresa(company, request.user, empresa)
            else:
                form = EmpresaAdicionalForm(request.POST)
                if not form.is_valid():
                    return self.render_to_response(self.get_context_data(form=form))
                empresa = agregar_empresa(company, request.user, form.cleaned_data)
        except ReglaPlan as e:
            messages.error(request, str(e))
            return HttpResponseRedirect(reverse('suscripcion_empresas'))
        audit(request, 'plan_company_added', company=company, empresa=empresa.pk, ruc=empresa.ruc)
        messages.success(request, f'{empresa.business_name} (RUC {empresa.ruc}) ya está incluida en tu plan. Para configurarla '
                                  'y facturar con ella, cámbiate de empresa desde el selector de empresas.')
        return HttpResponseRedirect(reverse('suscripcion_empresas'))


class PagarView(PlanAccessMixin, View):
    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        company = request.company
        plan = Plan.objects.filter(code=request.POST.get('plan', ''), is_active=True).first()
        modo = request.POST.get('modo', 'inmediato')
        if plan is None:
            messages.error(request, 'Elige un plan válido.')
            return HttpResponseRedirect(URL_SUSCRIPCION)
        if not payphone.configurado():
            messages.error(request, 'El cobro en línea aún no está habilitado. Escríbenos a ventas@facturaporaqui.com.')
            return HttpResponseRedirect(URL_SUSCRIPCION)
        base = settings.FPA_URL_APP.rstrip('/') if settings.FPA_URL_APP else request.build_absolute_uri('/').rstrip('/')
        try:
            pago, enlace = iniciar_pago_payphone(company, plan, request.user, modo,
                                                 base + reverse('suscripcion_retorno'),
                                                 base + reverse('suscripcion_cancelado'))
        except ReglaPlan as e:
            messages.error(request, str(e))
            return HttpResponseRedirect(URL_SUSCRIPCION)
        audit(request, 'plan_payment_start', company=company, plan=plan.code, modo=modo, referencia=pago.client_tx_id)
        return HttpResponseRedirect(enlace)


@method_decorator(never_cache, name='dispatch')
class RetornoView(View):
    """PayPhone devuelve aquí al cliente con ?id=<transacción>&clientTransactionId=<referencia>.

    No exige sesión: el resultado se confirma con PayPhone desde el servidor y
    nunca se toma de los parámetros del navegador.
    """

    def get(self, request, *args, **kwargs):
        referencia = request.GET.get('clientTransactionId', '')[:50]
        pago = confirmar_pago(referencia, request.GET.get('id')) if referencia else None
        propio = pago is not None and request.user.is_authenticated and (
            request.user.is_superuser or Membership.objects.active().filter(user=request.user, company=pago.company_id).exists())
        periodo = None
        if pago is not None and pago.status == 'aprobado':
            periodo = pago.target_period if pago.mode == 'mejora' else getattr(pago, 'period', None)
        return render(request, 'suscripciones/retorno.html', {
            'pago': pago, 'periodo': periodo, 'propio': propio, 'reintentar': request.get_full_path(),
        })


@method_decorator(never_cache, name='dispatch')
class CanceladoView(View):
    def get(self, request, *args, **kwargs):
        pago = Payment.objects.filter(client_tx_id=request.GET.get('ref', '')[:50]).select_related('plan').first()
        if pago is not None and request.user.is_authenticated and \
                Membership.objects.active().filter(user=request.user, company=pago.company_id).exists():
            pago = cancelar_por_usuario(pago)
        return render(request, 'suscripciones/cancelado.html', {'pago': pago})


class FacturaForm(forms.Form):
    razon_social = forms.CharField(label='Razón social o nombres', max_length=300)
    identificacion = forms.CharField(label='RUC o cédula', max_length=13)
    direccion = forms.CharField(label='Dirección', max_length=300)
    correo = forms.EmailField(label='Correo para recibir la factura')

    def clean_identificacion(self):
        valor = solo_digitos(self.cleaned_data['identificacion'])
        if valor != '9999999999999' and tipo_identificacion(valor) is None:
            raise forms.ValidationError('Ingresa un RUC o una cédula válidos.')
        return valor


class PagoDetalleView(PlanAccessMixin, TemplateView):
    template_name = 'suscripciones/pago.html'

    def get_pago(self):
        return get_object_or_404(Payment.objects.select_related('plan', 'user'), uuid=self.kwargs['uuid'],
                                 company=self.request.company)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pago = self.get_pago()
        company = self.request.company
        inicial = pago.invoice_data or {'razon_social': company.business_name, 'identificacion': company.ruc,
                                        'direccion': company.main_address, 'correo': company.email}
        periodo = pago.target_period if pago.mode == 'mejora' else getattr(pago, 'period', None)
        context.update({'title': 'Detalle del pago', 'pago': pago, 'periodo': periodo,
                        'form': kwargs.get('form') or FacturaForm(initial=inicial)})
        return context

    def post(self, request, *args, **kwargs):
        pago = self.get_pago()
        if pago.status != 'aprobado':
            raise Http404
        form = FacturaForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        solicitar_factura(pago, form.cleaned_data)
        audit(request, 'plan_invoice_request', company=request.company, referencia=pago.client_tx_id)
        messages.success(request, 'Solicitud recibida. Te enviaremos la factura al correo indicado.')
        return HttpResponseRedirect(request.path)
