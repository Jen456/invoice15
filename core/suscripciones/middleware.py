"""Acceso a los módulos de facturación y ventas según el plan de la empresa activa.

- Sin plan pagado (gratuito): los módulos de pago no se abren.
- Plan vencido: se consultan los comprobantes, pero no se crea ni se emite nada.
- Cupo agotado (en producción): todo sigue abierto salvo emitir.
La comprobación definitiva al emitir está en cupo.emitir_con_cupo; esto evita
llegar a formularios que no se podrán guardar.
"""
from django.contrib import messages
from django.http import HttpResponseRedirect, JsonResponse
from django.utils import timezone

from core.security.session import get_group
from core.suscripciones.reglas import URL_SUSCRIPCION, es_emision, requiere_plan
from core.suscripciones.servicios import estado_de_peticion

ESCRITURA = ('/add/', '/update/', '/delete/')
ACCIONES_DE_CONSULTA = ('send_invoice_by_email',)


def puede_gestionar_plan(request):
    if request.user.is_superuser:
        return True
    group = get_group(request)
    return group is not None and group.groupmodule_set.filter(module__url=URL_SUSCRIPCION).exists()


def mensaje_de_bloqueo(estado):
    if estado.gratuito:
        return ('La facturación y las ventas se activan con un plan anual. '
                'Mientras tanto puedes usar el inventario con el plan gratuito.')
    if estado.vencido:
        return (f'Tu {estado.ultimo.plan.name} venció el {timezone.localtime(estado.ultimo.ends_at):%d/%m/%Y}. '
                'Puedes consultar tus comprobantes; renueva el plan para volver a emitir.')
    p = estado.periodo
    return (f'Usaste los {p.document_limit} documentos de tu {p.plan.name}. '
            'Renueva o pasa al plan ilimitado para seguir emitiendo.')


def _solo_consulta(request):
    if request.method == 'GET':
        return not any(parte in request.path for parte in ESCRITURA)
    accion = request.POST.get('action', '')
    return accion.startswith('search') or accion in ACCIONES_DE_CONSULTA


class PlanMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request, 'company', None) is not None and request.user.is_authenticated \
                and requiere_plan(request.path):
            estado = estado_de_peticion(request)
            if estado.gratuito \
                    or estado.vencido and (es_emision(request) or not _solo_consulta(request)) \
                    or estado.codigo == 'cupo_agotado' and es_emision(request):
                return self.bloquear(request, mensaje_de_bloqueo(estado))
        return self.get_response(request)

    def bloquear(self, request, mensaje):
        if request.method == 'GET':
            messages.warning(request, mensaje)
            return HttpResponseRedirect(URL_SUSCRIPCION if puede_gestionar_plan(request) else '/dashboard/')
        return JsonResponse({'error': mensaje, 'plan': 'requerido'}, status=403)
