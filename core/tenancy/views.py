from django.contrib.auth.decorators import login_required
from django.utils.http import url_has_allowed_host_and_scheme
from django.http import Http404, HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from config import settings
from core.security.session import set_module
from core.tenancy.middleware import SESSION_KEY
from core.tenancy.models import Membership, audit


def destino_interno(request, destino):
    """`next` del selector: solo una ruta interna de este sitio (p. ej. la revisión del mes desde el resumen del contador o
    un archivo de la empresa abierto por un enlace); cualquier otra cosa (otro sitio, //, \\) vale ''."""
    destino = destino or ''
    if destino.startswith('/') and not destino.startswith('//') and url_has_allowed_host_and_scheme(
            destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return destino
    return ''


@login_required
def company_select(request):
    memberships = Membership.objects.active().filter(user=request.user).select_related('company', 'group') \
        .order_by('company__business_name')
    return render(request, 'tenancy/select.html', {
        'title': 'Selecciona una empresa',
        'memberships': memberships,
        'active_company': getattr(request, 'company', None),
        'destino': destino_interno(request, request.GET.get('next')),   # company_switch la vuelve a validar
    })


@login_required
@require_POST
def company_switch(request):
    """Cambia la empresa activa. Comprueba la membresía en el servidor: el
    identificador enviado solo indica cuál se pide, nunca concede acceso."""
    from core.pos.models import Company
    try:
        company_id = int(request.POST.get('company', ''))
    except ValueError:
        raise Http404
    membership = Membership.objects.active().filter(user=request.user, company_id=company_id) \
        .select_related('company').first()
    if membership is not None:
        company = membership.company
        action = 'company_switch'
    elif request.user.is_superuser:
        company = Company.objects.filter(pk=company_id, is_active=True).first()
        if company is None:
            raise Http404
        action = 'platform_enter'
    else:
        raise Http404
    request.session.cycle_key()
    request.session[SESSION_KEY] = company.pk
    request.session.pop('url_last', None)
    set_module(request, None)
    audit(request, action, company=company)
    destino = destino_interno(request, request.POST.get('next')) or settings.LOGIN_REDIRECT_URL   # `next`: opcional
    if 'application/json' in request.headers.get('Accept', ''):   # diálogo de la factura (R1): confirmación comprobable
        return JsonResponse({'ok': True, 'company': company.pk})
    return HttpResponseRedirect(destino)
