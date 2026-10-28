# D0 — Catálogo de retenciones: códigos 310 y 332E (informe definitivo)

**Fecha:** 28/10/2026 (America/Guayaquil)
**Base revisada:** rama `plataforma`, commit `8d2eead`, solo lectura. No se consultaron bases de datos.
**Origen:** síntesis D0 y dos verificaciones adversariales (`registros-fase/d0-sintesis-verif.json`). Este informe la sustituye e incorpora todas las correcciones de los verificadores. Lo que se programa ahora está en `registros-fase/espec-d0-fase-a.md`.
**Estado:** la Fase A (sin cambio fiscal) se implementa ya. La Fase B (cambio fiscal) espera las respuestas de la §6.

---

## 1. Resumen ejecutivo

En agosto de 2026 el SRI cambió cuánto se retiene del impuesto a la renta al pagar transporte terrestre comercial
(operadoras, sus socios y sus clientes): hasta el 31/12/2026 rige una transición y desde el 01/01/2027, la regla definitiva.
El sistema retiene por defecto 1 % al transporte y 0 % a lo que una cooperativa paga a sus socios, y deja escribir otro
porcentaje. Eso sigue valiendo durante la transición: hoy no hay ningún número que corregir.
Lo ya emitido no cambia con nada de esto, porque cada retención guarda su propia copia del porcentaje.
Ahora se añade al sistema desde y hasta cuándo vale cada porcentaje, sin alterar ningún resultado.
Para el 01/01/2027 hacen falta las respuestas de la propietaria y su contador a ocho preguntas cerradas (§6); las que
tocan 2027 se necesitan hacia el **15/12/2026**.

---

## 2. Qué tiene el sistema (commit 8d2eead)

Catálogo de plataforma `comprobantes.CodigoRetencion`, cargado por `0004_catalogo_retenciones.py` [R1]:

| Código | Concepto | % | Editable | Común | Fuente que cita la fila |
|---|---|---|---|---|---|
| 310 | Servicio de transporte privado de pasajeros o transporte público o privado de carga | 1,00 | Sí, de 0 a 100 | Sí | «Catálogo ATS SRI (06/08/2026), tabla 3.10; Res. NAC-DGERCGC26-00000009 (desde 01/03/2026)» |
| 332E | Valores entregados por las cooperativas de transporte a sus socios | 0,00 | Sí, de 0 a 100 | No | la misma |
| 3440 | Otras retenciones aplicables el 3% (incluye pago utilidades a extrabajadores) | 3,00 | No | Sí | la misma |

- **Incoherencia de la fuente.** La fila cita el Catálogo ATS del 06/08/2026 (no «solo la Res. 09»), pero para el 310 y el
  332E carga los valores del bloque «desde 01/03/2026» (1 y 0), sin la notación «1 /0» y «0 /1» de la Res. 28 que trae ese
  mismo archivo; para el 3440 carga el texto del bloque 06/08. La Fase A lo resuelve con una fila por vigencia, cada una con
  su fuente.
- **Sin vigencias.** El modelo no tiene fechas y la restricción única es `(impuesto, codigo)`. `retenciones.calcular()`
  toma el porcentaje del catálogo, salvo en los códigos editables, donde acepta el que escriba el usuario entre 0 y 100 [R3].
- **Fecha.** La retención se emite siempre con la fecha del día (`timezone.localdate()`), no se puede antedatar y el
  catálogo se lee ese mismo día. El `periodoFiscal` del XML sale de la fecha de emisión [R4]. La fecha de la factura del
  proveedor se pide y no puede ser futura [R3].
- **Lo emitido está protegido.** `RetencionDetalle` guarda su propia copia de impuesto, código, concepto, base, porcentaje
  y valor, sin clave foránea al catálogo [R2]. El XML (`codigoRetencion`, `porcentajeRetener`) y el RIDE salen de esa copia;
  el XML firmado queda en `xml_signed`, y si el SRI devuelve la retención se regenera desde los detalles guardados
  (`emision.py:290`) [R4][R6]. Cambiar o editar el catálogo no altera lo emitido ni lo que está en proceso.
- **Desde cuándo hay retenciones.** El módulo entró en el commit `aafbe4a` (14/10/2026, 19:01 UTC). *Inferido* por esa
  fecha, sin consultar la base: no hay retenciones del sistema anteriores a la Res. 28, se tome la fecha de inicio que se
  tome (D0-a).
- **Riesgos de hoy (no tocan lo emitido):**
  - la administración permite editar `porcentaje` en la propia lista, sin historial;
  - «Emitir» vuelve a calcular: si el catálogo cambia entre «Revisar» y «Emitir», se emite un valor distinto del revisado
    sin aviso;
  - con filas por vigencia y sin adaptar el código fallarían `views.py:130` (`.first()`), `forms.py:51` (códigos repetidos)
    y las pruebas con `.get(impuesto, codigo)` (`test_retenciones.py:45`, `test_liquidaciones.py:223/247`).

---

## 3. Qué dice la norma

### 3.1 Tabla por vigencia

| Período | 310 | 332E | Base |
|---|---|---|---|
| 01/03/2026 – 12/07/2026 | 1 % fijo | 0 % | 310: Res. 09, art. 2, num. 2 a) [5]. 332E: catálogo, bloque 01/03 [6]; la tabla del SRI lo funda en «LRTI/ RLRTI», **no en la Res. 09**, que no menciona operadoras, socios ni el 332E [9]. Operadoras y socios: régimen de la Res. NAC-DGERCGC17-00000295 (RO S. 3, 30/05/2017), **vigente hasta el 12/07/2026**; según la guía SRI de 2017, la operadora retenía al socio 0 % (código «332») o 1 % (código 310) [10]. |
| 13/07/2026 – 30/07/2026 | 1 % fijo | 0 % (discutible) | La Res. 24 (RO 4.º S. 324, 13/07/2026) deroga la 17-295, y su art. 8 original remite al «porcentaje previsto en la normativa vigente» [4]. 310: Res. 09. 332E: 0 % según el catálogo y la tabla del SRI (base LRTI/RLRTI), discutible tras la derogación: el art. innumerado a continuación del 114 del RLRTI manda retener a los socios «en los mismos porcentajes … aplicables para el sector de transporte» (1 %) [4]. Sin efecto práctico: el módulo no existía. |
| Desde la Res. 28 (31/07, 01/08, 03/08 o 01/09/2026; §3.4 y D0-a) hasta el 31/12/2026 | «1 /0 según resolución NAC-DGERCGC26-00000028» [6] | «0 /1 según resolución NAC-DGERCGC26-00000028» [6] | Res. 28 [1][2]. **Transición** (disp. trans. quinta), para las operadoras que siguen facturando por medio de sus socios como puntos de emisión: operadora → socio 0 %; cliente → socio 1 %; cliente → operadora con unidades propias 1 %. **Art. 8 nuevo** para las demás, en lectura literal (D0-c). |
| Desde el 01/01/2027 | según D0-b y D0-f | según D0-b y D0-f | Art. 8 nuevo para todas [1]: operadora → socio 1 %; cliente → operadora con unidades de socios 0 %; cliente → operadora con unidades propias 1 %. Qué código lleva cada caso es inferido (§4). |

### 3.2 Res. NAC-DGERCGC26-00000028

- Firmada el 31/07/2026 y publicada en el Registro Oficial, 5.º Suplemento Nº 339, del lunes 03/08/2026 [1][2][3].
  Disposición final: «tendrá vigencia a partir de su suscripción, sin perjuicio de su publicación en el Registro Oficial».
  Eso es lo que *dice* la resolución; su fecha efectiva es la duda D0-a (§3.4).
- Su artículo único reforma la Res. 24:
  - sustituye el art. 8 (escenarios del régimen definitivo, §3.1);
  - reforma las transitorias primera y tercera (plazos «hasta el 31 de diciembre de 2026»; la tercera es el requisito de la
    placa en la factura electrónica de las operadoras);
  - reforma la **transitoria segunda**: «A partir del 1 de enero de 2027» el SRI actualiza de oficio la actividad de los
    socios o accionistas a «Servicio de transporte únicamente de socios o accionistas a operadoras», que solo permite
    facturar a la operadora, y agrega: «El socio o accionista de la operadora de transporte, de forma voluntaria, y antes de
    la fecha indicada, podrá solicitar la actualización de esta actividad en el Registro Único de Contribuyentes para la
    aplicación de las disposiciones señaladas en la presente resolución». **Cada socio puede adelantarse** al 01/01/2027;
  - agrega la **cuarta** (los socios siguen como puntos de emisión de la operadora hasta el 31/12/2026, con su razón social
    y RUC en la información adicional de la factura) y la **quinta** (transición, §3.1).
- Habla de «operadoras» y de «socios o accionistas»; el concepto del 332E sigue diciendo «cooperativas … socios» (D0-g).

### 3.3 Momento de la retención

- Res. 09, art. 8: «La retención se efectuará el momento en que se realice el pago o se acredite en cuenta, lo que ocurra
  primero» [5]. Sus arts. 1 y 2 aplican los porcentajes a los pagos o acreditaciones en cuenta, y su transitoria única separa
  las retenciones «que deban realizarse entre el 1 y el 15 de marzo de 2026» de la emisión de su comprobante (permitida hasta
  el 31/03/2026). Ya consta en `NORMA-RETENCIONES-2026-10.md`, l. 46 [R7].
- Consecuencia: el porcentaje aplicable es el vigente en la fecha del pago o del crédito en cuenta, no en la de emisión del
  comprobante. Hoy no hay diferencia práctica (los valores por defecto no cambian entre agosto y diciembre), pero el
  01/01/2027 sí. La regla no está en duda: D0-d decide **cómo obtiene el sistema esa fecha**.

### 3.4 Fecha de inicio de la Res. 28: cuatro posibles

| Fecha | Fundamento |
|---|---|
| 31/07/2026 | Firma. La disposición final dice regir «a partir de su suscripción» [1]. |
| 01/08/2026 | Catálogo ATS, bloque «Desde 01/08/2026» [6]; DIMM ATS 1.19.0, donde el 310 pasa de fijo a libre el 2026-08-01 [8]. Ambos validan por mes. |
| 03/08/2026 | Publicación. Art. 11 del Código Tributario, inciso primero: las normas tributarias «regirán a partir de su publicación en el Registro Oficial, salvo que se establezcan fechas de vigencia posteriores a la misma» [11][12]. Una vigencia anterior a la publicación choca con ese inciso. |
| 01/09/2026 | Art. 11, inciso segundo: las normas sobre tributos que se liquidan por períodos «se aplicarán … desde el primer día del mes siguiente, cuando se trate de períodos menores» [11][12]. La página del SRI presenta el Programa ATS 1.19.0 «para los periodos fiscales septiembre 2026 en adelante» [7], aunque por dentro valida el 310 libre desde el 2026-08-01 [8]. |

Ninguna de las cuatro afecta a lo emitido: la primera retención del sistema no puede ser anterior al 14/10/2026 (§2).

### 3.5 Herramientas del SRI

**Catálogo ATS** (actualización 06/08/2026; sigue siendo el publicado al 28/10/2026) [6][7], hoja «TABLAS RETENCIONES»,
tabla 3.10:

| Bloque | 310 (fila 16) | 332E (fila 61) | 3440 (fila 77) |
|---|---|---|---|
| Desde 01/09/2025 y desde 01/02/2026 | 1 | 0 | 2,75 |
| Desde 01/03/2026 | 1 | 0 | 3 |
| **Desde 01/08/2026** | «1 /0 según resolución NAC-DGERCGC26-00000028» | «0 /1 según resolución NAC-DGERCGC26-00000028» | 3 |
| Desde 06/08/2026 | igual al 01/08 | igual al 01/08 | 3; el concepto agrega «(incluye pago utilidades a extrabajadores)» |

Entre el bloque 01/03 y el 01/08 solo cambian el 310 y el 332E; entre el 01/08 y el 06/08, solo el texto del 3440 (127
códigos por bloque, comparados celda a celda por los dos verificadores).

**DIMM ATS 1.19.0** (base interna `bdd_dimm_anexos.script` del 04/09/2026) [8]:
- **310:** 1,00 fijo (marca «N») del 2016-05-01 al 2026-07-31; desde el 2026-08-01, libre (marca «S»), base 0,00.
- **332E:** libre con base 0,00 desde el 2018-03-01. **En el DIMM el cambio del 01/08/2026 solo afecta al 310.** El
  2026-09-01 el 332E cambia de concepto interno (332 → 7332) sin cambio de tasa, cuando el DIMM separa el 332 (que pasa a
  fijo, concepto 1332).

**Tabla de retenciones del SRI** (grabada el 31/07/2026; todavía sin la Res. 28) [9]: 310 = 1 (Res. 09, art. 2, num. 2,
lit. a); 332E = 0, base «LRTI/ RLRTI», casillero 310 del formulario 103.

### 3.6 Lo que no se pudo verificar

- **Que la Res. 09 no se haya reformado después: no verificado.** La tabla del SRI [9] es del 31/07/2026 y no recoge ni la
  Res. 28; no se revisaron una por una las resoluciones NAC-DGERCGC26-00000029 a 00000033 ni las de septiembre y octubre.
  Las búsquedas (incluido el índice de JEZL [18]) no encontraron reformas, pero eso no lo prueba.
- Qué rango acepta el DIMM en los conceptos libres (no se descompiló su validación).
- Casillero del formulario 103 para el 332E: la tabla del SRI dice 310 [9] y el DIMM lo asocia al campo 332 [8]. Fuera de
  D0 (Etapa 2, `casillero_103`).
- La norma que motiva el texto nuevo del 3440.
- Las filas reales de `CodigoRetencion` y las retenciones emitidas: la comparación es contra la migración 0004.
- Si D0-d se responde C: cómo se relaciona la fecha de pago o crédito en cuenta con el `periodoFiscal` del XML. Se revisa en
  la Fase B.

---

## 4. Qué es inferido

Ninguna fuente oficial dice expresamente con qué código se reporta cada escenario de la Res. 28. Hay dos lecturas, y **la
guía SRI de 2017 no respalda el 332E al 1 %**:

| Escenario | Lectura del catálogo (notación «1 /0» y «0 /1») | Lectura de la guía de 2017 y el RLRTI |
|---|---|---|
| Operadora → socio, transición (0 %) | 332E al 0 % | código «332» al 0 % (la guía no menciona el 332E) |
| Operadora → socio, art. 8 nuevo (1 %) | **332E al 1 %** | **310 al 1 %** |
| Cliente → socio, transición (1 %) | 310 al 1 % | 310 al 1 %, a nombre del socio (D0-h) |
| Cliente → operadora con unidades de socios, art. 8 (0 %) | 310 al 0 % | sin precedente: la guía no lo trata |
| Cliente → operadora con unidades propias (1 %) | 310 al 1 % | 310 al 1 % |

- **Guía SRI de julio de 2017**, §3.3, págs. 18-19 (régimen de la Res. 17-295, derogada): la operadora «realizará la
  retención del 0% de Impuesto a la Renta, al socio o accionista por la factura emitida a ella, por los ingresos mensuales
  obtenidos como punto de emisión de la operadora; de otro lado efectuará la retención del 1% por los servicios de transporte
  que el socio le preste […] y reportará tales valores dentro del Formulario 103 (códigos 332 y 310, respectivamente) y en el
  ATS (códigos 332 y 310, respectivamente)» [10]. Es decir: el 1 % de la operadora al socio iba con el **310**, no con el
  332E. Esa lectura del 1 % la refuerza el art. innumerado a continuación del 114 del RLRTI, transcrito en la Res. 24: la
  retención de la operadora a sus socios va «en los mismos porcentajes […] aplicables para el sector de transporte» [4].
- **A favor de la lectura del catálogo:** es el documento oficial más reciente y el SRI cambió el 332E de «0» a «0 /1»
  precisamente «según resolución NAC-DGERCGC26-00000028». El único 1 % entre operadora y socio en esa resolución es el del
  art. 8 nuevo. Pero no lo dice expresamente.
- **Secundarias:** Boletín Contable [16] pone el 332E al 0 % o al 1 % según de quién sea la unidad (no coincide con la
  Res. 28). NMS [13], Lexis [14], Kruger [15] y Primicias [17] resumen la resolución como el texto oficial, sin hablar de
  códigos.
- **Otras inferencias:**
  - el SRI prevé usos del art. 8 antes del 01/01/2027: el catálogo y el DIMM habilitan el 0 % del 310 desde el 01/08/2026,
    y en la transición ningún escenario del 310 va al 0 % (pesa en D0-c);
  - no hay retenciones del sistema anteriores a la Res. 28 (por la fecha del commit, sin consultar la base).

---

## 5. Qué se hace ahora y qué espera respuesta

### 5.1 Fase A — ahora, sin cambio fiscal (`espec-d0-fase-a.md`)

Los resultados de hoy (28/10/2026) quedan idénticos a los de `8d2eead`.

- **`CodigoRetencion`:** `vigente_desde` y `vigente_hasta` (NULL = inicio no documentado / fila abierta) y `ayuda`. Las filas
  existentes quedan con inicio NULL: no se inventan fechas. Restricciones válidas en SQLite y PostgreSQL: única por
  `(impuesto, codigo, vigente_desde)`, una sola fila abierta y una sola sin inicio por código, hasta ≥ desde. `clean()`
  rechaza solapes. `vigentes(fecha)` y `CodigoRetencion.vigente(impuesto, codigo, fecha)`.
- **`RetencionDetalle.codigo_catalogo`:** FK nullable (PROTECT), solo en detalles nuevos; los históricos quedan NULL.
- **Migraciones** `0014_codigoretencion_vigencias` (esquema) y `0015_vigencias_res_28` (datos), reversibles, con una guardia
  que aborta si el 310 o el 332E se editaron en la administración:
  - 310: la fila actual cierra el 2026-07-31 y queda fija (como el DIMM); fila nueva desde el 2026-08-01, 1,00 editable, que
    cita el bloque 01/08 del catálogo y la Res. 28 (RO 5.º S. 339);
  - 332E: igual, con 0,00 en las dos filas;
  - 3440: una sola fila; la fuente anota que el concepto es del bloque 06/08;
  - ayuda neutral: la Res. 28 admite 1 % o 0 % según quién paga a quién y con qué unidades, con transición hasta el
    31/12/2026; el porcentaje lo confirma el contador;
  - fecha de corte 2026-08-01 en una constante comentada (D0-a);
  - la vuelta deja `codigo_catalogo` en NULL y el estado exacto de 0004.
- **Selección por fecha:** `crear()` fija la fecha una vez y `calcular(…, fecha)` busca la fila vigente. **Provisionalmente
  esa fecha es la de emisión** (comportamiento actual), no la regla legal (§3.3): el parámetro queda listo para D0-d y no se
  añade todavía un campo de fecha de pago.
- **Pantalla:** el formulario lista `vigentes(fecha)` (cada código una vez) con su ayuda; «Emitir» compara una huella de lo
  revisado y, si cambió, vuelve a «Revisar» sin emitir.
- **Administración:** sin edición de porcentaje en la lista; porcentaje, concepto y desde, de solo lectura cuando la vigencia
  ya empezó; acción «Nueva vigencia» que cierra la fila abierta, crea la siguiente y la registra en AuditLog.
- **Pruebas:** regresión de los resultados de hoy; límites 31/07 y 01/08; restricciones; lo emitido intacto byte a byte;
  huella a medianoche del 31/12/2026; ida y vuelta de las migraciones en SQLite y PostgreSQL.
- **Documentos internos:** §7.

### 5.2 Fase B — después de las respuestas, desplegada antes del 31/12/2026

| Cambio | Depende de |
|---|---|
| Admitir solo 0 % o 1 % en el 310 y el 332E desde la Res. 28 | D0-e, D0-c |
| Filas desde el 01/01/2027: código y valor por defecto del pago operadora → socio; valor por defecto del 310 | D0-b, D0-f, D0-g |
| Campo «fecha de pago o crédito en cuenta» y elección del porcentaje por esa fecha | D0-d |
| Retención a nombre del socio durante la transición | D0-h |
| Fecha de inicio definitiva (la constante de la Fase A) | D0-a |
| Opcional: guardar en el detalle el escenario elegido (unidades propias, de socios, operadora → socio) | D0-b |

Prueba que cambia respecto de la síntesis: con D0-d = C, un crédito en cuenta del 30/12/2026 con retención emitida el
02/01/2027 aplica la fila de 2026.

Para tenerla en producción antes del 31/12/2026, las respuestas de D0-b a D0-f hacen falta **hacia el 15/12/2026**.

### 5.3 Lo emitido

Nada se corrige con UPDATE. Si alguna respuesta mostrara retenciones mal emitidas (por ejemplo, por D0-h), se anulan en SRI
en línea y se emite una nueva. Según `NORMA-RETENCIONES-2026-10.md` («Anulación») [R7], la anulación solo cabe hasta el día
7 del mes siguiente: **las de octubre, hasta el 07/11/2026**. Para medirlo, una consulta de solo lectura y autorizada:
detalles con 310 o 332E agrupados por empresa, mes y porcentaje.

---

## 6. Dudas para la propietaria y su contador

Bloquean la Fase B: **D0-b, D0-c, D0-d, D0-e y D0-f**, con respuesta hacia el **15/12/2026**. D0-a, D0-g y D0-h no bloquean
el catálogo.

**D0-a. ¿Qué día empieza la nueva vigencia en el sistema?** No bloqueante; sin plazo.
- A) 31/07/2026: la resolución dice regir desde su firma.
- B) 01/08/2026: como el Catálogo ATS y el DIMM, con los que se valida el ATS. **Recomendada.**
- C) 03/08/2026: publicación en el Registro Oficial (art. 11 del Código Tributario, inciso primero).
- D) 01/09/2026: primer día del mes siguiente a la publicación (art. 11, inciso segundo).
- *Recomendación:* B, para que lo que emite el sistema cuadre con el ATS, dejando documentado que la norma admite las otras
  tres. No cambia nada de lo emitido.

**D0-b. ¿Con qué código se reporta cada pago?** Bloqueante; 15/12/2026.
- (i) Pago de la operadora al socio al 1 % (art. 8 nuevo):
  - A) 332E al 1 % (y al 0 % en la transición). Se apoya solo en la notación «0 /1» del catálogo.
  - B) 310 al 1 %; el 332E queda solo para el 0 % de la transición. Se apoya en la guía SRI de 2017 (régimen derogado) y en
    el art. innumerado a continuación del 114 del RLRTI.
  - C) Otra (por ejemplo, la de Boletín Contable: 332E al 0 % o al 1 % según de quién sea la unidad). Indique cuál.
- (ii) Pago del cliente a la operadora cuando el servicio se presta con unidades de los socios (0 %):
  - A) 310 al 0 % (notación «1 /0» del catálogo). **Recomendada.**
  - B) Otro código. Indique cuál.
- *Recomendación:* en (i) no hay base para recomendar sin el contador: que elija A o B y, si duda, que se consulte al SRI
  antes del 15/12/2026. La señal oficial más reciente (el catálogo) apunta a A, pero no es expresa, y la guía de 2017 dice B.
  En (ii), A.

**D0-c. ¿A quién se aplica el art. 8 nuevo antes del 01/01/2027?** Bloqueante; 15/12/2026.
- A) Por socio: desde que rige la Res. 28, a los socios que ya actualizaron su RUC y facturan a la operadora (la transitoria
  segunda reformada les permite adelantarse) y a los servicios prestados con sus unidades; los socios de la misma operadora
  que siguen como puntos de emisión, en la transición hasta el 31/12/2026. **Recomendada.**
- B) Por operadora: solo si la operadora ya no factura por medio de ninguno de sus socios; si le queda uno como punto de
  emisión, toda la operadora sigue en la transición (es la letra de la quinta).
- C) A nadie: todas siguen en la transición hasta el 31/12/2026.
- *Recomendación:* A. Combina la quinta con la segunda reformada y es coherente con que el catálogo y el DIMM ya admitan el
  0 % del 310 desde agosto. En el sistema, A y B se programan igual (los dos porcentajes disponibles desde la vigencia y el
  usuario elige según el caso); C obligaría a bloquear hasta el 31/12/2026 el 0 % del 310 y el 1 % del pago operadora → socio.

**D0-d. ¿Cómo obtiene el sistema la fecha que decide el porcentaje?** Bloqueante; 15/12/2026.
La regla ya está: el pago o el crédito en cuenta, lo que ocurra primero (Res. 09, art. 8). Ejemplo: factura recibida y
registrada el 30/12/2026 y retención emitida el 02/01/2027: corresponde el porcentaje de 2026.
- A) La fecha de emisión de la retención, como hoy. Simple, pero en el ejemplo aplicaría el de 2027: contradice el art. 8 en
  cada cambio de tabla.
- B) La fecha de la factura del proveedor, que el sistema ya pide. Sin campo nuevo, pero falla con pagos anticipados o con
  créditos en cuenta posteriores a la factura.
- C) Un campo «fecha de pago o crédito en cuenta» en la retención: por defecto la de la factura del proveedor, editable,
  nunca futura; el porcentaje se elige por esa fecha. **Recomendada.**
- *Recomendación:* C. Hasta la respuesta, la Fase A usa provisionalmente A, que hoy da los mismos resultados.

**D0-e. ¿Limitamos el 310 y el 332E a 0 % o 1 % desde la Res. 28?** Bloqueante; 15/12/2026.
- A) Sí: un selector 0 % / 1 % con una ayuda que explique cada caso. **Recomendada.**
- B) No: rango libre de 0 a 100, solo con un aviso.
- *Recomendación:* A. La norma solo prevé 0 % y 1 %, y el rango libre deja pasar errores de digitación.

**D0-f. ¿Qué valor sale por defecto desde el 01/01/2027?** Bloqueante; 15/12/2026.
- A) 310 al 1 % con el 0 % elegible (la ayuda dice que el 0 % es solo para pagos a una operadora cuyo servicio se presta con
  unidades de sus socios). El pago operadora → socio, al 1 % con el código que diga D0-b: el 332E si D0-b = A; el 310 si
  D0-b = B, y entonces el 332E deja de tener uso desde 2027.
- B) 310 sin valor por defecto: el usuario elige 1 % o 0 % e indica si el servicio fue con unidades propias o de socios. El
  pago operadora → socio, igual que en A.
- C) Otra.
- *Recomendación:* A. El 310 lo usan también transportistas que no son operadoras, para los que rige el 1 % de la Res. 09;
  obligar a elegir en todos los casos añade un paso sin beneficio. El 1 % por defecto del 332E solo se programa si D0-b = A.

**D0-g. ¿El 332E sirve también para lo que una compañía de transporte paga a sus accionistas?** No bloqueante; con D0-b.
- A) Sí. **Recomendada.**
- B) No, solo cooperativas y sus socios.
- *Recomendación:* A. La notación del catálogo remite a la Res. 28, que trata igual a socios y accionistas; el concepto del
  código conserva el texto anterior. Si D0-b = B, solo afecta al 0 % de la transición.

**D0-h. En la transición, cuando el cliente retiene 1 % al socio, ¿a nombre de quién va la retención?** No bloquea el
catálogo, pero afecta a la pantalla; cuanto antes (el esquema termina el 31/12/2026 y las retenciones de octubre solo se
pueden anular hasta el 07/11/2026).
La factura la emite la operadora desde el punto de emisión del socio, con el RUC del socio en la información adicional.
- A) Del socio, y el sistema permite un sujeto retenido distinto del proveedor de la compra (cambio de pantalla).
- B) De la operadora, como hoy.
- C) Del socio, sin cambiar el sistema: hasta el 31/12/2026 esas retenciones se emiten en SRI en línea.
- *Recomendación:* que el contador confirme que va a nombre del socio (la quinta dice «en los pagos a los socios o
  accionistas» y la guía de 2017 lo indicaba así, con el RUC del socio en el ATS y el 310 al 1 %). Si lo confirma, C, porque
  el esquema dura hasta fin de año, salvo que haya clientes con muchas retenciones de este tipo (entonces A). Si ya se
  emitió alguna a nombre de la operadora, §5.3.

---

## 7. Correcciones a los documentos internos

- **Error real:** `NORMA-CONTABLE-TRIBUTARIA-2026-10.md`, l. 8, atribuye el cambio del 310 y el 332E al último bloque
  (06/08/2026); está desde el bloque del 01/08/2026 [R8].
- **Omisión:** `NORMA-RETENCIONES-2026-10.md`, l. 27, recoge el cambio del 310 pero no el del 332E [R7].
- **Son correctas y no se tocan:** `NORMA-CONTABLE-TRIBUTARIA` l. 51 (la tabla vigente es la del bloque 06/08, que ya
  incluye el cambio) y `PLAN-PROFORMAS-BANCOS-CONTABILIDAD.md` l. 80, 237 y 352 (hablan del archivo con fecha de
  actualización 06/08/2026, que trae el cambio).
- Reemplazos exactos: `registros-fase/D0-correcciones-documentos.md`.

---

## 8. Fuentes

Todas consultadas el **28/10/2026**. Los sha256 son de las descargas de ese día y coinciden en las de los dos verificadores.

**Oficiales**

1. Res. NAC-DGERCGC26-00000028, Registro Oficial, 5.º Suplemento Nº 339, 03/08/2026 (firmada el 31/07/2026), repositorio de
   la Corte Constitucional:
   https://esacc.corteconstitucional.gob.ec/storage/api/v1/10_DWL_FL/eyJjYXJwZXRhIjoicm8iLCJ1dWlkIjoiMWQ5YzljMWQtY2UyZC00Yzk0LWE3ZGEtNTA0MGZlZDA0NThkLnBkZiJ9
   — sha256 `3c4b90e2762fbf6cf05d2b365e317e08c43b7c5f7be9f9e4f652b1bc404beecf`
2. La misma, en la biblioteca del SRI:
   https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar?id=eb7af553-b944-4656-baca-76d5aa180fb0&nombre=NAC-DGERCGC26-00000028.pdf
   — sha256 `dfbd77caa3663719494840851f1573fa18d4f2f6eb33c5622d04b97a8b49706d`
3. Índice del Registro Oficial, 5.º Suplemento Nº 339 (lista la Res. 28): https://www.registroficial.gob.ec/quinto-suplemento-no-339/
   — página web, sin sha256.
4. Res. NAC-DGERCGC26-00000024, Registro Oficial, 4.º Suplemento Nº 324, 13/07/2026 (firmada el 10/07/2026; art. 8 original;
   transitorias; derogatoria de la Res. NAC-DGERCGC17-00000295, RO S. 3 del 30/05/2017; considerando que transcribe el art.
   innumerado a continuación del 114 del RLRTI):
   https://esacc.corteconstitucional.gob.ec/storage/api/v1/10_DWL_FL/eyJjYXJwZXRhIjoicm8iLCJ1dWlkIjoiYzg0MjAxYjEtNjYwNC00YjQyLThiY2UtNTNhMWU5YzllMDU2LnBkZiJ9
   — sha256 `7e980db2e20a367bcd87970b9d007c14c70b8961af0059bc2adf8337fecd9c1c`
5. Res. NAC-DGERCGC26-00000009 (firmada el 27/02/2026; aplicable desde el 01/03/2026; art. 2, num. 2 a; art. 8; transitoria
   única):
   https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/272ca6a9-d679-4b4e-8da0-fb4671cf5f8f/NAC-DGERCGC26-00000009_Ret_IR.pdf
   — sha256 `efff64e5b1937f75fb5cb7f95402c4ad5b913a87eb87d7d3a9e4cc5e29dec201`
6. Catálogo ATS del SRI, actualización 06/08/2026 (archivo guardado el 11/08/2026; 3.823.616 bytes), hoja «TABLAS
   RETENCIONES», tabla 3.10, filas 16 (310), 61 (332E) y 77 (3440):
   https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/e6a826af-b22c-40bb-8752-d711f293b8f9/Catalogo_ATS.xls
   — sha256 `bd3f7834f2cd31187af39cd2f4c685a646d7e49316e92ee493da5f2dd9776e3e`
7. SRI, «Formularios e instructivos» (Catálogo ATS con fecha 06/08/2026; Programa ATS V 1.19.0 del 23/09/2026 «para los
   periodos fiscales septiembre 2026 en adelante»): https://www.sri.gob.ec/formularios-e-instructivos1 — página web, sin sha256.
8. Programa DIMM ATS 1.19.0 (`bdd_dimm_anexos.script` del 04/09/2026 dentro de `ec.gob.sri.dimm.data_1.23.0.jar`; tablas
   `ADM_CONCEP_FORMULARIOS_ANEXOS` y `ADM_PORCENT_FORMUL_CAMP_CONCEP`):
   https://descargas.sri.gob.ec/download/anexos/ats/ats.plugin.1.19.0.zip
   — sha256 `a721f471556c0bd4a53bfdf84b45c927fb91e03ec023e23c5d512c9dcf37eb04`
9. Tabla de retenciones del SRI (`tabla_retenciones.xls`, grabada el 31/07/2026; todavía con la Res. 09):
   https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/a305ad8c-7cfd-42c7-8cea-be4dbf850d0c/tabla_retenciones.xls
   — sha256 `fecf21eb3ce9497f5f527612ea1b5d7a035c1adfdb93ddc3cf9a78db62774181`
10. Guía técnica del SRI para el cumplimiento de obligaciones tributarias del sector de transporte terrestre, julio de 2017,
    §3.3, págs. 18-19 (régimen de la Res. 17-295, derogado; solo para interpretar):
    https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/05d5d170-1c17-4787-ac43-c82b5deadc24/Gu%EDa+T%E9cnica+para+el+cumplimiento+de+obligaciones+tributarias+-+sector+transporte+terrestre.pdf
    — sha256 `2573473693e21a8a7e115815cccf9d4f53090fa8b91c293c3cc1771a77638527`
11. Registro Oficial, 3.er Suplemento Nº 593, 08/12/2021 (circular NAC-DGECCGC21-00000006, que transcribe el art. 11 del
    Código Tributario):
    https://esacc.corteconstitucional.gob.ec/storage/api/v1/10_DWL_FL/eyJjYXJwZXRhIjoicm8iLCJ1dWlkIjoiMTUyZmQwZGItMzdiMC00ODIxLTg3OGUtYzUzNzhiZGFkMTFiLnBkZiJ9
    — sha256 `88e399ad55b05aeb4f5430e1338e98246d7d403c1ea0d16539d024387f2d2d57`

**Secundarias**

12. Código Tributario, copia codificada publicada por EMOV EP (art. 11, reformado por la Ley s/n, RO 744-S, 29/04/2016;
    coincide con [11]): https://www.emov.gob.ec/wp-content/uploads/2022/09/C%C3%93DIGO%20TRIBUTARIO.pdf
    — sha256 `2c75ac8f2c5adf07ac77deb22f0040b48c345fba2d731b90e2688ff0d51b4571`
13. NMS Law, 03/08/2026: https://nmslaw.com.ec/blog/2026/08/03/sri-extiende-hasta-2027-facturacion-transporte-terrestre-comercial-ecuador/
14. Lexis, Registro Oficial del día, 03/08/2026: https://www.lexis.com.ec/noticias/registro-oficial-del-dia-sri-reforma-el-regimen-de-retenciones-para-el-transporte-comercial-1
15. Kruger Law, 01/09/2026: https://kruger.law/sri-reforma-las-retenciones-para-el-transporte-comercial/
16. Boletín Contable, 17/08/2026, actualizado el 11/09/2026 (su lectura del 332E no coincide con la Res. 28):
    https://boletincontable.com/2026/08/17/nueva-actualizacion-del-ats-2026/
17. Primicias, 01/08/2026 (enlaza el mismo PDF que [2]): https://www.primicias.ec/economia/sri-plazo-transporte-comercial-ruc-facturacion-diciembre-resolucion-129355/
18. JEZL Auditores, índice de resoluciones y circulares del SRI 2026 (hacia el 20/09/2026):
    https://www.jezl-auditores.com/tributario/117-resoluciones-y-circulares-sri-2026-2025

Las páginas web y las secundarias 13–18 no tienen sha256: su contenido cambia o no se guardó copia.

**Repositorio** (rama `plataforma`, commit `8d2eead`, solo lectura)

- R1: `core/comprobantes/migrations/0004_catalogo_retenciones.py` (310 en la l. 23, 332E en la l. 68, 3440 en la l. 84)
- R2: `core/comprobantes/models.py` (`CodigoRetencion` l. 24, `RetencionDetalle` l. 175)
- R3: `core/comprobantes/retenciones.py` (`calcular` l. 64, `crear` l. 127)
- R4: `core/comprobantes/xml_retencion.py` (`fechaEmision` y `periodoFiscal` desde `emission_date`, l. 29-55)
- R5: `core/comprobantes/forms.py`, `views.py`, `admin.py` y `static/js/retenciones.js`
- R6: `core/pos/emision.py` (`preparar` l. 105, reenvío l. 290)
- R7: `entregas/facturaporaqui/NORMA-RETENCIONES-2026-10.md`
- R8: `entregas/facturaporaqui/NORMA-CONTABLE-TRIBUTARIA-2026-10.md`

**Archivos de trabajo** (no van al repositorio): en la VM101, `/root/invoice15/registros-fase/d0-verif0-descargas`,
`d0-verif0-dimm` y `d0-verif1-descargas` (descargas y textos extraídos); en el hipervisor,
`/tmp/claude-0/-root/eb503cf0-ed0f-4f93-8cb9-2743cee5bc69/scratchpad/d0/` (temporal).
