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

## Nota (14/11/2026) — bloque 1 del cierre contable: plan de cuentas y su importación, 6 migraciones (sin publicar)

Rama `fase/contable-1-cuentas` sobre `74ebb3d`. Lo publicado es `e0f2902`, con `contabilidad 0003` y `tenancy 0012`
aplicadas. El bloque añade seis migraciones: dos tablas nuevas con su seguridad por filas, tres permisos repartidos por el
módulo del kardex y tres acciones de auditoría. Ninguna toca una tabla ni una columna que use la versión publicada.

| # | Migración | Qué hace | Vuelta |
|---|---|---|---|
| 1 | `contabilidad/0004_plan_de_cuentas` | tabla `contabilidad_cuenta` (código único por empresa sin distinguir mayúsculas, clave del envío única por empresa cuando no es nula, tipo `grupo` o `movimiento`, índice por empresa y padre) y permisos `view_cuenta`, `add_cuenta` y `change_cuenta` | borra la tabla |
| 2 | `contabilidad/0005_seguridad_por_filas_cuentas` | RLS `fpa_empresa` forzada en esa tabla (solo PostgreSQL) | quita la política |
| 3 | `contabilidad/0006_permisos_plan_cuentas` | añade los tres permisos al módulo «Kardex por producto» y ejecuta `sync_roles`: Propietario, Administrador y Contador ven, crean y editan; Consulta solo ve; Vendedor y Cliente, nada. No crea módulos ni cambia el menú | quita esos tres permisos del módulo y de los roles, por ids en las tablas intermedias; las filas de `Permission` se quedan |
| 4 | `contabilidad/0007_importacion_cuentas` | tabla `contabilidad_importacioncuentas` (lote: archivo privado, huella, filas leídas, columnas elegidas, estado, claves y resultado) y columna nula `lote_id` en `contabilidad_cuenta` | quita la columna y borra la tabla |
| 5 | `contabilidad/0008_seguridad_por_filas_importacion` | RLS `fpa_empresa` forzada en la tabla de lotes (solo PostgreSQL) | quita la política |
| 6 | `tenancy/0013_acciones_plan_cuentas` | acciones de auditoría `cuenta_creada`, `cuenta_modificada` y `cuentas_importadas` (solo `choices`) | solo `choices` |

**Orden.** Un solo `migrate --noinput`, como siempre. Las de contabilidad van en fila, de 0004 a 0008. `tenancy 0013` va
sobre `tenancy 0012`; no depende de las de contabilidad ni ellas de esta.

**Dependencia corregida a mano en 0004 y 0007.** `makemigrations` puso la última de `pos`, `0035_sale_ride_diseno`. Se
cambió por `pos 0034_cliente_nacimiento_opcional`, la que ya exige `contabilidad 0001`: las tablas solo necesitan la
empresa. Con 0035, la vuelta documentada del diseño de factura (`migrate pos 0034`) arrastraría el plan de cuentas y
borraría sus tablas. `makemigrations --check --dry-run` sigue sin cambios. Quien añada la siguiente migración de
contabilidad debe mirar lo mismo.

**Convivencia durante el despliegue.** `desplegar.sh` migra antes de cambiar el código, así que la versión publicada
atiende un rato sobre la base ya migrada. No le afecta: no conoce las dos tablas nuevas, la columna `lote_id` está en una
de ellas, `tenancy 0013` no cambia el esquema y los tres permisos que `0006` añade al módulo del kardex y a los roles no
los usa. No hay columnas nuevas en tablas que ya existían.

**Vuelta del bloque a lo publicado**, sin datos nuevos, en este orden:

```
migrate contabilidad 0003_modulo_kardex
migrate tenancy 0012_accion_diseno_factura
```

Quedan pendientes las seis de la tabla. El módulo del kardex vuelve a sus tres permisos, ningún rol conserva los del plan
de cuentas y el resto del menú y de los roles queda igual. Otra ida lo deja todo como estaba. Lo recorre
`tests/test_migracion_vuelta_fase.py::test_vuelta_del_plan_de_cuentas_a_lo_publicado`, por subproceso, sobre una
instalación SQLite con menú. Vuelta solo de la importación: `migrate contabilidad 0006_permisos_plan_cuentas`.

**Las otras vueltas documentadas:**

- La de la fase (`contabilidad zero`, `tributario zero`, …, `tenancy 0006`) deshace también estas seis: la prueba espera
  47 pendientes, las 41 de antes más estas.
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
`tests/test_cuentas_importacion.py`); `makemigrations --check --dry-run` sin cambios.

**No probado:**

- El ensayo sobre una copia del respaldo de producción y el ensayo con la aplicación atendiendo. Sus guiones están fuera
  del repositorio (`verif-firma/ensayo-fase/ensayo_migraciones_candidato.sh` y `ensayo-pe/guiones/`) y no se tocaron: su
  vuelta sigue apuntando al estado anterior a la fase. Para ensayar la vuelta de este bloque, los destinos son los dos de
  arriba.
- La base real.

**Choque conocido al fusionar con `fase/primera-entrega`.** Esa rama trae `tenancy/0013_acciones_borrador_factura`, también
sobre `tenancy 0012`, y cambia el conteo de `tests/test_migracion_vuelta_fase.py`. Al unirlas, una de las dos `0013` pasa
a `0014` sobre la otra, con sus `choices` completas, y el conteo y las listas de la prueba se suman.

## Nota (14/11/2026) — bloque 2 del cierre contable, corte 1: libro diario y apertura, 7 migraciones (sin publicar)

Rama `fase/contable-2-apertura` sobre el bloque 1 (`fase/contable-1-cuentas`, `84d07cc`); código final del corte `a5bedf4`.
Lo publicado sigue siendo `e0f2902` (`contabilidad 0003`, `tenancy 0012`); el bloque 1 tampoco está publicado. Todas las
migraciones de esquema del bloque se crean en este corte: las tablas de auxiliares, cartera inicial, ajustes, cobertura por
mes y documentos históricos (Partes C a F) nacen vacías y el corte 2 solo añade código.

| # | Migración | Qué hace | Vuelta |
|---|---|---|---|
| 1 | `contabilidad/0009_clases_de_cuenta` | dos columnas en `contabilidad_cuenta` (tabla del bloque 1), `clase` y `auxiliar`, `CharField(12)` con `db_default=''`, y dos CHECK: `cuenta_clase_valida` (los siete valores) y `cuenta_auxiliar_solo_movimiento` (`tipo = 'movimiento' OR auxiliar = ''`) | quita los CHECK y las columnas |
| 2 | `contabilidad/0010_libro_diario` | ocho tablas: `iniciocontable` (una por empresa; es el candado del libro), `ejerciciocontable`, `periodocontable`, `asiento`, `lineaasiento`, `saldocuentames`, `contabilizacion` y `registroclave`, con sus UNIQUE (también los parciales: un asiento de apertura vigente, un reverso por asiento, un asiento y un expediente vigentes por origen), CHECK e índices; permisos declarados `view_asiento`, `add_asiento`, `change_asiento`, `change_reverso_asiento`, los del período y los del ejercicio | borra las tablas |
| 3 | `contabilidad/0011_apertura` | once tablas: `apertura`, `lineaapertura`, `importacionapertura`, `respaldoapertura`, `ajusteapertura`, `auxiliarapertura`, `partidabancoapertura`, `aplicacionauxiliar`, `vinculohistorico`, `coberturaperiodo` y `eventoapertura`, con sus UNIQUE parciales (una confirmada y una en preparación por empresa), CHECK e índices; permisos `add_apertura`, `view_apertura`, `change_confirmacion_apertura`, `add_aplicacionauxiliar`, `change_aplicacionauxiliar` | borra las tablas |
| 4 | `contabilidad/0012_rls_libro_apertura` | RLS `fpa_empresa` ENABLE + FORCE en las 19 tablas (solo PostgreSQL) | quita las políticas |
| 5 | `contabilidad/0013_libro_inmutable` | seis funciones y sus disparadores (solo PostgreSQL): `fpa_linea_solo_insercion`, `fpa_linea_en_asiento_abierto`, `fpa_asiento_solo_sello_o_reverso`, `fpa_asiento_nace_abierto`, `fpa_asiento_sellado` (diferido, al confirmar la transacción) y `fpa_evento_solo_insercion`. Hacen el libro y la historia de la apertura de solo inserción también por SQL | `DROP TRIGGER` y `DROP FUNCTION` |
| 6 | `contabilidad/0014_permisos_apertura` | cuelga del módulo «Kardex por producto» los seis permisos que el bloque reparte (`view_asiento`, `view_apertura`, `add_apertura`, `change_confirmacion_apertura`, `add_aplicacionauxiliar`, `change_aplicacionauxiliar`) y ejecuta `sync_roles`: Propietario, Administrador y Contador, los seis; Consulta, los dos de ver; Vendedor y Cliente, nada. Ni módulos nuevos ni cambios del menú. Los permisos de bloques posteriores no cuelgan de ningún módulo: nadie los recibe | quita esos seis del módulo y de los roles, por ids en las tablas intermedias; las filas de `Permission` se quedan |
| 7 | `tenancy/0014_acciones_apertura` | las 25 acciones de auditoría del bloque (también las del corte 2) en `AuditLog.action` (solo `choices`) | solo `choices` |

**Ninguna restricción hacia la operación.** Leído con `sqlmigrate`: las claves foráneas de las tablas nuevas van solo a
`pos_company` (la empresa, como en toda tabla por empresa), entre tablas de `contabilidad` y a
`contabilidad_movimientomanual` (el kardex). Ninguna hacia `pos_*` salvo la empresa, `importacion_*`, `comprobantes_*`,
`cobros_*`, `adjuntos_*` ni el usuario: los autores son el par `<rol>_por_id` (entero sin FK) y `<rol>_por_nombre`, y las
referencias a clientes, proveedores, productos, cuentas por cobrar o por pagar y documentos importados son enteros con
índice, sin FK. Borrar una venta, una compra, una cuenta por cobrar, un producto o un usuario no lee ni escribe nada de
contabilidad (`tests/test_convivencia_versiones.py`, por SQL directo). El SQL leído está en
`/root/invoice15/contable/registros/bloque2-c1-sqlmigrate-sqlite.sql` (fuera del repositorio; en SQLite el `AddField` de 0009
reconstruye `contabilidad_cuenta` y repite sus FK del bloque 1, que no son nuevas).

**Orden.** Un solo `migrate --noinput`. Las de contabilidad van en fila, de 0009 a 0014; `tenancy 0014` va sobre
`tenancy 0013` (bloque 1) y no depende de ellas. Dependencias corregidas a mano, como en el bloque 1: `0009` depende solo
de `contabilidad 0008`, y `0010` y `0011` de `pos 0034_cliente_nacimiento_opcional`, no de la `pos 0035` que proponía
`makemigrations`: así la vuelta documentada del diseño de factura (`migrate pos 0034`) no arrastra el libro ni la apertura.
`makemigrations --check --dry-run`: sin cambios.

**Convivencia durante el despliegue** (la versión anterior atiende un rato sobre la base ya migrada): no conoce las 19
tablas; las dos columnas nuevas de `contabilidad_cuenta` llevan `db_default=''`, así que un INSERT que no las nombra (el
código del bloque 1, o uno por SQL) recibe `''` y cumple los dos CHECK (`tests/test_convivencia_versiones.py` comprueba
que toda columna añadida a una tabla existente es nula o con `db_default`); los disparadores solo están en tablas nuevas;
`tenancy 0014` no cambia el esquema. Lo que toca tablas que la versión anterior lee a cada petición es `0014_permisos_apertura`
(permisos del módulo y de los roles), como `0006` del bloque 1.

**Ida en el ensayo.** Comprobar que el rol de la aplicación crea las seis funciones de `0013` (en las pruebas las crea el
rol `fpa_dev`, sin superusuario). `fpa_asiento_sellado` no usa `SET` en su definición precisamente por eso: PostgreSQL no
deja fijar así una variable propia a quien no es superusuario.

**Vuelta del bloque a lo publicado**, sin datos nuevos, en este orden:

```
migrate contabilidad 0003_modulo_kardex
migrate tenancy 0012_accion_diseno_factura
```

Deshace las siete de este corte y las seis del bloque 1. Para volver solo hasta el final del bloque 1:

```
migrate contabilidad 0008_seguridad_por_filas_importacion
migrate tenancy 0013_acciones_plan_cuentas
```

El módulo del kardex se queda con lo suyo y con lo del plan de cuentas, ningún rol conserva los permisos del libro ni de la
apertura y el resto del menú y de los roles queda igual; otra ida lo deja todo como estaba. Lo recorre
`tests/test_migracion_vuelta_fase.py::test_vuelta_del_plan_de_cuentas_a_lo_publicado` (primero hasta el bloque 1, después
hasta lo publicado), por subproceso, sobre una instalación SQLite con menú. La vuelta de `0013` y la de `0012` en PostgreSQL
(quitar y volver a poner los disparadores y las políticas) las recorre `tests/test_zz_libro_inmutable_pg.py`.

**Las otras vueltas documentadas:**

- La de la fase (`contabilidad zero`, …, `tenancy 0006`) deshace también estas siete: la prueba espera 54 pendientes, las
  47 de antes más estas.
- La del diseño de factura (`configuracion 0003`, `pos 0034`, `tenancy 0011`) deshace además `tenancy 0014`, que va sobre
  0013 y esta sobre 0012. Las tablas del libro y de la apertura no se tocan (`sin_diseno` de la prueba incluye
  `tenancy.0014_acciones_apertura`).

**Recuperación que conserva lo posterior: vuelta solo de código** (`deploy/scripts/desplegar.sh --revertir`). Es la vuelta
para después de usar el bloque: la base queda migrada y el código anterior sigue atendiendo sobre ella. Ventas, cobros,
compras, emisión y kardex no dependen de nada de contabilidad, así que siguen igual y nada de lo registrado después de
publicar se pierde; el libro, la apertura y sus archivos quedan en la base, inaccesibles hasta volver a publicar el bloque.
Dos límites mientras dure:

- El código anterior no conoce `clase` ni `auxiliar`: cambiar a grupo una cuenta de movimiento que tiene auxiliar choca con
  el CHECK `cuenta_auxiliar_solo_movimiento` y la petición falla (no se guarda nada).
- El código anterior no sabe qué cuentas tienen movimientos en el libro o en la apertura: podría desactivar una o pasarla a
  grupo. Las líneas ya escritas no cambian (el libro es de solo inserción), pero al volver a publicar el bloque esa cuenta
  quedaría inactiva o de grupo con líneas. Mientras dure la vuelta, no tocar el plan de cuentas.

El ensayo de la decisión 18 (con la versión publicada atendiendo, y la vuelta de solo código después de confirmar una
apertura) lo ejecuta el orquestador al cerrar el corte; no está hecho en esta nota.

**Restauración, último recurso.** `deploy/scripts/restaurar.sh <volcado> <versión anterior> [--ejecutar]` vuelve la base, el
código y los estáticos al volcado previo y **pierde todo lo registrado después** (ventas, cobros, compras, la apertura y sus
archivos). `migrate` hacia atrás con datos nuevos tampoco sirve: borraría el libro y la apertura (los archivos de lotes y respaldos quedan en
`privado/empresas/<uuid de la empresa>/apertura/` de `FPA_ARCHIVOS`, que la vuelta no borra; restaurar exige también esa
carpeta).

**Probado:** ida, vuelta al bloque 1, vuelta a lo publicado y otra ida, y las vueltas de la fase y del diseño, en
`tests/test_migracion_vuelta_fase.py` (SQLite, por subproceso, en las dos suites); las políticas forzadas de las 19 tablas
(`tests/test_rls_modelos_de_empresa.py` y `tests/test_rls_libro_apertura.py`, PostgreSQL); los disparadores y su vuelta
(`tests/test_zz_libro_inmutable_pg.py`); convivencia de columnas y borrados por SQL (`tests/test_convivencia_versiones.py`);
`makemigrations --check --dry-run` sin cambios.

**No probado:** el ensayo sobre una copia del respaldo de producción con la aplicación atendiendo y la vuelta de solo código
con el código anterior (decisión 18; los guiones de `ensayo-pe/guiones/` siguen apuntando a la vuelta anterior a la fase y
no se tocaron), y la base real.

**Choque conocido al integrar con `fase/primera-entrega`** (no se hizo rebase ni fusión): esa rama trae
`tenancy/0013_acciones_borrador_factura`, también sobre `tenancy 0012`, e `importacion 0008-0009`. Aquí `tenancy 0013` es del
bloque 1 y `0014` de este corte. Al integrar, las de tenancy se renumeran en fila (las tres sobre la anterior, cada una con
las `choices` completas de todas), y se suman el conteo y las listas de `tests/test_migracion_vuelta_fase.py` (`54`,
`sin_diseno`, `BLOQUE_2`) y lo que esa rama traiga en `tests/test_convivencia_versiones.py`. Las de contabilidad no chocan
con esa rama, pero sí con el cierre del bloque 1, que trae su propia `contabilidad 0009_anular_autores_en_la_base`: una de
las dos pasa a la siguiente libre y las de este corte se corren en fila detrás.
