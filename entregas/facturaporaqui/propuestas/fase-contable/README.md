# Propuesta de Proformas, Bancos y Contabilidad

28/10/2026 · Codex · **Maquetas con datos ficticios, sin integración ni publicación.**

Abrir desde la raíz del repositorio con `python -m http.server 8031` y visitar:

- Catálogo: http://localhost:8031/entregas/facturaporaqui/propuestas/fase-contable/
- Landing propuesta: http://localhost:8031/landing/
- PDF: [proforma-demo.pdf](proforma-demo.pdf).

El catálogo enlaza 21 pantallas: proformas y edición; complemento; cuentas, libro bancos, movimientos, importación, conciliación y reporte; plan de cuentas, asiento, diario, mayor, balance, 104, 103, ATS, kardex, estados financieros, calendario y ADI. Se añade una vista HTML del PDF.

## Qué permite revisar

- Siete estados de proforma, filtro local y acciones ilustrativas. Cantidad y precio actualizan el subtotal sin impuestos del ejemplo. El PDF muestra un ejemplo separado con IVA y total.
- Complemento en tres estados ficticios: vigente, vencido y no contratado. Precio por anunciar; contratación deshabilitada.
- Importación CSV simple: usar `estado-cuenta-demo.csv`, con una fila correcta y otra con errores. Solo vista previa de hasta 20 filas y 1 MB; no incorpora movimientos, no interpreta todos los formatos bancarios ni valida fechas contables reales.
- Conciliación: seleccionar los dos movimientos, revisar y confirmar la simulación. Los totales permanecen visibles; el reporte presenta 1225 + 40 − 15 = 1250.
- Asiento: debe/haber con cuadre local. Hojas 104/103 con detalle desplegable y casilleros DEMO, que **no son números oficiales**. El ATS no genera archivos; ADI no calcula obligación tributaria. Calendario con fechas ilustrativas.
- Las acciones de guardar, enviar y facturar solo muestran avisos. No hay peticiones de escritura, pagos, emisiones ni correos.

## Diseño e integración posterior

AdminLTE 3.2 y Bootstrap 4.6 se cargan desde las bibliotecas existentes en `static/lib`; no hay dependencias nuevas ni CDN. `fase.css` y `fase.js` son exclusivos de estas propuestas. Las tablas se presentan como tarjetas etiquetadas en móvil, sin duplicar inputs. Hay foco visible, enlace para saltar al contenido y respeto a movimiento reducido.

Los HTML son documentos independientes para revisión. Cuando Claude publique los contratos, las plantillas reales deberán extender `skin.html`, usar las clases compartidas y conservar campos, permisos, CSRF y acciones del servidor. No copiar estas simulaciones a producción como funcionalidad.

`proforma-pdf.django.html` reutiliza literalmente `ride/_estilos.html` y `ride/_pie.html`. Se renderizó con el motor PDF existente y datos ficticios para producir `proforma-demo.pdf` y `proforma-pdf.html`. La muestra A4 tiene una página, sin clave de acceso, autorización ni barras. No se modificaron los includes compartidos. La prueba de documento largo deberá añadirse al integrar líneas reales.

Los datos y endpoints pendientes se detallan en [CONTRATOS-PENDIENTES.md](CONTRATOS-PENDIENTES.md). La última sincronización incorporó `a8b893c` de Claude, con PLAN-PROFORMAS-BANCOS-CONTABILIDAD.md, NORMA-CONTABLE-TRIBUTARIA-2026-10.md y la sección de fase contable del HANDOFF. Se leyeron y contrastaron antes de cerrar la entrega. El plan existe; todavía faltan los contratos de las plantillas reales, como indica Claude. Las decisiones D9 (precio, cobertura y período del complemento) siguen pendientes.
