# Dependencias frontend — integración con plataforma

La entrega integrada conserva `static/lib` de Claude: archivos versionados, manifiesto de integridad `static/lib/MANIFIESTO.json` y recuperación mediante `deploy/scripts/recuperar_static_lib.py`. No usar el instalador antiguo de Codex, retirado de la rama. Highcharts ya no se importa ni se descarga; los gráficos usan Chart.js y `static/js/graficos.js`.

FormValidation se resuelve con la implementación compatible incluida por Claude. En la comprobación local de navegador no hubo errores JavaScript ni recursos faltantes.

El entorno de validación usó Python 3.12, dependencias de `requirements/base.txt` y `requirements/dev.txt` instaladas con `uv pip install --require-hashes`. No se modificaron estos archivos ni `.env`. El servidor local utilizó ajustes externos al checkout y empresas ficticias, con PayPhone deshabilitado.

Para desplegar, utilizar el procedimiento vigente de Claude, recoger los estáticos y comprobar versiones/cache. Codex no realizó despliegue ni pagos reales.
