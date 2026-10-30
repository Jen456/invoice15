# Propuesta: Ingenioso IA para FacturaPorAquí

Fecha: 30/10/2026, Ecuador. Estado: **propuesta para decidir antes de programar**. No se crea una funcionalidad disponible, no se contrata una API y no se fijan precios comerciales.

## Recomendación

Ofrecer **Ingenioso IA** como complemento opcional, separado de los planes de facturación y del futuro complemento Contable. El cliente paga por adelantado y recibe una bolsa limitada de uso. Como la app mantiene cobro anual, la propuesta principal es **suscripción anual con cupo renovado mensualmente** y recargas opcionales también prepagadas. No ofrecer uso ilimitado.

Se cobra por empresa/RUC, con una bolsa compartida por los usuarios autorizados de esa empresa y sublímites por usuario. Multiempresa necesita un paquete propio: los diez RUC del plan base no reciben diez cupos de IA automáticamente. Aunque una empresa titular compre una bolsa para varias, cada conversación y cada consulta permanecen dentro de un solo RUC autorizado.

El soporte básico y las instrucciones esenciales de la aplicación seguirían accesibles mediante ayuda convencional; las consultas que usan la API de IA requieren suscripción y saldo. Un ejemplo estático puede mostrar cómo funciona antes de contratar, sin hacer llamadas facturables.

## Alcance progresivo

| Etapa | Trabajo que puede ofrecerse | Condición de salida |
| --- | --- | --- |
| 1. Ayuda y redacción | Explicar pantallas, redactar correos, preparar textos comerciales y resolver preguntas de gestión; apoyarse en documentación aprobada de FacturaPorAquí | Respuestas útiles en español, referencias a la ayuda, límites de gasto y pagos probados |
| 2. Consulta del negocio | Resumen de ventas, cuentas por cobrar, productos y documentos de la empresa activa | Herramientas de consulta con permisos del usuario, resultados verificables y aislamiento entre RUC |
| 3. Trabajo práctico | Proponer una proforma, datos para un cliente/producto o un borrador de mensaje a partir de una instrucción | Vista previa completa, validación del backend y confirmación explícita antes de guardar o enviar |

No anunciar «hace cualquier trabajo». Publicar una lista de tareas disponibles. Los cálculos, tarifas, saldos y reglas fiscales provienen de servicios deterministas del sistema. El modelo interpreta y explica; no sustituye esa lógica. Emitir/anular comprobantes, enviar correos, registrar pagos o presentar declaraciones no forma parte del MVP. Los textos tributarios deben indicar fuente y fecha, y distinguir orientación de una validación contable.

## OpenAI o Anthropic

La integración usa una API de pago por consumo, no una suscripción personal de ChatGPT o Claude. El cliente de FacturaPorAquí no necesita una cuenta ni una clave del proveedor. Las claves pertenecen al operador y se usan únicamente desde el servidor.

**No hay un ganador de costo confirmado en esta propuesta.** Este entorno no permite consultar las páginas de precios de ambos proveedores. No se presentan nombres de modelos, tarifas ni condiciones de retención como verificados hoy.

Antes de elegir, contrastar las páginas oficiales:

- OpenAI: <https://openai.com/api/pricing/>
- Anthropic: <https://www.anthropic.com/pricing>

Comparar un modelo económico de cada proveedor con el mismo conjunto de al menos 50 tareas ficticias: ayuda, redacción, explicación de datos, selección de una herramienta y recuperación ante una solicitud incompleta. Medir aciertos, alucinaciones, latencia, entradas/salidas facturables y costo por tarea resuelta. Un modelo barato que necesita tres intentos puede costar más.

Implementar inicialmente **un proveedor**, con un adaptador que permita sustituirlo. No pagar consultas simultáneas a ambos por defecto. Un modelo de mayor capacidad sería una opción posterior, con costo en créditos visible y límite explícito. Confirmar en ese momento disponibilidad regional, política de uso de datos y condiciones de procesamiento.

## Costos y precio de venta

La cantidad de cuentas registradas no equivale al gasto. Importan usuarios activos, tareas por usuario, tamaño del contexto, adjuntos y número de llamadas a herramientas. El historial reenviado también puede generar consumo; una tarea del cliente puede requerir varias llamadas a la API.

Estimación de API por tarea: `(tokens de entrada × tarifa de entrada + tokens de salida × tarifa de salida) / 1.000.000`, más las demás partidas que facture el proveedor: razonamiento según el modelo, caché, búsqueda, procesamiento de archivos u otras herramientas. Confirmar qué conceptos están incluidos para no contarlos dos veces.

**Simulación, no cotización:** si una tarea completa cuesta en promedio USD 0,005 y cada empresa consume 200 tareas al mes:

| Empresas activas | Tareas al mes | Gasto mensual solo de API |
| ---: | ---: | ---: |
| 25 | 5.000 | USD 25 |
| 100 | 20.000 | USD 100 |
| 1.000 | 200.000 | USD 1.000 |

Con USD 0,02 por tarea, los tres importes se multiplican por cuatro. Estos valores son supuestos de cálculo, no precios de OpenAI ni Anthropic. No incluyen hosting, almacenamiento, soporte, comisión de PayPhone, impuestos, desarrollo o margen comercial.

La tarifa comercial y el cupo quedan **por definir** tras medir un piloto. No se modifica ningún precio vigente: Plan 1000 USD 50, Ilimitado USD 85 y Multiempresa USD 199. El complemento Contable conserva su propia decisión de precio pendiente.

Para el cliente conviene hablar de **créditos de uso**, con una regla sencilla publicada, en lugar de mostrar tokens. Una consulta breve puede consumir una unidad y un análisis extenso varias, siempre mostrando el máximo antes de empezar. Los ejemplos de créditos no se convierten en promesas de mensajes ilimitados ni de cantidad garantizada de documentos de cualquier longitud.

## Cobro antes de usar

1. El propietario elige el complemento, su alcance y período. Se muestran precio final, cupo, renovación y restricciones antes de pagar.
2. El backend crea la orden con el importe calculado por el servidor y la remite a PayPhone.
3. Solo una confirmación válida del servidor de PayPhone activa el derecho de uso. El retorno del navegador, una captura de pago o un estado pendiente no lo activan.
4. Antes de cada tarea se comprueba sesión, empresa activa, permiso, suscripción y saldo; se reserva el consumo máximo permitido de forma atómica.
5. Se ejecuta la tarea con un máximo de tokens, herramientas, duración y gasto. Al terminar se registra el consumo real y se libera la reserva no utilizada.
6. Sin saldo o con suscripción vencida, no se llama a la API. Se ofrecen renovación o recarga prepagada; no se genera una deuda ni un cargo automático sorpresa.
7. Pagos repetidos, retornos duplicados y solicitudes simultáneas no deben duplicar créditos ni gastar por encima del saldo. Las operaciones inciertas se concilian antes de repetirlas.

La app actual declara **renovación anual y manual** en `core/suscripciones/templates/suscripciones/plan.html`. Reutilizar la integración de cobros no significa que ya exista facturación recurrente automática: eso requiere confirmar soporte de PayPhone y autorización del cliente. La suspensión de IA no cambia la vigencia del plan base de facturación.

Propuesta de condiciones para decidir: bolsa mensual sin acumulación, límites por usuario y recargas con vencimiento explícito. Faltan la regla de contratación a mitad del año del plan base, cancelaciones/devoluciones, vigencia de recargas y tratamiento de tareas fallidas. Recomiendo devolver créditos por fallos del servicio, asumiendo como costo operativo lo que el proveedor hubiera facturado, y distinguir ese caso de una cancelación del usuario tras recibir parte de la respuesta.

## Arquitectura prevista para Claude, después de aprobar el alcance

Reutilizar Django, PostgreSQL, empresa activa, membresías y la infraestructura de pagos. Añadir un módulo delimitado de IA, sin reescribir el ERP.

Flujo: `interfaz → permiso y saldo → reserva de consumo → contexto autorizado → proveedor → resultado/consumo → historial`.

- Suscripción y bolsa de IA separadas del cupo de comprobantes fiscales.
- Libro de movimientos de créditos/reservas, orden de compra y conciliación; importes monetarios con decimal y trazabilidad del modelo/tarifa utilizados.
- Conversaciones y trabajos ligados a empresa y usuario; inicialmente privados para su autor salvo una política de compartir explícita.
- Herramientas con funciones concretas, por ejemplo consultar ventas del período; no SQL arbitrario ni acceso general de administrador. El servidor fija el RUC y verifica cada permiso, incluso cuando el modelo lo solicite.
- Documentación recuperada por relevancia, con fuentes y fecha; índices privados filtrados por empresa antes de enviar fragmentos. Adjuntos y texto recuperado son datos no confiables, no instrucciones que puedan otorgar permisos.
- Enviar al proveedor solo los datos necesarios. Nunca firmas, claves, tokens, archivos de entorno o datos de otra empresa. Informar al cliente del procesamiento externo y definir consentimiento/base aplicable, retención y eliminación antes del lanzamiento conforme a la LOPDP.
- Cola para análisis largos; progreso y recuperación del resultado sin depender de una petición web prolongada. Límites de tamaño/páginas de adjuntos y protección del historial por permisos.
- Límites de concurrencia, intentos, entrada/salida y presupuesto por empresa y global; registro técnico sin secretos. Resumen del historial para evitar reenviarlo completo indefinidamente. Cachés de datos privados siempre separadas por empresa y permisos.
- Pruebas con proveedores/pagos simulados: acceso sin pagar, devolución, doble confirmación, concurrencia de reservas, cambio de empresa, solicitudes que exceden cuota y recuperación de un resultado incierto.

Los modelos, endpoints, campos y estados definitivos se publicarán en HANDOFF antes de conectar el frontend. No están implementados ni autorizados por este documento.

## Diseño previsto para Codex

Marca propuesta: **Ingenioso IA · Tu asistente de negocio**, con el colibrí y la paleta existente.

- Acceso «Asistente IA» en el menú y botón contextual que no tape Guardar ni los controles móviles.
- Empresa/RUC activo visible; iniciar otra conversación al cambiar de empresa, conservando el aislamiento.
- Acciones sugeridas: «Ayúdame con esta pantalla», «Redacta un mensaje» y, solo cuando esté habilitado, «Resume mis cuentas por cobrar».
- En escritorio, panel lateral ampliable; en móvil, pantalla completa con entrada y controles accesibles.
- Tarjeta en «Plan y pagos» con precio, créditos disponibles, próxima reposición y fecha de vencimiento. Costos de tareas largas visibles antes de confirmar.
- Estados explícitos: sin contratar, pago pendiente, activo, en proceso, sin saldo, vencido y error recuperable.
- Resultados con enlaces a documentos autorizados y borradores revisables. Para una modificación: «Revisar propuesta» y después «Confirmar», con los datos exactos; una respuesta de texto no equivale a una operación guardada.

Antes del desarrollo: aprobar alcance del MVP y modelo de cobro; comparar proveedores con tarifas verificadas; elegir precio, cupo y reglas. Después, maquetas estáticas, contrato backend y piloto controlado. No añadir a la landing como «Disponible» hasta que esté integrado y probado.
