"""Inserción por lotes en contabilidad: la excepción escrita a la convención «nunca bulk_create»
(core/proformas/servicios.py:6), decisión común 13 de contable/bloque-2-especificacion.md.

`bulk_create` y `bulk_update` no pasan por `TenantModel.save()`: no fijan la empresa ni comprueban que cada referencia sea
de la misma (`check_tenant_references`). Por eso solo los usan los módulos de MODULOS_CON_LOTES, y siempre así:

- `company_id` fijado en cada fila, con la empresa activa;
- todas las referencias validadas antes con `objects` (que filtra por la empresa activa), en una consulta por lote;
- `batch_size=TAMANO_LOTE`.

En PostgreSQL la seguridad por filas rechaza además una fila de otra empresa, y el disparador de las líneas de asiento
una cuenta o un asiento de otra empresa. tests/test_esquema_contable.py recorre core/contabilidad y core/tributario con
ast: un `bulk_create` o `bulk_update` en un módulo que no está aquí hace fallar la prueba. Cada bloque posterior amplía la
lista nombrando su módulo (`motor.py`, `extractos.py`, `declaraciones.py`)."""

TAMANO_LOTE = 1000

MODULOS_CON_LOTES = (
    # Bloque 1 (ya en el código): la confirmación de la importación del plan de cuentas crea y renombra cuentas por lotes.
    'core.contabilidad.importar_cuentas',
    # Bloque 2: líneas del asiento; líneas, auxiliares y saldos iniciales del kardex de la apertura; su importación.
    'core.contabilidad.diario',
    'core.contabilidad.apertura',
    'core.contabilidad.auxiliares',
    'core.contabilidad.apertura_importar',
)
