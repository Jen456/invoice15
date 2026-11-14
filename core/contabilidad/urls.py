from django.urls import path

from core.contabilidad import views, vistas_capacidades, vistas_cuentas

urlpatterns = [
    path('kardex/', views.KardexPagina.as_view(), name='contabilidad_kardex'),
    path('kardex/exportar/', views.ExportarKardex.as_view(), name='contabilidad_kardex_exportar'),
    path('inventario/', views.InventarioPagina.as_view(), name='contabilidad_inventario'),
    path('inventario/exportar/', views.ExportarInventario.as_view(), name='contabilidad_inventario_exportar'),
    path('api/kardex/productos/', views.ProductosApi.as_view(), name='contabilidad_kardex_productos'),
    path('api/kardex/movimientos/', views.MovimientosApi.as_view(), name='contabilidad_kardex_movimientos'),
    path('api/kardex/movimientos/<int:pk>/anular/', views.AnularMovimiento.as_view(), name='contabilidad_kardex_anular'),
    path('api/kardex/<int:producto_id>/', views.KardexApi.as_view(), name='contabilidad_kardex_api'),
    path('api/inventario/', views.InventarioApi.as_view(), name='contabilidad_inventario_api'),
    # Contrato de capacidades: responde también con el complemento cerrado o sin plan (reglas.RUTAS_DE_CAPACIDADES).
    path('api/capacidades/', vistas_capacidades.CapacidadesApi.as_view(), name='contabilidad_capacidades'),
    # Plan de cuentas por empresa (C2 del contrato contable v9)
    path('api/cuentas/', vistas_cuentas.CuentasApi.as_view(), name='contabilidad_cuentas'),
    path('api/cuentas/<int:pk>/', vistas_cuentas.CuentaApi.as_view(), name='contabilidad_cuenta'),
]
