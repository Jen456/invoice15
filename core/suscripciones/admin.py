"""Planes, IVA, pagos, períodos y consumo en el panel de la plataforma."""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import path, reverse

from core.pos.models import Company
from core.suscripciones.models import IvaRate, Payment, PaymentEvent, Plan, QuotaReservation, SubscriptionPeriod
from core.suscripciones.servicios import ReglaPlan, activar_manual, fechas_del_nuevo_periodo
from core.tenancy.admin import plataforma
from core.tenancy.models import audit


@admin.register(Plan, site=plataforma)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'price_cents', 'document_limit', 'includes_billing', 'product_limit',
                    'provider_limit', 'purchase_limit_month', 'is_active', 'order')
    list_editable = ('is_active', 'order')
    readonly_fields = ('code',)

    def get_readonly_fields(self, request, obj=None):
        # El código identifica el plan en los pagos; el precio cobrado se congela en cada pago.
        return ('code',) if obj is not None else ()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IvaRate, site=plataforma)
class IvaRateAdmin(admin.ModelAdmin):
    list_display = ('rate', 'valid_from', 'legal_reference')

    def has_delete_permission(self, request, obj=None):
        return False


class PaymentEventInline(admin.TabularInline):
    model = PaymentEvent
    extra = 0
    can_delete = False
    fields = ('created_at', 'kind', 'detail')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class ActivacionManualForm(forms.Form):
    company = forms.ModelChoiceField(Company.objects.filter(is_active=True).order_by('business_name'), label='Empresa')
    plan = forms.ModelChoiceField(Plan.objects.filter(includes_billing=True, price_cents__gt=0), label='Plan')
    mode = forms.ChoiceField(choices=Payment.MODES, label='Inicio del período')
    note = forms.CharField(label='Motivo / comprobante del pago recibido', max_length=300,
                           widget=forms.TextInput(attrs={'size': 80}))


@admin.register(Payment, site=plataforma)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'company', 'plan', 'amount_cents', 'status', 'method', 'mode', 'client_tx_id',
                    'payphone_transaction_id', 'invoice_requested', 'invoice_number')
    list_filter = ('status', 'method', 'plan', 'invoice_requested')
    search_fields = ('client_tx_id', 'payphone_transaction_id', 'company__business_name', 'company__ruc')
    readonly_fields = [f.name for f in Payment._meta.fields if f.name not in ('note', 'invoice_number')]
    inlines = (PaymentEventInline,)
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False   # los pagos nacen en PayPhone o en «Activar plan manualmente»

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [path('activar/', self.admin_site.admin_view(self.activar_view), name='suscripciones_activar')] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        extra_context = {**(extra_context or {}), 'activar_url': reverse('plataforma:suscripciones_activar')}
        return super().changelist_view(request, extra_context)

    def activar_view(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied
        form = ActivacionManualForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            datos = form.cleaned_data
            try:
                pago, periodo = activar_manual(datos['company'], datos['plan'], request.user, datos['mode'], datos['note'])
            except ReglaPlan as e:
                form.add_error(None, str(e))
            else:
                audit(request, 'plan_manual', company=datos['company'], plan=datos['plan'].code, modo=pago.mode,
                      referencia=pago.client_tx_id, motivo=datos['note'])
                messages.success(request, f'{datos["plan"].name} activado para {datos["company"]}: '
                                          f'{periodo.starts_at:%d/%m/%Y} al {periodo.ends_at:%d/%m/%Y}.')
                return redirect('plataforma:suscripciones_subscriptionperiod_changelist')
        vista_previa = None
        if form.is_bound and form.is_valid():
            datos = form.cleaned_data
            vista_previa = fechas_del_nuevo_periodo(datos['company'], datos['plan'], datos['mode'])
        return render(request, 'suscripciones/admin_activar.html', {
            **self.admin_site.each_context(request), 'title': 'Activar plan manualmente', 'form': form,
            'opts': self.model._meta, 'vista_previa': vista_previa,
        })


@admin.register(SubscriptionPeriod, site=plataforma)
class SubscriptionPeriodAdmin(admin.ModelAdmin):
    list_display = ('company', 'plan', 'status', 'starts_at', 'ends_at', 'documents_used', 'documents_reserved',
                    'document_limit')
    list_filter = ('status', 'plan')
    search_fields = ('company__business_name', 'company__ruc')
    readonly_fields = ('company', 'plan', 'payment', 'documents_used', 'documents_reserved', 'created_at', 'replaced_at')
    actions = ('anular',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit(request, 'plan_period_change', company=obj.company, periodo=obj.pk, campos=list(form.changed_data))

    @admin.action(description='Anular los períodos seleccionados (la empresa pierde el plan)')
    def anular(self, request, queryset):
        for periodo in queryset.exclude(status='anulada'):
            periodo.status = 'anulada'
            periodo.save(update_fields=['status'])
            audit(request, 'plan_period_change', company=periodo.company, periodo=periodo.pk, campos=['status'],
                  valor='anulada')


@admin.register(QuotaReservation, site=plataforma)
class QuotaReservationAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'company', 'voucher_model', 'voucher_label', 'status', 'consumed_at', 'released_at')
    list_filter = ('status', 'voucher_model')
    search_fields = ('company__business_name', 'voucher_label')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
