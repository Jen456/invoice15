# Cobros, gastos y locales: guía de uso

**Edición de revisión · 2 de noviembre de 2026.** Describe la versión integrada y el diseño de esta entrega, todavía pendientes de publicación. Úsala para revisar el flujo con empresas ficticias; entregar a clientes después de que Claude publique y compruebe las pantallas. Complementa el manual general.

## Un respaldo se registra una sola vez

| Lo que necesitas | Dónde hacerlo |
| --- | --- |
| Respaldar el pago al contado de una factura | Facturas emitidas → Opciones → **Cobros y respaldos** |
| Cobrar una factura a crédito | Cuentas por cobrar → **Cobros y respaldos** o **Nuevo registro** |
| Adjuntar el recibo de una compra, gasto o pago a proveedor | En ese documento → **Comprobantes de pago** |
| Revisar respaldos de todo el mes | Administrativo → **Comprobantes de pago** |
| Incorporar una factura electrónica recibida | **Importación de documentos**, con su XML, RIDE o clave según las opciones disponibles |

Un comprobante bancario respalda un movimiento. No reemplaza la factura tributaria. Evita subir el mismo archivo otra vez desde otro módulo: la consulta mensual reúne los respaldos existentes.

## Factura al contado

Al crear la factura, elige la condición **Contado** y el **medio de cobro**. Efectivo recibido y cambio se usan únicamente con efectivo. Para transferencia u otro medio, adjunta el comprobante, escribe una nota interna o conserva ambos. En efectivo son opcionales.

Para una factura ya registrada, abre **Opciones → Cobros y respaldos → Añadir respaldo**. Comprueba la factura y su total, elige el medio, escribe la referencia si la tienes y añade la nota o archivo. Pulsa **Revisar antes de guardar** y después **Confirmar**. Esta acción documenta el contado; no crea otra cuenta por cobrar.

Se admiten **PDF, JPG y PNG, hasta 5 MB**. La nota admite 500 caracteres. Ni la nota ni el archivo se imprimen en el RIDE o ticket, ni se incluyen en el XML o correos del comprobante.

## Factura a crédito y abonos

Una factura a crédito sin abono no requiere respaldo de cobro al emitirla. Cuando recibas dinero:

1. Abre su ficha **Cobros y respaldos** desde Facturas emitidas o Cuentas por cobrar.
2. Pulsa **Registrar cobro**, elige el medio e indica importe y fecha.
3. Adjunta el comprobante o escribe una nota interna.
4. Comprueba los datos y pulsa **Confirmar**.

**Confirmar el cobro crea un abono y reduce el saldo**, aunque su respaldo siga pendiente de revisión. No uses esta acción si solo deseas consultar. Para revisar un abono ya registrado, utiliza su respaldo existente. Una cuenta originada en una nota de débito conserva su flujo propio de abonos en Cuentas por cobrar.

## Revisar y corregir

- **Pendiente de revisión:** falta que el responsable compruebe el respaldo.
- **Revisado:** el responsable dejó registrada su revisión.
- **Rechazado:** el responsable detectó un problema y escribió el motivo.

Propietario y Administrador revisan. El Vendedor registra los respaldos permitidos y corrige los suyos mientras están pendientes. Contador y Consulta los consultan según sus permisos. La pantalla muestra únicamente las acciones autorizadas por el servidor.

**Revisar o rechazar un respaldo no cambia el saldo ni revierte el abono.** Si el cobro fue registrado por error, debe corregirse desde Cuentas por cobrar con el permiso correspondiente. Su historial se conserva. «Revisado» tampoco significa conciliado con el banco.

**Corregir respaldo** permite actualizar nota, referencia o archivo. Si no eliges otro archivo, se conserva el actual. El anterior permanece en el historial al sustituirlo. Un respaldo que estaba revisado vuelve a pendiente al corregirse. Puedes consultar autor, fecha, revisión y cambios mediante **Ver historial**.

Si una respuesta se pierde, consulta la ficha. **Reintentar el mismo envío** conserva la clave del intento mientras permanezcas en esa página, para evitar un segundo abono. No recargues ni abras otro registro para repetirlo a ciegas. Si ya recargaste, verifica primero el saldo y los abonos registrados.

## Gastos cotidianos

En **Compras y gastos → Gastos → Nuevo registro**, completa tipo de gasto, fecha, importe y descripción. Puedes escribir en la descripción una nota útil, por ejemplo: «Taxi de la oficina a la bodega, pagado por Ana».

Adjunta el recibo si lo tienes. Referencia y datos adicionales se muestran aparte. El archivo y el gasto se envían juntos: si el archivo no es válido, el registro no se guarda. En gastos, compras y pagos se admiten **PDF, JPG, PNG y WEBP, hasta 8 MB por archivo y 10 por documento**.

**Límite de esta versión:** todavía no existe una bandeja para guardar solo una foto o nota y completar el gasto después. Tampoco la descripción del gasto cuenta por sí sola como respaldo en el filtro mensual. No inventes importes ni proveedores para eludir los campos: esa captura pendiente requiere una entrega de backend.

## Revisar el mes y entregar al contador

En **Administrativo → Comprobantes de pago**, elige el mes. La lista reúne compras, gastos, pagos a proveedores, facturas al contado y cobros a crédito, según tus permisos. Cada fila identifica su origen y permite abrir el respaldo correspondiente.

Usa los filtros de pendientes, notas y revisión para localizar lo que falta. **Descargar ZIP del mes** reúne los archivos y un índice CSV con origen, respaldo y revisión. También está disponible cuando solo hay notas. Las notas internas se incluyen en el índice; comparte la descarga únicamente con las personas autorizadas.

La lista y el ZIP no constituyen una declaración tributaria ni una conciliación bancaria. Adjuntar o quitar un archivo de compra, gasto o pago no cambia su importe ni elimina el movimiento. **Quitar** conserva autor, fecha y motivo en el historial.

## Locales y puntos de emisión

Abre **Configuración → Locales y puntos de emisión**. Un establecimiento identifica el local registrado para tu RUC; dentro de él puedes tener varios puntos, como Caja principal o Ventas web. Ejemplo: «Local Norte · Caja principal · 002-001».

1. **Agregar local:** copia código y dirección del establecimiento registrado en el SRI; añade un nombre fácil de reconocer. Registrarlo en la aplicación no lo registra en el SRI.
2. **Agregar punto:** elige el local, su código de tres dígitos y una descripción.
3. **Numeración:** configura cada tipo de documento y ambiente. Si vienes de otro sistema, usa el último número realmente utilizado. Comprueba antes de confirmar; las numeraciones usadas no se reinician.
4. **Usuarios:** asigna los puntos permitidos cuando necesites restringirlos. Sin autorizaciones explícitas, el usuario puede usar todos los puntos activos. Propietario y Administrador usan todos. **Quitar la última autorización devuelve el acceso a todos; no bloquea al usuario.**

El selector de la cabecera guarda tu punto preferido para documentos nuevos, por usuario y empresa. Cada formulario abierto conserva su propio punto. Si necesitas cambiarlo en esa factura, usa **Local y punto de este documento** dentro del formulario y comprueba el número mostrado.

La vista previa no reserva numeración. Si falta configuración, aparece el requisito que indica el servidor. En los listados de facturas y notas de crédito, el filtro de local/punto sirve para consultar y no cambia la preferencia de emisión.
