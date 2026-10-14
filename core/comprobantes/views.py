"""Comprobantes adicionales emitidos desde Compras (retención 07, liquidación de compra 03): emisión y listado."""
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import TemplateView

from core.comprobantes import liquidaciones as sl
from core.comprobantes import retenciones as sv
from core.comprobantes.forms import DocumentoSustentoForm, LineasLiquidacionFormSet, LineasRetencionFormSet, LiquidacionForm
from core.comprobantes.models import CodigoRetencion, LiquidacionCompra, Retencion
from core.pos import emision
from core.pos.choices import RETENTION_AGENT
from core.security.mixins import GroupPermissionMixin
from core.security.session import get_group

URL_LISTA = 'comprobantes_retenciones'
URL_LIQUIDACIONES = 'comprobantes_liquidaciones'


def tiene_permiso(request, codigo):
    grupo = get_group(request)
    return grupo is not None and grupo.permissions.filter(codename=codigo).exists()


def avisar_resultado(request, comprobante, resultado, nombre='Retención'):
    if resultado.get('resp'):
        nivel = messages.INFO if resultado.get('en_proceso') else messages.SUCCESS
        messages.add_message(request, nivel, resultado.get('mensaje') or f'{nombre} {comprobante.voucher_number_full} autorizada.')
    else:
        messages.error(request, resultado.get('error') or f'No se pudo emitir la {nombre.lower()}.')


class ComprobanteListView(GroupPermissionMixin, TemplateView):
    """Listado con reenvío al SRI y borrado de los no enviados. Las subclases fijan modelo, permisos y textos."""
    model = None
    nombre = ''            # «Retención», «Liquidación»: los dos son femeninos
    contexto = ''          # nombre de la lista en la plantilla
    titulo = ''
    url_lista = ''

    def permiso(self, accion):
        return f'{accion}_{self.model._meta.model_name}'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'title': self.titulo,
                        self.contexto: self.model.objects.select_related('purchase').order_by('-id')[:200],
                        'puede_emitir': tiene_permiso(self.request, self.permiso('add')),
                        'puede_eliminar': tiene_permiso(self.request, self.permiso('delete'))})
        return context

    def post(self, request, *args, **kwargs):
        comprobante = get_object_or_404(self.model, pk=request.POST.get('id'))
        accion = request.POST.get('action')
        try:
            if accion == 'generate_invoice' and tiene_permiso(request, self.permiso('add')):
                avisar_resultado(request, comprobante, comprobante.generate_electronic_invoice(), self.nombre)
            elif accion == 'delete' and tiene_permiso(request, self.permiso('delete')):
                if comprobante.status in emision.BLOQUEAN_BORRADO:
                    messages.error(request, f'Esta {self.nombre.lower()} ya fue enviada al SRI y no se puede eliminar. Para dejarla '
                                            'sin efecto, anúlala en «SRI en línea».')
                else:
                    numero = comprobante.voucher_number_full
                    comprobante.delete()
                    messages.success(request, f'{self.nombre} {numero} eliminada.')
            else:
                messages.error(request, 'Tu perfil no puede realizar esta acción.')
        except Exception as e:
            messages.error(request, str(e))
        return HttpResponseRedirect(reverse(self.url_lista))


class RetencionListView(ComprobanteListView):
    template_name = 'comprobantes/retencion/list.html'
    permission_required = 'view_retencion'
    model, nombre, contexto, titulo, url_lista = Retencion, 'Retención', 'retenciones', 'Comprobantes de retención', URL_LISTA


class LiquidacionListView(ComprobanteListView):
    template_name = 'comprobantes/liquidacion/list.html'
    permission_required = 'view_liquidacioncompra'
    model, nombre, contexto, titulo, url_lista = (LiquidacionCompra, 'Liquidación', 'liquidaciones', 'Liquidaciones de compra',
                                                  URL_LIQUIDACIONES)


class RetencionCrearView(GroupPermissionMixin, TemplateView):
    """Retención sobre una compra: revisar (cálculo sin guardar) y luego emitir."""
    template_name = 'comprobantes/retencion/create.html'
    permission_required = 'add_retencion'

    def get_compra(self):
        from core.pos.models import Purchase
        return get_object_or_404(Purchase.objects.select_related('provider'), pk=self.kwargs['compra'])

    def iniciales(self, compra):
        """(datos del sustento, líneas sugeridas, liquidación). Con una liquidación autorizada de esta compra, la retención
        se hace sobre ella (03): 100 % del IVA (código 3) y renta 311, según la Res. NAC-DGERCGC20-00000061 y la tabla vigente."""
        liq = sl.liquidacion_vigente(compra)
        if liq is None or liq.status not in emision.AUTORIZADOS:
            return {'fecha_doc_sustento': compra.date_joined, 'base_iva': compra.subtotal}, [], None
        grupos = liq.impuestos_por_tarifa()
        gravadas = [(t, b) for t, b, _ in grupos if t > 0]
        inicial = {'cod_doc_sustento': '03', 'num_doc_sustento': liq.voucher_number_full, 'aut_doc_sustento': liq.access_code,
                   'fecha_doc_sustento': liq.emission_date, 'base_0': sum((b for t, b, _ in grupos if t == 0), 0),
                   'base_iva': sum((b for _, b in gravadas), 0), 'valor_iva': liq.total_iva,
                   'tarifa_iva': f'{max((t for t, _ in gravadas), default=15):.2f}'}
        sugeridos = [CodigoRetencion.objects.filter(impuesto=i, codigo=c, activo=True).first() for i, c in (('1', '311'), ('2', '3'))]
        return inicial, [{'codigo': c.pk} for c in sugeridos if c and (c.impuesto == '1' or liq.total_iva > 0)], liq

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        compra = self.get_compra()
        inicial, sugeridas, liquidacion = self.iniciales(compra)
        context.update({
            'title': 'Emitir comprobante de retención', 'compra': compra,
            'vigente': sv.retencion_vigente(compra), 'liquidacion': liquidacion,
            'form': kwargs.get('form') or DocumentoSustentoForm(initial=inicial),
            'lineas': kwargs.get('lineas') or LineasRetencionFormSet(prefix='lineas', initial=sugeridas),
            'resumen': kwargs.get('resumen'),
            'es_agente': self.request.company.retention_agent == RETENTION_AGENT[0][0],
        })
        return context

    def post(self, request, *args, **kwargs):
        compra = self.get_compra()
        form = DocumentoSustentoForm(request.POST)
        lineas = LineasRetencionFormSet(request.POST, prefix='lineas')
        if not (form.is_valid() and lineas.is_valid()):
            return self.render_to_response(self.get_context_data(form=form, lineas=lineas))
        datos = form.cleaned_data
        filas = [(f.cleaned_data['codigo'].pk, f.cleaned_data.get('base'), f.cleaned_data.get('porcentaje'))
                 for f in lineas.forms if f.cleaned_data.get('codigo')]
        try:
            if request.POST.get('action') != 'emitir':
                doc, detalle, total = sv.calcular(datos, filas)
                return self.render_to_response(self.get_context_data(form=form, lineas=lineas, resumen={
                    'doc': doc, 'detalle': detalle, 'total': total,
                    'total_sin_impuestos': doc['base_0'] + doc['base_iva'],
                    'importe_total': doc['base_0'] + doc['base_iva'] + doc['valor_iva']}))
            with transaction.atomic():
                ret = sv.crear(request.company, request.user, compra, datos, filas)
                emision.preparar(ret)   # si la firma o el plan fallan, se deshace: nada salió al SRI
        except Exception as e:
            form.add_error(None, str(e))
            return self.render_to_response(self.get_context_data(form=form, lineas=lineas))
        avisar_resultado(request, ret, ret.generate_electronic_invoice())
        return HttpResponseRedirect(reverse(URL_LISTA))


class LiquidacionCrearView(GroupPermissionMixin, TemplateView):
    """Liquidación de compra sobre una compra: revisar (cálculo sin guardar) y luego emitir."""
    template_name = 'comprobantes/liquidacion/create.html'
    permission_required = 'add_liquidacioncompra'

    def get_compra(self):
        from core.pos.models import Purchase
        return get_object_or_404(Purchase.objects.select_related('provider'), pk=self.kwargs['compra'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        compra = self.get_compra()
        lineas_compra = sl.lineas_de_compra(compra)
        lineas = kwargs.get('lineas') or LineasLiquidacionFormSet(prefix='lineas', initial=[
            {'detalle': linea['detalle'], 'tarifa': f"{linea['tarifa']:.2f}"} for linea in lineas_compra])
        por_detalle = {linea['detalle']: linea for linea in lineas_compra}
        filas = []
        for f in lineas.forms:
            detalle = f['detalle'].value()
            filas.append((f, por_detalle.get(int(detalle)) if str(detalle or '').isdigit() else None))
        context.update({
            'title': 'Emitir liquidación de compra', 'compra': compra, 'vigente': sl.liquidacion_vigente(compra),
            'form': kwargs.get('form') or LiquidacionForm(initial={'tipo_identificacion': sl.tipo_sugerido(compra.provider.ruc),
                                                                   'direccion': compra.provider.address or ''}),
            'lineas': lineas, 'filas': filas, 'resumen': kwargs.get('resumen'),
        })
        return context

    def post(self, request, *args, **kwargs):
        compra = self.get_compra()
        form = LiquidacionForm(request.POST)
        lineas = LineasLiquidacionFormSet(request.POST, prefix='lineas')
        if not (form.is_valid() and lineas.is_valid()):
            return self.render_to_response(self.get_context_data(form=form, lineas=lineas))
        elegidas = {f.cleaned_data['detalle']: (f.cleaned_data['tarifa'], f.cleaned_data.get('descripcion') or '')
                    for f in lineas.forms if f.cleaned_data.get('detalle')}
        try:
            if request.POST.get('action') != 'emitir':
                doc, detalle, totales = sl.calcular(compra, form.cleaned_data, elegidas)
                return self.render_to_response(self.get_context_data(form=form, lineas=lineas, resumen={
                    'doc': doc, 'detalle': detalle, **totales}))
            with transaction.atomic():
                liq = sl.crear(request.company, request.user, compra, form.cleaned_data, elegidas)
                emision.preparar(liq)   # si la firma o el plan fallan, se deshace: nada salió al SRI
        except Exception as e:
            form.add_error(None, str(e))
            return self.render_to_response(self.get_context_data(form=form, lineas=lineas))
        avisar_resultado(request, liq, liq.generate_electronic_invoice(), 'Liquidación')
        return HttpResponseRedirect(reverse(URL_LIQUIDACIONES))
