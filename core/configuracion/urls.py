from django.urls import path

from core.configuracion import views

urlpatterns = [
    path('', views.InicioView.as_view(), name='configuracion_facturacion'),
    path('paso/<int:paso>/', views.PasoView.as_view(), name='configuracion_paso'),
    path('estado.json', views.EstadoView.as_view(), name='configuracion_estado'),
]
