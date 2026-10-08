from datetime import datetime

from core.pos.models import Company
from core.security.models import Dashboard
from core.security.session import get_group, get_module


def site_settings(request):
    dashboard = Dashboard.objects.first()
    parameters = {
        'dashboard': dashboard,
        'date_joined': datetime.now(),
        'menu': 'hzt_body.html' if dashboard is None else dashboard.get_template_from_layout(),
        'company': Company.objects.first()
    }
    return parameters


def session_profile(request):
    return {
        'session_group': get_group(request),
        'session_module': get_module(request),
    }
