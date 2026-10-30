# Migraciones de la fase contable (D0, Etapa 1 y Etapa 2) — resumen integrado

29/10/2026 · `plataforma` con D0 Fase A, Proformas, Compras y Ventas fusionadas, más el commit final de integración. El
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
en las tablas intermedias, como `proformas/0003`, para poder deshacerla junto con las de D0.

## Precauciones de aplicación (cuando la propietaria autorice publicar; nada de esto se ejecutó)

1. **Volcado previo** de la base publicada (lo hace `deploy/scripts/desplegar.sh`). Es el camino de vuelta si después
   de publicar se registran datos nuevos.
2. **Ensayo sobre una copia temporal de ese volcado**, con el código nuevo y el rol de la aplicación, antes de tocar la
   base real: `migrate`, `showmigrations` sin pendientes, `manage.py check` y `makemigrations --check --dry-run`.
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
  - en las suites completas de SQLite y PostgreSQL del commit entregado: ida y vuelta de `comprobantes` 0013↔0015 con
    sus guardias (`tests/test_zzz_vigencias_migraciones.py`), que también deshace y rehace las cuatro de Ventas en
    `comprobantes`; ida y vuelta de `proformas/0003` sobre un menú real (`tests/test_migracion_proformas.py`); datos
    «de antes» de Compras y de Ventas migrados sin cambios y, en Ventas, revertidos y migrados otra vez (SQLite, por
    subproceso);
  - en las ramas: reversa de Compras hasta `pos 0019` en una base SQLite vacía;
  - **no probado:** la reversa completa de Compras y de Ventas en PostgreSQL y cualquier `migrate` sobre una copia del
    volcado de producción. El ensayo del punto 2 de la aplicación cubre la ida; si se quiere tener la vuelta ensayada,
    se hace en la misma copia antes de publicar.

## Costo esperado

Columnas nulas o con valor constante, tablas nuevas vacías, políticas RLS y filas de permisos: en PostgreSQL 16 son
cambios de catálogo con bloqueos exclusivos breves. Con el volumen actual (decenas de filas por tabla) se espera que todo
tarde segundos. Las cifras por migración están en el documento de cada rama.
