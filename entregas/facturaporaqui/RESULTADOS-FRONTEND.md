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
