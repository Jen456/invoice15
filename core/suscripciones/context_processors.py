from core.suscripciones.middleware import puede_gestionar_plan
from core.suscripciones.servicios import estado_de_peticion


def plan(request):
    """Estado del plan de la empresa activa para el aviso de la cabecera y el menú."""
    if getattr(request, 'company', None) is None or not request.user.is_authenticated \
            or request.path.startswith('/plataforma/'):
        return {}
    return {'fpa_plan': estado_de_peticion(request), 'fpa_gestiona_plan': puede_gestionar_plan(request)}
