# Verificar el frontend sin emitir documentos

Estas pruebas usan las plantillas reales de factura con datos ficticios, un servidor local que rechaza todos los POST y respuestas simuladas por Playwright. No verifican persistencia en producción, SRI, PostgreSQL ni la importación real de un Excel.

## Dependencias

Usar el entorno Python del proyecto, Django, widget-tweaks y sus dependencias existentes. Para navegador: Python Playwright y Chromium. La aplicación ya referencia librerías en `static/lib`; no se incorporan bibliotecas nuevas ni CDN.

Los ajustes `config.settings_workflow_test` son los del PR #1. No importan los ajustes de producción ni leen `.env`. La base de renderizado vive en memoria. Los JSON de clientes/productos de `deploy/` no se utilizan.

```bash
python -m django test workflow_tests --settings=config.settings_workflow_test --verbosity=1
node --test workflow_tests/test_sale_frontend.cjs
python frontend_tests/render_preview.py /tmp/facturacion15-preview
python frontend_tests/serve_preview.py --runtime /tmp/facturacion15-preview --port 8766
```

Si las librerías ya instaladas están fuera de este checkout, agregar `--vendor-root /ruta/a/static/lib`. No es necesario copiarlas o versionarlas. Abrir `http://127.0.0.1:8766/sale/add/` y `http://127.0.0.1:8766/propuesta/index.html`.

En otra terminal:

```bash
python frontend_tests/verify_browser.py --chromium /usr/bin/chromium
```

Puede pasarse otra ruta a Chromium y otro directorio de evidencia con `--output`. El navegador solo permite solicitudes a localhost; no se conecta a servicios externos. Las respuestas de alta rápida y errores son simuladas explícitamente.

La validación recorre 360/390/768/1024/1360/1440 px, campos editables, corrección de errores sin pérdida, teclado, estados, vínculos de consulta y aislamiento visual de los datos de demostración frente al piloto pendiente. Las capturas y `verificacion.json` describen su alcance.
