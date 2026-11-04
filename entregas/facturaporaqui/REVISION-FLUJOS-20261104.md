# Revisión independiente de flujos — 04/11/2026

**Base revisada:** `frontend/etapa3 c00b620f7f72ff498a7a8773128056c56bfd88a1`, que contiene `plataforma f2a2b5b`. Se trabajó en un worktree aislado. Esta entrega añade documentación, evidencias y un reproductor de pruebas; no modifica la aplicación, el backend, sus estáticos ni las migraciones.

## Hallazgos reproducidos

| ID | Prioridad | Problema | Responsable |
|---|---|---|---|
| R1 | Alta | El alta rápida de cliente guarda en otra empresa después de cambiar de empresa en otra pestaña | Claude: guardia de servidor. Codex: empresa de origen y respuesta 409 en el diálogo |
| R3 | Alta | El rol Consulta puede modificar productos mediante la importación de Excel | Claude: permisos por acción y efectos de la importación |
| R2 | Media | El navegador considera válido el plazo de crédito vacío, aunque el servidor lo rechaza | Codex: validación local del formulario de factura |

### R1. Cliente guardado en la empresa equivocada

**Recorrido real en Chromium, con dos empresas ficticias y un propietario con acceso a ambas:**

1. Abrir una factura de la empresa A y el diálogo «Crear cliente aquí».
2. Completar una identificación ficticia, razón social y dirección.
3. Cambiar la empresa activa a B desde otra pestaña de la misma sesión.
4. Guardar el cliente en el diálogo que sigue abierto en A.

**Resultado observado:** HTTP 200 y mensaje «Cliente guardado y seleccionado… Puedes continuar con tu factura». La base local contiene el cliente en B, no en A. Las líneas de A siguen visibles. No se emitió ninguna factura. No es acceso a una empresa sin membresía: es una escritura involuntaria en otra empresa a la que el usuario también tiene acceso.

El formulario `core/pos/templates/sale/admin/_cliente_rapido.html` no conserva `empresa` como campo. `core/pos/static/sale/admin/js/cliente_rapido.js`, desde la línea 86, envía a `pathname`, sin el contexto de origen. `core/pos/views/sale/views.py`, rama `create_client` desde la línea 305, valida el permiso pero no la empresa del formulario. La prueba adicional confirma que **incluso enviando `empresa=A` explícitamente, el servidor la ignora**: obtiene `(HTTP 200, clientes en A=0, clientes en B=1)`.

**Corrección coordinada:** conservar la empresa que abrió el diálogo y validarla en el servidor antes de crear usuario, membresía o cliente. Reutilizar el contrato existente `409 / codigo=empresa_cambiada`, incluyendo las búsquedas/validaciones del diálogo para no seleccionar datos de otra empresa. La interfaz debe distinguir ese rechazo de una respuesta de guardado perdida, conservar lo escrito y explicar cómo volver a la empresa original o recargar. Un cambio de empresa no debe convertirse en un reenvío automático a la nueva. Acordar el tratamiento de formularios antiguos sin contexto; ocultar el botón o comprobar solo el DOM no resuelve el problema.

**Aceptación:** el caso normal sigue funcionando; después del cambio, no se crea cliente ni usuario/membresía en ninguna empresa, se recibe el 409 y se conservan los datos del diálogo. Probar también `buscar` y la recuperación de una respuesta perdida con la empresa original.

Evidencia: [captura](capturas/revision-flujos-20261104/cliente-cambio-empresa-1360.jpg) y [peticiones/conteos ficticios](capturas/revision-flujos-20261104/cliente-cambio-empresa.json).

### R3. Importación de catálogo sin permiso de modificar

`core/pos/views/product/views.py:41` exige `view_product` para la lista. La misma vista atiende `action=upload_excel` desde la línea 51 y escribe productos, precios y existencias sin exigir los permisos correspondientes a esas modificaciones.

**Reproducción:** usuario ficticio con rol **Consulta**, sin `change_product`, sube un XLSX de una fila para un producto existente. El servidor devuelve **HTTP 200 `{}`** y su PVP pasa de **10,00 a 19,99**. La fila usa un producto sin control de existencias para aislar el permiso del catálogo; no se probó una operación real ni se atribuye este resultado a la conciliación o al SRI.

**Corrección de Claude:** validar los permisos de cada efecto antes de escribir: alta (`add_product`), modificación (`change_product`) y ajuste de existencias (`adjust_product_stock`) según las operaciones admitidas por el importador. Una fila prohibida debe rechazar el lote completo sin escrituras parciales ni cambios de stock/kardex. Mantener el aislamiento por empresa. La interfaz puede ocultar la acción al rol no autorizado, pero la prohibición debe estar en el servidor.

**Aceptación:** Consulta obtiene 403 y el catálogo queda intacto; revisar igualmente Vendedor y cualquier rol personalizado con lectura, así como altas, actualizaciones y cambios de existencias con roles autorizados. No ampliar permisos del Contador ni modificar reglas tributarias para resolverlo.

### R2. Plazo vacío aceptado por la validación del navegador

Seleccionar Crédito, vaciar `end_credit` y ejecutar la validación del campo devuelve **`Valid`**. La comprobación se hizo con una línea cargada y sin emitir. `core/pos/static/sale/admin/js/form.js:541` configura `notEmpty.enabled=false`; al cambiar a Crédito se llama a `enableValidator('end_credit')`, pero el adaptador local de FormValidation sigue excluyendo los validadores cuyo `enabled` inicial es `false` (`static/lib/formvalidation-1.9.0/js/FormValidation.min.js:203`).

El servidor ya rechaza la fecha vacía con un mensaje legible. **No se observó una factura inválida guardada** por este caso. Falta evitar el envío y mostrar el error junto al campo, conservando cliente y líneas. La corrección debe quedar acotada al formulario; no cambiar el adaptador compartido de todos los módulos sin revisar sus consumidores.

Evidencia: [captura](capturas/revision-flujos-20261104/credito-plazo-vacio-1360.jpg) y hallazgo R2 en [verificacion.json](capturas/revision-flujos-20261104/verificacion.json).

## Qué sí pasó

- **174 pruebas existentes aprobadas en SQLite**: `test_factura_lineas`, `test_respaldo_cobros`, `test_capturas`, `test_adjuntos`, `test_complemento_contable`, `test_revision` y `test_frontend_cobros_puntos`.
- **39 comprobaciones de navegador aprobadas** sobre Django real local: factura con líneas, recibos y consulta mensual sin desborde a 360, 390, 768, 1024 y 1440 px; eliminación de línea con teclado; guardar solo una nota con éxito; completar un gasto; validación del cheque y conservación de campos/borradores; consulta y filtros del mes; ZIP con notas y sin rutas privadas.
- Se perdió deliberadamente una respuesta después de guardar un recibo en la base ficticia. El reintento conservó su clave y reconoció el mismo registro, sin duplicarlo.
- Un cobro ficticio de 5,00 redujo un saldo ficticio de 23,00 a 18,00. Revisar el respaldo dejó el saldo en 18,00. No hubo conexión bancaria ni emisión.
- El Vendedor no vio capturas de otro autor ni el acceso a la consulta mensual. El complemento cerrado redirigió al usuario sin acceso. Sin errores JavaScript ni estáticos faltantes en los recorridos finales.

El informe de navegador registra **por separado** el defecto R2: sus 39 comprobaciones aprobadas no lo dan por resuelto.

## Reproductor para corregir R1 y R3

Archivo: [revision-flujos-20261104/repro_regresiones.py](revision-flujos-20261104/repro_regresiones.py). Desde la raíz del repositorio, con el Python del proyecto:

```bash
python entregas/facturaporaqui/revision-flujos-20261104/repro_regresiones.py
```

Fuerza SQLite en memoria y los ajustes de pruebas. Crea temporalmente una copia del módulo dentro de `tests/` para heredar las fixtures normales, y la elimina al terminar. No modifica código de la aplicación ni usa datos reales. **Resultado sobre c00b620: 1 aprobada y 3 fallidas deliberadamente**, que reproducen la ausencia del campo de empresa, la escritura en B y la importación con el rol Consulta. El reproductor no entra en la suite por defecto; Claude debe incorporar los casos pertinentes a las pruebas del proyecto junto con la corrección.

## Alcance y coordinación

Las vistas de servidor de R1 y R3 y el diálogo rápido tienen los mismos bytes en `29623af`, versión que Claude reportó publicada, y en `c00b620`. Esto justifica priorizarlos, **pero no se comprobó ni se reprodujo el fallo en producción** y no se afirma que existan clientes afectados. No hay decisión fiscal pendiente que impida corregir estas dos guardias.

Claude conserva la propiedad de vistas, reglas y permisos. Codex conserva plantillas y JavaScript. Esta revisión no implementa los cambios propuestos ni interviene en su worktree; los contratos de empresa y de errores se acuerdan en HANDOFF antes de conectar ambos lados. Publicar las correcciones sigue el procedimiento ya autorizado por la propietaria, con respaldo y verificación.

No se ejecutaron la suite completa ni PostgreSQL en esta revisión. No se accedió a producción, archivos `.env`, firmas ni datos de clientes. El entorno local bloqueó conexiones externas y la emisión desde el navegador. Los resultados no certifican cálculos tributarios, ATS/104/103, bancos o contabilidad aún pendientes.
