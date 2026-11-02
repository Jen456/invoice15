# Migraciones de los comprobantes de pago adjuntos (`core/adjuntos`)

30/10/2026. Tres migraciones nuevas, sin publicar, que se suman a las 19 de la fase contable (ver `MIGRACIONES-FASE-CONTABLE.md`).

| Migración | Qué hace | Vuelta |
|---|---|---|
| `adjuntos/0001_inicial` | tabla `adjuntos_adjunto` (FK a `pos_company` y al usuario; índice por empresa, tipo y id de documento; índice por `sha256`) | borra la tabla; los archivos de `privado/empresas/<uuid>/comprobantes-pago/` quedan en disco |
| `adjuntos/0002_seguridad_por_filas` | RLS de PostgreSQL con la política `fpa_empresa` (igual que `proformas/0002`) | quita la política |
| `adjuntos/0003_modulo_comprobantes_de_pago` | permisos de la app, módulo `/adjuntos/` «Comprobantes de pago» en «Administrativo» (orden 4) y `sync_roles` (el Contador recibe `add_adjunto` y `delete_adjunto`) | quita el módulo y los permisos de los grupos, por ids |

Dependencias: `0001` de `pos/0031`; `0003` de `security/0003` e `importacion/0004` (ya publicadas). **No depende** de `proformas/0003` ni
`comprobantes/0023`: `organizar_menu` es idempotente y cada migración crea solo su módulo, así que el orden entre ellas no importa y
deshacer la fase contable no arrastra a esta (ni al revés).

- Vuelta documentada completa: `migrate adjuntos zero` antes de las cinco de la fase contable. `tests/test_migracion_vuelta_fase.py` recorre
  vuelta (22 pendientes), ida completa en un solo plan, otra vuelta, idas parciales e ida completa, y comprueba menú, módulos y roles.
- `roles.py` cambia para todos los roles al ejecutar `sync_roles`: el Contador suma exactamente dos permisos (`add_adjunto`, `delete_adjunto`);
  `tests/test_adjuntos.py::test_modulo_del_menu_y_roles` lo fija.
- Ensayo sobre una copia del respaldo: `verif-firma/ensayo-fase/ensayo_migraciones_fase.sh <checkout> [volcado]` también aplica estas tres
  (toma el checkout entero); el conteo de pendientes tras la vuelta pasa de 19 a 22.

## Nota (02/11/2026) — recibos por completar y notas de respaldo

| Migración | Qué hace | Vuelta |
|---|---|---|
| `adjuntos/0004_capturas_y_notas` | tabla `adjuntos_captura` (clave única por empresa, índices por empresa y estado y por `sha256`); en `adjuntos_adjunto`: `archivo`, `nombre`, `tipo_mime` y `sha256` admiten vacío, `tamano` 0 por defecto, `descripcion` de 300 a 500, clase `nota` y columna `captura_id` (FK PROTECT) | borra la tabla y la columna; `descripcion` vuelve a 300 (en PostgreSQL falla si ya hay textos más largos) |
| `adjuntos/0005_rls_capturas` | RLS `fpa_empresa` en `adjuntos_captura` (como 0002) | quita la política |
| `adjuntos/0006_modulo_capturas` | permisos `view/add/change_captura`, módulo «Recibos por completar» (`/adjuntos/capturas/`, «Compras y gastos», orden 6) y `sync_roles` | quita el módulo y esos permisos de los grupos, por ids |
| `tenancy/0010_acciones_capturas` | seis acciones de auditoría `captura_*` (solo `choices`) | solo `choices` |

Dependencias: `0004` cuelga de `adjuntos 0003` y del usuario, **no** de `pos` (la empresa existe desde `0001`, sobre `pos 0031`): deshacer
`pos 0032–0034` no arrastra a las capturas. `0006` depende de lo mismo que `0003`. `tenancy 0010` de `0009`.

- **Archivo compartido:** el adjunto que nace de una captura apunta al mismo archivo físico (`archivo.name` igual). Hoy nadie borra
  archivos; cualquier limpieza futura debe comprobar `adjuntos_captura` y `adjuntos_adjunto` antes de borrar.
- **Vuelta y restauración:** la vuelta documentada (`migrate adjuntos zero` primero; la vuelta a `tenancy 0006` deshace `0010`) deja
  31 pendientes (`tests/test_migracion_vuelta_fase.py`). Con datos reales nuevos se pierden capturas y notas, y el código anterior no sabe
  mostrar un adjunto sin archivo: en producción, revertir = restaurar el volcado previo y la carpeta `privado/empresas/<uuid>/comprobantes-pago/`
  (dentro de `FPA_ARCHIVOS`, ya en el respaldo diario), no `migrate` hacia atrás.
