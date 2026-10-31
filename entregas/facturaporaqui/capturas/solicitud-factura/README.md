# Solicitud de factura — aviso de éxito

31/10/2026. Solo datos ficticios: empresa de prueba, pago aprobado creado localmente y correo `example.com`. No es una captura de producción ni se completó un pago PayPhone.

- [360 px](exito-360.webp)
- [768 px](exito-768.webp)
- [1360 px](exito-1360.webp)

Origen: HTML real de la respuesta del cliente Django a POST → redirección → GET. Backend actual con las plantillas de `98cfa20` más el parche de mensajes. Chromium abre ese HTML en un servidor local que solo permite consultas; se emplea el CSS de marca de `98cfa20`. No se modificó el contenido para las capturas. El aviso de configuración corresponde a la empresa ficticia.

[Verificación](verificacion.json): 12 combinaciones, layouts vertical y horizontal a 360/390/768/1024/1360/1440 px. Mensaje de éxito único, `role=status`, sin modal SweetAlert de error, sin desbordes ni errores JS/HTTP. Movimiento reducido. WebP de 23–67 KB.

El guardado se verificó por separado con SQLite: solicitud registrada, pago aprobado e importe conservados; correo inválido no crea solicitud ni anuncia éxito. Correos exclusivamente en memoria. Las dos pruebas de éxito fallan con las plantillas antiguas; con el parche pasan las 11 pruebas de solicitud y mensajes. No se probó PostgreSQL, teléfono físico ni el servidor publicado.

[Diagnóstico y parche para Claude](../../correcciones/solicitud-factura/README.md).
