# Gastos y respaldos: revisión en nube y siguiente tarea

Fecha: 31/10/2026 (Ecuador). Base integrada: `plataforma 5041f56` y `frontend/etapa3 dbf7374`, fusión `537c010`. Datos exclusivamente ficticios. Sin despliegue.

## Decisión de experiencia de uso

El cliente debe poder conservar una foto del recibo o una nota cuando ocurre el gasto, y completar los datos después. Esa primera captura **no debe registrar un gasto contable, una cuenta por pagar ni un crédito tributario**. Quien tenga todos los datos puede seguir registrando el gasto directamente.

No conviene crear otro sistema de archivos: conservar el respaldo en su origen y consultarlo desde la misma bandeja mensual. Importar un XML/RIDE es distinto de adjuntar el respaldo de un pago.

## Lo comprobado en la aplicación integrada

| Recorrido | Resultado y acción |
| --- | --- |
| Importación XML/RIDE | Sirve para incorporar documentos tributarios. No sustituirla por el adjunto de un recibo ni mezclar sus estados con la revisión del pago. Se revisó su separación de responsabilidades; no se hizo una nueva prueba integral de importación en navegador. |
| Factura al contado y cobro de CxC | `core/cobros` conserva archivo, nota y revisión. La consulta mensual todavía apuntaba a la API de adjuntos, que rechaza estos tipos. Corregido el acceso con una consulta visual de la API de cobros. |
| Compra, gasto y pago a proveedor | `core/adjuntos` conserva el archivo una sola vez. La consulta mensual reutiliza esos archivos. Un segundo envío del mismo archivo al mismo documento devuelve 409. |
| Consulta mensual | Repetía las filas pendientes en dos tablas. Ahora hay una sola lista con filtros, origen, notas y estados de revisión. La nota sin archivo ya no es un enlace vacío; el ZIP queda disponible aunque solo haya notas. |
| Registrar gasto | Se guardó desde el navegador un gasto con nota sin archivo y otro con recibo. El recibo se conserva con el mismo envío del formulario. Se agruparon los cuatro datos esenciales; referencia y clase quedan en una sección desplegable. |
| Nota descriptiva de gasto | Se guarda en `Expenses.description`, pero `resumen_mes()` solo considera los `Adjunto` de ese gasto para decidir si tiene respaldo. No equivale a la nota de `core/cobros`. Esta diferencia sigue visible y necesita contrato de backend. |
| Guardar solamente una foto o una nota | No existe una captura pendiente: el formulario exige categoría, fecha, importe y medio de pago. No se inventaron esos valores ni se creó un botón de guardado ficticio. |

La consulta de cobros agregada en esta entrega es de **lectura**. No sustituye la ficha completa pendiente para registrar, editar, revisar y consultar el historial de cobros.

## Orden concreta para Claude

> Trabaja solo en **captura rápida de gastos y respaldo por nota**, sobre la versión integrada de `plataforma`. Lee este documento y el contrato consolidado de respaldos en HANDOFF. Reutiliza `core/adjuntos` para egresos y conserva `core/cobros` para ingresos. No fusiones la rama superada `fase/adjuntos-comprobantes`.
>
> 1. Implementa una captura pendiente que acepte **una foto/PDF o una nota, o ambos**, sin exigir aún importe, categoría ni medio de pago. Usa los formatos y límites de adjuntos existentes. Empresa, autor y fecha de registro salen del servidor. El archivo permanece privado. Respeta los permisos y reglas de plan existentes; no amplíes roles por defecto.
> 2. Permite listar estas capturas, completar sus datos y vincularlas a un gasto existente o registrar el gasto con las validaciones actuales. Si el respaldo es una factura de proveedor, permite completar el flujo de Compras conservando el archivo original. **No exijas subirlo otra vez.** La captura pendiente no afecta saldos, IVA, ATS ni asientos.
> 3. Evita duplicados por doble clic/reintento y por dos usuarios que completen la misma captura simultáneamente. Usa una clave de idempotencia y transacción con bloqueo al completar. Si un archivo ya se adjuntó al mismo documento, devuelve su referencia o un aviso claro. No prohíbas globalmente un archivo solo por coincidir con otra operación legítima.
> 4. Define el respaldo por nota en gastos: texto, autor y fecha; muéstralo en la consulta mensual y en el índice CSV aunque no haya archivo. No conviertas automáticamente todas las descripciones históricas en respaldos verificados. Una nota registrada no implica conciliación bancaria, aprobación ni deducibilidad. Conserva historial y permisos.
> 5. Entrega el contrato de pantallas/API con campos, estados, errores, capacidades y ejemplos ficticios; las migraciones y sus precauciones; pruebas de permisos, aislamiento por empresa, nota sola, archivo solo, ambos, reintentos, doble conversión, reutilización del archivo y ausencia de efectos contables antes de completar. Ejecuta SQLite y PostgreSQL sobre el resultado e identifica el commit probado. Sube a GitHub y actualiza HANDOFF; **no publiques**.
>
> Limita esta entrega a esos cinco puntos. No añadas OCR, IA, nuevas pantallas bancarias ni cambios fiscales. Informa brevemente: hecho, pruebas, hash y un bloqueo concreto si existe.

## Trabajo de Codex después del contrato

- Acceso «Guardar recibo o nota» desde Gastos y desde móvil.
- Captura breve con un adjunto y/o nota, estado «Pendiente de completar» y confirmación clara de qué quedó guardado.
- Una bandeja de pendientes y el formulario de completar con los datos ya disponibles, sin otro selector de archivo para el mismo respaldo.
- Acciones según las capacidades recibidas, foco visible y revisión a 360/390/768/1024/1360/1440 px.

## Evidencia y límites

Capturas y comprobaciones de navegador en [capturas/gastos-respaldos-nube](capturas/gastos-respaldos-nube/README.md). Resultados de la suite en [RESULTADOS-FRONTEND](RESULTADOS-FRONTEND.md). Vista local dentro del entorno de nube, no URL pública. Las credenciales, la base ficticia y el servidor de pruebas no forman parte del commit.

No se modificaron vistas, modelos, servicios, campos, endpoints, migraciones ni integración fiscal. Las operaciones de guardado en navegador afectan únicamente la base de demostración.
