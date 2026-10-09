"""web URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.0.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path, include

from config import settings
from core.dashboard.views import *
from core.security.views.files import protected_media
from core.tenancy.admin import plataforma

urlpatterns = [
    path('plataforma/', plataforma.urls),
    path('media/<path:path>', protected_media, name='protected_media'),
    path('empresas/', include('core.tenancy.urls')),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('login/', include('core.login.urls')),
    path('registro/', include('core.login.urls_registro')),
    path('pos/', include('core.pos.urls')),
    path('reports/', include('core.reports.urls')),
    path('security/', include('core.security.urls')),
    path('user/', include('core.user.urls')),
    path('', DashboardView.as_view(), name='dashboard'),
]
