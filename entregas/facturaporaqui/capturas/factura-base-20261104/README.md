# Facturas reutilizables y RUC del servicio en el pie — 04/11/2026

Empresas, personas, productos y documentos ficticios. Las capturas de la aplicación usan Django local con SQLite; no son capturas de producción. La empresa de demostración no tiene firma electrónica configurada y su aviso permanece visible. No se hicieron emisiones, pagos ni correos reales.

- `listado-opcion-1360.jpg`: nueva opción con foco de teclado.
- `nueva-desde-base-{360,390,768,1024,1360,1440}.jpg`: cliente por seleccionar y número de la nueva factura.
- `productos-{360,768,1360}.jpg`: líneas cargadas, cantidad, precio y descuento.
- `aviso-stock-390.jpg`: cantidad original conservada, revisión necesaria.
- `error-recuperable-390.jpg`: fallo de carga inyectado y reintento.
- `precio-vendedor-390.jpg`: precio vigente del catálogo con explicación.
- `sin-permiso-390.jpg`: respuesta 403 real del servidor en la vista previa.
- `ride-*.pdf`: seis tipos de RIDE de una página, más factura de 90 líneas largas (7 páginas). El RUC del proveedor del servicio aparece una vez en cada pie. `ride-factura.png` es la captura del PDF corto.

Resultados estructurados: `navegador-verificacion.json` y `pdf-verificacion.json`. Los PNG/JPG de esta carpeta pesan menos de 150 KB cada uno. Las pruebas de servidor y JavaScript están documentadas en RESULTADOS-FRONTEND.md; las pruebas específicas se incluyen en `tests/test_factura_base.py` y `tests/frontend/factura_base.test.cjs`.
