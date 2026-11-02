# Cierre de cobros y locales — 02/11/2026

Chromium 151, entorno de nube, servidor Django en loopback, SQLite exclusiva de demostración y conexiones externas del servidor bloqueadas. Sin datos reales, firmas ni emisiones. Empresa «DEMO GASTOS — datos ficticios», tres locales; facturas construidas como fixtures, no autorizadas en el SRI. El aviso de firma pendiente se conserva: no se ocultó para las capturas.

## Capturas

JPEG de menos de 150 KB cada uno, a 360, 768 y 1360 px. Son recortes del viewport de 900 px de alto; el contenido restante se desplaza normalmente. Se probó además 390, 1024 y 1440 px.

- `locales-*`: locales, puntos, estados y accesos de configuración.
- `factura-*`: formulario con punto fijado y vista previa de numeración.
- `abono-*`: registro de cobro y respaldo.
- `mes-*`: consulta común de ambas procedencias.
- `respaldo-*`: formulario de nota/archivo dentro de la ficha de cobros.

## Recorrido comprobado

Alta de nota en contado sin CxC; revisión rechazada con motivo; revisión aprobada y corrección que vuelve a pendiente; historial; rechazo de archivo inválido y guardado de PNG; registro de abono a crédito; respuesta perdida después del guardado, reintento con la misma clave y un solo abono; revisión sin cambiar saldo; cancelación; accesos desde factura/CxC; preferencia de punto independiente del formulario; numeración pendiente y respuesta antigua; filtros; usuarios Consulta/Vendedor; teclado, Escape, foco de retorno y movimiento reducido.

Los archivos de resultados JSON guardan las comprobaciones efectivamente ejecutadas. No acreditan pruebas en PostgreSQL, en un teléfono físico ni en producción. No se enviaron formularios de numeración; sus valores finales se contrastaron con el estado inicial de las fixtures.
