from datetime import datetime

from core.security.models import Dashboard
from core.security.session import get_group, get_module
from core.tenancy.models import Membership


def site_settings(request):
    dashboard = Dashboard.objects.first()
    parameters = {
        'dashboard': dashboard,
        'date_joined': datetime.now(),
        'menu': 'hzt_body.html' if dashboard is None else dashboard.get_template_from_layout(),
        'company': getattr(request, 'company', None),
    }
    return parameters


def session_profile(request):
    user = getattr(request, 'user', None)
    memberships = []
    if user is not None and user.is_authenticated:
        memberships = Membership.objects.active().filter(user=user).select_related('company', 'group') \
            .order_by('company__tradename')
    return {
        'session_group': get_group(request),
        'session_module': get_module(request),
        'user_memberships': memberships,
    }
