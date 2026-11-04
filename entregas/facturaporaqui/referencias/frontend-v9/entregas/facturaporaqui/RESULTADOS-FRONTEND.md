# Entrega de interfaz sobre facturacion15 — 3 de noviembre de 2026

**Entrega verificada en GitHub:** código, pruebas y evidencia en `eec8d8751d004096fb832bdfae685b01c0038e62`, rama `frontend/experiencia-contable-v9`. El commit de cierre posterior solo registra la entrega en esta documentación y HANDOFF. El PR no se ha abierto: pendiente de aplicar la ampliación del acceso de red a `api.github.com` guardada para revisión en la configuración del entorno. La rama y la descripción del PR sí están subidas.

## Base y alcance

- Repositorio: `Jen456/facturacion15`. Base: PR #1, `817c5be8a7e60c64a64d596d56dd37b7805aefc9`.
- Rama propia: `frontend/experiencia-contable-v9`; worktree separado. No se modificaron `main`, la rama del PR #1 ni `invoice15/frontend/etapa3`.
- Se revisaron el código, la documentación del PR #1 y el formulario renderizado antes de intervenir. Este repositorio no incluye `AGENTS.md` ni contratos de pantallas contables. Se contrastó, solo como referencia, el cierre de `invoice15 baadb8b` para documentar las diferencias.
- **Word v9 no recibido**. No se afirma conformidad con un archivo que no se ha leído. Pendiente de adjuntar y revisar antes de aprobar el diseño definitivo.
- Sin cambios de backend, modelos, formularios Python, migraciones, permisos, rutas, lógica SRI ni cálculos tributarios.

## Interfaz real de facturación

`core/pos/templates/sale/admin/create.html`, `core/pos/static/sale/admin/css/experience.css`, `core/pos/static/sale/admin/js/ux.js` y ajustes acotados en `form.js`:

- Secciones Cliente, Productos, Pago y Revisión; resumen junto al pago en escritorio y debajo en móvil. Sin campos clonados.
- Precio por línea sobre el contrato existente; conserva catálogo y cálculo del PR #1. Servicios identificados «Sin inventario».
- Altas rápidas con errores junto al campo. Cerrar el diálogo de cliente conserva su borrador; se limpia únicamente tras éxito confirmado.
- Botones con nombre accesible, foco visible, controles de archivo, nota con contador, errores sin interpretar HTML del servidor y campos conservados ante rechazo.
- Validación del vencimiento del crédito en navegador; no sobrescribe la fecha acordada al cambiar emisión. El servidor conserva su autoridad de validación.
- Aviso 409 con botón de recarga y confirmación de pérdida de lo no guardado. Sin reenvío automático ni cambio automático de empresa.
- Protección de interfaz contra doble confirmación/envío simultáneo. No sustituye idempotencia del backend ni autoriza reintentar una emisión incierta.
- «Contado» conserva `payment_type=efectivo`. La nota y el adjunto siguen opcionales; efectivo recibido y cambio ya estaban retirados por el PR #1 y no se reintroducen.
- Se advierte que la nota se incluye como condiciones de pago del comprobante. No se presenta como una nota interna ni como cobro confirmado.

`templates/base.html`: idioma español y zoom habilitado. `templates/form.html`: bloque opcional de clase para aplicar el diseño solo a la factura. El resto de formularios mantiene su clase y comportamiento.

`static/css/facturaporaqui.css`: componentes `fp-*` con coral, celeste y azul de la marca. `static/img/brand/isotipo-pie.png`: colibrí existente de la marca, sin modificación, 14.737 bytes. No se agregaron librerías ni CDN.

## Propuesta contable, todavía sin API

`propuestas/ux-v9/`: inicio, plan de cuentas, asientos desde comprobante, revisión del mes, reportes y puntos de emisión.

- Árbol de grupos/cuentas de movimiento y búsqueda que conserva padres.
- Diseño de importación con mapeo y errores por fila de **ejemplo**. Seleccionar Excel no lo analiza, envía ni importa. Confirmación deshabilitada.
- Comprobante → asiento → origen, débitos/créditos, borrador y excepciones. No se confirma ni contabiliza desde la maqueta.
- Mes: documentos, pendientes, IVA/ATS, apertura, responsables y respaldos. Sin cierre ni presentación ficticia.
- Resumen/detalle con etiqueta provisional y CSV de demostración rotulado en nombre y contenido.
- NEXALLTI solo como piloto reportado: Excel, apertura y conciliación pendientes. Al seleccionarlo desaparecen los ejemplos financieros de Comercio Demo. No se usaron sus identificaciones ni cifras reales.
- Tres puntos como límite interno ilustrado; establecimiento y punto separados. Ninguno se marca verificado sin evidencia.
- Estados seleccionables de carga, vacío, error, permisos insuficientes y pendientes, exclusivamente en la propuesta.

Dependencias detalladas en `CONTRATO-FRONTEND-PENDIENTE.md`. Son solicitudes para Claude, no un contrato acordado ni endpoints implementados.

## Comprobaciones reales

| Comprobación | Resultado y límite |
|---|---|
| Django SQLite, `workflow_tests`, ajustes aislados del PR #1 | 11 pruebas aprobadas; no se importan ajustes de producción |
| Node, `workflow_tests/test_sale_frontend.cjs` | 2 pruebas aprobadas: cálculo existente y precio editable |
| Navegador Chromium, `frontend_tests/verify_browser.py` | **87 comprobaciones aprobadas**, sin errores JS ni recursos fallidos |
| Anchuras | 360, 390, 768, 1024, 1360 y 1440 px: factura y seis pantallas contables sin desborde de página |
| Estados y conservación | Error de alta rápida, corrección, vencimiento, archivo inválido, 409, borrador del cliente, confirmación/cancelación y respuesta de validación; respuestas HTTP simuladas |
| Accesibilidad | Etiquetas, teclado, foco, diálogos, árbol nativo, zoom habilitado, movimiento reducido y tablas desplazables con región identificada |
| Contrastes de componentes | Texto principal 11,83:1; secundario 5,78:1; botón coral/blanco 4,75:1; aviso 6,64:1; estado verde 6,57:1. No equivale a auditoría WCAG completa |
| Guía PDF | Dos páginas A4, guía de propuesta; funciones no publicadas identificadas |
| Integridad | `git diff --check` y sintaxis JS sin errores; ningún archivo de backend modificado |

Evidencia en `capturas/ux-v9/`: **31 JPG**, todos menores de 150 KB, y `verificacion.json`. Capturas principales a 360/768/1360, más errores, importación, asiento, piloto y estados. Las pruebas usan la plantilla real con un marco de vista previa; **no son una prueba completa del menú/autenticación del servidor real**.

El servidor de vista previa rechaza POST. Playwright simula las respuestas del contrato para probar la interfaz; las 11 pruebas Django verifican la persistencia del backend existente en SQLite por separado. No se probó PostgreSQL, SRI, cobro real, correo, seguridad multiempresa de producción ni importación real de Excel en esta entrega.

Correcciones durante la revisión: altura de Select2 con textos largos, ancho del selector de empresa móvil y prueba de foco cambiada de enfoque programático a navegación real Tab/Shift+Tab. La guía se ajustó para evitar un pie aislado en una tercera página.

## Entrega y pendientes

- `manuales/guia-interfaz-v9.html` y `Guia-interfaz-v9-propuesta.pdf`: guía actualizada de esta propuesta; no distribuir como manual de funciones publicadas.
- Instrucciones reproducibles: `frontend_tests/README.md`.
- Word v9 y contratos contables pendientes; propiedad de archivos propuesta en HANDOFF, sin afirmar un acuerdo recibido de Claude.
- PR previsto **sobre la rama del PR #1** para mantener separado este diff frontend de sus cambios de backend. Su integración depende de esa base.
- La API `api.github.com` devuelve `Forbidden` en este entorno. Git funciona; el estado de subida y del PR se registra en el cierre de entrega.
- No se desplegó ni se emitieron documentos, pagos o correos.
