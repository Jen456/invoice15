# Comprobantes de pago: guía de uso

**Borrador para revisar antes de publicar.** Corresponde a las pantallas de adjuntos genéricos; Claude debe confirmar su alcance al integrar con el respaldo de ventas y cobros. No sustituye todavía el manual público.

## Adjuntar un archivo a un documento

1. Abre el listado del documento y su opción **Comprobantes de pago** (icono de clip).
2. Comprueba el documento, tercero e importe que aparecen en el encabezado.
3. Elige el archivo o arrástralo a la zona de subida. El límite y los formatos admitidos se muestran ahí mismo.
4. Revisa la clase, referencia, fecha e importe del comprobante. Puedes añadir una descripción para encontrarlo después.
5. Pulsa **Subir comprobante** y espera el resultado. El archivo aparecerá en «Archivos del documento» cuando el servidor confirme su guardado.

Si seleccionas varios archivos, todos reciben los datos que escribiste en ese formulario y se suben uno por uno. Si corresponden a referencias o importes diferentes, súbelos por separado. Los importes de los archivos son datos de respaldo, no nuevos cobros o pagos.

En los formularios que muestran **Comprobante de pago (opcional)** puedes adjuntarlo al crear el registro: se utiliza la referencia, fecha e importe del propio formulario. Si el archivo es rechazado, el servidor no guarda ese registro.

## Revisar el mes

En **Administrativo → Comprobantes de pago**, selecciona el mes y pulsa **Ver mes**. «Pendientes de comprobante» reúne documentos que el sistema identifica sin respaldo adjunto. Abre cada uno para consultar o añadir archivos, según tus permisos.

**Descargar ZIP del mes** reúne los archivos y un índice CSV para el contador. El botón aparece cuando hay archivos. Esta lista no es una declaración tributaria ni confirma la conciliación con el banco.

## Corregir un archivo equivocado

Pulsa **Quitar**, escribe el motivo si corresponde y confirma. El documento deja de tener ese archivo como vigente, pero el original, su autor y la baja siguen en **Historial de archivos quitados**. Quitar el archivo no elimina ni anula el cobro o pago.

Si no aparece «Subir» o «Quitar», revisa tus permisos y el aviso del plan. El acceso de consulta permite ver y descargar los archivos autorizados.

## Si la conexión se interrumpe

Consulta la lista antes de volver a subir. Una respuesta perdida no significa que el servidor no haya guardado el archivo. La pantalla no repite automáticamente la subida y muestra los errores sin ocultar los archivos confirmados. El servidor rechaza el mismo archivo duplicado dentro de un documento.

## Ventas y cobros

La entrega de `core/cobros` permite **comprobante, nota interna o ambos**, con revisión por los responsables autorizados. Tiene un contrato distinto: no hay que guardar el mismo respaldo otra vez en adjuntos genéricos. El lugar definitivo de acceso y su inclusión en el archivo mensual deben confirmarse antes de entregar esta guía a clientes.
