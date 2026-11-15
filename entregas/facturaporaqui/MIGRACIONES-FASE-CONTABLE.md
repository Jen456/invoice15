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
  dos ensayos nadie las retuvo.
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

## Nota (14/11/2026) — bloque 2 del cierre contable, corte 1: libro diario y apertura, 7 migraciones (sin publicar)

Rama `fase/contable-2-apertura`, que salió del bloque 1 en `84d07cc` (código final del corte `a5bedf4`) y el 15/11/2026 se
unió al bloque 1 final (`fase/contable-1-cuentas`, `8a421b3`) sin rebase: las seis de contabilidad de este corte, que
nacieron como `0009`–`0014`, son ahora `0010`–`0015` con los mismos sufijos (ver «Unión con el bloque 1 final», al final
de esta nota). Lo publicado sigue siendo `e0f2902` (`contabilidad 0003`, `tenancy 0012`); el bloque 1 tampoco está
publicado. Todas las migraciones de esquema del bloque se crean en este corte: las tablas de auxiliares, cartera inicial,
ajustes, cobertura por mes y documentos históricos (Partes C a F) nacen vacías y el corte 2 solo añade código.

| # | Migración | Qué hace | Vuelta |
|---|---|---|---|
| 1 | `contabilidad/0010_clases_de_cuenta` | dos columnas en `contabilidad_cuenta` (tabla del bloque 1), `clase` y `auxiliar`, `CharField(12)` con `db_default=''`, y dos CHECK: `cuenta_clase_valida` (los siete valores) y `cuenta_auxiliar_solo_movimiento` (`tipo = 'movimiento' OR auxiliar = ''`) | quita los CHECK y las columnas |
| 2 | `contabilidad/0011_libro_diario` | ocho tablas: `iniciocontable` (una por empresa; es el candado del libro), `ejerciciocontable`, `periodocontable`, `asiento`, `lineaasiento`, `saldocuentames`, `contabilizacion` y `registroclave`, con sus UNIQUE (también los parciales: un asiento de apertura vigente, un reverso por asiento, un asiento y un expediente vigentes por origen), CHECK e índices; permisos declarados `view_asiento`, `add_asiento`, `change_asiento`, `change_reverso_asiento`, los del período y los del ejercicio | borra las tablas |
| 3 | `contabilidad/0012_apertura` | once tablas: `apertura`, `lineaapertura`, `importacionapertura`, `respaldoapertura`, `ajusteapertura`, `auxiliarapertura`, `partidabancoapertura`, `aplicacionauxiliar`, `vinculohistorico`, `coberturaperiodo` y `eventoapertura`, con sus UNIQUE parciales (una confirmada y una en preparación por empresa), CHECK e índices; permisos `add_apertura`, `view_apertura`, `change_confirmacion_apertura`, `add_aplicacionauxiliar`, `change_aplicacionauxiliar` | borra las tablas |
| 4 | `contabilidad/0013_rls_libro_apertura` | RLS `fpa_empresa` ENABLE + FORCE en las 19 tablas (solo PostgreSQL) | quita las políticas |
| 5 | `contabilidad/0014_libro_inmutable` | seis funciones y sus disparadores (solo PostgreSQL): `fpa_linea_solo_insercion`, `fpa_linea_en_asiento_abierto`, `fpa_asiento_solo_sello_o_reverso`, `fpa_asiento_nace_abierto`, `fpa_asiento_sellado` (diferido, al confirmar la transacción) y `fpa_evento_solo_insercion`. Hacen el libro y la historia de la apertura de solo inserción también por SQL | `DROP TRIGGER` y `DROP FUNCTION` |
| 6 | `contabilidad/0015_permisos_apertura` | cuelga del módulo «Kardex por producto» los seis permisos que el bloque reparte (`view_asiento`, `view_apertura`, `add_apertura`, `change_confirmacion_apertura`, `add_aplicacionauxiliar`, `change_aplicacionauxiliar`) y ejecuta `sync_roles`: Propietario, Administrador y Contador, los seis; Consulta, los dos de ver; Vendedor y Cliente, nada. Ni módulos nuevos ni cambios del menú. Los permisos de bloques posteriores no cuelgan de ningún módulo: nadie los recibe | quita esos seis del módulo y de los roles, por ids en las tablas intermedias; las filas de `Permission` se quedan |
| 7 | `tenancy/0014_acciones_apertura` | las 25 acciones de auditoría del bloque (también las del corte 2) en `AuditLog.action` (solo `choices`) | solo `choices` |

**Ninguna restricción hacia la operación.** Leído con `sqlmigrate`: las claves foráneas de las tablas nuevas van solo a
`pos_company` (la empresa, como en toda tabla por empresa), entre tablas de `contabilidad` y a
`contabilidad_movimientomanual` (el kardex). Ninguna hacia `pos_*` salvo la empresa, `importacion_*`, `comprobantes_*`,
`cobros_*`, `adjuntos_*` ni el usuario: los autores son el par `<rol>_por_id` (entero sin FK) y `<rol>_por_nombre`, y las
referencias a clientes, proveedores, productos, cuentas por cobrar o por pagar y documentos importados son enteros con
índice, sin FK. Borrar una venta, una compra, una cuenta por cobrar, un producto o un usuario no lee ni escribe nada de
contabilidad (`tests/test_convivencia_versiones.py`, por SQL directo). El SQL leído está en
`/root/invoice15/contable/registros/bloque2-c1-sqlmigrate-sqlite.sql` (fuera del repositorio, leído antes de la unión, con
la numeración anterior; en SQLite el `AddField` de 0010 reconstruye `contabilidad_cuenta` y repite sus FK del bloque 1, que
no son nuevas).

**Orden.** Un solo `migrate --noinput`. Las de contabilidad van en fila, de 0010 a 0015, detrás de la 0009 del bloque 1;
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

**Ida en el ensayo.** Comprobar que el rol de la aplicación crea las seis funciones de `0014` (en las pruebas las crea el
rol `fpa_dev`, sin superusuario). `fpa_asiento_sellado` no usa `SET` en su definición precisamente por eso: PostgreSQL no
deja fijar así una variable propia a quien no es superusuario.

**Vuelta del bloque a lo publicado**, sin datos nuevos, en este orden:

```
migrate contabilidad 0003_modulo_kardex
migrate tenancy 0012_accion_diseno_factura
```

Deshace las siete de este corte (`contabilidad 0015` a `0010` y `tenancy 0014`) y después las siete del bloque 1
(`contabilidad 0009` a `0004` y `tenancy 0013`). Para volver solo hasta el final del bloque 1:

```
migrate contabilidad 0009_anular_autores_en_la_base
migrate tenancy 0013_acciones_plan_cuentas
```

El módulo del kardex se queda con lo suyo y con lo del plan de cuentas, ningún rol conserva los permisos del libro ni de la
apertura y el resto del menú y de los roles queda igual; otra ida lo deja todo como estaba. Lo recorre
`tests/test_migracion_vuelta_fase.py::test_vuelta_del_plan_de_cuentas_a_lo_publicado` (primero hasta el bloque 1, después
hasta lo publicado), por subproceso, sobre una instalación SQLite con menú. La vuelta de `0014` y la de `0013` en PostgreSQL
(quitar y volver a poner los disparadores y las políticas) las recorre `tests/test_zz_libro_inmutable_pg.py`.

**Las otras vueltas documentadas:**

- La de la fase (`contabilidad zero`, …, `tenancy 0006`) deshace también estas siete: la prueba espera 55 pendientes, las
  48 de antes (47 más la 0009 del bloque 1) y estas.
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
las `choices` completas de todas), y se suman el conteo y las listas de `tests/test_migracion_vuelta_fase.py` (`55`,
`sin_diseno`, `BLOQUE_2`) y lo que esa rama traiga en `tests/test_convivencia_versiones.py`. Las de contabilidad no chocan
con esa rama. Con el cierre del bloque 1, que trae su propia `contabilidad 0009_anular_autores_en_la_base`, chocaban: está
resuelto en la unión de abajo.

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
  pendientes.
- **`tests/test_zz_cuentas_0009_bloqueo_pg.py`** (bloque 1) vuelve contabilidad a `0008` para medir 0009 con `user_user`
  retenido: con este corte encima eso deshace también 0010–0015 (las 19 tablas, sus políticas, los seis disparadores y sus
  funciones y los permisos del módulo) y, al terminar, migra a las hojas del grafo, que las rehace.
