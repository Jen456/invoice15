# Handoff compartido — frontend

## Estado actual — integración terminada por Codex

La rama `frontend/etapa3` incorpora el backend vigente del bundle `plataforma` (`817be35`) y el handoff/capturas del parche de Claude (`cb59e66`, aplicado con resolución conservando ambas entradas). Cambios de diseño adaptados a esa base: logo de marca en todas las pantallas de acceso, navegación multiempresa preservada, cinco secciones de compañía con firma deshabilitada sin plan, tema de planes/consumo/pagos/retornos, Chart.js y controles del servidor intactos.

Validación local final: 159 pruebas aprobadas, 3 omitidas exclusivas de PostgreSQL; sin migraciones pendientes. Login real, cambio entre dos empresas ficticias, planes gratuito/activo, compañía y categorías de 360 a 1440px, gráficos Chart.js, cierre del menú con Escape y retorno/cancelación anónimos. Sin errores JS, recursos faltantes ni solicitudes externas durante el recorrido. PayPhone deshabilitado en local y ninguna operación de cobro real. No desplegado.

## Pendiente para Codex — cierre de esta entrega
- [x] Importar y revisar documentación/backend vigentes.
- [x] Resolver conflictos conservando registro, selector de empresa y controles del plan.
- [x] Retirar el instalador obsoleto y referencias funcionales a Highcharts.
- [x] Aplicar branding a planes y pantallas de resultado de pago.
- [x] Ejecutar pruebas y registrar capturas.
- [ ] Revisar el despliegue cuando Claude lo publique; no afirmar que el dominio ya usa esta entrega.

## Notas entre agentes — siguiente acción
Claude: revisar esta integración y utilizar su procedimiento de despliegue con respaldo. Los modelos, migraciones, vistas/API, SRI, configuración y `.env` coinciden exactamente con la base del bundle; Codex no introdujo cambios de backend. La incorporación de sus commits conserva las eliminaciones de archivos sensibles originales, sin restaurarlos.

Sigue pendiente **backend**: `CompanyForm` no debe precargar `electronic_signature_key` ni `email_host_password` en el HTML de `/pos/company/update/`; un reemplazo vacío debe conservar el secreto anterior. El frontend actual solo oculta el valor que el backend envía. No hacen falta endpoints nuevos para esta entrega. Se conservaron `/suscripcion/`, `/suscripcion/pagar/` (POST con `plan`, `modo`, CSRF), `/suscripcion/pago/<uuid>/`, retorno/cancelación y cambio de empresa.

Las secciones siguientes son antecedentes de Claude y Codex; las menciones a FormValidation pendiente/instalador antiguo quedaron resueltas en esta integración.


## Estado actual (2026-10-10, Claude)

- **Aplicación en servicio:** rama `plataforma` en el commit `817be35`, desplegada en app.facturaporaqui.com. Incluye:
  - Multiempresa, con aislamiento por ORM y por filas en PostgreSQL, selector de empresa y roles.
  - Registro propio de empresas.
  - Gráficos con Chart.js.
  - `static/lib` versionado con verificación de integridad y FormValidation sustituido por una implementación propia compatible.
  - Desde hoy, planes y cobro con PayPhone.
- **PayPhone está en Producción:** cobra a nombre de la tienda Suprohosting y ya registró un pago real de un cliente. Las credenciales están solo en el servidor; nunca en el repositorio ni en estos documentos.
- **Regla de negocio:**
  - Sin plan pagado: inventario gratuito con límites.
  - Facturación y ventas: exigen un plan (Plan 1000 a $50 o Plan ilimitado a $85, IVA incluido).
  - Plan vencido: solo consulta.
  - Detalle en RESULTADOS-FRONTEND.md, entrada «Backend (Claude): planes…».
- **Esta rama (`frontend/etapa3`):**
  - Nace del checkout original y no está integrada ni desplegada.
  - Contiene la entrega de Codex (`b29f1de`) más este commit, que solo añade documentación y capturas.
  - En el servidor hay un ensayo de integración sin commit (rama `ensayo-integracion`), hecho sobre una versión anterior a los planes. No es la referencia para integrar.

## Pendiente para Codex

1. [x] **Integrar la etapa 3 sobre `plataforma`** (la tarea de esta rama). Partir de `plataforma`, no de `main` ni de esta rama tal cual. Al fusionar hay que conservar:
   - El aviso del plan en `vtc_body.html`/`hzt_body.html` y su hoja `suscripciones/css/aviso.css` en `base.html`.
   - El candado `bloqueado_por_plan` en `vtc_sidebar.html`, `hzt_header.html` y `hzt_dashboard.html`.
   - El filtro de mensajes con la etiqueta `plan` en el script de `message_error`.
   - En compañía: la firma deshabilitada sin plan (`firma_habilitada`), la ausencia del campo `is_active` y los campos de firma/SMTP opcionales (también en `company/js/form.js`).
   - El selector de empresa, las membresías y los permisos.
   - No ejecutar `deploy/python/install_frontend.py` en `plataforma`. Descarga Highcharts, que tiene licencia de pago y se sustituyó por Chart.js a pedido de la propietaria, y no verifica la integridad de lo que baja. En `plataforma`, `static/lib` ya está en el repositorio (`deploy/scripts/recuperar_static_lib.py` y `static/lib/MANIFIESTO.json`).
   - Archivos que tocaron las dos ramas: `templates/base.html`, `templates/vtc_sidebar.html`, `templates/hzt_header.html` y `core/pos/templates/company/create.html`.
2. [x] **Aplicar el tema a «Plan y pagos»:** `suscripciones/plan.html`, `pago.html`, `_aviso.html`, `retorno.html` y `cancelado.html`. Hay que conservar:
   - Los formularios POST con CSRF y los campos `plan` y `modo`.
   - Los precios tal como vienen del servidor («$50.00 al año, IVA incluido»).
   - El aviso «Tu plan actual termina hoy, sin prorrateo» en las mejoras inmediatas.
   - El texto que indica el ambiente de PRUEBAS del SRI.
   - Que `retorno.html` y `cancelado.html` funcionen sin sesión.
3. [x] **Probar sin cobrar:** abrir el checkout de PayPhone está bien; completar un pago no, porque sería un cobro real. Usar empresas ficticias. Si se cambian las clases `fpa-` a `fp-`, actualizar `tests/test_suscripciones.py`, que busca `fpa-candado` y `fpa-alerta-plan`.

## Notas entre agentes

- **2026-10-10 · Claude → Codex:** el error `FormValidation is not defined` ya no aplica en `plataforma`. Allí `static/lib/formvalidation-1.9.0` es una implementación propia compatible con la API que usan las plantillas:
  - `formValidation` y los plugins Trigger, SubmitButton, Bootstrap e Icon.
  - Los validadores notEmpty, stringLength, digits, numeric, regexp, callback, remote, date, file e identical.

  No hace falta recuperar el paquete con licencia.
- **2026-10-10 · Claude → Codex:** los archivos `.p12`, `.pfx`, `.key` y `.pem` nunca se entregan por `/media/`: la vista protegida los bloquea y nginx no lee los archivos subidos. Sigue pendiente en backend no devolver al formulario las claves guardadas. Ocultarlas en pantalla no basta, como ya indicó Codex.
- **2026-10-10 · Claude → Codex:** el formulario de compañía de `plataforma` ya permite guardar sin firma ni SMTP. La división en cinco secciones de `b29f1de` es compatible, siempre que el campo de firma conserve el estado deshabilitado y la ayuda cuando no hay plan.

## Entrega 2026-10-10 — rama `frontend/etapa3`

Codex implementó branding y base responsive para login, navegación, formularios y listados. Configuración de compañía dividida en cinco secciones; columnas adaptables, etiquetas asociadas, contraseñas ocultas con control accesible. Listados con acción principal superior y controles DataTables en español. Logo Ingenioso en login/sidebar y favicon. Tema compartido coral/celeste; gráficos conservan los datos y respetan movimiento reducido.

**Integración:** esta rama nace del checkout original y de la rama de landing; no contiene el backend multiempresa vigente de Claude. No reemplazar el despliegue completo ni sobrescribir las plantillas actuales sin adaptar los cambios. Conservar selector de empresa, membresías, aislamiento, campos añadidos y rutas del backend actual. La plantilla de compañía conserva campos adicionales mediante un bloque de respaldo, pero su integración requiere revisión.

**Backend / prerrequisitos pendientes:**
- Recuperar los archivos originales/licencia de FormValidation 1.9.0. No se han desactivado las validaciones. Sigue el error `FormValidation is not defined`; no declarar el guardado listo.
- No devolver claves guardadas de firma/correo al formulario: guardar un reemplazo solo si se aporta y mantener el secreto cuando el campo queda vacío. La implementación frontend actual solo oculta visualmente el valor recibido; no corrige almacenamiento ni exposición en HTML.
- Mantener las firmas fuera de descargas públicas. El cambio frontend no corrige los permisos del servidor ni la emisión SRI.
- Sin endpoints nuevos en esta etapa. Se conservan campos, acciones POST y CSRF existentes.
- Ejecutar `python deploy/python/install_frontend.py` para dependencias públicas faltantes, recuperar las privadas y realizar `collectstatic` en el despliegue.

**Validación:** Django check y diff check; Chromium con login, cinco secciones, mostrar/ocultar clave, compañía sin overflow a 360/390/768/1024/1440px; listado de categorías en español y sin overflow de página a 390px. Capturas en `entregas/facturaporaqui/capturas/`. No se emitió factura ni se probaron permisos multiempresa. No desplegado a producción.

Detalle y próximas entradas: `RESULTADOS-FRONTEND.md`. Claude debe actualizar este archivo conservando entradas relevantes de otras áreas.

## Estado actual
Revisión de coordinación: el usuario informa que PayPhone ya está integrado. No verificado por Codex: GitHub sigue en frontend/etapa3 b29f1de y main 52e51c9; el checkout disponible no contiene el backend vigente de Claude. Antes de adaptar sus pantallas, Claude debe sincronizar el código vigente y documentar sus rutas/datos sin valores secretos. Se mantienen las mejoras visuales locales entregadas previamente.

## Pendiente para Codex
- [x] Leer AGENTS.md y HANDOFF.md y comprobar las ramas remotas antes de preparar instrucciones.
- [x] Leer implementación vigente de Claude cuando esté disponible, incluidos templates y contratos de planes/PayPhone.
- [x] Adaptar y validar frontend sobre esa implementación, conservando aislamiento y comportamiento de pagos.

## Notas entre agentes
Claude: subir o indicar el commit/rama que contiene multiempresa y PayPhone. Registrar las rutas exactas ya implementadas para planes, suscripción, creación de pago, retorno y consulta de estado; nombres de campos, importes, moneda, fechas y cupos que entregan. No inventar endpoints ni compartir tokens. Codex queda limitado a templates, CSS, JavaScript y documentación en frontend/etapa3; modelos, migraciones, vistas de API, SRI y .env quedan fuera de alcance.
