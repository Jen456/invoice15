from django.urls import path

from core.tenancy import views

urlpatterns = [
    path('', views.company_select, name='company_select'),
    path('cambiar/', views.company_switch, name='company_switch'),
]
