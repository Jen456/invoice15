# Norma tributaria y contable de Ecuador para Bancos, Contabilidad y Formularios (octubre de 2026)

Investigación del 27–28/10/2026 para el plan de Proformas, Bancos y Contabilidad (`PLAN-PROFORMAS-BANCOS-CONTABILIDAD.md`). Las cifras marcadas con [n] salen del documento oficial original: los PDF y Excel del SRI y la Supercias se descargaron y se leyeron en local. Lo marcado como **no confirmado** debe comprobarse en la etapa que lo use antes de programarlo.

## 0. Cambios de 2024 a 2026 que afectan al diseño
- **IVA 15 %** desde el 01/04/2024 (Registro Oficial S.525 del 25/03/2024) [8], y **5 % para materiales de construcción**, con casilleros propios en el 104 [6]. Sigue en 15 % en 2026.
- **Retenciones de renta, Res. NAC-DGERCGC26-00000009**: firmada el 27/02/2026, vigente desde el **01/03/2026**; deroga la NAC-DGERCGC24-00000008 [1]. El porcentaje supletorio sube de 2,75 % a **3 %**.
- **Catálogo ATS del 06/08/2026**: trae tablas de retención con vigencias "desde 01/03/2026", "01/08/2026" y "06/08/2026" [2]. La última cambia los códigos **310 y 332E** "según resolución NAC-DGERCGC26-00000028" (contenido **no confirmado**) → comparar con la tabla cargada en `CodigoRetencion` (decisión D0).
- **IVA: desde el 01/06/2026 la declaración solo es válida si se paga el total** (exceptuados exportadores de bienes y sus proveedores directos). La circular está **no confirmada**.
- **Ley Orgánica de Transparencia Social** (Registro Oficial del 28/08/2025; reglamento del 28/10/2025):
  - retención a dividendos del 12 % o 14 % (códigos 326 y 327);
  - **pago a cuenta sobre utilidades no distribuidas** (Res. NAC-DGERCGC26-00000026 del 14/07/2026), en agosto (código 1077) o en tres cuotas agosto–octubre (código 1078).
- **Res. NAC-DGERCGC26-00000027**, registro de proveedores de software de facturación electrónica: el RUC del proveedor va en "información adicional". **FacturaPorAquí ya lo cumple** (`FPA_RUC_PROVEEDOR`, publicado en octubre).
- **REBEFICS reemplazó al Anexo de Accionistas (APS)** desde el 30/09/2024.
- **Programa ATS 1.19.0** del 23/09/2026, "para períodos desde septiembre de 2026" [5]. Qué cambia: **no confirmado**.

## 1. Formulario 104 (IVA)
- **Periodicidad**: mensual para quien vende con tarifa distinta de 0 o es agente de retención; semestral para quien solo vende con tarifa 0, tiene retención total o es RIMPE [6][7].
- **Plazo** según el 9.º dígito del RUC: 1→10, 2→12, 3→14, 4→16, 5→18, 6→20, 7→22, 8→24, 9→26, 0→28. Si cae en día no hábil, pasa al siguiente día hábil (RLRTI art. 102) [7].
- **Medio**: solo en línea; **no hay archivo importable**. Hay prellenado y valores sugeridos (564, 565, 615, 617), y arrastre obligatorio de 483, 605, 606, 607 y 608 desde el mes anterior [6].

| Bloque | Casilleros (valor bruto / neto / impuesto) |
|---|---|
| Ventas con tarifa distinta de 0 (sin y con activos fijos) | 401-411-421 / 402-412-422 |
| Ventas al 5 % | 425-435-445 |
| Ventas 0 % sin / con derecho a crédito | 403-413 (no confirmado) / 405-415, 406-416 |
| Exportaciones de bienes / servicios | 407-417 / 408-418 |
| Totales de ventas | 409-419-429 |
| Ajustes por NC; no objeto o exentas; reembolsos | 423 / 424; 431; 434 |
| Contado / crédito / impuesto generado | 480 / 481 / 482 |
| Impuesto a liquidar: mes anterior / este mes / próximo mes; total | 483 / 484 / 485; 499 |
| Compras con derecho a crédito (sin / con activos fijos) | 500-510-520 / 501-511-521 |
| Compras al 5 % | 540-550-560 |
| Compras sin crédito; importación de servicios; de bienes | 502; 503; 504 / 505 |
| Compras 0 %; totales; no objeto / exentas | 507; 509-519-529; 531 / 532 |
| Factor de proporcionalidad; crédito aplicable; IVA no usado como crédito | 563; 564; 565 |
| Impuesto causado / crédito aplicable | 601 / 602 |
| Saldo de crédito del mes anterior (adquisiciones / retenciones) | 605 / 606 |
| **Retenciones de IVA que le hicieron** | **609** |
| Saldo de crédito para el mes próximo (adquisiciones / retenciones) | 615 / 617 |
| **Retenciones de IVA efectuadas como agente** | **721 = 10 %, 723 = 20 %, 725 = 30 %, 727 = 50 %, 729 = 70 %, 731 = 100 %** |
| Total a pagar; pago previo; intereses / multas | 902; 890; 903 / 904 |

Códigos de retención de IVA en el ATS (Tabla 11): 9 = 10 %, 10 = 20 %, 1 = 30 %, 11 = 50 %, 2 = 70 %, 3 = 100 % [3].

## 2. Formulario 103 (retenciones de renta)
- Mensual, mismo calendario por 9.º dígito. En línea.
- **Regla de casilleros**: el casillero de la **base** es el código de retención; el del **valor retenido**, la base + 50. Verificado en una declaración real de mayo de 2024: 303→353, 3030→3530, 3480→3980; subtotal país 349/399; **499 = 399 + 498** (exterior).
- En el Catálogo ATS la columna del código se llama "Número de campo" [2]. Los códigos con letra se agrupan en casilleros de 4 dígitos (303A→3030); el mapa completo está **no confirmado** y se carga desde el catálogo.

Tabla vigente (Catálogo ATS, bloque "desde 06/08/2026"; la columna "antes" es la de 2025):

| Código | Concepto | % hoy | Antes |
|---|---|---|---|
| 303 | Honorarios profesionales | 10 | 10 |
| 303A | Servicios profesionales de sociedades | 5 | 3 |
| 307 | Predomina la mano de obra | 3 | 2 |
| 309 | Medios de comunicación y publicidad | 3 | 2,75 |
| 310 | Transporte | 1 (o 0 según Res. 26-00000028) | 1 |
| 311 | Liquidación de compra | 3 | 2 |
| 312 | Bienes muebles | 2 | 1,75 |
| 320 | Arriendo de inmuebles | 10 | 10 |
| 322 | Seguros | 2 | 1 |
| 326 / 327 | Dividendos | 12 / 14 | — |
| 332… | No sujetos (incluye RIMPE negocio popular) | 0 | 0 |
| 343 | Otras 1 % (incluye RIMPE emprendedor) | 1 | 1 |
| 343A / 343B | Energía eléctrica / construcción | 2 / 2 | 1 / 1,75 |
| 3440 | Otras 3 % (supletoria) | 3 | 2,75 |
| 3482 | Comisiones a sociedades | 5 | 3 |
| 500–525 | Pagos a no residentes | 0–37 | — |

## 3. ATS (Anexo Transaccional Simplificado)
- **Obligados**: sociedades, personas naturales obligadas a llevar contabilidad, contribuyentes especiales, sector público y RIMPE (ficha técnica del 07/02/2025) [3]. **Sigue siendo obligatorio para sociedades.**
- **Periodicidad**: mensual; semestral para RIMPE. Archivo: un XML comprimido como `ATmmaaaa.zip`.
- **Factura electrónica** (Res. NAC-DGERCGC16-00000092): las ventas emitidas electrónicamente no van en `detalleVentas`, y desde 2018 las retenciones electrónicas no se reportan en compras. Las facturas de compra sí se reportan (práctica habitual; **no confirmado** literalmente).
- **Descargas** [5]: [ats.xsd](https://descargas.sri.gob.ec/download/anexos/ats/ats.xsd) (02/12/2020), Catálogo del 06/08/2026, ficha técnica del 07/02/2025, programa DIMM ATS 1.19.0.
- **Estructura del XSD** (raíz `iva`):
  - **Cabecera**: `TipoIDInformante`, `IdInformante`, `razonSocial`, `Anio`, `Mes`, `regimenMicroempresa`, `numEstabRuc`, `totalVentas`, `codigoOperativo`.
  - **`compras/detalleCompras`**: `codSustento`, `tpIdProv`, `idProv`, `tipoComprobante`, `tipoProv`, `denoProv`, `parteRel`, `fechaRegistro`, `establecimiento`, `puntoEmision`, `secuencial`, `fechaEmision`, `autorizacion`, bases (`baseNoGraIva`, `baseImponible`, `baseImpGrav`, `baseImpExe`), `montoIce`, `montoIva`, retenciones de IVA por porcentaje, `totbasesImpReemb`, `pagoExterior`, `formasDePago`, `air/detalleAir`, documento modificado y reembolsos.
  - **`ventas/detalleVentas`**: agrupado por cliente y tipo de comprobante, con `valorRetIva` y `valorRetRenta`.
  - **`ventasEstablecimiento`**, **`anulados`**, exportaciones y otros.
- **Catálogos** [3]:
  - Tabla 2, tipo de identificación: compras 01 RUC, 02 cédula, 03 pasaporte; ventas 04 RUC, 05 cédula, 06 pasaporte, 07 consumidor final. **Son distintos de los de la factura electrónica.**
  - Tabla 4, tipos de comprobante: 1 factura, 2 nota de venta, 3 liquidación, 4 NC, 5 ND, 11, 12, 15, 19, 20, 41, 47, 48…
  - Tabla 5, sustento tributario: 01 crédito de IVA, 02 costo o gasto, 03/04 activo fijo, 05 viajes, 06/07 inventario, 08 reembolso… hasta 15.
  - Tabla 13, formas de pago: 01, 15, 16, 17, 18, 19, 20, 21. Tabla 14 (`tipoProv`): 01 natural, 02 sociedad. Tabla 20: F física, E electrónica.

## 4. Formulario 101 (sociedades)
- Es el formulario único: estado de situación financiera, estado de resultados y **conciliación tributaria** (utilidad, 15 % de trabajadores, exentas, no deducibles, amortización de pérdidas, base, impuesto, retenciones y créditos) [9]. El casillero 324 (crédito de IVA) cuadra con el 104.
- El instructivo disponible es antiguo: **la numeración actual de casilleros está no confirmada** → el mapa debe ser editable.
- Tarifa del 25 %, plazos y diferencias entre el 102 y el 102A: **no confirmado** en esta revisión.

## 5. Superintendencia de Compañías
- [Plan de cuentas oficial](https://appscvsmovil.supercias.gob.ec/balances/PLAN_CUENTAS.pdf) (PDF de 28 páginas; no hay versión en Excel). Niveles 1 / 3 / 5 / 7 dígitos; cada cuenta lleva signo POSITIVO, NEGATIVO o DUAL.
- **Estado de situación financiera**: 1 Activo (101 corriente, 102 no corriente), 2 Pasivo (201 corriente, 202 no corriente), 3 Patrimonio (301 capital … 307 resultado del ejercicio).
- **Resultado integral**: 401 ingresos ordinarios, 501 costo de ventas, 502 gastos, 600 en adelante resultado antes del 15 % y del impuesto.
- **Flujo de efectivo**: grupo 95–98. **Cambios en el patrimonio**: grupo 99.
- **Presentación anual hasta el 30 de abril.**
- NIIF para PYMES: activos menores a USD 4 M, ventas hasta USD 5 M y menos de 200 trabajadores (fuentes secundarias).

## 6. Otros anexos
| Obligación | Periodicidad | ¿Lo genera el sistema? |
|---|---|---|
| REBEFICS (ex-APS) | Anual | No (datos societarios) |
| RDEP y 107 | Anual | Solo con nómina (fuera de este proyecto) |
| ADI (dividendos), v1.6.0 | Anual (plazo no confirmado) | Sí, Etapa 8 |
| Pago a cuenta por utilidades no distribuidas | Agosto, o tres cuotas agosto–octubre | Hoja de cálculo, Etapa 8 |
| ICE (105) | Mensual | Solo productores e importadores |

## 7. Contabilidad obligatoria
- **LRTI art. 19**: todas las sociedades; personas naturales con ingresos del año anterior mayores a USD 300.000 [8].
- **RLRTI art. 37**: también con capital propio mayor a USD 180.000 o costos y gastos mayores a USD 240.000. Firma un contador autorizado. Los documentos se conservan **7 años** [7].
- **RLRTI art. 39**: partida doble, en castellano y en dólares. **Arts. 99 y 156**: registros auxiliares de retenciones y crédito tributario.
- **No existe homologación de software contable** en Ecuador.

## 8. Extractos bancarios
- **Pichincha (Cash Management)**: Excel, PDF y formato "SAP". **Produbanco**: varios formatos, PDF o Excel hasta 6 meses. **Pacífico**: Excel. **Bolivariano**: TXT o Excel.
- **Guayaquil, Internacional, MT940/OFX/camt.053**: no confirmado.
- **Conclusión**: importador XLSX/CSV/TXT con plantilla de columnas por banco, armada a partir de muestras reales anonimizadas (decisión D6).

## Fuentes
1. [Res. NAC-DGERCGC26-00000009](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar?id=76ba02f0-718a-41b7-a54a-7e0f5615808a&nombre=NAC-DGERCGC26-00000009.pdf)
2. [Catálogo ATS, 06/08/2026](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/e6a826af-b22c-40bb-8752-d711f293b8f9/Catalogo_ATS.xls)
3. [Ficha técnica del ATS, 07/02/2025](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/72d717c2-88ed-47b7-baba-50b87b7198b7/Ficha%20Tecnica%20Transaccional%20Simplificado%20ATS.pdf)
4. [ats.xsd](https://descargas.sri.gob.ec/download/anexos/ats/ats.xsd)
5. [SRI, formularios e instructivos](https://www.sri.gob.ec/en/formularios-e-instructivos1)
6. [Guía del formulario de IVA](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/e084fae5-9677-450c-8161-21e7c3a9f65b/Gu%C3%ADa%20para%20el%20llenado%20del%20Formulario%20Impuesto%20al%20Valor%20Agregado%20IVA.PDF)
7. [RLRTI, compilación del 15/07/2024](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/bb4d529f-0501-4df9-a811-8d2a3697e212/RLRTI_15072024.pdf)
8. [LRTI, codificación del 01/04/2026](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/12c884d5-c8d9-4171-becc-1513b990b87a/LEY_DE_REGIMEN_TRIBUTARIO_INTERNO_LRTI.pdf)
9. [Instructivo del formulario 101](https://www.sri.gob.ec/o/sri-portlet-biblioteca-alfresco-internet/descargar/f3932589-7946-4dde-9bed-1e9840c2732f/Instructivo%20Formulario%20101.pdf)
10. [Plan de cuentas Supercias](https://appscvsmovil.supercias.gob.ec/balances/PLAN_CUENTAS.pdf)

Fuentes secundarias usadas solo para fechas o confirmaciones: NMS Law (registro de proveedores, pago a cuenta, REBEFICS, Ley de Transparencia Social), Andersen TIPS 21 (septiembre de 2026), Vistazo (pago total del IVA, 17/04/2026), Moore No. 154 (plazo de la Supercias), Siigo/Contífico (casilleros del 5 %), y los manuales de cash management de Pichincha, Produbanco, Pacífico y Bolivariano.
