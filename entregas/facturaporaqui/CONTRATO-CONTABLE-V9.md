# Contrato contable v9: rutas, datos y bloqueos por entrega (Claude → Codex)

04/11/2026. Base: la propuesta navegable `referencias/frontend-v9/entregas/facturaporaqui/propuestas/ux-v9/` (seis pantallas,
datos simulados) y su lista de datos pendientes `CONTRATO-FRONTEND-PENDIENTE.md`. Este documento sustituye esa lista como
contrato: fija qué se conecta hoy con rutas existentes, la forma exacta de las rutas nuevas y, por entrega, **solo** el dato o
la decisión que la bloquea. Las maquetas no entran al menú como funciones disponibles hasta que exista su ruta.

## Reglas comunes (vigentes; las rutas nuevas las cumplen igual)

- Todo bajo `/tributario/` o `/contabilidad/`: el Complemento Contable sigue **cerrado** salvo las empresas de
  `FPA_COMPLEMENTO_CONTABLE_REVISION` (páginas → `/dashboard/` con aviso; API y descargas → 403
  `{"codigo": "complemento_pendiente"}`). D9: precios decididos ($150 al año por módulo para una empresa y $250 para
  multiempresa); impuestos, alcance multiempresa y condiciones de activación pendientes. No se abre por esta nota.
- Empresa activa y permisos en el servidor. `empresa=<id>` en consultas y envíos: si no es la activa, 409
  `{"error": …, "codigo": "empresa_cambiada"}` sin leer ni escribir nada de la otra. Sin permiso: 403 en API, 302 en páginas.
- Importes como texto con dos decimales (`"115.00"`); desconocido = `null`, nunca `0`. Fechas `AAAA-MM-DD`; meses `AAAA-MM`.
- Envíos con `clave` (idempotencia): repetir la misma clave devuelve el mismo resultado con `repetido: true`.
- Concurrencia: los recursos editables traen `version`; si cambió, 409 `{"codigo": "version"}` y la interfaz ofrece recargar.
- Errores: `{"error": texto general, "errores": {campo: [textos]}}` (400); por fila en importaciones.

## Mapa de pantallas

| Pantalla v9 | Se conecta hoy | Entrega de backend | Bloqueo real |
|---|---|---|---|
| Inicio contable | pendientes de la revisión del mes (`/tributario/api/revision/`) | C1 `GET /contabilidad/api/inicio/` | ninguno |
| Plan de cuentas | — | C2 cuentas por empresa (modelo, API, permisos) | ninguno (D5 solo para ofrecer una plantilla predefinida) |
| Importación del plan | — | C3 vista previa por filas y confirmación | ninguno para la función; el piloto, ver abajo |
| Asientos por comprobante | — | C4 | **D7** (matriz de asientos validada) y el plan de cuentas de cada empresa (C2/C3) |
| Revisión del mes | revisión, libros y ATS existentes | C5 evidencias de presentación | cierre/reapertura: **decisión** de qué bloquea un mes cerrado; saldos anteriores: apertura (C6) |
| Reportes | libros, borradores 104/103, kardex e inventario | C6 apertura y mayor | estados financieros: **D5**, **D7** y saldos de apertura validados |
| Puntos de emisión | `/configuracion/puntos/` (establecimientos, puntos, autorizados, selección) | C7 cupo y verificación | ninguno si se confirma la definición de «verificado» propuesta abajo |
| Piloto NEXALLTI | — | usa C2/C3 | **dato:** su Excel real; **decisión:** incluir su RUC en la lista de revisión del complemento |

## C1 — Inicio contable (sin bloqueo)

`GET /contabilidad/api/inicio/?empresa=<id>` — permiso `view_kardex` o `view_revision` (cualquiera de los dos).

```
200 {"empresa": {"id": 2, "ruc": "0990000000001", "nombre": "DEMOSTRACION S.A."},
     "capacidades": {"revision": true, "libros": true, "kardex": true, "plan_cuentas": {"ver": true, "editar": false}},
     "etapas": {"plan_cuentas": {"estado": "sin_configurar", "cuentas": null, "importado_en": null},
                "apertura": {"estado": "pendiente", "fecha": null},
                "conciliacion": {"estado": "no_disponible", "causa": "Bancos y conciliación todavía no existen."}},
     "pendientes": [{"origen": "revision", "codigo": "sin_respaldo", "titulo": "Compras sin respaldo", "cantidad": 3,
                     "url": "/tributario/revision/?mes=2026-11#respaldos"},
                    {"origen": "capturas", "codigo": "recibo_por_completar", "titulo": "Recibos por completar", "cantidad": 2,
                     "url": "/adjuntos/capturas/"}]}
```

`etapas.*.estado`: `sin_configurar | importado | pendiente | no_disponible`; nunca «completado» por haber abierto una
pantalla. `pendientes` sale de la revisión del mes, las capturas por completar y los documentos importados pendientes.

## C2 — Plan de cuentas (sin bloqueo)

Cuenta por empresa: `codigo` (único por empresa sin distinguir mayúsculas, ≤ 30), `nombre` (≤ 200), `padre_id` (grupo de
la misma empresa o `null`), `tipo` (`grupo` | `movimiento`), `activa`, `version`. Reglas: un grupo no recibe movimientos;
una cuenta con hijas es grupo; sin ciclos; no se borra una cuenta con hijas o movimientos (se desactiva).
Permisos (como el kardex): ver `view_cuenta` (Propietario, Administrador, Contador, Consulta); crear y editar
`add_cuenta` / `change_cuenta` (Propietario, Administrador, Contador). Vendedor y Cliente no.

- `GET /contabilidad/api/cuentas/?q=&empresa=` → `{"cuentas": [{"id", "codigo", "nombre", "padre_id", "tipo", "activa",
  "hijas": 2, "version": 1}], "capacidades": {"crear", "editar", "importar"}}`. Con `q`, devuelve las coincidencias y sus
  antepasados (la interfaz conserva la jerarquía).
- `POST /contabilidad/api/cuentas/` `{clave, codigo, nombre, padre_id, tipo}` → 201 `{"cuenta": {…}}` (200 `repetido`).
  400 `{"errores": {"codigo": ["Ya existe la cuenta 1.1.01 en esta empresa."]}}`, `{"padre_id": ["El padre debe ser un
  grupo de esta empresa."]}`.
- `PATCH /contabilidad/api/cuentas/<id>/` `{nombre, padre_id, tipo, activa, version}` → 200; 409 `version`; 400
  `{"tipo": ["Tiene cuentas hijas: debe seguir siendo grupo."]}`, `{"padre_id": ["Crearía un ciclo."]}`.

## C3 — Importación del plan de cuentas (sin bloqueo)

Archivo CSV (UTF-8, `;` o `,`) o XLSX (primera hoja), hasta 2 MB y 5 000 filas. Columnas reconocidas por encabezado:
código, nombre, padre (opcional: si falta, la jerarquía sale de los puntos del código) y tipo (opcional: grupo si tiene
hijas). Nada se crea hasta confirmar.

- `POST /contabilidad/api/cuentas/importar/` (multipart `archivo`, `clave`) → 200 `{"lote": {"id": 7, "estado":
  "vista_previa", "archivo": "plan.xlsx", "columnas": {"codigo": "Código", "nombre": "Cuenta", "padre": null, "tipo":
  "Tipo"}, "filas": [{"fila": 2, "codigo": "1.1.01", "nombre": "Caja", "padre": "1.1", "tipo": "movimiento",
  "estado": "valida", "errores": []}, {"fila": 9, …, "estado": "error", "errores": ["El padre 1.9 no existe."]}],
  "resumen": {"validas": 40, "con_error": 1, "duplicadas": 2}}}`.
- `POST /contabilidad/api/cuentas/importar/<id>/mapeo/` `{codigo, nombre, padre, tipo}` (nombre de columna) → la misma
  vista previa recalculada.
- `POST /contabilidad/api/cuentas/importar/<id>/confirmar/` `{clave, duplicadas: "omitir" | "actualizar_nombre"}` → 200
  `{"lote": {"estado": "confirmado", "creadas": 40, "actualizadas": 0, "omitidas": 2, "confirmado_en": "2026-11-04"}}`;
  con filas en error, 400 `{"codigo": "filas_con_error"}`; lote ya confirmado o de otra empresa, 409.

## C4 — Asientos por comprobante (bloqueado por D7)

Sin la matriz validada (qué cuentas debita y acredita cada tipo de documento, IVA, retenciones y cobros) no se propone
ningún asiento. Forma de lectura para cuando exista:
`GET /contabilidad/api/asientos/?mes=&estado=&empresa=` → `{"asientos": [{"id", "version", "fecha", "documento": {"tipo",
"id", "numero", "url"}, "origen", "estado": "borrador | con_excepcion | confirmado | anulado", "lineas": [{"cuenta":
{"id", "codigo", "nombre"} | null, "concepto", "debe", "haber"}], "totales": {"debe", "haber", "cuadra"}, "excepciones":
[{"codigo", "texto", "linea"}], "capacidades": {"resolver", "confirmar"}}]}`; `POST …/<id>/resolver/` `{linea, cuenta_id,
version}`; `POST …/<id>/confirmar/` `{version}`. «Cuadra» no significa contabilizado.

## C5 — Revisión del mes (parcial, sin bloqueo para las evidencias)

Hoy: `GET /tributario/api/revision/?mes=&empresa=` (documentos y excepciones por categoría, con el documento de origen),
`/tributario/api/libros/<libro>/` y `/tributario/api/ats/` para «IVA y ATS» (contratos en HANDOFF, sección de libros,
revisión, ATS y borradores).
Nuevo: evidencias de presentación, privadas y ligadas al período. `POST /tributario/api/revision/evidencias/` (multipart
`archivo` PDF/JPG/PNG hasta 8 MB, `tipo`: `104 | 103 | ats | otro`, `mes`, `referencia`, `fecha_presentacion`, `clave`) →
201 `{"evidencia": {"id", "tipo", "mes", "referencia", "fecha_presentacion", "subida_por", "subida_en", "url"}}`; `GET` lista
del mes; descarga `GET /tributario/revision/evidencias/<id>/archivo/` con permiso y empresa. Se muestra «evidencia
registrada», nunca «declaración presentada».
**Decisión que bloquea el cierre/reapertura:** qué impide un mes cerrado (¿editar, anular o registrar documentos con fecha
del mes?) y quién cierra y reabre. Los saldos anteriores dependen de la apertura (C6).

## C6 — Reportes (parcial)

Hoy: libros con exportación, borradores 104/103, kardex e inventario valorizado. Toda respuesta de reporte nuevo trae
`provisional: true | false` y `causas: [texto]`. **Bloqueo de mayor y estados financieros:** D5 (plan de cuentas o catálogo
Supercias), D7 (matriz) y saldos de apertura validados por el contador.

## C7 — Puntos de emisión (sin bloqueo si se acepta la definición)

Hoy: `/configuracion/puntos/estado.json` (establecimientos y puntos, autorizados por usuario y selección). Se añade a esa
respuesta: `{"cupo": {"maximo": 3, "usados": 2}, "puntos": [{…, "verificacion": {"estado": "verificado | pendiente",
"evidencia": {"tipo": "comprobante_autorizado", "numero": "001-001-000000123", "fecha": "2026-10-20", "url": …} | null}}]}`
y el alta de un punto por encima del cupo responde 400 `{"codigo": "cupo"}`. El límite es interno (instrucciones de la
propietaria): no se presenta como regla del SRI.
**Definición propuesta de «verificado»:** el punto tiene al menos un comprobante autorizado por el SRI en producción (la
evidencia es ese comprobante). Si se quiere otra evidencia (por ejemplo, el catastro del SRI), decirlo antes de C7.

## Piloto NEXALLTI

No se usan cifras de ejemplo ni se marca nada como importado. **Bloquean:** el Excel real de su plan de cuentas (y, si se
quieren saldos, la apertura firmada por su contador) y la decisión de incluir su RUC en la lista de revisión del
complemento mientras D9 no fije impuestos y alcance.

## Orden propuesto

C1 → C2 → C3 (desbloquean el inicio, el plan y su importación) → C7 → C5 (evidencias) → C4 y C6 cuando lleguen D7, D5 y la
apertura. Codex conecta cada pantalla cuando su ruta esté publicada; hasta entonces, la maqueta queda en `entregas/`.
