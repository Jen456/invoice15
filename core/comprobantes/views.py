"""Comprobantes de retención: emisión desde Compras y listado."""
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.generic import TemplateView

from core.comprobantes import retenciones as sv
from core.comprobantes.forms import DocumentoSustentoForm, LineasRetencionFormSet
from core.comprobantes.models import Retencion
from core.pos import emision
from core.pos.choices import RETENTION_AGENT
from core.security.mixins import GroupPermissionMixin
from core.security.session import get_group

URL_LISTA = 'comprobantes_retenciones'


def tiene_permiso(request, codigo):
    grupo = get_group(request)
    return grupo is not None and grupo.permissions.filter(codename=codigo).exists()


def avisar_resultado(request, ret, resultado):
    if resultado.get('resp'):
        nivel = messages.INFO if resultado.get('en_proceso') else messages.SUCCESS
        messages.add_message(request, nivel, resultado.get('mensaje') or f'Retención {ret.voucher_number_full} autorizada.')
    else:
        messages.error(request, resultado.get('error') or 'No se pudo emitir la retención.')


class RetencionListView(GroupPermissionMixin, TemplateView):
    template_name = 'comprobantes/retencion/list.html'
    permission_required = 'view_retencion'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'title': 'Comprobantes de retención',
                        'retenciones': Retencion.objects.select_related('purchase').order_by('-id')[:200],
                        'puede_emitir': tiene_permiso(self.request, 'add_retencion'),
                        'puede_eliminar': tiene_permiso(self.request, 'delete_retencion')})
        return context

    def post(self, request, *args, **kwargs):
        ret = get_object_or_404(Retencion, pk=request.POST.get('id'))
        accion = request.POST.get('action')
        try:
            if accion == 'generate_invoice' and tiene_permiso(request, 'add_retencion'):
                avisar_resultado(request, ret, ret.generate_electronic_invoice())
            elif accion == 'delete' and tiene_permiso(request, 'delete_retencion'):
                if ret.status in emision.BLOQUEAN_BORRADO:
                    messages.error(request, 'Esta retención ya fue enviada al SRI y no se puede eliminar. Para dejarla sin efecto, '
                                            'anúlala en «SRI en línea».')
                else:
                    numero = ret.voucher_number_full
                    ret.delete()
                    messages.success(request, f'Retención {numero} eliminada.')
            else:
                messages.error(request, 'Tu perfil no puede realizar esta acción.')
        except Exception as e:
            messages.error(request, str(e))
        return HttpResponseRedirect(reverse(URL_LISTA))


class RetencionCrearView(GroupPermissionMixin, TemplateView):
    """Retención sobre una compra: revisar (cálculo sin guardar) y luego emitir."""
    template_name = 'comprobantes/retencion/create.html'
    permission_required = 'add_retencion'

    def get_compra(self):
        from core.pos.models import Purchase
        return get_object_or_404(Purchase.objects.select_related('provider'), pk=self.kwargs['compra'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        compra = self.get_compra()
        inicial = {'fecha_doc_sustento': compra.date_joined, 'base_iva': compra.subtotal}
        context.update({
            'title': 'Emitir comprobante de retención', 'compra': compra,
            'vigente': sv.retencion_vigente(compra),
            'form': kwargs.get('form') or DocumentoSustentoForm(initial=inicial),
            'lineas': kwargs.get('lineas') or LineasRetencionFormSet(prefix='lineas'),
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
