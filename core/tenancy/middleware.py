from django.http import HttpResponseRedirect, JsonResponse
from django.urls import reverse

from core.tenancy import context
from core.tenancy.models import Membership

SESSION_KEY = 'company_id'
# Rutas que no necesitan empresa activa (todo lo demás redirige al selector).
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
        request.session.pop(SESSION_KEY, None)
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
                if request.company is None and not request.path.startswith(NO_COMPANY_PREFIXES) \
                        and request.path != '/':
                    if request.method == 'GET':
                        return HttpResponseRedirect(reverse('company_select'))
                    return JsonResponse({'error': 'Selecciona una empresa para continuar'}, status=403)
        tokens = context.activate(request.company, platform=platform)
        try:
            return self.get_response(request)
        finally:
            context.deactivate(tokens)
