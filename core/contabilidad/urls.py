from django.urls import path

from core.contabilidad import views, vistas_capacidades, vistas_cuentas, vistas_diario, vistas_importar_cuentas, vistas_inicio
from core.contabilidad import vistas_apertura   # bloque 2 · Parte B

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
    # Inicio contable (C1 del contrato contable v9)
    path('api/inicio/', vistas_inicio.InicioApi.as_view(), name='contabilidad_inicio'),
    # Plan de cuentas por empresa (C2 del contrato contable v9)
    path('api/cuentas/', vistas_cuentas.CuentasApi.as_view(), name='contabilidad_cuentas'),
    path('api/cuentas/<int:pk>/', vistas_cuentas.CuentaApi.as_view(), name='contabilidad_cuenta'),
    # Importación del plan de cuentas con vista previa (C3)
    path('api/cuentas/importar/', vistas_importar_cuentas.ImportarCuentasApi.as_view(), name='contabilidad_cuentas_importar'),
    path('api/cuentas/importar/<int:pk>/', vistas_importar_cuentas.ImportacionApi.as_view(), name='contabilidad_cuentas_importacion'),
    path('api/cuentas/importar/<int:pk>/mapeo/', vistas_importar_cuentas.MapeoApi.as_view(),
         name='contabilidad_cuentas_importacion_mapeo'),
    path('api/cuentas/importar/<int:pk>/confirmar/', vistas_importar_cuentas.ConfirmarApi.as_view(),
         name='contabilidad_cuentas_importacion_confirmar'),
    # Bloque 2 · Parte A (libro diario, vistas_diario.py): cuentas/clasificar/, diario/, diario/<id>/, integridad/.
    # Sus rutas van aquí debajo, antes del comentario de la Parte B: cada parte escribe solo en su tramo.
    path('api/cuentas/clasificar/', vistas_cuentas.ClasificarApi.as_view(), name='contabilidad_cuentas_clasificar'),
    path('api/diario/', vistas_diario.DiarioApi.as_view(), name='contabilidad_diario'),
    path('api/diario/<int:pk>/', vistas_diario.AsientoApi.as_view(), name='contabilidad_asiento'),
    path('api/integridad/', vistas_diario.IntegridadApi.as_view(), name='contabilidad_integridad'),

    # Bloque 2 · Parte B (inicio y apertura, vistas_apertura.py): apertura/… Sus rutas van aquí debajo.
    path('api/apertura/', vistas_apertura.AperturaApi.as_view(), name='contabilidad_apertura'),
    path('api/apertura/importar/<int:pk>/', vistas_apertura.LoteApi.as_view(), name='contabilidad_apertura_lote'),
    path('api/apertura/respaldos/<int:pk>/descargar/', vistas_apertura.DescargarRespaldoApi.as_view(),
         name='contabilidad_apertura_respaldo_descargar'),
    path('api/apertura/respaldos/<int:pk>/anular/', vistas_apertura.AnularRespaldoApi.as_view(),
         name='contabilidad_apertura_respaldo_anular'),
    path('api/apertura/<int:pk>/', vistas_apertura.AperturaDetalleApi.as_view(), name='contabilidad_apertura_detalle'),
    path('api/apertura/<int:pk>/importar/', vistas_apertura.ImportarApi.as_view(), name='contabilidad_apertura_importar'),
    path('api/apertura/<int:pk>/mapear/', vistas_apertura.MapearApi.as_view(), name='contabilidad_apertura_mapear'),
    path('api/apertura/<int:pk>/lineas/', vistas_apertura.LineasApi.as_view(), name='contabilidad_apertura_lineas'),
    path('api/apertura/<int:pk>/respaldos/', vistas_apertura.RespaldosApi.as_view(), name='contabilidad_apertura_respaldos'),
    path('api/apertura/<int:pk>/descartar/', vistas_apertura.DescartarApi.as_view(), name='contabilidad_apertura_descartar'),

    # Bloque 2 · corte 2 (Partes C a F: vistas_apertura.py, vistas_cartera_inicial.py, vistas_historico.py).
]
