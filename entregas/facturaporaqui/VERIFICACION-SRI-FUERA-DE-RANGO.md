# Verificación de comprobantes recibidos fuera del rango del SRI

## Caso reproducido

Factura de Corporación El Rosado 078-015-000909168, emitida el 01/01/2026. La consulta oficial pública la mostró autorizada. El SOAP de producción `AutorizacionComprobantesOffline` respondió `RECHAZADA`, código 80 y detalle de fecha fuera del rango. El SOAP `ConsultaComprobante` respondió `RECHAZADA`, código 99 y el mismo detalle.

Al reproducir la primera respuesta con Suds 1.2.0, la implementación anterior devolvió `no_autorizado` y la corregida `fuera_de_rango`. Los estados no reconocidos quedan pendientes de confirmación. Una respuesta explícita de no autorización mantiene el rechazo. El detalle del documento muestra el resultado, la hora de consulta y un enlace al portal oficial cuando la fecha queda fuera del rango.

## Integración

**Actualizado en la primera entrega:** esta corrección se integró y se amplió en `primera-entrega/verificar-sri.md`.
El fuera de rango dejó de ser un estado propio (`fuera_rango_sri`). Ahora es una consulta fallida, «No se pudo verificar
en el SRI», con el resultado `fuera_de_rango` en el último intento y el mismo enlace al portal. La migración
`importacion.0009` traduce los estados. Después de desplegar, la factura de El Rosado debe mostrar **No se pudo
verificar: fecha fuera del rango de la consulta del SRI** si el SRI repite la misma respuesta.

- El cambio conserva el flujo de autorización del emisor y los permisos y pasos de revisión de la compra. La consulta manual en el portal es independiente de la verificación del XML.
