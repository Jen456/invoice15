# Captura rápida y revisión contable — vista ficticia en la nube

2 de noviembre de 2026 (Ecuador). Aplicación Django real en una base SQLite aislada, sobre `plataforma 69cdca3` y el diseño de esta entrega. Las consultas al SRI se sustituyeron por el simulador de las pruebas; el proceso de vista previa bloquea conexiones externas. Las empresas, archivos, notas, claves y documentos son ficticios. No se consultó producción.

## Evidencia

- `responsive.json`: 75 comprobaciones; 12 pantallas a **360, 390, 768, 1024, 1360 y 1440 px**, más teclado, foco, contraste de los componentes principales y movimiento reducido. Sin desbordes de página ni errores de JavaScript. Los libros y el kardex conservan desplazamiento dentro de sus tablas.
- `flujo.json`: 22 comprobaciones del flujo real, con las API de esta base aislada. Incluye respuesta perdida/reintento, archivo reutilizado por su huella, nota sin archivo, vínculo, edición, descarte, nota de gasto, selección/confirmación del lote, exportaciones, permisos y cambio de empresa entre pestañas.
- `lotes.json`: incorporación de **27 documentos ficticios, 25 + 2**, pausa y continuación; comprobación de la respuesta de plan Ilimitado (esta última respuesta se simuló en el navegador).
- `captura-final.json`: 3 comprobaciones tras ajustar el refresco al mismo filtro (respuesta perdida, corrección y descarte). El mensaje de éxito aparece después de actualizar la fila.
- **31 JPEG**, 360/768/1360 px y cuatro detalles de formularios, todos menores de 150 KB. Son capturas de viewport; para detalle se desplazó la página o se abrió el apartado correspondiente. No se ocultaron requisitos del servidor: el aviso de firma pendiente aparece porque las empresas de ejemplo no tienen firma.

## Muestras

- Captura: [1360 px](captura-1360.jpg), [360 px](captura-360.jpg), [formulario móvil](captura-formulario-360.jpg), [completar sin otra subida](captura-completar-360.jpg).
- Importación: [claves y reporte](claves-1360.jpg).
- Revisión: [mes](revision-1360.jpg), [empresas del contador](empresas-768.jpg), [libros](libros-1360.jpg).
- Tributario: [ATS](ats-1360.jpg), [aviso de borrador](borrador104-1360.jpg), [documentos del casillero](borrador-documentos-1360.jpg).
- Inventario: [kardex](kardex-1360.jpg), [movimientos](kardex-movimientos-1360.jpg), [valorización](inventario-1360.jpg).

La verificación visual no sustituye la revisión fiscal del contador ni las pruebas en PostgreSQL. No se comprobó cámara ni teclado virtual en un teléfono físico. El idioma de algunos controles nativos depende del Chromium instalado; las etiquetas de la aplicación están en español. No se desplegó.
