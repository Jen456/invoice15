# Norma de retenciones (SRI) usada por FacturaPorAquí — corte 14/10/2026

Base del comprobante de retención 07 (XML 2.0.0) y del catálogo `comprobantes.CodigoRetencion` (migración `0004_catalogo_retenciones`).
Cuando el SRI cambie porcentajes o códigos, la plataforma los actualiza en su administración y anota la resolución en «Fuente».

## Lo esencial

1. **Tabla de renta vigente desde el 01/03/2026:**
   - Norma: Res. NAC-DGERCGC26-00000009, que deroga la NAC-DGERCGC24-00000008.
   - Desaparece el 2,75 %, aparece el 5 % y queda un 3 % residual para pagos sin porcentaje específico (art. 3).
2. **El XML lleva el código del anexo,** no el casillero del formulario 103: `312A`, no `3120`. Va en `<codigoRetencion>`, de 1 a 5 caracteres.
3. **Ya no existen** los códigos 344 (2 %), 345 (8 %), 341 ni 342.
4. **Agentes de retención:**
   - Solo son agentes los contribuyentes especiales y los calificados por el SRI (LRTI art. 45; RLRTI art. 92 num. 1; catastro actualizado con la Res. NAC-DGERCGC25-00000010).
   - Los demás retienen solo en casos puntuales: liquidaciones de compra, pagos al exterior y otros (RLRTI art. 92 num. 2).
   - El RIMPE no es agente (LRTI art. 97.7).

## Renta — códigos de uso común (Catálogo ATS 06/08/2026, tabla 3.10)

| Código | Concepto | % vigente | % hasta 28/02/2026 |
|---|---|---|---|
| 303 | Honorarios profesionales relacionados con el título | 10 | 10 |
| 303A | Servicios profesionales de sociedades residentes | 5 | 3 |
| 304 / 304A | Servicios donde predomina el intelecto / comisiones | 10 | 10 |
| 307 | Servicios donde predomina la mano de obra | 3 | 2 |
| 309 | Medios de comunicación y agencias de publicidad | 3 | 2,75 |
| 310 | Transporte privado de pasajeros o carga | 1; desde 01/08/2026, 1 o 0 según la Res. 26-00000028 (el 332E, de la operadora a sus socios, pasa de 0 a 0 o 1; decisión D0) | 1 |
| 311 | Liquidación de compra (nivel cultural o rusticidad) | 3 | 2 |
| 312 | Transferencia de bienes muebles de naturaleza corporal | 2 | 1,75 |
| 312A | Compras al productor (agrícola, bioacuático, forestal) | 1 | 1 |
| 319 | Arrendamiento mercantil | 2 | 2 |
| 320 | Arrendamiento de bienes inmuebles | 10 | 10 |
| 322 | Seguros y reaseguros | 2 | 1 |
| 332 | Compras no sujetas a retención (incluye RIMPE Negocio Popular) | 0 | 0 |
| 343 | Otras al 1 % (incluye RIMPE Emprendedor) | 1 | 1 |
| 343A | Energía eléctrica | 2 | 1 |
| 343B | Construcción de obra material inmueble | 2 | 1,75 |
| 3440 | Otras al 3 % | 3 | 2,75 |
| 344A | Tarjetas y sistemas de pago | 2 | 2 |
| 3482 | Comisiones a sociedades residentes | 5 | 3 |

La lista completa (84 códigos para residentes) está en la migración. Reglas de la Res. 26-00000009:

- Si una factura tiene conceptos con porcentajes distintos, se retiene cada uno por separado; si no están separados, se aplica el más alto (art. 5).
- No hay retención sobre ingresos exentos ni sobre combustibles (art. 6).
- Se retiene al pagar o acreditar en cuenta, lo que ocurra primero (art. 8).
- Las sociedades Grandes Contribuyentes no son sujetas a retención de renta, salvo las excepciones de la LRTI art. 45.

## IVA (ficha técnica v2.34, tablas 20 y 23; Res. NAC-DGERCGC20-00000061)

| Código | % | Uso |
|---|---|---|
| 9 | 10 | Contribuyente especial que compra bienes a otro contribuyente especial |
| 10 | 20 | Contribuyente especial que compra servicios a otro contribuyente especial |
| 1 | 30 | Bienes; contratos de construcción |
| 2 | 70 | Servicios |
| 3 | 100 | Profesionales personas naturales, arriendo a personas naturales no obligadas a llevar contabilidad, liquidación de compra, importación de servicios |
| 8 | 0 | No procede retención |
| 7, 11, 4, 5, 6 | — | Cargados inactivos: uso residual o sin caso general vigente |

| Comprador → proveedor | Proveedor contribuyente especial | Otro proveedor |
|---|---|---|
| Contribuyente especial | 10 % bienes / 20 % servicios | 30 / 70 / 100 % |
| Agente de retención calificado | No retiene | 30 / 70 / 100 % |
| No calificado | No retiene | No retiene, salvo **liquidación de compra (100 %)** |

- **No se retiene IVA** a contribuyentes especiales, al Estado ni a las empresas públicas, ni por combustibles, servicios financieros y otros casos del art. 3.
- Por la reforma 23-00000026, según EY (sin texto oficial leído), tampoco a RIMPE Emprendedor pagado por medio electrónico.
- **Art. 17:** quien emite retenciones electrónicas debe emitir el comprobante aunque no proceda retención (usar el 332 al 0 %). Puede agrupar por mes y por proveedor.

## XML 2.0.0 — detalles que el sistema respeta

- `numDocSustento` es obligatorio en el XSD.
- `tipoSujetoRetenido` solo va con identificación del exterior (08).
- `contribuyenteEspecial` admite de 3 a 5 caracteres en el XSD 2.0.0; si no cabe, se omite.
- `porcentajeRetener` admite 3 dígitos con hasta 2 decimales.
- `agenteRetencion` va en infoTributaria si la empresa está marcada como agente, igual que en la factura.
- Sustentos admitidos con una factura como documento sustento: 01 a 09, 14 y 15 (tabla 5 del ATS). El 10 (dividendos) pide codDocSustento 19.
- Pagos al exterior (`pagoLocExt` 02), dividendos, banano y reembolsos (41): pendientes.

## Emisión y anulación

- **Plazo de entrega:** cinco días desde que se recibe el comprobante de venta (LRTI art. 50; RCV art. 8). La multa por no entregarlo es el 5 % de la retención.
- **Transmisión al SRI:** desde el 01/01/2026 se transmite al generarlo; se eliminó el plazo de 4 días (Res. 25-00000014, vigente según la 25-00000017).
- **Anulación:**
  - Solo en SRI en línea, hasta el día 7 del mes siguiente.
  - El receptor debe aceptarla en 5 días hábiles.
  - No se anulan las que sustentan devoluciones de impuestos.
  - Por eso el sistema no borra retenciones enviadas.

## Liquidación de compra (03) — para la siguiente etapa

- **Cuándo se emite** (RCV art. 13):
  - servicios de no residentes;
  - personas naturales sin RUC o con RUC suspendido que no pueden emitir comprobantes;
  - reembolsos a empleados, sin retención;
  - miembros de cuerpos colegiados de elección popular.
- **Retención:** 100 % del IVA (código 3) y la renta que corresponda (311 al 3 %).
- **Quién la emite:** puede emitirla un no agente.
- **XML:** versión 1.1.0, que admite 6 decimales en cantidad y precio. No se permite la identificación 07.

## Fuentes (consultadas el 14/10/2026)

- Res. NAC-DGERCGC26-00000009: https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/272ca6a9-d679-4b4e-8da0-fb4671cf5f8f/NAC-DGERCGC26-00000009_Ret_IR.pdf
- Catálogo ATS (06/08/2026): https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/e6a826af-b22c-40bb-8752-d711f293b8f9/Catalogo_ATS.xls
- Tabla código ↔ casillero 103: https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/a305ad8c-7cfd-42c7-8cea-be4dbf850d0c/tabla_retenciones.xls
- Res. NAC-DGERCGC20-00000061: https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/185c7087-f119-4f0d-8dcd-702c30ebd793/NAC-DGERCGC20-00000061.pdf
- Normativa para agentes de retención: https://www.sri.gob.ec/normativa-para-agentes-de-retencion-y-contribuyentes-especiales
- XSD de retención 2.0.0: https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/90950fca-73a7-4cfb-9c2d-3142b10435f2/XML%20y%20XSD%20Comprobante%20de%20Retenci%c3%b3n.zip
- XSD de liquidación de compra: https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/ee386507-04f8-4a45-b9cd-6d4e4c6ac1e6/XML%20y%20XSD%20Liquidaci%c3%b3n.zip

**Queda abierto:**

- El Registro Oficial de la Res. 26-00000009 solo consta en fuentes secundarias.
- No se leyó el texto oficial de la reforma 23-00000026.
- No se verificó si una reforma de 2024 cambió los arts. 8 y 13 del RCV.
