from django.urls import path

from core.comprobantes import views

urlpatterns = [
    path('retenciones/', views.RetencionListView.as_view(), name='comprobantes_retenciones'),
    path('retenciones/nueva/<int:compra>/', views.RetencionCrearView.as_view(), name='comprobantes_retencion_nueva'),
    path('liquidaciones/', views.LiquidacionListView.as_view(), name='comprobantes_liquidaciones'),
    path('liquidaciones/nueva/<int:compra>/', views.LiquidacionCrearView.as_view(), name='comprobantes_liquidacion_nueva'),
    path('notas-debito/', views.NotaDebitoListView.as_view(), name='comprobantes_notas_debito'),
    path('notas-debito/nueva/<int:venta>/', views.NotaDebitoCrearView.as_view(), name='comprobantes_nota_debito_nueva'),
]
