# Cobros, gastos y locales: guía de uso

**Edición de revisión · 2 de noviembre de 2026.** Describe la versión integrada y el diseño de esta entrega, todavía pendientes de publicación. Úsala para revisar el flujo con empresas ficticias; entregar a clientes después de que Claude publique y compruebe las pantallas. Complementa el manual general.

## Un respaldo se registra una sola vez

| Lo que necesitas | Dónde hacerlo |
| --- | --- |
| Respaldar el pago al contado de una factura | Facturas emitidas → Opciones → **Cobros y respaldos** |
| Cobrar una factura a crédito | Cuentas por cobrar → **Cobros y respaldos** o **Nuevo registro** |
| Guardar un recibo o nota sin completar datos todavía | Compras y gastos → **Recibos por completar** |
| Adjuntar el recibo de una compra, gasto o pago a proveedor | En ese documento → **Comprobantes de pago** |
| Revisar respaldos de todo el mes | Administrativo → **Comprobantes de pago** |
| Incorporar una factura electrónica recibida | **Importación de documentos**, con su XML, RIDE o clave según las opciones disponibles |

Un comprobante bancario respalda un movimiento. No reemplaza la factura tributaria. Evita subir el mismo archivo otra vez desde otro módulo: la consulta mensual reúne los respaldos existentes.

## Precio y descuento de la factura

Propietario y Administrador pueden cambiar el **precio unitario de una línea solo para esa factura**: el catálogo no cambia.
El Vendedor factura al precio del catálogo, o al de la proforma que está facturando. El descuento es un **porcentaje entero**
de 0 a 100. Si la cantidad supera el stock o un dato no es válido, la factura no se guarda y el aviso dice qué línea revisar.

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

## Cuando solo tienes un recibo o una nota

Abre **Compras y gastos → Recibos por completar**. Elige un PDF o una foto, escribe una nota o conserva ambos y pulsa **Guardar para completar después**. Puedes arrastrar un archivo desde el computador. En el teléfono, el selector permite elegir la foto o tomarla según el dispositivo. No necesitas importe, proveedor ni categoría para este primer paso.

**Guardar el recibo no registra un gasto, compra, pago, asiento ni crédito tributario.** Queda en la bandeja de pendientes. Allí, según tus permisos, puedes:

- **Completar como gasto:** elegir categoría, fecha, importe y medio de pago. La referencia es obligatoria con cheque. Conserva el mismo archivo y la nota; no los subas otra vez.
- **Registrar como compra:** si tienes la factura del proveedor, completa sus datos tributarios en Compras.
- **Vincular a un documento ya registrado:** busca la compra, gasto o pago existente para usar ese mismo respaldo. No crea otro documento.
- **Corregir la nota** o **Descartar:** el registro y el archivo permanecen en el historial.

Si la conexión se interrumpe al guardar, usa **Confirmar el envío pendiente** sin cerrar la página. Conserva la clave y el contenido del intento. Si ya cerraste la página, revisa primero la bandeja.

El Vendedor ve sus propios recibos. Las acciones disponibles dependen del perfil y del plan; tener permiso para guardar un recibo no da permiso para consultar documentos ajenos.

## Gastos cotidianos con todos los datos

En **Compras y gastos → Gastos → Nuevo registro**, completa categoría, fecha, importe y medio de pago. Escribe la nota una sola vez: en un gasto nuevo también se conserva como respaldo con tu usuario y fecha. Las descripciones de gastos anteriores no se convierten automáticamente en respaldos.

Adjunta el recibo si lo tienes. Referencia y datos adicionales se muestran aparte. El archivo y el gasto se envían juntos: si el archivo no es válido, el registro no se guarda. En gastos, compras y pagos se admiten **PDF, JPG, PNG y WEBP, hasta 8 MB por archivo y 10 respaldos por documento**.

Desde **Comprobantes de pago** del documento también puedes guardar una nota sin archivo o elegir **Usar un recibo pendiente**. Confirma el documento al que lo vinculas. No hace falta volver a cargarlo en la consulta mensual.

## Revisar el mes y entregar al contador

En **Administrativo → Comprobantes de pago**, elige el mes. La lista reúne compras, gastos, pagos a proveedores, facturas al contado y cobros a crédito, según tus permisos. Cada fila identifica su origen y permite abrir el respaldo correspondiente.

Usa los filtros de pendientes, notas y revisión para localizar lo que falta. **Descargar ZIP del mes** reúne los archivos y un índice CSV con origen, respaldo y revisión. También está disponible cuando solo hay notas o recibos pendientes. Los recibos sin completar aparecen en un bloque separado y en su propia carpeta del ZIP; no cuentan como gastos registrados. Las notas internas se incluyen en el índice; comparte la descarga únicamente con las personas autorizadas.

La lista y el ZIP no constituyen una declaración tributaria ni una conciliación bancaria. Adjuntar o quitar un archivo de compra, gasto o pago no cambia su importe ni elimina el movimiento. **Quitar** conserva autor, fecha y motivo en el historial.

## Locales y puntos de emisión

Abre **Configuración → Locales y puntos de emisión**. Un establecimiento identifica el local registrado para tu RUC; dentro de él puedes tener varios puntos, como Caja principal o Ventas web. Ejemplo: «Local Norte · Caja principal · 002-001».

1. **Agregar local:** copia código y dirección del establecimiento registrado en el SRI; añade un nombre fácil de reconocer. Registrarlo en la aplicación no lo registra en el SRI.
2. **Agregar punto:** elige el local, su código de tres dígitos y una descripción.
3. **Numeración:** configura cada tipo de documento y ambiente. Si vienes de otro sistema, usa el último número realmente utilizado. Comprueba antes de confirmar; las numeraciones usadas no se reinician.
4. **Usuarios:** asigna los puntos permitidos cuando necesites restringirlos. Sin autorizaciones explícitas, el usuario puede usar todos los puntos activos. Propietario y Administrador usan todos. **Quitar la última autorización devuelve el acceso a todos; no bloquea al usuario.**

El selector de la cabecera guarda tu punto preferido para documentos nuevos, por usuario y empresa. Cada formulario abierto conserva su propio punto. Si necesitas cambiarlo en esa factura, usa **Local y punto de este documento** dentro del formulario y comprueba el número mostrado.

La vista previa no reserva numeración. Si falta configuración, aparece el requisito que indica el servidor. En los listados de facturas y notas de crédito, el filtro de local/punto sirve para consultar y no cambia la preferencia de emisión.

## Importación y revisión contable del mes

**Importar por claves o reporte del SRI** admite una lista de hasta 500 claves de acceso, o el reporte TXT, CSV o XLSX del portal (hasta 5 MB). Revisa el resumen de rechazadas y sus motivos. Continúa en el lote, consulta los XML y abre **Incorporar en lote**. Comprueba la selección, los proveedores nuevos y las advertencias antes de confirmar. El avance indica el resultado de cada documento y permite pausar entre partes. Las confirmaciones especiales no se marcan automáticamente.

**Libros mensuales** muestra ventas, compras y retenciones, con los documentos de origen y totales por tarifa. Descarga un libro en XLSX/CSV o los cuatro en XLSX. **Revisión del mes** permite filtrar causas y abrir cada documento pendiente. Es una lista de controles: no cierra ni bloquea el mes. **Revisión de mis empresas** permite al contador abrir las empresas de sus membresías; al hacerlo cambia la empresa activa.

**ATS y borradores del 104 y 103:** funciones pendientes de revisión del contador antes de su publicación. El ATS solo permite descargar el ZIP cuando el XML valida técnicamente. Esa validación no confirma la aceptación del SRI ni la integridad tributaria del período. Revisa compras excluidas, advertencias, casilleros y documentos de origen. Los conceptos **Por confirmar** no se asignaron a casilleros. FacturaPorAquí prepara información; el contribuyente presenta en SRI en Línea.

## Kardex e inventario valorizado

Busca un producto y elige el período para consultar entradas, salidas, saldo y costo promedio ponderado. Lo que no tiene costo conocido se identifica; no lo interpretes como costo cero. El inventario valorizado muestra por separado esos productos y las diferencias frente al stock.

Los movimientos manuales **completan la historia del kardex y no cambian el stock**. Un saldo inicial reinicia la historia en su fecha: revisa producto, cantidad, costo y respaldo antes de registrar. Anular exige motivo y conserva el historial. El ajuste de stock sí modifica existencias y deja un movimiento registrado.

Las notas de crédito del proveedor se registran con líneas de gasto y no mueven el stock; si alguna fue una devolución física, el kardex lo avisa para revisarla con tu contador. El **Complemento Contable** (libros, revisión del mes, ATS, borradores del 104 y 103, kardex e inventario) todavía no está disponible: solo se abre para revisión en las empresas que habilite la plataforma. Estas pantallas no sustituyen un diario, mayor ni estados financieros, y no generan el 101.
