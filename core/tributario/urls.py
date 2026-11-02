from django.urls import path

from core.tributario import views

urlpatterns = [
    path('libros/', views.LibrosPagina.as_view(), name='tributario_libros'),
    path('libros/exportar/', views.ExportarLibro.as_view(), name='tributario_libros_exportar'),
    path('api/libros/<str:libro>/', views.LibroApi.as_view(), name='tributario_api_libro'),
]
