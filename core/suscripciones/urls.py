from django.urls import path

from core.suscripciones import views

urlpatterns = [
    path('', views.PlanView.as_view(), name='suscripcion'),
    path('pagar/', views.PagarView.as_view(), name='suscripcion_pagar'),
    path('pago/retorno/', views.RetornoView.as_view(), name='suscripcion_retorno'),
    path('pago/cancelado/', views.CanceladoView.as_view(), name='suscripcion_cancelado'),
    path('pago/<uuid:uuid>/', views.PagoDetalleView.as_view(), name='suscripcion_pago'),
]
