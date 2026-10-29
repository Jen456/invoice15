from django.urls import path

from core.importacion import views

urlpatterns = [
    # Páginas de los módulos del menú
    path('nueva/', views.NuevaImportacion.as_view(), name='importacion_nueva'),
    path('lotes/', views.Lotes.as_view(), name='importacion_lotes'),
    path('lotes/<int:pk>/', views.Lote.as_view(), name='importacion_lote'),
    path('pendientes/', views.Pendientes.as_view(), name='importacion_pendientes'),
    path('recibidos/', views.Recibidos.as_view(), name='importacion_recibidos'),
    path('documentos/<int:pk>/', views.Documento.as_view(), name='importacion_documento'),
    path('documentos/<int:pk>/compra/', views.CompraDesdeDocumento.as_view(), name='importacion_compra'),
    path('documentos/<int:pk>/retencion-recibida/', views.RetencionRecibidaDesdeDocumento.as_view(),
         name='importacion_retencion_recibida'),
    path('reglas/', views.Reglas.as_view(), name='importacion_reglas'),
    path('archivos/<int:pk>/descargar/', views.DescargarArchivo.as_view(), name='importacion_descargar'),
    # API JSON (contrato en entregas/facturaporaqui/HANDOFF.md)
    path('api/lotes/', views.LotesApi.as_view(), name='importacion_api_lotes'),
    path('api/lotes/<int:pk>/', views.LoteApi.as_view(), name='importacion_api_lote'),
    path('api/lotes/<int:pk>/archivos/', views.ArchivosLoteApi.as_view(), name='importacion_api_archivos'),
    path('api/lotes/<int:pk>/procesar/', views.ProcesarLoteApi.as_view(), name='importacion_api_procesar'),
    path('api/entradas/<int:pk>/clave/', views.ClaveEntradaApi.as_view(), name='importacion_api_clave'),
    path('api/documentos/', views.DocumentosApi.as_view(), name='importacion_api_documentos'),
    path('api/documentos/<int:pk>/', views.DocumentoApi.as_view(), name='importacion_api_documento'),
    path('api/documentos/<int:pk>/verificar/', views.VerificarDocumentoApi.as_view(), name='importacion_api_verificar'),
    path('api/documentos/<int:pk>/revisar/', views.RevisarDocumentoApi.as_view(), name='importacion_api_revisar'),
    path('api/documentos/<int:pk>/compra/', views.CompraDesdeDocumentoApi.as_view(), name='importacion_api_compra'),
    path('api/reglas/', views.ReglasApi.as_view(), name='importacion_api_reglas'),
]
