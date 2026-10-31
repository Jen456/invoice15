# Decisión de producto e integración — FacturaPorAquí

31/10/2026, Ecuador. Recomendación de Codex a petición de la propietaria. Esta entrega documenta decisiones y trabajo acotado; no cambia reglas, código operativo, precios ni autoriza publicar.

## Decisión

**Elegir A: conservar `core/cobros` para ventas y cobros; integrar `core/adjuntos` para compras, gastos y pagos a proveedores.** Una consulta mensual común, sin crear otro modelo de respaldo ni duplicar registros.

El riesgo principal de A está en la integración de permisos, formularios y exportación: se controla probando el resultado conjunto. B entrega antes pero deja fuera respaldos de compras ya construidos; C pierde revisión, nota e idempotencia; D rehace almacenamiento y reglas sin una necesidad inmediata. Dos modelos privados con responsabilidades claras son aceptables en esta fase.

| Pantalla | Responsable del dato | Comportamiento |
| --- | --- | --- |
| Factura de contado y sus respaldos | `core/cobros` | Archivo o nota según el medio; sin crear CxC; revisión e historial |
| Cobro de una factura a crédito / CxC | `core/cobros` | Un abono por operación idempotente; el respaldo acompaña al abono |
| Compras, gastos y pagos a proveedores / CxP | `core/adjuntos` | Archivos genéricos privados, metadatos y baja lógica |
| Consulta mensual y ZIP/CSV | Consulta de ambos orígenes en backend | Fuente e identificador propios, archivo o nota y revisión cuando corresponda; permisos por documento |

La consulta no guarda otra copia del respaldo ni crea abonos. Una nota válida en cobros no aparece como falta de respaldo por no tener archivo. Separar «sin archivo», «sin respaldo» y «pendiente de revisión». El ZIP solo contiene archivos autorizados; el índice distingue notas y estados, sin credenciales o rutas del disco. Importes de un respaldo y de su abono no se suman dos veces como ingresos. La revisión no concilia con el banco ni cambia el saldo.

## Base comprobada y correcciones al resumen recibido

Fetch de esta entrega: `plataforma=4a39a1a`, `frontend/etapa3=ebac423`, `fase/adjuntos-comprobantes=722475a`. Plataforma ya es ancestro de frontend. El diseño de adjuntos está subido (`2b37d09`, trazabilidad `ebac423`), probado con el backend aislado y pendiente de integración.

- **X-R1 ya está corregido**, según HANDOFF del 30/10 (`e6edc6d`, `1e87949`, `7ec9c67`). No pedir su implementación otra vez.
- `core/adjuntos/archivos.py` en `722475a` sí comprueba imágenes con Pillow (`Image.open`, `verify`, límite de píxeles). La ausencia de esa validación en el resumen no coincide con el código. Su baja lógica sí registra quién/cuándo/motivo; no equivale al historial completo y revisión de cobros.
- El ensayo antiguo de 19 migraciones no cubre por sí solo puntos, cobros y la futura integración de adjuntos. El candidato final necesita su plan real de migraciones y ensayo propio.
- En `core/comprobantes/views.py`, la acción `delete` de `ComprobanteListView` todavía decide con el estado leído antes de bloquear la fila. HANDOFF ya identifica la carrera con autorización. Priorizar su cierre acotado antes de publicar; no repetir una auditoría general.
- El estado de producción `98cfa20` procede del informe de Claude; esta sesión no consultó el servidor ni sus datos. No confundir GitHub con disponibilidad en la aplicación.

## Cómo competir y orden de entregas

Segmento inicial recomendado: pequeños negocios de servicios y comercio, uno o varios locales del mismo RUC, y su contador. El Plan Multiempresa sigue destinado a varios RUC separados. La propuesta comercial debe demostrar facilidad móvil, control de cobros y documentación para el contador.

No se verificó en esta sesión el catálogo/precio actual de Facturero Móvil o Contífico: sus sitios no están habilitados en la política de red del entorno. No se afirma superioridad funcional ni ahorro frente a ellos. La siguiente es una estrategia de producto basada en el código propio.

| Entrega | Claude: backend | Codex: diseño/comercial | Se considera terminada cuando… |
| --- | --- | --- | --- |
| **1. Operación comercial completa** | Integración A, consulta/ZIP común, contratos y cierre de riesgos conocidos que afecten el candidato; corregir `birthdate` sin inventar datos | Sección de pago de factura, ficha de respaldos y CxC; locales/selector/«Emites desde»; botones por permiso; adaptar el diseño de adjuntos ya entregado | El recorrido proforma → factura → cobro/respaldo se prueba de principio a fin con empresas ficticias; dos locales y dos pestañas conservan su punto; no duplicados ni mezcla de RUC |
| **2. Cierre mensual para el contador** | Fuentes y faltantes por período; mapa explícito/versionado de casilleros; auxiliares 104/103 y ATS con esquema oficial y revisión contable | Pantalla «Preparar período», pendientes y detalle de documentos por cifra; exportaciones y guía | Un período ficticio cuadra con cálculo independiente; faltantes visibles, ajustes/saldos respaldados y cada total trazable |
| **3. Contabilidad y cierre anual** | Caja/bancos y conciliación; libro de partida doble, apertura, asientos idempotentes, costos/kardex, ajustes y cierre; estados y apoyo al 101 | Bancos/conciliación y pantallas contables sobre contratos reales, reutilizando maquetas | Debe = haber, saldos y conciliación reproducibles; costo histórico y estados sustentan el 101 |

Esta es la prioridad funcional recomendada; no inicia automáticamente etapas futuras ni borra el plan histórico. 104/103/ATS pueden partir de auxiliares fiscales completos sin esperar todos los conectores bancarios. **El 101 exige contabilidad y cierre; no se obtiene restando compras a ventas.** La información ajena a los XML necesita fuentes complementarias y revisión. Ver [análisis de dependencias](ANALISIS-ERPNEXT-COMERCIAL-CONTABLE.md).

IA sigue pendiente. Nómina completa, fabricación, CRM extenso, todas las conexiones bancarias y un nuevo motor de adjuntos quedan fuera de esta entrega. Precios vigentes y cobro anual se conservan; complemento Contable: «Precio por anunciar», sin activación de cobro ni promesa de disponibilidad.

## Agrupación de publicación

**Una versión candidata para la entrega 1**, construida sobre la línea actual de plataforma y la integración A, incluyendo el diseño pendiente. No extraer Proformas/Compras/Ventas con cherry-picks ni deshacer migraciones para crear lanzamientos artificiales. Las entregas 2 y 3 tendrán versiones posteriores, no se añaden al candidato 1.

Antes de solicitar la publicación, Claude entrega:

1. SHA final y plan de migraciones completo; pruebas SQLite/PostgreSQL del código final. No sumar resultados de ramas aisladas como si fueran la integración.
2. Corrección y prueba del borrado concurrente ya identificado. Para los reenvíos documentados (liquidación sobre 04, sustento anulado, posible duplicado de NC/guía), confirmar los casos con pruebas y corregir los reproducibles que permitan una inconsistencia. No cambiar porcentajes/catálogos como parte de esta corrección. X-R1 no se reabre.
3. Revisión explícita de pendientes fiscales que afecten rutas habilitadas: producción/pruebas, IVA e ICE, vigencias y plazos. Resolver con fuente oficial/contador o dejar el caso afectado expresamente bloqueado; no reemplazar datos desconocidos por cero ni aplicar correcciones históricas.
4. Ensayo del candidato y su migración sobre una copia reciente del respaldo, en su entorno autorizado. Verificar restauración, también de archivos privados, y documentar el alcance de recuperación. No tratar `--revertir` o una reversa de Django como recuperación suficiente cuando ya hay datos nuevos; restaurar un respaldo puede perder operaciones posteriores y exige un plan para preservarlas/reconciliarlas.
5. Prueba local de navegador con datos ficticios: proforma a factura con SRI simulado; contado/efectivo y no efectivo; crédito/abonos; doble envío/respuesta perdida; permisos; dos locales; consulta/ZIP sin duplicados. Codex comprueba 360/390/768/1024/1360/1440 px y teclado.

Codex no despliega. Claude solicita aprobación de la propietaria sobre el candidato concreto antes de usar producción; las reglas de respaldo/ventana de mantenimiento del proyecto siguen vigentes. Si hay una guardia de migración o una prueba fallida, la versión no se presenta como lista.

## Decisiones menores recomendadas

Son recomendaciones de producto para adoptar/documentar, no cambios aplicados en esta entrega.

| Decisión | Recomendación | Quién valida |
| --- | --- | --- |
| Nota también en efectivo | Opcional. En no efectivo, archivo **o** nota; conservar el contrato actual | Propietaria |
| Revisión de cobros | Propietario y Administrador. Mantener lectura para Contador/Consulta | Propietaria |
| Respaldo rechazado | Motivo y corrección pendiente; sin anular factura, borrar abono ni cambiar saldo automáticamente | Propietaria; conservar separación contable actual |
| Contador en adjuntos genéricos | Puede subir y retirar lógicamente, con trazabilidad; no gana revisión de cobros ni otras escrituras | Propietaria |
| Vendedor | Mantener permisos del contrato de cobros, corrección propia según estado; no revisión ni eliminación libre | Propietaria |
| Formatos y límites | Conservar por ahora 8 MB/10/PDF-JPG-PNG-WEBP en genéricos y 5 MB/PDF-JPG-PNG en cobros; interfaz muestra el límite aplicable | Propietaria |
| Usuario sin restricciones de punto | En la primera entrega conservar compatibilidad y mostrar explícitamente «Todos los puntos». Confirmar al quitar la última restricción, que hoy devuelve acceso a todos. Un modo explícito todos/asignados/ninguno será tarea separada si se adopta | Propietaria; no necesita contador |
| Editar nombre/dirección del local | Mantener alta/activar/desactivar en esta entrega. Posponer edición hasta conservar los datos históricos por comprobante; códigos/numeraciones nunca se reinterpretan | Propietaria; dirección/código fiscal verificados por responsable de la empresa |
| Nacimiento del cliente | No obligatorio para empresas ni precargado con hoy; hacer opcional si no tiene finalidad operativa. Backend permite vacío; no limpiar históricos automáticamente ni inferir tipo de persona solo por tener RUC | Propietaria; no requiere criterio tributario para dejar de inventar una fecha |
| Correos fallidos de proformas | Los intentos cuentan para el límite técnico antiabuso; mostrar fallo y distinguirlo de «enviada» | Propietaria |
| IVA/ICE, códigos, fechas y obligaciones | Fuente oficial vigente y validación del contador. Retenciones efectuadas y recibidas se tratan por separado; un RUC no se mezcla con otro | Contador + Claude; aceptación de la propietaria |
| Precio del complemento | Continúa pendiente; definir cobertura/costo/soporte antes de fijar tarifa. No bloquea el diseño de cobros/locales | Propietaria |

## Encargo acotado para Claude

> Trabaja en plataforma sobre su HEAD actual, conservando ambas documentaciones. Cierra solamente la entrega 1 de esta decisión. Integra A: cobros para ventas/CxC y adjuntos para compras/gastos/CxP, sin dos campos o accesos al mismo respaldo. Consulta mensual y ZIP con ambos orígenes, permisos, notas y revisión, sin duplicar datos. Reutiliza el diseño de Codex de frontend/etapa3 (base ebac423) y entrega el contrato consolidado en HANDOFF antes de que Codex adapte la consulta.
>
> Conserva condición/medio, nota o archivo, idempotencia, auditoría, saldos, puntos y datos históricos. Corrige el nacimiento ficticio del cliente con contrato que permita vacío. Cierra el borrado concurrente identificado y los reenvíos inconsistentes reproducibles; no rehagas X-R1. No alteres tasas o reglas fiscales pendientes sin validarlas.
>
> Entrega pruebas del candidato integrado, plan/ensayo de migraciones, hash subido y bloqueos concretos. No inicies bancos, IA o nuevos módulos. No despliegues ni operes sobre documentos reales. Reporta solo bloqueos y un resumen final corto; conserva el detalle en los archivos del proyecto.

## Trabajo inmediato de Codex

1. Diseñar el bloque `sale/admin/_cobro.html`, ficha/modal de `/cobros/factura/<id>/` y formulario CxC usando el contrato ya publicado. Una nota/archivo nunca se presenta como confirmación bancaria. Conservar claves de idempotencia y mensajes de error.
2. Diseñar `configuracion/puntos.html`, `_selector_punto.html`, `_punto_emision.html` y filtros existentes de factura/NC. Mostrar local/punto del formulario, datos pendientes y regla «Todos los puntos»; sin reservar numeraciones en la vista previa.
3. Ajustar botones por permisos existentes en proveedores/gastos/CxP. Adaptar la consulta común de adjuntos cuando llegue su contrato consolidado. No inventar endpoints.
4. Probar con datos ficticios, teclado y movimiento reducido; documentar capturas, archivos, pruebas y commits. Sin cambios de backend.
5. Tras publicación confirmada, actualizar landing y manuales con lo realmente disponible: demostración móvil, alta inicial, factura/cobro y entrega al contador. No prometer declaración automática, certificación del SRI, estados financieros o precio contable inexistentes.

Criterios de producto para un piloto autorizado: registrar tiempo de alta y de factura recurrente, dificultades al cambiar de local, operaciones abandonadas, diferencias de saldo y tiempo para reunir documentos del mes. Cero duplicados de abonos y cero cruces entre RUC son condiciones de aceptación, no métricas comerciales opcionales. No fijar cifras de mejora sin medir una línea base.

No hace falta otra decisión para avanzar con los diseños existentes. Antes de cerrar la parte fiscal hace falta un contador responsable y casos de referencia; antes de vender el complemento, su precio/alcance; antes de desplegar, aprobación sobre el candidato probado. No se solicitan credenciales ni datos reales para Codex.
