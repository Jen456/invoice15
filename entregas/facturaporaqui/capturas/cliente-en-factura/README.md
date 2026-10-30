# Cliente dentro de la factura — revisión de diseño

Entrega funcional en `frontend/etapa3`, sobre la factura que ya incorpora alta de productos. Datos ficticios; ninguna captura corresponde a un cliente real. Conserva la marca y el flujo Django existente.

| Vista | Captura |
| --- | --- |
| Alta, móvil de 360 px | [Abrir](cliente-360.webp) |
| Alta, tablet de 768 px | [Abrir](cliente-768.webp) |
| Alta, escritorio de 1360 px | [Abrir](cliente-1360.webp) |
| Correo rechazado por el servidor, 360 px | [Abrir](error-360.webp) |
| Cliente existente por identificación, 1360 px | [Abrir](existente-1360.webp) |
| Cliente guardado y seleccionado, 390 px | [Abrir](seleccionado-390.webp) |
| Respuesta de guardado perdida, 390 px | [Abrir](respuesta-perdida-390.webp) |

## Cómo revisar en un entorno local de datos ficticios

1. Abrir `/pos/sale/admin/add/`, elegir un producto y añadir información adicional. No emitir.
2. Pulsar «Crear cliente aquí». Comprobar nombres, identificación según tipo, dirección, fecha, contacto y opciones plegables. La fecha de nacimiento sigue siendo requerida por el backend.
3. Cerrar con Escape y reabrir: los campos deben conservarse. Recargar la página sí pierde el formulario aún no guardado.
4. Introducir un correo adicional inválido y guardar: el servidor debe rechazarlo y el diálogo mostrar el mensaje junto al correo, abrir esa sección y darle foco.
5. Corregirlo y guardar: el cliente debe quedar seleccionado; comprobar que las líneas, importes y datos de la factura siguen iguales. El cliente creado persiste en el catálogo aunque se abandone después la factura.
6. Volver a abrir, escribir la identificación creada y buscar: «Usar este cliente» debe seleccionarlo sin crear otro. No hay consulta automática al SRI.
7. Revisar teclado, foco, cierre y movimiento reducido a 360, 390, 768, 1024, 1360 y 1440 px. El cuerpo del diálogo se desplaza; sus botones no tapan los campos.

Resultados del recorrido de navegador: [verificacion.json](verificacion.json). Fallos controlados: [fallos-controlados.json](fallos-controlados.json). Se interrumpió una respuesta **después** de que el servidor guardara para comprobar la recuperación sin repetir el POST. No equivale a idempotencia implementada en backend.

Sin nuevas dependencias, publicación, emisiones, pagos ni correos reales. Las pruebas de teléfono físico y PostgreSQL corresponden a la siguiente verificación; no se afirman aquí.
