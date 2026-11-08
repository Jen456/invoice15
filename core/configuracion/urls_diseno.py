"""/configuracion/diseno-factura/: diseño de la factura del comercio (piloto, core/configuracion/diseno.py).

Va en su propio prefijo, como urls_puntos.py: core/configuracion/urls.py se monta en /configuracion/facturacion/ y el módulo
del menú es /configuracion/diseno-factura/ (MODULOS_NUEVOS en core/security/menu.py)."""
from django.urls import path

from core.configuracion import views

urlpatterns = [
    path('', views.DisenoFacturaView.as_view(), name='diseno_factura'),
    path('muestra.pdf', views.DisenoFacturaMuestraView.as_view(), name='diseno_factura_preview'),
]
