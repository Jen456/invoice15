# Migraciones — Etapa 1, Proformas (rama P)

29/10/2026 · Escrito desde el código de la rama `fase/etapa1-proformas` en `3f91e75`, fusionada en `plataforma` en `7f0e576` junto con las demás ramas de la fase contable (orden y estado en `HANDOFF.md`).

**En una frase:** son tres migraciones, todas de la app nueva `proformas` (0001–0003). Crean tres tablas vacías, su seguridad por filas, los permisos y el módulo del menú. **No tocan ni recalculan ningún dato de negocio existente** (ventas, clientes, productos, comprobantes, cuentas por cobrar): solo crean tablas nuevas y actualizan las tablas de seguridad del menú y de los roles.

---

## Resumen

| Orden | Migración | Qué hace | Toca datos existentes | Reversible |
|---|---|---|---|---|
| 1 | `proformas/0001_inicial` | Tablas de proformas, líneas y contador, con sus restricciones e índices | No: tablas nuevas y vacías | Sí, automática (borra las tablas) |
| 2 | `proformas/0002_seguridad_por_filas` | Seguridad por filas (RLS) de las tres tablas, solo en PostgreSQL | No | Sí |
| 3 | `proformas/0003_modulo_proformas` | Permisos de proformas, grupo «Cotizaciones» y módulo «Proformas» del menú; roles | Solo tablas de seguridad (menú, permisos y roles) | Sí |

- **Ninguna de las tres tiene `RunPython` sobre datos de negocio.** La 0002 solo crea la política de seguridad por filas. La 0003 solo trabaja con permisos, módulos y roles.
- **No hay migraciones fuera de `proformas`:** ni `pos`, ni `comprobantes`, ni `importacion`, ni `security`, ni `tenancy`. Las choices de los 8 códigos de auditoría las pone el integrador en su migración única de `tenancy`.
- **No hay datos previos de proformas.** El contador de cada empresa se crea la primera vez que esa empresa guarda una proforma; la migración no crea filas para las empresas existentes.

---

## 1. `proformas/0001_inicial`

**Dependencias:** `('pos', '0019_orden_de_las_lineas')` y el modelo de usuario (`AUTH_USER_MODEL` = `user.User`).

**Operaciones** (generada con `makemigrations`: 3 CreateModel, 2 AddIndex y 8 AddConstraint)
- **CreateModel `Proforma`** (`proformas_proforma`):
  - número propio (`numero` y `numero_completo`, `PRO-000001`);
  - cliente opcional (`cliente` → `pos.Client`, `SET_NULL`) más la copia de sus datos (`cliente_nombre`, `cliente_identificacion`, `cliente_correo`, `cliente_telefono`, `cliente_direccion`);
  - `fecha`, `valida_hasta`, `condiciones` y `forma_pago_sugerida` (choices `PAYMENT_METHOD`);
  - importes `subtotal_gravado`, `subtotal_cero`, `total_descuento`, `total_iva` y `total` (`DecimalField(9, 2)`);
  - `estado` (borrador, enviada, aceptada, rechazada, facturada, anulada);
  - `venta` (`OneToOneField` → `pos.Sale`, `SET_NULL`): la factura que salió de la proforma;
  - `origen` (→ la proforma de la que se duplicó, `SET_NULL`), `motivo`, `enviada_a` y `envios`;
  - fechas de cada paso (`creada_en`, `actualizada_en`, `enviada_en`, `aceptada_en`, `rechazada_en`, `anulada_en`, `facturada_en`);
  - usuarios `vendedor`, `creada_por` y `facturada_por` (`SET_NULL`);
  - `company` (→ `pos.Company`, `PROTECT`), como todo `TenantModel`;
  - los cuatro permisos propios `view_proforma`, `add_proforma`, `change_proforma` y `delete_proforma`, sin los permisos por defecto de Django.
- **CreateModel `ProformaDetalle`** (`proformas_proformadetalle`): `proforma` (`CASCADE`), `product` (→ `pos.Product`, `SET_NULL`) con la copia de `codigo` y `descripcion`, y los mismos nombres de campo que la línea de venta: `cant`, `price`, `dscto` (fracción), `codigo_porcentaje`, `iva`, `price_with_vat`, `subtotal`, `total_dscto`, `total` y `total_iva`. También lleva `company` (`PROTECT`).
- **CreateModel `ContadorProforma`** (`proformas_contadorproforma`): `company` (`PROTECT`) y `ultimo`, con la restricción `un_contador_de_proformas_por_empresa` (uno por empresa).
- **AddIndex:** `proforma_estado_idx` (`company`, `estado`, `valida_hasta`) para los filtros por estado y vencimiento, y `proforma_fecha_idx` (`company`, `fecha`).
- **AddConstraint en `Proforma`:**
  - `proforma_numero_unico_por_empresa`: el número no se repite dentro de la empresa;
  - `proforma_vigencia_coherente`: `valida_hasta` ≥ `fecha`;
  - `proforma_facturada_con_venta`: «facturada» si y solo si tiene `venta`;
  - `proforma_total_no_negativo`.
- **AddConstraint en `ProformaDetalle`:** `proforma_detalle_cant_positiva`, `proforma_detalle_precio_no_negativo`, `proforma_detalle_descuento_valido` (fracción de 0 a 1) y `proforma_detalle_producto_unico` (un producto una sola vez por proforma, si el producto existe).

**Reversible:** sí, automáticamente: al revertir se borran las tres tablas.
- **Ojo:** revertir después de usar la versión nueva **borra todas las proformas** de todas las empresas, con sus líneas y sus contadores.
- Las facturas que salieron de proformas siguen intactas. Conservan la línea «Proforma: PRO-…» en su información adicional, que ya forma parte del comprobante.
- Si ya se usó en producción, lo seguro es restaurar el respaldo tomado antes de publicar, no revertir.
- Para revertirla hay que revertir antes la 0003 y la 0002 (`migrate proformas zero` lo hace en ese orden).

**Efecto sobre los registros existentes en producción**

| Tabla | Qué pasa | Cómo se ve |
|---|---|---|
| `proformas_*` (3 tablas nuevas) | Se crean vacías | Lista de proformas vacía |
| `pos_sale`, `pos_client`, `pos_product`, `pos_company`, `user_user` | Ningún cambio de columnas ni de filas. Solo pasan a ser destino de claves foráneas de las tablas nuevas | Sin cambio |

- No hay datos incompletos que marcar: no existen proformas previas.
- **Confirmación de que nada se recalcula:** no se toca ninguna venta, factura, cliente, producto, stock, cuenta por cobrar ni comprobante del SRI.
- **Efecto de las claves foráneas:**
  - borrar un cliente o un producto ya no puede fallar por las proformas: la proforma conserva la copia de los datos (`SET_NULL`);
  - una empresa con proformas no se puede borrar (`PROTECT`, igual que con sus demás datos);
  - al eliminar una venta (solo se puede si no salió al SRI), una señal `pre_delete` devuelve antes su proforma a «aceptada» o «enviada», y después Django vacía el vínculo. Así la restricción `proforma_facturada_con_venta` nunca se viola.

**Seguridad por filas (RLS):** la pone la 0002, en la misma ejecución de `migrate`. Entre la 0001 y la 0002 las tablas están vacías y nadie las usa.

**Costo esperado con el volumen real** (no se midió contra la base de producción, que esta rama no toca)
- Crea tres tablas vacías con sus índices (los dos compuestos, el único del número, el único condicional de las líneas y uno por cada clave foránea). Sobre tablas vacías cada índice tarda milisegundos.
- En PostgreSQL, Django crea las claves foráneas con `ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY` al final. Cada una toma un bloqueo breve (`SHARE ROW EXCLUSIVE`) sobre la tabla de destino (`pos_sale`, `pos_client`, `pos_product`, `pos_company`, `user_user`), que impide escribir en ella hasta que termina la transacción de la migración. La validación es inmediata porque las tablas nuevas están vacías.
- Las tablas nuevas empiezan vacías, así que el costo no depende del volumen de ventas, clientes o productos. Toda la migración debería tardar menos de un segundo; lo único que puede alargarla es esperar a que termine una escritura en curso sobre esas tablas de destino.
- Conviene aplicarla en la ventana habitual del despliegue, con el servicio y el temporizador de consultas al SRI detenidos o sin tráfico, para que esos bloqueos breves no esperen a una venta en curso.

---

## 2. `proformas/0002_seguridad_por_filas`

**Dependencias:** `('proformas', '0001_inicial')`.

**Operaciones:** un `RunPython` que **solo actúa en PostgreSQL** (en SQLite no hace nada). Para cada tabla (`proformas_contadorproforma`, `proformas_proforma` y `proformas_proformadetalle`):
- `ALTER TABLE … ENABLE ROW LEVEL SECURITY` y `ALTER TABLE … FORCE ROW LEVEL SECURITY` (también obliga al dueño de la tabla);
- `CREATE POLICY fpa_empresa … USING (…) WITH CHECK (…)` con la misma condición que `comprobantes/0012_seguridad_por_filas_guia`: se ve y se escribe una fila si `app.platform` = `on` o si su `company_id` es el de `app.company_id` de la conexión.

**Reversible:** sí. Al revertir: `DROP POLICY IF EXISTS fpa_empresa`, `NO FORCE ROW LEVEL SECURITY` y `DISABLE ROW LEVEL SECURITY` en las tres tablas. Las filas no cambian; solo deja de filtrarse por empresa en la base (la aplicación sigue filtrando con `TenantManager`).

**Efecto sobre los registros existentes en producción:** ninguno. Las tres tablas están vacías y ninguna otra tabla cambia. Nada se recalcula.

**Seguridad por filas:**
- Es la misma política que ya tienen las demás tablas por empresa. El contador también la lleva, para que una empresa no vea los números de otra.
- La comprueban las pruebas de PostgreSQL de `tests/test_proformas.py`: las tres tablas tienen RLS forzada y un `INSERT` con el `company_id` de otra empresa se rechaza, con un control positivo.
- Como las otras migraciones de RLS, hay que correrla con el usuario dueño de las tablas (el mismo que corre `migrate`).

**Costo esperado:** solo cambia el catálogo. Cada `ALTER TABLE` toma un bloqueo exclusivo breve sobre una tabla nueva que nadie usa todavía. Milisegundos.

---

## 3. `proformas/0003_modulo_proformas`

**Dependencias:** `('proformas', '0002_seguridad_por_filas')`, `('security', '0003_orden_menu')`, `('importacion', '0004_menu_con_guias')`, `('auth', '0012_alter_user_first_name_max_length')` y `('contenttypes', '0002_remove_content_type_name')`.

**Operaciones:** un `RunPython` (`forwards`, `backwards`) que no usa `schema_editor`.

**`forwards`**
1. Crea los tipos de contenido de las tres tablas y los **4 permisos** de proformas (`view_proforma`, `add_proforma`, `change_proforma`, `delete_proforma`). Normalmente Django los crea al terminar todas las migraciones; aquí hacen falta antes. Para eso marca la app como «con modelos» solo durante la llamada y luego restaura el valor anterior (`getattr(config, 'models_module', None)`).
2. Si la tabla de módulos está vacía (base nueva), termina: el menú lo arma después `start_installation`.
3. Si no (el caso de producción), llama a `organizar_menu` y luego a `sync_roles`:
   - **`organizar_menu`** (en `core/security/menu.py`):
     - crea el grupo «Cotizaciones» (icono `fas fa-file-alt`, orden 15);
     - crea el módulo «Proformas» (`/proformas/`, icono `fas fa-file-contract`, descripción «Cotizaciones sin validez tributaria que se convierten en factura») con sus 4 permisos;
     - vuelve a fijar el orden de todos los grupos y el nombre, el grupo y el orden de todos los módulos de `ESTRUCTURA`, con los valores que ya tienen;
     - vuelve a fijar los permisos de los módulos de importación, con los mismos códigos.
   - **`sync_roles`** recalcula los seis roles plantilla según `core/tenancy/roles.py`:

| Rol | Permisos de proformas que recibe |
|---|---|
| Propietario | `view_proforma`, `add_proforma`, `change_proforma`, `delete_proforma` |
| Administrador | los cuatro |
| Vendedor | `view_proforma`, `add_proforma`, `change_proforma` |
| Contador | `view_proforma` |
| Consulta | `view_proforma` |
| Cliente | ninguno (no ve el módulo) |

**`backwards`**
1. Borra el módulo `/proformas/`; sus asignaciones a los grupos caen en cascada.
2. Borra el grupo «Cotizaciones» si quedó sin módulos.
3. Quita los permisos de proformas de **todos** los grupos (los seis roles y los grupos personalizados), directamente en la tabla intermedia de permisos.

- No llama a `sync_roles`: en un `migrate proformas zero`, los modelos históricos de `auth.Group` quedan desfasados respecto de `GroupModule` (error «Must be "Group" instance»). Para los roles el resultado es el mismo.
- Los 4 `Permission` y los tipos de contenido se dejan: son inofensivos y la 0001 revertida ya no tiene tablas.

**Reversible:** sí. Al revertir, el menú y los roles quedan como antes de la 0003. Lo comprueba `tests/test_migracion_proformas.py`: el resto del menú, los grupos y los permisos ajenos a proformas quedan idénticos.

**Efecto sobre los registros existentes en producción**

| Tabla | Qué pasa |
|---|---|
| `django_content_type`, `auth_permission` | Se añaden 3 tipos de contenido y 4 permisos de proformas |
| `security_moduletype` (grupos del menú) | Se añade «Cotizaciones». A los demás grupos se les vuelve a escribir el orden que ya tienen. Si algún grupo usara ya el icono `fas fa-file-alt`, su icono pasaría a `fas fa-file-alt-x`, porque el icono es único. Ningún grupo del repositorio lo usa |
| `security_module` y sus permisos | Se añade «Proformas». A los módulos existentes de `ESTRUCTURA` se les vuelve a escribir el nombre, el grupo y el orden que fija el código. Si alguien hubiera renombrado a mano un módulo en producción, volvería al nombre del código, igual que con las migraciones de menú anteriores |
| `security_groupmodule` y `auth_group_permissions` de los **seis roles plantilla** | Se añade el módulo y se recalculan sus permisos según `roles.py`. Es lo mismo que hicieron las migraciones de menú anteriores. Si alguien cambió a mano los permisos de un rol plantilla, vuelven a los del código |
| Grupos personalizados (distintos de los seis roles) | `forwards` no los toca |
| Datos de negocio | Ninguno |

- No hay datos incompletos que marcar.
- **Confirmación de que nada se recalcula:** no se toca ninguna venta, comprobante, cliente, producto, stock ni saldo. Solo cambian las tablas de menú, permisos y roles.

**Seguridad por filas:** las tablas de menú, permisos y roles no son tablas por empresa y no tienen RLS. La migración no necesita `app.platform`.

**Costo esperado:** decenas de filas en las tablas de seguridad (unas decenas de módulos y algunos grupos). Milisegundos.

**Orden respecto a otras migraciones de menú** (por ejemplo, `comprobantes/0023_modulo_retenciones_recibidas` de la rama de Ventas):
- `organizar_menu` es idempotente y solo crea un módulo de `MODULOS_NUEVOS` si su app ya tiene sus permisos y, desde el 30/10/2026 (`a5e92a4`), si sus modelos existen en el estado de la migración (la 0003 le pasa `apps`): una vuelta deja las filas de `Permission`, que solas ya no bastan. Por eso la 0003 **no depende** de las migraciones de menú de otras ramas.
- Si la otra corre antes, crea el grupo «Cotizaciones» vacío y omite `/proformas/`. El menú no muestra grupos sin módulos, y la 0003 lo completa después.
- Si corre después, vuelve a ordenar todo sin duplicar. Cualquiera que corra última deja el menú completo.

---

## 4. Cómo se probaron

- **`tests/test_migracion_proformas.py`:**
  - `test_0003_backwards_y_forwards_con_el_registro_real`, en SQLite y PostgreSQL: revierte y vuelve a aplicar la 0003 sobre una base con menú. Comprueba que el resto del menú y de los roles queda idéntico, que los permisos por rol son los de la tabla anterior y que aplicarla dos veces no duplica nada.
  - `test_0003_en_una_instalacion_existente`, por subproceso con SQLite en archivo: `migrate`, `start_installation`, `migrate proformas zero` y `migrate`. Es el camino de producción: la app se instala sobre una base que ya tiene menú.
- **Menú:** `TestMenu.test_grupos_nombres_y_orden` (en `tests/test_importacion_flujo.py`) y las pruebas de menú de `tests/test_b0_contratos.py`.
- **Comprobaciones:** `manage.py check` sin problemas y `makemigrations --check --dry-run` sin cambios («No changes detected»).
- **Suites completas sobre `3f91e75`:** SQLite 717 aprobadas y 19 omitidas (las omitidas son solo de PostgreSQL); PostgreSQL 736 aprobadas y ningún fallo. La línea base de `f36d3b2` era 595 + 9 y 604.

---

## 5. Notas de integración

- **Sin dependencias de otras ramas.** Todas las dependencias de proformas 0001–0003 (`pos` 0019, `security` 0003, `importacion` 0004, `auth` 0012 y `contenttypes` 0002) ya están en `f36d3b2`. Al integrar **no se re-encadenan** ni se renumeran: no hay ciclos con Compras, Ventas ni D0, y cada app conserva un solo nodo hoja.
- **Fusión con la `plataforma` actual** (`544a8e7`, con B0, D0 y el ticket): una prueba de fusión en seco (`git merge-tree`) no da conflictos de texto. D0 añade `comprobantes` 0014–0015, que no se cruzan con proformas.
- **Conflictos de texto previstos con Ventas** (`fase/etapa2-ventas`, `6114e14`), según `git merge-tree`:
  - `core/security/menu.py`: las dos ramas añaden su tupla al final de `MODULOS_NUEVOS`. Hay que conservar las dos, más el grupo «Cotizaciones» de P y la línea «Retenciones recibidas» de Ventas en «Administrativo»;
  - `tests/test_b0_contratos.py`:
    - en `TestMenu`, la lista esperada debe llevar `('proformas', '/proformas/')` y `('comprobantes', '/comprobantes/retenciones-recibidas/')`;
    - en `TestRoles`, cada rama afirma que el módulo de la otra todavía no existe. Con las dos fusionadas existen los dos, así que esa afirmación se quita (o pasa a comprobar que existen ambos).
  - El commit de P que toca este archivo es `92b5eeb`.
- **Con Compras** (`fase/etapa2-compras`, `55f2e5f`) no se prevén conflictos de texto. Compras toca otras clases de `tests/test_importacion_flujo.py`, no `TestMenu`.
- **`tenancy` 0007 (integrador):** añadir las choices de los 8 códigos: `proforma_enviada`, `proforma_marcada_enviada`, `proforma_aceptada`, `proforma_rechazada`, `proforma_anulada`, `proforma_eliminada`, `proforma_facturada` y `proforma_venta_eliminada`. P no crea migraciones de `tenancy` y guarda en `AuditLog.detail` solo tipos JSON, así que no depende de que se añada un codificador.
- **La conversión toca tres archivos de la venta**, con hunks pequeños y anclados. Ninguna otra rama los toca hoy:
  - `core/pos/views/sale/views.py`: solo `SaleCreateView` (import de `messages`, `get`, `get_context_data` y dos hunks en `post`). Convive con el `SaleDeleteView` atómico de B0;
  - `core/pos/static/sale/admin/js/form.js`: `cargarProforma` y su llamada;
  - `core/pos/templates/sale/admin/create.html`: aviso, `proforma_id` oculto, «Emitir factura», `json_script` y la condición del consumidor final.
- **Nunca invertir el orden de bloqueo** proforma → numeración (`Receipt`) en `SaleCreateView.post`.
- **Señal:** `pre_delete` de `pos.Sale` (`dispatch_uid='fpa_proforma_libera_venta'`), conectada en `ProformasConfig.ready()`. Depende del borrado atómico de ventas de B0, que ya está en la base.
- **Prueba de concurrencia PG:** `tests/test_zz_proformas_concurrencia_pg.py` conserva el nombre del §7.4. En la suite PG completa corre antes que `test_zz_secuencias…`, `test_zz_ventas_borrado…` y `test_zzz_importacion…`, y todas pasan.
- **Tras cada fusión:** un solo nodo hoja por app, `makemigrations --check --dry-run` sin cambios, `migrate` desde una base vacía y la suite completa en SQLite y PostgreSQL.
- **Despliegue (cuando se autorice; ahora no):** respaldo antes de migrar, en la ventana habitual, con el servicio y el temporizador del SRI detenidos. Las tres migraciones van juntas en el mismo `migrate`.
