# Handoff compartido — frontend

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
- [ ] Leer implementación vigente de Claude cuando esté disponible, incluidos templates y contratos de planes/PayPhone.
- [ ] Adaptar y validar frontend sobre esa implementación, conservando aislamiento y comportamiento de pagos.

## Notas entre agentes
Claude: subir o indicar el commit/rama que contiene multiempresa y PayPhone. Registrar las rutas exactas ya implementadas para planes, suscripción, creación de pago, retorno y consulta de estado; nombres de campos, importes, moneda, fechas y cupos que entregan. No inventar endpoints ni compartir tokens. Codex queda limitado a templates, CSS, JavaScript y documentación en frontend/etapa3; modelos, migraciones, vistas de API, SRI y .env quedan fuera de alcance.
