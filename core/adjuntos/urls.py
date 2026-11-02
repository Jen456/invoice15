from django.urls import path

from core.adjuntos import views

# La API responde siempre JSON ('/api/' en la ruta: el PlanMiddleware no redirige). La regla de plan se hereda del módulo
# del documento (servicios.permisos), no de estas rutas. Las rutas de capturas van ANTES de api/<tipo>/<id>/, que si no
# las capturaría con tipo='capturas'.
urlpatterns = [
    path('', views.ComprobantesDelMes.as_view(), name='adjuntos_mes'),
    path('zip/', views.ZipDelMes.as_view(), name='adjuntos_zip'),
    path('capturas/', views.CapturasPagina.as_view(), name='adjuntos_capturas'),
    path('capturas/<int:pk>/archivo/', views.ArchivoCaptura.as_view(), name='captura_archivo'),
    path('api/capturas/', views.CapturasApi.as_view(), name='capturas_api'),
    path('api/capturas/documentos/', views.DocumentosParaVincular.as_view(), name='capturas_documentos'),
    path('api/capturas/<int:pk>/', views.CapturaApi.as_view(), name='captura_api'),
    path('api/capturas/<int:pk>/completar/', views.CompletarCaptura.as_view(), name='captura_completar'),
    path('api/capturas/<int:pk>/vincular/', views.VincularCaptura.as_view(), name='captura_vincular'),
    path('api/capturas/<int:pk>/descartar/', views.DescartarCaptura.as_view(), name='captura_descartar'),
    path('api/capturas/<int:pk>/nota/', views.NotaCaptura.as_view(), name='captura_nota'),
    path('api/quitar/<int:pk>/', views.QuitarAdjunto.as_view(), name='adjunto_quitar'),   # antes que <tipo>/<id>/
    path('api/<str:tipo>/<int:documento_id>/', views.AdjuntosDocumento.as_view(), name='adjuntos_documento'),
    path('<int:pk>/archivo/', views.ArchivoAdjunto.as_view(), name='adjunto_archivo'),
]
