from django.urls import path

from core.tributario import views

urlpatterns = [
    path('libros/', views.LibrosPagina.as_view(), name='tributario_libros'),
    path('libros/exportar/', views.ExportarLibro.as_view(), name='tributario_libros_exportar'),
    path('api/libros/<str:libro>/', views.LibroApi.as_view(), name='tributario_api_libro'),
    path('ats/', views.AtsPagina.as_view(), name='tributario_ats'),
    path('ats/descargar/', views.DescargarAts.as_view(), name='tributario_ats_descargar'),
    path('api/ats/', views.AtsApi.as_view(), name='tributario_api_ats'),
    path('formularios/', views.FormularioPagina.as_view(), name='tributario_formularios'),
    path('formularios/exportar/', views.ExportarFormulario.as_view(), name='tributario_formularios_exportar'),
    path('api/formularios/', views.FormularioApi.as_view(), name='tributario_api_formularios'),
    path('revision/', views.RevisionPagina.as_view(), name='tributario_revision'),
    path('api/revision/', views.RevisionApi.as_view(), name='tributario_api_revision'),
    path('empresas/', views.EmpresasPagina.as_view(), name='tributario_empresas'),
    path('api/empresas/', views.EmpresasApi.as_view(), name='tributario_api_empresas'),
]
