"""/configuracion/puntos/: locales y puntos de emisión (core/configuracion/puntos.py)."""
from django.urls import path

from core.configuracion import views

urlpatterns = [
    path('', views.PuntosView.as_view(), name='configuracion_puntos'),
    path('estado.json', views.PuntosEstadoView.as_view(), name='configuracion_puntos_estado'),
    path('seleccion.json', views.SeleccionView.as_view(), name='configuracion_punto_seleccion'),
    path('seleccionar/', views.SeleccionarView.as_view(), name='configuracion_punto_seleccionar'),
]
