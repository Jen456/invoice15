# «Verificar en el SRI» en los XML importados

Primera entrega, rama `fase/pe-verificar-sri`. Integra la entrega de Codex (`31b4e6f`: consulta fuera de rango, migración
`importacion.0008`) y la amplía.

## 1. Por qué el botón parecía no hacer nada

Hubo tres causas, reproducidas con el código publicado (`e0f2902`), SQLite y el SRI simulado en el navegador:

1. **Sin respuesta visible.** `importacion.js` enviaba el botón a `POST /importacion/api/documentos/<id>/verificar/` y
   recargaba la página. No mostraba ningún mensaje ni la hora de la consulta. Si el resultado repetía el anterior (por
   ejemplo, «El SRI no respondió» otra vez), la pantalla no cambiaba.
2. **Rechazos falsos.** Toda respuesta distinta de AUTORIZADO o EN PROCESO quedaba como «El SRI no la autoriza», que
   impide incorporar. Eso incluía la consulta que el SRI rechaza por la fecha de emisión: estado `RECHAZADA`, código 80 y
   «fecha fuera del rango» (caso de El Rosado, del 01/01/2026). Así, una factura autorizada aparecía rechazada y bloqueada.
3. **Respuestas perdidas.** Una consulta fallida reemplazaba una respuesta anterior del SRI. Por ejemplo, una
   autorización confirmada volvía a «sin verificar» por un tiempo de espera agotado.

Ahora el botón es un formulario normal hacia la página (`form.fp-import-verificar`, campo `accion=verificar`). Funciona
sin JavaScript. La página responde con el resultado y su hora. El JavaScript solo evita el doble envío y avisa que la
consulta puede tardar.

## 2. Tres dimensiones separadas

| Dimensión | Dónde | Qué dice |
|---|---|---|
| Lo que declara el XML | `servicios.autorizacion_del_xml(documento)`, calculado de `datos`, `numero_autorizacion` y el origen del archivo | `declarada` (el archivo trae AUTORIZADO), `sin_autorizacion` (comprobante sin autorización), `del_sri` (el XML lo entregó el SRI) o `sin_xml` (solo hay clave) |
| Lo que respondió el SRI | `estado_verificacion` | La tabla de la sección 3 |
| Revisión interna del comercio | `estado_revision` (sin cambios) | Pendiente, aprobado, vinculado o descartado. Verificar no la cambia |

El último intento queda en el mismo documento: `verificado_en` (fecha y hora de la última consulta, con cualquier
resultado), `ultima_consulta_por`, `ultima_consulta_resultado` y `ultima_consulta_mensaje`. `respuesta_sri_en` guarda la
fecha de la última respuesta concluyente. La bitácora (`EventoImportacion`, tipos `verificacion` y `xml_no_recuperado`)
guarda todos los intentos con `resultado`, `conservado`, `estados_sri` y los mensajes del SRI.

La ficha del documento muestra un panel «Verificación en el SRI» con cuatro filas: respuesta del SRI, autorización
declarada en el XML, última consulta (fecha, usuario, resultado y mensaje) y revisión interna del comercio. El botón dice
«Verificar en el SRI» o, si ya hubo una consulta, «Volver a verificar en el SRI».

## 3. Estados y condiciones exactas del SRI

La consulta es `autorizacionComprobante(clave)` de `AutorizacionComprobantesOffline` (`sri_autorizacion.py`).

| Resultado | `estado_verificacion` | Condición exacta | ¿Concluyente? | ¿Impide incorporar? |
|---|---|---|---|---|
| **1. Autorización confirmada** | `verificada_sri` | `estado` AUTORIZADO (o AUT) con `comprobante`, el XML devuelto se valida y coinciden la clave, el RUC del emisor, el receptor, la fecha, el número, la base, el IVA y el total | Sí | No |
| Autorizada pero distinta | `discrepancia_sri` | Igual que la anterior, pero algún campo comparado difiere del XML importado | Sí | Sí (pasa a revisión manual) |
| **2. Rechazo confirmado** | `no_autorizada_sri` | Todas las autorizaciones devueltas dicen NO AUTORIZADO (NO AUTORIZADA o NAT) | Sí | Sí |
| El SRI no tiene la clave | `no_encontrada_sri` | Sin autorizaciones y `numeroComprobantes = 0` | Sí | Sí. Se trata como no autorizada, pero no es un «rechazo» (ver sección 4) |
| **3. Autorización declarada en el XML** | `declarada_en_archivo` | El archivo trae `<autorizacion>` con AUTORIZADO y el SRI todavía no dio una respuesta concluyente | No | No, pero exige `confirmar_sin_verificar` si la regla pide verificación |
| Sin autorización en el XML | `sin_autorizacion` | El archivo trae solo el comprobante y el SRI todavía no respondió | No | Igual que la anterior |
| **4. Fallo de consulta** | `sri_no_disponible` | Tiempo de espera agotado, error de red, fallo SOAP, error HTTP, consulta «fuera de rango», respuesta inesperada o no concluyente (RECHAZADA o DEVUELTA sin ese detalle, estado vacío o nuevo, otra clave, AUTORIZADO sin comprobante, XML del SRI que no se valida) o clave no válida | No | Igual que la anterior: no es un rechazo |
| En proceso | `en_proceso_sri` | EN PROCESO, EN PROCESAMIENTO, POR PROCESAR o PPR | No | Igual que la anterior |

**Regla:** una respuesta concluyente siempre fija el estado. Un intento en proceso o fallido solo cambia el estado si no
había una respuesta concluyente anterior. En ese caso queda el último intento con su motivo y el aviso «Este intento no
cambió la respuesta anterior del SRI».

**Motivo del último intento** (`ultima_consulta_resultado`): `autorizado`, `discrepancia`, `no_autorizado`,
`no_encontrado` y `en_proceso`, más los motivos de fallo:

- `tiempo_agotado`: `TimeoutError` o `URLError` por tiempo agotado;
- `sin_conexion`: otro `URLError`, `ConnectionError` u `OSError`;
- `servicio_no_disponible`: `TransportError` HTTP de suds;
- `error_sri`: `WebFault` (SOAP);
- `fuera_de_rango`;
- `respuesta_inesperada`;
- `clave_invalida`.

Con `fuera_de_rango`, la ficha enlaza el portal público de validez del SRI. La tarea programada no reintenta sola
`fuera_de_rango` ni `clave_invalida`, porque esos resultados no cambiarían.

## 4. Decisión: «el SRI no tiene esta clave»

Es un caso aparte, `no_encontrada_sri`, con la etiqueta «El SRI no tiene esa clave»:

- **Se trata como no autorizada.** Impide aprobar, vincular, crear la compra o registrar la retención. Un comprobante
  que el SRI no registra no sustenta crédito tributario.
- **No lleva la etiqueta de rechazo.** El SRI no dijo NO AUTORIZADO. Puede ser un comprobante nunca enviado, o uno
  enviado hace poco por el emisor.
- **Se puede reintentar.** El reintento es manual desde la ficha o desde el lote (`REINTENTABLES`). La tarea programada
  no lo reintenta sola, igual que antes.

Si el SRI responde sin autorizaciones y **sin** `numeroComprobantes = 0`, es una respuesta inesperada: fallo de consulta,
no «sin la clave».

## 5. Reintento sin duplicar y concurrencia

- Reintentar es volver a llamar a `verificar_en_sri` sobre el mismo documento. Actualiza su estado y su último intento.
  Nunca crea otro documento, compra ni venta. La única escritura además del documento es el XML que entrega el SRI, que
  se guarda una vez por empresa (SHA-256).
- **Consulta en curso:** antes de consultar, una actualización condicionada marca `consulta_en_curso`. Es atómica también
  en SQLite. Con otra consulta en curso para el mismo documento (doble clic, otra pestaña u otra persona), no se llama al
  SRI:
  - la página muestra «Ya hay una consulta al SRI en curso…»;
  - la API responde 409 con `codigo = consulta_en_curso`;
  - el lote salta ese documento.

  La marca caduca a los `limites.SRI_CONSULTA_EN_CURSO_SEGUNDOS` (90 s), por si el proceso se corta. Si el proceso
  falla, la marca se libera.
- **Guardar el resultado:** se bloquea la fila (`select_for_update`). La regla «un fallo no borra una respuesta
  concluyente» se aplica sobre la fila recién leída, así que una consulta de la tarea programada y otra manual no se
  pisan.
- Si otro proceso completó el XML mientras tanto, `recuperar_xml` compara con él en vez de darlo por verificado.
- **XML subido después:** un XML que llega después para un documento que solo tenía la clave **no** reemplaza una
  respuesta concluyente del SRI. Por ejemplo, un «no autorizado» no pasa a «declarada» por subir un archivo que dice
  AUTORIZADO. Para cambiarlo hay que volver a verificar.

## 6. Decisiones que dependen de la verificación

La lista de estados que impiden incorporar está en un solo lugar, `DocumentoImportado.VERIFICACION_BLOQUEA`. La usan:

- `servicios._exigir_revisable` (aprobar y vincular);
- `compras.propuesta_compra` y `crear_compra_desde_documento`;
- `recibidos` (retención recibida);
- `plan_incorporacion` (incorporación en lote).

Todo lo que no es `verificada_sri` pide `confirmar_sin_verificar` cuando la regla exige verificación, como antes. Las
bandejas y la API muestran la etiqueta del estado. Los colores de `fp-import-tag` son verde para la autorización
confirmada, ámbar para lo declarado, en proceso o fallido, y rojo para lo que impide incorporar. La API añade:

- `estados.verificacion.resultado` y `estados.verificacion.concluyente`;
- `verificacion_sri`, con `sri`, `xml`, `revision_interna`, `ultima_consulta`, `fuera_de_rango` y `en_curso`.

Los campos anteriores se conservan.

## 7. Migraciones

- **`importacion.0008_estado_fuera_rango_sri`** (Codex): agrega la opción `fuera_rango_sri`. Solo cambia `choices` y su
  vuelta no toca la base.
- **`importacion.0009_verificacion_sri_ultimo_intento`** (aditiva y reversible):
  - **Estructura:** cinco columnas nuevas, nulas o con valor por defecto, en `importacion_documentoimportado`. La política
    de seguridad por filas de 0002 cubre la fila. También cambian los textos de `estado_verificacion` y `verificado_en`.
  - **Compatible con la versión que sigue atendiendo (revisión del PR #1, R1):** `ultima_consulta_resultado` y
    `ultima_consulta_mensaje` son NOT NULL con `db_default=''`, en la migración y en el modelo. El valor por defecto queda
    en la base: la versión publicada (importacion 0007) inserta sin nombrarlas durante el cambio de versión, o si se
    vuelve a ella sin restaurar la base. En PostgreSQL es `ADD COLUMN … DEFAULT '' NOT NULL`, que no reescribe la tabla.
    Ensayo y plan: [plan-de-despliegue.md](plan-de-despliegue.md).
  - **Lo que la versión anterior verifica después de migrar** queda con un estado consultado y sin resultado del último
    intento. `completar()` (la misma función del relleno) solo toca esas filas, y la tarea programada
    `procesar_importaciones` la vuelve a aplicar en cada ejecución
    (`servicios.completar_consultas_de_la_version_anterior`): mismo estado, resultado, mensaje y usuario que habría puesto
    la migración. Lo que ya tiene resultado no cambia.
  - **Límite conocido:** si la versión anterior vuelve a verificar un documento que YA tenía resultado, deja su estado y
    su fecha y no toca el resultado, que queda desactualizado hasta que esta versión lo verifique de nuevo. En una
    publicación normal solo ocurre si alguien pulsa «Verificar» en la versión anterior, entre la migración y el
    reinicio, sobre un documento ya consultado (hoy son 4).
  - **Ida (datos):** el último evento de verificación de cada documento da el usuario y el mensaje. Los estados se
    traducen así:

    | Antes | Después: estado y resultado del último intento |
    |---|---|
    | `verificada_sri` | igual, `autorizado` |
    | `no_autorizada_sri` | igual (sigue impidiendo incorporar), `rechazo_anterior`. El código anterior no guardaba el estado exacto del SRI: una consulta rechazada por la fecha también quedaba así. Se muestra «El SRI no la autorizó (consulta anterior: vuelve a verificar)», no «Rechazo confirmado» |
    | `no_encontrada_sri` | igual, `no_encontrado`. Si el mensaje era «La clave no es válida»: `sri_no_disponible`, `clave_invalida` |
    | `discrepancia_sri` | igual, `discrepancia`. Si el SRI devolvió un XML que no se validó, o el documento no tenía XML: `sri_no_disponible`, `respuesta_inesperada` |
    | `sri_no_disponible` | igual, `sin_respuesta` |
    | `fuera_rango_sri` (0008) | `sri_no_disponible`, `fuera_de_rango` |
    | `en_proceso_sri` | igual, `en_proceso` |
    | `declarada_en_archivo`, `sin_autorizacion` | iguales, sin intento |

    En las respuestas concluyentes, `respuesta_sri_en` toma el valor de `verificado_en`. No se borra nada.
  - **Vuelta:** `sri_no_disponible` con `fuera_de_rango` vuelve a `fuera_rango_sri`, y con `clave_invalida` a
    `no_encontrada_sri`. Los demás códigos existen en 0008 y se quedan. Después se quitan las columnas. El historial queda
    en la bitácora.
  - **PostgreSQL:** con la RLS forzada, la migración necesita `app.platform = on`. `desplegar.sh` migra con
    `PGOPTIONS="-c app.platform=on"`. Si falta, la migración la activa solo dentro de su transacción y la restaura al
    terminar.
- `tests/test_migracion_vuelta_fase.py` cuenta 43 migraciones pendientes tras la vuelta. Antes eran 41: se suman 0008 y
  0009.

## 8. Cómo se verificó

- **`tests/test_importacion_verificacion_sri.py`** (30 pruebas, SRI simulado y sin red):
  - **Motivos de fallo:** `TestConsultaFallida`.
  - **Aceptación:** `TestCuatroResultados::test_xml_autorizado_queda_confirmado_con_el_intento`,
    `::test_rechazo_confirmado_bloquea_la_compra` y `::test_tiempo_agotado_no_es_rechazo_y_el_reintento_no_duplica`.
  - **Casos adicionales:** sin la clave, en proceso, XML del SRI que no se valida, y un fallo posterior que no borra la
    respuesta concluyente.
  - **Reintento y consulta en curso:** `TestReintentoSinDuplicar`, por la página, la API y el lote.
  - **Recuperación del XML y XML subido después:** `TestSinXmlYSubidas`.
  - **Pantalla:** `TestPantalla`, que comprueba el formulario real del botón, las tres dimensiones, el último intento y el
    enlace del fuera de rango.
  - **Migración 0009:** `TestMigracion0009`, con los modelos históricos (ida y vuelta).
- **`tests/test_convivencia_versiones.py`** (revisión del PR #1, R1; SQLite y PostgreSQL): cada columna NOT NULL que la
  entrega agrega a una tabla existente tiene su valor por defecto en la base; los modelos de la versión publicada
  (importacion 0007, proformas 0003) importan y cotizan sobre la base migrada; lo que esa versión verifica después de
  0009 se completa con las reglas de la migración y una segunda pasada no cambia nada; modelos y migraciones coinciden.
  Con `tests/test_revision_primera_entrega_codex.py`, el reproductor de Codex.
- **`tests/test_zz_importacion_verificacion_concurrencia_pg.py`** (solo PostgreSQL): tres verificaciones a la vez del
  mismo documento hacen una sola consulta al SRI, dejan un intento y un solo documento.
- **Pruebas actualizadas:** la de Codex en `test_importacion_flujo.py` (el fuera de rango ahora es un fallo con su
  motivo), un texto en `test_importacion_masiva.py` («el SRI», sin pasar las siglas a minúsculas) y el conteo de
  `test_migracion_vuelta_fase.py`.
- **Navegador:** Chromium (Playwright) contra `runserver` local, en 127.0.0.1, con SQLite, datos ficticios y el SRI
  simulado (sin red).
  - **Código publicado:** el clic sí llega a la API (`POST …/verificar/`, 200) y la página se recarga, pero sin mensaje
    ni hora. Dos tiempos agotados seguidos dejan la pantalla igual. El fuera de rango aparece como «El SRI no la
    autoriza». Tras una autorización, un tiempo agotado la devuelve a «El SRI no respondió».
  - **Esta rama:**
    - el clic es un `POST` a la ficha (302) y la ficha muestra el aviso «Resultado de la consulta al SRI (fecha y
      hora): …», el panel con la última consulta y el usuario;
    - autorizado, NO AUTORIZADO, tiempo agotado y fuera de rango se muestran como resultados distintos;
    - un tiempo agotado conserva la autorización o el rechazo anteriores;
    - el doble clic hace un solo `POST` y una sola consulta;
    - sin desborde horizontal a 360 px, 390 px y 1280 px.

## 9. Pendiente y decisiones de la propietaria

- **Rechazos de antes.** Los documentos que hoy dicen «El SRI no la autoriza» siguen sin poder incorporarse tras migrar,
  con la etiqueta «consulta anterior: vuelve a verificar». Al volver a verificarlos se sabrá si eran rechazos reales o
  consultas fuera de rango. Hay que decidir si se reverifican uno por uno desde la ficha o con una tarea masiva. La tarea
  masiva consultaría al SRI en producción y no está incluida.
- **Fuera de rango.** El SRI no admite la consulta automática de comprobantes antiguos. Esos documentos quedan como «No
  se pudo verificar» con el enlace al portal. Para incorporarlos hay que confirmar que se hace sin verificar, como hoy.
  Falta decidir si se permite registrar a mano «verificado en el portal».
