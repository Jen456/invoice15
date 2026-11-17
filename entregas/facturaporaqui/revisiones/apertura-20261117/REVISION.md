# Revisión dirigida: apertura contable, corte 1

17/11/2026 · Codex. Rama revisada `fase/contable-2-apertura`, GitHub `2e247a2f6eb35a48fa1798ad744d789a9506bfc2`; último código `7a5c567`. Comprobado que los cambios posteriores son documentación. Trabajo en una copia aislada, sin modificar la rama de Claude ni producción. No incluye trabajo que Claude aún no haya subido.

**Resultado:** tres problemas reproducidos en cuatro casos; 37 pruebas existentes seleccionadas pasan. No se repite la suite completa ni las auditorías de migraciones ya informadas por Claude. Todos los ejemplos son ficticios.

## A1 · P2: resultado neto cero se confunde con ausencia de resultados

[apertura.py:1383](https://github.com/Jen456/invoice15/blob/7a5c567/core/contabilidad/apertura.py#L1383), especialmente la decisión en líneas 1417–1425.

Caso: corte 30/06/2026; caja 6.000 al debe, capital 6.000 al haber, ingresos 1.000 al haber y gastos 1.000 al debe. Se declara `resultado_ejercicio=en_cuentas_nominales` y `resultado_acumulado=0.00`. El balance cuadra; hay cuentas de resultados y su resultado neto es cero. Enviar a revisión devuelve **409 `resultado_duplicado`**.

Causa: `if n` comprueba si la suma neta es distinta de cero, no si existen líneas nominales. La rama `N=P=0` supone que no se aportó el resultado. Obliga a declarar algo distinto de lo que trae el balance o impide continuar.

**Corrección acotada:** distinguir presencia de cuentas de ingresos/costos/gastos de su resultado neto. Admitir el detalle nominal cuyo neto es cero y conservar las defensas contra duplicarlo en patrimonio. Añadir el caso al control de mitad de año y a la provisionalidad; no interpretar cero beneficio como ausencia de actividad.

## A2 · P2: una apertura valida indebidamente la cobertura del diario anterior

[reportes.py:68](https://github.com/Jen456/invoice15/blob/7a5c567/core/contabilidad/reportes.py#L68) y causas en el mismo archivo, usadas por `vistas_diario.DiarioApi`.

Caso: confirmar apertura por saldos al 31/12/2025 y consultar `GET /contabilidad/api/diario/?empresa=<id>&desde=2024-01-01&hasta=2024-12-31`. No se cargó el historial de 2024. La API responde **asientos vacíos, totales 0, `provisional=false`, sin causas**.

Causa: con apertura confirmada ya no aplican las causas de falta de apertura; `motor_pendiente` solo se activa si el rango pasa del corte. Falta distinguir un saldo confirmado al corte de disponer del detalle de los movimientos anteriores. Confirmar un saldo no prueba que 2024 no tuvo actividad.

**Corrección acotada:** indicar cobertura histórica faltante/parcial para el diario cuando el rango no esté respaldado por movimientos históricos revisados. Conservar la validez del saldo al corte para los reportes que realmente parten de ese saldo. Reutilizar la cobertura y las causas existentes; no exigir reconstruir años anteriores a quien eligió apertura por saldos. Revisar también la aserción de `tests/test_diario.py:672`, que actualmente da por suficiente la apertura para el rango anterior.

## A3 · P2: un importe fuera de rango termina en 500

[apertura.py:249](https://github.com/Jen456/invoice15/blob/7a5c567/core/contabilidad/apertura.py#L249), `leer_importe`, compartido por captura e importación.

Caso: importe ficticio `999999999999999999999999999999.99`. Tanto `POST …/apertura/<id>/mapear/` como la subida CSV en `POST …/apertura/<id>/importar/` devuelven **500**. La captura debería devolver el error de campo y el CSV identificar la fila inválida en la vista previa.

Causa: `Decimal.quantize(CENTAVO)` se ejecuta antes del límite de magnitud y lanza `decimal.InvalidOperation`; los llamadores solo convierten `ValueError` en validación. No es el mismo caso que el límite del total del asiento ya corregido por Claude.

**Corrección acotada:** comprobar magnitud/precisión antes de cuantizar y convertir errores decimales en el error de importe existente. Mantener la validación exacta de decimales y límites; no truncar silenciosamente.

## Evidencia, alcance y entrega funcional

- SQLite temporal sobre `2e247a2` (código `7a5c567`): **37 aprobadas + 4 fallos esperados de los reproductores; cero errores de preparación**, 37,21 s.
- Existentes seleccionadas: `test_apertura.py::TestAceptacion1`, `TestAceptacion2`, `TestConfirmar`, `TestAceptacion8` y `test_apertura_textos.py`. Cubren confirmación/reintento, saldos inválidos, aislamiento por empresa, permisos, plan y controles de texto.
- Los reproductores expresan el comportamiento esperado después de corregir; están en [reproductores.py](reproductores.py). [RESULTADOS.txt](RESULTADOS.txt) contiene el extracto de fallos y el resumen, sin el ruido de instalación.
- No ejecutados por Codex: suite completa, PostgreSQL/RLS/concurrencia, ensayo de despliegue y navegador de la app. No se atribuyen a Codex los resultados informados por Claude.
- Este corte ofrece API de cuentas, apertura y lectura del diario. **No incluye páginas nuevas conectadas.** Mayor/balance de comprobación y operaciones de auxiliares/históricos pendientes no se presentan como funcionales. Las Partes C–F siguen explícitamente pendientes del corte 2.
- Los límites de propietario de la base, reintento de despliegue, I3/I5 y el cambio de auxiliar después de confirmar ya están documentados por Claude: no se reabren aquí como hallazgos nuevos.

### Orden breve para Claude

Corrige A1–A3 en tu misma línea de trabajo, conservando lo nuevo del corte 2. Usa estos cuatro reproductores y las regresiones afectadas; ejecuta las verificaciones obligatorias de cierre cuando corresponda, sin repetir suites por documentos. Actualiza solo el contrato que cambie y entrega hash. Continúa con el corte 2; esta revisión no añade otro bloque de trabajo ni modifica permisos comerciales.

Para reproducir en una copia de la rama revisada (las dependencias habituales de las pruebas deben estar instaladas):

```bash
cp entregas/facturaporaqui/revisiones/apertura-20261117/reproductores.py tests/test_revision_codex_apertura.py
FPA_ENV_FILE=/dev/null python -m pytest tests/test_revision_codex_apertura.py --tb=short -r f
```

`config.settings_test` fuerza SQLite temporal por defecto y correo en memoria; no usar credenciales ni archivos de producción. Esta documentación se entrega en `frontend/etapa3`; copiar los reproductores a la copia de trabajo revisada sin fusionar código de ramas ajenas.
