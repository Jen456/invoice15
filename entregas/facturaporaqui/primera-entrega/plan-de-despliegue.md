# Plan de despliegue y ensayo de la actualización (primera entrega)

14/11/2026 · Rama `fase/primera-entrega`, código `3e30da4` (PR #1). Producción: `e0f2902`. **Sin publicar: espera la
aprobación del PR.** Responde a R1 de la revisión de Codex: la migración es compatible con la versión que sigue
atendiendo, y su duración y sus bloqueos están medidos.

## En pocas palabras

- **Las cuatro migraciones se aplican con la versión publicada atendiendo.** En cinco pasadas del ensayo no falló ninguna
  petición antes de migrar, mientras se migraba ni después. Las pantallas que tocan proformas o documentos importados, y
  el inicio de sesión, esperan mientras dura cada migración: entre 1,2 y 5,5 s, con la máquina cargada.
- **El cambio de proceso sí corta.** `desplegar.sh` reinicia gunicorn, como en todas las publicaciones anteriores: entre
  0,6 y 1,5 s sin aceptar conexiones y entre 3 y 6 s hasta la primera respuesta. Evitarlo exige otro cambio (activar el
  socket por systemd), que no es parte de esta corrección.
- **Volver al código anterior con la base ya migrada funciona**: importa y cotiza sin errores.
- **Sin el arreglo** (`10d75f0`), la versión publicada deja de importar en cuanto se aplica `importacion 0009`: 27 de 27
  importaciones fallidas («null value in column "ultima_consulta_mensaje"…»).

## Qué cambia en la base

| Migración | Qué hace | Por qué la versión publicada sigue funcionando |
|---|---|---|
| `importacion 0008` | Solo `choices` | No ejecuta SQL |
| `importacion 0009` | Cinco columnas en `importacion_documentoimportado` y el relleno del último intento | Tres son nulas y dos llevan `DEFAULT ''` en la base; los 8 códigos de estado son los de antes |
| `proformas 0004` | Dos columnas en `proformas_proforma` y la tabla `proformas_borradorfactura` con su RLS | Las columnas llevan `DEFAULT ''` y `DEFAULT false` en la base; la tabla nueva no la usa |
| `tenancy 0013` | Solo `choices` | No ejecuta SQL |

`tests/test_convivencia_versiones.py` lo comprueba en SQLite y en PostgreSQL con los modelos de la versión publicada.

## Cómo se ensayó

- **Dónde:** VM101, sin tocar producción (mismo PID del servicio antes y después, 0 reinicios). Base `fpa_ensayo_pe`,
  restaurada antes de cada pasada del respaldo diario del 13/11/2026: 32 documentos importados (28 «declarada en el
  archivo» y 4 «no autorizada»), 2 proformas, 38 ventas, 105 clientes y 12 empresas. Se borró al terminar.
- **Versiones:** `e0f2902` y la nueva, armadas como lo hace `desplegar.sh` (git archive y entorno virtual con hashes),
  con gunicorn en 127.0.0.1:8791 y las opciones de la unidad (2 workers).
- **Sin efectos fuera:** entorno propio (no el de producción), SRI simulado dentro del proceso, correo en memoria y
  salida de red cerrada. Un comercio ficticio creado en la copia hace todo el tráfico.
- **Tráfico continuo** (4 hilos): `/login/`, panel, listas, alta de proformas e importación de XML ficticios.
- **Secuencia de cada pasada:** 20 s de línea base con `e0f2902` → `migrate` de la versión nueva con el tráfico en
  marcha → 30 s de `e0f2902` sobre la base migrada (con tres verificaciones que el SRI simulado rechaza) → cambio de
  proceso como `systemctl restart` → 30 s con la versión nueva y `completar_consultas_de_la_version_anterior()` → vuelta
  a `e0f2902` sin revertir migraciones, 20 s → comparación de las filas que ya existían.
- **Bloqueos:** muestreo de `pg_locks` y `pg_stat_activity` cada 5 a 100 ms.
- **Condiciones:** la máquina estuvo compartida con otras pruebas y con los sitios que aloja (carga entre 4,3 y 13 con 6
  núcleos; un commit tardó entre 2 y 330 ms de mediana). Los tiempos están inflados y varían entre pasadas.

## Resultados

Las migraciones de `5961efb`, `39c05a1` y `3e30da4` son las mismas (solo cambia un comentario de `importacion 0009`), y
`3e30da4` añade a `39c05a1` una línea de JavaScript.

| Pasada | Versión nueva | Las 4 migraciones | Bloqueo exclusivo: importados / proformas | Espera máxima de la aplicación | Peticiones fallidas (antes, al migrar, ventana, versión nueva, vuelta) | Cambio de proceso: sin aceptar / primera respuesta / fallidas |
|---|---|---|---|---|---|---|
| principal-1 | `5961efb` | 9,9 s | 2,1 s / 5,5 s | 5,5 s | 0 | 0,74 s / 4,1 s / 26 |
| principal-2 | `5961efb` | 6,5 s | 2,2 s / 2,7 s | 2,6 s | 0 | 0,73 s / 4,9 s / 26 |
| principal-3 | `5961efb` | 7,8 s | 1,2 s / 4,0 s | 4,0 s | 0 | 0,59 s / 4,1 s / 22 |
| final-1 | `39c05a1` | 6,4 s | 1,5 s / 2,7 s | 2,7 s | 0 | 0,66 s / 3,2 s / 24 |
| final-2 | `39c05a1` | 10,5 s | 3,3 s / 4,8 s | 4,8 s | 0 | 1,46 s / 5,6 s / 47 |

- **Mientras se migra** no falla nada: las peticiones que tocan esas dos tablas esperan a que termine cada migración. El
  bloqueo dura toda la transacción de cada una; el relleno de datos (4 documentos consultados) no pesa. Sobre
  `tenancy_auditlog` no se vio ningún bloqueo.
- **Ventana con la versión publicada sobre la base migrada:** entre 9 y 20 importaciones y entre 29 y 53 proformas por
  pasada, todas correctas. Sus tres verificaciones quedaron «no autorizada» sin resultado y la versión nueva las completó
  como «rechazo anterior» (3 y, en la segunda llamada, 0).
- **Cambio de proceso:** las fallidas son conexiones rechazadas (18 a 43) o cortadas (3 o 4) del generador, que insiste
  sin pausa; ninguna respuesta 5xx. No se midió con nginx delante.
- **Vuelta al código anterior** con la base ampliada: 0 peticiones fallidas tras su propio cambio de proceso; importa y
  cotiza.
- **Integridad:** las filas que ya existían no cambian (mismos conteos y misma huella de sus columnas anteriores en
  documentos importados, eventos, proformas, ventas y clientes). Los 4 documentos «no autorizada» quedan con el mismo
  estado y el resultado «rechazo anterior», con su nota, su usuario y sus fechas.
- **Control sin el arreglo** (`10d75f0`): `migrate` termina bien, pero desde 0,7 s después de `importacion 0009` fallan
  las 27 importaciones de la versión publicada (`NotNullViolation` en `ultima_consulta_mensaje`); lo demás sigue.
- **Escala:** con 5.000 documentos ficticios ya consultados, `importacion 0009` mantuvo el bloqueo exclusivo 19,7 s y el
  sitio entero esperó ese tiempo (sin errores: el corte de gunicorn es a los 60 s). Son unos 3,5 ms por documento
  consultado; hoy hay 4.
- **Estáticos:** `collectstatic --clear`, paso que `desplegar.sh` ya tenía, deja sin `staticfiles.json` entre 0,7 y 6 s
  y sin los CSS y JS con huella entre 0,3 y 0,5 s (más con la máquina cargada). La aplicación no dio errores por ello.

Guiones, registros y `resultados.json`: VM101 `/root/invoice15/ensayo-pe/`.

## Orden de publicación

1. PR #1 aprobado y aprobación expresa de la propietaria.
2. `bash deploy/scripts/desplegar.sh pruebas <hash>`. No hay pasos manuales nuevos: código, entorno, volcado previo,
   migraciones, estáticos, comprobación, cambio de `current` y reinicio. Conviene un momento de poca actividad: las
   esperas y el corte son los medidos arriba.
3. Después, sin intervención: la tarea programada de importación (cada 5 minutos) completa lo que la versión publicada
   haya verificado entre la migración y el reinicio.
4. Comprobaciones de solo lectura: `REVISION`, migraciones aplicadas, `/login/` 200, registro del servicio sin errores y
   los 4 documentos «no autorizada» de la empresa 17 con el resultado «rechazo anterior». Conviene verificarlos de nuevo
   desde su ficha (aviso de `HANDOFF.md`).

## Vuelta atrás

- **Solo el código:** `bash deploy/scripts/desplegar.sh pruebas --revertir`. La versión anterior funciona sobre la base
  ampliada (ensayado). Mientras se use así:
  - si vuelve a verificar un documento que ya tenía resultado, deja su estado y no actualiza el detalle del último
    intento; al publicar otra vez la versión nueva conviene verificar de nuevo esos documentos;
  - no conoce las facturas en borrador: eliminar un cliente o un usuario que figure en una falla con un error de la
    base, sin perder nada. Si ya hay borradores, lo limpio es revertir también la base.
- **También la base** (con el código nuevo todavía activo, antes de revertir el código): `migrate importacion
  0007_lotes_de_claves`, `migrate proformas 0003_modulo_proformas` (borra las facturas en borrador; ninguna salió al SRI)
  y `migrate tenancy 0012_accion_diseno_factura`. O restaurar el volcado previo que deja `desplegar.sh`.

## Lo que este plan no resuelve

- **El corte del reinicio** (menos de 2 s rechazando conexiones). Para eliminarlo, systemd tendría que mantener abierto
  el socket de gunicorn durante el reinicio: es un cambio de las unidades de servicio, con su propia aprobación.
- **Los estáticos durante `collectstatic --clear`**: ya ocurría en cada publicación.
- **El relleno bajo el bloqueo exclusivo**: con el volumen de hoy son milisegundos. Si antes de publicar hubiera miles de
  documentos ya consultados, convendría pasar el relleno a una migración propia.
