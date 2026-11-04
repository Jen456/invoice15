# Entrega v9 accesible desde invoice15

Copia de los **55 archivos modificados** entre `817c5be` y `25e4f78d1013c6077c66f034f08502d091b0a89d` de `Jen456/facturacion15`, conservando sus rutas relativas y bytes. Procedencia y SHA-256 por archivo en [ORIGEN.json](ORIGEN.json). El [parche de interfaz](cambios-interfaz.patch) permite revisar el cambio original con su contexto.

El `.gitattributes` de esta carpeta conserva los espacios de contexto del parche y la línea vacía final de la plantilla original; no excluye de validación el código activo.

Esta carpeta es una **referencia aislada**. No cambia las plantillas activas, el backend ni las reglas de cobro de invoice15; no se añadieron rutas de la aplicación. Se trasladaron únicamente los archivos de la entrega de interfaz, sin el historial completo, configuraciones de entorno ni material de firma del otro repositorio.

## Revisar el diseño

- [Maqueta contable navegable](entregas/facturaporaqui/propuestas/ux-v9/index.html): inicio, cuentas, asientos, revisión mensual, reportes y puntos. Datos simulados, acciones definitivas deshabilitadas, sin API ni almacenamiento.
- [Datos que requiere del backend](entregas/facturaporaqui/CONTRATO-FRONTEND-PENDIENTE.md): propuesta original, no contrato acordado.
- [Resultados originales](entregas/facturaporaqui/RESULTADOS-FRONTEND.md) y [capturas originales](entregas/facturaporaqui/capturas/ux-v9/): corresponden a la base antigua, no certifican la aplicación actual.
- [Guía PDF original](entregas/facturaporaqui/manuales/Guia-interfaz-v9-propuesta.pdf): propuesta histórica. Sus reglas de pago y archivo de 10 MB no son las de producción; no distribuirla como manual vigente de invoice15.

Para abrir la maqueta, desde esta carpeta ejecutar `python -m http.server 8087 --bind 127.0.0.1` y visitar `http://127.0.0.1:8087/entregas/facturaporaqui/propuestas/ux-v9/`. Sus CSS y marca están incluidos aquí y no dependen del tema activo de invoice15.

Los archivos `core/`, `templates/`, `static/` y `frontend_tests/` de esta referencia sirven para comparar la entrega original. **No copiar encima de las carpetas activas ni aplicar el parche completo:** provienen de un backend diferente. La clasificación para integrar está en [INTEGRACION-V9-20261104.md](../../INTEGRACION-V9-20261104.md).

El Word v9 no fue recibido en la sesión de Codex. Se conservan las etiquetas honestas de la propuesta: piloto reportado, Excel sin importar y saldos sin confirmar. El límite de tres puntos es un requisito interno para el contrato del servidor; la maqueta no lo impone a la aplicación ni equivale a tres sucursales.
