# Llenado ágil de factura y respaldo del cobro

Entrega del 30/10/2026, frontend/etapa3, sin desplegar. Revisar primero [FLUJOS-ERPNEXT.md](FLUJOS-ERPNEXT.md): comparación del fork indicado por la propietaria y adaptación a los procesos y comprobantes de Ecuador.

## Factura implementada en la aplicación

- `core/pos/templates/sale/admin/create.html`: tres secciones, alta de cliente visible, búsqueda/alta de producto, líneas legibles y pago/resumen. Mismos campos, acciones y CSRF. Botón «Emitir factura» al final del formulario, sin superponerse a los campos.
- `_producto_rapido.html` + `core/pos/static/sale/admin/js/llenado.js`: diálogo que obtiene el formulario real y conserva sus campos; no ejecuta scripts de la página descargada. Es una alta real en el catálogo, incluso si luego se cancela la factura.
- Permiso `add_product` del rol activo mediante el tag `permisos_de`; comprobado también por los endpoints existentes. No se habilita el botón por tener únicamente permiso de facturar.
- GET `/pos/product/add/`: se obtiene el formulario con CSRF y marcador de empresa. POST a la misma ruta con `action=validate_data`, `pattern=code` y `pattern=pattern` (nombre/categoría); después `action=add` y los campos originales mediante FormData.
- Éxito actual del alta: `{}`. Recuperación en POST `/pos/sale/admin/add/`, `action=search_product_code`, `code`. Solo se añade la respuesta del servidor, con cantidad 1, mediante `sale.addProduct`; no se inventan ids, precios ni tarifas.
- Servicio/no inventariado: se añade al formulario. Inventariado sin existencias: se crea, pero no se añade ni se inventa stock. La entrada de inventario sigue siendo un proceso separado.
- Se preservan cliente, líneas, cantidades e información adicional. Cerrar y reabrir el diálogo conserva lo escrito mientras la página siga abierta. No se promete persistencia del formulario al recargar/cerrar el navegador.
- Fallo de respuesta al guardar: se consulta el código, sin repetir automáticamente el alta. Si el guardado no quedó confirmado, un producto encontrado no se añade a ciegas: se pide revisarlo en la búsqueda.
- Duplicados y errores por campo; sección opcional se abre si tiene errores. Sin nuevas librerías/CDN ni cambios fiscales.

El marcador en `product/create.html` usa el contexto `company` que ya existe. No se modificó Python, formularios, modelos, migraciones ni endpoints. Los scripts no sustituyen la autorización o las transacciones del backend. El GET de producto utiliza la vista existente, que registra su módulo en la sesión; una API específica de alta rápida podría evitar ese efecto y devolver directamente el producto.

## Propuesta del respaldo del cobro

Abrir [respaldo-cobro.html](respaldo-cobro.html) desde el repositorio local. Es independiente de la aplicación: selecciona un archivo y prepara la vista previa **sin enviarlo ni guardarlo**. No genera abonos. Permite comprobante, nota o ambos y muestra autor y estado de revisión. Mantiene un aviso contextual para cobro en efectivo.

Para servirlo localmente desde la raíz del repositorio:

```bash
python -m http.server 8040 --bind 127.0.0.1
```

http://127.0.0.1:8040/entregas/facturaporaqui/propuestas/venta-agil/respaldo-cobro.html

## Contrato solicitado a Claude — siguiente entrega de backend

No se inventan rutas ni se envían campos nuevos a una vista que no los recibe. Claude debe publicar rutas, métodos, nombres de campos, acciones, contexto, permisos y respuestas reales para:

1. **Separar condición y medio:** contado/crédito describe cuándo se cobra; efectivo/transferencia/tarjeta/cheque describe cómo. `payment_method` es la forma del comprobante SRI y no debe remapearse desde una etiqueta sin regla explícita. `cash`/`change` solo tienen sentido para efectivo. Mantener compatibilidad con los valores históricos `efectivo`/`credito`; no cambiar documentos existentes ni sus XML por esta mejora.
2. **Registrar respaldo ligado al cobro y la empresa:** importe, medio, referencia, nota interna y archivo opcional. Reutilizar `PaymentsCtaCollect.description`, `medio_pago`, `referencia`, `registrado_por` y `registrado_en` donde aplique, y definir la relación para cobros al contado. Pedir al menos archivo o nota cuando se registra un cobro; una factura a crédito sin abono no debe exigir una transferencia inexistente.
3. **Autoría:** autor, rol, empresa y fecha/hora desde la sesión y el servidor, nunca aceptados del navegador. Cambios de nota/respaldo con historial, sin sustituir silenciosamente el original. Vendedor registra con su permiso; el rol autorizado revisa. Exponer capacidades `puede_registrar`/`puede_revisar` o equivalentes reales.
4. **Archivo privado:** PDF/JPG/PNG (propuesta 5 MB); validar contenido/tamaño en servidor, almacenar por empresa y servir solo a usuarios autorizados. No usar una URL pública o un enlace que el cliente pueda adivinar. Errores claros sin perder la factura. Decidir con el contrato si la carga es temporal y se vincula al emitir, o se adjunta a un cobro ya registrado; limpiar adjuntos huérfanos según esa decisión.
5. **Revisión separada:** respaldo pendiente/revisado/rechazado, revisor, fecha y motivo. No marcar un pago como verificado por adjuntar una imagen o escribir una nota. El backend debe definir cuándo un cobro afecta al saldo; no cambiar esa regla ni duplicar el abono desde frontend. Reutilizar la lógica de CxC y su idempotencia; dejar explícito el tratamiento del cobro pendiente de verificación.
6. **Privacidad y fiscalidad:** nota y respaldo internos, fuera de `additional_info`, XML y RIDE. No cargar números completos de tarjeta. No confundir autorización SRI, respaldo de cobro, estado de pago y conciliación bancaria.
7. **Pruebas:** empresa/usuario sin permiso, acceso a archivo ajeno, autor falseado, crédito sin abono, transferencia con archivo, nota sin archivo, rechazo, modificación auditada, doble envío, pérdida de respuesta, fallo de subida y conservación del saldo/documento. Sin pagos, emisiones ni correos reales.

Hasta recibir ese contrato, los campos operativos `cash`/`change` se conservan. Ocultarlos y enviar valores inventados no resolvería el proceso contable. La maqueta establece la presentación solicitada, no una nueva regla de contabilización.

## Evidencia

- [Factura móvil](../../capturas/venta-agil/factura-360.webp), [factura escritorio](../../capturas/venta-agil/factura-1360.webp).
- [Alta de producto móvil](../../capturas/venta-agil/producto-360.webp), [escritorio](../../capturas/venta-agil/producto-1360.webp).
- [Respaldo de cobro móvil](../../capturas/venta-agil/respaldo-360.webp), [escritorio](../../capturas/venta-agil/respaldo-1360.webp).
- Resultados JSON en `capturas/venta-agil/`: factura, fallos de red/doble envío y respaldo. Datos exclusivamente ficticios; no hay archivos de cliente ni tokens en las capturas.

Pruebas Django y resultados detallados en `RESULTADOS-FRONTEND.md`. Chromium a 360/390/768/1024/1360/1440 px, teclado/Escape y movimiento reducido. Altas de productos realizadas en SQLite local; sin emisión de factura, correo, cobros ni despliegue. Teléfono físico y PostgreSQL no comprobados en esta entrega.
