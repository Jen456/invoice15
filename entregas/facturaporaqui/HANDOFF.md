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
