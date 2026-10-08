"""Perfil (grupo) y módulo activos de la sesión.

La sesión solo guarda identificadores (serializador JSON de Django). El grupo se
vuelve a validar contra los grupos del usuario en cada petición: un
identificador manipulado o un grupo que se le retiró al usuario no conceden
acceso.
"""
GROUP_KEY = 'group_id'
MODULE_KEY = 'module_id'


def get_group(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return None
    if not hasattr(request, '_fpa_group'):
        group = None
        group_id = request.session.get(GROUP_KEY)
        if group_id is not None:
            group = user.groups.filter(id=group_id).first()
            if group is None:
                request.session.pop(GROUP_KEY, None)
        request._fpa_group = group
    return request._fpa_group


def set_group(request, group):
    if group is None:
        request.session.pop(GROUP_KEY, None)
    else:
        request.session[GROUP_KEY] = group.id
    request._fpa_group = group
    set_module(request, None)


def ensure_group(request):
    """Asigna el primer grupo del usuario si la sesión todavía no tiene uno."""
    group = get_group(request)
    if group is None and request.user.is_authenticated:
        group = request.user.groups.order_by('id').first()
        if group is not None:
            set_group(request, group)
    return group


def get_module(request):
    if not hasattr(request, '_fpa_module'):
        from core.security.models import Module
        module_id = request.session.get(MODULE_KEY)
        request._fpa_module = Module.objects.filter(id=module_id).first() if module_id else None
    return request._fpa_module


def set_module(request, module):
    if module is None:
        request.session.pop(MODULE_KEY, None)
    else:
        request.session[MODULE_KEY] = module.id
    request._fpa_module = module


def client_ip(request):
    """IP del visitante. nginx fija X-Real-IP (con la IP real de Cloudflare) y
    Gunicorn solo escucha en 127.0.0.1, así que la cabecera es de confianza."""
    return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '')
