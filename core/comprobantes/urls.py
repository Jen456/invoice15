from django.urls import path

from core.comprobantes import views, vistas_recibidas

urlpatterns = [
    path('retenciones/', views.RetencionListView.as_view(), name='comprobantes_retenciones'),
    path('retenciones/nueva/<int:compra>/', views.RetencionCrearView.as_view(), name='comprobantes_retencion_nueva'),
    path('liquidaciones/', views.LiquidacionListView.as_view(), name='comprobantes_liquidaciones'),
    path('liquidaciones/nueva/<int:compra>/', views.LiquidacionCrearView.as_view(), name='comprobantes_liquidacion_nueva'),
    path('notas-debito/', views.NotaDebitoListView.as_view(), name='comprobantes_notas_debito'),
    path('notas-debito/nueva/<int:venta>/', views.NotaDebitoCrearView.as_view(), name='comprobantes_nota_debito_nueva'),
    path('guias/', views.GuiaListView.as_view(), name='comprobantes_guias'),
    path('guias/nueva/<int:venta>/', views.GuiaCrearView.as_view(), name='comprobantes_guia_nueva'),
    # Etapa 2 (O2): retenciones recibidas de clientes. /add/ a propósito: con el plan vencido, PlanMiddleware
    # bloquea esas páginas.
    path('retenciones-recibidas/', vistas_recibidas.RetencionRecibidaListView.as_view(), name='comprobantes_retenciones_recibidas'),
    path('retenciones-recibidas/add/', vistas_recibidas.RetencionRecibidaBuscarView.as_view(), name='comprobantes_retencion_recibida_buscar'),
    path('retenciones-recibidas/add/<int:venta>/', vistas_recibidas.RetencionRecibidaCrearView.as_view(), name='comprobantes_retencion_recibida_nueva'),
    path('retenciones-recibidas/<int:pk>/', vistas_recibidas.RetencionRecibidaDetalleView.as_view(), name='comprobantes_retencion_recibida'),
]
