# Contrato de pantallas — Etapa 1, Proformas (rama P)

29/10/2026 · Escrito desde el código de la rama `fase/etapa1-proformas` en `3f91e75`, fusionada en `plataforma` en `7f0e576` junto con las demás ramas de la fase contable (orden y estado en `HANDOFF.md`).

> **Estado en `plataforma` tras la integración (29/10/2026).** Este contrato es **definitivo** sobre la base que indica
> `HANDOFF.md`. Al integrar no cambió ningún campo, acción, permiso, mensaje ni identificador de Proformas. Único cambio:
> los 8 códigos del apartado B ya son choices de `AuditLog.ACTIONS` (migración `tenancy/0007_acciones_fase_contable`)
> y `AuditLog.detail` usa `DjangoJSONEncoder`. Lo que este documento atribuye al «integrador» y no se menciona aquí sigue
> pendiente en `HANDOFF.md`, salvo su publicación: está en «Pendiente para Codex — diseño de la fase contable» y en
> «Notas entre agentes — fase contable integrada (Claude → Codex)», no en una sección propia.

Este documento describe **lo que hace el código de la rama**, pantalla por pantalla, para que Codex haga el diseño sin romper nada y para que la propietaria vea cómo funciona. Parte de la sección 6 de su especificación interna de trabajo (no publicada) y de las decisiones del 28/10/2026, pero manda el código: cuando no coinciden, se describe el código y la diferencia queda anotada en la pantalla y en el apartado F. El integrador lo publicará en `HANDOFF.md` como «Notas entre agentes — contrato de Proformas (Claude → Codex)».

Cada ruta, nombre de campo, identificador y mensaje se tomó del código de la rama y se comprobó con `grep`.

**Estado del contrato.** Es **definitivo** para la rama P en `3f91e75`: campos, acciones, permisos, estados, mensajes e identificadores no cambian, salvo que el integrador anote un cambio al fusionar. Queda abierta una decisión de la propietaria que no cambia ningún campo ni pantalla: si los envíos fallidos cuentan para el límite de 60 por hora (apartado E). El commit base exacto para Codex lo indicará el integrador en `HANDOFF.md` después de fusionar Proformas → Compras → Ventas, y este contrato vale sobre esa base.

---

## Reglas comunes a todas las pantallas

**Lo que Codex no cambia**
- Modelos, servicios, vistas, rutas, nombres de URL y migraciones: todo `core/proformas/` salvo los estáticos, y `core/pos/views/sale/views.py`.
- Los `name=` de los campos, los valores de `action`, el `{% csrf_token %}` y la cabecera `X-CSRFToken` de los AJAX.
- Los identificadores, clases y atributos `data-*` que usa el JavaScript (se listan en cada pantalla) y los textos que comprueban las pruebas (apartado D).
- Que los botones de acción salgan **solo** de `acciones[]` del servidor. No se deducen del estado.

**Lo que queda libre para el diseño:** el marcado, el orden visual, las columnas de la lista y su orden, los iconos, las clases de Bootstrap/AdminLTE, el estilo de avisos e insignias, las etiquetas de los botones y los textos de ayuda que no estén en el apartado D. Las maquetas de `propuestas/fase-contable/` siguen siendo propuestas.

**Datos**
- La empresa activa la decide el servidor. Nunca se envía `company_id`. Un id de otra empresa responde 404 (en JSON, «La proforma no existe.»).
- Importes en JSON como texto con punto y 2 decimales (`"75.24"`): solo se muestran. El editor calcula una vista previa en JS, pero el servidor recalcula y manda. Las plantillas usan `floatformat:2`, que en pantalla y en el PDF sale con coma («75,24»).
- Fechas en JSON como `AAAA-MM-DD`. Fecha y hora como ISO con la zona de Ecuador (`2026-10-28T10:15:00-05:00`). Las plantillas muestran `d/m/Y`.
- «Hoy» es la fecha de Ecuador (`timezone.localdate()`).

**Texto de terceros** (nombres de clientes y prospectos, descripciones, condiciones, motivos, correos)
- En DataTables, toda columna de texto lleva `render: $.fn.dataTable.render.text()`.
- El HTML que arma `acciones.js` pasa cada dato por `fpAcciones.escapar`, que escapa `&`, `<`, `>`, `"` y `'`, porque los datos van dentro de atributos (`title`, `aria-label`, `href`, `data-*`). El editor arma sus filas con nodos del DOM y `.text()`/`.val()`.
- Los datos iniciales van con `json_script`, nunca con `|safe`.
- Los `messages` de Django que emite Proformas solo llevan textos fijos con número, estado, fecha o número de factura, nunca texto escrito por el usuario. Los muestra el marco general (`hzt_body.html`/`vtc_body.html`) con `message_error`, como hoy.

**Respuestas de error** (vistas de `core/proformas/views.py`)
- Forma: `{"error": "texto"}`, más `"campos"` cuando hay errores por campo.
- Estados HTTP:
  - 400: datos;
  - 403: permiso de la acción (`sin_permiso`) o plan (`"plan": "requerido"`, lo pone el middleware);
  - 404: no existe;
  - 409: estado (transición, vencida, no editable, no se elimina, límite de envíos);
  - 502: fallo del correo;
  - 500: fallo inesperado, con «No se pudo completar la acción.» (el detalle queda en el registro del servidor).
- Una `action` desconocida responde 400 «No ha seleccionado ninguna opción».
- **Excepción:** la pantalla de venta (pantalla 8) responde sus errores con HTTP 200 y `{"error": …}`, como hoy.

**Permiso denegado por la pantalla** (`GroupPermissionMixin`, sin cambios)
- GET: redirige a la última pantalla visitada con el mensaje «Tu perfil no cuenta con el permiso necesario para ingresar».
- POST: 403 `{"error": "Tu perfil no cuenta con el permiso necesario para ingresar"}`.

**Roles** (los reparte `sync_roles`; ver `core/tenancy/roles.py`)

| Acción | Propietario | Administrador | Vendedor | Contador | Consulta | Cliente |
|---|---|---|---|---|---|---|
| Ver lista, ficha y PDF (`view_proforma`) | sí | sí | sí | sí | sí | no (sin menú) |
| Crear y duplicar (`add_proforma`) | sí | sí | sí | no | no | no |
| Editar, enviar por correo, marcar enviada, aceptar, rechazar y anular (`change_proforma`) | sí | sí | sí | no | no | no |
| Eliminar un borrador nunca enviado (`delete_proforma`) | sí | sí | no | no | no | no |
| Facturar (`change_proforma` + `add_sale`) | sí | sí | sí | no | no | no |

- El Vendedor ve **todas** las proformas de la empresa (decisión 2).
- El vendedor de una proforma es quien la crea o la duplica, y no se reasigna (decisión 9).
- Sin el permiso del rol, la acción no aparece en `acciones[]`. Si alguien fuerza el POST, recibe 403 «Tu perfil no puede realizar esta acción.».

**Plan** (`PlanMiddleware`; `/proformas/` está en `RUTAS_DE_PAGO`, así que Proformas va en todos los planes pagados)

| Situación | Proformas | «Facturar» |
|---|---|---|
| Gratuito | No se abre ninguna ruta de `/proformas/`. Un GET redirige a `/suscripcion/` (si el rol gestiona el plan) o a `/dashboard/`, con el aviso del plan. Un POST responde 403 `{"error": <aviso>, "plan": "requerido"}`. El menú muestra el candado | No |
| Plan pagado activo | Todo | Sí |
| Vencido | Solo consulta: lista, ficha, PDF y las acciones `search` y `search_detalle`. `/add/`, `/update/` y `/delete/` redirigen; los demás POST reciben 403. El servidor ya reduce `acciones[]` a `ver` y `pdf`, `create_url` llega vacío y la lista muestra `mensaje_plan` | No: `facturar_bloqueado` trae el aviso del plan |
| Cupo agotado | Todo: las proformas no consumen cupo | No: `/pos/sale/admin/add/` está en `RUTAS_DE_EMISION` y `facturar_bloqueado` trae el aviso del cupo |
| Empresa en PRUEBAS (con cualquier plan pagado) | Todo | **Sí** (decisión 5): la factura queda vinculada y las pantallas avisan que no tiene validez tributaria |

Una proforma no usa la numeración de los comprobantes (`Receipt`), el cupo, el stock, las cuentas por cobrar ni el SRI. Todo eso lo hace la venta al facturarla.

---

## Estados y acciones

**Estados visibles** (`Proforma.ESTADOS_VISIBLES`, en este orden). La clase es la que pone hoy `fpAcciones.claseEstado`; el diseño la puede cambiar.

| `estado.id` | `estado.nombre` | Clase actual |
|---|---|---|
| `borrador` | Borrador | `badge-secondary` |
| `enviada` | Enviada | `badge-info` |
| `aceptada` | Aceptada | `badge-success` |
| `rechazada` | Rechazada | `badge-danger` |
| `vencida` | Vencida | `badge-warning` |
| `facturada` | Facturada | `badge-primary` |
| `anulada` | Anulada | `badge-dark` |

- «Vencida» no se guarda: es una borrador o enviada cuya «válida hasta» es anterior a hoy. El último día de validez la proforma sigue vigente.
- `estado.guardado` trae el estado real (`borrador` o `enviada` en una vencida).

**Acciones según el estado** (`ACCIONES_POR_ESTADO`, antes de filtrar por rol y plan)

| Estado visible | Acciones |
|---|---|
| borrador | `ver`, `pdf`, `editar`, `duplicar`, `enviar_correo`, `marcar_enviada`, `aceptar`, `anular`, `eliminar`* |
| enviada | `ver`, `pdf`, `editar`, `duplicar`, `enviar_correo`, `aceptar`, `rechazar`, `anular`, `facturar`** |
| vencida (guardada como borrador) | `ver`, `pdf`, `editar`, `duplicar`, `anular`, `eliminar`* |
| vencida (guardada como enviada) | `ver`, `pdf`, `editar`, `duplicar`, `rechazar`, `anular` |
| aceptada | `ver`, `pdf`, `duplicar`, `enviar_correo`, `rechazar`, `anular`, `facturar`** |
| rechazada | `ver`, `pdf`, `duplicar`, `anular` |
| facturada | `ver`, `pdf`, `duplicar` |
| anulada | `ver`, `pdf`, `duplicar` |

\* Solo si nunca se envió: `enviada_en` vacío y `envios` = 0.
\** Solo si no tiene factura vinculada y `puede_facturar` lo permite (rol, plan, cupo y configuración de facturación). El ambiente no cuenta.

**Transiciones**

| Acción | Desde (estado guardado) | Hacia | ¿Exige vigente? |
|---|---|---|---|
| crear o duplicar | — | borrador | — |
| editar | borrador | borrador | no (sirve para extender la validez) |
| editar | enviada | borrador (hay que enviarla de nuevo) | no |
| enviar_correo | borrador | enviada | sí |
| enviar_correo | enviada / aceptada | sin cambio de estado | sí (enviada) / no (aceptada) |
| marcar_enviada | borrador | enviada | sí |
| aceptar | borrador / enviada | aceptada | sí |
| rechazar | enviada / aceptada | rechazada | no |
| anular | borrador / enviada / aceptada / rechazada | anulada | no |
| facturar (al emitir la venta) | enviada vigente / aceptada | facturada | sí, si está enviada |
| se elimina su factura (solo si la venta se puede eliminar) | facturada | aceptada si alguna vez se aceptó; si no, enviada | — |
| eliminar | borrador nunca enviado | (se borra; su número no se reutiliza) | — |

- «Facturada» y «anulada» son finales.
- Una factura con la marca «Anulado en el SRI» (rama de Ventas) **no** libera la proforma: sigue «facturada» y, para volver a cotizar, se duplica (decisión 11). P no escucha la señal `anulado_en_sri`.

**Etiquetas y ejecución de cada acción** (`fpAcciones.etiquetas`; el diseño puede cambiar las etiquetas, los códigos no)

| Código | Etiqueta actual | Cómo se ejecuta |
|---|---|---|
| `ver` | Ver | Enlace a `urls.ver` |
| `pdf` | PDF | Enlace a `urls.pdf`, en pestaña nueva |
| `editar` | Editar | Enlace a `urls.editar` |
| `duplicar` | Duplicar | Confirmación «Se creará un borrador nuevo con la fecha de hoy. ¿Continuar?» y POST `action=duplicar` |
| `enviar_correo` | Enviar por correo | Modal `#fp-modal-correo` y POST `action=enviar_correo` (pantalla 7) |
| `marcar_enviada` | Marcar como enviada | Confirmación «¿Marcar la proforma como enviada al cliente?» y POST |
| `aceptar` | Marcar aceptada | Confirmación «¿Marcar la proforma como aceptada por el cliente?» y POST |
| `rechazar` | Marcar rechazada | Modal `#fp-modal-motivo` con el título «Marcar rechazada la proforma PRO-…» y POST con `motivo` |
| `anular` | Anular | Modal `#fp-modal-motivo` con el título «Anular la proforma PRO-…» y POST con `motivo` |
| `facturar` | Facturar (revisar antes de emitir) | Enlace a `urls.facturar` (pantalla 8) |
| `eliminar` | Eliminar borrador | Enlace a `urls.eliminar` (pantalla 5, que confirma) |

Si `facturar` no está en `acciones[]` y `facturar_bloqueado` trae texto, se muestra «Facturar» **deshabilitado** con ese texto en `title` y `aria-label` («Facturar: …»). En la ficha el texto también va debajo del botón. Si `facturar_bloqueado` es `null` (rol sin permiso, o un estado que no se factura), no se muestra nada.

Las acciones con POST se envían siempre a `/proformas/` (`fpAcciones.config.url_lista`), desde la lista y desde la ficha.

---

## Pantallas documentadas

| # | Pantalla | Ruta | Nombre de URL | Vista | Plantilla | Nueva o modificada |
|---|---|---|---|---|---|---|
| 1 | Lista | `/proformas/` | `proforma_list` | `ProformaListView` | `templates/proformas/list.html` | Nueva |
| 2 | Crear | `/proformas/add/` | `proforma_create` | `ProformaCreateView` | `templates/proformas/form.html` | Nueva |
| 3 | Editar | `/proformas/update/<pk>/` | `proforma_update` | `ProformaUpdateView` | `templates/proformas/form.html` | Nueva |
| 4 | Ficha | `/proformas/ver/<pk>/` | `proforma_detail` | `ProformaDetailView` | `templates/proformas/detalle.html` | Nueva |
| 5 | Eliminar | `/proformas/delete/<pk>/` | `proforma_delete` | `ProformaDeleteView` | `templates/proformas/delete.html` | Nueva |
| 6 | PDF A4 | `/proformas/pdf/<pk>/` | `proforma_pdf` | `ProformaPdfView` | `templates/proformas/pdf.html` | Nueva |
| 7 | Enviar por correo (modal de la lista y de la ficha) | POST `/proformas/`, `action=enviar_correo` | `proforma_list` | `ProformaListView` | `templates/proformas/_modales.html` y `templates/proformas/correo.txt` | Nueva |
| 8 | Facturar en la pantalla de venta | `/pos/sale/admin/add/?proforma=<pk>` | `sale_admin_create` | `SaleCreateView` | `core/pos/templates/sale/admin/create.html` | Modificada |
| 9 | Menú | grupo «Cotizaciones» | — | — | — | Modificado |

**Estáticos:** `core/proformas/static/proformas/js/acciones.js` (común a la lista y la ficha), `list.js`, `detalle.js` y `form.js`. En la venta, `core/pos/static/sale/admin/js/form.js` (`sale.cargarProforma`).

---

## 1. Lista — `GET /proformas/`

- **Vista y plantilla:** `ProformaListView`, `templates/proformas/list.html` (extiende `list.html`, que extiende `skin.html`). Carga `proformas/js/acciones.js` y `proformas/js/list.js`, e incluye `proformas/_modales.html`.
- **Permiso:** `view_proforma` (los cinco roles de personal).
- **Plan:** como en las reglas comunes. Con el plan vencido solo pasan los POST `search` y `search_detalle`.

**Contexto de la plantilla**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Proformas» |
| `list_url` | str | `/proformas/` |
| `puede_crear` | bool | El rol tiene `add_proforma` y el plan no está vencido |
| `create_url` | str o None | `/proformas/add/` si `puede_crear`. `list.html` pinta con él el botón «Nuevo registro» |
| `estados` | lista de `(id, nombre)` | Los siete estados visibles, en el orden de la tabla de estados |
| `solo_consulta` | bool | Plan vencido |
| `mensaje_plan` | str o None | Aviso del plan vencido, que se muestra arriba |
| `config` | dict (`json_script` id `fp-proforma-config`) | `{"max_destinatarios": 5, "max_mensaje": 1000, "max_motivo": 300, "url_lista": "/proformas/"}` |
| `company`, `dashboard`… | | De los procesadores de contexto, como en todas las pantallas |

**Filtros** (formulario `#fp-filtros`; no se envía como formulario, `list.js` arma el POST)

| Campo | Elemento | Regla del servidor |
|---|---|---|
| `estado` | `select#fp-estado` («Todos» = vacío) | `vencida`: borrador o enviada con «válida hasta» anterior a hoy. `borrador`/`enviada`: ese estado y vigente. Otro estado guardado: ese estado. Un valor desconocido se ignora |
| `desde` | `input[type=date]#fp-desde` | `fecha` ≥ desde (ISO; vacío o inválido = sin límite) |
| `hasta` | `input[type=date]#fp-hasta` | `fecha` ≤ hasta |
| `q` | `input[type=search]#fp-q` (`maxlength` 100) | Contiene el texto en el número, el nombre del cliente o la identificación |

«Buscar» (`submit`) recarga la tabla. `#fp-ver-todas` limpia los filtros y recarga.

**Tabla** (`table#data`, DataTables). Columnas actuales: Número, Cliente, Identificación, Vendedor, Fecha, Válida hasta, Total USD, Estado (insignia), Factura (número y, si es de PRUEBAS, la insignia «PRUEBAS · sin validez tributaria») y Acciones (`fpAcciones.botones(p, false)`, solo iconos). El orden y las columnas son libres, siempre con `render.text` en las de texto.

**Acciones POST a `/proformas/`** (`action` + `id`)

| `action` | Permiso | Parámetros | Respuesta 200 |
|---|---|---|---|
| `search` | `view_proforma` | `estado`, `desde`, `hasta`, `q` | Lista JSON de `fila` (como mucho 1000, las más recientes primero). DataTables la lee con `dataSrc` |
| `search_detalle` | `view_proforma` | `id` | `{"proforma": detalle}` (pantalla 4) |
| `duplicar` | `add_proforma` | `id` | `{"proforma": detalle de la copia, "url_editar": "/proformas/update/<id>/", "avisos": [str], "mensaje": "Se creó la proforma PRO-000013, copia de PRO-000012."}` |
| `marcar_enviada`, `aceptar` | `change_proforma` | `id` | `{"proforma": fila, "mensaje": "La proforma PRO-000012 quedó aceptada."}` |
| `rechazar`, `anular` | `change_proforma` | `id`, `motivo` (opcional; se colapsan los espacios y se corta a 300) | Igual |
| `enviar_correo` | `change_proforma` | `id`, `destinatarios`, `mensaje` | `{"proforma": fila, "aviso": bool, "mensaje": str}` (pantalla 7) |

- Tras una acción, la lista recarga la tabla sin perder la página.
- Tras duplicar, muestra el mensaje y los avisos y abre `url_editar`.
- `duplicar` copia desde cualquier estado: número nuevo, borrador, fecha de hoy, validez de 15 días, el mismo cliente (con sus datos actuales) o los datos del prospecto, las condiciones, la forma de pago, `origen` = la original, y las líneas con la tarifa **actual** de cada producto. Las líneas cuyo producto se eliminó se omiten, con el aviso «La línea «{descripcion}» no se cargó: el producto ya no existe.». La original no cambia.

**`fila`** (una proforma en la lista; también llega en las respuestas de las transiciones y del correo)

```json
{"id": 12, "numero": "PRO-000012", "fecha": "2026-10-28", "valida_hasta": "2026-11-12", "dias_para_vencer": 15,
 "estado": {"id": "enviada", "nombre": "Enviada", "guardado": "enviada"},
 "cliente": {"id": 5, "nombre": "CLIENTE FICTICIO S.A.", "identificacion": "0990000001001", "correo": "compras@example.test",
             "telefono": "", "direccion": "Av. Ficticia 1", "es_prospecto": false},
 "vendedor": {"id": 3, "nombre": "Vendedora Ficticia"},
 "subtotal_gravado": "51.70", "subtotal_cero": "18.25", "total_descuento": "3.25", "total_iva": "5.29", "total": "75.24",
 "venta": null, "envios": 1, "enviada_en": "2026-10-28T10:15:00-05:00",
 "acciones": ["ver", "pdf", "editar", "duplicar", "enviar_correo", "aceptar", "rechazar", "anular", "facturar"],
 "facturar_bloqueado": null,
 "urls": {"ver": "/proformas/ver/12/", "pdf": "/proformas/pdf/12/", "editar": "/proformas/update/12/",
          "facturar": "/pos/sale/admin/add/?proforma=12", "eliminar": null}}
```

- `dias_para_vencer`: días hasta «válida hasta» (0 = vence hoy; negativo = vencida). Solo en borrador y enviada; `null` en los demás estados, también en aceptada.
- `cliente.id` es `null` si es un prospecto (`es_prospecto: true`). Los datos del cliente son la copia guardada en la proforma.
- `vendedor` es `null` si se eliminó el usuario. Su `nombre` es el nombre del usuario o, sin nombre, su usuario.
- Cada valor de `urls` es `null` si la acción no está en `acciones[]`. `urls.eliminar` es `/proformas/delete/<id>/`.
- `facturar_bloqueado`: texto del plan, del cupo o de la configuración de facturación que falta (por ejemplo, «Para emitir facturas completa la configuración…»), o `null`.

**`venta`** (factura vinculada, o `null`)

```json
{"id": 271, "numero": "001-002-000000271", "estado": {"id": "authorized", "nombre": "Autorizada"},
 "ambiente": {"id": 1, "nombre": "PRUEBAS"}, "sin_validez_tributaria": true,
 "aviso_ambiente": "Factura emitida en el ambiente de PRUEBAS: sin validez tributaria.",
 "fecha": "2026-10-28", "total": "75.24", "url_lista": "/pos/sale/admin/",
 "url_ride": "/pos/sale/admin/print/a4/271/", "aviso": null}
```

- `ambiente` sale de la propia venta (`Sale.environment_type`: 1 = PRUEBAS, 2 = PRODUCCIÓN). Con PRUEBAS, `sin_validez_tributaria` es `true` y `aviso_ambiente` trae el texto; con PRODUCCIÓN, `false` y `null`.
- `fecha` es la fecha de emisión de la venta o, si no la tiene, la de registro.
- `url_ride` solo con los estados `authorized`, `authorized_and_sent_by_email` o `canceled`; si no, `null`.
- `aviso`:
  - con `in_process`: «La factura {numero} está «{estado}»: consulta su autorización desde «Facturas emitidas»; mientras tanto no se puede eliminar.»;
  - con `without_authorizing`, `returned`, `not_authorized` o `sequential_registered_error`: «La factura {numero} está «{estado}»: corrígela o reenvíala desde «Facturas emitidas». Si la eliminas, la proforma vuelve a su estado anterior («Aceptada» o «Enviada»).»;
  - en los demás estados, `null`.

**Identificadores que usa el JS (no cambiar):** `#fp-filtros`, `#fp-estado`, `#fp-desde`, `#fp-hasta`, `#fp-q`, `#fp-ver-todas`, `table#data`, `#fp-proforma-config`, los atributos `data-accion` y `data-id` de los botones, y los de los modales (pantalla 7 y modal de motivo: `#fp-modal-motivo`, `#fp-form-motivo`, `#fp-motivo`, `.fp-titulo-motivo`, `.fp-numero`). Variables globales que usa: `pathname`, `csrftoken`, `message_error`, `alert_sweetalert`, `dialog_action`, `loading` y `$.LoadingOverlay`.

**Libre:** la disposición de filtros y columnas, el texto de ayuda («Las proformas son cotizaciones sin validez tributaria…»), el estilo de las insignias y los botones, y la etiqueta del botón de crear (hoy la genérica «Nuevo registro» de `list.html`).

---

## 2. Crear — `GET/POST /proformas/add/`

- **Vista y plantilla:** `ProformaCreateView`, `templates/proformas/form.html` (extiende `form.html`: `form#frmForm.fp-responsive-form` con `data-url` = la lista, `input#action` oculto con `add` y `{% csrf_token %}`). Carga select2 y `proformas/js/form.js`.
- **Permiso:** `add_proforma` (Propietario, Administrador y Vendedor). Contador y Consulta reciben el permiso denegado de la pantalla.
- **Plan:** gratuito, bloqueada; vencido, el GET redirige (la ruta lleva `/add/`); cupo agotado o PRUEBAS, disponible.

**Contexto de la plantilla**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Nueva proforma» |
| `action` | str | `'add'` |
| `list_url` | str | `/proformas/` |
| `formas_pago` | lista de `(código, nombre)` | `PAYMENT_METHOD` (8 formas de pago del SRI) |
| `config` | dict (`json_script` id `fp-proforma-config`) | `{"hoy": "2026-10-29", "valida_hasta": "2026-11-13", "validez_por_defecto": 15, "max_validez": 365, "max_lineas": 200, "max_destinatarios": 5}` |
| `proforma` | None | Solo existe al editar |
| `aviso_estado` | None | Solo al editar |

El número se muestra como «se asigna al guardar». Al crear, `form.js` pone la fecha de hoy (con `max` = hoy) y «válida hasta» = fecha + 15 días. Si se cambia la fecha y no se tocó «válida hasta», esta se recalcula.

**Campos que envía el POST `action=add`** (`form.js` arma un `FormData` del formulario, quita `fp_tipo_cliente` y las entradas de las líneas, y añade `lineas` en JSON)

| `name` | Elemento | Obligatorio | Validación del servidor | Error (en `campos`) |
|---|---|---|---|---|
| `cliente` | `select#fp-cliente` (select2 con `search_client`) | No | Vacío o id de un cliente de la empresa. Con cliente, los `cliente_*` enviados se **ignoran** y se copian los datos actuales del cliente | `cliente`: «El cliente no existe.» |
| `cliente_nombre` | `#fp-cliente-nombre` (`maxlength` 300) | Sí, sin cliente | Espacios colapsados; de 2 a 300 caracteres | «Escribe el nombre del cliente o elige uno registrado.» |
| `cliente_identificacion` | `#fp-cliente-identificacion` (20) | No | Hasta 20; se guarda en mayúsculas. No se valida contra un tipo de identificación | «La identificación admite hasta 20 caracteres.» |
| `cliente_correo` | `#fp-cliente-correo` (500) | No | Separados por comas; cada uno válido; hasta 5 y 500 caracteres en total | «Este correo no es válido: {correo}.» o «Escribe hasta 5 correos, con 500 caracteres en total como máximo.» |
| `cliente_telefono` | `input[type=tel]#fp-cliente-telefono` (20) | No | De 7 a 20 caracteres entre dígitos, `+`, espacios, guiones y paréntesis | «Usa de 7 a 20 dígitos (puede llevar +, espacios, guiones o paréntesis).» |
| `cliente_direccion` | `#fp-cliente-direccion` (500) | No | Hasta 500 | «La dirección admite hasta 500 caracteres.» |
| `fecha` | `input[type=date]#fp-fecha` | Sí | ISO `AAAA-MM-DD` y no posterior a hoy | «La fecha no es válida o es futura.» |
| `valida_hasta` | `input[type=date]#fp-valida-hasta` | Sí | ISO, desde `fecha` hasta `fecha` + 365 días | «La validez debe ir de la fecha de la proforma hasta 365 días después.» |
| `forma_pago_sugerida` | `select#fp-forma-pago` («Sin indicar» = vacío) | No | Vacío o un código de `PAYMENT_METHOD` | «Elige una forma de pago de la lista.» |
| `condiciones` | `textarea#fp-condiciones` (2000) | No | Hasta 2000 | «Las condiciones admiten hasta 2000 caracteres.» |
| `lineas` | JSON que arma `form.js` | Sí | Lista de 1 a 200 objetos `{"product": int, "cant": int, "price": "10.00", "dscto": 10, "descripcion": "texto"}` | «Agrega al menos un producto.» o «Una proforma admite hasta 200 líneas.» |

`fp_tipo_cliente` (radios `#fp-tipo-registrado` y `#fp-tipo-prospecto`) es solo visual y no se envía: al elegir «Prospecto», `form.js` vacía `#fp-cliente`.

**Reglas de cada línea** (los errores llegan en `campos.lineas` como lista de `{indice, campo, texto}`; `indice` empieza en 0, en el orden enviado)

| Campo | Regla | Texto |
|---|---|---|
| `product` | Existe en la empresa y no se repite | «El producto no existe.» o «El producto {nombre} está repetido: suma las cantidades en una sola línea.» |
| `cant` | Entero de 1 a 999999 | «La cantidad es un número entero de 1 a 999999.» |
| `price` | De 0 a 999999,99, con hasta 2 decimales (el precio se puede negociar) | «El precio va de 0 a 999999,99, con hasta 2 decimales.» |
| `dscto` | Porcentaje **entero** de 0 a 100 (vacío = 0); se guarda como fracción | «El descuento es un porcentaje entero de 0 a 100, igual que en la factura.» |
| `descripcion` | Hasta 300; vacía = nombre del producto | «La descripción admite hasta 300 caracteres.» |

- `campos.lineas` es **texto** en los errores generales («Agrega al menos un producto.») y **lista** en los de cada línea.
- La tarifa de IVA de cada línea se toma del producto al guardar y queda fija en la línea.
- Ningún importe puede pasar de 9.999.999,99: si lo hace, 400 «El total de la proforma supera USD 9.999.999,99.».

**Respuestas del POST `add`**
- 200: `{"proforma": detalle, "mensaje": "Proforma PRO-000012 guardada.", "url_ver": "/proformas/ver/12/", "url_editar": "/proformas/update/12/"}`. `form.js` muestra el mensaje y abre `url_ver`.
- 400: `{"error": "Revisa los datos marcados.", "campos": {…}}`. `form.js` pinta el resumen en `#fp-errores`, el texto de cada campo en su `[data-campo="<name>"]` y marca con `.is-invalid` el campo o la entrada de la línea (`#tblLineas tbody tr[data-indice="<indice>"] [name="<campo>"]`).

**Buscadores (POST a la misma ruta)**

| `action` | Parámetros | Respuesta |
|---|---|---|
| `search_product` | `term` (hasta 100), `ids` (JSON con los ids ya elegidos) | Hasta 10 `Product.toJSON()` + `value`. **Incluye productos sin stock**: el stock solo se informa |
| `search_product_code` | `code` | El producto con ese código, o `{}` |
| `search_client` | `term` | Hasta 10 `Client.toJSON()` (formato select2) |

**Mensajes del navegador** (`form.js`): «Ese producto ya está en la proforma: cambia la cantidad de su línea.», «Una proforma admite hasta 200 líneas.», «No hay un producto con el código {código}.», «Agrega al menos un producto.» (antes de enviar), «No se pudo guardar la proforma.» y «No se pudo completar la búsqueda.».

**Diferencias con la venta del POS:** no hay selector de comprobante ni efectivo/crédito; el buscador incluye productos sin stock y la cantidad no tiene tope de stock; el precio se edita (2 decimales); el descuento es entero; cada línea muestra su tarifa; los totales por tarifa son una vista previa («Valores de referencia: el servidor recalcula al guardar.»). No hay líneas libres sin producto (decisión 7). «Enviar por correo» y «Facturar» no están en el editor: se usan desde la ficha o la lista.

**Identificadores que usa el JS (no cambiar):** `#frmForm`, `#action`, `#fp-errores`, `[data-campo]`, `input[name="fp_tipo_cliente"]`, `#fp-tipo-registrado`, `#fp-tipo-prospecto`, `.fp-registrado`, `.fp-prospecto`, `#fp-cliente`, `#fp-cliente-nombre`, `#fp-cliente-identificacion`, `#fp-cliente-correo`, `#fp-cliente-telefono`, `#fp-cliente-direccion`, `#fp-fecha`, `#fp-valida-hasta`, `#fp-forma-pago`, `#fp-condiciones`, `#fp-buscar-producto` (autocompletar desde 2 letras; Enter busca por código de barras), `#fp-abrir-busqueda`, `#fp-modal-productos`, `#fp-modal-termino`, `#fp-modal-resultados`, `#tblLineas` (filas `tr[data-indice]`, entradas `name="descripcion"`, `"cant"`, `"price"` y `"dscto"`, `.fp-total-linea`, botón `[data-quitar]`), `#fp-totales`, `#fp-proforma-config` y `#fp-proforma`. La tabla de líneas lleva `.fp-mobile-lines` y `data-label` en cada celda para el diseño móvil.

**Libre:** la disposición, el selector visual cliente/prospecto, la vista de líneas en móvil y el modal de búsqueda.

---

## 3. Editar — `GET/POST /proformas/update/<pk>/`

- **Vista y plantilla:** `ProformaUpdateView`, `templates/proformas/form.html`, con los mismos campos, buscadores, identificadores y validaciones que crear.
- **Permiso:** `change_proforma` (Propietario, Administrador y Vendedor).
- **Plan:** vencido, el GET redirige (la ruta lleva `/update/`).
- **Solo se edita** una proforma guardada como borrador o enviada (también si se ve «vencida»). En otro estado el GET redirige a la ficha con el mensaje «La proforma PRO-000012 está {estado} y ya no se puede editar. Puedes duplicarla.». Un id de otra empresa da 404.

**Contexto añadido**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Editar proforma PRO-000012» |
| `action` | str | `'edit'` |
| `proforma` | dict (`json_script` id `fp-proforma`) | `detalle` (pantalla 4). La plantilla muestra `proforma.numero` y «Cancelar» vuelve a `proforma.urls.ver` |
| `aviso_estado` | str o None | Si está guardada como «enviada» (vigente o vencida): «Al guardar, la proforma vuelve a borrador y tendrás que enviarla de nuevo.» |

- Al cargar, `form.js` rellena todo desde `#fp-proforma`. Las líneas cuyo producto ya no existe no se pueden conservar y avisa: «Estas líneas no se pueden conservar porque su producto ya no existe: {descripciones}.».
- Una borrador vencida sigue en borrador al editarla. Editar sirve para extender la validez.

**POST `action=edit`**
- Mismos campos que `add`. Las líneas se **reemplazan completas**, en el orden enviado.
- 200: `{"proforma": detalle, "mensaje": …, "url_ver", "url_editar"}`, con el mensaje «Proforma PRO-000012 guardada.» o, si estaba enviada, «Proforma PRO-000012 guardada. Volvió a borrador: envíala de nuevo a tu cliente.».
- 409: «… y ya no se puede editar. Puedes duplicarla.» si otra persona cambió el estado entretanto (por ejemplo, la facturó). La edición no se aplica.
- 400 y 404 como en crear.

---

## 4. Ficha — `GET /proformas/ver/<pk>/`

- **Vista y plantilla:** `ProformaDetailView`, `templates/proformas/detalle.html` (extiende `skin.html`). Carga `acciones.js` y `detalle.js` e incluye `_modales.html`.
- **Permiso:** `view_proforma` (los cinco roles de personal). Los botones dependen del rol (`acciones[]`).
- **Plan:** con el plan vencido se abre; solo quedan `ver` y `pdf`.
- Si no existe o es de otra empresa: 404 («La proforma no existe.»).

**Contexto de la plantilla**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Proforma PRO-000012» |
| `list_url` | str | `/proformas/` |
| `p` | `Proforma` | La instancia, para pintar en el servidor (cliente, fechas, condiciones, totales) |
| `lineas` | lista de `ProformaDetalle` | En el orden de ingreso |
| `impuestos` | lista de dict | `[{codigo, nombre, tarifa, base, valor}]` con Decimal, en el orden del RIDE |
| `proforma` | dict (`json_script` id `fp-proforma`) | `detalle` |
| `config` | dict (`json_script` id `fp-proforma-config`) | El mismo que en la lista |

**`detalle`** = `fila` más:

```json
{"lineas": [{"id": 1, "product_id": 7, "codigo": "P15", "descripcion": "PRODUCTO P15", "cant": 3, "price": "10.00", "dscto": "10",
             "codigo_porcentaje": "4", "tarifa": "15.00", "nombre_tarifa": "15 %", "subtotal": "30.00", "total_dscto": "3.00",
             "total": "27.00", "total_iva": "4.05", "producto_eliminado": false,
             "producto": {"nombre": "PRODUCTO P15", "stock": 8, "inventariado": true, "pvp": "10.00"}}],
 "impuestos_por_tarifa": [{"codigo": "4", "nombre": "15 %", "tarifa": "15.00", "base": "27.00", "valor": "4.05"}],
 "condiciones": "", "forma_pago_sugerida": {"id": "20", "nombre": "OTROS CON UTILIZACION DEL SISTEMA FINANCIERO"},
 "origen": null, "motivo": "", "enviada_a": "compras@example.test", "creada_por": "Vendedora Ficticia",
 "fechas": {"creada": "…", "actualizada": "…", "enviada": null, "aceptada": null, "rechazada": null, "anulada": null,
            "facturada": null},
 "empresa": {"razon_social": "…", "nombre_comercial": "…", "ruc": "…"}}
```

- `dscto` es el porcentaje entero, como texto. `producto` trae los datos **actuales** del producto (solo se informan) o `null` si se eliminó (`producto_eliminado: true`).
- `forma_pago_sugerida` es `null` si no se eligió; `origen` es `{id, numero}` de la proforma de la que se duplicó, o `null`.
- `motivo` es el del rechazo o la anulación.

**Contenido actual:** insignia de estado `.fp-estado-proforma` (con `data-estado`); el texto «Documento sin validez tributaria: es una cotización, no una factura.»; el bloque de la factura vinculada; los datos del cliente («(prospecto)» si lo es); fecha, validez (con `dias_para_vencer`), vendedor, forma de pago, correos enviados, «Duplicada de» (enlace a la original) y motivo; la tabla de líneas `#fp-lineas` («producto eliminado» si aplica); condiciones; totales por tarifa; los botones en `#fp-botones`; y «Volver a la lista».

**Bloque de la factura vinculada** (si `proforma.venta`): número, estado y total; con PRUEBAS, la insignia «PRUEBAS · sin validez tributaria» y el texto «Factura emitida en el ambiente de PRUEBAS: sin validez tributaria.»; el `aviso` si lo hay; los enlaces «Facturas emitidas» y «RIDE de la factura» (este último solo con `url_ride`).

**Acciones:** `detalle.js` pinta `fpAcciones.botones(proforma, true)` (iconos y texto) en `#fp-botones`. Los POST van a `/proformas/` con `action` + `id`; tras cada acción la ficha se recarga, y tras duplicar se abre el editor de la copia.

**Identificadores que usa el JS (no cambiar):** `#fp-proforma`, `#fp-proforma-config`, `.fp-estado-proforma`, `#fp-botones`, los de los modales y `data-accion`/`data-id`.

**Libre:** toda la disposición, el estilo del bloque de la factura y del aviso de PRUEBAS, y la tabla de líneas.

---

## 5. Eliminar — `GET/POST /proformas/delete/<pk>/`

- **Vista y plantilla:** `ProformaDeleteView`, `templates/proformas/delete.html` (extiende `delete.html`, cuyo JS confirma con «¿Estas seguro de eliminar el registro?» y envía el formulario por AJAX).
- **Permiso:** `delete_proforma` (solo Propietario y Administrador).
- **Plan:** vencido, el GET redirige (la ruta lleva `/delete/`) y el POST recibe 403.
- **Solo un borrador que nunca se envió.** Si no lo es, el GET redirige a la ficha con el mensaje «Solo se elimina un borrador que nunca se envió. Anula la proforma en su lugar.».

**Contexto:** `title` («Eliminar la proforma PRO-000012»), `list_url` y `object` (la proforma). La plantilla pregunta «¿Eliminar el borrador PRO-000012 de {cliente}?» y avisa que su número no se vuelve a usar.

**POST** (sin `action`)
- 200 `{}`: el JS vuelve a la lista. Se audita `proforma_eliminada`; las líneas se borran con la proforma y el contador no retrocede.
- 409 `{"error": "Solo se elimina un borrador que nunca se envió. Anula la proforma en su lugar."}`.
- 404 `{"error": "La proforma no existe."}`.

**Libre:** el texto y el estilo de la confirmación.

---

## 6. PDF A4 — `GET /proformas/pdf/<pk>/`

- **Vista y plantilla:** `ProformaPdfView`, `templates/proformas/pdf.html`, generado al vuelo con `printer.create_pdf` (WeasyPrint). No se guarda ningún archivo.
- **Permiso:** `view_proforma` (los cinco roles de personal). **Plan:** se abre también con el plan vencido.
- **Respuesta:** `application/pdf`, `Content-Disposition: inline; filename="PRO-000012.pdf"` y `Cache-Control: private, no-store`. Otra empresa: 404.
- **Si falla el render:** vuelve a la ficha con el mensaje «No se pudo generar el PDF de la proforma PRO-000012. Inténtalo de nuevo.».

**Contexto de la plantilla**

| Nombre | Significado |
|---|---|
| `proforma` | La instancia |
| `empresa` | La empresa de la proforma |
| `lineas` | Las líneas, en orden |
| `impuestos` | `[{codigo, nombre, tarifa, base, valor}]` con Decimal |
| `estado` / `estado_nombre` | Estado visible (`vencida`, `anulada`…) y su nombre |
| `establecimiento` | Dirección del punto de emisión predeterminado o, si no hay, la del establecimiento de la empresa |
| `proveedor` | Datos del proveedor para `ride/_pie.html`, o None |
| `forma_pago` | Nombre de la forma de pago sugerida, o '' |
| `vendedor` | Nombre del vendedor, o '' |
| `factura` | Número de la factura vinculada, o '' |
| `factura_pruebas` | `true` si la factura vinculada es de PRUEBAS |

**Contenido obligatorio**
- Incluye literalmente `ride/_estilos.html` y `ride/_pie.html` (`with proveedor=proveedor`), con `body.fp-ride` y `main.hoja`.
- **Emisor:** logo si hay, razón social, nombre comercial si es distinto, RUC, dirección matriz, establecimiento, teléfono y correo.
- **Cuadro de control:** «PROFORMA», el número, «Documento sin validez tributaria», la fecha y «Válida hasta». Si está vencida, rechazada, anulada o facturada, la línea «Estado: {estado_nombre}», con « con la factura {número}» si está facturada y « (PRUEBAS, sin validez tributaria)» si esa factura es de PRUEBAS.
- Una proforma anulada lleva la banda «ANULADA».
- **Cliente:** nombre y, si los hay, identificación, dirección, correo y teléfono.
- **Detalle:** código, cantidad, descripción (con su tarifa de IVA), precio unitario, descuento y total.
- **Condiciones de la propuesta:** forma de pago sugerida, vendedor, condiciones y el texto «Esta proforma es una cotización: no es una factura ni un comprobante de venta.».
- **Totales:** un subtotal por cada tarifa presente, descuentos, el IVA de cada tarifa con IVA y «TOTAL USD».
- La cabecera y los encabezados de la tabla salen **una sola vez** (no se repiten en las páginas siguientes; regla de `AGENTS.md`).

**Prohibido** (lo comprueba la prueba del PDF): clave de acceso, «Autorización» o «autorización», «Ambiente», código de barras, «Obligado a llevar contabilidad», «Contribuyente» (especial o RIMPE), «RIMPE» y la palabra «FACTURA» en mayúsculas.

**Libre:** la composición, siempre que se conserven los textos obligatorios, los prohibidos y la regla de la cabecera única. Hay que probarlo con documentos cortos y largos (la prueba usa 60 líneas).

---

## 7. Enviar por correo — modal `#fp-modal-correo` y POST `action=enviar_correo`

- **Dónde:** en la lista y en la ficha (`templates/proformas/_modales.html`). El editor no lo tiene.
- **Permiso:** `change_proforma`. **Plan:** con el plan vencido, 403.
- **Cuándo aparece:** `enviar_correo` en `acciones[]` (borrador o enviada vigentes, o aceptada).

**Campos del modal** (`form#fp-form-correo`)

| `name` | Elemento | Obligatorio | Regla |
|---|---|---|---|
| `destinatarios` | `#fp-destinatarios` (`maxlength` 600) | No | Separados por comas, hasta 5. El JS lo rellena con `cliente.correo`. Vacío = los correos de la proforma |
| `mensaje` | `textarea#fp-mensaje` (`maxlength` 1000) | No | Hasta 1000 caracteres |

El número va en `.fp-numero` del título.

**Validaciones, en este orden**

| Caso | HTTP | Mensaje |
|---|---|---|
| La proforma no existe | 404 | «La proforma no existe.» |
| Está vencida | 409 | «La proforma PRO-000012 venció el 12/11/2026. Cambia la fecha de validez antes de enviar por correo.» |
| Está rechazada, facturada o anulada | 409 | «La proforma PRO-000012 está {estado}: no se puede enviar por correo.» |
| Mensaje de más de 1000 caracteres | 400 | «El mensaje admite hasta 1000 caracteres.» |
| Un correo no válido | 400 | «Este correo no es válido: {correo}.» |
| Ningún correo | 400 | «Escribe al menos un correo válido para enviar la proforma.» |
| Más de 5 correos | 400 | «Puedes enviar la proforma a un máximo de 5 correos.» |
| 60 envíos en la última hora en la empresa | 409 | «Alcanzaste el límite de 60 envíos de proformas por hora. Inténtalo más tarde.» |
| Falla el PDF, la conexión o el envío | 502 | «No se pudo enviar la proforma PRO-000012 ({ClaseDeError}: {detalle}). Revisa el correo de la empresa e inténtalo de nuevo.» |

**El correo**
- **Asunto:** «Proforma PRO-000012 - {nombre comercial o razón social}».
- **Cuerpo** (`templates/proformas/correo.txt`, texto plano sin autoescape): saludo «Estimado(a) {cliente}:», número, total en USD con punto, «válida hasta» dd/mm/aaaa, «Este documento es una cotización sin validez tributaria: no es una factura.», el mensaje, las condiciones y «Para responder, conteste este correo.».
- **Adjunto:** `PRO-000012.pdf`.
- **Remitente:** el SMTP propio de la empresa si lo configuró; si no, el de la plataforma con el nombre «{empresa} vía FacturaPorAquí». **Responder a:** el correo de la empresa.

**Efecto**
- borrador → enviada; enviada y aceptada no cambian de estado.
- Se guardan `enviada_en` y `enviada_a`, `envios` sube en 1 y se audita `proforma_enviada`.
- Si el envío falla, no cambia nada.

**Respuesta 200:** `{"proforma": fila, "aviso": false, "mensaje": "Proforma PRO-000012 enviada a compras@example.test."}`.
- Si mientras salía el correo otra persona anuló, rechazó o facturó la proforma, el envío se registra igual, su estado no cambia y llega `"aviso": true` con el mensaje «Proforma PRO-000012 enviada a {destinatarios}, pero mientras salía el correo quedó {estado}: el envío se registró y su estado no cambió.».
- Hoy `acciones.js` muestra los dos mensajes igual; el estilo de advertencia para `aviso: true` queda para el diseño.

**Límite de envíos:** 60 envíos **con éxito** por hora y por empresa, contados en la auditoría (`proforma_enviada`). En PostgreSQL el conteo, el envío y su registro van juntos bajo un bloqueo por empresa, así que dos envíos simultáneos no pasan juntos el último cupo. Los intentos fallidos no cuentan (decisión pendiente, apartado E).

**Identificadores que usa el JS (no cambiar):** `#fp-modal-correo`, `#fp-form-correo`, `#fp-destinatarios`, `#fp-mensaje` y `.fp-numero`.

---

## 8. Facturar — `GET /pos/sale/admin/add/?proforma=<pk>` (pantalla de venta, modificada)

**Distinción clave para la interfaz**
- «Facturar» en la proforma **solo abre** la pantalla de venta precargada: no crea nada ni gasta número, cupo ni stock.
- «Emitir factura» en la venta **crea la factura y la envía al SRI en el mismo paso**. No existen facturas en borrador.
- La venta se abre **para revisión**: se puede cambiar el cliente, las cantidades y los descuentos, quitar o agregar productos y elegir efectivo o crédito. El servidor no exige que la venta coincida con la proforma; la auditoría registra si coincide.
- Una proforma **nunca** queda con dos facturas.

- **Vista y plantilla:** `SaleCreateView` (`sale_admin_create`), `core/pos/templates/sale/admin/create.html` y `core/pos/static/sale/admin/js/form.js`. Sin `?proforma=` la venta funciona exactamente como antes.
- **Permisos:** `add_sale` (lo pide la pantalla de venta) y además `change_proforma`.
  - Un rol sin `add_sale` (Contador, Consulta) recibe el permiso denegado de la pantalla y vuelve a la última página visitada.
  - Un rol con `add_sale` pero sin `change_proforma` vuelve a `/proformas/` con «Tu perfil no puede facturar proformas.».
- **Plan:** la ruta está en `RUTAS_DE_EMISION`; se bloquea con el plan gratuito, con el vencido y con el cupo agotado.
- **Ambiente:** en PRUEBAS se factura igual que en PRODUCCIÓN (decisión 5). La precarga lleva el aviso de PRUEBAS; la factura queda vinculada, la proforma pasa a «facturada» y no se puede facturar otra vez. Para volver a cotizar, se duplica.

**Errores al abrir** (redirigen con `messages.error`)

| Caso | Mensaje | Vuelve a |
|---|---|---|
| id no válido, inexistente o de otra empresa | «La proforma no existe.» | `/proformas/` |
| Ya tiene factura | «La proforma PRO-000012 ya se facturó con la factura {número}.» | la ficha |
| Vencida (borrador o enviada) | «La proforma PRO-000012 venció el {fecha}. Cambia la fecha de validez antes de facturar.» | la ficha |
| Otro estado no facturable (borrador vigente, rechazada, anulada) | «La proforma PRO-000012 está {estado}: solo se facturan las proformas enviadas y vigentes, o las aceptadas.» | la ficha |
| Ninguna línea se puede cargar | «Ningún producto de la proforma PRO-000012 se puede facturar ahora (sin stock o eliminado).» | la ficha |
| Sin `change_proforma` | «Tu perfil no puede facturar proformas.» | `/proformas/` |

**Contexto añadido**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Facturar la proforma PRO-000012» |
| `proforma_facturar` | dict | `{"id", "numero", "total", "valida_hasta", "url_ver"}` |
| `proforma_avisos` | lista de str | Los avisos de la precarga |
| `proforma_precarga` | dict (`json_script` id `fp-proforma-precarga`) | La precarga completa (abajo) |

**Precarga** (`precarga_para_venta`; solo lee)

```json
{"proforma": {"id": 12, "numero": "PRO-000012", "total": "75.24", "valida_hasta": "2026-11-12", "url_ver": "/proformas/ver/12/"},
 "cliente": {"…": "Client.toJSON(), formato select2"},
 "prospecto": null,
 "lineas": [{"…": "Product.toJSON()", "cant": 3, "price_current": 10.0, "dscto": 10.0, "total_dscto": 0.0, "pvp": 10.0,
             "value": "…"}],
 "forma_pago": "20",
 "info_adicional": [{"name": "Proforma", "value": "PRO-000012"}],
 "avisos": ["Al guardar se emite la factura y se envía al SRI. Revisa el cliente, los productos y la forma de pago."]}
```

- `cliente` es `null` con un prospecto; entonces `prospecto` es `{nombre, identificacion, correo, telefono, direccion}`.
- `lineas` va en el formato de una fila del POS (con números), con el precio y el descuento **de la proforma**.
- `forma_pago` es el código sugerido, o '' si no hay.

**Avisos, en este orden**

| Cuándo | Texto |
|---|---|
| Siempre, el primero | «Al guardar se emite la factura y se envía al SRI. Revisa el cliente, los productos y la forma de pago.» |
| La empresa está en PRUEBAS | «La empresa está en PRUEBAS: la factura no tendrá validez tributaria y la proforma quedará facturada con ella. Para volver a cotizar, duplícala.» |
| Línea sin producto (no se carga) | «La línea «{descripcion}» no se cargó: el producto ya no existe.» |
| Producto inventariado sin stock (no se carga) | «No se cargó «{nombre}»: no tiene stock (la proforma pedía {cant}).» |
| Stock menor que lo cotizado (se carga lo que hay) | ««{nombre}»: hay {stock} en stock y la proforma pedía {cant}; se cargaron {stock}.» |
| Cambió la tarifa de IVA (la factura usa la actual) | ««{nombre}»: el IVA cambió de {antes} a {ahora}; la factura usa la tarifa actual.» |
| El precio cotizado no es el actual | ««{nombre}»: se usa el precio de la proforma (USD {precio}) y no el actual (USD {actual}).» |
| Alguna descripción cotizada no es el nombre del producto (un solo aviso) | «La factura usa el nombre de cada producto, no la descripción escrita en la proforma.» |
| Es un prospecto | «La proforma es para un prospecto: registra al cliente antes de emitir.» |

**Plantilla `create.html`** (cuatro cambios anclados; el resto no cambia)
- Al inicio de `form_fields`, si hay `proforma_facturar`: el aviso `div.alert.alert-info.fp-proforma-aviso` (`role="status"`) con «Facturando la proforma PRO-000012 (total USD 75.24)», la lista de `proforma_avisos` y el enlace «Volver a la proforma» (`url_ver`).
- `<input type="hidden" name="proforma_id" value="<id>">`, dentro de `#frmForm` (así lo envía el `FormData` de la venta sin JS adicional).
- El botón principal dice «Emitir factura» en lugar de «Generar Venta».
- `{{ proforma_precarga|json_script:"fp-proforma-precarga" }}` y la condición `final_consumer and not proforma_precarga`: con una proforma no se preselecciona el consumidor final.

**`form.js` de la venta: `sale.cargarProforma(datos)`** (se llama al final del `$(function)` si existe `#fp-proforma-precarga`)
1. Fija el comprobante en 01 (`select_receipt`) y deshabilita las demás opciones.
2. Mete las líneas en `sale.detail.products` sin `addProduct`, para conservar cantidades, precio y descuento.
3. Copia `info_adicional` en `sale.detail.additional_info` y llama a `sale.listAdditionalInfo()`: «Proforma: PRO-000012» aparece en la información adicional y **se puede quitar** (decisión 3). Va al XML y al RIDE.
4. Elige la forma de pago en `select[name="payment_method"]`.
5. Cliente:
   - registrado: lo elige en `select_client` (select2);
   - prospecto: rellena `#frmClient` (`names`; el primer correo en `email` y los demás en `extra_emails`; `dni`; `mobile` solo con los dígitos y si caben en 10; `address`), elige `identification_type` 05 con 10 dígitos o 04 con 13, pone la fecha de nacimiento de hoy en `input_birthdate` y abre `#myModalClient`.

**Al emitir (POST `action=add` con `proforma_id`)**
- La proforma se bloquea **antes** de reservar el número de la factura (orden fijo: proforma → numeración). Una segunda conversión simultánea espera, ve la factura ya vinculada y falla **sin gastar número**.
- Al final de la misma transacción, después de firmar el XML, la proforma se marca con un `UPDATE` condicional: queda «facturada» con `venta` y se audita `proforma_facturada`. Si el prospecto no tenía cliente, queda ligado al cliente de la factura, salvo que sea el consumidor final.
- **Errores** (HTTP 200 `{"error": "…"}`, como los demás de la venta): «Tu perfil no puede facturar proformas.», «Una proforma se convierte en una factura electrónica (01), no en un ticket.», «La proforma no existe.», «… ya se facturó con la factura …», «… venció el …» y «… solo se facturan las proformas enviadas y vigentes, o las aceptadas.», más todos los de la venta. Con cualquiera de ellos no se crea la venta y la proforma no cambia.
- **Tras emitir:** vuelve a «Facturas emitidas», como hoy.
- **Si después el SRI la devuelve o queda en proceso:** la venta existe y la proforma sigue «facturada». La lista y la ficha muestran el `aviso` de la factura.
- **Si se elimina la factura** (solo se puede si no salió al SRI): la proforma vuelve a «aceptada» si alguna vez se aceptó, o si no a «enviada», y se audita `proforma_venta_eliminada`. Una factura autorizada, también la de PRUEBAS, no se puede eliminar.

**Identificadores que no cambian:** `.fp-proforma-aviso`, `input[name="proforma_id"]`, `#fp-proforma-precarga` y, de la venta, `#frmForm`, `#frmClient`, `#myModalClient`, `select[name="payment_method"]` y las variables `select_receipt`, `select_client`, `input_birthdate` y `sale.detail`.

**Libre:** el estilo del aviso `.fp-proforma-aviso` (hoy un `alert-info` simple).

---

## 9. Menú

- Grupo «Cotizaciones» (icono `fas fa-file-alt`, orden 15, después de «Comprobantes Electrónicos») con el módulo «Proformas» (`/proformas/`, icono `fas fa-file-contract`, orden 1, descripción «Cotizaciones sin validez tributaria que se convierten en factura»). Decisión 1.
- Lo ven Propietario, Administrador, Vendedor, Contador y Consulta. El Cliente no.
- Con el plan gratuito lleva el candado del menú.
- La landing sigue igual: esta rama no la toca.

---

## A. Mensajes (texto exacto, código HTTP y cuándo salen)

`{numero}` es `PRO-000012`; `{estado}` es el nombre del estado en minúsculas; `{fecha}` va como dd/mm/aaaa.

| Clave | Texto | HTTP / salida | Cuándo |
|---|---|---|---|
| `no_existe` | La proforma no existe. | 404, o redirección a `/proformas/` | id no válido, inexistente o de otra empresa |
| `sin_permiso` | Tu perfil no puede realizar esta acción. | 403 | POST de una acción sin el permiso del rol |
| `sin_opcion` | No ha seleccionado ninguna opción | 400 | `action` desconocida |
| `transicion` | La proforma {numero} está {estado}: no se puede {acción}. | 409 | Transición o envío desde un estado no permitido (estado guardado) |
| `vencida` | La proforma {numero} venció el {fecha}. Cambia la fecha de validez antes de {acción}. | 409, o redirección a la ficha | Marcar enviada, aceptar, enviar o facturar una vencida |
| `no_editable` | La proforma {numero} está {estado} y ya no se puede editar. Puedes duplicarla. | GET: redirección a la ficha; POST: 409 | Editar fuera de borrador o enviada |
| `guardada` | Proforma {numero} guardada. | 200 | Crear o editar una borrador |
| `vuelve_borrador` | Proforma {numero} guardada. Volvió a borrador: envíala de nuevo a tu cliente. | 200 | Editar una enviada |
| `duplicada` | Se creó la proforma {numero}, copia de {origen}. | 200 | Duplicar |
| `estado_cambiado` | La proforma {numero} quedó {estado}. | 200 | Marcar enviada, aceptar, rechazar o anular |
| `enviada` | Proforma {numero} enviada a {destinatarios}. | 200 | Correo enviado |
| `enviada_cambio` | Proforma {numero} enviada a {destinatarios}, pero mientras salía el correo quedó {estado}: el envío se registró y su estado no cambió. | 200, con `aviso: true` | El estado cambió durante el envío |
| `sin_correo` | Escribe al menos un correo válido para enviar la proforma. | 400 | Sin destinatarios |
| `correo_invalido` | Este correo no es válido: {correo}. | 400 | Un destinatario no válido |
| `demasiados_correos` | Puedes enviar la proforma a un máximo de 5 correos. | 400 | Más de 5 destinatarios |
| `mensaje_largo` | El mensaje admite hasta 1000 caracteres. | 400 | Mensaje del correo demasiado largo |
| `limite_envios` | Alcanzaste el límite de 60 envíos de proformas por hora. Inténtalo más tarde. | 409 | 60 envíos en la última hora |
| `correo_fallo` | No se pudo enviar la proforma {numero} ({detalle}). Revisa el correo de la empresa e inténtalo de nuevo. | 502 | Falla el PDF, la conexión o el envío |
| `eliminar_no` | Solo se elimina un borrador que nunca se envió. Anula la proforma en su lugar. | GET: redirección a la ficha; POST: 409 | Eliminar algo que no es un borrador nunca enviado |
| `eliminada` | Proforma {numero} eliminada. | No se muestra | La vista de eliminar responde `{}` |
| `ya_facturada` | La proforma {numero} ya se facturó con la factura {factura}. | 409; en la venta, redirección o 200 `{error}` | Facturar una proforma ya facturada |
| `no_facturable` | La proforma {numero} está {estado}: solo se facturan las proformas enviadas y vigentes, o las aceptadas. | Igual | Facturar desde otro estado |
| `solo_factura` | Una proforma se convierte en una factura electrónica (01), no en un ticket. | Venta: 200 `{error}` | Emitir con otro tipo de comprobante |
| `sin_lineas_facturables` | Ningún producto de la proforma {numero} se puede facturar ahora (sin stock o eliminado). | Duplicar: 409; venta: redirección a la ficha | No queda ninguna línea utilizable |
| `facturar_sin_permiso` | Tu perfil no puede facturar proformas. | Venta: redirección a `/proformas/` o 200 `{error}` | Rol con `add_sale` sin `change_proforma` |
| `total_maximo` | El total de la proforma supera USD 9.999.999,99. | 400 | Algún importe pasa del máximo |
| `revisa` | Revisa los datos marcados. | 400, con `campos` | Errores de validación |
| `pdf_fallo` | No se pudo generar el PDF de la proforma {numero}. Inténtalo de nuevo. | Redirección a la ficha | Falla el PDF |
| (genérico) | No se pudo completar la acción. | 500 | Fallo inesperado |

Verbos de `{acción}`: editar, enviar por correo, marcar como enviada, aceptar, rechazar, anular, facturar, eliminar.

---

## B. Auditoría (`AuditLog`, como texto)

Ocho códigos. El `detail` solo lleva texto, enteros y booleanos: importes como texto con 2 decimales e ids como enteros. Crear, editar y duplicar no se auditan (la proforma guarda `creada_por`, `creada_en`, `actualizada_en` y `origen`).

| Código | `detail` |
|---|---|
| `proforma_enviada` | `proforma`, `proforma_id`, `destinatarios` (cantidad, sin direcciones), `envio` (número de envío) |
| `proforma_marcada_enviada` | `proforma`, `proforma_id` |
| `proforma_aceptada` | `proforma`, `proforma_id` |
| `proforma_rechazada` | `proforma`, `proforma_id`, `motivo` |
| `proforma_anulada` | `proforma`, `proforma_id`, `motivo` |
| `proforma_eliminada` | `proforma`, `proforma_id` |
| `proforma_facturada` | `proforma`, `proforma_id`, `venta_id`, `factura`, `total_proforma`, `total_factura`, `coincide`, `ambiente` (1 = PRUEBAS, 2 = PRODUCCIÓN, de la venta) |
| `proforma_venta_eliminada` | `proforma`, `proforma_id`, `venta_id`, `factura`, `estado` (el restaurado: `aceptada` o `enviada`) |

- `coincide` es `true` solo si coinciden los totales **y** las líneas (producto, cantidad, precio y descuento).
- `proforma_venta_eliminada` registra al usuario de la petición; fuera de una petición (por ejemplo, un borrado desde la consola) queda sin usuario.
- `proforma_enviada` también sirve de contador del límite por hora.
- El integrador añade las choices de los 8 códigos en la migración única de `tenancy`; hasta entonces se guardan como texto.

---

## C. Estados de la factura vinculada que ve la proforma

| Estado de la venta | En la proforma |
|---|---|
| `authorized`, `authorized_and_sent_by_email`, `canceled` | Enlace al RIDE; sin aviso |
| `in_process` | Aviso «consulta su autorización…; mientras tanto no se puede eliminar.» |
| `without_authorizing`, `returned`, `not_authorized`, `sequential_registered_error` | Aviso «corrígela o reenvíala… Si la eliminas, la proforma vuelve a su estado anterior…» |
| Cualquier estado, con la venta en PRUEBAS | Insignia «PRUEBAS · sin validez tributaria» y texto `aviso_ambiente` |

---

## D. Textos y fragmentos que comprueban las pruebas (no cambiar)

- **Venta** (`tests/test_proformas_conversion.py`): `name="proforma_id" value="<id>"`, «Emitir factura» (y «Generar Venta» sin proforma), «Facturando la proforma PRO-… (total USD 75.24)», «Volver a la proforma», `<script id="fp-proforma-precarga" type="application/json">` (el `json_script`, sin `|safe`). Sin proforma no deben aparecer ni el aviso, ni `fp-proforma-precarga`, ni `name="proforma_id"`.
- **Ficha:** «PRUEBAS · sin validez tributaria» y «Factura emitida en el ambiente de PRUEBAS: sin validez tributaria.». Un nombre hostil sale escapado (`&lt;img …&gt;`) en el HTML y como `<…` en los `json_script` de la ficha y del editor.
- **Editor:** el texto de `aviso_estado` al editar una enviada.
- **`list.js`:** cada columna `numero`, `cliente.nombre`, `cliente.identificacion`, `vendedor.nombre`, `estado.nombre` y `venta.numero` declara `data: '<campo>'` y `render: $.fn.dataTable.render.text()` **en la misma línea** (la prueba usa una expresión regular).
- **Plantillas:** `list.html`, `detalle.html` y `form.html` no usan `|safe`.
- **`acciones.js`:** `fpAcciones.escapar` escapa `&`, `<`, `>`, `"` y `'`; `fpAcciones.botones(p, completos)` arma el HTML como texto con solo los atributos `class`, `href`, `title`, `aria-label`, `type`, `data-accion`, `data-id`, `disabled` y `aria-hidden`. La prueba lo corre con Node y un `$` mínimo que solo sabe `text()` y `html()`: si `botones` pasa a usar otras funciones de jQuery, la prueba se tiene que adaptar en el mismo cambio.
- **PDF:** «PROFORMA» (una sola vez y solo en la primera página), el número, «sin validez tributaria», «Válida hasta», «Subtotal {tarifa}», «IVA 15 %», «IVA 5 %», «TOTAL USD», el encabezado «Descripción» una sola vez, «ANULADA» y «Estado: Anulada», «(PRUEBAS, sin validez tributaria)», y los textos prohibidos del punto 6. Tamaño A4.

---

## E. Pendiente para Codex (lista para HANDOFF)

- [ ] `templates/proformas/list.html` y `list.js`: lista con filtros, siete estados, botones solo desde `acciones[]`, «Facturar» deshabilitado con `facturar_bloqueado`, y los modales de correo y motivo.
- [ ] `templates/proformas/form.html` y `form.js`: crear y editar, sin comprobante ni efectivo/crédito, con prospecto, precio editable, descuento entero y vista móvil de las líneas (`.fp-mobile-lines`, `data-label`).
- [ ] `templates/proformas/detalle.html`: ficha con la factura vinculada, su aviso y la marca de PRUEBAS.
- [ ] `templates/proformas/pdf.html`: integrar la propuesta `proforma-pdf.django.html` respetando el punto 6, y probar documentos cortos y largos.
- [ ] Estilo de advertencia para la respuesta del correo con `aviso: true` (hoy se muestra como un mensaje normal).
- [ ] Estilo del aviso `.fp-proforma-aviso` en `sale/admin/create.html`.
- [ ] Probar en un navegador real `sale.cargarProforma`, con cliente y con prospecto: hoy solo está verificado con `node --check` y un arnés jsdom.
- [ ] Revisar las pantallas a 360, 768 y 1360 px, con teclado y con movimiento reducido.
- [ ] Texto seguro en todas las columnas y modales (`render.text`, `fpAcciones.escapar` o `.text()`, `json_script`).
- [ ] Opcional: etiqueta propia del botón de crear («Nueva proforma» en lugar de «Nuevo registro»), sin cambiar `create_url`.

**Decisión pendiente de la propietaria (no cambia pantallas):** si los intentos de envío fallidos (SMTP caído, o un correo aceptado que falla al cerrar la conexión) deben contar para el límite de 60 por hora. Si se decide que sí, hace falta un código de auditoría nuevo (lo pondría el integrador en `tenancy`) o un contador compartido.

**Fuera del alcance de P (decisión 10):** el enlace a la proforma de origen en «Facturas emitidas».

---

## F. Diferencias con la especificación

1. **Facturar en PRUEBAS está permitido** (decisión 5). No existen el mensaje ni el bloqueo `ambiente_pruebas`; `facturar_bloqueado` nunca trae ese texto. La precarga añade el aviso «La empresa está en PRUEBAS…». La conversión vincula, deja la proforma facturada e impide una segunda factura, igual que en PRODUCCIÓN. La pantalla 8 ya no exige «empresa en PRODUCCIÓN».
2. **JSON `venta`:** además de `ambiente`, trae `sin_validez_tributaria` y `aviso_ambiente`, tomados de la venta. La lista, la ficha y el PDF marcan la factura de PRUEBAS. La auditoría `proforma_facturada` añade `ambiente` (entero).
3. **El aviso de PRUEBAS de la precarga** mira el ambiente de la empresa al abrir la venta; la lista, la ficha, el PDF y la auditoría miran el de la propia venta (`Sale.environment_type`).
4. **Errores al emitir:** llegan con HTTP 200 y `{"error"}`, el comportamiento actual de la venta, no con 409.
5. **Códigos HTTP del correo:** `sin_correo`, `correo_invalido`, `demasiados_correos` y `mensaje_largo` dan 400 (datos); `limite_envios` y `vencida` dan 409; `correo_fallo`, 502. La especificación los agrupaba bajo 409.
6. **Mensajes y avisos añadidos:** `sin_opcion`, `mensaje_largo`, `pdf_fallo` y `enviada_cambio`; por campo, `cliente_identificacion`, `cliente_correos` (más de 5 correos o más de 500 caracteres) y `cliente_direccion`; los avisos de editar una enviada, de factura pendiente, de factura en proceso (sin «si la eliminas», porque no se puede) y de factura de PRUEBAS.
7. **Respuesta del correo:** añade `aviso` (booleano) y puede traer `enviada_cambio`.
8. **Límite de envíos:** en PostgreSQL es atómico (bloqueo consultivo por empresa, que no frena la numeración). Cuentan solo los envíos con éxito.
9. **Prospecto facturado:** queda ligado al cliente de la factura solo si ese cliente **no** es el consumidor final; así un duplicado conserva los datos del prospecto. La especificación lo ligaba siempre.
10. **`coincide`** compara totales y líneas; la especificación no lo definía.
11. **`dias_para_vencer`** es `null` también en aceptada (solo vencen borrador y enviada). **`aviso_estado`** solo aparece si el estado guardado es «enviada» (una borrador vencida sigue en borrador). `eliminar` nunca aparece en una enviada vencida.
12. **Contexto ampliado:** la lista y la ficha reciben `config` (`fp-proforma-config` con `max_destinatarios`, `max_mensaje`, `max_motivo` y `url_lista`) y la lista `list_url`; la configuración del editor añade `max_validez`. Las líneas del detalle traen `producto` con los datos actuales; el índice de los errores por línea empieza en 0, y `campos.lineas` es texto o lista según el error.
13. **El modal de correo** está en la lista y la ficha, no en el editor (la especificación lo admitía también en la edición).
14. **Eliminar:** un GET de algo que no se puede eliminar redirige a la ficha con `eliminar_no`. `templates/proformas/delete.html` muestra el número, no el id.
15. **Archivos extra:** `templates/proformas/_modales.html` y `core/proformas/static/proformas/js/acciones.js`, compartidos por la lista y la ficha.
16. **PDF:** los importes salen con coma, como el RIDE (`floatformat`); el cuerpo del correo usa «USD 75.24», como el correo de facturas. El contexto del PDF añade `vendedor`, `factura` y `factura_pruebas`. La banda «ANULADA» no lleva espaciado entre letras.
17. **Venta con prospecto:** el primer correo va a `email` y los demás a `extra_emails`; el teléfono se carga solo con dígitos y si cabe en 10 caracteres.
18. **`proforma_venta_eliminada`** toma el usuario de la petición en curso; sin petición queda sin usuario.
19. **Columnas de la lista:** el código tiene diez (la especificación sugería cinco, como la maqueta). Es libre para el diseño.
