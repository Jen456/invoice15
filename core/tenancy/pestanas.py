"""Pestañas abiertas con otra empresa: la página manda para qué empresa se armó (`empresa=<id>` en la consulta o en el
envío) y, si ya no es la activa (se cambió en otra pestaña), el servidor responde 409 `empresa_cambiada` sin crear ni
mostrar nada de la empresa nueva.

En el envío, `empresa` viaja como campo del formulario (POST) o, si el cuerpo es JSON (POST, PATCH…), como `"empresa"` del
objeto: así el plan y el permiso del rol también responden 409 antes que su 403 cuando la pestaña mandó JSON."""
import json

from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.http.request import RawPostDataException

EMPRESA_CAMBIADA = ('La empresa activa cambió en otra pestaña: vuelve a cargar la página para ver los datos de la empresa '
                    'que tienes abierta ahora.')


def cuerpo_json(request):
    """El objeto JSON de un envío (dict), leído una sola vez por petición. None si el envío no es JSON, si no se puede leer
    (mal formado, demasiado grande) o si no es un objeto: quien necesite distinguirlo responde su propio error."""
    if not hasattr(request, '_fpa_cuerpo_json'):
        datos = None
        if request.method not in ('GET', 'HEAD') and (getattr(request, 'content_type', '') or '').startswith('application/json'):
            try:
                datos = json.loads(request.body or b'null')
            except (ValueError, RecursionError, RawPostDataException, RequestDataTooBig):
                datos = None
        request._fpa_cuerpo_json = datos if isinstance(datos, dict) else None
    return request._fpa_cuerpo_json


def empresa_pedida(request):
    """Empresa para la que se armó el enlace o el envío (como llegó), o None: `?empresa=`, el campo del formulario o, en un
    envío JSON, `"empresa"` del cuerpo."""
    pedida = request.GET.get('empresa') or (request.POST.get('empresa') if request.method == 'POST' else None)
    if not pedida:
        pedida = (cuerpo_json(request) or {}).get('empresa')
    return pedida


def empresa_cambiada(request):
    """True si el enlace o el formulario se armó para otra empresa que ya no es la activa."""
    pedida = empresa_pedida(request)
    actual = getattr(request, 'company', None)
    return bool(pedida) and str(actual.pk if actual is not None else '') != str(pedida).strip()


def rechazo_empresa_cambiada(request):
    """409 empresa_cambiada. El validador remoto del dni (diálogo de la factura) lee valid y message, no el código HTTP: así
    el aviso llega igual cuando corta el plan o el permiso del rol en la empresa nueva, y no solo la vista."""
    cuerpo = {'error': EMPRESA_CAMBIADA, 'codigo': 'empresa_cambiada'}
    if request.method == 'POST' and request.POST.get('action') == 'validate_client':
        cuerpo.update(valid=False, message=EMPRESA_CAMBIADA)
    return JsonResponse(cuerpo, status=409)
