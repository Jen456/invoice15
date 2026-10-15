# Importación de comprobantes electrónicos (XML / RIDE) — diseño del backend

Estado al 14/10/2026: implementado en `plataforma`, **sin publicar**. App `core/importacion`, migraciones `importacion 0001–0003` y `security 0003`.

## 1. Qué existía y qué se reutiliza

| Necesidad | Se reutiliza | Nuevo |
|---|---|---|
| Aislamiento por empresa | `TenantModel` (gestor que falla cerrado) y política RLS `fpa_empresa`; `request.company` por membresía | RLS en las 7 tablas nuevas (`importacion 0002`) |
| Contraparte | `pos.Provider` (por RUC exacto), `pos.Client` (por identificación exacta) | — (no se crean solos; «crear proveedor» es una acción de revisión) |
| Conciliación | `pos.Purchase` (proveedor + número + subtotal + fecha), `pos.Sale` (clave de acceso o número), `comprobantes.Retencion` (sustento = clave) | Candidatos y vínculos `compra` / `venta` |
| Consulta al SRI | `core/pos/emision.py`: `_cliente` (suds) y `URL_SRI` | `sri_autorizacion.consultar_autorizacion` |
| Permisos y menú | `GroupPermissionMixin`, `Module`/`ModuleType`, `sync_roles` | Campo `orden` y `core/security/menu.py` |
| Archivos | `MEDIA_ROOT` (fuera de la web; `/media/` exige sesión) | Carpeta `privado/` bloqueada en `/media/`; descarga propia con permiso |
| Cupo de emisión | — | **No se toca**: importar no consume cupo ni numeraciones |

## 2. Flujo y etapas (separadas)

1. **Importación** (`crear_lote`, `agregar_archivos`):
   - Cada archivo se guarda una vez por empresa (SHA-256) y tiene una entrada en el lote.
   - El tipo se detecta por el contenido.
   - Los XML se procesan al subirlos; los PDF quedan en cola.
2. **Validación** (`procesar_entrada`):
   - XML → `procesar_xml_sri`.
   - PDF → `procesar_ride_pdf` → clave → `consultar_autorizacion` → mismo procesador de XML.
3. **Verificación** (`verificar_en_sri`):
   - Compara emisor, receptor, fecha, número, base, IVA y total con el comprobante autorizado en el SRI.
   - Lo que el archivo declara (`declarada_en_archivo`) es distinto de lo verificado (`verificada_sri`).
4. **Clasificación** (`clasificar`), por coincidencia **exacta** con el RUC de la empresa activa, sin recortar identificaciones:
   - emitido: el emisor es la empresa;
   - recibido: el receptor es la empresa;
   - ajeno: ninguno de los dos;
   - revisión manual: ambos, o una discrepancia con el SRI.
5. **Revisión y vinculación** (`revisar`): aprobar, vincular a una compra o venta existente, clasificar a mano, crear el proveedor, descartar o reabrir. Nada se convierte automáticamente en compra, gasto o venta.
6. **Propuesta contable** (`propuesta_contable`):
   - Asiento revisable con las cuentas de «Reglas de importación y contabilización».
   - Siempre `contabilizado: false`, porque no hay libro mayor.

## 3. Seguridad

- **XML:**
  - Límite de tamaño.
  - Se rechaza cualquier `DOCTYPE`, `ENTITY`, `ELEMENT`, `ATTLIST` o `NOTATION`, antes y después de analizar.
  - lxml sin resolver entidades, sin red, sin DTD y con `huge_tree=False`.
  - Límites de elementos, profundidad y anidamiento del CDATA.
  - Solo UTF-8 o codificaciones compatibles con ASCII.
- **PDF:**
  - Cabecera `%PDF-`, tamaño y páginas limitados.
  - El análisis corre en un proceso aparte (`python -I trabajador_pdf.py`) con `RLIMIT_AS`, `RLIMIT_CPU`, sin poder escribir archivos (`RLIMIT_FSIZE=0`), con tiempo límite y resolución acotada.
  - No se visitan las URL del QR: solo se extrae la clave.
  - El texto incrustado se usa solo para buscar la clave. No hay OCR y el PDF nunca da importes.
- **Archivos:**
  - Se guardan en `privado/empresas/<uuid>/importados/…`, ruta que `/media/` no entrega.
  - Se descargan por `/importacion/archivos/<id>/descargar/`, que exige la empresa activa y el permiso `view_documentoimportado`, con `no-store`, `nosniff` y CSP sandbox.
- **Empresa:** la decide el servidor. Un id de otra empresa responde 404 y la seguridad por filas lo respalda en PostgreSQL.

## 4. Esquema (PostgreSQL, explicativo)

```sql
-- Todas las tablas: company_id NOT NULL REFERENCES pos_company + RLS fpa_empresa
-- (app.platform = 'on' OR company_id = app.company_id).

CREATE TABLE importacion_loteimportacion (
  id bigserial PRIMARY KEY, company_id int NOT NULL, usuario_id int NOT NULL,
  estado varchar(20),            -- procesando | terminado | con_errores
  total_archivos int, creado timestamptz, terminado timestamptz NULL);

CREATE TABLE importacion_archivoimportado (          -- el contenido, una sola vez por empresa
  id bigserial PRIMARY KEY, company_id int NOT NULL, sha256 char(64), tipo varchar(4),  -- xml | pdf
  origen varchar(10),            -- subido | sri
  tamano int, nombre_original varchar(255), archivo varchar(255),   -- privado/empresas/<uuid>/importados/...
  subido_por_id int, creado timestamptz,
  CONSTRAINT archivo_importado_unico_por_empresa UNIQUE (company_id, sha256));

CREATE TABLE importacion_documentoimportado (        -- el comprobante, uno por clave
  id bigserial PRIMARY KEY, company_id int NOT NULL, lote_id bigint NULL, importado_por_id int,
  origen varchar(10),            -- xml | pdf | sri | manual
  archivo_xml_id bigint NULL, archivo_pdf_id bigint NULL,
  clave_acceso char(49), cod_doc char(2), version varchar(10), ambiente smallint,
  estab char(3), pto_emi char(3), secuencial char(9), numero varchar(17), fecha_emision date,
  numero_autorizacion varchar(49), fecha_autorizacion timestamptz,
  emisor_ruc varchar(13), emisor_razon_social varchar(300), emisor_nombre_comercial varchar(300),
  receptor_tipo_identificacion char(2), receptor_identificacion varchar(20), receptor_razon_social varchar(300),
  moneda varchar(15),
  total_sin_impuestos numeric(16,2), total_descuento numeric(16,2), propina numeric(16,2),
  total_iva numeric(16,2), total_ice numeric(16,2), total_irbpnr numeric(16,2), importe_total numeric(16,2),
  estado_procesamiento varchar(20),  -- pendiente_xml | procesado
  estado_verificacion varchar(25),   -- sin_autorizacion | declarada_en_archivo | verificada_sri | discrepancia_sri
                                     -- | no_autorizada_sri | no_encontrada_sri | sri_no_disponible
  verificado_en timestamptz,
  clasificacion varchar(20),         -- pendiente | emitido | recibido | ajeno | revision_manual
  estado_revision varchar(15),       -- pendiente | aprobado | vinculado | descartado
  estado_contable varchar(15),       -- sin_propuesta | propuesta   (nunca «contabilizado»)
  proveedor_id int NULL, cliente_id int NULL, compra_id int NULL, venta_id int NULL,
  datos jsonb,                       -- resultado completo del análisis (importes como texto)
  advertencias jsonb, errores jsonb, propuesta_contable jsonb NULL,
  revisado_por_id int NULL, revisado_en timestamptz NULL, nota_revision varchar(300),
  creado timestamptz, actualizado timestamptz,
  CONSTRAINT documento_importado_unico UNIQUE (company_id, ambiente, clave_acceso));
-- índices: (company_id, estado_revision), (company_id, clasificacion), (company_id, emisor_ruc)

CREATE TABLE importacion_impuestoimportado (         -- desglose original, sin reinterpretar
  id bigserial PRIMARY KEY, company_id int NOT NULL, documento_id bigint NOT NULL ON DELETE CASCADE,
  codigo varchar(2), codigo_porcentaje varchar(4), impuesto varchar(20),
  categoria varchar(20),         -- iva_tarifa | iva_0 | iva_exento | iva_no_objeto | iva_diferenciado | ice | irbpnr | otro
  tarifa numeric(5,2) NULL, base_imponible numeric(16,2), valor numeric(16,2),
  descuento_adicional numeric(16,2), valor_devolucion_iva numeric(16,2) NULL);

CREATE TABLE importacion_entradalote (               -- cada archivo de un lote y su resultado
  id bigserial PRIMARY KEY, company_id int NOT NULL, lote_id bigint NOT NULL ON DELETE CASCADE,
  archivo_id bigint NULL, nombre varchar(255), tamano int, tipo varchar(12), orden int,
  estado varchar(20),            -- en_cola | procesando | procesado | duplicado | pendiente_xml | pendiente_clave | rechazado
  documento_id bigint NULL, errores jsonb, advertencias jsonb, candidatas jsonb,
  intentos smallint, procesado_en timestamptz NULL);

CREATE TABLE importacion_eventoimportacion (         -- bitácora de cada paso
  id bigserial PRIMARY KEY, company_id int NOT NULL, documento_id bigint NULL, lote_id bigint NULL,
  entrada_id bigint NULL, tipo varchar(30), mensaje varchar(500), datos jsonb, usuario_id int NULL, creado timestamptz);

CREATE TABLE importacion_reglaimportacion (          -- una por empresa
  id bigserial PRIMARY KEY, company_id int NOT NULL UNIQUE,
  verificar_con_sri bool, exigir_verificacion bool,
  naturaleza_compra varchar(15),  -- gasto | inventario | activo_fijo
  tratamiento_iva varchar(20),    -- credito_tributario | costo_gasto
  cuenta_gasto, cuenta_inventario, cuenta_activo_fijo, cuenta_iva_compras, cuenta_proveedores,
  cuenta_retencion_renta, cuenta_retencion_iva, cuenta_ventas, cuenta_iva_ventas, cuenta_clientes varchar(30),
  actualizado timestamptz, actualizado_por_id int NULL);
```

**Idempotencia y concurrencia:**
- El mismo contenido choca con `archivo_importado_unico_por_empresa` y la misma clave con `documento_importado_unico`. Quien pierde la carrera atrapa `IntegrityError` dentro de un punto de guardado y reutiliza lo que guardó el otro.
- Dos procesamientos del mismo lote toman entradas distintas (`SELECT … FOR UPDATE SKIP LOCKED`).
- Probado con hilos reales en PostgreSQL (`tests/test_zzz_importacion_concurrencia_pg.py`).

## 5. Procesador de XML (`procesar_xml_sri`)

- **Envolturas:**
  - `<autorizacion>`;
  - `<RespuestaAutorizacionComprobante>` con una o varias autorizaciones; varias distintas son ambiguas;
  - el sobre SOAP;
  - el comprobante solo, sin autorización.
- **Forma del comprobante:** en CDATA, como texto escapado (también escapado dos veces) o como elemento hijo. Los espacios de nombres se ignoran.
- **Estado:** solo AUTORIZADO se acepta como autorizado (declarado). NO AUTORIZADO se rechaza.
- **Tipos:** factura 01. Los demás devuelven `tipo_no_soportado` y no se interpretan.
- **Clave:**
  - 49 dígitos, dígito verificador módulo 11 y fecha real.
  - Debe coincidir con la fecha, el tipo, el RUC, el ambiente, el establecimiento, el punto, el secuencial y el tipo de emisión.
  - El número de autorización de 49 dígitos debe ser la clave.
- **Impuestos:**
  - Se conserva cada `(código, código de porcentaje)`. La tarifa sale del XML o, si falta, de la tabla 17 (0, 12, 13, 14, 15, 5 %, exento, no objeto, diferenciado).
  - Se calculan las bases agregadas por categoría y tarifa.
- **Advertencias de conciliación:**
  - IVA ≠ base × tarifa;
  - bases ≠ total sin impuestos;
  - total ≠ bases + impuestos + propina − compensaciones;
  - pagos ≠ total;
  - líneas ≠ total sin impuestos.
- **Montos y receptor:**
  - Todo importe es `Decimal` y en JSON viaja como texto.
  - El receptor puede tener RUC, cédula, pasaporte, identificación del exterior o ser consumidor final; solo se advierte si el formato no corresponde al tipo.

## 6. Límites (`core/importacion/limites.py`)

| Límite | Valor |
|---|---|
| XML | 2 MB |
| PDF | 5 MB y 5 páginas |
| Archivos por lote | 50 |
| Lote completo | 60 MB |
| Por petición | 9 MB (nginx admite 10 MB; el lote se sube por partes) |
| Elementos XML | 50 000 |
| Profundidad XML | 40 |
| Anidamientos de comprobante | 2 |
| Render del PDF | 200 dpi, tope de ~9,4 Mpx por página |
| Trabajador del PDF | 20 s de reloj, 15 s de CPU, 768 MB de memoria virtual |
| Consulta al SRI | 15 s por intento y 2 reintentos (solo si no responde) |
| Procesamiento por petición | 3 entradas |

## 7. Pendiente y decisiones

- **Tipos:** notas de crédito, notas de débito, retenciones recibidas, guías y liquidaciones importadas devuelven «tipo no soportado».
- **Crear la compra desde el XML** (líneas → productos e inventario): no está; hoy se aprueba como documento recibido o se vincula a una compra existente. Requiere decidir el emparejamiento de productos.
- **Libro mayor:** no existe. La propuesta contable es revisable y no se contabiliza.
- **Decisión comercial (propietaria, 15/10/2026):** la importación está incluida **solo en los planes Ilimitado y Multiempresa**, también para la empresa cubierta por un Multiempresa, y no consume cupo.
  - `core/suscripciones/reglas.py`: `RUTAS_ILIMITADAS` y `requiere_ilimitado`. `EstadoPlan.ilimitado` toma el período vigente o, si venció, el último.
  - Con Plan 1000 o el gratuito, el menú muestra el candado y la ruta redirige a Plan y pagos (la API responde 403 `{"plan": "ilimitado"}`).
  - Con un Ilimitado vencido se consulta, pero no se importa.
  - Plan y pagos muestra el beneficio en las tarjetas de Ilimitado y Multiempresa.
- **Al publicar:**
  - instalar `facturaporaqui-importacion@.{service,timer}` con `instalar-servicio.sh --aplicar`;
  - instalar las dependencias nuevas `pypdfium2` y `zxing-cpp`, que entran en `requirements/base.txt` con hashes;
  - aplicar las migraciones, que reorganizan el menú de todas las empresas.
- No se probó con documentos reales; todas las pruebas usan comprobantes ficticios.
