# Ticket B — muestras actualizadas, 30/10/2026

Muestras del código vigente en `e94c3a9`, con el rediseño `165fbc7` y las correcciones de Claude integradas mediante `a6f5db3`. Base de backend `3192d5d`. No se ha vuelto a la base histórica `4ce7888` ni se ha cambiado la plantilla en esta revisión.

Los datos son ficticios y se construyen en memoria con `tests/test_ticket_diseno.py::contexto_ticket`. Generación real mediante `printer.create_pdf_continuo`, sin emisión, correos ni datos de producción.

| Líneas | Descripción normal | Descripción larga | Alto normal / largo |
| --- | --- | --- | --- |
| 1 | [PDF normal](ticket-01-normal.pdf) | [PDF largo](ticket-01-largo.pdf) | 330.46 / 351.90 mm |
| 5 | [PDF normal](ticket-05-normal.pdf) | [PDF largo](ticket-05-largo.pdf) | 422.80 / 529.96 mm |
| 40 | [PDF normal](ticket-40-normal.pdf) | [PDF largo](ticket-40-largo.pdf) | 1231.11 / 2088.36 mm |

Los seis PDF tienen una sola hoja de 58 mm; el área útil de texto es de 48 mm. La longitud aumenta para mantener las descripciones completas y la tipografía legible. Se comprobaron también las seis variantes sin objeto de petición: doce renderizados en total.

- Blanco al final: **6.58–6.70 mm**, menor que 12 mm.
- Tipografía mínima 8 pt; descripción del artículo mínima 9 pt.
- Contenido, orden e importes íntegros; pie cursivo en el flujo, sin solapamientos.
- Las muestras incluyen dirección matriz, establecimiento de la numeración de la venta y fecha de emisión, conforme a las correcciones posteriores de Claude.
- [Medidas y verificaciones](verificacion.json).
- [Capturas](../../../capturas/ticket-b-20261030/): rasterizado con PDFium a 203 dpi, WebP. Las de 40 líneas muestran inicio y final; el PDF conserva el documento completo.

Pruebas: `python -m pytest tests/test_ticket_continuo.py tests/test_ticket_diseno.py tests/test_impresos.py -q -o addopts=` → **20 aprobadas en 26,50 s**, SQLite. No se cambiaron pruebas ni código operativo. La suite completa ya se ejecutó en la entrega frontend anterior; no se repite por esta actualización exclusiva de muestras/documentación.

No se verificaron impresora/controlador físicos ni el estado del servidor publicado. No hubo despliegue. Se conservan los PDF anteriores en la carpeta superior como evidencia histórica.
