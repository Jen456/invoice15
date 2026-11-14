# Inicio contable · propuesta para aprobación

13/11/2026. Decisión funcional: permitir comenzar desde estados financieros/saldos de apertura o reconstruir el historial. La carga progresiva de respaldos no debe duplicar el saldo inicial.

Abrir `index.html` en un navegador. Navegación de muestra: elegir → saldos → revisión, o elegir → historial. Los datos son ficticios, las fechas son ejemplos y ningún botón llama una API ni crea registros. No representa una importación de NEXALLTI ni de otra empresa real.

Contrato técnico propuesto: `../../CONTRATO-APERTURA-CONTABLE.md`. Orden de cierre: `../../ORDEN-CIERRE-CONTABLE-TRIBUTARIO.md`.

El precio pendiente no sustituye el desarrollo de cuentas, apertura, diario y mayor. Los endpoints nuevos se deben acordar con Claude antes de conectar esta interfaz. Las pantallas no se añaden al menú de la aplicación hasta que haya funcionalidad real y permisos.

Sin dependencias externas ni CDN. El colibrí proviene de `static/img/brand/isotipo-pie.png` (14,7 KB). Capturas y PDF identificados como propuesta, sin datos de clientes. Las pruebas de esta carpeta solo verifican presentación e interacción de demostración, no cálculos ni reglas contables.

## Entrega y validación

- [PDF para aprobación](Inicio-contable-saldos-o-historial.pdf): siete páginas A4 con la propuesta, ejemplos y diseños.
- [Evidencia de navegador](VALIDACION.json): cuatro vistas × seis anchos (360, 390, 768, 1024, 1360 y 1440), sin desborde; siete comprobaciones de interacción.
- [Capturas](capturas/): WebP sin pérdida, 360/768/1360 px y recortes de las pantallas para el PDF; cada imagen tiene menos de 150 KB.
- [Orden para Claude](../../ORDEN-CIERRE-CONTABLE-TRIBUTARIO.md) y [contrato propuesto](../../CONTRATO-APERTURA-CONTABLE.md).

Las fuentes de generación están en `fuentes/`. Requieren Python con Playwright, Pillow y ReportLab, Chromium en `/usr/bin/chromium` y Liberation Sans del sistema. No se añaden estas dependencias a la app. Para reproducir desde la raíz del repositorio, servirlo con `python -m http.server 8095 --bind 127.0.0.1`, ejecutar `python entregas/facturaporaqui/propuestas/apertura-contable/fuentes/verificar.py` y después `python entregas/facturaporaqui/propuestas/apertura-contable/fuentes/crear_pdf.py`.

No se ejecutó la suite Django: solo se añadieron documentación y una propuesta independiente. El primer recorrido de automatización se detuvo por un selector que coincidía con un botón visible y otro oculto; se acotó al visible y la ejecución final pasó completa.

Contraste calculado de los pares principales de texto: azul/blanco 11,83:1; blanco/coral 4,75:1; texto secundario/fondo 5,43:1; aviso ámbar 6,67:1. No sustituye una auditoría de accesibilidad de la app conectada.
