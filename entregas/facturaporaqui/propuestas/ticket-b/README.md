# Ticket térmico — diseño B

**Muestras actuales (30/10/2026):** [revalidación con las correcciones de Claude](revalidacion-20261030/README.md). Los archivos de esta carpeta superior se conservan como evidencia del diseño original del 28/10.

Muestras generadas con `printer.create_pdf_continuo` y datos ficticios el 28/10/2026, sobre la base **4ce7888**. No son comprobantes emitidos al SRI ni capturas de producción.

## Muestras de 58 mm

| Líneas | Descripción normal | Descripción larga | Alto normal / largo |
| --- | --- | --- | --- |
| 1 | [PDF](ticket-01-normal.pdf) | [PDF](ticket-01-largo.pdf) | 318,03 / 339,46 mm |
| 5 | [PDF](ticket-05-normal.pdf) | [PDF](ticket-05-largo.pdf) | 410,37 / 517,52 mm |
| 40 | [PDF](ticket-40-normal.pdf) | [PDF](ticket-40-largo.pdf) | 1218,67 / 2075,92 mm |

Los contextos incluyen datos fiscales extensos, cinco tarifas, descuentos y datos completos del proveedor. Las descripciones largas tienen unas 180 letras y terminan con FIN-001…FIN-040 para comprobar su conservación. La longitud de papel aumenta con el contenido y la letra legible; todos estos PDF tienen **una sola hoja continua**, no páginas A4.

- [Muestra adicional con logo ficticio del emisor](ticket-logo-ficticio.pdf). Logo de prueba 4:1, proporcionado dentro de un área de 22 × 12 mm.
- [Captura de cinco líneas](../../capturas/ticket-b-05-normal.png).
- [Comparación anterior, misma empresa ficticia](../../capturas/ticket-b-antes-05-normal.png).
- [Inicio del ticket largo de 40 líneas](../../capturas/ticket-b-40-largo-superior.png) y [final](../../capturas/ticket-b-40-largo-inferior.png). Son recortes de inspección del mismo PDF continuo.
- [Vista en escala de grises](../../capturas/ticket-b-logo-grises.png) e [importes de siete dígitos y nombres sin espacios](../../capturas/ticket-b-textos-importes-largos.png).

## Diseño y validación

Texto oscuro sobre blanco, regla coral y colibrí de 6 mm en el pie cursivo. Tipografía mínima de 8 pt; descripciones y valores de línea de 9 pt, total de 12 pt. Sin transformación automática a mayúsculas. Las descripciones usan todo el ancho y los valores se distribuyen debajo; se conserva cada descuento. Total destacado a todo el ancho para no partir los centavos de cantidades grandes.

`verificacion.json` recoge doce renderizados: las seis variantes con y sin petición. Se comprobaron ancho de 58 mm, texto dentro de los 48 mm centrales, orden y contenido de cada línea, importes e impuestos, tipografía real del PDF y pie cursivo sin solapamiento. Blanco inferior de 6,57–6,69 mm. Capturas de detalle a 203 ppp; vista completa de los dos tickets de 40 líneas a 100 ppp.

No se cambió la regla `@page`, el contexto `sale` / `alto_pagina`, la vista, la URL ni los cálculos. «Subtotal sin impuestos» sigue usando su valor actual, previo al descuento; la decisión fiscal pendiente no se modifica desde el diseño. La etiqueta «Establecimiento» identifica el mismo `establishment_address` que ya usaba el ticket.

La revisión es digital. La impresión física y los márgenes configurados en el controlador de la térmica quedan para la prueba de Claude/propietaria. El diseño es para 58 mm y no requiere un contrato nuevo de 80 mm. Codex no despliega.
