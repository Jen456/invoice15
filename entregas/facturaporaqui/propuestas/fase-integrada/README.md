# Diseño sobre la fase integrada — entrega del 30/10/2026 UTC

Base backend: `3192d5d`; fusión en frontend: `471fcdd`. Estas muestras corresponden a las plantillas reales, con una base SQLite local creada exclusivamente con datos ficticios de `tests/helpers.py`, `tests/ayudas_proformas.py`, `tests/ayudas_ventas.py` y `tests/fabricas_recibidos.py`. No son capturas de producción.

- [Proforma corta, A4](proforma-corta.pdf): 5 líneas, 1 página.
- [Proforma larga, A4](proforma-larga.pdf): 60 líneas con descripciones largas, 6 páginas.
- [Validación PDF](validacion-pdf.json): cabecera y encabezado de detalle una sola vez; última línea y total conservados. Se reutilizan los estilos y el pie B compartidos. Las muestras no incluyen datos fiscales del proveedor configurados en producción.
- [Resultados de navegador](verificacion-navegador.json): 24 recorridos × 360, 390, 768, 1024, 1360 y 1440 px; interacciones, permisos de cobros y teclado.
- [Capturas](../../capturas/fase-integrada/): vistas a 360, 768 y 1360 px; detalles móviles a 390 px y páginas de los PDF. Se captura el viewport de 900 px de alto; las imágenes de detalle muestran líneas, búsqueda y modales más abajo.

## Qué se comprobó

Chromium local. Ningún desborde horizontal del documento, error JavaScript ni respuesta HTTP >=400 en los 144 recorridos finales. Algunas tablas conservan desplazamiento dentro de su región enfocable. La vista de líneas conserva los inputs originales y sus eventos.

Precarga de 5 líneas de proforma con cliente y con prospecto; para este último aparece el modal con los datos sugeridos. No se pulsó Generar venta. Cambio de cantidad de 3 a 4 en la proforma: total mostrado 75,24 → 85,59, sin duplicar filas. Búsqueda AJAX de producto por línea de XML con selección por teclado. Escape cierra los modales; Tab recorre destinatarios y mensaje; foco visible; movimiento reducido activado. Una advertencia de correo simulada usa texto literal, sin interpretar HTML. No se envió correo.

Propietario: permiso de eliminar cuenta por cobrar y botón presentes. Contador: permiso falso y papelera ausente. El servidor sigue decidiendo los permisos; no se pulsó Eliminar.

## Límites

No se publicaron app ni landing. No se ejecutaron migraciones sobre una copia de producción, PostgreSQL ni reversas en esta entrega. No hubo pagos, correos, emisiones ni regularización histórica. Las comprobaciones de ancho son emulación de viewport en Chromium, no pruebas en teléfono físico. El PDF se revisó digitalmente, no en una impresora física.

Los contratos y todos los pendientes fiscales de Claude siguen vigentes. Bancos y el núcleo contable siguen como maquetas de etapas futuras.
