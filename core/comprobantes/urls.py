from django.urls import path

from core.comprobantes import views

urlpatterns = [
    path('retenciones/', views.RetencionListView.as_view(), name='comprobantes_retenciones'),
    path('retenciones/nueva/<int:compra>/', views.RetencionCrearView.as_view(), name='comprobantes_retencion_nueva'),
]
