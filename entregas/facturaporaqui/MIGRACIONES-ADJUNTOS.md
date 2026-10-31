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
