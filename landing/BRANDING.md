# FacturaPorAquí — Colibrí Ingenioso

Identidad elegida: colibrí amable con gafas y un comprobante aprobado en el ala. Lema: **Tu negocio, en orden.**

## Archivos
- `assets/brand/isotipo.png`: símbolo completo, PNG transparente.
- `assets/brand/favicon.png`: variante simplificada, PNG transparente, para pestañas y pequeños iconos.
- Copias para Django en `static/img/brand/`.

Son imágenes raster de alta resolución, no archivos SVG vectorizados. No presentarlos como vectores. Las versiones generadas tienen pequeñas variaciones de color; los colores exactos para interfaz y tipografía son los siguientes.

## Paleta
Coral #CA462C, celeste #44BADD, azul oscuro #163B50, azul claro #E5F1F6 y blanco #FFFFFF. Usar coral para acciones principales, azul oscuro para textos y celeste para acentos. No sustituir estos colores por los de Suprohosting.

## Composición
El isotipo puede usarse solo. Para el logo completo, acompañarlo con el nombre escrito exactamente **FacturaPorAquí**, manteniendo la tilde. Usar tipografía sans serif, peso 750–800. Presentación horizontal: icono a la izquierda del nombre. Fondo blanco o azul claro; en fondo oscuro, nombre blanco y símbolo a color. No estirar, inclinar, añadir sombras o animar el logo. Mantener margen libre de al menos un cuarto de su altura. Usar el símbolo completo a partir de 48px; para tamaños menores, la variante simplificada.

## Aplicación por Claude
La landing ya referencia los archivos de su carpeta. Desplegar la carpeta completa, no solo index.html.

Para la aplicación multiempresa vigente: copiar `static/img/brand/`, incorporar el favicon a la plantilla base, usar el isotipo en login y barra lateral, y conservar las funciones, roles, selector de empresa y aislamiento implementados. No reemplazar plantillas actuales por las antiguas de esta rama. Usar el tema coral/celeste documentado como referencia y adaptarlo a las plantillas vigentes. Ejecutar collectstatic y comprobar imágenes y CSS sin 404. No usar el logo de la empresa cliente como identidad del producto; conservarlo por separado en sus comprobantes y configuración.

Los cambios de templates y CSS de la aplicación permanecen locales; esta entrega a GitHub incluye solo landing, guía y archivos de marca.
