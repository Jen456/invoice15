# C6-A · Inicio contable desde saldos o desde historial

13/11/2026 · Propuesta de contrato Codex → Claude. Amplía C1–C6 de `CONTRATO-CONTABLE-V9.md`. Decisión funcional de la propietaria: unas empresas parten de estados financieros existentes y otras reconstruyen exhaustivamente sus operaciones. No obligar a la primera a registrar todos los años anteriores.

**14/11/2026 · Claude: corte 1 del bloque 2 construido (libro diario mínimo, inicio contable y apertura hasta confirmar).** Rama `fase/contable-2-apertura`, código final `a5bedf4`; desde la unión con el bloque 1 final `8a421b3` (15/11/2026), `3193edc`; desde las correcciones del cierre del corte (15/11/2026), `72a68ee`, y desde la corrección que dejó la verificación del cierre (15/11/2026: los controles en el código o el rubro de una fila del lote, DOC44-2), **`7a5c567`**. Sin `push` y sin publicar. Lo que este corte implementa deja de ser propuesta: la sección 6 es el contrato definitivo de esas rutas, con peticiones y respuestas reales obtenidas ejecutándolas con datos ficticios. Lo de las Partes C a F de la especificación (auxiliares, cartera inicial, ajustes, sustitución, reverso, documentos históricos y la guarda de la importación) está marcado **pendiente del corte 2**: sus rutas todavía no existen. Las secciones 1 a 5 y 7 son la propuesta funcional de Codex del 13/11, sin cambios; la 8 añade en qué estado queda cada prueba de aceptación.

**Qué se verificó y contra qué código.**

- Los ejemplos de la sección 6 son respuestas reales obtenidas en `a5bedf4` (bloque 1 en `84d07cc`) con una prueba
  temporal que no se entrega; las peticiones y respuestas están en la VM101, en
  `/root/invoice15/contable/registros/bloque2-c1-ejemplos.json`. No se volvieron a obtener después: sus fechas e instantes
  son los del 14/11 y, fuera de lo que dice la lista del cierre de abajo, valen tal cual.
- Tras la unión con el bloque 1 final (`3193edc`) solo se volvió a verificar la importación de los saldos, que desde
  entonces lee con el lector común `lectura_tabular.py` (`tests/test_apertura_importar.py::TestLectorComun`).
- En el cierre del corte, sobre `6efad50` (la rama unida: el código de `3193edc` y documentos), la revisión del contrato
  ejecutó con el cliente de pruebas de Django las 20 rutas del corte y los 53 bloques de ejemplo de §6.4–6.9, y los
  comparó por claves, orden de claves, tipos, valores, `codigo` y estado HTTP: coinciden, salvo los valores que dependen
  de la fecha y lo que se corrige abajo (H3 y H7; H10 se refutó). El recorrido en navegador del cierre (37 casos) también
  fue sobre `6efad50`, y no se repitió sobre el código corregido.
- Tras las correcciones del 15/11 (código `72a68ee`), cada corrección pasó sus pruebas (registro
  `/root/invoice15/contable/registros/correcciones-c2c1.json`), y las formas nuevas o corregidas de los puntos 1 a 7 de
  la lista de abajo, salvo `importe_total_excedido`, se comprobaron con el cliente de pruebas de Django en una copia de
  `72a68ee` hecha con `git archive` (SQLite, datos ficticios, el 15/11/2026 de 13:21 a 13:23 UTC, carga de 3,78 a 4,46
  con 6 núcleos compartidos; respuestas en `/root/invoice15/contable/registros/doc-c2c1-sondeo-72a68ee.json`). El punto
  8 es de `7a5c567` y se comprobó en una copia de ese código (abajo). Los ejemplos que llevan
  la marca «(`72a68ee`)» salen de ahí. La de `importe_total_excedido` (punto 3) no está en ese sondeo: la comprueba
  `tests/test_apertura.py::TestBloqueos::test_total_que_no_cabe_en_un_asiento` (en `19105ff`), y su texto y su máximo se
  leyeron en el código.
- El ensayo de la decisión 18 repetido sobre `72a68ee` (15/11, de 13:29 a 14:16 UTC) recorrió por HTTP 22 casos de las
  correcciones (`[C]`): los caracteres de control, `1e3`, el PNG dañado, el auxiliar cambiado en revisión con
  `detalle_fijado` y la clave usada en otra apertura. Los 22, bien (MIGRACIONES-FASE-CONTABLE.md, «Ensayo repetido sobre
  `72a68ee`»).
- La verificación del cierre (15/11, sobre los documentos de `44b8b71`) volvió a ejecutar en `72a68ee` los 52 bloques de
  §6.4–6.9 (SQLite, de 14:27 a 14:29 UTC, carga de 1,96 a 2,66): solo difieren las fechas, `detalle_fijado` (ya
  documentado), el extracto de capacidades (H10, refutado) y un artificio del lector en `Allow`. Sus correcciones de
  texto están en este documento. La de código, `7a5c567`, solo toca la importación
  de los saldos: sus formas (§6.1, «Textos libres», e importar) se comprobaron en una copia de `7a5c567` con el cliente de
  pruebas de Django (SQLite, datos ficticios, el 15/11/2026 de 15:02 a 15:11 UTC, carga de 5,80 a 6,34). Los ejemplos
  marcados «(`7a5c567`)» salen de ahí.

**No** está integrado con `fase/primera-entrega`: al integrar cambia la numeración de las migraciones de `tenancy` (la
receta está en `MIGRACIONES-FASE-CONTABLE.md`, «Receta de integración con `fase/primera-entrega`») y hay que volver a
verificar este contrato contra el commit integrado.

**15/11/2026 · Cierre del corte 1: lo que cambia para quien conecte las pantallas** (código `72a68ee`, y el punto 8 desde
`7a5c567`; el detalle, en cada sección):

1. Un código nuevo fuera del orden de las negativas, en las rutas nuevas de `/contabilidad/api/` (las de `ApiContable`;
   no en las del kardex ni del inventario de `e0f2902`, `api/kardex/…` y `api/inventario/`, donde un interbloqueo sigue
   siendo un 500): 409 `reintentar` cuando la base aborta la transacción por un interbloqueo o por un bloqueo que no
   consiguió a tiempo (§6.1 y §6.7).
2. Mientras la apertura se prepara, el `detalle` de cada línea es el auxiliar que su cuenta declara **ahora**; confirmar
   lo fija y el evento `confirmada` lo dice en `detalle_fijado` (§6.5, regla 4; la forma, en §6.6, `GET apertura/<id>/`,
   historial).
3. Dos bloqueos nuevos: `cuenta_no_aplica`, después de `cuenta_inactiva`, e `importe_total_excedido`, después de
   `apertura_desbalanceada` (§6.5, regla 5).
4. Con N = P = 0, declarar el resultado en cuentas de resultados o en patrimonio, o una cifra distinta de cero, es
   `resultado_duplicado`, también a 31/12 (§6.5, regla 6).
5. Los textos libres rechazan los caracteres de control (400 `validacion`, con «Quita los caracteres de control o no
   válidos de este texto (suelen llegar al copiarlo de otro programa).» en su campo), y un importe escrito solo admite
   signo, cifras ASCII y los separadores (§6.1).
6. Respaldos: la misma `clave` en otra apertura es 409 `clave_usada`, y una imagen que no se puede leer es 400
   `validacion` con `errores.archivo`, no un 500 (§6.6, respaldos).
7. Lo que el contrato decía mal o no decía, sin cambio de código: la forma del 409 `auxiliar_incompleto`, con `sobran`
   (H7); que `GET apertura/<id>/lineas/` y mapear devuelven también las líneas retiradas (D3); el sitio del 400 de un
   envío de mapear que no se puede leer (H2); y que «400 `fijo`» y «400 `tipo`» son 400 `validacion` con el error en su
   campo (H3 y D2).
8. Desde `7a5c567`: en un lote, un carácter de control en el código o en el rubro de una fila deja esa fila en `error`
   con el mismo texto del punto 5, y mapear desde ese lote responde 400 `validacion` con `filas.<n>.codigo` o
   `filas.<n>.rubro` (§6.1, «Textos libres», e importar). Antes esos controles llegaban a la línea y, al confirmar, al
   concepto del asiento inicial, que ya no se cambia.

## 1. Estado comprobado y prioridad

Base revisada: `plataforma 96d39e1`. La URL de Contabilidad ofrece kardex e inventario; no existen todavía las rutas de cuentas, apertura, diario o mayor. Tributario sí tiene libros, revisión, ATS y borradores 104/103, con validación contable pendiente. La restricción se origina en `core/suscripciones/reglas.py`, `MENSAJE_COMPLEMENTO` y la lista `FPA_COMPLEMENTO_CONTABLE_REVISION`.

El aviso comercial no sustituye el desarrollo faltante. Claude debe construir el núcleo genérico y conectar las funciones existentes, sin esperar al precio para programar. La activación comercial y la aprobación de resultados fiscales son controles distintos. Codex no cambia la licencia ni habilita el módulo eliminando el mensaje.

Prioridad de ejecución: cuentas e importador C2/C3 → apertura C6-A → asientos/diario/mayor → conciliación/cierre → validación de 104/103/ATS y cierre anual/101. C1 y evidencias C5 pueden construirse en paralelo. La plantilla Supercias y los datos reales del piloto no bloquean el importador genérico ni la interfaz; sí la configuración final de cada empresa.

## 2. Dos formas de comenzar, por empresa

### A. Saldos de apertura desde una fecha

1. Elegir fecha de corte inclusiva, fuente y plan de cuentas.
2. Importar balance de comprobación CSV/XLSX o capturar saldos respaldados por estados financieros. Un PDF es respaldo para revisión, no una importación contable automática confirmada.
3. Mapear a cuentas de movimiento; revisar sumas, clasificación y cuentas pendientes.
4. Conciliar los auxiliares necesarios para operar: cartera por tercero/documento, bancos, inventario por producto/almacén, activos y obligaciones según aplique.
5. Confirmar apertura con permiso y constancia de quién revisó. Comenzar operaciones nuevas al día siguiente del corte.

Ejemplo ficticio: corte 31/12/2025; los saldos incluyen ese día y las operaciones nuevas empiezan 01/01/2026. No se copian facturas de 2025 como ventas nuevas. No usar este ejemplo como apertura del piloto real.

### B. Reconstrucción detallada

Elegir el rango histórico, importar documentos o asientos del sistema anterior en lotes con vista previa, y conciliar por período. Si el rango no empieza con la constitución/inicio efectivo de la empresa, necesita un saldo de apertura anterior al rango. “Exhaustivo” no significa asumir que el saldo inicial es cero.

Cada período muestra cobertura, fuentes, errores y estado de revisión. No reemitir XML, reservar secuencias actuales o generar cobros/stock por importar un documento histórico. Sus efectos se habilitan únicamente en la reconstrucción controlada y conforme a las reglas aprobadas.

### Completar detalles progresivamente

La ruta A puede incorporar respaldos y auxiliares históricos después. Vincularlos al saldo de apertura **no crea otro asiento, ingreso, IVA, cobro ni stock**. La ruta B no puede solaparse con un saldo ya incluido en la apertura: cambiar la estrategia requiere reconciliación y una versión aprobada, no un selector que recalcula silenciosamente todo.

## 3. Qué se puede obtener de los estados financieros

| Fuente disponible | Qué permite | Qué no debe inferirse |
|---|---|---|
| Balance de comprobación al corte | Mapear saldos de cuentas a apertura. | Que todas las cuentas tienen auxiliares conciliados. |
| Estado de situación financiera resumido | Punto de partida por rubros, con detalle adicional cuando haga falta. | El tercero, número, vencimiento o tarifa de cada documento. |
| Estado de resultados acumulado del ejercicio hasta el corte | Completar ingresos, costos y gastos del año para continuidad y reportes. | Que el resultado del ejercicio deba cargarse otra vez si ya está representado en cuentas de resultado. |
| Documentos, libros y declaraciones anteriores | Cubrir obligaciones y saldos tributarios del período según fuente/revisión. | Autorización SRI por adjuntar un PDF, ni aceptación de una declaración por generar un archivo. |

El balance de comprobación es preferible a un estado resumido. Una cuenta de grupo no recibe un asiento: se requiere desglose o mapeo explícito a una cuenta de movimiento aprobada. No inventar cuentas, capital, terceros ni una “diferencia de apertura” para forzar el cuadre.

Para comenzar a mitad de año, conciliar el estado de situación con los ingresos/costos/gastos acumulados y el resultado del ejercicio, sin contar este último dos veces. Para cerrar el año o preparar el 101, un balance patrimonial aislado no basta. Si no existe esa información, el reporte anual es parcial/provisional aunque la apertura esté cuadrada.

## 4. Saldos y auxiliares, sin doble contabilización

Ejemplo ficticio de apertura:

| Cuenta ilustrativa | Debe USD | Haber USD |
|---|---:|---:|
| Bancos | 5.000,00 | 0,00 |
| Clientes | 3.000,00 | 0,00 |
| Inventario | 2.000,00 | 0,00 |
| Proveedores | 0,00 | 2.500,00 |
| Capital | 0,00 | 6.500,00 |
| Resultados acumulados | 0,00 | 1.000,00 |
| **Total** | **10.000,00** | **10.000,00** |

Las cuentas y cifras son didácticas, no una matriz o capital sugeridos para un cliente.

- Clientes: las facturas pendientes por 2.000 y 1.000 explican el débito de 3.000. Registrarlas como auxiliar no genera 3.000 adicionales de ventas o cartera. Un cobro posterior de 500 deja cartera de 2.500 y aumenta el banco; no vuelve a reconocer ingreso/IVA de la venta histórica.
- Proveedores: conservar tercero, documento, moneda, saldo pendiente y vencimiento; el pago posterior cancela ese saldo sin duplicar la compra/gasto.
- Inventario: cantidad por producto/almacén y costo al corte deben reconciliarse con 2.000. Diez unidades de ejemplo a 200 no son una nueva compra. No duplicar el stock que ya exista en la aplicación; comparar antes de activar.
- Bancos: saldo por cuenta, extracto al corte y partidas pendientes. La carga del extracto anterior sirve para conciliar; no suma sus movimientos otra vez sobre la apertura.
- Activos: costo, depreciación acumulada y datos operativos cuando la empresa necesite depreciar posteriormente. No deducirlos de un único neto sin confirmación.
- Tributario: créditos, retenciones y obligaciones anteriores con fuente, período e importe confirmado. El saldo contable de IVA no determina por sí solo cada casillero ni cada dato del ATS.

Una apertura contable confirmada puede tener auxiliares todavía por completar, si el contador confirma su importe. Esa situación debe ser visible y limitar las acciones que requieren ese detalle; por ejemplo, no registrar un cobro aplicado a una factura inexistente. No bloquear indiscriminadamente toda la facturación.

## 5. Modelo funcional y estados propuestos

**ConfiguracionInicioContable** por empresa: `modalidad` (`saldos`/`historial`), `fecha_corte`, `operaciones_desde`, `historial_desde`, `historial_hasta`, `version`, autor y fechas. `operaciones_desde` debe ser coherente con el corte; ningún rango se supone completo por seleccionar una fecha.

**Apertura**: empresa, corte, moneda, fuente, archivo privado/huella, estado, versión, totales, revisado por/en, confirmado por/en y asiento vinculado. Estados: `borrador`, `en_revision`, `confirmada`, `sustituida` o `reversada`. Una sola base inicial efectiva para el mismo libro/rango; no crear una segunda apertura activa que acumule la primera.

**LineaApertura**: cuenta de movimiento, debe/haber, referencia de origen y mapeo. Importes decimales; desconocido = `null`, no cero. Validar signo, duplicados/mapeo, cuentas de empresa, cuentas activas, totales y diferencia. Agrupar filas del mismo destino solo mediante una decisión explícita visible en la vista previa.

**AuxiliarApertura**: cuenta/tercero/documento o producto/almacén/costo o banco según naturaleza, saldo al corte, saldo aplicado y vínculo a la apertura. Debe reconciliarse con su cuenta sin emitir un segundo efecto contable. La aplicación posterior usa las reglas e idempotencia de cobros/pagos existentes.

**Cobertura** por empresa, ámbito y período: contabilidad, documentos tributarios, cartera, inventario y bancos. Indicar fuente y cobertura; `pendiente`, `parcial` o `conciliada`. No confundir estos estados con autorización fiscal o licencia.

Correcciones: borrador editable con `version`; confirmado inmutable por edición ordinaria. Un ajuste o sustitución conserva historial y vínculo; si hay movimientos posteriores, comprobar su impacto antes de reabrir/reconstruir. Nunca borrar el asiento inicial y dejar sus cobros, pagos o movimientos huérfanos.

**Cómo quedó en el código (corte 1).** `ConfiguracionInicioContable` es `InicioContable` (una fila por empresa, que además es el candado del libro) y añade `contabilidad_desde` (primer día que admite asientos ordinarios) y `guarda_importacion` (apagada; se enciende en el corte 2). La apertura añade el estado `descartada` (un borrador o una apertura en revisión que se abandona, con motivo; nada se borra). El asiento inicial vive en el libro diario (`Asiento` y `LineaAsiento`, solo inserción). Las tablas de auxiliares, cobertura por mes, aplicaciones, ajustes y vínculos históricos ya existen y están vacías: las llena el corte 2.

## 6. Contrato API (definitivo para lo que construye el corte 1)

Todo bajo `/contabilidad/api/`, detrás del complemento como el resto de `/contabilidad/` (ninguna ruta nueva cambia quién entra). Solo API JSON: no hay páginas nuevas ni entradas de menú; las pantallas las conecta Codex.

### 6.1 Reglas comunes

Son las de `CONTRATO-CONTABLE-V9.md` («Reglas comunes» y «Rutas nuevas de `/contabilidad/api/`»), con estas precisiones:

- **`empresa` en la consulta, también en los envíos JSON** (`?empresa=<id>`). El cuerpo puede repetirla; si una de las dos no es la empresa activa, 409 `empresa_cambiada`. Un envío sin `empresa` en ningún lado, 409 `sin_empresa`.
- **Orden de las negativas:** `empresa_cambiada` → licencia (403, la responde `PlanMiddleware`) → `sin_empresa` → permiso (403 `sin_permiso`) → datos por completar (409) → `clave` repetida (200 `repetido` o 409 `clave_usada`) → `version` (409) → estado del recurso (409) → conflicto con otros datos (409) → validación (400). La clave va antes que la versión: el reintento de un envío ya aplicado trae la versión vieja y recibe el mismo resultado.
- **Fuera del orden: 409 `reintentar`** (desde `72a68ee`), en cualquier ruta nueva de `/contabilidad/api/` (las de
  `ApiContable`: cuentas, importación del plan, diario, inicio, apertura y capacidades). Las del kardex y del inventario
  (`api/kardex/…` y `api/inventario/`), que son de la versión publicada y no usan `ApiContable`, no lo responden: allí un
  interbloqueo sigue siendo un 500. Si PostgreSQL aborta la transacción por un interbloqueo (SQLSTATE `40P01`) o porque
  un bloqueo no se consiguió a tiempo (`55P03`: `lock_timeout` o `NOWAIT`), la respuesta es exactamente
  `{"error": "Otra operación usaba los mismos datos al mismo tiempo: no se guardó nada. Vuelve a intentarlo.", "codigo": "reintentar"}`,
  sin más campos (ejemplo en §6.7). Nada quedó guardado (la transacción se deshizo entera) y repetir el mismo envío, con la
  misma `clave` y la misma `version`, es seguro: no hace falta recargar. La interfaz muestra `error` y deja repetir el
  envío tal cual. Queda un aviso (WARNING, con la traza) en el registro `core.contabilidad.api`: «Cruce de bloqueos
  (<sqlstate>) en <MÉTODO> <ruta>: la transacción se deshizo». Cualquier otro error de la base sigue siendo un 500. Antes,
  un interbloqueo salía como 500.
- **Una diferencia con la especificación del bloque, a favor de la pestaña:** con el complemento cerrado o el plan vencido, un envío armado para otra empresa que la lleva **solo** en el cuerpo JSON recibe el 409 `empresa_cambiada`, no el 403 de licencia. El bloque 1 lee `empresa` también del cuerpo JSON (`core/tenancy/pestanas.py`) y eso no se tocó.
- **Importes** como texto con dos decimales; **desconocido = `null`**, nunca `"0.00"`. Fechas `AAAA-MM-DD`, meses `AAAA-MM`. Instantes ISO 8601 en UTC (`"2026-11-14T14:30:03.654056+00:00"`), como los cobros. Los autores (`creado_por`, `enviado_por`, `confirmado_por`…) son el nombre de usuario guardado con la fila al escribirla: si el usuario se borra, el nombre se conserva.
- **Importes escritos como texto** (desde `72a68ee`): en mapear (`lineas.<i>.debe|haber`), en las filas del lote
  (columnas debe, haber o saldo: al importar, la fila queda en `error`, con el texto en su lista `errores`; al mapear
  desde ese lote, 400 con `filas.<n>.debe`, `filas.<n>.haber` o `filas.<n>.saldo`) y en el PATCH (`resultado_acumulado`,
  con su propio texto). Después de quitar `$`, los espacios y el espacio duro, solo valen el signo, cifras ASCII, `.` y
  `,`: `1.234,56`, `1,234.56`, `1234,56`, `$ 1 234,56` y `+1234.56` se leen 1234.56. Lo demás es «Escribe un importe
  válido.»: `1e3`, `1E3`, `1_000`, cifras de otras escrituras (`１２３`), la notación científica que escribe una hoja de
  cálculo en un CSV (`1,23457E+11`), `NaN` e `Infinity`. La única notación científica que se lee, venga del XLSX, del
  CSV o de un texto JSON, es la de la forma `d.ddd…e-NN` o `de-NN`, con un `-` delante opcional (minúscula y con
  exponente negativo de dos o tres cifras), que es la que trae una celda numérica del XLSX con el ruido de una
  fórmula que da cero: `5.551115123125783e-17` se lee `0.00` (y en mapear, como todo cero, da «El saldo debe ser mayor
  que cero; si no lo conoces, déjalo vacío.»), y `1e-05` da «Usa dos decimales.», como antes. Los números de un envío
  JSON no cambian.
  Antes, `1e3`, `1_000` y `１２３` se leían como importes.
- **Textos libres** (desde `72a68ee`): `fuente_detalle` (al crear y en el PATCH), `ambitos_no_aplican.<i>.nota`,
  `lineas.<i>.rubro` en la captura directa de mapear, `decisiones.<i>.motivo` al mapear desde un lote, `motivo` de
  descartar, devolver y anular un respaldo, `nota` de confirmar y `descripcion` de un respaldo; y, desde `7a5c567`, el
  código y el rubro de cada fila de un lote (abajo). Primero se colapsan los espacios: todo lo que Python trata como
  espacio pasa a ser un espacio (el tabulador, U+000A a U+000D —salto de línea, tabulador vertical, salto de página y
  retorno—, U+001C–U+001F, U+0085, el espacio duro y los demás espacios de Unicode). Después, un texto con un carácter
  de U+0000 a U+0008, de U+000E a U+001B, U+007F o una mitad suelta de un par sustituto (U+D800–U+DFFF) es 400
  `validacion` con el error en su campo: «Quita los caracteres de control o no válidos de este texto (suelen llegar al
  copiarlo de otro programa).» (`caracteres_de_control` es solo el nombre interno de ese texto: no sale en la
  respuesta). Se admiten U+00AD, U+200B, U+FEFF y los emoji compuestos con ZWJ. Si el texto además es demasiado largo,
  sale solo el error de largo. Antes, en PostgreSQL, un NUL terminaba en 500. (`72a68ee`):

  ```
  POST /contabilidad/api/apertura/1/mapear/?empresa=1
  {"empresa": 1, "version": 1, "lineas": [{"cuenta_id": 2, "rubro": "Caja\u0000chica", "debe": "10.00", "haber": null}, …]}

  400 {"error": "Revisa los datos marcados.",
       "codigo": "validacion",
       "errores": {"lineas.0.rubro": ["Quita los caracteres de control o no válidos de este texto (suelen llegar al copiarlo de otro programa)."]}}
  ```

  **En un lote** (desde `7a5c567`; DOC44-2 de la verificación del cierre). El código y el rubro de cada fila llegan a la
  línea (`codigo_origen`, `rubro` y `filas_origen`) y el rubro, al confirmar, al concepto de las líneas del asiento
  inicial, que ya no se cambia. Por eso se revisan con la misma regla, después de colapsar los espacios: un control en
  el código o en el rubro de una fila es un error de esa fila. Al importar, la respuesta sigue siendo 200 y la fila
  queda en `error`, con el texto en su lista `errores` (en `de_grupo` si su cuenta es un grupo, con los dos textos).
  Mapear desde ese lote responde 400 `validacion` con `filas.<n>.codigo` o `filas.<n>.rubro` y no escribe ninguna línea
  (`cuenta_de_grupo` si además alguna fila va a un grupo). En el lote no hay error de largo: el código se recorta a 60 y
  el rubro a 200, como antes. Una fila omitida no se revisa: no llega a la línea. El NUL ya lo rechazaba el lector, con
  el archivo entero (400 `formato`). Antes, un CSV con «Caja<BEL>chica» se importaba, se mapeaba, se enviaba y se
  confirmaba, y el asiento inicial quedaba con ese control en el concepto. (`7a5c567`, un CSV con `Caja\u0007chica` en
  el rubro de la fila 3 y `3.1.01\u001b` en el código de la fila 4):

  ```
  POST /contabilidad/api/apertura/1/mapear/?empresa=1
  {"empresa": 1, "version": 1, "lote_id": 1, "decisiones": [{"fila": 2, "omitir": true, "motivo": "Subtotal"}]}

  400 {"error": "Revisa los datos marcados.",
       "codigo": "validacion",
       "errores": {"filas.3.rubro": ["Quita los caracteres de control o no válidos de este texto (suelen llegar al copiarlo de otro programa)."],
                   "filas.4.codigo": ["Quita los caracteres de control o no válidos de este texto (suelen llegar al copiarlo de otro programa)."]}}
  ```

  Lo que el lector (`lectura_tabular.py`, compartido con C3) sigue dejando pasar son los controles que no son NUL en las
  demás celdas: las de las columnas que no se eligen y los encabezados. Se guardan en el lote; en su respuesta, los
  encabezados salen en `encabezados` y las cinco primeras filas en `muestra`. No llegan a la línea ni al asiento:
  `filas_origen` solo lleva la fila, el código, el rubro, el debe y el haber. Un control en una celda de importe deja la
  fila en `error` con «Escribe un importe válido.», salvo los que Python trata como espacio (el tabulador, por ejemplo)
  al principio o al final de la celda: esos se quitan, como los espacios.
- **Errores:** 400 `{"error", "codigo", "errores": {campo: [textos]}}` con todos los errores a la vez; en listas la clave lleva la posición enviada, base 0 (`"lineas.0.debe"`, `"decisiones.0.motivo"`, `"ambitos_no_aplican.0.nota"`). Inexistente o de otra empresa: 404 `{"codigo": "no_existe"}` (salvo las rutas de cuentas del bloque 1, que siguen con `"codigo": "cuenta"`). Conflicto de estado: 409 `{"codigo": "estado", "estado": actual, "permitidos": [...]}`. `version` vieja: 409 `version` con el recurso como está ahora.
- **Paginación:** `?pagina=1&por_pagina=100` (máximo 500) → `"paginacion": {"pagina", "por_pagina", "total", "paginas"}`; `paginas` vale al menos 1.
- **Reportes y coberturas:** `provisional` (booleano), `causas` (textos) y `causas_detalle` (`[{"codigo", "texto", "cantidad"?}]`, con códigos estables; sección 6.8).
- **Enlaces:** `url` solo lleva páginas que ya existen. Lo que no tiene página (un respaldo, un lote, una apertura) va con `"url": null` y `"recurso": {"tipo", "id", "api"}`, con su ruta de API. Codex añade la página cuando la conecte.
- **`capacidades`** de cada recurso: booleanos que ya combinan permiso, estado y licencia (con el plan vencido, todo `false`).

### 6.2 Permisos

Sin página nueva: los permisos cuelgan del módulo «Kardex por producto», como los del plan de cuentas.

| Permiso | Para qué | Propietario, Administrador, Contador | Consulta | Vendedor, Cliente |
|---|---|---|---|---|
| `view_asiento` | leer el diario y su integridad | sí | sí | no |
| `view_apertura` | leer la apertura, sus líneas, lotes y respaldos | sí | sí | no |
| `add_apertura` | configurar, crear, editar, importar, mapear, subir y anular respaldos, validar, enviar y descartar | sí | no | no |
| `change_confirmacion_apertura` | devolver a borrador y confirmar | sí | no | no |
| `add_aplicacionauxiliar`, `change_aplicacionauxiliar` | cobros sobre saldos iniciales (sin ruta hasta el corte 2) | sí | no | no |

El Contador recibe solo esas escrituras (`ACCOUNTANT_WRITE`); ningún permiso de compras ni de importación. Clasificar cuentas pide `change_cuenta` (bloque 1). Los permisos declarados para bloques posteriores (`add_asiento`, `change_asiento`, `change_reverso_asiento`, los de período y ejercicio) no los recibe nadie.

### 6.3 Rutas

| Método y ruta | Permiso | Qué hace |
|---|---|---|
| `GET diario/?desde=&hasta=&tipo=&origen_tipo=&origen_id=&cuenta=&pagina=&por_pagina=` | `view_asiento` | asientos del rango con sus líneas; sin fechas, el mes en curso |
| `GET diario/<id>/` | `view_asiento` | un asiento |
| `GET integridad/?anio=` | `view_asiento` | comprobaciones del libro del año; sin `anio`, el año en curso |
| `POST cuentas/clasificar/` | `change_cuenta` | clase de una cuenta y, si se pide, de sus descendientes sin clase (C2 en V9) |
| `GET apertura/` | `view_apertura` | configuración, apertura, vigente, cobertura y capacidades |
| `POST apertura/` | `add_apertura` | configura el inicio y crea el borrador |
| `GET apertura/<id>/` · `PATCH apertura/<id>/` | `view_apertura` · `add_apertura` | detalle · encabezado del borrador |
| `POST apertura/<id>/importar/` · `GET apertura/importar/<lote>/` | `add_apertura` · `view_apertura` | sube el balance (vista previa) · recarga el lote |
| `POST apertura/<id>/mapear/` | `add_apertura` | fija las líneas (desde el lote o captura directa) |
| `GET apertura/<id>/lineas/?pagina=&por_pagina=` | `view_apertura` | las líneas, paginadas |
| `POST apertura/<id>/respaldos/` | `add_apertura` | sube un respaldo |
| `GET apertura/respaldos/<id>/descargar/` · `POST apertura/respaldos/<id>/anular/` | `view_apertura` · `add_apertura` | descarga · anula |
| `POST apertura/<id>/descartar/` | `add_apertura` | borrador o en revisión → descartada |
| `POST apertura/<id>/validar/` | `add_apertura` | bloqueos, advertencias, cobertura y reportes; no escribe nada |
| `POST apertura/<id>/enviar/` | `add_apertura` | borrador → en revisión, solo sin bloqueos |
| `POST apertura/<id>/devolver/` | `change_confirmacion_apertura` | en revisión → borrador, con motivo |
| `POST apertura/<id>/confirmar/` | `change_confirmacion_apertura` | en revisión → confirmada, con el asiento inicial |

GET sin parámetros de ruta, todos con 200 por defecto (`tests/test_rutas.py`): `diario/` (mes en curso), `integridad/` (año en curso) y `apertura/`; sin inicio contable también responden 200, con sus causas. `cuentas/clasificar/` es solo POST y está en `ESPERADOS` con 405.

**Pendiente del corte 2** (no existen todavía; las capacidades `sustituir`, `ajustar`, `reversar` y `cobrar` responden `false`): `apertura/<id>/auxiliares/`, `apertura/auxiliares/<id>/anular|vincular|desvincular|completar|partidas/`, `apertura/partidas/<id>/anular/`, `apertura/cobertura/` (GET con `anio` y POST de lo declarado por mes), `apertura/cartera/…` y sus aplicaciones, `apertura/<id>/impacto/`, `apertura/<id>/ajustes/`, `apertura/ajustes/<id>/reversar/`, `apertura/<id>/sustituir/`, `apertura/<id>/reversar/`, `apertura/historico/…` y `apertura/guarda-importacion/`. Sus formas están en la especificación del bloque (`contable/bloque-2-especificacion.md`, Partes C a F) y pueden cambiar al construirlas.

### 6.4 Libro diario

El libro es de solo inserción: un asiento confirmado no se edita ni se borra, se reversa (en este corte ninguna ruta reversa; el único asiento que se crea es el de la apertura). Lo garantizan el servicio único `core/contabilidad/diario.py`, las guardas de los modelos y, en PostgreSQL, disparadores.

`GET diario/` devuelve los asientos del rango ordenados por fecha y número. `estado` es `vigente`, `reversado` o `reverso`; `numero` es `AAAA-NNNNNN` (correlativo por empresa y año, sin huecos); `origen` es `null` en un asiento sin origen; `huella` es el SHA-256 del contenido del asiento. `totales` suma el rango entero, no solo la página.

Con la apertura confirmada, el rango que llega hasta el corte:

```
GET /contabilidad/api/diario/?desde=2025-12-01&hasta=2025-12-31&empresa=1

200 {"desde": "2025-12-01",
     "hasta": "2025-12-31",
     "asientos": [{"id": 1,
                   "numero": "2025-000001",
                   "fecha": "2025-12-31",
                   "tipo": "apertura",
                   "concepto": "Apertura contable al 31/12/2025",
                   "motivo": "",
                   "origen": {"tipo": "apertura", "id": 2, "evento": "confirmacion", "numero": null, "fecha": null},
                   "estado": "vigente",
                   "reversa_de": null,
                   "reversado_por": null,
                   "totales": {"debe": "10000.00", "haber": "10000.00"},
                   "lineas": [{"orden": 1,
                               "cuenta": {"id": 3, "codigo": "1.1.02", "nombre": "Bancos"},
                               "concepto": "Bancos",
                               "debe": "5000.00",
                               "haber": "0.00",
                               "tercero": null,
                               "documento": null},
                              {"orden": 2,
                               "cuenta": {"id": 4, "codigo": "1.1.03", "nombre": "Clientes"},
                               "concepto": "Clientes",
                               "debe": "3000.00",
                               "haber": "0.00",
                               "tercero": null,
                               "documento": null},
                              {"orden": 3,
                               "cuenta": {"id": 5, "codigo": "1.1.04", "nombre": "Inventario de mercaderías"},
                               "concepto": "Inventario de mercaderías",
                               "debe": "2000.00",
                               "haber": "0.00",
                               "tercero": null,
                               "documento": null},
                              {"orden": 4,
                               "cuenta": {"id": 9, "codigo": "2.1.01", "nombre": "Proveedores"},
                               "concepto": "Proveedores",
                               "debe": "0.00",
                               "haber": "2500.00",
                               "tercero": null,
                               "documento": null},
                              {"orden": 5,
                               "cuenta": {"id": 11, "codigo": "3.1.01", "nombre": "Capital social"},
                               "concepto": "Capital social",
                               "debe": "0.00",
                               "haber": "6500.00",
                               "tercero": null,
                               "documento": null},
                              {"orden": 6,
                               "cuenta": {"id": 12, "codigo": "3.1.02", "nombre": "Resultados acumulados"},
                               "concepto": "Utilidades de años anteriores",
                               "debe": "0.00",
                               "haber": "1000.00",
                               "tercero": null,
                               "documento": null}],
                   "creado_por": "propietario.a",
                   "creado_en": "2026-11-14T14:30:03.072447+00:00",
                   "huella": "45ab214ecbf0e86a370e2d331e02f0a32c756b90ae3f3fbb2ffb16e3a10add50"}],
     "totales": {"debe": "10000.00", "haber": "10000.00", "asientos": 1},
     "provisional": false,
     "causas": [],
     "causas_detalle": [],
     "paginacion": {"pagina": 1, "por_pagina": 100, "total": 1, "paginas": 1}}
```

El mes en curso sigue provisional aunque la apertura esté confirmada: ninguna venta, compra ni cobro se contabiliza todavía (`motor_pendiente`, obligatoria en todo rango que pase del corte):

```
GET /contabilidad/api/diario/?empresa=1

200 {"desde": "2026-11-01",
     "hasta": "2026-11-30",
     "asientos": [],
     "totales": {"debe": "0.00", "haber": "0.00", "asientos": 0},
     "provisional": true,
     "causas": ["Los documentos de la operación todavía no se contabilizan."],
     "causas_detalle": [{"codigo": "motor_pendiente", "texto": "Los documentos de la operación todavía no se contabilizan."}],
     "paginacion": {"pagina": 1, "por_pagina": 100, "total": 0, "paginas": 1}}
```

Sin inicio contable:

```
GET /contabilidad/api/diario/?empresa=1

200 {"desde": "2026-11-01",
     "hasta": "2026-11-30",
     "asientos": [],
     "totales": {"debe": "0.00", "haber": "0.00", "asientos": 0},
     "provisional": true,
     "causas": ["La empresa todavía no configuró su inicio contable: falta la modalidad y la fecha de corte.",
                "Los documentos de la operación todavía no se contabilizan."],
     "causas_detalle": [{"codigo": "inicio_sin_configurar",
                         "texto": "La empresa todavía no configuró su inicio contable: falta la modalidad y la fecha de corte."},
                        {"codigo": "motor_pendiente", "texto": "Los documentos de la operación todavía no se contabilizan."}],
     "paginacion": {"pagina": 1, "por_pagina": 100, "total": 0, "paginas": 1}}
```

`GET diario/<id>/` responde `{"asiento": {…}}` con la misma forma que cada elemento de `asientos`. Filtros: `tipo` (`apertura`, `origen`, `manual`, `ajuste`, `reverso`, `cierre`, `historico`), `origen_tipo`, `origen_id` y `cuenta` (los asientos que tienen alguna línea en esa cuenta). Negativas:

```
GET /contabilidad/api/diario/?desde=2025-13-01&hasta=ayer&empresa=1

400 {"error": "Revisa los datos marcados.",
     "codigo": "validacion",
     "errores": {"desde": ["Escribe la fecha como AAAA-MM-DD."], "hasta": ["Escribe la fecha como AAAA-MM-DD."]}}
```

```
GET /contabilidad/api/diario/999999/?empresa=1

404 {"error": "El asiento no existe o es de otra empresa.", "codigo": "no_existe"}
```

`GET integridad/` hace siete comprobaciones con consultas agregadas: `cuadre` (cada asiento y sus líneas suman igual), `numeracion` (sin huecos ni repetidos), `huellas` (la huella guardada es la del contenido), `acumulados` y `acumulados_por_tipo` (los saldos por cuenta y mes coinciden con las líneas, también las columnas de apertura y de cierre), `apertura_unica` (un solo asiento de apertura vigente, el de la apertura confirmada) y `sellados`. `detalle` lleva como mucho 100 entradas por comprobación. Lo mismo hace la orden `manage.py verificar_libro --empresa <id> --anio <año>`.

```
GET /contabilidad/api/integridad/?anio=2025&empresa=1

200 {"anio": 2025,
     "asientos": 1,
     "comprobaciones": [{"codigo": "cuadre", "ok": true, "detalle": []},
                        {"codigo": "numeracion", "ok": true, "detalle": []},
                        {"codigo": "huellas", "ok": true, "detalle": []},
                        {"codigo": "acumulados", "ok": true, "detalle": []},
                        {"codigo": "acumulados_por_tipo", "ok": true, "detalle": []},
                        {"codigo": "apertura_unica", "ok": true, "detalle": []},
                        {"codigo": "sellados", "ok": true, "detalle": []}]}
```

```
GET /contabilidad/api/integridad/?anio=1999&empresa=1

400 {"error": "Revisa los datos marcados.", "codigo": "validacion", "errores": {"anio": ["Escribe un año entre 2000 y 2100."]}}
```

### 6.5 Inicio contable y apertura: estados y reglas

Estados de la apertura: `borrador → en_revision → confirmada`; `en_revision → borrador` (devolver, con motivo); `borrador | en_revision → descartada` (con motivo). Solo el borrador se edita. Como mucho una confirmada y una en preparación por empresa. `sustituida` y `reversada` existen en el modelo y las alcanza el corte 2.

Lo que el servidor hace cumplir:

1. **Inicio.** `saldos`: `contabilidad_desde = operaciones_desde = fecha_corte + 1`. `historial`: `historial_desde`–`historial_hasta` (hasta ayer como mucho); `fecha_corte = historial_desde − 1`, `contabilidad_desde = historial_desde` y `operaciones_desde = historial_hasta + 1`; la apertura es el saldo anterior al rango. El corte no puede ser futuro; el del día de hoy se admite en borrador y no se confirma hasta que el día termine (`fecha_corte_futura`). Corte del año 2000 en adelante.
2. **Sin saldo anterior no se supone cero.** Hasta confirmar, la cobertura de contabilidad es `pendiente` (`apertura_sin_confirmar`; en historial, `saldo_anterior_sin_confirmar`) y todo reporte sale provisional. La única apertura sin líneas es la de fuente `inicio_actividades` con `sin_saldos: true` y `fuente_detalle` obligatorio: se confirma sin asiento y queda con totales `0.00`.
3. **Solapamiento:** no se fija ni se mueve un corte igual o posterior a la fecha de un asiento ordinario o de una aplicación vigente (409 `rango_solapado` con cuántos y la primera fecha). Con una apertura confirmada la configuración no cambia (409 `apertura_confirmada`): cambiarla será una sustitución (corte 2).
4. **Líneas:** una cuenta de movimiento activa de la empresa por línea, con un solo lado mayor que cero o los dos `null` (desconocido). Las líneas no se borran: mapear da de alta, cambia o retira por cuenta y conserva el id; una línea retirada tiene los importes en `null` y queda fuera de totales, validación y asiento (pero las rutas que listan líneas la devuelven: §6.6, mapear y `GET apertura/<id>/lineas/`). `detalle` es la copia de `cuenta.auxiliar` que se toma al escribir la línea, pero **mientras la apertura está en `borrador` o `en_revision` vale el auxiliar que la cuenta declara ahora** (desde `72a68ee`; antes valía siempre la copia, y un auxiliar cambiado en revisión no se exigía al confirmar). La Parte A deja cambiar el auxiliar de una cuenta también con la apertura en revisión. Lo usan validar, enviar y confirmar (`auxiliar_incompleto`, `auxiliar_no_concilia`, `sin_cuenta_declarada` y `cuenta_no_aplica`), `detalle` y `auxiliares.estado` de `GET apertura/<id>/lineas/` y de la respuesta de mapear, la cobertura de `GET apertura/` y de validar, el 400 del PATCH de los ámbitos (`errores["ambitos_no_aplican.<i>.ambito"]`, «Hay cuentas con ese detalle en la apertura: no puede declararse que no aplica.») y el aviso `auxiliares_incompletos` de capacidades. Confirmar fija `detalle` con el auxiliar con que se acaba de validar, con el candado del libro tomado (un PATCH del auxiliar de esa cuenta espera a que termine la confirmación), y el evento `confirmada` lo dice en `detalle_fijado`. Desde entonces vale la copia: un cambio posterior del auxiliar, que la Parte A permite, no cambia la apertura confirmada.
5. **Bloqueos de enviar y confirmar**, en este orden (el primero da el `codigo` de la respuesta): `sin_lineas` · `sin_saldos_con_lineas` · `cuenta_sin_mapear` · `cuenta_de_grupo` · `cuenta_inactiva` · `cuenta_no_aplica` · `importe_pendiente` · `cuenta_sin_clase` · `apertura_desbalanceada` · `importe_total_excedido` · `auxiliar_no_concilia` · (`auxiliar_duplica_operativo`) · `vinculo_roto` · `auxiliar_incompleto` (solo al confirmar) · (`saldo_inicial_posterior`) · `resultado_sin_declarar` · `resultado_duplicado` · `rango_solapado` · `periodo_cerrado` · `fecha_corte_futura`. `auxiliar_duplica_operativo` y `saldo_inicial_posterior` tienen su sitio en el orden y no se evalúan en este corte: ninguna ruta crea auxiliares. Los dos que añadió el cierre del corte (`72a68ee`; no están en la especificación):
   - **`cuenta_no_aplica`**, justo después de `cuenta_inactiva`: una línea no retirada va a una cuenta cuyo auxiliar (el de ahora, regla 4) es el de un ámbito que la apertura declara en `ambitos_no_aplican`; pasa cuando la cuenta recibe ese auxiliar después de mapear. Mapear y el PATCH de los ámbitos ya lo rechazaban por campo (400); este bloqueo es la misma regla cuando la cuenta cambia después. Forma: `{"codigo": "cuenta_no_aplica", "texto", "lineas": [ids], "ambitos": [ámbitos en orden alfabético]}`, con el texto «{n} línea(s) van a una cuenta con detalle de {ámbitos}, y la apertura declara que ese detalle no aplica: quita la declaración o el auxiliar de la cuenta.» (los ámbitos con su nombre, separados por «, »). (`72a68ee`, la caja pasa a declarar `cliente` con la apertura en revisión y `clientes` declarado «no aplica»):

     ```
     {"codigo": "cuenta_no_aplica",
      "texto": "1 línea(s) van a una cuenta con detalle de clientes, y la apertura declara que ese detalle no aplica: quita la declaración o el auxiliar de la cuenta.",
      "lineas": [1],
      "ambitos": ["clientes"]}
     ```
   - **`importe_total_excedido`**, justo después de `apertura_desbalanceada` (pueden salir los dos): el debe o el haber de la apertura llega a 10^14, que no cabe en un asiento (`diario.TOTAL_MAX`; cada línea admite hasta 999 999 999 999,99). Forma: `{"codigo": "importe_total_excedido", "texto": "El total de la apertura (debe {debe}, haber {haber}) no cabe en un asiento: cada lado admite hasta {maximo}. Revisa los importes en la fuente.", "debe", "haber", "maximo": "99999999999999.99"}`. Antes, validar y enviar la daban por buena y confirmar terminaba en el 400 `importe` del diario; ahora sale en validar y como 409 en enviar y confirmar (que la revalida con el candado).

   En enviar y confirmar, el primer bloqueo es un 409 con su `codigo`, su detalle arriba (`lineas` y `ambitos`; `debe`, `haber` y `maximo`) y la lista completa.
6. **Resultado del ejercicio.** N = Σ (haber − debe) de las líneas en cuentas de ingreso, costo o gasto; P = lo mismo de las líneas con `es_resultado_ejercicio` (solo en cuentas de patrimonio). N ≠ 0 y P ≠ 0 → `resultado_duplicado`. Con N ≠ 0 vale `resultado_ejercicio` vacío o `en_cuentas_nominales`; con N = 0 y P ≠ 0, vacío o `en_patrimonio`, y los estados de resultados y el 101 de ese ejercicio llevan la causa `resultados_acumulados_sin_detalle`. Una declaración que contradice las líneas, o un `resultado_acumulado` distinto de N o de P, es `resultado_duplicado` con las dos cifras. **Con N = 0 y P = 0** (desde `72a68ee`; antes se aceptaba cualquier declaración): declarar `en_cuentas_nominales` o `en_patrimonio`, o un `resultado_acumulado` que no es nulo ni `0.00`, contradice las líneas y es `resultado_duplicado` con `{"en_cuentas_nominales": "0.00", "en_patrimonio": "0.00", "declarado", "resultado_acumulado"}`, también a 31/12; en ese caso sustituye a `resultado_sin_declarar`, y declarar `en_patrimonio` ya no evita la nota que exige `no_aplica`. Con N = P = 0 valen: vacío (solo a 31/12), `no_aplica` (a 31/12 sin más; a mitad de año, con la nota de la revisión al confirmar) y la cifra nula o `0.00`. No cambian los códigos ni los textos. **N = 0 se juzga por la cifra, no por las líneas:** cuentas nominales que se compensan al centavo (ingresos iguales a costos y gastos), o líneas marcadas con `es_resultado_ejercicio` que se anulan, cuentan como N = P = 0. Se declaran `no_aplica` (a mitad de año, con la nota) o se deja vacío a 31/12; declarar `en_cuentas_nominales` o `en_patrimonio` es `resultado_duplicado` con `0.00` y `0.00`. Juzgar por las líneas (que haya cuentas nominales o marcadas) cambiaría la regla de B2-AP-2: si la propietaria lo prefiere, es una decisión aparte, con su prueba en `TestAceptacion7` (C2C1V-AP-1 de la verificación del cierre, refutado por eso). N = 0, P = 0 y corte que no es 31/12: hay que declararlo (`no_aplica` exige la nota de la revisión al confirmar); vacío, `resultado_sin_declarar`, y advertencia `sin_resultados_acumulados`. Corte 31/12 con N ≠ 0: válida con la advertencia `ejercicio_sin_cerrar`. Al confirmar queda fijado lo que dicen las líneas.
7. **Un solo asiento inicial:** tipo `apertura`, fecha = corte, origen `('apertura', id, 'confirmacion')`, una línea por línea no retirada, sin tercero ni documento. Lo garantizan el candado del libro, el estado, `clave_confirmacion` y dos UNIQUE parciales.
8. **Auxiliar ≤ cuenta.** En este corte no hay auxiliares: toda línea cuya cuenta declara `auxiliar` (ahora, regla 4) está incompleta y, para confirmar, `incompletos_aceptados` tiene que ser exactamente el conjunto de esas líneas. Si no lo es, 409 `auxiliar_incompleto` con `"lineas"`, los ids que faltan (siempre, aunque esté vacía), y `"sobran"`, los ids aceptados de más (**solo si hay alguno**), arriba y dentro de su entrada de `bloqueos`, más `"advertencias"`; la forma está en §6.6, confirmar. Quedan `incompleto_aceptado` y la cobertura de contabilidad `parcial`.
9. Confirmar no llama al SRI, no envía correo y no crea ningún documento, cuenta por cobrar o por pagar, movimiento de kardex ni cambio de stock.

### 6.6 Rutas de la apertura, con ejemplos

Los ejemplos son respuestas reales de las rutas sobre una base de pruebas, con datos ficticios: la empresa 1 («EMPRESA A S.A.»), el plan mínimo de las pruebas (`tests/ayudas_contables.py`: caja 1.1.01, bancos 1.1.02 con auxiliar `banco`, clientes 1.1.03 con `cliente`, inventario 1.1.04 con `inventario`, crédito de IVA 1.1.05 con `tributario`, equipos 1.2.01 con `activo`, proveedores 2.1.01 con `proveedor`, capital 3.1.01, resultados acumulados 3.1.02…) y el balance didáctico de la sección 4. Usuario `propietario.a` (Propietario). Las respuestas largas recortan con «…» lo que repite una forma ya mostrada, y cada recorte lo dice.

#### `GET apertura/`

`apertura` es la que está en preparación si existe y, si no, la confirmada; `vigente` es siempre la confirmada o `null`. `acceso` es el objeto entero de `GET /contabilidad/api/capacidades/` (V9, «Capacidades»): se omite en los ejemplos. Sin configurar:

```
GET /contabilidad/api/apertura/?empresa=1

200 {"empresa": {"id": 1, "ruc": "0900000001001", "nombre": "EMPRESA A S.A."},
     "configuracion": null,
     "modalidad": null,
     "fecha_corte": null,
     "operaciones_desde": null,
     "apertura": null,
     "vigente": null,
     "cobertura": {"contabilidad": {"estado": "pendiente",
                                    "causas": ["La empresa todavía no configuró su inicio contable: falta la modalidad y la fecha de corte."],
                                    "causas_detalle": [{"codigo": "inicio_sin_configurar",
                                                        "texto": "La empresa todavía no configuró su inicio contable: falta la modalidad y la fecha de corte."}]},
                   "cartera": {"estado": "pendiente",
                               "causas": ["Ninguna cuenta de la apertura está declarada como de clientes.",
                                          "Ninguna cuenta de la apertura está declarada como de proveedores."],
                               "causas_detalle": [{"codigo": "sin_cuenta_declarada",
                                                   "texto": "Ninguna cuenta de la apertura está declarada como de clientes."},
                                                  {"codigo": "sin_cuenta_declarada",
                                                   "texto": "Ninguna cuenta de la apertura está declarada como de proveedores."}],
                               "clientes": {"estado": "pendiente", "cuenta": null, "detallado": null, "documentos": 0},
                               "proveedores": {"estado": "pendiente", "cuenta": null, "detallado": null, "documentos": 0}},
                   "inventario": {"estado": "pendiente",
                                  "causas": ["Ninguna cuenta de la apertura está declarada como de inventario."],
                                  "causas_detalle": [{"codigo": "sin_cuenta_declarada",
                                                      "texto": "Ninguna cuenta de la apertura está declarada como de inventario."}],
                                  "cuenta": null,
                                  "detallado": null,
                                  "filas": 0},
                   "bancos": {"estado": "pendiente",
                              "causas": ["Ninguna cuenta de la apertura está declarada como de bancos."],
                              "causas_detalle": [{"codigo": "sin_cuenta_declarada",
                                                  "texto": "Ninguna cuenta de la apertura está declarada como de bancos."}],
                              "cuenta": null,
                              "detallado": null,
                              "filas": 0},
                   "activos": {"estado": "pendiente",
                               "causas": ["Ninguna cuenta de la apertura está declarada como de activos fijos."],
                               "causas_detalle": [{"codigo": "sin_cuenta_declarada",
                                                   "texto": "Ninguna cuenta de la apertura está declarada como de activos fijos."}],
                               "cuenta": null,
                               "detallado": null,
                               "filas": 0},
                   "tributario": {"estado": "pendiente",
                                  "causas": ["No hay saldos tributarios anteriores registrados: sus arrastres quedan sin dato."],
                                  "causas_detalle": [{"codigo": "tributario_sin_saldos",
                                                      "texto": "No hay saldos tributarios anteriores registrados: sus arrastres quedan sin dato."}],
                                  "saldos_anteriores": null},
                   "periodos": []},
     "capacidades": {"editar": false,
                     "validar": false,
                     "enviar": false,
                     "devolver": false,
                     "confirmar": false,
                     "descartar": false,
                     "sustituir": false,
                     "ajustar": false,
                     "reversar": false,
                     "cobrar": false},
     "acceso": …}
```

Con la apertura confirmada (`cobertura.periodos`: un objeto por mes del año en curso, desde el mes de `contabilidad_desde` si es de este año o desde enero, hasta el mes en curso; se muestra el primero):

```
GET /contabilidad/api/apertura/?empresa=1

200 {"empresa": {"id": 1, "ruc": "0900000001001", "nombre": "EMPRESA A S.A."},
     "configuracion": {"version": 1,
                       "modalidad": "saldos",
                       "fecha_corte": "2025-12-31",
                       "contabilidad_desde": "2026-01-01",
                       "operaciones_desde": "2026-01-01",
                       "historial_desde": null,
                       "historial_hasta": null,
                       "guarda_importacion": false},
     "modalidad": "saldos",
     "fecha_corte": "2025-12-31",
     "operaciones_desde": "2026-01-01",
     "apertura": {"id": 2,
                  "version": 7,
                  "estado": "confirmada",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "10000.00",
                  "haber": "10000.00",
                  "diferencia": "0.00",
                  "lineas": 6,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [{"ambito": "activos",
                                          "nota": "La empresa no tiene activos fijos al corte (acta de inventario)",
                                          "declarado_por": "propietario.a",
                                          "declarado_en": "2026-11-14T14:30:03.079439+00:00"},
                                         {"ambito": "tributario",
                                          "nota": "Sin créditos ni retenciones pendientes según la declaración de diciembre",
                                          "declarado_por": "propietario.a",
                                          "declarado_en": "2026-11-14T14:30:03.079439+00:00"}],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": {"id": 1, "numero": "2025-000001", "fecha": "2025-12-31", "debe": "10000.00", "haber": "10000.00"},
                  "enviado_por": "propietario.a",
                  "enviado_en": "2026-11-14T14:30:02.888294+00:00",
                  "revisado_por": "propietario.a",
                  "confirmado_por": "propietario.a",
                  "confirmado_en": "2026-11-14T14:30:03.079439+00:00",
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.114977+00:00",
                  "motivo": ""},
     "vigente": {"id": 2,
                 "version": 7,
                 "fecha_corte": "2025-12-31",
                 "confirmado_en": "2026-11-14T14:30:03.079439+00:00",
                 "asiento": {"id": 1, "numero": "2025-000001", "fecha": "2025-12-31", "debe": "10000.00", "haber": "10000.00"}},
     "cobertura": {"contabilidad": {"estado": "parcial",
                                    "causas": ["La apertura se confirmó aceptando el detalle incompleto de 4 cuenta(s)."],
                                    "causas_detalle": [{"codigo": "detalle_incompleto_aceptado",
                                                        "texto": "La apertura se confirmó aceptando el detalle incompleto de 4 cuenta(s).",
                                                        "cantidad": 4}]},
                   "cartera": {"estado": "pendiente",
                               "causas": ["El saldo de clientes en la apertura todavía no tiene su detalle.",
                                          "El saldo de proveedores en la apertura todavía no tiene su detalle."],
                               "causas_detalle": [{"codigo": "sin_detalle",
                                                   "texto": "El saldo de clientes en la apertura todavía no tiene su detalle.",
                                                   "cantidad": 1},
                                                  {"codigo": "sin_detalle",
                                                   "texto": "El saldo de proveedores en la apertura todavía no tiene su detalle.",
                                                   "cantidad": 1}],
                               "clientes": {"estado": "pendiente", "cuenta": "3000.00", "detallado": "0.00", "documentos": 0},
                               "proveedores": {"estado": "pendiente", "cuenta": "2500.00", "detallado": "0.00", "documentos": 0}},
                   "inventario": {"estado": "pendiente",
                                  "causas": ["El saldo de inventario en la apertura todavía no tiene su detalle."],
                                  "causas_detalle": [{"codigo": "sin_detalle",
                                                      "texto": "El saldo de inventario en la apertura todavía no tiene su detalle.",
                                                      "cantidad": 1}],
                                  "cuenta": "2000.00",
                                  "detallado": "0.00",
                                  "filas": 0},
                   "bancos": {"estado": "pendiente",
                              "causas": ["El saldo de bancos en la apertura todavía no tiene su detalle."],
                              "causas_detalle": [{"codigo": "sin_detalle",
                                                  "texto": "El saldo de bancos en la apertura todavía no tiene su detalle.",
                                                  "cantidad": 1}],
                              "cuenta": "5000.00",
                              "detallado": "0.00",
                              "filas": 0},
                   "activos": {"estado": "no_aplica", "causas": [], "causas_detalle": [], "cuenta": null, "detallado": null, "filas": 0},
                   "tributario": {"estado": "no_aplica", "causas": [], "causas_detalle": [], "saldos_anteriores": null},
                   "periodos": [{"mes": "2026-01",
                                 "ambitos": {"contabilidad": {"estado": "sin_cobertura",
                                                              "fuente_tipo": null,
                                                              "declarado_por": null,
                                                              "declarado_en": null},
                                             "documentos": {"estado": "sin_cobertura",
                                                            "fuente_tipo": null,
                                                            "declarado_por": null,
                                                            "declarado_en": null},
                                             "cartera": {"estado": "sin_cobertura",
                                                         "fuente_tipo": null,
                                                         "declarado_por": null,
                                                         "declarado_en": null},
                                             "inventario": {"estado": "sin_cobertura",
                                                            "fuente_tipo": null,
                                                            "declarado_por": null,
                                                            "declarado_en": null},
                                             "bancos": {"estado": "sin_cobertura",
                                                        "fuente_tipo": null,
                                                        "declarado_por": null,
                                                        "declarado_en": null}}},
                                … (10 meses más, con la misma forma)]},
     "capacidades": {"editar": false,
                     "validar": false,
                     "enviar": false,
                     "devolver": false,
                     "confirmar": false,
                     "descartar": false,
                     "sustituir": false,
                     "ajustar": false,
                     "reversar": false,
                     "cobrar": false},
     "acceso": …}
```

`cobertura`:

- `contabilidad`: `pendiente` sin inicio (`inicio_sin_configurar`) o sin apertura confirmada (`apertura_sin_confirmar` / `saldo_anterior_sin_confirmar`); `parcial` si se confirmó con detalle incompleto aceptado (`detalle_incompleto_aceptado`); `conciliada` si no.
- `cartera` (`clientes` y `proveedores`), `inventario`, `bancos` y `activos`: `no_aplica` **solo** si la apertura lo declara en `ambitos_no_aplican`; sin declaración y sin ninguna línea de ese detalle, `pendiente` con `sin_cuenta_declarada`; con líneas, `pendiente` mientras no tengan detalle (`sin_detalle`), `parcial` con detalle incompleto (`detalle_incompleto`, `detalle_excede`, `importe_pendiente`) y `conciliada` cuando el detalle explica cada línea. `cuenta` es el saldo de las líneas de ese detalle y `detallado` lo explicado por sus auxiliares (`null` sin líneas).
- `tributario`: `saldos_anteriores` es `null` mientras no haya auxiliares tributarios (nunca `"0.00"`).
- `periodos`: por mes del año en curso (vacío sin inicio o si `contabilidad_desde` todavía no llega), lo declarado para cada ámbito (`contabilidad`, `documentos`, `cartera`, `inventario`, `bancos`); sin declaración, `sin_cobertura`. Declararlo es del corte 2 (`POST apertura/cobertura/`), así que hoy todos los meses salen `sin_cobertura`.
- No es licencia ni autorización fiscal.

`capacidades`: `editar` (borrador), `validar` y `descartar` (borrador o en revisión), `enviar` (borrador), `devolver` y `confirmar` (en revisión), cada una con su permiso; `sustituir`, `ajustar`, `reversar` y `cobrar` son siempre `false` hasta el corte 2.

#### `POST apertura/` — configurar y crear el borrador

Envío: `{empresa, clave, modalidad, fecha_corte | (historial_desde, historial_hasta), fuente, fuente_detalle, sin_saldos?}`. `fuente`: `balance_comprobacion`, `estado_situacion`, `captura_manual`, `sistema_anterior` o `inicio_actividades`. Crea o actualiza `InicioContable` y crea el borrador en la misma transacción, con el candado del libro. 201 la primera vez; la misma clave y el mismo contenido, 200 con `repetido: true`.

```
POST /contabilidad/api/apertura/?empresa=1
Content-Type: application/json
{"empresa": 1,
 "modalidad": "saldos",
 "fecha_corte": "2025-12-31",
 "fuente": "balance_comprobacion",
 "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
 "clave": "crear-apertura-0002"}

201 {"configuracion": {"version": 1,
                       "modalidad": "saldos",
                       "fecha_corte": "2025-12-31",
                       "contabilidad_desde": "2026-01-01",
                       "operaciones_desde": "2026-01-01",
                       "historial_desde": null,
                       "historial_hasta": null,
                       "guarda_importacion": false},
     "apertura": {"id": 2,
                  "version": 1,
                  "estado": "borrador",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "0.00",
                  "haber": "0.00",
                  "diferencia": "0.00",
                  "lineas": 0,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": null,
                  "enviado_por": null,
                  "enviado_en": null,
                  "revisado_por": null,
                  "confirmado_por": null,
                  "confirmado_en": null,
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.114977+00:00",
                  "motivo": ""},
     "repetido": false}
```

```
200 {"configuracion": {"version": 1,
                       "modalidad": "saldos",
                       "fecha_corte": "2025-12-31",
                       "contabilidad_desde": "2026-01-01",
                       "operaciones_desde": "2026-01-01",
                       "historial_desde": null,
                       "historial_hasta": null,
                       "guarda_importacion": false},
     "apertura": {"id": 2,
                  "version": 1,
                  "estado": "borrador",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "0.00",
                  "haber": "0.00",
                  "diferencia": "0.00",
                  "lineas": 0,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": null,
                  "enviado_por": null,
                  "enviado_en": null,
                  "revisado_por": null,
                  "confirmado_por": null,
                  "confirmado_en": null,
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.114977+00:00",
                  "motivo": ""},
     "repetido": true}
```

(El mismo envío de arriba, repetido.)

```
POST /contabilidad/api/apertura/?empresa=1
Content-Type: application/json
{"empresa": 1,
 "modalidad": "saldos",
 "fecha_corte": "2027-01-31",
 "fuente": "libro_mayor",
 "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
 "clave": "crear-mal-0001"}

400 {"error": "Revisa los datos marcados.",
     "codigo": "validacion",
     "errores": {"fecha_corte": ["La fecha de corte no puede ser futura."], "fuente": ["Elige la fuente de los saldos."]}}
```

```
POST /contabilidad/api/apertura/?empresa=1
Content-Type: application/json
{"empresa": 1,
 "modalidad": "saldos",
 "fecha_corte": "2025-12-31",
 "fuente": "balance_comprobacion",
 "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
 "clave": "crear-apertura-0003"}

409 {"error": "Ya hay una apertura en preparación: continúa con ella o descártala antes de crear otra.",
     "codigo": "apertura_existente",
     "apertura": {"id": 2,
                  "version": 1,
                  "estado": "borrador",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "0.00",
                  "haber": "0.00",
                  "diferencia": "0.00",
                  "lineas": 0,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": null,
                  "enviado_por": null,
                  "enviado_en": null,
                  "revisado_por": null,
                  "confirmado_por": null,
                  "confirmado_en": null,
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.114977+00:00",
                  "motivo": ""}}
```

```
POST /contabilidad/api/apertura/?empresa=1
Content-Type: application/json
{"empresa": 1,
 "modalidad": "saldos",
 "fecha_corte": "2025-12-31",
 "fuente": "balance_comprobacion",
 "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
 "clave": "crear-apertura-0004"}

409 {"error": "La apertura ya está confirmada: la configuración solo cambia sustituyendo la apertura.", "codigo": "apertura_confirmada"}
```

Sin ninguna cuenta de movimiento activa (empresa 2, sin plan de cuentas):

```
POST /contabilidad/api/apertura/?empresa=2
Content-Type: application/json
{"empresa": 2,
 "modalidad": "saldos",
 "fecha_corte": "2025-12-31",
 "fuente": "balance_comprobacion",
 "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
 "clave": "crear-apertura-b001"}

409 {"error": "Faltan datos por completar antes de usar esta función.",
     "codigo": "datos_por_completar",
     "causa": "datos",
     "faltan": [{"codigo": "plan_cuentas_vacio",
                 "texto": "Crea o importa el plan de cuentas: no tiene ninguna cuenta de movimiento activa.",
                 "url": null}]}
```

Otros: 409 `rango_solapado` `{"asientos", "aplicaciones", "primera_fecha"}`; 409 `clave_usada`; 400 por campo (`modalidad`, `fecha_corte`, `historial_desde`, `historial_hasta`, `fuente`, `fuente_detalle`, `sin_saldos`: `sin_saldos` exige fuente `inicio_actividades` y `fuente_detalle`).

#### `GET apertura/<id>/`

`archivos` junta los lotes de importación (`clase: "importacion"`) y los respaldos (`clase: "respaldo"`), del más reciente al más antiguo. `historial` es la historia de solo inserción de la apertura. `ajustes` está vacío hasta el corte 2.

```
GET /contabilidad/api/apertura/2/?empresa=1

200 {"apertura": {"id": 2,
                  "version": 7,
                  "estado": "confirmada",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "10000.00",
                  "haber": "10000.00",
                  "diferencia": "0.00",
                  "lineas": 6,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [{"ambito": "activos",
                                          "nota": "La empresa no tiene activos fijos al corte (acta de inventario)",
                                          "declarado_por": "propietario.a",
                                          "declarado_en": "2026-11-14T14:30:03.079439+00:00"},
                                         {"ambito": "tributario",
                                          "nota": "Sin créditos ni retenciones pendientes según la declaración de diciembre",
                                          "declarado_por": "propietario.a",
                                          "declarado_en": "2026-11-14T14:30:03.079439+00:00"}],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": {"id": 1, "numero": "2025-000001", "fecha": "2025-12-31", "debe": "10000.00", "haber": "10000.00"},
                  "enviado_por": "propietario.a",
                  "enviado_en": "2026-11-14T14:30:02.888294+00:00",
                  "revisado_por": "propietario.a",
                  "confirmado_por": "propietario.a",
                  "confirmado_en": "2026-11-14T14:30:03.079439+00:00",
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.114977+00:00",
                  "motivo": ""},
     "archivos": [{"clase": "respaldo",
                   "id": 2,
                   "nombre": "copia.pdf",
                   "tipo": "application/pdf",
                   "tamano": 84,
                   "sha256": "6bf06a9456eb57365c15d4b73a5cf6f2db97dc96c3c5581d08536ebf75dc2be5",
                   "descripcion": "Copia duplicada",
                   "subido_por": "propietario.a",
                   "subido_en": "2026-11-14T14:30:02.637811+00:00",
                   "estado": "anulado",
                   "anulado_por": "propietario.a",
                   "anulado_en": "2026-11-14T14:30:02.653172+00:00",
                   "motivo_anulacion": "Subido dos veces",
                   "url": null,
                   "recurso": {"tipo": "respaldo_apertura", "id": 2, "api": "/contabilidad/api/apertura/respaldos/2/descargar/"}},
                  {"clase": "respaldo",
                   "id": 1,
                   "nombre": "balance-firmado.pdf",
                   "tipo": "application/pdf",
                   "tamano": 77,
                   "sha256": "56c2ac043c28d3543275a6f50b593a6beb0b6888ed8159ac02e3e7f4a32ccb26",
                   "descripcion": "Balance firmado (PDF)",
                   "subido_por": "propietario.a",
                   "subido_en": "2026-11-14T14:30:02.596830+00:00",
                   "estado": "vigente",
                   "anulado_por": null,
                   "anulado_en": null,
                   "motivo_anulacion": "",
                   "url": null,
                   "recurso": {"tipo": "respaldo_apertura", "id": 1, "api": "/contabilidad/api/apertura/respaldos/1/descargar/"}},
                  {"clase": "importacion",
                   "id": 1,
                   "nombre": "balance-2025.csv",
                   "tipo": "saldos",
                   "tamano": 250,
                   "sha256": "280ded42e3c271dc647ece268fb419096c75338217c2e1e596a32dca3294b3b2",
                   "estado": "aplicado",
                   "subido_por": "propietario.a",
                   "subido_en": "2026-11-14T14:30:02.429677+00:00",
                   "url": null,
                   "recurso": {"tipo": "importacion_apertura", "id": 1, "api": "/contabilidad/api/apertura/importar/1/"}}],
     "ajustes": [],
     "historial": [{"accion": "creada",
                    "de_estado": "",
                    "a_estado": "borrador",
                    "usuario": "propietario.a",
                    "fecha": "2026-11-14T14:30:02.116370+00:00",
                    "detalle": {"fuente": "balance_comprobacion", "sin_saldos": false, "fecha_corte": "2025-12-31", "modalidad": "saldos"}},
                   {"accion": "modificada",
                    "de_estado": "",
                    "a_estado": "",
                    "usuario": "propietario.a",
                    "fecha": "2026-11-14T14:30:02.407506+00:00",
                    "detalle": {"version": 2,
                                "cambios": {"ambitos_no_aplican": [[],
                                                                   [{"ambito": "activos",
                                                                     "nota": "La empresa no tiene activos fijos al corte (acta de inventario)"},
                                                                    {"ambito": "tributario",
                                                                     "nota": "Sin créditos ni retenciones pendientes según la declaración de diciembre"}]]}}},
                   {"accion": "importada",
                    "de_estado": "",
                    "a_estado": "",
                    "usuario": "propietario.a",
                    "fecha": "2026-11-14T14:30:02.433312+00:00",
                    "detalle": {"lote_id": 1,
                                "nombre": "balance-2025.csv",
                                "sha256": "280ded42e3c271dc647ece268fb419096c75338217c2e1e596a32dca3294b3b2",
                                "filas": 7}},
                   {"accion": "mapeada",
                    "de_estado": "",
                    "a_estado": "",
                    "usuario": "propietario.a",
                    "fecha": "2026-11-14T14:30:02.531543+00:00",
                    "detalle": {"version": 3, "altas": 6, "cambios": 0, "retiradas": 0, "lote_id": 1, "omitidas": 1, "agrupadas": 0}},
                   {"accion": "respaldo_subido",
                    "de_estado": "",
                    "a_estado": "",
                    "usuario": "propietario.a",
                    "fecha": "2026-11-14T14:30:02.599811+00:00",
                    "detalle": {"respaldo_id": 1,
                                "nombre": "balance-firmado.pdf",
                                "sha256": "56c2ac043c28d3543275a6f50b593a6beb0b6888ed8159ac02e3e7f4a32ccb26",
                                "tamano": 77}},
                   {"accion": "respaldo_subido",
                    "de_estado": "",
                    "a_estado": "",
                    "usuario": "propietario.a",
                    "fecha": "2026-11-14T14:30:02.639563+00:00",
                    "detalle": {"respaldo_id": 2,
                                "nombre": "copia.pdf",
                                "sha256": "6bf06a9456eb57365c15d4b73a5cf6f2db97dc96c3c5581d08536ebf75dc2be5",
                                "tamano": 84}},
                   {"accion": "respaldo_anulado",
                    "de_estado": "",
                    "a_estado": "",
                    "usuario": "propietario.a",
                    "fecha": "2026-11-14T14:30:02.654348+00:00",
                    "detalle": {"respaldo_id": 2, "motivo": "Subido dos veces"}},
                   {"accion": "enviada_revision",
                    "de_estado": "borrador",
                    "a_estado": "en_revision",
                    "usuario": "propietario.a",
                    "fecha": "2026-11-14T14:30:02.772214+00:00",
                    "detalle": {"version": 4,
                                "advertencias": ["auxiliar_incompleto", "auxiliar_incompleto", "auxiliar_incompleto", "auxiliar_incompleto"]}},
                   {"accion": "devuelta",
                    "de_estado": "en_revision",
                    "a_estado": "borrador",
                    "usuario": "propietario.a",
                    "fecha": "2026-11-14T14:30:02.864360+00:00",
                    "detalle": {"version": 5,
                                "motivo": "Falta el respaldo del inventario",
                                "enviada": {"por": "propietario.a", "en": "2026-11-14T14:30:02.771329+00:00"}}},
                   {"accion": "enviada_revision",
                    "de_estado": "borrador",
                    "a_estado": "en_revision",
                    "usuario": "propietario.a",
                    "fecha": "2026-11-14T14:30:02.889066+00:00",
                    "detalle": {"version": 6,
                                "advertencias": ["auxiliar_incompleto", "auxiliar_incompleto", "auxiliar_incompleto", "auxiliar_incompleto"]}},
                   {"accion": "confirmada",
                    "de_estado": "en_revision",
                    "a_estado": "confirmada",
                    "usuario": "propietario.a",
                    "fecha": "2026-11-14T14:30:03.080976+00:00",
                    "detalle": {"version": 7,
                                "asiento": {"id": 1, "numero": "2025-000001", "debe": "10000.00", "haber": "10000.00"},
                                "sin_saldos": false,
                                "incompletos_aceptados": [1, 2, 3, 4],
                                "nota": "Revisada contra el balance firmado y el acta de inventario",
                                "advertencias": []}}],
     "capacidades": {"editar": false,
                     "validar": false,
                     "enviar": false,
                     "devolver": false,
                     "confirmar": false,
                     "descartar": false,
                     "sustituir": false,
                     "ajustar": false,
                     "reversar": false,
                     "cobrar": false}}
```

Desde `72a68ee`, el `detalle` del evento `confirmada` trae además **`detalle_fijado`**, entre `incompletos_aceptados` y
`nota`: `[{"linea_id", "anterior", "nuevo"}]`, las líneas cuya copia de `detalle` cambió al confirmar (§6.5, regla 4), o
`[]` si no cambió ninguna. El ejemplo de arriba se obtuvo en `a5bedf4` y no la tiene. (`72a68ee`; la caja pasó a declarar
`cliente` con la apertura en revisión):

```
"detalle": {"version": 4,
            "asiento": {"id": 1, "numero": "2025-000001", "debe": "10500.00", "haber": "10500.00"},
            "sin_saldos": false,
            "incompletos_aceptados": [1, 2],
            "detalle_fijado": [{"linea_id": 1, "anterior": "", "nuevo": "cliente"}],
            "nota": "",
            "advertencias": ["sin_cuenta_declarada", …, "tributario_sin_saldos"]}
```

(`apertura` tiene la forma de `GET apertura/`.) Recién creada:

```
GET /contabilidad/api/apertura/2/?empresa=1

200 {"apertura": {"id": 2,
                  "version": 1,
                  "estado": "borrador",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "0.00",
                  "haber": "0.00",
                  "diferencia": "0.00",
                  "lineas": 0,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": null,
                  "enviado_por": null,
                  "enviado_en": null,
                  "revisado_por": null,
                  "confirmado_por": null,
                  "confirmado_en": null,
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.114977+00:00",
                  "motivo": ""},
     "archivos": [],
     "ajustes": [],
     "historial": [{"accion": "creada",
                    "de_estado": "",
                    "a_estado": "borrador",
                    "usuario": "propietario.a",
                    "fecha": "2026-11-14T14:30:02.116370+00:00",
                    "detalle": {"fuente": "balance_comprobacion", "sin_saldos": false, "fecha_corte": "2025-12-31", "modalidad": "saldos"}}],
     "capacidades": {"editar": true,
                     "validar": true,
                     "enviar": true,
                     "devolver": false,
                     "confirmar": false,
                     "descartar": true,
                     "sustituir": false,
                     "ajustar": false,
                     "reversar": false,
                     "cobrar": false}}
```

```
GET /contabilidad/api/apertura/999999/?empresa=1

404 {"error": "La apertura no existe o es de otra empresa.", "codigo": "no_existe"}
```

#### `PATCH apertura/<id>/` — encabezado del borrador

Envío JSON: `{empresa, version, fecha_corte?, historial_hasta?, fuente?, fuente_detalle?, resultado_ejercicio?, resultado_acumulado?, inventario_modo?, ambitos_no_aplican?}`. `ambitos_no_aplican`: `[{ambito: clientes | proveedores | inventario | bancos | activos | tributario, nota}]`, con nota obligatoria y rechazado si la apertura tiene líneas con ese detalle (400 `validacion` con `errores["ambitos_no_aplican.<i>.ambito"]`, «Hay cuentas con ese detalle en la apertura: no puede declararse que no aplica.»; desde `72a68ee` se mira el auxiliar que declaran ahora las cuentas de las líneas, regla 4); al confirmar se congela con quién y cuándo. `modalidad`, `sin_saldos` e `historial_desde` no se cambian: se descarta la apertura y se crea otra. Si el envío trae uno de ellos, la respuesta es 400 `validacion` con `errores.modalidad`, `errores.sin_saldos` o `errores.historial_desde` («No se cambia en un borrador: descarta esta apertura y crea otra.»); `fijo` es solo el nombre interno de ese texto, no un `codigo` (antes este párrafo decía «400 `fijo`»). Mover el corte toma el candado y comprueba el solapamiento. `inventario_modo` (`solo_conciliar` o `reiniciar_kardex`) se guarda; en este corte no hay auxiliares de inventario, así que confirmar no crea movimientos de kardex en ningún modo.

```
PATCH /contabilidad/api/apertura/2/?empresa=1
Content-Type: application/json
{"empresa": 1,
 "version": 1,
 "ambitos_no_aplican": [{"ambito": "activos", "nota": "La empresa no tiene activos fijos al corte (acta de inventario)"},
                        {"ambito": "tributario", "nota": "Sin créditos ni retenciones pendientes según la declaración de diciembre"}]}

200 {"apertura": {"id": 2,
                  "version": 2,
                  "estado": "borrador",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "0.00",
                  "haber": "0.00",
                  "diferencia": "0.00",
                  "lineas": 0,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [{"ambito": "activos", "nota": "La empresa no tiene activos fijos al corte (acta de inventario)"},
                                         {"ambito": "tributario",
                                          "nota": "Sin créditos ni retenciones pendientes según la declaración de diciembre"}],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": null,
                  "enviado_por": null,
                  "enviado_en": null,
                  "revisado_por": null,
                  "confirmado_por": null,
                  "confirmado_en": null,
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.114977+00:00",
                  "motivo": ""},
     "configuracion": {"version": 1,
                       "modalidad": "saldos",
                       "fecha_corte": "2025-12-31",
                       "contabilidad_desde": "2026-01-01",
                       "operaciones_desde": "2026-01-01",
                       "historial_desde": null,
                       "historial_hasta": null,
                       "guarda_importacion": false}}
```

```
PATCH /contabilidad/api/apertura/2/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 9, "fuente_detalle": "x"}

409 {"error": "Otra persona cambió la apertura mientras la editabas: revisa cómo quedó y vuelve a intentarlo.",
     "codigo": "version",
     "apertura": {"id": 2,
                  "version": 1,
                  "estado": "borrador",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "0.00",
                  "haber": "0.00",
                  "diferencia": "0.00",
                  "lineas": 0,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": null,
                  "enviado_por": null,
                  "enviado_en": null,
                  "revisado_por": null,
                  "confirmado_por": null,
                  "confirmado_en": null,
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.114977+00:00",
                  "motivo": ""}}
```

```
PATCH /contabilidad/api/apertura/2/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 1, "ambitos_no_aplican": [{"ambito": "activos", "nota": ""}]}

400 {"error": "Revisa los datos marcados.",
     "codigo": "validacion",
     "errores": {"ambitos_no_aplican.0.nota": ["Escribe por qué no aplica."]}}
```

Fuera del borrador: 409 `estado` `{"estado", "permitidos": ["borrador"]}`.

#### `POST apertura/<id>/importar/` y `GET apertura/importar/<lote>/`

Multipart: `archivo`, `clave`, `empresa`, `tipo: "saldos"` (`auxiliares` es del corte 2: hoy 400 `validacion` con `errores.tipo`, «La importación del detalle (auxiliares) todavía no está disponible: por ahora se importan los saldos.»; otro valor, 400 `validacion` con `errores.tipo`, «Elige qué se importa: los saldos de la apertura.»). CSV en UTF-8 (`;` o `,`, con o sin BOM) o XLSX, con el lector endurecido del plan de cuentas (C3), que desde la unión con el cierre del bloque 1 es el lector común `lectura_tabular.py`: 2 MB, 5 000 filas; un XLSX con una parte en bzip2 o lzma o con entidades XML (DOCTYPE) en sus partes XML es 400 `formato`, y un logo SVG o una imagen dentro del libro no impiden subirlo. Columnas por encabezado, sin tildes ni mayúsculas: código (`codigo`, `cuenta`), rubro (`nombre`, `rubro`, `descripcion`, `detalle`; también `cuenta` si otra columna es el código), `debe` (también `saldo_deudor`, `deudor`) y `haber` (`saldo_acreedor`, `acreedor`), o una sola `saldo` (`saldo_final`; positivo = deudor). Importes con `1.234,56`, `1,234.56` o `1234,56`; un importe con notación científica, `_` o cifras que no son ASCII deja la fila en `error` con «Escribe un importe válido.» (§6.1, «Importes escritos como texto»). **Nada se escribe en las líneas hasta mapear**; el lote queda en la carpeta privada de la empresa con su huella. Importar no sube la versión de la apertura. Responde 200, también la primera vez.

Estados de fila: `valida`, `sin_cuenta` (el código no existe), `de_grupo`, `duplicada` (otra fila ya va a esa cuenta), `omitida` (decidido al mapear) y `error`. Desde `7a5c567`, un carácter de control en el código o en el rubro de una fila (la regla de §6.1, «Textos libres») la deja en `error` con «Quita los caracteres de control o no válidos de este texto (suelen llegar al copiarlo de otro programa).» en su lista `errores`, y la importación sigue respondiendo 200; mapear desde ese lote responde 400 `validacion` con `filas.<n>.codigo` o `filas.<n>.rubro` (ejemplo en §6.1). Si la cuenta de esa fila es un grupo, la fila queda `de_grupo` con los dos textos. (`7a5c567`, la fila 3 de un CSV con `Caja\u0007chica` en el rubro; `filas` recortada):

```
200 {"lote": {…,
              "filas": [{"fila": 3,
                         "codigo": "1.1.01",
                         "rubro": "Caja\u0007chica",
                         …,
                         "estado": "error",
                         "errores": ["Quita los caracteres de control o no válidos de este texto (suelen llegar al copiarlo de otro programa)."]},
                        …],
              …},
     "repetido": false}
```

Archivo del ejemplo (`balance-2025.csv`):

```
Código;Nombre;Debe;Haber
1;ACTIVO;10000,00;
1.1.02;Bancos;5000,00;
1.1.03;Clientes;3000,00;
1.1.04;Inventario de mercaderías;2000,00;
2.1.01;Proveedores;;2500,00
3.1.01;Capital social;;6500,00
3.9.99;Utilidades de años anteriores;;1000,00
```

```
POST /contabilidad/api/apertura/2/importar/?empresa=1
Content-Type: multipart/form-data
empresa=1 · clave=importar-saldos-0001 · tipo=saldos · archivo=<balance-2025.csv, 250 bytes>

200 {"lote": {"id": 1,
              "apertura_id": 2,
              "estado": "vista_previa",
              "tipo": "saldos",
              "archivo": "balance-2025.csv",
              "tamano": 250,
              "sha256": "280ded42e3c271dc647ece268fb419096c75338217c2e1e596a32dca3294b3b2",
              "encabezados": ["Código", "Nombre", "Debe", "Haber"],
              "columnas": {"codigo": "Código", "rubro": "Nombre", "debe": "Debe", "haber": "Haber", "saldo": null},
              "decisiones": [],
              "muestra": [["1", "ACTIVO", "10000,00", ""],
                          ["1.1.02", "Bancos", "5000,00", ""],
                          ["1.1.03", "Clientes", "3000,00", ""],
                          ["1.1.04", "Inventario de mercaderías", "2000,00", ""],
                          ["2.1.01", "Proveedores", "", "2500,00"]],
              "filas": [{"fila": 2,
                         "codigo": "1",
                         "rubro": "ACTIVO",
                         "debe": "10000.00",
                         "haber": "0.00",
                         "cuenta": {"id": 1, "codigo": "1", "nombre": "ACTIVO", "tipo": "grupo"},
                         "estado": "de_grupo",
                         "errores": ["La cuenta 1 es un grupo: elige una cuenta de movimiento u omite la fila (si es un subtotal) con su motivo."]},
                        {"fila": 3,
                         "codigo": "1.1.02",
                         "rubro": "Bancos",
                         "debe": "5000.00",
                         "haber": "0.00",
                         "cuenta": {"id": 3, "codigo": "1.1.02", "nombre": "Bancos", "tipo": "movimiento"},
                         "estado": "valida",
                         "errores": []},
                        {"fila": 4,
                         "codigo": "1.1.03",
                         "rubro": "Clientes",
                         "debe": "3000.00",
                         "haber": "0.00",
                         "cuenta": {"id": 4, "codigo": "1.1.03", "nombre": "Clientes", "tipo": "movimiento"},
                         "estado": "valida",
                         "errores": []},
                        {"fila": 5,
                         "codigo": "1.1.04",
                         "rubro": "Inventario de mercaderías",
                         "debe": "2000.00",
                         "haber": "0.00",
                         "cuenta": {"id": 5, "codigo": "1.1.04", "nombre": "Inventario de mercaderías", "tipo": "movimiento"},
                         "estado": "valida",
                         "errores": []},
                        {"fila": 6,
                         "codigo": "2.1.01",
                         "rubro": "Proveedores",
                         "debe": "0.00",
                         "haber": "2500.00",
                         "cuenta": {"id": 9, "codigo": "2.1.01", "nombre": "Proveedores", "tipo": "movimiento"},
                         "estado": "valida",
                         "errores": []},
                        {"fila": 7,
                         "codigo": "3.1.01",
                         "rubro": "Capital social",
                         "debe": "0.00",
                         "haber": "6500.00",
                         "cuenta": {"id": 11, "codigo": "3.1.01", "nombre": "Capital social", "tipo": "movimiento"},
                         "estado": "valida",
                         "errores": []},
                        {"fila": 8,
                         "codigo": "3.9.99",
                         "rubro": "Utilidades de años anteriores",
                         "debe": "0.00",
                         "haber": "1000.00",
                         "cuenta": null,
                         "estado": "sin_cuenta",
                         "errores": []}],
              "resumen": {"validas": 5,
                          "sin_cuenta": 1,
                          "de_grupo": 1,
                          "duplicadas": 0,
                          "con_error": 0,
                          "omitidas": 0,
                          "debe": "10000.00",
                          "haber": "10000.00",
                          "diferencia": "0.00",
                          "faltan_columnas": []},
              "subido_por": "propietario.a",
              "subido_en": "2026-11-14T14:30:02.429677+00:00",
              "aplicado_por": null,
              "aplicado_en": null},
     "repetido": false}
```

La misma clave con el mismo archivo devuelve el mismo lote con `repetido: true`; con otro archivo, 409 `clave_usada`. Un archivo que no es CSV ni XLSX:

```
POST /contabilidad/api/apertura/2/importar/?empresa=1
Content-Type: multipart/form-data
empresa=1 · clave=importar-saldos-0002 · tipo=saldos · archivo=<balance.pdf, 77 bytes>

400 {"error": "No se pudo leer el archivo: debe ser un CSV (UTF-8, separado por punto y coma o por coma) o un XLSX.", "codigo": "formato"}
```

Otros: 400 con `codigo` `archivo_grande` o `demasiadas_filas` (códigos propios del lector, como `formato` arriba); 400 `validacion` con `errores.tipo` si `tipo` no es `saldos` y con `errores.archivo` si falta el archivo (no son códigos: van dentro de `errores`); 409 `estado` fuera del borrador. `GET apertura/importar/<lote>/` responde `{"lote": {…}}` con la vista previa recalculada contra las cuentas de ahora (404 `no_existe` si es de otra empresa).

#### `POST apertura/<id>/mapear/`

Dos formas, las dos con `{empresa, version}`:

- **Desde un lote:** `{lote_id, columnas?: {codigo, rubro, debe, haber, saldo}, decisiones?: [{fila, cuenta_id?, omitir?, motivo?, agrupar?, es_resultado_ejercicio?}]}`. Una fila de grupo o de subtotal se omite solo con `omitir` y su `motivo`; dos filas hacia la misma cuenta se suman solo con `agrupar` (quedan en `filas_origen`); una fila sin cuenta se asigna con `cuenta_id`.
- **Captura directa del conjunto completo:** `{lineas: [{cuenta_id | null, rubro, debe | null, haber | null, es_resultado_ejercicio?}]}`.

El conjunto enviado se concilia con el que existe por `cuenta_id`: alta de las nuevas, cambio de las que siguen, retiro de las que ya no vienen; los ids de las que siguen no cambian. La diferencia la calcula el servidor; mapear no confirma nada. `auxiliares.estado` de cada línea: `sin_detalle`, `incompleto`, `conciliada`, `no_concilia` o `sin_declarar` (la cuenta no declara auxiliar); `detalle` y `auxiliares.estado` miran, en preparación, el auxiliar que declara ahora la cuenta (§6.5, regla 4). **La respuesta trae en `lineas` todas las líneas de la apertura, también las retiradas** (`"retirada": true`, `debe` y `haber` en `null`), y `retiradas` cuenta las que retiró este envío: la interfaz filtra por `retirada` para mostrar y sumar (D3 del cierre; el código ya respondía así).

```
POST /contabilidad/api/apertura/2/mapear/?empresa=1
Content-Type: application/json
{"empresa": 1,
 "version": 2,
 "lote_id": 1,
 "decisiones": [{"fila": 2, "omitir": true, "motivo": "Subtotal del grupo ACTIVO"}, {"fila": 8, "cuenta_id": 12}]}

200 {"apertura": {"id": 2,
                  "version": 3,
                  "estado": "borrador",
                  "debe": "10000.00",
                  "haber": "10000.00",
                  "diferencia": "0.00",
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0}},
     "lineas": [{"id": 1,
                 "orden": 1,
                 "cuenta": {"id": 3, "codigo": "1.1.02", "nombre": "Bancos", "clase": "activo"},
                 "rubro": "Bancos",
                 "codigo_origen": "1.1.02",
                 "debe": "5000.00",
                 "haber": "0.00",
                 "detalle": "banco",
                 "es_resultado_ejercicio": false,
                 "retirada": false,
                 "auxiliares": {"estado": "sin_detalle", "detallado": "0.00", "filas": 0},
                 "filas_origen": [{"fila": 3, "codigo": "1.1.02", "rubro": "Bancos", "debe": "5000.00", "haber": "0.00"}]},
                {"id": 2,
                 "orden": 2,
                 "cuenta": {"id": 4, "codigo": "1.1.03", "nombre": "Clientes", "clase": "activo"},
                 "rubro": "Clientes",
                 "codigo_origen": "1.1.03",
                 "debe": "3000.00",
                 "haber": "0.00",
                 "detalle": "cliente",
                 "es_resultado_ejercicio": false,
                 "retirada": false,
                 "auxiliares": {"estado": "sin_detalle", "detallado": "0.00", "filas": 0},
                 "filas_origen": [{"fila": 4, "codigo": "1.1.03", "rubro": "Clientes", "debe": "3000.00", "haber": "0.00"}]},
                {"id": 3,
                 "orden": 3,
                 "cuenta": {"id": 5, "codigo": "1.1.04", "nombre": "Inventario de mercaderías", "clase": "activo"},
                 "rubro": "Inventario de mercaderías",
                 "codigo_origen": "1.1.04",
                 "debe": "2000.00",
                 "haber": "0.00",
                 "detalle": "inventario",
                 "es_resultado_ejercicio": false,
                 "retirada": false,
                 "auxiliares": {"estado": "sin_detalle", "detallado": "0.00", "filas": 0},
                 "filas_origen": [{"fila": 5, "codigo": "1.1.04", "rubro": "Inventario de mercaderías", "debe": "2000.00", "haber": "0.00"}]},
                {"id": 4,
                 "orden": 4,
                 "cuenta": {"id": 9, "codigo": "2.1.01", "nombre": "Proveedores", "clase": "pasivo"},
                 "rubro": "Proveedores",
                 "codigo_origen": "2.1.01",
                 "debe": "0.00",
                 "haber": "2500.00",
                 "detalle": "proveedor",
                 "es_resultado_ejercicio": false,
                 "retirada": false,
                 "auxiliares": {"estado": "sin_detalle", "detallado": "0.00", "filas": 0},
                 "filas_origen": [{"fila": 6, "codigo": "2.1.01", "rubro": "Proveedores", "debe": "0.00", "haber": "2500.00"}]},
                {"id": 5,
                 "orden": 5,
                 "cuenta": {"id": 11, "codigo": "3.1.01", "nombre": "Capital social", "clase": "patrimonio"},
                 "rubro": "Capital social",
                 "codigo_origen": "3.1.01",
                 "debe": "0.00",
                 "haber": "6500.00",
                 "detalle": "",
                 "es_resultado_ejercicio": false,
                 "retirada": false,
                 "auxiliares": {"estado": "sin_declarar", "detallado": "0.00", "filas": 0},
                 "filas_origen": [{"fila": 7, "codigo": "3.1.01", "rubro": "Capital social", "debe": "0.00", "haber": "6500.00"}]},
                {"id": 6,
                 "orden": 6,
                 "cuenta": {"id": 12, "codigo": "3.1.02", "nombre": "Resultados acumulados", "clase": "patrimonio"},
                 "rubro": "Utilidades de años anteriores",
                 "codigo_origen": "3.9.99",
                 "debe": "0.00",
                 "haber": "1000.00",
                 "detalle": "",
                 "es_resultado_ejercicio": false,
                 "retirada": false,
                 "auxiliares": {"estado": "sin_declarar", "detallado": "0.00", "filas": 0},
                 "filas_origen": [{"fila": 8,
                                   "codigo": "3.9.99",
                                   "rubro": "Utilidades de años anteriores",
                                   "debe": "0.00",
                                   "haber": "1000.00"}]}],
     "retiradas": 0}
```

```
POST /contabilidad/api/apertura/2/mapear/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 2, "lote_id": 1, "decisiones": [{"fila": 2, "omitir": true}]}

400 {"error": "Revisa los datos marcados.",
     "codigo": "validacion",
     "errores": {"decisiones.0.motivo": ["Escribe por qué se omite la fila (por ejemplo, «subtotal del grupo»)."]}}
```

```
POST /contabilidad/api/apertura/2/mapear/?empresa=1
Content-Type: application/json
{"empresa": 1,
 "version": 3,
 "lineas": [{"cuenta_id": 2, "rubro": "Caja", "debe": "100.555", "haber": null},
            {"cuenta_id": 1, "rubro": "Activo", "debe": "100.00", "haber": "5.00"}]}

400 {"error": "Revisa los datos marcados.",
     "codigo": "cuenta_de_grupo",
     "errores": {"lineas.0.debe": ["Usa dos decimales."],
                 "lineas.1.cuenta_id": ["La cuenta 1 es un grupo: elige una cuenta de movimiento."],
                 "lineas.1.haber": ["La línea lleva saldo en un solo lado: deja el otro en cero o vacío."]}}
```

El 400 trae todos los errores de campo a la vez; su `codigo` es `cuenta_de_grupo` si alguna línea va a un grupo y `validacion` si no. Desde un lote, los errores de cada fila llevan su número (`filas.<n>.<campo>`, la de encabezados es la 1) y los de una decisión, su posición (`decisiones.<i>.<campo>`); desde `7a5c567`, también `filas.<n>.codigo` y `filas.<n>.rubro` con un carácter de control (§6.1, «Textos libres»). Otros: 409 `version` y `estado`; 409 `linea_con_auxiliares` `{"linea_id", "auxiliares"}` (no ocurre en este corte); 404 `no_existe` para un lote o una cuenta de otra empresa. Un envío que no se puede leer (líneas que no son lista, `lineas` y `lote_id` juntos) responde 400 `validacion` (`errores.lineas`) **después de los 409 `version` y `estado`** (como en el orden de §6.1) **y antes del 409 `linea_con_auxiliares`**: sin un conjunto que se pueda leer no hay líneas que conciliar, así que ese 400 va antes que el conflicto (antes este párrafo decía «antes de cualquier 409»; el código siempre respondió así). (`72a68ee`): con `{"version": 99, "lote_id": 1, "lineas": []}` o `{"version": 99, "lineas": "x"}` la respuesta es el 409 `version` con la apertura; con la versión vigente, `{"lineas": ["Envía las líneas o el lote, no los dos."]}` y `{"lineas": ["Envía las líneas como una lista."]}`.

#### `GET apertura/<id>/lineas/`

Dos consultas, paginado (`?pagina=&por_pagina=`, hasta 500). **Devuelve también las líneas retiradas**, en su orden, con `"retirada": true` y `debe` y `haber` en `null`, y `paginacion.total` las cuenta; `lineas` de la apertura (`GET apertura/<id>/`) cuenta solo las vigentes. La interfaz las filtra por `retirada` para mostrar, paginar lo que muestra y sumar (D3 del cierre; el código ya respondía así). `detalle` y `auxiliares.estado`, como en mapear. En el ejemplo de abajo no hay ninguna retirada. Una retirada (`72a68ee`; mapeadas caja, bancos y capital, y mapeadas otra vez sin bancos):

```
{"id": 2, "orden": 2, "cuenta": {"id": 3, "codigo": "1.1.02", "nombre": "Bancos", "clase": "activo"}, "rubro": "Bancos",
 "codigo_origen": "", "debe": null, "haber": null, "detalle": "banco", "es_resultado_ejercicio": false, "retirada": true,
 "auxiliares": {"estado": "sin_detalle", "detallado": "0.00", "filas": 0}, "filas_origen": []}
…
"paginacion": {"pagina": 1, "por_pagina": 100, "total": 3, "paginas": 1}
```

(dos vigentes y la retirada; `GET apertura/<id>/` dice `"lineas": 2`). `detalle` y `auxiliares.estado` de una retirada no significan nada: no entra en la validación.

```
GET /contabilidad/api/apertura/2/lineas/?pagina=1&por_pagina=100&empresa=1

200 {"apertura": {"id": 2,
                  "version": 3,
                  "estado": "borrador",
                  "debe": "10000.00",
                  "haber": "10000.00",
                  "diferencia": "0.00",
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0}},
     "lineas": [{"id": 1,
                 "orden": 1,
                 "cuenta": {"id": 3, "codigo": "1.1.02", "nombre": "Bancos", "clase": "activo"},
                 "rubro": "Bancos",
                 "codigo_origen": "1.1.02",
                 "debe": "5000.00",
                 "haber": "0.00",
                 "detalle": "banco",
                 "es_resultado_ejercicio": false,
                 "retirada": false,
                 "auxiliares": {"estado": "sin_detalle", "detallado": "0.00", "filas": 0},
                 "filas_origen": [{"fila": 3, "codigo": "1.1.02", "rubro": "Bancos", "debe": "5000.00", "haber": "0.00"}]},
                {"id": 2,
                 "orden": 2,
                 "cuenta": {"id": 4, "codigo": "1.1.03", "nombre": "Clientes", "clase": "activo"},
                 "rubro": "Clientes",
                 "codigo_origen": "1.1.03",
                 "debe": "3000.00",
                 "haber": "0.00",
                 "detalle": "cliente",
                 "es_resultado_ejercicio": false,
                 "retirada": false,
                 "auxiliares": {"estado": "sin_detalle", "detallado": "0.00", "filas": 0},
                 "filas_origen": [{"fila": 4, "codigo": "1.1.03", "rubro": "Clientes", "debe": "3000.00", "haber": "0.00"}]},
                {"id": 3,
                 "orden": 3,
                 "cuenta": {"id": 5, "codigo": "1.1.04", "nombre": "Inventario de mercaderías", "clase": "activo"},
                 "rubro": "Inventario de mercaderías",
                 "codigo_origen": "1.1.04",
                 "debe": "2000.00",
                 "haber": "0.00",
                 "detalle": "inventario",
                 "es_resultado_ejercicio": false,
                 "retirada": false,
                 "auxiliares": {"estado": "sin_detalle", "detallado": "0.00", "filas": 0},
                 "filas_origen": [{"fila": 5, "codigo": "1.1.04", "rubro": "Inventario de mercaderías", "debe": "2000.00", "haber": "0.00"}]},
                {"id": 4,
                 "orden": 4,
                 "cuenta": {"id": 9, "codigo": "2.1.01", "nombre": "Proveedores", "clase": "pasivo"},
                 "rubro": "Proveedores",
                 "codigo_origen": "2.1.01",
                 "debe": "0.00",
                 "haber": "2500.00",
                 "detalle": "proveedor",
                 "es_resultado_ejercicio": false,
                 "retirada": false,
                 "auxiliares": {"estado": "sin_detalle", "detallado": "0.00", "filas": 0},
                 "filas_origen": [{"fila": 6, "codigo": "2.1.01", "rubro": "Proveedores", "debe": "0.00", "haber": "2500.00"}]},
                {"id": 5,
                 "orden": 5,
                 "cuenta": {"id": 11, "codigo": "3.1.01", "nombre": "Capital social", "clase": "patrimonio"},
                 "rubro": "Capital social",
                 "codigo_origen": "3.1.01",
                 "debe": "0.00",
                 "haber": "6500.00",
                 "detalle": "",
                 "es_resultado_ejercicio": false,
                 "retirada": false,
                 "auxiliares": {"estado": "sin_declarar", "detallado": "0.00", "filas": 0},
                 "filas_origen": [{"fila": 7, "codigo": "3.1.01", "rubro": "Capital social", "debe": "0.00", "haber": "6500.00"}]},
                {"id": 6,
                 "orden": 6,
                 "cuenta": {"id": 12, "codigo": "3.1.02", "nombre": "Resultados acumulados", "clase": "patrimonio"},
                 "rubro": "Utilidades de años anteriores",
                 "codigo_origen": "3.9.99",
                 "debe": "0.00",
                 "haber": "1000.00",
                 "detalle": "",
                 "es_resultado_ejercicio": false,
                 "retirada": false,
                 "auxiliares": {"estado": "sin_declarar", "detallado": "0.00", "filas": 0},
                 "filas_origen": [{"fila": 8,
                                   "codigo": "3.9.99",
                                   "rubro": "Utilidades de años anteriores",
                                   "debe": "0.00",
                                   "haber": "1000.00"}]}],
     "paginacion": {"pagina": 1, "por_pagina": 100, "total": 6, "paginas": 1}}
```

#### Respaldos: `POST apertura/<id>/respaldos/`, descarga y anulación

Multipart: `archivo`, `descripcion`, `clave`, `empresa`. PDF, JPG, PNG, XLSX o CSV hasta 8 MB, reconocidos por su contenido (no por el nombre); WEBP se rechaza con su texto. Solo con la apertura en borrador o en revisión. Un respaldo no se borra ni se reemplaza: se anula con motivo y el archivo se conserva.

```
POST /contabilidad/api/apertura/2/respaldos/?empresa=1
Content-Type: multipart/form-data
empresa=1 · clave=respaldo-balance-0001 · descripcion=Balance firmado (PDF) · archivo=<balance-firmado.pdf, 77 bytes>

201 {"respaldo": {"id": 1,
                  "nombre": "balance-firmado.pdf",
                  "tipo": "application/pdf",
                  "tamano": 77,
                  "sha256": "56c2ac043c28d3543275a6f50b593a6beb0b6888ed8159ac02e3e7f4a32ccb26",
                  "descripcion": "Balance firmado (PDF)",
                  "subido_por": "propietario.a",
                  "subido_en": "2026-11-14T14:30:02.596830+00:00",
                  "estado": "vigente",
                  "anulado_por": null,
                  "anulado_en": null,
                  "motivo_anulacion": "",
                  "url": null,
                  "recurso": {"tipo": "respaldo_apertura", "id": 1, "api": "/contabilidad/api/apertura/respaldos/1/descargar/"}},
     "repetido": false}
```

```
POST /contabilidad/api/apertura/2/respaldos/?empresa=1
Content-Type: multipart/form-data
empresa=1 · clave=respaldo-balance-0002 · descripcion=Foto · archivo=<foto.webp, 32 bytes>

400 {"error": "Revisa los datos marcados.",
     "codigo": "validacion",
     "errores": {"archivo": ["Las imágenes WEBP no se admiten como respaldo contable: guárdala como JPG o PNG. Formatos admitidos: PDF, JPG, PNG, XLSX o CSV."]}}
```

```
GET /contabilidad/api/apertura/respaldos/1/descargar/?empresa=1

200
Content-Type: application/pdf
Content-Disposition: attachment; filename="balance-firmado.pdf"
Content-Length: 77
X-Content-Type-Options: nosniff
Content-Security-Policy: sandbox; default-src 'none'; img-src 'self'
Cache-Control: private, no-store
Referrer-Policy: strict-origin-when-cross-origin
(el archivo)
```

```
POST /contabilidad/api/apertura/respaldos/2/anular/?empresa=1
Content-Type: application/json
{"empresa": 1, "motivo": "Subido dos veces"}

200 {"respaldo": {"id": 2,
                  "nombre": "copia.pdf",
                  "tipo": "application/pdf",
                  "tamano": 84,
                  "sha256": "6bf06a9456eb57365c15d4b73a5cf6f2db97dc96c3c5581d08536ebf75dc2be5",
                  "descripcion": "Copia duplicada",
                  "subido_por": "propietario.a",
                  "subido_en": "2026-11-14T14:30:02.637811+00:00",
                  "estado": "anulado",
                  "anulado_por": "propietario.a",
                  "anulado_en": "2026-11-14T14:30:02.653172+00:00",
                  "motivo_anulacion": "Subido dos veces",
                  "url": null,
                  "recurso": {"tipo": "respaldo_apertura", "id": 2, "api": "/contabilidad/api/apertura/respaldos/2/descargar/"}}}
```

Otros: 409 `ya_anulado`; 404 `no_existe`; 400 `archivo_grande`.

**La misma `clave`** (desde `72a68ee`): responde 200 con `"repetido": true` y el respaldo solo si coinciden la apertura de
la ruta, el archivo (`sha256`) y la descripción. En cualquier otro caso, también si la clave se usó en **otra apertura**
(por ejemplo, una ya descartada), 409 `clave_usada` con `respaldo` = el que ya existe, que puede ser de otra apertura; es
la misma regla que `importar/`. Antes, la misma clave con el mismo archivo en otra apertura respondía 200 `repetido` con
el respaldo de la primera, y la segunda se quedaba sin el suyo. (`72a68ee`, la clave se usó en la apertura 1, descartada,
y se repite en la 2):

```
POST /contabilidad/api/apertura/2/respaldos/?empresa=1
Content-Type: multipart/form-data
empresa=1 · clave=respaldo-clave-0001 · descripcion=Balance firmado · archivo=<balance.pdf, 77 bytes>

409 {"error": "Esta clave ya se usó para otro envío: vuelve a cargar la página e inténtalo de nuevo.",
     "codigo": "clave_usada",
     "respaldo": {"id": 1, "nombre": "balance.pdf", "tipo": "application/pdf", "tamano": 77, …, "estado": "vigente", …}}
```

**Una imagen que no se puede leer** (desde `72a68ee`): un JPG o PNG que Pillow no abre ni verifica (un PNG con la suma de
un bloque dañada, uno sin el bloque IDAT…) es 400 `validacion` con `errores.archivo` y el mismo texto que los
comprobantes de pago; antes era un 500 en HTML. (`72a68ee`, PNG con la suma de IDAT cambiada):

```
400 {"error": "Revisa los datos marcados.",
     "codigo": "validacion",
     "errores": {"archivo": ["La imagen no se puede leer: vuelve a tomarla o expórtala como JPG, PNG o PDF."]}}
```

`descripcion` y el `motivo` de anular rechazan los caracteres de control (§6.1, «Textos libres»). Una descripción con
controles y una clave ya usada da 409 `clave_usada`: no es la misma descripción.

#### `POST apertura/<id>/descartar/`

`{empresa, version, motivo}`; borrador o en revisión. Libera el sitio de la apertura en preparación: después se puede crear otra.

```
POST /contabilidad/api/apertura/1/descartar/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 1, "motivo": "Se cargó con el balance equivocado"}

200 {"apertura": {"id": 1,
                  "version": 2,
                  "estado": "descartada",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "0.00",
                  "haber": "0.00",
                  "diferencia": "0.00",
                  "lineas": 0,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": null,
                  "enviado_por": null,
                  "enviado_en": null,
                  "revisado_por": null,
                  "confirmado_por": null,
                  "confirmado_en": null,
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.060588+00:00",
                  "motivo": "Se cargó con el balance equivocado"}}
```

#### `POST apertura/<id>/validar/`

`{empresa, version}`. **No escribe nada.** Evalúa todo con consultas agregadas (sin una consulta por línea: 5 000 líneas validan y confirman con un tope de consultas fijado en las pruebas). Advertencias: `auxiliar_incompleto` (una por línea, con `linea_id`), `tributario_sin_saldos`, `cartera_operativa_anterior_al_corte` (cuentas por cobrar o por pagar de la aplicación con saldo y fecha hasta el corte, sin vincular, con `documentos: {cuentas_por_cobrar, cuentas_por_pagar}`), `sin_resultados_acumulados`, `ejercicio_sin_cerrar` y `sin_cuenta_declarada` (con `ambito`). `reportes` dice qué necesita cada uno y si sale provisional en su rango: `estado_situacion` (hasta hoy), `f104_f103_ats` (el primer mes después del corte) y `resultado_anual_101` (el año del corte).

Sin líneas:

```
POST /contabilidad/api/apertura/2/validar/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 1}

200 {"apertura": {"id": 2,
                  "version": 1,
                  "estado": "borrador",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "0.00",
                  "haber": "0.00",
                  "diferencia": "0.00",
                  "lineas": 0,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": null,
                  "enviado_por": null,
                  "enviado_en": null,
                  "revisado_por": null,
                  "confirmado_por": null,
                  "confirmado_en": null,
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.114977+00:00",
                  "motivo": ""},
     "valida": false,
     "bloqueos": [{"codigo": "sin_lineas",
                   "texto": "La apertura no tiene líneas: mapea los saldos o, si la empresa empieza sin saldos, crea la apertura como inicio de actividades."}],
     "advertencias": [{"codigo": "sin_cuenta_declarada",
                       "texto": "Ninguna cuenta de la apertura está declarada como de clientes.",
                       "ambito": "clientes"},
                      {"codigo": "sin_cuenta_declarada",
                       "texto": "Ninguna cuenta de la apertura está declarada como de proveedores.",
                       "ambito": "proveedores"},
                      {"codigo": "sin_cuenta_declarada",
                       "texto": "Ninguna cuenta de la apertura está declarada como de inventario.",
                       "ambito": "inventario"},
                      {"codigo": "sin_cuenta_declarada",
                       "texto": "Ninguna cuenta de la apertura está declarada como de bancos.",
                       "ambito": "bancos"},
                      {"codigo": "sin_cuenta_declarada",
                       "texto": "Ninguna cuenta de la apertura está declarada como de activos fijos.",
                       "ambito": "activos"},
                      {"codigo": "sin_cuenta_declarada",
                       "texto": "Ninguna cuenta de la apertura está declarada como de saldos tributarios.",
                       "ambito": "tributario"},
                      {"codigo": "tributario_sin_saldos",
                       "texto": "No hay saldos tributarios anteriores registrados: sus arrastres quedan sin dato."}],
     "ambitos_no_aplican": [],
     "cobertura": {"contabilidad": {"estado": "pendiente",
                                    "causas": ["La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero."],
                                    "causas_detalle": [{"codigo": "apertura_sin_confirmar",
                                                        "texto": "La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero."}]},
                   "cartera": {"estado": "pendiente",
                               "causas": ["Ninguna cuenta de la apertura está declarada como de clientes.",
                                          "Ninguna cuenta de la apertura está declarada como de proveedores."],
                               "causas_detalle": [{"codigo": "sin_cuenta_declarada",
                                                   "texto": "Ninguna cuenta de la apertura está declarada como de clientes."},
                                                  {"codigo": "sin_cuenta_declarada",
                                                   "texto": "Ninguna cuenta de la apertura está declarada como de proveedores."}],
                               "clientes": {"estado": "pendiente", "cuenta": null, "detallado": null, "documentos": 0},
                               "proveedores": {"estado": "pendiente", "cuenta": null, "detallado": null, "documentos": 0}},
                   "inventario": {"estado": "pendiente",
                                  "causas": ["Ninguna cuenta de la apertura está declarada como de inventario."],
                                  "causas_detalle": [{"codigo": "sin_cuenta_declarada",
                                                      "texto": "Ninguna cuenta de la apertura está declarada como de inventario."}],
                                  "cuenta": null,
                                  "detallado": null,
                                  "filas": 0},
                   "bancos": {"estado": "pendiente",
                              "causas": ["Ninguna cuenta de la apertura está declarada como de bancos."],
                              "causas_detalle": [{"codigo": "sin_cuenta_declarada",
                                                  "texto": "Ninguna cuenta de la apertura está declarada como de bancos."}],
                              "cuenta": null,
                              "detallado": null,
                              "filas": 0},
                   "activos": {"estado": "pendiente",
                               "causas": ["Ninguna cuenta de la apertura está declarada como de activos fijos."],
                               "causas_detalle": [{"codigo": "sin_cuenta_declarada",
                                                   "texto": "Ninguna cuenta de la apertura está declarada como de activos fijos."}],
                               "cuenta": null,
                               "detallado": null,
                               "filas": 0},
                   "tributario": {"estado": "pendiente",
                                  "causas": ["No hay saldos tributarios anteriores registrados: sus arrastres quedan sin dato."],
                                  "causas_detalle": [{"codigo": "tributario_sin_saldos",
                                                      "texto": "No hay saldos tributarios anteriores registrados: sus arrastres quedan sin dato."}],
                                  "saldos_anteriores": null},
                   "periodos": [{"mes": "2026-01",
                                 "ambitos": {"contabilidad": {"estado": "sin_cobertura",
                                                              "fuente_tipo": null,
                                                              "declarado_por": null,
                                                              "declarado_en": null},
                                             "documentos": {"estado": "sin_cobertura",
                                                            "fuente_tipo": null,
                                                            "declarado_por": null,
                                                            "declarado_en": null},
                                             "cartera": {"estado": "sin_cobertura",
                                                         "fuente_tipo": null,
                                                         "declarado_por": null,
                                                         "declarado_en": null},
                                             "inventario": {"estado": "sin_cobertura",
                                                            "fuente_tipo": null,
                                                            "declarado_por": null,
                                                            "declarado_en": null},
                                             "bancos": {"estado": "sin_cobertura",
                                                        "fuente_tipo": null,
                                                        "declarado_por": null,
                                                        "declarado_en": null}}},
                                … (10 meses más, con la misma forma)]},
     "reportes": [{"reporte": "estado_situacion",
                   "necesita": "La apertura confirmada y los movimientos posteriores al corte contabilizados.",
                   "desde": null,
                   "hasta": "2026-11-14",
                   "provisional": true,
                   "causas": ["La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero.",
                              "Los documentos de la operación todavía no se contabilizan."],
                   "causas_detalle": [{"codigo": "apertura_sin_confirmar",
                                       "texto": "La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero."},
                                      {"codigo": "motor_pendiente", "texto": "Los documentos de la operación todavía no se contabilizan."}]},
                  {"reporte": "f104_f103_ats",
                   "necesita": "Los comprobantes de cada mes y los saldos tributarios anteriores al corte (créditos y retenciones).",
                   "desde": "2026-01-01",
                   "hasta": "2026-01-31",
                   "provisional": true,
                   "causas": ["La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero.",
                              "Los documentos de la operación todavía no se contabilizan."],
                   "causas_detalle": [{"codigo": "apertura_sin_confirmar",
                                       "texto": "La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero."},
                                      {"codigo": "motor_pendiente", "texto": "Los documentos de la operación todavía no se contabilizan."}]},
                  {"reporte": "resultado_anual_101",
                   "necesita": "Los ingresos, costos y gastos de todo el año del corte, también los anteriores al corte, y la conciliación tributaria.",
                   "desde": "2025-01-01",
                   "hasta": "2025-12-31",
                   "provisional": true,
                   "causas": ["La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero."],
                   "causas_detalle": [{"codigo": "apertura_sin_confirmar",
                                       "texto": "La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero."}]}]}
```

Con el balance mapeado (se omiten `apertura`, que es la de `GET apertura/<id>/`, y los meses de la cobertura después del primero):

```
POST /contabilidad/api/apertura/2/validar/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 3}

200 {"apertura": …,
     "valida": true,
     "bloqueos": [],
     "advertencias": [{"codigo": "auxiliar_incompleto",
                       "texto": "El detalle de la cuenta 1.1.02 explica 0.00 de 5000.00: para confirmar hay que aceptarlo como incompleto.",
                       "linea_id": 1},
                      {"codigo": "auxiliar_incompleto",
                       "texto": "El detalle de la cuenta 1.1.03 explica 0.00 de 3000.00: para confirmar hay que aceptarlo como incompleto.",
                       "linea_id": 2},
                      {"codigo": "auxiliar_incompleto",
                       "texto": "El detalle de la cuenta 1.1.04 explica 0.00 de 2000.00: para confirmar hay que aceptarlo como incompleto.",
                       "linea_id": 3},
                      {"codigo": "auxiliar_incompleto",
                       "texto": "El detalle de la cuenta 2.1.01 explica 0.00 de 2500.00: para confirmar hay que aceptarlo como incompleto.",
                       "linea_id": 4}],
     "ambitos_no_aplican": [{"ambito": "activos", "nota": "La empresa no tiene activos fijos al corte (acta de inventario)"},
                            {"ambito": "tributario", "nota": "Sin créditos ni retenciones pendientes según la declaración de diciembre"}],
     "cobertura": {"contabilidad": {"estado": "pendiente",
                                    "causas": ["La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero."],
                                    "causas_detalle": [{"codigo": "apertura_sin_confirmar",
                                                        "texto": "La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero."}]},
                   "cartera": {"estado": "pendiente",
                               "causas": ["El saldo de clientes en la apertura todavía no tiene su detalle.",
                                          "El saldo de proveedores en la apertura todavía no tiene su detalle."],
                               "causas_detalle": [{"codigo": "sin_detalle",
                                                   "texto": "El saldo de clientes en la apertura todavía no tiene su detalle.",
                                                   "cantidad": 1},
                                                  {"codigo": "sin_detalle",
                                                   "texto": "El saldo de proveedores en la apertura todavía no tiene su detalle.",
                                                   "cantidad": 1}],
                               "clientes": {"estado": "pendiente", "cuenta": "3000.00", "detallado": "0.00", "documentos": 0},
                               "proveedores": {"estado": "pendiente", "cuenta": "2500.00", "detallado": "0.00", "documentos": 0}},
                   "inventario": {"estado": "pendiente",
                                  "causas": ["El saldo de inventario en la apertura todavía no tiene su detalle."],
                                  "causas_detalle": [{"codigo": "sin_detalle",
                                                      "texto": "El saldo de inventario en la apertura todavía no tiene su detalle.",
                                                      "cantidad": 1}],
                                  "cuenta": "2000.00",
                                  "detallado": "0.00",
                                  "filas": 0},
                   "bancos": {"estado": "pendiente",
                              "causas": ["El saldo de bancos en la apertura todavía no tiene su detalle."],
                              "causas_detalle": [{"codigo": "sin_detalle",
                                                  "texto": "El saldo de bancos en la apertura todavía no tiene su detalle.",
                                                  "cantidad": 1}],
                              "cuenta": "5000.00",
                              "detallado": "0.00",
                              "filas": 0},
                   "activos": {"estado": "no_aplica", "causas": [], "causas_detalle": [], "cuenta": null, "detallado": null, "filas": 0},
                   "tributario": {"estado": "no_aplica", "causas": [], "causas_detalle": [], "saldos_anteriores": null},
                   "periodos": [{"mes": "2026-01",
                                 "ambitos": {"contabilidad": {"estado": "sin_cobertura",
                                                              "fuente_tipo": null,
                                                              "declarado_por": null,
                                                              "declarado_en": null},
                                             "documentos": {"estado": "sin_cobertura",
                                                            "fuente_tipo": null,
                                                            "declarado_por": null,
                                                            "declarado_en": null},
                                             "cartera": {"estado": "sin_cobertura",
                                                         "fuente_tipo": null,
                                                         "declarado_por": null,
                                                         "declarado_en": null},
                                             "inventario": {"estado": "sin_cobertura",
                                                            "fuente_tipo": null,
                                                            "declarado_por": null,
                                                            "declarado_en": null},
                                             "bancos": {"estado": "sin_cobertura",
                                                        "fuente_tipo": null,
                                                        "declarado_por": null,
                                                        "declarado_en": null}}},
                                … (10 meses más, con la misma forma)]},
     "reportes": [{"reporte": "estado_situacion",
                   "necesita": "La apertura confirmada y los movimientos posteriores al corte contabilizados.",
                   "desde": null,
                   "hasta": "2026-11-14",
                   "provisional": true,
                   "causas": ["La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero.",
                              "Los documentos de la operación todavía no se contabilizan."],
                   "causas_detalle": [{"codigo": "apertura_sin_confirmar",
                                       "texto": "La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero."},
                                      {"codigo": "motor_pendiente", "texto": "Los documentos de la operación todavía no se contabilizan."}]},
                  {"reporte": "f104_f103_ats",
                   "necesita": "Los comprobantes de cada mes y los saldos tributarios anteriores al corte (créditos y retenciones).",
                   "desde": "2026-01-01",
                   "hasta": "2026-01-31",
                   "provisional": true,
                   "causas": ["La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero.",
                              "Los documentos de la operación todavía no se contabilizan."],
                   "causas_detalle": [{"codigo": "apertura_sin_confirmar",
                                       "texto": "La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero."},
                                      {"codigo": "motor_pendiente", "texto": "Los documentos de la operación todavía no se contabilizan."}]},
                  {"reporte": "resultado_anual_101",
                   "necesita": "Los ingresos, costos y gastos de todo el año del corte, también los anteriores al corte, y la conciliación tributaria.",
                   "desde": "2025-01-01",
                   "hasta": "2025-12-31",
                   "provisional": true,
                   "causas": ["La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero."],
                   "causas_detalle": [{"codigo": "apertura_sin_confirmar",
                                       "texto": "La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero."}]}]}
```

#### `POST apertura/<id>/enviar/` y `POST apertura/<id>/devolver/`

Enviar: `{empresa, version}`, borrador → en revisión, solo sin bloqueos. Con bloqueos, 409 con el `codigo` del primero, su detalle arriba y el cuerpo entero de validar:

```
POST /contabilidad/api/apertura/2/enviar/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 1}

409 {"error": "La apertura no tiene líneas: mapea los saldos o, si la empresa empieza sin saldos, crea la apertura como inicio de actividades.",
     "codigo": "sin_lineas",
     "apertura": …,
     "valida": false,
     "bloqueos": [{"codigo": "sin_lineas",
                   "texto": "La apertura no tiene líneas: mapea los saldos o, si la empresa empieza sin saldos, crea la apertura como inicio de actividades."}],
     "advertencias": [{"codigo": "sin_cuenta_declarada",
                       "texto": "Ninguna cuenta de la apertura está declarada como de clientes.",
                       "ambito": "clientes"},
                      {"codigo": "sin_cuenta_declarada",
                       "texto": "Ninguna cuenta de la apertura está declarada como de proveedores.",
                       "ambito": "proveedores"},
                      {"codigo": "sin_cuenta_declarada",
                       "texto": "Ninguna cuenta de la apertura está declarada como de inventario.",
                       "ambito": "inventario"},
                      {"codigo": "sin_cuenta_declarada",
                       "texto": "Ninguna cuenta de la apertura está declarada como de bancos.",
                       "ambito": "bancos"},
                      {"codigo": "sin_cuenta_declarada",
                       "texto": "Ninguna cuenta de la apertura está declarada como de activos fijos.",
                       "ambito": "activos"},
                      {"codigo": "sin_cuenta_declarada",
                       "texto": "Ninguna cuenta de la apertura está declarada como de saldos tributarios.",
                       "ambito": "tributario"},
                      {"codigo": "tributario_sin_saldos",
                       "texto": "No hay saldos tributarios anteriores registrados: sus arrastres quedan sin dato."}],
     "ambitos_no_aplican": [],
     "cobertura": …,
     "reportes": …}
```

(`apertura`, `cobertura` y `reportes` como en validar.)

```
POST /contabilidad/api/apertura/2/enviar/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 3}

200 {"apertura": {"id": 2,
                  "version": 4,
                  "estado": "en_revision",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "10000.00",
                  "haber": "10000.00",
                  "diferencia": "0.00",
                  "lineas": 6,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [{"ambito": "activos", "nota": "La empresa no tiene activos fijos al corte (acta de inventario)"},
                                         {"ambito": "tributario",
                                          "nota": "Sin créditos ni retenciones pendientes según la declaración de diciembre"}],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": null,
                  "enviado_por": "propietario.a",
                  "enviado_en": "2026-11-14T14:30:02.771329+00:00",
                  "revisado_por": null,
                  "confirmado_por": null,
                  "confirmado_en": null,
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.114977+00:00",
                  "motivo": ""}}
```

Devolver: `{empresa, version, motivo}`, en revisión → borrador. Vacía `enviado_por` y `enviado_en`; la historia conserva quién la envió.

```
POST /contabilidad/api/apertura/2/devolver/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 4, "motivo": "Falta el respaldo del inventario"}

200 {"apertura": {"id": 2,
                  "version": 5,
                  "estado": "borrador",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "10000.00",
                  "haber": "10000.00",
                  "diferencia": "0.00",
                  "lineas": 6,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [{"ambito": "activos", "nota": "La empresa no tiene activos fijos al corte (acta de inventario)"},
                                         {"ambito": "tributario",
                                          "nota": "Sin créditos ni retenciones pendientes según la declaración de diciembre"}],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": null,
                  "enviado_por": null,
                  "enviado_en": null,
                  "revisado_por": null,
                  "confirmado_por": null,
                  "confirmado_en": null,
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.114977+00:00",
                  "motivo": ""}}
```

```
POST /contabilidad/api/apertura/2/devolver/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 4}

400 {"error": "Revisa los datos marcados.", "codigo": "validacion", "errores": {"motivo": ["Escribe el motivo."]}}
```

#### `POST apertura/<id>/confirmar/`

`{empresa, version, clave, revisado: true, nota, incompletos_aceptados: [linea_id…]}`. `revisado`, `nota` (hasta 500), `incompletos_aceptados` y `version` se revisan antes de tomar el candado (400). Después: candado del libro → la apertura; la misma `clave_confirmacion` de una apertura ya confirmada devuelve el mismo cuerpo con `repetido: true` (también con la versión vieja); otra clave, 409 `apertura_confirmada`; `version`; estado distinto de `en_revision`, 409 `estado`; y vuelve a evaluar todo con el candado (409 con el primer bloqueo, `bloqueos` y `advertencias`). Escribe el asiento inicial (ninguno con `sin_saldos`), fija el `detalle` de cada línea con el auxiliar de su cuenta con que se acaba de validar (§6.5, regla 4; desde `72a68ee`), fija totales, `revisado_por/en` (quien confirma), `confirmado_por/en`, `incompleto_aceptado` de cada línea, `ambitos_no_aplican` con `declarado_por` y `declarado_en`, `resultado_ejercicio` según las líneas, sincroniza `InicioContable` con el corte, deja su historia (el evento `confirmada`, con `detalle_fijado`: §6.6, `GET apertura/<id>/`) y la auditoría `apertura_confirmada` con el asiento.

```
POST /contabilidad/api/apertura/2/confirmar/?empresa=1
Content-Type: application/json
{"empresa": 1,
 "version": 6,
 "clave": "confirmar-apertura-0001",
 "revisado": true,
 "nota": "Revisada contra el balance firmado y el acta de inventario",
 "incompletos_aceptados": [1, 2, 3, 4]}

200 {"apertura": {"id": 2,
                  "version": 7,
                  "estado": "confirmada",
                  "debe": "10000.00",
                  "haber": "10000.00",
                  "diferencia": "0.00",
                  "revisado_por": "propietario.a",
                  "confirmado_por": "propietario.a",
                  "confirmado_en": "2026-11-14T14:30:03.079439+00:00",
                  "asiento": {"id": 1, "numero": "2025-000001", "fecha": "2025-12-31", "debe": "10000.00", "haber": "10000.00"}},
     "cobertura": {"contabilidad": {"estado": "parcial",
                                    "causas": ["La apertura se confirmó aceptando el detalle incompleto de 4 cuenta(s)."],
                                    "causas_detalle": [{"codigo": "detalle_incompleto_aceptado",
                                                        "texto": "La apertura se confirmó aceptando el detalle incompleto de 4 cuenta(s).",
                                                        "cantidad": 4}]},
                   "cartera": {"estado": "pendiente",
                               "causas": ["El saldo de clientes en la apertura todavía no tiene su detalle.",
                                          "El saldo de proveedores en la apertura todavía no tiene su detalle."],
                               "causas_detalle": [{"codigo": "sin_detalle",
                                                   "texto": "El saldo de clientes en la apertura todavía no tiene su detalle.",
                                                   "cantidad": 1},
                                                  {"codigo": "sin_detalle",
                                                   "texto": "El saldo de proveedores en la apertura todavía no tiene su detalle.",
                                                   "cantidad": 1}],
                               "clientes": {"estado": "pendiente", "cuenta": "3000.00", "detallado": "0.00", "documentos": 0},
                               "proveedores": {"estado": "pendiente", "cuenta": "2500.00", "detallado": "0.00", "documentos": 0}},
                   "inventario": {"estado": "pendiente",
                                  "causas": ["El saldo de inventario en la apertura todavía no tiene su detalle."],
                                  "causas_detalle": [{"codigo": "sin_detalle",
                                                      "texto": "El saldo de inventario en la apertura todavía no tiene su detalle.",
                                                      "cantidad": 1}],
                                  "cuenta": "2000.00",
                                  "detallado": "0.00",
                                  "filas": 0},
                   "bancos": {"estado": "pendiente",
                              "causas": ["El saldo de bancos en la apertura todavía no tiene su detalle."],
                              "causas_detalle": [{"codigo": "sin_detalle",
                                                  "texto": "El saldo de bancos en la apertura todavía no tiene su detalle.",
                                                  "cantidad": 1}],
                              "cuenta": "5000.00",
                              "detallado": "0.00",
                              "filas": 0},
                   "activos": {"estado": "no_aplica", "causas": [], "causas_detalle": [], "cuenta": null, "detallado": null, "filas": 0},
                   "tributario": {"estado": "no_aplica", "causas": [], "causas_detalle": [], "saldos_anteriores": null},
                   "periodos": [{"mes": "2026-01",
                                 "ambitos": {"contabilidad": {"estado": "sin_cobertura",
                                                              "fuente_tipo": null,
                                                              "declarado_por": null,
                                                              "declarado_en": null},
                                             "documentos": {"estado": "sin_cobertura",
                                                            "fuente_tipo": null,
                                                            "declarado_por": null,
                                                            "declarado_en": null},
                                             "cartera": {"estado": "sin_cobertura",
                                                         "fuente_tipo": null,
                                                         "declarado_por": null,
                                                         "declarado_en": null},
                                             "inventario": {"estado": "sin_cobertura",
                                                            "fuente_tipo": null,
                                                            "declarado_por": null,
                                                            "declarado_en": null},
                                             "bancos": {"estado": "sin_cobertura",
                                                        "fuente_tipo": null,
                                                        "declarado_por": null,
                                                        "declarado_en": null}}},
                                … (10 meses más, con la misma forma)]},
     "repetido": false}
```

```
200 {"apertura": {"id": 2,
                  "version": 7,
                  "estado": "confirmada",
                  "debe": "10000.00",
                  "haber": "10000.00",
                  "diferencia": "0.00",
                  "revisado_por": "propietario.a",
                  "confirmado_por": "propietario.a",
                  "confirmado_en": "2026-11-14T14:30:03.079439+00:00",
                  "asiento": {"id": 1, "numero": "2025-000001", "fecha": "2025-12-31", "debe": "10000.00", "haber": "10000.00"}},
     "cobertura": …,
     "repetido": true}
```

(El mismo envío repetido: mismo cuerpo, `repetido: true`, ningún asiento más; `cobertura` igual que arriba.)

```
POST /contabilidad/api/apertura/2/confirmar/?empresa=1
Content-Type: application/json
{"empresa": 1,
 "version": 6,
 "clave": "confirmar-apertura-0002",
 "revisado": true,
 "nota": "Revisada contra el balance firmado y el acta de inventario",
 "incompletos_aceptados": [1, 2, 3, 4]}

409 {"error": "La apertura ya está confirmada con otro envío: vuelve a cargarla.",
     "codigo": "apertura_confirmada",
     "apertura": {"id": 2,
                  "version": 7,
                  "estado": "confirmada",
                  "debe": "10000.00",
                  "haber": "10000.00",
                  "diferencia": "0.00",
                  "revisado_por": "propietario.a",
                  "confirmado_por": "propietario.a",
                  "confirmado_en": "2026-11-14T14:30:03.079439+00:00",
                  "asiento": {"id": 1, "numero": "2025-000001", "fecha": "2025-12-31", "debe": "10000.00", "haber": "10000.00"}}}
```

```
POST /contabilidad/api/apertura/2/confirmar/?empresa=1
Content-Type: application/json
{"empresa": 1,
 "version": 6,
 "clave": "confirmar-apertura-0001",
 "revisado": true,
 "nota": "Revisada contra el balance firmado y el acta de inventario",
 "incompletos_aceptados": []}

409 {"error": "Acepta una por una las cuentas con el detalle incompleto, o completa su detalle antes de confirmar.",
     "codigo": "auxiliar_incompleto",
     "lineas": [1, 2, 3, 4],
     "bloqueos": [{"codigo": "auxiliar_incompleto",
                   "texto": "Acepta una por una las cuentas con el detalle incompleto, o completa su detalle antes de confirmar.",
                   "lineas": [1, 2, 3, 4]}],
     "advertencias": []}
```

Forma del 409 `auxiliar_incompleto` (H7 del cierre; el código ya respondía así): `"lineas"`, los ids de las líneas que
faltan por aceptar, va siempre (vacía si solo sobran); `"sobran"`, los ids aceptados que no lo necesitan, va **solo si hay
alguno**; `"bloqueos"`, cada entrada con las mismas dos claves; y `"advertencias"`. Con una línea que falta y otra que
sobra (`72a68ee`; `advertencias` recortada):

```
POST /contabilidad/api/apertura/1/confirmar/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 3, "clave": "…", "revisado": true, "nota": "", "incompletos_aceptados": [1]}

409 {"error": "Acepta una por una las cuentas con el detalle incompleto, o completa su detalle antes de confirmar.",
     "codigo": "auxiliar_incompleto",
     "lineas": [2],
     "sobran": [1],
     "bloqueos": [{"codigo": "auxiliar_incompleto",
                   "texto": "Acepta una por una las cuentas con el detalle incompleto, o completa su detalle antes de confirmar.",
                   "lineas": [2],
                   "sobran": [1]}],
     "advertencias": [{"codigo": "sin_cuenta_declarada", …}, …]}
```

Con todas las que faltan aceptadas y una de más, `"lineas": []` y `"sobran": [1]`.

```
POST /contabilidad/api/apertura/2/confirmar/?empresa=1
Content-Type: application/json
{"empresa": 1,
 "version": 6,
 "clave": "confirmar-apertura-0001",
 "revisado": false,
 "nota": "Revisada contra el balance firmado y el acta de inventario"}

400 {"error": "Revisa los datos marcados.", "codigo": "validacion", "errores": {"revisado": ["Confirma que revisaste la apertura."]}}
```

```
POST /contabilidad/api/apertura/2/confirmar/?empresa=1
Content-Type: application/json
{"empresa": 1,
 "version": 1,
 "clave": "confirmar-apertura-0001",
 "revisado": true,
 "nota": "Revisada contra el balance firmado y el acta de inventario",
 "incompletos_aceptados": [1, 2, 3, 4]}

409 {"error": "Otra persona cambió la apertura mientras la editabas: revisa cómo quedó y vuelve a intentarlo.",
     "codigo": "version",
     "apertura": {"id": 2,
                  "version": 6,
                  "estado": "en_revision",
                  "fuente": "balance_comprobacion",
                  "fuente_detalle": "Balance de comprobación al 31/12/2025 firmado por el contador",
                  "sin_saldos": false,
                  "fecha_corte": "2025-12-31",
                  "moneda": "USD",
                  "debe": "10000.00",
                  "haber": "10000.00",
                  "diferencia": "0.00",
                  "lineas": 6,
                  "pendientes": {"sin_cuenta": 0, "importe_pendiente": 0, "de_grupo": 0, "sin_clase": 0},
                  "resultado_ejercicio": "",
                  "resultado_acumulado": null,
                  "inventario_modo": "solo_conciliar",
                  "ambitos_no_aplican": [{"ambito": "activos", "nota": "La empresa no tiene activos fijos al corte (acta de inventario)"},
                                         {"ambito": "tributario",
                                          "nota": "Sin créditos ni retenciones pendientes según la declaración de diciembre"}],
                  "sustituye": null,
                  "ajustes": 0,
                  "asiento": null,
                  "enviado_por": "propietario.a",
                  "enviado_en": "2026-11-14T14:30:02.888294+00:00",
                  "revisado_por": null,
                  "confirmado_por": null,
                  "confirmado_en": null,
                  "creado_por": "propietario.a",
                  "creado_en": "2026-11-14T14:30:02.114977+00:00",
                  "motivo": ""}}
```

Otros 409 de confirmar, cada uno con `bloqueos` y `advertencias`: todos los de la regla 5; `resultado_duplicado` trae además `en_cuentas_nominales`, `en_patrimonio`, `declarado` y `resultado_acumulado`; `apertura_desbalanceada`, `debe`, `haber` y `diferencia` (debe − haber, con signo); `rango_solapado`, `asientos`, `aplicaciones` y `primera_fecha`; `cuenta_no_aplica`, `lineas` y `ambitos`; `importe_total_excedido`, `debe`, `haber` y `maximo`. 409 `clave_usada` si la clave ya la usó otra apertura. Y, fuera del orden, 409 `reintentar` (§6.1): la confirmación no se guardó y se repite con la misma `clave`.

### 6.7 Negativas comunes, tal como salen

```
GET /contabilidad/api/apertura/?empresa=2

409 {"error": "La empresa activa cambió en otra pestaña: vuelve a cargar la página para ver los datos de la empresa que tienes abierta ahora.",
     "codigo": "empresa_cambiada"}
```

```
POST /contabilidad/api/apertura/2/validar/
Content-Type: application/json
{"version": 6}

409 {"error": "El envío no indica para qué empresa se preparó: vuelve a cargar la página e inténtalo de nuevo.", "codigo": "sin_empresa"}
```

Consulta intenta confirmar:

```
POST /contabilidad/api/apertura/2/confirmar/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 6, "clave": "confirmar-consulta-0001", "revisado": true}

403 {"error": "Tu perfil no cuenta con el permiso necesario.",
     "codigo": "sin_permiso",
     "causa": "permiso",
     "permisos": ["change_confirmacion_apertura"]}
```

Plan vencido: se consulta (el diario responde 200) y no se guarda nada:

```
POST /contabilidad/api/apertura/2/validar/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 1}

403 {"error": "Tu Plan ilimitado venció el 13/11/2026. Puedes consultar tus comprobantes; renueva el plan para volver a emitir.",
     "plan": "requerido",
     "codigo": "plan",
     "causa": "licencia",
     "licencia": {"estado": "plan_vencido",
                  "solo_consulta": true,
                  "texto": "Tu Plan ilimitado venció el 13/11/2026. Puedes consultar tus comprobantes; renueva el plan para volver a emitir.",
                  "puede_gestionar": true,
                  "url": "/suscripcion/"}}
```

Complemento cerrado (empresa fuera de la lista de revisión), en una consulta y en un envío:

```
GET /contabilidad/api/apertura/?empresa=1

403 {"error": "El Complemento Contable (libros, revisión del mes, ATS, borradores del 104 y del 103, kardex e inventario valorizado) todavía no está disponible: su precio y sus condiciones están por anunciar.",
     "plan": "complemento_contable",
     "codigo": "complemento_pendiente",
     "causa": "licencia",
     "licencia": {"estado": "complemento_pendiente",
                  "solo_consulta": false,
                  "texto": "El Complemento Contable (libros, revisión del mes, ATS, borradores del 104 y del 103, kardex e inventario valorizado) todavía no está disponible: su precio y sus condiciones están por anunciar.",
                  "puede_gestionar": true,
                  "url": null}}
```

```
403 {"error": "El Complemento Contable (libros, revisión del mes, ATS, borradores del 104 y del 103, kardex e inventario valorizado) todavía no está disponible: su precio y sus condiciones están por anunciar.",
     "plan": "complemento_contable",
     "codigo": "complemento_pendiente",
     "causa": "licencia",
     "licencia": {"estado": "complemento_pendiente",
                  "solo_consulta": false,
                  "texto": "El Complemento Contable (libros, revisión del mes, ATS, borradores del 104 y del 103, kardex e inventario valorizado) todavía no está disponible: su precio y sus condiciones están por anunciar.",
                  "puede_gestionar": true,
                  "url": null}}
```

(El mismo 403 para `POST apertura/2/validar/`.)

```
GET /contabilidad/api/cuentas/clasificar/?empresa=1

405
Allow: POST {"error": "Esta ruta no admite ese método.", "codigo": "metodo"}
```

Un cruce con otra transacción que la base aborta (interbloqueo `40P01` o bloqueo no conseguido a tiempo `55P03`), en
cualquier ruta de `ApiContable` (las del kardex y del inventario no lo responden: §6.1). (`72a68ee`, simulado en validar
con el error real de psycopg, como hace `tests/test_cuentas_importacion.py::TestCruceDeBloqueos` en la confirmación de
la importación del plan):

```
POST /contabilidad/api/apertura/1/validar/?empresa=1
Content-Type: application/json
{"empresa": 1, "version": 1}

409 {"error": "Otra operación usaba los mismos datos al mismo tiempo: no se guardó nada. Vuelve a intentarlo.", "codigo": "reintentar"}
```

Se repite el mismo envío, con la misma `clave` y la misma `version` (§6.1).

### 6.8 Provisionalidad y causas

`provisional`, `causas` y `causas_detalle` salen siempre de una sola función (`core/contabilidad/reportes.py: provisionalidad(reporte, desde, hasta)`), con un registro de causas que cada bloque amplía. Causas de este bloque:

| `codigo` | Texto | Cuándo |
|---|---|---|
| `inicio_sin_configurar` | La empresa todavía no configuró su inicio contable: falta la modalidad y la fecha de corte. | sin `InicioContable` |
| `apertura_sin_confirmar` | La apertura contable no está confirmada: sin saldos iniciales confirmados no se supone que sean cero. | modalidad `saldos`, sin apertura confirmada |
| `saldo_anterior_sin_confirmar` | El saldo anterior al historial no está confirmado: no se supone que sea cero. | modalidad `historial`, sin apertura confirmada |
| `resultados_acumulados_sin_detalle` | El resultado del ejercicio del corte está en patrimonio, sin el detalle de sus ingresos, costos y gastos. | estados de resultados y 101 del ejercicio del corte, con el resultado en patrimonio |
| `aplicaciones_sin_contabilizar` | Hay cobros, pagos o descargos sobre saldos iniciales sin contabilizar. | con `cantidad`; en este corte no hay aplicaciones |
| `motor_pendiente` | Los documentos de la operación todavía no se contabilizan. | todo rango que pase de la fecha de corte, y todo rango sin inicio contable; el bloque 3 la sustituye |

Ningún rango se supone completo por tener la apertura confirmada. Las causas de la cobertura (`sin_cuenta_declarada`, `sin_detalle`, `detalle_incompleto`, `detalle_excede`, `importe_pendiente`, `detalle_incompleto_aceptado`, `tributario_sin_saldos`, `tributario_por_revisar`) son de la cobertura, no del registro.

### 6.9 Capacidades y etapa del inicio

En `GET /contabilidad/api/capacidades/` (detalle en V9, «Capacidades»):

- `apertura`: disponible, acciones `ver` (`view_apertura`), `preparar` (`add_apertura`) y `confirmar` (`change_confirmacion_apertura`); requisito `plan_cuentas_vacio`; avisos `cuentas_sin_clase`, `cuentas_sin_auxiliar`, `auxiliares_incompletos` y `vinculos_rotos`, ninguno con `decision`.
- `diario_mayor`: disponible, solo `ver` (`view_asiento`); el bloque 3 añade `exportar`.
- `cartera_inicial` e `historico`: `modulo_pendiente`, con su texto, hasta el corte 2.

```
GET /contabilidad/api/capacidades/?empresa=1

200 {"funciones": {"apertura": {"nombre": "Apertura contable",
                                "ambito": "contabilidad",
                                "estado": "disponible",
                                "causa": null,
                                "texto": null,
                                "acciones": {"ver": true, "preparar": true, "confirmar": true},
                                "faltan": [],
                                "avisos": [{"codigo": "auxiliares_incompletos",
                                            "texto": "4 cuenta(s) de la apertura tienen su detalle (clientes, proveedores, inventario…) incompleto.",
                                            "cantidad": 4,
                                            "url": null,
                                            "recurso": {"tipo": "apertura", "id": 2, "api": "/contabilidad/api/apertura/2/lineas/"},
                                            "decision": null}]},
                   "cartera_inicial": {"nombre": "Cobros y pagos sobre saldos iniciales",
                                       "ambito": "contabilidad",
                                       "estado": "modulo_pendiente",
                                       "causa": "modulo_pendiente",
                                       "texto": "Los cobros, pagos y descargos sobre los saldos iniciales de la apertura están en construcción.",
                                       "acciones": {"ver": false},
                                       "faltan": [],
                                       "avisos": []},
                   "historico": {"nombre": "Documentos anteriores al corte",
                                 "ambito": "contabilidad",
                                 "estado": "modulo_pendiente",
                                 "causa": "modulo_pendiente",
                                 "texto": "El destino de los documentos importados anteriores al corte (consulta, completar un auxiliar o reconstrucción) está en construcción.",
                                 "acciones": {"ver": false},
                                 "faltan": [],
                                 "avisos": []},
                   "diario_mayor": {"nombre": "Diario, mayor y balance de comprobación",
                                    "ambito": "contabilidad",
                                    "estado": "disponible",
                                    "causa": null,
                                    "texto": null,
                                    "acciones": {"ver": true},
                                    "faltan": [],
                                    "avisos": []},
                   …}}
```

En `GET /contabilidad/api/inicio/`, `etapas.apertura` es `{"estado": "sin_configurar" | "pendiente" | "en_revision" | "confirmada", "fecha": corte | null, "causa": null}` (`no_disponible` con la causa del contrato de capacidades si el usuario no puede ver la apertura: sin licencia o sin permiso).

## 7. Documentos anteriores y cobertura tributaria

**Pendiente del corte 2** (Parte F de la especificación): destinos `consulta`, `auxiliar_apertura` y `reconstruccion`, vínculo por clave de acceso o candidato revisado, y la guarda de la importación con activación por empresa. Propuesta de Codex del 13/11:

- Importar un documento con fecha hasta el corte inclusive ofrece primero consulta o completar auxiliar. No genera ventas, compras, stock o asiento automáticamente.
- Si ya existe por clave de acceso, vincular. Si la apertura solo tiene tercero y número, mostrar candidatos y exigir coincidencia revisada; no inventar una clave ni unir documentos ambiguos.
- Reconstruir un período que ya está incluido en la apertura requiere plan explícito de sustitución/reconciliación; bloquear el solapamiento por defecto.
- Un archivo importado después del corte puede corresponder a un hecho anterior. No basta la fecha de subida para decidir efectos.
- 104/103/ATS requieren información tributaria del período y reglas vigentes. El estado financiero por sí solo no aporta todos sus documentos, tarifas, retenciones y casilleros.
- Para 101/estados anuales: incluir resultados acumulados al corte, movimientos posteriores y conciliación tributaria. Mostrar por reporte alcance y causa de provisionalidad; una cobertura parcial no se muestra como año completo.
- Se puede emitir un estado de situación a una fecha posterior con apertura validada y movimientos conciliados sin reconstruir todos los años anteriores. No exigir historial innecesario para ese reporte. Comparativos de años sin información deben decir «sin cobertura», no cero.

## 8. Pruebas de aceptación

| # | Prueba | Estado tras el corte 1 | Dónde |
|---|---|---|---|
| 1 | Saldos: corte 31/12 y operaciones desde 01/01; exactamente un asiento inicial de 10.000/10.000, incluso con doble clic/concurrencia. | cubierta | `tests/test_apertura.py::TestAceptacion1`; en PostgreSQL, dos confirmaciones a la vez con la misma clave y con claves distintas, `tests/test_zz_apertura_concurrencia_pg.py` |
| 2 | Importe faltante se mantiene pendiente. Diferencia no cero o cuenta de grupo bloquea confirmar; no cuenta automática para cuadrar. | cubierta | `tests/test_apertura.py::TestAceptacion2` |
| 3 | Cobro de 500 sobre auxiliar inicial de clientes de 3.000 deja 2.500, banco +500 y ningún nuevo ingreso/IVA por la venta histórica. | pendiente del corte 2 | — |
| 4 | Importar XML de esa factura inicial completa/vincula el auxiliar sin aumentar cartera, ventas, impuestos, asientos ni stock. | pendiente del corte 2 | — |
| 5 | Inventario inicial se distribuye por almacén, cantidad/costo concilian y repetir no duplica existencias. | pendiente del corte 2 | — |
| 6 | Historial desde un período intermedio exige saldo anterior confirmado; sin él los reportes lo indican. Reconstrucción solapada queda bloqueada. | en parte: el historial sin saldo anterior confirmado deja la cobertura `pendiente` con `saldo_anterior_sin_confirmar` y el diario provisional; la reconstrucción es del corte 2 | `tests/test_apertura.py::TestConfirmar::test_historial` |
| 7 | Corte a mitad de año: resultados acumulados más movimientos posteriores cuadran con el ejercicio; no duplicar resultado en patrimonio y cuentas nominales. 101 incompleto se identifica como provisional. | cubierta (regla 6; desde `72a68ee`, también con N = P = 0) | `tests/test_apertura.py::TestAceptacion7` (con `test_sin_resultado_en_las_lineas_lo_declarado_las_contradice` y `test_sin_resultado_en_las_lineas_lo_que_vale`) |
| 8 | Dos empresas: cuentas, documentos, archivos y saldos aislados; 409 en pestaña vieja, permisos por acción y control de versiones. | cubierta | `tests/test_apertura.py::TestAceptacion8`, `tests/test_apertura_preparar.py`; seguridad por filas en `tests/test_zz_apertura_concurrencia_pg.py` y `tests/test_rls_libro_apertura.py` |
| 9 | Reapertura/ajuste con movimientos posteriores mantiene trazabilidad, aplicaciones y períodos; no elimina efectos sin reverso. | pendiente del corte 2 | — |
| 10 | Confirmar apertura no envía nada al SRI ni crea una factura nueva. La emisión básica sigue funcionando aunque Contabilidad no esté contratada. | cubierta | `tests/test_apertura.py::TestAceptacion10` |

## 9. Propiedad y salida

Codex: diseño y adaptación responsive de este asistente, componentes de mapeo, estados de cobertura y reportes. Propuesta visual en `propuestas/apertura-contable/`; no está conectada a una API ni entra al menú productivo.

Claude: modelos/migraciones, servicios, permisos, contratos definitivos, importadores, idempotencia, asientos y despliegue compatible. Completar el núcleo genérico; no postergar cuentas/apertura por falta de precio o de una plantilla oficial. Los saldos reales, la matriz y la aprobación tributaria son datos de configuración/validación necesarios para cerrar cada empresa, no motivos para dejar sin construir el motor.

Revisar con la propietaria el diseño antes de conectarlo a la aplicación, como se pidió. Al entregar backend, documentar endpoints reales y ejemplos; Codex integra sin cambiar campos ni reglas fiscales. Se conserva la aprobación correspondiente a publicación y las pruebas de continuidad: este contrato no autoriza por sí solo una migración en producción.
