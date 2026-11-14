from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse

from core.security.session import MODULE_KEY
from core.tenancy import context
from core.tenancy.models import Membership
from core.tenancy.pestanas import cabecera_de_otra_empresa, rechazo_empresa_cambiada

SESSION_KEY = 'company_id'
# Rutas que no necesitan empresa activa (todo lo demás redirige al selector, también «/»: el panel consulta datos de
# la empresa y, sin empresa elegida, respondía 500 a quien tiene varias).
NO_COMPANY_PREFIXES = ('/login/', '/registro/', '/empresas/', '/static/', '/plataforma/', '/media/',
                       '/user/update/password/', '/user/update/profile/',
                       # Retorno de PayPhone: se confirma por la referencia del pago, sin empresa activa.
                       '/suscripcion/pago/retorno/', '/suscripcion/pago/cancelado/')
PLATFORM_PREFIX = '/plataforma/'


def resolve_company(request):
    """(empresa, membresía) activas para el usuario, validadas en cada petición."""
    from core.pos.models import Company
    user = request.user
    memberships = Membership.objects.active().filter(user=user).select_related('company', 'group')
    company_id = request.session.get(SESSION_KEY)
    if company_id is not None:
        membership = memberships.filter(company_id=company_id).first()
        if membership is not None:
            return membership.company, membership
        if user.is_superuser:
            company = Company.objects.filter(pk=company_id, is_active=True).first()
            if company is not None:
                return company, None
        # La empresa guardada ya no vale (membresía o empresa desactivada, o un id ajeno): tampoco su última página ni
        # su módulo, como al cambiar de empresa (company_switch).
        for clave in (SESSION_KEY, 'url_last', MODULE_KEY):
            request.session.pop(clave, None)
    only = list(memberships[:2])
    if len(only) == 1:
        request.session[SESSION_KEY] = only[0].company_id
        return only[0].company, only[0]
    return None, None


class CompanyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = None
        request.membership = None
        platform = False
        if request.user.is_authenticated:
            if request.path.startswith(PLATFORM_PREFIX):
                platform = request.user.is_superuser
            else:
                request.company, request.membership = resolve_company(request)
                if request.company is None and not request.path.startswith(NO_COMPANY_PREFIXES):
                    if request.method == 'GET':
                        return HttpResponseRedirect(reverse('company_select'))
                    return JsonResponse({'error': 'Selecciona una empresa para continuar'}, status=403)
                if request.company is not None and not request.path.startswith(NO_COMPANY_PREFIXES) \
                        and cabecera_de_otra_empresa(request):
                    # AJAX de una pestaña armada para otra empresa: no se responde con datos de la activa (409).
                    return rechazo_empresa_cambiada(request)
        tokens = context.activate(request.company, platform=platform)
        try:
            return self.get_response(request)
        finally:
            context.deactivate(tokens)
