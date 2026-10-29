"""Comprobantes adicionales emitidos desde Compras (retención 07, liquidación de compra 03): emisión y listado."""
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from core.comprobantes import guias as sg
from core.comprobantes import liquidaciones as sl
from core.comprobantes import notas_debito as snd
from core.comprobantes import retenciones as sv
from core.comprobantes.forms import (DocumentoSustentoForm, GuiaForm, LineasGuiaFormSet, LineasLiquidacionFormSet,
                                     LineasRetencionFormSet, LiquidacionForm, MotivosNotaDebitoFormSet, NotaDebitoForm)
from core.comprobantes.models import CodigoRetencion, GuiaRemision, LiquidacionCompra, NotaDebito, Retencion
from core.pos import emision
from core.pos.choices import RETENTION_AGENT
from core.security.mixins import GroupPermissionMixin
from core.security.session import get_group

URL_LISTA = 'comprobantes_retenciones'
URL_LIQUIDACIONES = 'comprobantes_liquidaciones'
URL_NOTAS_DEBITO = 'comprobantes_notas_debito'
URL_GUIAS = 'comprobantes_guias'


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
    relacionados = ('purchase',)
    nombre = ''            # «Retención», «Liquidación», «Nota de débito»: todos femeninos
    contexto = ''          # nombre de la lista en la plantilla
    titulo = ''
    url_lista = ''

    def permiso(self, accion):
        return f'{accion}_{self.model._meta.model_name}'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'title': self.titulo,
                        self.contexto: self.model.objects.select_related(*self.relacionados).order_by('-id')[:200],
                        'puede_emitir': tiene_permiso(self.request, self.permiso('add')),
                        'puede_eliminar': tiene_permiso(self.request, self.permiso('delete'))})
        # Etapa 2 (O2): enlace «Marcar como anulada en el SRI» (core/comprobantes/vistas_anulados.py).
        context['puede_anular'] = tiene_permiso(self.request, f'change_anulado_sri_{self.model._meta.model_name}')
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


class NotaDebitoListView(ComprobanteListView):
    template_name = 'comprobantes/notadebito/list.html'
    permission_required = 'view_notadebito'
    relacionados = ('sale',)
    model, nombre, contexto, titulo, url_lista = NotaDebito, 'Nota de débito', 'notas', 'Notas de débito', URL_NOTAS_DEBITO


class GuiaListView(ComprobanteListView):
    template_name = 'comprobantes/guia/list.html'
    permission_required = 'view_guiaremision'
    relacionados = ('sale',)
    model, nombre, contexto, titulo, url_lista = GuiaRemision, 'Guía de remisión', 'guias', 'Guías de remisión', URL_GUIAS


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


class NotaDebitoCrearView(GroupPermissionMixin, TemplateView):
    """Nota de débito sobre una factura autorizada: revisar (cálculo sin guardar) y luego emitir."""
    template_name = 'comprobantes/notadebito/create.html'
    permission_required = 'add_notadebito'

    def get_venta(self):
        from core.pos.models import Sale
        return get_object_or_404(Sale.objects.select_related('client__user', 'receipt'), pk=self.kwargs['venta'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        venta = self.get_venta()
        try:
            snd.validar_factura(venta, self.request.company)
            impedimento = None
        except snd.ErrorNotaDebito as e:
            impedimento = str(e)
        tarifas = snd.tarifas_permitidas(venta)
        context.update({
            'title': 'Emitir nota de débito', 'venta': venta, 'impedimento': impedimento,
            'anteriores': NotaDebito.objects.filter(sale=venta).order_by('-id'),
            'form': kwargs.get('form') or NotaDebitoForm(tarifas=tarifas, initial={'tarifa_iva': f'{tarifas[0]:.2f}',
                                                                                  'forma_pago': venta.payment_method or '20'}),
            'motivos': kwargs.get('motivos') or MotivosNotaDebitoFormSet(prefix='motivos'),
            'resumen': kwargs.get('resumen'),
        })
        return context

    def post(self, request, *args, **kwargs):
        venta = self.get_venta()
        form = NotaDebitoForm(request.POST, tarifas=snd.tarifas_permitidas(venta))
        motivos = MotivosNotaDebitoFormSet(request.POST, prefix='motivos')
        if not (form.is_valid() and motivos.is_valid()):
            return self.render_to_response(self.get_context_data(form=form, motivos=motivos))
        filas = [(f.cleaned_data.get('razon'), f.cleaned_data.get('valor')) for f in motivos.forms if f.cleaned_data]
        try:
            if request.POST.get('action') != 'emitir':
                snd.validar_factura(venta, request.company)
                doc, limpios, totales = snd.calcular(venta, form.cleaned_data, filas)
                return self.render_to_response(self.get_context_data(form=form, motivos=motivos, resumen={
                    'doc': doc, 'motivos': limpios, **totales}))
            with transaction.atomic():
                nota = snd.crear(request.company, request.user, venta, form.cleaned_data, filas)
                emision.preparar(nota)   # si la firma o el plan fallan, se deshace: nada salió al SRI
        except Exception as e:
            form.add_error(None, str(e))
            return self.render_to_response(self.get_context_data(form=form, motivos=motivos))
        avisar_resultado(request, nota, nota.generate_electronic_invoice(), 'Nota de débito')
        return HttpResponseRedirect(reverse(URL_NOTAS_DEBITO))


class GuiaCrearView(GroupPermissionMixin, TemplateView):
    """Guía de remisión de lo vendido en una factura autorizada: revisar (sin guardar) y luego emitir."""
    template_name = 'comprobantes/guia/create.html'
    permission_required = 'add_guiaremision'

    def get_venta(self):
        from core.pos.models import Sale
        return get_object_or_404(Sale.objects.select_related('client__user', 'receipt'), pk=self.kwargs['venta'])

    def get_context_data(self, **kwargs):
        from core.configuracion.servicios import punto_predeterminado
        context = super().get_context_data(**kwargs)
        venta = self.get_venta()
        try:
            sg.validar_factura(venta, self.request.company)
            impedimento = None
        except sg.ErrorGuia as e:
            impedimento = str(e)
        lineas_factura = sg.lineas_de_factura(venta)
        lineas = kwargs.get('lineas') or LineasGuiaFormSet(prefix='lineas', initial=[
            {'detalle': l['detalle'], 'cantidad': l['pendiente'].normalize()} for l in lineas_factura])
        por_detalle = {l['detalle']: l for l in lineas_factura}
        filas = []
        for f in lineas.forms:
            detalle = f['detalle'].value()
            filas.append((f, por_detalle.get(int(detalle)) if str(detalle or '').isdigit() else None))
        punto = punto_predeterminado(self.request.company)
        partida = (punto.establishment.address if punto else '') or self.request.company.establishment_address or ''
        hoy = timezone.localdate()
        context.update({
            'title': 'Emitir guía de remisión', 'venta': venta, 'impedimento': impedimento,
            'anteriores': GuiaRemision.objects.filter(sale=venta).order_by('-id'),
            'form': kwargs.get('form') or GuiaForm(initial={'fecha_inicio': hoy, 'fecha_fin': hoy, 'dir_partida': partida,
                                                            'direccion': venta.client.address or '', 'motivo': 'Venta'}),
            'lineas': lineas, 'filas': filas, 'resumen': kwargs.get('resumen'),
        })
        return context

    def post(self, request, *args, **kwargs):
        venta = self.get_venta()
        form = GuiaForm(request.POST)
        lineas = LineasGuiaFormSet(request.POST, prefix='lineas')
        if not (form.is_valid() and lineas.is_valid()):
            return self.render_to_response(self.get_context_data(form=form, lineas=lineas))
        cantidades = {f.cleaned_data['detalle']: f.cleaned_data.get('cantidad') for f in lineas.forms if f.cleaned_data.get('detalle')}
        try:
            if request.POST.get('action') != 'emitir':
                sg.validar_factura(venta, request.company)
                doc, detalle = sg.calcular(venta, form.cleaned_data, cantidades)
                return self.render_to_response(self.get_context_data(form=form, lineas=lineas, resumen={'doc': doc, 'detalle': detalle}))
            with transaction.atomic():
                guia = sg.crear(request.company, request.user, venta, form.cleaned_data, cantidades)
                emision.preparar(guia)   # si la firma o el plan fallan, se deshace: nada salió al SRI
        except Exception as e:
            form.add_error(None, str(e))
            return self.render_to_response(self.get_context_data(form=form, lineas=lineas))
        avisar_resultado(request, guia, guia.generate_electronic_invoice(), 'Guía de remisión')
        return HttpResponseRedirect(reverse(URL_GUIAS))
