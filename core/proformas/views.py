"""Pantallas de Proformas: lista, crear, editar, ficha, eliminar y PDF.

Patrón: GroupPermissionMixin con el permiso de la pantalla, acciones por POST en `action` y respuestas JSON. Los errores
van como {"error": texto} (más "campos" si los hay) con el estado HTTP de ErrorProforma; cualquier otro fallo se registra
y responde 500 con un texto genérico. Ningún texto escrito por el usuario va a los `messages` de Django.
"""
import json
import logging

from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView, View

from core.pos.choices import PAYMENT_METHOD
from core.proformas import servicios as sv
from core.proformas.models import Proforma
from core.security.mixins import GroupPermissionMixin

logger = logging.getLogger(__name__)

URL_LISTA = sv.URL_LISTA
ERROR_GENERICO = 'No se pudo completar la acción.'


def url_ver(pk):
    return f'{URL_LISTA}ver/{pk}/'


def url_editar(pk):
    return f'{URL_LISTA}update/{pk}/'


def responder(atender):
    try:
        return atender()
    except sv.ErrorProforma as e:
        datos = {'error': e.mensaje}
        if e.campos:
            datos['campos'] = e.campos
        return JsonResponse(datos, status=e.estado_http)
    except Exception:  # noqa: BLE001 - se registra; el usuario recibe un texto genérico
        logger.exception('Falló una acción de proformas')
        return JsonResponse({'error': ERROR_GENERICO}, status=500)


def sin_opcion():
    return JsonResponse({'error': sv.MENSAJES['sin_opcion']}, status=400)


def fila_de(pk, ctx):
    return sv.fila(Proforma.objects.select_related('venta', 'vendedor').get(pk=pk), **ctx)


def configuracion_acciones():
    return {'max_destinatarios': sv.MAX_DESTINATARIOS, 'max_mensaje': sv.MAX_MENSAJE, 'max_motivo': sv.MAX_MOTIVO,
            'url_lista': URL_LISTA}


class ProformaListView(GroupPermissionMixin, TemplateView):
    template_name = 'proformas/list.html'
    permission_required = 'view_proforma'

    def get_context_data(self, **kwargs):
        from core.suscripciones.middleware import mensaje_de_bloqueo
        from core.suscripciones.servicios import estado_de_peticion
        context = super().get_context_data(**kwargs)
        ctx = sv.contexto_de_peticion(self.request)
        puede_crear = 'add_proforma' in ctx['permisos'] and not ctx['plan_vencido']
        context.update({
            'title': 'Proformas', 'list_url': URL_LISTA, 'puede_crear': puede_crear,
            'create_url': f'{URL_LISTA}add/' if puede_crear else None,
            'estados': Proforma.ESTADOS_VISIBLES, 'solo_consulta': ctx['plan_vencido'],
            'mensaje_plan': mensaje_de_bloqueo(estado_de_peticion(self.request)) if ctx['plan_vencido'] else None,
            'config': configuracion_acciones(),
        })
        return context

    def post(self, request, *args, **kwargs):
        return responder(lambda: self.atender(request, request.POST.get('action', '')))

    def atender(self, request, accion):
        ctx = sv.contexto_de_peticion(request)
        datos = request.POST
        if accion == 'search':
            proformas = sv.consultar(datos.get('estado', ''), datos.get('desde', ''), datos.get('hasta', ''),
                                     datos.get('q', ''), ctx['hoy'])
            return JsonResponse([sv.fila(p, **ctx) for p in proformas], safe=False)
        if accion == 'search_detalle':
            return JsonResponse({'proforma': sv.detalle(sv.obtener(datos.get('id')), **ctx)})
        if accion == 'duplicar':
            sv._exigir(ctx['permisos'], 'duplicar')
            copia, avisos = sv.duplicar(datos.get('id'), request.user)
            copia = sv.obtener(copia.pk)
            return JsonResponse({'proforma': sv.detalle(copia, **ctx), 'url_editar': url_editar(copia.pk), 'avisos': avisos,
                                 'mensaje': sv.MENSAJES['duplicada'].format(numero=copia.numero_completo,
                                                                            origen=copia.origen.numero_completo)})
        if accion in sv.TRANSICIONES:
            sv._exigir(ctx['permisos'], accion)
            p = sv.cambiar_estado(datos.get('id'), accion, request.user, datos.get('motivo', ''), request)
            return JsonResponse({'proforma': fila_de(p.pk, ctx),
                                 'mensaje': sv.MENSAJES['estado_cambiado'].format(numero=p.numero_completo,
                                                                                  estado=sv._estado_en_texto(p, ctx['hoy']))})
        if accion == 'enviar_correo':
            sv._exigir(ctx['permisos'], 'enviar_correo')
            p = sv.enviar_por_correo(datos.get('id'), request.user, datos.get('destinatarios', ''), datos.get('mensaje', ''),
                                     request)
            # aviso: la proforma cambió de estado mientras salía el correo (se registró el envío sin tocar ese estado).
            return JsonResponse({'proforma': fila_de(p.pk, ctx), 'aviso': p.aviso_envio is not None,
                                 'mensaje': p.aviso_envio or sv.MENSAJES['enviada'].format(numero=p.numero_completo,
                                                                                           destinatarios=p.enviada_a)})
        return sin_opcion()


class BusquedasMixin:
    """Buscadores del editor: productos (incluidos los sin stock: el stock solo se informa) y clientes de la empresa."""

    def buscar(self, request, accion):
        from core.pos.models import Client, Product
        datos = request.POST
        if accion == 'search_product':
            try:
                excluir = [i for i in (sv._entero(x) for x in json.loads(datos.get('ids') or '[]')) if i is not None]
            except (TypeError, ValueError):
                excluir = []
            productos = Product.objects.select_related('category').exclude(id__in=excluir).order_by('name')
            termino = datos.get('term', '').strip()[:sv.MAX_BUSQUEDA]
            if termino:
                productos = productos.filter(Q(name__icontains=termino) | Q(code__icontains=termino))
            return JsonResponse([dict(p.toJSON(), value=p.get_full_name()) for p in productos[:10]], safe=False)
        if accion == 'search_product_code':
            codigo = datos.get('code', '').strip()
            producto = Product.objects.select_related('category').filter(code=codigo).first() if codigo else None
            return JsonResponse(dict(producto.toJSON(), value=producto.get_full_name()) if producto else {})
        if accion == 'search_client':
            termino = datos.get('term', '').strip()[:sv.MAX_BUSQUEDA]
            clientes = Client.objects.select_related('user').filter(Q(user__names__icontains=termino) | Q(dni__icontains=termino))
            return JsonResponse([c.toJSON() for c in clientes.order_by('user__names')[:10]], safe=False)
        return None

    def contexto_editor(self, context, title, action, proforma=None):
        context.update({'title': title, 'action': action, 'list_url': URL_LISTA, 'formas_pago': PAYMENT_METHOD,
                        'config': sv.configuracion_editor(), 'proforma': proforma, 'aviso_estado': None})
        return context


class ProformaCreateView(BusquedasMixin, GroupPermissionMixin, TemplateView):
    template_name = 'proformas/form.html'
    permission_required = 'add_proforma'

    def get_context_data(self, **kwargs):
        return self.contexto_editor(super().get_context_data(**kwargs), 'Nueva proforma', 'add')

    def post(self, request, *args, **kwargs):
        return responder(lambda: self.atender(request, request.POST.get('action', '')))

    def atender(self, request, accion):
        if accion == 'add':
            p = sv.obtener(sv.crear(request.POST, request.user).pk)
            return JsonResponse({'proforma': sv.detalle(p, **sv.contexto_de_peticion(request)),
                                 'mensaje': sv.MENSAJES['guardada'].format(numero=p.numero_completo),
                                 'url_ver': url_ver(p.pk), 'url_editar': url_editar(p.pk)})
        return self.buscar(request, accion) or sin_opcion()


class ProformaUpdateView(BusquedasMixin, GroupPermissionMixin, TemplateView):
    template_name = 'proformas/form.html'
    permission_required = 'change_proforma'

    def get(self, request, *args, **kwargs):
        self.proforma = get_object_or_404(Proforma.objects, pk=kwargs['pk'])
        if self.proforma.estado not in Proforma.PUEDEN_VENCER:
            messages.info(request, sv.MENSAJES['no_editable'].format(numero=self.proforma.numero_completo,
                                                                     estado=sv._estado_en_texto(self.proforma)))
            return HttpResponseRedirect(url_ver(self.proforma.pk))
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        p = sv.obtener(self.proforma.pk)
        context = self.contexto_editor(super().get_context_data(**kwargs), f'Editar proforma {p.numero_completo}', 'edit',
                                       sv.detalle(p, **sv.contexto_de_peticion(self.request)))
        context['aviso_estado'] = sv.AVISO_EDITAR_ENVIADA if p.estado == 'enviada' else None
        return context

    def post(self, request, *args, **kwargs):
        return responder(lambda: self.atender(request, request.POST.get('action', ''), kwargs['pk']))

    def atender(self, request, accion, pk):
        if accion == 'edit':
            p, mensaje = sv.editar(pk, request.POST, request.user)
            p = sv.obtener(p.pk)
            return JsonResponse({'proforma': sv.detalle(p, **sv.contexto_de_peticion(request)), 'mensaje': mensaje,
                                 'url_ver': url_ver(p.pk), 'url_editar': url_editar(p.pk)})
        return self.buscar(request, accion) or sin_opcion()


class ProformaDetailView(GroupPermissionMixin, TemplateView):
    template_name = 'proformas/detalle.html'
    permission_required = 'view_proforma'

    def get_context_data(self, **kwargs):
        from core.pos.models import impuestos_por_tarifa
        context = super().get_context_data(**kwargs)
        try:
            p = sv.obtener(self.kwargs['pk'])
        except sv.ErrorProforma:
            raise Http404(sv.MENSAJES['no_existe'])
        lineas = list(p.detalles.all())
        context.update({'title': f'Proforma {p.numero_completo}', 'list_url': URL_LISTA, 'p': p, 'lineas': lineas,
                        'impuestos': impuestos_por_tarifa(lineas),
                        'proforma': sv.detalle(p, **sv.contexto_de_peticion(self.request)),
                        'config': configuracion_acciones()})
        return context


class ProformaDeleteView(GroupPermissionMixin, TemplateView):
    template_name = 'proformas/delete.html'
    permission_required = 'delete_proforma'

    def get(self, request, *args, **kwargs):
        self.proforma = get_object_or_404(Proforma.objects, pk=kwargs['pk'])
        if 'eliminar' not in sv._acciones_de_estado(self.proforma):
            messages.info(request, sv.MENSAJES['eliminar_no'])
            return HttpResponseRedirect(url_ver(self.proforma.pk))
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({'title': f'Eliminar la proforma {self.proforma.numero_completo}', 'list_url': URL_LISTA,
                        'object': self.proforma})
        return context

    def post(self, request, *args, **kwargs):
        def atender():
            sv.eliminar(kwargs['pk'], request.user, request)
            return JsonResponse({})
        return responder(atender)


class ProformaPdfView(GroupPermissionMixin, View):
    permission_required = 'view_proforma'

    def get(self, request, *args, **kwargs):
        p = get_object_or_404(Proforma.objects.select_related('company', 'venta', 'vendedor'), pk=kwargs['pk'])
        try:
            pdf = sv.generar_pdf(p)
        except Exception:  # noqa: BLE001 - se registra y se vuelve a la ficha con un aviso
            logger.exception('No se pudo generar el PDF de la proforma %s', p.numero_completo)
            messages.error(request, sv.MENSAJES['pdf_fallo'].format(numero=p.numero_completo))
            return HttpResponseRedirect(url_ver(p.pk))
        respuesta = HttpResponse(pdf, content_type='application/pdf')
        respuesta['Content-Disposition'] = f'inline; filename="{p.numero_completo}.pdf"'
        respuesta['Cache-Control'] = 'private, no-store'
        return respuesta
