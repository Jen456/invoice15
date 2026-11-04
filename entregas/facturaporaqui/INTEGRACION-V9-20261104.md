# Cierre del acceso a la entrega v9 y alcance de integración

04/11/2026. Repositorio de producción: **Jen456/invoice15**. Rama de entrega: **frontend/etapa3**.

## Resuelto en esta entrega

1. Se fusionó `plataforma f2a2b5b` en `frontend/etapa3`, conservando las secciones de ambos agentes en HANDOFF. El merge `673b82c` contiene las correcciones publicadas de plan y ganancias en móvil, los guiones de respaldo/restauración y la documentación de publicación.
2. Se conserva la entrega `006dea7` / `0d92a86`: RUC del proveedor del servicio solo en el pie y «Usar como base para otra factura». Estos commits **no estaban en `plataforma f2a2b5b` ni en el código publicado `29623af`** al comprobar GitHub.
3. La entrega v9 `25e4f78` de facturacion15 se puede revisar en [referencias/frontend-v9/](referencias/frontend-v9/README.md), dentro de invoice15. Son los 55 archivos de la entrega, con huellas por archivo y parche original de interfaz. Claude puede leerlos mediante el acceso a invoice15 que ya utiliza. No necesita una nueva llave ni acceso al otro repositorio.

No se fusionó el historial antiguo de facturacion15. Su backend parte de `817c5be`, mientras invoice15 ya incorpora multiempresa, cobros privados, secuencias, permisos y reglas posteriores. Las propuestas y sus recursos quedan dentro de `entregas/`, fuera de las plantillas, estáticos y rutas activos.

## Qué se integra y qué se usa como referencia

| Elemento de v9 | Situación comprobada en invoice15 | Tratamiento |
|---|---|---|
| Precio por línea y alta de cliente/producto | Ya existen con validación del servidor y permisos | Conservar la implementación actual; la referencia permite comparar el diseño |
| Formularios por secciones, campos móviles y foco | Ya existen; las correcciones publicadas están en esta rama | Conservar las mejoras de ambas entregas sin sustituir el tema compartido |
| Nota/archivo de pago opcionales de facturacion15 | Contrato diferente: `payment_note`, archivo de 10 MB y nota en `additional_info`; invoice15 usa cobros privados y condiciones específicas | No trasladar esos campos ni enviar una nota interna al XML. La instrucción sobre opcionalidad requiere adaptación explícita del contrato de backend, no ocultar campos que el servidor exige |
| Plan de cuentas, asientos, cierre y reportes de v9 | Son maquetas sin API; el backend contable completo sigue pendiente | Usar como diseño para los contratos de las próximas entregas; no incorporarlas al menú como funciones disponibles |
| Puntos de emisión | invoice15 ya tiene locales/puntos por usuario; v9 muestra ejemplos y verificación pendiente | Mantener permisos y numeración existentes; el cupo interno y la evidencia deben proceder del backend, no del ejemplo de tres puntos |
| NEXALLTI piloto | La propuesta recoge que se creó en localhost, sin confirmar Excel ni apertura | Mantener «pendiente de importar» y saldos desconocidos hasta obtener evidencia real; no cargar cifras de ejemplo |
| Guía PDF v9 | Describe la propuesta del otro backend | Referencia histórica, no manual de la aplicación publicada |

El contrato original trasladado se llama **CONTRATO-FRONTEND-PENDIENTE.md** y declara expresamente que no es un contrato API acordado. La copia accesible no cambia esa condición.

## Continuación concreta para Claude

1. En el worktree limpio de plataforma, hacer fetch del remoto de **invoice15** e integrar `frontend/etapa3`. A fecha de esta entrega `f2a2b5b` es ancestro de la rama, por lo que admite avance rápido. Si plataforma avanzó entretanto, conservar ambos cambios en una fusión normal, sin forzar historial.
2. Revisar los cambios de código desde `f2a2b5b`: corresponden a los RIDE y a reutilizar una factura. La carpeta `referencias/frontend-v9` es material para revisión, no código que se copie sobre la aplicación.
3. Ejecutar la verificación de integración del procedimiento de publicación, publicar los cambios activos y los estáticos con respaldo reciente y comprobarlos en la aplicación. La autorización de publicación de la propietaria sigue vigente; esta documentación no añade otra aprobación.
4. **Regenerar los PDF antiguos afectados:** publicar las plantillas no sustituye los archivos ya guardados al autorizar. Empezar por el comprobante señalado por la propietaria, identificado dentro de su empresa, usar `regenerar_ride` en ensayo, verificar fidelidad con el XML y aplicar con respaldo conservando el original. Mantener número, clave, XML, autorización e importes. Registrar documentos regenerados y pendientes por tipo. No volver a emitir para cambiar el diseño.
5. Confirmar con datos ficticios que «Usar como base» pide cliente, conserva las líneas, aplica los permisos de precio y asigna el número solo mediante el alta normal. Confirmar que el A4 descargado muestra el RUC del servicio en el pie.
6. Registrar hash efectivamente desplegado y resultados. No dar por conectadas las maquetas contables ni por actualizado un PDF únicamente porque cambió la plantilla.

La nueva entrega frontend no añade migraciones. El estado de producción y sus respaldos se toma de la verificación de Claude; Codex no accedió al servidor.

## Decisiones comerciales y contables: evitar volver a preguntar lo ya definido

La propietaria indicó en su encargo de backend, en esta conversación: **«Los precios anuales definidos por módulo son $150 para una empresa y $250 para multiempresa; impuestos y alcance multiempresa siguen pendientes».** Registrar esos importes y la periodicidad como decididos, sin convertirlos en un precio final con IVA ni inferir número de RUC, módulos agrupados o condiciones de activación. No se cambiaron precios, ofertas públicas ni accesos del complemento en esta entrega.

Siguen pendientes los impuestos y la cobertura/condiciones comerciales que falten, las respuestas a las 12 preguntas del contador, D5 (cuentas), D6 (extractos) y D7 (matriz de asientos). El acceso técnico a v9 queda resuelto independientemente de esas decisiones. No se inventan capital, saldos, fecha exacta de apertura ni criterios fiscales para completar pantallas.
