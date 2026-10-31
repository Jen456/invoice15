# Diseño de comprobantes de pago — entrega para integrar

31/10/2026 · Codex · `frontend/etapa3`. **Diseño probado sobre el backend aislado de adjuntos; no publicado ni fusionado ese backend con plataforma.**

## Qué se entrega

- Página mensual con período, descarga ZIP/CSV, indicadores, pendientes y archivo mensual. Tablas que se presentan como fichas en móvil; desplazamiento contenido en tablet, foco visible y acciones de tamaño táctil.
- Modal con documento origen, archivos vigentes, historial desplegable y formulario. Los archivos retirados siguen accesibles según el permiso del servidor. El motivo se confirma dentro del mismo modal, sin abrir un tercer diálogo.
- Selección/arrastre de archivos, lista de espera y resultado por archivo; límites recibidos del servidor. Un lote congela destino y metadatos; no se permite cerrar o abrir otro documento mientras termina. No hay reintentos automáticos de POST.
- Respuesta perdida: consultar nuevamente, explicar la incertidumbre y mostrar la lista del servidor. Si esa consulta confirma un cambio, la página mensual se actualiza al cerrar. Una consulta antigua no reemplaza el contenido de un documento abierto después.
- Campo opcional de adjunto para los formularios que lo incluyen. Se conservan `comprobante`, `comprobante_clase`, las opciones y los datos del contexto.
- Marca colibrí, paleta actual, tipografía legible, mensajes escapados, teclado y movimiento reducido. Abrir un archivo mantiene la ruta privada del servidor; no se incrusta contenido externo.

El indicador dice «Pendientes de comprobante»: `requiere` incluye medios distintos del efectivo, lo que no equivale necesariamente a un pago confirmado por el banco. La descripción y el texto de ayuda aclaran que adjuntar no confirma ni concilia.

## Archivos de diseño

Rutas desde la raíz del repositorio:

- `core/adjuntos/templates/adjuntos/_modal.html`
- `core/adjuntos/templates/adjuntos/_campo_formulario.html`
- `core/adjuntos/templates/adjuntos/mes.html`
- `static/adjuntos/js/adjuntos.js`
- `static/adjuntos/css/adjuntos.css` (compatibilidad con los includes; tema centralizado)
- `static/css/facturaporaqui.css` (bloque final `fp-adjuntos-*`)

Los estáticos nuevos se entregan en `static/` para que sus rutas resuelvan también antes de instalar `core/adjuntos`. Django los encuentra antes que los estáticos homónimos de la app. Al integrar, conservar esta versión y retirar o sincronizar los dos archivos antiguos de `core/adjuntos/static/adjuntos/`, evitando mantener dos implementaciones distintas del mismo recurso. No cambiar las URL públicas `adjuntos/js/adjuntos.js` y `adjuntos/css/adjuntos.css`.

No se añadieron modelos, vistas, servicios, migraciones, permisos, rutas, dependencias ni accesos en listados existentes. Las plantillas permanecen inactivas en plataforma hasta integrar su backend. Se conservan `fpAdjuntos.abrir(tipo, id)`, `data-adjuntos-tipo`, `data-adjuntos-id`, los campos de la API y el evento `fp-adjuntos:cerrado`.

## Base y solapamiento que debe resolver Claude

`plataforma=4a39a1a` ya está incorporado por avance rápido en `frontend/etapa3`. La rama `fase/adjuntos-comprobantes=722475a` permanece separada. Se revisó su [contrato exacto](https://github.com/Jen456/invoice15/blob/722475a164b4f4ab8d4246ca61038a156c7b9414/entregas/facturaporaqui/CONTRATO-PANTALLAS-ADJUNTOS.md).

Un ensayo con `git merge-tree --write-tree` identificó conflictos en siete archivos, sin iniciar una fusión en el árbol de trabajo:

- `core/pos/templates/ctas_collect/create.html`
- `core/pos/views/ctas_collect/views.py`
- `core/security/menu.py`
- `core/tenancy/roles.py`
- `entregas/facturaporaqui/HANDOFF.md`
- `tests/test_b0_contratos.py`
- `tests/test_migracion_vuelta_fase.py`

`settings.py` y `urls.py` fusionan textualmente, pero eso no resuelve el solapamiento funcional. **Codex no resolvió conflictos del backend ni eligió una nueva regla de permisos.**

Recomendación para decisión de la propietaria, coincidente con HANDOFF de Claude: ventas/cobros por `core/cobros`; compras/gastos/pagos a proveedores por `core/adjuntos`. Ventas ya admite nota o archivo, revisión e idempotencia, incluso en facturas de contado sin CxC. No añadir una segunda acción para guardar el mismo respaldo.

Antes de integrar el diseño definitivo:

1. Confirmar el reparto funcional y resolver los conflictos conservando ambas entregas de documentación. No perder condición/medio de pago, nota, revisión, idempotencia ni selección de puntos.
2. Definir el alcance del resumen mensual y ZIP: el contrato actual solo cuenta `Adjunto`, no `RespaldoCobro`. Si incluye ventas/cobros, debe recoger la fuente real y distinguir archivo, nota y estado de revisión, sin duplicar ni contar una nota como archivo. Si queda solo para compras/gastos/pagos, entregar textos y filas con ese alcance explícito. No simular esa agregación en JavaScript.
3. Publicar los tipos/acciones autorizados y los datos por fila que usará la interfaz. El diseño mantiene los cinco tipos del contrato original para que la exclusión se decida en servidor; no oculta duplicación de datos con filtros locales.
4. Mantener límites diferenciados mientras no se apruebe otro contrato: adjuntos genéricos PDF/JPG/PNG/WEBP, 8 MB y 10 archivos; respaldo de cobros PDF/JPG/PNG, 5 MB y nota o archivo. No trasladar por CSS permisos del Contador de una app a otra.
5. Revisar `documentos.describir('venta')`: la rama de adjuntos usa `payment_method` (forma SRI); plataforma ya tiene `medio_cobro`. Con la separación propuesta, ventas debe proceder del contrato de cobros. No inferir el medio real de una venta antigua.

No hay decisión de publicación en esta entrega. Claude integra y valida las migraciones del conjunto y PostgreSQL antes de proponer un despliegue con respaldo.

## Cómo se verificó

Backend original `722475a` en un checkout de prueba separado, con las plantillas/estáticos de esta entrega por las rutas de búsqueda de Django. SQLite y empresas ficticias; red fiscal/correo deshabilitados. No se modifica ningún archivo del backend de ese checkout.

- Suites de adjuntos, estáticos, rutas e integración frontend: **46 aprobadas**.
- Sobre `frontend/etapa3` actualizado a `4a39a1a`, estáticos, rutas e integración frontend: **11 aprobadas**. Se comprobó que los estáticos entregados resuelven sin instalar todavía la app.
- Navegador y capturas: [evidencia de adjuntos](../../capturas/adjuntos/README.md).
- Contraste calculado de seis pares de texto/fondo: mínimo **4,75:1**. Foco visible y movimiento reducido.

Estas comprobaciones no equivalen a probar la fusión final de las dos apps, PostgreSQL, un teléfono físico o producción. [Guía de uso para revisar antes de publicar](../../manuales/COMPROBANTES-DE-PAGO.md).
