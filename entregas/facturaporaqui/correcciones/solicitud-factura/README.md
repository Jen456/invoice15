# Solicitud de factura de la suscripción presentada como «Error»

31/10/2026 · Diagnóstico frontend. Sin publicación ni operaciones sobre pagos reales.

## Causa comprobada

En la base reportada como publicada, `98cfa20`, `templates/vtc_body.html` y `hzt_body.html` concatenan todos los mensajes Django ordinarios y llaman a `message_error(errors)`, sin distinguir su nivel. Esa función fija título «Error» e icono rojo. `PagoDetalleView.post` registra la solicitud y genera **`messages.success`** con el texto «Solicitud recibida. Te enviaremos la factura al correo indicado.». La página posterior muestra «Ya la solicitaste» cuando `invoice_requested` es verdadero.

La captura coincide con ese fallo de presentación; no prueba un rechazo de PayPhone. No se consultó la base de producción ni se comprobó la entrega de correo del cliente. Sus datos, referencia de pago y captura no se incorporan a esta entrega.

La corrección general ya existe desde `adbe62f` y está incluida en `plataforma=4a39a1a` y en frontend: `fp_mensajes.html` presenta éxito, advertencia, información y error según el nivel del servidor, una sola vez y con escape HTML. No hay que reprogramar el backend ni cambiar indiscriminadamente `message_error()` a éxito, porque también se usa para errores reales.

## Solicitar no equivale a emitir

`core/suscripciones/servicios.py::solicitar_factura` guarda la petición/datos y programa un aviso a la dirección interna de facturación. El contrato actual indica emisión manual por la plataforma. No genera el XML/PDF ni envía por sí mismo una factura emitida al cliente. Un fallo del aviso SMTP se registra en el log y no revierte el pago ni la solicitud.

Claude debe comprobar en modo lectura si existe la solicitud y si llegó el aviso interno, y confirmar quién la atenderá. No repetir un cobro ni reenviar/emitir documentos reales para diagnosticar el icono. La emisión automática, si se desea después, es otra tarea con su contrato.

## Corrección aislada para evaluar una publicación urgente

[mensajes-por-nivel.patch](mensajes-por-nivel.patch) extrae exclusivamente estas cuatro plantillas de la corrección existente, respecto a `98cfa20`:

- `templates/fp_mensajes.html` (componente nuevo).
- `templates/vtc_body.html` y `templates/hzt_body.html` (include y retirada del bucle que convierte todos los avisos en errores).
- `templates/hzt_dashboard.html` (también incluye el componente porque sustituye el bloque de contenido).

Los avisos de plan/configuración mantienen sus componentes. El parche utiliza las clases Bootstrap ya disponibles; no necesita el resto del rediseño, nuevas dependencias o migraciones. El CSS de marca de `98cfa20` se usó en la revisión visual.

Claude: confirmar primero el commit realmente desplegado. Si sigue en esta base, revisar `git apply --check` y el diff del parche en una copia aislada de esa versión. Si ya tiene `fp_mensajes` integrado, comprobar las plantillas servidas y el proceso de aplicación antes de aplicar de nuevo. No se propone publicar toda la fase contable para corregir este aviso. Cualquier publicación sigue requiriendo la aprobación de la propietaria, respaldo y verificaciones habituales; Codex no despliega.

## Pruebas de esta entrega

- Se amplió `tests/test_suscripciones.py::TestPagos::test_solicitar_factura` para recorrer POST → redirección → página en los layouts vertical y horizontal. Comprueba solicitud guardada, aviso único de éxito, pago aprobado por el mismo importe y ausencia de número de factura emitida.
- Dos casos adicionales de correo inválido: error en el campo, sin solicitud/aviso de éxito ni aviso interno, pago intacto.
- En la rama actual, los cuatro casos junto con `TestMensajesEnPantalla`: **11 aprobadas** en 16,30 s.
- Con las tres plantillas antiguas en una carpeta de prueba prioritaria: los dos casos de solicitud válida **fallan por la ausencia del aviso de éxito**, reproduciendo el defecto; la solicitud sí se guardó. Sin cambiar backend.
- `git apply --check` sobre la copia de plantillas de `98cfa20`: correcto. Aplicado allí el parche, las mismas **11 pruebas pasan** en 14,38 s.
- Backend actual, SQLite ficticia y correo en memoria en todas estas comprobaciones. No se ejecutó el backend entero de `98cfa20`, PostgreSQL ni producción; la sustitución controlada aísla el problema de presentación.

Navegador y capturas: [evidencia](../../capturas/solicitud-factura/README.md). No se completaron pagos, emisiones o correos reales. La única modificación de código de esta entrega en la rama principal es la ampliación de pruebas; las plantillas activas ya estaban corregidas.
