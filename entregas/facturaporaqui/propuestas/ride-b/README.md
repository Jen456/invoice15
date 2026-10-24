# Documentos A4 — estilo B aprobado

Muestras ficticias generadas con las plantillas de la aplicación; no son comprobantes emitidos ni autorizados en el SRI.

- [Factura con logo ficticio](factura-demo.pdf)
- [Nota de crédito](nota-credito-demo.pdf)
- [Nota de débito](nota-debito-demo.pdf)
- [Retención](retencion-demo.pdf)
- [Liquidación de compra](liquidacion-compra-demo.pdf)
- [Guía de remisión](guia-remision-demo.pdf)
- [Factura de 90 líneas, varias páginas](factura-demo-90-lineas.pdf)

Los seis casos cortos de cinco líneas caben en una página A4. Se verificaron además seis casos de 90 líneas: factura 7 páginas, nota de crédito 7, nota de débito 5, retención 4, liquidación 7 y guía 5. Total de la matriz: 41 páginas. La factura con logo es una comprobación adicional a esa matriz. El logo ficticio conserva su proporción 2:1.

La cabecera del documento y los encabezados de tabla aparecen una sola vez, como pidió la propietaria. El pie cursivo aparece en cada página con el colibrí, proveedor, RUC, correo, dirección y número de página. Margen superior/lateral 10 mm; los 28 mm inferiores reservan el pie y la zona de seguridad inferior. `.hoja` conserva 190 mm.

`report.json` registra dimensiones, límites del texto, última línea, encabezados y lectura de la clave. `footers-report.json` confirma separación entre cuerpo/pie y la fuente cursiva en las 41 páginas. Son comprobaciones digitales, no una prueba de impresora/escáner físico.

La lectura con ZXing recuperó la clave exacta en los doce PDF a **300 dpi sin suavizado de imagen y 600 dpi con configuración predeterminada de PDFium**. Las variantes de 216 dpi y 300 dpi con suavizado no la recuperaron por aliasing; no se oculta ese resultado ni se garantiza cualquier lector. El código PNG original y el incrustado conservan la clave. Impresión y escaneo físicos pendientes.

Estos archivos no modifican PDFs guardados de clientes ni provocan emisiones. El diseño se aplicará a los PDF que se generen con las nuevas plantillas. Los archivos A4 ya almacenados conservan su formato hasta una regeneración expresamente coordinada; no se debe reenviar un comprobante al SRI para cambiar su presentación.
