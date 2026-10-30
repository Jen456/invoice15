"""Pantallas de retenciones recibidas de clientes (Etapa 2, O2): listado, elegir factura, registrar (revisar sin guardar
y registrar) y ficha con anulación del registro.

- Funcionan sin JavaScript. Reglas en core/comprobantes/retenciones_recibidas.py; aquí, permisos y presentación.
- Permisos: ver con view_retencionrecibida; registrar con add_retencionrecibida; anular con change_retencionrecibida
  (empieza por change_: Contador y Consulta solo ven). Un id de otra empresa responde 404 (gestor de empresa).
- Plan: rutas bajo /comprobantes/ (plan pagado). Con el plan vencido, PlanMiddleware deja ver el listado y la ficha y
  bloquea …/add/… y los POST. No es emisión: con el cupo agotado sigue disponible, no consume cupo ni llama al SRI.
- El registro desde un 07 importado no tiene pantalla aquí: es de O1, bajo /importacion/ (plan Ilimitado).
"""
import re
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import DecimalField, Exists, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from core.comprobantes import retenciones_recibidas as rr
from core.comprobantes.forms_recibidas import (AnularRetencionRecibidaForm, LineasRecibidasFormSet, RetencionRecibidaForm,
                                               leer_fecha)
from core.comprobantes.models import RetencionRecibida, redondear
from core.comprobantes.views import tiene_permiso
from core.login.identificacion import ruc_valido
from core.pos import consultas, cxc
from core.pos.choices import ESTADOS_DECLARABLES_VENTA
from core.security.mixins import GroupPermissionMixin

URL_LISTA = 'comprobantes_retenciones_recibidas'
URL_FICHA = 'comprobantes_retencion_recibida'
LIMITE_LISTA = 200
LIMITE_FACTURAS = 20
ESTADOS_FILTRO = ('registrada', 'anulada', 'todas')
SIN_PERMISO = 'Tu perfil no puede realizar esta acción.'


def _dinero(valor):
    return f'${redondear(valor):.2f}'


def _texto_busqueda(valor):
    return ' '.join((valor or '').split())[:100]


def _saldos_de(ventas):
    """{venta_id: saldo} de la CxC de cada factura (no la de una nota de débito), en una sola consulta."""
    from core.pos.models import CtasCollect, PaymentsCtaCollect
    vigentes = (PaymentsCtaCollect.all_companies.filter(ctas_collect=OuterRef('pk'), anulado_en__isnull=True)
                .order_by().values('ctas_collect').annotate(total=Sum('valor')).values('total')[:1])
    cuentas = (cxc._sin_nota_debito(CtasCollect.objects.filter(sale__in=ventas))
               .annotate(abonado=Coalesce(Subquery(vigentes), Value(Decimal('0')),
                                          output_field=DecimalField(max_digits=12, decimal_places=2)))
               .order_by('id').values_list('sale_id', 'debt', 'abonado'))
    saldos = {}
    for venta_id, deuda, abonado in cuentas:
        saldos.setdefault(venta_id, redondear(Decimal(deuda) - Decimal(abonado or 0)))
    return saldos


class RetencionRecibidaListView(GroupPermissionMixin, TemplateView):
    template_name = 'comprobantes/retencion_recibida/list.html'
    permission_required = 'view_retencionrecibida'

    def filtros(self):
        datos = self.request.GET
        estado = datos.get('estado') or 'registrada'
        desde, hasta = leer_fecha(datos.get('desde')), leer_fecha(datos.get('hasta'))
        return {'desde': desde.isoformat() if desde else '', 'hasta': hasta.isoformat() if hasta else '',
                'q': _texto_busqueda(datos.get('q')), 'estado': estado if estado in ESTADOS_FILTRO else 'registrada'}

    def consulta(self, filtros):
        queryset = RetencionRecibida.objects.all()
        if filtros['estado'] != 'todas':
            queryset = queryset.filter(estado=filtros['estado'])
        if filtros['desde']:
            queryset = queryset.filter(fecha_emision__gte=filtros['desde'])
        if filtros['hasta']:
            queryset = queryset.filter(fecha_emision__lte=filtros['hasta'])
        texto = filtros['q']
        if texto:
            condicion = (Q(numero__icontains=texto) | Q(emisor_razon_social__icontains=texto)
                         | Q(emisor_identificacion__icontains=texto) | Q(cliente__user__names__icontains=texto)
                         | Q(cliente__dni__icontains=texto) | Q(venta__voucher_number_full__icontains=texto))
            numero = rr.normalizar_numero(texto)
            if numero:
                condicion |= Q(numero=rr.con_guiones(numero)) | Q(venta__voucher_number_full=rr.con_guiones(numero))
            queryset = queryset.filter(condicion)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filtros = self.filtros()
        queryset = self.consulta(filtros)
        cero = Value(Decimal('0'), output_field=DecimalField(max_digits=14, decimal_places=2))
        totales = queryset.filter(estado='registrada').aggregate(renta=Coalesce(Sum('total_renta'), cero),
                                                                 iva=Coalesce(Sum('total_iva'), cero),
                                                                 total=Coalesce(Sum('total_retenido'), cero))
        context.update({
            'title': 'Retenciones recibidas',
            'retenciones': (queryset.select_related('venta', 'cliente__user').prefetch_related('detalles')
                            .order_by('-fecha_emision', '-id')[:LIMITE_LISTA]),
            'filtros': filtros,
            'puede_registrar': tiene_permiso(self.request, 'add_retencionrecibida'),
            'totales': {clave: redondear(valor) for clave, valor in totales.items()},
        })
        return context


class RetencionRecibidaBuscarView(GroupPermissionMixin, TemplateView):
    """Elegir la factura sobre la que se registra la retención."""
    template_name = 'comprobantes/retencion_recibida/buscar.html'
    permission_required = 'add_retencionrecibida'

    def facturas(self, texto):
        from core.pos.clientes import CONSUMIDOR_FINAL
        from core.pos.models import CtasCollect, Sale
        queryset = (Sale.objects.filter(receipt__voucher_type='01', status__in=ESTADOS_DECLARABLES_VENTA,
                                        anulado_sri_fecha__isnull=True, environment_type=self.request.company.environment_type)
                    .exclude(client__identification_type='07').exclude(client__dni=CONSUMIDOR_FINAL))
        if texto:
            condicion = (Q(voucher_number_full__icontains=texto) | Q(client__user__names__icontains=texto)
                         | Q(client__dni__icontains=texto))
            numero = rr.normalizar_numero(texto)
            if numero:
                condicion |= Q(voucher_number_full=rr.con_guiones(numero))
            queryset = queryset.filter(condicion)
        else:   # las facturas a crédito más recientes que aún tienen saldo
            con_saldo = cxc._sin_nota_debito(CtasCollect.all_companies.filter(sale=OuterRef('pk'), saldo__gt=0))
            queryset = queryset.filter(Exists(con_saldo))
        ventas = list(queryset.select_related('client__user').annotate(fecha_efectiva=consultas.fecha_efectiva(Sale))
                      .order_by('-fecha_efectiva', '-id')[:LIMITE_FACTURAS])
        saldos = _saldos_de([v.pk for v in ventas])
        for venta in ventas:
            venta.saldo = saldos.get(venta.pk)   # None: venta de contado
        return ventas

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        texto = _texto_busqueda(self.request.GET.get('q'))
        context.update({'title': 'Registrar una retención recibida', 'q': texto, 'ventas': self.facturas(texto)})
        return context


class RetencionRecibidaCrearView(GroupPermissionMixin, TemplateView):
    """Registrar a mano la retención que el cliente hizo sobre una factura: revisar (sin guardar) y registrar."""
    template_name = 'comprobantes/retencion_recibida/create.html'
    permission_required = 'add_retencionrecibida'

    def get_venta(self):
        from core.pos.models import Sale
        return get_object_or_404(Sale.objects.select_related('client__user', 'receipt'), pk=self.kwargs['venta'])

    @staticmethod
    def pide_emisor_ruc(venta):
        return not ruc_valido(re.sub(r'\s', '', venta.client.dni or ''))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        venta = kwargs.get('factura') or self.get_venta()   # 'venta' es el id de la URL
        try:
            rr.validar_factura(venta)
            impedimento = None
        except rr.ErrorRetencionRecibida as e:
            impedimento = str(e)
        cuenta = cxc.cxc_de_factura(venta)
        hoy = timezone.localdate()
        pide = self.pide_emisor_ruc(venta)
        context.update({
            'title': 'Registrar retención recibida', 'venta': venta, 'cliente': venta.client, 'cxc': cuenta,
            'saldo': cxc.saldo(cuenta) if cuenta is not None else None, 'impedimento': impedimento,
            'pide_emisor_ruc': pide,
            'anteriores': RetencionRecibida.objects.filter(venta=venta).order_by('-id'),
            'topes': rr.topes(venta),
            'form': kwargs.get('form') or RetencionRecibidaForm(initial={'fecha_emision': hoy}, pide_emisor_ruc=pide),
            'lineas': kwargs.get('lineas') or LineasRecibidasFormSet(prefix='lineas', form_kwargs={'fecha': hoy}),
            'resumen': kwargs.get('resumen'),
        })
        return context

    def post(self, request, *args, **kwargs):
        venta = self.get_venta()
        form = RetencionRecibidaForm(request.POST, pide_emisor_ruc=self.pide_emisor_ruc(venta))
        fecha = leer_fecha(request.POST.get('fecha_emision')) or timezone.localdate()
        lineas = LineasRecibidasFormSet(request.POST, prefix='lineas', form_kwargs={'fecha': fecha})
        if not (form.is_valid() and lineas.is_valid()):
            return self.render_to_response(self.get_context_data(factura=venta, form=form, lineas=lineas))
        datos = form.cleaned_data
        filas = [f.linea() for f in lineas.forms if f.cleaned_data and f.linea()]
        retencion = rr.DatosRetencionRecibida(
            numero=datos['numero'], autorizacion=datos['autorizacion'], fecha_emision=datos['fecha_emision'],
            emisor_ruc=datos.get('emisor_ruc') or '', notas=datos.get('notas') or '',
            lineas=[rr.LineaRetencionRecibida(impuesto=i, codigo=c, base_imponible=b, porcentaje=p, valor_retenido=v)
                    for i, c, b, p, v in filas])
        try:
            if request.POST.get('action') != 'registrar':
                resumen = rr.calcular(venta, retencion)
                return self.render_to_response(self.get_context_data(factura=venta, form=form, lineas=lineas, resumen=resumen))
            with transaction.atomic():
                ret = rr.registrar(request.company, request.user, venta, retencion, request=request)
        except rr.ErrorRetencionRecibida as e:
            form.add_error(None, str(e))
            return self.render_to_response(self.get_context_data(factura=venta, form=form, lineas=lineas))
        if ret.abono_id:
            mensaje = (f'Retención {ret.numero} registrada: se abonaron {_dinero(ret.abono.valor)} a la cuenta por cobrar.')
        elif ret.cxc_estado == 'sin_cxc':
            mensaje = (f'Retención {ret.numero} registrada. La venta fue de contado: la retención no abona ninguna cuenta '
                       'por cobrar.')
        else:
            mensaje = (f'Retención {ret.numero} registrada. La cuenta por cobrar ya estaba saldada: no se abonó nada.')
        messages.success(request, mensaje)
        return HttpResponseRedirect(reverse(URL_FICHA, args=[ret.pk]))


class RetencionRecibidaDetalleView(GroupPermissionMixin, TemplateView):
    """Ficha de la retención recibida; POST action=anular anula el registro (revierte su abono)."""
    template_name = 'comprobantes/retencion_recibida/detalle.html'
    permission_required = 'view_retencionrecibida'

    def get_retencion(self):
        return get_object_or_404(RetencionRecibida.objects.select_related('venta', 'cliente__user', 'abono',
                                                                          'documento_importado', 'registrado_por',
                                                                          'anulado_sri_por')
                                 .prefetch_related('detalles'), pk=self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        ret = kwargs.get('retencion') or self.get_retencion()
        context.update({
            'title': f'Retención recibida {ret.numero}', 'retencion': ret,
            'puede_anular': tiene_permiso(self.request, 'change_retencionrecibida') and ret.estado == 'registrada',
            'form_anular': kwargs.get('form_anular') or AnularRetencionRecibidaForm(),
            'url_documento': (reverse('importacion_documento', args=[ret.documento_importado_id])
                              if ret.documento_importado_id else None),
            'error_permiso': kwargs.get('error_permiso'),
        })
        return context

    def post(self, request, *args, **kwargs):
        ret = self.get_retencion()
        if request.POST.get('action') != 'anular' or not tiene_permiso(request, 'change_retencionrecibida'):
            return self.render_to_response(self.get_context_data(retencion=ret, error_permiso=SIN_PERMISO), status=403)
        form = AnularRetencionRecibidaForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(retencion=ret, form_anular=form))
        try:
            with transaction.atomic():
                ret = rr.anular(request.company, request.user, ret, form.cleaned_data['motivo'], request=request)
        except rr.ErrorRetencionRecibida as e:
            form.add_error(None, str(e))
            return self.render_to_response(self.get_context_data(retencion=self.get_retencion(), form_anular=form))
        if ret.abono_id and ret.cxc_estado == 'revertida':
            mensaje = (f'Retención {ret.numero} anulada: se revirtió su abono de {_dinero(ret.abono.valor)} en la cuenta '
                       'por cobrar.')
        else:
            mensaje = f'Retención {ret.numero} anulada.'
        messages.success(request, mensaje)
        return HttpResponseRedirect(reverse(URL_FICHA, args=[ret.pk]))
