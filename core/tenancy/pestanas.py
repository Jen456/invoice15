"""Pestañas abiertas con otra empresa: la página manda para qué empresa se armó (`empresa=<id>` en la consulta o en el
envío) y, si ya no es la activa (se cambió en otra pestaña), el servidor responde 409 `empresa_cambiada` sin crear ni
mostrar nada de la empresa nueva.

Además, toda página con empresa lleva `<meta name="fpa-empresa">` (templates/base.html) y static/js/functions.js manda ese
id en la cabecera X-FPA-Empresa de cada petición AJAX de jQuery al mismo sitio (listados, filtros, gráficos del panel,
guardados): CompanyMiddleware responde 409 si no es la empresa activa, también en las vistas que no miran `empresa`."""
from django.http import JsonResponse

EMPRESA_CAMBIADA = ('La empresa activa cambió en otra pestaña: vuelve a cargar la página para ver los datos de la empresa '
                    'que tienes abierta ahora.')
CABECERA = 'X-FPA-Empresa'


def empresa_cambiada(request):
    """True si el enlace o el formulario se armó para otra empresa que ya no es la activa."""
    pedida = request.GET.get('empresa') or (request.POST.get('empresa') if request.method == 'POST' else None)
    actual = getattr(request, 'company', None)
    return bool(pedida) and str(actual.pk if actual is not None else '') != str(pedida).strip()


def cabecera_de_otra_empresa(request):
    """True si la petición AJAX salió de una página armada para otra empresa (cabecera X-FPA-Empresa). Sin cabecera
    (formularios normales, fetch, pruebas, integraciones) no se decide nada aquí."""
    pedida = request.headers.get(CABECERA, '').strip()
    actual = getattr(request, 'company', None)
    return bool(pedida) and pedida != str(actual.pk if actual is not None else '')


def rechazo_empresa_cambiada(request):
    """409 empresa_cambiada. El validador remoto del dni (diálogo de la factura) lee valid y message, no el código HTTP: así
    el aviso llega igual cuando corta el plan o el permiso del rol en la empresa nueva, y no solo la vista."""
    cuerpo = {'error': EMPRESA_CAMBIADA, 'codigo': 'empresa_cambiada'}
    if request.method == 'POST' and request.POST.get('action') == 'validate_client':
        cuerpo.update(valid=False, message=EMPRESA_CAMBIADA)
    return JsonResponse(cuerpo, status=409)
