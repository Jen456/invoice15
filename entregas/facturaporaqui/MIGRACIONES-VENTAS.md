# Migraciones — Etapa 2, ventas y empresa (rama O2)

28/10/2026 · Escrito desde el código de la rama `fase/etapa2-ventas` en `6114e14`, fusionada en `plataforma` en `fff9bb3` junto con las demás ramas de la fase contable (orden y estado en `HANDOFF.md`). Al integrar, `pos/0030` pasó a depender de `pos/0024_permiso_completar_compras` (Compras) y `comprobantes/0020` de `comprobantes/0015_vigencias_res_28` (D0), en lugar de `pos/0019` y `comprobantes/0013`; nada más cambió.

**En una frase:** son seis migraciones (pos 0030–0031 y comprobantes 0020–0023). Agregan columnas y dos tablas nuevas, permisos y un módulo del menú. **No cambian ni recalculan ningún dato de negocio existente:** las filas antiguas reciben valores «vacíos» o una marca explícita de «anterior a la regla».

---

## Resumen

| Orden | Migración | Qué hace | Toca datos existentes | Reversible |
|---|---|---|---|---|
| 1 | `pos/0030_cxc_abonos_anulados_empresa` | Columnas nuevas en empresa, factura, nota de crédito y abonos; dos índices | Solo agrega columnas con valor por defecto (marca «no_aplica» en las NC) | Sí, automática |
| 2 | `comprobantes/0020_anulado_sri_y_cxc_nota_debito` | Marca de anulado en retención, liquidación, ND y guía; CxC propia de la ND | Solo agrega columnas (marca «no_aplica» en las ND) | Sí, automática |
| 3 | `comprobantes/0021_retencion_recibida` | Dos tablas nuevas: retenciones recibidas y su detalle | No (tablas nuevas) | Sí, automática |
| 4 | `comprobantes/0022_seguridad_por_filas_retencion_recibida` | Seguridad por filas (RLS) de esas dos tablas, solo en PostgreSQL | No | Sí |
| 5 | `pos/0031_permisos_anulado_sri` | Permisos «Anulado en el SRI» de factura y NC en sus módulos; roles | Solo tablas de seguridad (módulos y roles) | Sí |
| 6 | `comprobantes/0023_modulo_retenciones_recibidas` | Módulo «Retenciones recibidas» en el menú y permisos de anulado de los cuatro comprobantes; roles | Solo tablas de seguridad | Sí |

`migrate` las aplica en un orden compatible con sus dependencias. Hacia atrás se deshacen primero las de comprobantes (dependen de pos 0030) y después las de pos.

**Ninguna tiene `RunPython` sobre datos de negocio.** Las dos con `RunPython` de seguridad (pos 0031 y comprobantes 0023) solo tocan permisos, módulos y roles, y la 0022 solo crea la política de seguridad por filas.

---

## 1. `pos/0030_cxc_abonos_anulados_empresa`

**Dependencias:** `('pos', '0019_orden_de_las_lineas')` y el modelo de usuario (`AUTH_USER_MODEL`).

**Operaciones** (21 AddField, 1 AlterField, 2 AlterModelOptions y 2 AddIndex)
- **AlterModelOptions** de `sale` y `creditnote`: añaden los permisos `change_anulado_sri_sale` («Puede marcar facturas como anuladas en el SRI») y `change_anulado_sri_creditnote` («Puede marcar notas de crédito como anuladas en el SRI»). Las opciones repiten los permisos que ya tenían.
- **`company`** (2 columnas): `tipo_contribuyente` (texto de 20) y `periodicidad_iva` (texto de 10), con valor por defecto `''`.
- **`sale`** (5 columnas, la marca «Anulado en el SRI»): `anulado_sri_fecha` (fecha, nula), `anulado_sri_motivo` (texto de 300, `''`), `anulado_sri_por` (usuario, nulo, `SET_NULL`), `anulado_sri_registrado_en` (fecha y hora, nula) y `anulado_sri_stock` (booleano, `False`).
- **`creditnote`** (7 columnas):
  - las mismas cinco de anulado;
  - `abono_cxc` (uno a uno con el abono, nulo, `PROTECT`);
  - `cxc_ajuste` (texto de 12). Se agrega con valor por defecto `'no_aplica'`, que rellena las filas existentes, y enseguida un **AlterField** deja `'pendiente'` como valor por defecto de las nuevas.
- **`paymentsctacollect`** (abonos, 7 columnas): `tipo` (`'cobro'`), `medio_pago` (`''`), `referencia` (`''`), `registrado_por` (nulo), `registrado_en` (nulo), `anulado_en` (nulo) y `anulado_motivo` (`''`).
- **AddIndex** `venta_emision` (`company`, `emission_date`) en `pos_sale` y `nc_emision` (`company`, `emission_date`) en `pos_creditnote`, para los reportes por fecha de emisión.

**Reversible:** sí, automáticamente. Al revertir se quitan las columnas, los índices y los permisos de las opciones del modelo.
- **Ojo:** revertir después de usar la versión nueva pierde información. Desaparecen las marcas de anulado, el medio y la referencia de los cobros nuevos y, sobre todo, el **tipo** y la **anulación** de los abonos. Los abonos automáticos (de NC, de retenciones y de anulación) quedarían como cobros comunes, y los que estaban anulados volverían a restar del saldo con el código anterior.
- Si ya se usó en producción, lo seguro es restaurar el respaldo tomado antes de publicar, no revertir.
- Para revertirla hay que revertir antes comprobantes 0020–0023 y pos 0031.

**Efecto sobre los registros existentes en producción**

| Tabla | Qué reciben las filas que ya existen | Cómo se ve |
|---|---|---|
| `pos_company` | `tipo_contribuyente = ''`, `periodicidad_iva = ''` | **Dato incompleto marcado:** «Sin indicar» y el aviso «Completa el tipo de contribuyente y la declaración del IVA…» en Empresa. La sugerencia no se guarda sola |
| `pos_sale` | Marca de anulado vacía (`NULL`, `''`, `False`) | Sin cambio. `emission_date` **no se toca**: las ventas antiguas que no lo tienen siguen así y los reportes marcan con «*» la fecha tomada de la autorización o del registro |
| `pos_creditnote` | `cxc_ajuste = 'no_aplica'`, `abono_cxc` nulo, marca vacía | **Marcadas como anteriores a la regla:** «Anterior a la regla: no ajusta la cuenta por cobrar». No se crea ningún abono ni se muestra «saldo a favor» |
| `pos_paymentsctacollect` | `tipo = 'cobro'`, `medio_pago = ''`, `referencia = ''`, registro y anulación vacíos | **Dato incompleto marcado:** el medio de pago se muestra «Sin dato» (no se inventa). Valor, fecha y descripción, intactos |
| `pos_ctascollect` | Ninguna columna nueva | Deuda, saldo y estado **intactos** |

**Confirmación de que nada se recalcula:**
- no se crean abonos por las NC antiguas;
- no cambian saldos ni estados de las cuentas por cobrar;
- no se rellena `emission_date`;
- no se tocan estados, XML ni RIDE.

Lo comprueba `tests/test_migracion_datos_origen_ventas.py`: carga «ventas de antes» con los modelos de pos 0019 (una factura sin `emission_date`, su cuenta por cobrar con un cobro, una NC y una ND autorizadas), migra y verifica que la cuenta conserva deuda 23,00 y saldo 13,00 aunque haya una NC de 5,00. Luego revierte, vuelve a migrar y verifica lo mismo.

**Seguridad por filas (RLS):** `pos_sale`, `pos_creditnote` y `pos_paymentsctacollect` ya tienen la política `fpa_empresa` (tenancy 0002). Las columnas nuevas quedan cubiertas por la política de la fila, sin cambios. `pos_company` no es una tabla por empresa y no tiene RLS.
- **Detalle importante:** el relleno de `'no_aplica'` y de los demás valores lo hace el propio `ALTER TABLE … ADD COLUMN … DEFAULT` (una orden de estructura), no un `UPDATE`. Por eso la RLS forzada no oculta filas y **todas las empresas** reciben el valor, aunque la migración corra sin `app.platform`.

**Costo esperado con el volumen real** (no se midió contra la base de producción, que esta rama no toca)
- El volumen es pequeño. La única empresa real factura en FacturaPorAquí desde el 13/10/2026; las demás son de demostración y de pruebas. Son decenas o pocos cientos de filas por tabla.
- En PostgreSQL 16 (el de la VM), agregar una columna nula o con valor por defecto constante solo cambia el catálogo y no reescribe la tabla. Django la agrega con `DEFAULT` y luego quita el `DEFAULT` de la base; las dos órdenes son de catálogo. El AlterField de `cxc_ajuste` solo cambia el valor por defecto de Django, que no vive en la base.
- Las claves foráneas nuevas (`anulado_sri_por`, `registrado_por`, `abono_cxc`) crean su restricción y su índice. `abono_cxc` es único. Los dos AddIndex crean índices normales (no `CONCURRENTLY`).
- Con este volumen, cada índice tarda milisegundos. La migración entera debería tardar segundos como mucho.
- Bloqueos: los `ALTER TABLE` toman un bloqueo exclusivo breve sobre `pos_company`, `pos_sale`, `pos_creditnote` y `pos_paymentsctacollect` hasta que termina la transacción de la migración. Conviene aplicarla en la ventana habitual del despliegue, con el servicio y el temporizador de consultas al SRI detenidos o sin tráfico.

---

## 2. `comprobantes/0020_anulado_sri_y_cxc_nota_debito`

**Dependencias:** `('comprobantes', '0013_modulo_guias')`, `('pos', '0030_cxc_abonos_anulados_empresa')` y el modelo de usuario.

**Operaciones** (18 AddField, 1 AlterField y 4 AlterModelOptions)
- **AlterModelOptions** de `retencion`, `liquidacioncompra`, `notadebito` y `guiaremision`: añaden `change_anulado_sri_retencion`, `change_anulado_sri_liquidacioncompra`, `change_anulado_sri_notadebito` y `change_anulado_sri_guiaremision` («Puede marcar … como anuladas en el SRI»).
- **AddField** de los cuatro campos de anulado (`anulado_sri_fecha`, `anulado_sri_motivo`, `anulado_sri_por`, `anulado_sri_registrado_en`; sin `anulado_sri_stock`) en los cuatro modelos: 16 columnas.
- **`notadebito.cuenta_por_cobrar`**: uno a uno con `pos.CtasCollect`, nulo, `PROTECT`.
- **`notadebito.cxc_ajuste`**: AddField con `'no_aplica'` (rellena las existentes) y AlterField a `'pendiente'` para las nuevas.

**Reversible:** sí, automáticamente: quita las columnas y los permisos de las opciones.
- Revertir después de usarla pierde las marcas de anulado y el enlace de cada ND con su cuenta por cobrar. Esas cuentas seguirían en `pos_ctascollect` y el código anterior las vería como una segunda cuenta de la factura.
- Si ya hay datos nuevos, restaurar el respaldo.

**Efecto sobre los registros existentes**
- Retenciones emitidas, liquidaciones, ND y guías existentes: marca de anulado vacía.
- ND existentes: `cxc_ajuste = 'no_aplica'` (**marca de anterior a la regla**) y **ninguna cuenta por cobrar creada**.

Nada se recalcula. Las ND anteriores pueden regularizarse con la orden `regularizar_cxc_historico` (ensayo por defecto; `--aplicar` exige `--decision` de la propietaria; no se ejecuta en esta fase).

**Seguridad por filas:** las cuatro tablas ya tienen la política `fpa_empresa` (comprobantes 0002, 0006, 0009 y 0012); las columnas nuevas quedan cubiertas. El relleno es por `DEFAULT`, sin `UPDATE`, igual que en pos 0030.

**Costo:** igual que pos 0030: columnas de catálogo y dos índices (la clave foránea de `anulado_sri_por` en cada tabla y la única de `cuenta_por_cobrar`), sobre tablas de decenas de filas. Segundos como mucho.

---

## 3. `comprobantes/0021_retencion_recibida`

**Dependencias:** `('comprobantes', '0020_anulado_sri_y_cxc_nota_debito')`, `('importacion', '0004_menu_con_guias')`, `('pos', '0030_cxc_abonos_anulados_empresa')` y el modelo de usuario.

**Operaciones**
- **CreateModel `RetencionRecibida`** (por empresa). Columnas principales:
  - la factura sustento (`venta`, `PROTECT`) y el cliente (`PROTECT`);
  - el agente de retención (RUC y razón social);
  - número, establecimiento, punto y secuencial;
  - autorización y clave de acceso, fecha de emisión, período fiscal y ambiente;
  - datos del documento sustento;
  - totales de renta, IVA y total;
  - origen (`manual` / `importado`) y `documento_importado` (`PROTECT`);
  - verificación, estado (`registrada` / `anulada`) y estado en la CxC;
  - el abono (uno a uno, `PROTECT`), advertencias (JSON), notas, quién registró y cuándo, y los campos de anulación.
- **CreateModel `RetencionRecibidaDetalle`** (por empresa): impuesto, código, concepto, base, porcentaje y valor retenido, con borrado en cascada desde la retención.
- **AddIndex** `retrec_fecha` (`company`, `fecha_emision`) y `retrec_venta` (`company`, `venta`).
- **AddConstraint:**
  - `retencion_recibida_unica`: única por empresa, agente, establecimiento, punto, secuencial y venta, mientras esté registrada;
  - `retencion_recibida_clave_unica`: única por empresa, clave de acceso y venta, si la clave no está vacía;
  - `retencion_recibida_documento_unica`: única por empresa, documento importado y venta, si hay documento. Da la idempotencia del 07 importado;
  - `retencion_recibida_totales_no_negativos` (CHECK);
  - `retencion_recibida_detalle_valido` (CHECK: base > 0, porcentaje de 0 a 100, valor ≥ 0).

Las tres de unicidad son condicionales (`estado='registrada'`): una retención anulada se puede registrar de nuevo.

**Reversible:** sí, automáticamente (borra las dos tablas).
- Si ya se registraron retenciones, revertir las pierde. Sus abonos (tipo `retencion`) quedarían en `pos_paymentsctacollect` sin su documento.
- Con datos, restaurar el respaldo.

**Efecto sobre los registros existentes:** ninguno; son tablas nuevas y vacías.

**Seguridad por filas:** la pone la migración siguiente (0022). En un `migrate` normal las dos corren seguidas; si se detuviera entre ambas, las tablas existirían un momento sin RLS, vacías.

**Costo:** crear dos tablas vacías con sus índices y restricciones: instantáneo.

---

## 4. `comprobantes/0022_seguridad_por_filas_retencion_recibida`

**Dependencias:** `('comprobantes', '0021_retencion_recibida')`.

**Operación:** `RunPython`, solo en PostgreSQL (en SQLite no hace nada). Para `comprobantes_retencionrecibida` y `comprobantes_retencionrecibidadetalle`:
- `ENABLE ROW LEVEL SECURITY` y `FORCE ROW LEVEL SECURITY`;
- `CREATE POLICY fpa_empresa … USING (…) WITH CHECK (…)`, con la misma condición de comprobantes 0002, 0006, 0009 y 0012: `current_setting('app.platform', true) = 'on' OR company_id = NULLIF(current_setting('app.company_id', true), '')::integer`.

**Reversible:** sí. Hacia atrás: `DROP POLICY IF EXISTS fpa_empresa`, `NO FORCE` y `DISABLE ROW LEVEL SECURITY`.

**Efecto sobre los registros existentes:** ninguno.

**Seguridad por filas:** es justamente esta migración.
- Cada empresa solo ve sus retenciones recibidas y sus detalles.
- Las pruebas de RLS de `tests/test_retenciones_recibidas.py` lo comprueban en PostgreSQL.
- El respaldo con `pg_dump` ya usa `PGOPTIONS='-c app.platform=on' --enable-row-security` (`deploy/scripts/desplegar.sh` y `deploy/scripts/respaldo-diario.sh`), así que las tablas nuevas entran en el respaldo.

**Costo:** cambios de catálogo, instantáneos.

---

## 5. `pos/0031_permisos_anulado_sri`

**Dependencias:** `('pos', '0030_cxc_abonos_anulados_empresa')`, `('security', '0003_orden_menu')`, `('auth', '0012_alter_user_first_name_max_length')` y `('contenttypes', '0002_remove_content_type_name')`.

**Operación:** `RunPython(forwards, backwards)`, con el patrón de comprobantes 0013.
- **forwards:**
  1. Crea los permisos de pos que falten (`create_permissions`; normalmente se crean al final de todas las migraciones).
  2. Si la tabla de módulos está vacía (base sin instalar), termina: lo hará `start_installation`.
  3. Si no, agrega `change_anulado_sri_sale` al módulo `/pos/sale/admin/` y `change_anulado_sri_creditnote` a `/pos/credit/note/admin/`.
  4. Ejecuta `sync_roles`.
- **backwards:** quita esos dos permisos de los módulos y ejecuta `sync_roles`. Las filas de `Permission` se dejan.

**Reversible:** sí.

**Efecto sobre los registros existentes**
- Solo tablas de seguridad: los permisos de los módulos, `GroupModule` y los permisos de los seis roles.
- Los permisos nuevos empiezan con `change_`, así que `sync_roles` los da solo a **Propietario y Administrador**; Contador, Vendedor y Consulta no los reciben.
- **Efecto lateral conocido:** `sync_roles` vuelve a dejar los seis roles con su configuración estándar. Si alguien cambió a mano los permisos de un rol de empresa, se normaliza. Es el mismo comportamiento de las migraciones de menú anteriores (por ejemplo, comprobantes 0013).
- Ningún dato de negocio cambia.

**Seguridad por filas:** las tablas de seguridad y de permisos no son por empresa; no aplica.

**Costo:** decenas de filas de permisos; milisegundos.

---

## 6. `comprobantes/0023_modulo_retenciones_recibidas`

**Dependencias:** `('comprobantes', '0022_seguridad_por_filas_retencion_recibida')`, `('security', '0003_orden_menu')`, `('importacion', '0004_menu_con_guias')`, `('auth', '0012_alter_user_first_name_max_length')`, `('contenttypes', '0002_remove_content_type_name')` y `('pos', '0031_permisos_anulado_sri')`.

**Operación:** `RunPython(forwards, backwards)`.
- **forwards:**
  1. Crea los permisos de comprobantes que falten: `view_retencionrecibida`, `add_retencionrecibida`, `change_retencionrecibida` y los cuatro `change_anulado_sri_*`.
  2. Si no hay módulos, termina: lo hará `start_installation`.
  3. Agrega cada `change_anulado_sri_<modelo>` a su módulo: `/comprobantes/retenciones/`, `/comprobantes/liquidaciones/`, `/comprobantes/notas-debito/` y `/comprobantes/guias/`.
  4. Llama a `organizar_menu` (la versión generalizada de B0). Crea el módulo `/comprobantes/retenciones-recibidas/` («Retenciones recibidas», icono `fas fa-hand-holding-usd`, con los tres permisos de la retención recibida) desde `MODULOS_NUEVOS` y lo coloca en «Administrativo», orden 3, desde `ESTRUCTURA`. **No crea el módulo a mano.**
  5. Ejecuta `sync_roles`.
- **backwards:**
  1. Borra el módulo `/comprobantes/retenciones-recibidas/` (sus `GroupModule` caen en cascada).
  2. Quita los cuatro permisos de anulado de sus módulos.
  3. Ejecuta `sync_roles`.
  - Las filas de `Permission` se dejan.

**Reversible:** sí.

**Efecto sobre los registros existentes**
- Solo menú y roles:
  - Propietario y Administrador reciben el módulo con todos sus permisos y los de anulado.
  - Contador (por `ACCOUNTANT_URLS` de B0) y Consulta lo reciben en solo lectura.
  - Vendedor no lo recibe.
- `organizar_menu` vuelve a aplicar nombres y orden de la `ESTRUCTURA` a los módulos que ya figuran en ella. Es idempotente: repetirla no duplica nada. Si el menú se había cambiado a mano, se normaliza.
- `sync_roles` tiene el mismo efecto lateral que en pos 0031.
- Ningún dato de negocio cambia.

**Seguridad por filas:** no aplica (tablas de seguridad).

**Costo:** milisegundos.

**Pruebas:** `tests/test_migracion_menu_ventas.py` (3 pruebas, en SQLite y en PostgreSQL). Ejecuta las funciones de pos 0031 y comprobantes 0023 con los modelos históricos hacia adelante y hacia atrás: el resto del menú queda igual, repetir no duplica y en una base sin módulos no se crea nada. También comprueba los permisos de cada rol.

---

## 7. Cómo se probaron

- **`tests/test_migracion_datos_origen_ventas.py`** (SQLite en un archivo temporal, por subproceso):
  - datos «de antes» con los modelos de pos 0019 y comprobantes 0013;
  - migrar → verificar que nada cambió → revertir a comprobantes 0013 y pos 0019 → migrar otra vez → verificar.
- **`tests/test_migracion_menu_ventas.py`**: menú y permisos, en los dos motores.
- **Suites completas en `6114e14`:** SQLite 888 aprobadas + 20 omitidas; PostgreSQL 908 aprobadas. La base de pruebas de PostgreSQL 16 se crea aplicando todas las migraciones, también estas seis.
- **`manage.py check`** y **`makemigrations --check --dry-run`** (settings de pruebas), repetidos al escribir este documento: «System check identified no issues (0 silenced).» y «No changes detected».
- **No probado:** la reversa completa del esquema en PostgreSQL (la reversa de esquema se probó en SQLite y la de menú en los dos). No se ejecutó nada contra la base de producción ni la de pruebas del servicio.

---

## 8. Notas de integración

1. **Re-encadenar dependencias** (lo hace el integrador; O2 no fusiona `plataforma`):
   - `pos 0030` pasará a depender de `('pos', '0024_permiso_completar_compras')` de O1. El hueco 0025–0029 se deja a propósito.
   - `comprobantes 0020` pasará a depender de la última de D0 (según `espec-d0-fase-a.md`, `('comprobantes', '0015_vigencias_res_28')`; D0 tiene reservadas 0014–0019). Si D0 entra después de O2, D0 renumera las suyas a 0024 o más y las hace depender de `comprobantes 0023`.
   - Tras cada fusión: un solo nodo hoja por app y `makemigrations --check --dry-run` sin cambios, en SQLite y en PostgreSQL.
2. **AlterModelOptions:**
   - pos 0030 escribe la lista completa de permisos de `Sale` y `CreditNote`;
   - comprobantes 0020, la de `Retencion`, `LiquidacionCompra`, `NotaDebito` y `GuiaRemision`.
   - Si otra rama cambió el `Meta` de alguno de esos modelos, la última migración tiene que llevar la unión de los dos; si no, `makemigrations --check` lo detectará.
3. **Menú:** `MODULOS_NUEVOS` y `ESTRUCTURA` ya traen la entrada de O2. P y O1 añaden las suyas en sus regiones.
   - O2 cambió dos aserciones de `tests/test_b0_contratos.py`, porque ahora hay una entrada nueva y el módulo existe tras instalar. A P le pasará lo mismo con su tupla.
   - Revisar el orden final de «Administrativo».
4. **tenancy 0007** (integrador): las choices de `AuditLog.ACTIONS` para los cinco códigos de O2 (`comprobante_anulado_sri`, `retencion_recibida_registro`, `retencion_recibida_anulacion`, `cxc_cobro_eliminado`, `regularizacion_datos_origen`) y `encoder=DjangoJSONEncoder` en `AuditLog.detail`. O2 no creó migraciones de tenancy y guarda solo tipos JSON. `company_change` ya existía.
5. **Prueba de punta a punta del 07 importado** (integrador): O1 implementa `core/importacion/recibidos.py` (`retencion_recibida_de`, `marcar_incorporado` idempotente y `desmarcar_incorporado`) y su pantalla; O2 registra y anula contra esas firmas.
   - En esta rama siguen con `NotImplementedError` y las pruebas de O2 las sustituyen con `monkeypatch`.
   - Anular una retención **importada** llama a `desmarcar_incorporado`; no puede ocurrir hasta que O1 esté integrado.
6. **Catálogo de retenciones (D0):** cuando D0 programe las vigencias, `codigo_retencion_vigente` y `codigos_retencion_vigentes` llamarán a `CodigoRetencion.vigente`. Las migraciones de O2 no tocan `CodigoRetencion`.
7. **Despliegue** (cuando se autorice; nada de esto se ejecutó):
   - Tomar el respaldo `pg_dump` antes de migrar. Es el camino de vuelta si ya hay datos nuevos.
   - Las migraciones no rellenan nada histórico.
   - Las NC y ND **creadas antes** de publicar quedan en `no_aplica`, aunque el SRI las autorice después, y no ajustan la cuenta por cobrar. Las que se creen después nacen en `pendiente` y se ajustan al autorizarse.
   - Si un receptor falla, la NC o ND queda en `pendiente` hasta correr `aplicar_ajustes_cxc --aplicar`. El integrador puede sumarla al temporizador de `consultar_sri` cuando se autorice desplegar.
8. **Órdenes de regularización** (no son migraciones; ensayo por defecto; no se ejecutan en esta fase):
   - `regularizar_cxc_historico --empresa RUC`: NC y ND en `no_aplica`. `--aplicar` exige `--decision`; las filas «revisar» solo con `--incluir-revisar`. Audita `regularizacion_datos_origen`.
   - `completar_fecha_emision --empresa RUC`: `emission_date` desde el XML autorizado, nunca sobrescribe. `--aplicar` exige `--decision`. Audita `regularizacion_datos_origen`.
   - `aplicar_ajustes_cxc [--empresa RUC]`: solo las `pendiente`. `--aplicar` sin decisión, porque aplica la regla que ya debió aplicarse.

   Las tres cumplen las condiciones de la propietaria: se conservan los registros, lo incompleto queda marcado y nada histórico se recalcula sin una decisión y un procedimiento revisable.
