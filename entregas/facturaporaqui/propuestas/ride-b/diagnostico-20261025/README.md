# Diagnóstico de impresión — 25/10/2026

Muestras ficticias generadas localmente desde **6b2d2c2**, usando el renderizador actual de la aplicación. No son documentos emitidos al SRI ni capturas del servidor.

- [Factura A4 actual](factura-a4-actual-demo.pdf): estilo B, línea coral, tablas celestes, total destacado, RUC Proveedor en Información adicional y pie cursivo con colibrí. No hay logo del emisor porque esta empresa ficticia no lo tiene configurado.
- [Ticket actual, todavía sin rediseño](ticket-actual-demo.pdf): muestra la plantilla antigua de 58 mm; sirve para identificar la diferencia, no como propuesta aprobada de ticket.

Ambos tienen los mismos cinco productos ficticios y total USD 104,00. Los RUC, dirección y correos son de demostración. Capturas correspondientes en `../../../capturas/diagnostico-20261025-factura-a4.png` y `../../../capturas/diagnostico-20261025-ticket.png`.

El botón A4 devuelve el PDF ya guardado si existe. Esto puede explicar un PDF histórico, pero no demuestra la causa del incidente reportado para documentos nuevos. Hace falta comparar el PDF concreto y el proceso que lo generó en producción. Las 40 pruebas locales de impresión/diseño pasan; no reemplazan esa comprobación.
