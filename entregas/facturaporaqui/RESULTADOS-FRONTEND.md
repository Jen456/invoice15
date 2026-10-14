# Resultados frontend — FacturaPorAquí

## 2026-10-10 — Revisión y propuesta previa a implementación

### Alcance y estado
El usuario solicita una propuesta antes de modificar la interfaz y exige mantener este registro para cada intervención futura: qué se hizo, archivos cambiados, cómo se probó y limitaciones. Esta intervención modifica únicamente este documento; no implementa el rediseño ni despliega cambios.

Se revisaron las dos capturas aportadas y las plantillas locales `templates/list.html`, `templates/form.html` y `core/pos/templates/company/create.html`. El checkout no representa la implementación multiempresa desplegada por Claude. Los hallazgos sobre código local deben contrastarse con esa versión antes de aplicar cambios. No se accedió al servidor ni se hicieron pruebas de producción.

### Hallazgos
- La configuración de compañía presenta muchos campos con poca jerarquía visual. En la plantilla local se agrupan en filas con `.col`, sin puntos de ruptura explícitos; esto puede mantener columnas demasiado estrechas en móvil.
- Los enlaces largos de archivos ocupan espacio y dificultan leer el formulario. La ruta técnica no debería ser la etiqueta del archivo.
- La tabla de categorías muestra desplazamiento horizontal pese a tener pocas columnas. La plantilla compartida envuelve DataTables en un contenedor de scroll y existen inicializaciones específicas por módulo; hay que revisar anchos, wrappers y configuración antes de cambiarla.
- Los controles de tablas aparecen en inglés en las capturas.
- Cabecera y selector de empresa compiten por espacio; hace falta un diseño específico para móviles y nombres extensos.
- Las capturas mantienen la identidad visual antigua y el icono anterior, en lugar del colibrí Ingenioso y la paleta acordada.
- Los campos de claves aparecen como texto visible. No se transcriben sus valores a este documento. Si las credenciales mostradas son reales, el propietario debe rotarlas. La interfaz debe ocultarlas por defecto y no devolver secretos existentes al navegador; esta última medida requiere backend.
- Las capturas de escritorio no permiten confirmar por sí solas todos los fallos en móvil. La revisión responsive debe hacerse en navegador con la versión vigente.

### Propuesta
1. Mantener Django y las funciones existentes. Aprovechar Bootstrap/AdminLTE inicialmente, con CSS compartido y JavaScript limitado a interacción. No introducir una reescritura con React como requisito.
2. Crear una base visual coherente: colibrí Ingenioso, coral #CA462C, celeste #44BADD, azul oscuro #163B50, azul claro #E5F1F6. Texto principal 16–18px y controles táctiles de al menos 44px.
3. Navegación responsive: sidebar en escritorio, menú lateral desplegable en móvil, botón accesible, cierre con Escape y gestión de foco. Selector de empresa compacto con nombre completo disponible; conservar membresías y permisos.
4. Formularios por secciones: datos de empresa, datos tributarios, establecimientos/puntos de emisión, firma y correo. Una columna en móvil, dos en tablet y hasta tres en escritorio cuando el contenido lo permita. Direcciones y nombres largos ocupan mayor ancho. Mantener nombres de campos, CSRF, validaciones y endpoints vigentes.
5. Archivos con nombre legible, estado y acciones explícitas. No mostrar rutas internas; no exponer descargas de firmas. Contraseñas ocultas, botón accesible de mostrar/ocultar y opción de reemplazo sin precargar secretos guardados.
6. Listados: título y acción principal arriba, búsqueda y filtros en español, acciones con etiquetas accesibles. Categorías sin desplazamiento horizontal innecesario. Tablas complejas mantienen scroll dentro de su panel o detalle responsive, nunca desbordan toda la página. Conservar ordenación, búsqueda y paginación.
7. Facturación como pantalla prioritaria: búsqueda de cliente/productos, detalle editable, totales legibles y acción de emisión clara en móvil. Distinguir pruebas y producción con texto, no solo color. Conservar cálculos y aislamiento multiempresa.
8. Feedback: errores junto al campo, confirmación de guardado, estado de carga y prevención de doble envío. Animaciones breves y respeto a movimiento reducido; no animar el logo ni distraer durante una emisión.

### Etapas y validación previstas (no ejecutadas)
- Etapa 1: base visual, navegación, login, configuración de compañía y categorías.
- Etapa 2: ventas/facturación, productos, clientes y reportes.
- Etapa 3: revisión transversal y despliegue coordinado con Claude.

Validar a 360, 390, 768, 1024 y 1440px: ausencia de desbordamiento de página; tablas desplazables solo cuando corresponde; menú y selector accesibles; foco por teclado; legibilidad y contraste; archivos estáticos sin 404; errores JavaScript. Probar login, cambio de empresa, búsqueda/paginación, alta/edición y validación de formularios. Para facturación usar entorno de pruebas y datos autorizados; no emitir en producción durante pruebas de diseño. Repetir las pruebas existentes de permisos/aislamiento cuando se integre en el código vigente.

### Archivos cambiados y comprobaciones de esta intervención
- Creado: `RESULTADOS-FRONTEND.md`.
- Comprobación: lectura de plantillas, revisión de capturas y `git diff --check`.
- No se ejecutaron pruebas funcionales ni de navegador en esta intervención. No se corrigió el error de permisos de archivos ni se validó SRI/PayPhone.

## Antecedentes de esta sesión (previos a este registro)
Ya existían cambios locales en `templates/base.html`, `templates/vtc_dashboard.html`, `templates/vtc_header.html`, `templates/vtc_sidebar.html` y `core/login/templates/login/login.html`; además de `static/css/facturaporaqui.css`, `static/js/facturaporaqui.js`, `deploy/python/install_frontend.py` y `entregas/facturaporaqui/DEPENDENCIAS-FRONTEND.md`. Se preparó branding en `static/img/brand/` y en `landing/`; la landing y los archivos de marca fueron subidos a la rama `landing-facturaporaqui`. Los cambios locales de templates de la aplicación no se subieron como reemplazo de la versión multiempresa.

En intervenciones anteriores se ejecutó `manage.py check` y se verificaron localmente login, renderizado de dos gráficos, menú lateral y dashboard móvil de 390px. Quedó pendiente FormValidation y otras dependencias específicas. Estas verificaciones corresponden al checkout original, no prueban el estado actual del dominio ni la versión multiempresa de Claude.

## Regla para próximas intervenciones
Agregar una entrada por intervención con objetivo, implementación real, archivos modificados, comandos y resultados de validación, errores pendientes y estado de despliegue. Distinguir propuesta, cambio local, cambio en GitHub y publicación. No registrar contraseñas, claves privadas ni valores secretos.

## 2026-10-10 — Implementación inicial con branding, rama `frontend/etapa3`

### Qué se hizo
Se adoptó la coordinación solicitada con Claude: handoff compartido, resultados detallados, convenciones en AGENTS y commits en la rama frontend. Se consolidó el tema y branding local preparados en sesiones anteriores. Nueva implementación: formulario de compañía en cinco secciones (empresa, tributaria, emisión, firma, correo), grid de una/dos/tres columnas, fallback para campos nuevos, etiquetas asociadas, claves ocultas y botón mostrar/ocultar. Listados con nueva acción superior y controles en español; corrección del wrapper de tabla compartido/categorías. Cabecera móvil ajustada para evitar overflow, soporte de Escape en menú y marca en navegación horizontal. Se recuperaron dependencias públicas TouchSpin y tema Select2.

### Archivos de la entrega
Nuevos: `static/css/facturaporaqui.css`, `static/js/facturaporaqui.js`, `core/pos/templates/company/field.html`, `deploy/python/install_frontend.py`, `entregas/facturaporaqui/DEPENDENCIAS-FRONTEND.md`, `HANDOFF.md`, `AGENTS.md`, este registro y `entregas/facturaporaqui/capturas/`.
Modificados: `templates/base.html`, `templates/vtc_dashboard.html`, `templates/vtc_header.html`, `templates/vtc_sidebar.html`, `templates/hzt_header.html`, `templates/list.html`, `templates/form.html`, `core/login/templates/login/login.html`, `core/pos/templates/company/create.html`, `core/pos/static/category/js/list.js`.
Los archivos de marca ya estaban versionados en la rama de landing de la que nace esta rama.

### Pruebas y resultados
- `manage.py check`: sin problemas.
- `git diff --check`: sin errores de formato.
- Chromium local: login correcto, cinco secciones renderizadas, password oculto inicialmente y control de visibilidad funcional.
- Compañía a 360, 390, 768, 1024 y 1440px: sin desbordamiento horizontal de página. La primera prueba falló a 360px por la cabecera; se corrigió y la repetición pasó.
- Categorías a 390px: controles en español y sin desbordamiento horizontal de página.
- Capturas: `entregas/facturaporaqui/capturas/company-escritorio.png`, `company-movil.png`, `categorias-movil.png`. Datos locales de desarrollo; no capturas de credenciales de producción.
- Dependencias: se detectaron `FormValidation is not defined` y TouchSpin faltante. Se instaló TouchSpin; FormValidation permanece pendiente. No se probó guardado con certificado, correo, emisión SRI ni permisos multiempresa.

### Límites y coordinación
Cambios locales sobre código original, no una comprobación de app.facturaporaqui.com. No despliegue ni modificación de datos productivos. Claude debe adaptar la capa visual al backend multiempresa actual; no reemplazar todo su código con esta rama. El frontend oculta claves pero sigue recibiendo los valores que entrega el backend: la solución de no precargar secretos se solicita en HANDOFF.

### Ubicación de entrega solicitada
Documentación reunida en `entregas/facturaporaqui/`: HANDOFF.md, RESULTADOS-FRONTEND.md, AGENTS.md, DEPENDENCIAS-FRONTEND.md y capturas/. No existe RESULTADOS-REGISTRO.md en este checkout; no se creó un informe de backend ficticio ni se sobrescribió el archivo de Claude. Al integrar, colocar estos documentos junto al informe existente en su versión. Los archivos funcionales CSS/JS/templates permanecen en sus rutas requeridas por Django.

## Revisión de coordinación y prompt para Claude
Se leyeron `entregas/facturaporaqui/AGENTS.md` y `HANDOFF.md` y se comprobaron rama activa, limpieza del checkout y referencias remotas. Rama activa frontend/etapa3. Las referencias previas a esta entrada siguen en b29f1de (frontend), e980891 (landing) y 52e51c9 (main). La integración PayPhone informada por el usuario no está disponible en ese código y no se afirma haberla auditado. Se prepararon instrucciones para que Claude sincronice su versión e integre el diseño manteniendo contratos existentes.

Archivos modificados: HANDOFF.md (Estado actual, Pendiente para Codex, Notas entre agentes) y RESULTADOS-FRONTEND.md. No se modificaron aplicación, modelos, migraciones, API, SRI o .env. Validación: lectura de instrucciones, git ls-remote --heads origin y git diff --check; sin pruebas de navegador porque no hay cambios visuales en esta intervención.
## 2026-10-10 — Backend (Claude): planes, cobro con PayPhone y cambios que tocan la interfaz

### Objetivo y estado
Regla de negocio pedida por la propietaria: facturación y ventas solo después de pagar un plan con PayPhone, e inventario gratuito con límites. Implementado en la rama `plataforma` (aplicación multiempresa vigente), **no en esta rama**: commits `24023f1`, `588ddaf`, `ddd88e9` y `817be35`, desplegados en app.facturaporaqui.com. Esta entrada documenta lo que la capa visual debe conservar al integrar `frontend/etapa3`.

### Qué se hizo
- App nueva `core.suscripciones`: planes (gratuito, Plan 1000 a $50 y Plan ilimitado a $85, IVA 15 % incluido), pagos, períodos anuales y cupo de comprobantes.
- **Sin plan pagado:** productos, categorías, proveedores, compras, ajustes de stock, cuentas por pagar, reporte de compras, usuarios y datos de la empresa. Límites editables en /plataforma/: 50 productos, 10 proveedores y 30 compras al mes.
- **Exigen plan:** ventas, clientes, comprobantes, notas de crédito, promociones, gastos, cobros y reportes de ventas.
- **Plan vencido:** solo consulta. **Cupo agotado** (solo en producción del SRI): todo salvo emitir.
- **Cobro:** Botón de Pagos de PayPhone por redirección desde «Plan y pagos» (`/suscripcion/`). El precio y el IVA los fija el servidor; el resultado se confirma con PayPhone servidor a servidor en `/suscripcion/pago/retorno/`. Renovación sin prorrateo y sin días de gracia.
- **Cupo:** se descuenta solo cuando el SRI autoriza el comprobante; el ambiente de PRUEBAS del SRI no descuenta.
- **Compañía:** la firma `.p12` solo se puede subir con plan vigente. Firma, clave de firma y SMTP propio dejan de ser obligatorios para guardar los demás datos, y el formulario ya no muestra el campo `is_active`.

### Cambios visibles que hay que conservar al integrar
| Elemento | Archivos | Detalle |
|---|---|---|
| Aviso del plan bajo la cabecera | `core/suscripciones/templates/suscripciones/_aviso.html`, `templates/vtc_body.html`, `templates/hzt_body.html`, `templates/base.html` | `{% include 'suscripciones/_aviso.html' %}` justo antes de `{% block content %}`. Estilos en `core/suscripciones/static/suscripciones/css/aviso.css`, cargado en `base.html` después de `css/style.css`. |
| Candado en módulos que exigen plan | `templates/vtc_sidebar.html`, `templates/hzt_header.html`, `templates/hzt_dashboard.html` | `{% load suscripciones %}` y `{% if module.url\|bloqueado_por_plan:fpa_plan %}` con `.fpa-candado` y texto oculto «(requiere plan)». Solo aparece en plan gratuito. |
| Mensajes del plan | `templates/vtc_body.html`, `templates/hzt_body.html` | El script que llama a `message_error` omite los mensajes con la etiqueta `plan`; se muestran dentro de «Plan y pagos» (`.fpa-alerta-plan`). |
| Plan y pagos | `core/suscripciones/templates/suscripciones/plan.html`, `pago.html`, `static/suscripciones/css/plan.css` | Estado y vigencia, uso del plan gratuito, tarjetas de planes y historial. Cada botón es un formulario POST con CSRF a `/suscripcion/pagar/` con los campos `plan` y `modo`. El detalle del pago incluye la solicitud de factura. |
| Retorno y cancelación de PayPhone | `retorno.html`, `cancelado.html` | Estilo del login (`login/base.html`, `.fpa-auth-card`). Se abren sin sesión. |
| Compañía | `core/pos/templates/company/create.html`, `core/pos/static/company/js/form.js` | Sin plan, `electronic_signature` se pinta deshabilitado con ayuda y enlace a planes (variable `firma_habilitada`). Sin `notEmpty` en firma, clave de firma y usuario/clave SMTP; el validador del `.p12` acepta el campo vacío. |
| Errores AJAX | `static/js/functions.js` y JS de cliente, proveedor, compañía, venta y dos reportes | El callback `error:` muestra `jqXHR.responseJSON.error` si existe. El bloqueo por plan responde HTTP 403 con `{"error": "...", "plan": "requerido"}`. |
| Menú | módulo `/suscripcion/` | «Plan y pagos», icono `fas fa-credit-card`, sin tipo de módulo. Solo Propietario y Administrador. |

### Archivos (rama `plataforma`)
- **Nuevos:**
  - `core/suscripciones/`: modelos, `servicios.py`, `cupo.py`, `payphone.py`, `middleware.py`, `senales.py`, `reglas.py`, vistas, URL, admin, plantillas, CSS, `templatetags/suscripciones.py`, el comando `vencer_pagos_pendientes` y las migraciones 0001–0002.
  - `core/pos/migrations/0007_purchase_created_at.py`, `core/tenancy/migrations/0004_alter_auditlog_action.py` y `tests/test_suscripciones.py`.
- **Modificados:**
  - Configuración: `config/settings.py`, `config/urls.py`, `.env.ejemplo`.
  - POS: `core/pos/models.py`, `core/pos/forms.py`, `core/pos/views/company/views.py`, `core/pos/templates/company/create.html`, `core/pos/static/company/js/form.js` y los comandos `electronic_billing` e `insert_test_data`.
  - Seguridad y multiempresa: `core/security/management/commands/start_installation.py` y `core/tenancy/{admin,middleware,models,roles}.py`.
  - Plantillas y JS: las plantillas y los callbacks AJAX de la tabla anterior.
  - Pruebas: `tests/helpers.py` y `tests/test_rutas.py`.

### Pruebas y resultados
- **pytest:** 156 pruebas (53 nuevas de suscripciones) pasan en SQLite y en PostgreSQL 16.
- **Navegador:** Playwright sobre app.facturaporaqui.com (a través de Cloudflare), a 1366×900 y 390×844, con dos empresas ficticias: una en plan gratuito y otra con un período de demostración sin pago.
  - La empresa gratuita ve el aviso y los candados, y Ventas la lleva a «Plan y pagos» con el aviso dentro de la página.
  - La acción AJAX bloqueada responde 403 con mensaje.
  - La firma aparece deshabilitada.
  - El límite de proveedores se muestra al intentar crear uno.
  - La empresa con plan abre Ventas y Nueva venta; los botones dicen «Renovar desde…» o «Cambiar desde…».
  - Sin desbordamiento horizontal y sin peticiones fallidas. El único error de consola es el 403 que provoca la prueba a propósito.
- **PayPhone:**
  - El token se verificó con una consulta que no cobra.
  - El botón abre el checkout oficial «Pagar a Suprohosting $50.00», sin introducir datos.
  - El 10/10/2026 un cliente real completó el primer pago en producción; el sistema lo confirmó y activó su plan.
- **No probado en navegador:** la emisión SRI real con cupo; está cubierta por pruebas automáticas con el SRI simulado. Tampoco se probó el diseño de la etapa 3 integrado.

### Capturas
En `entregas/facturaporaqui/capturas/`, con datos de empresas ficticias y sin credenciales:
- `plan-gratuito-productos-escritorio.png` y `plan-gratuito-productos-movil.png`: aviso y candados.
- `plan-gratuito-planes-movil.png`: Plan y pagos tras la redirección desde Ventas.
- `plan-activo-movil.png`: empresa con plan.
- `plan-retorno-desconocido-movil.png`: retorno de PayPhone con una referencia inexistente.
- `payphone-checkout-suprohosting.png`: checkout oficial, vacío.

### Pendientes
- Integrar `frontend/etapa3` sobre `plataforma`. Detalle en HANDOFF.md, «Pendiente para Codex».
- **Backend:** no devolver al HTML la clave de la firma ni la del SMTP; guardar un reemplazo solo si se escribe uno nuevo. Sigue pendiente, con la pantalla de firma cifrada.
- Unificar prefijos de clases: login y planes usan `fpa-` y AGENTS.md pide `fp-`. Las pruebas y el guion de verificación buscan `.fpa-aviso-plan`, `.fpa-candado` y `.fpa-alerta-plan`.

### Despliegue
- `plataforma`: desplegada en app.facturaporaqui.com. Ese entorno ya cobra dinero real (PayPhone en Producción).
- `frontend/etapa3`: este commit solo añade documentación y capturas; no se desplegó nada desde esta rama.


## 2026-10-10 — Integración real del frontend sobre plataforma 817be35

### Qué se hizo y base
Se verificaron SHA256SUMS (4 archivos) y git bundle verify. Se importó la referencia del bundle sin cambiar de rama de trabajo: frontend/etapa3. Se aplicó el parche documental de Claude mediante git am -3; el conflicto de RESULTADOS se resolvió preservando las dos entradas. Se fusionó la base plataforma y se resolvieron conflictos en login, compañía y landing, manteniendo registro/recuperación y la landing vigente de Claude. Las fusiones automáticas de base, menús y dashboard se revisaron para conservar avisos, candados, mensajes plan, selector de empresa y Chart.js.

Se sustituyó la marca compartida de acceso por el colibrí Ingenioso, de modo que login, registro, recuperación y resultados de pago usan el mismo símbolo. Se adaptó la sección de firma del formulario agrupado al indicador firma_habilitada y su enlace a planes. Se aplicó el tema compartido a Plan y pagos, estado, cupo, tarjetas, detalle y resultados, sin cambiar formularios POST ni precios/datos del servidor. Se mantuvieron los hooks fpa-candado y fpa-alerta-plan. Se retiró deploy/python/install_frontend.py y su descarga de Highcharts; los reportes y dashboard conservan Chart.js de plataforma. Se reforzó el margen de escritorio para evitar superposición del sidebar, observada en la revisión de capturas.

### Archivos específicos de esta integración
Modificados frente a la entrega frontend anterior: core/login/templates/login/login.html (versión vigente de Claude), core/login/templates/login/_marca.html, core/pos/templates/company/field.html, core/suscripciones/templates/suscripciones/plan.html, static/js/facturaporaqui.js, static/css/facturaporaqui.css, landing/index.html (versión vigente de Claude). Retirado: deploy/python/install_frontend.py. Incorporados desde Claude: backend y estáticos versionados; no son implementación de Codex. Documentación actualizada: HANDOFF.md, RESULTADOS-FRONTEND.md y DEPENDENCIAS-FRONTEND.md. Nuevo: tests/test_frontend_integracion.py y 6 capturas integracion-*.png.

### Cómo se probó
- Python 3.12 con dependencias base/dev mediante uv pip install --require-hashes. No cambios a requirements ni archivos .env.
- DJANGO_SETTINGS_MODULE=config.settings_test python manage.py check: sin avisos.
- manage.py makemigrations --check --dry-run con settings_test: no cambios detectados.
- python -m pytest -o addopts= -q: **159 passed, 3 skipped**. Las 3 omitidas requieren PostgreSQL; no se afirma haber validado RLS/concurrencia real con SQLite. Se agregaron 6 casos: dos estados de firma con/sin plan, logo y registro del login, precios/POST/checkout deshabilitado y retorno/cancelación sin sesión. La suite de PayPhone usa dobles del backend, no cobra.
- Chromium local: login y selección inicial de empresa; cambio entre dos empresas ficticias por selector; firma deshabilitada en gratuito y habilitada en plan activo; texto PRUEBAS del SRI preservado; 2 gráficos Chart.js; cierre de menú móvil con Escape.
- /suscripcion/, compañía y categorías revisadas a 360/390/768/1024/1440px: sin overflow de página. Retorno/cancelación anónimos a 390px: HTTP 200 y sin overflow.
- Durante el recorrido no hubo errores JavaScript, respuestas >=400 ni solicitudes a hosts externos. Pago local deshabilitado; ningún pago real ni envío al SRI.
- Revisión de diferencia frente al bundle: modelos, forms Python, vistas, API, SRI, config, migraciones y .env sin cambios propios de Codex. Diff check limitado a archivos frontend/pruebas propios sin errores; no se reformatearon vendor files de Claude con CRLF.

### Capturas y límites
Capturas en capturas/: integracion-login.png, integracion-plan-gratuito.png, integracion-plan-activo.png, integracion-dashboard.png, integracion-company-movil.png, integracion-cancelado-movil.png. Son del entorno local con datos ficticios, no evidencias de publicación.

No se accedió ni modificó ensayo-integracion del servidor. No se desplegó a app.facturaporaqui.com. Sigue pendiente que Claude deje de devolver claves guardadas al navegador. No se alteraron ni probaron fondos/pagos reales. Los botones deshabilitados en capturas corresponden a la configuración local, no al estado de PayPhone en producción.

## 2026-10-11 — Backend (Claude): claves fuera del navegador y publicación de `7eb9bd0`

### Qué se hizo
- Se revisó la integración de Codex `5cb91f1`. Es descendiente directo de `plataforma` `817be35` y, frente a esa base, solo cambia plantillas, CSS/JS, documentación, capturas y una prueba.
- Se comprobó que conserva:
  - el aviso del plan, el candado, el filtro de mensajes `plan` y `aviso.css`;
  - la firma bloqueada sin plan, ahora en `company/field.html`, y la ausencia de `is_active`;
  - el selector de empresa;
  - Chart.js, sin Highcharts ni el instalador antiguo.
- El escaneo de secretos de los 110 objetos nuevos no encontró nada. `plataforma` avanzó a `5cb91f1` sin conflictos.
- **Corrección de backend pendiente:**
  - La clave de la firma `.p12` y la del SMTP ya no se devuelven al navegador: `PasswordInput` sin valor. Vacío conserva la guardada; texto nuevo la reemplaza.
  - Aviso «Guardada. Déjala vacía para conservarla» en el `placeholder` y en el texto de ayuda.
  - «Ver certificado» usa la clave guardada si no se escribe otra.
- **Fuga adicional encontrada y corregida:**
  - `Company.toJSON()` se incrustaba en cada venta y nota de crédito de los listados AJAX (personal, reportes y el listado de compras que ven los clientes de la empresa) con la clave de la firma y la configuración SMTP.
  - Ahora excluye `electronic_signature_key`, `email_host`, `email_port`, `email_host_user` y `email_host_password`, y la ruta del `.p12` pasa a ser `true`/`false`.
  - Ningún JavaScript usaba esos datos.

### Archivos
- Modificados: `core/pos/forms.py`, `core/pos/models.py`, `core/pos/views/company/views.py`.
- Nuevos: `tests/test_secretos_empresa.py` y las capturas `capturas/despliegue-*.png`.
- Commit `7eb9bd0`, sobre `5cb91f1`.

### Pruebas
- **PostgreSQL 16:** 167 aprobadas, sin omitidas.
- **SQLite:** 164 aprobadas y 3 omitidas (solo PostgreSQL).
- `manage.py check` sin avisos; `makemigrations --check` sin cambios.
- Nuevas: el HTML de compañía no contiene las claves; vacío conserva; valor nuevo reemplaza; empresa sin claves guarda vacío; el JSON de ventas no lleva secretos (personal y cliente); «Ver certificado» con la clave guardada.

### Despliegue
- **Publicado:** `7eb9bd0` en app.facturaporaqui.com, con `deploy/scripts/desplegar.sh pruebas 7eb9bd0`, el 11/10/2026 a las 01:36 UTC.
- Respaldo previo de la base: `pre-20261011-013604-7eb9bd01.dump` (212 KB). Sin migraciones nuevas. Salud `/login/` → 200.
- Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir`.
- Tras el reinicio:
  - PayPhone sigue configurado (Producción, tienda Suprohosting).
  - Los planes no cambiaron: el cliente real conserva su Plan 1000, la demostración su período de demostración y OTRA-DEMO el plan gratuito.
- GitHub: `plataforma` y `frontend/etapa3` en `7eb9bd0`. Este registro va en el commit siguiente, que solo añade documentación.

### Verificación en el dominio
Playwright a 1366×900, 390×844 y 360×780, a través de Cloudflare, con empresas ficticias:

| Comprobación | Resultado |
|---|---|
| Login | Colibrí cargado, «Bienvenido de nuevo», enlace de registro, sin desbordamiento |
| Selector de empresa | Lista DEMOSTRACIÓN y OTRA-DEMO con sus roles; elegir lleva al panel; el cambio desde la cabecera funciona |
| Panel | 2 gráficos de Chart.js dibujados, aviso del plan gratuito y 14 candados |
| Menú móvil | Se abre con el botón y se cierra con Escape (390 y 360 px) |
| Compañía | 5 secciones, firma deshabilitada sin plan, claves de tipo `password` **sin atributo `value`**, sin `is_active` |
| Planes | Ventas redirige a «Plan y pagos» con el aviso en línea; $50.00 y $85.00 IVA incluido; botones de PayPhone activos y **no pulsados** |
| Cambio a DEMOSTRACIÓN (rol Consulta) | Ventas abre (200); «Plan y pagos» no está disponible para Consulta, que vuelve al panel, como corresponde |
| Retorno de PayPhone sin sesión | 200, colibrí, «No encontramos ese pago» |
| Landing facturaporaqui.com | 200, «FacturaPorAquí — Tu negocio, en orden», 2 enlaces a la aplicación, `www` → dominio principal |
| Recursos | 0 respuestas ≥400, 0 errores de JavaScript, 0 peticiones a dominios externos y 309 estáticos por vista |

- No se completó ningún pago ni se envió nada al SRI.
- Para probar el selector se añadió una membresía temporal de rol Consulta, en DEMOSTRACIÓN, al propietario de OTRA-DEMO. Se borró al terminar.

### Capturas
En `capturas/`: `despliegue-login-movil.png`, `despliegue-selector-movil.png`, `despliegue-panel-escritorio.png`, `despliegue-menu-movil.png`, `despliegue-compania-escritorio.png` y `despliegue-landing-movil.png`. Son del dominio publicado, con empresas ficticias y sin credenciales.

### Pendientes
- **Frontend (Codex), estéticos:** leyenda del pastel cortada en escritorio, rol cortado en la barra lateral, ruta interna en el campo del logotipo, barra fija de «Guardar» en la captura móvil y color del enlace «Cerrar sesión» del selector. Detalle en HANDOFF.md.
- **Backend (Claude):**
  - Las claves siguen guardadas en texto plano en la base; cifrarlas queda para la pantalla de firma de la etapa 3.
  - Falta una forma explícita de borrar una clave guardada.
  - Respaldo diario de la base, ahora que el dominio cobra dinero real.
  - Etapa 3: establecimientos y secuencias, envío al SRI en segundo plano y retenciones.


## 11/10/2026 — ajustes visuales tras la publicación (Codex)

Base sincronizada por avance directo a `2199c14`. Se leyeron AGENTS y HANDOFF y se conservaron las correcciones de claves de Claude. No se modificaron backend, modelos, migraciones, API, SRI ni `.env`.

Archivos cambiados:
- `static/js/graficos.js`: sustituida la leyenda truncada del pastel por una leyenda HTML con nombres completos, ajuste de línea y botones con `aria-pressed` para mostrar/ocultar segmentos. Se retira la leyenda anterior al redibujar, sin cambiar datos ni importes.
- `static/css/facturaporaqui.css`: ajuste de texto del usuario en sidebar, leyenda accesible, enlaces btn-link con coral de marca y acciones de compañía en flujo normal en móvil para evitar superposición; espacio inferior para área segura.
- `core/pos/templates/company/field.html`: logotipo actual descrito con texto legible, sin imprimir ruta. Se conservan carga `image`, borrado `image-clear`, errores y ayudas; claves siguen vacías según backend.
- `HANDOFF.md` y este informe: coordinación y límites de la entrega.
- Seis capturas locales `capturas/ajustes-*.png`, con empresas ficticias. El dashboard incluye un nombre artificial largo para comprobar la leyenda.

Pruebas: `node --check static/js/graficos.js`, `git diff --check`, suite SQLite: **164 aprobadas, 3 omitidas** (exclusivas de PostgreSQL). Chromium/Playwright: login, selector, cambio entre empresas ficticias, compañía, categorías, planes, gráficos y resultados anónimos; compañía/listados/planes a 360/390/768/1024/1440 px sin desbordamiento. Leyenda de nombre largo comprobada a esos tamaños, botón cambia aria-pressed al ocultar/mostrar segmento. Sin errores JS, recursos faltantes ni peticiones externas. La primera lectura inmediatamente después del cambio de tamaño detectó desbordamiento transitorio antes de que Chart.js redimensionara; se esperó el redimensionado y pasó. No se completó pago; PayPhone deshabilitado en configuración local externa al repositorio.

Inspección visual de la captura final del dashboard: nombre completo envuelto dentro de la tarjeta y marca preservada. No se verificó carga/borrado real del logotipo ni teclado virtual en teléfono físico. El guardado mantiene el contrato Django; revisar en dispositivo real tras desplegar. No desplegado por Codex: `7eb9bd0` es el publicado según Claude. PostgreSQL y comprobación directa del dominio no ejecutados en esta revisión.


## 11/10/2026 — colibrí en la landing

Petición: sustituir los símbolos de flecha señalados en la cabecera y el panel ilustrativo por el colibrí Ingenioso. Cambiado `landing/index.html`: logo PNG existente en ambas posiciones, también en pie de página para coherencia, y favicon de marca. Ajustados alineación, tamaño y texto alternativo sin modificar navegación, precios ni formulario.

Prueba real Chromium: imágenes cargadas y sin desbordamiento horizontal a 360/390/768/1024/1440px. Capturas: `capturas/landing-colibri-escritorio.png` y `capturas/landing-colibri-movil.png`. No desplegado; Claude debe publicar el directorio landing completo con assets en facturaporaqui.com. No cambia app.facturaporaqui.com ni backend.


## 10/10/2026 (Ecuador) — diseño de mejora de suscripción

Petición: que un suscriptor pueda mejorar pagando la diferencia incluso a un mes del vencimiento. Interpretación para coordinar: $35 IVA incluido de Plan 1000 a ilimitado y conservar fin del período; no nuevo año ni cálculo por días.

Cambios: `core/suscripciones/templates/suscripciones/plan.html` incorpora resumen con importe/vencimiento desde `o.mejora`, elimina aviso de terminar hoy para esa mejora y bloquea CTA mientras no exista cotización del backend; conserva formularios y renovación futura. `static/css/facturaporaqui.css`: tarjeta celeste, importe destacado y resumen adaptable con colores de marca. `tests/test_frontend_integracion.py`: pruebas de cotización presente/ausente y texto de vigencia. HANDOFF describe contrato exacto para Claude. No cambios backend, .env ni SRI.

Chromium local: planes, compañía y categorías sin overflow a 360/390/768/1024/1440px; login, cambio de empresas, gráficos y resultados anónimos, sin errores JS ni recursos fallidos. Captura `capturas/mejora-plan-pendiente.png`: estado real sin backend nuevo. La variante $35 está validada por renderizado con contexto ficticio; no implementa ni verifica cobro real. PayPhone local deshabilitado, no se paga ni se despliega. Pendiente integrar cálculo/activación backend y verificar el flujo completo con dobles de pago.

Pruebas finales: **61 aprobadas** (frontend y suscripciones). `git diff --check` sin incidencias.
## 11/10/2026 — Publicación de la landing `61f67f7` y de los ajustes `bf66b3e` (Claude)

### Qué se hizo
- Se leyeron HANDOFF.md y este informe, y se trajeron de GitHub `bf66b3e` y `61f67f7`, que descienden de `2199c14`. No tocan backend, modelos, migraciones, configuración ni `.env`. El escaneo de secretos de los 26 objetos nuevos salió limpio.
- **Corrección `1b6785d`:** el listado de usuarios (`/user/`) daba «DataTables warning: Ajax error». `User.toJSON()` incluía `email_verified_at`, una fecha y hora que `json.dumps` no sabe convertir. Afectaba a usuarios del registro propio con el correo confirmado, y también habría roto el listado de ventas, que incluye al vendedor. Ahora se envía como texto `AAAA-MM-DD`.
- **`deploy/scripts/publicar-landing.sh --publicar <ref>`** (`a6b77d5`) publica además `landing/assets/`, solo con imágenes, CSS, JS y fuentes; los `.md` de marca no se publican. Guarda antes una copia del sitio en `private/` y comprueba que cada recurso citado por `index.html` responde 200.
- Se ejecutaron las pruebas y se desplegó la app, luego se publicó la landing y se verificó en el dominio.

### Pruebas
- **PostgreSQL 16:** 169 aprobadas. **SQLite:** 166 aprobadas y 3 omitidas (solo PostgreSQL).
- Sin migraciones pendientes; `node --check static/js/graficos.js` correcto.

### Publicación
- **App:** `a6b77d5` en app.facturaporaqui.com desde el 11/10/2026 a las 02:16 UTC.
  - Respaldo `pre-20261011-021620-a6b77d52.dump`. Sin migraciones. Salud 200.
  - Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir`.
- **Landing:** `61f67f7` en facturaporaqui.com a las 02:17 UTC: `index.html` más `assets/brand/{isotipo,favicon}.png`.
  - Copia previa: `private/landing-antes-20261011021701.tar.gz`.
  - `index.html` servido idéntico (sha256 `8588d3fac9a8…`); los dos recursos responden 200.
- Tras el despliegue, PayPhone sigue configurado (Producción, Suprohosting) y los planes de las empresas no cambiaron.

### Verificación en el dominio
A través de Cloudflare, con empresas ficticias y sin pagos:

| Comprobación | Resultado |
|---|---|
| Landing, cabecera (1366/390/360) | Colibrí `assets/brand/isotipo.png` cargado, 48×48, alt «Colibrí de FacturaPorAquí» |
| Landing, panel ilustrativo | Colibrí cargado, 29×29, junto a «FacturaPorAquí / Mi empresa» |
| Landing, pie y favicon | Colibrí en el pie; favicon `assets/brand/favicon.png` |
| Landing, general | 200, sin desbordamiento, sin errores ni peticiones externas, `www` → dominio principal |
| Usuarios | Búsqueda AJAX 200 y sin aviso de DataTables (antes, error 500) |
| Panel | 2 gráficos; leyenda HTML con 10 botones; `aria-pressed` pasa a `false` al pulsar; ningún nombre cortado |
| Compañía | «Logotipo guardado.» sin ruta interna; claves sin `value`; en móvil, acciones sin posición fija |
| Recorrido completo (1366/390/360) | Login, selector con dos empresas, menú móvil con Escape, planes con $50/$85 (sin pulsar), cambio de empresa, retorno de PayPhone: 0 fallos, 0 errores de JavaScript, 309 estáticos |
| Datos reales | Los 10 usuarios se convierten a JSON sin error (1 con el correo confirmado) |

Para probar el selector se volvió a crear una membresía temporal de rol Consulta del propietario de OTRA-DEMO en DEMOSTRACIÓN, y se borró al terminar.

### Capturas
`publicado-landing-cabecera-escritorio.png`, `publicado-landing-panel-movil.png`, `publicado-app-usuarios-escritorio.png` y `publicado-app-panel-escritorio.png`. Son del dominio publicado, con empresas ficticias y sin credenciales.

### Pendientes
- **Codex:**
  - Optimizar `isotipo.png` y `favicon.png` (unos 500 KB cada uno y 1374×1145 para mostrarse a 48 px o menos).
  - Validar la barra de guardado de compañía en un teléfono físico.
- **Claude:** cifrar en la base las claves guardadas, permitir borrar una clave, respaldo diario de la base y etapa 3 (establecimientos, SRI en segundo plano, retenciones).

## 11/10/2026 — Mejora Plan 1000 → ilimitado por $35 y publicación de `67f353a` (Claude)

### Qué se hizo
- Se leyeron AGENTS.md, HANDOFF.md y este informe. Se integró `5579ded`, el diseño de mejora de Codex: escaneo de secretos limpio y avance directo desde `0fb08c5`.
- **Regla en el servidor:**
  - `PlanUpgrade` (Plan 1000 → ilimitado, 3500 centavos con IVA, al menos 1 mes de vigencia restante), editable en /plataforma/.
  - Con al menos un mes, `modo=inmediato` hacia ilimitado crea un pago `mode='mejora'` con `target_period`. El importe sale de la regla: 3043 + 457 de IVA.
  - Con menos de un mes, el cambio es una renovación al vencer; con el cupo agotado, un año nuevo a precio completo (regla D6).
- **Activación:**
  - Solo con PayPhone confirmado, y después de bloquear empresa y período y revalidar.
  - El período cambia de plan y de límite, pero conserva `starts_at`, `ends_at`, `documents_used` y las reservas.
  - Queda registro en `plan_original`, `upgraded_at` y `upgrade_payment`. No se crea otro período.
  - Si al volver de PayPhone la mejora ya no aplica (vencida, ya mejorada o regla desactivada), no se confirma y PayPhone reversa el cobro.
- **Contrato con el frontend:** `o.mejora.{disponible, amount_cents, ends_at}` más `renovacion` y `motivo`. Ajustes mínimos en `plan.html`, `retorno.html` y `pago.html`. El correo de pago aprobado indica «ilimitados hasta …».

### Archivos
- Modificados en `core/suscripciones/`: `models.py`, `servicios.py`, `views.py`, `admin.py` y las plantillas `plan.html`, `retorno.html` y `pago.html`.
- Nuevos: migraciones `0003_mejora_por_diferencia` y `0004_mejora_plan_1000_a_ilimitado`, y las pruebas `tests/test_mejora_plan.py` y `tests/test_zz_mejora_concurrencia_pg.py`.
- Commit `67f353a`.

### Pruebas (pagos simulados; ningún pago real)
- **PostgreSQL 16:** 188 aprobadas. **SQLite:** 184 aprobadas y 4 omitidas, solo PostgreSQL (3 de RLS y la de concurrencia).
- `tests/test_mejora_plan.py` (16):
  - más de un mes con cotización de $35 y el vencimiento;
  - un mes justo sí y un mes menos un día no;
  - pocos días, que no prepara el cobro;
  - plan vencido, que compra el año completo;
  - importe editable y regla desactivada;
  - cupo agotado con pocos días (renovación) y con más de un mes (mejora);
  - flujo completo: vencimiento, inicio y consumo conservados, un solo período e importes del navegador ignorados;
  - pago cancelado o rechazado;
  - confirmación duplicada, que aplica una vez;
  - segundo pago de mejora bloqueado y, si llega, no se confirma;
  - período vencido antes de confirmar;
  - importe distinto en PayPhone, que queda en revisión;
  - un vendedor no puede pagar;
  - una empresa no puede mejorar un período ajeno.
- `tests/test_zz_mejora_concurrencia_pg.py`: tres confirmaciones simultáneas en hilos (el mismo retorno dos veces y otra pestaña) dejan un pago aprobado y otro rechazado, una sola llamada a PayPhone y una sola mejora. Con los bloqueos quitados a propósito, la prueba falla (`['aprobado', 'aprobado']`).

### Publicación
- `67f353a` en app.facturaporaqui.com desde el 11/10/2026 a las 03:47 UTC.
- Migraciones 0003 y 0004 aplicadas. Respaldo `pre-20261011-034657-67f353a0.dump`. Salud 200.
- Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir`.
- Tras el despliegue: PayPhone configurado (Producción, Suprohosting). Regla «Plan 1000 → Plan ilimitado ($35.00)».
- Cotización por empresa: solo el cliente real con Plan 1000 la tiene disponible (vence el 10/10/2027); las empresas demo, no.

### Verificación en el dominio
Empresa ficticia OTRA-DEMO con un período Plan 1000 temporal, sin pago y anulado al terminar:

| Caso | Resultado |
|---|---|
| Con 199 días (1366 y 390 px) | Resumen «Paga solo la diferencia $35.00 IVA incluido», «Conservas tu vencimiento 28/04/2027» y «Esta mejora no renueva tu suscripción por otro año». Botón «Mejorar por $35.00» activo, más «Renovar desde…» y «Cambiar desde…». Sin desbordamiento |
| Checkout | Botón real → formulario oficial «Pagar a Suprohosting $35.00». **No se introdujo ningún dato ni se pagó** |
| Con 10 días (1366 y 390 px) | Resumen con el motivo «…Con menos de un mes de vigencia, el cambio a Plan ilimitado se hace como renovación». Solo «Renovar desde…» y «Cambiar desde…» |
| Limpieza | Período anulado; el pago de verificación pasó de «En PayPhone» a cancelado; ningún pago aprobado; OTRA-DEMO vuelve al plan gratuito |

Los avisos de consola (un 400 y `requestStorageAccess`) se producen dentro del checkout de PayPhone, que es externo; la aplicación no tuvo respuestas de error.

### Capturas
`publicado-mejora-disponible-escritorio.png`, `publicado-mejora-pocos-dias-escritorio.png` y `publicado-mejora-checkout-escritorio.png` (checkout vacío). Datos ficticios y sin credenciales.

### Pendientes
- **Propietaria:** confirmar la interpretación del plazo (mejora con un mes o más; renovación con menos). Si era al revés, basta con cambiar la regla.
- **Codex:** validar en el dominio el tema con la cotización real (sin pagar).
- **Claude:** cifrar las claves en la base, permitir borrar una clave guardada, respaldo diario de la base y etapa 3.

## 11/10/2026 — «Plan y pagos»: renovación con ilimitado, tarjetas equilibradas y mejora desde 30 días; publicado `af1f365` (Claude)

### Qué se hizo
1. **«Renovar con ilimitado por $85.00».** El botón de cambio al vencer hacia ilimitado usaba «Cambiar desde el…». Ahora el precio sale de `Plan.price_cents` en el servidor y debajo se muestra «Nuevo período anual: del {inicio} al {fin}. Es una renovación separada de la mejora.». El cambio de ilimitado a Plan 1000 al vencer conserva «Cambiar desde el…».
2. **Tarjetas equilibradas sin cambiar la marca:**
   - Recuadro `fp-current-summary` en la tarjeta del plan actual: vence el, días restantes, usados, disponibles, barra de consumo y aviso de la mejora cuando aplica.
   - Columnas `fp-plan-col`: lado a lado desde 1360 px, apiladas por debajo.
   - Resumen de la mejora en dos columnas desde 1360 px. Se mantienen colores, tipografía y estructura de Codex.
3. **Mejora por $35:**
   - Se conserva tal cual: mismo vencimiento y ningún año nuevo.
   - La vigencia mínima pasa de «1 mes» (`min_months`) a **30 días de calendario** (`min_days`, migración `0005`), contados con fechas locales de Ecuador. Así, un plan que vence en 30 días mejora todo el día.
   - `EstadoPlan.dias_restantes` usa la misma cuenta: el resumen superior decía 29 cuando quedaban 30.

### Archivos
- Modificados: `core/suscripciones/templates/suscripciones/plan.html`, `static/css/facturaporaqui.css`, `core/suscripciones/{models,servicios,views,admin}.py` y `tests/test_mejora_plan.py`.
- Nueva: la migración `0005_mejora_por_dias`.
- Commit `af1f365`.

### Medición del diseño
Vista previa local con SQLite y datos ficticios, y luego el dominio publicado. Empresa con Plan 1000 que vence en 30 días. «Vacío» es el espacio entre la lista de la tarjeta Plan 1000 y su primer bloque inferior:

| Ancho | Antes (67f353a) | Después (af1f365) |
|---|---|---|
| 360 / 390 | apiladas, 16 px | apiladas, 16 px |
| 768 | lado a lado, 480 px | apiladas, 40 px |
| 1024 | lado a lado, 507 px | apiladas, 40 px |
| 1280 | (sin medir) | apiladas, 40 px |
| 1366 | (sin medir) | lado a lado, 93 px, alturas iguales |
| 1440 | lado a lado, 415 px | lado a lado, 72 px, alturas iguales |
| 1920 | (sin medir) | lado a lado, 92 px |

Sin desbordamiento horizontal ni errores en ningún ancho, ni en la vista previa ni en el dominio.

### Pruebas (pagos simulados)
- **PostgreSQL 16:** 190 aprobadas. **SQLite:** 186 aprobadas y 4 omitidas.
- Nuevas o ajustadas en `tests/test_mejora_plan.py`:
  - 30 días justos sí y 29 no.
  - Cuenta por día de calendario: creado a las 10:00, sigue disponible a las 23:59 y deja de estarlo a las 00:01 del día siguiente.
  - **Escenario de 30 días de punta a punta:** $35 y vencimiento en la tarjeta; «Renovar con ilimitado por $85.00» y su nuevo período anual; el cuerpo enviado a PayPhone lleva `amount` 3500, `amountWithTax` 3043 y `tax` 457, aunque el navegador envíe otro importe; nada cambia antes de confirmar; la confirmación duplicada aplica una vez; un solo período; tras la mejora, la renovación anual sigue disponible aparte.

### Publicación y verificación
- `af1f365` en app.facturaporaqui.com desde el 11/10/2026 a las 18:40 UTC.
  - Migración `0005` aplicada. Respaldo `pre-20261011-183959-af1f365c.dump`. Salud 200.
  - Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir`.
- **Simulación en el servidor publicado,** en una transacción deshecha que no deja datos ni envía nada a PayPhone:
  - Cotización disponible: 3500, vence el 10/11/2026.
  - Prepare enviado: `{'amount': 3500, 'amountWithTax': 3043, 'tax': 457, 'amountWithoutTax': 0, 'currency': 'USD'}`.
  - Antes de confirmar, el plan sigue en Plan 1000. Después: aprobado, ilimitado, mismo vencimiento y 250 usados.
  - 1 llamada a Confirm y 1 mejora con el retorno duplicado; 1 período.
  - Renovación aparte: 10/11/2026 → 10/11/2027 por $85.00.
- **Dominio,** con OTRA-DEMO y un período Plan 1000 temporal de 30 días:
  - Tarjeta con «Paga solo la diferencia $35.00» y «Conservas tu vencimiento 10/11/2026».
  - Botones «Renovar desde el 10/11/2026», «Mejorar por $35.00» y «Renovar con ilimitado por $85.00».
  - El checkout oficial dice «Pagar a Suprohosting $35.00». **No se pagó.**
  - Tras abrir el checkout, el período seguía en Plan 1000 con un pago `mejora` de 3500 «redirigido».
  - Limpieza: período anulado, pago cancelado, ningún pago aprobado y OTRA-DEMO otra vez gratuita.

### Capturas
`publicado-plan-tarjetas-1440.png`, `publicado-plan-tarjetas-1024.png`, `publicado-plan-tarjetas-390.png` y `publicado-mejora-30dias-checkout.png` (checkout vacío). Datos ficticios y sin credenciales.

### Pendientes
- **Codex:** revisar el recuadro «Tu plan actual» y los puntos de corte (1360 px) con su criterio visual. Si cambia las clases, mantener los textos que comprueban las pruebas.
- **Claude:** asistente de configuración inicial de facturación (siguiente tarea), cifrado de claves, respaldo diario y etapa 3.

## 11/10/2026 — Asistente de configuración inicial de facturación: backend (Claude)

### Diagnóstico previo
- «Secuencia actual» (`Receipt.sequence`) era el **último número usado**: el siguiente se calculaba como +1 al crear el comprobante. Se creaba con **1**, así que la primera factura de una empresa nueva salía **000000002**. Además se leía sin bloqueo: dos ventas simultáneas podían recibir el mismo número.
- El registro asignaba **001-001** sin preguntar y no creaba secuencias. Una empresa recién registrada no podía crear ventas: «Receipt matching query does not exist».
- «Compañía» y «Comprobantes» guardaban por separado establecimiento, punto y ambiente, que podían contradecirse. La secuencia se editaba libremente, incluso hacia atrás, y no distinguía ambiente.

### Qué se hizo
- **Modelos** (`core/pos`, aislados por empresa y con seguridad por filas):
  - `Establishment` y `EmissionPoint`: códigos de tres dígitos con ceros iniciales (000 no vale), únicos por empresa y establecimiento, y un solo punto predeterminado por empresa.
  - `BillingSetup`: progreso del asistente.
  - `Receipt`: ahora es la secuencia por **empresa + ambiente + establecimiento + punto + tipo**, con restricción única, origen (`nuevo`, `otro_sistema`, `existente`) y confirmación.
- **Reserva atómica:** `Receipt.reservar_numero()` bloquea la fila dentro de la transacción de la venta, salta números ya registrados y nunca retrocede. Restricción única `(receipt, voucher_number)` en ventas y notas de crédito.
- **Asistente** `/configuracion/facturacion/` (app `core/configuracion`, solo Propietario y Administrador), en cinco pasos, con progreso guardado que se puede retomar:
  1. Datos de la empresa.
  2. Establecimientos y puntos, con confirmación de los códigos y sin asumir 001-001.
  3. Numeración independiente de facturas y notas de crédito, por ambiente: empezar en 000000001 con confirmación, o continuar desde otro sistema (último 001-002-000000125 → próximo 001-002-000000126). Nunca se reinicia ni retrocede lo ya usado.
  4. Firma `.p12`, validada con su clave y solo con plan, y ambiente (Producción con confirmación).
  5. Revisión del próximo número y confirmación.
- `/estado.json` para el frontend. Auditoría en `AuditLog`: `billing_setup_step`, `billing_point_change`, `billing_sequence_change` (con valor anterior, último y próximo) y `billing_setup_confirm`.
- **Emisión:**
  - Venta, nota de crédito y ticket exigen la configuración confirmada; la emisión electrónica, además, firma.
  - El error explica qué falta y enlaza al paso.
  - **El inventario no se bloquea.**
  - Aviso «Continuar configuración» para Propietario y Administrador con plan pagado.
  - Se mantienen los controles de plan, firma, permisos y la separación Pruebas/Producción.
- **Unificación:** «Compañía» muestra establecimiento, punto, dirección, ambiente y próximos números en solo lectura. «Comprobantes» es solo consulta, con último y próximo número, ambiente y estado; crear, editar o borrar lleva al paso 3.
- **Migraciones:**
  - `pos 0008`: esquema.
  - `pos 0009`: datos existentes sin cambiar ningún número. Las empresas que ya emitían quedan confirmadas; las demás, pendientes; a quien no tenía secuencias no se le asigna 001-001.
  - `pos 0010`: seguridad por filas de las tablas nuevas.
  - `pos 0011`: módulo de menú.
  - `tenancy 0005`: acciones de auditoría.
- El registro ya no asigna 001-001. `insert_test_data` (solo demostración) deja la configuración confirmada.

### Archivos
- **Nuevos:**
  - `core/configuracion/`: `servicios.py`, `forms.py`, `views.py`, `urls.py`, `context_processors.py` y las plantillas `asistente.html`, `_campos.html`, `_aviso.html` y `_resumen_compania.html`.
  - Migraciones `pos 0008–0011` y `tenancy 0005`.
  - `tests/test_configuracion_facturacion.py` y `tests/test_zz_secuencias_concurrencia_pg.py`.
- **Modificados:**
  - Modelos y vistas: `core/pos/models.py`, `core/pos/forms.py` y las vistas de venta, nota de crédito, comprobantes y compañía.
  - Plantillas y JS: `core/pos/templates/company/create.html`, `receipt/list.html`, `receipt/js/list.js`, `templates/vtc_body.html` y `templates/hzt_body.html`.
  - Configuración y comandos: `config/settings.py`, `config/urls.py`, `core/login/registro.py`, `core/tenancy/{models,roles}.py`, `start_installation`, `insert_test_data`, `tests/helpers.py` y `static/css/facturaporaqui.css` (bloque mínimo `.fp-config`).
- **Commits** `db184cd` y `5175401`.

### Pruebas (empresas ficticias; sin emitir documentos reales)
- **PostgreSQL 16:** 217 aprobadas. **SQLite:** 212 aprobadas y 5 omitidas (solo PostgreSQL).
- `tests/test_configuracion_facturacion.py`:
  - **Empresa nueva:** empieza en el paso 1 y conserva el inventario; la emisión se bloquea con el mensaje exacto y el enlace.
  - **Flujo completo:** establecimiento 002 con ceros conservados; sin confirmar los códigos no avanza; factura desde otro sistema (125 → 002-001-000000126); nota de crédito desde 000000001; Pruebas; confirmación. Después, emitir sin firma solo exige la firma en la emisión electrónica.
  - **Progreso:** se retoma donde quedó.
  - **Validaciones:** códigos `1`, `01`, `0001`, `000` y `A01` rechazados; establecimiento y punto duplicados; formatos y rangos del último número, incluido uno de otro punto; empezar en 1 exige confirmación.
  - **Empresa existente:** no se reinicia ni retrocede (980 → «no puede ser menor que 000000980»); `mantener` deja el próximo en 981; avanzar a 1200 queda auditado. Una secuencia usada solo avanza.
  - **Migración de datos:** no cambia los números; la empresa que ya emitía queda confirmada; la que no tenía secuencias no recibe 001-001.
  - **Independencia:** factura y nota de crédito tienen secuencias separadas, y Pruebas y Producción también. La reserva salta números ya usados y la base rechaza un número duplicado.
  - **Cambio a Producción:** exige confirmación, numeración propia y volver a confirmar; mientras tanto, la emisión se bloquea.
  - **Permisos:** Propietario y Administrador sí; Vendedor y Consulta reciben 403.
  - **Aislamiento:** una empresa no puede desactivar el punto de otra (404) ni lo ve en `estado.json`.
  - **Pantallas unificadas:** Comprobantes es solo consulta y muestra 003-002-000000042; Compañía no tiene los campos y muestra el resumen. El aviso aparece con plan pagado.
- `tests/test_zz_secuencias_concurrencia_pg.py` (PostgreSQL, transacciones reales, 8 hilos):
  - Seis emisiones simultáneas de la empresa A continúan desde 125 con 126–131, sin huecos ni repetidos, y la empresa B tiene sus propios 1–2.
  - **Comprobación por mutación:** sin el bloqueo de `reservar_numero()`, la prueba falla con `IntegrityError` (`venta_numero_unico_por_secuencia`). La restricción única es la segunda barrera.
- **Recorrido en la vista previa local** (SQLite, datos ficticios, Playwright a 1366 px), una empresa nueva de punta a punta por la interfaz:
  - El aviso «Para emitir facturas completa la configuración de facturación (paso 1).» lleva al paso 1.
  - Paso 2 sin confirmar: «Confirma que estos códigos son los que el SRI asignó a tu RUC.».
  - Paso 3: factura con último 002-001-000000125 y próximo 002-001-000000126; nota de crédito con próximo 002-001-000000001.
  - Paso 5: tabla de revisión y «Configuración confirmada.».
  - Compañía y Comprobantes muestran los mismos valores. 0 errores de JavaScript y 0 peticiones fallidas.

### Capturas
`configuracion-paso1.png` … `configuracion-paso5.png` y `configuracion-comprobantes-consulta.png`, de la vista previa local con datos ficticios. El estilo es mínimo; el diseño final es de Codex.

### Pendientes
- **Despliegue** en app.facturaporaqui.com: pendiente de autorización. Al desplegar, las tres empresas actuales quedan con la configuración pendiente y deben completar el asistente. El cliente real (empresa 6) no tenía secuencias y no podía registrar ventas; el asistente lo resuelve. No se cambia ninguna numeración existente.
- **Codex:** diseño del asistente, del aviso y de los resúmenes según el contrato de HANDOFF.md.
- **Futuro:** elegir el punto de emisión al vender (hoy se emite desde el punto predeterminado), retenciones (etapa 3) y cifrado de claves.

## 11/10/2026 — Publicación del asistente de configuración `d275331` (Claude)

### Publicación
- `bash deploy/scripts/desplegar.sh pruebas d275331` el 11/10/2026 a las 19:37 UTC.
- Migraciones aplicadas: `pos.0008_configuracion_facturacion`, `0009_configuracion_datos_existentes`, `0010_rls_configuracion`, `0011_modulo_configuracion` y `tenancy.0005_configuracion_facturacion`.
- Respaldo previo: `pre-20261011-193652-d2753319.dump`. Salud `/login/` → 200.
- **Revertir el código:** `bash deploy/scripts/desplegar.sh pruebas --revertir`.
- **Revertir también el esquema:** restaurar el volcado. La versión anterior no sabe rellenar las columnas nuevas de `pos_receipt` al crear comprobantes.

### Datos tras la migración (solo cifras)
- **Empresa 2:** 001-001 registrado y pendiente de confirmar. Factura 1051713 → próximo 001-001-001051714; nota de crédito 1016491; ticket 1. Origen «existente».
- **Empresa 3:** igual, con 990999, 2756341 y 1.
- **Empresa 6** (cliente real): sin establecimientos ni secuencias, y sin 001-001 asumido. Requisito pendiente: «configuración (paso 1)».
- **Módulo** «Configuración de facturación»: grupos Propietario y Administrador.

### Verificación en el dominio (sin emitir)
- **DEMOSTRACIÓN (ficticia), con la numeración en «mantener»:**
  - Aviso y bloqueo de la venta con el mensaje y el enlace al paso 1.
  - Pasos 1→5 completados por la interfaz; «Configuración confirmada.».
  - `estado.json`: completo, punto 001-001, próximos 001-001-001051714 (factura), 001-001-001016492 (nota de crédito) y 001-001-000000002 (ticket). Solo falta la firma.
  - El formulario de venta muestra 001-001-001051714 como próximo número.
  - Compañía muestra el resumen y 0 campos editables de establecimiento, punto o ambiente.
  - Comprobantes: tres filas «Confirmada». Crear una secuencia → 403 con el mensaje del paso 3; es el único 403 del recorrido y fue provocado a propósito.
- **Regresión completa** (`fpa-despliegue.mjs`) a 1366, 390 y 360 px:
  - Login, selector con dos empresas (membresía temporal borrada al terminar) y panel con 2 gráficos.
  - Menú móvil con Escape; compañía con 5 secciones, firma bloqueada sin plan y claves sin `value`.
  - Ventas redirige a planes en la empresa gratuita; cambio de empresa; retorno de PayPhone.
  - 0 fallos, 0 errores de JavaScript, 0 peticiones externas y 309 estáticos. Landing: 200 y `www` → dominio principal.

### Capturas
`publicado-configuracion-paso5.png` (revisión de DEMOSTRACIÓN en el dominio) y `publicado-configuracion-compania.png` (resumen de solo lectura en Compañía). Datos ficticios.

### Pendientes
- **Cliente real (empresa 6):** debe completar el asistente para poder vender y emitir. Sugerencia: avisarle que lo encontrará en «Configuración de facturación».
- **Codex:** diseño del asistente según el contrato de HANDOFF.md.


## 11/10/2026 — diseño del asistente de configuración (Codex)

### Base y alcance

Leídos AGENTS, HANDOFF (estado publicado d275331 y contrato) y este informe. Rama frontend/etapa3 actualizada por avance directo a 0b69f22. Solo presentación; no se modificaron backend, modelos, formularios Python, servicios, migraciones, SRI ni .env. No despliegue.

### Archivos y decisiones

- `core/configuracion/templates/configuracion/asistente.html`: colibrí Ingenioso, jerarquía de títulos y cinco tarjetas de progreso con estado escrito (no solo color), columnas adaptables, formularios de establecimiento/punto separados, numeración por documento y tabla de revisión con desplazamiento local accesible. Conservados nombres, acciones, CSRF, prefijos 01/04, ambiente y multipart.
- `_campos.html`: grupos de opciones con fieldset/legend, etiquetas asociadas, IDs distintos en los dos códigos del paso 2, errores invalid-feedback conservados, aria-invalid y asociaciones de ayuda en campos de texto. Mensajes del servidor sin reformular; clave sigue PasswordInput sin valor.
- `_aviso.html`: aviso Continuar configuración con icono y tema celeste.
- `_resumen_compania.html`: jerarquía visual para solo lectura, números legibles y enlace al asistente; misma fuente única.
- `static/css/facturaporaqui.css`: reemplazado bloque mínimo fp-config por diseño completo coral/celeste/azul oscuro; foco visible, controles amplios, móvil sin desbordamiento y texto de enlaces largo envuelto. Se corrigió el nowrap heredado que hacía desbordar el enlace de Compañía a 360 px.
- `static/js/configuracion.js`: vista previa de último + 1 para otro sistema, 1 para nuevo y dato del servidor para mantener. Oculta vista si formato/rango/punto no coincide. No cambia datos POST ni numeración real; servidor recalcula y valida.
- `core/pos/templates/receipt/list.html` y `core/pos/static/receipt/js/list.js`: introducción Solo consulta y acceso al asistente, estado con badge, valores de tabla escapados y ningún botón de creación/edición. Columnas Último número utilizado / Número del próximo documento conservadas.
- HANDOFF y este informe, capturas `asistente-diseno-*.png`.

### Validación ejecutada

Suite completa SQLite: **212 aprobadas, 5 omitidas** en 19,14 s; las omitidas necesitan PostgreSQL. Node --check para ambos JS y git diff --check sin incidencias.

Chromium/Playwright local (servidor 8013, configuración externa al repo con PayPhone vacío): empresa ficticia nueva sin numeración preparada con helpers, no insert_test_data; sesión real de propietario y pasos 1–5 completados por interfaz. No se ejercitó registro/correo en esta tarea. Establecimiento 002, punto 001; factura desde último 125, nota de crédito nueva, Pruebas, revisión y confirmación: próximo 002-001-000000126. Error por no confirmar códigos mostrado con texto del servidor; clave de firma vacía. No se subió firma ni se emitió comprobante ni se completó pago.

Pasos 1–5 y Comprobantes a 360/390/768/1024/1440 px sin overflow de documento; tabla ancha permanece en su contenedor. Vista previa y resumen Compañía a los mismos tamaños, sin overflow final. Vista previa 125 → 126 y rechazo visual de código de otro punto. Navegación Tab y orden del paso 2 comprobados, IDs sin duplicados en esa pantalla, controles radio/checkbox operados; contexto de navegador con movimiento reducido. Sin errores JS ni recursos HTTP fallidos en recorrido completo. Al incorporar el JS se reinició servidor local para descartar plantillas cacheadas antes de verificarlo.

Inspeccionadas capturas de escritorio del paso 1 y móvil del paso 3. Capturas de los cinco pasos en escritorio/móvil, error del paso 2, Comprobantes y Compañía. Datos ficticios únicamente; no claves ni tokens.

### Pendientes y publicación

No desplegado. Claude publica con respaldo y collectstatic, incluyendo el nuevo JS. No hacen falta cambios backend para el diseño. PostgreSQL no ejecutado por Codex; pruebas de concurrencia permanecen omitidas localmente. No prueba de lector de pantalla ni teléfono físico. Optimización de PNG y revisión adicional de Plan y pagos quedan como tareas opcionales posteriores; no se tocaron en esta entrega.


## 11/10/2026 — primera campaña de redes (Codex)

Entrega gráfica para captar empresas: 10 posts y 10 historias, sin videos ni publicación automática. Ubicación `redes/campana-01/` dentro de entregas/facturaporaqui. Se mantuvo colibrí Ingenioso, coral/celeste/azul oscuro y nombre FacturaPorAquí. Imágenes generadas con referencia al isotipo existente y a la primera pieza aprobada como línea visual, ilustraciones conceptuales sin datos de clientes.

Archivos: `posts/post-01.png` a `post-10.png`; `historias/historia-01.png` a `historia-10.png`; `GALERIA.html`, `README.md`, `TEXTOS-Y-PUBLICACION.md` (captions, hashtags, propuesta de 20 días, respuestas y medición), `contenidos.json` y `ARCHIVOS.json` con dimensiones/hash. Exportación ZIP adicional fuera del repo en `/workspace/facturaporaqui-redes-01.zip`, sin duplicar binarios en git.

Posts aproximadamente 4:5, 1122×1402 px; historias aproximadamente 9:16, 941×1672 px (historia 06 corregida: 940×1672). No se presentan como archivos vectoriales ni plantillas editables. La galería local permite abrir PNG individuales; revisar recorte en cada red al subir. Sticker de enlace de historias se agrega manualmente en la plataforma.

Mensajes: presentación, orden, asistente, planes $50/$85 anuales por empresa con IVA, numeración independiente, multiempresa, ventas/inventario/cuentas por cobrar, inventario gratuito con límites y CTA. No se anuncian retenciones disponibles, financiamiento confirmado, firma incluida en venta, testimonios inventados ni garantías de aprobación. Contacto: mensajes directos y facturaporaqui.com; teléfono y correo pendientes, sin inventarlos.

Verificación: inspección visual de las 20 piezas en galería. Se detectó y corrigió con herramienta de imagen el ejemplo de la historia 06 para mostrar Último 125 → Próximo 126 en lugar del mismo número. Comprobados textos de precios/IVA y marca. 20 PNG íntegros y manifiesto SHA256. Chromium: 20 imágenes cargadas en GALERIA.html, sin overflow a 360/390/768/1440. ZIP sin errores y 20 imágenes incluidas. No se necesitan pruebas Django para esta entrega de archivos gráficos; aplicación intacta.

No se publicaron redes, no se crearon campañas pagadas, no se desplegó la aplicación. Próxima fase: videos tras revisar estas piezas. La captación depende de publicación, atención a mensajes y medición; no se afirma haber conseguido clientes.

## 11/10/2026 — Publicación del diseño del asistente y corrección del paso 2: `3348345` (Claude)

### Qué se publicó
- **`7ae6eb7` (Codex):** diseño de los cinco pasos, colibrí, progreso, formularios y errores accesibles, aviso de cabecera, resumen de Compañía, Comprobantes de solo consulta y vista previa del próximo número (`static/js/configuracion.js`). Integrado por avance directo sobre `0b69f22`, sin reescribir historial.
- **`3348345` (Claude): corrección del paso 2.**
  - **Problema:** la propietaria no pudo escribir el punto de emisión del cliente real (empresa 6). El formulario «Agregar punto de emisión» tenía la lista de establecimientos vacía y el único error era «Este campo es obligatorio».
  - **Ahora, sin establecimientos:** el paso 2 muestra un único formulario, «Agrega tu establecimiento y su punto de emisión». Pide el código del establecimiento, el del punto (obligatorio), la dirección, el nombre y la descripción, e incluye el ejemplo «en 001-002-000000125 el establecimiento es 001 y el punto de emisión es 002». Crea ambos en una transacción y deja dos registros de auditoría.
  - **Con establecimientos:** vuelven las dos columnas. El código del punto en «Agregar establecimiento» pasa a ser opcional.
  - **Página abierta antes de publicar:** si se envía el formulario de punto sin establecimientos, vuelve al paso 2 con el aviso «Elige el establecimiento al que pertenece el punto. Si no aparece en la lista, agrégalo primero.».

### Revisión del commit de Codex
- No cambió vistas, formularios, servicios, modelos ni migraciones. Los `name`, `action`, prefijos 01/04, `?ambiente`, CSRF y multipart siguen intactos.
- Los IDs con sufijo (`-establecimiento`, `-punto`) evitan duplicados en el paso 2.
- `assets_body` está vacío en `vtc_body.html` y `hzt_body.html`, así que el script nuevo no desplaza otros recursos.
- Las variables CSS usadas (`--fp-ink`, `--fp-coral`, `--fp-border`, `--fp-muted`) están definidas.
- La lista de Comprobantes escapa los valores con `$.fn.dataTable.render.text()`, disponible en DataTables 1.10.25.
- La expresión regular de la vista previa acepta exactamente lo mismo que `interpretar_ultimo` (rango 1–999999998).
- **Observación** (pasada a Codex como opcional): la vista previa no conoce el mínimo de la numeración, y el servidor rechaza el retroceso al guardar.

### Pruebas
- PostgreSQL: **219 aprobadas**, incluidas las de concurrencia `test_zz_*`. SQLite: **214 aprobadas y 5 omitidas** (solo PostgreSQL).
- `check` sin problemas y sin migraciones pendientes. `node --check` de `configuracion.js` y `receipt/js/list.js`; `git diff --check` limpio.
- Pruebas nuevas:
  - `test_primer_establecimiento_pide_su_punto_en_el_mismo_formulario`: formulario conjunto, error sin punto, creación de 001-002 con auditoría, formulario de punto visible después y segundo establecimiento sin punto.
  - `test_punto_sin_establecimiento_explica_que_hacer`.
- `completar_pasos_1_y_2` ahora usa el formulario conjunto.

### Vista previa local (empresa ficticia nueva, `/root/capturas/fpa-asistente-v2.mjs`)
- **Recorrido completo:**
  - Paso 1: RUC inválido.
  - Paso 2: formulario conjunto sin punto suelto; error sin punto; «Establecimiento 001 y punto de emisión 001-002 agregados.»; duplicado; falta de confirmación de los códigos.
  - Paso 3: vista previa 125 → 001-002-000000126, «001-002-000000125» → …126; otro punto → vista oculta; nota de crédito nueva → …001. El servidor rechaza otro punto y la falta de confirmación.
  - Paso 4: clave vacía tipo `password`; Producción sin confirmar → error.
  - Paso 5: sin confirmar → error; luego «Configuración confirmada.» y el aviso desaparece.
- Comprobantes: tres filas, 0 acciones.
- Sin desbordes a 360/390/768/1024/1440 px en los cinco pasos, Comprobantes y Compañía. 0 errores de consola y 0 respuestas ≥ 400. Navegador con movimiento reducido.

### Verificación en app.facturaporaqui.com (`/root/capturas/fpa-asistente-dominio-v2.mjs`)
Empresas ficticias. **DEMOSTRACIÓN** solo recibió envíos que el servidor rechaza; **OTRA-DEMO**, solo lectura. Sin pagos ni comprobantes emitidos, y ninguna numeración real tocada.

| Comprobación | Resultado |
|---|---|
| Paso 1 | «Ingresa un RUC válido de 13 dígitos.» |
| Paso 2 | Dos columnas (ya tiene 001-001). Duplicado: «Ya existe el establecimiento 001.» Punto sin establecimiento: «Elige el establecimiento al que pertenece el punto…». Sin confirmar: «Confirma que estos códigos son los que el SRI asignó a tu RUC.» |
| Paso 3 | Vista previa inicial 001-001-001051714 («mantener»). Con «Ya emití en otro sistema» y 125: **001-001-000000126**. Al guardar, el servidor responde «El último número no puede ser menor que 001051713…». |
| Paso 4 | Clave de la firma `password`, vacía y habilitada (con plan). Producción sin confirmar: error del servidor. OTRA-DEMO (sin plan): archivo y clave **bloqueados**, vacíos, con «Podrás subir tu firma electrónica cuando actives un plan.» |
| Paso 5 | Revisión de las tres numeraciones. Sin confirmar: «Confirma que estos son los números con los que debes continuar.» |
| Continuar configuración | En DEMOSTRACIÓN, «…sube tu firma electrónica (.p12) y su clave (paso 4). Continuar configuración» lleva a `/paso/4/`. OTRA-DEMO no tiene aviso porque no tiene plan pagado (comportamiento previsto). |
| Compañía | Resumen «Tu configuración de emisión · Solo lectura»; 0 campos editables de establecimiento, punto, ambiente o dirección. |
| Comprobantes | Introducción «Solo consulta» y tres filas «Confirmada»; 0 acciones; `POST /pos/receipt/add/` → 403. |
| Numeración | `estado.json` igual antes y después: factura 001-001-001051714, nota de crédito 001-001-001016492, ticket 001-001-000000002. |
| Teclado | Tab recorre radios, último número, confirmación y botón. Foco visible en los campos (`solid 3px`); los botones conservan el anillo de Bootstrap. |
| Responsive | Sin desbordes a 360/390/768/1024/1440 px en los cinco pasos, Comprobantes, Compañía y Panel. |
| Estáticos y consola | `css/facturaporaqui.3daeeb4d2ac1.css`, `js/configuracion.17d19e760f65.js`, `receipt/js/list.d83ee4ba33c3.js` e `img/brand/isotipo.edbb16e2e7fb.png` → 200. 0 errores de consola y 0 respuestas ≥ 400. |

**Capturas** (`capturas/asistente-publicado-*.png`):
- primer punto (vista previa local);
- paso 2 con errores;
- paso 2 a 390 px;
- paso 3 con la vista previa 125;
- paso 4 sin plan;
- aviso;
- Comprobantes.

Muestran nombres de usuario de demostración; ninguna contraseña ni token.

### Incidencias
- Las contraseñas de las dos cuentas de demostración aparecieron en una salida de consola al leer el archivo de credenciales. Se cambiaron en el acto sin mostrarlas y siguen solo en `credenciales/demo-pruebas.txt`.

### Pendientes
- **Cliente real (empresa 6):** completar el asistente. Al publicar no tenía establecimientos ni puntos y ahora verá el formulario conjunto.
- **Opcionales (Codex):** pulir el formulario conjunto; aviso de mínimo en la vista previa; optimizar los PNG de marca; revisar Plan y pagos.
- **Teléfono físico:** probar la barra de guardado.


## 11/10/2026 (Ecuador) — formularios de aplicación responsive

Base sincronizada por avance directo a `9835933`; se leyó la publicación del asistente y corrección de Claude. Solo cambios frontend en frontend/etapa3; backend intacto. No desplegado.

Archivos:
- `templates/form.html`: clase de alcance fp-responsive-form en la base de formularios, sin alterar action, names, CSRF o enctype.
- `static/css/facturaporaqui.css`: límites de ancho, columnas en móvil, Select2 con textos largos, TouchSpin, botones de acción apilados, totales y modales. Líneas de documento como fichas en móvil, tabla normal en escritorio; cabeceras preservadas ocultas visualmente. No se fuerza ocultar overflow del documento para disimular problemas.
- `static/js/facturaporaqui.js`: etiquetas de celdas tomadas de encabezados y actualizadas al redibujar DataTables, labels asociados e inputs con nombre accesible. Conserva celdas/inputs originales y eventos. Eliminar producto permite teclado sin alterar lógica de eliminación. Observador limitado a frmForm y cambios childList, sin bucle por atributos.
- `core/pos/templates/sale/admin/create.html`: guardia de selección inicial para no pasar `{}` a Select2 si una empresa nueva no tiene Consumidor final. El error reproducido fue reading toString of undefined; corregido en presentación, sin crear cliente automáticamente ni modificar backend.
- AGENTS documenta la convención; HANDOFF y este informe; 9 capturas formulario-*.png (venta, compra, nota de crédito y producto en escritorio/móvil, y modal cliente móvil).

Validación Chromium con usuario/empresa ficticios locales, plan ilimitado asignado por helper y configuración confirmada, sin firma: 12 rutas de creación HTTP200 con formulario real: ventas, compras, notas de crédito, clientes, productos, proveedores, categorías, gastos, tipos de gasto, promociones, cuentas por pagar y por cobrar. Las 12 sin overflow de documento a 360/390/768/1024/1440px. Venta con producto ficticio inyectado solo en memoria del navegador para ejercer el mismo addProduct/listProducts: $25 con IVA15%; cantidad1 total28,75 y cantidad2 total57,50. Edición y valor conservados tras resize; no se envió venta. Modal Crear cliente abierto por interfaz a390 sin overflow; no guardado. Movimiento reducido activado, Tab verificado, nuevas etiquetas y controles operables. Sin errores JS al final. Captura de venta móvil inspeccionada: fichas, totales y botones apilados, sin desplazamiento horizontal. El aviso de firma pendiente y validación de efectivo continúan visibles.

Node --check y git diff --check sin incidencias. Suite SQLite ejecutada completa; resultado final registrado debajo. No pagos ni emisiones reales, modelos/migraciones/vistas/API/.env/SRI sin cambios. No pruebas de dispositivo físico, lector de pantalla ni de guardado. Formularios de compras/notas de crédito probados en su estado inicial; solo venta ejercitada con línea y cálculo. Las tablas de búsqueda en modales conservan desplazamiento local cuando sea necesario.

Resultado final SQLite: **214 aprobadas, 5 omitidas** exclusivas de PostgreSQL, en 19,78 s.


## 13/10/2026 (Ecuador) — márgenes de piezas de redes

Petición: margen 60 px arriba/abajo/izquierda/derecha y actualización en entregas/facturaporaqui/redes. Se corrigieron las 20 imágenes mediante edición de imagen con referencia a cada original; se reemplazaron `campana-01/posts/post-01…10.png` y `historias/historia-01…10.png`, manteniendo contenidos comerciales y marca. La zona segura se implementó como mínimo de 60 px para contenido; algunas composiciones dejan más espacio, no una banda matemáticamente idéntica de exactamente 60 px.

Actualizados GALERIA.html (alternar imagen completa/miniatura orientativa3:4), README.md y ARCHIVOS.json (dimensiones, hash y margen de contenido oscuro medido). Regenerados ZIP locales `/workspace/facturaporaqui-redes-01.zip` y `/workspace/facturaporaqui-redes-01-margen60.zip`; el directorio temporal de preparación propio se retiró después de copiar, sin duplicar campaña. HANDOFF y AGENTS registran la regla.

Validación: inspección visual de 20 PNG en pares; textos legibles, planes50/85 al año con IVA, numeración Último125/Próximo126 conservada. Lectura de píxeles confirma contenido oscuro (luminancia<140, indicador de texto/marca, no OCR) a >=60px de los cuatro bordes en todas. Esa medición se complementa con revisión visual; no certifica una banda uniforme de fondo. Chromium: 20 imágenes cargadas y alternancia de vista grid correcta. ZIP íntegros con20 PNG. No pruebas Django necesarias: no código de aplicación modificado. No se afirma verificación directa en una cuenta Instagram; revisar su vista previa antes de publicar. Sin publicación externa ni despliegue.
## 12/10/2026 — Facturación electrónica: firma nativa y Etapa A, publicado `e3a2932` (Claude)

### Contexto
- La propietaria reportó que el cliente real (empresa 6, Producción) no podía emitir: `java.lang.NoClassDefFoundError: es/mityc/javasign/...` en la etapa «Firma del XML».
- No se guardó ninguna venta: el número 001-002-000000271 sigue libre y el SRI nunca recibió nada.
- La propietaria pidió revisar cada componente frente a la normativa ecuatoriana. Se hizo con tres revisiones paralelas: XML e impuestos, flujo de envío, y RIDE, correo y NC. Resultado en `AUDITORIA-SRI-2026-10.md`.

### Qué se publicó
- **`fd656a1`:** firma XAdES-BES nativa (`core/pos/utilities/firma.py`).
- **`e3a2932`:** Etapa A, emisión en dos fases y reglas del SRI en el servidor. El detalle está en la auditoría y en HANDOFF.
- Migración `pos 0012`. Respaldo `pre-20261012-022817-e3a29324.dump`. Temporizador `facturaporaqui-sri@pruebas.timer`.

### Pruebas
- PostgreSQL **257**; SQLite **252 + 5** solo PostgreSQL; `makemigrations --check` sin cambios; `node --check` de los JS modificados.
- Nuevas:
  - `test_firma_sri.py`: estructura, verificación independiente, alteración, clave incorrecta, firma vencida o aún no vigente.
  - `test_fechas_sri.py`.
  - `test_emision_sri.py`, con 28 casos y SRI simulado:
    - autorización inmediata;
    - en proceso sin reutilizar el número;
    - sin respuesta → reenvío del mismo XML;
    - devuelta → reenvío con la misma clave;
    - 45, no autorizado, tarea periódica;
    - firma fallida o sin cupo → la venta se deshace;
    - sin RUC del proveedor;
    - fecha forzada;
    - apóstrofos;
    - listados JSON;
    - borrado;
    - ticket;
    - consumidor final y tope;
    - identificación;
    - comprador de otra empresa;
    - NC (precio de la factura, saldo, duplicado, permiso, consumidor final);
    - correo con XML y RIDE.
- Controles de mutación:
  - Regenerar la clave en un reintento hace fallar la prueba de devuelta.
  - signxml rechaza un XML firmado y luego alterado (InvalidDigest).

### Verificación contra el SRI (ambiente de PRUEBAS)
- **Firma sola:** RECIBIDA → AUTORIZADO.
- **Con el código publicado, de punta a punta**, en una transacción deshecha y sin correos:
  - factura → AUTORIZADO, con XML autorizado y RIDE;
  - nota de crédito → AUTORIZADO, y la factura queda «Anulado»;
  - NC sobre consumidor final → NO AUTORIZADO, error 69.
- Al final no quedó nada en la base y se borraron los 4 archivos temporales.

### Verificación en el dominio (DEMOSTRACIÓN, PRUEBAS, sin firma)
- Los listados de ventas y notas responden 200; el JSON no incluye el XML firmado.
- El formulario ofrece FACTURA y TICKET (en PRUEBAS), con la factura electrónica fija y el consumidor final preseleccionado.
- Emitir sin firma da «…sube tu firma electrónica (.p12)… paso 4» y no se guarda la venta (0 → 0).
- 0 errores de consola y 0 respuestas ≥ 400.

### Incidencias de Claude
- **Contraseñas de demostración:** aparecieron en una salida de consola y se rotaron sin mostrarlas.
- **`/dev/null` del hipervisor:** se borró por un comando erróneo y se restauró en segundos.
- **Permisos del entorno publicado:** un `chmod -R go-rwx` sobre un entorno de verificación creado con `uv` quitó la lectura de grupo a 41 archivos compartidos por enlaces duros con los entornos publicados (`cffi`, `pycparser`, `certifi`).
  - Se restauró en unos 15 minutos, antes de que se reiniciara algún worker; el sitio no cayó.
  - Lección: nunca hacer `chmod -R` sobre un entorno de `uv`.
- **Falsa alarma de zona horaria:** Claude afirmó que las facturas saldrían con la fecha del día siguiente. No era así: Django fija `TZ=America/Guayaquil` en el proceso. Se corrigió el aviso y la clave y la fecha salen ahora del mismo valor.

### Pendientes
- **`FPA_RUC_PROVEEDOR`:** RUC de Suprohosting y registro como proveedor en su RUC. Bloquea la emisión en Producción hasta que se configure.
- Etapas B y C de la auditoría.
- Publicar `3fc3104` (Codex, formularios móviles), ya fusionado en la rama.
- Prueba en teléfono físico.


## 13/10/2026 — Publicado `f787684` (Claude)
- **Diagnóstico de «no puedo facturar desde el RUC de Fernando»:** la empresa 6 cumple plan, cupo, firma y numeración; el único bloqueo es `FPA_RUC_PROVEEDOR` vacío (decisión pendiente de la propietaria). Se reprodujo el mensaje exacto.
- **Corrección:** 12 vistas de edición (clientes, productos, categorías, proveedores, tipos de gasto, gastos, promociones, comprobantes, usuarios, grupos, módulos, tipos de módulo) daban 500 sin sesión.
- **Prueba nueva:** `tests/test_vistas_sin_sesion.py`, que falla con el código anterior.
- **Suites:** PostgreSQL 259; SQLite 254 + 5 solo PostgreSQL.
- **Publicado con `f787684`:** los formularios móviles de Codex (`3fc3104`).
- **Verificación:** sin sesión → 302 al login; recorrido de DEMOSTRACIÓN sin errores de consola ni respuestas ≥ 400; temporizador del SRI activo.


## 13/10/2026 — corrección del marco de redes

El usuario rechazó el marco visible del ajuste anterior. Se editaron las 20 imágenes con la herramienta de imagen para eliminar el panel interior/banda y extender el fondo y formas decorativas hasta los bordes. Texto, marca y CTA permanecen dentro de la zona segura invisible de60px. Se sustituyeron los mismos PNG en `redes/campana-01/posts` e `historias`; se conservaron captions y nombres de archivo.

Actualizados README, ARCHIVOS.json, AGENTS y HANDOFF. ZIP locales regenerados, incluido `/workspace/facturaporaqui-redes-01-sin-marco.zip`. Inspección visual de las20 piezas en galería: sin panel, precios50/85 y textos completos, ejemplo125→126 conservado. Chromium cargó las20 imágenes. ZIP íntegros con20 PNG. La prueba anterior basada en todos los píxeles oscuros ya no es adecuada: la decoración puede extenderse al borde (historia02 tiene papeles oscuros al extremo). El manifiesto ahora registra el criterio de zona segura y revisión visual, no un margen automático de todos los píxeles. No se certifica geometría idéntica entre versiones generadas; textos/marca revisados dentro de la zona solicitada.

Sin publicación externa, sin cambios de app/backend y sin despliegue.


## 14/10/2026 — diseño y campaña Plan Multiempresa (Codex)

Leídos AGENTS, contrato/estado Multiempresa publicado c2eb08e y este informe. Base frontend/etapa3 a4e8415. Todo trabajo propio en esa rama; no se reescribió historial ni se desplegó.

Archivos:
- landing/index.html: diseño final3 tarjetas, Multiempresa azul oscuro/celeste/coral, Unlimited claro. Precio, etiquetas Para 1 RUC / Hasta 10 RUC distintos, textos incluida retenciones, data-plan y opciones de formulario conservados. Tres columnas escritorio, dos más una tarjeta completa en tablet, una móvil.
- core/suscripciones/templates/suscripciones/plan.html: contenedor fp-plan-options para distribución de tres planes; contratos y condiciones o.es_mejora/o.cambio_multiempresa/cubierta preservados.
- static/css/facturaporaqui.css: tema de fp-plan-multiempresa, fp-plan-cubierta, fp-plan-multi; página empresas, tabla como fichas móvil, formularios adaptables y foco.
- core/suscripciones/templates/suscripciones/empresas.html: colibrí, jerarquía de estado/cupos, tabla de RUC y tarjetas de agregar/vincular, campos dos columnas o una móvil. Names, accion=nueva|vincular, empresa y CSRF intactos; errores del servidor conservados, incluyendo errores generales del formulario.
- templates/vtc_sidebar.html y core/tenancy/templates/tenancy/company_switcher.html: acceso Empresas del plan para titular con plan Multiempresa vigente y permisos, usando contexto existente. Empresa adicional no recibe ese acceso; el backend mantiene permisos reales y rol propietario.
- redes/plan-multiempresa: posts/post-01…02.png e historias/historia-01…02.png, TEXTOS-Y-PUBLICACION.md, GALERIA.html, ARCHIVOS.json. Oferta $199 al año, IVA incluido, hasta 10 RUCtotales incluida titular, documentos ilimitados. Sin nuevas funciones prometidas. Edición de historia2 para ampliar margen de titular. ZIP `/workspace/facturaporaqui-plan-multiempresa.zip` fuera del repo, verificado.
- HANDOFF y este informe. Capturas multi-*.png con datos ficticios.

Pruebas: Python 3.12 con requirements/base.txt/dev.txt instalados con --require-hashes, SQLite: **270 aprobadas, 5 omitidas** exclusivas PostgreSQL, 39,27 s. git diff --check limpio. Los textos/clases que verifican tests se conservaron, sin necesidad de cambiar pruebas. Sin modelos, servicios, vistas ni migraciones modificados.

Chromium/Playwright local con movimiento reducido: 1440/1024/768/390/360px, sin overflow de documento en landing, Plan y pagos, Empresas del plan y cubierta. Data-plan/opción multiempresa comprobados, no submit de lead. Login/selector reales con titular/adicional/vinculable ficticias. Resumen 2 de 10, menú visible titular, adicional con aviso y sin tarjetas ni acceso de gestión. RUC inválido enviado y rechazado; error exacto visible. Tab RUC → razón social. No se creó/vinculó empresa mediante esta prueba; tests backend existentes cubren esas acciones. Sin errores JS ni respuestas HTTP >= 400 en recorrido. PayPhone deshabilitado localmente; no compras ni emisión SRI.

Inspección visual: tarjetas de landing con texto y alcance legibles, app Multiempresa contrastado, cuatro PNG comerciales revisados y sin marco. Dimensiones: posts 1122×1402, historias 941×1672 aprox; imágenes conceptuales, no datos reales. Capturas de landing/planes/empresas/cubierta en escritorio/móvil, error móvil y tarjetas de landing. En prueba adicional con animación normal la captura inicial se hizo antes de completar reveal; se esperó visibilidad y se verificó opacidad 1. Prueba principal con movimiento reducido.

Configuración de desarrollo reutilizable guardada con herramienta de onboarding: install_script y start_skill, estado saved, no publicación ejecutada. Entorno de navegador usa settings_frontend externo al repo y SQLite; no .env de producción. Para activar configuración cloud nueva se revisa/guarda en ajustes de entorno y se publica ese entorno; no es despliegue de app.

Pendientes: revisión/publicación por Claude con respaldo; PostgreSQL, teléfono físico y lector de pantalla no probados por Codex. No publicación en redes ni publicidad pagada. No requisitos nuevos de backend.


## 14/10/2026 — portada de Facebook

Creada redes/portadas/facebook-facturaporaqui.png y guía README. Banner2035×773 px, colibrí Ingenioso, paleta coral/celeste/azul oscuro, lema y dominio. Fondo continuo, sin marco, sin precios; zona de perfil inferior izquierda despejada. Generado con referencia al isotipo, inspeccionado visualmente y PNG verificado. No cuenta de Facebook comprobada ni publicación automática; revisar recortes en plataforma al subir. Sin cambios de app.


## 14/10/2026 — tabla de precios inspirada en la referencia

Se leyó el texto adjunto (jQuery, selector mensual/anual, beneficios móviles y Odometer) como referencia de diseño, sin ejecutar ni copiar dependencias de terceros. La propietaria mantiene cobro anual y marca. Base frontend/etapa3 0bede49.

Archivos:
- `landing/index.html`: tarjetas con zonas claras de cabecera, precio anual, alcance RUC, CTA y beneficios en filas con checks. Se agregan beneficios disponibles: clientes/ventas/cuentas por cobrar, inventario/reportes y configuración guiada. Se conservan precios $50/$85/$199, data-plan, opciones de lead, retenciones y alcance 1 RUC / hasta 10 RUC. Aviso de pago anual con IVA. Sin selector mensual ni descuento inventado.
- `core/suscripciones/templates/suscripciones/plan.html`: aviso de planes anuales, beneficios con details/summary nativos, carga del JS. Campos y formularios de pago intactos; no se promete un nuevo año en una mejora de período existente.
- `static/css/facturaporaqui.css`: filas de beneficios, foco, checks y contraste en Multiempresa.
- `static/js/precios.js` y `landing/assets/pricing.js`: implementación compartida sin bibliotecas nuevas. Entrada de tarjetas con Web Animations/IntersectionObserver, una vez al entrar en pantalla; si movimiento reducido está activo no anima. Selección visual del plan en landing conservando el handler existente que selecciona la opción del formulario. No cambia importe ni datos de pago. Sin JS el contenido sigue visible y los details funcionan nativamente.
- HANDOFF y este informe; capturas `precios-*.png`.

Validación: suite SQLite **270 aprobadas y 5 omitidas** (exclusivas de PostgreSQL), 41,81 s. Node --check y git diff --check correctos. Chromium: landing, planes de titular, empresas y adicional cubierta a 1440/1024/768/390/360 px, sin overflow; contratos de data-plan y lead, errores de RUC y menú/cobertura intactos. Sin errores JS ni recursos fallidos.

Prueba adicional: con movimiento normal, 3 animaciones activas al entrar en precios; con movimiento reducido, 0. Details abierto/cerrado con Enter; CTA Multiempresa añade selección visual y mantiene el valor multiempresa del formulario. Precio199 visible y sin mutación. Capturas de comparación con ambas preferencias y vista previa revisada visualmente: paleta sin verde del ejemplo, texto legible y beneficios comparables. PayPhone deshabilitado localmente; no se completó pago ni se emitió documento.

Sin modificaciones de vistas, servicios, modelos, migraciones o .env. No despliegue ni publicación externa. Claude debe incluir el nuevo JS al publicar landing y ejecutar collectstatic en app. Móvil físico y PostgreSQL no probados en esta revisión.

## 14/10/2026 — tabla de precios publicada (Claude)

- **Commit desplegado:** `3e25b3e` en la app (19:47 UTC, respaldo `pre-20261014-194656-3e25b3e3.dump`) y en la landing (`assets/pricing.js` → 200). Incluye `14d0090` de Codex, fusionado en `78b9e95`.
- **Pruebas:** PostgreSQL 296 aprobadas; SQLite 291 aprobadas y 5 omitidas. `makemigrations --check` sin cambios y `node --check static/js/precios.js` correcto.
- **Dominio:** se verificaron los precios anuales, los tres alcances, los desplegables con teclado, la selección del formulario (`multiempresa`) y las animaciones (3 con movimiento normal, 0 con movimiento reducido). Sin desborde a 1440, 1024, 390 y 360 px, sin errores JS y sin respuestas ≥ 400.
- **Empresa cubierta:** sin formularios de pago (verificado en el servidor dentro de una transacción deshecha).
- **Capturas:** `/root/capturas/salida-precios/` en VM101 (landing-1440/1024/390/360, app-1366/390).
- **Cambio adicional de Claude:** el cupo en Plan y pagos dice «facturas, notas de crédito y retenciones».
- No se completaron pagos.
