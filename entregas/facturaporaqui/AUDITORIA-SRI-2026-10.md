# Auditoría de facturación electrónica SRI — octubre de 2026

Revisión de cada componente frente a la normativa vigente, tras el primer intento de factura real (empresa 6, en Producción), que falló en la firma.

## Fuentes (consultadas el 11/10/2026)
- **Ficha técnica de comprobantes electrónicos, esquema offline, v2.34** (27/07/2026), en sri.gob.ec → Facturación electrónica. Hay un texto extraído en el espacio de trabajo de Claude.
- **XSD oficiales** de factura 1.0.0/1.1.0 y de nota de crédito 1.1.0.
- **Res. NAC-DGERCGC25-00000014** (RO 70, 30/06/2025) y **NAC-DGERCGC25-00000017** (29/07/2025). Desde el 01/01/2026:
  - el comprobante se transmite al emitirlo;
  - la anulación en línea se hace hasta el día 7 del mes siguiente;
  - no hay notas de crédito sobre facturas a consumidor final.
- **Res. NAC-DGERCGC26-00000027** (RO 335, 28/07/2026): el campo adicional **«RUC Proveedor»** (Anexo 26 de la ficha) es obligatorio 60 días después de su publicación.
- **Decreto 586** (2022): una factura de más de USD 50 debe identificar al comprador (§9.10 de la ficha).
- **Res. NAC-DGERCGC18-00000233**, art. 6: el comprobante solo se considera entregado si el comprador recibe el XML **y** el RIDE.

## Validación contra el SRI (ambiente de PRUEBAS, sin validez tributaria)
Se usó la firma de la empresa 6, con autorización de la propietaria.

| Prueba | Resultado |
|---|---|
| Factura mínima firmada con la firma nativa | RECIBIDA → **AUTORIZADO** |
| Código publicado `e3a2932`, factura completa (generate_xml + firma + dos fases) | **AUTORIZADO**; XML autorizado y RIDE generados |
| Nota de crédito sobre esa factura (comprador con pasaporte ficticio) | **AUTORIZADO**; la factura queda «Anulado» |
| Nota de crédito sobre una factura a consumidor final | NO AUTORIZADO, error 69 «No se puede emitir… Nota de Crédito para CONSUMIDOR FINAL», que confirma la regla de 2026 |

Todas las pruebas de punta a punta corrieron dentro de una transacción que se deshizo: no quedó nada en la base y se borraron los archivos temporales.

## Estado por hallazgo

### Hecho y publicado (`fd656a1` + `e3a2932`, desplegado el 12/10/2026 a las 02:28 UTC)

| Área | Hallazgo | Corrección |
|---|---|---|
| Firma | El jar Java exigía 18 bibliotecas (MITyC 1.1.7, BouncyCastle, xmlsec) que nunca estuvieron en el repositorio: toda emisión fallaba | XAdES-BES nativa en Python (`core/pos/utilities/firma.py`), verificada además con signxml y por el SRI. La clave no pasa por la línea de órdenes |
| Flujo | La conversación con el SRI ocurría dentro de la transacción de la venta: si la autorización tardaba ~2 s, la venta se borraba aunque el SRI ya la tuviera (número reutilizado → error 45, comprobante huérfano en el SRI) | Dos fases (`core/pos/emision.py`): se guarda firmado antes de enviar y nunca se deshace después. Estado «En proceso en el SRI», consulta por la misma clave (botón y temporizador `facturaporaqui-sri@`) |
| Flujo | Cada reintento generaba otra clave de acceso | La fecha y la clave se fijan una vez; se reenvía el mismo XML; 43 y 70 = ya recibido |
| Flujo | Todo estado distinto de «NO AUTORIZADO» se tomaba como autorizado | Solo cuenta AUTORIZADO. El 45 queda para revisión. Devuelta y no autorizada se reenvían con la misma clave |
| Flujo | Sin tiempos de espera; se bloqueaban la numeración y el cupo durante la llamada | Esperas de 10–20 s. Solo se bloquea la fila del comprobante |
| Flujo | El ambiente y la URL se tomaban de la empresa, no del comprobante | Se toman del comprobante |
| Flujo | `create_voucher_errors` podía reinsertar una «venta fantasma» | Ahora solo registra |
| Archivos | El .p12 y los adjuntos se buscaban en `BASE_DIR/media`, pero viven en `FPA_ARCHIVOS` | Se abren por su almacenamiento |
| XML | Faltaba «RUC Proveedor» (obligatorio desde fines de septiembre de 2026) | `FPA_RUC_PROVEEDOR` en el XML y en el RIDE. **Sin él no se emite en Producción** |
| XML | Campo adicional vacío (cliente sin correo) → error 35. Sin tope de 15 campos | Se omiten los vacíos y se limita a 15 |
| XML | La nota de crédito declaraba «RISE», régimen que ya no existe | Etiqueta eliminada |
| XML | `.replace("'", '"')` alteraba nombres con apóstrofo y rompía atributos | Solo la declaración lleva comillas dobles |
| Correo | Nunca se enviaba (ruta errónea); usaba `multipart/alternative`; se marcaba «enviada» sin enviar | XML y RIDE adjuntos, tiempo de espera, SMTP de la empresa o de la plataforma con responder-a; «enviada» solo si se envió |
| Venta | Factura «no electrónica» con número de la serie electrónica; fecha editable | Toda factura y nota es electrónica; la fecha de emisión es la de hoy (en el servidor) |
| Venta | Se podían borrar comprobantes autorizados | No se borra nada desde «En proceso»; se indica anular en SRI en línea o con nota de crédito |
| Venta | El tope de USD 50 a consumidor final no se aplicaba (el JS comparaba con `'1'`) | Validación en el servidor y JS corregido; se permite 50,00 exacto |
| Venta | Ticket 08 sin validez y con desglose de IVA | No disponible en Producción (decisión de la propietaria) |
| Compradores | `username = cédula` es único en toda la plataforma: el 9999999999999 de las demos impedía crear el consumidor final de otra empresa | Consumidor final propio por empresa; si la cédula ya está tomada en otra empresa, se crea un usuario aparte |
| Compradores | Sin validación de la identificación en el servidor | Se valida por tipo (05 cédula, 04 RUC, 06/08 alfanumérico, 07 solo 9999999999999) |
| NC | NC total con solo permiso de consulta; precios y cantidades del navegador; sin límites; dobles clics → NC duplicadas; IVA actual en vez del de la factura | Servicio `core/pos/notas_credito.py`: factura autorizada, mismo ambiente, no a consumidor final, ≤ vendido − acreditado, precio, descuento y tarifa de la factura, motivo obligatorio, permiso `add_credit_note`, factura bloqueada mientras se crea |
| NC | Una NC parcial marcaba la factura como «Anulado» | «Anulado» solo cuando las NC autorizadas cubren el total |
| NC | Borrar una NC sumaba stock en vez de restarlo | Corregido |
| Cupo | Se liberaba si la autorización tardaba | Se verifica antes de guardar, se reserva al enviar, se mantiene «en proceso» y se consume al autorizar |
| Pagos | Faltaba la forma de pago 19 (tarjeta de crédito) | Añadida |

### Etapa B — después de que la primera factura real salga bien
- **RIDE completo:**
  - razón social, dirección del establecimiento, ambiente y tipo de emisión;
  - leyendas RIMPE y agente de retención solo cuando correspondan;
  - «Contribuyente especial» solo si lo es;
  - subtotales por tarifa;
  - fechas de la NC corregidas (hoy están intercambiadas);
  - «Subtotal sin impuestos» después del descuento.
- **Régimen de cada empresa:** RIMPE, agente de retención con resolución y contribuyente especial, en el XML (`contribuyenteRimpe`, `agenteRetencion`, `contribuyenteEspecial`). Se puede rellenar desde el catastro público del SRI.
  - La empresa 6 no lo necesita: régimen GENERAL, no es agente de retención ni contribuyente especial.
- **Tarifas de IVA por producto:** 15 %, 5 %, 0 %, no objeto y exento, con subtotales separados en el XML. Hoy solo existe «con o sin IVA», y lo «sin IVA» sale siempre como 0 %.
- **Redondeo con Decimal HALF_UP e IVA por grupo:** hoy el IVA calculado por línea puede cobrar centavos de más.
- **NC parciales con estado propio.** Distinguir devolución (vuelve al stock) de descuento.
- **Portal del comprador:** su clave es su cédula. Pasar a un enlace de activación y revisar la protección de datos (LOPDP).
- **Edición del perfil del cliente:** borra la cédula, porque se usan campos deshabilitados en el HTML.
- **Validación de cédula en el JS:** acepta solo las provincias 1–22 (faltan la 24 y la 30) y no admite pasaporte.

### Etapa C — operación
- Cola o worker de envíos con reintentos hasta 24 h; el temporizador actual consulta cada 5 minutos.
- Conservación de comprobantes por 7 años con respaldo diario de la base y de `archivos/`.
- Estado «Anulado en SRI» para registrar las anulaciones hechas en línea.
- Cifrar en la base las claves de la firma y del SMTP.

## Decisiones pendientes del negocio
1. **RUC del proveedor (bloqueante para Producción).** Hay que poner el RUC de Suprohosting en `FPA_RUC_PROVEEDOR` y confirmar con el contador que Suprohosting está registrado como proveedor de sistemas de facturación electrónica en su RUC (actividad J62021002 o J62021003, Res. NAC-DGERCGC26-00000027).
2. Para cada empresa cliente: régimen RIMPE, resolución de agente de retención y si es contribuyente especial.
3. Si se venden productos al 5 %, exentos o no objeto de IVA.
4. Si hacen falta cantidades o precios con más de 2 decimales, lo que implica pasar a la factura 1.1.0.
5. NC parciales y por descuento. Quién anula en SRI en línea y cómo se refleja en el sistema.
6. Si el correo al comprador sale por el SMTP de cada empresa o por el de la plataforma.
   - Hoy se usa el de la empresa si está configurado; si no, el de la plataforma con responder-a de la empresa.
   - Para el dominio de la plataforma faltan SPF y DMARC.
7. Si se mantiene el portal del comprador y cómo obtiene su acceso.
