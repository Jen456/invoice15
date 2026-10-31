"""/cobros/: respaldo del cobro (core/cobros)."""
from django.urls import path

from core.cobros import views

urlpatterns = [
    path('factura/<int:venta>/', views.FacturaCobrosView.as_view(), name='cobros_factura'),
    path('factura/<int:venta>/registrar/', views.RegistrarView.as_view(), name='cobros_registrar'),
    path('respaldo/<int:pk>/', views.RespaldoView.as_view(), name='cobros_respaldo'),
    path('respaldo/<int:pk>/editar/', views.EditarView.as_view(), name='cobros_respaldo_editar'),
    path('respaldo/<int:pk>/revisar/', views.RevisarView.as_view(), name='cobros_respaldo_revisar'),
    path('respaldo/<int:pk>/archivo/', views.ArchivoView.as_view(), name='cobros_respaldo_archivo'),
]
