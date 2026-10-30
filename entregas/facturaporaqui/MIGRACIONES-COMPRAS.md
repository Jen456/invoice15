# Migraciones — Etapa 2, compras (rama O1)

28/10/2026 · Escrito desde el código de la rama `fase/etapa2-compras` en `f0f6fbd`, fusionada en `plataforma` en `eaa6d10` junto con las demás ramas de la fase contable (orden y estado en `HANDOFF.md`).

**En una frase:** son siete migraciones (pos 0020–0024 e importacion 0005–0006). Agregan columnas, una tabla nueva con su seguridad por filas y un permiso. **No cambian ni recalculan ningún dato de negocio existente:** las compras, líneas, cuentas por pagar, pagos, gastos y proveedores que ya existen reciben valores «vacíos» (`''` o `NULL`) o una marca explícita de «datos incompletos», sin inventar impuestos.

---

## Resumen

| Orden | Migración | Qué hace | Toca datos existentes | Reversible |
|---|---|---|---|---|
| 1 | `pos/0020_proveedor_datos_ats` | Proveedor: identificación de hasta 20 caracteres, tipo de identificación, tipo de sujeto y parte relacionada | Solo agrega columnas vacías y alarga una | Sí; en PostgreSQL falla si ya hay identificaciones de más de 13 caracteres |
| 2 | `pos/0021_compra_datos_ats` | Compra: datos del comprobante (ATS), documento modificado, 11 importes, marca de datos incompletos, origen, unicidad del comprobante, índices y permiso `change_purchase` | Solo agrega columnas (importes `NULL`, marca «incompleta») | Sí; falla si ya hay compras nuevas con el mismo número |
| 3 | `pos/0022_detalle_compra_tarifa` | Línea de compra: líneas de gasto (sin producto), tarifa e IVA por línea | Solo agrega columnas vacías | Sí; falla si ya hay líneas sin producto |
| 4 | `pos/0023_pagos_y_gastos` | Cuenta por pagar con base de cálculo; pagos y gastos con medio de pago y referencia; tipo de gasto con cuenta contable y sustento | Solo agrega columnas (base «subtotal», medio de pago vacío) | Sí, automática |
| 5 | `pos/0024_permiso_completar_compras` | Permiso «Completar datos» en el módulo Compras y reparto a los roles | Solo tablas de seguridad | Sí (la reversa no hace nada) |
| 6 | `importacion/0005_equivalencia_producto` | Tabla nueva de equivalencias «código del proveedor → producto» | No (tabla nueva) | Sí, automática |
| 7 | `importacion/0006_seguridad_por_filas_equivalencia` | Seguridad por filas (RLS) de esa tabla, solo en PostgreSQL | No | Sí |

`migrate` las aplica en un orden compatible con sus dependencias (la 6 necesita la 3). Hacia atrás, Django deshace primero pos 0024 y 0023, luego importacion 0006 y 0005 y al final pos 0022, 0021 y 0020; así ocurrió en el ensayo de reversa del apartado 8.

**Ninguna tiene `RunPython` sobre datos de empresa.** La pos 0024 solo toca permisos, módulos y roles, y la importacion 0006 solo crea la política de seguridad por filas. El marcado de las compras existentes lo hacen los valores por defecto de `AddField`, que fallan cerrados: `version_datos=1`, `datos_incompletos=True`, `DebtsPay.base_calculo='subtotal'`.

No hay migraciones de `tenancy`, `comprobantes`, `security` ni `proformas` en esta rama.

---

## 1. `pos/0020_proveedor_datos_ats`

**Dependencias:** `('pos', '0019_orden_de_las_lineas')`.

**Operaciones** (3 AddField y 1 AlterField, en `pos_provider`)
- `tipo_identificacion`: texto de 2, opciones `04` RUC, `05` cédula, `06` pasaporte, `08` identificación del exterior; valor por defecto `''`.
- `tipo_sujeto`: texto de 2, `01` persona natural o `02` sociedad; `''`.
- `parte_relacionada`: booleano nulo; `NULL` = sin indicar.
- **AlterField** `ruc`: de 13 a 20 caracteres, con la etiqueta «Identificación» (para pasaportes e identificaciones del exterior). El nombre de la columna no cambia.

**Reversible:** sí. Al revertir se quitan las tres columnas y `ruc` vuelve a 13 caracteres.
- En PostgreSQL, volver a 13 **falla** si algún proveedor ya tiene una identificación más larga (un pasaporte o una identificación del exterior registrados con la versión nueva). En SQLite no falla, porque SQLite no impone el largo.
- Revertir pierde el tipo de identificación, el tipo de sujeto y la parte relacionada que se hayan llenado.

**Efecto sobre los registros existentes en producción**

| Qué reciben los proveedores existentes | Cómo se ven |
|---|---|
| `tipo_identificacion = ''`, `tipo_sujeto = ''`, `parte_relacionada = NULL`; nombre, RUC, celular, correo y dirección intactos | **Dato incompleto marcado:** insignia «Datos incompletos» con «Falta el tipo de identificación» e «Indica si es parte relacionada». Sus compras también cuentan ese faltante |

**Nada se recalcula ni se infiere.** El tipo de identificación deducible de un RUC o una cédula válidos lo propone la orden `proveedores_incompletos`, que es de ensayo por defecto y **no se ejecuta en esta fase** (apartado 9). La parte relacionada no la sugiere nada: la elige la empresa.

**Seguridad por filas:** `pos_provider` ya tiene la política `fpa_empresa` (tenancy 0002). Las columnas nuevas quedan cubiertas por la política de la fila. El relleno lo hace el propio `ALTER TABLE … ADD COLUMN … DEFAULT` (una orden de estructura, no un `UPDATE`): la RLS forzada no oculta filas y todas las empresas reciben el valor aunque la migración corra sin `app.platform`.

**Costo esperado:** en PostgreSQL 16, agregar una columna nula o con valor constante y alargar un `varchar` solo cambian el catálogo; no reescriben la tabla ni reconstruyen el índice único `(company, ruc)`. Es instantáneo con cualquier volumen; toma un bloqueo exclusivo breve sobre `pos_provider`.

---

## 2. `pos/0021_compra_datos_ats`

**Dependencias:** `('pos', '0020_proveedor_datos_ats')` y el modelo de usuario (`AUTH_USER_MODEL`).

**Operaciones** (en `pos_purchase`: 1 AlterModelOptions, 1 RemoveConstraint, 32 AddField, 1 AlterField, 2 AddIndex y 4 AddConstraint)
- **AlterModelOptions:** permisos del modelo con el nuevo `change_purchase` («Can change Compra»: completar los datos del comprobante).
- **RemoveConstraint** `purchase_number_por_empresa` (unicidad de `company` + `number`).
- **AddField** (32 columnas):
  - comprobante del proveedor: `tipo_comprobante`, `cod_sustento`, `estab`, `pto_emi`, `secuencial`, `autorizacion` (texto, `''`), `fecha_emision` (fecha, nula), `forma_pago` (Tabla 13, `''`), `parte_relacionada` (booleano nulo), `pago_loc_ext` (`''`);
  - documento modificado: `tipo_doc_modificado`, `num_doc_modificado`, `aut_doc_modificado` (`''`), `fecha_doc_modificado` (nula) y `compra_modificada` (clave a otra compra, nula, `PROTECT`, `related_name='ajustes'`);
  - importes: `base_0`, `base_gravada`, `base_5`, `base_no_objeto`, `base_exenta`, `total_descuento`, `total_iva`, `total_ice`, `total_irbpnr`, `propina` y `total` (decimal 12,2, **nulos**);
  - estado: `version_datos` (1), `datos_incompletos` (`True`), `fuera_plazo_ats` (`False`), `origen` (`'manual'`), `completada_en` (nula) y `completada_por` (usuario, nulo, `SET_NULL`). Las dos últimas llevan `editable=False`.
- **AlterField** `number`: de 8 a 20 caracteres, opcional, valor por defecto `''` (en las compras nuevas guarda `EEE-PPP-SSSSSSSSS`).
- **AddIndex** `compra_incompleta` (`company`, `datos_incompletos`) y `compra_fecha_emision` (`company`, `fecha_emision`).
- **AddConstraint:**
  - `compra_comprobante_unico_por_proveedor`: único (`company`, `provider`, `tipo_comprobante`, `estab`, `pto_emi`, `secuencial`) **solo cuando `secuencial` no está vacío** (índice único parcial);
  - `compra_total_no_negativo`: `total` nulo o ≥ 0;
  - `compra_completa_con_totales`: una compra sin `total` no puede figurar como completa;
  - `compra_v2_con_totales`: una compra con impuestos por línea (`version_datos=2`) siempre tiene `total`.

**Reversible:** sí. Al revertir se quitan las columnas, los índices y las restricciones, y se vuelve a crear `purchase_number_por_empresa`.
- **Falla** si ya hay dos compras con el mismo `number` en una empresa. Con la versión nueva eso pasa enseguida: las compras «Completar después» y las de liquidación guardan `number = ''`, y dos proveedores distintos pueden tener el mismo `001-001-000000001`.
- Revertir pierde todos los datos del comprobante, los importes y las marcas que se hayan registrado.
- El permiso `change_purchase` no se borra de la tabla de permisos (Django no borra permisos al revertir); el código anterior no lo usa.

**Efecto sobre los registros existentes en producción**

| Qué reciben las compras existentes | Cómo se ven |
|---|---|
| `version_datos = 1`, `datos_incompletos = True`, `fuera_plazo_ats = False`, `origen = 'manual'`; cabecera del comprobante vacía; los 11 importes `NULL` (no 0) | **Marcadas como datos incompletos:** insignia «Compra anterior · sin IVA», IVA y total «—», y el faltante «Faltan los importes de la factura (bases, IVA y total)» |
| `number`, `subtotal`, `provider`, `payment_type`, `date_joined`, `end_credit` y `created_at` | **Intactos.** El número antiguo se sigue mostrando (`numero_comprobante` lo usa si no hay secuencial) |

- Las compras existentes tienen `secuencial = ''`, así que **no entran** en la unicidad nueva; una compra antigua entra recién cuando alguien completa su número en «Completar datos» (un choque da el mensaje «Ya registraste … (compra #N).»).
- Las tres `CheckConstraint` se cumplen en todas las filas existentes (total nulo, incompletas y versión 1): la migración no falla por datos.
- Al quitar `purchase_number_por_empresa`, dos compras antiguas con el mismo número ya no chocan. Para no duplicar, «Nueva compra» y «Crear compra desde el XML» avisan `posible_duplicado` cuando hay una compra anterior del mismo proveedor con el mismo número.

**Confirmación de que nada se recalcula:** no se calcula IVA, no se reparten bases, no se llena el número, no cambia `subtotal` ni la fecha. Completar una compra anterior es una decisión explícita en «Completar datos» (auditada `purchase_complete`) o, desde el XML vinculado, la orden `compras_incompletas`, que es de ensayo por defecto y **no se ejecuta en esta fase**.

**Seguridad por filas:** `pos_purchase` ya tiene `fpa_empresa` (tenancy 0002); las columnas nuevas quedan cubiertas. Los valores por defecto se aplican con la orden de estructura, no con `UPDATE`: llegan a todas las empresas.

**Costo esperado**
- Las 32 columnas son nulas o de valor constante: en PostgreSQL 16 solo cambian el catálogo. Alargar `number` de `varchar(8)` a `varchar(20)` tampoco reescribe la tabla.
- Lo que sí recorre la tabla una vez: las dos claves foráneas nuevas (`compra_modificada`, `completada_por`) validan su restricción y crean su índice; los dos AddIndex y el índice único parcial se crean de forma normal (no `CONCURRENTLY`); cada `CHECK` revisa las filas existentes.
- Es lineal en el número de compras: milisegundos con miles de filas.
- Bloqueo exclusivo sobre `pos_purchase` hasta que termina la transacción de la migración.

---

## 3. `pos/0022_detalle_compra_tarifa`

**Dependencias:** `('pos', '0021_compra_datos_ats')`.

**Operaciones** (en `pos_purchasedetail`: 1 AlterModelOptions, 9 AddField, 1 AlterField y 1 AddConstraint)
- **AlterModelOptions:** `ordering = ('id',)`.
- **AddField:** `type_expense` (tipo de gasto, nulo, `PROTECT`), `descripcion` (300, `''`), `codigo_proveedor` (25, `''`), `codigo_porcentaje` (2, `''`), `tarifa` (decimal 5,2, nula), `total_dscto` (decimal 9,2, `0`), `total` (decimal 12,2, nulo), `total_iva` (decimal 12,2, nulo), `total_ice` (decimal 12,2, `0`).
- **AlterField** `product`: pasa a nulo (línea de gasto sin producto).
- **AddConstraint** `detalle_compra_producto_o_descripcion`: una línea tiene producto o descripción.

**Reversible:** sí. Al revertir se quitan las columnas y la restricción, y `product` vuelve a ser obligatorio.
- **Falla** si ya hay líneas sin producto (líneas de gasto, notas de crédito o débito del proveedor, compras creadas desde un XML como gasto).
- Revertir pierde la tarifa, el IVA y la descripción de las líneas nuevas.

**Efecto sobre los registros existentes en producción**

| Qué reciben las líneas existentes | Cómo se ven |
|---|---|
| `codigo_porcentaje = ''`, `tarifa`, `total` y `total_iva` `NULL`, `total_dscto = 0`, `total_ice = 0`, `descripcion = ''`, `type_expense` nulo; producto, cantidad, precio y subtotal intactos | **Sin tarifa registrada:** tarifa «—»; en el resumen por tarifa salen como «Sin tarifa registrada» con IVA desconocido |

`total_dscto = 0` no inventa nada: el descuento anterior (`dscto`) nunca se usó y vale 0 en todas las líneas. **No se toca el stock** ni se recalcula ninguna línea.

**Seguridad por filas:** `pos_purchasedetail` ya tiene `fpa_empresa`. Mismo comportamiento de los valores por defecto.

**Costo esperado:** columnas de catálogo; `DROP NOT NULL` es de catálogo; la clave de `type_expense` crea su índice y la `CHECK` recorre las líneas una vez (todas tienen producto, así que se cumple). Lineal y pequeño; bloqueo exclusivo breve sobre `pos_purchasedetail`.

---

## 4. `pos/0023_pagos_y_gastos`

**Dependencias:** `('pos', '0022_detalle_compra_tarifa')` y el modelo de usuario.

**Operaciones** (1 AlterModelOptions y 9 AddField)
- **AlterModelOptions** de `paymentsdebtspay`: `ordering = ('id',)`.
- `pos_debtspay`: `base_calculo` (texto de 10, `subtotal` | `total`, valor por defecto `'subtotal'`).
- `pos_paymentsdebtspay`: `medio_pago` (15, `MEDIOS_DE_PAGO`, `''`), `referencia` (100, `''`), `registrado_por` (usuario, nulo, `SET_NULL`, `editable=False`) y `registrado_en` (fecha y hora, nula, `editable=False`).
- `pos_expenses`: `medio_pago` (15, `''`) y `referencia` (100, `''`).
- `pos_typeexpense`: `cuenta_contable` (30, `''`) y `cod_sustento` (Tabla 5, `''`).

**Reversible:** sí, automáticamente. Al revertir se quitan las columnas.
- **Ojo:** revertir después de usar la versión nueva pierde la base de cálculo. Si luego se vuelve a migrar, **todas** las cuentas quedarían con `'subtotal'` y las de compras nuevas perderían sus abonos automáticos (retenciones y notas de crédito). También se pierden medio de pago, referencia y quién registró cada pago.
- Si ya se usó en producción, lo seguro es restaurar el respaldo tomado antes de publicar, no revertir.

**Efecto sobre los registros existentes en producción**

| Tabla | Qué reciben las filas que ya existen | Cómo se ve |
|---|---|---|
| `pos_debtspay` | `base_calculo = 'subtotal'`; `debt`, `saldo` y `state` **intactos** | Insignia «Calculada sin IVA». **No reciben abonos automáticos:** su saldo solo cambia por sus pagos, igual que antes (deuda − pagos) |
| `pos_paymentsdebtspay` | `medio_pago = ''`, `referencia = ''`, `registrado_por` y `registrado_en` nulos | **Dato incompleto marcado:** «Sin dato» en el medio de pago. Valor, fecha y descripción intactos |
| `pos_expenses` | `medio_pago = ''`, `referencia = ''` | «Sin dato» |
| `pos_typeexpense` | `cuenta_contable = ''`, `cod_sustento = ''` | «Sin indicar». Nada se elige de oficio (decisión P2): con `02` de oficio el IVA iría al casillero sin crédito |

**Confirmación de que nada se recalcula:** ninguna deuda ni saldo cambia. Pasar una cuenta antigua al total con IVA solo ocurre con la casilla «Ajustar la cuenta por pagar al total con IVA» de «Completar datos», auditada `purchase_debt_adjust`; la orden `compras_incompletas` nunca lo hace.

**Seguridad por filas:** las cuatro tablas ya tienen `fpa_empresa`. Mismo comportamiento de los valores por defecto.

**Costo esperado:** nueve columnas de catálogo; la clave de `registrado_por` valida su restricción (todo nulo) y crea su índice. Instantáneo con este volumen; bloqueos exclusivos breves sobre las cuatro tablas.

---

## 5. `pos/0024_permiso_completar_compras`

**Dependencias:** `('pos', '0023_pagos_y_gastos')`, `('security', '0003_orden_menu')`, `('auth', '0012_alter_user_first_name_max_length')` y `('contenttypes', '0002_remove_content_type_name')`.

**Operaciones:** un `RunPython` (patrón de `comprobantes/0013_modulo_guias.py`):
1. crea los permisos del modelo `purchase` que falten (aquí aparece `change_purchase` en las instalaciones existentes);
2. si existe el módulo con URL `/pos/purchase/`, le añade `change_purchase`;
3. vuelve a sincronizar los seis roles con `sync_roles`: el permiso llega solo a los roles con escritura (Propietario y Administrador), no a Contador, Consulta ni Vendedor.

Las instalaciones nuevas lo reciben de `start_installation`, que asigna al módulo Compras todos los permisos del modelo `purchase` (ese archivo no se tocó).

**Reversible:** sí; la reversa no hace nada (`noop`). El permiso queda en el módulo y en los roles, sin efecto para el código anterior.

**Efecto sobre los registros existentes:** solo tablas de seguridad globales: `auth_permission`, los permisos del módulo «Compras» y los permisos y módulos de los seis roles plantilla. **No toca datos de empresa.** Como toda migración que llama a `sync_roles`, devuelve los roles plantilla a su definición de `core/tenancy/roles.py`: un cambio manual en esos grupos se sobrescribe (igual que en las migraciones anteriores de menú).

**Seguridad por filas:** esas tablas no son por empresa y no tienen RLS; corre igual sin `app.platform`.

**Costo esperado:** unas decenas de filas de seguridad; instantáneo.

---

## 6. `importacion/0005_equivalencia_producto`

**Dependencias:** `('importacion', '0004_menu_con_guias')`, `('pos', '0022_detalle_compra_tarifa')` y el modelo de usuario.

**Operaciones:** **CreateModel** `EquivalenciaProducto` (tabla `importacion_equivalenciaproducto`): `company` (empresa, `PROTECT`, `editable=False`), `proveedor` (`CASCADE`), `codigo_proveedor` (25), `producto` (`CASCADE`), `creado_por` (usuario, nulo, `SET_NULL`), `creado` y `actualizado`; único (`company`, `proveedor`, `codigo_proveedor`) con el nombre `equivalencia_producto_unica`; orden (`proveedor`, `codigo_proveedor`); sin permisos por defecto.

Solo se escribe una fila cuando el usuario marca «Recordar» en una línea de «Crear compra desde el XML» (decisión DC8).

**Reversible:** sí, automáticamente: se borra la tabla y con ella las equivalencias guardadas.

**Efecto sobre los registros existentes:** ninguno (tabla nueva y vacía).

**Seguridad por filas:** la tabla nueva **no** está en `TENANT_MODELS_FOR_RLS` de `pos` (es de `importacion`); su política la crea la 0006.

**Costo esperado:** crear una tabla vacía con sus índices; instantáneo.

---

## 7. `importacion/0006_seguridad_por_filas_equivalencia`

**Dependencias:** `('importacion', '0005_equivalencia_producto')`.

**Operaciones:** `RunPython`, solo en PostgreSQL (en SQLite no hace nada):
- `ALTER TABLE importacion_equivalenciaproducto ENABLE ROW LEVEL SECURITY` y `FORCE ROW LEVEL SECURITY`;
- `CREATE POLICY fpa_empresa … USING (…) WITH CHECK (…)` con la misma condición que las demás tablas: `app.platform = 'on'` o `company_id = app.company_id`.

**Reversible:** sí: `DROP POLICY IF EXISTS fpa_empresa`, `NO FORCE` y `DISABLE ROW LEVEL SECURITY`.

**Efecto sobre los registros existentes:** ninguno.

**Prueba:** `tests/test_rls_compras.py` (solo PostgreSQL) comprueba que la política está activa y forzada, que una consulta sin filtro solo ve la empresa fijada y que no se puede insertar una fila de otra empresa.

**Costo esperado:** órdenes de catálogo; instantáneo.

---

## 8. Cómo se probaron

- **`tests/test_migracion_compras.py`:**
  - `test_compras_anteriores_migran_sin_cambios_y_marcadas`: en un subproceso con una base SQLite en archivo, migra hasta `pos 0019`, carga «compras de antes» (dos compras, una a crédito con un pago de 40,00 sobre una deuda de 100,00, líneas con producto, un gasto, un tipo de gasto y un proveedor), migra hasta el final y verifica: las compras con `version_datos=1`, incompletas, `fuera_plazo_ats=False`, origen manual, cabecera vacía y los 11 importes `NULL`; las líneas sin tarifa; la deuda con 100,00 y saldo 60,00 intactos y base `subtotal`; el pago y el gasto con medio de pago vacío; el tipo de gasto con sustento vacío; el proveedor sin tipo ni parte relacionada, y el stock sin cambios.
  - `test_0024_devuelve_completar_datos_al_modulo_y_a_los_roles_con_escritura`: quita `change_purchase` del módulo y de los grupos, ejecuta la migración y comprueba que vuelve al módulo y solo a Propietario y Administrador.
- **Suites completas sobre `f0f6fbd`:** SQLite **871 aprobadas y 22 omitidas** (las omitidas son las exclusivas de PostgreSQL) y PostgreSQL **893 aprobadas, 0 fallidas**. Línea base de `f36d3b2`: 595 + 9 y 604.
- **`makemigrations --check --dry-run`:** «No changes detected».
- **Ensayo de reversa (28/10/2026, para este documento):** en una base SQLite **vacía** y temporal, `migrate` completo, `migrate pos 0019_orden_de_las_lineas` (deshizo, en este orden, pos 0024, pos 0023, importacion 0006, importacion 0005, pos 0022, pos 0021 y pos 0020) y otra vez `migrate` completo: todo correcto.
- **Lo que no se probó:** la reversa en PostgreSQL ni con datos nuevos (donde 0020, 0021 y 0022 fallan a propósito, como se explica arriba) y la migración sobre una copia del volcado de producción. Las dos cosas quedan para el integrador y para el ensayo previo a publicar (apartado 10).

---

## 9. Órdenes de gestión relacionadas (no son migraciones)

Las dos son **de ensayo por defecto** y **no se ejecutan contra datos reales en esta fase**.
- `python manage.py proveedores_incompletos [--empresa ID | --todas] [--aplicar --decision TEXTO --csv RUTA]`: lista los proveedores con datos del ATS incompletos. Con `--aplicar` llena solo el tipo de identificación y el tipo de sujeto de los RUC y cédulas válidos; nunca la parte relacionada ni el número. Auditoría `provider_type_fill` por empresa.
- `python manage.py compras_incompletas [--empresa ID | --todas] [--desde-xml] [--aplicar --decision TEXTO --csv RUTA]`: informe de compras incompletas. Con `--desde-xml --aplicar` completa solo la cabecera vacía e importes desde el XML vinculado y verificado cuando la diferencia con el subtotal es de hasta 0,02; un dato distinto ya registrado se informa como «conflicto» y esa compra no se toca. Nunca cambia líneas, stock ni cuentas por pagar. Auditoría `purchase_complete` con la decisión y la ruta del informe.
- `--aplicar` exige `--empresa` o `--todas`, `--decision` (al menos 10 caracteres, con el motivo y quién lo autorizó) y `--csv`; `compras_incompletas` exige además `--desde-xml`. El CSV antepone un apóstrofo a las celdas que empiezan como fórmula.

---

## 10. Notas de integración

1. **Orden de fusión:** B0 → D0 → P → **O1** → O2 → X. O1 se fusiona antes que O2.
2. **Re-encadenar O2:** las migraciones `pos 0030+` de O2 (hoy dependen de `pos 0019`) pasarán a depender de `('pos', '0024_permiso_completar_compras')`, la última de O1. El hueco 0025–0029 se deja a propósito. Así `pos` queda con un solo nodo hoja.
3. **Sin cruces con las demás ramas:**
   - P (proformas) no tiene migraciones de `pos` ni de `importacion`; sus dependencias (`pos 0019`, `importacion 0004`) ya están en `f36d3b2`.
   - D0 usa `comprobantes 0014–0019`; O1 no tiene migraciones de `comprobantes`.
   - `importacion` 0005–0006 son las únicas de esa app en las ramas de esta fase.
4. **Tenancy 0007 (integrador):** sumar a las `choices` de `AuditLog.ACTIONS` los 6 códigos de O1: `purchase_complete`, `purchase_debt_adjust`, `purchase_delete`, `debt_payment_delete`, `debt_delete` y `provider_type_fill`. O1 los guarda como texto y convierte los importes y fechas a texto antes de auditar.
5. **Prueba de punta a punta del 07 (integrador, commit X):** O1 lee el 07 importado y ofrece la pantalla; O2 registra con `registrar_desde_importacion`. La prueba con un 07 v2.0.0 de dos sustentos la hace el integrador tras fusionar O1 y O2; `tests/fabricas_recibidos.py` ya permite armarla.
6. **Tras cada fusión:** un solo nodo hoja por app; `makemigrations --check --dry-run` sin cambios en SQLite y PostgreSQL; `migrate` desde base vacía y desde el estado de `f36d3b2` con datos ficticios; reversa probada de lo declarado reversible.
7. **Antes de publicar (no en esta fase):** migrar una copia del volcado de producción y comparar conteos de compras, líneas, cuentas por pagar y pagos, más la suma de `subtotal`, `debt` y `saldo`, antes y después (deben ser iguales). Aplicar en la ventana de despliegue, con el servicio y el temporizador de consultas al SRI detenidos o sin tráfico, porque cada `ALTER TABLE` toma un bloqueo exclusivo breve.
8. **Volumen real:** no se midió; esta rama no consulta la base de producción. Todas las operaciones que dependen del número de filas (índices, claves foráneas y `CHECK`) son lineales y de un solo recorrido. El conteo de filas de `pos_purchase`, `pos_purchasedetail`, `pos_debtspay`, `pos_paymentsdebtspay` y `pos_provider` se obtiene en el ensayo del punto 7.
