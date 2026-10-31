# Locales y puntos de emisión — maqueta navegable

Entrega de diseño del 30/10/2026. Abrir [index.html](index.html) en un navegador. No necesita Django, base de datos ni instalación de librerías. Si se sirve desde un servidor estático, conservar la estructura del repositorio para cargar el colibrí.

Desde la raíz del repositorio, una opción local es:

```bash
python -m http.server 8040 --bind 127.0.0.1
```

Abrir http://127.0.0.1:8040/entregas/facturaporaqui/propuestas/establecimientos/index.html

## Recorrido

1. Consultar las tarjetas de Local Centro y Local Norte; buscar por nombre, dirección o código.
2. Agregar un local en tres pasos: establecimiento, primer punto y revisión. Se rechazan códigos inválidos y duplicados. El nuevo punto queda pendiente de numeración.
3. Agregar más puntos dentro de un local. Un mismo código de punto puede existir en locales distintos.
4. Consultar la numeración de facturas y notas de crédito, separadas por punto; son referencias ficticias y nunca se incrementan.
5. Abrir «Vista de facturación». Cambiar «Mi punto de trabajo»: el borrador abierto conserva su punto. «Nuevo borrador de ejemplo» adopta la preferencia. «Cambiar punto del borrador» afecta solo al borrador.

Todo se mantiene únicamente en memoria. Recargar restablece el ejemplo. No hay API, almacenamiento persistente, pagos, emisiones, trámites SRI ni cambio de numeraciones reales. La marca Matriz es un dato ficticio explícito, no una deducción del código 001. El nombre «Caja principal» identifica un punto; no implementa caja contable ni inventario por sucursal.

## Capturas y verificación

- [Escritorio](../../capturas/establecimientos/locales-1360.webp), [tablet](../../capturas/establecimientos/locales-768.webp), [móvil](../../capturas/establecimientos/locales-360.webp).
- [Revisión antes de crear](../../capturas/establecimientos/revision-360.webp).
- [Punto del borrador en móvil](../../capturas/establecimientos/facturacion-360.webp).
- [Resultados de navegador](../../capturas/establecimientos/verificacion.json).

Chromium: 48 comprobaciones de vistas a 360/390/768/1024/1360/1440 px, sin desbordes del documento ni errores JS/HTTP. Flujos de registro, errores, consulta, selección, foco con teclado/Escape y movimiento reducido comprobados. Capturas revisadas visualmente, WebP de menos de 60 KB. No se probó teléfono físico ni backend.

## Integración pendiente

Seguir [PROPUESTA.md](PROPUESTA.md) y el contrato que Claude publique en HANDOFF. Los nombres de campos de esta maqueta son locales; **no establecen ni sustituyen el contrato del servidor**. Antes de trasladar la presentación a plantillas reales hacen falta las rutas, acciones, campos, permisos y mensajes para catálogo/alta, selección por usuario y punto ligado al documento. También el estado por documento/ambiente y la numeración de referencia sin reservar números. La maqueta no valida permisos ni concurrencia reales.

Se mantienen el colibrí y la paleta de la aplicación, sin nuevas dependencias ni recursos externos. Los estilos están aislados en `locales.css`; la integración usará el marco y los componentes existentes.
