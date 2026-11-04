# Datos necesarios para conectar las pantallas contables

Propuesta para Claude, **no contrato API acordado**. Fecha de la entrega: 3 de noviembre de 2026 (Ecuador). Repositorio de esta entrega: `Jen456/facturacion15`, base PR #1 `817c5be`.

## Lo que sí está conectado al contrato del PR #1

La factura mantiene nombres de campos, `action`, JSON de productos, endpoints, CSRF y `multipart/form-data`. El precio por línea y el alta rápida usan los servicios existentes. La presentación «Contado» conserva el valor histórico `efectivo`; Crédito conserva `credito`.

`payment_note` sigue siendo opcional, máximo 300 caracteres. `payment_attachment` sigue siendo opcional, PDF/JPG/PNG hasta 10 MB. La validación del navegador es ayuda; la seguridad y la validación del contenido siguen en el servidor.

La nota del PR se guarda en `additional_info`, como `Condiciones de pago`. La pantalla lo advierte. No se trasladó el contrato de `core/cobros` del otro repositorio ni se prometen notas internas. Claude debe resolver ese destino según el Word v9 antes de publicar.

## Contratos todavía ausentes en este repositorio

| Pantalla | Datos que debe devolver el servidor | Acciones y validaciones necesarias |
|---|---|---|
| Inicio contable | Empresa activa; capacidades; estado real de importación, apertura y conciliación; pendientes con origen | No inferir que se completó una etapa por abrir su pantalla; valores desconocidos como `null`, no cero |
| Plan de cuentas | Identificador, código, nombre, cuenta padre, tipo grupo/movimiento, estado y permisos | Crear/configurar; impedir movimientos en grupos; validar jerarquía sin ciclos y unicidad por empresa |
| Importación del plan | Lote y archivo; columnas reconocidas; mapeo; filas válidas y errores por fila; resultado confirmado y fecha | Vista previa antes de confirmar, permiso, empresa, reintentos idempotentes y resolución de duplicados. XLSX/CSV y límites por confirmar |
| Asientos por comprobante | Origen con URL autorizada; asiento y versión; fecha; estado; cuentas; débitos/créditos decimales; totales; excepciones y capacidades | Consulta; proponer/resolver cuentas conforme a matriz validada; confirmación con control de concurrencia. Balanceado no significa contabilizado |
| Revisión/cierre del mes | Empresa, período, controles y causas, documentos de origen, saldos anteriores conocidos/desconocidos, conciliación IVA/ATS, revisión y responsables | Guardar revisión; cierre/reapertura si están aprobados; exportar; adjuntar evidencia privada vinculada al período. Archivo subido no prueba presentación |
| Reportes | Empresa, período, filtros, filas y totales, nivel resumen/detalle, estado provisional y causas | Exportar con el mismo alcance y etiqueta provisional. No mostrar estados financieros sin mayor y apertura validados |
| Puntos de emisión | Empresa/RUC, establecimiento y punto separados, alias, activo/inactivo, verificación y evidencia; cantidad usada; máximo 3; capacidades | Validar cupo en servidor; no alterar numeración desde la interfaz; mostrar verificación solo con evidencia autorizada |
| Piloto NEXALLTI | Identificador autorizado de empresa; alcance reducido del plan de cuentas; estado de importación y apertura | No se usaron datos reales ni se creó/modificó la empresa. La noticia de creación en localhost es un reporte de la propietaria, no verificación de la API |

## Reglas para todas las respuestas

- Aislamiento por empresa y permisos validados por servidor. El selector visual no concede acceso.
- Importes decimales como texto; estado desconocido explícito. No calcular casilleros tributarios en JavaScript.
- Errores por campo/fila y mensaje general. 403 para permisos insuficientes; el código que se acuerde para empresa cambiada debe conservar los datos hasta que el usuario decida recargar.
- En 409 la interfaz ofrece recargar con aviso de pérdida de datos sin guardar. No reenvía información a otra empresa.
- Carga y errores recuperables sin afirmar éxito antes de respuesta confirmada. No reintentar automáticamente emisiones.
- El límite de tres puntos es interno: no se presenta como restricción general del SRI ni como número de sucursales.

## Integración pendiente de diseño

La propuesta está en `propuestas/ux-v9/index.html`. No hace solicitudes API. Sus ejemplos, descargas CSV y estados están rotulados como simulados; los botones de importación definitiva, contabilización y respaldo real están deshabilitados.

Cuando Claude publique las rutas y el contrato real, Codex conectará las pantallas conservando la presentación y retirando el selector de estados de demostración. No se aprobará una función como terminada solo porque exista su maqueta.
