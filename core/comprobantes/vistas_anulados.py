"""Pantalla «Marcar como anulado en el SRI», común a los seis comprobantes emitidos (Etapa 2, O2).

Solo registra en FacturaPorAquí una anulación que la empresa ya hizo en SRI en línea: no llama al SRI, no devuelve cupo
ni envía correos (core/pos/anulados.py). Permiso change_anulado_sri_<modelo> según el slug (desconocido → 404); un
comprobante de otra empresa → 404. La ruta termina en /update/: con el plan vencido, PlanMiddleware la bloquea.
"""
import logging

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.views.generic import TemplateView

from core.comprobantes.forms_recibidas import AnuladoSRIForm
from core.pos import anulados
from core.security.mixins import GroupPermissionMixin

logger = logging.getLogger(__name__)

# El texto fijo obligatorio («Esto solo registra en FacturaPorAquí…») está escrito en la plantilla anulado/marcar.html.


def _receptor(slug, doc):
    if slug == 'factura':
        return f'{doc.client.user.names} · {doc.client.dni}'
    if slug == 'nota-credito':
        return f'{doc.sale.client.user.names} · {doc.sale.client.dni}'
    return f'{doc.razon_social} · {doc.identificacion}'


def _total(slug, doc):
    return {'factura': lambda: doc.total, 'nota-credito': lambda: doc.total, 'retencion': lambda: doc.total_retenido,
            'liquidacion': lambda: doc.importe_total, 'nota-debito': lambda: doc.valor_total}.get(slug, lambda: None)()


class MarcarAnuladoView(GroupPermissionMixin, TemplateView):
    template_name = 'comprobantes/anulado/marcar.html'

    def get_permissions(self):
        return [anulados.permiso(self.kwargs['modelo'])]   # slug desconocido → Http404

    def get_doc(self):
        return anulados.obtener(self.kwargs['modelo'], self.kwargs['pk'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slug = self.kwargs['modelo']
        doc = kwargs.get('doc') or self.get_doc()
        nombre, url_lista = anulados.MODELOS[slug][2], anulados.MODELOS[slug][4]
        fecha = kwargs.get('fecha') or timezone.localdate()
        revision = anulados.revisar(doc, fecha)
        muestra_stock = slug in ('factura', 'nota-credito') and bool(revision['stock'])
        anulado = None
        if anulados.esta_anulado(doc):
            anulado = {'fecha': doc.anulado_sri_fecha, 'motivo': doc.anulado_sri_motivo,
                       'por': doc.anulado_sri_por.names if doc.anulado_sri_por_id else '',
                       'registrado_en': doc.anulado_sri_registrado_en}
        form = kwargs.get('form') or AnuladoSRIForm(numero=doc.voucher_number_full, muestra_stock=muestra_stock,
                                                    limite_plazo=revision['limite_plazo'],
                                                    initial={'fecha': timezone.localdate()})
        context.update({
            'title': f'Marcar como anulada en el SRI: {nombre} {doc.voucher_number_full}', 'modelo': slug, 'nombre': nombre,
            'doc': doc, 'numero': doc.voucher_number_full, 'fecha_emision': anulados.fecha_emision(doc),
            'receptor': _receptor(slug, doc), 'total': _total(slug, doc), 'autorizacion': doc.access_code or '',
            'impedimentos': [] if anulado else revision['impedimentos'], 'avisos': revision['avisos'],
            'efectos': revision['efectos'], 'muestra_stock': muestra_stock, 'limite_plazo': revision['limite_plazo'],
            'pide_confirmar_plazo': revision['pide_confirmar_plazo'], 'form': form, 'url_lista': url_lista,
            'anulado': anulado,
        })
        return context

    def post(self, request, *args, **kwargs):
        slug = self.kwargs['modelo']
        doc = self.get_doc()
        if request.POST.get('action') != 'marcar':
            return self.render_to_response(self.get_context_data(doc=doc))
        revision = anulados.revisar(doc)
        muestra_stock = slug in ('factura', 'nota-credito') and bool(revision['stock'])
        form = AnuladoSRIForm(request.POST, numero=doc.voucher_number_full, muestra_stock=muestra_stock,
                              limite_plazo=revision['limite_plazo'])
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(doc=doc, form=form, fecha=form.cleaned_data.get('fecha')))
        datos = form.cleaned_data
        try:
            with transaction.atomic():
                anulados.marcar(request.company, request.user, slug, doc, datos['fecha'], datos['motivo'],
                                ajustar_stock=datos.get('ajustar_stock', False), confirmo_plazo=datos.get('confirmo_plazo', False),
                                request=request)
        except anulados.ErrorAnulacion as e:
            form.add_error(None, str(e))
            return self.render_to_response(self.get_context_data(doc=self.get_doc(), form=form, fecha=datos['fecha']))
        except Exception as e:   # un receptor de anulado_en_sri falló: la transacción se deshizo y no se guardó nada
            logger.exception('No se pudo marcar como anulado en el SRI %s %s', slug, doc.pk)
            form.add_error(None, f'No se pudo marcar: falló un ajuste relacionado ({e.__class__.__name__}). No se guardó '
                                 'nada; inténtalo de nuevo o avisa a soporte.')
            return self.render_to_response(self.get_context_data(doc=self.get_doc(), form=form, fecha=datos['fecha']))
        messages.success(request, f'La {anulados.MODELOS[slug][2]} {doc.voucher_number_full} quedó marcada como anulada en '
                                  'el SRI. No se envió nada al SRI.')
        return HttpResponseRedirect(anulados.MODELOS[slug][4])
