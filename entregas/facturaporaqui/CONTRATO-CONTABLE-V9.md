# Contrato contable v9: rutas, datos y bloqueos por entrega (Claude → Codex)

04/11/2026. Base: la propuesta navegable `referencias/frontend-v9/entregas/facturaporaqui/propuestas/ux-v9/` (seis pantallas,
datos simulados) y su lista de datos pendientes `CONTRATO-FRONTEND-PENDIENTE.md`. Este documento sustituye esa lista como
contrato: fija qué se conecta hoy con rutas existentes, la forma exacta de las rutas nuevas y, por entrega, **solo** el dato o
la decisión que la bloquea. Las maquetas no entran al menú como funciones disponibles hasta que exista su ruta.

**Actualizado el 14/11/2026 (bloque 1 de `ORDEN-CIERRE-CONTABLE-TRIBUTARIO.md`).** El contrato de capacidades, C1, C2 y C3
están construidos en la rama `fase/contable-1-cuentas`, sin publicar. Esas cuatro secciones describen el código tal como
quedó y sus ejemplos son respuestas reales de las pruebas, con datos ficticios. C4 a C7 siguen como propuesta. Cada
sección construida termina con lo que cambió respecto de la propuesta del 04/11.

**Corregido el 14/11/2026 tras la revisión independiente del bloque 1.** Lo que cambia para quien conecte las pantallas:
un PATCH va siempre en JSON; con sesión y sin empresa activa la respuesta no es JSON (la segunda excepción de las reglas
comunes); con el plan vencido tampoco guarda un formulario que lleve `action`; y la subida del plan rechaza tres archivos
más, cada uno con su texto: el CSV con las comillas mal cerradas, el XLSX que declara entidades XML y la tabla con
demasiado texto.

**Corregido otra vez el 14/11/2026** (revisión de las correcciones, ensayo de migración y recorrido en navegador). Para
quien conecte las pantallas: un envío sin token CSRF válido es la tercera excepción de las reglas comunes (403 en HTML de
Django); un JSON que no se puede leer y que traía dentro la empresa recibe 409 `sin_empresa`, no 400 `cuerpo`; en C3, un
logo SVG dentro del XLSX ya no impide subirlo y un XLSX con una parte comprimida en bzip2 o lzma se rechaza (400
`formato`), y la lista de cambios dice ya que un lote de otra empresa es 404 `lote`. No hay códigos nuevos: salvo lo del
XLSX, el código ya respondía así y ahora el contrato lo dice.

**Actualizado el 14/11/2026 (corte 1 del bloque 2: libro diario mínimo, inicio contable y apertura hasta confirmar).**
Rama `fase/contable-2-apertura`, código final del corte `a5bedf4`, sin publicar; el 15/11/2026 se le unió el bloque 1
final (`fase/contable-1-cuentas`, `8a421b3`), con las dos correcciones de arriba, así que C3 vale aquí tal como lo
describen (también la importación de los saldos de la apertura, que lee con el mismo lector, `lectura_tabular.py`). Las rutas de la apertura y del diario y sus ejemplos
reales están en `CONTRATO-APERTURA-CONTABLE.md` (C6-A, sección 6). Aquí cambia lo que ya existía: las reglas comunes
(`empresa` en la consulta, `url` y `recurso`), «Capacidades» (funciones nuevas, el campo `avisos` y el primer requisito
real), C1 (la etapa de la apertura), C2 (clase y auxiliar de cada cuenta, reclasificar y la ruta para clasificar por lote)
y C3 (la columna «clase»). Todo es aditivo: ninguna clave que ya existía cambió de forma ni de sentido.

**Cierre del corte 1 del bloque 2 (15/11/2026).** Sobre `6efad50` (la rama unida con el bloque 1 final) se hicieron la
revisión independiente (libro, apertura, y contrato con documentos), el ensayo de migraciones con la versión publicada
atendiendo, el recorrido en navegador y una integración de prueba con `fase/primera-entrega`; de los 25 puntos que se
confirmaron, los de código se corrigieron y los demás se documentaron. Código final de la rama: **`72a68ee`**, sin
publicar (detalle en HANDOFF.md, «Cierre del corte 1»). Para quien conecte las pantallas, aquí cambian dos cosas:

1. Un código nuevo, 409 `reintentar`, fuera del orden de las negativas y en cualquier ruta nueva de `/contabilidad/api/`
   (abajo, «Orden de las negativas»).
2. En C2, cambiar con un PATCH el `auxiliar` de una cuenta que está en una apertura en preparación cambia lo que esa
   apertura exige al validar y al confirmar: mientras se prepara, vale el auxiliar que la cuenta declara ahora (C6-A
   §6.5, regla 4). Si el PATCH llega mientras se confirma la apertura, espera a que termine: toma el mismo candado del
   libro (ya lo hacía; lo vigila una prueba nueva en PostgreSQL).

En C3, la confirmación de una importación ya no se cruza con el libro: bloquea las cuentas con `FOR NO KEY UPDATE`, y
editar una cuenta (C2) también. Para la interfaz no cambia nada, salvo que, si la base llega a abortar por un cruce, la
respuesta es el 409 `reintentar` y no un 500. El resto de cambios del cierre es de la apertura: están en C6-A (cabecera
y sección 6).

## Reglas comunes

Valen para todo lo que cuelga de `/tributario/` y `/contabilidad/`:

- El Complemento Contable sigue **cerrado** salvo las empresas de `FPA_COMPLEMENTO_CONTABLE_REVISION`, que además necesitan
  plan pagado (páginas → `/dashboard/` con aviso; API, descargas y envíos → 403 `{"codigo": "complemento_pendiente"}`). D9:
  precios decididos ($150 al año por módulo para una empresa y $250 para multiempresa); impuestos, alcance multiempresa y
  condiciones de activación pendientes. No se abre por esta nota, y el bloque 1 no cambió quién entra.
- Empresa activa y permisos en el servidor. `empresa=<id>` en consultas y envíos: si no es la activa, 409
  `{"error": …, "codigo": "empresa_cambiada"}` sin leer ni escribir nada de la otra.
- Importes como texto con dos decimales (`"115.00"`); desconocido = `null`, nunca `0`. Fechas `AAAA-MM-DD`; meses `AAAA-MM`.
- Envíos con `clave` (idempotencia): repetir la misma clave devuelve el mismo resultado con `repetido: true`.
- Concurrencia: los recursos editables traen `version`; si cambió, 409 `{"codigo": "version"}` y la interfaz ofrece recargar.
- Errores: `{"error": texto general, "errores": {campo: [textos]}}` (400); por fila en importaciones.

### Rutas nuevas de `/contabilidad/api/` (capacidades, inicio, cuentas e importación)

Las rutas que ya existían (kardex, inventario y todo `/tributario/`) no cambiaron: allí un GET sin permiso sigue
redirigiendo (302). Las nuevas cumplen además esto:

- **Toda negativa de la ruta es JSON, también en GET.** Hay tres excepciones, las de todo el proyecto, que responden
  antes de llegar a la ruta:

  1. Sin sesión: 302 a `/login/?next=…`.
  2. Con sesión y sin empresa activa: responde `CompanyMiddleware`. Un GET recibe 302 a `/empresas/` (el selector de
     empresas, HTML); un POST o un PATCH, 403 `{"error": "Selecciona una empresa para continuar"}`, sin `codigo` ni
     `causa`. Le pasa a quien tiene varias empresas y todavía no eligió ninguna, a quien le desactivaron la membresía de
     la empresa que tenía abierta y al superusuario que no eligió empresa. (Si a quien perdió la membresía le queda
     exactamente otra empresa, la sesión pasa sola a esa: la pestaña armada para la anterior recibe el 409
     `empresa_cambiada` de siempre.)
  3. Un envío (POST o PATCH) sin token CSRF válido: Django lo corta con su 403 en HTML («403 Forbidden», sin `codigo`).
     Los envíos llevan la cabecera `X-CSRFToken` con el valor de la cookie `csrftoken`, como el resto del proyecto
     (`static/js/functions.js` ya la pone). Conviene leer la cookie al enviar y no al cargar la página: iniciar sesión
     en otra pestaña la cambia. Las consultas (GET) no la necesitan.

  Para la interfaz: una respuesta redirigida o que no es JSON, y un 403 sin `codigo`, no son de la ruta. Se tratan como
  «vuelve a cargar la página»: al recargar, el proyecto lleva al inicio de sesión o al selector de empresas, o renueva el
  token.
- **Orden de las negativas.** Se responde la primera que aplique:

  | # | Causa | Respuesta |
  |---|---|---|
  | 1 | La consulta o el envío se armó para otra empresa | 409 `empresa_cambiada` |
  | 2 | Licencia: complemento cerrado, sin plan pagado o, en un envío, plan vencido | 403 `complemento_pendiente` o `plan`, con `causa: "licencia"` |
  | 3 | El envío no dice para qué empresa se preparó (tampoco cuando la trae dentro de un JSON que no se puede leer) | 409 `sin_empresa` |
  | 4 | El rol no tiene el permiso | 403 `sin_permiso`, con `causa: "permiso"` |
  | 5 | Faltan datos por completar | 409 `datos_por_completar`, con `causa: "datos"` |
  | 6 | Validación | 400 `clave`, `cuerpo`, `validacion` o el código propio de la ruta |

  Una excepción al primer puesto, que ya existía en `PlanMiddleware` para todas las consultas: si la empresa activa no
  tiene plan pagado, a un GET de una pestaña armada para otra empresa le responde el 403 `plan` y no el 409.

  **Fuera del orden: 409 `reintentar`** (desde el cierre del corte 1 del bloque 2, `72a68ee`). En cualquier ruta nueva
  de `/contabilidad/api/` (capacidades, inicio, cuentas, importación del plan, diario y apertura: todas las que usan
  `ApiContable`), si PostgreSQL aborta la transacción por un interbloqueo (SQLSTATE `40P01`) o porque un bloqueo no se
  consiguió a tiempo (`55P03`: `lock_timeout` o `NOWAIT`), la respuesta es exactamente

  ```
  409 {"error": "Otra operación usaba los mismos datos al mismo tiempo: no se guardó nada. Vuelve a intentarlo.", "codigo": "reintentar"}
  ```

  sin más campos. No tiene puesto en la tabla porque lo decide la base, en el momento en que corta. No se guardó nada
  (la transacción se deshizo entera) y repetir el mismo envío, con la misma `clave` y la misma `version`, es seguro: la
  interfaz muestra `error` y ofrece repetirlo tal cual, sin recargar. Queda un aviso (WARNING, con la traza) en el
  registro `core.contabilidad.api`. Cualquier otro error de la base sigue siendo un 500; antes, un interbloqueo también
  lo era. Es 409 y no 503 porque encaja con los 409 de conflicto, la interfaz ya muestra el `error` de cualquier 409 JSON
  y no cuenta como 5xx en las verificaciones. Lo prueba `tests/test_cuentas_importacion.py::TestCruceDeBloqueos`, con
  los errores reales de psycopg; que la importación del plan ya no se cruza con el libro lo prueba, con conexiones
  reales, `tests/test_zz_diario_concurrencia_pg.py`.

- **`empresa`.** Va en la consulta (`?empresa=<id>`) o en el envío: `"empresa"` del objeto JSON o, en un POST de
  formulario, el campo `empresa`; como número o como texto. En GET es opcional. En POST y PATCH es obligatoria. Basta que
  la consulta o el cuerpo nombren otra empresa para el 409.
- **Cuerpo.** JSON (`Content-Type: application/json`, un objeto). Un POST admite también un formulario, y la subida de
  un archivo va en `multipart` por fuerza. **Un PATCH va siempre en JSON:** el servidor no lee un cuerpo de formulario
  en PATCH (Django solo lo hace en POST), y `activa` (booleano) y `padre_id: null` no se pueden escribir en un
  formulario. Un PATCH de formulario no cambia nada y llega vacío: recibe 409 `sin_empresa` aunque traiga `empresa` en
  el cuerpo, o 400 `validacion` por `version` si la empresa va en la consulta. Un JSON que no se puede leer o que no es
  un objeto: 400 `cuerpo` si la empresa va en la consulta (`?empresa=`); si iba dentro de ese JSON, el servidor no la
  puede leer y responde antes el 409 `sin_empresa` (puesto 3 del orden).
- **`clave`.** De 8 a 40 caracteres: letras, cifras, guion y guion bajo. La genera el navegador una vez por formulario.
  Misma clave y mismo contenido: el mismo resultado con 200 y `"repetido": true`. Misma clave y otro contenido: 409
  `clave_usada`. Sin clave o mal formada: 400 `clave`.
- **`version`.** Entero que empieza en 1 y sube en cada cambio, también al activar, desactivar o actualizar por
  importación. El envío manda la que leyó. Si ya no es la vigente: 409 `version` con el recurso como está ahora.
- **Validación (400).** `{"error": "Revisa los datos marcados.", "codigo": "validacion", "errores": {campo: [textos]}}`,
  con todos los errores de campo a la vez.
- **Plan vencido.** Se consulta (GET) y no se guarda nada: POST y PATCH responden 403 `plan`, llegue como llegue el
  envío. `PlanMiddleware` deja pasar un formulario que lleve un campo `action` de consulta (`search…` o
  `send_invoice_by_email`), porque así buscan por POST las pantallas de ventas; las rutas nuevas repiten la
  comprobación en cada envío y responden el mismo 403, con el mismo cuerpo. Solo cambia el orden en un caso que ninguna
  pantalla produce: ese formulario, si además no trae `empresa`, recibe el 409 `sin_empresa`. Tampoco guarda nada.
- **Método que la ruta no admite.** 405 `{"codigo": "metodo"}` con la cabecera `Allow`.

Reglas que añade el bloque 2 (libro diario y apertura, corte 1) y que valen para toda ruta nueva desde ahí:

- **`empresa` va siempre en la consulta (`?empresa=<id>`), también cuando el envío es JSON.** Es lo único que mira
  `PlanMiddleware` antes de la vista. El cuerpo puede repetirla; si una de las dos no es la activa, 409
  `empresa_cambiada`. Las rutas de C2 y C3 la siguen aceptando solo en el cuerpo, como hasta ahora, pero la interfaz la
  manda en los dos sitios.
- **Orden ampliado de las negativas** de una ruta que escribe: los seis puestos de arriba y, entre los datos por completar
  y la validación, `clave` repetida (200 `repetido` o 409 `clave_usada`) → `version` (409) → estado del recurso (409
  `estado`, con `estado` y `permitidos`) → conflicto con otros datos (409 con su código: `rango_solapado`,
  `periodo_cerrado`…). La clave va antes que la versión: el reintento de un envío ya aplicado trae la versión vieja y
  recibe el mismo resultado. Fuera de ese orden, el 409 `reintentar` de arriba.
- **Inexistente o de otra empresa:** 404 `{"codigo": "no_existe"}` en las rutas del bloque 2. Las del bloque 1 conservan
  sus códigos (`cuenta`, `lote`), también `cuentas/clasificar/`.
- **Errores en listas:** la clave lleva la posición enviada, base 0: `"lineas.2.debe"`. En archivos, por `fila` (la de
  encabezados es la 1), como C3.
- **Enlaces (`url` y `recurso`).** `url` lleva solo una página que ya existe. Un recurso sin página (un respaldo, un lote de
  importación, una apertura, un expediente) va con `"url": null` y `"recurso": {"tipo", "id", "api"}`, con su ruta de API.
  El servidor no inventa rutas de página: cuando Codex conecte la pantalla, se añade su `url`.
- **Reportes y coberturas:** `provisional` (booleano), `causas` (textos, la forma de C6) y `causas_detalle`
  (`[{"codigo", "texto", "cantidad"?}]`) con códigos estables. Las causas salen de un solo registro
  (`core/contabilidad/reportes.py`): ver C6.
- **Instantes** en ISO 8601 con zona (UTC, `+00:00`), como los cobros. **Autores**: el nombre de usuario guardado con la
  fila al escribirla; si el usuario se borra, se conserva.
- **Paginación:** `?pagina=1&por_pagina=100` (máximo 500) → `"paginacion": {"pagina", "por_pagina", "total", "paginas"}`.
- **`capacidades` de un recurso:** booleanos que ya combinan permiso, estado y licencia (con el plan vencido, `false`).

Negativas comunes, tal como salen:

```
409 {"error": "La empresa activa cambió en otra pestaña: vuelve a cargar la página para ver los datos de la empresa que tienes abierta ahora.",
     "codigo": "empresa_cambiada"}
409 {"error": "El envío no indica para qué empresa se preparó: vuelve a cargar la página e inténtalo de nuevo.", "codigo": "sin_empresa"}
403 {"error": "Tu perfil no cuenta con el permiso necesario.", "codigo": "sin_permiso", "causa": "permiso", "permisos": ["add_cuenta"]}
400 {"error": "Falta la clave del envío: vuelve a cargar la página e inténtalo de nuevo.", "codigo": "clave",
     "errores": {"clave": ["Falta la clave del envío: vuelve a cargar la página e inténtalo de nuevo."]}}
400 {"error": "El envío no se pudo leer: debe ser un objeto JSON.", "codigo": "cuerpo"}
405 {"error": "Esta ruta no admite ese método.", "codigo": "metodo"}
```

`permisos` lista los permisos que lo habrían permitido (basta uno). Los 403 de licencia están en la sección siguiente.

## Capacidades (licencia, permiso, módulo pendiente y datos por completar)

Sustituye el aviso único «todavía no está disponible» por una explicación con cuatro causas. **No cambia quién entra:** la
puerta sigue siendo `PlanMiddleware` (lista de revisión más plan pagado) y `MENSAJE_COMPLEMENTO` sigue en su sitio. Lo
calcula un solo módulo, `core/contabilidad/capacidades.py`, con las mismas funciones y en el mismo orden que el middleware.

| Causa | Qué significa | Qué puede hacer el usuario |
|---|---|---|
| `licencia` | La empresa no tiene el complemento habilitado, no tiene plan pagado o lo tiene vencido | Lo que diga `licencia`: contratar o renovar el plan. El complemento todavía no se contrata en ningún sitio |
| `permiso` | Su rol en la empresa activa no incluye la función | Pedirla a quien administra los roles |
| `modulo_pendiente` | La función todavía no está construida | Nada: `texto` dice qué falta y, si la hay, qué decisión espera |
| `datos` | Está construida y permitida, pero antes hay que completar algo | Lo que liste `faltan`, cada cosa con su `url` |

### `GET /contabilidad/api/capacidades/?empresa=<id>`

La consulta cualquier rol de personal de la empresa, también Vendedor. El rol Cliente recibe 403 `sin_permiso` con
`permisos: []`. Es la única ruta de `/tributario/` y `/contabilidad/` que responde con el complemento cerrado, sin plan o
con el plan vencido, porque está para explicar el bloqueo. No devuelve ningún dato contable y no abre ninguna otra ruta.

```
200 {"empresa": {"id": 1, "ruc": "0900000001001", "nombre": "DEMOSTRACION S.A."},
     "licencia": {"estado": "activa", "solo_consulta": false, "texto": null, "puede_gestionar": true, "url": null},
     "funciones": {
       "kardex": {"nombre": "Kardex por producto", "ambito": "contabilidad", "estado": "disponible", "causa": null, "texto": null,
                  "acciones": {"ver": true, "registrar": true, "anular": true}, "faltan": []},
       "plan_cuentas": {"nombre": "Plan de cuentas", "ambito": "contabilidad", "estado": "disponible", "causa": null, "texto": null,
                        "acciones": {"ver": true, "crear": true, "editar": true}, "faltan": []},
       "asientos": {"nombre": "Asientos por comprobante", "ambito": "contabilidad", "estado": "modulo_pendiente",
                    "causa": "modulo_pendiente",
                    "texto": "Los asientos por comprobante están en construcción. La matriz de asientos está por validar con un contador: una regla sin aprobar quedará como excepción, sin contabilizar.",
                    "acciones": {"ver": false}, "faltan": []},
       …}}
```

**`licencia`**

| `estado` | Cuándo | `solo_consulta` | `texto` | `url` |
|---|---|---|---|---|
| `activa` | En la lista de revisión y con plan vigente | `false` | `null` | `null` |
| `complemento_pendiente` | Fuera de la lista de revisión, tenga plan o no | `false` | el aviso del complemento | `null` |
| `plan_requerido` | En la lista y sin plan pagado | `false` | el aviso del plan | `/suscripcion/` si `puede_gestionar` |
| `plan_vencido` | En la lista y con el plan vencido | `true` | «Tu Plan ilimitado venció el 13/11/2026. …» | `/suscripcion/` si `puede_gestionar` |

`puede_gestionar` dice si este usuario puede abrir `/suscripcion/` (Propietario y Administrador). `texto` es el mismo
`error` del 403 correspondiente.

**`funciones`**: un objeto con todas las funciones, siempre en este orden: `libros`, `revision`, `ats`, `formularios`,
`kardex`, `inventario`, `plan_cuentas`, `importar_cuentas`, `inicio`, `evidencias`, `apertura`, `cartera_inicial`,
`historico`, `asientos`, `diario_mayor`, `bancos`, `cierre`, `estados_financieros`, `formulario_101`. Cada una trae
`nombre`, `ambito` (`tributario` o `contabilidad`), `estado`, `causa`, `texto`, `acciones`, `faltan` y `avisos` (este
último desde el bloque 2; en el ejemplo de arriba, del bloque 1, todavía no aparece).

| `estado` | `causa` | `texto` | `acciones` |
|---|---|---|---|
| `modulo_pendiente` | `modulo_pendiente` | qué falta y, si la hay, la decisión que espera | todas `false` |
| `sin_licencia` | `licencia` | el de `licencia.texto` | todas `false` |
| `sin_permiso` | `permiso` | «Tu perfil no cuenta con el permiso necesario.» | todas `false` |
| `datos_por_completar` | `datos` | «Faltan datos por completar antes de usar esta función.» | todas `false`; `faltan` dice qué |
| `disponible` | `null` | `null` | las que el rol tiene; con el plan vencido, solo `ver` |

La precedencia, por función, es el orden de la tabla. Lo que no está construido nunca se anuncia como «te falta la
licencia» ni «te falta el permiso». `acciones` trae siempre todas sus claves. `faltan` es una lista de
`{"codigo", "texto", "url"}` y solo tiene contenido en `datos_por_completar`.

| Función | Acciones y su permiso | Construcción |
|---|---|---|
| `libros`, `ats`, `formularios` | `ver`: `view_libros` | disponible |
| `revision` | `ver`: `view_revision` | disponible |
| `kardex` | `ver`: `view_kardex`; `registrar`: `add_movimientomanual`; `anular`: `change_movimientomanual` | disponible |
| `inventario` | `ver`: `view_kardex` | disponible |
| `plan_cuentas` | `ver`: `view_cuenta`; `crear`: `add_cuenta`; `editar`: `change_cuenta` (incluye activar y desactivar) | disponible (C2) |
| `importar_cuentas` | `ver` e `importar`: `add_cuenta`; `actualizar_nombre`: `change_cuenta` | disponible (C3) |
| `inicio` | `ver`: `view_kardex`, `view_revision` o `view_cuenta` | disponible (C1) |
| `apertura` | `ver`: `view_apertura`; `preparar`: `add_apertura` (configurar, crear, editar, importar, mapear, respaldos, validar, enviar y descartar); `confirmar`: `change_confirmacion_apertura` (también devolver a borrador) | disponible (C6-A, bloque 2) |
| `diario_mayor` | `ver`: `view_asiento` (el diario y su integridad; el bloque 3 añade `exportar`) | disponible (bloque 2) |
| `evidencias`, `cartera_inicial`, `historico`, `asientos`, `bancos`, `cierre`, `estados_financieros`, `formulario_101` | `ver`, siempre `false` | pendiente |

Textos de las pendientes: `evidencias`, `cartera_inicial` (cobros, pagos y descargos sobre los saldos iniciales) e
`historico` (destino de los documentos importados anteriores al corte) dicen solo que están en construcción; las dos
últimas son del corte 2 del bloque 2. Las demás añaden la decisión que espera su regla o su activación: `asientos`, la
matriz por validar con un contador; `bancos`, las muestras de extractos; `cierre`, qué impide un mes cerrado y quién lo
cierra o lo reabre; `estados_financieros`, la correspondencia con el catálogo de la Superintendencia de Compañías;
`formulario_101`, la numeración de casilleros y la fórmula de la conciliación tributaria.

**Datos por completar.** El primer requisito real es el de `apertura`: sin ninguna cuenta de movimiento activa no hay
dónde llevar un saldo. La función queda `datos_por_completar` y crear la apertura responde:

```
409 {"error": "Faltan datos por completar antes de usar esta función.", "codigo": "datos_por_completar", "causa": "datos",
     "faltan": [{"codigo": "plan_cuentas_vacio", "texto": "Crea o importa el plan de cuentas: no tiene ninguna cuenta de movimiento activa.",
                 "url": null}]}
```

`url` es `null` porque el plan de cuentas todavía no tiene página.

**Avisos** (desde el bloque 2). Lo pendiente que **no** impide usar la función va en `avisos`, no en `faltan`:
`[{"codigo", "texto", "cantidad", "url", "recurso", "decision"}]`, con la regla de `url` y `recurso` de las reglas comunes.
Se calculan solo para quien puede usar la función (con `estado: disponible`); para los demás la lista va vacía. `decision`
solo aparece en lo que depende de una decisión de plataforma; lo que la empresa no ha configurado todavía (cuentas sin
clase) es un aviso sin `decision`. Avisos de `apertura`, todos sin `decision`:

| `codigo` | Cuándo | `cantidad` | `recurso` |
|---|---|---|---|
| `cuentas_sin_clase` | hay cuentas de movimiento activas sin clase | cuántas | `{"tipo": "plan_cuentas", "id": null, "api": "/contabilidad/api/cuentas/"}` |
| `cuentas_sin_auxiliar` | algún ámbito de detalle (clientes, proveedores, inventario, bancos, activos, tributario) no tiene ninguna cuenta que lo declare ni declaración de que no aplica | cuántos ámbitos | el del plan de cuentas |
| `auxiliares_incompletos` | líneas de la apertura de trabajo con detalle cuyo saldo no está explicado del todo | cuántas | `{"tipo": "apertura", "id", "api": "/contabilidad/api/apertura/<id>/lineas/"}` |
| `vinculos_rotos` | auxiliares vinculados a un documento que ya no existe (hoy no los crea nada: los vínculos son del corte 2) | cuántos | la apertura |

```
"apertura": {"nombre": "Apertura contable", "ambito": "contabilidad", "estado": "disponible", "causa": null, "texto": null,
             "acciones": {"ver": true, "preparar": true, "confirmar": true}, "faltan": [],
             "avisos": [{"codigo": "cuentas_sin_clase",
                         "texto": "1 cuenta(s) de movimiento no tienen clase (activo, pasivo, patrimonio, ingreso, costo o gasto): decláralas antes de confirmar la apertura.",
                         "cantidad": 1, "url": null,
                         "recurso": {"tipo": "plan_cuentas", "id": null, "api": "/contabilidad/api/cuentas/"}, "decision": null}]}
```

### Los 403 de licencia

Los responde `PlanMiddleware` antes de llegar a la vista, en las rutas nuevas y en las que ya existían. Conservan `error`,
`plan` y `codigo`; el bloque 1 añadió `causa` y `licencia` (el mismo objeto de arriba). El del plan vencido lo repiten
además las rutas nuevas en sus envíos, idéntico (ver «Plan vencido» en las reglas comunes).

```
403 {"error": "El Complemento Contable (libros, revisión del mes, ATS, borradores del 104 y del 103, kardex e inventario valorizado) todavía no está disponible: su precio y sus condiciones están por anunciar.",
     "plan": "complemento_contable", "codigo": "complemento_pendiente", "causa": "licencia",
     "licencia": {"estado": "complemento_pendiente", "solo_consulta": false, "texto": "El Complemento Contable (…) por anunciar.",
                  "puede_gestionar": true, "url": null}}

403 {"error": "La facturación y las ventas se activan con un plan anual. Mientras tanto puedes usar el inventario con el plan gratuito.",
     "plan": "requerido", "codigo": "plan", "causa": "licencia",
     "licencia": {"estado": "plan_requerido", "solo_consulta": false, "texto": "La facturación y las ventas se activan con un plan anual. …",
                  "puede_gestionar": true, "url": "/suscripcion/"}}

403 {"error": "Tu Plan ilimitado venció el 13/11/2026. Puedes consultar tus comprobantes; renueva el plan para volver a emitir.",
     "plan": "requerido", "codigo": "plan", "causa": "licencia",
     "licencia": {"estado": "plan_vencido", "solo_consulta": true, "texto": "Tu Plan ilimitado venció el 13/11/2026. …",
                  "puede_gestionar": true, "url": "/suscripcion/"}}
```

El primero es el de una empresa fuera de la lista de revisión; el segundo, sin plan pagado; el tercero, el de un envío
con el plan vencido. Las páginas siguen redirigiendo como antes (`/dashboard/` o `/suscripcion/`).

Fuera del complemento (ventas, importación, proformas, cobros) el 403 del plan añade `"codigo": "plan"` y
`"causa": "licencia"`, sin `licencia`: ese objeto describe el Complemento Contable y no tiene que ver con esos rechazos.

### Cómo usarlo en la interfaz

- Para mostrar, ocultar o desactivar una acción: `funciones[codigo].acciones[accion]`.
- Para explicar por qué no se puede: `estado`, `causa` y `texto` de esa función. Con `causa: "licencia"`, `licencia.url`
  lleva a donde se resuelve, si este usuario puede.
- Con `licencia.solo_consulta` se puede leer y no se puede guardar: las acciones que guardan ya vienen en `false`.
- Ante un 403 o un 409 de una ruta nueva, `codigo` y `causa` dicen cuál de las cuatro es; `error` es el texto para la
  persona. Un 403 sin `codigo`, o una respuesta que no es JSON, no viene de la ruta: es una de las tres excepciones de las
  reglas comunes (sin sesión, sin empresa activa o un envío sin token CSRF válido) y se resuelve recargando la página.

### Cambios respecto de lo que había

- Los 403 de licencia llevan `causa` y, en `/tributario/` y `/contabilidad/`, `licencia`. El 403 del plan lleva además
  `codigo: "plan"`, que antes no tenía código. No se quitó ninguna clave.
- `empresa` se lee también de un cuerpo JSON en cualquier ruta del proyecto (`core/tenancy/pestanas.py`): un envío JSON
  armado para otra empresa recibe el 409 antes que el 403 de licencia o de permiso. Ninguna pantalla actual manda
  `empresa` en un cuerpo JSON, así que hoy no cambia nada en las rutas que ya existían.
- Un envío sin `empresa` con la licencia cerrada recibe el 403 de licencia y no `sin_empresa`: el middleware no sabe qué
  rutas la exigen.
- Bloque 2 (aditivo): cada función trae `avisos`; hay dos funciones nuevas (`cartera_inicial` e `historico`, pendientes);
  `apertura` y `diario_mayor` pasan a disponibles y `apertura` tiene el primer requisito real (`plan_cuentas_vacio`).
  Por la misma razón que arriba, un envío JSON armado para otra empresa que la lleva solo en el cuerpo recibe el 409 también
  con el complemento cerrado o el plan vencido (la especificación del bloque 2 esperaba ahí el 403 de licencia).

## Mapa de pantallas

| Pantalla v9 | Se conecta hoy | Entrega de backend | Bloqueo real |
|---|---|---|---|
| Inicio contable | `GET /contabilidad/api/inicio/` | C1, construido | ninguno |
| Plan de cuentas | `/contabilidad/api/cuentas/` | C2, construido | ninguno (D5 solo para ofrecer una plantilla predefinida) |
| Importación del plan | `/contabilidad/api/cuentas/importar/` | C3, construido | ninguno para la función; el piloto, ver abajo |
| Apertura contable (inicio por saldos o por historial) | `/contabilidad/api/apertura/` y sus rutas | C6-A, corte 1 construido (hasta confirmar); auxiliares, cartera inicial, ajustes, sustitución e históricos en el corte 2 | ninguno para la función; los saldos reales y su revisión, del contador de cada empresa |
| Diario e integridad del libro | `/contabilidad/api/diario/`, `/contabilidad/api/integridad/` | bloque 2, construido (solo lectura) | ninguno; los asientos de la operación diaria esperan el motor (bloque 3), y mientras tanto todo rango posterior al corte sale provisional |
| Asientos por comprobante | — | C4 | **D7** (matriz de asientos validada) y el plan de cuentas de cada empresa (C2/C3) |
| Revisión del mes | revisión, libros y ATS existentes | C5 evidencias de presentación | cierre/reapertura: **decisión** de qué bloquea un mes cerrado; saldos anteriores: apertura (C6) |
| Reportes | libros, borradores 104/103, kardex e inventario | C6 apertura y mayor | estados financieros: **D5**, **D7** y saldos de apertura validados |
| Puntos de emisión | `/configuracion/puntos/` (establecimientos, puntos, autorizados, selección) | C7 cupo y verificación | ninguno si se confirma la definición de «verificado» propuesta abajo |
| Piloto NEXALLTI | — | usa C2/C3 | **dato:** su Excel real; **decisión:** incluir su RUC en la lista de revisión del complemento |

Las tres primeras se pueden conectar cuando el bloque 1 esté publicado; la apertura y el diario, cuando se publique el
bloque 2. Sus rutas siguen detrás del complemento: solo responden a las empresas de la lista de revisión con plan pagado.

## C1 — Inicio contable (construido)

`GET /contabilidad/api/inicio/?empresa=<id>` — `view_kardex`, `view_revision` o `view_cuenta`, basta uno: Propietario,
Administrador, Contador y Consulta. Solo GET. Con el plan vencido se sigue consultando.

```
200 {"empresa": {"id": 1, "ruc": "0900000001001", "nombre": "DEMOSTRACION S.A."},
     "capacidades": {"revision": true, "libros": true, "kardex": true, "plan_cuentas": {"ver": true, "editar": true}},
     "acceso": {"empresa": {…}, "licencia": {…}, "funciones": {…}},
     "etapas": {"plan_cuentas": {"estado": "importado", "cuentas": 8, "importado_en": "2026-11-14", "causa": null},
                "apertura": {"estado": "no_disponible", "fecha": null,
                             "causa": "La apertura contable (por saldos de apertura o por historial detallado) está en construcción."},
                "conciliacion": {"estado": "no_disponible",
                                 "causa": "Bancos y conciliación están en construcción. Los formatos de extracto de cada banco esperan muestras reales; un CSV con columnas a elegir no depende de ellas."}},
     "pendientes": [{"origen": "revision", "codigo": "devueltos", "titulo": "Comprobantes devueltos o sin autorizar", "cantidad": 1,
                     "url": "/tributario/revision/?mes=2026-11#fp-rev-devueltos"},
                    {"origen": "revision", "codigo": "datos_ats", "titulo": "Datos del ATS incompletos", "cantidad": 2,
                     "url": "/tributario/revision/?mes=2026-11#fp-rev-datos_ats"},
                    {"origen": "revision", "codigo": "respaldos", "titulo": "Respaldos pendientes", "cantidad": 1,
                     "url": "/tributario/revision/?mes=2026-11#fp-rev-respaldos"},
                    {"origen": "capturas", "codigo": "recibo_por_completar", "titulo": "Recibos por completar", "cantidad": 1,
                     "url": "/adjuntos/capturas/"},
                    {"origen": "importacion", "codigo": "documento_por_revisar",
                     "titulo": "Documentos importados pendientes de revisión", "cantidad": 2, "url": "/importacion/pendientes/"}],
     "origenes": ["revision", "capturas", "importacion"]}
```

- **`capacidades`**: la forma corta de la propuesta, cuatro datos en booleanos. Sale de `acceso`, así que nunca dicen cosas
  distintas. `plan_cuentas.editar` es falso para Consulta y, con el plan vencido, para todos.
- **`acceso`**: el objeto completo de `GET /contabilidad/api/capacidades/`, con su explicación por función.
  `acceso.empresa` es igual a `empresa`.
- **`etapas.plan_cuentas`**:

  | `estado` | Cuándo | `cuentas` | `importado_en` |
  |---|---|---|---|
  | `sin_configurar` | La empresa no tiene ninguna cuenta | `null` | `null` |
  | `configurado` | Tiene cuentas y ningún lote de importación confirmado | número de cuentas | `null` |
  | `importado` | Tiene un lote confirmado | número de cuentas | fecha local del último lote confirmado |
  | `no_disponible` | El usuario no puede ver el plan de cuentas (`view_cuenta`) | `null` | `null` |

  `cuentas` cuenta todas, también las desactivadas. Un lote en vista previa no cambia la etapa: subir un archivo y mirar
  sus filas no configura nada. `causa` es `null` salvo en `no_disponible`, donde lleva el texto de `acceso` («Tu perfil no
  cuenta con el permiso necesario.»).
- **`etapas.apertura`** (desde el bloque 2): sale de la configuración del inicio y del estado de la apertura.

  | `estado` | Cuándo | `fecha` |
  |---|---|---|
  | `sin_configurar` | La empresa no configuró su inicio contable | `null` |
  | `pendiente` | Configurado, sin apertura en revisión ni confirmada (un borrador o ninguna) | el corte |
  | `en_revision` | Hay una apertura enviada a revisión | el corte |
  | `confirmada` | Hay una apertura confirmada | el corte |
  | `no_disponible` | El usuario no puede ver la apertura (sin licencia o sin `view_apertura`) | `null`, con la `causa` de `acceso` |

  `causa` es `null` salvo en `no_disponible`. Con el plan de cuentas vacío la etapa se informa igual. Ejemplo, con la
  apertura confirmada: `"apertura": {"estado": "confirmada", "fecha": "2025-12-31", "causa": null}`.
- **`etapas.conciliacion`**: `no_disponible` con su `causa` hasta que exista el bloque de bancos, que añadirá valores a
  `estado`.
- Ninguna etapa llega a «completado»: solo se informa lo que hay guardado.
- **`pendientes`**: solo entradas con `cantidad` mayor que cero, de tres orígenes. Cada origen se consulta solo si el
  usuario puede abrir su pantalla.

  | `origen` | Qué cuenta | Quién lo recibe | `codigo` |
  |---|---|---|---|
  | `revision` | Observaciones «por revisar» de la revisión del mes en curso, una entrada por categoría con el nombre y la cuenta de esa pantalla | `view_revision` | `devueltos`, `datos_ats`, `respaldos`, `numeracion`, `retenciones` |
  | `capturas` | Recibos y notas guardados que nadie completó, de cualquier mes | `view_captura`; sin `view_adjunto`, solo los propios | `recibo_por_completar` |
  | `importacion` | Documentos importados pendientes de revisión, la bandeja de `/importacion/pendientes/` | `view_documentoimportado` y plan Ilimitado o Multiempresa | `documento_por_revisar` |

  Las observaciones informativas de la revisión (cuentas vencidas, respaldos por revisar) no son pendientes. El enlace de
  la revisión baja al título de su categoría. Un recibo guardado este mes cuenta en `capturas` y también en
  «Respaldos pendientes» de la revisión: las cantidades de dos orígenes no se suman.
- **`origenes`**: los orígenes que se consultaron para este usuario. Un origen que está en la lista y no tiene entradas en
  `pendientes` significa «consultado y sin pendientes». Uno que no está no se consultó: no le corresponde al usuario y no
  se presenta como cero.

Negativas: sin ninguno de los tres permisos, 403 `sin_permiso` con
`"permisos": ["view_kardex", "view_revision", "view_cuenta"]`; `empresa` de otra pestaña, 409 `empresa_cambiada`;
complemento cerrado o sin plan, el 403 de licencia; otro método, 405.

Cambios respecto de la propuesta del 04/11:

- Se añade `view_cuenta` a los permisos que abren el inicio.
- Claves nuevas: `acceso` y `origenes`; `causa` en `etapas.plan_cuentas`.
- `etapas.plan_cuentas.estado` añade `configurado` y `no_disponible`. `etapas.apertura.estado` era `no_disponible` con su
  causa hasta el bloque 2, que añade `sin_configurar`, `pendiente`, `en_revision` y `confirmada` (cambio aditivo de
  valores: la clave y su forma no cambian).
- Los pendientes de la revisión van por categoría (`codigo: "respaldos"`), no por código de observación
  (`sin_respaldo`), y su enlace termina en `#fp-rev-<categoría>`, el `id` que tiene hoy cada título de
  `tributario/revision.html`.

## C2 — Plan de cuentas (construido)

Cuenta por empresa:

| Campo | Regla |
|---|---|
| `id` | identificador |
| `codigo` | hasta 30 caracteres; se guarda sin espacios sobrantes; único en la empresa sin distinguir mayúsculas; no cambia después del alta |
| `nombre` | hasta 200 caracteres |
| `padre_id` | un grupo de la misma empresa, o `null` en la raíz |
| `tipo` | `grupo` o `movimiento` |
| `activa` | `true` al crearla; una cuenta no se borra, se desactiva |
| `clase` (bloque 2) | `""` (sin clase), `activo`, `pasivo`, `patrimonio`, `ingreso`, `costo` o `gasto`. Dice dónde va la cuenta en los estados: balance (las tres primeras) o resultados (las tres últimas). La declara una persona; nunca se deduce del código |
| `auxiliar` (bloque 2) | `""` (sin auxiliar), `cliente`, `proveedor`, `inventario`, `banco`, `activo` o `tributario`. Qué detalle explica el saldo de la cuenta en la apertura. Solo en cuentas de movimiento |
| `hijas` | cuántas cuentas cuelgan directamente de ella, activas o no |
| `version` | empieza en 1 y sube en cada cambio |

Reglas del árbol: el padre es un grupo; no hay ciclos; una cuenta con hijas sigue siendo grupo; un grupo no se desactiva
mientras tenga hijas activas. Un grupo no recibe movimientos, y una cuenta con movimientos no pasa a grupo ni se
desactiva. Desde el bloque 2 «con movimientos» es: con líneas en el libro diario, o con una línea no retirada de una
apertura en borrador, en revisión o confirmada (`cuentas.tiene_movimientos`, el único sitio que lo decide).

**Lo ya validado no cambia por reclasificar** (bloque 2). Con la cuenta en el libro, un cambio de `clase` que la pase entre
balance y resultados (o que le quite la clase que tenía) responde 409 antes que cualquier error de campo:

- `ejercicio_cerrado` `{"ejercicios": [años]}` si tiene líneas en un ejercicio cerrado (en este bloque ninguno se cierra);
- `apertura_confirmada` (con `cuenta`) si es cuenta de una línea de la apertura confirmada: su resultado del ejercicio se
  validó con esa clase. Se comprueba aunque la cuenta no tenga todavía otras líneas en el libro.

Declarar la primera clase no cruza nada y siempre se admite. `auxiliar` no cambia mientras haya auxiliares vigentes de la
apertura en una línea de esa cuenta o líneas del libro con tercero en ella: 409 `cuenta_con_detalle`
`{"auxiliares": n, "lineas_con_tercero": n}`. Cambiar `tipo`, `activa`, `clase` o `auxiliar` (o clasificar) toma antes el
candado del libro de la empresa, si tiene inicio contable, para no cruzarse con un asiento o con la confirmación de la
apertura; renombrar no lo toma.

Permisos: ver, `view_cuenta` (Propietario, Administrador, Contador y Consulta); crear y editar, `add_cuenta` y
`change_cuenta` (Propietario, Administrador y Contador). Vendedor y Cliente, nada. No hay página ni entrada de menú nuevas:
los tres permisos viajan con el módulo «Kardex por producto» hasta que la pantalla del plan tenga el suyo.

### `GET /contabilidad/api/cuentas/?q=&empresa=` — `view_cuenta`

```
200 {"cuentas": [{"id": 1, "codigo": "1", "nombre": "Activo", "padre_id": null, "tipo": "grupo", "activa": true, "hijas": 1, "version": 1},
                 {"id": 2, "codigo": "1.1", "nombre": "Activo corriente", "padre_id": 1, "tipo": "grupo", "activa": true, "hijas": 1, "version": 1},
                 {"id": 3, "codigo": "1.1.01", "nombre": "Caja", "padre_id": 2, "tipo": "movimiento", "activa": true, "hijas": 0, "version": 1}],
     "capacidades": {"crear": true, "editar": true, "importar": true}}
```

- Todas las cuentas de la empresa, activas o no, sin paginar, ordenadas por código como lo lee una persona (1.2 antes que
  1.10).
- Con `q`: las cuentas que lo contienen en el código o en el nombre, sin distinguir mayúsculas ni tildes, y todas sus
  antepasadas. El ejemplo de arriba es también la respuesta a `?q=caja`.
- `capacidades.importar` es igual a `crear`. Para Consulta y con el plan vencido las tres son `false`.
- Desde el bloque 2 cada cuenta trae además `clase` y `auxiliar`, entre `activa` y `hijas`. Respuesta real a `?q=1.1.0`
  con el plan mínimo de las pruebas:

```
200 {"cuentas": [{"id": 1, "codigo": "1", "nombre": "ACTIVO", "padre_id": null, "tipo": "grupo", "activa": true, "clase": "activo", "auxiliar": "", "hijas": 6, "version": 1},
                 {"id": 2, "codigo": "1.1.01", "nombre": "Caja", "padre_id": 1, "tipo": "movimiento", "activa": true, "clase": "activo", "auxiliar": "", "hijas": 0, "version": 1},
                 {"id": 3, "codigo": "1.1.02", "nombre": "Bancos", "padre_id": 1, "tipo": "movimiento", "activa": true, "clase": "activo", "auxiliar": "banco", "hijas": 0, "version": 1},
                 {"id": 4, "codigo": "1.1.03", "nombre": "Clientes", "padre_id": 1, "tipo": "movimiento", "activa": true, "clase": "activo", "auxiliar": "cliente", "hijas": 0, "version": 1},
                 …],
     "capacidades": {"crear": true, "editar": true, "importar": true}}
```

### `POST /contabilidad/api/cuentas/` — `add_cuenta`

Envío: `{"empresa", "clave", "codigo", "nombre", "tipo", "padre_id"}`. `padre_id` puede faltar o ser `null`. `codigo`
admite texto o un entero (`1101`); un número con decimales no, porque `1.10` ya llegó como `1.1`.

```
201 {"cuenta": {"id": 1, "codigo": "1", "nombre": "Activo", "padre_id": null, "tipo": "grupo", "activa": true, "hijas": 0, "version": 1},
     "repetido": false}
200 {"cuenta": {…la misma…}, "repetido": true}                       (misma clave y mismo contenido)
409 {"error": "Esta clave ya se usó para otra cuenta: vuelve a cargar la página e inténtalo de nuevo.", "codigo": "clave_usada",
     "cuenta": {"id": 1, "codigo": "1", "nombre": "Activo", …}}       (misma clave y otro contenido)
400 {"error": "Revisa los datos marcados.", "codigo": "validacion",
     "errores": {"codigo": ["Escribe el código de la cuenta."], "nombre": ["Escribe el nombre de la cuenta."],
                 "tipo": ["Elige grupo o movimiento."], "padre_id": ["El padre debe ser un grupo de esta empresa."]}}
```

El envío repetido se compara con la cuenta como está ahora: si alguien la cambió después del alta, repetirlo da el 409
`clave_usada` con la cuenta actual, nunca una segunda cuenta.

### `PATCH /contabilidad/api/cuentas/<id>/` — `change_cuenta`

Envío: `{"empresa", "version", "nombre"?, "padre_id"?, "tipo"?, "activa"?, "clase"?, "auxiliar"?}`. Solo cambia lo que
viene. `padre_id: null` pasa la cuenta a la raíz. `activa` es un booleano. `clase` y `auxiliar` (bloque 2) admiten `""`
para quitarlos, con las reglas de reclasificar de arriba; un auxiliar en una cuenta de grupo, o pasar a grupo una cuenta
con auxiliar, es 400. Los cambios se auditan (`cuenta_modificada`) con el valor anterior y el nuevo.

```
PATCH /contabilidad/api/cuentas/2/?empresa=1   {"empresa": 1, "version": 1, "auxiliar": "banco"}
200 {"cuenta": {"id": 2, "codigo": "1.1.01", "nombre": "Caja", "padre_id": 1, "tipo": "movimiento", "activa": true, "clase": "activo", "auxiliar": "banco", "hijas": 0, "version": 2}}

PATCH /contabilidad/api/cuentas/1/?empresa=1   {"empresa": 1, "version": 1, "auxiliar": "cliente"}
400 {"error": "Revisa los datos marcados.", "codigo": "validacion", "errores": {"auxiliar": ["Solo las cuentas de movimiento llevan auxiliar."]}}

PATCH /contabilidad/api/cuentas/11/?empresa=1  {"empresa": 1, "version": 1, "clase": "ingreso"}     (capital social, en la apertura confirmada)
409 {"error": "La cuenta está en la apertura confirmada, que se validó con su clase: no puede pasar entre balance y resultados. Corrige la apertura con un ajuste o una sustitución.",
     "codigo": "apertura_confirmada",
     "cuenta": {"id": 11, "codigo": "3.1.01", "nombre": "Capital social", "padre_id": 10, "tipo": "movimiento", "activa": true, "clase": "patrimonio", "auxiliar": "", "hijas": 0, "version": 1}}
```

```
200 {"cuenta": {"id": 3, "codigo": "1.1.01", "nombre": "Caja general", "padre_id": 2, "tipo": "movimiento", "activa": true, "hijas": 0, "version": 2}}
409 {"error": "Otra persona cambió esta cuenta mientras la editabas: revisa cómo quedó y vuelve a intentarlo.", "codigo": "version",
     "cuenta": {"id": 3, "codigo": "1.1.01", "nombre": "Caja general", …, "version": 2}}
404 {"error": "La cuenta no existe o es de otra empresa.", "codigo": "cuenta"}
```

- Orden dentro del PATCH: 404, después 409 `version`, después 400. Con una versión vieja se responde el 409 aunque el
  resto del envío tenga errores.
- Si nada cambia, responde 200 con la misma `version`.
- No hay DELETE (405).

### Errores de campo (400 `validacion`)

| Campo | Texto |
|---|---|
| `codigo` | «Escribe el código de la cuenta.» · «El código admite hasta 30 caracteres.» · «El código tiene caracteres que no se pueden guardar.» · «Ya existe la cuenta 1.1.01 en esta empresa.» (muestra el código como está guardado) · en PATCH, si llega distinto: «El código de una cuenta no se cambia: crea otra cuenta y desactiva esta.» |
| `nombre` | «Escribe el nombre de la cuenta.» · «El nombre admite hasta 200 caracteres.» · «El nombre tiene caracteres que no se pueden guardar.» |
| `tipo` | «Elige grupo o movimiento.» · «Tiene cuentas hijas: debe seguir siendo grupo.» · «Tiene movimientos: no puede pasar a grupo.» |
| `padre_id` | «El padre debe ser un grupo de esta empresa.» · «Crearía un ciclo.» |
| `activa` | «Indica si la cuenta queda activa: verdadero o falso.» · «Desactiva primero sus cuentas hijas.» · «Tiene movimientos: no se puede desactivar.» |
| `version` | «Falta la versión de la cuenta que estás editando: vuelve a cargarla e inténtalo de nuevo.» |
| `clase` | «Elige la clase: activo, pasivo, patrimonio, ingreso, costo o gasto (o vacío, sin clase).» |
| `auxiliar` | «Elige el auxiliar: clientes, proveedores, inventario, bancos, activos o tributario (o vacío, sin auxiliar).» · «Solo las cuentas de movimiento llevan auxiliar.» |

Auditoría: `cuenta_creada` y `cuenta_modificada`, esta con los campos que cambiaron.

### `POST /contabilidad/api/cuentas/clasificar/` — `change_cuenta` (bloque 2)

Fija una clase en una cuenta y, con `incluir_descendientes: true`, en sus descendientes **sin clase**: es una decisión
expresa por lote y nunca pisa una clase ya puesta. Envío JSON: `{"empresa", "cuenta_id", "version", "clase",
"incluir_descendientes"}`; `clase` es obligatoria (vacía no vale) y `version` es la de la cuenta pedida, que sigue las reglas
de reclasificar. Responde la cuenta como queda y cuántas recibieron la clase (ella incluida si cambió). Auditoría
`cuentas_clasificadas`, solo si alguna cambió. Solo POST: un GET es 405 (`tests/test_rutas.py`, `ESPERADOS`).

```
POST /contabilidad/api/cuentas/clasificar/?empresa=1
{"empresa": 1, "cuenta_id": 19, "version": 1, "clase": "activo", "incluir_descendientes": true}
200 {"cuenta": {"id": 19, "codigo": "1.3", "nombre": "OTROS ACTIVOS", "padre_id": null, "tipo": "grupo", "activa": true, "clase": "activo", "auxiliar": "", "hijas": 1, "version": 2},
     "clasificadas": 2}

{"empresa": 1, "cuenta_id": 19, "version": 7, "clase": "activo", "incluir_descendientes": true}
409 {"error": "Otra persona cambió esta cuenta mientras la editabas: revisa cómo quedó y vuelve a intentarlo.", "codigo": "version",
     "cuenta": {"id": 19, "codigo": "1.3", "nombre": "OTROS ACTIVOS", "padre_id": null, "tipo": "grupo", "activa": true, "clase": "", "auxiliar": "", "hijas": 1, "version": 1}}

{"empresa": 1, "cuenta_id": 19, "version": 2, "clase": "capital", "incluir_descendientes": false}
400 {"error": "Revisa los datos marcados.", "codigo": "validacion", "errores": {"clase": ["Elige la clase: activo, pasivo, patrimonio, ingreso, costo o gasto."]}}
```

Otros: 404 `cuenta` (el código del bloque 1, no `no_existe`); 409 `ejercicio_cerrado` y `apertura_confirmada`; 400
`cuenta_id` e `incluir_descendientes` (booleano).

Cambios respecto de la propuesta del 04/11:

- Los envíos llevan `empresa`, obligatoria.
- El POST responde siempre `repetido`. El 409 `clave_usada` y el 409 `version` traen `cuenta`.
- Los 400 traen `codigo` además de `error` y `errores`.
- El código no se cambia por PATCH. Se rechazan los códigos y nombres con caracteres de control o invisibles.
- No hay reglas sobre padres inactivos: se puede crear o mover una cuenta bajo un grupo desactivado y reactivar la hija
  de un grupo desactivado. Solo está prohibido desactivar un grupo con hijas activas.

## C3 — Importación del plan de cuentas (construido)

Tres pasos, y nada se crea hasta el último: subir el archivo, corregir las columnas si hace falta y confirmar. Todas las
rutas piden `add_cuenta` (Propietario, Administrador y Contador); confirmar con `actualizar_nombre` pide además
`change_cuenta`.

**Archivo.** CSV en UTF-8, con o sin BOM, separado por `;` o por `,` (se detecta) y con comillas; o XLSX, primera hoja.
Se reconoce por su contenido, no por su nombre. Límites: 2 MB, 5 000 filas de cuentas, 40 columnas, 2 097 152 caracteres
de texto entre todas las celdas de la tabla y, el XLSX, 20 MB al descomprimirlo. El tope de texto es lo que cabe en un CSV
de 2 MB: a un CSV no lo alcanza nunca, y corta el XLSX que repite un texto largo en miles de celdas (pesa unos kilobytes
y dejaba un lote de cientos de megas). **No se lee `.xls`** ni un libro con contraseña, y un CSV en otra codificación se
rechaza en vez de adivinarla: guardaría mal los nombres con tilde. La primera fila con contenido es la de encabezados;
las filas en blanco se saltan sin cambiar la numeración.

Tampoco se adivina dónde terminaba un texto con las comillas mal puestas. Un CSV con unas comillas que se abren y no se
cierran, o con texto pegado después de cerrarlas (`"Otros" ingresos`), se rechaza entero con 400 `formato` y la fila:
«El CSV no se pudo leer a partir de la fila 5: revisa sus comillas (unas que no se cierran o texto pegado después de
cerrarlas) o guarda el archivo de nuevo desde la hoja de cálculo.» Un salto de línea dentro de unas comillas bien
cerradas vale, y se guarda como un espacio. Las hojas de cálculo exportan siempre las comillas bien cerradas: esto solo
alcanza a un CSV escrito a mano.

Un XLSX que declara entidades XML (un `DOCTYPE` en cualquiera de sus partes XML, las `.xml` y las `.rels`) no se abre:
400 `formato`, «El XLSX trae declaraciones que una hoja de cálculo no escribe (DOCTYPE): ábrelo y guárdalo de nuevo como
XLSX, o súbelo como CSV UTF-8.» Ninguna hoja de cálculo las escribe en esas partes, y con ellas unos kilobytes ocupan gigas
de memoria al leerlos. De las imágenes y los objetos incrustados solo se comprueba que no estén dañados, cifrados ni
comprimidos de otra forma, y lo que traen no se interpreta: un logo SVG, que sí puede traer su `DOCTYPE`, o una imagen
en una hoja de gráfico no impiden subir el libro. Tampoco se abre un XLSX con una parte dañada o cifrada, o comprimida de
otra forma que la de un XLSX (bzip2, lzma…), aunque no sea la hoja: 400 `formato` con el texto general.

**Columnas.** Se reconocen por su encabezado, sin distinguir mayúsculas ni tildes:

| Dato | Encabezados |
|---|---|
| `codigo` | Código, Cuenta, Code |
| `nombre` | Nombre, Descripción, Detalle, Name; y Cuenta, si otra columna ya es el código |
| `padre` (opcional) | Padre, Cuenta padre, Parent |
| `tipo` (opcional) | Tipo, Type |
| `clase` (opcional, bloque 2) | Clase, Class |

**Clase** (bloque 2). Si viene, uno de los seis valores en singular, sin distinguir mayúsculas ni tildes (`activo`,
`pasivo`, `patrimonio`, `ingreso`, `costo`, `gasto`); vacía, la cuenta queda sin clase. Otro valor es error de fila:
«Clase no reconocida («X»): escribe activo, pasivo, patrimonio, ingreso, costo o gasto, o déjala vacía.» La clase solo se
fija en las cuentas que se crean: a una `duplicada` no se le cambia, igual que el padre y el tipo. El lote añade `clase` a
`columnas` y a cada fila, y el mapeo (`…/mapeo/`) la admite como un dato más. El auxiliar no se importa: se declara en el
plan de cuentas.

Los encabezados se devuelven con nombre único: una celda vacía pasa a «Columna 3» y uno repetido a «Nombre (2)». El
mapeo se hace con ese nombre exacto. Sin columna de código o de nombre no hay vista previa: `filas` va vacía y `resumen`
dice qué elegir.

**Jerarquía.** Con columna padre, el padre es ese código, esté en el archivo o ya en la empresa. Sin ella sale de los
puntos del código: el prefijo más largo que exista (de `1.1.01`, primero `1.1` y después `1`); si ninguno existe, la
cuenta va en la raíz.

**Tipo.** Si viene: `G` o `Grupo`; `M`, `Movimiento` o `Detalle`. Si falta: grupo si tiene hijas, en el archivo o en la
empresa, y movimiento si no.

**Estado de cada fila:**

- `valida`: se creará.
- `duplicada`: su código ya existe en la empresa, sin distinguir mayúsculas. Al confirmar se omite o se le actualiza el
  nombre; nunca cambia de padre ni de tipo. El `padre` y el `tipo` que muestra son los del archivo.
- `error`: no se puede importar. Trae todos sus errores.

| Error de fila | Texto |
|---|---|
| Sin código o sin nombre | «Falta el código.» · «Falta el nombre.» |
| Demasiado largo o con caracteres que no se guardan | los textos de C2 |
| Código repetido en el archivo | «El código 1.1 está repetido en el archivo: ya aparece en la fila 3.» (en la segunda aparición) |
| Padre que no existe | «El padre 1.9 no existe.» |
| Padre que ya existe como cuenta de movimiento | «El padre 1.1.01 ya existe en esta empresa como cuenta de movimiento: pásalo a grupo antes de importar.» |
| Escrita como movimiento y con hijas en el archivo | «Es de movimiento y el archivo le cuelga cuentas hijas: debe ser grupo.» |
| Ciclo | «Crearía un ciclo.» |
| Tipo no reconocido | «Tipo no reconocido («X»): escribe grupo o movimiento.» |
| La hoja convirtió el código o el padre en fecha o en un número de 15 cifras o más | «La hoja de cálculo cambió el código (lo guardó como fecha o como un número que ya no es exacto): escríbelo como texto.» |
| Más celdas que encabezados | «La fila tiene más celdas que columnas el encabezado: revisa si un texto con el separador va sin comillas.» |

Las reglas del árbol (padre, ciclo, movimiento con hijas) se aplican a las filas que se van a crear. A una duplicada
solo se le revisa lo que se lee de ella: código, nombre, tipo reconocible y repetición en el archivo.

### `POST /contabilidad/api/cuentas/importar/` — subir

Formulario `multipart` con `archivo`, `clave` y `empresa`. Responde 200, también la primera vez.

```
200 {"lote": {"id": 1, "estado": "vista_previa", "archivo": "plan.csv",
              "columnas": {"codigo": "Código", "nombre": "Cuenta", "padre": null, "tipo": "Tipo"},
              "encabezados": ["Código", "Cuenta", "Tipo"],
              "muestra": [["1", "Activo", "G"], ["1.1", "Activo corriente", ""], ["1.1.01", "Caja", ""], ["1.1.02", "Bancos", "M"],
                          ["1.9.01", "Otros activos", "X"]],
              "filas": [{"fila": 2, "codigo": "1", "nombre": "Activo", "padre": null, "tipo": "grupo", "estado": "duplicada", "errores": []},
                        {"fila": 5, "codigo": "1.1.02", "nombre": "Bancos", "padre": "1.1", "tipo": "movimiento", "estado": "valida", "errores": []},
                        {"fila": 6, "codigo": "1.9.01", "nombre": "Otros activos", "padre": "1", "tipo": null, "estado": "error",
                         "errores": ["Tipo no reconocido («X»): escribe grupo o movimiento."]},
                        …],
              "resumen": {"validas": 3, "con_error": 1, "duplicadas": 3, "faltan_columnas": [], "texto": null}},
     "repetido": false}
```

- `fila` es el número de fila en el archivo; la de encabezados es la 1.
- `muestra` son las cinco primeras filas tal como se leyeron, columna por columna, para elegir el mapeo viendo los datos.
- `filas` trae todas las filas del archivo, hasta 5 000.
- Misma `clave` y mismo archivo: el mismo lote con `"repetido": true`. Misma `clave` y otro archivo: 409 `clave_usada`.
- Sin columnas reconocidas el lote se crea igual, para poder mapearlo:
  `"resumen": {"validas": 0, "con_error": 0, "duplicadas": 0, "faltan_columnas": ["codigo", "nombre"],
  "texto": "Elige qué columna del archivo trae el código y el nombre de cada cuenta."}`.
- El archivo queda en la carpeta privada de la empresa, con su huella SHA-256. No hay ruta para descargarlo.

### `GET /contabilidad/api/cuentas/importar/<id>/?empresa=` — recargar

`{"lote": {…}}`. En vista previa, con las filas revisadas contra las cuentas que existan en ese momento. Confirmado, con
su resultado y sin las filas.

### `POST /contabilidad/api/cuentas/importar/<id>/mapeo/` — elegir columnas

Envío JSON: `{"empresa", "codigo", "nombre", "padre", "tipo"}`, cada uno el nombre de un encabezado o `null`. Un dato que
no viene queda sin columna. Responde `{"lote": {…}}` con la vista previa recalculada.

```
400 {"error": "Revisa los datos marcados.", "codigo": "validacion",
     "errores": {"nombre": ["Esa columna no está en el archivo."], "tipo": ["Esa columna ya está elegida para otro dato."]}}
```

### `POST /contabilidad/api/cuentas/importar/<id>/confirmar/` — crear las cuentas

Envío JSON: `{"empresa", "clave", "duplicadas": "omitir" | "actualizar_nombre"}`. `duplicadas` es obligatorio.

```
200 {"lote": {"id": 1, "estado": "confirmado", "archivo": "plan.csv", "duplicadas": "omitir", "creadas": 4, "actualizadas": 0,
              "omitidas": 3, "confirmado_en": "2026-11-14"},
     "repetido": false}
400 {"error": "Hay filas con errores: corrige el archivo o las columnas elegidas. No se creó ninguna cuenta.", "codigo": "filas_con_error",
     "resumen": {"validas": 3, "con_error": 1, "duplicadas": 3, "faltan_columnas": [], "texto": null}}
409 {"error": "Esta importación ya se confirmó: sus cuentas ya están en el plan.", "codigo": "lote_confirmado",
     "lote": {"id": 1, "estado": "confirmado", …}}
```

- La vista previa se vuelve a calcular al confirmar, contra las cuentas de ese momento. Con una sola fila en error no se
  crea nada.
- `actualizar_nombre` cambia el nombre de las duplicadas y sube su `version`. Si el nombre ya es igual, cuenta como
  omitida. Pide `change_cuenta` aunque el archivo no traiga duplicadas.
- Repetir con la misma `clave` devuelve el mismo resultado con `"repetido": true`. Dos confirmaciones a la vez crean las
  cuentas una sola vez.
- Las cuentas se crean en una sola transacción: o todas o ninguna. 5 000 filas se confirman en alrededor de un segundo.
- Auditoría: una entrada `cuentas_importadas` por importación, con el lote, las cantidades, el archivo y su huella.

### Códigos de las cuatro rutas

| Estado | `codigo` | Cuándo |
|---|---|---|
| 400 | `clave` | falta la clave o está mal formada |
| 400 | `validacion` | falta `archivo`; `duplicadas` falta o no es válido; en el mapeo, una columna que no está o que se repite |
| 400 | `archivo_grande` | más de 2 MB, XLSX de más de 20 MB al abrirlo, demasiadas celdas fuera de la tabla o demasiado texto en la tabla («El archivo trae demasiado texto para un plan de cuentas: deja solo las columnas del plan (código, nombre, padre y tipo) y súbelo de nuevo.») |
| 400 | `demasiadas_filas` | más de 5 000 filas de cuentas |
| 400 | `formato` | no es CSV ni XLSX, está dañado, vacío o solo trae encabezados, tiene más de 40 columnas, es un `.xls` o un libro con contraseña, el CSV no está en UTF-8 o tiene las comillas mal cerradas, o el XLSX declara entidades XML (`DOCTYPE`) en una de sus partes XML o trae una parte dañada, cifrada o comprimida de otra forma que la de un XLSX. `error` dice cuál |
| 400 | `faltan_columnas` | al confirmar sin columna de código o de nombre; trae `resumen` |
| 400 | `filas_con_error` | al confirmar con alguna fila en error; trae `resumen` |
| 404 | `lote` | el lote no existe o es de otra empresa |
| 409 | `clave_usada` | la clave de la subida ya se usó con otro archivo; o la de la confirmación, con otra opción de `duplicadas` (trae `lote`) |
| 409 | `lote_confirmado` | mapear un lote confirmado o confirmarlo con otra clave; trae `lote` |
| 409 | `plan_cambiado` | alguien creó uno de esos códigos mientras se confirmaba; no se creó nada y basta repetir |

Más los comunes: 409 `empresa_cambiada` y `sin_empresa`, 403 de licencia y `sin_permiso`, 405 y, fuera del orden,
409 `reintentar` («Orden de las negativas»; desde el cierre del corte 1 del bloque 2).

Cambios respecto de la propuesta del 04/11:

- Los envíos llevan `empresa`. Hay una ruta nueva, el GET del lote.
- El lote en vista previa añade `encabezados` y `muestra`; `resumen` añade `faltan_columnas` y `texto`.
- La subida y la confirmación responden siempre `repetido`. El lote confirmado añade `id`, `archivo` y `duplicadas`.
- Códigos que la propuesta no nombraba: `faltan_columnas`, `plan_cambiado`, `archivo_grande`, `demasiadas_filas` y
  `formato`.
- Un lote que no existe o es de otra empresa responde 404 `lote`, no el 409 de la propuesta; el ya confirmado, 409
  `lote_confirmado`.
- La maqueta v9 acepta `.xls`: el servidor no lo lee.
- Sin decidir: cuánto tiempo se conservan los lotes que se quedan en vista previa y su archivo. Hoy no se borran.

## C4 — Asientos por comprobante (bloqueado por D7)

Sin la matriz validada (qué cuentas debita y acredita cada tipo de documento, IVA, retenciones y cobros) no se propone
ningún asiento. Forma de lectura para cuando exista:
`GET /contabilidad/api/asientos/?mes=&estado=&empresa=` → `{"asientos": [{"id", "version", "fecha", "documento": {"tipo",
"id", "numero", "url"}, "origen", "estado": "borrador | con_excepcion | confirmado | anulado", "lineas": [{"cuenta":
{"id", "codigo", "nombre"} | null, "concepto", "debe", "haber"}], "totales": {"debe", "haber", "cuadra"}, "excepciones":
[{"codigo", "texto", "linea"}], "capacidades": {"resolver", "confirmar"}}]}`; `POST …/<id>/resolver/` `{linea, cuenta_id,
version}`; `POST …/<id>/confirmar/` `{version}`. «Cuadra» no significa contabilizado.

## C5 — Revisión del mes (parcial, sin bloqueo para las evidencias)

Hoy: `GET /tributario/api/revision/?mes=&empresa=` (documentos y excepciones por categoría, con el documento de origen),
`/tributario/api/libros/<libro>/` y `/tributario/api/ats/` para «IVA y ATS» (contratos en HANDOFF, sección de libros,
revisión, ATS y borradores).
Nuevo: evidencias de presentación, privadas y ligadas al período. `POST /tributario/api/revision/evidencias/` (multipart
`archivo` PDF/JPG/PNG hasta 8 MB, `tipo`: `104 | 103 | ats | otro`, `mes`, `referencia`, `fecha_presentacion`, `clave`) →
201 `{"evidencia": {"id", "tipo", "mes", "referencia", "fecha_presentacion", "subida_por", "subida_en", "url"}}`; `GET` lista
del mes; descarga `GET /tributario/revision/evidencias/<id>/archivo/` con permiso y empresa. Se muestra «evidencia
registrada», nunca «declaración presentada».
**Decisión que bloquea el cierre/reapertura:** qué impide un mes cerrado (¿editar, anular o registrar documentos con fecha
del mes?) y quién cierra y reabre. Los saldos anteriores dependen de la apertura (C6).

## C6 — Reportes (parcial)

Hoy: libros con exportación, borradores 104/103, kardex e inventario valorizado. Toda respuesta de reporte nuevo trae
`provisional: true | false` y `causas: [texto]`. **Bloqueo de mayor y estados financieros:** D5 (plan de cuentas o catálogo
Supercias), D7 (matriz) y saldos de apertura validados por el contador.

Desde el bloque 2 (construido): el diario (`GET /contabilidad/api/diario/`, `…/diario/<id>/`) y la comprobación de
integridad del libro (`GET /contabilidad/api/integridad/`), con sus formas y ejemplos en `CONTRATO-APERTURA-CONTABLE.md`,
sección 6.4. La provisionalidad de todo reporte sale de una sola función con un registro de causas
(`core/contabilidad/reportes.py: provisionalidad(reporte, desde, hasta)`), y cada respuesta trae además
`causas_detalle: [{"codigo", "texto", "cantidad"?}]`. Causas registradas: `inicio_sin_configurar`,
`apertura_sin_confirmar`, `saldo_anterior_sin_confirmar`, `resultados_acumulados_sin_detalle`,
`aplicaciones_sin_contabilizar` y `motor_pendiente`, obligatoria en todo rango que pase de la fecha de corte mientras la
operación diaria no se contabilice (bloque 3). Con la apertura confirmada, un rango posterior al corte **sigue
provisional**. El mayor, el balance de comprobación y los estados son de los bloques siguientes.

## C7 — Puntos de emisión (sin bloqueo si se acepta la definición)

Hoy: `/configuracion/puntos/estado.json` (establecimientos y puntos, autorizados por usuario y selección). Se añade a esa
respuesta: `{"cupo": {"maximo": 3, "usados": 2}, "puntos": [{…, "verificacion": {"estado": "verificado | pendiente",
"evidencia": {"tipo": "comprobante_autorizado", "numero": "001-001-000000123", "fecha": "2026-10-20", "url": …} | null}}]}`
y el alta de un punto por encima del cupo responde 400 `{"codigo": "cupo"}`. El límite es interno (instrucciones de la
propietaria): no se presenta como regla del SRI.
**Definición propuesta de «verificado»:** el punto tiene al menos un comprobante autorizado por el SRI en producción (la
evidencia es ese comprobante). Si se quiere otra evidencia (por ejemplo, el catastro del SRI), decirlo antes de C7.

## Piloto NEXALLTI

No se usan cifras de ejemplo ni se marca nada como importado. **Bloquean:** el Excel real de su plan de cuentas (y, si se
quieren saldos, la apertura firmada por su contador) y la decisión de incluir su RUC en la lista de revisión del
complemento mientras D9 no fije impuestos y alcance.

## Orden propuesto

C1, C2 y C3 están construidos (inicio, plan de cuentas e importación) y, en el bloque 2, el diario y la apertura hasta
confirmar (C6-A, corte 1) → corte 2 del bloque 2 (auxiliares, cartera inicial, ajustes, sustitución e históricos) → C7 →
C5 (evidencias) → C4 y el resto de C6 cuando lleguen D7 y D5. Codex conecta cada pantalla cuando su ruta esté publicada; hasta entonces, la maqueta queda en
`entregas/`.
