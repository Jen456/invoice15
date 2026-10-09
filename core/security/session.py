"""Rol (grupo) y módulo activos.

El rol sale de la membresía del usuario en la empresa activa, que el middleware
de empresas valida en cada petición. La sesión solo guarda identificadores
(serializador JSON de Django).
"""
MODULE_KEY = 'module_id'


def get_group(request):
    """Rol del usuario en la empresa activa.

    Sale de la membresía (validada por el middleware en cada petición). Un
    superusuario que entra en una empresa sin ser miembro actúa como
    Propietario (queda auditado al entrar). Sin empresa activa no hay rol.
    """
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return None
    if not hasattr(request, '_fpa_group'):
        group = None
        membership = getattr(request, 'membership', None)
        if membership is not None:
            group = membership.group
        elif user.is_superuser and getattr(request, 'company', None) is not None:
            from django.contrib.auth.models import Group
            from core.tenancy.models import ROLE_OWNER
            group = Group.objects.filter(name=ROLE_OWNER).first()
        request._fpa_group = group
    return request._fpa_group


def set_group(request, group):
    """Compatibilidad: el rol ya no se elige; lo fija la membresía de la empresa."""
    set_module(request, None)


def ensure_group(request):
    return get_group(request)


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
