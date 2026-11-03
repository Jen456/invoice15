# Cierre de captura y revisión contable — orden propuesta para Claude

2 de noviembre de 2026. Base revisada: `plataforma 69cdca3`. El diseño de esta entrega se incorpora desde `frontend/etapa3`. No publicar todavía. No fusionar `fase/adjuntos-comprobantes c5e04a9`: ya está superada.

## 1. Integrar y conservar el flujo único de respaldo

Haz fetch y comprueba la ascendencia real antes de fusionar. Conserva ambas historias y las secciones de HANDOFF/RESULTADOS. No reconstruyas una entrega a partir de un mensaje ni uses force push.

El diseño reutiliza tus campos, rutas, capacidades, acciones y mensajes. La nueva captura permite recibo, nota o ambos; completar o vincular reutiliza el archivo. El modal de egresos admite nota sola y recibo pendiente. Ventas y cobros siguen en `core/cobros`.

Decisión de presentación aplicada: en **un gasto nuevo**, el texto de `description` también se envía en `nota_respaldo`. Se avisa al usuario. No se hace esa copia al editar, ni se reclasifican gastos históricos. Los roles se mantienen como los entregaste; Codex no cambió permisos.

## 2. Corregir las notas de crédito del proveedor antes de publicar inventario

Hallazgo confirmado en `core/contabilidad/kardex.py`, función `movimientos_desde_documentos`: todas las líneas de compra positivas crean una entrada; `tipo_comprobante == '04'` solo añade una advertencia. No basta corregir la tabla visual: stock y kardex deben usar la misma operación.

**Recomendación funcional para decisión de la propietaria y validación del contador:**

- Distinguir **devolución física al proveedor**, **descuento o corrección de precio sin devolución**, y **caso mixto**. No deducir el movimiento de inventario únicamente del código 04 ni de que el XML contenga productos.
- Una devolución física debe referenciar compra y líneas, descontar las cantidades devueltas y respetar lo ya devuelto. Un descuento no debe alterar cantidades; su efecto en costo y contabilidad requiere criterio validado. Un caso mixto necesita desglose explícito.
- Mientras no esté definido el tratamiento, impedir que se confirme una nota de crédito de proveedor con productos como si fuera una compra de entrada. Mostrar el motivo y conservarla para revisión. No reescribir movimientos históricos ni aplicar ajustes masivos automáticamente.
- Mantener idempotencia, bloqueo concurrente y trazabilidad de anulación. Probar devolución parcial, descuento sin devolución, combinación, repetición, otra empresa y anulación. Contrastar cantidad de producto, kardex y valorización.
- Publicar el contrato de los campos/estados nuevos para que Codex adapte el formulario. No pedir que el frontend invente la naturaleza del movimiento.

Esta es una recomendación de corrección, **no una aprobación de cambios fiscales ni un cambio ya aplicado**.

## 3. Aplicar el acceso al complemento en el servidor

`core/suscripciones/reglas.py` incluye `/tributario/` y `/contabilidad/` solo en las rutas de plan pagado. Eso no comprueba la contratación del complemento Contable.

Antes de publicar, implementar la regla acordada del complemento en páginas, API y descargas, comprobando la empresa y su cobertura. Ocultar el menú no protege las rutas. Probar acceso directo, empresa cubierta, cambio de empresa, complemento vencido y no contratado. Conservar la captura breve de recibos bajo su regla actual; no bloquearla accidentalmente junto con los reportes.

D9 sigue pendiente: **no inventar precio, vigencia, cupos ni herencia del complemento para todos los RUC de Multiempresa**. Entregar una propuesta concreta de reglas para decisión. Hasta resolverlo, dejar estas funciones fuera del acceso comercial en producción mediante una condición de servidor; la vista de revisión debe seguir siendo solo para pruebas autorizadas. No activar cobros de un complemento sin precio aprobado.

## 4. Cerrar la revisión tributaria con evidencia

Usar `revision-contador/LEEME.md` y sus 12 preguntas. Registrar responsable, fecha, respuestas y ejemplos contrastados. Mantener «Por confirmar», las exclusiones del ATS y el aviso de borrador hasta resolver cada caso.

Validación XSD significa estructura válida; no acredita aceptación del SRI ni que el mes esté completo. No anunciar ATS/104/103 como terminados fiscalmente, no presentar declaraciones y no asignar casilleros por aproximación.

D5/D7 siguen siendo dependencias del diario, mayor, balance y estados financieros; D6/D9, de bancos. No declarar terminado el 101 ni generar estados sin mayor y criterios validados. Resolver esas decisiones por separado, con los datos que efectivamente falten, sin abrir una reconstrucción general de ERPNext ni el chatbot.

## 5. Entregar el candidato comprobado

Sobre el resultado integrado, correr las suites completas SQLite y PostgreSQL. Un fallo intermitente debe investigarse y documentarse; una repetición aislada no equivale a una suite completa aprobada. Ensayar las migraciones necesarias en una copia autorizada del respaldo, registrar límites de restauración y conservar base y archivos privados.

Actualizar HANDOFF con hash exacto, pruebas, contratos cambiados y lista corta de decisiones externas. Subir a GitHub sin desplegar. La publicación requiere la aprobación de la propietaria y su plan de respaldo/restauración.

Codex se encarga de adaptar las pantallas a los contratos que cambien, la revisión móvil, mensajes y guía. Claude se encarga de las reglas, datos, aislamiento, concurrencia, migraciones y validación PostgreSQL. No rehacer pantallas ya integradas.
