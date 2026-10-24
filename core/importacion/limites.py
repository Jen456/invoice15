"""Límites de la importación (documentados en HANDOFF para el frontend). Cambiarlos aquí y en el contrato."""
MB = 1024 * 1024

MAX_XML_BYTES = 2 * MB              # una factura con muchas líneas cabe holgadamente
MAX_PDF_BYTES = 5 * MB
MAX_ARCHIVOS_POR_LOTE = 50
MAX_BYTES_POR_LOTE = 60 * MB          # suma de todas las peticiones del lote
MAX_BYTES_POR_PETICION = 9 * MB       # nginx admite 10 MB por petición (client_max_body_size): se sube en varias
MAX_PDF_PAGINAS = 5                 # un RIDE tiene la clave en la primera página; más páginas no se renderizan

# Estructura del XML (además de prohibir DTD y entidades)
MAX_ELEMENTOS_XML = 50_000
MAX_PROFUNDIDAD_XML = 40
MAX_ANIDAMIENTOS_CDATA = 2          # <autorizacion><comprobante>...<factura> y nada más adentro

# Trabajador del PDF (proceso aparte con límites del sistema operativo)
PDF_DPI = 200
PDF_MAX_PIXELES_PAGINA = 2600 * 3600   # ~ A4 a 300 dpi: una página enorme no agota la memoria
PDF_TIEMPO_SEGUNDOS = 15
PDF_CPU_SEGUNDOS = 12
PDF_MEMORIA_BYTES = 768 * MB

# Consulta de autorización al SRI
SRI_TIEMPO_SEGUNDOS = 10
SRI_REINTENTOS = 1                  # un intento adicional si no responde (no si responde «sin resultados»)

# Procesamiento por petición (el navegador pide «procesar» hasta terminar el lote). gunicorn corta a los 60 s: no se
# empieza otro archivo ni otra verificación después de PRESUPUESTO_PETICION_SEGUNDOS. Peor caso de una tarea:
# PDF 15 s + SRI (10 s × 2 intentos + 1 s) ≈ 36 s; con el presupuesto, una petición queda por debajo de ~45 s.
PROCESAR_POR_PETICION = 3
PRESUPUESTO_PETICION_SEGUNDOS = 20
