# Cierre actual y siguiente entrega para Claude

Fecha: 02/11/2026. Este documento sustituye la lista de pendientes del informe antiguo de `fase/adjuntos-comprobantes c5e04a9`, no los contratos vigentes.

> **Estado (Claude, 02/11/2026):** integración, verificación y captura rápida cerradas. Entregas 1 a 5 cerradas en backend, con su contrato en HANDOFF; la 4 (ATS) y la 5 (104/103) esperan la revisión del contador con el paquete ficticio de `revision-contador/`. Vista del contador: `/tributario/empresas/`. De la 6, solo el kardex es independiente de D5, D6, D7 y D9 (entrega aparte). Nada publicado.

## Punto de partida comprobado

- GitHub `plataforma`: `5041f56`. Ya incluye reparto de adjuntos/cobros, consulta mensual y ZIP comunes, nacimiento opcional y correcciones de concurrencia de la Entrega 1.
- El informe que sitúa `plataforma` en `4a39a1a` y pide fusionar `c5e04a9` está desactualizado. **No fusionar la rama superada.**
- `frontend/etapa3` ya contiene `5041f56`, la corrección de los mensajes de solicitud de factura y la mejora de gastos/consulta mensual. Esta entrega añade la ficha completa de cobros, locales/puntos, filtros y guía PDF. Código de esta entrega: `a80622b`; cierre de pruebas en HANDOFF y RESULTADOS-FRONTEND.
- Nada de esta entrega se ha publicado. Codex no opera producción.

## Orden inmediata para Claude

1. Haz fetch, lee las entradas nuevas de HANDOFF y compara las ramas actuales. Integra `frontend/etapa3` en `plataforma` sin reescribir historial y conservando las secciones de ambos agentes. No reconstruyas cambios existentes ni vuelvas a fusionar adjuntos por separado.
2. Verifica los contratos de la ficha de cobros y puntos con la suite PostgreSQL y el navegador. Prueba el reintento con la misma clave, permisos, saldos, separación entre empresas, dos formularios abiertos con puntos distintos y ambas procedencias de la consulta mensual. No emitas documentos reales.
3. Implementa **solo la captura pendiente de gasto por recibo y/o nota**, según `REVISION-GASTOS-Y-RESPALDOS-NUBE.md`: guardar ahora; completar o vincular después. Reutiliza almacenamiento y permisos actuales, sin un segundo módulo de subidas, sin OCR y sin IA. Una captura pendiente no crea compra, gasto, pago, asiento ni crédito tributario. Completar o vincular debe ser idempotente y no duplicar el archivo ni el gasto. La revisión mensual debe distinguir nota registrada, archivo, pendiente de completar y revisión; no declarar revisados los históricos.
4. Deja en HANDOFF el contrato exacto de esa captura (campos, endpoints, estados, permisos, respuestas y ejemplos ficticios). Codex implementa su interfaz y guía sobre ese contrato; no se simulará guardado antes de tenerlo.
5. Entrega un commit acotado por cambio, pruebas y migraciones si hacen falta. Informa hash realmente subido, resultados y bloqueo concreto. Si no hay bloqueo, termina esta entrega; no abras módulos nuevos durante ella.

La corrección X-R1 y las decisiones fiscales pendientes conservan su registro propio: no darlas por resueltas por esta integración. La prueba intermitente de concurrencia de mejora de plan debe informarse con su resultado real, sin convertir una repetición aislada en una suite completa aprobada.

## Siguientes entregas contables, en el orden pedido por la propietaria

| Entrega | Alcance cerrado | Condición para darla por terminada |
| --- | --- | --- |
| 1. Importación masiva | Pegar varias claves o cargar un formato reconocido del reporte del SRI; reutilizar los lotes/importadores existentes. Vista previa, resultado por fila, reanudación, duplicados y confirmación antes de incorporar. | Reintentar un lote no duplica documentos; datos de proveedor/ATS prellenados con procedencia visible; lo que no se obtiene queda pendiente. No inventar acceso a servicios o datos que el SRI no entregue. |
| 2. Libros mensuales | Ventas, compras y retenciones efectuadas/recibidas, separados por tarifa, XLSX y CSV con los datos disponibles para ATS. | Totales contrastados con documentos y sus estados; trazabilidad hasta cada registro; decimales exactos, notas/anulaciones tratadas según reglas verificadas y exportaciones que no ejecuten fórmulas de texto. |
| 3. Revisión del mes | Devueltos, datos ATS incompletos, respaldos pendientes, numeración y cuentas vencidas. Una falta de retención se muestra como revisión posible, no como incumplimiento automático. | Cada observación enlaza a los documentos y explica por qué aparece. Un salto de numeración no prueba una omisión. No bloquear ni certificar un cierre contable inexistente. |
| 4. ATS | XML con el esquema oficial vigente, validación y lista de errores/advertencias. | XSD y fuentes versionados, período correcto, ejemplo ficticio revisado por contador. Pasar XSD no equivale a aceptación del SRI. |
| 5. Hojas del 104 y 103 | Borradores por casillero con tabla de mapeo por vigencia y detalle de documentos. | Mapeo respaldado por fuente oficial y validado por contador; sin presentar declaraciones ni llamarlas automáticas. |
| 6. Bancos y núcleo contable | Conciliación, plan de cuentas, diario/mayor, asientos desde operaciones verificadas, kardex, balance de comprobación y estados financieros. Después: cierre, 101 y Supercias. | Debe/haber cuadran, períodos y reversos conservan trazabilidad, saldos conciliados. El 101 no se construye solo con totales de facturas; requiere contabilidad y conciliación tributaria. |

Desarrollar y cerrar una entrega antes de ampliar la siguiente. No prometer estas funciones como disponibles ni fijar el precio del complemento Contable: sigue **Precio por anunciar**.

## Vista del contador con varias empresas

Después de disponer de la revisión mensual, añadir un resumen por membresías autorizadas. Consultar cada empresa en su contexto y conservar RLS; no usar un acceso global que salte el aislamiento. Mostrar empresa, mes, cantidad de pendientes y enlace a su revisión. Al abrir otra empresa, volver a comprobar membresía y permisos. Probar usuario sin membresía, membresía revocada y cambio de empresa con pestañas abiertas.

## Reparto y publicación

- **Claude:** backend, contratos, criterio fiscal respaldado por fuentes, migraciones y pruebas PostgreSQL; publicación únicamente con aprobación de la propietaria y respaldo de base/archivos privados, ensayo y restauración verificados.
- **Codex:** interacción, diseño responsive, accesibilidad, plantillas/JS/CSS, mensajes, capturas, manuales y textos comerciales fieles al estado real.
- Sin emisiones, pagos ni correos reales durante pruebas. Sin modificar históricos a ciegas. El chatbot IA permanece pendiente.
