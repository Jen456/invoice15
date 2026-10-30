from django.urls import path

from core.adjuntos import views

# La API responde siempre JSON ('/api/' en la ruta: el PlanMiddleware no redirige). La regla de plan se hereda del módulo
# del documento (servicios.permisos), no de estas rutas.
urlpatterns = [
    path('', views.ComprobantesDelMes.as_view(), name='adjuntos_mes'),
    path('zip/', views.ZipDelMes.as_view(), name='adjuntos_zip'),
    path('api/quitar/<int:pk>/', views.QuitarAdjunto.as_view(), name='adjunto_quitar'),   # antes que <tipo>/<id>/
    path('api/<str:tipo>/<int:documento_id>/', views.AdjuntosDocumento.as_view(), name='adjuntos_documento'),
    path('<int:pk>/archivo/', views.ArchivoAdjunto.as_view(), name='adjunto_archivo'),
]
