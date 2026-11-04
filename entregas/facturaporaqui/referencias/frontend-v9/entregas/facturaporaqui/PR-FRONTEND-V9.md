La captura de facturas necesitaba una secuencia más clara, errores junto a los campos y un uso móvil legible. Esta propuesta organiza cliente, productos, pago y revisión, conserva los datos al corregir errores y mantiene el contrato del PR #1: precio por línea, alta rápida y respaldo opcional sin efectivo recibido/cambio.

Incluye seis pantallas contables navegables con datos simulados, identificadas como propuestas: plan de cuentas e importación, asientos por comprobante, revisión del mes, reportes provisionales, piloto pendiente y máximo interno de tres puntos. No confirma importaciones, cobros, asientos ni verificaciones. Las acciones sin backend están deshabilitadas.

**Base:** `codex/facturacion-captura-agil-20261103` (PR #1, `817c5be`). Es un PR dependiente de esa entrega; no incorpora código de `Jen456/invoice15` ni modifica sus ramas. Sin cambios en backend, modelos, formularios Python, migraciones o endpoints.

**Validación:** 11 pruebas Django SQLite y 2 Node aprobadas; 87 comprobaciones Chromium a 360/390/768/1024/1360/1440 px; 31 capturas; sin errores JS ni desbordes. Navegador con respuestas API simuladas y plantilla real. No se probó el guardado en producción ni PostgreSQL. Guía de revisión en PDF de dos páginas.

**Pendientes de revisión:** recibir el Word versión 9; confirmar propiedad de archivos y contratos contables con Claude; resolver la diferencia de pagos frente al backend de invoice15 y si las notas deben ser internas. El piloto NEXALLTI conserva el estado de Excel pendiente.

Ver `entregas/facturaporaqui/HANDOFF.md`, `RESULTADOS-FRONTEND.md` y `CONTRATO-FRONTEND-PENDIENTE.md`. No desplegar.
