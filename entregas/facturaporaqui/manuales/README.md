# Manual de uso para clientes — FacturaPorAquí

[Descargar PDF](Manual-de-uso-FacturaPorAqui.pdf) · [Fuente HTML](manual.html) · [Estilos](manual.css)

Edición 1.0 · 28/10/2026 · 16 páginas A4. Marca colibrí Ingenioso, índice con enlaces y ejemplos ficticios. Contenido revisado contra el código y las plantillas de frontend/etapa3; no se usó una cuenta de producción ni se emitieron documentos.

Incluye registro, planes, los cinco pasos del asistente, clientes/productos, facturas, estados e impresión, otros comprobantes, guías, importación de facturas XML/RIDE, empresas/roles, trabajo diario y solución de problemas. Proformas y Complemento Contable figuran como próximos, sin precio inventado. Sin números de soporte, credenciales ni datos de clientes reales.

## Editar y regenerar

1. Editar `manual.html` y `manual.css`. Los diagramas son ilustrativos; no se presentan como capturas de la aplicación.
2. Desde la raíz, con las dependencias de `requirements/base.txt` y las bibliotecas de sistema de WeasyPrint instaladas:

   ```bash
   python entregas/facturaporaqui/manuales/generar_pdf.py
   ```

3. Revisar el PDF generado: no debe aumentar el número de páginas por desbordes. Si cambia la estructura, actualizar el índice y los enlaces `#pN` del HTML.
4. Comprobar estado de funciones/precios en HANDOFF antes de entregar una edición nueva. El manual sirve al cliente; instrucciones de servidor, secretos, mantenimiento y contratos pertenecen al README técnico.

El generador solo renderiza HTML con recursos locales; no inicializa Django ni consulta la base de datos. Reutiliza `static/img/brand/isotipo-pie.png`. No necesita CDN, firma electrónica, PayPhone ni conexión al SRI.

## Verificación de esta edición

- PDF A4, 16 páginas, texto seleccionable, marcadores e índice enlazado.
- Revisados portada, numeración, factura, importación y vista general de todas las páginas.
- Comprobadas las cajas de texto dentro de la página y los destinos del índice.
- Contenido basado en asistente, templates, rutas, reglas y límites vigentes. No es una prueba de emisión, pago o atención por soporte.
- Capturas de muestra en `../capturas/manual-clientes-*.webp`.

Para compartir con clientes, descargar el PDF y enviarlo por el canal de atención acordado. El enlace del repositorio privado no es accesible a quien no tenga permisos. Esta entrega no ha enviado mensajes ni publicado el archivo en el sitio.
