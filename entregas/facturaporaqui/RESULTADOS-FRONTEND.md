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
