# Comprobantes de pago — evidencia de diseño

31/10/2026. Chromium local, SQLite y datos ficticios de «DEMO RESPALDOS». Backend de adjuntos `722475a` en una copia de prueba separada; plantillas y estáticos de esta entrega cargados desde `frontend/etapa3`. **No corresponde a producción ni a una fusión con `core/cobros`.**

## Capturas

WebP de 21–72 KB, sin modificar el contenido de las capturas. Las vistas de teléfono emulan el ancho, no sustituyen una prueba en dispositivo físico. El aviso de configuración pertenece a la empresa ficticia.

| Pantalla | 360 px | 768 px | 1360 px |
| --- | --- | --- | --- |
| Página mensual | [Ver](mes-360.webp) | [Ver](mes-768.webp) | [Ver](mes-1360.webp) |
| Modal y archivo vigente | [Ver](modal-360.webp) | [Ver](modal-768.webp) | [Ver](modal-1360.webp) |

Detalles a 390 px: [indicadores](indicadores-390.webp), [documento pendiente](pendientes-390.webp), [selección de archivos](formulario-390.webp) e [historial](historial-demo-390.webp).

## Recorridos de navegador

- [51 comprobaciones](verificacion.json): 360/390/768/1024/1360/1440 px, página y modal sin desbordes, pie del modal accesible, permisos, historial, campo del gasto, teclado, Escape y devolución de foco. Movimiento reducido a 390 y 1360 px.
- Subida real de un PNG ficticio a SQLite, consulta, descarga privada y eliminación lógica con motivo. Doble envío bloqueado; destino y metadatos no cambian durante el lote. Texto con etiquetas HTML tratado como texto.
- Duplicado rechazado por el servidor: un HTTP 409 esperado; no se crea otra copia. Consulta sin botones de subida/eliminación. Modal anidado sobre abonos: conserva el primero abierto y recupera su foco. ZIP mensual real, mes vacío sin enlace de descarga.
- [Cuatro fallos controlados](fallos-controlados.json): respuesta GET antigua descartada; POST guardado en servidor pero respuesta interrumpida, recuperado por GET sin repetirlo; lista mensual actualizada al cerrar tras esa recuperación; archivo de 9 MB bloqueado antes del POST por el límite de 8 MB del servidor.

Cero errores JavaScript. Una interrupción de red inducida y un 409 esperado; ninguna escritura en facturas, cobros, pagos o emisión durante estos recorridos. Las únicas escrituras del navegador fueron adjuntos ficticios y sus bajas en la base local. No hubo correos, pagos o emisiones reales.

## Verificaciones del código

- Contra el backend aislado de adjuntos: `tests/test_adjuntos.py`, `tests/test_estaticos.py`, `tests/test_rutas.py`, `tests/test_frontend_integracion.py`: **46 aprobadas** en 23,02 s.
- Sobre plataforma `4a39a1a`, sin instalar todavía adjuntos: estáticos, rutas e integración frontend: **11 aprobadas** en 17,14 s. Las rutas de los estáticos nuevos resuelven desde `static/adjuntos/`.
- `node --check` del JavaScript y `git diff --check` correctos. Seis pares de texto/fondo calculados, mínimo 4,75:1. Sin nuevas dependencias ni CDN.

No se ejecutó la suite completa ni PostgreSQL en esta entrega. Falta probar la integración que resuelva Claude, los permisos/rutas del contrato consolidado, las migraciones del conjunto y un teléfono físico.

[Alcance y notas de integración](../../propuestas/adjuntos/README.md) · [Guía de uso en borrador](../../manuales/COMPROBANTES-DE-PAGO.md).
