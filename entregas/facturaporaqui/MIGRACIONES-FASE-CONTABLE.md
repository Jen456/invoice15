# Migraciones de la fase contable (D0, Etapa 1 y Etapa 2) — resumen integrado

29/10/2026 · `plataforma` con D0 Fase A, Proformas, Compras y Ventas fusionadas, más el commit final de integración.
Actualizado el 30/10/2026 con el ensayo sobre una copia del respaldo y la vuelta de `pos/0031` corregida (`1c4973d`). El
detalle de cada migración está en `MIGRACIONES-PROFORMAS.md`, `MIGRACIONES-COMPRAS.md`, `MIGRACIONES-VENTAS.md` y, para
D0, en `D0-CATALOGO-RETENCIONES-2026-10.md`.

**En una frase:** son 19 migraciones, todas nuevas frente a lo publicado: 2 de D0, 3 de Proformas, 7 de Compras, 6 de
Ventas y 1 de integración. Agregan columnas, tablas nuevas con su seguridad por filas, permisos y módulos del
menú, y parten en dos vigencias las filas 310 y 332E del catálogo de retenciones. **Ninguna recalcula documentos ni
importes existentes.** Lo que falta en los registros antiguos queda vacío o marcado como incompleto o «anterior a la
regla», a la vista del usuario.

## Orden de aplicación

Django las aplica según sus dependencias, en un solo `migrate --noinput` (el de `desplegar.sh`). Con lo publicado hoy
(pos 0019, comprobantes 0013, importacion 0004, tenancy 0006), el orden resultante es el de la tabla (calculado con el
grafo de migraciones de Django sobre el commit entregado, sin tocar ninguna base). Cada migración se confirma por
separado: si la guardia de `comprobantes/0015` detiene el `migrate`, las siete de `pos` y `comprobantes/0014` ya
quedaron aplicadas.

| # | Migración | Rama | Qué hace | Datos existentes | Reversible |
|---|---|---|---|---|---|
| 1 | `pos/0020_proveedor_datos_ats` | Compras | Proveedor: tipo de identificación, tipo de sujeto, parte relacionada | Columnas vacías: «Datos incompletos» | Sí |
| 2 | `pos/0021_compra_datos_ats` | Compras | Compra: comprobante del proveedor (ATS), importes por tarifa, marca de datos incompletos, unicidad | Importes en `NULL` y marca «incompleta»; nada se recalcula | Sí |
| 3 | `pos/0022_detalle_compra_tarifa` | Compras | Línea de compra: tarifa, IVA y líneas de gasto | Columnas vacías: «Sin tarifa registrada» | Sí |
| 4 | `pos/0023_pagos_y_gastos` | Compras | Base de cálculo de la cuenta por pagar; medio de pago y referencia en pagos y gastos | Base «subtotal» (como hoy) y medio de pago «Sin dato» | Sí |
| 5 | `pos/0024_permiso_completar_compras` | Compras | Permiso «Completar datos» y roles | Solo permisos y roles | Sí |
| 6 | `pos/0030_cxc_abonos_anulados_empresa` | Ventas | Empresa (tipo de contribuyente, periodicidad), marca «Anulado en el SRI» en factura y NC, abonos con tipo y medio de pago | Columnas vacías; las NC antiguas quedan «anterior a la regla» | Sí |
| 7 | `pos/0031_permisos_anulado_sri` | Ventas | Permisos «Anulado en el SRI» de factura y NC; roles | Solo permisos y roles | Sí |
| 8 | `comprobantes/0014_codigoretencion_vigencias` | D0 | Vigencias (`vigente_desde`, `vigente_hasta`) y `ayuda` en el catálogo de retenciones; unicidad por vigencia (una sola fila abierta y una sola sin inicio por código) y cierre no anterior al inicio (el no solape lo valida `clean()`, no la base); `RetencionDetalle.codigo_catalogo` | Columnas vacías; los detalles históricos quedan sin enlace (no se infiere) | Sí |
| 9 | `comprobantes/0015_vigencias_res_28` | D0 | 310 y 332E: la fila actual cierra el 31/07/2026 y se crea otra desde el 01/08/2026, con los mismos porcentajes de hoy | Solo el catálogo. Aborta si el 310 o el 332E se editaron en `/plataforma/` | Sí |
| 10 | `comprobantes/0020_anulado_sri_y_cxc_nota_debito` | Ventas | Marca de anulado en retención, liquidación, ND y guía; cuenta por cobrar propia de la ND | Columnas vacías; las ND antiguas quedan «anterior a la regla» | Sí |
| 11 | `comprobantes/0021_retencion_recibida` | Ventas | Retenciones recibidas y su detalle | No (tablas nuevas) | Sí |
| 12 | `comprobantes/0022_seguridad_por_filas_retencion_recibida` | Ventas | RLS de esas tablas (solo PostgreSQL) | No | Sí |
| 13 | `comprobantes/0023_modulo_retenciones_recibidas` | Ventas | Módulo «Retenciones recibidas» y permisos de anulado de los cuatro comprobantes; roles | Solo menú, permisos y roles | Sí |
| 14 | `importacion/0005_equivalencia_producto` | Compras | Equivalencias «código del proveedor → producto» | No (tabla nueva) | Sí |
| 15 | `importacion/0006_seguridad_por_filas_equivalencia` | Compras | RLS de esa tabla (solo PostgreSQL) | No | Sí |
| 16 | `proformas/0001_inicial` | Proformas | Tablas de proformas, líneas y contador | No (tablas nuevas) | Sí |
| 17 | `proformas/0002_seguridad_por_filas` | Proformas | RLS de esas tablas (solo PostgreSQL) | No | Sí |
| 18 | `proformas/0003_modulo_proformas` | Proformas | Permisos, grupo «Cotizaciones», módulo y roles | Solo menú, permisos y roles | Sí |
| 19 | `tenancy/0007_acciones_fase_contable` | Integración | Códigos de auditoría de la fase en `AuditLog.action` y `AuditLog.detail` con `DjangoJSONEncoder` | No (solo opciones del campo y su codificador) | Sí |

Dependencias cambiadas al integrar: `pos/0030` depende de `pos/0024` (antes de `pos/0019`) y `comprobantes/0020` de
`comprobantes/0015` (antes de `comprobantes/0013`). La vuelta de `comprobantes/0023` quita su módulo y sus permisos por ids
en las tablas intermedias, como `proformas/0003`, para poder deshacerla junto con las de D0. Desde `1c4973d` (30/10) la
vuelta de `pos/0031` hace lo mismo: el ensayo mostró que `migrate pos 0019_orden_de_las_lineas` fallaba con ValueError
«Must be "Permission" instance» (al deshacer varias migraciones en un mismo plan, los modelos históricos de `Permission`
quedan desfasados respecto de `Module` y `Group`). Desde `a5e92a4`, `comprobantes/0023` y `proformas/0003` pasan sus modelos
históricos a `organizar_menu`, que solo crea el módulo de una app migrada en ese estado; desde `22ff73d`, también
`importacion/0003` y `0004` (ya publicadas), para una vuelta que bajara de ellas. En la base publicada eso no cambia nada: Django no vuelve a
ejecutar una migración aplicada.

## Precauciones de aplicación (cuando la propietaria autorice publicar; en la base real no se ejecutó nada)

1. **Volcado previo** de la base publicada (lo hace `deploy/scripts/desplegar.sh`). Es el camino de vuelta si después
   de publicar se registran datos nuevos.
2. **Ensayo sobre una copia temporal de un volcado reciente de la base publicada** (el último respaldo diario o uno hecho
   aparte; no el del punto 1, que `desplegar.sh` hace en la misma corrida, justo antes de `migrate`), con el código nuevo
   y el rol de la aplicación, antes de tocar la base real: `migrate`, `showmigrations` sin pendientes, `manage.py check` y `makemigrations --check --dry-run`. En
   VM101 lo hace `verif-firma/ensayo-fase/ensayo_migraciones_fase.sh <checkout> [volcado]`, con el último respaldo diario
   o con el volcado que se le pase: ida, esas comprobaciones, huellas de los datos, vuelta documentada, esquema comparado
   con una copia intacta y otra ida. Las copias se borran al terminar, aunque falle. No imprime credenciales ni datos de
   clientes: solo filas del catálogo de retenciones, del menú y de los roles, y los errores de un `migrate` que falle. Los
   del 30/10 están en «Lo que se probó», abajo. Hay que repetirlo con datos del día de la publicación, con un volcado
   hecho aparte ese día.
3. **Guardia de `comprobantes/0015`:** aborta si el 310 o el 332E se editaron en `/plataforma/`. Si salta, no se fuerza:
   se revisa el catálogo con la propietaria y se decide antes de reintentar. Como las de `pos` y `comprobantes/0014` ya
   quedaron aplicadas, el ensayo del punto 2 es donde debe aparecer; si apareciera en la base real, se restaura el volcado.
4. **Ventana habitual**, con el servicio y el temporizador del SRI detenidos, y las 19 migraciones en el mismo `migrate`.
5. **Nada histórico se recalcula.** Las NC y ND creadas antes de publicar quedan «anterior a la regla» (`no_aplica`) y no
   ajustan la cuenta por cobrar; las compras y proveedores anteriores quedan marcados como incompletos.
6. **Órdenes de revisión, solo en modo ensayo** y para revisar con el contador: `proveedores_incompletos`,
   `compras_incompletas`, `regularizar_cxc_historico` y `completar_fecha_emision`. Ninguna se ejecuta con `--aplicar`
   sin una decisión escrita: las cuatro la exigen con `--decision` (las dos de Compras piden además `--csv` y
   `--empresa` o `--todas`).

## Precauciones de reversión

- **Si ya se registraron datos con la versión nueva, la vuelta es restaurar el volcado previo y el código anterior, no
  `migrate` hacia atrás.** La reversa borra columnas y tablas: proformas, retenciones recibidas, datos ATS de compras y
  proveedores, base de cálculo de las cuentas por pagar, medio de pago y referencia de pagos y cobros, tipo y anulación
  de los abonos, y las marcas «Anulado en el SRI». Sin el tipo de abono, los abonos anulados volverían a restar del
  saldo de la cuenta por cobrar.
- **Cuatro reversas fallan a propósito cuando hay datos nuevos** (no forzarlas: restaurar el volcado). Tres, en
  PostgreSQL:
  - `pos/0020`: `ruc` vuelve a 13 caracteres y falla si hay un pasaporte o una identificación del exterior más larga;
  - `pos/0021`: devuelve `number` a 8 caracteres y falla si ya hay una compra con secuencial (su número se guarda como
    `001-001-000000123`, más de 8 caracteres). Si no la hay, falla al volver a crear la unicidad de `number` por empresa
    cuando hay dos compras con el mismo número (pasa enseguida: las de liquidación y las de «Completar después» sin
    secuencial guardan `number = ''`);
  - `pos/0022`: `product` vuelve a ser obligatorio y falla si hay líneas de gasto o de notas del proveedor sin producto.
  - y, en cualquier motor, `comprobantes/0015`: se niega si en `/plataforma/` se creó otra vigencia (una fila con fecha
    de inicio, aparte de las dos del 01/08/2026).
- **Destino de una reversa sin datos nuevos** (lo publicado hoy): `migrate proformas zero`,
  `migrate comprobantes 0013_modulo_guias`, `migrate pos 0019_orden_de_las_lineas`, `migrate importacion 0004_menu_con_guias`
  y `migrate tenancy 0006_accion_empresa_agregada`, en ese orden. Django deshace antes lo que depende de cada una: las de
  Ventas en `comprobantes` (0023→0020) antes que las de D0 (0015, 0014), y `importacion` 0006–0005 antes que
  `pos` 0022–0020.
- **Reversas que no restauran todo:** `pos/0024` no hace nada al revertir (el permiso «Completar datos» queda en el
  módulo y los roles, sin efecto para el código anterior) y Django no borra filas de `Permission`. La vuelta de
  `comprobantes/0015` deja en `NULL` el `codigo_catalogo` de los detalles que apuntaban a las filas del 01/08/2026 y deja
  el catálogo exacto de antes; los demás detalles pierden el enlace con la vuelta de `comprobantes/0014`, que borra la
  columna. Las de seguridad por filas
  (`proformas/0002`, `importacion/0006`, `comprobantes/0022`) quitan la política antes de que se borren sus tablas.
- **Lo que se probó y lo que no:**
  - **Ensayo sobre una copia del respaldo diario (30/10/2026)**, con el guion del punto 2 de la aplicación: PostgreSQL 16,
    rol de la aplicación y respaldo `diario-20261029-231633` (base de lo publicado, `98cfa20`, con las 19 pendientes).
    Se restaura dos veces en bases temporales: una se migra y la otra queda intacta para comparar. Se repitió con cada
    cambio de código; el último, con `22ff73d` (código final de la fase), da lo mismo que los anteriores.
    - **Ida:** las 19 en un solo `migrate`, entre 40 y 58 s en total, con una o dos suites de pruebas corriendo en la
      misma máquina. Ninguna pasó de 11 s; las más lentas son `proformas/0001` (de 6,5 a 10,7 s), `comprobantes/0021`
      (de 2,9 a 7,9 s) y `pos/0021` (de 5,4 a 6,5 s). Después,
      `showmigrations` sin pendientes, `check` sin avisos y `makemigrations --check` sin cambios. El 310 y el 332E
      quedan en dos vigencias (hasta el 31/07/2026 y desde el 01/08/2026) con los mismos porcentajes, 1 % y 0 %.
    - **Datos que ya existían:** de las 68 tablas, 59 quedan idénticas en sus columnas anteriores (filas y valores).
      Las otras 9 son las de permisos, módulos, tipos de módulo, permisos de los módulos, módulos y permisos de los
      roles, tipos de contenido, `django_migrations` y el catálogo de retenciones. En menú, roles y permisos solo se
      añaden filas: por claves naturales (rol, URL del módulo, código del permiso), 81 nuevas, y ninguna existente cambia
      ni desaparece; el nombre, el grupo y el orden de los módulos publicados quedan como están. El catálogo gana las 2
      filas nuevas del 310 y el 332E y, como manda `comprobantes/0015`, cambia dos existentes: la del 310 hasta el
      31/07/2026 deja de tener porcentaje editable (el DIMM lo da fijo) y la «fuente» del 3440 anota el bloque del
      06/08/2026.
    - **Vuelta documentada** (destinos y orden de arriba): se deshacen las 19 (de 62 a 69 s, cinco órdenes `migrate`) y
      el esquema queda idéntico al publicado. Los datos quedan idénticos a la copia intacta en 64 de 68 tablas. Por claves
      naturales, solo sobran los 6 tipos de contenido y las 14 filas de `Permission` de la fase, que Django no borra, y
      `pos.change_purchase`, que sigue en el módulo de Compras y en Propietario y Administrador porque la vuelta de
      `pos/0024` no hace nada.
    - **Otra ida:** las 19 se aplican de nuevo sin pendientes. Menú, permisos, roles, catálogo y migraciones quedan
      idénticos a la primera ida por claves naturales (972 filas); solo cambian los ids de las filas que se vuelven a
      crear y la hora de aplicación en `django_migrations`.
    - La primera vez, la vuelta falló en `migrate pos 0019` (`pos/0031`, ver «Dependencias cambiadas al integrar»).
      Desde `1c4973d`, `tests/test_migracion_vuelta_fase.py` recorre la misma vuelta y otra ida por subproceso sobre una
      instalación SQLite con menú. Desde `a5e92a4` y `22ff73d` recorre vuelta, ida completa (las 19 en un solo plan, como
      `desplegar.sh`), otra vuelta, dos idas parciales (`migrate proformas` y `migrate comprobantes`) e ida completa.
      Antes, `organizar_menu` tomaba como migrada una app solo porque la vuelta deja sus `Permission`, y creaba el módulo
      de la otra sin sus tablas.
  - En las suites completas de SQLite y PostgreSQL: ida y vuelta de `comprobantes` 0013↔0015 con sus guardias
    (`tests/test_zzz_vigencias_migraciones.py`), que también deshace y rehace las cuatro de Ventas en `comprobantes`; ida
    y vuelta de `proformas/0003` sobre un menú real (`tests/test_migracion_proformas.py`); la vuelta documentada completa
    (`tests/test_migracion_vuelta_fase.py`); y datos «de antes» de Compras y de Ventas migrados sin cambios y, en Ventas,
    revertidos y migrados otra vez (SQLite, por subproceso).
  - **No probado:**
    - la vuelta con datos registrados con la versión nueva: ahí no se deshace, se restaura el volcado, y las cuatro
      reversas de arriba se niegan a propósito;
    - la base real;
    - el ensayo con el volcado del día de la publicación: repetirlo entonces con el mismo guion.

## Costo esperado

Columnas nulas o con valor constante, tablas nuevas vacías, políticas RLS y filas de permisos: en PostgreSQL 16 son
cambios de catálogo con bloqueos exclusivos breves. En los ensayos del 30/10, con una o dos suites de pruebas corriendo a la
vez, la ida tardó entre 40 y 58 s y la vuelta entre 62 y 69 s; ninguna migración pasó de 11 s. Los tiempos de las más
lentas están en «Lo que se probó», arriba. Los documentos de cada rama traen estimaciones previas al ensayo, que en esas se
quedaron cortas: «menos de un segundo» para `proformas/0001` (medido: de 6,5 a 10,7 s), «instantáneo» para
`comprobantes/0021` (de 2,9 a 7,9 s) y «milisegundos con miles de filas» para `pos/0021` (de 5,4 a 6,5 s).

## Nota (30/10/2026) — migraciones de locales y puntos de emisión (`91ddccc`)

Se agregan `configuracion/0001_puntos_por_usuario`, `0002_rls_puntos` y `0003_modulo_puntos` (dependen de `pos/0019`, anterior a la
fase: la vuelta documentada arriba **no** las deshace ni toca sus tablas) y `tenancy/0008_acciones_puntos` (depende de `tenancy/0007`:
la vuelta a `tenancy 0006` también la deshace, así que tras la vuelta quedan 20 pendientes en vez de 19; `tests/test_migracion_vuelta_fase.py`
lo comprueba). Al publicar, el mismo `migrate` las aplica todas.

## Nota (31/10/2026) — migraciones del respaldo de cobros (`9eef6d5`)

`pos/0032_sale_medio_cobro` y `pos/0033_condicion_de_pago` cuelgan de `pos/0031` (una app tiene una sola hoja): la vuelta documentada
las deshace también, y con ella se pierde la columna `medio_cobro` (vacía en todo lo anterior a esta regla). `cobros/0001_respaldo_cobro`,
`0002_rls_cobros` y `0003_permisos_cobros` cuelgan de `pos/0019` y **no** se deshacen con la fase (los respaldos y sus archivos se conservan);
`tenancy/0009_acciones_cobros` sí (sobre `tenancy/0007`). Tras la vuelta quedan 23 pendientes (`tests/test_migracion_vuelta_fase.py`).

## Nota (31/10/2026) — candidato de la entrega 1 (`c103bb4`): 33 migraciones y vuelta ampliada

Frente a lo publicado (`98cfa20`) quedan pendientes 33 (ensayo corrido sobre `e4be758`, mismas migraciones que el candidato): las 19 de la fase más configuracion 0001–0003, tenancy 0008–0009, pos
0032–0034, cobros 0001–0003 y adjuntos 0001–0003 (pos 0034 = nacimiento opcional; adjuntos 0001 cuelga de pos 0031). Ensayo con
`ensayo_migraciones_candidato.sh` sobre copia del respaldo diario: ida 54,5 s en un solo `migrate`; vuelta en este orden: `adjuntos
zero`, `cobros zero`, `configuracion zero`, `proformas zero`, `comprobantes 0013`, `pos 0019`, `importacion 0004`, `tenancy 0006`
(94,6 s), esquema IDÉNTICO al publicado; segunda ida idéntica a la primera. Residuos de la vuelta, inocuos: filas nuevas de
`Permission` y `ContentType` (como en la fase) y el orden de «Reglas de importación» (3→4) y «Numeraciones registradas» (4→5) en
el menú, que `organizar_menu` reordena en la ida y la vuelta no deshace. `tests/test_migracion_vuelta_fase.py` espera 27 pendientes
tras la vuelta documentada de la fase (que no deshace configuracion ni cobros).

## Nota (02/11/2026) — candidato con recibos por completar: 37 migraciones

Frente a lo publicado (`98cfa20`) quedan 37: las 33 del candidato de la entrega 1 más `adjuntos 0004–0006` y `tenancy 0010`
(ver `MIGRACIONES-ADJUNTOS.md`). La vuelta documentada no cambia de orden (`adjuntos zero` primero; `tenancy 0006` deshace 0010).
`tests/test_migracion_vuelta_fase.py` espera 31 pendientes tras la vuelta de la fase. Ensayo sobre copia del respaldo: abajo.

## Nota (02/11/2026) — candidato con importación por claves y tributario: 41 migraciones

Frente a lo publicado (`98cfa20`) quedan 41: las 37 de la nota anterior, `importacion 0007` y `tributario 0001–0003`.

| Migración | Qué hace | Vuelta |
|---|---|---|
| `importacion/0007_lotes_de_claves` | columnas y opciones nuevas en lotes, entradas, archivos y documentos importados (origen por claves o reporte, clave, sugerencias, «en proceso en el SRI»); módulo «Importar por claves o reporte del SRI» | quita las columnas y, desde `b64e156`, también el módulo (sus permisos son los de la importación de siempre y se quedan) |
| `tributario/0001_libros_mensuales` | tabla `tributario_exportacionlibro` (registro de cada exportación: libro, mes, formato, filas, totales, huella y autor) y permisos `view_libros` y `view_revision` | borra la tabla |
| `tributario/0002_seguridad_por_filas` | RLS `fpa_empresa` en esa tabla (solo PostgreSQL), como `adjuntos 0002` | quita la política |
| `tributario/0003_modulo_libros` | grupo «Tributario» del menú con cinco módulos (libros, revisión, ATS, borradores y empresas del contador) y `sync_roles` | quita los cinco módulos, los permisos de la app en los grupos y el grupo si queda vacío |

Dependencias: `tributario 0001` cuelga de `pos 0019` (la empresa existe desde antes) y `0003` de `importacion 0004`. Por eso
la vuelta de la fase no la arrastraba: dejaba los cinco módulos con rutas que el código anterior no sirve. **La vuelta empieza
ahora por `tributario zero`**. Orden completo hacia lo publicado: `tributario zero`, `adjuntos zero`, `cobros zero`,
`configuracion zero`, `proformas zero`, `comprobantes 0013_modulo_guias`, `pos 0019_orden_de_las_lineas`,
`importacion 0004_menu_con_guias` y `tenancy 0006_accion_empresa_agregada`. `tests/test_migracion_vuelta_fase.py` espera
35 pendientes tras la vuelta de la fase (que no deshace configuracion ni cobros) y comprueba que no quedan los módulos nuevos.

**Ensayo** con `ensayo_migraciones_candidato.sh` sobre una copia del respaldo diario, código `32c20d8`: 41 pendientes; ida en 96,7 s en un solo `migrate`; vuelta en el orden de arriba en 120,9 s hasta un esquema **idéntico** al publicado, sin los módulos de tributario ni «Importar por claves»; segunda ida idéntica a la primera (menú, roles y permisos: 1138 filas iguales). Residuos de la vuelta, inocuos: filas nuevas de `Permission` y `ContentType`, `pos.change_purchase` en Propietario, Administrador y el módulo de Compras (como en la fase) y el orden de cuatro módulos del menú (Lotes 2→3, Pendientes 3→4, Reglas 3→4 y Numeraciones 4→5), que `organizar_menu` reordena en la ida. Lo posterior a `32c20d8` solo cambia pruebas y documentos.

**Restauración:** si ya se registraron datos con la versión nueva (recibos por completar, notas de respaldo, lotes por claves,
exportaciones registradas), revertir = restaurar el volcado previo de la base y la carpeta `privado/` de `FPA_ARCHIVOS` (ya en el
respaldo diario) y volver al código anterior, no `migrate` hacia atrás. Las exportaciones de libros, ATS y borradores no guardan
archivos: solo su registro y su huella.

## Nota (02/11/2026) — kardex: 45 migraciones

Frente a lo publicado (`98cfa20`) quedan 45: las 41 de la nota anterior, `contabilidad 0001–0003` y `tenancy 0011`.

| Migración | Qué hace | Vuelta |
|---|---|---|
| `contabilidad/0001_kardex` | tablas `contabilidad_movimientomanual` (clave única por empresa, cantidad > 0, costo obligatorio en saldo inicial y entrada y vacío en salida) y `contabilidad_ajusteinventario`; permisos `view_kardex`, `add_movimientomanual` y `change_movimientomanual` | borra las tablas |
| `contabilidad/0002_seguridad_por_filas` | RLS `fpa_empresa` en las dos tablas (solo PostgreSQL) | quita las políticas |
| `contabilidad/0003_modulo_kardex` | grupo «Contabilidad» del menú con «Kardex por producto» e «Inventario valorizado» y `sync_roles` | quita los dos módulos, los permisos de la app en los grupos y el grupo si queda vacío |
| `tenancy/0011_acciones_kardex` | dos acciones de auditoría `kardex_*` (solo `choices`) | solo `choices` |

`contabilidad 0001` cuelga de `pos 0034`: la vuelta a `pos 0019` también la deshace, pero la vuelta documentada empieza por
`contabilidad zero` y sigue como en la nota anterior. `tests/test_migracion_vuelta_fase.py` espera 39 pendientes tras la vuelta
de la fase. `ensayo_migraciones_candidato.sh` añade `contabilidad zero` cuando el candidato trae la app. Ensayo sobre una copia
del respaldo diario, código `53e5297`: 45 pendientes; ida en 63,1 s en un solo `migrate`; vuelta en 113,7 s (empieza por `contabilidad zero`) hasta un esquema **idéntico** al publicado, sin grupos ni módulos nuevos; segunda ida idéntica a la primera (menú, roles y permisos: 1172 filas iguales). Residuos de la vuelta, los mismos de la nota anterior.

**Restauración:** la vuelta pierde los ajustes de stock registrados y los movimientos manuales del kardex (el stock de los
productos no cambia). Con datos reales nuevos, revertir = restaurar el volcado previo, no `migrate` hacia atrás.

## Nota (03/11/2026) — cierre integrado: sin migraciones nuevas

El cierre integrado no añade migraciones: el candidato sigue con las 45 de la nota anterior. Ensayo repetido sobre el código
final: sobre `0fb9167` y una copia del último respaldo diario: 45 aplicadas y 0 pendientes; la vuelta (`contabilidad zero`, `tributario zero`, …) deja el esquema IDÉNTICO al publicado y la otra ida termina igual que la primera. Mismo resultado que el ensayo del kardex. Bases temporales borradas al terminar.

## Publicación (04/11/2026): las 45 migraciones aplicadas en app.facturaporaqui.com

Aplicadas el 04/11/2026 entre las 14:07:52 y las 14:09:43 UTC con `baadb8b`, con el servicio y las tareas del SRI y de
importación detenidos. Antes: ensayo sobre un volcado fresco de producción (45 en 78 s; vuelta con esquema idéntico) y
restauración comprobada (`respaldos/cierre-20261104-135137/`: 68 tablas con los mismos conteos y 264 archivos privados con
la misma huella). Volcado previo del despliegue: `respaldos/pre-20261104-140752-baadb8bd.dump`; versión anterior:
`releases/20261028-130922-98cfa208`. Vuelta: `deploy/scripts/restaurar.sh <volcado> <versión anterior> [--ejecutar]`
(base, código y estáticos; `desplegar.sh --revertir` no sirve con migraciones). Las facturas autorizadas en el SRI
después del volcado no están en él: con documentos nuevos, corregir hacia adelante o volver a registrarlos.

## Nota (14/11/2026) — bloque 1 del cierre contable: plan de cuentas y su importación, 7 migraciones (sin publicar)

Rama `fase/contable-1-cuentas` sobre `74ebb3d`. Lo publicado es `e0f2902`, con `contabilidad 0003` y `tenancy 0012`
aplicadas. El bloque añade siete migraciones: dos tablas nuevas con su seguridad por filas, tres permisos repartidos por
el módulo del kardex, la regla de la base que anula a los autores de cuentas y lotes cuando se borra un usuario, y tres
acciones de auditoría. Ninguna toca una tabla ni una columna que use la versión publicada.

| # | Migración | Qué hace | Vuelta |
|---|---|---|---|
| 1 | `contabilidad/0004_plan_de_cuentas` | tabla `contabilidad_cuenta` (código único por empresa sin distinguir mayúsculas, clave del envío única por empresa cuando no es nula, tipo `grupo` o `movimiento`, índice por empresa y padre) y permisos `view_cuenta`, `add_cuenta` y `change_cuenta` | borra la tabla |
| 2 | `contabilidad/0005_seguridad_por_filas_cuentas` | RLS `fpa_empresa` forzada en esa tabla (solo PostgreSQL) | quita la política |
| 3 | `contabilidad/0006_permisos_plan_cuentas` | añade los tres permisos al módulo «Kardex por producto» y ejecuta `sync_roles`: Propietario, Administrador y Contador ven, crean y editan; Consulta solo ve; Vendedor y Cliente, nada. No crea módulos ni cambia el menú | quita esos tres permisos del módulo y de los roles, por ids en las tablas intermedias; las filas de `Permission` se quedan |
| 4 | `contabilidad/0007_importacion_cuentas` | tabla `contabilidad_importacioncuentas` (lote: archivo privado, huella, filas leídas, columnas elegidas, estado, claves y resultado) y columna nula `lote_id` en `contabilidad_cuenta` | quita la columna y borra la tabla |
| 5 | `contabilidad/0008_seguridad_por_filas_importacion` | RLS `fpa_empresa` forzada en la tabla de lotes (solo PostgreSQL) | quita la política |
| 6 | `contabilidad/0009_anular_autores_en_la_base` | `ON DELETE SET NULL` en las cuatro claves hacia `user_user` (`creada_por` y `actualizada_por` de la cuenta, `creado_por` y `confirmado_por` del lote), que siguen diferidas y con su nombre; pide el bloqueo de `user_user` en intentos cortos (solo PostgreSQL; ver abajo) | nada: la regla se queda hasta que 0007 o 0004 borran su tabla |
| 7 | `tenancy/0013_acciones_plan_cuentas` | acciones de auditoría `cuenta_creada`, `cuenta_modificada` y `cuentas_importadas` (solo `choices`) | solo `choices` |

**Orden.** Un solo `migrate --noinput`, como siempre. Las de contabilidad van en fila, de 0004 a 0009. `tenancy 0013` va
sobre `tenancy 0012`; no depende de las de contabilidad ni ellas de esta.

**Por qué 0009.** Django anula `creada_por` y los demás con un UPDATE antes de borrar al usuario, y con la seguridad por
filas forzada ese UPDATE solo alcanza a la empresa activa. Quitar de su última empresa a quien había creado cuentas en
otra fallaba al confirmar, con la membresía ya quitada y el usuario sin ninguna (ensayo, D1); la versión publicada, que no
conoce estas tablas, fallaba siempre que el usuario tuviera cuentas o lotes (D2 y D5). La base no aplica la seguridad por
filas a sus acciones referenciales, así que con `ON DELETE SET NULL` las anula ella, en todas las empresas y con
cualquier versión del código. Cambiar la acción es quitar la restricción y volver a crearla: quitarla toma
`AccessExclusiveLock` sobre `user_user` (medido en PostgreSQL 16; crearla toma `ShareRowExclusiveLock`). Mientras 0009
espera ese bloqueo, toda lectura nueva de `user_user` (cada petición con sesión) hace cola detrás de ella, y mientras lo
tiene, también. 0004 y 0007 solo toman `ShareRowExclusiveLock`, que no para lecturas: este parón es propio de 0009.

La primera versión de 0009 lo esperaba una sola vez, con `lock_timeout = 5s`, y no era cosa de milisegundos: con otra
transacción abierta que solo había leído `user_user`, cada petición con sesión se paraba hasta 5 s y, si la retención
pasaba de 5 s, `migrate` fallaba (verificación de la segunda ronda: retención de 2 s, lectura parada 1,66 s y 0009 bien a
los 2,18 s; de 8 s, lectura parada 5,07 s y 0009 cortada por `lock_timeout` a los 5,59 s). Ahora lo pide en intentos
cortos. Cada intento va en su propio punto de guardado (`transaction.atomic` anidado), toma primero las dos tablas del
plan y al final `user_user`, con `lock_timeout` de 1 s por bloqueo; si no lo consigue, vuelve al punto de guardado, con lo
que suelta lo que había tomado y las lecturas en cola pasan, espera 2 s sin retener nada y lo intenta de nuevo, hasta 8
veces. Con `user_user` ya tomado no queda ningún bloqueo que esperar: los dos `ALTER TABLE` (uno por tabla, con sus dos
claves; cada clave se quita y se vuelve a crear con su nombre y `DEFERRABLE INITIALLY DEFERRED`) van sobre tablas recién
creadas y vacías y duran milisegundos (de 9 a 20 ms en el ensayo con 0009), pero `user_user` sigue tomado hasta que
`migrate` confirma la migración: de 150 a 510 ms en ese ensayo, con el disco cargado. Tomar `user_user` el último es lo que
acota el parón: con los `ALTER TABLE` solos, el segundo podía esperar por su tabla con `user_user` ya tomado. Un
interbloqueo con una petición que ya leyó `user_user` y quiere leer una tabla del plan cuenta como un intento fallido.

**Peor caso de 0009:** en cada intento, las lecturas de `user_user` se paran lo que 0009 espera el bloqueo (como mucho
1 s) y, en el intento que lo consigue, además lo que tarda `migrate` en confirmar (de 150 a 510 ms en el ensayo con 0009,
con el disco cargado); como mucho 8 intentos, separados por 2 s sin bloqueo: unos 22 s en total. Sin nadie que retenga
`user_user` tampoco son milisegundos: 0009 espera a las escrituras en curso de la propia aplicación, que ya tocaron
`user_user` (en el ensayo, de 0,20 a 0,78 s; como mucho 1 s por intento), y la lectura más lenta esperó 1,21 s (0,34 y
0,42 s en las dos pasadas principales). Las de las tablas del plan, que la versión publicada no conoce, se paran durante
todo el intento. Si se agotan los intentos, porque otra transacción retiene `user_user` todo ese tiempo, `migrate` falla
sin haber cambiado nada, con un mensaje que dice qué tabla esperaba y qué hacer: `desplegar.sh` se detiene antes de
activar el código nuevo (0004 a 0008 quedan aplicadas, y la versión publicada sigue atendiendo sin problema), borra al
salir la carpeta de la versión que no activó y basta repetir el despliegue, mejor con poco tráfico.

Medido con `tests/test_zz_cuentas_0009_bloqueo_pg.py` (PostgreSQL 16, 14/11/2026 hacia las 23:55 UTC, carga de 4 con 6
núcleos), que vuelve a 0008, deja las claves como las crea Django y retiene `user_user` desde otra conexión mientras una
tercera lo lee sin parar: retenido 3,5 s desde el primer intento, 0009 terminó a los 3,53 s, con nombres y diferido
intactos, y la lectura más lenta esperó 0,98 s (de 50); retenido hasta que se rinde (3 intentos en la prueba), falló a
los 6,99 s con el mensaje, sin anotarse y con las cuatro claves como estaban, y la lectura más lenta esperó 1,00 s (de
90). Con la 0009 anterior la misma prueba falla en los dos casos: con la retención de 3,5 s, la lectura más lenta esperó
3,59 s; con la larga, `lock_timeout` a los 5 s. Si 0009 se volviera a aplicar con cuentas y lotes ya cargados, la
comprobación de cada clave recorre su tabla con el bloqueo tomado: al publicar están vacías.

Quien cambie más adelante una de esas cuatro claves con `AlterField` tiene que volver a ponerle la acción: Django 5.2 no
la conoce y recrearía la restricción sin ella.

**Dependencia corregida a mano en 0004 y 0007.** `makemigrations` puso la última de `pos`, `0035_sale_ride_diseno`. Se
cambió por `pos 0034_cliente_nacimiento_opcional`, la que ya exige `contabilidad 0001`: las tablas solo necesitan la
empresa. Con 0035, la vuelta documentada del diseño de factura (`migrate pos 0034`) arrastraría el plan de cuentas y
borraría sus tablas. `makemigrations --check --dry-run` sigue sin cambios. Quien añada la siguiente migración de
contabilidad debe mirar lo mismo.

**Convivencia durante el despliegue.** `desplegar.sh` migra antes de cambiar el código, así que la versión publicada
atiende un rato sobre la base ya migrada. No le afecta: no conoce las dos tablas nuevas, la columna `lote_id` está en una
de ellas, `tenancy 0013` no cambia el esquema, los tres permisos que `0006` añade al módulo del kardex y a los roles no
los usa y `0009` solo cambia la acción de cuatro claves de esas tablas (con ella, borrar desde esa versión a un usuario
que creó cuentas funciona). No hay columnas nuevas en tablas que ya existían.

**Vuelta del bloque a lo publicado**, sin datos nuevos, en este orden:

```
migrate contabilidad 0003_modulo_kardex
migrate tenancy 0012_accion_diseno_factura
```

Quedan pendientes las siete de la tabla. El módulo del kardex vuelve a sus tres permisos, ningún rol conserva los del plan
de cuentas y el resto del menú y de los roles queda igual. Quedan las filas de `Permission` y `ContentType` de `cuenta` e
`importacioncuentas`, inocuas. Otra ida lo deja todo como estaba. Lo recorre
`tests/test_migracion_vuelta_fase.py::test_vuelta_del_plan_de_cuentas_a_lo_publicado`, por subproceso, sobre una
instalación SQLite con menú. Vuelta solo de la importación: `migrate contabilidad 0006_permisos_plan_cuentas`; borra la
tabla de lotes con sus filas, su mapeo y su resultado, y la columna `lote_id` de las cuentas, y los archivos de los lotes
se quedan sin dueño en `privado/`: con lotes registrados, solo con la aplicación detenida y con respaldo previo de la base
y de `privado/` (ver «Restauración»).

**Las otras vueltas documentadas:**

- La de la fase (`contabilidad zero`, `tributario zero`, …, `tenancy 0006`) deshace también estas siete: la prueba espera
  48 pendientes, las 41 de antes más estas.
- La del diseño de factura (`configuracion 0003`, `pos 0034`, `tenancy 0011`) deshace además `tenancy 0013`, que va sobre
  0012. Las tablas del plan de cuentas no se tocan.

**Ida parcial después de una vuelta.** Si se deshace contabilidad por debajo de 0004 y se vuelve a aplicar solo hasta
0003, el módulo «Kardex por producto» no reaparece hasta aplicar 0006: `organizar_menu` no crea un módulo cuya lista de
permisos incluye un modelo sin migrar, y las filas de `Permission` sobreviven a la vuelta. Un `migrate` completo termina
igual que antes.

**Restauración.** La vuelta borra las cuentas y los lotes de importación. Con datos registrados, revertir es restaurar el
volcado previo y la carpeta `privado/` de `FPA_ARCHIVOS` (los archivos subidos quedan en `plan-cuentas/`, dentro de la
carpeta de cada empresa) y volver al código anterior, no `migrate` hacia atrás.

**Probado:** ida, vuelta a lo publicado y otra ida, y las vueltas de la fase y del diseño, en
`tests/test_migracion_vuelta_fase.py` (SQLite, por subproceso); la política forzada de las dos tablas en PostgreSQL
(`tests/test_rls_modelos_de_empresa.py` y las pruebas de seguridad por filas de `tests/test_cuentas.py` y
`tests/test_cuentas_importacion.py`); en PostgreSQL, la acción y el diferido de las cuatro claves de 0009 y el borrado del
usuario autor desde otra empresa y sin pasar por Django (`tests/test_cuentas.py::TestBorrarAlAutor`, que fallaba antes de
0009 con la misma restricción que el ensayo); 0009 con `user_user` retenido desde otra conexión
(`tests/test_zz_cuentas_0009_bloqueo_pg.py`, ver «Por qué 0009»); `makemigrations --check --dry-run` sin cambios. Con
la aplicación atendiendo, sobre copias del volcado diario: la ida con 0009, también con `user_user` retenido, su fallo
limpio, la vuelta con la aplicación detenida, D1, D2, la reparación de D6 y el borrado de una empresa con plan de cuentas
(«Ensayo con 0009», abajo). Que `desplegar.sh` no deje la carpeta de una versión que no quedó activa:
`tests/test_desplegar_releases.py` (punto 1 del plan).

**Ensayo con la aplicación atendiendo (14/11/2026, sobre `84d07cc`, sin 0009).** Guiones propios fuera del repositorio
(`ensayo-contable-1/guiones/`); los de la fase (`verif-firma/ensayo-fase/`) y de primera entrega no se tocaron. Tres
pasadas y una de escala, cada una sobre el último volcado diario restaurado de nuevo (12 empresas, 112 usuarios), con un
rol de base con los mismos atributos que el de producción (sin `BYPASSRLS`, dueño de las tablas), `e0f2902` atendiendo
tráfico ficticio (consultas, proformas, compras, cobros, importación de XML e inicios de sesión), el SRI simulado y
`migrate` como `desplegar.sh` más `lock_timeout=5s`. La máquina estaba cargada (6,4 a 10,9 con 6 núcleos): los tiempos
están inflados.

- Ida: `migrate` sin errores en las tres; 0 peticiones fallidas; 14,5 a 28,4 s de proceso; ninguna petición esperó por
  un bloqueo (D4: las escrituras en `user_user` y `pos_company` habrían esperado hasta 3,2 s, por las claves nuevas de
  0004 y 0007 hasta el final de cada migración; las lecturas no se bloquean).
- Vuelta del bloque (`migrate contabilidad 0003_modulo_kardex`, `migrate tenancy 0012_accion_diseno_factura`) con
  tráfico: sin errores de `migrate`, pero el `DROP TABLE` de 0007 y 0004 toma `AccessExclusiveLock` sobre `user_user` y
  luego sobre `pos_company` (hasta 1,3 s) y en una pasada hubo un interbloqueo con un cobro, que PostgreSQL abortó sin
  guardar nada (D3).
- Otra ida después de la vuelta: igual que la primera.
- Borrar usuarios: el autor de cuentas en otra empresa (D1) y, con el código anterior, cualquier autor (D2, D5): ver
  «Por qué 0009».
- `start_installation` de la versión anterior sobre la base migrada deja el módulo del kardex con su tupla vieja y a los
  roles sin `view_cuenta`, `add_cuenta` ni `change_cuenta` (D6).
- El reinicio del servicio deja de 3,5 a 13,8 s sin atender con la máquina cargada, de 15 a 27 peticiones fallidas por
  cambio (conexiones rechazadas o cortadas); no es de este bloque (D7).

**Ensayo con 0009 y la aplicación atendiendo (15/11/2026, de 00:29 a 01:13 UTC, sobre `6b7ccbf`).** Guiones propios
fuera del repositorio (`ensayo-contable-1b/guiones/`; las cifras, en `ensayo-contable-1b/resultados.json`), con el
montaje del anterior: el último volcado diario restaurado de nuevo en cada pasada principal, un rol con los atributos
del de producción, `e0f2902` atendiendo el mismo tráfico ficticio y el SRI simulado. El despliegue del ensayo sigue los
pasos, el orden y el `set -euo pipefail` de `desplegar.sh`, y esta vez `migrate` va sin `lock_timeout` añadido (0009
pone el suyo). Para retener `user_user`, otra transacción lo lee y queda abierta hasta N s después de ver a 0009 pedir
su bloqueo. La máquina estaba compartida con suites completas (carga de 7,8 a 12,2 con 6 núcleos): los tiempos están
inflados.

- Ida, dos pasadas: `migrate` sin errores (23,9 y 14,2 s) y 0 peticiones fallidas durante `migrate` y en la ventana de
  al menos 30 s con `e0f2902` sobre la base migrada. 0009 terminó en 0,30 y 0,21 s, con 1 intento que esperó 0,29 y
  0,20 s a las escrituras en curso de la aplicación; la lectura de `user_user` más lenta, 0,34 y 0,42 s.
- 0009-A, `user_user` retenido 5 s: 3 intentos, 0009 bien a los 6,0 s, la lectura más lenta 1,00 s y 0 peticiones
  fallidas.
- 0009-B, retenido 40 s: 8 intentos en 22,1 s y `RuntimeError` con el mensaje, sin cambiar nada (0009 sin anotar y las
  cuatro claves como estaban); el despliegue se detuvo en el paso 4 con `current` en `e0f2902` y la aplicación
  atendiendo, 0 peticiones fallidas y la lectura más lenta 1,00 s. Repetido sin retención: 1 intento, que esperó 0,78 s
  a las escrituras en curso, y la lectura más lenta 1,21 s. Después, `--revertir` eligió la carpeta del despliegue
  fallido (el mismo `6b7ccbf`) y, repetido, la de la repetición: alternaba entre las dos sin volver a `e0f2902`.
  Corregido en `desplegar.sh` (punto 1 del plan).
- Borrar a usuarios que crearon cuentas o lotes (D1, desde otra empresa, con la versión nueva y con `e0f2902`; D2, con
  `e0f2902`): sin errores.
- Vuelta del bloque con la aplicación detenida (48,1 y 4,2 s las dos órdenes): borra las cuentas, los lotes y `lote_id`;
  el kardex, los roles y los módulos vuelven idénticos; quedan pendientes las siete y los archivos de los lotes, sin
  dueño, en `privado/`.
- D6: `start_installation` de `e0f2902` sobre la base migrada lo reproduce y la reparación del punto 4 lo deja como dice
  su comprobación (`organizar_menu` 11,4 s y `sync_roles` 2,3 s con la máquina cargada).
- Borrar desde `/plataforma/` con `e0f2902` una empresa con plan de cuentas: 500 sin borrar nada, como dice el punto 3.
- Cambio de proceso (D7): de 3,6 a 7,7 s sin servicio y de 16 a 24 peticiones fallidas por cambio (conexiones
  rechazadas o cortadas, ningún 5xx). Un caso aislado, la segunda `--revertir` de 0009-B, con la máquina saturada (carga
  12) y un checkpoint de PostgreSQL en curso: 46,9 s y 28 fallidas. No es el rango normal; por eso se publica con la
  máquina sin otras suites corriendo.
- Producción intacta: `facturaporaqui@pruebas` con el mismo MainPID (1447381) y sin reinicios al empezar y al terminar
  cada corrida; ninguna conexión a la base publicada.

**Plan de recuperación del bloque** (además de «Restauración»):

1. Publicar con poco tráfico y con la máquina sin otras suites: la ida bloquea unos segundos las escrituras en
   `user_user` y `pos_company` (inicios de sesión, ediciones de empresa) y, en 0009, las lecturas de `user_user` (cada
   petición con sesión). Si nada retiene `user_user`, hasta 1,21 s en el ensayo: 0009 espera a las escrituras en curso
   de la propia aplicación (como mucho 1 s por intento) y retiene `user_user` hasta confirmar (de 150 a 510 ms con el
   disco cargado). Si una transacción lo retiene, hasta 1 s por intento más esa confirmación en el que lo consigue, y
   como mucho 8 intentos en unos 22 s, con 2 s sin bloqueo entre uno y otro. Si no lo consigue, `migrate` falla sin
   cambiar nada, `desplegar.sh` se detiene con la versión publicada atendiendo, borra al salir la carpeta de la versión
   que no activó y se repite el despliegue (ver «Por qué 0009»). Esa carpeta se queda solo en una primera instalación,
   sin `current`. Antes del arreglo (`4f9987f`) se quedaba siempre, y `--revertir` la tomaba por la versión anterior:
   ensayo, 0009-B. Si al salir un proceso aún trabaja dentro, la carpeta no se borra: se aparta como
   `releases/.no-activa-<nombre>` (ni `--revertir` ni la limpieza la ven) y se borra a mano cuando termine. Un `kill` al
   script espera a que termine la orden en curso (`migrate`, `collectstatic`) antes de limpiar. Lo vigila
   `tests/test_desplegar_releases.py`.

   **Del cierre del corte 1 del bloque 2 (15/11/2026).** No solo esperan las escrituras en `user_user` y `pos_company`:
   en una pasada de prueba de aquel ensayo (`prueba-2`, con `e0f2902` atendiendo) un **cobro** esperó 1,80 s por
   `user_user` mientras 0004/0007 tenían `ShareRowExclusiveLock` sobre esa tabla (C2E-2). En las pasadas principales hubo
   0 esperas de ventas, cobros y compras: depende de en qué momento cae la petición. En la pasada principal 0004 y 0007
   retuvieron `user_user` hasta 2,4 s y `pos_company` hasta 2,6 s, y en la base propia del corrector de C2E-1, hasta
   3,41 s. Un cobro, una venta o cualquier envío que escriba en `user_user` o en `pos_company` puede esperar hasta unos
   2 s, o más con la máquina cargada, durante 0004 y 0007: **publicar sin tráfico**. Desde `72a68ee`, además,
   `desplegar.sh` migra con `lock_timeout=5s` y repite `migrate` hasta 3 veces solo si una migración no consiguió un
   bloqueo o chocó en un interbloqueo (C2E-3); el `RuntimeError` de 0009 al rendirse no se repite: `desplegar.sh` sale
   con error, `current` sigue en la versión anterior y el despliegue se repite a mano cuando la otra transacción suelte
   el bloqueo (ver la nota del corte 1 del bloque 2, «Cierre del corte 1»). Un matiz de aquel ensayo: en `prueba-2` el
   muestreo fino no estaba corregido y la ruta que atribuye (el «cobro») puede ser otra petición de la misma conexión
   persistente (`CONN_MAX_AGE` 60); la espera sí fue real.

   **C2E-2 sigue en el ensayo repetido sobre `72a68ee`** (15/11/2026, una ejecución por escenario, carga de 5,2 a 10,3
   con 6 núcleos; «Ensayo repetido sobre `72a68ee`», en la nota del corte 1 del bloque 2). Sin nadie que retenga las
   tablas hubo 0 esperas de ventas, cobros y compras, y en la pasada principal 0004 y 0007 retuvieron `user_user` hasta
   0,91 s y `pos_company` hasta 1,14 s. Con `pos_company` retenida 7 s (escenario `r1`): 0004 esperó su bloqueo hasta el
   `lock_timeout` de 5 s y se cortó, y mientras tanto las sondas de escritura en `user_user` y `pos_company` esperaron
   5,0 y 4,7 s; en el intento 2, durante 0009, **un cobro y un movimiento del kardex esperaron unos 0,4–0,5 s por
   `user_user`** (407 y 401 ms en el monitor de 100 ms; 500 y 493 ms en el muestreo fino). La decisión 18a pide que el
   monitor no registre esperas de ventas, cobros ni compras. Lo que se puede esperar: durante 0009, un cobro y un
   movimiento del kardex unos 0,5 s; si 0004 o 0007 esperan un bloqueo, hasta 5 s por intento. **Recomendación: publicar
   sin tráfico, o que la propietaria acepte por escrito la excepción a 18a.**
2. Deshacer migraciones solo con la aplicación detenida o en mantenimiento, sin escrituras, y con `lock_timeout` corto
   (2 a 5 s, en `PGOPTIONS`) y reintento: con tráfico, la vuelta puede interbloquearse con una escritura (D3). Toda vuelta
   del bloque por debajo de 0007 o de 0004 borra lotes o cuentas con sus datos: con datos registrados no se deshace, se
   restaura (ver «Restauración»).
3. Volver solo el código (`desplegar.sh … --revertir`) con la base migrada: la versión anterior atiende. `--revertir`
   toma por fecha la carpeta más reciente que no es `current`; como la de un despliegue fallido ya no se queda (punto 1),
   es la de la versión que atendía antes. Con 0009 puede borrar a un usuario que creó cuentas o lotes; sin 0009 (si el
   despliegue se detuvo antes) no hay que borrar usuarios
   que crearon o editaron cuentas o lotes, y si ocurre, devolverle la membresía o borrarlo con la versión nueva. Borrar
   una empresa con plan de cuentas da 500 y no borra nada (lo impide `PROTECT`, como debe; ya lo impedían su período de
   suscripción y el `PROTECT` de los demás modelos de empresa). Desde `/plataforma/`, igual.
4. No ejecutar `start_installation` de la versión anterior sobre la base migrada: deja el módulo «Kardex por producto»
   con su tupla vieja (`view_kardex`, `add_movimientomanual`, `change_movimientomanual`) y a los roles sin
   `view_cuenta`, `add_cuenta` ni `change_cuenta` (D6). Si ocurre, la única reparación es la que hace `start_installation`
   para el menú y los roles, con el código de la versión nueva: desde su carpeta, con su entorno y
   `PGOPTIONS="-c app.platform=on"` como en `desplegar.sh`, `manage.py shell` con

   ```python
   from django.contrib.auth.models import Group, Permission
   from core.security.menu import organizar_menu
   from core.security.models import GroupModule, Module, ModuleType
   from core.tenancy.context import platform_scope
   from core.tenancy.roles import strip_platform_modules, sync_roles
   with platform_scope():
       organizar_menu(ModuleType, Module, Permission)   # primero: devuelve al módulo del kardex su tupla de seis
       sync_roles(Group, Module, GroupModule)           # después: los roles toman los permisos de sus módulos
       strip_platform_modules(Group, GroupModule)       # como start_installation
   ```

   En ese orden: `sync_roles` reparte los permisos que tiene cada módulo, y antes de `organizar_menu` el del kardex
   todavía tiene la tupla vieja. Medido en el ensayo con la versión nueva y la máquina cargada: 3,3 a 9,6 s
   `organizar_menu` y 1,1 a 1,9 s `sync_roles`. Para comprobar que quedó bien, a continuación y con los mismos imports:

   ```python
   with platform_scope():
       print(sorted(Module.objects.get(url='/contabilidad/kardex/').permissions.values_list('codename', flat=True)))
       print({g.name: sorted(g.permissions.filter(codename__in=['view_cuenta', 'add_cuenta', 'change_cuenta'])
                             .values_list('codename', flat=True)) for g in Group.objects.order_by('name')})
   # ['add_cuenta', 'add_movimientomanual', 'change_cuenta', 'change_movimientomanual', 'view_cuenta', 'view_kardex']
   # Propietario, Administrador y Contador: add_cuenta, change_cuenta y view_cuenta; Consulta: view_cuenta;
   # Vendedor y Cliente: ninguno
   ```

   No sirve `migrate contabilidad 0005` seguido de `migrate contabilidad`: volver a 0005 deshace también 0007, así que
   borra la tabla `contabilidad_importacioncuentas` (todos los lotes con sus filas, su mapeo y su resultado) y la columna
   `lote_id` de las cuentas, deja sin dueño los archivos privados de los lotes y toma sobre `user_user` y `pos_company`
   los bloqueos de la vuelta (D3). Si alguna vez se elige esa vía por otra razón, solo con la aplicación detenida y con
   respaldo previo de la base y de `privado/`.
5. El corte del reinicio (D7) se anuncia o se evita con una recarga sin corte de gunicorn: queda fuera del bloque. En el
   ensayo con 0009, de 3,6 a 7,7 s por cambio; el caso aislado de 46,9 s fue con la máquina saturada (carga 12 y un
   checkpoint de PostgreSQL): publicar con la máquina sin otras suites.

**No probado:**

- 0009 con la versión nueva atendiendo (si alguna vez se aplicara con `6b7ccbf` ya activa, por ejemplo después de una
  vuelta a 0008): el ensayo atendía con `e0f2902`, que no lee las tablas del plan, así que no midió las peticiones de
  C1–C3, que esperan durante todo el intento.
- 0004 y 0007 con una transacción que retenga `user_user` o `pos_company` (una escritura larga): `desplegar.sh` no pone
  `lock_timeout` a `migrate`, así que esperarían lo que dure, con las escrituras de esas tablas en cola detrás. En los
  dos ensayos nadie las retuvo. **Desde `72a68ee`** (C2E-3, cierre del corte 1 del bloque 2) `migrate` va con
  `lock_timeout=5s` y se intenta hasta 3 veces, con 10 s de pausa, solo ante `55P03`/`40P01`: 0004 y 0007 esperan como
  mucho 5 s por intento, la cortada no cambia nada y lo que esperaba detrás pasa. Probado en el ensayo repetido sobre
  `72a68ee` (escenario `r1`, con tráfico ficticio y `pos_company` retenida 7 s): 0004 se cortó a los 5 s, «se repite
  migrate en 10 s», el intento 2 fue bien y no falló ninguna petición. Lo que sigue sin medir es el reintento con tráfico
  real.
- La base real.

**Choque conocido al fusionar con `fase/primera-entrega`.** Esa rama trae `tenancy/0013_acciones_borrador_factura`, también
sobre `tenancy 0012`, y cambia el conteo de `tests/test_migracion_vuelta_fase.py`. Al unirlas, una de las dos `0013` pasa
a `0014` sobre la otra, con sus `choices` completas, y el conteo y las listas de la prueba se suman. Si primera entrega
se publica antes y este bloque encima (su acción como `tenancy 0014_acciones_plan_cuentas`), la vuelta de primera entrega
(`migrate tenancy 0012_accion_diseno_factura`, en su `plan-de-despliegue.md`) deshace también la 0014 del bloque y deja
aplicadas `contabilidad 0004-0009`: un estado mixto. En ese orden, para volver por debajo de primera entrega va primero la
vuelta del bloque (`migrate contabilidad 0003_modulo_kardex`, `migrate tenancy 0013_acciones_borrador_factura`), que borra
las cuentas y los lotes (con datos registrados, «Restauración»), y después la de primera entrega, o se restaura el
volcado. La guarda de convivencia de esa rama
(`tests/test_convivencia_versiones.py`, `DE_ESTA_ENTREGA`) recorre solo sus migraciones: al unirlas hay que añadirle
`contabilidad 0004-0009` y la `tenancy` del bloque; `NO_NULAS_AGREGADAS` no cambia, porque la única columna que el bloque
agrega (`cuenta.lote`) admite nulos y va en una tabla nueva.

**Con `fase/contable-2-apertura`.** Esa rama, sin publicar y en curso, parte de `84d07cc` y numera sus migraciones de
contabilidad desde `0009` sobre `0008`. Al llevarla sobre este bloque, su primera migración tiene que depender de
`0009_anular_autores_en_la_base` (si no, `contabilidad` queda con dos hojas y `migrate` se niega).

## Nota (14/11/2026) — bloque 2 del cierre contable, corte 1: libro diario y apertura, 7 migraciones, 8 desde el cierre (sin publicar)

Rama `fase/contable-2-apertura`, que salió del bloque 1 en `84d07cc` (código final del corte `a5bedf4`) y el 15/11/2026 se
unió al bloque 1 final (`fase/contable-1-cuentas`, `8a421b3`) sin rebase: las seis de contabilidad de este corte, que
nacieron como `0009`–`0014`, son ahora `0010`–`0015` con los mismos sufijos (ver «Unión con el bloque 1 final», al final
de esta nota). Lo publicado sigue siendo `e0f2902` (`contabilidad 0003`, `tenancy 0012`); el bloque 1 tampoco está
publicado. Todas las migraciones de esquema del bloque se crean en este corte: las tablas de auxiliares, cartera inicial,
ajustes, cobertura por mes y documentos históricos (Partes C a F) nacen vacías y el corte 2 solo añade código.

**Desde el cierre del corte (15/11/2026, código `72a68ee`) son ocho:** la nueva `contabilidad
0016_claves_hacia_tablas_anteriores` crea al final, en una transacción corta, las 26 claves foráneas hacia tablas que ya
existían, que `0011` y `0012` dejan de crear (hallazgo C2E-1). El esquema final es el mismo. Qué cambia, por qué, las
cifras, las vueltas, el despliegue y la receta de integración con `fase/primera-entrega`: «Cierre del corte 1», al final de
esta nota.

| # | Migración | Qué hace | Vuelta |
|---|---|---|---|
| 1 | `contabilidad/0010_clases_de_cuenta` | dos columnas en `contabilidad_cuenta` (tabla del bloque 1), `clase` y `auxiliar`, `CharField(12)` con `db_default=''`, y dos CHECK: `cuenta_clase_valida` (los siete valores) y `cuenta_auxiliar_solo_movimiento` (`tipo = 'movimiento' OR auxiliar = ''`) | quita los CHECK y las columnas |
| 2 | `contabilidad/0011_libro_diario` | ocho tablas: `iniciocontable` (una por empresa; es el candado del libro), `ejerciciocontable`, `periodocontable`, `asiento`, `lineaasiento`, `saldocuentames`, `contabilizacion` y `registroclave`, con sus UNIQUE (también los parciales: un asiento de apertura vigente, un reverso por asiento, un asiento y un expediente vigentes por origen), CHECK e índices; permisos declarados `view_asiento`, `add_asiento`, `change_asiento`, `change_reverso_asiento`, los del período y los del ejercicio. Desde el cierre, sin sus 11 claves hacia tablas que ya existían (`company` de las ocho tablas, `lineaasiento.cuenta`, `saldocuentames.cuenta` y `contabilizacion.tesoreria_cuenta`): `AplazarClaves`, su última operación, las deja para 0016 (solo PostgreSQL) | borra las tablas (desde el cierre, sin tocar `pos_company` ni `contabilidad_cuenta`) |
| 3 | `contabilidad/0012_apertura` | once tablas: `apertura`, `lineaapertura`, `importacionapertura`, `respaldoapertura`, `ajusteapertura`, `auxiliarapertura`, `partidabancoapertura`, `aplicacionauxiliar`, `vinculohistorico`, `coberturaperiodo` y `eventoapertura`, con sus UNIQUE parciales (una confirmada y una en preparación por empresa), CHECK e índices; permisos `add_apertura`, `view_apertura`, `change_confirmacion_apertura`, `add_aplicacionauxiliar`, `change_aplicacionauxiliar`. Desde el cierre, sin sus 15 claves hacia tablas que ya existían (`company` de las once tablas, `auxiliarapertura.cuenta`, `auxiliarapertura.movimiento_kardex`, `aplicacionauxiliar.cuenta_contrapartida` y `lineaapertura.cuenta`), que deja para 0016 | borra las tablas (desde el cierre, sin tocar `pos_company`, `contabilidad_cuenta` ni `contabilidad_movimientomanual`) |
| 4 | `contabilidad/0013_rls_libro_apertura` | RLS `fpa_empresa` ENABLE + FORCE en las 19 tablas (solo PostgreSQL) | quita las políticas |
| 5 | `contabilidad/0014_libro_inmutable` | seis funciones y sus disparadores (solo PostgreSQL): `fpa_linea_solo_insercion`, `fpa_linea_en_asiento_abierto`, `fpa_asiento_solo_sello_o_reverso`, `fpa_asiento_nace_abierto`, `fpa_asiento_sellado` (diferido, al confirmar la transacción) y `fpa_evento_solo_insercion`. Hacen el libro y la historia de la apertura de solo inserción también por SQL | `DROP TRIGGER` y `DROP FUNCTION` |
| 6 | `contabilidad/0015_permisos_apertura` | cuelga del módulo «Kardex por producto» los seis permisos que el bloque reparte (`view_asiento`, `view_apertura`, `add_apertura`, `change_confirmacion_apertura`, `add_aplicacionauxiliar`, `change_aplicacionauxiliar`) y ejecuta `sync_roles`: Propietario, Administrador y Contador, los seis; Consulta, los dos de ver; Vendedor y Cliente, nada. Ni módulos nuevos ni cambios del menú. Los permisos de bloques posteriores no cuelgan de ningún módulo: nadie los recibe | quita esos seis del módulo y de los roles, por ids en las tablas intermedias; las filas de `Permission` se quedan |
| 7 | `contabilidad/0016_claves_hacia_tablas_anteriores` (nueva en el cierre) | crea las 26 claves aplazadas por 0011 y 0012, con el nombre y la definición de siempre (`DEFERRABLE INITIALLY DEFERRED`, sin acción al borrar): `SET LOCAL lock_timeout = '1000ms'` y, en cada intento y en su punto de guardado, `LOCK TABLE contabilidad_cuenta, contabilidad_movimientomanual, pos_company IN SHARE ROW EXCLUSIVE MODE` y los 26 `ALTER TABLE`; hasta 8 intentos con 2 s de pausa; si se agotan, `migrate` falla sin cambiar nada. No repite las claves que ya existan. En SQLite no hace nada | `SET CONSTRAINTS … IMMEDIATE; ALTER TABLE … DROP CONSTRAINT` de las 26, con `LOCK … IN ACCESS EXCLUSIVE MODE` y los mismos intentos |
| 8 | `tenancy/0014_acciones_apertura` | las 25 acciones de auditoría del bloque (también las del corte 2) en `AuditLog.action` (solo `choices`) | solo `choices` |

**Ninguna restricción hacia la operación.** Leído con `sqlmigrate`: las claves foráneas de las tablas nuevas van solo a
`pos_company` (la empresa, como en toda tabla por empresa), entre tablas de `contabilidad` y a
`contabilidad_movimientomanual` (el kardex). Ninguna hacia `pos_*` salvo la empresa, `importacion_*`, `comprobantes_*`,
`cobros_*`, `adjuntos_*` ni el usuario: los autores son el par `<rol>_por_id` (entero sin FK) y `<rol>_por_nombre`, y las
referencias a clientes, proveedores, productos, cuentas por cobrar o por pagar y documentos importados son enteros con
índice, sin FK. Borrar una venta, una compra, una cuenta por cobrar, un producto o un usuario no lee ni escribe nada de
contabilidad (`tests/test_convivencia_versiones.py`, por SQL directo). El SQL leído está en
`/root/invoice15/contable/registros/bloque2-c1-sqlmigrate-sqlite.sql` (fuera del repositorio, leído antes de la unión, con
la numeración anterior; en SQLite el `AddField` de 0010 reconstruye `contabilidad_cuenta` y repite sus FK del bloque 1, que
no son nuevas). Desde el cierre, las claves hacia `pos_company`, `contabilidad_cuenta` y `contabilidad_movimientomanual` no
las crean 0011 y 0012 sino 0016; sigue siendo cierto que no hay ninguna hacia la operación ni hacia el usuario.

**Orden.** Un solo `migrate --noinput`. Las de contabilidad van en fila, de 0010 a 0015 (y, desde el cierre, 0016, que
depende solo de `('contabilidad', '0015_permisos_apertura')`), detrás de la 0009 del bloque 1;
`tenancy 0014` va sobre `tenancy 0013` (bloque 1) y no depende de ellas. Dependencias corregidas a mano, como en el bloque
1: `0010` depende solo de `contabilidad 0009_anular_autores_en_la_base` (la última del bloque 1), y `0011` y `0012` de
`pos 0034_cliente_nacimiento_opcional`, no de la `pos 0035` que proponía
`makemigrations`: así la vuelta documentada del diseño de factura (`migrate pos 0034`) no arrastra el libro ni la apertura.
`makemigrations --check --dry-run`: sin cambios.

**Convivencia durante el despliegue** (la versión anterior atiende un rato sobre la base ya migrada): no conoce las 19
tablas; las dos columnas nuevas de `contabilidad_cuenta` llevan `db_default=''`, así que un INSERT que no las nombra (el
código del bloque 1, o uno por SQL) recibe `''` y cumple los dos CHECK (`tests/test_convivencia_versiones.py` comprueba
que toda columna añadida a una tabla existente es nula o con `db_default`); los disparadores solo están en tablas nuevas;
`tenancy 0014` no cambia el esquema. Lo que toca tablas que la versión anterior lee a cada petición es `0015_permisos_apertura`
(permisos del módulo y de los roles), como `0006` del bloque 1.

**Corregido en el cierre (C2E-1): la frase de arriba no era cierta.** `0011` y `0012` tomaban `ShareRowExclusiveLock` sobre
`pos_company` (y `0012` también sobre `contabilidad_movimientomanual`) desde su primera clave foránea hasta confirmar: en el
ensayo del cierre, con `e0f2902` atendiendo, 6,0 y 12,0 s sobre `pos_company` y 8,1 s sobre
`contabilidad_movimientomanual`, y un movimiento manual del kardex esperó hasta 5,47 s. Desde `72a68ee` las que tocan
tablas que usa la versión anterior son `0015` (solo filas de permisos) y `0016` (las claves foráneas: como mucho 1 s por
intento esperando el bloqueo, más los 26 ALTER y la confirmación). Cifras de antes y de después en «Cierre del corte 1».

**Ida en el ensayo.** Comprobar que el rol de la aplicación crea las seis funciones de `0014` (en las pruebas las crea el
rol `fpa_dev`, sin superusuario). `fpa_asiento_sellado` no usa `SET` en su definición precisamente por eso: PostgreSQL no
deja fijar así una variable propia a quien no es superusuario.

**Vuelta del bloque a lo publicado**, sin datos nuevos, en este orden:

```
migrate contabilidad 0003_modulo_kardex
migrate tenancy 0012_accion_diseno_factura
```

Con la primera orden deshace `contabilidad 0016` a `0004`: las siete de contabilidad de este corte (seis hasta el cierre;
desde `72a68ee`, 0016 la primera) y después las seis del bloque 1. Con la segunda, `tenancy 0014` (de este corte) y
`tenancy 0013` (del bloque 1). Quedan pendientes quince: las ocho del corte y las siete del bloque 1 (catorce antes del
cierre). Para volver solo hasta el final del bloque 1:

```
migrate contabilidad 0009_anular_autores_en_la_base
migrate tenancy 0013_acciones_plan_cuentas
```

El módulo del kardex se queda con lo suyo y con lo del plan de cuentas, ningún rol conserva los permisos del libro ni de la
apertura y el resto del menú y de los roles queda igual; otra ida lo deja todo como estaba. Lo recorre
`tests/test_migracion_vuelta_fase.py::test_vuelta_del_plan_de_cuentas_a_lo_publicado` (primero hasta el bloque 1, después
hasta lo publicado), por subproceso, sobre una instalación SQLite con menú. La vuelta de `0014` y la de `0013` en PostgreSQL
(quitar y volver a poner los disparadores y las políticas) las recorre `tests/test_zz_libro_inmutable_pg.py`. Qué bloquea
0016 a la vuelta: «Cierre del corte 1», «Vueltas con 0016».

**Las otras vueltas documentadas:**

- La de la fase (`contabilidad zero`, …, `tenancy 0006`) deshace también estas siete: la prueba espera 55 pendientes, las
  48 de antes (47 más la 0009 del bloque 1) y estas. Desde el cierre, 56: también 0016.
- La del diseño de factura (`configuracion 0003`, `pos 0034`, `tenancy 0011`) deshace además `tenancy 0014`, que va sobre
  0013 y esta sobre 0012. Las tablas del libro y de la apertura no se tocan (`sin_diseno` de la prueba incluye
  `tenancy.0014_acciones_apertura`).

**Recuperación que conserva lo posterior: vuelta solo de código** (`deploy/scripts/desplegar.sh --revertir`). Es la vuelta
para después de usar el bloque: la base queda migrada y el código anterior sigue atendiendo sobre ella. Ventas, cobros,
compras, emisión y kardex no dependen de nada de contabilidad, así que siguen igual y nada de lo registrado después de
publicar se pierde; el libro, la apertura y sus archivos quedan en la base, inaccesibles hasta volver a publicar el bloque.
Lo que vale mientras dure depende de cuál sea el código anterior (separado en el cierre, H9):

- **Si el anterior es el bloque 1 publicado** (los bloques se publican por separado), dos límites:
  - El código anterior no conoce `clase` ni `auxiliar`: cambiar a grupo una cuenta de movimiento que tiene auxiliar choca
    con el CHECK `cuenta_auxiliar_solo_movimiento` y la petición falla (no se guarda nada).
  - El código anterior no sabe qué cuentas tienen movimientos en el libro o en la apertura: podría desactivar una o
    pasarla a grupo. Las líneas ya escritas no cambian (el libro es de solo inserción), pero al volver a publicar el bloque
    esa cuenta quedaría inactiva o de grupo con líneas. Mientras dure la vuelta, no tocar el plan de cuentas.
- **Si el anterior es `e0f2902`** (los bloques 1 y 2 publicados juntos; es el anterior que fija hoy la decisión 18a,
  porque el bloque 1 tampoco está publicado): ese código no tiene el plan de cuentas ni ninguna de sus rutas, así que esos
  dos límites no aplican, y el plan de cuentas, el libro, la apertura y sus archivos quedan en la base sin ruta ni
  pantalla. Valen los límites del **punto 3 del plan de recuperación del bloque 1** (nota del 14/11 del bloque 1): borrar
  una empresa con plan de cuentas da 500 y no borra nada, también desde `/plataforma/`, y con 0009 borrar a un usuario que
  creó cuentas o lotes funciona; y el punto 4: no ejecutar `start_installation` de la versión anterior sobre la base
  migrada. Es la vuelta que recorrió el ensayo del cierre: ventas, cobros, compras y kardex siguieron, no se perdió nada y
  la única petición fallida fue ese 500 («Cierre del corte 1», «Ensayo del cierre»).

El ensayo de la decisión 18 (con la versión publicada atendiendo, y la vuelta de solo código después de confirmar una
apertura) lo ejecuta el orquestador al cerrar el corte; no está hecho en esta nota. **Hecho el 15/11/2026 sobre `6efad50`**
(antes de 0016 y del `desplegar.sh` nuevo): «Cierre del corte 1», «Ensayo del cierre». **Repetido el 15/11/2026 sobre
`72a68ee`** (con 0016 y el `desplegar.sh` nuevo; `7a5c567` no toca migraciones ni despliegue): «Ensayo repetido sobre
`72a68ee`», también en «Cierre del corte 1».

**Restauración, último recurso.** `deploy/scripts/restaurar.sh <volcado> <versión anterior> [--ejecutar]` vuelve la base, el
código y los estáticos al volcado previo y **pierde todo lo registrado después** (ventas, cobros, compras, la apertura y sus
archivos). `migrate` hacia atrás con datos nuevos tampoco sirve: borraría el libro y la apertura (los archivos de lotes y respaldos quedan en
`privado/empresas/<uuid de la empresa>/apertura/` de `FPA_ARCHIVOS`, que la vuelta no borra; restaurar exige también esa
carpeta).

**Probado:** ida, vuelta al bloque 1, vuelta a lo publicado y otra ida, y las vueltas de la fase y del diseño, en
`tests/test_migracion_vuelta_fase.py` (SQLite, por subproceso, en las dos suites); las políticas forzadas de las 19 tablas
(`tests/test_rls_modelos_de_empresa.py` y `tests/test_rls_libro_apertura.py`, PostgreSQL); los disparadores y su vuelta
(`tests/test_zz_libro_inmutable_pg.py`); convivencia de columnas y borrados por SQL (`tests/test_convivencia_versiones.py`);
`makemigrations --check --dry-run` sin cambios. Desde el cierre, además: la guarda estática
`tests/test_convivencia_versiones.py::test_claves_hacia_tablas_anteriores_solo_en_la_migracion_corta_del_final` (SQLite y
PostgreSQL), que falla con `6efad50` con las 26 claves sin aplazar; `tests/test_zz_claves_anteriores_pg.py` (PostgreSQL,
marca `tiempos`), que hace la vuelta del corte y otra ida, mira tras cada sentencia de `migrate` los bloqueos fuertes de
su propia transacción y exige que solo 0016 bloquee lo publicado, solo para sus ALTER y en menos de 2,5 s, con las claves
iguales a las de antes, y que con `pos_company` ocupada 0016 termine al primer intento libre o se rinda limpio (con
`6efad50` falla en la vuelta de 0011 y 0012); `tests/test_zz_cuentas_0009_bloqueo_pg.py`, que al volver a 0008 deshace y
rehace también 0016; y `tests/test_desplegar_releases.py` con el reintento de `migrate` (13 casos).

**No probado:** el ensayo sobre una copia del respaldo de producción con la aplicación atendiendo y la vuelta de solo código
con el código anterior (decisión 18; los guiones de `ensayo-pe/guiones/` siguen apuntando a la vuelta anterior a la fase y
no se tocaron), y la base real. Al cierre, el ensayo y la vuelta de solo código se hicieron sobre `6efad50` con guiones
propios (`ensayo-contable-2c1/guiones/`), y se repitieron sobre `72a68ee` (0016 y el `desplegar.sh` nuevo) con
`guiones-2/`, sobre una copia del volcado diario y con tráfico ficticio («Ensayo repetido sobre `72a68ee`»). Siguen sin
probar la base real, el reintento de `desplegar.sh` con tráfico real (en el ensayo se probó con tráfico ficticio), la
medida de 0016 con la máquina tranquila, las dos salvedades de la vuelta de solo código con el bloque 1 publicado (no
aplican con `e0f2902`) y el saldo inicial del kardex desde la apertura (corte 2).

**Choque conocido al integrar con `fase/primera-entrega`** (no se hizo rebase ni fusión): esa rama trae
`tenancy/0013_acciones_borrador_factura`, también sobre `tenancy 0012`, e `importacion 0008-0009`. Aquí `tenancy 0013`
es del bloque 1 y `0014` de este corte. Al integrar, las de tenancy se renumeran en fila (las tres sobre la anterior,
cada una con las `choices` completas de todas), y se suman el conteo y las listas de
`tests/test_migracion_vuelta_fase.py` (`56` desde el cierre, `55` antes; `sin_diseno`, `BLOQUE_2`) y lo que esa rama
traiga en `tests/test_convivencia_versiones.py`. Las de contabilidad no chocan con esa rama. Con el cierre del bloque 1,
que trae su propia `contabilidad 0009_anular_autores_en_la_base`, chocaban: está resuelto en la unión de abajo. Al
cierre del corte se ensayó la integración en un worktree desechable; la receta, ya con 0016 (conteo 60,
`DE_ESTA_ENTREGA` 19), está en «Cierre del corte 1», «Receta de integración con `fase/primera-entrega`».

### Unión con el bloque 1 final (15/11/2026)

`git merge --no-ff fase/contable-1-cuentas` (`8a421b3`) sobre `98b0a27`, sin rebase. La 0009 del bloque 1 se queda con su
número (ya estaba ensayada y documentada así) y las de este corte pasan a la siguiente libre, en fila, con `git mv` y los
mismos sufijos:

| Antes (rama del corte, sobre `0008`) | Ahora (sobre `0009_anular_autores_en_la_base`) |
|---|---|
| `contabilidad/0009_clases_de_cuenta` | `contabilidad/0010_clases_de_cuenta`, que depende de `('contabilidad', '0009_anular_autores_en_la_base')` |
| `contabilidad/0010_libro_diario` | `contabilidad/0011_libro_diario` (sobre `0010_clases_de_cuenta` y `pos 0034`) |
| `contabilidad/0011_apertura` | `contabilidad/0012_apertura` (sobre `0011_libro_diario` y `pos 0034`) |
| `contabilidad/0012_rls_libro_apertura` | `contabilidad/0013_rls_libro_apertura` |
| `contabilidad/0013_libro_inmutable` | `contabilidad/0014_libro_inmutable` |
| `contabilidad/0014_permisos_apertura` | `contabilidad/0015_permisos_apertura` |
| `tenancy/0014_acciones_apertura` | sin cambio: va sobre `tenancy/0013_acciones_plan_cuentas`, que el bloque 1 ya traía en `84d07cc` |

`contabilidad` queda con una sola hoja (`0015_permisos_apertura`) y `tenancy` con una (`0014_acciones_apertura`). Ni el
bloque 1 ni este corte están publicados, así que la renumeración no toca ninguna base de servicio. Una base de desarrollo o
de ensayo que tuviera aplicada la numeración anterior (`contabilidad 0009_clases_de_cuenta` a `0014_permisos_apertura`) se
vuelve antes a `contabilidad 0008` con el código anterior a la unión, o se crea de nuevo: con el código unido, Django no
conoce esos nombres, querría aplicar de 0009 a 0015 y fallaría en 0010, porque las columnas ya existen.

Lo que se comprobó al unir:

- **Las claves de quién de 0009.** Ninguna migración de este corte hace `AlterField` (ni `RemoveField` ni `RenameField`)
  sobre `creada_por`/`actualizada_por` de `Cuenta` ni `creado_por`/`confirmado_por` de `ImportacionCuentas`: 0010 añade
  `clase` y `auxiliar` y dos CHECK, y las demás crean tablas nuevas. En PostgreSQL esas cuatro claves siguen con
  `ON DELETE SET NULL` y diferidas después de 0015 (`tests/test_cuentas.py::TestBorrarAlAutor`, que corre con todo
  migrado), y `tests/test_convivencia_versiones.py` falla si una migración posterior a 0009 toca una de ellas.
- **SQLite.** 0009 no hace nada allí; el `AddConstraint` de 0010 reconstruye `contabilidad_cuenta` como antes, con las
  mismas FK del bloque 1 (las ida y vuelta de `tests/test_migracion_vuelta_fase.py` pasan por ella).
- **La vuelta al bloque 1** es ahora `migrate contabilidad 0009_anular_autores_en_la_base`; la de la fase espera 55
  pendientes (56 desde el cierre, con 0016).
- **`tests/test_zz_cuentas_0009_bloqueo_pg.py`** (bloque 1) vuelve contabilidad a `0008` para medir 0009 con `user_user`
  retenido: con este corte encima eso deshace también 0010–0015 (y, desde el cierre, 0016; las 19 tablas, sus
  políticas, los seis disparadores y sus funciones y los permisos del módulo) y, al terminar, migra a las hojas del
  grafo, que las rehace.

### Cierre del corte 1 (15/11/2026)

Al cerrar el corte se hicieron, sobre `6efad50` (la rama unida con el bloque 1 final), la revisión independiente, el
ensayo de la decisión 18 con la versión publicada atendiendo, el recorrido en navegador y una integración de prueba con
`fase/primera-entrega`. Lo que toca a las migraciones y al despliegue se corrigió en dos ramas hechas desde `6efad50` y
unidas sin rebase: `fix/c2c1-migraciones` (`9826cd0`, `4c052a0` y `6f27265`; unión `19c4110`) y `fix/c2c1-despliegue`
(`85a8e10`; unión `72a68ee`). Las otras dos ramas de correcciones (`fix/c2c1-apertura` y `fix/c2c1-importar`) no traen
migraciones: `makemigrations --check --dry-run` sale limpio en las cuatro. La verificación del cierre dejó una corrección
más, `7a5c567` (los controles en el código o el rubro de una fila del lote de la apertura, DOC44-2), que solo toca
`core/contabilidad/apertura_importar.py` y su prueba: ni migraciones ni despliegue. **Código final del corte:
`7a5c567`** (las correcciones de migraciones y despliegue, en `72a68ee`), sin `push` y sin publicar.

#### 0016 y `AplazarClaves`: las claves hacia tablas anteriores, al final y en una transacción corta (C2E-1)

**Por qué.** En PostgreSQL, Django crea las claves foráneas de un `CreateModel` al final de la migración (en
`deferred_sql`, mezcladas con los índices de esas columnas), y cada una toma `ShareRowExclusiveLock` sobre la tabla a la
que apunta. Ese bloqueo choca con toda escritura en esa tabla (no con las lecturas) y dura hasta que la migración
confirma. En `0011_libro_diario` la primera clave hacia `pos_company` es la sentencia 48 de 88 (contando `BEGIN` y
`COMMIT`), y el bloqueo dura 41 sentencias, de ella al `COMMIT`, ambos incluidos; en `0012_apertura` es la 81 de 153, y
dura 73. La de `auxiliarapertura.movimiento_kardex`
hacía lo mismo con `contabilidad_movimientomanual` (SQL registrado por el corrector en
`/root/invoice15/c2e1-medicion/sqlmigrate-base-0011.sql` y `-0012.sql`). Medido:

- Ensayo del cierre (pasada `principal-1`, 15/11 de 08:38 a 08:54 UTC, carga de 6,3 a 4,98 con 6 núcleos; `e0f2902`
  atendiendo): `0011` duró 28,2 s y retuvo `pos_company` 6,0 s; `0012` duró 53,5 s y retuvo `pos_company` 12,0 s y
  `contabilidad_movimientomanual` 8,1 s. La sonda de escritura en `pos_company` esperó 12,04 s; los movimientos manuales
  del kardex de `e0f2902` (`POST /contabilidad/api/kardex/movimientos/`), 55 muestras con un máximo de 5,47 s (en la
  segunda ida, 36 muestras y 3,6 s). Ventas, cobros y compras: 0 esperas. Registro:
  `/root/invoice15/ensayo-contable-2c1/registros/principal-1/resumen.json`.
- Corrector, en una base propia con datos ficticios (`fpa_c2e1`, rol sin superusuario ni `BYPASSRLS`), con una sonda de
  `pg_locks` cada 50 ms y escritores y un lector cada 50 ms, sobre `6efad50` (de 10:22:15 a 10:26:11 UTC, carga de 4,89
  a 7,73): a la ida, `0011` retuvo `pos_company` 10,43 s (ventana de 10,89 s con 41 sentencias dentro) y `0012`
  retuvo `pos_company` 9,03 s y `contabilidad_movimientomanual` 7,12 s (ventana de 9,29 s, 73 sentencias); en la otra
  ida, 4,86 s, 10,68 s y 8,82 s. La escritura más lenta en `pos_company` esperó 10,8 s y la de
  `contabilidad_movimientomanual`, 8,9 s. A la vuelta, el `DROP TABLE` de 0012 y de 0011 tomaba `AccessExclusiveLock`
  sobre `pos_company` (0,25 y 0,20 s; ventanas de 0,58 y 0,52 s), que para también las lecturas: el lector esperó hasta
  377 ms.

La nota del corte decía que la única migración que tocaba tablas de la versión anterior era `0015`: no era cierto.

**Cómo queda** (`core/contabilidad/migrations/_claves_aplazadas.py`; el `_` del nombre hace que el cargador de Django no
lo tome por una migración):

- `AplazarClaves(claves=[(modelo, campo)…])` es la última operación de `0011` (11 claves) y de `0012` (15). En
  PostgreSQL quita de `deferred_sql` exactamente esas claves foráneas y, si no las encuentra todas tal como las generó
  Django, falla sin migrar («AplazarClaves: Django no dejó para el final estas claves foráneas: … No se aplazó nada.»).
  En SQLite no hace nada: allí la clave va dentro del `CREATE TABLE`, como antes.
- `CrearClavesAplazadas(claves=…)` es la única operación de la nueva `0016_claves_hacia_tablas_anteriores`, que depende
  solo de `('contabilidad', '0015_permisos_apertura')`. Crea las 26 claves con `_create_fk_sql` y el mismo sufijo de
  Django, así que el SQL y los nombres son los de siempre (`DEFERRABLE INITIALLY DEFERRED`, sin acción al borrar). Como
  `0009` con `user_user`: primero `SET LOCAL lock_timeout = '1000ms'` (para toda la transacción de la migración); después,
  en cada intento y dentro de su propio punto de guardado,
  `LOCK TABLE contabilidad_cuenta, contabilidad_movimientomanual, pos_company IN SHARE ROW EXCLUSIVE MODE` y los 26
  `ALTER TABLE … ADD CONSTRAINT`. Un `55P03` (lock_timeout) o un `40P01` (interbloqueo) cuenta como intento fallido:
  vuelve al punto de guardado, espera 2 s sin retener nada y lo intenta otra vez, hasta 8 veces (peor caso, unos 22 s,
  como 0009). Si se agotan, `migrate` falla sin cambiar nada: «contabilidad, claves foráneas aplazadas: en 8 intentos de
  1 s no se consiguió el bloqueo de contabilidad_cuenta, contabilidad_movimientomanual, pos_company para crear sus
  claves foráneas, porque otra transacción lo retiene. No se cambió nada: repite `migrate` (o el despliegue), mejor con
  poco tráfico.» (hacia atrás dice «para quitar»).
- No repite las claves que ya existan: una base migrada con `6efad50` (con las claves creadas por 0011 y 0012) aplica
  0016 sin cambiar nada (lo vio el corrector en la primera pasada de su guion de esquema). La vuelta desde ahí también
  funciona.
- Hacia atrás quita las que existan (`SET CONSTRAINTS … IMMEDIATE; ALTER TABLE … DROP CONSTRAINT`) con
  `LOCK … IN ACCESS EXCLUSIVE MODE` y los mismos intentos; así la vuelta de 0012 y 0011 borra sus tablas sin tocar
  `pos_company`, `contabilidad_cuenta` ni `contabilidad_movimientomanual`.
- `sqlmigrate contabilidad 0016` enseña el `SET LOCAL`, el `LOCK TABLE` y los 26 `ALTER TABLE`, pero no el bucle de
  intentos. Las dos operaciones no se eliden al aplastar migraciones.
- Las 26 claves: `company` en las 19 tablas del corte; seis hacia `contabilidad_cuenta` (`lineaasiento.cuenta`,
  `saldocuentames.cuenta`, `contabilizacion.tesoreria_cuenta`, `auxiliarapertura.cuenta`,
  `aplicacionauxiliar.cuenta_contrapartida` y `lineaapertura.cuenta`); y `auxiliarapertura.movimiento_kardex`, hacia
  `contabilidad_movimientomanual`. Las de `contabilidad_cuenta` (del bloque 1, sin publicar) también se aplazan: así
  encaja con el criterio de la guarda («anterior» es toda tabla que no crea un `CreateModel` de los bloques 2 a 6) y el
  corte no retiene el plan de cuentas si el bloque 1 se publica antes, por separado. Con `e0f2902` no cambia nada.

**Mismo esquema.** El corrector comparó en PostgreSQL (desde lo publicado, con cada código) y en SQLite (desde cero), con
los resultados en `/root/invoice15/c2e1-medicion/esquema/`: `pg_dump --schema-only` de toda la base idéntico (11 481
líneas, 277 FOREIGN KEY, quitadas las líneas `\restrict` aleatorias); el catálogo de las tablas `contabilidad_*`
idéntico (457 columnas, 198 restricciones con su diferido y su acción, 165 índices, 6 disparadores, 23 políticas, 23
tablas con RLS ENABLE/FORCE y el md5 de las 6 funciones `fpa_*`; también los disparadores internos de las claves sobre
`pos_company` y `user_user`); `sqlite_master` y las 70 claves de `contabilidad_*` idénticos. Las 52 sentencias FOREIGN KEY
y las 185 demás de `0011`+`0012` de antes son las mismas que las de `0011`+`0012`+`0016` de ahora: solo cambia dónde van.
Ningún nombre de restricción cambia.

**Medidas después** (los mismos guiones del corrector; la máquina nunca estuvo tranquila):

- Recorrido completo con la rama (de 10:28:13 a 10:32:29 UTC, carga de 6,32 a 12,01): `0011` y `0012` no retienen nada
  sobre tablas publicadas, ni a la ida ni a la vuelta. `0016` a la ida retuvo `pos_company` 0,20 s y
  `contabilidad_movimientomanual` 0,45 s; ventana de 0,641 s (espera del `LOCK` 0,422 s, los 26 ALTER 0,069 s, registro y
  COMMIT 0,142 s; con el bloqueo tomado, 0,218 s). A la vuelta, ventana de 0,770 s (espera 0,709 s, los 26 DROP 0,025 s;
  con el bloqueo tomado, 0,060 s); el lector de `pos_company` esperó como mucho 118 ms en toda la pasada. En la otra ida,
  ventana de 0,987 s y 0,490 s con el bloqueo tomado.
- Solo 0016, tres vueltas y tres idas (de 11:47 a 11:49 UTC, carga de 4,45 a 5,68): ventanas de 0,184 a 1,077 s; espera
  del `LOCK` de 0,108 a 0,565 s; los 26 ALTER, de 0,026 a 0,105 s; con el bloqueo tomado, de 0,072 a 0,586 s. En esa
  máquina una escritura sin ningún bloqueo tardaba 298,6 ms de mediana y 604,2 ms en el p95 (máximo 1516,9 ms de 175):
  lo que se retiene lo pone sobre todo el COMMIT (el disco compartido), no los ALTER. Falta la cifra con la máquina
  tranquila; el guion para repetirla es `bash /root/invoice15/c2e1-medicion/medir_0016.sh <checkout>`.
- `tests/test_zz_claves_anteriores_pg.py` sobre `6f27265` (15/11, de 11:25:40 a 13:10:14 UTC, carga de 4,63 a 4,91 al
  empezar y al terminar; esperó unos 55 min el candado de otra rama): vuelta de 0016 con 29 sentencias con lo publicado
  bloqueado, 0,16 s hasta confirmar; ida con 30, 0,10 s; con `pos_company` ocupada 3,5 s, 0016 bien a los 4,06 s y la
  escritura más lenta esperó 1,20 s (de 23); ocupada hasta rendirse (3 intentos en la prueba), falla a los 7,00 s con el
  mensaje, sin cambiar nada, y la escritura más lenta esperó 1,10 s (de 69).
- **Ensayo de la decisión 18 repetido sobre `72a68ee`** (15/11, de 13:29 a 14:16 UTC, carga de 5,2 a 10,3 con 6
  núcleos, `e0f2902` atendiendo; detalle en «Ensayo repetido sobre `72a68ee`», abajo). En las cuatro idas (la
  principal, la otra ida después de la vuelta y los escenarios `r1` y `r3`), 0011 y 0012 no tomaron ningún bloqueo sobre
  tablas existentes, y tampoco a la vuelta. 0016 duró de 0,23 a 0,60 s, con un intento, y retuvo `pos_company` y
  `contabilidad_movimientomanual` de 0,10 a 0,49 s (espera del `LOCK` de 81 a 264 ms, los 26 ALTER de 61 a 119 ms, y el
  resto, el COMMIT). Su vuelta, con la aplicación parada, tomó `AccessExclusiveLock` de 0,51 a 0,64 s. El kardex de
  `e0f2902` no esperó nada (antes, 55 muestras y 5,47 s) y la escritura más lenta en `pos_company`, 1,14 s, es de 0007,
  del bloque 1 (C2E-2). Las 26 claves quedaron diferidas y validadas, con la misma huella tras cada ida. **C2E-1 queda
  resuelto.**

**Qué bloquea ahora, con `e0f2902` atendiendo.** Solo `0016` toma un bloqueo que choca con la versión publicada: mientras
espera el `LOCK` (como mucho 1 s por intento) y mientras lo tiene (26 ALTER sobre tablas vacías y el COMMIT) hacen cola
las escrituras en `pos_company` y en `contabilidad_movimientomanual` (ediciones de empresa, movimientos manuales del
kardex), y en `contabilidad_cuenta`, que `e0f2902` no usa; las lecturas no. En el ensayo repetido, de 0,10 a 0,49 s
con el bloqueo tomado. Su vuelta toma `AccessExclusiveLock` y para también las lecturas, con los mismos intentos de 1 s.
El `SET LOCAL lock_timeout` de 0016 solo vale dentro de su transacción y no cambia el `lock_timeout=5s` que pone
`desplegar.sh` (abajo). La recomendación de publicar sin uso del kardex ya no hace falta por 0011 y 0012; para el bloque
1 (0004 y 0007, C2E-2) sigue igual.

**Depende de piezas internas de Django 5.2.** `AplazarClaves` lee y modifica `schema_editor.deferred_sql`, reconoce las
claves por la plantilla `schema_editor.sql_create_fk` y por `Statement.parts['table']` y `['column']`, y
`CrearClavesAplazadas` usa `_create_fk_sql`, `_delete_fk_sql` y `_fk_constraint_name`. Ninguna es API pública. Si Django
cambia, `AplazarClaves` falla sin migrar (no aplaza en silencio) y la guarda estática y
`tests/test_zz_claves_anteriores_pg.py` lo dicen. Al subir de versión de Django hay que pasar las dos antes de publicar.

**Ventana en que el estado de Django y la base no coinciden.** Entre `0011` y `0016`, en PostgreSQL, el estado de las
migraciones dice que esas 26 claves existen y la base no las tiene. Pasa durante la ventana del despliegue (un solo
`migrate` las aplica seguidas, y el código nuevo no atiende hasta después) y si alguien deja la base a medias entre 0011
y 0015, por ejemplo con `migrate contabilidad 0013`. Mientras dure, la base no comprueba que las filas de esas 19 tablas
apunten a una empresa, una cuenta o un movimiento que existen. No dejar la base ahí: o hasta 0016, o de vuelta a 0010 o
más abajo.

**Regla para los cortes y bloques siguientes.** Toda clave foránea de una tabla nueva hacia una tabla que no crean los
bloques 2 a 6 (empresa, usuario, operación, kardex, plan de cuentas…) se aplaza con `AplazarClaves` en la migración del
`CreateModel` y se crea en una migración que solo contiene `CrearClavesAplazadas`. Un `AddField` o `AlterField` con una
clave así, o SQL con FOREIGN KEY o REFERENCES fuera de esa migración, hacen fallar la guarda
`tests/test_convivencia_versiones.py::test_claves_hacia_tablas_anteriores_solo_en_la_migracion_corta_del_final`, que
corre en SQLite y en PostgreSQL y exige además las 26 de 0016. Al publicar otra versión hay que poner al día `PUBLICADO`
en `tests/test_zz_claves_anteriores_pg.py` (las hojas publicadas) y, si cambia dónde empiezan los bloques en
`contabilidad` o `tributario`, `DESDE` en `tests/test_convivencia_versiones.py`. Si `contabilidad` recibe otra migración,
va en fila detrás de 0016.

#### Vueltas con 0016

Las órdenes no cambian; cambia lo que deshacen.

- **Al final del bloque 1** (`migrate contabilidad 0009_anular_autores_en_la_base`, `migrate tenancy
  0013_acciones_plan_cuentas`): deshace ocho, no siete, en este orden: `contabilidad 0016` a `0010` y después
  `tenancy 0014`. La primera es 0016, que quita las 26 claves con `AccessExclusiveLock` sobre `pos_company`,
  `contabilidad_cuenta` y `contabilidad_movimientomanual` (también paran las lecturas), en intentos de 1 s y solo para los
  26 DROP y el COMMIT (el corrector midió entre 0,06 y 0,52 s con el bloqueo tomado; el ensayo repetido, en la
  vuelta a lo publicado y en la de solo 0016, con la aplicación parada, de 0,51 a 0,64 s, y la lectura de `pos_company`
  esperó hasta 0,55 s). Las vueltas de 0015 a 0011 ya no tocan esas tablas. La de 0010, como siempre, toma
  `AccessExclusiveLock` sobre `contabilidad_cuenta` para quitar `clase`, `auxiliar` y sus dos CHECK. Antes, el
  `DROP TABLE` de 0012 y de 0011 tomaba `AccessExclusiveLock` sobre `pos_company` hasta confirmar (ventanas de 0,58 y
  0,52 s medidas). Quedan pendientes las ocho (`BLOQUE_2` de `tests/test_migracion_vuelta_fase.py`, que ya incluye
  `contabilidad.0016_claves_hacia_tablas_anteriores`).
- **A lo publicado** (`migrate contabilidad 0003_modulo_kardex`, `migrate tenancy 0012_accion_diseno_factura`): con la
  primera orden deshace `contabilidad 0016` a `0004` (las siete de contabilidad de este corte, 0016 la primera, y después
  las seis del bloque 1); con la segunda, `tenancy 0014` (de este corte) y `tenancy 0013` (del bloque 1). Quedan
  pendientes quince: las ocho del corte y las siete del bloque 1. En el ensayo repetido, 58,5 s la primera y 5,9 s la
  segunda, un intento cada una.
- **La de la fase** espera 56 pendientes (55 antes del cierre). **La del diseño de factura** no cambia: 0016 no depende de
  `pos 0035` ni de `tenancy`.
- Con datos registrados vale lo de siempre (abajo): vuelta solo de código o restaurar.

**Vuelta solo de código** (`desplegar.sh --revertir`), separando los dos casos posibles (H9 del cierre; también en
«Recuperación que conserva lo posterior», arriba):

1. **El anterior es el bloque 1 publicado** (bloques publicados por separado): valen los dos límites de arriba (el CHECK
   `cuenta_auxiliar_solo_movimiento` al pasar a grupo una cuenta con auxiliar, y que ese código puede desactivar o pasar
   a grupo una cuenta con movimientos en el libro o la apertura: mientras dure, no tocar el plan de cuentas).
2. **El anterior es `e0f2902`** (los bloques 1 y 2 publicados juntos; hoy es el caso de la decisión 18a, porque el bloque
   1 no está publicado): ese código no tiene el plan de cuentas ni ninguna de sus rutas, así que esos dos límites no
   aplican; el plan de cuentas, el libro, la apertura y sus archivos quedan en la base sin ruta ni pantalla hasta volver a
   publicar. Valen los límites del **punto 3 del plan de recuperación del bloque 1** (nota del 14/11 del bloque 1): borrar
   una empresa con plan de cuentas da 500 y no borra nada, también desde `/plataforma/`; con 0009, borrar a un usuario
   que creó cuentas o lotes funciona; y el punto 4: no ejecutar `start_installation` de la versión anterior. Es la vuelta
   que recorrió el ensayo del cierre (abajo).

#### Despliegue: `migrate` con `lock_timeout` y reintento acotado (C2E-3)

Hasta `6efad50`, `deploy/scripts/desplegar.sh` ejecutaba `migrate` solo con `PGOPTIONS="-c app.platform=on"`: sin
`lock_timeout` ni reintento, aunque el encargo del ensayo lo daba por hecho («como lo hace `desplegar.sh`»), la decisión
18a lo pide para el ensayo y esta nota lo recomendaba para la vuelta; el ensayo lo añadió como única diferencia de
procedimiento. Desde `72a68ee` (`85a8e10`), el paso 4 llama a `migrar()`:

- `migrate --noinput` con `PGOPTIONS="-c app.platform=on -c lock_timeout=5s"`, como mucho 3 intentos con 10 s de pausa
  entre uno y otro (constantes al principio del guion: `LOCK_TIMEOUT_MIGRATE=5s`, `INTENTOS_MIGRATE=3`,
  `PAUSA_MIGRATE=10`).
- Repite **solo** si la última excepción que imprimió Python en ese intento es `psycopg.errors.LockNotAvailable`
  (`55P03`) o `DeadlockDetected` (`40P01`), o un `django.db.utils.OperationalError` cuya causa directa es una de esas dos
  (`fallo_por_bloqueo()`, que mira la clase y no el texto, porque el texto depende de `lc_messages`). Cualquier otro
  fallo para el despliegue al primer intento, con el código de salida de `migrate`, como antes.
- **0009 y 0016 se rinden con su propio `RuntimeError`, que no se repite:** ya hicieron sus 8 intentos de 1 s y su
  mensaje dice qué hacer, aunque la causa sea un `55P03`. Así 0009 conserva su peor caso documentado (unos 22 s) y 0016 el
  suyo. Lo que pasa entonces: `desplegar.sh` dice «FALLO de migrate en el intento 1 de 3; no se repite…» y sale con el
  código de `migrate` (1); `current` sigue en la versión anterior, que sigue atendiendo, y la carpeta de la nueva se
  borra al salir. **El despliegue se repite a mano** cuando la otra transacción suelte el bloqueo (mirar en
  `pg_stat_activity` y `pg_locks` quién lo retiene). El texto de 0016 contiene «no se consiguió el bloqueo», pero
  `desplegar.sh` no mira el texto, sino la clase de la última excepción. El caso de 0009 lo prueba
  `tests/test_desplegar_releases.py`; el de 0016 no tiene caso propio en esa prueba, pero lo recorrió el ensayo repetido
  sobre `72a68ee` (escenario `r2`, con `pos_company` retenida 40 s): 8 intentos cortados con `55P03` en 24,0 s, el
  `RuntimeError`, «no se repite», salida 1, `current` en `e0f2902` y ninguna de las 64 peticiones fallida; después, sin
  retención, solo 0016 se aplicó en 0,23 s al primer intento (`r3`). Si se quiere que `desplegar.sh` también repita ese
  caso, es una decisión aparte. El `migrar()` de los primeros guiones del ensayo (`ensayo-contable-2c1/guiones/comun.sh`)
  era distinto: buscaba en el texto `lock timeout`, `LockNotAvailable`, `deadlock` o «no se consiguió el bloqueo» y sí
  habría repetido esos dos `RuntimeError`. El de `guiones-2/` ya es el de `desplegar.sh`.
- Dentro de una migración manda su propio `SET LOCAL`: medido en el PostgreSQL de pruebas, la sesión con 5 s, tras
  `SET LOCAL '1000ms'` 1 s (también dentro y después de un punto de guardado) y tras el COMMIT otra vez 5 s; la 0009 real
  con `user_user` retenido e `INTENTOS=2` se rindió a los 4,29 s.
- Repetir es seguro: ninguna migración de `core/` ni de las apps instaladas tiene `atomic = False` (solo hay puntos de
  guardado internos en contabilidad 0009 y en auth 0011; `widget_tweaks`, `django_user_agents` y `django_cleanup` no
  migran), así que la cortada no deja nada, las anteriores quedan confirmadas y el intento siguiente sigue donde se
  quedó. Matiz de Django 5.2: una migración con SQL diferido se anota en `django_migrations` después de confirmarse; ese
  INSERT solo esperaría a quien retuviera `django_migrations` en SHARE o más (nadie; `pg_dump` toma ACCESS SHARE), y si
  pasara, la repetición pararía con un error que no es de bloqueo.
- La salida de cada intento va a `$BASE/registros/migrate-<AAAAMMDD-HHMMSS>-<commit8>.log` (en el servidor,
  `/opt/facturaporaqui/<entorno>/registros/`; carpeta 0700 de root, se conservan los 30 más recientes), sin el entorno
  ni la URL de la base, y queda aunque la versión fallida se borre. En pantalla sale al terminar cada intento, no en
  vivo: para seguirla, `tail -f` en ese archivo.
- Mensajes nuevos al operador: «migrate, intento N de 3 (su salida, al terminar; mientras, en <registro>)», «se repite
  migrate en 10 s (intento N de 3)», «migrate: bien en el intento N de 3 (salida en <registro>)», «FALLO de migrate en el
  intento N de 3; no se repite (solo se repiten un lock_timeout o un interbloqueo de la base)…» y, al agotar los
  intentos, «FALLO de migrate: en los 3 intentos, una migración no consiguió en 5s el bloqueo…», que pide mirar en
  `pg_stat_activity` y `pg_locks` qué transacción retiene la tabla (una transacción larga, un `pg_dump` en curso),
  esperar y repetir el despliegue con poco tráfico.
- `--revertir`, la limpieza de la carpeta de una versión que no quedó activa, los `trap` y `.no-activa-*` no cambian.
  `tests/test_desplegar_releases.py` tiene 13 casos (los 8 de antes y 5 nuevos: el reintento ante `LockNotAvailable` y
  ante `DeadlockDetected`, los 3 intentos agotados, y `statement_timeout` y 0009 sin reintento); su simulador imprime la
  salida real de un `migrate` cortado (Django 5.2.18, psycopg 3.3.6, PostgreSQL 16). Sobre `85a8e10`: 13 aprobadas en
  16,51 s (10:27:41 UTC, carga 7,12); con el guion de `6efad50`, 5 fallan.
- **Probado con tráfico en el ensayo repetido sobre `72a68ee`** (tráfico ficticio, `e0f2902` atendiendo): sin
  retención, bien al primer intento; con `pos_company` retenida 7 s (`r1`), 0004 se cortó por `lock_timeout` a los 5 s
  (`LockNotAvailable` → `OperationalError`), «se repite migrate en 10 s», el intento 2 fue bien y ninguna de las 299
  peticiones durante `migrate` falló; con 0016 rendida (`r2`), lo de arriba. **C2E-3 queda resuelto y probado con
  tráfico.** Sigue sin probar con tráfico real.

#### Límite: la inmutabilidad del libro no resiste el DDL del rol dueño de las tablas (C2E-4)

El libro y la historia de la apertura son de solo inserción frente a lo que el rol de la aplicación hace con datos
(`UPDATE`, `DELETE`, `INSERT` en un asiento sellado: rechazados con `P0001` por los disparadores de 0014, comprobado en el
ensayo con el rol de la aplicación y la empresa activa, también con `app.platform=on`). **No** lo son frente a su DDL:
ese rol es dueño de las tablas y de las funciones, como `facturaporaqui_pruebas` en producción, y puede
`ALTER TABLE contabilidad_asiento DISABLE TRIGGER …`, `DROP TRIGGER`, `TRUNCATE contabilidad_lineaasiento` (que además
ignora la seguridad por filas y deja asientos sellados sin líneas en todas las empresas) o
`CREATE OR REPLACE FUNCTION fpa_linea_solo_insercion …`. Comprobado en el cierre: el ensayo hizo un
`ALTER TABLE … DISABLE TRIGGER` dentro de `BEGIN…ROLLBACK` y pasó; la revisión del libro, `DISABLE TRIGGER` seguido de un
UPDATE de `debe`, `TRUNCATE` y `CREATE OR REPLACE FUNCTION` (y que `set_config('app.platform', 'on')` da a ese rol
visibilidad sobre las demás empresas; ningún módulo de `core/contabilidad` lo usa). `DROP TRIGGER` lo permite la misma
propiedad y no se probó aparte. La decisión 2 de la especificación dice «hace imposible, no improbable», y la
especificación solo admite que `TRUNCATE` y `DROP TABLE` no disparan los disparadores.

`verificar` lo detecta después: el cuadre no coincide (`n` distinto de `lineas_n`) y fallan las huellas. La medida de
fondo —un rol dueño de las tablas distinto del rol con el que atiende la aplicación, o un *event trigger* que registre
los `ALTER TABLE`/`DROP TRIGGER` sobre las tablas del libro— es de infraestructura y fuera del bloque: **la decide la
propietaria**. Mientras tanto queda como límite escrito.

#### Ensayo del cierre (15/11/2026, sobre `6efad50`)

Guiones propios en `/root/invoice15/ensayo-contable-2c1/guiones/` (copiados de `ensayo-contable-1b`, que no se tocaron);
resultados en `ensayo-contable-2c1/resultados.json`. Base restaurada del volcado diario `diario-20261114-231604.dump`, con
un rol con los atributos del publicado (`NOSUPERUSER`, `NOBYPASSRLS`, dueño de la base y de las 208 tablas); `e0f2902`
atendiendo tráfico ficticio con 9 hilos (lecturas, inicios de sesión, proformas, compras, cobros, importación de XML,
ventas emitidas con el SRI simulado y movimientos manuales del kardex); `migrate` como `desplegar.sh` de `6efad50` más
`lock_timeout=5s` y reintento. Máquina compartida (carga de 4 a 17 con 6 núcleos; en `principal-1`, de 6,3 a 4,98): los
tiempos están inflados. Es anterior a 0016 y al `desplegar.sh` nuevo.

- **Ida con tráfico:** `migrate` bien al primer intento, 105,3 s de proceso (0011 28,2 s; 0012 53,5 s; las demás, de 0,03
  a 4,8 s; 0009, 0,49 s, con un intento de 0,12 s). 277 peticiones durante `migrate`, ninguna fallida; 0 esperas de ventas, cobros
  y compras; el kardex, hasta 5,47 s (C2E-1); 0004 y 0007 retuvieron `user_user` hasta 2,4 s y `pos_company` hasta 2,6 s,
  y 0009 tomó `AccessExclusiveLock` sobre `user_user` 0,23 s. El rol de la aplicación creó las seis funciones y los seis
  disparadores de 0014 sin superusuario, y las 19 tablas quedaron con la seguridad por filas forzada.
- **Ventana de más de 30 s con `e0f2902` sobre la base migrada:** 33 pasos de seguridad y 363 peticiones, 0 fallidos.
- **Con la versión nueva:** 794 peticiones y el uso del corte por HTTP (77 pasos), 0 fallidos; los disparadores
  rechazaron con `P0001` los 14 intentos de cambiar el libro o la historia con el rol de la aplicación, también tras
  revertir el código.
- **Vuelta solo de código a `e0f2902`:** 499 peticiones; la única fallida, el 500 esperado al borrar desde `/plataforma/`
  una empresa con plan de cuentas (sin borrar nada). Ventas, cobros, compras y kardex siguieron (de 55 a 90 ventas
  autorizadas, de 84 a 139 cobros, de 87 a 144 compras, de 61 a 97 movimientos del kardex) y ninguna fila de la operación
  desapareció fuera de las borradas a propósito; borrar por pantallas y por SQL lo que las filas contables nombran
  funcionó y las tablas contables no cambiaron (salvo el `SET NULL` de 0009).
- **Vuelta de migraciones con la aplicación detenida:** contabilidad 0015 a 0004 en 52,4 s y tenancy en 4,5 s, un intento
  cada una; borra las 21 tablas del plan, el libro y la apertura con sus datos, y los archivos de la apertura quedan sin
  dueño en `privado/`. Otra ida con `e0f2902` atendiendo: bien, 81,9 s, 270 peticiones sin fallos, 0 esperas de ventas,
  cobros y compras, y el kardex hasta 3,6 s.
- El cambio de proceso dejó de 4,4 a 5,4 s sin servicio y de 21 a 27 peticiones fallidas por cambio (D7, fuera del
  bloque). Producción intacta: `facturaporaqui@pruebas` con el mismo MainPID (1447381) y sin reinicios, `current` en
  `e0f2902`, ninguna conexión a la base publicada.

En una pasada de prueba (`prueba-2`) un **cobro** esperó 1,80 s por `user_user` mientras 0004/0007 lo tenían (C2E-2):
está en el punto 1 del plan del bloque 1. La espera fue real, pero la ruta la atribuye el muestreo fino, que en esa pasada
no estaba corregido (límites del ensayo repetido, abajo): puede ser otra petición de la misma conexión persistente.

#### Ensayo repetido sobre `72a68ee` (15/11/2026)

La decisión 18 sobre el código corregido: 0016 y el `desplegar.sh` nuevo. `7a5c567`, posterior, solo toca la importación
del lote de la apertura: no cambia nada de lo que mide este ensayo. Resultados en
`/root/invoice15/ensayo-contable-2c1/resultados-2.json` (con la comparación entera, «comparacion_con_principal_1»);
guiones en `ensayo-contable-2c1/guiones-2/`; registros en `registros/principal-2/`, `vuelta-2/` y `reintento-2/`. Los de
la primera pasada no se tocaron.

**Cómo.**

- Las mismas garantías que la primera pasada: base restaurada del mismo volcado diario (`diario-20261114-231604.dump`),
  rol con los atributos del publicado (sin superusuario ni `BYPASSRLS`, dueño de las tablas), `e0f2902` atendiendo con
  2 workers, el SRI simulado (0 conexiones externas), correo local y el mismo tráfico ficticio.
- `migrar()` es ahora la de `deploy/scripts/desplegar.sh` de `72a68ee` (`lock_timeout=5s`, 3 intentos, 10 s de pausa) y
  `fallo_por_bloqueo()` está copiada sin cambios: ya no hay diferencia de procedimiento en el paso 4. Solo se añadió
  instrumentación que observa.
- Sondas nuevas: escritura en `contabilidad_movimientomanual` y lectura de `pos_company`. El uso del corte suma 22 casos
  de las correcciones (`[C]`).
- Tres pasadas, de 13:29 a 14:16 UTC. `principal-2`: ida con tráfico, ventana de 30 s o más con `e0f2902` sobre la base
  migrada, cambio a la nueva, uso del corte y vuelta de solo código. `vuelta-2`: vuelta de migraciones con la aplicación
  parada, `e0f2902` sobre la base deshecha y otra ida con tráfico. `reintento-2`, sobre otra copia restaurada: `r1`,
  `pos_company` retenida hasta 7 s después de que `migrate` pidiera el bloqueo; `r2`, vuelta de solo 0016 con la
  aplicación parada y después `pos_company` retenida 40 s; `r3`, sin retención; `r4`, el uso del corte otra vez y las
  pruebas de inmutabilidad.

**Comparación con la primera pasada** (las duraciones están infladas por la carga y no se comparan entre pasadas; los
bloqueos sí):

| Medida | principal-1 (`6efad50`) | principal-2 (`72a68ee`) |
|---|---|---|
| Carga al empezar / al terminar (6 núcleos) | 6,3 / 5,0 | 6,9 / 9,7 |
| `migrate` de la ida: salida, intentos, segundos | 0, 1, 105,3 | 0, 1, 119,8 |
| 0011: segundos; bloqueo sobre tablas existentes | 28,2 s; `pos_company` 6021 ms | 33,4 s; ninguno |
| 0012: segundos; bloqueos | 53,5 s; `pos_company` 12023 ms, `movimientomanual` 8140 ms | 63,4 s; ninguno |
| 0016 | no existía | 0,60 s; `pos_company` y `movimientomanual` 490 ms |
| 0004 / 0007 (bloque 1) | `user_user` 1682 / 2439 ms, `pos_company` 1466 / 2621 ms | `user_user` 133 / 906 ms, `pos_company` 102 / 1135 ms |
| Sonda de escritura en `pos_company` (máximo) | 12040,5 ms (4 de más de 1 s) | 1139,7 ms (1 de más de 1 s) |
| Sonda de escritura en `movimientomanual` | no medida | 501,9 ms |
| Sonda de escritura en `user_user` | 2440,5 ms | 911,6 ms |
| Lectura de `user_user` / de `pos_company` | 322,8 ms / no medida | 4,4 / 4,4 ms |
| Monitor: kardex (muestras, máximo) | 55, 5474 ms | 0, 0 |
| Monitor: lecturas | 3, 299 ms | 0 |
| Esperas de ventas, cobros y compras | 0 / 0 / 0 | 0 / 0 / 0 |
| Peticiones durante `migrate` (total, fallidas, p95, máximo) | 277, 0, 6165 ms, 10305 ms | 285, 0, 6022 ms, 8166 ms |
| Cambio a la nueva / vuelta de código (D7) | 5,4 s, 27 fallidas / 4,4 s, 21 | 8,4 s, 29 / 8,3 s, 24 |
| Uso del corte | 77 pasos, 0 fallidos | 99 pasos, 0 fallidos (+22 `[C]`) |
| Vuelta contabilidad 0003 / tenancy 0012 | 52,4 s / 4,5 s | 58,5 s / 5,9 s |
| Vuelta de 0012 / 0011 sobre `pos_company` | 59,5 ms (y `movimientomanual` 27,5) / 205 ms | ninguno / ninguno |
| Vuelta de 0016 | no existía | `AccessExclusiveLock` 512 ms (aplicación parada) |
| Otra ida: 0011 / 0012 | `pos_company` 6017 ms / `pos_company` 9250 ms y `movimientomanual` 6594 ms | ninguno / ninguno; 0016, 342 / 224 ms |
| Otra ida: kardex; escritura en `pos_company` | 36 muestras, 3597 ms; 9232 ms | 0; 384 ms |
| Integridad (datos distintos en todas las comparaciones) | ninguno | ninguno |

**Lo demás de `principal-2` y `vuelta-2`.**

- Ventana de 30 s o más con `e0f2902` sobre la base migrada: seguridad 33/33 y 373 peticiones, 0 fallidas. Con
  `72a68ee`: 1007 peticiones, 0 fallidas, y los 22 casos `[C]` bien (controles, `1e3`, PNG dañado, auxiliar cambiado en
  revisión con `detalle_fijado`, la clave usada en otra apertura).
- Con el rol de la aplicación, los 13 intentos de cambiar el libro o la historia, rechazados con `P0001`, y la seguridad
  por filas de otra empresa con 0 filas: los mismos intentos que la primera pasada. `DISABLE TRIGGER` sigue siendo
  posible (C2E-4). El rol de la aplicación creó las seis funciones y sus disparadores.
- Vuelta de solo código a `e0f2902`: 528 peticiones; la única fallida, el 500 esperado al borrar desde `/plataforma/` una
  empresa con plan de cuentas. Borrados por pantallas 10/10 y por SQL 9/9. No desapareció nada salvo lo borrado a
  propósito.
- Vuelta de migraciones con la aplicación parada: deshace 0016 la primera (arriba), borra las 21 tablas con sus datos y
  deja 15 pendientes. `e0f2902` sobre la base deshecha: 395 peticiones, 0 fallidas. Otra ida con tráfico: 115,8 s, un
  intento, 246 peticiones, 0 fallidas; kardex sin esperas; lo único, un inicio de sesión que esperó 229 ms por 0009.

**Escenario de reintento** (`reintento-2`, carga de 5,2 a 7,9):

- `r1`: 0004 se cortó por `lock_timeout` a los 5 s; «se repite migrate en 10 s»; el intento 2 fue bien; 299 peticiones,
  0 fallidas. Las sondas de escritura en `user_user` y `pos_company` esperaron 5,0 y 4,7 s: es el tope de 5 s. Durante
  0009 del intento 2, un cobro y un movimiento del kardex esperaron unos 0,4–0,5 s por `user_user` (C2E-2: punto 1 del
  plan del bloque 1).
- `r2`: 0016 hizo 8 intentos, todos cortados con `55P03`, en 24,0 s; las escrituras esperaron hasta 1,0 s por intento y
  el kardex, 12 muestras con un máximo de 933 ms. 0016 se rindió con su `RuntimeError` y `desplegar.sh` no repitió:
  salida 1, `current` en `e0f2902` y 0 de 64 peticiones fallidas («Despliegue», arriba).
- `r3`: solo 0016, 0,23 s, bien al primer intento.
- `r4`: el uso del corte, 99 de 99; el asiento sin sellar se rechaza al confirmar y quedan 0 sin sellar.

**Veredicto.** **C2E-1 queda resuelto:** 0011 y 0012 ya no retienen `pos_company` ni `contabilidad_movimientomanual`, ni
a la ida ni a la vuelta, y 0016 es corta y se rinde limpia. **C2E-3 queda resuelto y probado con tráfico** (ficticio).
Siguen C2E-2 (bloque 1: punto 1 de su plan de recuperación) y C2E-4 (el límite de arriba). Lo que el ensayo vio que no
coincidía con lo que se había dejado para documentar (C2R-1 a C2R-3) está corregido en estos documentos.

**Límites.**

- Máquina compartida (6 núcleos): carga de 6,9 a 10,3 en `principal-2` y `vuelta-2`, y de 5,2 a 7,9 en `reintento-2`,
  contra 4 a 6,3 en la primera pasada. Las duraciones de 0011 y 0012 y las de las peticiones están infladas.
- Una ejecución por escenario, sin pasadas de prueba. La retención fue solo sobre `pos_company`, en `ROW EXCLUSIVE`.
- El muestreo fino corre en un solo bloque `DO`, y PostgreSQL congela `pg_stat_activity` en la primera lectura de la
  transacción. En esta pasada se corrige con el monitor de 100 ms; en la primera y en `prueba-2` no, y la ruta que
  atribuye puede ser otra petición de la misma conexión (`CONN_MAX_AGE` 60). La espera sí es real.
- El guion de despliegue del ensayo sigue sin borrar la carpeta de una versión que no quedó activa: la de `r2` quedó en
  `releases/` y el `--revertir` de `r4` la eligió (`72a68ee`). La prueba de inmutabilidad tras revertir corrió con
  `72a68ee` atendiendo; los disparadores son de la base y el resultado no depende del código. En `principal-2` la vuelta
  de código sí fue a `e0f2902`. El `desplegar.sh` real sí borra esa carpeta.
- D7, fuera del bloque: cada cambio de proceso dejó de 4,3 a 8,4 s sin servicio y de 20 a 29 peticiones fallidas, con 0
  respuestas 5xx.
- `referencias.py` crea por ORM las filas contables que apuntan a la operación, porque el corte 1 no tiene rutas que las
  creen.
- No se ejecutaron suites, ni navegador, ni la integración con primera entrega. Falta la medida de 0016 con la máquina
  tranquila.
- Producción intacta: `facturaporaqui@pruebas`, leído solo con `systemctl show`, siempre con MainPID 1447381 y sin
  reinicios; `current` en `e0f2902`; ninguna conexión a la base publicada. La base y el rol del ensayo están borrados.

#### Receta de integración con `fase/primera-entrega`

Ensayada el 15/11/2026 en un worktree desechable (fusión `b550173` de `6efad50` sobre `e0d7c38` y la prueba `2c4bad7`,
ya borrados), con todo en verde: SQLite en tres grupos (219, 674 y 432 aprobadas) y PostgreSQL con cuatro archivos (212
aprobadas). Registros y archivos resueltos en la VM101, `/root/invoice15/contable/registros/integracion-c2c1-pe/`. **No
hacerla de verdad hasta que la propietaria apruebe el PR #1** (`fase/primera-entrega`). Lo ensayado fue sin 0016: la
receta de abajo ya la incluye (código `72a68ee`; `7a5c567` no la cambia: solo toca
`core/contabilidad/apertura_importar.py` y su prueba, que primera entrega no toca), y lo que 0016 cambia (un número más
en cada cuenta, la guarda nueva) es una cuenta hecha sobre el código, no una medida; los archivos resueltos de esa
carpeta son de antes de 0016 y hay que ponerlos al día con ella.

0. Sin rebase. Sobre `fase/primera-entrega` (`e0d7c38`, o la rama que quede al publicarla):
   `git merge --no-ff fase/contable-2-apertura` (`7a5c567`, que ya trae el bloque 1 `8a421b3`). En el ensayo salieron 3
   conflictos de texto: `core/tenancy/pestanas.py`, `tests/test_migracion_vuelta_fase.py` y
   `tests/test_convivencia_versiones.py` (add/add). Primera entrega no toca `deploy/`, `core/contabilidad`,
   `core/security/menu.py` ni `core/tenancy/roles.py`.
1. `pestanas.py`: el docstring con los dos párrafos, primero el del cuerpo JSON y después el de la cabecera
   `X-FPA-Empresa`; imports `json`, `RequestDataTooBig`, `JsonResponse`, `RawPostDataException`. El resto como lo une
   git (`cuerpo_json`, `empresa_pedida`, `empresa_cambiada` sobre `empresa_pedida`, `CABECERA`,
   `cabecera_de_otra_empresa`, `rechazo_empresa_cambiada`).
2. **tenancy, en fila y con `git mv`** (I2), en este orden:
   - `git mv core/tenancy/migrations/0014_acciones_apertura.py core/tenancy/migrations/0015_acciones_apertura.py`, con la
     dependencia `('tenancy', '0014_acciones_plan_cuentas')`;
   - `git mv core/tenancy/migrations/0013_acciones_plan_cuentas.py core/tenancy/migrations/0014_acciones_plan_cuentas.py`,
     con la dependencia `('tenancy', '0013_acciones_borrador_factura')`;
   - las `choices` regeneradas desde `AuditLog.ACTIONS` ya unido: 0014 hasta `cuentas_importadas` (60), 0015 entero (85);
   - `tests/test_esquema_contable.py` importa por nombre `core.tenancy.migrations.0014_acciones_apertura` (línea 746;
     docstring en la 741): pasa a `0015_acciones_apertura` y «tenancy 0015», o falla con `ImportError`;
   - comprobar `makemigrations --check --dry-run` («No changes detected») y que `sqlmigrate tenancy` 0013, 0014 y 0015 no
     hacen nada.
   Contabilidad 0004–0016 no se toca. Quedan sin publicar **19** migraciones (18 en el ensayo, sin 0016): contabilidad
   0004–0016, importacion 0008–0009, proformas 0004 y tenancy 0013–0015.
3. `tests/test_migracion_vuelta_fase.py`:
   - conteo **60** (59 en el ensayo), con el comentario por bloques: 45 con primera entrega, 49 con el plan, 52 con su
     importación, 60 en total;
   - `sin_diseno` = configuracion 0004/0005/0006, pos 0035, tenancy 0012, `0013_acciones_borrador_factura`,
     `0014_acciones_plan_cuentas` y `0015_acciones_apertura`;
   - `BLOQUE_2` con `contabilidad.0016_claves_hacia_tablas_anteriores` y terminado en `tenancy.0015_acciones_apertura`;
   - vuelta del corte: (`contabilidad 0009_anular_autores_en_la_base`, `tenancy 0014_acciones_plan_cuentas`);
   - vuelta del bloque 1: (`contabilidad 0003_modulo_kardex`, `tenancy 0013_acciones_borrador_factura`), con el comentario
     de que, con primera entrega publicada antes, su 0013 se queda; pendientes = contabilidad 0004–0009 +
     `tenancy.0014_acciones_plan_cuentas` + `BLOQUE_2`.
4. `tests/test_convivencia_versiones.py` en un solo archivo (I1):
   - el docstring común de las tres entregas;
   - los imports de los dos lados (también `re`, `sys` y `Path`, que usa la guarda nueva) y
     `from tests.test_importacion_verificacion_sri import archivos_temporales, dueno, empresa` (`archivos_temporales` es
     autouse; el `empresa` de las pruebas del corte pasa a ser «RECEPTORA VERIFICA», `conftest.admin` se cuelga de ella y
     pasan igual);
   - `PUBLICADAS` = la última migración de cada app en `e0f2902` (adjuntos 0006, cobros 0003, comprobantes 0023,
     configuracion 0006, contabilidad 0003, importacion 0007, pos 0035, proformas 0003, security 0003, suscripciones 0006,
     tenancy 0012, tributario 0003, user 0002);
   - `DE_PRIMERA_ENTREGA` (4) + `DEL_BLOQUE_1` (contabilidad 0004–0009, tenancy 0014) + `DEL_CORTE_1` (contabilidad
     **0010–0016**, tenancy 0015) = `DE_ESTA_ENTREGA` (**19**; 18 en el ensayo);
   - la prueba nueva `test_de_esta_entrega_son_todas_las_que_no_estan_publicadas`: lo que hay en disco en `core.*` menos
     el `forwards_plan` de `PUBLICADAS` tiene que ser igual a `DE_ESTA_ENTREGA`;
   - la prueba de columnas de primera entrega deja fuera los `AddField` sobre modelos que nacen con `CreateModel` en esas
     mismas migraciones: si no, falla con contabilidad 0011 `asiento.ejercicio` y 0012 `auxiliarapertura.linea` (claves
     NOT NULL sin `db_default` en tablas nuevas, que Django separa del `CreateModel`);
   - `NO_NULAS_AGREGADAS` se queda en sus 4: `cuenta.clase` y `cuenta.auxiliar` van en una tabla del bloque 1 sin
     publicar y las vigila la prueba de `DESDE`;
   - lo demás del corte, tal cual: `DESDE`, `CLAVES_DE_0009`, el INSERT de `Cuenta`, las claves fuera de contabilidad, el
     borrado por SQL y **la guarda de claves hacia tablas anteriores**
     (`test_claves_hacia_tablas_anteriores_solo_en_la_migracion_corta_del_final`, con `SQL_DE_CLAVE` y `_apunta_a`). Solo
     mira las apps de `DESDE` (contabilidad desde 0010 y tributario desde 0004): las migraciones de primera entrega
     (importacion, proformas, tenancy) quedan fuera.
   Quedan **11** pruebas (10 en el ensayo, sin la guarda nueva).
   - `tests/test_zz_claves_anteriores_pg.py` no cambia mientras primera entrega no esté publicada (`PUBLICADO` es
     `e0f2902`). Si se publica antes que los bloques, `PUBLICADO` pasa a sus hojas: importacion
     `0009_verificacion_sri_ultimo_intento`, proformas `0004_borrador_factura` y tenancy `0013_acciones_borrador_factura`.
5. Contrato (decisión 20b): en `CONTRATO-APERTURA-CONTABLE.md` (§6.1, las viñetas de `empresa` y del orden de las
   negativas), en `CONTRATO-CONTABLE-V9.md` («Orden de las negativas») y en la decisión de API 2/5 del bloque 1 en
   HANDOFF: «Cabecera `X-FPA-Empresa` (jQuery la manda sola, `static/js/functions.js`): si no es la empresa activa, 409
   `empresa_cambiada` con el mismo cuerpo, también en GET, antes que `PlanMiddleware` y que la vista (la responde
   `CompanyMiddleware`)». Puesto 1 del orden: `empresa_cambiada` (cabecera, `?empresa=` o cuerpo). Puesto 3: la cabecera
   no sustituye a `empresa`; sin ella, 409 `sin_empresa` aunque la cabecera sea la correcta. Anotar en el contrato el
   commit de la rama integrada contra el que se verificó.
6. Añadir `tests/test_integracion_cabecera_bloque2.py` (o pasar sus 3 casos a `test_pestanas_envios_json.py`), con las
   rutas sacadas de `test_complemento_contable.JSON`; copia en
   `/root/invoice15/contable/registros/integracion-c2c1-pe/archivos/`.
7. Vueltas, para esta nota y para el `plan-de-despliegue.md` de primera entrega:
   - (a) Primera entrega publicada antes y los bloques encima. Corte → bloque 1: `migrate contabilidad
     0009_anular_autores_en_la_base`, `migrate tenancy 0014_acciones_plan_cuentas` (deshace también 0016). Bloques →
     primera entrega: `migrate contabilidad 0003_modulo_kardex`, `migrate tenancy 0013_acciones_borrador_factura`.
     Después, si hace falta, la de primera entrega (`migrate importacion 0007_lotes_de_claves`, `migrate proformas
     0003_modulo_proformas`, `migrate tenancy 0012_accion_diseno_factura`). Al revés, `tenancy 0012` deshace también 0014 y
     0015 y deja contabilidad 0004–0016 aplicada: un estado mixto.
   - (b) Las tres publicadas juntas, vuelta a `e0f2902`: `migrate contabilidad 0003_modulo_kardex`, `migrate tenancy
     0012_accion_diseno_factura`, `migrate importacion 0007_lotes_de_claves`, `migrate proformas 0003_modulo_proformas`.
   - (c) La de la fase espera **60**; la del diseño (tenancy 0011) deshace tenancy 0012–0015 y no toca las tablas
     contables.
   Con datos registrados vale lo de siempre: la vuelta solo de código o restaurar.
8. Documentos: una nota «Integración con primera entrega» con la tabla de la renumeración, como «Unión con el bloque 1
   final», en lugar de reescribir las notas antiguas (aquí hay muchas referencias a `tenancy 0013`/`0014` y a 55 o 56).
   Poner al día en HANDOFF la fila «Integración con `fase/primera-entrega`» de la dependencia concreta. Y poner al día las
   líneas de `core/importacion` que cita la Parte F de la especificación (I4; comprobadas con `git show` de `72a68ee` y de
   `e0d7c38` el 15/11), que con primera entrega se mueven sin cambiar de contenido:

   | Enganche | Aquí (`72a68ee`) | Con primera entrega (`e0d7c38`) |
   |---|---|---|
   | `CONFIRMACIONES` | `servicios.py:825` | `servicios.py:945` |
   | `revisar` | `servicios.py:610-662` | `servicios.py:730-786` |
   | `propuesta_contable` y `estado_contable = 'propuesta'` dentro de `revisar` | `servicios.py:660-661` | `servicios.py:780-781` |
   | `_exigir_revisable` | `servicios.py:668` | `servicios.py:788` (en `:794` rechaza `DocumentoImportado.VERIFICACION_BLOQUEA`, que es nuevo) |
   | llamada con `confirmar_sin_verificar` | `servicios.py:1024-1025` | `servicios.py:1144-1145` |
   | `confirmar_no_duplicada` en `crear_compra_desde_documento` | `compras.py:589-590` | `compras.py:590-591` |
   | `registrar_en_retenciones_recibidas` | `recibidos.py:199` | `recibidos.py:201` |

9. Pendiente sobre la rama integrada real: las suites completas, el ensayo de la decisión 18 (en un solo `migrate` tocan
   `user_user` contabilidad 0004, 0007 y 0009 —esta con intentos de 1 s— y la clave `ultima_consulta_por` de importacion
   0009, y 0016 toma `pos_company`, `contabilidad_cuenta` y `contabilidad_movimientomanual`; cada ensayo se midió por
   separado) y el recorrido en navegador (decisión 19).
