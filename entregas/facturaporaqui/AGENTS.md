# Convenciones frontend de FacturaPorAquí

- Mantener el branding: colibrí Ingenioso, coral #CA462C, celeste #44BADD, azul oscuro #163B50 y azul claro #E5F1F6.
- Usar `static/css/facturaporaqui.css` para el tema compartido y prefijo `fp-` para componentes propios. Conservar Django/Bootstrap y las funciones existentes.
- Registrar cada intervención en `RESULTADOS-FRONTEND.md`: cambios, archivos, pruebas reales, capturas, pendientes y despliegue. Al finalizar actualizar `HANDOFF.md` para Claude. Trabajo frontend en `frontend/etapa3`.
- Probar interfaces a 360/390/768/1024/1440px, etiquetas, teclado y movimiento reducido. No afirmar guardado/emisión verificados con pruebas solo visuales.
- No sobrescribir la implementación multiempresa con el checkout original. Mantener campos, CSRF, selector de empresa y permisos.
- Nunca registrar secretos en documentación, capturas ni commits. Ocultar un campo no corrige la exposición de su valor en HTML: coordinar esto con backend.

- Formularios compartidos usan `.fp-responsive-form`. En móvil las líneas de documento se presentan con `.fp-mobile-lines` y `data-label`, conservando las celdas e inputs originales (sin clones) para no romper eventos ni cálculos. Verificar filas con productos y edición de cantidad, además del formulario vacío.

- Material de redes: dejar una zona segura mínima de 60 px arriba, abajo, izquierda y derecha para texto y marca; comprobar miniatura y formato completo. Las historias requieren también espacio para la interfaz de la plataforma.

- La zona segura de redes es invisible: extender fondo y formas decorativas hasta el borde; no crear marcos, paneles interiores ni bandas que alteren el diseño. Mantener texto/logo al menos a 60 px.

- Los RIDE A4 usan `static/css/facturaporaqui-ride.css` y el pie `templates/ride/_pie.html`, separados del tema web. Elección de la propietaria: estilo B, contenido de 190 mm, margen superior/lateral de 10 mm y reserva inferior para el pie; cabecera y encabezados de tabla una sola vez, sin repetición en páginas posteriores. Colibrí pequeño y datos del proveedor en cursiva en el pie de cada página. Conservar los cuatro datos del proveedor, RIMPE y desglose por tarifa. Probar PDF corto/largo, no solo HTML; indicar configuración de rasterizado al informar lectura de barras.

- El ticket térmico tiene diseño propio en `sale/format/ticket.html`: papel de 58 mm, contenido de 48 mm y alto medido por `printer.create_pdf_continuo` mediante `alto_pagina`. Conservar la regla `@page`; sin alturas estimadas, pie fijo/absoluto, `min-height` internos ni saltos forzados. Descripciones a todo el ancho, mínimo de 8 pt y cifras monetarias sin partir. Validar PDF de 1/5/40 líneas y largas, una hoja y menos de 12 mm blancos al final. El pie cursivo permanece en el flujo; no incluir el pie fijo/running del A4.

- Los mensajes Django ordinarios se presentan una sola vez mediante `templates/fp_mensajes.html`, con el nivel del servidor y escape HTML. Los mensajes etiquetados `plan` y `configuracion` siguen en sus componentes propios. `hzt_dashboard.html` sustituye `section_content`, por lo que incluye el componente explícitamente; verificar los dos layouts al cambiar el marco.
- La adaptación de tablas de líneas en `static/js/fase-contable.js` añade etiquetas a las celdas originales; no clona campos ni calcula reglas de negocio. Las regiones de tablas desplazables son enfocables y tienen `position: relative` para contener los textos accesibles posicionados de sus encabezados.
