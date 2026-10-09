# Landing pública — FacturaPorAquí

Sitio estático independiente de Django. Publicar `index.html` en **https://facturaporaqui.com**. La aplicación multiempresa permanece en **https://app.facturaporaqui.com**; el enlace de acceso apunta allí.

Sin compilación ni dependencias externas: HTML, CSS y JavaScript incluidos. Incluye diseño responsive, animaciones con movimiento reducido y planes anuales por empresa de $50 por 1000 documentos y $85 ilimitado, ambos con IVA incluido.

## Pendientes antes de captar solicitudes reales

El propietario dejó pendientes WhatsApp y correo. El formulario está explícitamente marcado como demostración y no envía ni guarda datos. No inventar contactos ni mostrar un envío exitoso. Para activar captación: configurar destino, protección contra abuso, aviso de privacidad y consentimiento. La sección financiera describe conexión con entidades, no préstamos propios ni aprobación garantizada. Confirmar entidades y condiciones antes de habilitar solicitudes.

## Instrucciones para Claude

1. Actualizar el repositorio preservando la implementación multiempresa desplegada y los datos existentes. Incorporar únicamente la carpeta `landing/`; no sustituir la aplicación con una versión anterior.
2. Servir esta carpeta en un sitio/vhost independiente para `facturaporaqui.com` y definir el comportamiento de `www.facturaporaqui.com` (redirección al dominio principal).
3. Mantener `app.facturaporaqui.com` apuntando al servicio Django actual. No cambiar sus rutas, base de datos, media o autenticación.
4. Configurar DNS, certificado del servidor y Cloudflare Full (strict). Usar los mecanismos compatibles con Hestia y conservar correo y otros registros existentes.
5. Verificar HTTPS de ambos dominios, enlace de login, vista móvil y autenticación de la aplicación después del despliegue. No afirmar que se captan solicitudes mientras el formulario siga siendo demostrativo.
6. La carpeta `static/lib` de la aplicación es un pendiente separado: esta landing no la necesita y este cambio no la resuelve.

Las mejoras locales del frontend Django no se incluyen en el commit de esta landing y deben adaptarse al código multiempresa vigente en una tarea separada.
