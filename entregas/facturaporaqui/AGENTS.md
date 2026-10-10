# Convenciones frontend de FacturaPorAquí

- Mantener el branding: colibrí Ingenioso, coral #CA462C, celeste #44BADD, azul oscuro #163B50 y azul claro #E5F1F6.
- Usar `static/css/facturaporaqui.css` para el tema compartido y prefijo `fp-` para componentes propios. Conservar Django/Bootstrap y las funciones existentes.
- Registrar cada intervención en `RESULTADOS-FRONTEND.md`: cambios, archivos, pruebas reales, capturas, pendientes y despliegue. Al finalizar actualizar `HANDOFF.md` para Claude. Trabajo frontend en `frontend/etapa3`.
- Probar interfaces a 360/390/768/1024/1440px, etiquetas, teclado y movimiento reducido. No afirmar guardado/emisión verificados con pruebas solo visuales.
- No sobrescribir la implementación multiempresa con el checkout original. Mantener campos, CSRF, selector de empresa y permisos.
- Nunca registrar secretos en documentación, capturas ni commits. Ocultar un campo no corrige la exposición de su valor en HTML: coordinar esto con backend.
