# Precios con IVA incluido — contrato del servidor

Rama `fase/precios-con-iva` (sale de `fase/primera-entrega` e0d7c38, PR #1). Parte del servidor del pedido de la
propietaria del 16/11/2026. La fuente común con la pantalla es `/root/invoice15/precios-iva/contrato-comun.md` (en la VM).
Este documento no cambia ese contrato: lo precisa donde hizo falta y lo dice.

## 1. Qué cambia

- El precio que se escribe es el precio **con IVA**: en el catálogo, en la factura y en la proforma.
- El total con IVA de cada línea es exacto. La base y el IVA se derivan.
- El catálogo guarda `precio_con_iva`. `pvp` (sin IVA) se sigue llenando, derivado, para quien lo lee hoy.
- Cada línea tiene su **descripción** (por defecto, el nombre del producto). No cambia el catálogo.
- Las líneas quedan en el **orden en que llegan**. Ese orden va al XML, al RIDE, al ticket y al volver a abrir.
- La factura nueva sale en XML **1.1.0**, con precio unitario de hasta 6 decimales.
- La venta ya no pide **efectivo recibido** ni **cambio**. Se guardan en 0.
- Nada de lo ya emitido cambia (sección 7).

## 2. El cálculo de una línea (contrato común §1)

Entradas: `P` precio con IVA en centavos, `q` cantidad (entero 1–999 999), `d` descuento en % (entero 0–100), `t` tarifa
en % (15, 5, 0; exento y no objeto = 0).

    medio_arriba(a, b) = floor((2a + b) / (2b))
    bruto = P × q
    desc  = medio_arriba(bruto × d, 100)        descuento con IVA
    T     = bruto − desc                        total de la línea con IVA (lo que paga el cliente)
    base  = medio_arriba(T × 100, 100 + t)      precioTotalSinImpuesto y baseImponible
    iva   = T − base

Solo en el servidor (XML y RIDE):

    subtotal_sin_iva  = medio_arriba(bruto × 100, 100 + t)
    descuento_sin_iva = subtotal_sin_iva − base          (≥ 0; con d = 0 es 0)
    precioUnitario    = subtotal_sin_iva / q a 6 decimales, ajustado ±0,000001 si hace falta,
                        para que round_half_up(q × precioUnitario, 2) = subtotal_sin_iva

Código: `core/pos/precios_iva.py` (`calcular`, `precio_unitario`, `medio_arriba`). Todo con enteros.

Totales del comprobante: `importeTotal = Σ T`; por tarifa `baseImponible = Σ base` y `valor = Σ iva`;
`totalSinImpuestos = Σ base`; `totalDescuento = Σ descuento_sin_iva`. Nunca se recalcula el IVA como base × tarifa.

Dos descuentos distintos, los dos correctos:

- **Descuento con IVA** (`desc`): el que se escribe y ve la usuaria en la pantalla, en el ticket y en el PDF de la
  proforma. 1000,00 con 10 % → 100,00.
- **Descuento sin IVA** (`descuento_sin_iva`): el del XML (`descuento` de la línea y `totalDescuento`), el del RIDE y el
  de `Sale.total_dscto`. El mismo ejemplo → 86,96.

Dónde queda cada número en la línea guardada (`SaleDetail`, `CreditNoteDetail`, `ProformaDetalle`):

| Campo | Valor |
|---|---|
| `precio_con_iva` | P (nuevo; NULL en las líneas anteriores) |
| `precio_unitario` | precioUnitario sin IVA, 6 decimales (nuevo; NULL en las anteriores) |
| `descripcion` | la de la línea (nuevo; `''` en las anteriores) — ProformaDetalle ya la tenía |
| `price_with_vat` | P |
| `price` | precioUnitario a 2 decimales (se sigue llenando) |
| `subtotal` | subtotal_sin_iva |
| `total_dscto` | descuento_sin_iva |
| `total` | base |
| `total_iva` | iva |
| `iva`, `dscto`, `codigo_porcentaje` | como antes (fracciones y código de tarifa) |

T no se guarda aparte: es `total + total_iva`.

### Ejemplos reales (salidos de `tests/test_precios_con_iva.py`)

| P | q | d | t | T | base | IVA | subtotal sin IVA | desc. sin IVA | precioUnitario |
|---|---|---|---|---|---|---|---|---|---|
| 1000,00 | 1 | 0 | 15 | 1000,00 | 869,57 | 130,43 | 869,57 | 0,00 | 869.57 |
| 1000,00 | 1 | 10 | 15 | 900,00 | 782,61 | 117,39 | 869,57 | 86,96 | 869.57 |
| 1000,00 | 3 | 0 | 15 | 3000,00 | 2608,70 | 391,30 | 2608,70 | 0,00 | 869.566667 |
| 1000,00 | 1 | 0 | 0 | 1000,00 | 1000,00 | 0,00 | 1000,00 | 0,00 | 1000.00 |
| 1000,00 | 1 | 0 | 5 | 1000,00 | 952,38 | 47,62 | 952,38 | 0,00 | 952.38 |
| 0,01 | 1 | 0 | 15 | 0,01 | 0,01 | 0,00 | 0,01 | 0,00 | 0.01 |
| 999 999,99 | 9 | 0 | 15 | 8 999 999,91 | 7 826 086,88 | 1 173 913,03 | 7 826 086,88 | 0,00 | 869565.208889 |
| 10,06 | 2 | 10 | 15 | 18,11 | 15,75 | 2,36 | 17,50 | 1,75 | 8.75 |

- 10 líneas de 1000,00 al 15 %: total 10 000,00; base 8695,70; IVA 1304,30 (la suma de las líneas).
- En todos los casos: `cantidad × precioUnitario − descuento = precioTotalSinImpuesto` al centavo (lo comprueban las pruebas).
- Cruce con la pantalla: el cálculo del servidor da lo mismo al centavo que `prueba_calculo.cjs` en sus 20 011 líneas
  (`precios-iva/registros/servidor-cruce-calculo-pantalla-*.log`).

### Caso documentado: más de 10 000 unidades

Con `q ≤ 10 000` siempre existe un precioUnitario de 6 decimales exacto (probado con 4000 líneas al azar y demostrable:
el intervalo válido mide 10 000 millonésimas). Con más unidades puede no existir. Entonces el servidor toma el más cercano a
`subtotal_sin_iva / q` y lo marca (`LineaConIva.exacto = False`).

Ejemplo de la prueba: 999 999 × 9,99 con IVA 15 %. Subtotal sin IVA 8 686 947,83. precioUnitario 8.686957 da
8 686 948,31 (0,48 de diferencia en `cantidad × precioUnitario`). La base, el IVA y el total del comprobante son exactos;
solo esa multiplicación de control no cuadra.

**Ojo**: no es tan raro como dice el contrato común. Con 10 001–999 999 unidades y precios bajos falla en la mayoría de
los casos (en 20 000 líneas al azar con precio ≤ 20,00: 94 %). No sabemos si el SRI tolera esa diferencia. Decisión pendiente
(sección 9).

## 3. Lo que el servidor manda a la pantalla

Producto (`Product.toJSON()`: búsqueda, por código, alta rápida, proformas, «Usar como base»), además de lo de siempre:

| Clave | Tipo | Valor |
|---|---|---|
| `precio_con_iva` | texto `"1000.00"` | precio con IVA con que sale hoy: el de la promoción vigente o el del catálogo |
| `precio_con_iva_catalogo` | texto | el del catálogo con IVA, sin promoción (precisión nueva: útil para el formulario y el listado de productos) |
| `descripcion` | texto | la de una línea nueva: el nombre del producto |
| `price_current`, `pvp` | número | siguen, SIN IVA; la pantalla ya no calcula con ellos |

Línea guardada (`SaleDetail.toJSON()` en `search_detail_products`, las líneas de la nota de crédito, `_linea_json` de la
proforma), en el orden guardado:

| Clave | Valor |
|---|---|
| `precio_con_iva` | texto; en líneas anteriores, el `price_with_vat` que calcularon |
| `descripcion` | texto; en líneas anteriores, el nombre del producto |
| `total_con_iva` | texto, T = total + total_iva |
| `precio_unitario` | texto, sin IVA, como en el XML (mínimo 2 decimales, hasta 6) |
| `con_iva_incluido` | booleano: `false` en las líneas anteriores al cambio |
| `cant`, `dscto` (porcentaje), `codigo_porcentaje`, `tarifa` | como antes |

Precarga de la venta desde una proforma o su factura en borrador (`proforma_precarga.lineas`): `precio_con_iva` (texto) y
`descripcion` de la línea de la proforma o del borrador, en su orden. Se quitó el aviso «La factura usa el nombre de cada
producto…»: ahora la factura lleva la descripción de la proforma.

Proforma (`_linea_json`): además `producto.precio_con_iva`. `price` (sin IVA) sigue por compatibilidad.

## 4. Lo que la pantalla manda al servidor

Venta, acciones `add` y `guardar_borrador`: `products` es una lista JSON en el orden en que se ven las filas.

    {"id": 12, "cant": 2, "precio_con_iva": "1000.00", "dscto": 0, "descripcion": "Servicio de diseño",
     "codigo_porcentaje": "4"}          ← codigo_porcentaje solo en la factura en borrador de una proforma

- `precio_con_iva`: texto o número con punto decimal y hasta 2 decimales, de 0 a 999999.99. **Con punto**: «1000,5» no
  se acepta (la pantalla normaliza la coma antes de enviar).
- `descripcion`: opcional. Sin ella o vacía, el nombre del producto.
- `cash` y `change` ya no se envían. Si llegan, se ignoran.

Proformas (crear y editar, campo `lineas`): se mantienen sus claves de siempre y cambia el precio:

    {"product": 12, "cant": 2, "precio_con_iva": "1000.00", "dscto": 0, "descripcion": ""}

(`id` también vale en lugar de `product`.) Precisión del contrato: en proformas la lista sigue llamándose `lineas` y el
producto `product`, como hoy. El error de línea del precio viene con `campo: "precio_con_iva"` (antes `"price"`; la
pantalla ya pinta los dos en la casilla del precio).

Formulario del producto (`/pos/product/add/` y `/pos/product/update/<id>/`, también el alta rápida desde la factura):
campo **`precio_con_iva`** (obligatorio, etiqueta «Precio de venta (con IVA)»). Ya no hay campo `pvp` en el formulario.

## 5. Errores

| Situación | Texto |
|---|---|
| Venta sin `precio_con_iva` (página anterior) | La pantalla de venta cambió: recarga la página y vuelve a intentarlo. |
| Proforma sin `precio_con_iva` (HTTP 409) | La pantalla de la proforma cambió: recarga la página y vuelve a intentarlo. |
| Precio fuera de rango o con más de 2 decimales | Línea n (nombre): El precio va de 0 a 999999,99, con hasta 2 decimales. |
| Descripción de más de 300 caracteres | Línea n (nombre): La descripción admite hasta 300 caracteres. |
| Descripción con saltos de línea, tabuladores u otros controles | Línea n (nombre): La descripción no admite saltos de línea, tabuladores ni otros caracteres de control. |
| Descripción que no es texto | Línea n (nombre): La descripción debe ser un texto. |
| Precio con IVA distinto del catálogo sin `change_product` | El precio de {nombre} no coincide con el del catálogo ({catálogo con IVA}) y tu perfil no puede cambiarlo: quita la línea y vuelve a agregarla, o factura desde una proforma. |
| Línea cuyo bruto supera 9 999 999,99 | Línea n (nombre): El importe de la línea supera USD 9.999.999,99: revisa la cantidad y el precio. |
| Total de la factura que supera 9 999 999,99 | El total de la factura supera USD 9.999.999,99. |

En proformas los errores de línea van, como siempre, en `campos.lineas = [{indice, campo, texto}]` con `campo`
`precio_con_iva` o `descripcion`. Los demás textos (cantidad, descuento, repetido, stock, tarifa) no cambian.

Caracteres de control: categorías Unicode Cc (incluye \t, \n, \r), Cs, Zl y Zp, y U+FFFE/U+FFFF. Los espacios sobrantes
(incluido el de no separación) se juntan en uno y se quitan los de los extremos.

El permiso del precio compara el precio con IVA con el del catálogo con IVA (con promoción, si la hay). Desde una proforma
vale además su precio con IVA (en sus líneas anteriores, el que calculó o el de su precio sin IVA con la tarifa actual).
La descripción la cambia quien puede vender.

## 6. XML, RIDE, ticket y PDF de la proforma

Factura con líneas nuevas: `<factura version="1.1.0">`. En cada `<detalle>`:

- `descripcion`: la de la línea.
- `cantidad`: con 2 decimales (`3.00`; es entera).
- `precioUnitario`: sin IVA, **mínimo 2 decimales y hasta 6, sin ceros de más** (`869.57`, `869.566667`, `1000.00`).
  Justificación: en la ficha técnica 1.1.0 `precioUnitario` y `cantidad` son `xsd:decimal` con `fractionDigits 6` y
  `totalDigits 18`: valen de 0 a 6 decimales. Con 2 como mínimo los precios exactos se leen como antes; los 6 solo
  aparecen cuando hacen falta para cuadrar. El RIDE escribe el mismo número (con coma).
- `descuento`: descuento sin IVA. `precioTotalSinImpuesto` y `baseImponible`: base. `valor`: iva.
- `totalSinImpuestos`, `totalConImpuestos`, `importeTotal` y `pagos/total` como en la sección 2. `importeTotal = pagos`.

La validación de las pruebas usa el XSD 1.0.0 del repositorio con `cantidad` y `precioUnitario` de la 1.1.0
(`tests/ayudas_precios.py`). El XSD oficial 1.1.0 de la factura no está en el repositorio: conviene agregarlo.

Nota de crédito (ya era 1.1.0): sus líneas copian `precio_con_iva` y `descripcion` de la línea de la factura y usan el
mismo cálculo con la cantidad devuelta. Una devolución total da los mismos importes que la factura. Valida contra el XSD
oficial `NotaCredito_V1.1.0.xsd`.

RIDE (factura y nota de crédito): en las líneas nuevas, la descripción de la línea y el precio unitario con los
decimales del XML. `core/comprobantes/fidelidad.py` compara el precio unitario con esos decimales (`869,566667`): el RIDE
regenerado sigue siendo fiel (`manage.py regenerar_ride`).

Ticket: en las líneas nuevas, la descripción, «Cant. × p. unit. con IVA» con P y el importe T; el descuento con IVA
solo si lo hay. El pie (subtotales sin IVA por tarifa, descuentos, IVA y total) no cambia. Sin «Efectivo» ni «Cambio»
cuando valen 0 (muestra «Pago: Efectivo» si el medio es efectivo); las ventas anteriores con valores los conservan.

PDF y ficha de la proforma (`templates/proformas/pdf.html` y `detalle.html`): la descripción de cada línea y, si todas
sus líneas tienen precio con IVA, las columnas «P. unit. con IVA», «Descuento» (con IVA) y «Total con IVA». Las proformas
anteriores, como siempre.

Listado de ventas (modal de detalle, `search_detail_products`): el servidor ya manda `descripcion`, `precio_con_iva` y
`total_con_iva` de cada línea; el JS del modal (`core/pos/static/sale/admin/js/list.js`) todavía muestra nombre y
precio/total sin IVA: se ajusta al unir las ramas.

Guía de remisión: la descripción de la línea de la factura. Excel del catálogo: columna 11 «Precio de venta (con IVA)» al
exportar; al importar, si esa columna cambia, manda; si no, manda la 6 (sin IVA), como en los archivos de antes.

## 7. Qué NO cambia en lo ya emitido

- Una línea sin `precio_con_iva` (todas las guardadas antes) se calcula con `calcular_linea_iva` de siempre.
- Su factura genera el mismo XML 1.0.0 byte a byte si se vuelve a firmar (prueba con una copia literal del código de
  e0d7c38). La nota de crédito sobre ella, los mismos `<detalle>`.
- Su RIDE y su ticket dan el mismo HTML que la plantilla anterior (prueba que reduce cada condición nueva a su rama
  anterior y compara; y el hash de la plantilla de producción sigue igual con esa reducción).
- Ningún XML firmado, RIDE guardado, total ni estado se recalcula. `cash` y `change` guardados no se tocan.

## 8. Catálogo, tarifa y promociones

- `Product.save()`: quien escribe el precio con IVA manda y `pvp = medio_arriba(P × 100, 100 + t)`.
- Cambiar la tarifa conserva el precio con IVA (cambia `pvp`).
- Quien escribe solo `pvp` (versión anterior durante la publicación, Excel, facturero, SQL) manda: el precio con IVA se
  deriva de `pvp`.
- Lectura (`precio_con_iva_catalogo()`): si el `pvp` guardado no sale del precio con IVA guardado (fila escrita por la
  versión anterior), vale el derivado de `pvp`. Nunca se cobra un precio con IVA viejo.
- Promoción: guarda su precio final sin IVA (sobre `pvp`). Con IVA = `medio_arriba(precio final × (100 + t), 100)`: lo que
  cobraba la factura antes. La pantalla de promociones no cambió (sigue en sin IVA).

## 9. Migraciones y convivencia

| Migración | Qué hace | Tablas |
|---|---|---|
| `pos 0036_precios_con_iva` | ADD COLUMN: `pos_product.precio_con_iva` (NULL); `pos_saledetail` y `pos_creditnotedetail`: `precio_con_iva`, `precio_unitario` (NULL) y `descripcion` (DEFAULT '' en la base) | pos_product, pos_saledetail, pos_creditnotedetail |
| `pos 0037_precio_con_iva_del_catalogo` | Llena `precio_con_iva` de los productos con NULL: `pvp × (1 + t)` mitad hacia arriba (no cambia pvp: la vuelta es exacta) | pos_product (UPDATE por lotes de 500) |
| `proformas 0005_precios_con_iva` | ADD COLUMN `precio_con_iva` y `precio_unitario` (NULL) | proformas_proformadetalle |

- Todas solo agregan. En PostgreSQL ADD COLUMN NULL o con DEFAULT constante no reescribe la tabla.
- 0036 y 0005 fijan `lock_timeout = 5s` en su transacción: si otra transacción retiene la tabla más de 5 s, la migración
  falla sin cambiar nada y el despliegue se detiene con la versión anterior en servicio.
- 0037 necesita `app.platform=on` (lo pone `desplegar.sh`); sin él no actualiza nada y el código deriva igual el precio.
- Bloqueo medido en PostgreSQL: ver la tabla de mediciones abajo y
  `precios-iva/registros/servidor-pg-medicion-bloqueos-*.log`.

Mediciones en PostgreSQL 16 (base de pruebas con RLS forzada; 5001 productos, 60 001 líneas de venta, 20 000 de nota de
crédito y 20 000 de proforma; VM101 con carga ≈ 8; `servidor-pg-medicion-bloqueos-20261117-0522.log`):

| Migración | Bloqueo que toma | Cuánto lo retiene |
|---|---|---|
| pos 0036 (7 ADD COLUMN) | AccessExclusiveLock en pos_product, pos_saledetail y pos_creditnotedetail | 3,3–4,0 ms (las sentencias, 3 pasadas); `manage.py migrate` entero: 1,7–2,4 s (grafo y post_migrate, sin bloqueo de esas tablas) |
| proformas 0005 (2 ADD COLUMN) | AccessExclusiveLock en proformas_proformadetalle | 43 ms |
| pos 0037 (UPDATE de 5001 productos) | RowExclusiveLock (y AccessShareLock) en pos_product: no bloquea la tabla; sí las filas que actualiza | 2,1 s hasta el COMMIT (una venta que baje el stock de un producto en ese rato espera hasta que termine) |

Con otra transacción que lee pos_saledetail durante 1 s, pos 0036 espera y se aplica (2,1 s en total). Durante 8 s: falla
por `lock_timeout` a los ≈ 6 s y la columna no queda creada (nada cambió). Mientras espera retiene las tablas que ya
alteró (hasta 5 s). Recomendación: publicar fuera de horas de venta.

Convivencia durante la publicación (migrar → reiniciar):

- La versión publicada (e0f2902) y la del PR #1 (e0d7c38) siguen funcionando con el esquema nuevo: sus INSERT no nombran
  las columnas nuevas (quedan NULL o '') y sus lecturas no las ven (prueba `TestConvivencia`).
- Lo que esas versiones escriban en ese rato se lee como «anterior»: líneas con el cálculo de siempre y productos con el
  precio derivado de su `pvp`.
- Volver a la versión anterior después de publicar (`desplegar.sh --revertir`, sin migrar hacia atrás) funciona. Las
  facturas emitidas con precios con IVA conservan su XML firmado y su RIDE. Si la versión anterior las volviera a firmar
  (reenvío de una devuelta), generaría un XML 1.0.0 con el precio a 2 decimales: no reenviar esas facturas con la versión
  anterior.
- Vuelta de las migraciones: `migrate pos 0035_sale_ride_diseno` y `migrate proformas 0004_borrador_factura`. Probada
  (ida, vuelta, ida) en `TestMigracion.test_ida_y_vuelta` y en `test_migracion_vuelta_fase.py`.

## 10. Decisiones y avisos para la propietaria

1. **Más de 10 000 unidades en una línea**: el precio unitario de 6 decimales a veces no cuadra (sección 2). Opciones:
   dejarlo así (contrato), rechazar la línea y pedir que se divida, o absorber la diferencia en el descuento.
2. **Cambiar la tarifa de una línea en la factura en borrador** (el caso real de los tres conceptos al 0 %): ahora se
   conserva el precio con IVA que envía la pantalla. Antes bajaba el total (se quitaba el IVA); ahora el total no cambia y
   la base sube. Ejemplo de la prueba: 425,05 → 425,05 al 0 % (antes 369,60). Si la propietaria quiere que al pasar a 0 %
   baje el precio, lo decide la pantalla (enviar otro `precio_con_iva`).
3. **Promociones**: siguen calculándose sobre el precio sin IVA; la venta las muestra con IVA.

## Para la revisión de Codex

Archivos del servidor tocados (rama `fase/precios-con-iva`):

- `core/pos/precios_iva.py` (nuevo): cálculo §1, precio unitario de 6 decimales, texto del XML, descripción.
- `core/pos/models.py`: `Product.precio_con_iva` y su sincronización con `pvp`, precios con IVA de catálogo y promoción,
  `toJSON`; campos nuevos de `SaleDetail` y `CreditNoteDetail`; `calcular_linea_con_iva`, `calcular_linea`,
  `xml_cantidades_de_linea`, `json_de_linea`; `Sale.generate_xml` (1.1.0), `CreditNote.generate_xml`, `calculate_detail`.
- `core/pos/migrations/0036_precios_con_iva.py`, `0037_precio_con_iva_del_catalogo.py`,
  `core/proformas/migrations/0005_precios_con_iva.py` (nuevos).
- `core/pos/lineas_venta.py`: formato nuevo, formato viejo rechazado, descripción, permiso con IVA, importes máximos.
- `core/pos/views/sale/views.py`: líneas con precio con IVA y descripción; sin efectivo ni cambio.
- `core/pos/forms.py`: `ProductForm` pide `precio_con_iva`; `SaleForm` sin `cash` ni `change`.
- `core/pos/notas_credito.py`: la línea de la nota copia precio con IVA y descripción.
- `core/proformas/models.py`, `core/proformas/servicios.py`, `core/proformas/views.py`: validación, cálculo, duplicar,
  precarga, borrador, conversión, JSON y contexto del PDF y de la ficha.
- `core/pos/templates/sale/format/invoice.html`, `ticket.html`, `core/pos/templates/credit_note/format/invoice.html`,
  `templates/proformas/pdf.html`: formatos de impresión; `templates/proformas/detalle.html` (ficha de la proforma, a
  pedido de la coordinación: la rama de pantalla no la toca).
- `core/comprobantes/fidelidad.py`, `core/comprobantes/guias.py`, `core/pos/views/product/views.py` (Excel).
- Pruebas: `tests/test_precios_con_iva.py` y `tests/ayudas_precios.py` (nuevas); ajustadas al formato nuevo:
  `ayudas_proformas.py`, `test_alta_producto_en_factura.py`, `test_diseno_factura.py`, `test_emision_sri.py`,
  `test_factura_base.py`, `test_factura_lineas.py`, `test_iva_tarifas.py`, `test_multiempresa.py`, `test_proformas.py`,
  `test_proformas_borrador.py`, `test_proformas_conversion.py`, `test_respaldo_cobros.py`, `test_suscripciones.py`.

No se tocaron plantillas, CSS ni JS de las pantallas de venta, productos ni proformas (rama de pantalla).
