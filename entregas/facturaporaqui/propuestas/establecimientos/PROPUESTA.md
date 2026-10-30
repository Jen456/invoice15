# Locales y puntos de emisión — propuesta funcional y de diseño

30/10/2026, Ecuador. Revisión sobre `d2bed3d`, con backend `3192d5d`; referencias remotas consultadas y coincidentes. **Propuesta, no implementada ni desplegada.** Codex diseña; Claude desarrolla backend y publica el contrato antes de conectar las pantallas.

## Lo que ya existe

- `core/pos/models.py`: `Establishment` (código, nombre, dirección, activo), `EmissionPoint` (establecimiento, código, descripción, activo, predeterminado) y `Receipt` (secuencia por empresa/ambiente/establecimiento/punto/tipo).
- `core/configuracion/forms.py` y `views.py`: el paso 2 permite agregar establecimientos, agregar puntos, desactivar puntos sin uso y confirmar uno. No hace falta recrear estos catálogos.
- `core/configuracion/servicios.py::confirmar_punto` cambia un único `is_default` por empresa y alinea los códigos y dirección de `Company`. El paso 3 configura el punto predeterminado. **Esto no equivale a tener una selección independiente para dos locales trabajando simultáneamente.**
- El modelo ya reserva secuencias mediante bloqueo; reutilizar y probar esa protección al ampliar la selección. Este análisis no es una prueba de concurrencia ni una inspección del servidor publicado.

## Recorrido propuesto

Menú: **Configuración → Locales y puntos de emisión**. En la ayuda: «Un establecimiento es un local registrado para tu RUC. Dentro de él puedes tener varios puntos de emisión, por ejemplo Caja principal o Ventas web». Los nombres son etiquetas amigables; los códigos fiscales siguen visibles.

Ejemplo ficticio:

```
MI EMPRESA · un RUC
├─ 001 · Local Centro (matriz, si así consta en el RUC)
│  ├─ 001-001 · Caja principal
│  └─ 001-002 · Ventas web
└─ 002 · Local Norte
   └─ 002-001 · Caja principal
```

No confundir el establecimiento `002` con el punto `002` de otro local. Tampoco confundir varios locales del mismo RUC con varias empresas/RUC del plan Multiempresa. No inventar cargos o límites nuevos.

### 1. Registrar el local

Tarjetas de local: código, nombre, dirección, estado y puntos asociados. Acción **Agregar local**: código del establecimiento según el RUC, nombre fácil de reconocer y dirección. Identificación de matriz basada en los datos confirmados, no deducida automáticamente del código 001. Explicar que registrar aquí no da de alta un establecimiento en el SRI. No prometer consulta automática al SRI ni copiar logos institucionales.

### 2. Registrar un punto dentro del local

Botón **Agregar punto de emisión** dentro de la tarjeta del local, que conserva ese establecimiento como contexto visible. Código y nombre descriptivo: «Caja principal», «Caja 2», «Ventas web». Mostrar inmediatamente la pareja completa, por ejemplo `002-001`. La denominación comercial «caja» no crea una cuenta bancaria ni una caja contable; tampoco crea una bodega.

### 3. Configurar su numeración

Ficha del punto con documentos habilitados y estado de configuración. Por cada tipo y ambiente: último número utilizado, siguiente número ilustrativo y confirmación. Facturas y notas de crédito tienen secuencias independientes, igual que los demás tipos soportados. Si viene de otro sistema, pedir el último utilizado y explicar el próximo; no asumir que todos empiezan en 1. No consumir números por abrir la ficha o mostrar una vista previa.

### 4. Elegir dónde trabaja el usuario

Selector visible: **Local Norte · Caja principal · 002-001**, separado del selector de empresa y del ambiente Pruebas/Producción. Recordar una preferencia por usuario y empresa, con los puntos que el servidor autorice. Si solo tiene uno autorizado y listo, puede preseleccionarse y permanecer visible. Si hay varios y no hay preferencia válida, pedir selección.

Cambiar de punto no modifica el predeterminado global ni mueve las sesiones de otros usuarios. Cada formulario conserva el punto con el que se abrió; si el usuario cambia desde otra pestaña, no se reasigna silenciosamente el documento en curso. Antes de enviar, el servidor valida pertenencia, permiso, estado, ambiente y configuración de ese punto. Si ya no es válido, bloquear con explicación y permitir revisar los datos.

### 5. Revisar y emitir

Encima del formulario: **Emites desde Local Norte / Caja principal · 002-001 · Pruebas**. Mostrar próxima numeración como referencia, indicando que se confirma al emitir. El servidor asigna el número definitivo atómicamente. El cambio de punto dentro de un borrador debe ser explícito, actualizar resumen y volver a validar. Nunca renumerar documentos autorizados ni mover comprobantes antiguos.

Proformas: al convertir, mostrar y confirmar el punto de la nueva factura. Documentos relacionados (NC, ND, retenciones, guías y liquidaciones): Claude debe definir en el contrato cómo se resuelve el punto de cada uno, respetando su documento de sustento y las reglas fiscales, sin asumir que todos heredan el punto de la factura.

Listados: filtro por local/punto; debajo del número, nombre corto del local. PDF/ticket/XML: dirección del establecimiento emisor correspondiente y coherencia con los datos fiscales históricos; no sustituirlos por el local activo al imprimir o regenerar.

## Diseño y accesibilidad

Colibrí y paleta vigentes. Locales en tarjetas, puntos anidados, acciones con texto, estado «Listo para emitir» o «Falta configurar» acompañado de explicación (no solo color). En móvil, lista de tarjetas y selector de ancho completo; sin una tabla amplia como única opción. Errores junto al campo, foco visible, controles táctiles, contraste y movimiento reducido. Revisar a 360/390/768/1024/1440 px.

No mostrar un selector funcional en la app actual simulando independencia: mientras el backend cambie el punto global, sería confuso y podría elegir la numeración incorrecta para otro operador.

## Contrato que necesita Codex de Claude

Reutilizar rutas/servicios existentes cuando corresponda y documentar las nuevas solo si hacen falta. No se inventa un endpoint operativo en esta propuesta. Especificar:

- Datos por local: id, código, nombre, dirección, activo e identificación confirmada de matriz, si se incorpora.
- Datos por punto: id, local, código completo, descripción, activo, estado de configuración y tipos de documento habilitados.
- Puntos autorizados para el usuario, preferencia vigente por empresa y permisos de administrar/seleccionar; validación siempre del servidor.
- Campo/contexto y acción exactos para fijar un punto al formulario y a la emisión. Comportamiento cuando otra pestaña cambia de preferencia o la empresa activa cambia.
- Respuesta para numeración por punto/tipo/ambiente: último, próximo estimado, estado confirmado y bloqueos; nunca reservar al consultar.
- Datos y reglas de impresión histórica, edición de direcciones/códigos, desactivación y migración de las empresas existentes.

## Aceptación del backend

1. Dos locales de un mismo RUC y dos usuarios emitiendo en paralelo: un cambio de punto no altera el del otro usuario ni el formulario abierto.
2. Dos emisiones simultáneas sobre el mismo punto no duplican números; tipos/ambientes y puntos distintos no mezclan contadores.
3. Rechazar punto de otra empresa, inactivo, no autorizado, sin numeración confirmada o con ambiente incorrecto. Probar manipulación del POST y cambio de empresa.
4. Preservar secuencias, documentos, auditoría y configuración existentes; no reiniciar numeración ni elegir otro punto en silencio.
5. Un documento anterior conserva su emisor, dirección y numeración al consultar, imprimir y regenerar. Determinar si hace falta una instantánea histórica adicional.
6. Pruebas locales con empresas ficticias y emisión simulada. Sin pagos, correos, emisiones reales, regularización ni despliegue en esta tarea.

No ampliar esta entrega a inventario por bodega, turnos de caja, conciliación bancaria ni cuotas nuevas: son decisiones y módulos distintos.
