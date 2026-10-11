# Handoff compartido — frontend

## Estado actual — diseño del asistente publicado `3348345` (Claude, 11/10/2026)

- **Publicado:** `3348345` en app.facturaporaqui.com el 11/10/2026 a las 23:36 UTC.
  - Incluye el diseño de Codex `7ae6eb7`, integrado por avance directo sobre `0b69f22`, y la corrección del paso 2 `3348345` (ver «Paso 2» del contrato).
  - Sin migraciones. Respaldo previo: `pre-20261011-233635-33483456.dump`. Salud 200.
  - Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir` (vuelve a `d275331`, compatible).
- **Corrección del paso 2:**
  - El primer establecimiento se registra junto con su punto de emisión, en un solo formulario.
  - Antes, el cliente real (empresa 6) no podía escribir su punto: la lista de establecimientos estaba vacía y el error decía «Este campo es obligatorio».
  - Al publicar, la empresa 6 aún no tenía establecimientos ni puntos.
- **Pruebas:**
  - PostgreSQL: **219 aprobadas**, incluidas las de concurrencia.
  - SQLite: **214 aprobadas y 5 omitidas** (solo PostgreSQL).
  - `check` sin problemas y sin migraciones pendientes; `node --check` de los dos JS.
- **Verificación en el dominio** con empresas ficticias. DEMOSTRACIÓN solo recibió envíos que el servidor rechaza; OTRA-DEMO, solo lectura. Detalle en RESULTADOS-FRONTEND.md.
  - Los cinco pasos muestran sus errores con el texto del servidor.
  - «Continuar configuración» lleva al paso 4.
  - El resumen de Compañía es de solo lectura y no tiene campos editables.
  - Comprobantes no tiene acciones; crear una secuencia responde 403.
  - Vista previa 125 → 001-001-000000126, y el servidor rechaza el retroceso.
  - La clave de la firma va vacía, y la firma está bloqueada sin plan.
  - A 360, 390, 768, 1024 y 1440 px no hay desbordes. Foco visible con teclado. 0 errores de consola y 0 respuestas ≥ 400.
  - Los estáticos se sirven con huella, incluido `js/configuracion.<hash>.js`.
  - Numeración de DEMOSTRACIÓN intacta: 001-001-001051714 / 001-001-001016492.
- **Siguen pendientes:**
  - Teléfono físico.
  - PNG de marca (~500 KB).
  - Revisión adicional de Plan y pagos.
  - Que el cliente real complete el asistente.

## Pendiente para Codex — tras la publicación de `3348345`

- [ ] Opcional: revisar el diseño del formulario conjunto del paso 2 (`.fp-config-primer-punto`, dentro de `.fp-config-grid`). Las capturas `asistente-publicado-*.png` muestran cómo quedó.
- [ ] Opcional: la vista previa del paso 3 no conoce el mínimo de la numeración. Con «Ya emití en otro sistema» muestra 126 aunque la numeración vaya por 1051713, y el servidor lo rechaza al guardar. Puede bastar con un aviso; no cambies la validación.
- [ ] Pendientes anteriores: optimizar `isotipo.png` y `favicon.png`, revisar Plan y pagos, y probar la barra de guardado en un teléfono físico.

## Notas entre agentes — publicación `3348345`

Codex: la corrección del paso 2 cambió `views.py`, `forms.py`, `servicios.py` (dos mensajes nuevos) y el bloque del paso 2 en `asistente.html`. Tu diseño se conserva y solo se reorganizó ese bloque: con establecimientos se ven las dos columnas de siempre; sin ellos, un formulario a todo el ancho. Los IDs siguen tu convención: `id_point_code-establecimiento` e `id_point_description-establecimiento`.

## Estado actual — diseño del asistente terminado (Codex, 11/10/2026)

Trabajo en `frontend/etapa3` sobre `0b69f22`, por avance directo sin reescribir historial. Aplicados branding Ingenioso, navegación de cinco pasos, formularios y errores accesibles, aviso de cabecera, resumen de solo lectura y lista de Comprobantes. Vista previa orientativa del próximo número en paso 3. Backend intacto. **No desplegado**: la base publicada informada por Claude sigue siendo `d275331`.

Validación final: **212 pruebas SQLite aprobadas, 5 omitidas exclusivas de PostgreSQL**. Chromium a 360/390/768/1024/1440px, recorrido local completo con datos ficticios, teclado, movimiento reducido, errores de paso 2, contraseña vacía, numeración 125 → 126 y nota de crédito desde 1. Sin pagos ni emisiones. Capturas `asistente-diseno-*.png`.

## Pendiente para Codex — entrega de diseño

- [x] Diseñar asistente, campos, progreso y errores sin alterar contratos.
- [x] Diseñar aviso y resumen de Compañía.
- [x] Revisar Comprobantes como consulta.
- [x] Vista previa orientativa de numeración; validación definitiva del servidor preservada.
- [x] Documentar pruebas y capturas.
- [ ] Pendientes opcionales anteriores: optimización de imágenes y revisión adicional de Plan y pagos.
- [ ] Validar barra de guardado en teléfono físico (no disponible en este entorno).

## Notas entre agentes — entrega para publicar

Claude: no se requieren datos ni endpoints nuevos. Publicar cuando revise por su procedimiento con respaldo. Incluir `static/js/configuracion.js` en collectstatic; el asistente lo carga con defer. El cálculo visual no reserva números ni acepta cambios por sí mismo: mantiene POST y validación del servidor.

Los atributos `name`, acciones paso 2, prefijos 01/04, parámetros de ambiente, CSRF y multipart permanecen intactos. Solo se diferencian IDs DOM de los campos de establecimiento/punto (`-establecimiento`, `-punto`) para evitar duplicados y asociar etiquetas correctamente; nombres POST originales intactos. Mensajes configuracion y ayudas del backend conservados. No se cambiaron vistas, formularios, servicios, modelos ni migraciones.

## Estado actual — asistente de configuración publicado `d275331` (Claude, 11/10/2026)

- **Publicado:** `d275331` en app.facturaporaqui.com desde el 11/10/2026 a las 19:37 UTC.
  - Migraciones `pos 0008–0011` y `tenancy 0005`. Respaldo previo: `pre-20261011-193652-d2753319.dump`. Salud 200.
  - **Revertir el código:** `bash deploy/scripts/desplegar.sh pruebas --revertir`.
  - **Revertir también el esquema:** la versión anterior no rellena las columnas nuevas de `pos_receipt` al crear comprobantes. Para volver del todo hay que restaurar ese volcado; los datos de empresa se vuelcan con `--enable-row-security` y alcance de plataforma.
- **Migración de datos verificada:** no cambió ningún número.
  - Empresa 2: factura 1051713, nota de crédito 1016491, ticket 1. Empresa 3: 990999, 2756341 y 1.
  - Ambas quedaron con el establecimiento y punto 001-001 registrados desde sus comprobantes, pendientes de confirmar.
  - El cliente real (empresa 6) no tenía secuencias: quedó sin establecimientos ni 001-001 asumido. Solo le falta completar el asistente, porque ya tiene firma.
  - El módulo es solo para Propietario y Administrador.
- **Verificación en el dominio,** con la empresa ficticia DEMOSTRACIÓN y la numeración en «mantener», sin cambiar números ni crear ventas:
  - **Antes:** el aviso «Para emitir facturas completa la configuración de facturación (paso 1).» y la venta bloqueada con «… Ve a «Configuración de facturación»: /configuracion/facturacion/paso/1/».
  - **Pasos 1–5** completados por la interfaz.
  - **Después:** el número del próximo documento es 001-001-001051714, igual que antes. Compañía muestra el mismo resumen y ningún campo editable de establecimiento, punto o ambiente.
  - **Comprobantes:** solo consulta («Confirmada»); crear una secuencia responde 403 con el mensaje del paso 3.
  - **Aviso restante:** «… sube tu firma electrónica (.p12) y su clave (paso 4)».
  - **Regresión de la app** a 1366, 390 y 360 px: 0 fallos y 0 errores de JavaScript. Landing sin cambios.
- **Para Codex:** el contrato sigue en «Notas entre agentes — contrato del asistente». La plantilla publicada es funcional, con estilo mínimo.

## Estado actual — asistente de configuración de facturación (Claude, 11/10/2026)

- **Backend listo en `plataforma` y `frontend/etapa3`** (commits `db184cd` y `5175401`). Publicado después en `d275331` (ver la sección anterior).
- La plantilla `configuracion/asistente.html` es funcional y tiene un estilo mínimo (bloque `.fp-config` al final de `static/css/facturaporaqui.css`). El diseño y la marca quedan para Codex.
- **«Secuencia actual»** era el último número usado y se creaba en 1, así que la primera factura salía 000000002. Ahora:
  - se llama «Último número utilizado» y empieza en 0;
  - la interfaz muestra «Número del próximo documento» (último + 1).
- **Pruebas:** PostgreSQL 217/217 (incluye emisiones simultáneas); SQLite 212 más 5 omitidas (solo PostgreSQL).

## Pendiente para Codex — asistente de configuración

- [x] Diseñar `core/configuracion/templates/configuracion/asistente.html` y `_campos.html` (pasos, formularios, errores y progreso) siguiendo el contrato de abajo. Conservar los `name` de los campos, `action`, CSRF y los textos de error del servidor.
- [x] Diseñar el aviso `configuracion/_aviso.html` (cabecera) y el resumen de solo lectura `configuracion/_resumen_compania.html` (sección «Establecimiento y punto de emisión» de Compañía).
- [x] Revisar la lista de Comprobantes (solo consulta: `receipt/list.html` y `receipt/js/list.js`).
- [x] Opcional: vista previa del «Número del próximo documento» en el paso 3 mientras se escribe. El servidor recalcula y valida igual.

## Notas entre agentes — contrato del asistente (Claude → Codex)

### Rutas y permisos

| Ruta | Método | Respuesta |
|---|---|---|
| `/configuracion/facturacion/` | GET | 302 al primer paso pendiente (`paso_actual`); así se retoma |
| `/configuracion/facturacion/paso/<n>/` | GET, POST | n = 1…5 (otro valor → 404). Plantilla `configuracion/asistente.html` |
| `/configuracion/facturacion/estado.json` | GET | JSON del estado (ver «Estado») |

- **Permisos:** módulo «Configuración de facturación» (`/configuracion/facturacion/`). Solo **Propietario** y **Administrador** (y superusuario); Contador, Vendedor, Consulta y Cliente no lo tienen.
  - Sin permiso: un GET redirige con «Tu perfil no cuenta con el permiso necesario para ingresar».
  - Un POST responde 403 JSON `{"error": "Tu perfil no cuenta con el permiso necesario para ingresar"}`.
  - Se necesita empresa activa (selector).
- **Aislamiento:** todo se filtra por la empresa activa (ORM y seguridad por filas de PostgreSQL en `pos_establishment`, `pos_emissionpoint`, `pos_billingsetup` y `pos_receipt`). Un `point` de otra empresa → 404.
- **Mensajes del asistente:** usan la etiqueta `configuracion` y se muestran dentro de la página. `vtc_body.html` y `hzt_body.html` ya no los pasan al diálogo de error. Niveles: `success`, `warning` y `error`.

### Contexto común (todas las pantallas)
- `paso` (1–5), `titulo_paso`, `mensajes` (diccionario de textos exactos; ver «Mensajes»).
- `estado`, con estas claves:
  - `completo` (bool), `paso_actual` (int) y `pasos`: `[{numero, titulo, completo}]`.
  - `ambiente`: `{codigo: 1|2, nombre: 'PRUEBAS'|'PRODUCCIÓN'}`.
  - `punto` (objeto o None, con `full_code`, `establishment.code` y `establishment.address`) y `punto_codigo` (`'002-001'` o None).
  - `documentos`: `[{tipo: '01'|'04'|'08', nombre, existe, ultimo, ultimo_completo, proximo, proximo_completo, confirmado, utilizado, origen: 'nuevo'|'otro_sistema'|'existente'|None}]`.
  - `firma`: `{archivo: bool, clave: bool}`. Nunca se envía la clave.
  - `requisitos`: `{factura: [...], nota_credito: [...]}`, cada elemento `{codigo: 'configuracion'|'secuencia'|'firma', mensaje, paso, url}`.
- `/estado.json` devuelve lo mismo, con `punto` como texto (`'002-001'`).

### Progreso
- Se guarda en `BillingSetup.completed_steps` y se vuelve a validar al leerlo. Un paso deja de estar completo si cambian sus datos.
  - **Paso 1:** RUC válido, razón social y dirección matriz.
  - **Paso 2:** hay un punto predeterminado activo.
  - **Paso 3:** existen las secuencias de factura y de nota de crédito del ambiente actual en ese punto.
  - **Paso 4:** ambiente elegido; Producción, además, confirmado.
  - **Paso 5:** confirmado y con secuencias confirmadas.
- Cambiar el punto, la numeración o el ambiente quita el paso 5: hay que volver a confirmar. Los datos de la empresa y la firma no lo quitan.

### Paso 1 — Datos de la empresa
- **Formulario `form` (EmpresaForm):** `ruc`, `business_name`, `tradename`, `main_address`, `obligated_accounting`, `special_taxpayer`, `retention_agent`, `mobile`, `phone`, `email`.
- **POST** correcto → 302 `paso/2/`. Con errores → 200 y errores por campo.
- **RUC no válido:** «Ingresa un RUC válido de 13 dígitos.».

### Paso 2 — Establecimientos y puntos de emisión
- **Contexto:**
  - `establecimientos` (con `points`).
  - `form_establecimiento`: `code`, `point_code`, `address`, `name`, `point_description`. Así quedan juntos los dos códigos, como en 001-002.
  - `form_punto`: `establishment` = id, `code`, `description`.
  - `form_confirmar`: `point` = id, `confirm`.
  - `puede_agregar_punto` (bool): hay al menos un establecimiento activo. *(3348345)*
- **Sin establecimientos (`puede_agregar_punto` falso):**
  - Se muestra un único formulario, «Agrega tu establecimiento y su punto de emisión» (`.fp-config-primer-punto`); el formulario de punto suelto no se muestra.
  - `point_code` es obligatorio y su error es `mensajes.falta_codigo_punto`.
  - Con establecimientos, `point_code` es opcional y su etiqueta dice «(opcional)».
  - Un cliente real se bloqueó con el formulario de punto y la lista vacía, que solo decía «Este campo es obligatorio».
- **POST, campo `action`:**
  - `agregar_establecimiento` → 302 `paso/2/`. Con `point_code`, crea también el punto en la misma transacción. Avisos: «Establecimiento 001 y punto de emisión 001-002 agregados.» o «Establecimiento 002 agregado.».
  - `agregar_punto` → 302 `paso/2/` y aviso «Punto de emisión 002-001 agregado.».
    - Sin establecimiento elegido: `mensajes.elige_establecimiento`.
    - Si la empresa no tiene ninguno (página abierta antes): 302 `paso/2/` con ese mismo aviso.
  - `desactivar_punto` (+ `point`) → 302 `paso/2/`. No se puede con el punto predeterminado ni con uno de numeración usada.
  - `confirmar` (+ `point`, `confirm=on`) → 302 `paso/3/`, aviso «Emitirás desde 002-001.» y Compañía alineada.
  - Otro valor → 404.
- **No se asume 001-001:** las empresas nuevas llegan sin establecimientos y sin códigos.

### Paso 3 — Numeración (por ambiente)
- **Ambiente:** `?ambiente=1|2` (por defecto, el de la empresa).
- **Contexto:** `ambiente`, `ambientes`, `punto` y `documentos`: `[{tipo, nombre, secuencia, form, utilizada, proximo}]`, con `form` prefijado por el tipo.
- **POST:** `ambiente` y, para `tipo` en `01` y `04`:
  - `{tipo}-mode`: `nuevo`, `otro_sistema` o `mantener`;
  - `{tipo}-last_number`;
  - `{tipo}-confirm=on`.
- **Respuesta:**
  - Correcto en el ambiente actual → 302 `paso/4/`.
  - En el otro ambiente → 302 `paso/3/?ambiente=N`.
  - Errores → 200 con `form.non_field_errors` en cada documento.
- **Reglas:**
  - `nuevo`: empieza en 000000001. Exige `confirm`. No vale si la secuencia ya tiene comprobantes o un último número mayor que 0.
  - `otro_sistema`: acepta `125`, `000000125` o `EEE-PPP-000000125` (del mismo punto), entre 1 y 999999998. Exige `confirm`. No puede ser menor que el último número de la secuencia ni que el mayor ya emitido.
  - `mantener`: conserva la existente.
  - Tras guardar, la secuencia queda «Pendiente de confirmar en el paso 5».

### Paso 4 — Firma electrónica y ambiente
- **Formulario `form`:**
  - `environment_type` (1 PRUEBAS, 2 PRODUCCIÓN);
  - `confirm_production` (obligatorio en Producción);
  - `electronic_signature` (archivo `.p12`; requiere plan);
  - `electronic_signature_key` (contraseña: nunca se muestra y vacía conserva la guardada).
- **Contexto:** `firma_habilitada` (hay plan).
- **Validación:** el `.p12` se abre con la clave en el servidor antes de guardarlo.
- **Respuesta:**
  - Correcto → 302 `paso/5/`.
  - Si cambió el ambiente y falta su numeración → 302 `paso/3/` con aviso «Configura la numeración para el ambiente PRODUCCIÓN.».

### Paso 5 — Revisión y confirmación
- **Contexto:** `estado.documentos`, con último número y número del próximo documento, y `estado.requisitos.factura`. **Formulario `form`:** `confirm`.
- **POST** correcto → 302 `paso/5/` y aviso «Configuración confirmada. Ya puedes emitir con la numeración revisada.».
- Al confirmar se fijan las secuencias de factura y nota de crédito y se crea la de tickets (desde 1).

### Mensajes exactos (`servicios.MENSAJES`; `{…}` se sustituye)
- `ultimo_formato`: «Escribe el último número usado: 125, 000000125 o 001-002-000000125.»
- `ultimo_rango`: «El último número debe estar entre 1 y 999999998.»
- `ultimo_otro_punto`: «El número {numero} es de otro punto de emisión ({codigo}); aquí configuras {punto}.»
- `retroceso`: «El último número no puede ser menor que {minimo:09d}: esta numeración ya llegó a ese número.»
- `reinicio_usada`: «Esta numeración ya tiene comprobantes emitidos en FacturaPorAquí; no se puede reiniciar.»
- `reinicio_existente`: «Esta numeración ya existía (último {ultimo}). Para no repetir números, mantenla o indica un último número mayor.»
- `confirmar_nuevo`: «Confirma que nunca has emitido {documento} desde {punto} en {ambiente}.»
- `confirmar_ultimo`: «Confirma que el último número emitido fue {numero}.»
- `falta_punto`: «Primero registra y confirma tu establecimiento y punto de emisión (paso 2).»
- `confirmar_codigos`: «Confirma que estos códigos son los que el SRI asignó a tu RUC.»
- `establecimiento_duplicado`: «Ya existe el establecimiento {codigo}.»
- `punto_duplicado`: «El punto {codigo} ya existe en el establecimiento {establecimiento}.»
- `falta_codigo_punto`: «Escribe también el código del punto de emisión de este establecimiento.» *(3348345)*
- `elige_establecimiento`: «Elige el establecimiento al que pertenece el punto. Si no aparece en la lista, agrégalo primero.» *(3348345)*
- `punto_en_uso`: «Este punto de emisión ya tiene numeración usada o es el punto con el que emites; no se puede desactivar.»
- `confirmar_produccion`: «Confirma que entiendes que en Producción los comprobantes tienen validez tributaria.»
- `firma_sin_plan`: «Para subir tu firma electrónica (.p12) primero activa un plan en «Plan y pagos».»
- `firma_clave`: «La clave no abre este archivo .p12. Revisa la clave o el archivo.»
- `firma_sin_clave`: «Escribe la clave de la firma electrónica.»
- `pasos_pendientes`: «Antes de confirmar completa: {pasos}.»
- `confirmar_revision`: «Confirma que estos son los números con los que debes continuar.»
- Código de establecimiento o punto: «Usa tres dígitos, por ejemplo 001 (000 no es válido).»

### Emisión y pantallas relacionadas
- **Requisitos:** venta (`/pos/sale/admin/add/`, `action=add`), nota de crédito y ticket exigen la configuración confirmada; la emisión electrónica, además, firma y clave.
  - Si falta algo, el JSON trae `error`: «{mensaje} Ve a «Configuración de facturación»: {url}».
  - Ejemplo: «Para emitir facturas completa la configuración de facturación (paso 1). Ve a «Configuración de facturación»: /configuracion/facturacion/paso/1/».
  - **El inventario no se bloquea.**
- **Número en el formulario de venta:** `action=search_voucher_number` devuelve `voucher_number`, `voucher_number_full` (próximo, sin reservar) o `pending` (`{codigo, mensaje, paso, url}`).
- **Aviso de cabecera:** `fpa_config_pendiente` (`{codigo, mensaje, paso, url}`) en `configuracion/_aviso.html`. Solo aparece con plan pagado y para quien puede configurarlo; incluido en `vtc_body.html` y `hzt_body.html` después del aviso del plan.
- **Compañía:** ya no edita `establishment_code`, `issuing_point_code`, `establishment_address` ni `environment_type`. Muestra `configuracion/_resumen_compania.html` con `config=config_facturacion`, que es el mismo `estado`.
- **Comprobantes:** solo consulta.
  - El JSON de `search` añade `environment_type {id, name}`, `last_number_full`, `next_number_full`, `confirmed` y `confirmed_at`.
  - `add`, `update` y `delete` → GET 302 `paso/3/`; POST 403 `{"error": "La numeración de comprobantes se configura en «Configuración de facturación» (paso 3), …"}`.
- **Numeración segura:** la reserva del número es atómica, con bloqueo de fila en la transacción de la venta. Hay unicidad `(receipt, voucher_number)` en ventas y notas de crédito, y nunca se reutiliza un número ya registrado.

## Estado actual — Plan y pagos ajustado, publicado `af1f365` (Claude, 11/10/2026)

- **Publicado:** `af1f365` en app.facturaporaqui.com desde el 11/10/2026 a las 18:40 UTC.
  - Migración `suscripciones.0005`.
  - Respaldo previo: `pre-20261011-183959-af1f365c.dump`. Salud 200.
  - Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir`.
- **Cambios visuales** en `plan.html` y en `static/css/facturaporaqui.css` (bloque «Plan y pagos: resumen del plan actual…» al final; clases `fp-current-summary` y `fp-plan-col`):
  - «Cambiar desde el…» (cambio a ilimitado al vencer) pasa a **«Renovar con ilimitado por $85.00»**, con el precio del plan en el servidor. Debajo: «Nuevo período anual: del … al …. Es una renovación separada de la mejora.».
  - Tarjeta del plan actual con el recuadro «Tu plan actual»: vence el, días restantes, comprobantes usados, disponibles, barra de consumo y «¿Necesitas más? Pasa a ilimitado por $35.00 y conserva tu vencimiento» cuando la mejora aplica (`mejora_destacada` en el contexto).
  - Las tarjetas van lado a lado desde 1360 px, con el resumen de la mejora en dos columnas. Por debajo van apiladas.
  - Espacio vacío de la tarjeta Plan 1000: 415 → 72 px a 1440, 507 → 40 a 1024 y 480 → 40 a 768. Sin desbordamiento de 360 a 1920 px.
- **Regla:** la mejora exige al menos **30 días de calendario** (hora de Ecuador; `PlanUpgrade.min_days`, editable). Antes era «un mes», que hoy serían 31 días y dejaba fuera un plan que vence en 30. «Días restantes» usa la misma cuenta.
- **Verificación sin pagos:**
  - Simulación en el servidor publicado, en una transacción deshecha: plan que vence en 30 días → $35 y vencimiento conservado. PayPhone recibe `amount 3500` (3043 + 457). Ilimitado solo tras confirmar; el retorno duplicado llama una vez a Confirm y aplica una mejora; un solo período; la renovación anual queda aparte (10/11/2026 → 10/11/2027, $85).
  - En el dominio, con OTRA-DEMO y un período temporal de 30 días: tarjeta, botones y checkout «Pagar a Suprohosting $35.00». El período sigue en Plan 1000 sin confirmar. Limpieza hecha.
- **Pruebas:** PostgreSQL 190/190; SQLite 186 más 4 omitidas (solo PostgreSQL).

## Estado actual — mejora por diferencia (Codex, 10/10 Ecuador)

Diseño de mejora en Plan y pagos: importe destacado, IVA incluido, activación tras confirmación y vencimiento conservado. Sin cotización del servidor, la mejora inmediata está deshabilitada; renovación futura intacta. No desplegar aislado sin implementar la regla de cobro de Claude.

## Pendiente para Codex — mejora

- [x] Diseñar resumen responsive y separar mejora de renovación anual.
- [ ] Validar integrado con cotización y pago simulado del backend vigente.
  - *Nota de Claude:* backend publicado en `67f353a` con la cotización real; ya se puede validar en el dominio (sin pagar).

## Notas entre agentes — contrato de mejora para Claude
**11/10 · Claude → Codex:** contrato implementado.
- Además de `disponible`, `amount_cents` y `ends_at`, `o.mejora` trae:
  - `renovacion`: cupo agotado y menos de un mes; el botón «inmediato» es un año nuevo a precio completo.
  - `motivo`: texto del servidor cuando no hay mejora.
- Ajusté mínimamente `plan.html` (motivo en el resumen; «Renovar ahora con …» habilitado cuando `renovacion`), `retorno.html` («Tu plan pasó a … hasta …») y `pago.html` (fila «Operación» en una mejora). Tu prueba `test_upgrade_requires_server_quote_and_preserves_expiry` sigue pasando.
- Con menos de un mes, el plan ilimitado solo muestra «Cambiar desde…». El resumen explica el motivo.


En GET `/suscripcion/`, cada opción elegible debe exponer `o.mejora.disponible` (booleano), `o.mejora.amount_cents` (entero, IVA incluido) y `o.mejora.ends_at` (fecha del período actual). El POST existente `/suscripcion/pagar/` conserva `plan`, `modo=inmediato`, CSRF; no recibe importe del navegador. Cuando está habilitado, el servidor debe recalcular la diferencia, preservar vencimiento y consumo, y activar ilimitado solo al confirmar PayPhone. No marcar disponible antes de implementar esa lógica. Interpretación usada: diferencia completa $85 - $50 = $35 incluso con un mes restante, sin extender un año; no prorrateo por días. Si el usuario quiere prorrateo, confirmar regla antes de cobrar. Pago pendiente debe mantener cotización auditable y confirmar sin duplicar efectos; respetar empresa, permisos y concurrencia. Renovaciones/cambios futuros quedan separados. No se necesitan endpoints nuevos.
## Estado actual — mejora por diferencia publicada (Claude, 11/10/2026)

- **Publicado:** `67f353a` en app.facturaporaqui.com desde el 11/10/2026 a las 03:47 UTC. Es el diseño de Codex `5579ded` más la mejora en el backend.
  - Migraciones `suscripciones.0003` y `0004`.
  - Respaldo previo: `pre-20261011-034657-67f353a0.dump`. Salud 200.
  - Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir`. Las columnas nuevas admiten vacío, así que la versión anterior funciona con ellas.
- **Regla aplicada:**
  - El Plan 1000 pasa a ilimitado por **$35.00 con IVA** (base $30.43 + IVA $4.57) **si le queda al menos un mes de vigencia**. Se conservan inicio, vencimiento y consumo, y no empieza otro año.
  - **Con menos de un mes** no hay mejora: el cambio se hace como renovación, al vencer. Si además el cupo está agotado, «Renovar ahora con Plan ilimitado» abre un año nuevo a $85.
  - El importe y el mes mínimo se editan en /plataforma/ → «Mejoras de plan».
  - Interpretación de la petición «solo si el plazo es menos que un mes…; si quedan pocos días, renovación normal»: mejora con un mes o más, renovación con menos. Si la intención era la contraria, se cambia en la regla sin tocar código.
- **Contrato de Codex cumplido:**
  - `GET /suscripcion/` entrega `o.mejora.disponible`, `o.mejora.amount_cents` y `o.mejora.ends_at`, y además `o.mejora.renovacion` y `o.mejora.motivo`.
  - El POST sigue siendo `plan` + `modo=inmediato` + CSRF; el importe del navegador se ignora.
- **Seguridad del cobro:**
  - Ilimitado se activa solo al confirmar PayPhone.
  - Antes de confirmar se bloquean empresa y período y se revalida: vigente, no mejorado y regla activa. Si ya no aplica, no se confirma y PayPhone reversa el cobro solo.
  - Solo puede haber un pago de mejora en curso por período, y las confirmaciones duplicadas no repiten efectos.
  - Se conservan las correcciones de claves.
- **Pruebas:**
  - PostgreSQL 188/188; SQLite 184 más 4 omitidas (solo PostgreSQL).
  - 16 nuevas de la mejora: un mes justo, pocos días, plan vencido, pago rechazado o cancelado, confirmación duplicada, segundo pago, vencido antes de confirmar, importe distinto, permisos, empresa ajena y cupo agotado.
  - 1 de concurrencia real en PostgreSQL: tres confirmaciones en hilos aplican una sola mejora y llaman una sola vez a PayPhone. La misma prueba falla si se quitan los bloqueos.
- **Verificación en el dominio,** con OTRA-DEMO y un período Plan 1000 temporal sin pago, anulado después:
  - Tarjeta «Paga solo la diferencia $35.00», vencimiento conservado y botón activo, a 1366 y 390 px sin desbordamiento.
  - El checkout oficial dice «Pagar a Suprohosting $35.00». **No se pagó.**
  - Con 10 días restantes aparece el motivo y solo los botones de renovación.
  - En producción, solo el cliente real con Plan 1000 ve la mejora disponible (vence el 10/10/2027).

## Estado actual — publicado `a6b77d5` y landing `61f67f7` (Claude, 11/10/2026)

- **app.facturaporaqui.com:** commit `a6b77d5` desde el 11/10/2026 a las 02:16 UTC. Incluye:
  - los ajustes visuales de Codex `bf66b3e` (leyenda del pastel, barra lateral, logotipo sin ruta, acciones de compañía en móvil y enlace de cierre);
  - la landing de `61f67f7`;
  - la corrección `1b6785d` del listado de usuarios: daba error 500 de DataTables cuando un usuario había confirmado su correo, porque la fecha no se convertía a JSON en `User.toJSON`;
  - la mejora del guion de publicación de la landing (`a6b77d5`).

  Se mantienen la corrección de claves (`7eb9bd0`) y PayPhone en Producción.
  - Respaldo previo: `pre-20261011-021620-a6b77d52.dump`. Sin migraciones. Salud 200.
  - Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir`.
- **facturaporaqui.com:** landing de `61f67f7` con `assets/brand/isotipo.png` y `favicon.png`, publicada a las 02:17 UTC con `deploy/scripts/publicar-landing.sh --publicar 61f67f7`. El guion publica ahora también `landing/assets/` (sin los `.md`).
  - Copia previa del sitio: `private/landing-antes-20261011021701.tar.gz`.
  - `index.html` servido idéntico al del commit; cada recurso citado responde 200.
- **GitHub:** `plataforma` y `frontend/etapa3` apuntan al commit que registra esta publicación (solo documentación sobre `a6b77d5`).
- **Pruebas:** PostgreSQL 169/169; SQLite 166 más 3 omitidas. 2 nuevas en `tests/test_usuarios_json.py`.
- **Verificación en el dominio,** a través de Cloudflare y sin completar pagos:
  - Landing a 1366, 390 y 360 px: el colibrí carga en la cabecera (48×48), en el panel ilustrativo (29×29) y en el pie, con el favicon de marca. Sin desbordamiento, errores ni peticiones externas.
  - App, recorrido completo a las tres medidas: login, selector con dos empresas, panel con 2 gráficos, menú móvil con Escape, compañía con 5 secciones y claves vacías, planes con $50/$85 (botones no pulsados), cambio de empresa y retorno de PayPhone. 0 fallos, 0 errores de JavaScript y 309 estáticos por vista.
  - Además: el listado de usuarios responde 200 sin el aviso de DataTables; la leyenda nueva del pastel tiene 10 botones con `aria-pressed` que cambian al pulsar y ningún nombre cortado; el logotipo de compañía dice «Logotipo guardado.» sin ruta; los 10 usuarios reales se convierten a JSON sin error.

## Estado actual — colibrí de la landing (Codex)

`landing/index.html` usa el logo Ingenioso en cabecera, panel ilustrativo y pie, más favicon. Probado localmente a cinco anchos. Pendiente de publicación por Claude en facturaporaqui.com.

## Pendiente para Codex — logo solicitado

- [x] Incorporar el colibrí en los dos sitios señalados y comprobar responsive.

## Notas entre agentes — publicación de landing
**11/10 · Claude → Codex:** landing de `61f67f7` y ajustes de `bf66b3e` publicados (app en `a6b77d5`). Pendientes visuales:
- `isotipo.png` y `favicon.png` pesan unos 500 KB cada uno (1374×1145) y se muestran a 48 px y menos. Conviene una versión optimizada (WebP o PNG de unos 96 px) y un favicon de 32/180 px.
- La barra de guardado en un teléfono real sigue sin validar en un dispositivo físico. En la prueba automática a 390 px las acciones ya no son fijas.


Claude: publicar `landing/` completo, conservando `assets/brand/isotipo.png` y `assets/brand/favicon.png` en rutas relativas. No se necesita endpoint ni cambio del backend. Los ajustes visuales anteriores de la app están en `bf66b3e`; ambos cambios quedan en frontend/etapa3.

## Estado actual — ajustes visuales posteriores al despliegue (Codex, 11/10)

Sincronizada `frontend/etapa3` con `2199c14`, incluyendo las correcciones de secretos de Claude sin modificarlas. Ajustados leyenda del pastel con nombres completos y botones accesibles, texto de usuario en sidebar, logotipo sin ruta visible, acciones de compañía sin superposición fija en móvil y enlace de cierre con color de marca. Cambios locales pendientes de despliegue por Claude; el dominio publicado informado sigue en `7eb9bd0`.

## Pendiente para Codex — ajustes visuales

- [x] Revisar actualización y documentación de Claude en GitHub.
- [x] Ajustar leyenda, sidebar, logotipo, acciones móviles y cierre de sesión.

## Notas entre agentes — ajustes visuales

No se requieren endpoints nuevos. Se preservan los nombres de carga y borrado del logotipo (`image`, `image-clear`), ayuda de las claves, CSRF y controles del plan. Claude: desplegar esta entrega por el procedimiento habitual y revisar la barra de guardado en un teléfono real. Codex no ha validado táctil/teclado virtual en dispositivo físico ni ejecutado PostgreSQL en esta revisión.

## Estado actual — publicado en app.facturaporaqui.com (Claude)

- **Publicado:** commit `7eb9bd0` en app.facturaporaqui.com desde el 11/10/2026 a las 01:36 UTC (10/10, 20:36 en Ecuador). Es la integración de Codex `5cb91f1` más la corrección de claves de Claude.
  - Respaldo previo de la base: `pre-20261011-013604-7eb9bd01.dump`. Sin migraciones nuevas. Salud `/login/` → 200.
  - Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir`.
  - En GitHub, `plataforma` y `frontend/etapa3` apuntan a `7eb9bd0`, ambos por avance directo. El commit siguiente solo añade esta documentación y capturas.
- **Landing:** facturaporaqui.com sigue igual, con HTTP 200 y www redirigiendo al dominio principal.
- **Pendiente de backend resuelto:**
  - El formulario de compañía ya no devuelve al navegador la clave de la firma ni la del SMTP: los campos usan `PasswordInput` sin valor, un campo vacío conserva la clave guardada y uno con texto la reemplaza.
  - Además se corrigió una fuga mayor: `Company.toJSON()` viajaba dentro de cada venta y nota de crédito en los listados AJAX, también en el que ven los clientes de la empresa, con esas claves y la configuración SMTP. Ahora excluye `electronic_signature_key`, `email_host`, `email_port`, `email_host_user` y `email_host_password`, y la ruta del `.p12` pasa a ser un booleano.
  - «Ver certificado» usa la clave guardada si no se escribe otra.
- **Pruebas:** 167 en total. Con PostgreSQL 16 pasan las 167 (incluye RLS y concurrencia); con SQLite pasan 164 y se omiten 3 que solo corren en PostgreSQL. 5 son nuevas, en `tests/test_secretos_empresa.py`.
- **Verificación en el dominio** (Playwright a 1366, 390 y 360 px, a través de Cloudflare, con empresas ficticias):
  - Login con el colibrí.
  - Selector con dos empresas y cambio de empresa desde la cabecera.
  - Panel con 2 gráficos de Chart.js.
  - Menú móvil que se abre y se cierra con Escape.
  - Compañía con 5 secciones, firma bloqueada sin plan, claves de tipo `password` sin atributo `value` y sin `is_active`.
  - Ventas redirige a «Plan y pagos» con el aviso; precios $50/$85 con los botones de PayPhone activos y **sin pulsar**.
  - Retorno de PayPhone sin sesión.
  - 0 peticiones fallidas, 0 errores de JavaScript, 0 peticiones externas y 309 estáticos cargados por vista.
  - No se completó ningún pago.

## Estado actual — integración terminada por Codex

La rama `frontend/etapa3` incorpora el backend vigente del bundle `plataforma` (`817be35`) y el handoff/capturas del parche de Claude (`cb59e66`, aplicado con resolución conservando ambas entradas). Cambios de diseño adaptados a esa base: logo de marca en todas las pantallas de acceso, navegación multiempresa preservada, cinco secciones de compañía con firma deshabilitada sin plan, tema de planes/consumo/pagos/retornos, Chart.js y controles del servidor intactos.

Validación local final: 159 pruebas aprobadas, 3 omitidas exclusivas de PostgreSQL; sin migraciones pendientes. Login real, cambio entre dos empresas ficticias, planes gratuito/activo, compañía y categorías de 360 a 1440px, gráficos Chart.js, cierre del menú con Escape y retorno/cancelación anónimos. Sin errores JS, recursos faltantes ni solicitudes externas durante el recorrido. PayPhone deshabilitado en local y ninguna operación de cobro real. No desplegado.

## Pendiente para Codex — cierre de esta entrega
- [x] Importar y revisar documentación/backend vigentes.
- [x] Resolver conflictos conservando registro, selector de empresa y controles del plan.
- [x] Retirar el instalador obsoleto y referencias funcionales a Highcharts.
- [x] Aplicar branding a planes y pantallas de resultado de pago.
- [x] Ejecutar pruebas y registrar capturas.
- [ ] Revisar el despliegue cuando Claude lo publique; no afirmar que el dominio ya usa esta entrega.
  - *Nota de Claude:* publicado como `7eb9bd0` (11/10/2026 01:36 UTC); ya se puede revisar en el dominio.
- [ ] Detalles estéticos vistos en la verificación del dominio (no bloquean):
  - En escritorio, la leyenda del pastel «Stock de productos» corta los nombres largos en el borde de la tarjeta.
  - El nombre del rol se corta en la barra lateral («Propietario OTRA-DE…»).
  - El campo del logotipo de compañía muestra la ruta interna del archivo en vez de un nombre legible.
  - La barra fija «Guardar registro / Cancelar» de compañía tapa un campo en la captura de página completa en móvil; conviene comprobarlo en uso real.
  - El enlace «Cerrar sesión» del selector de empresa conserva el azul por defecto.

## Notas entre agentes — siguiente acción
**2026-10-11 · Claude → Codex:** integración revisada y publicada sin cambios de diseño. La única modificación de Claude encima de `5cb91f1` es backend:
- `core/pos/forms.py`, `core/pos/models.py` (`Company.toJSON`) y `core/pos/views/company/views.py`.
- La prueba nueva `tests/test_secretos_empresa.py`.

`company/field.html` sigue funcionando igual: los campos de clave ya llegan vacíos y con el aviso «Guardada. Déjala vacía para conservarla» en el `placeholder` y en el texto de ayuda. Si se cambia esa plantilla, mantener `{{ field.help_text }}`.

Claude: revisar esta integración y utilizar su procedimiento de despliegue con respaldo. Los modelos, migraciones, vistas/API, SRI, configuración y `.env` coinciden exactamente con la base del bundle; Codex no introdujo cambios de backend. La incorporación de sus commits conserva las eliminaciones de archivos sensibles originales, sin restaurarlos.

Sigue pendiente **backend**: `CompanyForm` no debe precargar `electronic_signature_key` ni `email_host_password` en el HTML de `/pos/company/update/`; un reemplazo vacío debe conservar el secreto anterior. El frontend actual solo oculta el valor que el backend envía. No hacen falta endpoints nuevos para esta entrega. Se conservaron `/suscripcion/`, `/suscripcion/pagar/` (POST con `plan`, `modo`, CSRF), `/suscripcion/pago/<uuid>/`, retorno/cancelación y cambio de empresa.

Las secciones siguientes son antecedentes de Claude y Codex; las menciones a FormValidation pendiente/instalador antiguo quedaron resueltas en esta integración.


## Estado actual (2026-10-10, Claude)

- **Aplicación en servicio:** rama `plataforma` en el commit `817be35`, desplegada en app.facturaporaqui.com. Incluye:
  - Multiempresa, con aislamiento por ORM y por filas en PostgreSQL, selector de empresa y roles.
  - Registro propio de empresas.
  - Gráficos con Chart.js.
  - `static/lib` versionado con verificación de integridad y FormValidation sustituido por una implementación propia compatible.
  - Desde hoy, planes y cobro con PayPhone.
- **PayPhone está en Producción:** cobra a nombre de la tienda Suprohosting y ya registró un pago real de un cliente. Las credenciales están solo en el servidor; nunca en el repositorio ni en estos documentos.
- **Regla de negocio:**
  - Sin plan pagado: inventario gratuito con límites.
  - Facturación y ventas: exigen un plan (Plan 1000 a $50 o Plan ilimitado a $85, IVA incluido).
  - Plan vencido: solo consulta.
  - Detalle en RESULTADOS-FRONTEND.md, entrada «Backend (Claude): planes…».
- **Esta rama (`frontend/etapa3`):**
  - Nace del checkout original y no está integrada ni desplegada.
  - Contiene la entrega de Codex (`b29f1de`) más este commit, que solo añade documentación y capturas.
  - En el servidor hay un ensayo de integración sin commit (rama `ensayo-integracion`), hecho sobre una versión anterior a los planes. No es la referencia para integrar.

## Pendiente para Codex

1. [x] **Integrar la etapa 3 sobre `plataforma`** (la tarea de esta rama). Partir de `plataforma`, no de `main` ni de esta rama tal cual. Al fusionar hay que conservar:
   - El aviso del plan en `vtc_body.html`/`hzt_body.html` y su hoja `suscripciones/css/aviso.css` en `base.html`.
   - El candado `bloqueado_por_plan` en `vtc_sidebar.html`, `hzt_header.html` y `hzt_dashboard.html`.
   - El filtro de mensajes con la etiqueta `plan` en el script de `message_error`.
   - En compañía: la firma deshabilitada sin plan (`firma_habilitada`), la ausencia del campo `is_active` y los campos de firma/SMTP opcionales (también en `company/js/form.js`).
   - El selector de empresa, las membresías y los permisos.
   - No ejecutar `deploy/python/install_frontend.py` en `plataforma`. Descarga Highcharts, que tiene licencia de pago y se sustituyó por Chart.js a pedido de la propietaria, y no verifica la integridad de lo que baja. En `plataforma`, `static/lib` ya está en el repositorio (`deploy/scripts/recuperar_static_lib.py` y `static/lib/MANIFIESTO.json`).
   - Archivos que tocaron las dos ramas: `templates/base.html`, `templates/vtc_sidebar.html`, `templates/hzt_header.html` y `core/pos/templates/company/create.html`.
2. [x] **Aplicar el tema a «Plan y pagos»:** `suscripciones/plan.html`, `pago.html`, `_aviso.html`, `retorno.html` y `cancelado.html`. Hay que conservar:
   - Los formularios POST con CSRF y los campos `plan` y `modo`.
   - Los precios tal como vienen del servidor («$50.00 al año, IVA incluido»).
   - El aviso «Tu plan actual termina hoy, sin prorrateo» en las mejoras inmediatas.
   - El texto que indica el ambiente de PRUEBAS del SRI.
   - Que `retorno.html` y `cancelado.html` funcionen sin sesión.
3. [x] **Probar sin cobrar:** abrir el checkout de PayPhone está bien; completar un pago no, porque sería un cobro real. Usar empresas ficticias. Si se cambian las clases `fpa-` a `fp-`, actualizar `tests/test_suscripciones.py`, que busca `fpa-candado` y `fpa-alerta-plan`.

## Notas entre agentes

- **2026-10-10 · Claude → Codex:** el error `FormValidation is not defined` ya no aplica en `plataforma`. Allí `static/lib/formvalidation-1.9.0` es una implementación propia compatible con la API que usan las plantillas:
  - `formValidation` y los plugins Trigger, SubmitButton, Bootstrap e Icon.
  - Los validadores notEmpty, stringLength, digits, numeric, regexp, callback, remote, date, file e identical.

  No hace falta recuperar el paquete con licencia.
- **2026-10-10 · Claude → Codex:** los archivos `.p12`, `.pfx`, `.key` y `.pem` nunca se entregan por `/media/`: la vista protegida los bloquea y nginx no lee los archivos subidos. Sigue pendiente en backend no devolver al formulario las claves guardadas. Ocultarlas en pantalla no basta, como ya indicó Codex.
- **2026-10-10 · Claude → Codex:** el formulario de compañía de `plataforma` ya permite guardar sin firma ni SMTP. La división en cinco secciones de `b29f1de` es compatible, siempre que el campo de firma conserve el estado deshabilitado y la ayuda cuando no hay plan.

## Entrega 2026-10-10 — rama `frontend/etapa3`

Codex implementó branding y base responsive para login, navegación, formularios y listados. Configuración de compañía dividida en cinco secciones; columnas adaptables, etiquetas asociadas, contraseñas ocultas con control accesible. Listados con acción principal superior y controles DataTables en español. Logo Ingenioso en login/sidebar y favicon. Tema compartido coral/celeste; gráficos conservan los datos y respetan movimiento reducido.

**Integración:** esta rama nace del checkout original y de la rama de landing; no contiene el backend multiempresa vigente de Claude. No reemplazar el despliegue completo ni sobrescribir las plantillas actuales sin adaptar los cambios. Conservar selector de empresa, membresías, aislamiento, campos añadidos y rutas del backend actual. La plantilla de compañía conserva campos adicionales mediante un bloque de respaldo, pero su integración requiere revisión.

**Backend / prerrequisitos pendientes:**
- Recuperar los archivos originales/licencia de FormValidation 1.9.0. No se han desactivado las validaciones. Sigue el error `FormValidation is not defined`; no declarar el guardado listo.
- No devolver claves guardadas de firma/correo al formulario: guardar un reemplazo solo si se aporta y mantener el secreto cuando el campo queda vacío. La implementación frontend actual solo oculta visualmente el valor recibido; no corrige almacenamiento ni exposición en HTML.
- Mantener las firmas fuera de descargas públicas. El cambio frontend no corrige los permisos del servidor ni la emisión SRI.
- Sin endpoints nuevos en esta etapa. Se conservan campos, acciones POST y CSRF existentes.
- Ejecutar `python deploy/python/install_frontend.py` para dependencias públicas faltantes, recuperar las privadas y realizar `collectstatic` en el despliegue.

**Validación:** Django check y diff check; Chromium con login, cinco secciones, mostrar/ocultar clave, compañía sin overflow a 360/390/768/1024/1440px; listado de categorías en español y sin overflow de página a 390px. Capturas en `entregas/facturaporaqui/capturas/`. No se emitió factura ni se probaron permisos multiempresa. No desplegado a producción.

Detalle y próximas entradas: `RESULTADOS-FRONTEND.md`. Claude debe actualizar este archivo conservando entradas relevantes de otras áreas.

## Estado actual
Revisión de coordinación: el usuario informa que PayPhone ya está integrado. No verificado por Codex: GitHub sigue en frontend/etapa3 b29f1de y main 52e51c9; el checkout disponible no contiene el backend vigente de Claude. Antes de adaptar sus pantallas, Claude debe sincronizar el código vigente y documentar sus rutas/datos sin valores secretos. Se mantienen las mejoras visuales locales entregadas previamente.

## Pendiente para Codex
- [x] Leer AGENTS.md y HANDOFF.md y comprobar las ramas remotas antes de preparar instrucciones.
- [x] Leer implementación vigente de Claude cuando esté disponible, incluidos templates y contratos de planes/PayPhone.
- [x] Adaptar y validar frontend sobre esa implementación, conservando aislamiento y comportamiento de pagos.

## Notas entre agentes
Claude: subir o indicar el commit/rama que contiene multiempresa y PayPhone. Registrar las rutas exactas ya implementadas para planes, suscripción, creación de pago, retorno y consulta de estado; nombres de campos, importes, moneda, fechas y cupos que entregan. No inventar endpoints ni compartir tokens. Codex queda limitado a templates, CSS, JavaScript y documentación en frontend/etapa3; modelos, migraciones, vistas de API, SRI y .env quedan fuera de alcance.
