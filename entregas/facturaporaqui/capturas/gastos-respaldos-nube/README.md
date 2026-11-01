# Revisión de gastos y respaldos en nube

Datos ficticios. Django sobre SQLite aislada y Chromium del entorno de nube; no se accedió a producción. Fecha de trabajo: 31/10/2026 (Ecuador).

| Pantalla | 360 px | 768 px | 1360 px |
| --- | --- | --- | --- |
| Registrar gasto | [Móvil](gasto-360.webp) | [Tableta](gasto-768.webp) | [Escritorio](gasto-1360.webp) |
| Consulta mensual | [Móvil](consulta-360.webp) | [Tableta](consulta-768.webp) | [Escritorio](consulta-1360.webp) |

Consulta de una nota de cobro: [390 px](cobro-nota-390.webp) y [1360 px](cobro-nota-1360.webp).

Ocho capturas WebP, dimensiones originales, 24–148 KB cada una. La empresa de demostración conserva el aviso de configuración pendiente: no se configuraron firmas ni se emitieron comprobantes para obtener estas imágenes. Las facturas ficticias se prepararon mediante los helpers de pruebas.

## Comprobaciones

- [38 verificaciones iniciales](verificacion-navegador.json): 360/390/768/1024/1360/1440 px, sin desbordamiento horizontal del documento, filtros, nota sin enlace vacío, origen correcto, consulta del recibo existente, ZIP, teclado, límites de archivo, acceso de Consulta y guardados reales en la base ficticia. Sin errores JS ni respuestas HTTP fallidas inesperadas.
- [12 verificaciones finales](verificacion-final.json): rechazo 409 al repetir el archivo en el mismo documento, conservación del archivo original, error 503 simulado y reintento, guardado con importe válido y comprobación del mínimo en navegador, capturas finales a 360/768/1360 px. Se corrigió la pérdida de foco al ocultar el botón de reintento; Escape vuelve a cerrar la consulta.
- Confirmación por ORM de la nota guardada sin archivo y de un único `Adjunto` en el gasto con recibo. Comprobación del CSV dentro del ZIP: nota de cobro incluida, sin rutas del almacenamiento privado.
- La nota descriptiva de un gasto sigue marcada como falta de respaldo por el backend mensual. No se escondió esta diferencia; se documenta para Claude.

La prueba de cero corresponde a la interfaz, no demuestra una validación nueva del servidor. No se modificó el backend. Los estados de revisión proceden de la API; no se calculan a partir de la presencia de un archivo.

Scripts, servidor, base y medios de ensayo en un directorio temporal de trabajo fuera del repositorio. El acceso de demostración es local al entorno de nube y no se incluyó en la aplicación. No es un enlace público de revisión ni una validación sobre un teléfono físico.

Suite completa final: **1494 aprobadas y 47 omitidas exclusivas de PostgreSQL**, sin fallos, sobre el código `a9cbe28`. [Registro reproducible de comandos, entorno y resultados](pruebas-automatizadas.json). Los commits posteriores de cierre solo documentan esta verificación.
