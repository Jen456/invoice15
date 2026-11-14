# C6-A · Inicio contable desde saldos o desde historial

13/11/2026 · Propuesta de contrato Codex → Claude. Amplía C1–C6 de `CONTRATO-CONTABLE-V9.md`; los endpoints nuevos de este documento **no están implementados ni acordados aún**. Decisión funcional de la propietaria: unas empresas parten de estados financieros existentes y otras reconstruyen exhaustivamente sus operaciones. No obligar a la primera a registrar todos los años anteriores.

## 1. Estado comprobado y prioridad

Base revisada: `plataforma 96d39e1`. La URL de Contabilidad ofrece kardex e inventario; no existen todavía las rutas de cuentas, apertura, diario o mayor. Tributario sí tiene libros, revisión, ATS y borradores 104/103, con validación contable pendiente. La restricción se origina en `core/suscripciones/reglas.py`, `MENSAJE_COMPLEMENTO` y la lista `FPA_COMPLEMENTO_CONTABLE_REVISION`.

El aviso comercial no sustituye el desarrollo faltante. Claude debe construir el núcleo genérico y conectar las funciones existentes, sin esperar al precio para programar. La activación comercial y la aprobación de resultados fiscales son controles distintos. Codex no cambia la licencia ni habilita el módulo eliminando el mensaje.

Prioridad de ejecución: cuentas e importador C2/C3 → apertura C6-A → asientos/diario/mayor → conciliación/cierre → validación de 104/103/ATS y cierre anual/101. C1 y evidencias C5 pueden construirse en paralelo. La plantilla Supercias y los datos reales del piloto no bloquean el importador genérico ni la interfaz; sí la configuración final de cada empresa.

## 2. Dos formas de comenzar, por empresa

### A. Saldos de apertura desde una fecha

1. Elegir fecha de corte inclusiva, fuente y plan de cuentas.
2. Importar balance de comprobación CSV/XLSX o capturar saldos respaldados por estados financieros. Un PDF es respaldo para revisión, no una importación contable automática confirmada.
3. Mapear a cuentas de movimiento; revisar sumas, clasificación y cuentas pendientes.
4. Conciliar los auxiliares necesarios para operar: cartera por tercero/documento, bancos, inventario por producto/almacén, activos y obligaciones según aplique.
5. Confirmar apertura con permiso y constancia de quién revisó. Comenzar operaciones nuevas al día siguiente del corte.

Ejemplo ficticio: corte 31/12/2025; los saldos incluyen ese día y las operaciones nuevas empiezan 01/01/2026. No se copian facturas de 2025 como ventas nuevas. No usar este ejemplo como apertura del piloto real.

### B. Reconstrucción detallada

Elegir el rango histórico, importar documentos o asientos del sistema anterior en lotes con vista previa, y conciliar por período. Si el rango no empieza con la constitución/inicio efectivo de la empresa, necesita un saldo de apertura anterior al rango. “Exhaustivo” no significa asumir que el saldo inicial es cero.

Cada período muestra cobertura, fuentes, errores y estado de revisión. No reemitir XML, reservar secuencias actuales o generar cobros/stock por importar un documento histórico. Sus efectos se habilitan únicamente en la reconstrucción controlada y conforme a las reglas aprobadas.

### Completar detalles progresivamente

La ruta A puede incorporar respaldos y auxiliares históricos después. Vincularlos al saldo de apertura **no crea otro asiento, ingreso, IVA, cobro ni stock**. La ruta B no puede solaparse con un saldo ya incluido en la apertura: cambiar la estrategia requiere reconciliación y una versión aprobada, no un selector que recalcula silenciosamente todo.

## 3. Qué se puede obtener de los estados financieros

| Fuente disponible | Qué permite | Qué no debe inferirse |
|---|---|---|
| Balance de comprobación al corte | Mapear saldos de cuentas a apertura. | Que todas las cuentas tienen auxiliares conciliados. |
| Estado de situación financiera resumido | Punto de partida por rubros, con detalle adicional cuando haga falta. | El tercero, número, vencimiento o tarifa de cada documento. |
| Estado de resultados acumulado del ejercicio hasta el corte | Completar ingresos, costos y gastos del año para continuidad y reportes. | Que el resultado del ejercicio deba cargarse otra vez si ya está representado en cuentas de resultado. |
| Documentos, libros y declaraciones anteriores | Cubrir obligaciones y saldos tributarios del período según fuente/revisión. | Autorización SRI por adjuntar un PDF, ni aceptación de una declaración por generar un archivo. |

El balance de comprobación es preferible a un estado resumido. Una cuenta de grupo no recibe un asiento: se requiere desglose o mapeo explícito a una cuenta de movimiento aprobada. No inventar cuentas, capital, terceros ni una “diferencia de apertura” para forzar el cuadre.

Para comenzar a mitad de año, conciliar el estado de situación con los ingresos/costos/gastos acumulados y el resultado del ejercicio, sin contar este último dos veces. Para cerrar el año o preparar el 101, un balance patrimonial aislado no basta. Si no existe esa información, el reporte anual es parcial/provisional aunque la apertura esté cuadrada.

## 4. Saldos y auxiliares, sin doble contabilización

Ejemplo ficticio de apertura:

| Cuenta ilustrativa | Debe USD | Haber USD |
|---|---:|---:|
| Bancos | 5.000,00 | 0,00 |
| Clientes | 3.000,00 | 0,00 |
| Inventario | 2.000,00 | 0,00 |
| Proveedores | 0,00 | 2.500,00 |
| Capital | 0,00 | 6.500,00 |
| Resultados acumulados | 0,00 | 1.000,00 |
| **Total** | **10.000,00** | **10.000,00** |

Las cuentas y cifras son didácticas, no una matriz o capital sugeridos para un cliente.

- Clientes: las facturas pendientes por 2.000 y 1.000 explican el débito de 3.000. Registrarlas como auxiliar no genera 3.000 adicionales de ventas o cartera. Un cobro posterior de 500 deja cartera de 2.500 y aumenta el banco; no vuelve a reconocer ingreso/IVA de la venta histórica.
- Proveedores: conservar tercero, documento, moneda, saldo pendiente y vencimiento; el pago posterior cancela ese saldo sin duplicar la compra/gasto.
- Inventario: cantidad por producto/almacén y costo al corte deben reconciliarse con 2.000. Diez unidades de ejemplo a 200 no son una nueva compra. No duplicar el stock que ya exista en la aplicación; comparar antes de activar.
- Bancos: saldo por cuenta, extracto al corte y partidas pendientes. La carga del extracto anterior sirve para conciliar; no suma sus movimientos otra vez sobre la apertura.
- Activos: costo, depreciación acumulada y datos operativos cuando la empresa necesite depreciar posteriormente. No deducirlos de un único neto sin confirmación.
- Tributario: créditos, retenciones y obligaciones anteriores con fuente, período e importe confirmado. El saldo contable de IVA no determina por sí solo cada casillero ni cada dato del ATS.

Una apertura contable confirmada puede tener auxiliares todavía por completar, si el contador confirma su importe. Esa situación debe ser visible y limitar las acciones que requieren ese detalle; por ejemplo, no registrar un cobro aplicado a una factura inexistente. No bloquear indiscriminadamente toda la facturación.

## 5. Modelo funcional y estados propuestos

**ConfiguracionInicioContable** por empresa: `modalidad` (`saldos`/`historial`), `fecha_corte`, `operaciones_desde`, `historial_desde`, `historial_hasta`, `version`, autor y fechas. `operaciones_desde` debe ser coherente con el corte; ningún rango se supone completo por seleccionar una fecha.

**Apertura**: empresa, corte, moneda, fuente, archivo privado/huella, estado, versión, totales, revisado por/en, confirmado por/en y asiento vinculado. Estados: `borrador`, `en_revision`, `confirmada`, `sustituida` o `reversada`. Una sola base inicial efectiva para el mismo libro/rango; no crear una segunda apertura activa que acumule la primera.

**LineaApertura**: cuenta de movimiento, debe/haber, referencia de origen y mapeo. Importes decimales; desconocido = `null`, no cero. Validar signo, duplicados/mapeo, cuentas de empresa, cuentas activas, totales y diferencia. Agrupar filas del mismo destino solo mediante una decisión explícita visible en la vista previa.

**AuxiliarApertura**: cuenta/tercero/documento o producto/almacén/costo o banco según naturaleza, saldo al corte, saldo aplicado y vínculo a la apertura. Debe reconciliarse con su cuenta sin emitir un segundo efecto contable. La aplicación posterior usa las reglas e idempotencia de cobros/pagos existentes.

**Cobertura** por empresa, ámbito y período: contabilidad, documentos tributarios, cartera, inventario y bancos. Indicar fuente y cobertura; `pendiente`, `parcial` o `conciliada`. No confundir estos estados con autorización fiscal o licencia.

Correcciones: borrador editable con `version`; confirmado inmutable por edición ordinaria. Un ajuste o sustitución conserva historial y vínculo; si hay movimientos posteriores, comprobar su impacto antes de reabrir/reconstruir. Nunca borrar el asiento inicial y dejar sus cobros, pagos o movimientos huérfanos.

## 6. Contrato API propuesto para acordar con Claude

Mantener empresa activa, RLS, permisos, CSRF, importes como texto decimal, `clave` de idempotencia y `version` del contrato v9. Ningún endpoint de esta tabla se considera disponible hoy.

| Acción | Propuesta | Resultado esperado |
|---|---|---|
| Consultar configuración/cobertura | `GET /contabilidad/api/apertura/?empresa=` | Modalidad, fechas, apertura actual, causas pendientes y capacidades. |
| Guardar borrador de apertura | `POST /contabilidad/api/apertura/` | ID, versión y estado; sin asiento ni efecto en saldo. |
| Importar fuente | `POST /contabilidad/api/apertura/<id>/importar/` | Lote y vista previa, columnas, filas válidas/errores/duplicadas; archivo privado. |
| Guardar mapeo/líneas | `POST /contabilidad/api/apertura/<id>/mapear/` | Diferencia calculada en servidor y pendientes; no confirmar. |
| Conciliar auxiliares | `POST /contabilidad/api/apertura/<id>/auxiliares/` | Resultado por cuenta y detalle faltante, sin otro asiento. |
| Validar | `POST /contabilidad/api/apertura/<id>/validar/` | Bloqueos, advertencias y cobertura por reporte; no aprobación automática. |
| Confirmar apertura | `POST /contabilidad/api/apertura/<id>/confirmar/` | Una confirmación y un asiento inicial; repetir la clave devuelve el mismo resultado. |
| Previsualizar histórico | Reutilizar importaciones existentes con contrato ampliado | Destino `consulta`/`auxiliar_apertura`/`reconstruccion`, solapamientos y efectos previstos antes de confirmar. |

Ejemplo ficticio de consulta:

```json
{
  "empresa": {"id": 101, "nombre": "Comercio de demostración"},
  "modalidad": "saldos",
  "fecha_corte": "2025-12-31",
  "operaciones_desde": "2026-01-01",
  "apertura": {
    "id": 7, "version": 2, "estado": "en_revision",
    "debe": "10000.00", "haber": "10000.00", "diferencia": "0.00"
  },
  "cobertura": {
    "contabilidad": {"estado": "pendiente", "causas": ["Apertura por confirmar"]},
    "cartera": {"estado": "parcial", "causas": ["Faltan vencimientos de dos documentos"]},
    "tributario": {"estado": "pendiente", "saldos_anteriores": null}
  },
  "capacidades": {"editar": true, "validar": true, "confirmar": false}
}
```

Errores estables propuestos: `apertura_desbalanceada`, `cuenta_sin_mapear`, `cuenta_de_grupo`, `auxiliar_no_concilia`, `rango_solapado`, `periodo_cerrado`, además de `empresa_cambiada`, `version` y `sin_permiso`. Campo/fila y explicación legible; la interfaz conserva lo escrito.

Permisos propuestos: Propietario/Administrador/Contador con capacidad específica para preparar/validar; confirmar exige permiso específico y registro de la revisión. Consulta lee lo autorizado; Vendedor no administra aperturas. Los permisos definitivos se implementan en servidor, no con botones ocultos.

## 7. Documentos anteriores y cobertura tributaria

- Importar un documento con fecha hasta el corte inclusive ofrece primero consulta o completar auxiliar. No genera ventas, compras, stock o asiento automáticamente.
- Si ya existe por clave de acceso, vincular. Si la apertura solo tiene tercero y número, mostrar candidatos y exigir coincidencia revisada; no inventar una clave ni unir documentos ambiguos.
- Reconstruir un período que ya está incluido en la apertura requiere plan explícito de sustitución/reconciliación; bloquear el solapamiento por defecto.
- Un archivo importado después del corte puede corresponder a un hecho anterior. No basta la fecha de subida para decidir efectos.
- 104/103/ATS requieren información tributaria del período y reglas vigentes. El estado financiero por sí solo no aporta todos sus documentos, tarifas, retenciones y casilleros.
- Para 101/estados anuales: incluir resultados acumulados al corte, movimientos posteriores y conciliación tributaria. Mostrar por reporte alcance y causa de provisionalidad; una cobertura parcial no se muestra como año completo.
- Se puede emitir un estado de situación a una fecha posterior con apertura validada y movimientos conciliados sin reconstruir todos los años anteriores. No exigir historial innecesario para ese reporte. Comparativos de años sin información deben decir «sin cobertura», no cero.

## 8. Pruebas de aceptación

1. Saldos: corte 31/12 y operaciones desde 01/01; exactamente un asiento inicial de 10.000/10.000, incluso con doble clic/concurrencia.
2. Importe faltante se mantiene pendiente. Diferencia no cero o cuenta de grupo bloquea confirmar; no cuenta automática para cuadrar.
3. Cobro de 500 sobre auxiliar inicial de clientes de 3.000 deja 2.500, banco +500 y ningún nuevo ingreso/IVA por la venta histórica.
4. Importar XML de esa factura inicial completa/vincula el auxiliar sin aumentar cartera, ventas, impuestos, asientos ni stock.
5. Inventario inicial se distribuye por almacén, cantidad/costo concilian y repetir no duplica existencias.
6. Historial desde un período intermedio exige saldo anterior confirmado; sin él los reportes lo indican. Reconstrucción solapada queda bloqueada.
7. Corte a mitad de año: resultados acumulados más movimientos posteriores cuadran con el ejercicio; no duplicar resultado en patrimonio y cuentas nominales. 101 incompleto se identifica como provisional.
8. Dos empresas: cuentas, documentos, archivos y saldos aislados; 409 en pestaña vieja, permisos por acción y control de versiones.
9. Reapertura/ajuste con movimientos posteriores mantiene trazabilidad, aplicaciones y períodos; no elimina efectos sin reverso.
10. Confirmar apertura no envía nada al SRI ni crea una factura nueva. La emisión básica sigue funcionando aunque Contabilidad no esté contratada.

## 9. Propiedad y salida

Codex: diseño y adaptación responsive de este asistente, componentes de mapeo, estados de cobertura y reportes. Propuesta visual en `propuestas/apertura-contable/`; no está conectada a una API ni entra al menú productivo.

Claude: modelos/migraciones, servicios, permisos, contratos definitivos, importadores, idempotencia, asientos y despliegue compatible. Completar el núcleo genérico; no postergar cuentas/apertura por falta de precio o de una plantilla oficial. Los saldos reales, la matriz y la aprobación tributaria son datos de configuración/validación necesarios para cerrar cada empresa, no motivos para dejar sin construir el motor.

Revisar con la propietaria el diseño antes de conectarlo a la aplicación, como se pidió. Al entregar backend, documentar endpoints reales y ejemplos; Codex integra sin cambiar campos ni reglas fiscales. Se conserva la aprobación correspondiente a publicación y las pruebas de continuidad: este contrato no autoriza por sí solo una migración en producción.
