# Contrato de pantallas — Etapa 2, compras (rama O1)

28/10/2026 · Escrito desde el código de la rama `fase/etapa2-compras` en `f0f6fbd`, fusionada en `plataforma` en `eaa6d10` junto con las demás ramas de la fase contable (orden y estado en `HANDOFF.md`).

> **Estado en `plataforma` tras la integración (29/10/2026).** Este contrato es **definitivo** sobre la base que indica
> `HANDOFF.md`, con estos cambios respecto de la rama:
> - **Pantalla 14 (retención recibida desde un 07):** ya funciona. `registrar_desde_importacion`
>   (`core/comprobantes/retenciones_recibidas.py`) y el permiso `add_retencionrecibida` llegan con Ventas;
>   `comprobantes/0023` crea el permiso y lo asigna a Propietario y Administrador.
> - **Punto 8 del apartado B, hecho:** `RetencionCrearView` (Retención sobre una compra, de `comprobantes`) rechaza en GET
>   y en POST las compras que `compras.admite_retencion` no admite (notas de crédito del proveedor, 04): redirige a
>   Compras con «La compra #N es una nota de crédito del proveedor (04): sobre ella no se emite comprobante de retención.
>   No se emitió nada.», sin reservar número ni llamar al SRI. Sin liquidación autorizada, los datos iniciales salen de
>   `compras.datos_sustento_retencion` y la plantilla `comprobantes/retencion/create.html` muestra sus avisos como
>   `<div class="alert alert-warning" data-advertencia="sustento_varias_tarifas|sustento_tarifa_no_disponible">` (contexto
>   `avisos_sustento`: lista de `{codigo, texto}`). Codex conserva `data-advertencia`.
> - Los 6 códigos de auditoría de Compras son choices de `AuditLog.ACTIONS` (`tenancy/0007`).
> - Resultados y tablero restan la 04 (ver la nota al inicio del contrato de Ventas).
> - Sigue pendiente del punto 8: mostrar la clave `aviso` de `liquidaciones.lineas_de_compra` en
>   `comprobantes/liquidacion/create.html` y enlazar Retenciones recibidas con la pantalla 14 en el diseño.

Este documento describe **lo que hace el código de la rama**, pantalla por pantalla, para que Codex haga el diseño sin romper nada y para que la propietaria vea qué cambia en Compras. Se escribió a partir de la sección 6 de su especificación interna de trabajo (no publicada), pero manda el código: cuando no coinciden, se describe el código y la diferencia queda anotada en «Diferencias con la especificación» de cada pantalla y en el resumen final (apartado C). Lo publicará el integrador en `HANDOFF.md`.

Cada ruta, nombre de URL, nombre de campo, acción y mensaje de este documento se comprobó con `grep` en la rama. Cuando un mensaje lleva datos variables se escribe con `N`, `$X` o `…` en su lugar.

---

## Reglas comunes a todas las pantallas

**Lo que Codex no cambia**
- Modelos, servicios, vistas, rutas, nombres de URL y migraciones.
- Los nombres de los campos (`name=`), los valores de `action`, el prefijo `lineas` del formset y su `management_form`, el `{% csrf_token %}` de los formularios y la cabecera `X-CSRFToken` de los AJAX.
- Los identificadores, clases y atributos `data-*` que usa el JavaScript (se listan en cada pantalla) y los textos o fragmentos de HTML que comprueban las pruebas (lista en el apartado B, punto 10).

**Datos**
- La empresa activa la decide el servidor. Nunca se envía `company_id`. Un id de otra empresa responde 404 (en las acciones JSON de eliminar, 404 con `{"error": …}`).
- Importes nuevos en JSON como texto decimal con punto (`"135.00"`) o `null` cuando no se conocen (compras anteriores a esta etapa). Nunca se calcula con `float` en el navegador: los totales que se muestran los calcula el servidor.
- Las claves que ya existían en los JSON siguen siendo números (`float`): `subtotal` de la compra; `debt` y `saldo` de la cuenta por pagar; `valor` de pagos y gastos; `price`, `dscto` y `subtotal` de las líneas.
- Fechas en JSON como `AAAA-MM-DD`.

**Texto de terceros (razón social, identificación, número, descripciones, referencias, motivos)**
- La razón social y las descripciones pueden venir del XML de un tercero. DataTables inserta cada dato como HTML.
- Toda columna de texto lleva `render: $.fn.dataTable.render.text()`.
- Todo `render` que arma HTML pasa cada dato por `esc(x)`, que es `$('<div>').text(x).html()`; el HTML del detalle se arma con `.text()`.
- Los datos que van al JavaScript salen con `json_script`, nunca con `|safe`.
- Lo vigila `tests/test_estaticos_compras.py`: revisa 13 JS de compras, proveedores, cuentas por pagar, gastos, tipos de gasto y sus reportes; que ningún `columnDefs` reescriba una columna de texto; que ninguna plantilla de esas carpetas ni de `importacion/` use `|safe`, y que cuatro plantillas usen `json_script`.

**Sugerencias, no valores (decisión DC12 de la especificación)**
- Nada que decida el crédito tributario empieza elegido: forma de pago (ATS) y sustento tributario de la compra, sustento del tipo de gasto, parte relacionada de un proveedor nuevo y medio de pago de pagos y gastos empiezan vacíos.
- Donde el contrato dice «sugerencia», se muestra el texto con un botón «Usar sugerencia» que solo cambia el campo en el navegador. Nada se guarda solo.
- Lo que trae el documento sí se precarga: la parte relacionada ya registrada del proveedor, la forma de pago y el plazo del XML importado.

**Permiso denegado**
- Pantallas y acciones de `pos` y reportes (`GroupPermissionMixin` y `GroupModuleMixin`):
  - GET: redirige a la última pantalla visitada con el mensaje «Tu perfil no cuenta con el permiso necesario para ingresar».
  - POST: 403 con `{"error": "Tu perfil no cuenta con el permiso necesario para ingresar"}`.
- API de importación (`/importacion/api/…`): siempre 403 en JSON con `{"error": "Tu perfil no cuenta con el permiso necesario."}`, también en GET.
- Eliminar un pago de cuenta por pagar sin `delete_debts_pay`: 403 con `{"error": "Tu perfil no puede eliminar pagos."}` (lo decide el servicio, no el mixin).

**Mensajes de Django**
- «Compra #N registrada.», «Datos de la compra guardados», «Compra #N creada desde el XML» y «Retención recibida registrada (N documentos sustento)» salen con `messages.success`.
- El marco general (`hzt_body.html` o `vtc_body.html`) muestra todos los mensajes, también los de éxito, en una ventana titulada «Error». Ver el apartado B.

**Reglas de plan (`PlanMiddleware`, sin cambios en esta rama)**

| Rutas | Gratuito | Plan vencido (el último plan) | Plan 1000 | Ilimitado y Multiempresa |
|---|---|---|---|---|
| `/pos/purchase/` (incluido «Completar datos»), `/pos/provider/`, `/pos/debts/pay/`, `/reports/purchase/`, `/reports/debts/pay/` | Se abren. Límites del plan gratuito: compras por mes (`purchase_limit_month`, 30 si la plataforma no lo define) y proveedores (`provider_limit`, 10). Cuentan todas las compras nuevas, también las de gasto y las notas de crédito o débito | Se abren igual (no son rutas de pago) | Todo | Todo |
| `/pos/expenses/`, `/pos/type/expense/`, `/reports/expenses/` | No se abren: un GET redirige a `/suscripcion/` (si el rol gestiona el plan) o a `/dashboard/`; un POST responde 403 `{"error": <aviso>, "plan": "requerido"}` | Solo consulta: se abren los GET salvo las rutas con `/add/`, `/update/` o `/delete/`; un POST solo pasa si su `action` empieza con `search` | Todo | Todo |
| `/importacion/…` (crear compra desde el XML, registrar retención recibida, ficha del documento) | No se abren: GET redirige con el aviso «La importación de comprobantes recibidos (XML y RIDE) está incluida en los planes Ilimitado y Multiempresa. Mejora tu plan para usarla.»; POST y API, 403 `{"error": …, "plan": "ilimitado"}` | Si el último plan era Ilimitado o Multiempresa, solo consulta: GET sí; **todo POST** responde 403 | Igual que gratuito (403 o redirección); vencido también | Todo |

Nada de Compras consume cupo de emisión ni habla con el SRI. Ninguna acción nueva se llama `generate_invoice`.

**Roles** (los reparte `sync_roles`; los permisos que empiezan con `add_`, `change_`, `delete_` o `adjust_` nunca llegan a Contador ni a Consulta; Vendedor no tiene Compras). `core/tenancy/roles.py` no cambia en esta rama.

| Acción | Propietario | Administrador | Contador | Vendedor | Consulta |
|---|---|---|---|---|---|
| Ver compras, proveedores, cuentas por pagar y gastos (con insignias de datos incompletos) | ✔ | ✔ | ✔ | — | ✔ |
| Registrar compra, compra de gasto o nota de crédito o débito del proveedor (`add_purchase`) | ✔ | ✔ | — | — | — |
| Completar datos de una compra (`change_purchase`) | ✔ | ✔ | — (decisión P1) | — | — |
| Eliminar una compra (`delete_purchase`) | ✔ | ✔ | — | — | — |
| Crear o editar proveedores (`add_provider`, `change_provider`) | ✔ | ✔ | — | — | — |
| Registrar pagos de cuentas por pagar (`add_debts_pay`) | ✔ | ✔ | — | — | — |
| Eliminar pagos o cuentas por pagar (`delete_debts_pay`) | ✔ | ✔ | 403 | — | 403 |
| Gastos sin comprobante: crear, editar y eliminar | ✔ | ✔ | Solo ver | — | Solo ver |
| Tipos de gasto | ✔ | ✔ | — (no está en su menú) | — | Solo ver |
| Crear compra desde un XML importado (`change_documentoimportado` + `add_purchase`) | ✔ | ✔ | — | — | — |
| Registrar retención recibida desde un 07 (`change_documentoimportado` + `add_retencionrecibida`) | ✔ tras fusionar O2 | ✔ tras fusionar O2 | — | — | — |
| Reportes de compras, cuentas por pagar y gastos (por módulo) | ✔ | ✔ | ✔ | — | ✔ |

`add_retencionrecibida` lo crea O2: en esta rama **nadie** puede abrir la pantalla 14 salvo en las pruebas, que crean el permiso con `tests/ayuda_compras.permiso_retencion_recibida(grupo)`.

**Auditoría.** Las acciones de esta rama dejan registro con estos códigos de texto (las `choices` las añade el integrador en tenancy 0007): `purchase_complete`, `purchase_debt_adjust`, `purchase_delete`, `debt_payment_delete`, `debt_delete` y `provider_type_fill`. Los eventos nuevos del documento importado son `compra_creada`, `compra_eliminada`, `equivalencia_guardada`, `incorporado` y `desincorporado`. Las pantallas no los muestran todavía.

---

## Pantallas documentadas

| # | Pantalla | Ruta | Nombre de URL | Nueva o modificada |
|---|---|---|---|---|
| 1 | Compras: listado | `/pos/purchase/` | `purchase_list` | Modificada |
| 2 | Compras: nueva compra (y compra de gasto) | `/pos/purchase/add/`, `/pos/purchase/add/?tipo=gasto` | `purchase_create` | Modificada |
| 3 | Compras: completar datos | `/pos/purchase/complete/<pk>/` | `purchase_complete` | Nueva |
| 4 | Compras: eliminar | `/pos/purchase/delete/<pk>/` | `purchase_delete` | Modificada |
| 5 | Proveedores: listado | `/pos/provider/` | `provider_list` | Modificada |
| 6 | Proveedores: nuevo y edición | `/pos/provider/add/`, `/pos/provider/update/<pk>/` | `provider_create`, `provider_update` | Modificadas |
| 7 | Cuentas por pagar: listado, pagos y abonos | `/pos/debts/pay/` | `debts_pay_list` | Modificada |
| 8 | Cuentas por pagar: registrar pago | `/pos/debts/pay/add/` | `debts_pay_create` | Modificada |
| 9 | Cuentas por pagar: eliminar | `/pos/debts/pay/delete/<pk>/` | `debts_pay_delete` | Modificada |
| 10 | Gastos: listado | `/pos/expenses/` | `expenses_list` | Modificada |
| 11 | Gastos: nuevo y edición | `/pos/expenses/add/`, `/pos/expenses/update/<pk>/` | `expenses_create`, `expenses_update` | Modificadas |
| 12 | Tipos de gasto: listado, nuevo y edición | `/pos/type/expense/`, `add/`, `update/<pk>/` | `type_expense_list`, `type_expense_create`, `type_expense_update` | Modificadas |
| 13 | Importación: crear compra desde el XML (página y API) | `/importacion/documentos/<pk>/compra/`, `/importacion/api/documentos/<pk>/compra/` | `importacion_compra`, `importacion_api_compra` | Nuevas |
| 14 | Importación: registrar retención recibida desde un 07 | `/importacion/documentos/<pk>/retencion-recibida/` | `importacion_retencion_recibida` | Nueva |
| 15 | Importación: ficha del documento, API de documentos y nueva importación (cambios) | `/importacion/documentos/<pk>/`, `/importacion/api/documentos/`, `/importacion/nueva/` | `importacion_documento`, `importacion_api_documentos`, `importacion_api_documento`, `importacion_nueva` | Modificadas |
| 16 | Reporte de compras | `/reports/purchase/` | `purchase_report` | Modificada |
| 17 | Reporte de cuentas por pagar | `/reports/debts/pay/` | `debts_pay_report` | Modificada |
| 18 | Reporte de gastos | `/reports/expenses/` | `expenses_report` | Modificada |

Sin cambios de comportamiento en esta rama: eliminar proveedor, eliminar gasto y eliminar tipo de gasto (plantilla genérica `delete.html`).

El apartado A resume los datos que devuelven los modelos (`toJSON`), el B es lo pendiente para Codex y el C, el resumen de diferencias con la especificación.

---

## 1. Compras: listado (modificada)

- **Ruta:** `GET/POST /pos/purchase/`, nombre `purchase_list`.
- **Vista:** `PurchaseListView` (`core/pos/views/purchase/views.py`). **Plantilla:** `purchase/list.html` (extiende `list.html`). **JS:** `core/pos/static/purchase/js/list.js`.
- **Permiso:** `view_purchase`. Los botones dependen de `add_purchase`, `change_purchase` y `delete_purchase` del perfil.
- **Qué ve y hace cada rol:**
  - Propietario y Administrador: ven todo; registran, completan y eliminan.
  - Contador y Consulta: ven el listado y el detalle. No ven «Nuevo Registro», «Compra de gasto», «Completar datos» ni «Eliminar». Sí ven «Retención» y «Liquidación»; esas pantallas son de `comprobantes` y deciden su propio permiso.
  - Vendedor: no tiene el módulo.
- **Plan:** se abre en todos los planes.

**Contexto de la plantilla**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Listado de Compras» |
| `create_url` | str | `/pos/purchase/add/` |
| `url_gasto` | str | `/pos/purchase/add/?tipo=gasto` |
| `form` | `ReportForm` | Solo se pinta `date_range` |
| `puede_crear`, `puede_completar`, `puede_eliminar` | bool | `add_purchase`, `change_purchase` y `delete_purchase` del perfil |
| `permisos_listado` | dict | Los mismos tres booleanos, para el JS con `json_script` id `fp-compras-permisos` |

**Filtros de la pantalla:** rango de fechas (`date_range`), «Filtrar por» (`#fp-compras-fecha`: `registro` por defecto o `emision`) y «Solo compras con datos incompletos» (`#fp-compras-incompletas`, valor `1`). Con `emision`, las compras sin fecha de emisión (anteriores o «Completar después») no aparecen; solo se ven al filtrar por fecha de registro. El texto de ayuda lo dice.

**Acciones (POST con `X-CSRFToken`; responden JSON con estado 200)**
1. `action=search`, con `start_date` y `end_date` (`AAAA-MM-DD`; los dos vacíos = todas), `fecha` (`registro` | `emision`) e `incompletas` (`1` | `''`). Devuelve `[compra.toJSON()]` ordenado por id (claves en el apartado A). No trae `faltantes` ni `clase`: no consulta por fila.
2. `action=totales`, con los mismos filtros. Devuelve `{"completas": {"cantidad": n, "total": "0.00"}, "incompletas": {"cantidad": n, "subtotal": "0.00"}}`:
   - `completas.total`: total con IVA de las compras completas; las notas de crédito del proveedor (tipo 04) restan;
   - `incompletas.subtotal`: subtotal registrado de las compras con datos incompletos, también con signo.
3. `action=search_detail_products`, con `id`: `[linea.toJSON()]` (se conserva).
4. `action=detalle`, con `id`. Devuelve:
   - `compra`: `toJSON(detalle=True)`, con `clase` (`inventario` | `gasto` | `mixta`) y `faltantes` `[{codigo, texto}]`;
   - `lineas`: `[linea.toJSON()]`;
   - `por_tarifa`: `[{codigo, nombre, tarifa, base, valor}]` (importes como texto; `valor` es `null` en líneas anteriores sin tarifa);
   - `cuenta_por_pagar`: `{id, debt, saldo, pagado, base_calculo: {id, name}, abonos: [{tipo, id, numero, fecha, valor}]}` o `null`;
   - `retencion`: `{id, numero, estado}` o `null` (la vigente);
   - `liquidacion`: `{id, numero, estado}` o `null` (la vigente);
   - `documento_importado`: `{id, url}` o `null`.
   - Si la compra no existe o es de otra empresa: `{"error": "La compra no existe."}`.
5. Otro `action`: `{"error": "No ha seleccionado ninguna opción"}`.

**Columnas:** Número (`numero_comprobante`, o el número antiguo, o «S/N»), Tipo, Proveedor, Identificación, Fecha de emisión («—» si no hay), Fecha de registro, Tipo de pago (insignia), Base (`subtotal`), IVA, Total, Datos y Opciones. IVA y total salen «—» cuando son `null`.

**Estados de datos de una compra (columna «Datos»)**

| Estado | Cuándo | Insignia | Qué permite |
|---|---|---|---|
| Compra anterior | `datos_incompletos` y `version_datos == 1` (registrada antes de esta etapa) | «Compra anterior · sin IVA» (`badge-secondary`) | Detalle; «Completar datos» (cabecera e importes de la factura); retención y liquidación según el tipo; eliminar |
| Datos incompletos | `datos_incompletos` y `version_datos == 2` | «Datos incompletos» (`badge-warning`); la lista de lo que falta sale en el detalle | Igual, pero sin editar importes (vienen de las líneas o del XML) |
| Fuera del plazo del ATS | `fuera_plazo_ats` | «Fuera del plazo del ATS» (`badge-danger`), además de la anterior | La compra queda incompleta para siempre (faltante `fuera_plazo_ats`) |
| Completa | `datos_incompletos` falso | Texto «Completa» | «Editar datos del comprobante» (mismos bloqueos) |

Paso de un estado a otro: incompleta → completa al completar los datos, al autorizarse su liquidación (tipo 03) o al completar el proveedor; completa → incompleta si se anula su liquidación en el SRI o si el proveedor queda con datos incompletos.

**Opciones por fila**
- Detalle (`a[rel="detail"]`): abre el modal con `action=detalle`.
- Con `puede_completar`: «Completar datos» (incompleta) o «Editar datos del comprobante» (completa) → `/pos/purchase/complete/<id>/`.
- «Retención» → `/comprobantes/retenciones/nueva/<id>/`, solo si el tipo es `''`, `01` o `03`.
- «Liquidación» → `/comprobantes/liquidaciones/nueva/<id>/`, solo si el tipo es `''` o `03`.
- Con `puede_eliminar`: Eliminar → `pathname + 'delete/<id>/'`.

**Pie:** «Total con IVA de las compras completas (las notas de crédito restan):» en `.fp-total-completas` y, aparte, «N compras con datos incompletos — subtotal registrado $X» en `.fp-total-incompletas` (vacío si no hay). Los dos salen de `action=totales`. Botones «Nuevo Registro» y «Compra de gasto» solo con `puede_crear`; «Actualizar».

**Modal de detalle:** cabecera (compra, tipo, proveedor, sustento, autorización, fechas, forma de pago, origen, bases, IVA, ICE, propina, total y documento modificado), alerta «Datos incompletos:» con la lista de faltantes, tabla de líneas (producto o gasto, tarifa, cantidad, precio, descuento, base, IVA), resumen por tarifa, cuenta por pagar con sus abonos, y vínculos a la retención, la liquidación y «Ver el XML importado de esta compra».

**Identificadores que usa el JS (no cambiar):** `#data`, `input[name="date_range"]`, `.btnSearchAll`, `#fp-compras-fecha`, `#fp-compras-incompletas`, `#fp-compras-permisos`, `.fp-total-completas`, `.fp-total-incompletas`, `#myModalDetails`, `#fp-compra-cabecera`, `#fp-compra-faltantes` (con su `ul`), `#tblProducts tbody`, `#fp-compra-tarifas tbody`, `#fp-compra-cuenta`, `#fp-compra-vinculos`, `a[rel="detail"]`, las variables globales `pathname` y `csrftoken` y la función `message_error`. La prueba `test_botones_de_retencion_y_liquidacion_segun_el_tipo` busca en `list.js` los textos literales `['', '01', '03'].indexOf(tipo) >= 0` y `['', '03'].indexOf(tipo) >= 0`.

**Libre para el diseño:** orden y aspecto de las columnas, insignias, iconos, el diseño del modal y del pie, siempre que se conserven los identificadores, el escape y las condiciones de los botones.

**Diferencias con la especificación:**
- Acción nueva `totales`: el pie lo calcula el servidor (la especificación solo tenía `search`).
- Contexto nuevo `permisos_listado`.
- `detalle.cuenta_por_pagar` trae además `id` y `pagado`.
- Una compra completa muestra el texto «Completa» (la especificación decía «sin insignia»).
- «Retención» y «Liquidación» no dependen de permisos del listado: decide la pantalla de destino.

---

## 2. Compras: nueva compra y compra de gasto (modificada)

- **Ruta:** `GET/POST /pos/purchase/add/` y `/pos/purchase/add/?tipo=gasto`, nombre `purchase_create`.
- **Vista:** `PurchaseCreateView` (ahora `TemplateView`). **Plantilla:** `purchase/create.html` (extiende `form.html`, formulario `#frmForm` con `data-url` = `list_url`). **JS:** `core/pos/static/purchase/js/form.js`.
- **Permiso:** `add_purchase`. Propietario y Administrador. Contador, Consulta y Vendedor: GET redirige con el mensaje de permiso; POST 403.
- **Plan:** todos los planes; en el gratuito, con el límite mensual de compras.

**Contexto de la plantilla**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Nuevo registro de una Compra» o, con `?tipo=gasto`, «Nueva compra de gasto» |
| `list_url` | str | `/pos/purchase/` |
| `action` | str | `add` |
| `form` | `CompraForm` | Cabecera de la compra |
| `frmProvider` | `ProviderForm` | Modal de proveedor nuevo, con `auto_id='fp_proveedor_%s'` |
| `tipo_inicial` | str | `inventario` o `gasto` (con `?tipo=gasto`); va al JS con `json_script` id `fp-compra-tipo-inicial` |
| `opciones` | dict | Catálogos para el JS (`json_script` id `fp-compra-opciones`): `tipos_comprobante`, `sustentos`, `comprobantes_por_sustento`, `tipo_id_por_comprobante`, `formas_pago`, `tarifas` `[{codigo, nombre, tarifa, tarifa_variable}]`, `pago_loc_ext`, `tipos_con_doc_modificado`, `tipos_sin_forma_pago`, `tipos_sin_iva_discriminado`, `codigos_iva_nota_venta`, `umbral_bancarizacion` |
| `sustento_gasto_sugerido` | str | `01` si la empresa vende con IVA, si no `02` (`json_script` id `fp-compra-sustento-sugerido`). Solo texto |
| `nombre_sustento_sugerido` | str | Nombre del sustento sugerido |
| `hoy` | str | Fecha de hoy `AAAA-MM-DD` |

**Secciones de la pantalla:** 1. Proveedor y registro; 2. Comprobante del proveedor; 3. Líneas; 4. Totales. Con `?tipo=gasto` sale el aviso «Compra de gasto: registra la factura con líneas de gasto (sin producto). Sustenta el IVA y el ATS; no mueve stock.», una línea de gasto vacía y, bajo el sustento, «Sugerencia: 0X — …» con el botón «Usar sugerencia» y la nota «01 da crédito tributario de IVA; 02 no. Confírmalo con tu contador.».

**Campos (nombres exactos del POST; `CompraForm` solo revisa tipos y formatos, las reglas están en `core.pos.compras`)**

| Campo | Tipo | Obligatorio | Validaciones y notas |
|---|---|---|---|
| `provider` | id (select2 con `search_provider`) | Sí | «Elige el proveedor.». En modos `si` y `liquidacion`, el proveedor debe tener tipo de identificación: «Completa el tipo de identificación del proveedor antes de registrar el comprobante.». Al elegirlo se muestra `#fp-proveedor-aviso` con sus datos incompletos y un enlace a editarlo |
| `date_joined` | fecha (fecha de registro) | Sí; inicial hoy | «Escribe la fecha de registro.», «La fecha de registro no puede ser futura.» |
| `payment_type` | `efectivo` \| `credito` | Sí; inicial `efectivo` | Una nota de crédito (04) se guarda de contado |
| `end_credit` | fecha | Con `credito` | «Escribe la fecha de plazo del crédito.», «La fecha de plazo del crédito no puede ser anterior a la fecha de registro.». De contado se guarda igual a la fecha de registro |
| `modo_comprobante` | radio `si` \| `liquidacion` \| `despues` | Sí; inicial `si` | Etiquetas «Tengo el comprobante del proveedor», «Emitiré una liquidación de compra», «Completar después» |
| `tipo_comprobante` | Tabla 4 sin el 03 | En modo `si` | «Elige el tipo de comprobante.». El 03 se registra con el modo `liquidacion`: «La liquidación de compra (03) se registra con el modo «Liquidación».» |
| `cod_sustento` | Tabla 5, filtrada por el tipo en el navegador | En modos `si` y `liquidacion`; sin inicial | «Elige el sustento tributario.», «El sustento 0X no admite el tipo de comprobante «…».». Con `?tipo=gasto` se precarga solo si el tipo de gasto elegido en una línea tiene sustento |
| `estab`, `pto_emi` | 3 dígitos | En modo `si` | «El establecimiento del comprobante tiene tres dígitos, por ejemplo 001 (000 no es válido).» (y lo mismo para el punto de emisión) |
| `secuencial` | 1 a 9 dígitos | En modo `si` | «El secuencial del comprobante tiene de 1 a 9 dígitos y es mayor que cero.». Se guarda con ceros a 9 |
| `autorizacion` | dígitos | En modo `si` | Tipos 01, 04 y 05: 49 dígitos, o 10 o 37 en comprobantes antiguos; los demás tipos, de 3 a 49. Con 49 dígitos se analiza la clave de acceso: «La autorización es de un comprobante de PRUEBAS: no sustenta.» y «La autorización no corresponde a este comprobante: no coincide …» |
| `fecha_emision` | fecha | En modo `si` | «Escribe la fecha de emisión del comprobante.», «La fecha de emisión del comprobante no puede ser futura.», «La fecha de emisión del comprobante no puede ser posterior a la fecha de registro.». Más de 365 días antes del registro exige `confirmar_plazo_ats` |
| `forma_pago` | Tabla 13 (`01`, `15`–`21`) | En modos `si` y `liquidacion`, salvo tipo 04; sin inicial | «Elige la forma de pago del comprobante (ATS).» |
| `parte_relacionada` | `''` \| `no` \| `si` | En modos `si` y `liquidacion` | «Indica si el proveedor es parte relacionada.». El JS la precarga con la del proveedor si ya la tiene |
| `pago_loc_ext` | `01` \| `02` | En modos `si` y `liquidacion` | «Indica si el pago es a residente o a no residente.». El JS precarga `01` solo con proveedor RUC o cédula |
| `tipo_doc_modificado`, `num_doc_modificado`, `aut_doc_modificado`, `fecha_doc_modificado` | `01`/`02`/`03`; 15 dígitos (con o sin guiones); autorización; fecha | Con tipo 04 o 05 en modo `si` | Se muestran solo con tipo 04 o 05 (`#fp-doc-modificado`). «Escribe los datos del documento modificado: tipo, número, autorización y fecha.», «La fecha del documento modificado no puede ser posterior a la del comprobante.» |
| `compra_modificada` | id (select2 con `search_compra_modificada`) | No | Mismo proveedor y no puede ser otra nota. Con ella, la nota de crédito abona la cuenta por pagar de esa compra |
| `total_ice`, `propina` | importe | No (0) | Hasta 2 decimales: «ICE: admite hasta 2 decimales.» |
| `iva_factura` | importe | No | «Opcional: si lo escribes, manda el de la factura (se confirma si difiere).». Si difiere en más de $0,05 del IVA por líneas exige `confirmar_iva` |
| `confirmar_iva`, `confirmar_plazo_ats` | casilla (`on`) | Solo si el servidor la pide | Ocultas (`.fp-confirmacion[data-confirmacion=…]`) hasta que `calcular` o `add` las piden |
| `lineas` | JSON en texto | Al menos una | Ver abajo. «Las líneas de la compra no tienen un formato válido.», «Agrega al menos una línea a la compra.», «Una compra admite hasta 500 líneas.» |

**Formato de `lineas`** (lo arma el JS; cada error de línea llega como «Línea N: …»):
```json
[{"tipo": "producto", "product": 12, "cant": 3, "price": "4.50", "descuento": "0.00", "codigo_porcentaje": "4"},
 {"tipo": "gasto", "type_expense": 3, "descripcion": "Mantenimiento", "cant": 1, "price": "100.00", "descuento": "0.00",
  "codigo_porcentaje": "8", "tarifa": "8.00"}]
```
- `cant`: entero de 1 a 10.000.000. `price` y `descuento` (en dólares): hasta 2 decimales («Precio: admite hasta 2 decimales.»); el descuento no puede superar el subtotal de la línea.
- `codigo_porcentaje`: `4` (15 %), `5` (5 %), `0` (0 %), `6` (no objeto), `7` (exento), `2` (12 %, solo comprobantes anteriores al 01/04/2024) u `8` (IVA diferenciado, con `tarifa` obligatoria: «Escribe la tarifa del IVA diferenciado que figura en la factura.»).
- Con fecha de emisión: «La tarifa del 15 % rige desde el 01/04/2024: este comprobante es anterior.» y «La tarifa del 12 % ya no rige para comprobantes desde el 01/04/2024.».
- Con tipo `02` (nota de venta) el selector solo ofrece 0 % y no objeto: «Una nota de venta no discrimina IVA: registra sus valores con tarifa 0 %.».
- Línea de gasto: descripción obligatoria, hasta 300 caracteres («Escribe la descripción de la línea de gasto.»). Las notas de crédito y débito solo admiten líneas de gasto.
- Producto: el buscador (`search_product`) solo ofrece productos inventariados; un producto no inventariado se registra como línea de gasto. El servidor acepta cualquier producto de la empresa («Elige un producto de la empresa.») y solo mueve stock en los inventariados.

**Qué mostrar según el modo**
- `si`: todos los datos del comprobante.
- `liquidacion`: sin tipo ni numeración (`#fp-grupo-tipo` y `#fp-numeracion` ocultos) y el aviso «La numeración la da la liquidación que emitirás desde Compras.». El servidor exige numeración y autorización vacías, solo IVA del 15, 5 o 0 %, sin descuentos, sin ICE ni propina, y sin un IVA de la factura distinto del calculado.
- `despues`: todo opcional, con el aviso «La compra quedará con datos incompletos.». Lo que llegue se valida igual.

**Acciones (POST multipart con `X-CSRFToken`; responden JSON con estado 200)**
1. `action=calcular`: valida y calcula sin guardar. Devuelve `{lineas, por_tarifa, base_0, base_gravada, base_5, base_no_objeto, base_exenta, total_descuento, total_iva, total_ice, propina, total, total_iva_calculado, subtotal, advertencias, faltantes, confirmaciones}`. Importes como texto; `lineas[]` trae `tipo, product, type_expense, descripcion, codigo_proveedor, cant, price, descuento, codigo_porcentaje, tarifa, nombre_tarifa, subtotal, total, total_iva`; `advertencias` y `faltantes` son `[{codigo, texto}]`; `confirmaciones`, una lista de códigos. El JS lo llama 600 ms después de cada cambio y con «Calcular totales» (`#fp-calcular`).
2. `action=add`: registra. Éxito: `{"id": n, "advertencias": [{codigo, texto}]}`, mensaje «Compra #N registrada.» y el JS vuelve a `list_url`. Error: `{"error": "…"}`; si falta una confirmación, además `"confirmacion": "confirmar_iva"` o `"confirmar_plazo_ats"` y el JS muestra la casilla. Textos de confirmación:
   - «El IVA de la factura difiere del calculado por líneas en $X: confírmalo.»
   - «La factura tiene más de un año: el ATS no la admitirá en este período. Confírmalo para registrarla.»
3. `action=validate_comprobante`, con `provider`, `tipo_comprobante`, `estab`, `pto_emi`, `secuencial`. Devuelve `{valid, compra_id, mensaje, documento_importado}` y, a veces, `posible_duplicado`:
   - comprobante ya registrado: `valid: false`, `compra_id` y «Ya registraste este comprobante (compra #N).»;
   - XML importado pendiente con ese número: `documento_importado: {id, url, url_compra}` y «Este comprobante ya está en Importación: puedes crear la compra desde su XML.»; el JS enlaza «Crear la compra desde el XML» y «Ver el XML importado»;
   - compra anterior (sin secuencial) del mismo proveedor con el mismo número: `posible_duplicado: [ids]` y «Ya hay una compra registrada antes con el mismo número: #N (número …). Revísala antes de registrar otra: duplicaría el stock y la cuenta por pagar.». Sigue `valid: true`.
4. `action=search_product`, con `term` e `ids` (JSON de los ya elegidos): hasta 10 productos inventariados, `Product.toJSON()` con `value`, `tarifa_iva`, `tarifa` y `nombre_tarifa`.
5. `action=search_provider`, con `term`: hasta 10 proveedores por nombre o identificación (`Provider.toJSON()`, con `text`).
6. `action=validate_provider`, con `pattern` (`name`, `ruc`, `mobile`, `email`) y `parameter`: `{valid}`.
7. `action=create_provider`: los campos del proveedor (pantalla 6). Devuelve `Provider.toJSON()` con `advertencias`, o `{"error": {campo: [mensajes]}}` o un texto.
8. `action=search_type_expense`, con `term`: `[{id, text, cod_sustento}]` (hasta 20).
9. `action=search_compra_modificada`, con `provider` y `term`: `[{id, text}]` (hasta 20; no lista notas 04 o 05). `text` con el formato `#<id> · <número> · <dd/mm/aaaa> · $<total>`.
10. Otro `action`: `{"error": "No ha seleccionado ninguna opción"}`. Se retiró `validate_purchase`.

**Advertencias** (no bloquean; salen en `#fp-resumen-advertencias`):

| Código | Texto |
|---|---|
| `bancarizacion` | «Un pago de más de USD 1.000 sin el sistema financiero no da crédito tributario de IVA ni es deducible.» |
| `tarifa_5_anterior` | «La tarifa del 5 % se aplica desde el 01/04/2024: revisa la tarifa de este comprobante, que es anterior.» |
| `tarifa_12_sin_fecha` | «La tarifa del 12 % solo rige para comprobantes anteriores al 01/04/2024: se revisará al completar la fecha de emisión.» |
| `liquidacion_con_ruc` | «El catálogo ATS solo admite liquidaciones con cédula o pasaporte; con RUC, la liquidación solo procede si está suspendido.» |
| `ice_sin_iva_factura` | «El IVA se calcula sin incluir el ICE en la base: si la factura lo incluye, escribe el IVA de la factura.» |

**Otros errores** (texto exacto): «Ya registraste … de … (compra #N).» (duplicado; código `duplicado`), el límite del plan gratuito («El plan gratuito permite hasta N compras por mes. Activa un plan en «Plan y pagos» para registrar más.», código `limite_plan`), «Una factura solo se registra con un proveedor con RUC.», «La compra debe tener un total mayor que cero.», «El total de la compra supera el máximo admitido ($9999999.99).», «Las notas de crédito y débito del proveedor se registran con líneas de gasto (sin producto): no mueven stock en esta etapa.», «Línea N: la liquidación de compra solo admite IVA del 15 %, del 5 % o del 0 %.», «Línea N: la liquidación de compra no admite descuentos: registra el precio ya rebajado.», «La liquidación de compra que emite el sistema no incluye ICE ni propina: déjalos en 0.», «En una liquidación de compra el IVA es el de sus líneas: deja vacío el IVA de la factura.».

**Resumen (`#fp-resumen`):** tabla por tarifa, totales («Subtotal sin impuestos», «Descuento», «IVA calculado por líneas», «IVA de la compra», «ICE», «Propina», «Total con IVA»), advertencias y «La compra quedará con datos incompletos:» con los faltantes. El total grande va en `.fp-total-compra`.

**Modal de proveedor nuevo:** `#myModalProvider` con el formulario `#frmProvider` y los campos de la pantalla 6 (ids `fp_proveedor_<campo>`). Los errores salen en `#fp-proveedor-errores`. Al guardar, el proveedor queda elegido.

**Identificadores que usa el JS (no cambiar):** `#frmForm` y su `data-url`; `#fp-compra-opciones`, `#fp-compra-tipo-inicial`, `#fp-compra-sustento-sugerido`; `input[name="modo_comprobante"]` y los `name` de la cabecera; los ids de fecha `#date_joined`, `#end_credit`, `#fecha_emision`, `#fecha_doc_modificado` (datetimepicker); `#fp-aviso-liquidacion`, `#fp-aviso-despues`, `#fp-grupo-tipo`, `#fp-numeracion`, `#fp-grupo-forma-pago`, `#fp-doc-modificado`, `#fp-plazo-credito`, `#fp-proveedor-aviso`, `#fp-comprobante-aviso`, `#fp-usar-sugerencia`, `#fp-buscar-producto`, `#fp-agregar-gasto`, `#tblLineas tbody` (filas con `data-index`; dentro, `input[name=descripcion|cant|price|descuento|tarifa]`, `select[name=codigo_porcentaje|type_expense]`, `.fp-base`, `.fp-iva` y `button[rel="remove"]`), `#fp-calcular`, `#fp-resumen-error`, `#fp-resumen-tarifas`, `#fp-resumen-totales`, `#fp-resumen-advertencias` y `#fp-resumen-faltantes` (con su `ul`), `.fp-confirmacion[data-confirmacion]`, `.fp-total-compra`, `.btnAddProvider`, `#myModalProvider`, `#frmProvider`, `#fp-proveedor-errores`, `label[for="fp_proveedor_<campo>"]`; las funciones globales `dialog_action` y `message_error`. La prueba `test_compras_completas` busca `id="fp-compra-opciones"` en la página y que no aparezca `validate_purchase`.

**Libre para el diseño:** distribución de las cuatro secciones, tabla de líneas (puede ser tarjetas en el móvil), ubicación del resumen y del total, textos de ayuda e iconos. `#fp-grupo-fecha-emision` y `#fp-sugerencia-sustento` no los usa el JS.

**Diferencias con la especificación:**
- `add` devuelve `{id, advertencias}` en vez de `{}` y deja el mensaje «Compra #N registrada.»; con una confirmación pendiente añade `confirmacion`.
- `opciones` trae cinco claves más (las de la tabla de contexto) y hay un contexto nuevo `nombre_sustento_sugerido`.
- `validate_comprobante` añade `documento_importado.url_compra` y `posible_duplicado`.
- El selector de tipo no ofrece el 03; el 03 en modo «después» se rechaza.
- Se quitó el modal «Buscar productos»: queda el autocompletado. `search_product` conserva el filtro de productos inventariados.
- `search_provider` busca también por identificación.
- Advertencias nuevas `tarifa_12_sin_fecha`, `liquidacion_con_ruc` e `ice_sin_iva_factura`. Reglas del modo liquidación más estrictas (tarifas, descuento, ICE, propina e IVA de la factura). Importes con más de 2 decimales se rechazan. Límite de $9.999.999,99.
- El modal del proveedor usa `auto_id='fp_proveedor_%s'` para que sus ids no choquen con los de la compra.

---

## 3. Compras: completar datos (nueva)

- **Ruta:** `GET/POST /pos/purchase/complete/<pk>/`, nombre `purchase_complete`.
- **Vista:** `PurchaseCompleteView`. **Plantilla:** `purchase/complete.html` (extiende `skin.html`; formulario de servidor, sin JS propio).
- **Permiso:** `change_purchase`: Propietario y Administrador (el Contador no, decisión P1). Compra de otra empresa: 404.
- **Plan:** todos los planes.
- Sirve para las compras incompletas y también para corregir la cabecera de una completa. **No cambia** líneas, stock, subtotal, proveedor ni fecha de registro. La cuenta por pagar solo cambia con la casilla `ajustar_cxp`.

**Contexto de la plantilla**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Completar datos de la compra» (la plantilla añade `#id`) |
| `compra` | dict | `Purchase.toJSON()` |
| `lineas` | list | `[linea.toJSON()]` |
| `form` | `CompletarCompraForm` | Cabecera, importes (solo compras anteriores) y casillas |
| `campos_cabecera` | tuple | Nombres de los campos de cabecera, en orden |
| `campos_importes` | tuple | Nombres de los importes |
| `campos_importes_visibles` | bool | `version_datos == 1` |
| `bloqueados` | list | Campos que salen deshabilitados |
| `motivo_bloqueo` | str | Por qué están bloqueados (vacío si no hay) |
| `faltantes` | list | `[{codigo, texto}]` de lo que le falta hoy |
| `cuenta_por_pagar` | dict o None | `{id, debt, saldo, pagado, base_calculo: {id, name}}` |
| `puede_ajustar_cxp` | bool | Hay cuenta por pagar con base `subtotal` (calculada sin IVA) |
| `resumen` | dict o None | Tras «Revisar»: `{cambios: [{campo, etiqueta, antes, despues}], advertencias, confirmaciones, textos_confirmacion, faltantes, total}` |
| `confirmaciones_visibles` | list | Casillas de confirmación que se muestran |
| `textos_confirmacion` | dict | `{código: texto}` de cada confirmación pedida |
| `total_con_iva` | str o None | Total que resultaría, para el texto de `ajustar_cxp` |
| `list_url` | str | `/pos/purchase/` |

**Campos (`CompletarCompraForm`)**
- Cabecera, en este orden: `tipo_comprobante` (Tabla 4, incluido el 03), `cod_sustento`, `estab`, `pto_emi`, `secuencial`, `autorizacion`, `fecha_emision`, `forma_pago`, `parte_relacionada` (`''`/`no`/`si`), `pago_loc_ext`, `tipo_doc_modificado`, `num_doc_modificado`, `aut_doc_modificado`, `fecha_doc_modificado`, `compra_modificada` (selector con hasta 200 compras del mismo proveedor que no son notas, más «Sin enlazar a una compra registrada»). Todos opcionales: se puede completar por partes.
- Solo en compras anteriores (`version_datos == 1`): `base_0`, `base_gravada`, `base_5`, `base_no_objeto`, `base_exenta`, `total_descuento`, `total_iva`, `total_ice`, `total_irbpnr`, `propina` (importes ≥ 0, hasta 2 decimales). **Todos o ninguno:** «Escribe todos los importes de la factura (usa 0 donde no haya valor).». El total se calcula.
- Casillas: `confirmar_diferencia`, `confirmar_iva`, `confirmar_plazo_ats` (solo se muestran cuando el servidor las pide) y `ajustar_cxp` (solo con `puede_ajustar_cxp`).
- Los campos bloqueados salen `disabled` y no se envían al servicio, que conserva lo guardado.

**Bloqueos**

| Situación | Campos bloqueados | Motivo que se muestra |
|---|---|---|
| Compra creada desde un XML (`origen = importacion`) | Tipo, establecimiento, punto, secuencial, autorización y fecha de emisión | «El tipo de comprobante, la numeración, la autorización y la fecha de emisión vienen del XML autorizado.» |
| Con retención vigente | Los de esos datos que ya están llenos (los vacíos se pueden llenar) | «La retención 001-001-… usa este número: anúlala antes de cambiarlo.» |
| Con liquidación vigente | El tipo siempre y la numeración ya llena | «La liquidación 001-001-… usa este número: anúlala antes de cambiarlo.» |

**Acciones (POST de formulario con `{% csrf_token %}`)**
- `name="action" value="revisar"`: misma página con `resumen` (tabla «Dato / Antes / Después», advertencias, «Seguirá incompleta:» con lo que falta o «Con estos datos la compra queda completa.»). No guarda. Cualquier `action` distinto de `completar` se trata como `revisar`.
- `name="action" value="completar"`: guarda con `compras.completar_datos` (auditado `purchase_complete`; con la casilla, también `purchase_debt_adjust`) y redirige a `/pos/purchase/` con «Datos de la compra guardados». Con un error vuelve a la página con el error arriba.

**Confirmaciones** (si falta la casilla, el error es el texto y la casilla aparece):
- `confirmar_diferencia`: «La factura suma $X sin impuestos y la compra registró $Y. No se cambian las líneas ni el stock: solo se guardan los importes de la factura para los formularios.»
- `confirmar_iva`: «El IVA escrito no corresponde a la tarifa general sobre la base gravada (más el 5 % de la base 5 %): confírmalo.»
- `confirmar_plazo_ats`: «La factura tiene más de un año: el ATS no la admitirá en este período. Confírmalo para guardarla.»

**Errores** (además de los de formato de la pantalla 2):
- Bloqueo: el motivo de la tabla (código `bloqueado`).
- Duplicado: «Ya registraste … de … (compra #N).».
- Ajuste de la cuenta: «Esta compra no tiene una cuenta por pagar calculada sin IVA para ajustar.», «Escribe los importes de la factura antes de ajustar la cuenta por pagar.», «Los pagos registrados ($X) superan el total con IVA ($Y): revisa los pagos antes de ajustar.».
- Tipo frente a líneas y pago guardados:
  - «Las notas de crédito y débito del proveedor se registran con líneas de gasto (sin producto): esta compra tiene productos y movió el stock. Elimínala y regístrala de nuevo como nota.»
  - «Una nota de crédito del proveedor no tiene cuenta por pagar propia y esta compra se registró a crédito: elimínala y regístrala de nuevo como nota de crédito.»
  - «Una nota de venta no discrimina IVA y esta compra tiene IVA: elimínala y regístrala de nuevo con tarifa 0 %.»
  - Al pasar a 03, las reglas de la liquidación (pantalla 2) y numeración vacía.
- Fecha frente a la tarifa de las líneas: «Las líneas de esta compra tienen IVA del 15 %, que rige desde el 01/04/2024: la fecha de emisión es anterior. Revisa la fecha.» y «Las líneas de esta compra tienen IVA del 12 %, que no rige para comprobantes desde el 01/04/2024: revisa la fecha de emisión.».

**Textos obligatorios:** «Las líneas, el stock y el subtotal registrado no cambian.» y, junto a `ajustar_cxp`, «Cambia la deuda de $X (sin IVA) a $Y (total con IVA). Queda registrado.» (si aún no hay total, «$Y» se sustituye por «el total que resulte de los importes»). La insignia «Calculada sin IVA» acompaña a la cuenta con base `subtotal`.

**Efectos al guardar:** si la compra es o pasa a ser una nota de crédito (04) y cambian el tipo, la compra que modifica o el total, se recalculan la cuenta por pagar de la compra modificada anterior y la de la nueva.

**Estados:** incompleta → completa (desaparece la insignia). Una compra completa se puede volver a abrir para corregir la cabecera, con los mismos bloqueos.

**Identificadores:** no hay JS. Las pruebas buscan «Las líneas, el stock y el subtotal registrado no cambian.», «Cambia la deuda de $100.00 (sin IVA)» y «vienen del XML autorizado».

**Libre para el diseño:** todo el aspecto (secciones, columnas, tabla de cambios), siempre que se conserven los `name` de los campos, los dos botones `action` y el CSRF.

**Diferencias con la especificación:**
- El formulario incluye además `total_irbpnr` (sin él, volver a guardar una compra completada desde el XML con IRBPNR lo pondría en 0) y `confirmar_plazo_ats`.
- Contexto adicional: `campos_cabecera`, `campos_importes`, `campos_importes_visibles`, `confirmaciones_visibles`, `textos_confirmacion` y `total_con_iva`; `resumen` añade `textos_confirmacion` y `faltantes`.
- El tipo de comprobante también se bloquea (compras importadas, con liquidación vigente o con retención vigente si ya está lleno).
- Reglas nuevas del tipo y de la fecha frente a las líneas y el pago guardados, y recálculo de cuentas al corregir una nota de crédito.

---

## 4. Compras: eliminar (modificada)

- **Ruta:** `GET/POST /pos/purchase/delete/<pk>/`, nombre `purchase_delete`. **Vista:** `PurchaseDeleteView`. **Plantilla:** `delete.html` (la genérica de confirmación: «¿Estas seguro de eliminar el registro N° …?»).
- **Permiso:** `delete_purchase` (Propietario y Administrador).
- **POST** (con `submit_with_formdata`): `{}` si se eliminó (el JS vuelve a `list_url`); `{"error": "…"}` si no; 404 `{"error": "La compra no existe."}` con un id de otra empresa o inexistente.
- **Qué hace:** devuelve el stock de las líneas con producto inventariado, borra la cuenta por pagar sin pagos, devuelve a «pendiente» el XML importado del que salió (evento `compra_eliminada`), recalcula la cuenta de la compra que modificaba una nota de crédito y audita `purchase_delete`.
- **Errores:** «La compra tiene un comprobante de retención: no se puede eliminar.», «La compra tiene una liquidación de compra: no se puede eliminar.», «La compra tiene notas de crédito o débito que la modifican: elimínalas primero.», «Tiene pagos registrados: elimínalos primero en Cuentas por pagar.», «La compra ya no existe.».
- **Libre para el diseño:** la plantilla genérica es común a todo el sistema.

---

## 5. Proveedores: listado (modificada)

- **Ruta:** `GET/POST /pos/provider/`, nombre `provider_list`. **Vista:** `ProviderListView`. **Plantilla:** `provider/list.html`. **JS:** `core/pos/static/provider/js/list.js`.
- **Permiso:** `view_provider` (Propietario, Administrador, Contador y Consulta). **Plan:** todos.
- **Acción `search`:** `[Provider.toJSON()]` con `tipo_identificacion {id, name}`, `tipo_sujeto {id, name}`, `parte_relacionada` (true/false/null), `tipo_id_ats`, `datos_completos` y `faltantes [{codigo, texto}]`.
- **Columnas:** Id, Nombre, Tipo, Identificación, Teléfono, Email, Dirección, «Datos del ATS» (texto «Completos», o la insignia «Datos incompletos» con lo que falta debajo) y Opciones (editar y eliminar).
- **Faltantes del proveedor:**

| Código | Texto |
|---|---|
| `tipo_identificacion` | «Falta el tipo de identificación» |
| `tipo_sujeto` | «Elige si es persona natural o sociedad» (solo pasaporte o identificación del exterior) |
| `parte_relacionada` | «Indica si es parte relacionada» |
| `identificacion_invalida` | El error de la validación de la identificación con el tipo guardado |

- **Identificadores que usa el JS:** `#data`.
- **Libre para el diseño:** columnas e insignias, con `render.text` en las de texto y `esc()` en el HTML de la insignia.
- **Diferencias con la especificación:** ninguna de fondo. Los botones de editar y eliminar se dibujan para todos los roles (como antes) y el servidor decide.

---

## 6. Proveedores: nuevo y edición (modificadas) — también el modal de la pantalla 2

- **Rutas:** `GET/POST /pos/provider/add/` (`provider_create`, `add_provider`) y `/pos/provider/update/<pk>/` (`provider_update`, `change_provider`). **Vistas:** `ProviderCreateView`, `ProviderUpdateView`. **Plantilla:** `provider/create.html` (extiende `form.html`). **JS:** `core/pos/static/provider/js/form.js`.
- **Roles:** Propietario y Administrador. **Plan:** todos; en el gratuito, con el límite de proveedores («El plan gratuito permite hasta N proveedores. Activa un plan en «Plan y pagos» para registrar más.»).
- **Contexto:** `title` («Nuevo registro de un Proveedor» o «Edición de un Proveedor»), `list_url`, `action` (`add` | `edit`), `form` (`ProviderForm`).

**Campos (`ProviderForm`, en este orden)**

| Campo | Tipo | Obligatorio | Validaciones |
|---|---|---|---|
| `name` | texto | Sí | Único en la empresa |
| `tipo_identificacion` | `04` RUC, `05` cédula, `06` pasaporte, `08` identificación del exterior | Sí | «Elige el tipo de identificación.»; el 07: «Un proveedor no puede ser consumidor final: elige RUC, cédula, pasaporte o identificación del exterior.» |
| `ruc` (etiqueta «Identificación») | texto, hasta 20 | Sí | Según el tipo: 13 dígitos para RUC, 10 para cédula, de 3 a 20 caracteres para pasaporte o exterior. Única en la empresa |
| `tipo_sujeto` | `01` persona natural, `02` sociedad | Con 06 u 08 | Con RUC se calcula (tercer dígito 6 o 9 → sociedad) y con cédula es persona natural: el JS lo deshabilita y el servidor lo recalcula. «Elige si es persona natural o sociedad» |
| `parte_relacionada` | `''` \| `no` \| `si` | Sí (lo exige el servidor) | Sin valor inicial en un proveedor nuevo; al editar muestra lo guardado. «Indica si es parte relacionada» |
| `mobile`, `email`, `address` | texto | Celular y correo sí | Únicos en la empresa (validación remota `validate_data`) |

**Acciones (POST multipart)**
- `add` / `edit`: guarda. Devuelve `Provider.toJSON()` con `advertencias [{codigo, texto}]`, o `{"error": {campo: [mensajes]}}`. Con advertencias, el JS muestra «Proveedor guardado» con el texto y luego vuelve al listado.
- `validate_data` (`pattern`, `parameter`): `{valid}`.
- `search_ruc_in_sri` (`ruc`): datos del SRI. El botón «Buscar RUC con el SRI» (`.btnSearchRUCInSRI`) solo se habilita con tipo 04 y 13 dígitos; la respuesta se muestra como texto en `#myModalSRI`.

**Advertencia:** `ats_longitud`, «El ATS admite hasta 13 caracteres en la identificación del proveedor» (no bloquea).

**Efecto al editar:** en la misma transacción se recalcula la marca de datos incompletos de todas las compras del proveedor (sin auditoría propia).

**Identificadores que usa el JS (no cambiar):** `#frmForm` y su `data-url`, `input[name="ruc"]`, `select[name="tipo_identificacion"]`, `select[name="tipo_sujeto"]`, `input[name="name"]`, `input[name="mobile"]`, `.btnSearchRUCInSRI`, `#myModalSRI`, `#details`, `i[data-field="search_ruc_sri"]`; los nombres de campo de FormValidation; las funciones globales `identificacion_valida`, `es_identificacion_extranjera`, `validate_text_box`, `submit_with_formdata`, `alert_sweetalert` (de `static/js/functions.js`).

**Libre para el diseño:** orden visual, ayudas y el modal del SRI.

**Diferencias con la especificación:** `parte_relacionada` es opcional en el campo y el mensaje lo da solo el servicio (una sola fuente). La respuesta del SRI se muestra como texto. El aviso de advertencias al guardar es nuevo.

---

## 7. Cuentas por pagar: listado, pagos y abonos (modificada)

- **Ruta:** `GET/POST /pos/debts/pay/`, nombre `debts_pay_list`. **Vista:** `DebtsPayListView`. **Plantilla:** `debts_pay/list.html`. **JS:** `core/pos/static/debts_pay/js/list.js`.
- **Permiso:** `view_debts_pay`. Eliminar un pago exige además `delete_debts_pay`, que comprueba el servicio.
- **Qué ve y hace cada rol:** Propietario y Administrador: todo. Contador y Consulta: ven listado y movimientos; no ven los botones de eliminar (y el servidor responde 403 si lo intentan). Vendedor: no tiene el módulo.
- **Plan:** todos.

**Contexto:** `title` («Listado de Cuentas por Pagar»), `create_url` (`/pos/debts/pay/add/`), `form` (`ReportForm`, solo `date_range`), `puede_borrar` (bool, `delete_debts_pay`; al JS con `json_script` id `fp-cxp-puede-borrar`).

**Acciones (POST con `X-CSRFToken`)**
1. `search`, con `start_date` y `end_date` (filtra por la fecha de la cuenta). Devuelve `[DebtsPay.toJSON()]`: `id`, `purchase` (`toJSON()` de la compra), `date_joined`, `end_date`, `debt` y `saldo` (float), `state`, `base_calculo {id, name}`, `pagado`, `abonado` (texto) y `saldo_a_favor` (bool). Número de consultas constante.
2. `search_pays`, con `id`. Devuelve los pagos y luego los abonos: `[{index, tipo: 'pago'|'retencion'|'nota_credito', id, date_joined, valor ("15.00"), medio_pago {id, name}, referencia, description, puede_borrar}]`.
   - Pagos: `medio_pago.name` «Sin dato» si está vacío (pagos anteriores); `puede_borrar` según el permiso.
   - Abonos: `medio_pago` `{"id": "", "name": "No aplica"}`, `referencia` = número de la retención o de la nota de crédito, `description` = «Retención emitida» o «Nota de crédito del proveedor», `puede_borrar: false`.
   - Cuenta inexistente o de otra empresa: `{"error": "La cuenta por pagar no existe."}`.
3. `delete_pay`, con `id` (de un pago). `{}` si se eliminó (auditado `debt_payment_delete`; el saldo se recalcula). Errores: 403 `{"error": "Tu perfil no puede eliminar pagos."}`; 200 `{"error": "El pago no existe."}`.
4. Otro `action`: `{"error": "No ha seleccionado ninguna opción"}`.

**Estados de la cuenta**

| Estado | Cuándo | Qué se muestra | Qué permite |
|---|---|---|---|
| Calculada sin IVA | `base_calculo = subtotal` (cuentas anteriores a esta etapa) | Insignia «Calculada sin IVA» | Pagos. No recibe abonos automáticos por retenciones ni notas de crédito. Se ajusta al total con IVA solo desde «Completar datos» con la casilla |
| Total con IVA | `base_calculo = total` (compras nuevas a crédito) | «Total con IVA» | Pagos y abonos automáticos (retenciones autorizadas y notas de crédito del proveedor) |
| Adeuda / Pagado | `state` verdadero / falso | Insignias «Adeuda» y «Pagado» | Registrar pagos solo mientras adeuda |
| Saldo a favor | `saldo < 0` | Insignia «Saldo a favor» con el valor positivo | Solo ver |

**Columnas:** Número (de la compra), Proveedor, Fecha de compra, Fecha de plazo, Deuda, Base, Pagado, Abonado, Saldo, Estado y Opciones («Pagos y abonos» y, con `puede_borrar`, Eliminar → `pathname + 'delete/<id>/'`). **Pie:** «Saldo pendiente» en `.total`: suma solo los saldos positivos, en centavos enteros. Botones «Registrar pago» (se dibuja para todos; la pantalla 8 exige su permiso) y «Actualizar».

**Modal «Pagos y abonos»:** N.º, Tipo («Pago», «Retención emitida», «Nota de crédito»), Fecha, Valor, Medio de pago, Referencia, Detalles y Opciones (eliminar solo en pagos con `puede_borrar`). Confirmación: «¿Estas seguro de eliminar el pago? Queda registrado.».

**Identificadores que usa el JS (no cambiar):** `#data`, `input[name="date_range"]`, `.btnSearchAll`, `.total`, `#myModalPayments`, `#tblPayments`, `a[rel="payments"]`, `a[rel="delete"]`, `#fp-cxp-puede-borrar`, `pathname`, `csrftoken`.

**Libre para el diseño:** columnas, insignias y el modal.

**Diferencias con la especificación:** `search_pays` devuelve `valor` como texto; en los abonos `medio_pago` es «No aplica» y la descripción es el tipo de abono. El pie no resta los saldos a favor. Se añadió el error «El pago no existe.».

---

## 8. Cuentas por pagar: registrar pago (modificada)

- **Ruta:** `GET/POST /pos/debts/pay/add/`, nombre `debts_pay_create`. **Vista:** `DebtsPayCreateView`. **Plantilla:** `debts_pay/create.html`. **JS:** `core/pos/static/debts_pay/js/form.js`.
- **Permiso:** `add_debts_pay` (Propietario y Administrador). **Plan:** todos.
- **Contexto:** `title` («Nuevo registro de un Pago»), `list_url`, `action` (`add`), `form` (`PaymentsDebtsPayForm`).

**Campos**

| Campo | Tipo | Obligatorio | Validaciones |
|---|---|---|---|
| `debts_pay` | id (select2 con `search_debts_pay`) | Sí | «La cuenta por pagar no existe.» |
| `date_joined` | fecha | Sí | «Escribe la fecha del pago (AAAA-MM-DD).», «La fecha del pago no puede ser futura.», «La fecha del pago no puede ser anterior a la de la cuenta por pagar (dd/mm/aaaa).» |
| `valor` | importe | Sí | «Escribe el valor del pago.», «El valor del pago debe ser mayor que cero.», «El valor del pago admite hasta 2 decimales.», «El pago ($X) supera el saldo pendiente ($Y).» |
| `medio_pago` | `efectivo`, `transferencia`, `deposito`, `cheque`, `tarjeta_debito`, `tarjeta_credito`, `compensacion`, `otro` | Sí; sin inicial | «Elige el medio de pago.», «Medio de pago no válido.» |
| `referencia` | texto, hasta 100 | Con `cheque` | «Escribe el número del cheque.», «La referencia admite hasta 100 caracteres.». Ayuda: «Obligatoria si pagas con cheque (escribe su número).» |
| `description` | texto | No | Se guarda «s/n» si va vacía |
| `cuenta_bancaria` | reservado | No enviarlo | Con valor: «Las cuentas bancarias llegan en la Etapa 3.» |

**Acciones**
- `search_debts_pay` (`term`): hasta 10 cuentas que adeudan, buscadas por proveedor, número o secuencial de la compra: `DebtsPay.toJSON()` con `text` en el formato `<proveedor> (<número>) / <AAAA-MM-DD> / $<deuda>`. El JS muestra «Saldo: $X» en `.deuda` y limita el valor.
- `add`: `{}` (el JS vuelve al listado) o `{"error": "…"}`. Guarda `registrado_por` y `registrado_en`.

**Identificadores que usa el JS:** `#frmForm`, `select[name="debts_pay"]`, `input[name="valor"]` (TouchSpin), `input[name="date_joined"]`, `select[name="medio_pago"]`, `.deuda`, `.select2`, `i[data-field="valor"]`. **Libre para el diseño:** el resto.

**Diferencias con la especificación:** los mensajes del servicio terminan en punto («Elige el medio de pago.», «Escribe el número del cheque.»); la validación del navegador usa los mismos textos sin punto.

---

## 9. Cuentas por pagar: eliminar (modificada)

- **Ruta:** `GET/POST /pos/debts/pay/delete/<pk>/`, nombre `debts_pay_delete`. **Vista:** `DebtsPayDeleteView`. **Plantilla:** `delete.html`.
- **Permiso:** `delete_debts_pay` (Propietario y Administrador).
- **POST:** `{}` si se eliminó (auditado `debt_delete`). Errores: «Tiene pagos registrados: elimínalos primero.», «Tiene retenciones o notas de crédito aplicadas.», 404 `{"error": "La cuenta por pagar no existe."}` (id ajeno) y 403 `{"error": "Tu perfil no puede eliminar cuentas por pagar."}` (defensa del servicio; antes salta el permiso de la vista).
- Antes se borraba en cascada con sus pagos y sin registro; ahora se rechaza si tiene pagos o abonos.

---

## 10. Gastos: listado (modificada)

- **Ruta:** `GET/POST /pos/expenses/`, nombre `expenses_list`. **Vista:** `ExpensesListView`. **Plantilla:** `expenses/list.html`. **JS:** `core/pos/static/expenses/js/list.js`.
- **Permiso:** `view_expenses` (Propietario, Administrador, Contador y Consulta). **Plan:** ruta de pago (tabla de reglas comunes).
- **Contexto:** `title`, `create_url`, `form`, `url_gasto` (`/pos/purchase/add/?tipo=gasto`).
- **Aviso fijo** sobre la tabla: «¿Tienes factura? Regístrala en Compras como compra de gasto (sustenta el IVA y el ATS).», con el enlace a `url_gasto`.
- **Acción `search`** (`start_date`, `end_date`): `[Expenses.toJSON()]` con `medio_pago {id, name}` («Sin dato» si está vacío) y `referencia`.
- **Columnas:** Id, Tipo de gasto, Fecha de registro, Valor, Medio de pago, Referencia, Detalles y Opciones. Pie: suma en `.total` (en centavos).
- **Identificadores:** `#data`, `input[name="date_range"]`, `.btnSearchAll`, `.total`. **Libre para el diseño:** el resto.

---

## 11. Gastos: nuevo y edición (modificadas)

- **Rutas:** `/pos/expenses/add/` (`expenses_create`, `add_expenses`) y `/pos/expenses/update/<pk>/` (`expenses_update`, `change_expenses`). **Plantilla:** `expenses/create.html`. **JS:** `core/pos/static/expenses/js/form.js`.
- **Roles:** Propietario y Administrador. **Plan:** ruta de pago; vencido, no se abren.
- **Contexto:** `title`, `list_url`, `url_gasto`, `action` (`add` | `edit`), `form` (`ExpensesForm`).
- **Campos:** `type_expense`, `description`, `date_joined`, `valor`, `medio_pago` (`MEDIOS_DE_PAGO`, obligatorio, sin inicial: «Elige el medio de pago») y `referencia` (hasta 100; obligatoria con cheque: «Escribe el número del cheque»).
- **Acción `add` / `edit`:** `{}` o `{"error": {campo: [mensajes]}}`.
- **Aviso fijo:** el mismo «¿Tienes factura? …» de la pantalla 10 (lo comprueba `test_gastos_medio_pago`).
- **Identificadores:** `#frmForm`, `select[name="medio_pago"]` y los de FormValidation de siempre.

---

## 12. Tipos de gasto: listado, nuevo y edición (modificadas)

- **Rutas:** `/pos/type/expense/` (`type_expense_list`, `view_type_expense`), `add/` (`type_expense_create`), `update/<pk>/` (`type_expense_update`). **Plantillas:** `type_expense/list.html`, `type_expense/create.html`. **JS:** `core/pos/static/type_expense/js/list.js` y `form.js`.
- **Roles:** Propietario y Administrador; Consulta solo ve; el Contador no tiene el módulo. **Plan:** ruta de pago.
- **Listado (`search`):** `TypeExpense.toJSON()` con `cuenta_contable`, `cod_sustento` y `nombre_sustento` («Sin indicar» si está vacío). Columnas: Id, Nombre, Cuenta contable, Sustento tributario y Opciones.
- **Formulario:** `name`, `cuenta_contable` (texto opcional, hasta 30; ayuda «Código del plan de cuentas de tu contador (opcional).») y `cod_sustento` (Tabla 5, opcional, primera opción «Sin indicar»; ayuda «01 da crédito tributario de IVA; 02 no. Confírmalo con tu contador.»).
- **Contexto adicional:** `sustento_gasto_sugerido` (`01` | `02`, al JS con `json_script` id `fp-sustento-sugerido`) y `nombre_sustento_sugerido`. Bajo el sustento: «Sugerencia: 0X — …» y el botón «Usar sugerencia» (`#fp-usar-sugerencia`), que solo cambia `select[name="cod_sustento"]`.
- **Identificadores:** `#fp-usar-sugerencia`, `#fp-sustento-sugerido`, `select[name="cod_sustento"]`. **Libre para el diseño:** el resto.

---

## 13. Importación: crear compra desde el XML (nueva: página y API)

- **Rutas:** página `GET/POST /importacion/documentos/<pk>/compra/` (`importacion_compra`) y API `GET/POST /importacion/api/documentos/<pk>/compra/` (`importacion_api_compra`).
- **Vistas:** `CompraDesdeDocumento` y `CompraDesdeDocumentoApi` (`core/importacion/views.py`); servicios en `core/importacion/compras.py`. **Plantilla:** `importacion/compra.html` (extiende `importacion/base.html`). **JS:** `core/importacion/static/importacion/js/compra.js` (solo «Usar sugerencia»).
- **Permisos:** `change_documentoimportado` + `add_purchase` (Propietario y Administrador). Documento de otra empresa: 404.
- **Plan:** solo Ilimitado y Multiempresa; vencido, solo consulta (el POST de crear responde 403).

**API `GET`** → `{"documento": documento_dict, "puede_crear": bool, "propuesta": {…}, "opciones": {"sustentos": [[cod, nombre]], "formas_pago": [[cod, nombre]], "tipos_gasto": [{id, nombre, cod_sustento}]}}`.

**`propuesta`** (lo mismo usa la página):

| Clave | Significado |
|---|---|
| `tipo_comprobante`, `numero`, `estab`, `pto_emi`, `secuencial`, `autorizacion` (clave de acceso), `fecha_emision` | Del XML; no se editan |
| `proveedor` | `{id, nombre, ruc, tipo_identificacion}` o `null` si hay que crearlo |
| `cod_sustento_sugerido`, `nombre_sustento_sugerido` | Sugerencia según las reglas de importación (o el sustento de la compra modificada). El selector empieza vacío |
| `forma_pago_del_xml` | Forma de pago del pago de mayor valor, o `null` si el XML no trae pagos (o es una nota de crédito) |
| `payment_type_sugerido`, `end_credit_sugerido` | `credito` si un pago del XML trae plazo (nunca en notas de crédito) y la fecha = hoy + plazo; si no, `efectivo` y `null` |
| `parte_relacionada` | La del proveedor (true/false/null) |
| `doc_modificado` | Notas 04 y 05: `{tipo_doc_modificado, num_doc_modificado, fecha_doc_modificado, aut_doc_modificado, motivo}`; si no, `null` |
| `compra_modificada` | `{id, numero, base_calculo}` o `null` |
| `importes` | `{base_0, base_gravada, base_5, base_no_objeto, base_exenta, total_descuento, total_iva, total_ice, total_irbpnr, propina, total}` (texto) o `null` |
| `subtotal`, `por_tarifa` | Total sin impuestos y resumen por tarifa |
| `lineas` | `[{indice, codigo_principal, codigo_auxiliar, descripcion, cantidad ("1.000000"), cantidad_entera, precio_unitario, descuento, precio_total_sin_impuesto, codigo_porcentaje, tarifa, nombre_tarifa, iva, ice, producto_sugerido {id, nombre, codigo} o null, origen_sugerencia ('equivalencia' | 'mismo_codigo' | null), modo_sugerido ('producto' | 'gasto'), solo_gasto}]` |
| `agrupar_obligatorio` | Verdadero en notas 04 y 05 y con más de 500 líneas |
| `exige_confirmar_sin_verificar` | El documento no está verificado en el SRI y la regla lo exige |
| `confirmaciones` | Puede traer `confirmar_plazo_ats` y `confirmar_no_duplicada` |
| `advertencias` | `[{codigo, texto}]`: las del XML más las de abajo |
| `bloqueos` | `[{codigo, texto, compra_id}]`; con alguno, `puede_crear` es falso |
| `textos` | «Los importes son los del XML autorizado.» y «El stock solo sube en las líneas que emparejes con un producto inventariado.» (o, en notas, «Las notas de crédito y débito no mueven stock en esta etapa.») |

**Bloqueos**

| Código | Texto |
|---|---|
| `sin_xml` | «El documento todavía no tiene su XML autorizado.» |
| `no_recibido` | «Solo se crea una compra desde un documento recibido por la empresa.» |
| `tipo_no_admitido` | «Un comprobante de retención se registra en «Registrar retención recibida», no como compra.» (07) o «Solo se crean compras desde facturas, notas de crédito y notas de débito.» |
| `verificacion` | «No se puede incorporar: <estado de verificación>.» (no autorizada, no encontrada o con discrepancias) |
| `ambiente_pruebas` | «El documento es del ambiente de PRUEBAS del SRI: no sustenta una compra.» |
| `ya_vinculado` | «Ya se creó o se vinculó la compra #N con este documento.» |
| `revisado` | «El documento ya está «…». Reábrelo para crear la compra.» |
| `proveedor_incompleto` | «Completa el tipo de identificación del proveedor en Proveedores antes de crear la compra.» |
| `comprobante_registrado` | «Ya está registrada en la compra #N: vincúlala en lugar de crear otra.» (con `compra_id`) |
| `tarifa_desconocida` | «Una línea del XML no trae una tarifa de IVA que la compra pueda guardar.» (u otro texto del lector) |
| `sin_lineas` | «El XML no detalla líneas ni impuestos de IVA para la compra.» |

**Advertencias propias:** `cantidad_fraccionaria`, `sin_equivalencia`, `muchas_lineas`, `doc_modificado_sin_compra`, `bancarizacion`, `iva_linea_descuadrado` y `posible_duplicado` («Ya hay una compra registrada antes con el mismo número: #N (número …, dd/mm/aaaa). Si es este comprobante, vincúlala desde el documento en lugar de crear otra (duplicaría el stock y la cuenta por pagar); si es otra compra, confírmalo.»).

**API `POST`** (JSON, `Content-Type: application/json`):
```json
{"cod_sustento": "06", "payment_type": "credito", "end_credit": "2026-11-27", "forma_pago": "20",
 "parte_relacionada": "no", "date_joined": "2026-10-28", "agrupar_por_tarifa": false, "type_expense": null,
 "confirmar_sin_verificar": false, "confirmar_plazo_ats": false, "confirmar_no_duplicada": false,
 "lineas": [{"indice": 0, "modo": "producto", "product": 7, "recordar": true}, {"indice": 1, "modo": "gasto", "type_expense": 3}],
 "proveedor_nuevo": {"mobile": "0999999999", "email": "proveedor@example.com", "parte_relacionada": "no"}}
```
- Respuestas: 201 `{"compra": {"id", "numero", "url": "/pos/purchase/"}, "documento": documento_dict}`; 400 `{"error": "…"}` con `"codigo"` cuando lo hay (un bloqueo, `confirmar_no_duplicada`, `ya_vinculado`, `duplicado`, `confirmar_plazo_ats`…); 403 (permiso o plan); 404 (la página estándar de Django, no JSON).
- Reglas: una línea sin elección va como gasto; `producto` exige cantidad entera («La línea N tiene cantidad 2,5: regístrala como gasto o ajusta el stock a mano.») y un producto de la empresa («Línea N: elige un producto de la empresa.»); `recordar` guarda la equivalencia (evento `equivalencia_guardada`); si no llega `end_credit`, el plazo del XML se cuenta desde `date_joined`; si `forma_pago` no llega se usa la del XML, y si llega vacía la compra queda con el faltante `forma_pago`.
- Sin verificación cuando la regla la exige: «El documento no está verificado en el SRI. Verifícalo o confirma que lo incorporas sin verificar.».
- Con más de 500 líneas sin agrupar: «La factura tiene N líneas: agrúpalas por tarifa (una compra admite hasta 500).».
- Dos peticiones a la vez sobre el mismo documento: solo una crea la compra; la otra recibe «Ya se creó la compra #N desde este documento.» o «Ya se creó una compra desde este documento.».

**Página: contexto**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Crear compra desde el XML» |
| `documento` | dict | `documento_dict(detalle=True)` (pantalla 15) |
| `propuesta` | dict | La de la API |
| `form` | `CompraDesdeDocumentoForm` | Cabecera |
| `lineas` | formset | `LineasCompraFormSet`, prefijo `lineas` |
| `filas` | list | Pares (línea de la propuesta, su formulario); vacío si se agrupa |
| `puede_crear` | bool | Sin bloqueos |
| `url_documento` | str | `/importacion/documentos/<pk>/` |
| `limites`, `puede_importar`, `puede_revisar`, `bandeja` | — | Comunes de las páginas de importación |

**Página: campos.** Cabecera: `cod_sustento` (sin inicial), `forma_pago` (inicial la del XML; opción vacía «Sin forma de pago (completar después)»), `date_joined` (inicial hoy), `payment_type`, `end_credit`, `parte_relacionada`, `agrupar_por_tarifa` (casilla; en notas y con más de 500 líneas va oculta con valor `on`), `type_expense` (tipo de gasto de las líneas agrupadas), `confirmar_sin_verificar`, `confirmar_plazo_ats` y `confirmar_no_duplicada` (estas tres solo cuando la propuesta las pide) y, si no hay proveedor, `mobile` y `email` (el proveedor se crea con la razón social del XML, tipo RUC y la parte relacionada elegida). Formset por línea: `lineas-N-indice` (oculto), `lineas-N-modo` (`gasto` | `producto`), `lineas-N-product`, `lineas-N-type_expense`, `lineas-N-recordar`, más el `management_form`. Botón `name="action" value="crear"`.

**Página: acción.** Éxito: redirige a `/pos/purchase/` con «Compra #N creada desde el XML». Error: la misma página con el error arriba. Otro `action`: «Acción no válida.».

**Identificadores:** `[data-fp-sugerencia]` (id del campo destino) y `data-valor` en el botón «Usar sugerencia»; `data-bloqueo` y `data-advertencia` en las alertas; la clase `fp-importacion-compra` con `data-documento`. Las pruebas buscan «Usar sugerencia», `data-valor="06"`, «Los importes son los del XML autorizado.», «Se registra una línea de gasto por tarifa de IVA, con el motivo de la nota.», «Las notas de crédito y débito no mueven stock en esta etapa.» y que una nota no tenga `lineas-TOTAL_FORMS`.

**Libre para el diseño:** todo el aspecto; el selector de producto por línea (hoy lista todos los productos de la empresa) puede pasar a un autocompletado si conserva el `name`.

**Diferencias con la especificación:** bloqueos nuevos `ambiente_pruebas`, `proveedor_incompleto`, `tarifa_desconocida` y `sin_lineas`; claves nuevas en la propuesta (`proveedor`, `nombre_sustento_sugerido`, `subtotal`, `por_tarifa`, `agrupar_obligatorio`, `exige_confirmar_sin_verificar`, `confirmaciones`, `textos`, `lineas[].solo_gasto`, `lineas[].codigo_auxiliar`, `compra_modificada.base_calculo`); `type_expense` de las líneas agrupadas; confirmación `confirmar_no_duplicada`; las notas 04 y 05 siempre se agrupan; los 400 llevan `codigo`; contexto adicional `filas` y `url_documento`.

---

## 14. Importación: registrar retención recibida desde un 07 (nueva)

- **Ruta:** `GET/POST /importacion/documentos/<pk>/retencion-recibida/`, nombre `importacion_retencion_recibida`. **Vista:** `RetencionRecibidaDesdeDocumento`. **Plantilla:** `importacion/retencion_recibida.html`. Sin JS propio.
- **Permisos:** `change_documentoimportado` + `add_retencionrecibida` (este lo crea O2; ver «Roles»). Sin permiso: redirección con el mensaje de permiso (GET) o 403 (POST). Documento de otra empresa: 404.
- **Plan:** solo Ilimitado y Multiempresa; vencido, solo consulta.

**Contexto**

| Nombre | Tipo | Significado |
|---|---|---|
| `title` | str | «Registrar retención recibida» |
| `documento` | dict | `documento_dict(detalle=True)` |
| `leida` | dict o None | `{numero, fecha_emision, periodo_fiscal, agente_ruc, agente_razon_social, version, ambiente, total_retenido, verificado_sri, sustentos: [{numero_con_guiones, cod_doc_sustento, fecha_emision_doc_sustento, num_aut_doc_sustento, cod_sustento, retenciones: [{impuesto, codigo_retencion, base_imponible, porcentaje, valor_retenido}]}]}` (importes como texto) |
| `error_lectura` | str | Por qué no se pudo leer el 07 (vacío si se leyó) |
| `bloqueos` | list | `[{codigo, texto}]` (el de `ya_registrada` trae `url`) |
| `exige_confirmar_sin_verificar` | bool | Muestra la casilla |
| `form` | `RetencionRecibidaDesdeDocumentoForm` | Solo `confirmar_sin_verificar` |
| `puede_registrar` | bool | Se leyó y no hay bloqueos |
| `url_documento`, `url_retenciones_recibidas` | str | Ficha del documento y `/comprobantes/retenciones-recibidas/` |

**Bloqueos:** `no_es_07` («El documento no es un comprobante de retención (07).»), `no_recibido` («Solo se registra una retención que recibió la empresa (la empresa es el sujeto retenido).»), `sin_xml` («El documento todavía no tiene su XML autorizado.»), `verificacion` («No se puede registrar: <estado>.»), `descartado` («El documento está descartado: reábrelo antes.»), `ya_registrada` (se muestra como éxito: «Registrada en Retenciones recibidas.» con «Ver las retenciones recibidas»).

**Acción (POST de formulario):** `name="action" value="registrar"` + CSRF (+ `confirmar_sin_verificar` si se pide). Éxito: redirige a la ficha del documento con «Retención recibida registrada (N documentos sustento)». Error: la misma página con el mensaje. Mensajes de O1: «El documento no está verificado en el SRI. Verifícalo o confirma que lo registras sin verificar.» (código `confirmar_sin_verificar`), «El registro de retenciones recibidas todavía no está disponible» (sin el servicio de O2, código `no_disponible`), «Acción no válida.». Los errores de O2 llegan con su texto y su código.

**Estados del documento:** pendiente o aprobado → se puede registrar; vinculado → solo lectura con enlace a las retenciones recibidas; descartado → bloqueado. **Todo o nada:** si un sustento no es una factura propia o la retención trae ISD, no se registra ninguno (lo hace O2).

**Textos obligatorios:** «Se registra una retención recibida por cada factura sustento y se abona su cuenta por cobrar.», «Para deshacerlo, anula la retención en Retenciones recibidas: el documento vuelve a quedar pendiente.» y, junto al botón, «Si una factura sustento no es tuya o la retención trae ISD, no se registra ninguna.».

**Identificadores:** `data-bloqueo` en las alertas. Las pruebas buscan los números de los sustentos, «Se registra una retención recibida por cada factura sustento», `name="action" value="registrar"`, «Registrada en Retenciones recibidas» y `name="confirmar_sin_verificar"`.

**Diferencias con la especificación:** contexto adicional `error_lectura` y `puede_registrar`; `leida.sustentos[]` añade `cod_doc_sustento`; mensaje «Acción no válida.». En esta rama el permiso `add_retencionrecibida` no existe: la pantalla solo se abre en las pruebas.

---

## 15. Importación: ficha del documento, API de documentos y nueva importación (modificadas)

- **Rutas:** `/importacion/documentos/<pk>/` (`importacion_documento`, `view_documentoimportado`), `/importacion/api/documentos/` (`importacion_api_documentos`), `/importacion/api/documentos/<pk>/` (`importacion_api_documento`) y `/importacion/nueva/` (`importacion_nueva`). Plantillas `importacion/documento.html` y `importacion/nueva.html`.
- **`documento_dict(detalle=True)` añade:**
  - `detalles` (líneas del XML de 01 y 04), `doc_modificado` (`{cod_doc, numero, fecha_emision, motivo}`), `motivos` (`[{razon, valor}]` de la 05) y `retencion` (`{version, periodo_fiscal, tipo_sujeto, parte_rel, docs_sustento}` del 07). Un documento importado antes de esta etapa se vuelve a leer de su XML sin modificarlo.
  - `aviso_contable`: «La retención se contabiliza con la retención recibida.» en un 07.
  - `motivo_sin_reabrir`: «La compra #N se creó desde este documento: elimínala en Compras para reabrirlo.» o «Se incorporó como retención recibida: anula allí el registro de la retención para reabrir el documento.».
  - `urls`: `{compra: '/importacion/documentos/<id>/compra/' | null, retencion_recibida: '/importacion/documentos/<id>/retencion-recibida/' | null, retenciones_recibidas: '/comprobantes/retenciones-recibidas/' | null}`.
- **`acciones`:**

| Documento | Acciones |
|---|---|
| Recibido 01/04/05 pendiente | `verificar`, `aprobar`, `vincular_compra`, `crear_compra` (si no tiene compra), `crear_proveedor` (si no hay proveedor), `descartar` |
| Recibido 07 pendiente | `verificar`, `aprobar`, `registrar_retencion`, `descartar` (nunca `crear_proveedor`: el emisor es el cliente) |
| Recibido 07 aprobado | `verificar`, `registrar_retencion`, `reabrir` |
| Emitido 01 pendiente | `verificar`, `aprobar`, `vincular_venta`, `descartar` |
| Emitido 04/05/07 pendiente | `verificar`, `aprobar`, `descartar` |
| Recibido 07 descartado | `verificar`, `reabrir` |
| Otro documento ya revisado | `verificar` y `reabrir`, salvo que `motivo_sin_reabrir` lo impida |

- **Ficha:** botones «Crear compra» (a `urls.compra`) y «Registrar retención recibida» (a `urls.retencion_recibida`), distintos del botón «Vincular» de cada candidato; secciones nuevas «Documento modificado», «Motivos», «Líneas del XML» y «Retención recibida (versión …, período …)» con «Documento sustento …»; avisos «Registrada en Retenciones recibidas.» (07 vinculado) y «Vinculado con la compra #N.»; `crear_proveedor` pide además `parte_relacionada` (`''` sin indicar, `no`, `si`).
- **Servicio de revisión:** `vincular_compra` con un 07: «Un comprobante de retención no se vincula con una compra: regístralo en «Registrar retención recibida».»; con una compra de otro tipo: «La compra es de otro tipo de comprobante (…): no es este documento.»; `vincular_venta` solo con una factura emitida; `crear_proveedor` con un 07: «El emisor de un comprobante de retención es tu cliente (agente de retención), no un proveedor.». Los candidatos de conciliación marcan `exacto: true` y la razón «mismo comprobante».
- **API de documentos:** filtro nuevo `?cod_doc=01|04|05|07` («Tipo de comprobante no válido.» con otro valor).
- **Nueva importación:** «Se admiten facturas, notas de crédito, notas de débito y retenciones (01, 04, 05 y 07).». Los tipos 03 y 06 siguen como «tipo no soportado todavía. Por ahora se importan facturas (01), notas de crédito (04), notas de débito (05) y comprobantes de retención (07).». Advertencias nuevas del lector: `motivos_descuadrados` y `retencion_descuadrada`.
- **Pruebas que leen esta página:** «Registrar retención recibida», «Documento sustento 001001000000123», que un 07 vinculado no muestre «Reabrir revisión», «Documento modificado», «Líneas del XML», el enlace `/compra/` y `name="parte_relacionada"`.
- **Diferencias con la especificación:** claves nuevas `aviso_contable`, `motivo_sin_reabrir` y `urls.retenciones_recibidas`; un 07 aprobado ofrece también `reabrir`; los emitidos 04, 05 y 07 ofrecen además `descartar`; `reabrir` deja de ofrecerse cuando está bloqueado.

---

## 16. Reporte de compras (modificada)

- **Ruta:** `GET/POST /reports/purchase/`, nombre `purchase_report`. **Vista:** `PurchaseReportView` (`GroupModuleMixin`). **Plantilla:** `purchase_report/report.html`. **JS:** `core/reports/static/purchase_report/js/report.js`.
- **Acceso:** por módulo (Propietario, Administrador, Contador y Consulta). **Plan:** todos.
- **Acciones:** `search_report` (`start_date`, `end_date`, `fecha` = `registro` | `emision`) → `[compra.toJSON()]` ordenado por fecha de registro; `totales` → igual que en la pantalla 1.
- **Columnas:** Número, Tipo, Sustento, Proveedor, Identificación, Fecha de emisión, Fecha de registro, Tipo de pago, Base, IVA, Total y Datos («Compra anterior · sin IVA», «Datos incompletos», «Fuera del plazo del ATS» o «Completa»). Base y total de las notas de crédito salen con «-$».
- **Pie:** «Total con IVA de las compras completas (las notas de crédito restan):» (`.fp-total-completas`) y «Subtotal registrado de las compras con datos incompletos:» (`.fp-total-incompletas`). Ejemplo probado: una nota de crédito de $20 sobre una compra de $100 deja $80.
- **Identificadores:** `#tblReport`, `#fp-reporte-fecha`, `.fp-total-completas`, `.fp-total-incompletas`, `input[name="date_range"]`, `.btnSearchAll`. Excel y PDF con los botones de DataTables.

## 17. Reporte de cuentas por pagar (modificada)

- **Ruta:** `/reports/debts/pay/`, nombre `debts_pay_report`. **Vista:** `DebtsPayReportView`. **Plantilla y JS:** `debts_pay_report/report.html`, `core/reports/static/debts_pay_report/js/report.js`.
- **Acceso:** por módulo. **Plan:** todos.
- **Acción `search_report`:** `[DebtsPay.toJSON()]` (consultas constantes).
- **Columnas:** Proveedor, Identificación, Número, Fecha de compra, Fecha de plazo, Base de cálculo («Calculada sin IVA» o total), Deuda, Pagado, Abonado, Saldo y Estado.

## 18. Reporte de gastos (modificada)

- **Ruta:** `/reports/expenses/`, nombre `expenses_report`. **Vista:** `ExpensesReportView`. **Plantilla y JS:** `expenses_report/report.html`, `core/reports/static/expenses_report/js/report.js`.
- **Acceso:** por módulo. **Plan:** ruta de pago.
- **Columnas:** Id, Tipo de gasto, Fecha de registro, Detalles, Medio de pago («Sin dato» si está vacío), Referencia y Valor.

**Diferencias con la especificación (16–18):** el reporte de compras filtra también por fecha de emisión y usa la acción `totales`; el de cuentas por pagar añade Identificación y Número.

---

## A. Datos que devuelven los modelos (`toJSON`)

- **`Purchase.toJSON(detalle=False)`:** `id`, `number`, `provider` (`Provider.toJSON()`), `payment_type {id, name}`, `date_joined`, `end_credit`, `subtotal` (float), `numero_comprobante`, `tipo_comprobante {id, name}`, `cod_sustento {id, name}`, `estab`, `pto_emi`, `secuencial`, `autorizacion`, `fecha_emision` (o `null`), `forma_pago {id, name}`, `parte_relacionada` (true/false/null), `pago_loc_ext {id, name}`, `signo` (-1 en notas de crédito), `version_datos` (1 o 2), `datos_incompletos`, `fuera_plazo_ats`, `origen {id, name}` (`manual` | `importacion`), los importes `base_0`, `base_gravada`, `base_5`, `base_no_objeto`, `base_exenta`, `total_descuento`, `total_iva`, `total_ice`, `total_irbpnr`, `propina`, `total` (texto o `null`) y `doc_modificado {tipo, numero, autorizacion, fecha, compra_id}` o `null`. Con `detalle=True`, además `clase` y `faltantes`.
- **Faltantes de una compra** (código → texto): `importes` «Faltan los importes de la factura (bases, IVA y total)», `tipo_comprobante` «Falta el tipo de comprobante», `cod_sustento` «Falta el sustento tributario», `sustento_no_admitido`, `proveedor_incompleto` («Faltan datos del proveedor: …»), `tipo_id_no_admitido`, `estab`, `pto_emi`, `secuencial`, `autorizacion`, `fecha_emision`, `forma_pago` «Falta la forma de pago (ATS)», `parte_relacionada` «Indica si el proveedor es parte relacionada», `pago_loc_ext`, `pago_exterior_pendiente` «Los datos del pago al exterior se completan en la Etapa 4», `doc_modificado`, `liquidacion_pendiente` «Falta emitir la liquidación de compra y que el SRI la autorice» (o «La liquidación … se autorizó en el ambiente de PRUEBAS del SRI: no sustenta la compra»), `liquidacion_descuadrada` y `fuera_plazo_ats` «Registrada más de un año después de su emisión: el ATS no la admite».
- **`PurchaseDetail.toJSON()`:** `id`, `product` (dict o `null`), `tipo` (`producto` | `gasto`), `descripcion` (la del producto si la línea no tiene), `type_expense {id, name}` o `null`, `codigo_proveedor`, `codigo_porcentaje`, `tarifa` (texto o `null`), `nombre_tarifa` («—» si no se conoce; «IVA diferenciado N %» para el 8), `cant`, `price`, `dscto`, `subtotal` (float) y `total_dscto`, `total`, `total_iva`, `total_ice` (texto o `null`).
- **`Provider.toJSON()`:** los campos del modelo más `text`, `tipo_identificacion {id, name}`, `tipo_sujeto {id, name}`, `parte_relacionada`, `tipo_id_ats` (`01` RUC, `02` cédula, `03` pasaporte o exterior, `''`), `datos_completos` y `faltantes`.
- **`DebtsPay.toJSON(detalle=False)`:** ver la pantalla 7; con `detalle=True` añade `abonos` y calcula `abonado` con ellos.
- **`PaymentsDebtsPay.toJSON()`** y **`Expenses.toJSON()`:** `valor` (float), `medio_pago {id, name}` («Sin dato» si está vacío) y `referencia`. **`TypeExpense.toJSON()`:** `cuenta_contable`, `cod_sustento` y `nombre_sustento`.

---

## B. Pendiente para Codex

1. **Diseño de todas las pantallas** sobre este contrato. No hubo revisión visual en navegador: los JS solo pasaron `node --check` y las vistas se probaron con el cliente de Django.
2. **Mensajes de éxito con título «Error».** «Compra #N registrada.», «Datos de la compra guardados», «Compra #N creada desde el XML» y «Retención recibida registrada (…)» salen en la ventana global de `hzt_body.html`/`vtc_body.html`, que titula todo «Error». Esas plantillas no son de esta rama; que el integrador o Codex distingan el nivel del mensaje.
3. **Autocompletado de productos por línea** en «Crear compra desde el XML» (pantalla 13): hoy cada línea lista todos los productos de la empresa. Usar una búsqueda AJAX como `search_product`, conservando `lineas-N-product`. El servidor ya valida el id.
4. **Errores por campo en la página «Crear compra desde el XML»:** la plantilla solo muestra bajo su campo los de `cod_sustento` y `email`; los demás llegan como errores del formulario o del servicio arriba. Mostrar `field.errors` de todos los campos.
5. **Aviso de posible duplicado:** sale con las demás advertencias (`data-advertencia="posible_duplicado"`) y su casilla `confirmar_no_duplicada` aparece abajo. Conviene ponerlo junto a la casilla y con más realce.
6. **Botones sin permiso que se dibujan igual** (comportamiento anterior, el servidor decide): «Registrar pago» en cuentas por pagar, editar y eliminar en proveedores, y los de gastos y tipos de gasto. En Compras ya se ocultan según `permisos_listado`; Codex puede aplicar el mismo patrón donde haya un booleano en el contexto.
7. **Botón «Actualizar» del listado de compras:** apunta a `{{ list_url }}`, que esa vista no pasa (como antes); recarga la página actual.
8. **Fuera de las pantallas de esta rama, para el integrador o Codex:**
   - mostrar la clave `aviso` de cada línea de `liquidaciones.lineas_de_compra` en `comprobantes/liquidacion/create.html`;
   - `RetencionCrearView.iniciales` debe usar `compras.datos_sustento_retencion` (con los avisos `sustento_varias_tarifas` y `sustento_tarifa_no_disponible`) después de traer D0, y rechazar las compras con `compras.admite_retencion(compra) == False` (notas de crédito);
   - el diseño de Retenciones recibidas de O2 debe enlazar con la pantalla 14.
9. **Móvil:** las tablas de líneas de «Nueva compra» y de «Crear compra desde el XML» son anchas; la segunda ya usa `data-label` por celda.
10. **Textos y fragmentos que comprueban las pruebas** (no cambiarlos sin avisar al integrador):
    - Compras: `id="fp-compra-opciones"`; los literales de `list.js` de la pantalla 1; «Las líneas, el stock y el subtotal registrado no cambian.»; «Cambia la deuda de $100.00 (sin IVA)»; «vienen del XML autorizado»; «Usar sugerencia» con `?tipo=gasto` y su ausencia sin él.
    - Gastos: «¿Tienes factura?». Tipos de gasto: «Usar sugerencia».
    - Importación: los de las pantallas 13, 14 y 15.
    - Escape: todo lo que revisa `tests/test_estaticos_compras.py`.

---

## C. Diferencias con la especificación (resumen)

| # | Pantalla | Diferencia | Motivo |
|---|---|---|---|
| 1 | Compras: listado | Acción `totales` y contexto `permisos_listado`; `detalle.cuenta_por_pagar` con `id` y `pagado`; «Completa» como texto | El pie se calcula en el servidor, sin `float` |
| 2 | Nueva compra | `add` devuelve `{id, advertencias}` (+ `confirmacion`); `opciones` con cinco claves más; contexto `nombre_sustento_sugerido`; `validate_comprobante` con `url_compra` y `posible_duplicado` | Mostrar la casilla pedida y los avisos |
| 3 | Nueva compra | Sin el 03 en el selector; reglas del modo liquidación más estrictas; importes de más de 2 decimales rechazados; advertencias `tarifa_12_sin_fecha`, `liquidacion_con_ruc`, `ice_sin_iva_factura` | Correcciones de la revisión (la liquidación que se emite debe cuadrar con la compra) |
| 4 | Nueva compra | Se quitó el modal «Buscar productos»; `search_provider` busca también por identificación; modal de proveedor con `auto_id='fp_proveedor_%s'` | Menos código, sin ids repetidos |
| 5 | Completar datos | Campos `total_irbpnr` y `confirmar_plazo_ats`; contexto adicional; el tipo también se bloquea; reglas del tipo y la fecha frente a líneas y pago; recálculo de cuentas al corregir una NC | No perder el IRBPNR del XML; correcciones O1-F1, F2 y F3 |
| 6 | Eliminar compra y cuenta | 404 con `{"error"}` para ids ajenos | Corrección O1-T5 |
| 7 | Proveedores | `parte_relacionada` opcional en el campo (el mensaje lo da el servicio); aviso de advertencias al guardar; editar recalcula la marca de sus compras | Una sola fuente del mensaje; corrección O1-F4 |
| 8 | Cuentas por pagar | `search_pays` con `valor` texto y abonos «No aplica»; pie sin saldos a favor; error «El pago no existe.»; mensajes con punto final | Importes sin `float`; texto claro |
| 9 | Crear compra desde el XML | Bloqueos `ambiente_pruebas`, `proveedor_incompleto`, `tarifa_desconocida`, `sin_lineas`; claves nuevas de la propuesta; `type_expense` de líneas agrupadas; `confirmar_no_duplicada`; notas siempre agrupadas; 400 con `codigo`; contexto `filas` y `url_documento` | Fallar cerrado ante datos que la compra no puede guardar; corrección O1-F6 |
| 10 | Retención recibida | Contexto `error_lectura` y `puede_registrar`; `cod_doc_sustento` en `leida`; el permiso aún no existe en la rama | El permiso es de O2 |
| 11 | Ficha del documento | `aviso_contable`, `motivo_sin_reabrir`, `urls.retenciones_recibidas`; acciones de 07 aprobado y de emitidos 04/05/07 | El 07 no tiene propuesta contable; no ofrecer acciones que el servicio rechaza |
| 12 | Reportes | Filtro por fecha de emisión y acción `totales` en compras; Identificación y Número en cuentas por pagar | Mismo pie que el listado |
| 13 | Roles | El Contador no completa datos (P1); sin cambios en `roles.py` | Decisión de esta entrega |

**Contratos definitivos:** las pantallas 1 a 13 y 15 a 18 quedan definitivas para esta rama, salvo lo que cambie al integrar con O2 y el commit X (pantalla 14 y el punto 8 del apartado B). La pantalla 14 es definitiva en sus campos y textos, pero no funciona hasta que O2 aporte `add_retencionrecibida` y `registrar_desde_importacion`.
