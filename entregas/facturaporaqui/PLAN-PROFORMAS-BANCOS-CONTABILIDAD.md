# FacturaPorAquí — Plan de trabajo: Proformas, Bancos y Contabilidad (Ecuador)

> Aprobado por la propietaria el 28/10/2026. Documento vivo (seguimiento de etapas y decisiones): https://claude.ai/artifact/Gxt36BgC1o8LEZMSKT9P5s · Norma y fuentes: `NORMA-CONTABLE-TRIBUTARIA-2026-10.md`.

## Context

facturaporaqui.com (repo `Jen456/invoice15`, rama `plataforma`, publicado `98cfa20`, GitHub `4ce7888`) ya hace lo siguiente:
- emite 01, 03, 04, 05, 06 y 07 en el SRI;
- es multiempresa, con RLS en PostgreSQL 16;
- cobra los planes con PayPhone.

La propietaria pide ampliar su capacidad con tres cosas:
1. **Proformas** que no van al SRI.
2. **Bancos**: cuentas bancarias, movimientos y conciliación.
3. **Contabilidad** según el sistema financiero ecuatoriano (NIIF/Supercias), con el **104**, el **103**, el **ATS** y los demás formularios de las sociedades. erpnext se usa como referencia.

Este documento es la **Etapa 0 (análisis y plan)**. No se escribe código hasta aprobar las decisiones de la sección 7.

## 1. Lo que encontré

### erpnext (`Jen456/erpnext`)
- Es un fork **sin cambios propios** de `frappe/erpnext` (rama develop de nov-2020, v13-beta). El único commit propio toca el README. No tiene nada ecuatoriano.
- **Solo sirve como referencia de diseño.** erpnext es **GPL-3.0**: copiar código obligaría a liberar invoice15. Se toman conceptos, no código.
- Conceptos que se adoptan:
  - `Account`: árbol con número, tipo raíz, `account_type` y "balance must be".
  - `GL Entry`: línea inmutable con documento origen, tercero, debe/haber y anulada.
  - `Journal Entry`, `Payment Entry`, `Mode of Payment` (con su cuenta), `Fiscal Year`, `Accounting Period` y `Period Closing Voucher`.
  - `Bank Account`: enlazada a una cuenta contable.
  - `Bank Transaction`: línea del extracto con estado y asignaciones parciales (`allocated` / `unallocated`).
  - `Bank Clearance` y el reporte `Bank Reconciliation Statement`: saldo en libros, partidas en tránsito y saldo del banco.
- Lo que **no** se adopta:
  - Su plan ecuatoriano `ec_ec_chart_template.json`: está en "unverified", no tiene códigos y es anterior a NIIF.
  - Su emparejamiento por importe con `LIKE 'importe%'`.

### invoice15 (hoy)
- **No hay bancos, caja ni plan de cuentas.** Solo existe `propuesta_contable()` (`core/importacion/servicios.py:582`), que nunca se contabiliza, y `ReglaImportacion`, con cuentas como texto libre.
- **Huecos en los datos de origen** (bloquean asientos, 104, 103 y ATS):
  - **Compras** (`Purchase`, `core/pos/models.py:262`):
    - Guardan solo el subtotal: sin IVA, tarifa, descuento ni ICE.
    - La cuenta por pagar (`DebtsPay`) queda **sin IVA**.
    - No guardan tipo de comprobante, sustento, establecimiento, punto, secuencial, autorización ni fecha de emisión.
    - `number` es único por empresa, no por proveedor.
  - **Proveedor** (`Provider`, `:113`): sin tipo de identificación, tipo de sujeto ni parte relacionada.
  - **Gastos** (`Expenses`, `:1132`): sin proveedor, comprobante ni IVA.
  - **Cobros y pagos** (`PaymentsCtaCollect` `:1008`, `PaymentsDebtsPay` `:1080`): sin medio de pago, banco ni referencia.
  - **NC y ND**: no tocan el saldo de la cuenta por cobrar.
  - **Retenciones recibidas** de clientes: no existen, y la importación rechaza el tipo 07.
  - **Anulados**: no existe el estado "Anulado en SRI".
  - **Costo de ventas**:
    - No hay kardex ni costo.
    - `SaleDetail` no guarda el costo.
    - El ajuste de stock sobrescribe el número sin dejar registro.
  - **Ventas** (`Sale.subtotal_12`): junta 15 % y 5 %. Los formularios deben salir de `SaleDetail.codigo_porcentaje` con `impuestos_por_tarifa()` (`core/pos/models.py:594`).
  - **Reportes actuales**: filtran por `date_joined` y mezclan PRUEBAS, no autorizados y anulados.
- **Lo que ya sirve**:
  - `Retencion` 07: sustento, parte relacionada, autorización del documento de sustento y detalle por código.
  - `DocumentoImportado`: autorización, establecimiento, punto, secuencial, bases por tarifa, ICE y formas de pago.
  - El rol **Contador** ya existe, pero solo con lectura (`core/tenancy/roles.py:28`).
  - openpyxl y xlsxwriter están instalados.
  - Patrones de importación seguros: SHA-256, `privado/` y subida por partes de 9 MB.
- **Proformas**: no existe nada. El ticket 08 consume secuencia y mueve stock, así que no sirve.

### Norma vigente (oct-2026; fuentes oficiales en el informe adjunto al artefacto)
- **IVA 15 %, más 5 % para construcción**, con casilleros propios: ventas 425/435/445 y compras 540/550/560.
- **104**:
  - Solo en línea, sin archivo importable. Hay prellenado.
  - Arrastre obligatorio de 605–608 desde 615/617.
  - **Desde el 01/06/2026 la declaración solo es válida si se paga el total.**
  - Periodicidad mensual, o semestral para RIMPE o quien solo vende con tarifa 0.
- **103**:
  - Casillero de la base = código de retención; casillero del valor retenido = código + 50.
  - Totales 349/399 y exterior 498/499.
  - El código del catálogo ATS es el "número de campo".
- **ATS**:
  - Sigue siendo obligatorio para sociedades.
  - Formato: XML según `ats.xsd` (02/12/2020), entregado en `ATmmaaaa.zip`.
  - Las ventas electrónicas no van en `detalleVentas`; las compras sí van en `detalleCompras`.
  - Los tipos de identificación del ATS difieren de los de la factura electrónica.
  - Versión vigente del programa DIMM: 1.19.0.
- **Retenciones**: tabla desde el 01/03/2026 (Res. 26-00000009, ya cargada). **El catálogo ATS del 06/08/2026 trae cambios posteriores en el 310 y el 332E (Res. 26-00000028)** → hay que revisar la tabla del sistema (ver D0).
- **Supercias**: plan de cuentas oficial en PDF (niveles 1/3/5/7). Estados financieros anuales hasta el 30 de abril (situación financiera, resultado integral, flujo de efectivo grupo 95–98, cambios en el patrimonio grupo 99).
- **101**: estado de situación financiera + estado de resultados + conciliación tributaria (15 % para los trabajadores).
- **Otros**:
  - REBEFICS (reemplazó al APS): no es del sistema.
  - RDEP y 107: requieren nómina.
  - ADI y pago a cuenta por utilidades no distribuidas: opcionales.
- **Contabilidad obligatoria**: partida doble, en castellano y en USD, con conservación de 7 años. **No existe homologación** de software contable.
- **Res. 26-00000027** (RUC del proveedor en "información adicional"): **ya cumplida** (`FPA_RUC_PROVEEDOR`, publicado el 13 y el 24 de octubre).
- **Extractos bancarios**: Pichincha, Produbanco, Pacífico y Bolivariano exportan Excel, TXT o PDF. Ninguno confirma MT940 ni OFX → importador XLSX/CSV con un perfil por banco.

## 2. Principios para todos los módulos
- **Patrón de app existente** (`core/comprobantes`, `core/importacion`):
  - modelos `TenantModel`;
  - migración RLS copiando `comprobantes/migrations/0012_seguridad_por_filas_guia.py`;
  - registro en `TENANT_APPS` (`core/tenancy/checks.py:6`);
  - vistas con `GroupPermissionMixin`;
  - menú por migración de datos **y** en `start_installation.py`, generalizando `organizar_menu()` en `core/security/menu.py:72` (hoy filtra `app_label='importacion'`);
  - acciones nuevas en `AuditLog.ACTIONS`.
- **Solo los comprobantes AUTORIZADOS en PRODUCCIÓN** (`environment_type=2`), por `emission_date`, alimentan libros y formularios. PRUEBAS queda fuera.
- **Inmutabilidad**: lo contabilizado no se edita, se anula con un asiento reverso. Los períodos y las conciliaciones cerradas bloquean cambios. La reapertura queda registrada.
- **Trazabilidad**: cada línea de asiento apunta a su documento y cada casillero del 104/103 lleva a su lista de documentos.
- **Idempotencia**: contabilizar o importar dos veces no duplica nada (unicidad por origen y SHA-256 por archivo y por línea).
- **Importes**: `Decimal` siempre, a 2 decimales al guardar.
- **Catálogos de plataforma con vigencia**: retenciones, casilleros y plan Supercias se pueden editar desde `/plataforma/`.
- **Contabilidad opcional por empresa**: el asistente "Activar contabilidad" la enciende. Nada cambia para quien no la active.

## 3. Módulos (diseño)

### 3.1 Proformas — app `core/proformas`
- **Modelos**:
  - `Proforma`:
    - número propio `PRO-000001` por empresa, con contador `select_for_update`, **sin `Receipt`**;
    - cliente registrado o prospecto (nombre y correo libres);
    - fecha, validez (15 días por defecto), vendedor, condiciones y forma de pago sugerida;
    - totales por tarifa;
    - estado: borrador, enviada, aceptada, rechazada, vencida (calculada), facturada o anulada;
    - `venta` OneToOne, que se llena al facturar.
  - `ProformaDetalle`: producto, descripción, cantidad, precio, descuento y `codigo_porcentaje`. Los totales se calculan con `calcular_linea_iva` / `totales_de_lineas` (`core/pos/models.py:568,606`).
- **Pantallas**: lista con filtros, crear, editar, duplicar, PDF y correo.
  - **PDF A4 "PROFORMA – sin validez tributaria"**: reutiliza `templates/ride/_estilos.html` y `_pie.html`, sin clave, autorización ni código de barras.
  - **Correo**: reutiliza `_correo_saliente()` (`core/pos/utilities/sri.py:87`) y `separar_correos`.
- **Facturar**: abre la pantalla de venta precargada con `?proforma=ID`, que lleva a `core/pos/views/sale/views.py` y `core/pos/static/sale/admin/js/form.js`. Al guardar, la venta sigue el flujo normal (número, stock, cupo, firma y SRI) y la proforma pasa a "facturada" con bloqueo, lo que impide facturarla dos veces.
- **Restricciones**:
  - Ninguna llamada al SRI, ningún `reservar_numero`, nada de stock, cupo ni `CtasCollect`.
  - Prefijo propio `/proformas/` en `RUTAS_DE_PAGO`, sin acciones llamadas `generate_invoice`.
  - El Vendedor escribe (`SELLER_URLS`) y el Contador solo lee.

### 3.2 Datos de origen — mejoras en `core/pos`, `core/comprobantes` y `core/importacion`
- **Compras completas**:
  - **Campos nuevos**: `tipo_comprobante` (Tabla 4 del ATS), `cod_sustento` (Tabla 5), establecimiento, punto, secuencial de 9 dígitos, autorización, fecha de emisión, fecha de registro, forma de pago y parte relacionada.
  - **Por línea**: tarifa, IVA y descuento.
  - **Totales**: base 0, gravada 15, 5, no objeto y exenta, más IVA, ICE y total. La cuenta por pagar se calcula sobre el **total con IVA**.
  - **Unicidad**: (empresa, proveedor, tipo, establecimiento, punto, secuencial).
  - **Compras antiguas**: quedan marcadas como `datos_incompletos` y no se recalculan (D8).
- **Proveedor**: tipo de identificación (04/05/06/08), tipo de sujeto (natural/sociedad) y parte relacionada. Se agrega la conversión a los códigos del ATS (01/02/03).
- **Gastos**:
  - Con factura: se registran como **compra de tipo gasto**, con sustento 02 y la cuenta del tipo de gasto.
  - Sin comprobante: siguen en `Expenses`, con medio de pago.
- **Importación**:
  - Crear la compra desde el XML importado, emparejando productos por código del proveedor o registrándola como gasto.
  - Importar también 04, 05 y **07 recibidas**.
- **Retenciones recibidas**: modelo `RetencionRecibida` con su detalle, ligado a la venta. Abona la cuenta por cobrar y alimenta el 609 del 104, el ATS y el crédito tributario del 101.
- **NC y ND**: ajustan la cuenta por cobrar (abono de tipo NC; la ND crea o aumenta la deuda).
- **"Anulado en SRI"**: marca manual con fecha y motivo, después de anular en SRI en línea. Lo excluye de los formularios.
- **Empresa**: tipo de contribuyente (sociedad / persona natural obligada / no obligada) y periodicidad (mensual/semestral). Calendario de vencimientos según el 9.º dígito.
- **Reportes actuales**: pasan a filtrar por `emission_date`, producción y autorizados.
- **Comprobantes de pago adjuntos (hecho el 30/10/2026, app `core/adjuntos`, sin publicar):** transferencias, depósitos, cheques,
  vouchers y recibos adjuntos a facturas emitidas, compras, gastos, cobros y pagos; página «Comprobantes de pago» del mes con los pagados
  por banco sin comprobante y ZIP con índice; referencia, fecha e importe del comprobante quedan para las sugerencias de conciliación de
  la Etapa 3. Contrato en `CONTRATO-PANTALLAS-ADJUNTOS.md`. Adelanta la parte de «respaldo» de §3.3 sin crear cuentas ni movimientos.

### 3.3 Bancos y conciliación — app `core/bancos`
- **Catálogos y cuentas**:
  - `InstitucionFinanciera`: catálogo de plataforma con los bancos del Ecuador.
  - `CuentaBancaria`: tipo corriente, ahorros o **caja** (caja general o chica), número, titular, saldo inicial con fecha, y `cuenta_contable` (se llena al activar la contabilidad).
- **`MovimientoBancario` (libro bancos)**:
  - **Tipo**: depósito, transferencia recibida o enviada, cheque emitido (número, beneficiario, estado girado/cobrado/anulado/protestado), nota de débito o crédito bancaria, comisión, interés, retiro o transferencia entre cuentas.
  - **Datos**: importe con signo, referencia y tercero.
  - **Origen**: cobro, pago, venta al contado, gasto o manual.
  - **Estado**: pendiente, conciliado o anulado.
- **Integración**: cobros, pagos, ventas al contado y gastos piden **medio de pago y cuenta**, y crean el movimiento en la misma transacción. El efectivo va a caja.
- **Extractos**:
  - `ExtractoBancario`: archivo en `privado/`, SHA-256 único y saldos inicial y final declarados.
  - `LineaExtracto`: fecha, descripción, referencia, débito, crédito, saldo y hash de línea, para no duplicar extractos que se solapan.
  - `PerfilImportacion` por banco: mapa de columnas, formato de fecha, separador decimal y fila de cabecera. Se precargan perfiles a partir de **muestras reales anonimizadas** (D6).
  - Lectura: XLSX (openpyxl en solo lectura, con límite de filas) o CSV/TXT.
  - Validación: saldo inicial + movimientos = saldo final.
- **`Conciliacion`**:
  - **Datos**: cuenta, fecha de corte, saldo según banco, saldo según libros y estado (en curso / cerrada).
  - **Emparejamientos**: muchos a muchos con importe asignado (1:1, 1:n o n:1).
  - **Sugerencias automáticas**: importe exacto con el mismo signo, fecha ±5 días y referencia o número de cheque. Se confirman con un clic.
  - **Líneas sin contraparte** (comisión, interés, débito automático): desde ellas se crea el movimiento.
  - **Reporte clásico**: saldo del estado de cuenta + depósitos en tránsito − cheques girados y no cobrados ± otras partidas = saldo en libros. Solo se puede cerrar con diferencia 0.
  - **Cierre**: bloquea lo conciliado. La reapertura la hacen Propietario o Contador, con registro en `AuditLog`.
- **Pantallas**: cuentas, libro por cuenta con saldo corrido, registrar movimiento, transferencia o cheque, importar extracto, conciliar (extracto y libros lado a lado), historial, cheques en circulación.

### 3.4 Núcleo contable — app `core/contabilidad`
- **Plan de cuentas**:
  - `PlantillaPlanCuentas` (plataforma): el **catálogo Supercias** transcrito del PDF oficial (código, nombre, nivel, signo), más un **detalle PYME recomendado**: caja, una subcuenta por cada banco, clientes, IVA en compras 15/5, crédito tributario de renta e IVA, IVA en ventas, retenciones por pagar por código, proveedores, inventario, costo de ventas, ventas por tarifa y gastos típicos.
  - `Cuenta` por empresa (copiada de la plantilla y editable): código, padre, nivel, de movimiento o de grupo, naturaleza, tipo, `codigo_supercias` (para los estados financieros), `rol` automático (banco, caja, cxc, cxp, iva_ventas…), `requiere_tercero` y `no_deducible` (para el 101).
- **Períodos**: `Ejercicio` y `Periodo` mensual, abierto o cerrado.
- **`Asiento`**:
  - número por empresa y ejercicio;
  - tipo: diario, ingreso, egreso, apertura, ajuste o cierre;
  - glosa;
  - origen (`origen_tipo` + `origen_id`, únicos);
  - estado: borrador, contabilizado o anulado;
  - `reversa_de`.
- **`LineaAsiento`**: cuenta de movimiento, debe y haber (CHECK: uno de los dos en cero, ambos ≥ 0), tercero, referencia y movimiento bancario. El cuadre se valida en el servicio y lo comprueba la orden `verificar_cuadre`.
- **Asistente "Activar contabilidad"**: elegir plantilla, fecha de inicio y saldos iniciales (asiento de apertura con importación desde Excel).
- **Reportes** (XLSX en servidor con xlsxwriter, PDF con WeasyPrint): libro diario, libro mayor, balance de comprobación (sumas y saldos), auxiliares de clientes y proveedores, y asientos manuales con reverso.
- **Roles**: el Contador **escribe** en `/contabilidad/` y `/bancos/` (cambio en `role_modules()`). Consulta solo lee. Vendedor no tiene acceso.

### 3.5 Contabilización automática y kardex (`core/contabilidad/motor.py`)
- **`contabilizar(documento)`**:
  - Es idempotente.
  - Se llama de forma explícita: al autorizar (`_despues_de_autorizar`, `core/pos/emision.py:299`) y al guardar compras, cobros, pagos, retenciones y movimientos.
  - **Nunca bloquea la emisión**: si falta una cuenta, el documento queda en la bandeja "Pendiente de contabilizar".
- **Orden `contabilizar --desde --hasta [--aplicar]`**: ensayo por defecto. Sirve para el arranque y para regenerar.
- **Matriz de asientos** (cuentas resueltas por rol, con excepciones por categoría, producto o tipo de gasto):
  - **Factura**: D clientes, caja o banco / C ventas por tarifa y C IVA en ventas. Además, D costo de ventas / C inventario.
  - **NC**: reverso proporcional, más reingreso al costo si es devolución.
  - **ND**: D clientes / C otros ingresos e IVA.
  - **Compra o liquidación**: D inventario, gasto o activo (según el sustento) y D IVA en compras, o al costo si no da crédito / C proveedores.
  - **Retención emitida**: D proveedores / C retenciones de renta por pagar (por código) y de IVA por pagar.
  - **Retención recibida**: D crédito tributario de renta e IVA / C clientes.
  - **Cobro y pago**: banco o caja contra clientes o proveedores.
  - **Gasto sin factura**: D gasto / C caja o banco.
  - **Movimiento bancario manual**: comisión, interés o ND/NC bancaria.
  - **Transferencia entre cuentas**.
  - **Liquidación del IVA del mes**: asiento sugerido desde la hoja del 104.
- **Kardex** (decidido: automático cuando los datos están completos y completable a mano):
  - `MovimientoInventario`: entrada, salida, devolución o ajuste, con cantidad, costo unitario, saldo y **costo promedio ponderado** por producto.
  - **Automático**: las compras completas (Etapa 2) suman al costo, las ventas y NC autorizadas guardan el costo del momento en `SaleDetail.costo`, y los ajustes de stock quedan registrados (hoy sobrescriben el número).
  - **Manual**: si el contador no cargó todo en el sistema, registra saldos iniciales por producto (cantidad y costo), entradas y salidas manuales con documento de respaldo y compras antiguas. Así el kardex sale completo.
  - Orden `reconstruir_kardex --producto/--desde [--aplicar]`, que recalcula el promedio cuando se corrige un movimiento con fecha anterior (ensayo por defecto).
  - Reporte kardex por producto (fecha, documento, entradas, salidas, saldo, costo unitario y total) en XLSX y PDF, más el inventario valorizado a una fecha.
  - Si un producto tiene costo desconocido, la venta se contabiliza igual, pero el asiento de costo queda en la bandeja "Pendiente de costo" hasta que se complete el kardex.

### 3.6 Formularios del SRI — app `core/tributario`
Se calculan desde los documentos, **sin depender de la contabilidad**, para que también sirvan a quien no la active.
- **104** (`DeclaracionIVA` por mes o semestre):
  - **Ventas**: por tarifa, desde `SaleDetail.codigo_porcentaje`: 401/411/421, 425/435/445, 403/405/413/415, 431, contado/crédito 480/481. Las NC van como ajustes en 423/424.
  - **Compras**: con crédito 500/510/520 y 540/550/560; tarifa 0 en 507; sin crédito en 502.
  - **Retenciones**: las recibidas en **609**; las efectuadas en **721–731**, por porcentaje, desde `RetencionDetalle`.
  - **Proporcionalidad**: factor 563.
  - **Arrastre**: 605/606 se toman de los 615/617 guardados en el período anterior.
  - **Uso**: cada casillero lleva a sus documentos. Se exporta a XLSX y PDF. Al marcarla como "Presentada" (número y fecha del formulario) queda una foto inmutable de los valores.
- **103**:
  - Se arma desde `RetencionDetalle` de renta autorizado.
  - Casillero de la base = `CodigoRetencion.casillero_103`; valor retenido = casillero + 50; totales 349/399, 498 y 499.
  - El mapa de códigos con letra a casilleros de 4 dígitos sale del Catálogo ATS.
- **ATS**:
  - Genera el XML según el **`ats.xsd` oficial**, guardado en el repo con su SHA-256 y fecha.
  - **Cabecera**: `numEstabRuc` desde `Establishment` y `totalVentas`.
  - **`compras`**: `Purchase`, `LiquidacionCompra` y compras desde XML, con `air` desde `Retencion` y `formasDePago`.
  - **`ventas`** y **`ventasEstablecimiento`**: solo lo que exija la ficha técnica.
  - **`anulados`**.
  - Se valida contra el XSD con lxml **antes** de descargar y se entrega `ATmmaaaa.zip` con un informe de advertencias (compras incompletas, proveedores sin tipo de identificación).
  - Las reglas de la ficha que no están confirmadas (ventas electrónicas en `ventasEstablecimiento`, anulados electrónicos, tope de `formasDePago`) se verifican en esta etapa contra la ficha y el DIMM 1.19.0.
- **`CodigoRetencion`**: añadir `vigente_desde`, `vigente_hasta` y `casillero_103`, y actualizar según el Catálogo ATS del 06/08/2026.
- **Tablero**: vencimientos del mes según el 9.º dígito (104, 103, ATS).

### 3.7 Estados financieros, cierre y 101 (en `core/contabilidad`)
- **Estados financieros en formato Supercias**, agregados por `codigo_supercias`:
  - estado de situación financiera;
  - estado de resultado integral;
  - flujo de efectivo indirecto (grupo 95–98);
  - cambios en el patrimonio (grupo 99).
  - Se entregan en XLSX para facilitar la carga anual.
- **Cierre del ejercicio**:
  - asiento de cierre de resultados;
  - asientos sugeridos del 15 % para los trabajadores y del impuesto a la renta;
  - asiento de apertura del ejercicio siguiente.
- **Conciliación tributaria de apoyo para el 101**:
  - utilidad − 15 % + no deducibles − exentas = base;
  - el impuesto se calcula sobre esa base;
  - se restan las retenciones recibidas del año y los anticipos.
  - El mapa de casilleros del 101 se edita desde la plataforma, porque su numeración actual no está confirmada.

### 3.8 Complemento "Contable" con precio aparte (decidido) — en `core/suscripciones`
- **Qué cubre**: `/bancos/`, `/contabilidad/` y `/tributario/` quedan bajo una regla nueva, `RUTAS_COMPLEMENTO_CONTABLE` (`core/suscripciones/reglas.py`), que comprueba `PlanMiddleware` (`core/suscripciones/middleware.py:263`), igual que hoy hace con `RUTAS_ILIMITADAS`.
- **Modelos**:
  - `Complemento` (plataforma): nombre, precio con IVA, duración y activo. Se edita en `/plataforma/`.
  - `ComplementoContratado` por empresa: período desde y hasta, pago y estado.
  - `EstadoPlan` gana `.contable`.
- **Cobro**: con PayPhone, reutilizando Prepare/Confirm con `Payment.mode='complemento'`. También hay activación manual auditada, como la de los planes.
- **Vencido**: solo consulta. Los datos contables se conservan (7 años) y se pueden exportar.
- **Proformas**: en todos los planes pagados (`RUTAS_DE_PAGO`), sin complemento.
- Se construye en la **Etapa 3**, porque Bancos es el primer módulo que lo necesita.

### 3.9 ADI y pago a cuenta (decidido) — en `core/contabilidad`
- **Accionistas y dividendos**:
  - Registro de accionistas: identificación, tipo, residencia fiscal y % de participación.
  - `DistribucionDividendos`: acta, ejercicio, monto y fecha.
  - La retención 326/327 (12 % o 14 %) se calcula para cada accionista.
  - Genera el asiento y el **Anexo de Dividendos (ADI)** según la ficha técnica vigente (v1.6.0). Se valida contra su XSD si lo hay; el plazo se confirma en la etapa.
- **Hoja del pago a cuenta sobre utilidades no distribuidas** (Res. NAC-DGERCGC26-00000026, código 1077 de contado o 1078 en tres cuotas):
  - Se calcula desde los estados financieros (utilidades acumuladas no distribuidas).
  - La fórmula exacta se confirma contra la resolución en la etapa.

## 4. Etapas (un solo plan; cada una cierra con: qué se hizo, pruebas, qué es simulado y qué es real, parches y publicación con autorización)

| # | Etapa | Tamaño | Depende de | Entrega |
|---|---|---|---|---|
| 0 | Análisis y plan | — | — | Este plan publicado como artefacto, más `entregas/facturaporaqui/PLAN-PROFORMAS-BANCOS-CONTABILIDAD.md` |
| 1 | Proformas | M | — | §3.1. Puede ir **en paralelo** con la 2 (archivos distintos) |
| 2 | Datos de origen | L | — | §3.2, más la actualización del catálogo de retenciones (D0) |
| 3 | Complemento "Contable" + Bancos y conciliación | L | 2 | §3.8 + §3.3 |
| 4 | Formularios SRI: 104, 103 y ATS | L | 2 | §3.6 |
| 5 | Núcleo contable | L | — | §3.4 |
| 6 | Contabilización automática y kardex | XL | 2, 3, 5 | §3.5, más el arranque contable de las empresas que lo activen |
| 7 | Estados financieros Supercias, cierre y 101 | M | 6 | §3.7 |
| 8 | ADI y pago a cuenta | S–M | 7 | §3.9 |

Orden **decidido**: **1 ∥ 2 → 3 → 4 → 5 → 6 → 7 → 8**. Nómina, RDEP y 107 quedan fuera de este proyecto. Codex lleva el diseño de cada pantalla mediante el contrato en `HANDOFF.md`, como hasta ahora.

## 5. Archivos críticos
- **Modificar**:
  - `core/pos/models.py` (Purchase, PurchaseDetail, Provider, Expenses, PaymentsCtaCollect, PaymentsDebtsPay, SaleDetail.costo);
  - `core/pos/views/{sale,purchase,ctas_collect}/views.py`;
  - `core/pos/static/sale/admin/js/form.js`;
  - `core/pos/emision.py` (gancho de contabilización);
  - `core/comprobantes/models.py` (`CodigoRetencion`);
  - `core/importacion/{xml_sri,servicios}.py`;
  - `core/security/menu.py`;
  - `core/security/management/commands/start_installation.py`;
  - `core/tenancy/{roles,checks,models}.py`;
  - `core/suscripciones/{reglas,models,servicios,middleware}.py` y el flujo de PayPhone existente (complemento);
  - `config/{settings,urls}.py`.
- **Apps nuevas**: `core/proformas`, `core/bancos`, `core/contabilidad`, `core/tributario`.
- **Reutilizar**:
  - `impuestos_por_tarifa`, `calcular_linea_iva` y `totales_de_lineas` (`core/pos/models.py:568-606`);
  - `propuesta_contable()` como base de la matriz (`core/importacion/servicios.py:582`);
  - `_correo_saliente()` (`core/pos/utilities/sri.py:87`);
  - `printer.create_pdf()` (`core/pos/utilities/printer.py:90`);
  - la migración RLS `comprobantes/0012`;
  - el patrón de subida e importación de `core/importacion`;
  - `tests/helpers.py`.

## 6. Verificación
- **Suites**: SQLite y PostgreSQL. La línea base es SQLite 548+7 y PG 555. Cada etapa añade sus pruebas, incluidas la RLS de cada tabla nueva, `test_rutas` y `test_estaticos`.
- **Proformas**:
  - el `SRIFalso` no recibe llamadas;
  - stock, cupo y `Receipt` quedan intactos;
  - facturar dos veces en concurrencia produce una sola venta (`test_zz_*` en PG).
- **Bancos**:
  - un archivo de muestra por banco;
  - duplicados descartados;
  - validación de saldos;
  - emparejamientos 1:1, 1:n, n:1 y ±días;
  - la ecuación del reporte;
  - el bloqueo tras el cierre.
- **Complemento**:
  - sin complemento, `/bancos/`, `/contabilidad/` y `/tributario/` quedan bloqueados;
  - vencido, solo consulta;
  - Prepare/Confirm con un PayPhone simulado y activación manual auditada.
- **Kardex**:
  - el promedio ponderado coincide con un ejemplo calculado a mano;
  - movimientos manuales y saldos iniciales;
  - `reconstruir_kardex` da el mismo resultado al repetirse;
  - una venta sin costo cae en la bandeja "Pendiente de costo".
- **ADI**: el XML valida contra su esquema oficial, si existe.
- **Contabilidad**:
  - todo asiento cuadra;
  - regenerar dos veces da lo mismo;
  - el balance de comprobación suma igual en debe y haber;
  - en los estados financieros, Activo = Pasivo + Patrimonio;
  - `verificar_cuadre` sin errores.
- **104 y 103**: un mes de ejemplo con los casilleros calculados a mano (de ser posible, revisado por un contador, D7), y comparación en solo lectura con el prellenado del SRI en un mes real.
- **ATS**: el XML valida contra el `ats.xsd` oficial con lxml, y la propietaria lo prueba en el DIMM ATS 1.19.0 con una empresa demo.
- **Migraciones con datos reales**: ensayo en una copia del volcado (patrón `verif-firma/staging_tarifas.sh`) antes de publicar. Volcado previo con `desplegar.sh`.
- **Navegador**: guiones de Playwright en `/root/capturas/` sobre DEMOSTRACIÓN, sin dejar residuos.

## 7. Decisiones
- **D0 (hallazgo urgente)**: comparar la tabla `CodigoRetencion` cargada (01/03/2026) con el Catálogo ATS del 06/08/2026 (cambios del 310 y 332E, Res. 26-00000028) y corregir. Propuesto: dentro de la Etapa 2, o antes como corrección suelta si hay diferencias.
**Decididas (28/10/2026)**
- **D1** Orden: Bancos primero (1 ∥ 2 → 3 → 4 → 5 → 6 → 7 → 8).
- **D2** Bancos, Contabilidad y Formularios van en un **complemento con precio aparte**. Las Proformas, en todos los planes pagados.
- **D3** Kardex con promedio ponderado: automático con datos completos y completable a mano.
- **D4** Alcance: estados financieros Supercias + 101, más ADI y pago a cuenta. Nómina, RDEP y 107 quedan fuera. REBEFICS también.

**Pendientes** (no bloquean las Etapas 1 y 2)
- **D9 Complemento**, antes de la Etapa 3:
  - precio anual con IVA;
  - si exige un plan base pagado (recomendado: sí);
  - si tiene período propio desde el pago (recomendado: sí, sin prorrateo, como D6 de los planes) o vence junto con el plan;
  - en Multiempresa, si se cobra por cada RUC (recomendado) o uno cubre todos.
- **D5** Plan de cuentas: plantilla Supercias con detalle PYME, editable por empresa (recomendado).
- **D6** Muestras **anonimizadas** de extractos de los bancos de los clientes (Pichincha, Guayaquil, Produbanco, Pacífico, Bolivariano, Internacional), colocadas por SSH en `/root/invoice15-subidas/`.
- **D7** ¿Hay un contador que valide la matriz de asientos y un 104/ATS real?
- **D8** Compras antiguas sin IVA: se marcan como incompletas, sin recalcular (recomendado).

## 8. Estado
- **Etapa 0 cerrada el 28/10/2026**: plan aprobado, documento vivo publicado, norma con fuentes en `NORMA-CONTABLE-TRIBUTARIA-2026-10.md` y nota para Codex en `HANDOFF.md`.
- Siguiente: Etapas 1 (Proformas) y 2 (Datos de origen), cuando la propietaria dé la orden. D9 hace falta antes de la Etapa 3.
- **30/10/2026:** Etapas 1 y 2 integradas en `plataforma` (`3549c16`) sin publicar. Añadidos los **comprobantes de pago adjuntos**
  (`core/adjuntos`, rama `fase/adjuntos-comprobantes`) a pedido de la propietaria; la Etapa 3 los usará para la conciliación.

## 9. Anexo — prompt para Codex (comercial de la landing + diseño gráfico de la app)

Texto que la propietaria pega a Codex:

```text
PROYECTO FACTURAPORAQUÍ — NUEVA FASE: PROFORMAS, BANCOS Y CONTABILIDAD
Tu papel en esta fase: la parte COMERCIAL de la landing y el DISEÑO GRÁFICO de la app. El backend lo hace Claude.

1) CONTEXTO
- Repo privado Jen456/invoice15. Ramas: `plataforma` (backend, Claude) y `frontend/etapa3` (la tuya). Antes de empezar: git fetch y fusiona `plataforma` en tu rama.
- Lee primero: entregas/facturaporaqui/AGENTS.md, entregas/facturaporaqui/HANDOFF.md (sección "Pendiente para Codex — fase contable") y entregas/facturaporaqui/PLAN-PROFORMAS-BANCOS-CONTABILIDAD.md.
- Orden aprobado de las etapas: 1 Proformas ∥ 2 Datos de origen → 3 Complemento «Contable» + Bancos y conciliación → 4 Formularios SRI (104, 103, ATS) → 5 Núcleo contable → 6 Asientos automáticos + kardex → 7 Estados financieros Supercias, cierre y 101 → 8 Anexo de dividendos (ADI) y pago a cuenta.
- Modelo comercial:
  · Proformas: incluidas en todos los planes pagados (Plan 1000 $50, Ilimitado $85, Multiempresa $199, IVA incluido; mejora de 1000 a Ilimitado por $35).
  · Bancos + Contabilidad + Formularios del SRI: un COMPLEMENTO «Contable» con precio aparte. El PRECIO AÚN NO ESTÁ DEFINIDO: no inventes cifras.

2) TAREA A — COMERCIAL Y LANDING (carpeta landing/)
a. Mensajes y estructura:
   · Sección «Proformas»: cotiza sin enviar al SRI, sin gastar comprobantes del plan, PDF y correo, y conviértela en factura con un clic.
   · Sección «Complemento Contable»: cuentas bancarias y caja, importación de estados de cuenta, conciliación bancaria, plan de cuentas NIIF en formato Supercias, asientos automáticos desde tus comprobantes, kardex, libros y balances, hoja del 104 y del 103, ATS en XML validado contra el esquema oficial, estados financieros, ADI.
   · Preguntas frecuentes, comparativa por plan y llamadas a la acción.
b. Tabla de precios: añade el complemento como tarjeta o fila con «Precio por anunciar». No toques los precios vigentes.
c. Etiquetas honestas: cada función marcada «Disponible» o «Próximamente».
   · Hoy disponible: facturas, notas de crédito, notas de débito, retenciones, liquidaciones de compra, guías de remisión, importación XML/RIDE (solo Ilimitado y Multiempresa).
   · Próximamente: proformas, bancos, contabilidad y formularios.
   · Usa el estado que indique HANDOFF.md en cada entrega.
d. Reglas legales del texto (obligatorias):
   · NO digas «homologado» ni «certificado por el SRI»: en Ecuador no existe homologación de software contable.
   · NO digas «declaramos por ti» ni «declaración automática». El sistema PREPARA la hoja del 104 y del 103 y GENERA el XML del ATS; el contribuyente presenta en SRI en Línea.
   · Sin logos del SRI, la Supercias ni los bancos.
e. Piezas para redes en entregas/facturaporaqui/redes/fase-contable/: lanzamiento de Proformas y adelanto del Complemento Contable, con el estilo colibrí.
f. SEO: title y description de las secciones nuevas; el schema.org SoftwareApplication solo con ofertas de los planes que tienen precio.
Todo esto es una PROPUESTA. La landing la publica Claude con publicar-landing.sh, solo con aprobación de la propietaria.

3) TAREA B — DISEÑO GRÁFICO DE LA APP
Primero maquetas estáticas (HTML+CSS con datos FICTICIOS) en entregas/facturaporaqui/propuestas/fase-contable/. Después, plantillas reales cuando Claude publique el contrato de cada pantalla en HANDOFF.md.
Orden:
 1. PROFORMAS (prioridad, Etapa 1):
    · Lista con estados: borrador, enviada, aceptada, rechazada, vencida, facturada, anulada.
    · Crear/editar basada en la pantalla de venta del POS, pero sin selector de comprobante ni efectivo/crédito.
    · Acciones: Duplicar, PDF, Enviar por correo y Facturar.
    · PDF A4 «PROFORMA — documento sin validez tributaria»: reutiliza templates/ride/_estilos.html y _pie.html, sin clave de acceso, sin número de autorización y sin código de barras.
 2. COMPLEMENTO CONTABLE: tarjeta de compra en /suscripcion/ y recuadro «Tu complemento» (vigente / vencido / no contratado).
 3. BANCOS Y CONCILIACIÓN (Etapa 3):
    · Cuentas (banco o caja).
    · Libro bancos con saldo corrido.
    · Registrar movimiento, cheque o transferencia.
    · Importar estado de cuenta: subida, vista previa con las columnas reconocidas y errores por fila.
    · Conciliación a dos columnas (extracto | libros) con sugerencias que se confirman con un clic, y totales con la diferencia siempre visibles.
    · Reporte de conciliación imprimible: saldo del banco + depósitos en tránsito − cheques no cobrados = saldo en libros.
 4. CONTABILIDAD Y TRIBUTARIO (etapas 4 a 8, por ahora SOLO maquetas):
    · Plan de cuentas en árbol.
    · Asiento con debe/haber y cuadre en vivo.
    · Libro diario, mayor y balance de comprobación.
    · Hoja del 104 por casilleros, con el detalle de documentos al hacer clic.
    · 103.
    · Generar el ATS con lista de advertencias.
    · Kardex por producto.
    · Estados financieros.
    · Calendario de vencimientos en el tablero.
Reglas de diseño:
 · Identidad colibrí: coral #CA462C, celeste #44BADD, #E5F1F6, azul #163B50.
 · AdminLTE 3.2 + Bootstrap 4.6, plantillas {% extends 'skin.html' %} y las clases fp-* que ya existen.
 · Móvil primero: revisa a 360, 768 y 1360 px. Contraste ≥ 4,5:1, foco visible, tablas responsive.
 · Solo librerías de licencia abierta, servidas desde static/lib y registradas en static/lib/MANIFIESTO.json. Nada de CDN en la app. Nada de Highcharts.
 · Imágenes optimizadas (PNG/WebP de menos de 150 KB).

4) LÍMITES (no negociables)
- No modifiques modelos, migraciones, vistas Python, core/suscripciones/reglas.py, core/pos/emision.py, la firma ni nada que hable con el SRI. Si una pantalla necesita un dato nuevo, pídelo en «Notas entre agentes» de HANDOFF.md.
- No despliegues ni publiques nada.
- No leas ni pidas credenciales, archivos .env ni firmas .p12.
- Usa siempre datos de ejemplo ficticios: nunca datos de clientes reales.

5) CADA ENTREGA
- Commits en frontend/etapa3, fusionando antes `plataforma`.
- Capturas en entregas/facturaporaqui/capturas/ (360, 768 y 1360 px).
- HANDOFF.md actualizado: qué hiciste, qué falta y qué necesitas del backend.
- Si tocaste plantillas o estáticos y tu entorno lo permite: pytest tests/test_estaticos.py tests/test_rutas.py.

ORDEN SUGERIDO DE TRABAJO
(1) Landing: mensajes, etiquetas Disponible/Próximamente y piezas de Proformas.
(2) Maquetas de Proformas y de su PDF.
(3) Tarjeta del Complemento.
(4) Maquetas de Bancos y conciliación.
(5) Resto de maquetas contables.
```
