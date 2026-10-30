# Contrato de pantallas — Etapa 2, ventas y empresa (rama O2)

28/10/2026 · Escrito desde el código de la rama `fase/etapa2-ventas` en `6114e14`, fusionada en `plataforma` en `fff9bb3` junto con las demás ramas de la fase contable (orden y estado en `HANDOFF.md`).

> **Estado en `plataforma` tras la integración (29/10/2026).** Este contrato es **definitivo** sobre la base que indica
> `HANDOFF.md`, con estos cambios respecto de la rama:
> - Las migraciones `pos/0030` y `comprobantes/0020` dependen ahora de las de Compras y D0 (`pos/0024`,
>   `comprobantes/0015`), y la vuelta de `comprobantes/0023` quita su módulo y sus permisos por ids. No cambian campos.
> - El menú tiene los dos módulos nuevos de la fase: «Proformas» y «Retenciones recibidas».
> - Los 5 códigos de auditoría de Ventas son choices de `AuditLog.ACTIONS` (`tenancy/0007`).
> - Resultados y tablero: «Compras» = Σ subtotal con signo (la nota de crédito del proveedor, 04, resta; las compras
>   sin tipo suman como antes). «Gastos» no cambia.
> - La prueba de punta a punta del 07 importado (Compras lee, Ventas registra) existe: `tests/test_integracion_07_importado.py`.
> - Siguen pendientes los puntos 2 a 8 del apartado B (los que dicen «integrador» no se hicieron en esta entrega).

Este documento describe **lo que hace el código de la rama**, pantalla por pantalla, para que Codex haga el diseño sin romper nada y para que la propietaria vea qué cambia. Se escribió a partir de la sección 6 de su especificación interna de trabajo (no publicada), pero manda el código: cuando no coinciden, se describe el código y la diferencia queda anotada en «Diferencias con la especificación» de cada pantalla y en el resumen final. Lo publicará el integrador en `HANDOFF.md`.

Cada ruta, nombre de campo y mensaje de este documento se comprobó con `grep` en la rama.

---

## Reglas comunes a todas las pantallas

**Lo que Codex no cambia**
- Modelos, servicios, vistas, rutas, nombres de URL y migraciones.
- Los nombres de los campos (`name=`), los valores de `action`, el prefijo `lineas` del formset y su `management_form`, el `{% csrf_token %}` de los formularios y la cabecera `X-CSRFToken` de los AJAX.
- Los identificadores y clases que usa el JavaScript (se listan en cada pantalla) y los textos o fragmentos de HTML que comprueban las pruebas (lista completa en el apartado B, punto 9).

**Datos**
- La empresa activa la decide el servidor. Nunca se envía `company_id`. Un id de otra empresa responde 404.
- Montos nuevos en JSON como texto decimal con punto (`"12.34"`). Las claves que ya existían en los JSON de DataTables (`debt`, `saldo`, `valor`, `total`…) siguen siendo números (float).
- Fechas en JSON como `AAAA-MM-DD`. En pantalla se muestran como `dd/mm/aaaa`.

**Texto de terceros (nombres de clientes, descripciones, referencias, motivos, números)**
- DataTables inserta cada dato como HTML. Toda columna de texto lleva `render: $.fn.dataTable.render.text()`.
- Todo `render` que arma HTML pasa cada dato por `fpaTexto(x)`, que es `$('<div>').text(x).html()`.
- Los datos que van al JavaScript salen con `json_script`, nunca con `|safe`.
- Lo vigila `tests/test_escape_listados.py`: revisa los cinco JS de listados y reportes que toca O2 y que ninguna de sus 17 plantillas use `|safe`.

**Mensajes de Django**
- Las pantallas de comprobantes (las que extienden `skin.html`) pintan los `messages` dentro de la página con una alerta según el nivel.
- Además, el marco general (`hzt_body.html` o `vtc_body.html`) muestra todos los mensajes, también los de éxito, en una ventana con `message_error` y el título «Error». Ver «Pendiente para Codex».

**Permiso denegado (común a todas, `GroupPermissionMixin` y `GroupModuleMixin`)**
- GET: redirige a la última pantalla visitada con el mensaje «Tu perfil no cuenta con el permiso necesario para ingresar».
- POST: responde 403 con `{"error": "Tu perfil no cuenta con el permiso necesario para ingresar"}`.

**Reglas de plan (`PlanMiddleware`, sin cambios en esta rama)**

| Plan | Qué pasa en las pantallas de O2 |
|---|---|
| Gratuito | No se abren `/pos/ctas/collect/…`, `/pos/sale/…`, `/pos/credit/note/…`, `/comprobantes/…`, `/reports/sale/`, `/reports/ctas/collect/` ni `/reports/results/`. Un GET redirige a `/suscripcion/` (si el rol gestiona el plan) o a `/dashboard/`, con el aviso del plan. Un POST responde 403 `{"error": <aviso>, "plan": "requerido"}`. |
| Vencido | Solo consulta. Se abren los GET, salvo las rutas que contienen `/add/`, `/update/` o `/delete/`. Un POST solo pasa si su `action` empieza con `search` (o es `send_invoice_by_email`); los demás reciben 403 en JSON, **también los formularios normales** (por ejemplo, anular desde la ficha de una retención recibida). |
| Cupo agotado | No se bloquea nada de O2: nada de esto es emisión ni consume cupo. |
| Plan 1000, Ilimitado y Multiempresa | Todo disponible. Las retenciones recibidas a mano no exigen el plan Ilimitado; el registro desde un 07 importado sí, porque su pantalla (de O1) está bajo `/importacion/`. |

`/pos/company/update/` no es ruta de pago: la pantalla de Empresa se abre con cualquier plan.

**Roles** (los reparte `sync_roles`; los permisos que empiezan con `add_`, `change_` o `delete_` nunca llegan a Contador ni a Consulta, y Vendedor solo recibe los de su lista)

| Acción | Propietario | Administrador | Contador | Vendedor | Consulta |
|---|---|---|---|---|---|
| Ver cuentas por cobrar y abonos (`view_ctas_collect`) | ✔ | ✔ | ✔ | — | ✔ |
| Registrar un cobro (`add_ctas_collect`) | ✔ | ✔ | — | — | — |
| Eliminar un cobro o una cuenta por cobrar (`delete_ctas_collect`) | ✔ | ✔ | 403 | — | 403 |
| Ver retenciones recibidas (`view_retencionrecibida`) | ✔ | ✔ | ✔ | — | ✔ |
| Registrar una retención recibida (`add_retencionrecibida`) | ✔ | ✔ | — | — | — |
| Anular el registro de una retención recibida (`change_retencionrecibida`) | ✔ | ✔ | — | — | — |
| Marcar «Anulado en el SRI», los seis tipos (`change_anulado_sri_*`) | ✔ | ✔ | — | — | — |
| Editar el tipo de contribuyente y la periodicidad (`change_company`) | ✔ | ✔ | — | — | — |
| Reportes con «Comprobantes» (alcance) | Según el módulo (`GroupModuleMixin`): Contador ve los tres, Vendedor solo el de ventas y Consulta los tres. |||||

**Menú.** El módulo nuevo «Retenciones recibidas» (`/comprobantes/retenciones-recibidas/`, icono `fas fa-hand-holding-usd`, descripción «Retenciones que te hicieron tus clientes sobre tus facturas») va en «Administrativo», orden 3, después de «Cuentas por cobrar» y «Cuentas por pagar».

---

## Pantallas documentadas

| # | Pantalla | Ruta | Nombre de URL | Nueva o modificada |
|---|---|---|---|---|
| 1 | Cuentas por cobrar: listado y abonos | `/pos/ctas/collect/` | `ctas_collect_list` | Modificada |
| 2 | Cuentas por cobrar: eliminar | `/pos/ctas/collect/delete/<pk>/` | `ctas_collect_delete` | Modificada |
| 3 | Cuentas por cobrar: registrar cobro | `/pos/ctas/collect/add/` | `ctas_collect_create` | Modificada |
| 4 | Retenciones recibidas: listado | `/comprobantes/retenciones-recibidas/` | `comprobantes_retenciones_recibidas` | Nueva |
| 5 | Retenciones recibidas: elegir factura | `/comprobantes/retenciones-recibidas/add/` | `comprobantes_retencion_recibida_buscar` | Nueva |
| 6 | Retenciones recibidas: registrar | `/comprobantes/retenciones-recibidas/add/<venta>/` | `comprobantes_retencion_recibida_nueva` | Nueva |
| 7 | Retención recibida: ficha | `/comprobantes/retenciones-recibidas/<pk>/` | `comprobantes_retencion_recibida` | Nueva |
| 8 | Marcar «Anulado en el SRI» (seis tipos) | `/comprobantes/anulados/<modelo>/<pk>/update/` | `comprobantes_marcar_anulado` | Nueva |
| 9 | Facturas emitidas: listado | `/pos/sale/admin/` | `sale_admin_list` | Modificada |
| 10 | Notas de crédito: listado | `/pos/credit/note/admin/` | `credit_note_admin_list` | Modificada |
| 11–14 | Retenciones emitidas, liquidaciones, notas de débito y guías: listados | `/comprobantes/{retenciones,liquidaciones,notas-debito,guias}/` | `comprobantes_retenciones`, `comprobantes_liquidaciones`, `comprobantes_notas_debito`, `comprobantes_guias` | Modificadas |
| 15–16 | Portal del cliente: facturas y notas de crédito | `/pos/sale/client/`, `/pos/credit/note/client/` | `sale_client_list`, `credit_note_client_list` | Modificadas |
| 17 | Empresa | `/pos/company/update/` | `company_update` | Modificada |
| 18–20 | Reportes de ventas, cuentas por cobrar y resultados | `/reports/sale/`, `/reports/ctas/collect/`, `/reports/results/` | `sale_report`, `ctas_collect_report`, `results_report` | Modificadas |

El apartado A añade los datos que O2 entrega a la pantalla de O1 del 07 importado; esa pantalla no es de esta rama. El apartado B es lo pendiente para Codex y el C, el resumen de diferencias con la especificación.

---

## 1. Cuentas por cobrar: listado y abonos (modificada)

- **Ruta:** `GET/POST /pos/ctas/collect/`, nombre `ctas_collect_list`.
- **Vista:** `CtasCollectListView` (`core/pos/views/ctas_collect/views.py`).
- **Plantilla:** `ctas_collect/list.html` (extiende `list.html`). **JS:** `core/pos/static/ctas_collect/js/list.js`.
- **Permiso:** `view_ctas_collect`. Eliminar un cobro exige además `delete_ctas_collect` del rol; lo comprueba el servicio `cxc.eliminar_cobro`.
- **Qué ve y hace cada rol:**
  - Propietario y Administrador: ven todo y eliminan cobros.
  - Contador y Consulta: ven todo. El botón de eliminar cobro se les dibuja igual, pero el servidor responde 403 «Tu perfil no puede eliminar cobros.».
  - Vendedor: no tiene el módulo.
- **Plan vencido:** el listado, `search` y `search_pays` funcionan; `delete_pay` responde 403 en JSON con el aviso del plan; «Nuevo Registro» lleva a `/add/`, que está bloqueada.

**Contexto de la plantilla**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Listado de Cuentas por Cobrar» |
| `create_url` | str | `/pos/ctas/collect/add/` |
| `form` | `ReportForm` | Solo se pinta `date_range`. El formulario trae también `alcance` (de los reportes), que esta pantalla no usa. |

**Acciones (POST con `X-CSRFToken`; responden JSON)**

1. `action=search`, con `start_date` y `end_date` (`AAAA-MM-DD`; los dos vacíos = todas). Filtra por la fecha de la cuenta (`date_joined`). Devuelve una lista; cada fila trae las claves de siempre (`id`, `sale` con el `Sale.toJSON()` completo, `date_joined`, `end_date`, `debt` y `saldo` como float, `state`) más:
   - `documento`: `{tipo: 'factura' | 'nota_debito', id, numero}`.
   - `estado`: `{id: 'pendiente' | 'pagada' | 'anulada', name: 'Pendiente' | 'Pagada' | 'Anulada en el SRI'}`.
   - `saldo_texto`: `"12.34"`.
2. `action=search_pays`, con `id` (de la cuenta). Devuelve todos los abonos de la cuenta, también los anulados, en orden de registro. Cada abono trae `id`, `date_joined`, `description`, `valor` (float) y además:
   - `valor_texto`: `"12.34"`;
   - `tipo`: `{id, name}`, con `cobro` «Cobro registrado», `nota_credito` «Nota de crédito», `retencion` «Retención recibida» y `anulacion` «Anulación en el SRI»;
   - `medio_pago`: `{id, name}`, con `name` = «Sin dato» si está vacío (los cobros anteriores a esta etapa);
   - `referencia`;
   - `documento`: número de la nota de crédito o de la retención que generó el abono, o `''`;
   - `anulado`: bool;
   - `index`: 1, 2, 3…
3. `action=delete_pay`, con `id` (del abono). Responde `{}` si se eliminó. El cobro eliminado queda en la auditoría (`cxc_cobro_eliminado`). Si al subir el saldo hay notas de crédito o retenciones de esa factura que no se abonaron enteras, se les abona lo que faltaba, por fecha. Errores:
   - 403 `{"error": "Tu perfil no puede eliminar cobros."}`;
   - 200 `{"error": "Este abono lo generó una nota de crédito, una retención o una anulación: se revierte anulando ese documento, no aquí."}` (también si el cobro ya estaba anulado);
   - 200 `{"error": "El cobro ya no existe: actualiza la página."}`.
4. Otro `action`: `{"error": "No ha seleccionado ninguna opción"}`.

**Estados de la cuenta por cobrar (`estado.id`)**

| Estado | Cuándo | Qué permite |
|---|---|---|
| `pendiente` | Saldo mayor que 0 | Registrar cobros (pantalla 3), ver y eliminar cobros |
| `pagada` | Saldo 0 o menos | Ver y eliminar cobros; al eliminar uno vuelve a `pendiente` |
| `anulada` | Tiene un abono de anulación vigente (la factura o la ND se marcó «Anulado en el SRI») | Solo ver. No admite cobros nuevos: no aparece al registrar un cobro y el servicio lo rechaza |

Paso de un estado a otro: `pendiente` → `pagada` (se cobra todo); `pendiente` → `anulada` (se marca anulado el comprobante); `pagada` → `pendiente` (se elimina un cobro o se revierte un abono automático).

**Abonos en el modal**
- Cobro (`tipo.id == 'cobro'`) vigente: botón de eliminar.
- Abonos automáticos (nota de crédito, retención, anulación): sin botón; se revierten desde su documento.
- Abono anulado: insignia «Anulado», fila tachada y en gris.
- Confirmación al eliminar: «¿Eliminar este cobro? Queda registrado en la auditoría.».

**Interfaz actual**
- Columnas: Documento (el número; con «ND » delante si `documento.tipo == 'nota_debito'`), Cliente, Fecha de compra (`date_joined`), Fecha de plazo (`end_date`), Deuda, Saldo, Estado (insignia `badge-danger` pendiente, `badge-success` pagada, `badge-secondary` anulada) y Opciones (Abonos y Eliminar → `pathname + 'delete/<id>/'`).
- Pie: suma de `saldo` en `.total`.
- Modal de abonos: N.º, Fecha, Tipo, Medio de pago, Referencia, Valor, Detalles y Opciones.

**Identificadores que usa el JS (no cambiar):** `#data`, `input[name="date_range"]`, `.btnSearchAll`, `.total`, `#myModalPayments`, `#tblPayments`, `a[rel="payments"]`, `a[rel="delete"]`, la función `fpaTexto` y las variables globales `pathname` y `csrftoken`.

**Libre para el diseño:** orden y aspecto de las columnas, insignias, textos de ayuda y el diseño del modal, siempre que se conserven esos identificadores y el escape.

**Diferencias con la especificación:** se añadió el error «El cobro ya no existe: actualiza la página.». La especificación pedía mostrar el botón de eliminar solo con el permiso; el código lo muestra en todo cobro vigente y deja que el servidor decida (ver Pendiente).

---

## 2. Cuentas por cobrar: eliminar (modificada)

- **Ruta:** `GET/POST /pos/ctas/collect/delete/<pk>/`, nombre `ctas_collect_delete`. **Vista:** `CtasCollectDeleteView`. **Plantilla:** `delete.html` (la genérica de confirmación).
- **Permiso:** `delete_ctas_collect` (Propietario y Administrador). **Plan vencido:** bloqueada (la ruta tiene `/delete/`).
- **Contexto:** `title` «Notificación de eliminación», `list_url` y el objeto.
- **Acción:** POST. Responde `{}` si la borró; una cuenta de otra empresa da 404. Errores (`{"error": …}`):
  - «Esta cuenta por cobrar tiene abonos de notas de crédito, retenciones o anulaciones, o es de una nota de débito: no se puede eliminar.»
  - «Esta cuenta por cobrar tiene cobros registrados: elimínalos antes de eliminarla.»
- Antes de esta etapa, borrar la cuenta borraba sus cobros en cascada y sin auditoría; ahora hay que eliminar antes cada cobro (que sí se audita).
- **Libre para el diseño:** la página genérica no cambia en esta rama.

---

## 3. Cuentas por cobrar: registrar cobro (modificada)

- **Ruta:** `GET/POST /pos/ctas/collect/add/`, nombre `ctas_collect_create`. **Vista:** `CtasCollectCreateView`.
- **Plantilla:** `ctas_collect/create.html` (extiende `form.html`, que trae `#frmForm` con `data-url` = `list_url`). **JS:** `core/pos/static/ctas_collect/js/form.js`.
- **Permiso:** `add_ctas_collect` (Propietario y Administrador). **Plan:** con plan gratuito o vencido la página no se abre.
- **Contexto:** `title` «Nuevo registro de un Pago», `list_url` (`/pos/ctas/collect/`), `action` (`'add'`) y `form` (`PaymentsCtaCollectForm`).

**Campos (`PaymentsCtaCollectForm`, en este orden)**

| Campo | Tipo | Obligatorio | Validación |
|---|---|---|---|
| `ctas_collect` | select (select2 con búsqueda AJAX); llega vacío | Sí | Cuenta de la empresa, con saldo y sin anulación |
| `date_joined` | fecha `AAAA-MM-DD` (datetimepicker, `id="date_joined"`, inicial hoy); etiqueta «Fecha de registro» | Sí | No futura y no anterior a la fecha de la cuenta por cobrar |
| `valor` | número (TouchSpin: mínimo 0.01, dos decimales, tope = `saldo_texto` de la cuenta elegida) | Sí | Mayor que 0 y no mayor que el saldo |
| `medio_pago` | select. Primera opción vacía «Elige el medio de pago»; luego `efectivo` «Efectivo», `transferencia` «Transferencia», `deposito` «Depósito», `cheque` «Cheque», `tarjeta_debito` «Tarjeta de débito», `tarjeta_credito` «Tarjeta de crédito», `compensacion` «Compensación de deudas» y `otro` «Otro». Sin valor inicial | Sí | Uno de esos valores |
| `referencia` | texto, máximo 100; marcador «N.º de transferencia, cheque o comprobante»; ayuda «Obligatoria si el medio es un cheque.» | Solo con cheque | — |
| `description` | texto largo (máximo 500); etiqueta «Detalles» | No | — |

**Acciones (POST; responden JSON)**
1. `action=search_ctas_collect`, con `term`. Devuelve hasta 10 cuentas con saldo y sin anulación que coinciden por nombre o identificación del cliente, número de factura o número de ND. Cada una trae su `toJSON()` (el de la pantalla 1) más `text`, con la forma «001-001-000000010 · NOMBRE DEL CLIENTE (RUC) / AAAA-MM-DD / $23.00». El tope del valor sale de `saldo_texto`.
2. `action=add`, con `ctas_collect`, `date_joined`, `valor`, `medio_pago`, `referencia` y `description`. Responde `{}` si se registró (el JS vuelve a `data-url`) o `{"error": texto}`.

**Errores, en el orden en que se comprueban (texto exacto)**
1. «Elige la cuenta por cobrar.» (vacío o no numérico)
2. «El valor debe ser mayor que cero.»
3. «Escribe la fecha del cobro (AAAA-MM-DD).»
4. «La cuenta por cobrar no existe: actualiza la página.» (no existe o es de otra empresa)
5. «Esta cuenta por cobrar es de un comprobante anulado en el SRI.»
6. «Esta cuenta por cobrar ya no tiene saldo.»
7. «El valor (X) supera el saldo de la cuenta por cobrar (Y).» (X e Y como `12.34`)
8. «La fecha del cobro no puede ser futura.»
9. «La fecha del cobro no puede ser anterior a la venta (dd/mm/aaaa).» (la fecha es la de la cuenta por cobrar; en una cuenta de ND, la de la ND)
10. «Elige el medio de pago.»
11. «Escribe el número del cheque en «Referencia».»

Validación previa en el navegador (FormValidation): «Seleccione un cuenta por pagar» (texto antiguo, ver Pendiente), «La fecha es obligatoria», «La fecha no es válida», «El valor no es un número», «Elige el medio de pago.» y «Escribe el número del cheque en «Referencia».».

**Identificadores que usa el JS (no cambiar):** `#frmForm` y su `data-url`, `select[name="ctas_collect"]`, `input[name="date_joined"]` (`#date_joined`), `input[name="valor"]`, `select[name="medio_pago"]`, los nombres de los seis campos (FormValidation valida por nombre, también `referencia` y `description`) y la insignia `.deuda` («Saldo: $…»).

**Libre para el diseño:** disposición de los campos, la insignia del saldo y los textos de ayuda.

**Diferencias con la especificación:**
- Mensajes añadidos: «Elige la cuenta por cobrar.», «La cuenta por cobrar no existe: actualiza la página.» y «Escribe la fecha del cobro (AAAA-MM-DD).».
- La búsqueda incluye el número de factura y de ND, no solo el nombre o la cédula.
- «Anterior a la venta» se compara con la fecha de la cuenta por cobrar.

---

## 4. Retenciones recibidas: listado (nueva)

- **Ruta:** `GET /comprobantes/retenciones-recibidas/`, nombre `comprobantes_retenciones_recibidas`.
- **Vista:** `RetencionRecibidaListView` (`core/comprobantes/vistas_recibidas.py`). **Plantilla:** `comprobantes/retencion_recibida/list.html` (extiende `skin.html`). Sin JS y sin POST.
- **Permiso:** `view_retencionrecibida`. El botón «Registrar retención recibida» sale si `puede_registrar`.
- **Qué ve cada rol:** Propietario y Administrador ven y registran; Contador y Consulta solo ven; Vendedor no tiene acceso.
- **Plan vencido:** el listado se ve; el botón lleva a `/add/`, que sí se bloquea.

**Filtros (GET)**

| Parámetro | Valores |
|---|---|
| `desde`, `hasta` | `AAAA-MM-DD` sobre la fecha de emisión; una fecha inválida se ignora |
| `q` | Hasta 100 caracteres. Busca en el número, el agente (razón social o RUC), el nombre o la identificación del cliente y el número de la factura. Con 15 dígitos (con o sin guiones) busca además el número exacto. |
| `estado` | `registrada` (por defecto), `anulada` o `todas`; cualquier otro valor se toma como `registrada` |

**Contexto de la plantilla**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Retenciones recibidas» |
| `retenciones` | QuerySet de `RetencionRecibida` | Hasta 200, de la más reciente a la más antigua, con `venta`, `cliente__user` y `detalles` ya cargados |
| `filtros` | dict de str | `desde`, `hasta`, `q`, `estado` actuales |
| `puede_registrar` | bool | El rol tiene `add_retencionrecibida` |
| `totales` | dict de Decimal | `renta`, `iva`, `total` de las **registradas** que cumplen el filtro |

**Datos de cada fila:** `numero`, `fecha_emision`, `emisor_razon_social` y `emisor_identificacion` (el agente de retención), `venta.voucher_number_full`, `total_renta`, `total_iva`, `total_retenido`, `get_cxc_estado_display`, `estado` / `get_estado_display` («Registrada» / «Anulada»), `get_origen_display` («Registro manual» / «Importado desde XML»), `get_verificacion_display` y el enlace «Ver» a la ficha.

Valores de `cxc_estado`: `aplicada` «Abonada a la cuenta por cobrar», `parcial` «Abonada en parte: el resto excede el saldo», `sin_cxc` «Venta de contado: sin cuenta por cobrar», `sin_saldo` «La cuenta por cobrar ya estaba saldada» y `revertida` «Abono revertido al anular».

Valores de `verificacion`: `sin_verificar` «Registrada a mano, sin verificar en el SRI», `declarada_en_archivo` «Autorización declarada en el archivo (sin verificar)» y `verificada_sri` «Verificada en el SRI».

**Textos fijos:** sin resultados, «No hay retenciones recibidas con estos filtros.»; pie de la tabla, «Total registradas (filtro actual)». Los `messages` se muestran dentro de la página.

**No cambiar:** los nombres de los parámetros GET y los valores de `estado`. **Libre para el diseño:** todo lo demás (no hay JS).

---

## 5. Retenciones recibidas: elegir factura (nueva)

- **Ruta:** `GET /comprobantes/retenciones-recibidas/add/?q=`, nombre `comprobantes_retencion_recibida_buscar`.
- **Vista:** `RetencionRecibidaBuscarView`. **Plantilla:** `comprobantes/retencion_recibida/buscar.html`.
- **Permiso:** `add_retencionrecibida` (Propietario y Administrador). **Plan:** gratuito y vencido la bloquean.

**Contexto:** `title` «Registrar una retención recibida»; `q` (str, hasta 100 caracteres); `ventas`, una lista de hasta 20 `Sale`, cada una con `saldo` (Decimal, o `None` si fue de contado), `fecha_efectiva` (date) y `client.user`.

**Qué facturas salen:** facturas (tipo `01`) autorizadas o cubiertas por notas de crédito (`authorized`, `authorized_and_sent_by_email`, `canceled`), sin la marca «Anulado en el SRI», del ambiente actual de la empresa, sin consumidor final (`9999999999999`) ni clientes con tipo de identificación `07`.
- Con `q`: por número (contiene, o exacto si son 15 dígitos), nombre o identificación del cliente.
- Sin `q`: solo las facturas a crédito con saldo.
- Orden: la fecha de emisión efectiva más reciente primero.

**Acción por fila:** enlace a `/comprobantes/retenciones-recibidas/add/<id>/` («Registrar retención»).

**Textos fijos:** sin resultados con búsqueda, «No hay facturas autorizadas que coincidan con «{q}».»; sin búsqueda, «No tienes facturas a crédito con saldo. Busca la factura por su número o cliente.».

**No cambiar:** el parámetro `q` y el enlace por factura. **Libre para el diseño:** todo lo demás.

**Diferencia con la especificación:** además del consumidor final, excluye a los clientes con tipo de identificación `07`.

---

## 6. Retenciones recibidas: registrar (nueva)

- **Ruta:** `GET/POST /comprobantes/retenciones-recibidas/add/<venta>/`, nombre `comprobantes_retencion_recibida_nueva`.
- **Vista:** `RetencionRecibidaCrearView`. **Plantilla:** `comprobantes/retencion_recibida/create.html`. Funciona sin JavaScript.
- **Permiso:** `add_retencionrecibida` (Propietario y Administrador). **Plan:** gratuito y vencido la bloquean. No consume cupo ni llama al SRI.
- Una venta de otra empresa responde 404.

**Contexto de la plantilla**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Registrar retención recibida» |
| `venta` | `Sale` | La factura sustento, con `client.user` y `receipt` |
| `cliente` | `Client` | El cliente de la factura (agente de retención) |
| `cxc` | `CtasCollect` o `None` | Cuenta por cobrar de la factura; `None` si fue de contado |
| `saldo` | Decimal o `None` | Saldo de esa cuenta |
| `impedimento` | str o `None` | Si la factura no admite retención: se muestra el aviso y no se dibuja el formulario |
| `pide_emisor_ruc` | bool | La identificación del cliente no es un RUC válido: aparece el campo `emisor_ruc` |
| `anteriores` | QuerySet | Retenciones de esta factura, en cualquier estado, de la más nueva a la más vieja |
| `topes` | dict de Decimal | `renta` (subtotal sin impuestos de la factura), `iva` (IVA de la factura), `usado_renta`, `usado_iva` (bases de las retenciones ya registradas) |
| `form` | `RetencionRecibidaForm` | Datos del comprobante |
| `lineas` | `LineasRecibidasFormSet` | Líneas, prefijo `lineas` |
| `resumen` | `None` o dict | Resultado de revisar (abajo) |

`resumen`:
- `doc`: `numero`, `establecimiento`, `punto_emision`, `secuencial`, `autorizacion`, `clave_acceso`, `fecha_emision` (date), `periodo_fiscal` (`MM/AAAA`), `emisor_ruc`, `emisor_razon_social`, `ambiente`, `cod_doc_sustento`, `num_doc_sustento`, `fecha_doc_sustento`, `verificacion`, `notas` y `origen`.
- `lineas`: `[{impuesto ('1' renta | '2' IVA), codigo, concepto, base_imponible, porcentaje, valor_retenido}]`, con importes en Decimal.
- `total_renta`, `total_iva`, `total_retenido`, `abono_previsto` y `excedente` (Decimal).
- `cxc_estado`: `aplicada`, `parcial`, `sin_cxc` o `sin_saldo`.
- `advertencias`: `[{codigo, texto}]`.
- `topes`: igual que el `topes` del contexto.

**Campos del comprobante (`RetencionRecibidaForm`)**

| Campo | Tipo | Obligatorio | Validación |
|---|---|---|---|
| `numero` | texto, máximo 17; ayuda «001-001-000000123» | Sí | 15 dígitos con o sin guiones; establecimiento, punto y secuencial distintos de cero |
| `autorizacion` | texto, máximo 49; ayuda «49 dígitos (clave de acceso), o 10 o 37 en comprobantes antiguos.» | Sí | Se quitan los caracteres que no son dígitos; deben quedar 10, 37 o 49. Con 49 se comprueba como clave de acceso: tipo 07, RUC del agente, número, fecha y ambiente |
| `fecha_emision` | `<input type="date">`, inicial hoy | Sí | No futura y no anterior a la fecha de emisión efectiva de la factura |
| `emisor_ruc` | texto, máximo 13; ayuda «Vacío: el RUC del cliente de la factura.». **Solo existe si `pide_emisor_ruc`** | No | RUC válido; igual al del cliente, o su cédula seguida de `001` (con advertencia) |
| `notas` | texto, máximo 300 | No | — |

**Líneas (`LineaRecibidaForm` en un formset con prefijo `lineas`)**
- Nombres: `lineas-<n>-codigo`, `lineas-<n>-base_imponible`, `lineas-<n>-porcentaje`, `lineas-<n>-valor_retenido`.
- Management form: `lineas-TOTAL_FORMS`, `lineas-INITIAL_FORMS`, `lineas-MIN_NUM_FORMS` y `lineas-MAX_NUM_FORMS`.
- Llegan 3 filas vacías. El máximo es 10: aunque se envíen más, el servidor arma 10 como mucho y el formset da error.

| Campo | Tipo | Obligatorio | Validación |
|---|---|---|---|
| `codigo` | select con valor `'impuesto:codigo'` (por ejemplo `'1:312'` o `'2:1'`). Primera opción vacía «— Sin retención en esta línea —». Una opción por pareja (impuesto, código), tomada de `codigos_retencion_vigentes(fecha, incluir_inactivos=True)`, con la fecha de emisión enviada (hoy en el GET). Etiqueta «Renta · 312 · <concepto> (2 %)» o «IVA · 1 · 30 %» (porcentaje con coma), más « (no disponible para emitir)» si el código está inactivo | No | Una de las opciones |
| `base_imponible` | decimal (12, 2) | No | Mínimo 0.01 |
| `porcentaje` | decimal (5, 2); ayuda «Vacío: el del catálogo vigente.» | No | De 0 a 100 |
| `valor_retenido` | decimal (12, 2); ayuda «Vacío: base × porcentaje.» | No | Mínimo 0; si se escribe, debe coincidir con base × porcentaje con tolerancia de 0.01 |

Una línea sin código ni números se ignora. Una línea con números pero sin código da el error de campo «Elige el código de la retención de esta línea.».

**Acciones**
- Un solo formulario POST con dos botones `name="action"`:
  - `value="calcular"`: revisa y muestra el resumen sin guardar. Cualquier valor distinto de `registrar` se trata como `calcular`.
  - `value="registrar"`: registra, dentro de una transacción.
- Sin resumen, la plantilla muestra solo «Revisar retención» (`calcular`). Con resumen, «Registrar retención» (`registrar`) y «Volver a revisar» (`calcular`).
- Registrar sin revisar antes también funciona: el servidor recalcula todo.
- Si se registra, redirige a la ficha con un mensaje de éxito (el importe va con punto decimal, por ejemplo `$1.30`):
  - «Retención {numero} registrada: se abonaron ${valor} a la cuenta por cobrar.»
  - «Retención {numero} registrada. La venta fue de contado: la retención no abona ninguna cuenta por cobrar.»
  - «Retención {numero} registrada. La cuenta por cobrar ya estaba saldada: no se abonó nada.»
- Textos del resumen en la plantilla: «La venta fue de contado: la retención no abona ninguna cuenta por cobrar.» · «La cuenta por cobrar ya no tiene saldo: no se abonará nada.» · «Se abonarán $X a la cuenta por cobrar.», con « (excedente sin abonar: $Y)» antes del punto si hay excedente.

**Estados:** formulario → (calcular) → resumen → (registrar) → ficha en estado `registrada`. Con `impedimento`: aviso, enlace «Elegir otra factura» y ningún botón de envío.

**Errores del servicio** (se muestran como `non_field_errors` y la página vuelve con 200; texto exacto)
- Factura (también como `impedimento`):
  - «Las retenciones recibidas se registran sobre facturas (no sobre tickets).»
  - «Solo se registran retenciones sobre facturas autorizadas por el SRI.»
  - «La factura {numero} está anulada en el SRI.»
  - «Una factura a consumidor final no admite retención: el comprador no está identificado.»
- Agente de retención:
  - «El agente de retención se identifica con un RUC válido de 13 dígitos; el cliente de esta factura tiene la identificación {dni}.»
  - «El RUC {ruc} del agente de retención no es el del cliente de la factura ({dni}).»
- Número y autorización:
  - «Escribe el número de la retención con establecimiento, punto y secuencial: 001-001-000000123.»
  - «La autorización de la retención tiene 49 dígitos (clave de acceso), o 10 o 37 en comprobantes antiguos.»
- Clave de acceso:
  - «La clave de acceso no es válida: {detalle}»
  - «La clave de acceso no corresponde a un comprobante de retención (tipo {tipo}).»
  - «La clave de acceso es de otro emisor (RUC {ruc}); el cliente es {dni}.»
  - «La clave de acceso es del comprobante {numero_clave}, no del {numero}.»
  - «La fecha de la clave de acceso ({fecha_clave}) no coincide con la fecha de emisión.»
  - «La clave de acceso es del ambiente {ambiente_clave}; la factura es de {ambiente}.»
- Duplicado: «Ya registraste la retención {numero} de {cliente} sobre esta factura.» ({cliente} = razón social del agente). Se comprueba antes que los topes.
- Fechas:
  - «La fecha de emisión de la retención no puede ser futura.»
  - «La retención no puede ser anterior a la factura (dd/mm/aaaa).»
- Líneas:
  - «Agrega al menos una retención (renta o IVA).»
  - «Una retención admite hasta 10 líneas.»
  - «El código {codigo} no está en el catálogo de retenciones vigente el dd/mm/aaaa.»
  - «El código {codigo} está repetido.»
  - «La base del código {codigo} debe ser mayor que cero.»
  - «El porcentaje del código {codigo} debe estar entre 0 y 100.»
  - «El valor retenido del código {codigo} ({valor}) no coincide con base × porcentaje ({calculado}).»
  - «El sistema todavía no registra retenciones de ISD (código 6).» (a mano no se puede elegir; aplica al 07 importado)
- Topes (suman las retenciones ya registradas):
  - «Las bases de renta ({base}) superan el subtotal sin impuestos de la factura ({tope}), sumando otras retenciones registradas.»
  - «Las bases de IVA ({base}) superan el IVA de la factura ({tope}), sumando otras retenciones registradas.»

**Errores de los campos** (los pinta Django, configuración `es-ec`)
- «Este campo es obligatorio.»
- «Introduzca una fecha válida.»
- «Asegúrese de que este valor tenga menos de 17 caracteres (tiene N).»
- «Asegúrese de que este valor es mayor o igual a 0.01.»
- «Asegúrese de que este valor es menor o igual a 100.»
- «Escoja una opción válida. X no es una de las opciones disponibles.»
- Del formset (`lineas.non_form_errors`): «Por favor, envíe 10 formularios como máximo.».

**Advertencias** (no bloquean; salen en el resumen y se guardan con la retención)

| Código | Texto | Cuándo |
|---|---|---|
| `porcentaje_catalogo` | «El código {c} tiene {x} % en el catálogo vigente y la retención usa {y} %. Revisa el comprobante del cliente.» | El porcentaje no coincide con el catálogo y el código no admite porcentaje editable |
| `excedente_cxc` | «La retención supera el saldo de la cuenta por cobrar en {excedente}: no se abona ese excedente.» | Abono parcial |
| `plazo_5_dias` | «La retención se emitió {d} días después de la factura (la ley da 5 días).» | Más de 5 días |
| `ruc_de_cedula` | «El agente de retención usa el RUC {ruc}; la factura se emitió con su cédula {dni}.» | El agente usa cédula + 001 |
| `sin_verificar` | «Registrada a mano: no se verificó en el SRI.» | Siempre en el registro manual |

**No cambiar:** los nombres de los campos, `name="action"` con `calcular` y `registrar`, el prefijo `lineas` con su management form y el CSRF. Las pruebas comprueban que con `impedimento` no aparecen `value="calcular"` ni `value="registrar"`.

**Libre para el diseño:** disposición de las líneas (hoy un `fieldset` por línea, `.fp-retencion-linea`), el bloque de topes, la lista de retenciones anteriores y el resumen.

**Diferencias con la especificación:**
- Tercera variante del mensaje de éxito («La cuenta por cobrar ya estaba saldada: no se abonó nada.»).
- La variante de contado empieza con «Retención {numero} registrada.».
- Error de campo nuevo «Elige el código de la retención de esta línea.».
- `resumen` trae más claves en `doc` y añade `topes`.
- Cualquier `action` que no sea `registrar` se trata como `calcular`.
- La comprobación de duplicado se hace antes que los topes.

---

## 7. Retención recibida: ficha (nueva)

- **Ruta:** `GET/POST /comprobantes/retenciones-recibidas/<pk>/`, nombre `comprobantes_retencion_recibida`.
- **Vista:** `RetencionRecibidaDetalleView`. **Plantilla:** `comprobantes/retencion_recibida/detalle.html`.
- **Permisos:** ver con `view_retencionrecibida`; anular con `change_retencionrecibida`.
- **Qué ve cada rol:** Propietario y Administrador ven y anulan; Contador y Consulta solo ven (sin el bloque de anular).
- **Plan vencido:** la ficha se ve, pero el POST de anular recibe 403 en JSON con el aviso del plan (ver Pendiente).

**Contexto de la plantilla**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Retención recibida {numero}» |
| `retencion` | `RetencionRecibida` | Con `venta`, `cliente__user`, `abono`, `documento_importado`, `registrado_por`, `anulado_sri_por` y `detalles` |
| `puede_anular` | bool | Tiene `change_retencionrecibida` y el estado es `registrada` |
| `form_anular` | `AnularRetencionRecibidaForm` | Formulario de anular |
| `url_documento` | str o `None` | Enlace a la ficha del documento importado (`importacion_documento`, de O1) |
| `error_permiso` | str o `None` | «Tu perfil no puede realizar esta acción.» tras un POST rechazado |

**Datos que muestra:** estado, origen y verificación; agente (`emisor_razon_social`, `emisor_identificacion`); fecha de emisión y período fiscal; autorización; factura sustento y su fecha; estado en la cuenta por cobrar y abono (valor, fecha y «(revertido)» si se anuló); notas; quién la registró y cuándo; si está anulada, la fecha, quién y el motivo; las advertencias guardadas al registrar; y el detalle por línea (impuesto, código, concepto, base, porcentaje y valor) con los totales.

**Campo:** `motivo` (texto largo, obligatorio, de 10 a 300 caracteres, etiqueta «Motivo de la anulación»).

**Acción:** POST con `action=anular` y `motivo`. Si sale bien, redirige a la misma ficha con:
- «Retención {numero} anulada: se revirtió su abono de ${valor} en la cuenta por cobrar.»
- o «Retención {numero} anulada.» si no tenía un abono vigente.

**Qué pasa al anular**
- El abono se revierte (queda anulado, no se borra).
- El saldo que se libera se abona a las notas de crédito o retenciones de la misma factura que tenían excedente.
- Se audita como `retencion_recibida_anulacion`.
- Si venía de un 07 importado y era la última registrada de ese documento, el documento vuelve a «pendiente» en Importación. Esa función es de O1: en esta rama todavía lanza `NotImplementedError`, pero solo afecta a retenciones importadas, que no existen sin O1.

**Estados:** `registrada` → (anular) → `anulada`. Es final, pero el mismo número se puede registrar de nuevo.

**Errores y mensajes**
- En el campo: «Escribe el motivo (al menos 10 caracteres).» (vacío o corto) y «Asegúrese de que este valor tenga menos de 300 caracteres (tiene N).».
- En el formulario: «Esta retención ya está anulada.».
- Página con estado 403 y «Tu perfil no puede realizar esta acción.»: sin `change_retencionrecibida`, o con un `action` distinto de `anular`.

**No cambiar:** `name="action" value="anular"`, `name="motivo"` y el CSRF. **Libre para el diseño:** todo lo demás.

**Diferencias con la especificación:** segunda variante del mensaje de éxito (sin abono); el contexto añade `error_permiso`; un `action` desconocido también responde 403.

---

## 8. Marcar «Anulado en el SRI» (nueva, común a los seis tipos)

- **Ruta:** `GET/POST /comprobantes/anulados/<modelo>/<pk>/update/`, nombre `comprobantes_marcar_anulado` (argumentos: slug y pk).
- **Vista:** `MarcarAnuladoView` (`core/comprobantes/vistas_anulados.py`). **Plantilla:** `comprobantes/anulado/marcar.html`.

| `modelo` (slug) | Comprobante | Permiso | Vuelve a |
|---|---|---|---|
| `factura` | Factura | `change_anulado_sri_sale` | `/pos/sale/admin/` |
| `nota-credito` | Nota de crédito | `change_anulado_sri_creditnote` | `/pos/credit/note/admin/` |
| `retencion` | Retención emitida | `change_anulado_sri_retencion` | `/comprobantes/retenciones/` |
| `liquidacion` | Liquidación de compra | `change_anulado_sri_liquidacioncompra` | `/comprobantes/liquidaciones/` |
| `nota-debito` | Nota de débito | `change_anulado_sri_notadebito` | `/comprobantes/notas-debito/` |
| `guia` | Guía de remisión | `change_anulado_sri_guiaremision` | `/comprobantes/guias/` |

- Un slug desconocido o un comprobante de otra empresa responden 404.
- **Roles:** solo Propietario y Administrador. Los demás reciben el permiso denegado común.
- **Plan:** gratuito y vencido la bloquean. Marcar no devuelve cupo.

**Contexto de la plantilla**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Marcar como anulada en el SRI: {nombre} {numero}» |
| `modelo` | str | El slug |
| `nombre` | str | «factura», «nota de crédito», «retención», «liquidación de compra», «nota de débito» o «guía de remisión» |
| `doc` | modelo | El comprobante |
| `numero` | str | `voucher_number_full` |
| `fecha_emision` | date | Fecha efectiva de emisión (la del SRI, la de autorización o la de registro) |
| `receptor` | str | «NOMBRE · identificación» |
| `total` | Decimal o `None` | Total (en la retención, lo retenido); `None` en la guía |
| `autorizacion` | str | Clave de acceso o `''` |
| `impedimentos` | list[str] | Si hay alguno, el botón sale deshabilitado; `[]` si ya está marcado |
| `avisos` | list[str] | No bloquean |
| `efectos` | list[str] | Lo que pasará al marcar |
| `muestra_stock` | bool | Factura o NC con productos inventariados: aparece `ajustar_stock` |
| `limite_plazo` | date | Día 7 del mes siguiente a la emisión |
| `pide_confirmar_plazo` | bool | La fecha revisada pasa del límite |
| `form` | `AnuladoSRIForm` | Formulario |
| `url_lista` | str | Listado al que se vuelve |
| `anulado` | `None` o dict | `{fecha, motivo, por (nombre), registrado_en}` si ya estaba marcado; en ese caso la página es de solo lectura |

En el GET la revisión se hace con la fecha de hoy; tras un POST con error, con la fecha enviada.

**Campos (`AnuladoSRIForm`)**

| Campo | Tipo | Obligatorio | Validación |
|---|---|---|---|
| `fecha` | `<input type="date">`, inicial hoy; etiqueta «Fecha de la anulación en el SRI» | Sí | El servicio comprueba que no sea futura ni anterior a la emisión |
| `motivo` | texto largo; etiqueta «Motivo» | Sí | De 10 a 300 caracteres |
| `ajustar_stock` | casilla, marcada al abrir; etiqueta «Ajustar el inventario». Solo existe si `muestra_stock` | No | — |
| `confirmar_numero` | texto, máximo 20; etiqueta «Escribe el número del comprobante para confirmar» (la plantilla añade el número) | Sí | Igual a `numero` |
| `confirmo_sri` | casilla; etiqueta «Ya anulé este comprobante en SRI en línea y, si correspondía, el receptor aceptó la anulación» | Sí | — |
| `confirmo_plazo` | casilla; etiqueta «La anulación es posterior al dd/mm/aaaa: confirmo que el SRI la aceptó». Se muestra siempre | Solo si `fecha` pasa de `limite_plazo` | — |

**Acción:** POST con `action=marcar` (otro valor vuelve a mostrar la página sin hacer nada). Si sale bien, redirige a `url_lista` con «La {nombre} {numero} quedó marcada como anulada en el SRI. No se envió nada al SRI.» y se audita como `comprobante_anulado_sri`.

**Texto fijo obligatorio** (está en la plantilla y lo comprueba una prueba): «Esto solo registra en FacturaPorAquí una anulación que ya hiciste en SRI en línea. No se envía nada al SRI y no se devuelve el cupo del plan. El SRI acepta anulaciones hasta el día 7 del mes siguiente a la emisión y no permite anular facturas a consumidor final.»

**Estados:** sin marcar → (marcar) → anulado en el SRI. Es final: en esta fase no se puede desmarcar. Si ya estaba marcado, la página muestra «Este comprobante ya está marcado como anulado en el SRI desde el {fecha}», con « (marcado por {por} el {registrado_en})» si se sabe quién lo marcó, seguido de «. Motivo: {motivo}» y el enlace «Volver al listado».

**Impedimentos** (texto exacto; deshabilitan el botón y, si aparecen al guardar, salen como error del formulario)
- Generales:
  - «Solo se marca como anulado un comprobante autorizado por el SRI.» (la factura admite también `canceled`)
  - «Este comprobante ya está marcado como anulado en el SRI desde el {fecha}.»
  - «El ticket de venta no es un comprobante del SRI: no se anula en el SRI.»
  - «La fecha de anulación no puede ser futura.»
  - «La fecha de anulación no puede ser anterior a la emisión ({fecha}).»
- Consumidor final (factura con fecha efectiva desde el 01/01/2026): «El SRI no permite anular facturas emitidas a consumidor final (Res. NAC-DGERCGC25-00000014, desde el 01/01/2026).»
- Notas de crédito de la factura:
  - «Primero marca como anulada la nota de crédito {numero}: modifica esta factura.»
  - «La nota de crédito {numero} está en proceso en el SRI: espera su respuesta.»
  - «Elimina antes la nota de crédito {numero}, que el SRI no autorizó o no se envió.»
- Notas de débito de la factura:
  - «Primero marca como anulada la nota de débito {numero}.»
  - «La nota de débito {numero} está en proceso en el SRI: espera su respuesta.»
  - «Elimina antes la nota de débito {numero}, que el SRI no autorizó o no se envió.»
- Retenciones:
  - «Primero anula el registro de la retención {numero} que te hizo el cliente.» (factura)
  - «Primero marca como anulada la retención {numero} emitida sobre esta liquidación.» (liquidación)
- Cobros (factura o ND): «La cuenta por cobrar tiene cobros por {valor}. Elimínalos o regístralos en el comprobante que la reemplace antes de marcarla como anulada.» ({valor} como `$23,00`)

**Avisos** (no bloquean)
- «La factura tiene guías de remisión autorizadas ({numeros}): anúlalas también en SRI en línea si corresponde.»
- «El inventario de {producto} quedará en {n}.»

**Efectos que se anuncian** (los importes con coma: `$23,00`)
- Factura:
  - «Se registrará un abono de anulación de {valor} en la cuenta por cobrar.»
  - «Si ajustas el inventario, se devolverán al inventario {cantidad} unidades de {producto}.»
  - «La factura ya no admitirá notas de crédito, notas de débito, guías de remisión ni retenciones recibidas nuevas.»
- Nota de crédito:
  - «Se revertirá el abono de {valor} de esta nota en la cuenta por cobrar.»
  - «Se abonarán {valor} de la {nota de crédito o retención} {numero}, que antes superaba el saldo de la cuenta por cobrar.» (una línea por documento que recibe el saldo liberado)
  - «Si ajustas el inventario, se descontarán del inventario {cantidad} unidades de {producto} (se deshace la devolución).»
  - «La factura {numero} volverá a «Autorizada»: deja de estar cubierta por notas de crédito.»
  - «Sus cantidades podrán acreditarse otra vez en la factura.»
- Nota de débito: «Se registrará un abono de anulación de {valor} en la cuenta por cobrar de la nota de débito.»
- Retención: «La compra podrá tener una nueva retención.»
- Liquidación: «La compra volverá a necesitar una liquidación de compra.»
- Guía: «Las cantidades de esta guía vuelven a quedar pendientes de traslado.»

**Errores de los campos**
- `fecha`: «Este campo es obligatorio.» · «Introduzca una fecha válida.»
- `motivo`: «Escribe el motivo de la anulación (al menos 10 caracteres).» · «Asegúrese de que este valor tenga menos de 300 caracteres (tiene N).»
- `confirmar_numero`: «Este campo es obligatorio.» · «Escribe el número {numero} para confirmar.»
- `confirmo_sri`: «Confirma que ya lo anulaste en SRI en línea.»
- `confirmo_plazo`: «La fecha pasa del plazo del SRI (dd/mm/aaaa): confirma que el SRI aceptó la anulación.»

**Errores del formulario al guardar** (no se guarda nada)
- El primer impedimento que aparezca en ese momento.
- «Otra operación usaba este comprobante al mismo tiempo: no se guardó nada. Inténtalo de nuevo.» (cruce de bloqueos en PostgreSQL)
- «No se pudo marcar: falló un ajuste relacionado ({Excepción}). No se guardó nada; inténtalo de nuevo o avisa a soporte.» (falló un receptor de la señal `anulado_en_sri`, por ejemplo de Compras)

**No cambiar:**
- Los nombres de los campos, `action=marcar`, el CSRF y el texto fijo.
- La prueba `test_impedimento_deshabilita_y_receptor_que_falla_muestra_el_error` busca literalmente `value="marcar" class="btn btn-danger" disabled`. Si Codex cambia las clases del botón, hay que ajustar esa prueba con el integrador.

**Libre para el diseño:** la presentación de impedimentos, avisos y efectos, la cabecera y el bloque de solo lectura.

**Diferencias con la especificación:**
- Mensajes añadidos: «Escribe la fecha de anulación.» (código `fecha`, del servicio), los impedimentos de ND en proceso o sin enviar, el del cruce de bloqueos y el de receptor que falla (la especificación no daba texto).
- Los efectos de inventario empiezan con «Si ajustas el inventario, …».
- Se añade el efecto de excedentes de la nota de crédito.

---

## 9. Facturas emitidas: listado (modificada)

- **Ruta:** `GET/POST /pos/sale/admin/`, nombre `sale_admin_list`. **Vista:** `SaleListView` (de P, sin cambios).
- **Plantilla:** `sale/admin/list.html`. La región de O2 añade `{% load static permisos %}` y `{% permisos_de 'change_anulado_sri_sale' 'add_retencionrecibida' as fpa_permisos %}{{ fpa_permisos|json_script:'fpa-permisos' }}`. **JS:** `core/pos/static/sale/admin/js/list.js`.
- **Permiso:** `view_sale` (Propietario, Administrador, Contador, Vendedor y Consulta). Las opciones nuevas dependen de `fpa-permisos`; el servidor vuelve a comprobar cada permiso.
- **JSON de `search`:** `Sale.toJSON()` con la clave nueva `anulado_sri`: `null` o `{fecha: 'AAAA-MM-DD'}`. No lleva motivo ni usuario, porque el portal del cliente usa el mismo `toJSON`.

**Interfaz**
- Número, fecha de registro y cliente con `render.text()`; el tipo de comprobante, escapado.
- Estado: si `anulado_sri`, la insignia «Anulada en el SRI (dd/mm/aaaa)» (`badge-secondary`) en lugar del estado.
- Opciones de una factura anulada (estado autorizado): Detalle de productos, ticket, A4 y «Descargar xml». No aparecen correo, nota de crédito, nota de débito, guía ni retención recibida.
- En una factura `01` sin anular, autorizada o cubierta por NC (`authorized`, `authorized_and_sent_by_email`, `canceled`):
  - «Registrar retención recibida» → `/comprobantes/retenciones-recibidas/add/<id>/`, si el rol tiene `add_retencionrecibida` y el cliente no es consumidor final;
  - «Marcar como anulada en el SRI» → `/comprobantes/anulados/factura/<id>/update/`, si tiene `change_anulado_sri_sale` y el cliente no es consumidor final o la emisión es anterior al 01/01/2026.
  - La emisión que usa el JS es `emission_date || authorization_date || date_joined`. Consumidor final = tipo de identificación `07` o identificación `9999999999999`.

**No cambiar:** el `<script id="fpa-permisos" type="application/json">` (lo comprueba una prueba), las funciones `fpaTexto`, `fpaPermiso`, `fpaFechaCorta`, `fpaConsumidorFinal` y `fpaAnulableEnSri`, la variable `fpaPermisos` y las rutas de los enlaces.

**Libre para el diseño:** iconos, orden dentro del menú «Opciones» y aspecto de la insignia.

---

## 10. Notas de crédito: listado (modificada)

- **Ruta:** `GET/POST /pos/credit/note/admin/`, nombre `credit_note_admin_list`. **Vista:** `CreditNoteListView`.
- **Plantilla:** `credit_note/admin/list.html`, con `{% permisos_de 'change_anulado_sri_creditnote' as fpa_permisos %}{{ fpa_permisos|json_script:'fpa-permisos' }}`. **JS:** `core/pos/static/credit_note/admin/js/list.js`.
- **Permiso:** `view_credit_note`. Marcar exige `change_anulado_sri_creditnote`.
- **JSON de `search`:** `CreditNote.toJSON()` (sin `abono_cxc`) más:
  - `anulado_sri`;
  - `cxc_ajuste`: `{id, name}`;
  - `excedente_cxc`: texto `"0.00"`. Es la parte del total que no se abonó (distinta de cero en `parcial` y `sin_saldo`) y vale `"0.00"` si la nota está anulada en el SRI.

Valores de `cxc_ajuste`:

| id | name |
|---|---|
| `no_aplica` | Anterior a la regla: no ajusta la cuenta por cobrar |
| `pendiente` | Se aplica al autorizarse |
| `aplicada` | Aplicada a la cuenta por cobrar |
| `parcial` | Aplicada en parte: el resto excede el saldo |
| `sin_cxc` | Venta de contado: sin cuenta por cobrar |
| `sin_saldo` | La cuenta por cobrar ya estaba saldada |
| `revertida` | Revertida al anular el comprobante |

**Interfaz**
- Número, fecha de registro, factura y cliente con `render.text()`.
- Estado: la insignia, debajo «Cuenta por cobrar: {cxc_ajuste.name}» y, si `excedente_cxc != "0.00"`, «Saldo a favor del cliente: ${excedente}». Si está anulada: la insignia «Anulada en el SRI (dd/mm/aaaa)» y la línea de la cuenta.
- Opciones:
  - nota anulada (estado autorizado): «Imprimir pdf» y «Descargar xml», sin correo;
  - autorizada sin anular: «Marcar como anulada en el SRI» → `/comprobantes/anulados/nota-credito/<id>/update/` si el rol tiene el permiso, y luego correo, pdf y xml.
- Al crear una nota de crédito, la búsqueda de facturas ya no ofrece las anuladas en el SRI.

**No cambiar:** `#fpa-permisos` y las funciones `fpaTexto`, `fpaPermiso` y `fpaFechaCorta`. **Libre para el diseño:** dónde va la información de la cuenta por cobrar (columna propia o ayuda) y el aspecto del aviso de saldo a favor.

---

## 11–14. Retenciones emitidas, liquidaciones, notas de débito y guías: listados (modificados)

| Listado | Ruta y nombre | Plantilla | Variable de la lista | Permiso para ver | Slug para marcar |
|---|---|---|---|---|---|
| Retenciones | `/comprobantes/retenciones/`, `comprobantes_retenciones` | `comprobantes/retencion/list.html` | `retenciones` | `view_retencion` | `retencion` |
| Liquidaciones | `/comprobantes/liquidaciones/`, `comprobantes_liquidaciones` | `comprobantes/liquidacion/list.html` | `liquidaciones` | `view_liquidacioncompra` | `liquidacion` |
| Notas de débito | `/comprobantes/notas-debito/`, `comprobantes_notas_debito` | `comprobantes/notadebito/list.html` | `notas` | `view_notadebito` | `nota-debito` |
| Guías | `/comprobantes/guias/`, `comprobantes_guias` | `comprobantes/guia/list.html` | `guias` | `view_guiaremision` | `guia` |

- **Vista:** `ComprobanteListView` y sus subclases (`core/comprobantes/views.py`). Se renderizan en el servidor, con autoescape.
- **Contexto añadido:** `puede_anular` (bool, `change_anulado_sri_<modelo>`). Siguen `puede_emitir` y `puede_eliminar`.
- **Por fila:**
  - Si `anulado_sri_fecha`: `<span class="badge badge-secondary fp-anulado-sri">Anulada en el SRI (dd/mm/aaaa)</span>` en lugar del estado.
  - Si no está anulado, `puede_anular` y el estado es autorizado: el enlace «Marcar como anulada en el SRI» (`{% url 'comprobantes_marcar_anulado' '<slug>' pk %}`).
  - «Enviar al SRI» solo existe para estados no autorizados, así que nunca sale en una anulada.
  - En liquidaciones, el botón «Retención» se oculta si la liquidación está anulada.
- Los `messages` se muestran dentro de la página.

**No cambiar:** las URL de los enlaces y la condición de permiso. **Libre para el diseño:** el aspecto de la insignia y de los botones.

**Diferencia con la especificación:** ocultar «Retención» en una liquidación anulada no estaba pedido; el servicio ya lo rechaza.

---

## 15–16. Portal del cliente: facturas y notas de crédito (modificadas)

- **Rutas:** `/pos/sale/client/` (`sale_client_list`, `SaleClientListView`, permiso `view_sale_client`) y `/pos/credit/note/client/` (`credit_note_client_list`, `CreditNoteClientListView`). Rol Cliente.
- **JS:** `core/pos/static/sale/client/js/list.js` y `core/pos/static/credit_note/client/js/list.js`. Si `anulado_sri`, la columna de estado muestra «Anulada en el SRI» (sin fecha). Las plantillas no cambian.
- **Diferencia con la especificación:** el §6 no las mencionaba (solo decía que el `toJSON` no lleva motivo ni usuario porque lo usa el portal).

---

## 17. Empresa (modificada)

- **Ruta:** `GET/POST /pos/company/update/`, nombre `company_update`. **Vista:** `CompanyUpdateView`.
- **Plantilla:** `company/create.html` (extiende `form.html`). **JS:** `core/pos/static/company/js/form.js`.
- **Permiso:** `change_company` (Propietario y Administrador; Contador, Vendedor y Consulta no tienen el módulo). **Plan:** se abre con cualquier plan.

**Campos nuevos** (fieldset «Configuración tributaria»; los dos nombres van completos en la lista de ese bloque y en la de exclusión de «Preserve additional fields», que comparan por subcadena)

| Campo | Tipo | Obligatorio | Opciones |
|---|---|---|---|
| `tipo_contribuyente` | select (select2); etiqueta «Tipo de contribuyente»; ayuda «Sociedad o persona natural, obligada o no a llevar contabilidad. Define tus formularios y anexos.» | No | `''` «Sin indicar», `sociedad` «Sociedad», `pn_obligada` «Persona natural obligada a llevar contabilidad», `pn_no_obligada` «Persona natural no obligada a llevar contabilidad» |
| `periodicidad_iva` | select (select2); etiqueta «Declaración del IVA»; ayuda «Mensual. Semestral solo si vendes únicamente con tarifa 0 %, te retienen todo el IVA o estás en el RIMPE.» | No | `''` «Sin indicar», `mensual` «Mensual», `semestral` «Semestral» |

No tienen valor inicial: se muestra lo guardado (`''` en las empresas existentes). Guardar sin tocarlos deja `''`.

**Contexto añadido**

| Nombre | Tipo | Significado |
|---|---|---|
| `sugerencias_tributarias` | dict | `tipo` y `periodicidad`: tuplas `(código, motivo)` (código `''` si no hay sugerencia); `faltan`: campos vacíos; `tipo_nombre` y `periodicidad_nombre`: etiqueta del código sugerido. **Nunca se guardan solas.** |
| `vencimientos` | list[dict] | Próximos 90 días, ordenados por fecha límite. Cada uno: `obligacion` (`'104'` o `'103'`), `periodo` (`'AAAA-MM'`, `'AAAA-S1'` o `'AAAA-S2'`), `desde`, `hasta`, `fecha_nominal`, `fecha_limite` (date), `confirmado` (bool), `feriados_cargados` (bool) y `nota` (str) |
| `vencimientos_aviso` | str | `''`, o «Revisa el RUC de la empresa: con él se calculan tus fechas de vencimiento.» si el RUC no es válido |

Motivos de las sugerencias:
- Tipo:
  - «RUC de sociedad o entidad pública»
  - «RUC de persona natural (tercer dígito N) obligada a llevar contabilidad»
  - «RUC de persona natural (tercer dígito N) no obligada a llevar contabilidad»
  - «No se puede sugerir: revisa el RUC de la empresa.» (código vacío)
- Periodicidad:
  - «Eres agente de retención: declaras el IVA cada mes»
  - «Estás en el RIMPE: puedes declarar el IVA cada semestre»
  - «Régimen general: el IVA se declara cada mes»

Notas de los vencimientos:
- «Plazo semestral por confirmar (RLRTI art. 158, no verificado en la norma del repo).»
- «Contribuyente especial: confirma tu plazo.»
- «Si la fecha cae en feriado nacional, el plazo pasa al siguiente día hábil.» (siempre, porque no hay feriados cargados)
- «Periodicidad sugerida ({periodicidad}): complétala en Empresa.» (sin periodicidad guardada)

El 103 sale si la empresa es agente de retención o emitió una retención autorizada en el mes.

**Interfaz**
- Si `faltan`: alerta «Completa el tipo de contribuyente y la declaración del IVA: con ellos se calculan tus vencimientos.».
- Por cada select vacío que tiene sugerencia: «Tipo de contribuyente · Sugerencia: {tipo_nombre} ({motivo})» o «Declaración del IVA · Sugerencia: {periodicidad_nombre} ({motivo})», con `<button type="button" data-fpa-sugerencia="<campo>" data-valor="<código>">Usar sugerencia</button>`. El botón solo cambia el select en el navegador (y dispara `change`); la empresa decide si guarda.
- Tabla «Próximos vencimientos (90 días)»: Formulario, Período, Fecha límite (dd/mm/aaaa) y Nota (insignia «Por confirmar» si `confirmado` es falso, más la nota). Si no hay ninguno: «No hay vencimientos del 104 ni del 103 en los próximos 90 días.».

**Acción:** `POST action=create_or_edit`, como hoy. Responde `{}` o `{"error": {campo: [mensajes]}}`. Si cambió el tipo o la periodicidad, se audita `company_change` con `campos: {campo: [antes, después]}`.

**Errores nuevos** (en el campo `tipo_contribuyente`; solo si el tipo está indicado)
- «Las sociedades y las personas naturales obligadas llevan contabilidad: marca «Obligado a llevar contabilidad: Sí».»
- «Una persona natural no obligada a llevar contabilidad tiene «Obligado a llevar contabilidad: No».»
- «El RUC {ruc} es de persona natural (tercer dígito {d}): no corresponde a una sociedad.»
- «El RUC {ruc} es de sociedad o entidad pública (tercer dígito {d}).»

**No cambiar:** `[data-fpa-sugerencia]` y `data-valor` (los usa el JS y los comprueban las pruebas), `select[name="tipo_contribuyente"]`, `select[name="periodicidad_iva"]` y la opción `<option value="" selected>Sin indicar</option>` (también la comprueba una prueba).

**Libre para el diseño:** la ubicación del aviso y de las sugerencias, y la tabla de vencimientos (`.fp-sugerencias-tributarias`, `.fp-vencimientos`).

**Diferencias con la especificación:**
- `vencimientos` trae todos los campos del `Vencimiento`, no solo cinco.
- Se añaden `tipo_nombre`, `periodicidad_nombre` y `vencimientos_aviso`.
- Los errores de coherencia se informan en el campo `tipo_contribuyente`.

---

## 18–20. Reportes de ventas, cuentas por cobrar y resultados (modificados)

- **Comunes:**
  - Vistas con `GroupModuleMixin` (el permiso es el módulo).
  - Plantillas que extienden `report.html`.
  - Con plan vencido se abren y `search_report` funciona.
- **Campo nuevo `alcance`** (`ReportForm`): select con `name="alcance"`, etiqueta «Comprobantes», `required=False`, inicial `declarables`, clase `form-control`.
  - El JS lo envía como `$('select[name="alcance"]').val() || 'declarables'` y vuelve a listar al cambiarlo.
- **Acción:** `POST action=search_report`, con `start_date`, `end_date` y `alcance`. Con un alcance desconocido: `{"error": "Elige qué comprobantes mostrar."}`.

| `alcance` | Etiqueta | Qué incluye |
|---|---|---|
| `declarables` (por defecto) | Autorizados en producción (para declarar) | Producción; facturas `01` autorizadas o `canceled`; NC autorizadas; sin la marca de anulado; por fecha de emisión efectiva |
| `anulados_sri` | Anulados en el SRI | Producción, con la marca |
| `no_autorizados` | Sin autorizar, en proceso o rechazados | Producción, fuera de los autorizados |
| `pruebas` | Ambiente de pruebas | Ambiente de pruebas (incluye tickets) |
| `todos` | Todos los registros (como antes, por fecha de registro) | Exactamente lo de antes: sin filtro, por fecha de registro |

**Importante para la propietaria:** por defecto los reportes muestran ahora solo facturas autorizadas en producción, por fecha de emisión. Los tickets y los comprobantes de pruebas ya no salen salvo que se elija otro alcance; «Todos los registros» reproduce lo de antes.

**Ventas** (`/reports/sale/`, `sale_report`, `SaleReportView`, `sale_report/report.html`, JS `core/reports/static/sale_report/js/report.js`)
- Filas: `Sale.toJSON()` más `fecha_emision_efectiva` (`AAAA-MM-DD`) y `fecha_emision_origen` (`sri`, `autorizacion` o `registro`).
- Columnas: Número, Fecha de emisión (con « *» si el origen no es `sri`), Cliente, Forma de pago, Subtotal, Descuento, IVA, Total y Estado («Anulada en el SRI» si tiene la marca).
- Nota al pie: «* Fecha tomada de la autorización o del registro: la venta no tiene la fecha de emisión del SRI.»

**Cuentas por cobrar** (`/reports/ctas/collect/`, `ctas_collect_report`, `CtasCollectReportView`, `ctas_collect_report/report.html`, JS `core/reports/static/ctas_collect_report/js/report.js`)
- Filas: el `toJSON()` de la pantalla 1 más `fecha_emision_efectiva`. El criterio es el del documento de cada cuenta (la factura o la ND).
- Columnas: Documento («ND » delante si es de ND), Cliente, Identificación, Fecha de emisión, Fecha de plazo (`end_date`), Deuda, Saldo (`saldo_texto`) y Estado (`estado.name`).

**Resultados** (`/reports/results/`, `results_report`, `ResultsReportView`, `results_report/report.html`, JS `core/reports/static/results_report/js/report.js`)
- Respuesta: `[{"name": "Compras", "y": …}, {"name": "Ventas", "y": …}, {"name": "Gastos", "y": …}]`.
- Con un alcance distinto de `todos`, «Ventas» = Σ total de las facturas del alcance − Σ total de las NC del mismo alcance (cada una por su fecha efectiva). «Compras» y «Gastos» no cambian: son del integrador.
- Título del gráfico: «Ventas (por emisión) frente a compras y gastos (por registro)». Nota: «Ventas: facturas del alcance elegido menos sus notas de crédito, por fecha de emisión. Compras y gastos por fecha de registro.»

**No cambiar:** `select[name="alcance"]` y sus valores, `action=search_report`, y el escape de las columnas de cliente y documento (lo revisa `test_escape_listados`).

**Libre para el diseño:** ubicación del selector junto al rango de fechas, rótulos de columnas y notas.

**Diferencias con la especificación:**
- En el reporte de cuentas por cobrar cambian también las columnas (documento primero, fecha de emisión, estado como texto).
- Con `todos`, la fecha efectiva se calcula en la vista.
- Si `data` ya era una lista, el error ahora se devuelve bien (antes lanzaba `TypeError`).

---

## A. Datos que O2 entrega a la pantalla de O1: retención recibida desde un 07 importado

La pantalla es de O1 (`GET/POST /importacion/documentos/<pk>/retencion-recibida/`, plan Ilimitado). O1 debe exigir su permiso de documentos recibidos **y** `add_retencionrecibida`. O2 entrega dos funciones en `core/comprobantes/retenciones_recibidas.py`, que trabajan con los dataclasses de B0 (`core/importacion/recibidos.py`).

**`revisar_importacion(company, documento, leida)`** (no escribe nada) devuelve:

```
{'documento_id': int, 'numero': '001-001-000000123', 'agente_ruc': str, 'agente_razon_social': str,
 'fecha_emision': date, 'ambiente': int, 'verificacion': 'verificada_sri' | 'declarada_en_archivo',
 'puede_registrar': bool,
 'errores_documento': [{'codigo', 'texto'}],
 'sustentos': [{'num_doc_sustento': '001-001-000000045', 'venta_id': int | None, 'venta_numero': str,
                'cliente': str, 'ya_registrada_id': int | None,
                'resultado': <dict de calcular() sin 'doc'> | None,
                'error': {'codigo', 'texto'} | None}]}
```

`resultado` trae `lineas`, `total_renta`, `total_iva`, `total_retenido`, `abono_previsto`, `excedente`, `cxc_estado`, `advertencias` y `topes`.

**`registrar_desde_importacion(company, usuario, documento, leida, request=None)`**
- Registra una retención por sustento, todo o nada. Es idempotente por (documento, factura).
- Al final marca el documento como incorporado (función de O1) y devuelve la lista de retenciones.
- Si falla, lanza `ErrorRetencionRecibida` con el texto «Sustento 001-001-000000045: …» y no guarda nada.

**Errores de documento** (código `codigo` entre paréntesis)
- «Los datos leídos no corresponden a este documento.» (`documento_no_corresponde`)
- «Este documento no es un comprobante de retención.» (`no_es_retencion`)
- «El documento fue descartado.» (`documento_descartado`)
- «El sistema todavía no registra retenciones de ISD (código 6): registra a mano la parte de renta e IVA.» (`impuesto_no_soportado`)

**Errores por sustento:** los de la pantalla 6, más:
- «El documento sustento {numero} no es una factura.» (`sustento_no_factura`)
- «No hay una factura {numero} emitida por la empresa en el ambiente {ambiente}.» (`sustento_no_encontrado`)
- «Hay más de una factura con el número {numero}: regístrala a mano.» (`sustento_ambiguo`)
- «La factura {numero} aparece en varios sustentos de esta retención: regístrala a mano con todas sus líneas.» (`sustento_repetido`)

La ficha de la retención (pantalla 7) enlaza al documento con la ruta `importacion_documento`. La prueba de punta a punta (O1 lee, O2 registra) es del integrador.

**Diferencia con la especificación:** `sustento_repetido` es nuevo. La pantalla de O1 debe mostrar su texto como los demás errores de sustento.

---

## B. Pendiente para Codex

1. **Diseño de las pantallas nuevas** (retenciones recibidas: listado, elegir factura, registrar y ficha; marcar anulado) y ajuste de las modificadas, con AdminLTE, `skin.html` y componentes `fp-*`. Las maquetas de `entregas/facturaporaqui/propuestas/fase-contable/` no cubren estas pantallas. Probar a 360, 390, 768, 1024 y 1440 px, con teclado y movimiento reducido. El registro de retenciones tiene hasta 10 líneas: en móvil conviene `.fp-mobile-lines` con `data-label`, sin clonar los inputs.
2. **Mensajes de éxito con aspecto de error.** El marco (`hzt_body.html` / `vtc_body.html`) muestra todo mensaje con `message_error` (título «Error»). Las pantallas de comprobantes, además, lo pintan dentro de la página, así que se ve dos veces. Decidirlo con el integrador (O2 no tocó el marco).
3. **Marcar anulado con una fecha inválida.** Si se envía una fecha futura o anterior a la emisión, el error vuelve como impedimento y el botón queda deshabilitado aunque se corrija la fecha: hay que recargar la página. Propuesta: volver a habilitar el botón con JS al cambiar la fecha, o que el integrador trate esos dos errores como errores del campo `fecha`.
4. **Botones de eliminar en cuentas por cobrar.** El de eliminar cobro y la papelera de la cuenta se dibujan para todos los roles; con Contador o Consulta el servidor responde 403. Se pueden ocultar con `{% permisos_de 'delete_ctas_collect' %}` y `json_script`, con el mismo patrón de facturas (cambio de plantilla y JS, coordinado con el integrador).
5. **Plan vencido en la ficha de una retención recibida.** El formulario de anular se muestra, pero el POST recibe un JSON 403 del middleware que el navegador enseña tal cual. Hace falta que el servidor diga si el plan está vencido para ocultarlo (integrador).
6. **Formato de los importes en los mensajes.** Las retenciones recibidas usan punto (`$1.30`); la marca de anulado y los efectos usan coma (`$23,00`). Unificar con el integrador; las pruebas comprueban los textos actuales.
7. **Texto antiguo** en la validación del navegador del registro de cobros: «Seleccione un cuenta por pagar» debería decir «Elige la cuenta por cobrar.».
8. **Reportes:** explicar en pantalla que el valor por defecto («Autorizados en producción») ya no incluye tickets ni pruebas.
9. **Fragmentos que comprueban las pruebas** (si se cambian, ajustar la prueba con el integrador):
   - `value="marcar" class="btn btn-danger" disabled` (test_anulados_sri);
   - el texto fijo de la marca de anulado;
   - `<script id="fpa-permisos" type="application/json">`, `"change_anulado_sri_sale": true` y `"change_anulado_sri_creditnote": true`;
   - `|json_script:'fpa-permisos'` en las plantillas de facturas y NC, y `JSON.parse(nodo.textContent)` en sus JS;
   - que no aparezcan `value="calcular"` ni `value="registrar"` con impedimento;
   - `data-fpa-sugerencia="tipo_contribuyente" data-valor="sociedad"`, `data-fpa-sugerencia="periodicidad_iva" data-valor="mensual"` y `<option value="" selected>Sin indicar</option>`;
   - los mensajes de éxito de retenciones y de la marca, y «Escribe el motivo (al menos 10 caracteres).»;
   - el escape de columnas y la ausencia de `|safe` (test_escape_listados).
10. **No tocar `HANDOFF.md` desde esta rama:** el integrador publica este contrato.

---

## C. Diferencias con la especificación (resumen)

1. Cuentas por cobrar: error nuevo «El cobro ya no existe: actualiza la página.»; el botón de eliminar cobro se dibuja en todo cobro vigente, sin mirar el permiso (decide el servidor con 403).
2. Registrar cobro: mensajes nuevos «Elige la cuenta por cobrar.», «La cuenta por cobrar no existe: actualiza la página.» y «Escribe la fecha del cobro (AAAA-MM-DD).»; la búsqueda incluye números de factura y de ND; «anterior a la venta» se compara con la fecha de la cuenta por cobrar.
3. Elegir factura: excluye también a los clientes con tipo de identificación `07`.
4. Registrar retención: tercera variante del éxito («La cuenta por cobrar ya estaba saldada: no se abonó nada.»); la de contado empieza con «Retención {numero} registrada.»; error de campo «Elige el código de la retención de esta línea.»; `resumen` con más claves y `topes`; un `action` desconocido = `calcular`; el duplicado se comprueba antes que los topes.
5. Ficha: segunda variante del éxito («Retención {numero} anulada.»); contexto `error_permiso`; un `action` desconocido también da 403.
6. Marcar anulado: impedimentos nuevos de ND en proceso o sin enviar; mensaje de servicio «Escribe la fecha de anulación.»; textos para el cruce de bloqueos y para el receptor que falla; efectos de inventario con «Si ajustas el inventario, …» y efecto nuevo de excedentes.
7. Listado de liquidaciones: «Retención» oculto si la liquidación está anulada.
8. Portal del cliente: insignia «Anulada en el SRI» en facturas y NC (no figuraba en el §6).
9. Empresa: `vencimientos` con todos los campos; `tipo_nombre`, `periodicidad_nombre` y `vencimientos_aviso` nuevos; errores en el campo `tipo_contribuyente`.
10. Reporte de cuentas por cobrar: columnas nuevas (documento, fecha de emisión, estado como texto); con `todos`, fecha efectiva calculada en la vista.
11. 07 importado: error nuevo `sustento_repetido`.
12. Importes de los mensajes: punto en retenciones recibidas y coma en la marca de anulado (la especificación usaba los dos sin decidir).
