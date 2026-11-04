# Diseño de formularios y contabilidad — entrega paralela

## Entrega subida a GitHub

Código y evidencia: `eec8d8751d004096fb832bdfae685b01c0038e62`, subido y verificado con `git ls-remote` en `frontend/experiencia-contable-v9`. Pruebas: 11 Django SQLite, 2 Node y 87 comprobaciones de navegador aprobadas; 31 capturas y guía PDF de dos páginas. Sin despliegue.

La apertura del PR queda pendiente: Git permite push, pero `api.github.com` responde `Forbidden`. Se guardó una propuesta de acceso **solo a ese dominio** en la configuración del entorno; todavía no se ha aplicado al runtime. No se solicitaron ni leyeron credenciales. Base prevista del PR: `codex/facturacion-captura-agil-20261103`. Descripción lista en `PR-FRONTEND-V9.md`.

Comparación para abrir la revisión: https://github.com/Jen456/facturacion15/compare/codex/facturacion-captura-agil-20261103...frontend/experiencia-contable-v9?expand=1

Pendientes externos: adjuntar el Word v9 y acordar los contratos contables con Claude. La entrega no afirma haber completado ninguno de esos dos requisitos.

Base: `Jen456/facturacion15`, PR #1, `817c5be`. Rama de diseño: `frontend/experiencia-contable-v9`. Este repositorio es distinto de `Jen456/invoice15`; no se fusiona su backend ni se sustituye su candidata `baadb8b`.

## Alcance y propiedad de archivos

- Codex: `core/pos/templates/sale/admin/create.html`, CSS y JavaScript de presentación de esa pantalla; `static/css/facturaporaqui.css`; `static/img/brand/isotipo-pie.png`; prototipos, pruebas de interfaz y documentación de esta entrega.
- Cambios compartidos mínimos: idioma y zoom en `templates/base.html`; bloque opcional de clase en `templates/form.html`.
- Claude: modelos, servicios, vistas, rutas, formularios Python, permisos, migraciones, cálculos contables y contratos API. Codex no modifica esos archivos.
- Esta delimitación se entrega para coordinación; no constituye una confirmación recibida de Claude. Integrar la rama sobre el PR #1, no sobre el backend distinto de invoice15.

## Documento y contratos pendientes

El Word `Facturaporaqui_Apuntes_y_decisiones.docx`, versión 9, no estaba adjunto ni disponible en el repositorio al iniciar. Se pidió a la propietaria. La entrega sigue sus requisitos escritos; no afirma haber revisado el Word.

El contrato verificable de facturación está en `docs/facturacion-usabilidad.md`, `core/pos/sale_workflow.py` y las vistas de este PR. No hay API de plan de cuentas, asientos, cierre contable o verificación de puntos en esta rama. Sus pantallas serán propuestas identificadas, sin rutas inventadas ni guardados ficticios.

## Diferencias que Claude debe resolver antes de integrar en producción

1. Este PR permite nota/archivo opcionales y conserva `cash/change` históricos sin pedirlos en la interfaz. La candidata de invoice15 exige efectivo/cambio y respaldo para otros medios. La nueva instrucción de la propietaria pide el comportamiento del PR; cambiar el otro backend requiere su contrato, no ocultar campos obligatorios.
2. Aquí `payment_note` y el nombre del archivo pasan a `additional_info`; las condiciones de pago pueden aparecer en el XML. No prometer notas internas ni privacidad de su texto. Claude debe definir el almacenamiento interno si ese es el destino acordado en el Word.
3. La nota o el archivo no registra ni confirma un cobro. El estado real debe venir de la API. No inferir pago a partir de `payment_type`, una promesa o un adjunto.
4. El máximo interno de tres puntos necesita validación de servidor y estado de verificación con evidencia. No confundir punto con sucursal. Esta rama no contiene ese contrato.
5. No hay confirmación de importación del Excel de NEXALLTI. El piloto se representa como configuración de plan de cuentas reducido pendiente de importación; no es un cambio de tarifa de suscripción.

Sin despliegue, emisiones, pagos, correo ni datos reales. Pruebas y evidencias se registran en `RESULTADOS-FRONTEND.md`.
