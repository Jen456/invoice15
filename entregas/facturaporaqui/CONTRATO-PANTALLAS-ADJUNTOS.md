# Contrato de pantallas — Comprobantes de pago adjuntos (`core/adjuntos`)

30/10/2026. Backend terminado y probado en la rama `fase/adjuntos-comprobantes` (sobre `plataforma` `3549c16`), **sin publicar**.
Las pantallas funcionan con el estilo base; el diseño definitivo es de Codex, con las reglas de `AGENTS.md` y el prefijo `fp-adjuntos`.

## 0. Qué es y de dónde viene

Un **comprobante de pago** (transferencia, papeleta de depósito, cheque, voucher de tarjeta, recibo, estado de cuenta) se adjunta al
documento que respalda: **compra**, **gasto** o **pago** de una cuenta por pagar.

> **Reparto vigente (decisión de la propietaria, 31/10/2026).** Las **facturas emitidas y sus cobros** llevan su respaldo en `core/cobros`
> (`RespaldoCobro`: nota o archivo, revisión, historial e idempotencia; contrato en HANDOFF, sección del 31/10). `core/adjuntos` queda
> **solo para compras, gastos y pagos a proveedores**: la API responde 404 a `venta` y `cobro`, y ni Facturas emitidas ni Cuentas por cobrar
> tienen acceso de adjuntos. Un mismo respaldo nunca se registra por las dos apps.
 Sirve de respaldo para las declaraciones del mes y, en la Etapa 3 (Bancos), para conciliar contra el extracto.

Referencia de diseño (erpnext, solo conceptos; es GPL-3.0 y no se copia código):

| erpnext | Aquí |
|---|---|
| Cualquier documento lleva archivos adjuntos privados con la huella de su contenido (doctype `File`: `attached_to_doctype`, `attached_to_name`, `is_private`, `content_hash`) | `Adjunto` cuelga de su documento por (`documento_tipo`, `documento_id`), archivo bajo `privado/`, `sha256`; nunca lo sirve `/media/` |
| `Payment Entry` guarda `mode_of_payment`, `reference_no`, `reference_date` y, al conciliar, `clearance_date` | el cobro y el pago ya tienen `medio_pago` y `referencia` (Etapa 2); el adjunto añade `clase`, `referencia`, `fecha` e `importe` del comprobante; la conciliación llega con `MovimientoBancario` (Etapa 3) |
| `Bank Transaction` se empareja con pagos por importe, fecha y referencia (`allocated_amount`) | las sugerencias de la Etapa 3 usarán importe, fecha ±5 días y referencia del adjunto y del cobro o pago |
| `Mode of Payment` de tipo Cash no deja rastro bancario | con medio «efectivo» (o sin dato) no se exige comprobante; con cualquier otro medio el documento aparece en «Pendientes de comprobante» |
| Los documentos confirmados no se editan: se cancelan y queda el rastro | el adjunto no se borra: se marca **quitado** (quién, cuándo, motivo) y se conserva el archivo |

## 1. Reglas (servidor)

- **Formatos:** PDF, JPG, PNG o WEBP, reconocidos por el contenido (no por la extensión); una imagen ilegible o de más de 50 megapíxeles se
  rechaza. **Tamaño:** hasta **8 MB** por archivo (cada archivo viaja en su propia petición: nginx admite 10 MB). **Hasta 10 comprobantes por documento.**
  Límites en `core/adjuntos/archivos.py`; el JS los recibe en la respuesta (`limites`) y el campo del formulario los muestra desde `registro.contexto()`.
- **Duplicados:** el mismo archivo (SHA-256) no se adjunta dos veces al mismo documento (HTTP 409, `codigo: "duplicado"`). Sí puede estar en
  varios documentos (una transferencia que paga dos facturas): la respuesta trae `tambien_en` para avisarlo.
- **Clase:** si no se envía o no vale, se toma la sugerida por el medio de pago del documento (`clase_sugerida` en `documento`).
- **Fecha** del comprobante: ISO `AAAA-MM-DD`, no futura. **Importe:** mayor que cero, dos decimales. Ambos opcionales; el formulario los
  precarga con la fecha y el importe del documento.
- **Quitar** es una baja lógica: `eliminado` pasa a `true` con `eliminado_en`, `eliminado_por` y `eliminado_motivo`; el archivo sigue
  descargable desde el historial; el mismo archivo se puede volver a subir.

### Permisos (del rol activo en la empresa)

| Acción | Regla |
|---|---|
| Ver y descargar | permiso de **ver el documento** (`view_sale`, `view_purchase`, `view_expenses`, `view_ctas_collect`, `view_debts_pay`) |
| Subir | ver, y además `add_adjunto` **o** un permiso de escritura del documento (`add_sale`; `add_purchase` o `change_purchase`; `add_expenses` o `change_expenses`; `add_ctas_collect`; `add_debts_pay`) |
| Quitar | ver, y además `delete_adjunto` **o** el permiso de eliminar el documento |

Reparto por rol (`core/tenancy/roles.py`, módulo `/adjuntos/` en «Administrativo»): **Propietario y Administrador** todo; **Contador** todo
(`ACCOUNTANT_WRITE = {add_adjunto, delete_adjunto}`: es la única escritura que tiene); **Consulta** solo ve; **Vendedor** no entra (no ve
compras, gastos ni cuentas por pagar, ni la página del mes). **Cliente** nada.

### Plan

La regla de plan se hereda del **módulo del documento**: con el plan gratuito no se accede a los adjuntos de gastos
(módulo de pago), sí a los de compras y pagos a proveedores; con el plan vencido se consulta, pero no se sube ni se quita (`permisos.subir`
y `permisos.quitar` en `false`, y `bloqueo` con el mensaje de siempre). La página `/adjuntos/` y la API no están en `RUTAS_DE_PAGO`.

## 2. API JSON (`core/adjuntos/views.py`)

Sin sesión o sin empresa activa: 403 JSON. Siempre `{"error": "…"}` en los fallos, a veces con `codigo`.

| Método y ruta | Devuelve |
|---|---|
| `GET /adjuntos/api/<tipo>/<id>/` | `documento` (ver abajo), `adjuntos` (vigentes **y quitados**, en orden de subida), `permisos` `{subir, quitar}`, `bloqueo` (texto o `null`), `clases` `[{id, name}]`, `limites` `{max_bytes, max_por_documento, formatos}` |
| `POST /adjuntos/api/<tipo>/<id>/` (multipart) | 201 con `adjunto`, `tambien_en` `[{tipo, id, titulo}]` y `adjuntos` completos. Campos: `archivo` (uno), `clase`, `referencia`, `fecha`, `importe`, `descripcion` |
| `POST /adjuntos/api/quitar/<id>/` | `adjunto` ya quitado. Campo `motivo` (opcional, 300) |
| `GET /adjuntos/<id>/archivo/` | el archivo: imágenes y PDF en línea dentro de un documento aislado (`Content-Security-Policy: sandbox`, `nosniff`, `no-store`); con `?descargar=1`, como descarga con su nombre original |

`tipo` ∈ `compra`, `gasto`, `pago` (`venta` y `cobro` → 404: son de `core/cobros`). 404 si el tipo no existe o el documento no es de la empresa activa.

`documento`: `tipo`, `tipo_nombre`, `id`, `numero`, `titulo` («Gasto #3 · MOVILIZACIÓN»,
«Compra 001-002-000000123», «Pago de …»), `tercero`, `identificacion`, `fecha` (ISO), `importe` (texto con dos decimales), `medio_id`, `medio`,
`contado`, `requiere` (se espera un comprobante: pagado por un medio distinto del efectivo), `clase_sugerida`.

`adjunto`: `id`, `clase {id, name}`, `nombre`, `tipo_mime`, `extension`, `tamano`, `tamano_texto`, `sha256`, `referencia`, `fecha`, `importe`,
`descripcion`, `subido_por`, `subido_en`, `url`, `url_descarga`, `eliminado`, `eliminado_en`, `eliminado_por`, `eliminado_motivo`.
Todo texto de terceros (nombre del archivo, descripción, razón social) **se dibuja como texto**, nunca como HTML.

## 3. Pantallas

### 3.1 Modal compartido «Comprobantes de pago» (`templates/adjuntos/_modal.html` + `static/adjuntos/js/adjuntos.js`)

- Se abre con cualquier elemento `[data-adjuntos-tipo="<tipo>"][data-adjuntos-id="<id>"]` o con `fpAdjuntos.abrir(tipo, id)`. El listado que lo
  incluye carga `adjuntos/css/adjuntos.css` y `adjuntos/js/adjuntos.js` en `assets_list` e incluye el modal en `content_list_before`.
- Contenido: resumen del documento (`#fpAdjuntosDocumento`; con `requiere` y sin adjuntos añade «Este documento se pagó por un medio bancario y
  todavía no tiene comprobante.»), aviso de plan (`#fpAdjuntosBloqueo`), tabla (clase, archivo con enlace a `url` en pestaña nueva y tamaño,
  referencia, fecha, importe, subido por y cuándo, opciones), formulario de subida (`#fpAdjuntosForm`, visible solo con `permisos.subir`;
  acepta varios archivos y los sube uno por uno con progreso «Subiendo 1 de 3…»). Quitar pide motivo (jquery-confirm) y deja la fila
  tachada con «Quitado el … por …: motivo».
- **Apilado:** se abre encima del modal de abonos (Cuentas por cobrar) y del de pagos (Cuentas por pagar); al cerrarse, el modal de abajo sigue
  abierto (`z-index` y fondo los ajusta el JS). Al cerrar dispara `fp-adjuntos:cerrado` con `{tipo, id, cambios}`: la página del mes recarga si hubo cambios.
- Dónde se abre: Compras (botón con clip, antes de Eliminar); Gastos (clip, antes de Editar); Cuentas por pagar → Pagos y abonos → clip en
  cada pago; y desde la página del mes. Facturas emitidas y Cuentas por cobrar no lo incluyen (su respaldo: `core/cobros`).

### 3.2 Campo «Comprobante de pago (opcional)» en los formularios de pago y gasto (`templates/adjuntos/_campo_formulario.html`)

- Solo al crear (`action == 'add'`): `comprobante` (archivo) y `comprobante_clase` (vacío = según el medio de pago). Toma `referencia`,
  `date_joined` y `valor` del propio formulario. Si el archivo no vale, **no se registra el pago ni el gasto** (misma transacción) y el
  error vuelve como en los demás campos («Solo se admiten comprobantes en PDF, JPG, PNG o WEBP.», «El archivo pesa más de 8 MB…»).

### 3.3 Página «Comprobantes de pago» (`/adjuntos/`, menú Administrativo, permiso `view_adjunto`; `templates/adjuntos/mes.html`)

- Filtro por mes (`?mes=AAAA-MM`; inválido = mes actual), «Mes anterior / siguiente», botón **«Descargar ZIP del mes»** (`/adjuntos/zip/?mes=`).
- Tarjetas: documentos del mes, con comprobante, **pagados por banco sin comprobante**, archivos adjuntos.
- Tabla «Pendientes de comprobante» (documentos con `requiere` y sin adjuntos, con botón «Adjuntar» que abre el modal) y tabla «Documentos del mes y
  sus comprobantes» (todos, con sus adjuntos enlazados y botón «Comprobantes»).
- Qué cuenta como «del mes»: compras por fecha de emisión (o de registro) sin notas de crédito ni de débito del proveedor; gastos y pagos a
  proveedores por su fecha. A crédito, el comprobante va en el pago, no en la compra. **Alcance explícito:** ni la página ni el ZIP agregan
  facturas emitidas ni cobros (`RespaldoCobro`); la página lo dice en su encabezado. Incluirlos sería un contrato nuevo (pendiente).
- ZIP: `AAAA-MM/<compras|gastos|pagos>/<numero>_<n>.<ext>` más `AAAA-MM/indice.csv` (`;`, UTF-8 con BOM: tipo,
  documento, tercero, identificación, fecha e importe del documento, medio, clase, referencia, fecha e importe del comprobante, descripción,
  archivo, sha256, subido por, subido el; los pendientes salen con «SIN COMPROBANTE»). Más de 250 MB: HTTP 413 con el aviso.

## 4. Pendiente para Codex (diseño)

- [ ] Estilo del modal y del campo del formulario (marca, `fp-adjuntos-*`), vista previa de la imagen o del PDF dentro del modal si lo ves útil
  (la URL ya se sirve en línea con CSP sandbox).
- [ ] Página del mes: tarjetas, tablas a 360/390/768/1024/1440 px (hoy la tabla se apila en móvil con `data-label`).
- [ ] Botón con clip en los listados: hoy es `btn-outline-secondary btn-xs` con `title` y `aria-label`.
- [ ] Manual de clientes: cómo adjuntar al cobrar y desde la página del mes; qué formatos; que quitar deja historial.

## 5. Decisiones tomadas por defecto (la propietaria puede cambiarlas)

- **DA-1** El Contador sube y quita comprobantes (es su respaldo contable); no gana ninguna otra escritura.
- **DA-2** ~~El Vendedor adjunta a sus facturas~~ Sustituida por el reparto del 31/10: las facturas van por `core/cobros`.
- **DA-3** Formatos PDF/JPG/PNG/WEBP, 8 MB, 10 por documento. Sin HEIC (los iPhone exportan JPG al compartir).
- **DA-4** Quitar = baja lógica con motivo opcional; sin borrado físico (una orden de limpieza puede llegar después).
- **DA-5** Se espera comprobante cuando el medio no es efectivo; con medio sin dato (compras y cobros anteriores a la Etapa 2) no se exige.
- **DA-6** ~~Factura de contado y cobros~~ Sustituida por el reparto del 31/10 (`core/cobros`). En compras: a crédito lo pide el pago.
