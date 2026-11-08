# Verificación de comprobantes recibidos fuera del rango del SRI

## Caso reproducido

Factura de Corporación El Rosado 078-015-000909168, emitida el 01/01/2026. La consulta oficial pública la mostró autorizada. El SOAP de producción `AutorizacionComprobantesOffline` respondió `RECHAZADA`, código 80 y detalle de fecha fuera del rango. El SOAP `ConsultaComprobante` respondió `RECHAZADA`, código 99 y el mismo detalle.

Al reproducir la primera respuesta con Suds 1.2.0, la implementación anterior devolvió `no_autorizado` y la corregida `fuera_de_rango`. Los estados no reconocidos quedan pendientes de confirmación. Una respuesta explícita de no autorización mantiene el rechazo. El detalle del documento muestra el resultado, la hora de consulta y un enlace al portal oficial cuando la fecha queda fuera del rango.

## Integración

- Integra sobre la base vigente y aplica la migración aditiva `importacion.0008_estado_fuera_rango_sri`.
- Ejecuta `tests/test_importacion_xml_pdf.py` y `tests/test_importacion_flujo.py` con el entorno del proyecto. Se añadieron pruebas del caso observado y del botón.
- Repite la consulta desde el detalle de la factura de El Rosado después de desplegar. Debe mostrar **Fecha fuera del rango del SRI** si persiste la misma respuesta. No se deben reimportar ni editar masivamente los estados históricos.
- El cambio conserva el flujo de autorización del emisor y los permisos y pasos de revisión de la compra. La consulta manual en el portal es independiente de la verificación del XML.
