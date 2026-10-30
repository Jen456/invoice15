# Handoff compartido — frontend

## Estado actual — fase contable integrada en `plataforma`, sin publicar (Claude, 29/10/2026)

D0 Fase A (`6d2a066`), Etapa 1 (Proformas) y Etapa 2 (Compras, y Ventas y Empresa) están fusionadas en `plataforma`, en este orden: `7f0e576` Proformas → `eaa6d10` Compras → `fff9bb3` Ventas → `90da085` correcciones de la integración → `f109d4d` piezas compartidas (`fase/integracion-cruces`). Los commits posteriores (`8c8a657` y la corrección de su revisión) solo cambian documentación en `entregas/facturaporaqui/`. **No se publicó nada**: la app sigue en lo publicado el 28/10 y la base publicada no tiene ninguna de estas migraciones.

- **Correcciones de la integración (`90da085`):** las pruebas de Compras emiten la retención con la huella de «Revisar» que exige D0; la vuelta de `comprobantes/0023` quita su módulo y sus permisos por ids (antes no se podía deshacer junto con las de D0); la prueba de migraciones de D0 crea su retención con todas las migraciones aplicadas.
- **Piezas compartidas (`fase/integracion-cruces`):** códigos de auditoría de la fase en `AuditLog.ACTIONS` y `AuditLog.detail` con `DjangoJSONEncoder` (`tenancy/0007`); Resultados y tablero restan la nota de crédito del proveedor (04); «Retención sobre una compra» rechaza la 04 y precarga el sustento desde Compras; pruebas cruzadas del 07 importado de punta a punta, de «Anulado en el SRI» sobre compras y de seguridad por filas en todas las tablas de empresa.
- **Pruebas:** las suites completas de SQLite y PostgreSQL se ejecutaron sobre `8c8a657`, antes de subirlo; lo posterior solo cambia `entregas/`, que ninguna prueba lee. Los totales están en el informe de entrega a la propietaria.
- **Migraciones:** 19 nuevas. Orden, efecto sobre los datos existentes y precauciones de aplicación y de reversión en [`MIGRACIONES-FASE-CONTABLE.md`](MIGRACIONES-FASE-CONTABLE.md); detalle por rama en [`MIGRACIONES-PROFORMAS.md`](MIGRACIONES-PROFORMAS.md), [`MIGRACIONES-COMPRAS.md`](MIGRACIONES-COMPRAS.md) y [`MIGRACIONES-VENTAS.md`](MIGRACIONES-VENTAS.md).
- **Norma:** la sección «Anulación» de [`NORMA-RETENCIONES-2026-10.md`](NORMA-RETENCIONES-2026-10.md) se corrigió contra las Res. NAC-DGERCGC25-00000014 y 25-00000017 (prórroga al día hábil, aceptación del receptor y excepciones).

## Pendiente — fase contable integrada (Claude, 29/10/2026)

- [ ] **Publicar**, solo con la autorización de la propietaria y siguiendo las precauciones de `MIGRACIONES-FASE-CONTABLE.md` (volcado, ensayo sobre una copia, ventana con el servicio y el temporizador detenidos). La regularización histórica sigue solo en modo ensayo.
- [ ] **Decisiones de la propietaria** (ninguna cambia campos ni pantallas de los contratos):
  - Proformas: si los envíos fallidos cuentan para el límite de 60 por hora;
  - Compras: si `retenciones_autorizadas` y `liquidacion_vigente` cuentan solo comprobantes de PRODUCCIÓN, y el IVA sobre base + ICE (D7, con el contador);
  - Ventas: si el aviso del día 7 de «Anulado en el SRI» cuenta la prórroga al siguiente día hábil (hoy pide confirmación pasado el día 7; si se decide, cambia el texto del aviso);
  - D0-b a D0-f (escenarios del 310 y el 332E desde el 01/08/2026), antes del 15/12/2026;
  - D9: precio del complemento (sigue «Precio por anunciar»).
- [ ] **Hallazgo X-R1 (backend, sin efecto hoy en datos: nada de esto está publicado):** «Completar datos» acepta cambiar a nota de crédito del proveedor (04) una compra sin tipo, de contado (sin cuenta por pagar) y sin líneas con producto, que ya tiene una retención vigente: una registrada con «Completar después» y solo con líneas de gasto, o una antigua sin líneas. La retención queda sobre una 04, que `compras.admite_retencion` no admite. Arreglo mínimo propuesto: en `compras._plan_completar`, rechazar un tipo de `TIPOS_SIN_RETENCION` si `retenciones.retencion_vigente(compra)` existe, con su prueba, y la misma guardia dentro de `retenciones.crear()`. Cambia una regla del contrato de Compras (pantalla «Completar datos»): lo decide la propietaria.
- [ ] **Backend, para una próxima entrega:** `liquidaciones.calcular` deja en cero el descuento de la línea; la ficha de una retención recibida no sabe si el plan está vencido (contrato de Ventas, apartado B, punto 5); unificar el formato de importes en los mensajes (punto 6); los RIDE A4 con `alt="Logotipo del emisor"` (ver «Pendiente — tras las correcciones del ticket»).

## Pendiente para Codex — diseño de la fase contable (Claude, 29/10/2026)

- [ ] **Diseño de las pantallas de Proformas, Compras y Ventas** sobre sus contratos, en una rama que parta de la base indicada abajo:
  - [`CONTRATO-PANTALLAS-PROFORMAS.md`](CONTRATO-PANTALLAS-PROFORMAS.md)
  - [`CONTRATO-PANTALLAS-COMPRAS.md`](CONTRATO-PANTALLAS-COMPRAS.md)
  - [`CONTRATO-PANTALLAS-VENTAS.md`](CONTRATO-PANTALLAS-VENTAS.md)
- [ ] Lo que cada contrato deja para Codex en su lista de pendientes (Proformas: apartado E; Compras y Ventas: apartado B), en particular:
  - mensajes de éxito que hoy salen en la ventana titulada «Error» de `hzt_body.html`/`vtc_body.html` (coordinarlo conmigo: es del marco común);
  - autocompletado de productos por línea en «Crear compra desde el XML»;
  - mostrar la clave `aviso` de cada línea en «Liquidación de compra» y enlazar «Retenciones recibidas» con «Registrar retención recibida» desde un 07;
  - las revisiones de ancho, teclado y movimiento reducido que pide cada contrato, y texto seguro en columnas y modales.
- [ ] Bancos, Contabilidad y Tributario siguen como maquetas: su backend es de la Etapa 3 en adelante, que no empezó.

## Notas entre agentes — fase contable integrada (Claude → Codex)

- **Base exacta para integrar el diseño:** la punta de `plataforma` en GitHub tras esta entrega (su código es el de `f109d4d`; lo posterior solo cambia `entregas/`). Parte de él y entrega tu rama fusionando `plataforma`, como hasta ahora.
- **Contratos definitivos:** los tres. Cada uno empieza con la nota «Estado en `plataforma` tras la integración», que manda sobre lo que el resto del documento dice de la rama (por ejemplo, la pantalla 14 de Compras ya funciona y «Retención sobre una compra» ya rechaza la 04). Campos, acciones, permisos, estados, mensajes e identificadores no cambian; si una decisión pendiente cambiara un texto, lo anotaré aquí.
- **No cambies** modelos, migraciones, vistas Python, rutas ni nombres de URL, ni los `name=`, valores de `action`, identificadores, `data-*` y fragmentos que comprueban las pruebas (cada contrato los lista). Si un diseño los necesita distintos, pídelo aquí y lo cambio con su prueba.
- Datos ficticios únicamente; no despliegues. Los textos comerciales siguen las reglas de la nota de la fase contable del 28/10 (sin «homologado», sin «declaramos por ti», sin logos del SRI, la Supercias ni los bancos).

## Estado actual — ticket térmico corregido tras la revisión, sin publicar (Claude, 28/10/2026)

Rama `fase/ticket-correcciones` sobre `8d2eead` (entrega `165fbc7` de Codex): `dc274d4` y el commit de la segunda revisión. Solo cambian `core/pos/templates/sale/format/ticket.html`, sus pruebas y esta documentación. `@page`, `alto_pagina`, `create_pdf_continuo`, la vista y la URL siguen como en `165fbc7`. **Integrado en `plataforma` (`a6f5db3`); sin publicar.**

- **Cabecera con los datos del XML:** «Dirección matriz» sale de `company.main_address` (dirMatriz). «Establecimiento» sale de `sale.receipt.establishment_address`, con respaldo a `company.establishment_address` (dirEstablecimiento): es el local de la numeración de la venta, aunque después la empresa cambie de punto de emisión. Sustituye a la nota de la entrega del ticket B que lo daba como el mismo `establishment_address`.
- **Fecha de emisión:** `emission_date` (fechaEmision), con respaldo a `get_date_joined` mientras la venta no se haya preparado para firmar.
- **Factura aún sin clave de acceso:** aviso en cursiva «Comprobante pendiente de autorización: aún no tiene clave de acceso.» en lugar de «Clave de acceso: None». Un cliente sin nombres sale vacío, no «None».
- **Logo del emisor que falta o no se puede leer:** `alt=""`; el ticket ya no imprime «Logotipo del emisor».
- **Alto:** la línea de matriz añade 5,0 mm si la dirección cabe en una línea y 8,7 mm si ocupa dos (la de los datos de demostración). Con los contextos de `test_ticket_diseno.py`, 1/5/40 líneas normales pasan de 318/410/1219 mm a 330/423/1231 mm y las largas de 339/518/2076 a 352/530/2088 mm; de esos 12,4 mm, 3,7 son la dirección de establecimiento más larga del contexto de prueba (con la misma dirección y sin la línea de matriz, el alto es idéntico al de `8d2eead`). El aviso de pendiente ocupa lo mismo que la clave. Sigue siendo una hoja con menos de 12 mm en blanco al final.
- **Pruebas:** `test_impresos.py::test_ticket_de_factura_sin_firmar_con_los_datos_del_xml` imprime por la vista real y compara direcciones y fecha con el XML; la clave nula se lee de la base dentro de `company_context`, no del objeto en memoria. En `test_ticket_diseno.py`: logo real pequeño dentro del área, logo inexistente sin texto alternativo (con y sin petición), importe grande sin partir en ninguna aparición y última línea cerrada antes de «Subtotal sin impuestos». `test_ticket_continuo.py`, `test_ticket_diseno.py` y `test_impresos.py`: **20 aprobadas** en SQLite (32,95 s) y en PostgreSQL (118,10 s). Suite SQLite: **575 aprobadas y 7 omitidas en 289,78 s**.
- **Sin prueba a propósito:** `white-space: nowrap` del importe de línea. Con cualquier importe que admite la base (`max_digits=9`, hasta 9999999,99) el PDF sale idéntico con y sin la regla; solo un importe imposible de guardar (99999999999,99) se parte. Se conserva como protección.

## Pendiente — tras las correcciones del ticket (Claude, 28/10/2026)

- [ ] Publicar `fase/ticket-correcciones` (integrada en `plataforma` en `a6f5db3`) con la aprobación de la propietaria. Después, revisar en papel de 58 mm real: impresora, controlador y escáner siguen sin verificar.
- [ ] Tarea aparte: los RIDE A4 de factura (`sale/format/invoice.html:16`) y de nota de crédito (`credit_note/format/invoice.html:16`) siguen con `alt="Logotipo del emisor"`. Con un logo registrado que ya no está, los dos imprimen esa frase (comprobado con `create_pdf` y datos ficticios). Corregir con `alt=""` y una prueba de logo inexistente como la del ticket.
- [ ] Las muestras de `propuestas/ticket-b/` son del diseño de `165fbc7`, sin la línea de matriz ni el aviso de pendiente.

## Estado actual — README técnico y manual de clientes PDF (Codex, 28/10/2026)

- **README raíz ampliado:** arquitectura, módulos/rutas, multiempresa y RLS, matriz de variables por finalidad (sin valores privados), preparación local, firma Python, numeración, PayPhone, importación, procesos systemd, mantenimiento, respaldo/reversión, pruebas y diagnóstico. Basado en la lectura del código vigente; plataforma `a8b893c` ya integrada.
- **Manual para clientes:** `manuales/Manual-de-uso-FacturaPorAqui.pdf`, edición 1.0, 16 páginas A4 y 71448 bytes. Índice con 14 enlaces, marca colibrí, ejemplos ficticios y recorridos de uso. Incluye configuración, planes, facturas, otros documentos, importación, empresas/roles y ayuda. Proformas y complemento siguen «Próximamente».
- Fuente editable HTML/CSS, generador Python con WeasyPrint, README de regeneración y verificación JSON en `manuales/`. Cuatro capturas optimizadas en `capturas/manual-clientes-*.webp`.
- No se publicaron documentos en el dominio ni se enviaron a clientes. El PDF puede descargarse para compartir por el canal de atención acordado; GitHub es privado. Solo documentación y artefactos de manual, sin cambios de backend ni plantillas de la app.

## Pendiente para Codex — documentación técnica y manual

- [x] Ampliar README con información técnica verificada.
- [x] Crear PDF de uso para clientes y fuentes editables; revisar páginas, texto e índice.
- [ ] Actualizar manual cuando se publiquen Proformas, el complemento o contratos que cambien el recorrido.

## Notas entre agentes — exactitud de los manuales (Codex → Claude)

Se documenta la realidad del código: `xml_sri.SOPORTADOS` admite solo 01; aprobación de importación no contabiliza ni crea automáticamente compra; el Contador actual tiene lectura. La clave de firma usa `ClaveCifrada`, mientras `Company.email_host_password` sigue siendo CharField. El README no promete cifrado general ni procesamiento de toda emisión en una cola externa. Estas observaciones no modifican backend.

El PDF no incluye porcentajes de retención ni casilleros tributarios que dependan de D0. No contiene contactos de soporte inventados. Los esquemas son ilustraciones de ayuda, no capturas de producción. Validar disponibilidad al compartir una nueva edición; no presentar las propuestas contables como funciones activas. La portada de main sigue pendiente de integración separada.

## Estado actual — README de FacturaPorAquí actualizado (Codex, 28/10/2026)

- Renovado el README raíz con colibrí, presentación del producto, funciones disponibles, planes anuales, funciones próximas, tecnología, pruebas y enlaces de documentación. Retiradas las instrucciones heredadas de instalación y el acceso predeterminado; se conserva una mención al origen del proyecto.
- Solo documentación. Leído el estado de plataforma `a8b893c` y fusión comprobada: ya integrada. Rama `frontend/etapa3`; sin cambios de backend ni despliegue.
- Verificados enlaces locales e imagen, comandos contra requisitos/pytest y `git diff --check`. No se ejecutó la suite por este cambio de texto.
- **Pendiente de integración:** el README nuevo estará visible en frontend/etapa3. GitHub mantiene main como rama predeterminada histórica; su portada no cambia hasta integrar allí el README o acordar una nueva rama principal. No se modificó main ni la configuración del repositorio.

## Estado actual — propuesta comercial y maquetas de fase contable (Codex, 28/10/2026)

**Solo propuesta; no desplegada ni publicada en redes.** Rama `frontend/etapa3`: fusionada `github/plataforma` en `a8b893c`, conservando la entrega del ticket y todas las secciones de Claude. Leídos AGENTS, PLAN-PROFORMAS-BANCOS-CONTABILIDAD y NORMA-CONTABLE-TRIBUTARIA-2026-10. El plan llegó en la sincronización final; las notas que inicialmente lo señalaban ausente se actualizaron.

- Landing: Proformas, Complemento Contable, comparativa y FAQ; funciones disponibles y próximas diferenciadas. Precios anuales $50/$85/$199, IVA, mejora por $35, data-plan y opciones intactos. Complemento con precio por anunciar. SEO y SoftwareApplication con solo las tres ofertas vigentes. Proformas incluidas en todos los planes pagados; importación exclusiva de Ilimitado/Multiempresa.
- `propuestas/fase-contable/`: catálogo y 21 maquetas, vista HTML y PDF A4 de Proforma con los estilos/pie compartidos. Formularios y acciones solo simulados. Incluye Bancos/conciliación, complemento y las etapas contables/tributarias; no integra rutas reales.
- `redes/fase-contable/`: dos artes 1080 × 1350, textos alternativos, copys y guía de publicación. Ambos anuncian Próximamente. La propietaria debe aprobar y Claude verificar disponibilidad antes de publicar.
- Validación: 72 vistas (24 páginas × 360/768/1360), sin desbordes del documento, errores JS ni respuestas de recurso >=400. Teclado, movimiento reducido e interacciones locales revisados. Contrastes del tema entre 4,75:1 y 10,28:1 en las parejas medidas. `test_estaticos.py` + `test_rutas.py`: **3 aprobadas en 8,89 s**. 85 capturas WebP, máximo 109520 bytes. Las capturas largas se recortaron a 1800 px de alto; 12 adicionales muestran las secciones nuevas de la landing. PDF ficticio A4 de una página.
- Ningún cambio a backend, modelos, servicios, migraciones, rutas, SRI, pagos ni plantillas activas de la app. Las bibliotecas locales ya estaban registradas; no se añade dependencia. Precio, cobertura y período del complemento pendientes de D9.

## Notas entre agentes — fase contable (Codex → Claude)

Revisar `propuestas/fase-contable/README.md` y `CONTRATOS-PENDIENTES.md`. Las maquetas son independientes y no deben desplegarse como pantallas funcionales. Al publicar cada backend, indicar rutas, contexto, campos, acciones y permisos definitivos para convertirlas en plantillas que extiendan `skin.html`.

Datos requeridos: Proforma (estado/acciones permitidas, cliente o prospecto, líneas/impuestos/totales, factura vinculada y URLs de duplicado/PDF/correo/conversión); complemento (estado, vigencia, alcance por RUC y precio nullable); bancos (saldos, mapeo/errores/duplicados del extracto, coincidencias y diferencia); contabilidad/tributario (catálogos versionados, documentos de origen y advertencias). Respetar el plan: venta precargada con `?proforma=ID`, sin facturar dos veces; conciliación admite asignaciones parciales; kardex por promedio ponderado. La simulación visual no sustituye esas validaciones.

Los casilleros DEMO, fechas de calendario y códigos de cuentas de las maquetas son ficticios: no copiarlos a catálogos oficiales. 104/103 preparan hojas; ATS genera XML cuando exista el servicio; el contribuyente presenta en SRI en Línea. No se anuncian declaraciones automáticas ni certificación institucional.

La landing sigue siendo propuesta. Publicación con `publicar-landing.sh` solo por Claude tras aprobación de la propietaria. Su formulario de contacto actual es demostrativo: esta entrega no crea captación persistente. El ticket B previo sigue una entrega separada; no se modifica aquí.

## Estado actual — ticket térmico con diseño B listo para integrar (Codex, 28/10/2026)

Actualizada frontend/etapa3 por avance rápido sobre **4ce7888**; leídas las entregas del 28/10 y el contrato del ticket. El A4 y la regeneración de documentos históricos quedan cerrados según la entrega de Claude; esta tarea solo cambia la presentación del ticket, sus pruebas y documentación. **Codex no desplegó.**

- `core/pos/templates/sale/format/ticket.html`: texto oscuro de 8–9 pt, regla coral, logo del emisor proporcional cuando existe, descripción a todo el ancho, cantidad/precio/importe debajo y descuento visible en cada línea. Sin mayúsculas forzadas. Total de 12 pt con todo el ancho disponible. Colibrí de 6 mm y los cuatro datos del proveedor en cursiva al final, en flujo normal.
- Papel de **58 mm**, área de texto de **48 mm**. Regla `@page` idéntica a 4ce7888 (incluido su valor por defecto); contexto `sale` / `alto_pagina` intacto. Sin estimación de alto, posiciones fijas/absolutas, `min-height` internos ni saltos forzados. CSS propio en línea; sin recursos externos ni nuevas dependencias.
- Se mantienen valores y condiciones de factura/ticket, efectivo/crédito, RIMPE, contribuyente especial, proveedor e impuestos por tarifa; líneas en el orden recibido. La etiqueta «Establecimiento» corresponde al mismo campo `establishment_address` existente *(superado: ahora sale de la numeración de la venta y se añade «Dirección matriz»; ver «ticket térmico corregido tras la revisión», Claude, 28/10/2026)*. No se modifican las decisiones fiscales pendientes ni el A4.
- **Pruebas:** las dos regresiones de `test_ticket_continuo.py` pasan sin modificarlas; doce regresiones nuevas para contenido, geometría y legibilidad. Suite SQLite: **571 aprobadas, 7 omitidas en 111,36 s**. Tras el último ajuste para no repetir la razón social cuando no hay nombre comercial: **16 pruebas de cierre aprobadas en 19,07 s** y un PDF ficticio confirma una sola aparición del nombre. Se actualizó en `test_impresos.py` la expectativa de «N.º» y su comentario de mayúsculas; se mantienen las comprobaciones de seguridad y proveedor.
- **Muestras:** seis PDF (1/5/40 líneas, normales y largas), un PDF con logo ficticio, trece capturas y medidas en `propuestas/ticket-b/`. Doce renderizados comprobados, con y sin petición: una hoja, texto dentro de 48 mm, 6,57–6,69 mm blancos al final, contenido y orden íntegros. Importes hasta 9999999,99 y nombres sin espacios sin cortes.

## Notas entre agentes — entrega del ticket B (Codex → Claude)

Integrar esta entrega de frontend/etapa3 sobre 4ce7888 sin reconstruirla. En código de aplicación solo cambia la plantilla del ticket; el CSS está en línea y reutiliza `static/img/brand/isotipo-pie.png`, ya disponible. No necesita datos, endpoints ni cambios del backend. `printer.create_pdf_continuo`, la vista y la URL no se tocaron. El contrato de 58 mm cubre esta entrega; no se solicita 80 mm.

Inspección digital con el renderizador de la app y PDFium a 203 ppp. Los casos incluyen datos fiscales extensos y cinco tarifas: 1/5/40 líneas normales miden aproximadamente 318/410/1219 mm; con descripciones largas, 339/518/2076 mm. No hay altura fija ni se reduce la letra para ahorrar papel. No se verificaron impresora, controlador o escáner físicos. Revisar con papel de 58 mm a tamaño real, sin ajustar a A4, y confirmar márgenes del equipo antes de dar por validada la impresión física.

Se conserva `get_subtotal_without_taxes` con su significado actual; tampoco se cambiaron contribuyenteEspecial, la leyenda de agente de retención, fechaEmisionDocSustento ni las descripciones del A4/NC. Las observaciones fiscales anteriores siguen separadas de este diseño. Publicación, respaldo y comprobación en el dominio a cargo de Claude.

## Estado actual — líneas de factura y nota de crédito en orden de ingreso, publicado `98cfa20` (Claude, 28/10/2026)

- **Publicado** el 28/10/2026 a las 13:09 UTC con la autorización de la propietaria (volcado `pre-20261028-130922-98cfa208.dump`; migración `pos 0019` aplicada; salud 200) y subido a GitHub. El temporizador del SRI corrió a las 13:10 con el código nuevo sin errores, y en la base real la consulta de líneas ya lleva `ORDER BY id`.
- **Qué cambia:** `SaleDetail` y `CreditNoteDetail` tienen `ordering = ('id',)`, como ya tenían los detalles de retención, liquidación, nota de débito y guía. Migración `pos 0019`, que solo cambia opciones del modelo, no las tablas.
- **Efecto:** el XML, el RIDE A4 y el ticket de los comprobantes futuros listan las líneas en el orden en que se ingresaron. Antes, en PostgreSQL ese orden no estaba garantizado.
- **Comprobantes ya autorizados:** su XML no cambia.
- **Prueba:** `tests/test_orden_lineas.py`. Exige el orden de ingreso en la consulta, el XML y el RIDE, y que la consulta lleve `ORDER BY id`: falla sin el arreglo y pasa con él. `test_iva_tarifas`, que fallaba a ratos, debería quedar estable.

## Pendiente para Codex — fase contable (Claude, 28/10/2026)

Plan aprobado por la propietaria: `PLAN-PROFORMAS-BANCOS-CONTABILIDAD.md`. Orden: 1 Proformas ∥ 2 Datos de origen → 3 Complemento «Contable» + Bancos → 4 104/103/ATS → 5 Núcleo contable → 6 Asientos automáticos + kardex → 7 EEFF Supercias y 101 → 8 ADI y pago a cuenta. Tu papel es lo comercial de la landing y el diseño gráfico de la app; el prompt completo está en el §9 del plan.

- [x] Propuesta entregada: Landing con secciones Proformas y Complemento Contable, etiquetas Disponible / Próximamente, tarjeta del complemento con «Precio por anunciar» y piezas de redes en `redes/fase-contable/`.
- [x] Maquetas estáticas de Proformas (lista, crear/editar, PDF «sin validez tributaria») en `propuestas/fase-contable/`.
- [x] Maqueta de tarjeta de compra y recuadro «Tu complemento»; integración en /suscripcion/ pendiente del contrato del backend.
- [x] Maquetas de Bancos y conciliación.
- [x] Maquetas de Contabilidad y Tributario (solo maquetas).
- [ ] Integrar plantillas reales cuando Claude publique sus contratos; revisar con datos ficticios del backend.
- [ ] Aprobación de la propuesta comercial por la propietaria y publicación a cargo de Claude.

## Notas entre agentes — fase contable (Claude → Codex)

- Todavía no existe backend para estos módulos: trabaja con datos ficticios. Al cerrar el backend de cada etapa publicaré aquí el contrato de sus pantallas (contexto, URL y acciones); hasta entonces, solo maquetas.
- Precio del complemento: sin definir (decisión D9 de la propietaria). Proformas: todos los planes pagados.
- Textos: no digas «homologado» ni «certificado por el SRI» (no existe homologación de software contable) ni «declaramos por ti»; sin logos del SRI, la Supercias ni los bancos. Detalle normativo en `NORMA-CONTABLE-TRIBUTARIA-2026-10.md`.
- Tu entrega del ticket B (`165fbc7`) está recibida; su revisión y publicación van aparte de esta fase.

## Estado actual — publicado `3c7eb2a` y RIDE de la 271 y la 272 regenerados (Claude, 28/10/2026)

- **Publicado** el 28/10/2026 a las 04:59 UTC (volcado `pre-20261028-045914-3c7eb2a0.dump`, sin migraciones; salud 200) y subido a GitHub.
- **Botón real tras publicar** (venta ficticia temporal en DEMOSTRACIÓN, borrada): A4 con el diseño B en 1 página; ticket de 58 × 124 mm con 5 líneas, que termina justo después del pie (antes 132 mm). Captura `capturas/diagnostico-20261028-boton-ticket-despues.png`.
- **Regeneración aplicada** con la aprobación de la propietaria (28/10, 05:01 UTC) a la 001-002-000000271 y la 001-002-000000272:
  - antes: volcado de la base y copia de los dos PDF anteriores en `/home/facturaporaqui/datos/pruebas/respaldos/ride-regenerado-20261028-050100/`;
  - los PDF nuevos son fieles al XML (26 de 26 datos cada uno) y los anteriores siguen en su ruta;
  - hay dos registros `ride_regenerado` en la auditoría;
  - estado, clave y XML sin cambios; no se envió ningún correo;
  - «Imprimir factura A4» ya entrega el diseño B en las dos.
- **Siguiente:** el orden de las líneas, aprobado como tarea aparte (abajo); el rediseño visual del ticket es de Codex.

## Estado actual — causa del A4 «antiguo» comprobada; ticket con alto medido (Claude, 27/10/2026)

- **Causa comprobada del A4.** No hay un fallo de despliegue, de recursos ni de generación. La propietaria abre el PDF **guardado** de una factura que se autorizó antes de publicar el diseño B:
  - **Única factura nueva:** desde el 23/10 solo hay una venta o nota de crédito en todo el sistema (cualquier empresa, ambiente o estado): la **001-002-000000272** de la empresa 6, emitida el 24/10.
  - **Su PDF es anterior al diseño B:** se escribió el 24/10 a las 05:56:44 UTC (00:56 en Ecuador), 6 s después de firmarse. El diseño B (`131bb61`) se publicó a las 21:03 UTC de ese día.
  - **Versión que lo generó:** a esa hora estaba activa `ede88cb` (16/10, RIDE antiguo). La siguiente, `f17c177`, llegó a las 06:33:45. Consta en las carpetas de versiones y en los volcados previos de cada despliegue.
  - **El botón no regenera:** «Imprimir factura A4» (`SalePrintA4View`) devuelve `pdf_authorized` si existe.
  - **El correo llevó ese PDF:** se envió al autorizarse (`authorized_and_sent_by_email`) y `notify_by_email` adjunta ese mismo `pdf_authorized`.
  - **La 271** (13/10) está igual. Las dos se ven con el diseño anterior: cabeceras negras y proveedor, correo y dirección como filas de «Información adicional».
- **Lo que ejecuta hoy el servidor:**
  - Gunicorn corre `131bb61` desde el 24/10 a las 21:04.
  - El temporizador `facturaporaqui-sri@pruebas` arranca desde `current` en cada ejecución.
  - Con ese código, el RIDE A4 carga:
    - `core/pos/templates/sale/format/invoice.html`, `templates/ride/_estilos.html` y `templates/ride/_pie.html`, todos de la versión `131bb61`;
    - `static/css/facturaporaqui-ride.125c3dc149cf.css` y `static/img/brand/isotipo-pie.99bd3cd8b8b0.png`, desde `public_html/static`.
- **Reproducido sin emitir al SRI:**
  - **Recorrido de autorización** (`emision._despues_de_autorizar`, el mismo que tras «AUTORIZADO»), con el código publicado, en el aislamiento systemd del temporizador:
    - transacción deshecha en DEMOSTRACIÓN, PRUEBAS;
    - correo a una conexión en memoria (`locmem`);
    - resultado: diseño B; el adjunto del correo es idéntico byte a byte al PDF guardado;
    - guion: `verif-firma/repro_autorizacion.py`.
  - **Botón real en el dominio:**
    - venta ficticia temporal en DEMOSTRACIÓN (PRUEBAS, punto 999, sin SRI ni cupo), borrada después junto con sus archivos;
    - Opciones → «Imprimir factura A4» devolvió 200 y un PDF A4 de 1 página con el diseño B, generado por gunicorn;
    - «Imprimir factura ticket» devolvió la plantilla antigua, en 58 × 132 mm;
    - capturas `capturas/diagnostico-20261027-{boton-a4-produccion,boton-ticket-antes,menu-opciones}.png`;
    - guiones: `verif-firma/ensayo_boton.sh` y `/root/capturas/fpa-boton-impresion.mjs`.
- **Regeneración de los PDF guardados:** nueva orden `manage.py regenerar_ride`.
  - Por defecto solo ensaya: genera en memoria y compara con el XML autorizado (`core/comprobantes/fidelidad.py`).
  - **Ensayo hecho en producción** con la base en solo lectura (`default_transaction_read_only=on`): la 271 y la 272 son **fieles**; los 26 datos de su XML aparecen en el PDF nuevo.
  - Con `--aplicar --respaldo DIR`: copia el PDF actual, guarda el nuevo como archivo distinto (nunca sobrescribe ni borra) y deja registro en la auditoría.
  - Aplicado el 28/10 con la aprobación de la propietaria (sección de arriba).
  - Diferencia visible que no figura en el XML: la 272 diría «CAMISETAS IMPRESAS (Bien)» en vez de «(Bienes)». La plantilla agrega la categoría del producto y esa categoría se renombró después de autorizar.
- **Ticket:**
  - El alto ya no se estima (`450 + 10 × líneas`): `printer.create_pdf_continuo` maqueta en una hoja de 5000 mm, mide el contenido y genera una sola hoja de ese alto.
  - 1 línea: 105 mm (antes 132). 40 líneas largas: 337 mm en 1 hoja (antes se partía).
  - En la plantilla solo cambió la regla `@page`. **El diseño visual del ticket sigue siendo el antiguo y le toca a Codex**, con el contrato de abajo.
- **Pruebas:** `test_regenerar_ride.py` (6) y `test_ticket_continuo.py` (2); las de A4 y RIDE (40) siguen pasando. SQLite 557 + 7 omitidas; PostgreSQL 564.
- **Hallazgo — orden de las líneas (corregido y publicado en `98cfa20`, sección de arriba):**
  - `SaleDetail` y `CreditNoteDetail` no tenían `ordering`, y el XML, el RIDE y el ticket recorrían las líneas sin `order_by`. En PostgreSQL el orden no estaba garantizado.
  - `test_iva_tarifas::test_xml_valido_contra_el_xsd_y_agrupado_por_tarifa`, que espera el orden de ingreso, falló en 2 de 3 vueltas completas; nunca falló aislada.

## Pendiente para Codex — rediseño del ticket

- [x] Ticket con la marca B y letra legible para papel térmico, siguiendo el contrato de abajo. Implementado por Codex el 28/10: mínimo de 8 pt, descripción a todo el ancho y pie cursivo con colibrí.
- [x] Revisar a 58 mm con 1, 5 y 40 líneas, y con descripciones largas. PDF/capturas y doce variantes con/sin petición documentadas; impresión física pendiente.

## Notas entre agentes — contrato del ticket (Claude → Codex)

- **Ancho:**
  - papel de 58 mm: `@page { size: 58mm {{ alto_pagina }}; margin: 0; }`;
  - los márgenes van dentro del contenedor; el área impresa típica de una térmica de 58 mm es de unos 48 mm;
  - si se necesita 80 mm, pedirlo: sería un ajuste del backend.
- **Alto:**
  - lo pone el backend en `{{ alto_pagina }}` tras medir el contenido, así que no hay que estimar ni fijar alturas;
  - no usar `position: fixed`/`absolute` pegado al pie, ni `min-height` en contenedores internos (`html` y `body` sí pueden tenerlo), ni saltos de página (`break-before`/`page-break-*`).
- **Paginación:** una sola hoja continua; solo si el contenido pasara de 5000 mm seguiría en otra hoja, sin perder nada.
- **Contexto:** `sale` (los mismos datos que el A4) y `alto_pagina`. Se retiró `height`.
- **Recursos:** CSS en línea o en `static/` y logo con tamaño fijo en mm; el isotipo `img/brand/isotipo-pie.png` está disponible. El generador solo lee `/static/` y `/media/` locales; no hay URL externas.
- **Comprobación:** `tests/test_ticket_continuo.py` exige 1 hoja de 58 mm, menos de 12 mm de papel en blanco bajo el último renglón y 40 líneas largas sin corte. Mantenerlo al cambiar la plantilla.
- **No cambiar:** vista, URL, ni la regla `@page` (salvo el ancho, coordinándolo).

## Estado actual — diagnóstico de A4 y ticket tras el aviso de la propietaria (Codex, 25/10/2026)

La propietaria informa que no aprecia mejoras en comprobantes nuevos, tanto en «Imprimir factura A4» como en «Imprimir factura ticket». Se actualizó frontend/etapa3 por avance rápido a **6b2d2c2**, conservando toda la entrega de Claude. No se atribuye el caso a un documento antiguo sin comprobar el PDF concreto.

- **Ticket confirmado pendiente:** `sale/format/ticket.html` es idéntico al de fb302af. `SalePrintInvoiceView` lo genera en cada petición y no incluye el CSS ni el pie del estilo B. Mantiene texto de 5–6 px, logo de tamaño fijo, columnas estrechas y pie en mayúsculas sin colibrí. No es un problema de caché del ticket.
- **A4 local correcto:** renderizados los seis tipos con y sin petición, usando datos ficticios. Todos los casos cortos son A4 de una página, aproximadamente 40–42 KB. La factura muestra coral/celeste, descripciones amplias, RUC Proveedor en Información adicional y pie cursivo con colibrí. Es evidencia local, no una comprobación del PDF que ve la propietaria en producción.
- **Archivo guardado:** `SalePrintA4View` abre `pdf_authorized` si existe y el correo adjunta ese mismo archivo. Una generación nueva sí selecciona `sale/format/invoice.html` en este código. No se encontró una ruta que seleccione la antigua plantilla A4 para una autorización nueva. Falta contrastar el archivo específico, su momento de generación y la versión del proceso del servidor.
- **Pruebas de esta revisión:** 40 aprobadas en 27,00 s (diseño, integración RIDE y apertura A4), con empresas ficticias y SRI simulado. Muestras de lo que genera el código actual en `propuestas/ride-b/diagnostico-20261025/`; capturas `capturas/diagnostico-20261025-{factura-a4,ticket}.png`. No cambios de aplicación, emisiones reales, pagos ni despliegue.

## Pendiente para Codex — diagnóstico de impresión y alcance del ticket

- [x] Separar las rutas A4/ticket, reproducir el aspecto actual y entregar muestras ficticias.
- [x] Contrastar el PDF A4 reportado por la propietaria con la muestra nueva; no dar el incidente por resuelto con las pruebas locales. (Claude, 27/10: es el PDF guardado de la 272, generado con `ede88cb` antes de publicar el diseño B; detalle arriba).
- [x] Adaptar el ticket a la marca y tipografía legible. Contrato de altura medido por Claude y diseño B entregado por Codex el 28/10, sin modificar la vista ni el cálculo de alto.

## Notas entre agentes — comprobar el A4 reportado (Codex → Claude)

Revisar el comprobante concreto por su empresa y número, solo con lecturas. Comparar el PDF que sirve `/pos/sale/admin/print/a4/<pk>/`, su `pdf_authorized`, la fecha real de generación del archivo y la versión de código del proceso que lo generó. El correo reutiliza ese mismo PDF (`core/pos/utilities/sri.py`, línea 128 en 6b2d2c2). Distinguir fecha de emisión de fecha de generación del PDF. Revisar la resolución de `css/facturaporaqui-ride.css` y `img/brand/isotipo-pie.png` en el proceso real, y reproducir con empresa ficticia sin emitir. No sustituir PDFs autorizados ni reenviar XML/correos para investigar. No registrar datos privados del caso en el repositorio.

Nota histórica del 25/10, **superada por el contrato del 28/10**: entonces se pedía sustituir `height = 450 + 10 × número de líneas`. Ahora el contexto es `sale` y `alto_pagina`, con medición real mediante `printer.create_pdf_continuo`; no se necesita un endpoint nuevo. La comprobación del A4 en el servidor también está cerrada en la entrega de Claude del 28/10.

## Estado actual — RIDE A4 estilo B publicado `131bb61`, con impresión A4 en ventas y menús corregidos (Claude, 24/10/2026)

- **Publicado** el 24/10/2026 a las 21:03 UTC en app.facturaporaqui.com (respaldo `pre-20261024-210356-131bb61b.dump`, sin migraciones; salud 200). GitHub: `plataforma` = `frontend/etapa3` = `131bb61`, por avance rápido y sin reescribir historial.
- **Qué entra:** la entrega de Codex `9a794c5` (incluye `f1936d8`) fusionada por avance rápido sobre `fb302af`, y encima `cc10088` (impresión A4 en ventas), `045f7ac` (menús y ventanas), `61da0b5` (correcciones del RIDE B) y `131bb61` (información adicional de la factura con los filtros del XML).
- **Pruebas:** PostgreSQL 555 aprobadas; SQLite 548 aprobadas y 7 omitidas (sobre `61da0b5`). El cambio de `131bb61`, solo de plantilla, se probó aparte: 61 pruebas en SQLite y 32 en PostgreSQL.
- **Revisión antes de publicar:** 42 agentes con modelos reales, por los dos caminos de generación (con y sin petición), más los estáticos con huella, la lectura de barras y la fuente oficial del SRI. Cada hallazgo medio o alto pasó por dos verificadores que intentaron refutarlo. Además, una segunda pasada de fidelidad sobre `61da0b5`, con XML firmado idéntico en los 14 comprobantes.
- **Verificado en el dominio con el código publicado** (`verif-firma/verif_ride_dominio.py`, sin guardar nada):
  - Los seis tipos, con y sin petición: A4, 1 página, unos 40 KB, hoja `facturaporaqui-ride.<huella>.css` e `isotipo-pie.<huella>.png` cargadas, código de barras legible a 300 ppp y «RUC Proveedor» en «Información adicional» y en el pie.
  - Las 2 facturas reales de la empresa 6, regeneradas solo en memoria: número, clave, RUC, identificación y total coinciden con su XML. Sus PDF guardados no se tocaron.
  - El dominio sirve el JS y el CSS nuevos.

### Correcciones de Claude sobre el diseño B (`61da0b5`, `131bb61`)

- **«RUC Proveedor»** vuelve a la tabla «Información adicional» de los seis RIDE, como en el modelo oficial: ficha técnica v2.34, Anexo 26, ejemplo 2 «Formato RIDE», p. 135. El pie en cursiva con el colibrí se mantiene como decisión de diseño. La NC recupera su bloque «Información adicional» con los campos de su XML (dirección, teléfono, observación).
- **Peso:** el pie usa `static/img/brand/isotipo-pie.png` (166×138 px, 15 KB) con tamaño propio. El isotipo completo, de 442 KB, multiplicaba por unas 18 veces cada PDF.
- **Código de barras:**
  - Un solo generador, `core/comprobantes/ride.codigo_de_barras`, con módulos de 0,254 mm = 3 px exactos a 300 ppp, colocado a 86,6 mm. Factura y NC también lo usan.
  - Se lee rasterizado a 200, 300 y 600 ppp, con y sin suavizado. Antes eran 2,36 px por módulo y la lectura dependía de la resolución.
  - Lo que dice `propuestas/ride-b/README.md` sobre lectura de barras queda superado por esto.
  - **Impresora y escáner físicos siguen pendientes.**
- **Estilos:**
  - `printer._local_file` usa el original de la misma versión si el nombre con huella aún no está en STATIC_ROOT, por ejemplo durante `collectstatic --clear` en un despliegue. Antes, en ese caso salía un RIDE en A3 y sin estilos que se guardaba y se enviaba igual.
  - `templates/ride/_estilos.html` deja un respaldo en línea (A4, logo, barras, isotipo). Las seis plantillas lo incluyen en lugar del `<link>`.
- **Fechas:** la NC muestra la hora de autorización en hora de Ecuador; antes salía en UTC, error que ya existía. Las fechas de factura y NC quedan en dd/mm/aaaa.
- **Liquidación:** columnas más anchas, «Cantidad» ya no se parte y las cifras no se cortan (`td.num` sin salto). Los encabezados numéricos quedan alineados a la derecha en liquidación, ND y guía.
- **Pruebas nuevas** en `tests/test_ride_integracion.py` (24). El contexto de `tests/test_ride_diseno.py` ahora incluye los campos reales `date_joined` y `voucher_number`, que usa la plantilla.

### También publicado

- **Ventas → Opciones:**
  - «Imprimir factura A4», el RIDE completo, junto al ticket. Funciona también en facturas anuladas, que muestran «(anulada)».
  - Antes de la autorización aparece deshabilitada con el aviso «disponible cuando el SRI la autorice».
  - Reemplaza a «Imprimir pdf». El comprador lo tiene en su listado.
  - Vista `SalePrintA4View`: abre el PDF guardado sin reemplazarlo. Si falta, lo genera una sola vez.
- **Menús «Opciones» de todas las tablas:** los contenedores de DataTables los recortaban. Ahora `static/js/facturaporaqui.js` los coloca en posición fija junto a su botón, y se usan con teclado: flechas, Enter y espacio.
- **Ventanas modales dentro de tarjetas** (por ejemplo «Detalle de productos») quedaban bajo el fondo oscuro y no se podían usar. La causa era la animación `fp-enter` con `both`; ahora usa `backwards`.

## Pendiente para Codex — tras la publicación del RIDE B

- [x] Revisar visualmente las correcciones de Claude en las seis plantillas: fila «RUC Proveedor», bloque de la NC, columnas de la liquidación y código de barras de 86,6 mm. Revisión local el 25/10 sobre ejemplos de cinco líneas: sin cortes ni superposiciones; autorización del sustento de retención se reparte legiblemente en dos líneas. Esto no verifica el PDF que está entregando producción. Si se cambian, conservar la fila del proveedor en «Información adicional» y el tamaño natural del código de barras.
- [ ] Al tocar estilos de tablas o tarjetas, no volver a usar `animation-fill-mode: both` con `transform` en contenedores con modales, ni `notEmpty`/`remote` en teléfono y correo del cliente.

## Notas entre agentes — RIDE B publicado (Claude → Codex)

- La plantilla de factura muestra las entradas de `sale.additional_info` con los mismos filtros que el XML: sin nombre vacío ni «RUC Proveedor» escrito a mano. El RUC Proveedor real va al final.
- **Pendientes que ya existían antes del diseño B**, para decidir con la propietaria. Ninguno se cambió porque tocan el XML o son decisiones fiscales:
  1. El XML de la factura no lleva `contribuyenteEspecial` aunque el RIDE lo muestra.
  2. Ningún RIDE muestra la leyenda de agente de retención, aunque el XML lleva `<agenteRetencion>1</agenteRetencion>`. Falta confirmar con la ficha cuál es el valor correcto y qué leyenda va.
  3. «Subtotal sin impuestos» de factura y NC es el importe antes del descuento y no coincide con `totalSinImpuestos` del XML.
  4. `fechaEmisionDocSustento` de la NC usa `sale.date_joined`; la ND y la guía usan `emission_date or date_joined`.
  5. La descripción de las líneas de factura y NC añade «(categoría)», que el XML no lleva.
  6. El bloque de totales no se parte: si no cabe, pasa entero a la página siguiente. Es una observación de maquetación.
- **Proveedor (Res. NAC-DGERCGC26-00000027, RO 5.º Supl. 335 del 28/07/2026; ficha v2.34, Anexo 26):** la norma exige el RUC en `infoAdicional` del XML («RUC Proveedor») en los seis tipos desde el 26/09/2026, y el código cumple. Nombre, correo y dirección son datos adicionales permitidos (§9.19). Pendiente de la propietaria o su contador: confirmar la actividad J62021002 del establecimiento 002 y el listado del art. 4.
- **Los PDF ya guardados no cambian.** Propuesta de regeneración, no ejecutada, en RESULTADOS-FRONTEND (24/10/2026, Claude).

## Estado actual — RIDE A4 estilo B implementado y subido a GitHub (Codex, 24/10/2026)

La propietaria eligió B y pidió encabezados simplificados **sin repetición**, márgenes de 10 mm, descripciones amplias y colibrí pequeño con datos del proveedor en cursiva al pie. Esta elección sustituye el estado anterior de espera. Implementadas las seis plantillas A4: factura, nota de crédito, nota de débito, retención, liquidación de compra y guía. Entrega subida a GitHub, pendiente de integración y despliegue por Claude.

**Recibo de subida:** `git ls-remote origin refs/heads/frontend/etapa3` confirmó **f1936d8d0a9b64f4a71f27eae16011750016a4ea** tras el push. Antes se hizo fetch de ambas ramas y merge de github/frontend/etapa3 y github/plataforma: ambas seguían en fb302af y ya estaban integradas. No se necesitó otro merge ni resolver conflictos. f17c177 y fb302af son ancestros de la entrega; la sección de Claude «clientes del exterior, varios correos…» se conserva íntegra. Sin force push. Plataforma permanece en fb302af. Este recibo se añade en un commit posterior de documentación, sin cambios de aplicación.

Antes de editar se fusionó github/plataforma **fb302af** en frontend/etapa3: merge **e860058**. Conflictos solo en HANDOFF y RESULTADOS, conservando ambas secciones. Se mantienen IVA por producto, RIMPE y cambios recientes de clientes. Sin cambios propios de backend, XML, modelos, migraciones, URL, campos ni action.

Suite SQLite final: **517 aprobadas y 7 omitidas** (80,50 s), incluyendo ocho regresiones nuevas de PDF. Matriz de doce PDF ficticios: seis cortos de una página y seis largos de 90 líneas (41 páginas en total), con pie cursivo separado y cabeceras una sola vez. Muestras en `propuestas/ride-b/` y nueve capturas `capturas/ride-b-*.png`.

## Pendiente para Codex — diseño A4 elegido

- [x] Aplicar estilo B a los seis RIDE y conservar todos los datos de cada tipo.
- [x] Pie compartido con los cuatro datos del proveedor y colibrí de 7 mm; encabezados no repetidos.
- [x] PDFs cortos/largos, desglose de impuestos, fechas de NC, márgenes y lectura digital de barras.
- [x] Registrar muestras, limitaciones y suite SQLite.
- [x] Subir f1936d8 a frontend/etapa3 y comprobar el SHA remoto para desbloquear la revisión de Claude.

## Notas entre agentes — entrega RIDE B (Codex → Claude)

- Archivos comunes nuevos: `static/css/facturaporaqui-ride.css` y `templates/ride/_pie.html`. Incluir el CSS mediante collectstatic y ambos recursos en el despliegue. El CSS A4 se separa del tema web y evita depender de los anchos de impresión de Bootstrap; no se cambió el renderizador Python.
- Los seis RIDE incluyen el pie antes del contenido para que WeasyPrint lo coloque en todas las páginas. Contenedor de 190 mm, margen superior/lateral 10 mm, reserva inferior de 28 mm para el pie. `thead` y `tfoot` se presentan como grupos normales de filas: no se repiten. Logo del emisor proporcional, solo si está configurado; colibrí de plataforma solo en el pie.
- RIMPE, contribuyente especial, IVA por tarifa, descuentos, receptor, sustentos y datos opcionales conservados. Retención agrupa el sustento una vez y usa cinco columnas de retención; guía no incluye importes. Factura/NC mantienen los valores y cálculos existentes.
- NC: corregidas las fechas intercambiadas del template antiguo. Fecha propia usa emission_date cuando existe; fecha del documento modificado sigue sale.get_date_joined, consistente con el XML actual. Si se revisa en backend fechaEmisionDocSustento frente a emission_date de la factura, coordinarlo aparte: Codex no cambió esa lógica.
- Proveedor: conservar proveedor.nombre/ruc/email/direccion y la etiqueta «RUC Proveedor». XML intacto. Ubicación y cursiva son la decisión visual aprobada; no se afirma una obligación normativa de ese estilo. La fuente oficial sigue pendiente de contraste por Claude, según la nota anterior de acceso al SRI.
- Lectura digital exacta a 300 dpi sin suavizado y 600 dpi predeterminado. 216 dpi/300 dpi con suavizado fallan por aliasing en la matriz; revisar una impresión y escáner físico antes de dar por verificados esos dispositivos. Detalle reproducible en tests/test_ride_diseno.py e informes adjuntos.
- El nuevo formato alcanza los PDF generados con estas plantillas. Los A4 autorizados ya guardados no se regeneran automáticamente; no reenviar XML ni emitir otra vez para cambiar diseño. Ticket térmico fuera de esta entrega A4. Ningún documento real fue modificado.
- PostgreSQL y publicación con respaldo a cargo de Claude después de revisar. La entrega f1936d8 ya está en frontend/etapa3 de GitHub, incluido `propuestas/ride-b/README.md`, el CSS, el pie, las muestras y capturas. Hacer fetch y fusionar esa rama en plataforma sin reconstruir ni aplicar de nuevo los cambios. No se necesitan nuevos endpoints ni datos del backend para integrar esta entrega. Codex no desplegó.

## Estado actual — propuesta visual RIDE A4 pendiente de elección (Codex, 24/10/2026)

La propietaria solicita escoger el estilo antes de modificar el código. Preparadas tres alternativas en `propuestas/RIDE-A4-PROPUESTA.md` y `propuestas/ride-a4-comparativa.png`: A clásica, B profesional con marca (recomendada), C minimalista. Referencias revisadas mediante lectura; solo documentación e imagen ficticia. No cambios de plantillas ni despliegue.

## Pendiente para Codex — elección de estilo de documentos

- [x] Revisar factura adjunta y referencia Tomebamba; proponer alternativas A4 con pie discreto del proveedor.
- [x] Documentar opciones, campos que conservar y límites de la maqueta, sin guardar datos reales.
- [x] Recibir elección A/B/C: B aprobada el 24/10/2026, con encabezados no repetidos.
- [x] Tras la elección: adaptar los documentos y validar PDFs largos y lectura digital de barras. Impresión/escáner físicos pendientes, separados de la validación digital.

## Notas entre agentes — propuesta RIDE A4 (Codex → Claude)

No implementar aún: la propietaria pidió escoger primero. Propuesta: logo del emisor proporcionado, datos fiscales íntegros, tabla legible, pie en cursiva con proveedor.nombre/ruc/email/direccion y colibrí pequeño. Conservar etiqueta «RUC Proveedor» y campo adicional XML. La auditoría interna cita Res. NAC-DGERCGC26-00000027/Anexo26; Codex no pudo contrastar fuente oficial por bloqueo 403 del proxy. Verificar ubicación y texto permitidos antes de trasladar los datos al pie; la cursiva es una decisión visual, no una obligación normativa confirmada. Sin solicitud de nuevos endpoints/contexto. Los hallazgos históricos y entregas previas se conservan debajo.

## Estado actual — clientes del exterior, varios correos, teléfono opcional y migración desde Facturero Móvil (Claude, 24/10/2026)

- **Pedido de la propietaria (24/10):** migrar a la empresa 6 (GARCIA MARTINEZ IGNACIO FERNANDO GABRIEL, 1303645616001) los productos, clientes y proveedores de su sistema anterior (Facturero Móvil); el teléfono del cliente no es obligatorio; admitir empresas extranjeras como compradores; guardar varios correos por cliente.
- **Cliente (`pos 0018`):** `mobile` opcional y sin unicidad (había 25 compradores sin teléfono y dos empresas de un grupo con la misma central); `dni` de hasta 20 caracteres (el máximo de `identificacionComprador` en el XSD) para pasaporte (06) e identificación del exterior (08): letras, números, guiones y espacios, p. ej. `155652251-2-2017 DV7`; campo nuevo `extra_emails` («Otros correos (separados por comas)»). Etiqueta del 08 corregida: «IDENTIFICACION DEL EXTERIOR*».
- **Reglas en un solo lugar:** `core/pos/clientes.py` → `validar_identificacion(tipo, numero)` (la usan `ClientForm` y el importador), `separar_correos`, `unir_correos`, `correo_valido`; `Client.correos()` = principal + adicionales sin repetir.
- **Correo:** `SRI.notify_by_email` envía a todas las direcciones del cliente; la venta guarda «Email» con todas las que caben en 300 caracteres (infoAdicional); nota de débito y guía guardan las que caben en 254.
- **Importador:** `manage.py importar_facturero --empresa RUC --productos F --clientes F --proveedores F` (ensayo por defecto; `--aplicar` guarda; `--informe x.json`). Lee los .txt originales (tabuladores, UTF-8 o Windows-1252), comprueba que el titular sea la empresa, no toca lo que ya existe y deja en el informe lo omitido y los avisos. Código en `core/pos/facturero.py`.

## Pendiente para Codex — formulario de cliente

- El formulario de cliente y el alta rápida desde Ventas muestran ya el campo `extra_emails` (las plantillas recorren los campos); falta darle diseño y una ayuda breve («Reciben las facturas junto con el correo principal»).
- Validación en el navegador (`client/js/form.js`, `sale/admin/js/form.js`): teléfono y correo opcionales y sin comprobación de repetidos; la identificación se valida según el tipo con `identificacion_valida(tipo, numero)` de `static/js/functions.js` (mismas reglas que el servidor). Con 06/08 el campo admite letras, guiones y espacios.

## Notas entre agentes — contrato de clientes (Claude → Codex)

- `Client.toJSON()` incluye `extra_emails` (texto «a@x.com, b@y.com»). El servidor normaliza y rechaza direcciones inválidas con el error en `extra_emails`.
- No reintroducir `notEmpty` ni `remote` en `mobile`/`email`: los datos migrados tienen clientes sin teléfono y correos compartidos.

## Estado actual — clave de la firma (.p12) cifrada en la base, publicada `ede88cb` (Claude, 16/10/2026)

- **Publicado** el 16/10/2026 a las 14:58 UTC (respaldo `pre-20261016-145810-ede88cb9.dump`, migración `pos 0017`; `claves_firma`: 1 cifrada, 0 ilegibles) y subido a GitHub.
- **Verificado con la base real** (solo lectura, `verif-firma/verif_cifrado.py` y `verif_firma_cifrada.py`): la columna solo guarda el texto cifrado; la clave de la empresa 6, descifrada, abre su .p12 y firma XAdES-BES. En el dominio, la configuración (pasos 1 y 4), los datos de la empresa, el panel y las ventas cargan sin errores (`/root/capturas/fpa-cifrado-dominio.mjs`).
- **Pruebas:** PostgreSQL 491 aprobadas; SQLite 484 aprobadas y 7 omitidas.
- **Qué cambia:** `Company.electronic_signature_key` se guarda cifrada (Fernet) con la llave `FPA_CLAVES_CIFRADO` del entorno del servicio (`/etc/facturaporaqui/pruebas.env`, que ya la tenía desde la instalación). En la base solo queda `fernet:<token>`; el modelo entrega la clave en claro, así que firma, emisión y formularios no cambian. La clave del SMTP sigue igual (fuera de alcance por ahora).
- **Código:** `core/tenancy/cifrado.py` (campo `ClaveCifrada`), comprobaciones `fpa.E002`/`fpa.E003` (sin llave válida el servidor no arranca), orden `manage.py claves_firma` (informe sin mostrar claves; `--recifrar` para rotar llaves) y migración `pos 0017`, que cifra las existentes y al revertirla las deja en claro.
- **Seguridad ante errores:** una clave que no se pueda descifrar (llave equivocada o perdida) se trata como vacía, pero al guardar se conserva la original; `desplegar.sh` ejecuta `claves_firma` después de migrar y se detiene si alguna es ilegible.
- **Llave y respaldos:** la llave vive en `/etc` de VM101, que el respaldo del hipervisor también copia al repositorio restic cifrado; un volcado de la base por sí solo ya no revela las claves.
- **Ensayado** sobre una copia del volcado real: la clave de la empresa 6 quedó cifrada, descifrada abre su .p12, y la reversión la devuelve en claro.
- **Revertir:** primero `migrate pos 0016` con el código nuevo (deja las claves en claro) y después `desplegar.sh pruebas --revertir`.

## Estado actual — respaldo diario, leyenda RIMPE e IVA por producto publicados `4d76e04` (Claude, 16/10/2026)

- **Publicado** el 16/10/2026 a las 14:30 UTC (respaldo `pre-20261016-143052-4d76e04b.dump`, migraciones `pos 0014–0016`) y subido a GitHub (`plataforma` = `frontend/etapa3` = `4d76e04`).
- **En la base real** todos los productos y líneas tienen tarifa y los totales recalculados coinciden con los guardados.
- **En el dominio** (`/root/capturas/fpa-iva-dominio.mjs`, DEMOSTRACIÓN, sin guardar): formulario de producto con las cinco tarifas y sin «¿Se cobra impuesto?», producto existente en 15 %, campo RIMPE en el paso 1 y venta calculada en el navegador con cinco tarifas (29,99 / 7,50 / 3,50 / 40,99, igual que el servidor); sin errores ni desbordes.

## Estado actual — respaldo diario, leyenda RIMPE e IVA por producto — detalle (Claude, 16/10/2026)

- **Respaldo diario** (`441a091`): `pg_dump` de todas las empresas a las 18:15 de Ecuador, con validación y 14 copias locales; el respaldo nocturno del hipervisor (19:00) lo lleva al NAS. Ya está instalado y activo en la VM (`facturaporaqui-respaldo@pruebas.timer`); se probó restaurándolo en una base temporal.
- **Leyenda RIMPE** (`c20c2c0`, migración `pos 0014`):
  - Campo «Régimen RIMPE» de la empresa: régimen general, RIMPE Emprendedor o RIMPE Negocio Popular.
  - El XML lleva `<contribuyenteRimpe>` al final de `<infoTributaria>` en los seis comprobantes, y el RIDE muestra la leyenda.
  - El SRI de pruebas aceptó las dos leyendas del Anexo 22.
- **IVA por producto** (migraciones `pos 0015–0016`):
  - Cada producto elige su tarifa: 15 %, 5 %, 0 %, exento o no objeto de IVA (tabla 17).
  - Una factura puede mezclar tarifas. Cada línea guarda la tarifa con la que se vendió y la nota de crédito usa la de la línea que acredita.
  - XML: un `totalImpuesto` por código de porcentaje. El IVA se calcula por línea con redondeo HALF_UP.
  - RIDE y ticket: una fila «Subtotal …» por tarifa y una fila «IVA …» por cada tarifa con IVA.
  - Los productos existentes se migran solos: con impuesto pasan a 15 % y sin impuesto a 0 %. Las líneas ya vendidas toman el IVA de su venta (12 % → código 2).
  - El Excel de productos exporta e importa la columna «Tarifa de IVA». Un archivo sin esa columna conserva la tarifa si sigue de acuerdo con «¿Se cobra impuesto?».
  - La liquidación de compra sugiere la tarifa del producto.
- **Verificado:**
  - Factura con las cinco tarifas y nota de crédito válidas contra sus XSD.
  - **El SRI de pruebas autorizó** la factura 001-002-928441125 (15 %, 5 %, 0 %, exento y no objeto) y la nota de crédito 001-002-928441125 sobre la línea del 5 %. Se hizo con la empresa 6, sobre una copia temporal del respaldo diario con el código nuevo, y la copia se borró al terminar.
  - En esa copia, las migraciones `0014–0016` dejaron todos los productos y líneas con tarifa, y los totales recalculados coinciden con los guardados.

## Pendiente para Codex — tarifa de IVA y régimen RIMPE en pantallas

- [ ] Formulario de producto: el campo `tarifa_iva` (select) reemplaza a «¿Se cobra impuesto?».
- [ ] Venta: la tabla muestra la tarifa bajo el nombre del producto (`nombre_tarifa`); los totales dicen «Subtotal con IVA» e «IVA general %». Revisar si conviene un desglose por tarifa en pantalla.
- [ ] Nota de crédito: los totales usan la tarifa de cada línea de la factura.
- [ ] RIDE de factura, nota de crédito y ticket: filas por tarifa (conservar `.hoja` de 190 mm).
- [ ] Configuración de la empresa: el campo `rimpe` en el paso 1.

## Notas entre agentes — contrato de IVA por producto y RIMPE (Claude → Codex)

- **No cambiar:** modelos, cálculos del servidor, XML ni migraciones. El servidor recalcula todo; el navegador solo muestra.
- **JSON del producto:** `tarifa_iva` (código 4, 5, 0, 7 o 6), `tarifa` (porcentaje numérico) y `nombre_tarifa` («15 %», «exento de IVA»…).
- **JSON de la línea de factura** (para la nota de crédito): `codigo_porcentaje` y `tarifa`.
- **RIDE:** `OBJ.impuestos_por_tarifa` es una lista de `{codigo, nombre, tarifa, base, valor}` en el orden 15 %, 5 %, 0 %, no objeto, exento. Se muestra «IVA …» solo cuando `tarifa > 0`.
- **Empresa:** `rimpe` (vacío, `emprendedor` o `negocio_popular`); la leyenda está en `company.leyenda_rimpe`.

## Estado actual — importación, menú nuevo y diseños de Codex publicados `c233b74` (Claude, 16/10/2026)

- **Publicado:**
  - App `c233b74` el 16/10/2026 a las 02:30 UTC (respaldo `pre-20261016-023018-c233b745.dump`; migraciones `security 0003` e `importacion 0001–0004`; `pypdfium2` y `zxing-cpp` instaladas con hashes).
  - Contenido: la entrega de Codex `8f1003f` (diseño de la importación y de la guía, menú accesible, PNG optimizados, landing) y el presupuesto de tiempo por petición.
  - Temporizador `facturaporaqui-importacion@pruebas.timer` activo (cada 5 minutos).
  - Landing desde `c233b74` (copia previa `private/landing-antes-20261016023121.tar.gz`).
- **Pruebas:** PostgreSQL 450 aprobadas; SQLite 443 aprobadas y 7 omitidas.
- **El lector de PDF** se probó con el aislamiento systemd del servicio.
- **Verificado con el código publicado** y la base real, en una transacción deshecha con un usuario y una empresa temporales (`verif-firma/verif_importacion.py`):
  - menú en el orden nuevo, «Facturas emitidas» y RLS en las 7 tablas;
  - subida de XML y PDF (201); el XML se procesa y la clave del PDF se lee y se consulta en el SRI de pruebas («no existe», por ser ficticia), sin inventar datos;
  - ruta privada; `/media/` bloquea (404) y la descarga con permiso funciona (200);
  - las 5 páginas responden 200 y el Plan 1000 queda bloqueado (403, `plan: ilimitado`);
  - se borraron los archivos y no quedó nada en la base.
- **Navegador** (`/root/capturas/fpa-publicacion-importacion.mjs`):
  - menú por procesos a 1366 y 390 px; páginas de importación, guías y facturas sin desborde, sin errores y sin respuestas ≥ 400;
  - landing con la importación solo en Ilimitado y Multiempresa.

## Estado actual — entrega subida a GitHub y cierre de landing (Codex, 15/10/2026)

**Commit de cierre subido y verificado en GitHub: `26c98d5d73c5ee9f567e0f7c62b012416d1c1af7`.** Incluye 12a2800, PNG optimizados, 14 capturas y resultados. El commit posterior que registra este recibo solo modifica HANDOFF y RESULTADOS; Claude debe integrar la punta de frontend/etapa3.

Primero se ejecutó fetch de las dos ramas remotas y merge de github/plataforma: ambas seguían en 36bb8de y ya estaban integradas mediante e5da4f6. Git respondió «Already up to date», sin conflictos ni reescritura. Suite SQLite completa: **442 aprobadas y 7 omitidas** (98,38 s). Después se subió **12a2800f8c549df0b8788039e505ed0af2425623** a GitHub, rama frontend/etapa3; confirmado mediante ls-remote. Incluye el diseño de importación 579047b y guía 06.

Landing verificada a 1440/1024/768/390/360 px, sin desbordes. El beneficio «Importación de comprobantes recibidos (XML y RIDE)» ya estaba en Ilimitado y Multiempresa; se conserva sin duplicarlo. Plan 1000 no lo incluye. Precios, anualidad, data-plan y formulario intactos.

Optimizados sin pérdida los cuatro PNG de marca de landing y app: ahorro total 309.900 bytes (14,90 %), sin redimensionar. Píxeles RGBA y transparencia idénticos; nombres y chunks auxiliares originales conservados. Capturas nuevas cierre-landing-* y cierre-marca-login-*; detalle en RESULTADOS-FRONTEND.

## Pendiente para Codex — cierre de guía e importación

- [x] Fetch/merge sin reescribir historial y suite completa SQLite.
- [x] Subir primero 12a2800 a GitHub y comprobar la referencia remota.
- [x] Verificar beneficio comercial solo en Ilimitado/Multiempresa y cinco anchos de landing.
- [x] Optimizar isotipo.png y favicon.png en ambas carpetas conservando nitidez y nombres.
- [x] Capturas y documentación del cierre para Claude.

## Notas entre agentes — revisión y publicación del cierre (Codex → Claude)

- La rama frontend/etapa3 está disponible en GitHub para integrar sobre plataforma. Revisar el cierre 26c98d5 y el recibo documental posterior, además de 12a2800. Esta entrega no despliega app ni landing.
- Ejecutar PostgreSQL y publicar con respaldo a cargo de Claude. Para los PNG de app, incluir collectstatic; para landing, publicar su carpeta assets/brand junto con index.html. Los nombres/rutas no cambian: comprobar caché de los recursos después de publicar.
- No se necesita endpoint ni dato nuevo. No hay cambios de backend, campos, action, CSRF, precios ni permisos. No se hicieron pagos, emisiones ni envíos de formularios comerciales.
- Se conserva íntegro el contenido histórico de ambos agentes que sigue debajo. El antiguo estado «sin push» describe la entrega anterior y queda actualizado por esta sección.

## Estado actual — diseño guía 06 e importación integrados (Codex, 15/10/2026)

Fusionado github/frontend/etapa3 36bb8de (igual a plataforma) con el diseño local de importación 579047b. Merge e5da4f6: dos conflictos solo de documentación, resueltos conservando ambas entregas. El backend integrado no se modificó. Producción informada por Claude sigue siendo 561437a, versión aparte sin importación; esta entrega no se desplegó ni hizo push.

Validación final: 442 pruebas SQLite aprobadas y 7 omitidas exclusivas de PostgreSQL.

Guía: transporte agrupado, cantidades vendido/ya en guías/pendiente, errores, resumen completo y líneas sin importes; listado, opción en facturas, sección 06 y RIDE A4. Importación conservada y revalidada con la guía en el menú nuevo, incluyendo carga, claves, permisos, filtros y propuesta no contabilizada. Capturas guia-*.png y capturas de importación actualizadas.

## Notas entre agentes — entrega de guía e importación (Codex → Claude)

- No endpoints, datos de contexto ni backend nuevos. Names, lineas, management_form, detalle oculto, action=calcular/emitir y acciones generate_invoice/delete intactos.
- La revisión de guía muestra también ruta, motivo, establecimiento de destino y documento aduanero cuando existen. Las cantidades visibles vienen del servidor; no se recalculan en el navegador. La guía no muestra precios.
- RIDE mantiene .hoja de 190 mm y table-layout fixed, con todos los datos obligatorios y opcionales. Usa el logo del emisor como antes; conserva identificación de FACTURAPORAQUI en información adicional.
- Conservar en la futura publicación el diseño de importación 579047b y sus archivos estáticos/landing. Se revalidó tras integrar 36bb8de; faltaba entregarlo junto con esta guía, no desarrollar nuevamente el backend.
- Incluir cambios de static/css/facturaporaqui.css y sale/admin/js/list.js mediante collectstatic. No hay JS nuevo para guía; la importación sigue usando static/js/importacion.js.
- Datos de guía y factura autorizada son fixtures locales, sin firmar ni enviar. Las cuatro guías de historial se insertaron como datos ficticios (sin reservar números mediante el servicio). Formularios solo enviados con calcular. Secuencias y número de guías comprobados intactos después de revisar. SRI de importación simulado; no emisión ni pago real.
- Revisión/publicación por Claude con respaldo; PostgreSQL y teléfono físico no ejecutados por Codex. El informe distingue suite SQLite, navegador, PDF y límites.

## Estado actual — diseño de importación terminado (Codex, 15/10/2026)

Base frontend/etapa3 actualizada por fast-forward a 9b73485, igual a plataforma al comenzar. Diseñadas carga XML/RIDE, lotes, bandejas con filtros, revisión con consentimiento explícito, reglas y visual del menú. Marca Ingenioso y paleta conservadas. Landing anuncia la importación exclusivamente en Ilimitado y Multiempresa. No se desplegó ni publicó app/landing.

Verificación: 419 pruebas SQLite aprobadas y 7 omitidas exclusivas de PostgreSQL; 45 dirigidas aprobadas y cinco anchos de navegador sin desborde.

La carga envía un archivo por petición (XML hasta 2 MB, PDF hasta 5 MB; menor de 9 MB con multipart), crea el lote y agrega al mismo; muestra progreso de subida por archivo y procesa después. Las páginas originales siguen como alternativa sin JS. La verificación declarada se diferencia de la verificada en el SRI. Propuesta contable siempre no contabilizada.

## Notas entre agentes — entrega visual de importación (Codex → Claude)

- Ejecutar collectstatic para incluir `static/js/importacion.js` y cambios de CSS/JS de menú; publicar landing/index.html cuando corresponda. No endpoints ni variables adicionales necesarios.
- Corregido consentimiento implícito del HTML base: vincular ya no lleva confirmar_sin_verificar=1 oculto. Aprobar/vincular requieren una casilla visible de revisión; la excepción sin verificar es otra casilla, nunca preseleccionada. Backend conserva las validaciones.
- El navegador no envía company_id ni calcula montos. Muestra importes decimales como texto y conserva nombres, CSRF y endpoints. Acciones de documento se basan en acciones[] y permisos del contexto.
- Siete PDF ficticios necesitaron tres POST a procesar. Subida de 12 MB probada con API simulada: tres archivos/peticiones de 4 MB, sin pretender validar PDF en esa prueba. Recorrido funcional usa XML/PDF reales ficticios y SRI simulado en un servidor local externo al repo; ninguna llamada real al SRI o PayPhone.
- Si se corta la carga, no se reintenta a ciegas: enlace al lote/historial y mensaje para revisar lo recibido. Si se estanca el procesamiento, se puede retomarlo desde el lote. Procesamiento y subida no son la misma barra.
- Las verificaciones del SRI al final del lote siguen el comportamiento del backend: procesa/verifica hasta tres por llamada; progreso 100 % significa archivos procesados, no que todos estén verificados. Cada documento muestra su verificación, y puede verificarse individualmente.
- Revisar PostgreSQL y publicar con respaldo a cargo de Claude. Dependencias PDF y temporizador siguen siendo los indicados en la entrega backend. Sin cambios propios de modelos, vistas, servicios, URL ni migraciones. Capturas importacion-*.png y detalle en RESULTADOS-FRONTEND.
## Estado actual — guía de remisión (06) publicada `561437a` (Claude, 15/10/2026)

- **Qué hace:**
  - Desde **Facturas emitidas** («Opciones» de una factura autorizada → «Crear guía de remisión») se emite la guía: codDoc 06, XML 1.1.0, XSD oficial en `tests/xsd/guia/`.
  - El destinatario es el cliente de la factura y el documento sustento es la factura (número, clave y fecha).
- **Reglas:**
  - Solo sobre facturas autorizadas, del mismo ambiente y no emitidas a consumidor final.
  - Transportista: RUC o cédula validados, o pasaporte o identificación del exterior; nombre obligatorio.
  - Placa: letras, números y guion. Fechas de inicio y fin del transporte; el fin no puede ser anterior al inicio.
  - Direcciones de partida (la del establecimiento por defecto) y de destino (la del cliente por defecto), motivo («Venta» por defecto), ruta, establecimiento de destino y documento aduanero opcionales.
  - Las líneas son las de la factura y admiten entregas parciales en varias guías; entre todas las guías vigentes no se traslada más de lo vendido.
  - La guía no tiene importes y cuenta 1 del cupo. El correo respeta la preferencia del cliente y no muestra un total.
- **Código:**
  - `core/comprobantes/guias.py`, `xml_guia.py`, modelos `GuiaRemision` y `GuiaDetalle` (RLS).
  - Migraciones `comprobantes 0011–0013` e `importacion 0004`, que vuelve a ordenar el menú con «Guías de remisión» en Comprobantes Electrónicos (posición 5).
- **Verificado:**
  - SQLite: 440 pruebas aprobadas y 7 omitidas. PostgreSQL: 447 aprobadas.
  - El XML firmado es válido contra el XSD.
  - **El SRI de pruebas autorizó** la guía 001-002-953941043 sobre una factura de prueba autorizada. Era de la empresa 6, dentro de una transacción deshecha; se borraron los archivos y no quedó nada en la base.
  - El RIDE se revisó en A4.
- **Publicado** el 15/10/2026 a las 19:25 UTC (respaldo `pre-20261015-192505-561437aa.dump`, migraciones `comprobantes 0011–0013`):
  - es una **versión aparte**: `561437a`, rama local `publicacion/guia` = lo publicado (`914f0b7`) + la guía, **sin** la importación ni el menú nuevo, que esperan el diseño de Codex;
  - las migraciones son idénticas a las de `plataforma`, así que al publicar `plataforma` más adelante no se repiten;
  - en producción la guía aparece en el grupo «Facturación» hasta que se publique el menú nuevo.
- **Verificado en el dominio:**
  - el listado, la sección 06 de Otros comprobantes y el menú cargan sin errores ni desbordes (`/root/capturas/fpa-guias-dominio.mjs`);
  - el formulario y «Revisar» se probaron con el código publicado en una transacción deshecha (`verif-firma/verif_guia_formulario.py`): factura autorizada ficticia en DEMOSTRACIÓN, «pendiente 2» y el resumen; no se creó ninguna guía.

## Pendiente para Codex — pantallas de guía de remisión

- [x] `core/comprobantes/templates/comprobantes/guia/create.html`: transporte (transportista, placa, fechas, partida, destino, motivo, ruta y opcionales), líneas con vendido, ya en guías y pendiente, resumen «Revisa antes de emitir», guías anteriores y el aviso `impedimento`.
- [x] `core/comprobantes/templates/comprobantes/guia/list.html` y la opción «Crear guía de remisión» del menú de facturas (`core/pos/static/sale/admin/js/list.js`).
- [x] La sección 06 en `configuracion/otros.html`.
- [x] RIDE `core/comprobantes/templates/comprobantes/guia/ride.html` (conservar `.hoja` de 190 mm).
- [x] Revisar a 1440, 1024, 390 y 360 px.

## Notas entre agentes — contrato de guía de remisión (Claude → Codex)

- **No cambiar:** modelos, servicios, vistas, URL ni migraciones.
- **Formulario `GuiaForm`:** campos `transportista_tipo_identificacion` (04, 05, 06 u 08), `transportista_identificacion`, `transportista_razon_social`, `placa`, `fecha_inicio`, `fecha_fin` (input date ISO), `dir_partida`, `direccion`, `motivo`, `ruta`, `cod_estab_destino` y `doc_aduanero`.
- **Formset con prefijo `lineas`:**
  - Cada forma tiene `detalle` oculto y `cantidad`; con 0 o vacío, la línea no va.
  - Conservar el `management_form`, `action=calcular/emitir` y el CSRF.
- **Contexto de `create.html`:**
  - `venta`, `impedimento`, `anteriores`, `form`, `lineas`.
  - `filas`: pares (forma, línea), donde la línea tiene codigo, descripcion, vendido, trasladado y pendiente.
  - `resumen`, con `doc` (datos normalizados del transporte) y `detalle` (codigo, descripcion, cantidad).
- **Listado:**
  - Contexto: `guias`, `puede_emitir`, `puede_eliminar`.
  - Acciones por POST: `generate_invoice` y `delete`, con `id`.
- **RIDE, contenido obligatorio:**
  - emisor, número, autorización, ambiente, clave en código de barras;
  - transportista (identificación y nombre), placa, punto de partida y fechas de inicio y fin;
  - comprobante de venta con número, fecha y autorización; motivo, destino, destinatario e identificación; ruta y los datos opcionales;
  - detalle (código, descripción, cantidad);
  - información adicional (RUC Proveedor y FACTURAPORAQUI).

## Estado actual — importación de comprobantes XML / RIDE (backend terminado, sin publicar) (Claude, 15/10/2026)

- **App `core/importacion`:**
  - Ingesta segura de XML del SRI, RIDE en PDF con lectura de QR y código de barras en un proceso aislado, y consulta oficial de autorización al SRI.
  - Lotes con deduplicación por hash y por clave, clasificación, verificación, revisión, vinculación con compras y ventas existentes, y propuesta contable revisable.
  - Detalle técnico y esquema SQL en `entregas/facturaporaqui/IMPORTACION-COMPROBANTES.md`.
- **Menú reorganizado** con datos y permisos (`core/security/menu.py`, campo `orden`); las URL no cambian:
  - **Comprobantes Electrónicos:** Facturas emitidas (antes «Ventas»), Notas de crédito, Retenciones emitidas, Notas de débito, Liquidaciones de compra, Errores de comprobantes. Guías de remisión no aparece porque no está implementada.
  - **Clientes y promociones.**
  - **Compras y gastos:** Compras registradas, Documentos recibidos, Proveedores, Gastos, Tipos de gastos.
  - **Importación de documentos:** Nueva importación XML / RIDE, Lotes e historial, Documentos pendientes de revisión.
  - **Bodega, Administrativo, Reportes.**
  - **Configuración:** Empresa, Facturación y numeración, Reglas de importación y contabilización, Numeraciones registradas.
  - **Seguridad.** «Plan y pagos» sigue suelto.
- **Verificado:** pruebas nuevas (82, más las de concurrencia en PostgreSQL) y las suites completas. Ver RESULTADOS.
- **No publicado. Hace falta además:** las dependencias `pypdfium2` y `zxing-cpp` (en `requirements/base.txt`) y el temporizador `facturaporaqui-importacion@` (`instalar-servicio.sh --aplicar`).

## Pendiente para Codex — importación

- [x] **Nueva importación** (`importacion/nueva.html`):
  - zona para arrastrar archivos y selector de XML o RIDE;
  - subida por partes con progreso por archivo: el primer POST crea el lote y los siguientes agregan archivos;
  - después, llamar a «procesar» hasta que `pendientes` sea 0.
- [x] **Lote** (`importacion/lote.html` y `lotes.html`):
  - estado de cada archivo y errores en lenguaje claro (tabla de códigos abajo);
  - clave manual o elegida entre las `candidatas`.
- [x] **Bandejas** (`importacion/bandeja.html`): Pendientes y Documentos recibidos, con filtros, etiqueta Emitido / Recibido / Ajeno y el estado de verificación.
- [x] **Revisión** (`importacion/documento.html`):
  - impuestos por código y tarifa, bases por tarifa, advertencias, duplicados y candidatos de conciliación;
  - confirmar antes de incorporar, con la casilla «incorporar sin verificar» cuando corresponda;
  - propuesta contable marcada como **no contabilizada**.
- [x] **Reglas** (`importacion/reglas.html`).
- [x] **Visual del menú** con los nuevos grupos y el orden. Mostrar «Facturas emitidas» donde antes decía «Ventas», sin cambiar las URL.
- [x] **Acción «Importar XML / RIDE»** en Documentos recibidos y en la bandeja, visualmente distinta de «Emitir factura».
- [x] **Revisión visual:** 1440, 1024, 768, 390 y 360 px, teclado y movimiento reducido. Mantener el colibrí Ingenioso y la marca.

- [x] Landing: beneficio de importación en Ilimitado y Multiempresa, conservando precios y data-plan.

## Notas entre agentes — contrato de importación (Claude → Codex)

**Principios:**
- **Empresa activa:** la decide el servidor, por la sesión y la membresía. Nunca envíes `company_id`. Un id de otra empresa responde 404.
- **Montos:** todos llegan como texto decimal (`"135.00"`). No los conviertas a float para calcular; solo muéstralos.
- **Autenticación y errores:** sesión de Django y cabecera `X-CSRFToken` en cada POST. Las respuestas de error son `{"error": "texto para el usuario"}`, con estado 400, 403, 404 o 413.

**Permisos (códigos del grupo):**

| Código | Qué permite | Roles |
|---|---|---|
| `view_documentoimportado` | ver lotes, bandejas, documentos y descargar archivos | Propietario, Administrador, Contador y Consulta |
| `add_documentoimportado` | importar, procesar lotes y escribir claves | Propietario y Administrador |
| `change_documentoimportado` | verificar en el SRI y revisar | Propietario y Administrador |
| `view_reglaimportacion` / `change_reglaimportacion` | ver y cambiar las reglas | ver: Propietario, Administrador y Consulta; cambiar: Propietario y Administrador |

El Vendedor no tiene nada de la importación. El Contador y Consulta ven pero no importan, así que «Nueva importación» no está en su menú.

**Endpoints reales:**

| Método y ruta | Permiso | Entrada | Respuesta |
|---|---|---|---|
| `POST /importacion/api/lotes/` | add | multipart, campo `archivos` (varios) | 201 `{lote}` con `entradas` |
| `POST /importacion/api/lotes/<id>/archivos/` | add | multipart `archivos` | 201 `{lote}` (agrega al mismo lote) |
| `POST /importacion/api/lotes/<id>/procesar/` | add | — | `{lote}`; procesa hasta 3 entradas en cola, pero no empieza otra después de 20 s (cada llamada responde en menos de ~45 s); cuando no queda cola, verifica en el SRI si las reglas lo piden |
| `GET /importacion/api/lotes/` | view | `?pagina=` | `{lotes, pagina, paginas}` |
| `GET /importacion/api/lotes/<id>/` | view | — | `{lote}` con `entradas` (para el avance) |
| `POST /importacion/api/entradas/<id>/clave/` | add | `clave` (form o JSON) | `{entrada}`; registra la clave y busca el XML en el SRI |
| `GET /importacion/api/documentos/` | view | `?bandeja=pendientes\|recibidos\|emitidos\|ajenos\|sin_xml\|todos&q=&pagina=` | `{bandeja, documentos, total, pagina, paginas}` |
| `GET /importacion/api/documentos/<id>/` | view | — | `{documento}` con el detalle completo |
| `POST /importacion/api/documentos/<id>/verificar/` | change | — | `{documento}` |
| `POST /importacion/api/documentos/<id>/revisar/` | change | `accion` y sus datos (form o JSON) | `{documento}` o 400 con `error` |
| `GET` / `POST /importacion/api/reglas/` | view / change | campos de la regla (JSON: solo cambia lo que envías) | `{reglas, puede_editar, opciones}` |
| `GET /importacion/archivos/<id>/descargar/` | view | — | descarga privada (XML o PDF), `no-store` |

Las páginas de los módulos (`/importacion/nueva/`, `lotes/`, `lotes/<id>/`, `pendientes/`, `recibidos/`, `documentos/<id>/`, `reglas/`) ya funcionan sin JavaScript. Son una base: rediséñalas sin cambiar los nombres de los campos (`archivos`, `accion`, `clave`, `entrada`, `id`, `motivo`, `clasificacion`, `mobile`, `email`, `confirmar_sin_verificar`).

**`lote`:**
- Campos: `id`, `estado {id, nombre}` (procesando | terminado | con_errores), `total_archivos`, `pendientes`, `progreso` (0–100), `por_estado {estado: n}`, `creado`, `terminado`, `usuario`.
- `entradas[]` tiene `id`, `nombre`, `tamano`, `tipo` (xml | pdf | desconocido), `orden`, `estado {id, nombre}`, `errores[]`, `advertencias[]` ({codigo, texto}), `candidatas[]` ({clave, origen}), `documento_id` y `sha256`.
- **Avance:** después de subir, repite `POST …/procesar/` mientras `pendientes > 0`. Cada llamada responde en pocos segundos porque procesa 3 archivos. Si se corta, la tarea programada termina el lote.

**Estados de una entrada:**
- `en_cola` → `procesando` → uno de estos:
  - `procesado`;
  - `duplicado`: el contenido o la clave ya estaban importados y se enlaza al documento existente;
  - `pendiente_clave`: el PDF no tiene una clave legible o es ambigua; pide la clave y ofrece las `candidatas`;
  - `pendiente_xml`: hay clave, pero el SRI no entregó el XML; se puede reintentar con la misma clave;
  - `rechazado`: ver `errores`.

**Errores por archivo (`codigo` → qué mostrar):**
- **Archivo:** `tipo_archivo` (no es XML ni PDF), `archivo_grande`, `vacio`, `no_es_xml`, `no_es_pdf`, `codificacion`.
- **Estructura:** `xml_malformado`, `dtd_prohibida` (DOCTYPE o entidades rechazados por seguridad), `xml_excesivo`, `estructura_desconocida`, `estructura_invalida`, `comprobante_vacio`.
- **Autorización:** `no_autorizado`, `sin_autorizaciones`, `ambiguo`.
- **Tipo:** `tipo_no_soportado` (por ahora solo facturas 01).
- **Clave:** `clave_invalida`, `clave_incoherente`, `autorizacion_incoherente`.
- **Datos:** `campo_faltante`, `ruc_emisor`, `fecha_invalida`, `importe_invalido`, `importe_faltante`.
- **PDF:** `demasiadas_paginas`, `pdf_protegido`, `pdf_invalido`, `pdf_tiempo`, `ambigua`.
- **Advertencias (no impiden importar):** `sin_autorizacion`, `iva_descuadrado`, `bases_descuadradas`, `total_descuadrado`, `pagos_descuadrados`, `lineas_descuadradas`, `tarifa_incoherente`, `iva_desconocido`, `identificacion_formato`, `autorizacion_antigua`, `ambiente_autorizacion`, `varias_autorizaciones`, `sin_clave`, `texto_distinto`.

**`documento`:**
- **Siempre:**
  - `id`, `clave_acceso`, `cod_doc`, `tipo_documento`, `version`, `ambiente`, `numero`, `fecha_emision`, `numero_autorizacion`, `fecha_autorizacion`, `origen {id, nombre}`;
  - `emisor {ruc, razon_social, nombre_comercial}`, `receptor {tipo_identificacion, identificacion, razon_social}`, `moneda`;
  - `importes {total_sin_impuestos, total_descuento, propina, total_iva, total_ice, total_irbpnr, importe_total}`;
  - `estados {procesamiento, verificacion {.., en}, clasificacion, revision, contable}`, cada uno `{id, nombre}`;
  - `proveedor`, `cliente`, `compra_id`, `venta_id`, `advertencias`, `creado`.
- **Detalle:**
  - `impuestos[]` {codigo, codigo_porcentaje, impuesto, categoria, tarifa, base_imponible, valor, descuento_adicional, valor_devolucion_iva}, `bases_por_tarifa[]`, `pagos[]`, `lineas`, `info_adicional`;
  - `archivos {xml, pdf}` ({id, tipo, origen, tamano, sha256, nombre, descarga});
  - `candidatos[]` ({tipo: compra | venta, id, numero, fecha, subtotal | total, razones[], exacto}) y `retenciones[]`;
  - `propuesta_contable` ({estado: propuesta, contabilizado: false, cuadra, debe, haber, lineas[{cuenta, descripcion, debe, haber}], avisos[], nota});
  - `nota_revision`, `eventos[]` y `acciones[]`: las acciones que hoy admite el servidor. Úsalas para mostrar u ocultar botones.

**Estados y transiciones del documento:**
- **Procesamiento:** `pendiente_xml` (solo la clave, sin importes) → `procesado` cuando llega el XML (subido o del SRI).
- **Verificación:**
  - `sin_autorizacion` o `declarada_en_archivo` → (verificar) → `verificada_sri`, `discrepancia_sri`, `no_autorizada_sri`, `no_encontrada_sri` o `sri_no_disponible`.
  - Lo declarado en el archivo **no** prueba autenticidad: muéstralo distinto de «Verificada en el SRI».
  - `discrepancia_sri` pasa la clasificación a `revision_manual`.
- **Clasificación:**
  - `emitido`, `recibido`, `ajeno` o `revision_manual`; `pendiente` mientras falta el XML.
  - `clasificar` solo acepta lo que coincide exactamente con el RUC.
  - Ajeno no se incorpora.
- **Revisión:**
  - Desde `pendiente`: `aprobar`, `vincular_compra` o `vincular_venta` (con `id`), `descartar` (con `motivo`), `clasificar`, `crear_proveedor` (`mobile`, `email`).
  - Desde `aprobado`, `vinculado` o `descartado`: `reabrir`.
  - Aprobar y vincular exigen la verificación en el SRI. Si no está verificado, hay que enviar `confirmar_sin_verificar=1`, con una confirmación explícita del usuario.
  - Con `no_autorizada_sri`, `no_encontrada_sri` o `discrepancia_sri` nunca se incorpora.
- **Contable:** `sin_propuesta` → `propuesta` al aprobar o vincular. No existe «contabilizado».
- **Conciliación:** importar **no** crea compras, gastos ni ventas. Si hay candidatos, propón vincular; con `exacto: true`, destácalo como «probable duplicado».

**Límites que la interfaz debe anunciar:**
- XML de 2 MB; PDF de 5 MB y 5 páginas.
- 50 archivos y 60 MB por lote; **9 MB por petición**: sube de a pocos archivos y agrégalos al lote.
- Facturas 01 por ahora.
- El procesamiento de cada PDF puede tardar unos segundos, y más si el SRI está lento.

**Comercial (decidido el 15/10/2026):** la importación está incluida solo en **Ilimitado y Multiempresa**, también para la empresa cubierta por un Multiempresa. No descuenta cupo, no cambia numeraciones y no emite nada.
- Con Plan 1000 o el gratuito, el menú muestra el candado (`bloqueado_por_plan`) y las páginas redirigen a `/suscripcion/` con un aviso.
- La API responde 403 `{"error": "La importación de comprobantes recibidos (XML y RIDE) está incluida en los planes Ilimitado y Multiempresa. Mejora tu plan para usarla.", "plan": "ilimitado"}`. Muestra una invitación a mejorar el plan.
- Con un Ilimitado vencido se consulta, pero no se importa.
- Plan y pagos ya lista «Importación de comprobantes recibidos (XML y RIDE)» en esas dos tarjetas. Falta agregarlo a la landing: es tarea de Codex, y es texto comercial.

## Estado actual — nota de débito (05) publicada `914f0b7` (Claude, 14/10/2026)

- **Qué hace:**
  - Desde **Ventas** («Opciones» de una factura autorizada → «Crear nota de débito») se emite la nota de débito: codDoc 05, XML 1.0.0, XSD oficial en `tests/xsd/notadebito/`.
  - Sirve para cargos posteriores, como intereses de mora o gastos de cobranza.
- **Reglas:**
  - Solo sobre facturas autorizadas, del mismo ambiente y no emitidas a consumidor final.
  - Admite de 1 a 10 motivos (razón y valor sin IVA); el XSD acepta varios `<motivo>`.
  - La tarifa de IVA es la de la factura (nota de la ficha: la tarifa de la fecha del sustento) o 0 %. Nunca la decide el navegador.
  - Una factura admite varias notas de débito, y cada una cuenta 1 del cupo.
- **Emisión:**
  - Revisión antes de emitir, firma nativa, dos fases y `consultar_sri`.
  - El correo al cliente respeta su opción «¿Enviar email de factura?».
  - La numeración se configura en Otros comprobantes (05).
- **Código:**
  - `core/comprobantes/notas_debito.py`, `xml_nota_debito.py`, modelos `NotaDebito` y `NotaDebitoMotivo` (RLS).
  - Migraciones `comprobantes 0008–0010`. Módulo «Notas de débito» en Facturación para Propietario, Administrador, Contador y Consulta; el Vendedor no lo tiene.
- **Verificado:**
  - SQLite: 330 pruebas aprobadas y 5 omitidas. PostgreSQL: 335 aprobadas.
  - El XML firmado es válido contra el XSD oficial.
  - **El SRI de pruebas autorizó** la nota de débito 001-002-955832690 sobre una factura de prueba también autorizada. Era de la empresa 6, dentro de una transacción deshecha; se borraron los archivos y no quedó nada en la base.
  - El RIDE se revisó en A4.
- **Publicado** el 14/10/2026 a las 23:20 UTC (respaldo `pre-20261014-232038-914f0b70.dump`, migraciones `comprobantes 0008–0010`).
- **Verificado en el dominio:**
  - El listado, la sección 05 de Otros comprobantes y el menú cargan sin errores (`/root/capturas/fpa-notas-debito-dominio.mjs`).
  - Las empresas demo no tienen ventas. Por eso el formulario se probó con el código publicado y la base real, dentro de una transacción deshecha (`verif-firma/verif_nd_formulario.py`): factura autorizada ficticia en DEMOSTRACIÓN, GET con IVA 15 % y «Revisar» con un total de $11,50. No se creó ninguna nota y no quedó nada en la base.

## Pendiente para Codex — pantallas de nota de débito

- [ ] `core/comprobantes/templates/comprobantes/notadebito/create.html`: motivos (hasta 10), IVA y forma de pago, resumen «Revisa antes de emitir», notas anteriores de la factura y el aviso cuando no se puede emitir (`impedimento`).
- [ ] `core/comprobantes/templates/comprobantes/notadebito/list.html` y la opción «Crear nota de débito» del menú de Ventas (`core/pos/static/sale/admin/js/list.js`).
- [ ] La sección 05 en `configuracion/otros.html`.
- [ ] RIDE `core/comprobantes/templates/comprobantes/notadebito/ride.html` (conservar `.hoja` de 190 mm).
- [ ] Revisar a 1440, 1024, 390 y 360 px.

## Notas entre agentes — contrato de nota de débito (Claude → Codex)

- **No cambiar:** modelos, servicios, vistas, URL ni migraciones.
- **Formulario `NotaDebitoForm`:** campos `tarifa_iva` (opciones que fija el servidor) y `forma_pago`.
- **Formset con prefijo `motivos`:**
  - Cada forma tiene `razon` y `valor`. Se puede adoptar la mejora progresiva de `retenciones.js` (hasta 10).
  - Conservar el `management_form`, `action=calcular/emitir` y el CSRF.
- **Contexto de `create.html`:**
  - `venta`, `impedimento` (texto o None), `anteriores`, `form`, `motivos`.
  - `resumen`, con `doc.tarifa_iva`, `motivos` [razon, valor], `total_sin_impuestos`, `valor_iva` y `valor_total`.
- **Listado:**
  - Contexto: `notas`, `puede_emitir`, `puede_eliminar`.
  - Acciones por POST: `generate_invoice` y `delete`, con `id`.
- **RIDE, contenido obligatorio:**
  - emisor, número, autorización, ambiente, clave en código de barras;
  - comprador e identificación;
  - comprobante que se modifica y su fecha;
  - las razones con sus valores;
  - subtotales, IVA y valor total;
  - la forma de pago y la información adicional (RUC Proveedor y FACTURAPORAQUI).

## Estado actual — liquidación de compra (03) publicada `d9d142a` (Claude, 14/10/2026)

- **Qué hace:**
  - Desde **Compras** (botón «Liquidación») se emite la liquidación de compra de bienes y prestación de servicios: codDoc 03, XML 1.1.0 (Anexo 17).
  - Es para cuando el vendedor no puede emitir factura (RCV art. 13): personas naturales sin RUC o con RUC suspendido, y no residentes.
- **Proveedor:**
  - El nombre y la identificación salen de la ficha del proveedor y se copian al emitir.
  - Identificaciones: cédula (05, validada), pasaporte (06), exterior (08) o RUC (04). El RUC exige confirmar que está suspendido, porque con RUC activo la liquidación no sustenta crédito ni gasto. El tipo 07 no se admite.
- **Líneas y totales:**
  - Las líneas son las de la compra (cantidad × precio). El emisor elige la tarifa de IVA de cada una (15, 5 o 0 %); la sugerida es 15 % si el producto cobra impuesto y 0 % si no.
  - El IVA de cada línea se redondea por separado y el total por tarifa es la suma de las líneas, como en la factura.
- **Emisión:** paso «Revisa antes de emitir», firma nativa, emisión en dos fases, `consultar_sri`, cupo 1 y correo al proveedor con el RIDE.
- **Numeración:** en **Otros comprobantes** (tipo 03). Una sola liquidación vigente por compra; las que están en proceso o autorizadas no se borran.
- **Retención sobre la liquidación:** si la compra tiene una liquidación autorizada, la pantalla de retención la usa como documento sustento (03).
  - Precarga número, clave, fecha, bases e IVA.
  - Sugiere renta 311 (3 %) e IVA 3 (100 %), según la Res. NAC-DGERCGC20-00000061.
  - La retención tiene un campo nuevo, `cod_doc_sustento` (01 factura / 03 liquidación). Es opcional y vale 01 por defecto. El sustento 09 no admite 03.
- **Código:**
  - `core/comprobantes/liquidaciones.py`, `xml_liquidacion.py`, modelos `LiquidacionCompra` y `LiquidacionDetalle` (RLS).
  - Migraciones `comprobantes 0005–0007` (modelo, seguridad por filas, módulo «Liquidaciones de compra» en Facturación).
  - `ComprobanteListView` reúne el listado de retenciones y el de liquidaciones.
- **Verificado:**
  - SQLite: 312 pruebas aprobadas y 5 omitidas. PostgreSQL: 317 aprobadas. `makemigrations --check` sin cambios.
  - El XML firmado es válido contra el XSD oficial 1.1.0.
  - **El SRI de pruebas (celcer) autorizó** la liquidación 001-002-920115897 y la retención 001-002-966385138, que tiene esa liquidación como sustento 03. Las dos son de la empresa 6, se armaron en memoria con un proveedor ficticio y no dejaron nada en la base.
  - El RIDE se revisó en A4.
- **Publicado** el 14/10/2026 a las 20:33 UTC junto con el diseño de retenciones de Codex (`13d0cde`):
  - respaldo `pre-20261014-203336-d9d142aa.dump`; migraciones `comprobantes 0005–0007`;
  - el módulo «Liquidaciones de compra» queda en Facturación para Propietario, Administrador, Contador y Consulta;
  - las tablas nuevas tienen seguridad por filas.
- **Verificado en el dominio** con DEMOSTRACIÓN (`/root/capturas/fpa-liquidaciones-dominio.mjs`, salida en `salida-liquidaciones/`):
  - el listado, la sección 03 de Otros comprobantes y los 9 botones «Liquidación» y «Retención» de Compras funcionan;
  - el formulario carga las 4 líneas de la compra #9;
  - «Revisar» con pasaporte da un total de $323,28 (subtotal 15 %) sin guardar nada;
  - sin desborde a 1366 ni a 390 px;
  - el botón de Codex para agregar líneas de retención pasa de 3 a 4 líneas;
  - sin errores de consola, sin respuestas ≥ 400 y sin liquidaciones creadas.

## Pendiente para Codex — pantallas de liquidación de compra

- [ ] `core/comprobantes/templates/comprobantes/liquidacion/create.html`: proveedor y pago, líneas de la compra con tarifa por línea, resumen «Revisa antes de emitir» con subtotales por tarifa, y avisos (qué es una liquidación; compra con liquidación vigente).
- [ ] `core/comprobantes/templates/comprobantes/liquidacion/list.html`: estados, PDF/XML, reenviar, eliminar y acceso a «Retención» cuando está autorizada.
- [ ] Botón «Liquidación» en Compras (`core/pos/static/purchase/js/list.js`) y la sección 03 en `configuracion/otros.html`.
- [ ] Aviso de la retención cuando el sustento es una liquidación (`retencion/create.html`, bloque `{% if liquidacion %}`).
- [ ] RIDE `core/comprobantes/templates/comprobantes/liquidacion/ride.html` (WeasyPrint, A4; conservar `.hoja` de 190 mm).
- [ ] Revisar a 1440, 1024, 390 y 360 px, y registrar capturas.

## Notas entre agentes — contrato de liquidación (Claude → Codex)

- **No cambiar:** modelos, servicios, vistas, URL ni migraciones.
- **Formulario `LiquidacionForm`:** campos `tipo_identificacion`, `direccion`, `forma_pago`, `concepto` y `confirma_sin_ruc`.
- **Formset con prefijo `lineas`:**
  - Una forma por línea de la compra, con `detalle` oculto, `descripcion` y `tarifa`. No se agregan ni quitan líneas: salen de la compra.
  - Conservar el `management_form`, los botones `name="action"` con `value="calcular"` y `value="emitir"`, y el CSRF.
- **Contexto de `create.html`:**
  - `compra`, `vigente`, `form`, `lineas`.
  - `filas`: pares (forma, línea), donde la línea tiene codigo, descripcion, cantidad, precio_unitario y tarifa.
  - `resumen`, con `doc`, `detalle` (descripcion, cantidad, precio_unitario, base, tarifa, iva), `por_tarifa` [(tarifa, base, iva)], `total_sin_impuestos`, `total_iva` e `importe_total`.
- **Listado:**
  - Contexto: `liquidaciones`, `puede_emitir`, `puede_eliminar`.
  - Acciones por POST: `generate_invoice` y `delete`, con `id`. Los estados se comparan de forma exacta.
- **Retención:** el contexto agrega `liquidacion`, que existe cuando el sustento sugerido es la liquidación autorizada.
- **RIDE, contenido obligatorio:**
  - del emisor y del comprobante: emisor, número, autorización, fecha, ambiente, clave en código de barras;
  - del proveedor: nombre, tipo e identificación, fecha y dirección;
  - el detalle (código, cantidad, descripción, precio unitario, descuento, precio total);
  - los subtotales por tarifa, el descuento, el IVA por tarifa y el valor total;
  - la forma de pago y la información adicional (RUC Proveedor y FACTURAPORAQUI).
- **Datos de prueba:** usar empresas ficticias. No emitir documentos reales.

## Estado actual — tabla de precios de Codex publicada `3e25b3e` (Claude, 14/10/2026)

- **Publicado:**
  - App `3e25b3e` el 14/10/2026 a las 19:47 UTC (respaldo `pre-20261014-194656-3e25b3e3.dump`, sin migraciones; `static/js/precios.js` incluido por collectstatic).
  - Landing desde `3e25b3e` con `assets/pricing.js` (copia previa en `private/landing-antes-20261014194722.tar.gz`).
  - `3e25b3e` = `400e459` (retenciones) + fusión de `14d0090` (`78b9e95`) + el cupo de Plan y pagos dice «facturas, notas de crédito y retenciones», porque cada retención cuenta 1.
- **Revisión del código:**
  - Sin cambios de backend. Se conservan `data-plan`, las opciones del formulario de la landing y los formularios de pago.
  - `precios.js` y `pricing.js` son idénticos.
  - Pruebas: PostgreSQL 296 aprobadas; SQLite 291 aprobadas y 5 omitidas.
- **Verificado en el dominio** (`/root/capturas/fpa-precios-dominio.mjs`, salida en `salida-precios/`):
  - **Landing a 1440, 1024, 390 y 360 px:** $50, $85 y $199 «/ año»; alcances «Para 1 RUC», «Para 1 RUC» y «Hasta 10 RUC distintos»; nota «Pago anual · IVA incluido»; ningún texto de mensualidad; sin desborde.
  - **Desplegables:** 3. Abren y cierran con Enter, y el precio sigue visible con el desplegable cerrado.
  - **Selección:** «Me interesa el Multiempresa» marca la tarjeta y deja el formulario en `multiempresa`.
  - **Animaciones:** 3 con movimiento normal y 0 con movimiento reducido.
  - **App (DEMOSTRACIÓN, 1366 y 390 px):** nota anual, 3 tarjetas con desplegables abiertos y `precios.js` cargado. Sin desborde, sin errores de consola y sin respuestas ≥ 400.
  - **Empresa cubierta:** se probó con el código publicado y la base real, dentro de una transacción que se deshizo, con un período Multiempresa temporal en OTRA-DEMO y una empresa adicional ficticia.
    - La página responde 200 y oculta la nota anual.
    - No hay formularios ni botones de pago: el único formulario POST es el selector de empresa.
    - No quedó nada en la base.
  - No se completaron pagos.
- **Diseño de retenciones de Codex (`13d0cde`):** revisado e integrado en `plataforma`; se publica junto con la liquidación de compra (03).

## Estado actual — diseño de retenciones 07 terminado (Codex, 14/10/2026)

Fusionado github/plataforma 400e459 en frontend/etapa3 con merge 6d67d81, sin reescribir historial. Resuelto únicamente HANDOFF conservando las dos secciones de entregas. Se mantiene 14d0090 (precios) pendiente de revisión/publicación por Claude. Publicado informado por la propietaria: 400e459; no se desplegó desde esta tarea.

Formulario con jerarquía de sustento, líneas y revisión; hasta 10 líneas mediante mejora progresiva del formset. Listado como fichas en móvil, estados/acciones exactos conservados. Tema de Otros comprobantes, acceso en asistente, botón de Compras y RIDE A4 de 190 mm. No modificaciones propias de modelos, vistas, servicios, URL, formularios Python ni migraciones.

Validación: 291 pruebas SQLite aprobadas, 5 omitidas exclusivas de PostgreSQL. Navegador 1440/1024/768/390/360 px sin desborde de documento; cálculo y errores del servidor, 10 líneas, foco y fallback sin JS. RIDE en memoria, una página A4, tres tablas dentro de 190 mm. Capturas retencion-*.png en capturas/. Ninguna emisión/pago, ninguna retención guardada ni numeración existente modificada.

## Notas entre agentes — entrega visual de retenciones (Codex → Claude)

No datos nuevos del backend necesarios. Incluir `static/js/retenciones.js` al ejecutar collectstatic. El JS usa empty_form y management_form de Django, conserva prefijo lineas y max 10; no calcula impuestos ni envía al SRI. Sin JS quedan las tres líneas originales. Revisión por action=calcular; action=emitir intacto y nunca pulsado en esta revisión.

Las capturas de formulario/cálculo/Compras/configuración usan una empresa local ficticia nueva. El listado poblado usa objetos no guardados renderizados con la plantilla real para comprobar estados sin consumir secuencias. RIDE igualmente en memoria, con dos líneas y total $6,50. No se verificaron descargas/reenviados reales ni autorización SRI; esas acciones conservan el backend. El resumen ancho mantiene desplazamiento horizontal exclusivamente en su contenedor, como en 400e459. No publicación; Claude revisa PostgreSQL y publica con respaldo cuando corresponda.

## Estado actual — tabla de precios y beneficios (Codex, 14/10/2026)

Diseño inspirado en la referencia enviada por la propietaria, adaptado a los tres planes anuales y marca FacturaPorAquí. Landing: cabecera, precio fijo, alcance, CTA y beneficios con checks; beneficios desplegables con teclado. Multiempresa diferenciado. App: mismos beneficios desplegables y animaciones suaves. Sin mensualidad, descuentos ni importes animados.

JavaScript propio con Web Animations e IntersectionObserver, respetando movimiento reducido. Se conservan precios, data-plan, opciones de formulario, CSRF, modos y reglas del backend. No desplegado.

## Pendiente para Codex — tabla de precios

- [x] Leer la referencia y adaptar diseño sin cambiar el cobro anual.
- [x] Mejorar beneficios y agregar animaciones accesibles.
- [x] Revisar responsive, teclado, selección de plan y movimiento reducido.
- [x] Documentar pruebas y capturas.

## Notas entre agentes — tabla de precios

Claude: publicar cuando revise, con respaldo. Landing requiere `landing/assets/pricing.js` junto con index.html; app requiere collectstatic de `static/js/precios.js`. Son la misma implementación, sin dependencias nuevas. No se copió el selector mensual ni Odometer del ejemplo. No endpoints nuevos ni cambios de backend. Los detalles mantienen visibles precio y acciones de pago aunque se cierren los beneficios. Se mantuvo retenciones en landing por decisión previa de la propietaria. La animación no garantiza retención de clientes: cobro y vigencia siguen en servidor.

## Estado actual — portada Facebook (Codex, 14/10)

Lista redes/portadas/facebook-facturaporaqui.png y guía de uso, sin publicación. No requiere backend ni despliegue.

## Pendiente para Codex — portada

- [x] Diseñar y verificar PNG de portada con marca Ingenioso y fondo continuo.

## Notas entre agentes — portada

Revisar recorte móvil/escritorio al subir a Facebook. No se requieren endpoints.

## Estado actual — comprobante de retención (07) publicado `400e459` (Claude, 14/10/2026)

- **Qué hace:**
  - Desde **Compras** (botón «Retención») se emite el comprobante de retención 07, XML versión 2.0.0 (Anexo 10).
  - Los datos del sujeto retenido salen del proveedor de la compra. El documento sustento es la factura del proveedor (15 dígitos y autorización de 10, 37 o 49).
  - Un paso «Revisa antes de emitir» calcula sin guardar.
  - Usa firma nativa, emisión en dos fases y la tarea `consultar_sri`. Cada retención cuenta 1 del cupo. Se envía por correo al proveedor con su RIDE.
  - Listado en `/comprobantes/retenciones/`.
  - La numeración se configura en **Configuración de facturación → Otros comprobantes** (`/configuracion/facturacion/otros/`).
  - Una compra admite una sola retención vigente. Las que están en proceso o autorizadas no se borran: se anulan en SRI en línea.
- **Catálogo de códigos:**
  - `comprobantes.CodigoRetencion` es de la plataforma, no de cada empresa. La migración `0004_catalogo_retenciones` carga la tabla vigente desde el 01/03/2026 (Res. NAC-DGERCGC26-00000009, Catálogo ATS del 06/08/2026): 84 códigos de renta para residentes y 11 de IVA, de ellos 78 activos.
  - Se edita en la administración de la plataforma; no se pueden borrar códigos, solo desactivarlos.
  - Quedan inactivos los códigos que piden nodos que aún no generamos: dividendos, banano y autorretenciones. Los pagos al exterior (5xx) no se cargan.
  - Detalle y fuentes en `NORMA-RETENCIONES-2026-10.md`.
- **Aviso a no agentes:** las sociedades ya no son agentes de retención por sí solas. Si la empresa no está marcada como agente, la pantalla lo explica, pero no bloquea la emisión: hay casos puntuales en que cualquiera retiene.
- **Verificado:**
  - SQLite: 289 pruebas aprobadas y 5 omitidas. PostgreSQL: 294 aprobadas.
  - `makemigrations --check` sin cambios.
  - El XML firmado es válido contra el XSD oficial.
  - **El SRI de pruebas (celcer) autorizó** la retención 001-002-988274312 de la empresa 6. Se armó en memoria con un proveedor ficticio; no quedó nada en la base.
  - El RIDE se revisó generado con petición web y sin ella.
- **Publicado** el 14/10/2026 a las 19:10 UTC (`aafbe4a`, respaldo `pre-20261014-191047-aafbe4a6.dump`, migraciones `comprobantes 0001–0004` y `pos 0013`), con correcciones hasta `400e459` (enlace a Otros comprobantes, fecha ISO, resumen responsive). Verificado en el dominio con DEMOSTRACIÓN (`/root/capturas/fpa-retenciones-dominio.mjs`). Falta el diseño de Codex.
- **Siguiente etapa:** liquidación de compra (03), después nota de débito (05) y guía de remisión (06).

## Pendiente para Codex — pantallas de retenciones

- [x] `core/comprobantes/templates/comprobantes/retencion/create.html`: datos del sustento, líneas de retención (hasta 10), resumen «Revisa antes de emitir», aviso de compra con retención vigente y aviso a no agentes.
- [x] `core/comprobantes/templates/comprobantes/retencion/list.html`: estados, descargas de XML y PDF, reenviar y eliminar.
- [x] Sección «Comprobante de retención» en `core/configuracion/templates/configuracion/otros.html`.
- [x] Botón «Retención» en el listado de Compras (`core/pos/static/purchase/js/list.js`).
- [x] RIDE `core/comprobantes/templates/comprobantes/retencion/ride.html` (WeasyPrint, A4).
- [x] Revisar a 1440, 1024, 390 y 360 px, y registrar capturas.

## Notas entre agentes — contrato de retenciones (Claude → Codex)

- **No cambiar:** modelos, servicios, vistas, URL ni migraciones.
- **Formulario de emisión** (deben conservarse):
  - Nombres de los campos de `DocumentoSustentoForm`.
  - El formset con prefijo `lineas` y su `management_form`.
  - Los botones `name="action"` con `value="calcular"` y `value="emitir"`, y el CSRF.
- **Contexto de `create.html`:**
  - `compra`, `vigente`, `form`, `lineas`, `es_agente`.
  - `resumen`, con `doc` (normalizado), `detalle` (codigo, concepto, base_imponible, porcentaje, valor_retenido, impuesto), `total`, `total_sin_impuestos` e `importe_total`.
- **Listado:**
  - Contexto: `retenciones`, `puede_emitir`, `puede_eliminar`.
  - Acciones por POST: `action=generate_invoice` y `action=delete`, con `id`.
  - Los estados se comparan de forma exacta: «authorized» está contenido en «not_authorized».
- **Otros comprobantes:** el formulario envía `tipo` oculto y usa como prefijo el tipo (`07-…`).
- **RIDE:**
  - Conservar el contenedor `.hoja` de 190 mm y `table-layout: fixed`. Bootstrap fija `body { min-width: 992px }` al imprimir; sin eso el contenido se sale de la hoja.
  - Contenido obligatorio:
    - del emisor: razón social, RUC, direcciones, contabilidad y contribuyente especial;
    - del comprobante: número, autorización y fecha, ambiente, clave en código de barras;
    - del sujeto retenido: nombre e identificación, fecha y período fiscal;
    - el detalle por línea (comprobante, número, fecha, ejercicio, base, impuesto, código, %, valor) y el total retenido;
    - la información adicional, que incluye el RUC Proveedor y los datos de FACTURAPORAQUI.
- **Datos de prueba:** usar empresas ficticias. No emitir documentos reales ni tocar numeraciones de clientes.

## Estado actual — diseño Plan Multiempresa terminado (Codex, 14/10/2026)

Trabajo en frontend/etapa3 sobre a4e8415, sin reescribir historial. Landing con tres tarjetas y Multiempresa diferenciado, tema del plan/aviso cubierto/resumen de cupos en app, página Empresas del plan responsive y acceso desde sidebar/selector para la titular con permisos de plan. Se conservan condiciones de propietario para agregar RUC. No cambios backend. No desplegado; publicado informado por Claude sigue siendo c2eb08e.

Validación: 270 pruebas SQLite aprobadas y 5 omitidas exclusivas de PostgreSQL. Navegador local a 1440/1024/768/390/360px: landing, planes, empresas y cubierta sin overflow; RUC inválido muestra error del servidor, navegación Tab, empresa adicional sin tarjetas ni menú de gestión. Sin errores JS/recursos fallidos. PayPhone vacío en configuración local externa; no pagos reales.

Comercial: 2 posts y 2 historias en redes/plan-multiempresa, con textos/guía/galería. Fondo continuo, zona segura invisible de 60 px, oferta $199 anual con IVA hasta 10 RUC y documentos ilimitados. ZIP local listo. No publicación de redes.

## Pendiente para Codex — cierre Multiempresa

- [x] Diseñar las tres tarjetas de landing conservando precios, textos, retenciones, data-plan y opciones.
- [x] Diseñar tarjeta, cobertura y resumen en app.
- [x] Diseñar Empresas del plan y acceso visible para titular.
- [x] Crear 2 posts / 2 historias, textos y guía.
- [x] Registrar pruebas y capturas.

## Notas entre agentes — entrega Multiempresa

Claude: no variables/endpoints nuevos. El acceso usa fpa_plan.periodo.plan.multiempresa, not fpa_plan.titular y fpa_gestiona_plan, ya disponibles. Titular con permiso puede consultar; solo Propietario agrega según backend existente. No se tocaron vistas/servicios/modelos/migraciones; names, accion, CSRF, select empresa y mensajes intactos. Publicar cuando revise con respaldo y collectstatic; redes no necesitan despliegue Django. Se mantuvo retenciones en landing por instrucción explícita del usuario.

Configuración de desarrollo guardada en borrador de entorno (Python 3.12, requirements con hashes y arranque local con PayPhone deshabilitado), no publicada. No confundir publicación del entorno cloud con despliegue en Hestia. Backend/PostgreSQL y móvil físico no verificados en esta entrega.

## Estado actual — redes con fondo continuo (Codex, 13/10 Ecuador)

Reemplazadas las 20 imágenes en `redes/campana-01/` para quitar el marco de la entrega anterior. Fondo y formas decorativas continuos hasta los bordes; zona segura invisible para texto/marca. Textos, precios y nombres de archivo conservados. Manifiesto y ZIP actualizados. No cambios de aplicación ni publicación externa.

## Pendiente para Codex — corrección de estilo

- [x] Eliminar rectángulo/marco de los 10 posts y 10 historias.
- [x] Revisar la campaña completa y regenerar ZIP.

## Notas entre agentes — diseño de redes

El margen de 60 px es una zona segura para texto/logo, no un borde uniforme. La decoración de fondo puede llegar al límite del PNG. No se requiere backend ni despliegue de aplicación. La versión anterior con marco queda en el historial de git; la carpeta vigente usa fondo continuo.

## Estado actual — encuadre de redes actualizado (Codex, 13/10 Ecuador)

Actualizadas las 20 imágenes en la misma ruta `entregas/facturaporaqui/redes/campana-01/`: zona segura mínima de 60 px en los cuatro lados para textos y marca. Conservados precios y captions. Galería con opción de miniatura orientativa 3:4, manifiesto y ZIP actualizados. No aplicación ni publicación de redes modificadas.

## Pendiente para Codex — margen de redes

- [x] Ajustar los 10 posts y 10 historias con la zona segura solicitada.
- [x] Verificar visualmente, actualizar galería/manifiesto y regenerar ZIP.

## Notas entre agentes — archivos de redes

Claude: solo archivos gráficos/documentación; no necesitan despliegue de Django. Ruta de campaña sin cambios. Revisar la miniatura en Instagram al publicar; una zona segura de 60 px no garantiza todos los recortes de plataformas. La exportación conserva separación mayor en algunas piezas, sin exigir un borde idéntico de 60 px en el fondo.
## Estado actual — diseño Multiempresa de Codex publicado `e1f6ee5` (Claude, 14/10/2026)

- **Publicado:** app `e1f6ee5` el 14/10/2026 a las 18:09 UTC (respaldo `pre-20261014-180916-e1f6ee53.dump`, sin migraciones) y landing desde `e1f6ee5` (copia previa en `private/landing-antes-20261014180943.tar.gz`).
- **Revisión:** solo plantillas, CSS y landing. El menú y el selector usan `fpa_plan` y `fpa_gestiona_plan`, que ya existen en el procesador de contexto. Pruebas: PostgreSQL 275 y SQLite 270 + 5.
- **Verificado en el dominio**, con un período Multiempresa TEMPORAL en la empresa ficticia OTRA-DEMO (período 6), anulado al terminar sin crear empresas adicionales:
  - el titular ve el acceso a «Empresas del plan» en el menú lateral, el selector y Plan y pagos;
  - la página muestra «RUC en tu plan: 1 de 10» y los dos formularios con sus campos;
  - la landing muestra tres tarjetas a 1440, 1024 y 390;
  - sin desbordes, sin errores de consola y sin respuestas ≥ 400.
- **Piezas de redes:** en `entregas/facturaporaqui/redes/plan-multiempresa/` (2 posts y 2 historias). Revisadas: precio, «hasta 10 RUC» e «ilimitado» coinciden con la landing. No están publicadas.

## Estado actual — Plan Multiempresa publicado `c2eb08e` (Claude, 14/10/2026)

- **Publicado** el 14/10/2026 a las 15:33 UTC.
  - Migraciones `suscripciones 0006` (`Plan.company_limit`, `EmpresaAdicional` y el plan `multiempresa`) y `tenancy 0006`.
  - Respaldo `pre-20261014-153355-c2eb08ef.dump`.
  - Landing publicada desde `c2eb08e`; copia previa en `private/landing-antes-20261014153442.tar.gz`.
- **Planes:**
  - Plan 1000 ($50) e ilimitado ($85): **1 RUC**.
  - **Plan Multiempresa: $199 al año con IVA, hasta 10 RUC distintos, documentos ilimitados.**
- **Reglas de la propietaria:**
  - Pasar de un plan de un RUC al multiempresa empieza un año nuevo desde el pago, sin prorrateo.
  - El Propietario de la empresa titular agrega los RUC desde la app.
  - Se mantiene la mención de retenciones en la landing.
- **Pruebas:** `tests/test_plan_multiempresa.py`. PostgreSQL 275; SQLite 270 + 5 solo PostgreSQL.
  - Hubo que restaurar `tests/test_multiempresa.py`, el de aislamiento entre empresas, que se había sobrescrito por error antes del commit.

## Notas entre agentes — contrato del Plan Multiempresa (Claude → Codex)

- **`/suscripcion/` (plan.html):**
  - Cada opción trae `o.es_mejora`: existe la mejora por diferencia; ya no se deduce de «ilimitado».
  - `o.cambio_multiempresa`: pasar del plan actual al multiempresa (botón «Cambiar a Plan Multiempresa por $199.00»).
  - Variables nuevas:
    - `cubierta` (bool): la empresa es adicional, no ve tarjetas ni botones de pago;
    - `multiempresa` (`{usados, limite}`, solo en la titular).
  - `o.plan.multiempresa` y `o.plan.company_limit`.
  - Clases: `fp-plan-multiempresa` (tarjeta), `fp-plan-cubierta` (aviso de la adicional), `fp-plan-multi` (resumen de la titular).
- **`/suscripcion/empresas/` (`suscripciones/empresas.html`):**
  - POST `accion=nueva` con `ruc`, `business_name`, `tradename`, `main_address`, `email`, `mobile`.
  - POST `accion=vincular` con `empresa` (id).
  - Contexto: `multiempresa`, `periodo`, `usados`, `adicionales` (lista de pares empresa/cubierta), `propietario`, `form`, `vinculables`, `estado`.
  - Hoy solo se llega desde el enlace «Ver y agregar empresas del plan» de Plan y pagos.
- **`EstadoPlan.titular`:** empresa que paga, si la actual es adicional.

## Estado actual — facturación electrónica: firma nativa y Etapa A publicadas `e3a2932` (Claude, 12/10/2026)

- **Publicado:** `e3a2932` en app.facturaporaqui.com el 12/10/2026 a las 02:28 UTC.
  - Incluye `fd656a1`, la firma XAdES-BES nativa en Python, que sustituye al jar Java: le faltaban sus bibliotecas y toda emisión fallaba.
  - Migración `pos 0012` (solo agrega columnas y opciones). Respaldo previo: `pre-20261012-022817-e3a29324.dump`. Salud 200.
  - Revertir el código: `bash deploy/scripts/desplegar.sh pruebas --revertir`. La versión anterior ignora las columnas nuevas.
  - Temporizador nuevo: `facturaporaqui-sri@pruebas.timer`, cada 5 minutos (`manage.py consultar_sri`).
- **Auditoría completa:** `AUDITORIA-SRI-2026-10.md` (hallazgos, fuentes, Etapas B/C y decisiones pendientes).
- **Validado en el ambiente de PRUEBAS del SRI** con el código publicado: factura y nota de crédito AUTORIZADAS; la NC sobre consumidor final fue rechazada con el error 69, como exige 2026.
- **Bloqueo intencional:** en Producción no se emite hasta configurar `FPA_RUC_PROVEEDOR`, el RUC de Suprohosting como proveedor (Anexo 26). Lo confirma la propietaria.
  - Al configurarlo, la primera factura de la empresa 6 será la 001-002-000000271 (el número no se consumió en el intento fallido).
- **Pruebas:** PostgreSQL 257 y SQLite 252 + 5 solo PostgreSQL. `tests/test_emision_sri.py` usa un SRI simulado.
- **13/10/2026, 15:24 UTC — publicado `f787684`:** incluye `3fc3104` de Codex (formularios móviles) y la corrección del error 500 en 12 vistas de edición, que sin sesión cargaban el registro antes de comprobarla (visto en `/pos/client/update/8/`); ahora llevan al login. Respaldo `pre-20261013-152429-f7876848.dump`.
- **13/10/2026 — `FPA_RUC_PROVEEDOR=0941609729001` instalado** en `/etc/facturaporaqui/pruebas.env` (RUC de Suprohosting: Alava Bolaños Jenny Julizza, ACTIVO; respaldo previo en `credenciales/`) y servicio reiniciado. Validado en el SRI de PRUEBAS: factura y NC con «RUC Proveedor», AUTORIZADAS. **La emisión en Producción queda habilitada** para la empresa 6 (próxima factura 001-002-000000271).

- **14/10/2026 03:41 UTC — publicado `bb4f4f2`:** comprobantes impresos.
  - **Primera factura real de la empresa 6**, 001-002-000000271: AUTORIZADA en Producción el 13/10 y enviada por correo. El primer intento automático falló con `SMTPAuthenticationError` (SMTP propio de la empresa); el reenvío de las 16:15 salió bien.
  - **Ticket:**
    - sin «usuario y clave» del portal (la clave era la cédula; el portal genérico para compradores queda para más adelante);
    - «FACTURA N° …» en vez de «TICKET N°»;
    - «Subtotal 15%» (salía «15%%»);
    - «Contribuyente Especial» solo si lo es.
  - **Ticket y RIDE:** datos del proveedor sin teléfono (`FPA_PROVEEDOR_*`): FACTURAPORAQUI, soporte@facturaporaqui.com, Milagro, Manta y Rumiñahui.
  - **Pruebas:** `tests/test_impresos.py`. PostgreSQL 261; SQLite 256 + 5 solo PostgreSQL.

## Pendiente para Codex — Plan Multiempresa

- [x] Landing: diseño final de las tres tarjetas, con la del Multiempresa diferenciada y los textos y precios actuales.
- [x] Plan y pagos: estilo de la tercera tarjeta, del aviso de la empresa cubierta y del resumen de RUC de la titular.
- [x] Diseñar `suscripciones/empresas.html` y proponer un acceso visible a «Empresas del plan» para la titular (menú o selector de empresas); si hace falta un dato nuevo, pedirlo en HANDOFF.
- [x] Piezas de redes que anuncien el Plan Multiempresa, en la línea de `redes/campana-01`.

## Pendiente para Codex — tras la Etapa A

- [ ] Venta (`sale/admin/create.html`): la fecha la fija el servidor (hoy). Mostrar el campo de fecha como solo lectura o como texto.
- [ ] Mensajes largos del SRI (devuelta o no autorizada) en el diálogo de error: legibles en móvil y sin desbordar.
- [ ] Leyenda o ayuda de los estados nuevos en los listados de Ventas y Notas de crédito (ver el contrato abajo).
- [ ] Portal genérico para que los compradores consulten sus comprobantes en línea (pedido de la propietaria para el futuro; hoy el ticket ya no muestra usuario ni clave).
- [ ] Etapa B del RIDE (`sale/format/invoice.html` y `credit_note/format/invoice.html`):
  - razón social, dirección del establecimiento, ambiente y tipo de emisión;
  - fechas de la NC (hoy intercambiadas);
  - «Contribuyente especial» solo si lo es;
  - subtotales por tarifa.

  Coordinar antes los campos con Claude.

## Notas entre agentes — contrato de la Etapa A (Claude → Codex)

- **Estados (`status.id`)**, sin cambiar los anteriores:
  - `without_authorizing` «Sin Autorizar» (guardado y firmado, aún sin enviar);
  - `in_process` «En proceso en el SRI»;
  - `returned` «Devuelta por el SRI»;
  - `not_authorized` «No autorizada por el SRI»;
  - `authorized`, `authorized_and_sent_by_email`, `canceled`, `sequential_registered_error`.
- **Listados:** la acción POST `generate_invoice` envía o, si está `in_process`, consulta. Los botones se llaman «Enviar al SRI» (`without_authorizing` / `returned` / `not_authorized`) y «Consultar autorización en el SRI» (`in_process`).
- **Respuesta JSON** de `add`, `generate_invoice` y `create_credit_note`:
  - Claves: `resp`, `estado`, `mensaje`, `error`, `print_url`, y `en_proceso: true` cuando el SRI todavía autoriza.
  - Con `en_proceso`, el formulario de venta muestra `mensaje` y vuelve al listado sin imprimir.
- **Factura y NC siempre electrónicas:** el formulario envía `create_electronic_invoice=on` oculto y el servidor lo exige igual. En Producción el selector de comprobante ya no incluye el ticket 08.
- **Consumidor final:** cada empresa tiene el suyo (`final_consumer` siempre trae `id`). Tope USD 50: 50,00 exacto es válido.
- **NC (pantalla de notas):** `search_sale` devuelve en `detail[].quantity` lo que queda por acreditar y omite las líneas ya acreditadas. El servidor ignora `price` y `dscto` del navegador.
- **No modificar** `core/pos/emision.py`, `core/pos/notas_credito.py` ni `core/pos/utilities/firma.py` sin coordinar.

## Estado actual — formularios responsive (Codex, 11/10 Ecuador)

Base `9835933`, rama frontend/etapa3. Formularios compartidos adaptados: campos y Select2, tablas de líneas como fichas etiquetadas en móvil, totales, botones y modal. Se mantienen controles y eventos originales; calculadora y backend intactos. Guardado/emisión no ejecutados. No desplegado.

## Pendiente para Codex — formularios

- [x] Adaptar base común y líneas de ventas/compras/notas de crédito.
- [x] Revisar 12 formularios a 360/390/768/1024/1440 px.
- [x] Verificar edición de cantidad y conservación del total/valor al redimensionar.
- [x] Probar modal de cliente y registrar capturas.
- [ ] Probar teléfono físico y teclado virtual, no disponibles en este entorno.

## Notas entre agentes — formularios

No endpoints nuevos. La plantilla de venta ahora omite la selección automática de consumidor final cuando el servidor devuelve `{}`; antes provocaba error Select2 en empresas nuevas sin ese cliente. Conserva la selección cuando existe ID. No cambios a vistas ni facturación.

Claude: revisar/publicar con respaldo y collectstatic después de integrar. La lista de 12 formularios y limitaciones está en RESULTADOS-FRONTEND. Los cambios no incluyen una emisión real, guardado de ventas ni una prueba completa de edición de filas de compras/notas de crédito; verificados sus formularios y layout. Mantener el DOM de filas para los cálculos/eventos existentes.

## Estado actual — diseño del asistente publicado `3348345` (Claude, 11/10/2026)

- **Publicado:** `3348345` en app.facturaporaqui.com el 11/10/2026 a las 23:36 UTC.
  - Incluye el diseño de Codex `7ae6eb7`, integrado por avance directo sobre `0b69f22`, y la corrección del paso 2 `3348345` (ver «Paso 2» del contrato).
  - Sin migraciones. Respaldo previo: `pre-20261011-233635-33483456.dump`. Salud 200.
  - Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir` (vuelve a `d275331`, compatible).
- **Corrección del paso 2:**
  - El primer establecimiento se registra junto con su punto de emisión, en un solo formulario.
  - Antes, el cliente real (empresa 6) no podía escribir su punto: la lista de establecimientos estaba vacía y el error decía «Este campo es obligatorio».
  - Al publicar, la empresa 6 aún no tenía establecimientos ni puntos.
- **Pruebas:**
  - PostgreSQL: **219 aprobadas**, incluidas las de concurrencia.
  - SQLite: **214 aprobadas y 5 omitidas** (solo PostgreSQL).
  - `check` sin problemas y sin migraciones pendientes; `node --check` de los dos JS.
- **Verificación en el dominio** con empresas ficticias. DEMOSTRACIÓN solo recibió envíos que el servidor rechaza; OTRA-DEMO, solo lectura. Detalle en RESULTADOS-FRONTEND.md.
  - Los cinco pasos muestran sus errores con el texto del servidor.
  - «Continuar configuración» lleva al paso 4.
  - El resumen de Compañía es de solo lectura y no tiene campos editables.
  - Comprobantes no tiene acciones; crear una secuencia responde 403.
  - Vista previa 125 → 001-001-000000126, y el servidor rechaza el retroceso.
  - La clave de la firma va vacía, y la firma está bloqueada sin plan.
  - A 360, 390, 768, 1024 y 1440 px no hay desbordes. Foco visible con teclado. 0 errores de consola y 0 respuestas ≥ 400.
  - Los estáticos se sirven con huella, incluido `js/configuracion.<hash>.js`.
  - Numeración de DEMOSTRACIÓN intacta: 001-001-001051714 / 001-001-001016492.
- **Siguen pendientes:**
  - Teléfono físico.
  - PNG de marca (~500 KB).
  - Revisión adicional de Plan y pagos.
  - Que el cliente real complete el asistente.

## Pendiente para Codex — tras la publicación de `3348345`

- [ ] Opcional: revisar el diseño del formulario conjunto del paso 2 (`.fp-config-primer-punto`, dentro de `.fp-config-grid`). Las capturas `asistente-publicado-*.png` muestran cómo quedó.
- [ ] Opcional: la vista previa del paso 3 no conoce el mínimo de la numeración. Con «Ya emití en otro sistema» muestra 126 aunque la numeración vaya por 1051713, y el servidor lo rechaza al guardar. Puede bastar con un aviso; no cambies la validación.
- [x] Optimizar `isotipo.png` y `favicon.png`: compresión sin pérdida completada el 15/10/2026 en ambas carpetas de marca; ver cierre arriba.
- [ ] Pendientes anteriores restantes: revisar Plan y pagos y probar la barra de guardado en un teléfono físico.

## Notas entre agentes — publicación `3348345`

Codex: la corrección del paso 2 cambió `views.py`, `forms.py`, `servicios.py` (dos mensajes nuevos) y el bloque del paso 2 en `asistente.html`. Tu diseño se conserva y solo se reorganizó ese bloque: con establecimientos se ven las dos columnas de siempre; sin ellos, un formulario a todo el ancho. Los IDs siguen tu convención: `id_point_code-establecimiento` e `id_point_description-establecimiento`.

Campaña de redes (`e51a2c8`): fusionada sin reescribir historial (solo `entregas/`). Desde el próximo despliegue, `deploy/scripts/desplegar.sh` ya no copia `entregas/` a las versiones del servidor, así que las imágenes de redes no viajan con Django.

## Estado actual — primera campaña de redes (Codex, 11/10/2026)

10 posts y 10 historias de FacturaPorAquí en `redes/campana-01/`, con colibrí Ingenioso, paleta, captions y guía de publicación. Galería y manifiesto de imágenes revisados, ZIP local de descarga. No publicación externa ni cambio en aplicación.

## Pendiente para Codex — redes

- [x] Crear 10 posts y 10 historias en imágenes.
- [x] Preparar captions, CTA, hashtags y orden de publicación.
- [x] Revisar marca, texto comercial, galería y paquete.
- [ ] Videos: fase posterior indicada por el usuario.

## Notas entre agentes — redes

No se requiere backend. Claude: imágenes y documentos comerciales están en `entregas/facturaporaqui/redes/campana-01/`; no incluirlas en despliegue de Django. Los materiales mencionan funciones disponibles y precios anuales por empresa con IVA; no anuncian retenciones ni financiamiento como servicio disponible. Contacto por mensajes directos y dominio; WhatsApp y correo comercial siguen pendientes. Publicación a cargo del usuario, sin autorización para publicar automáticamente.

## Estado actual — diseño del asistente terminado (Codex, 11/10/2026)

Trabajo en `frontend/etapa3` sobre `0b69f22`, por avance directo sin reescribir historial. Aplicados branding Ingenioso, navegación de cinco pasos, formularios y errores accesibles, aviso de cabecera, resumen de solo lectura y lista de Comprobantes. Vista previa orientativa del próximo número en paso 3. Backend intacto. **No desplegado**: la base publicada informada por Claude sigue siendo `d275331`.

Validación final: **212 pruebas SQLite aprobadas, 5 omitidas exclusivas de PostgreSQL**. Chromium a 360/390/768/1024/1440px, recorrido local completo con datos ficticios, teclado, movimiento reducido, errores de paso 2, contraseña vacía, numeración 125 → 126 y nota de crédito desde 1. Sin pagos ni emisiones. Capturas `asistente-diseno-*.png`.

## Pendiente para Codex — entrega de diseño

- [x] Diseñar asistente, campos, progreso y errores sin alterar contratos.
- [x] Diseñar aviso y resumen de Compañía.
- [x] Revisar Comprobantes como consulta.
- [x] Vista previa orientativa de numeración; validación definitiva del servidor preservada.
- [x] Documentar pruebas y capturas.
- [ ] Pendientes opcionales anteriores: optimización de imágenes y revisión adicional de Plan y pagos.
- [ ] Validar barra de guardado en teléfono físico (no disponible en este entorno).

## Notas entre agentes — entrega para publicar

Claude: no se requieren datos ni endpoints nuevos. Publicar cuando revise por su procedimiento con respaldo. Incluir `static/js/configuracion.js` en collectstatic; el asistente lo carga con defer. El cálculo visual no reserva números ni acepta cambios por sí mismo: mantiene POST y validación del servidor.

Los atributos `name`, acciones paso 2, prefijos 01/04, parámetros de ambiente, CSRF y multipart permanecen intactos. Solo se diferencian IDs DOM de los campos de establecimiento/punto (`-establecimiento`, `-punto`) para evitar duplicados y asociar etiquetas correctamente; nombres POST originales intactos. Mensajes configuracion y ayudas del backend conservados. No se cambiaron vistas, formularios, servicios, modelos ni migraciones.

## Estado actual — asistente de configuración publicado `d275331` (Claude, 11/10/2026)

- **Publicado:** `d275331` en app.facturaporaqui.com desde el 11/10/2026 a las 19:37 UTC.
  - Migraciones `pos 0008–0011` y `tenancy 0005`. Respaldo previo: `pre-20261011-193652-d2753319.dump`. Salud 200.
  - **Revertir el código:** `bash deploy/scripts/desplegar.sh pruebas --revertir`.
  - **Revertir también el esquema:** la versión anterior no rellena las columnas nuevas de `pos_receipt` al crear comprobantes. Para volver del todo hay que restaurar ese volcado; los datos de empresa se vuelcan con `--enable-row-security` y alcance de plataforma.
- **Migración de datos verificada:** no cambió ningún número.
  - Empresa 2: factura 1051713, nota de crédito 1016491, ticket 1. Empresa 3: 990999, 2756341 y 1.
  - Ambas quedaron con el establecimiento y punto 001-001 registrados desde sus comprobantes, pendientes de confirmar.
  - El cliente real (empresa 6) no tenía secuencias: quedó sin establecimientos ni 001-001 asumido. Solo le falta completar el asistente, porque ya tiene firma.
  - El módulo es solo para Propietario y Administrador.
- **Verificación en el dominio,** con la empresa ficticia DEMOSTRACIÓN y la numeración en «mantener», sin cambiar números ni crear ventas:
  - **Antes:** el aviso «Para emitir facturas completa la configuración de facturación (paso 1).» y la venta bloqueada con «… Ve a «Configuración de facturación»: /configuracion/facturacion/paso/1/».
  - **Pasos 1–5** completados por la interfaz.
  - **Después:** el número del próximo documento es 001-001-001051714, igual que antes. Compañía muestra el mismo resumen y ningún campo editable de establecimiento, punto o ambiente.
  - **Comprobantes:** solo consulta («Confirmada»); crear una secuencia responde 403 con el mensaje del paso 3.
  - **Aviso restante:** «… sube tu firma electrónica (.p12) y su clave (paso 4)».
  - **Regresión de la app** a 1366, 390 y 360 px: 0 fallos y 0 errores de JavaScript. Landing sin cambios.
- **Para Codex:** el contrato sigue en «Notas entre agentes — contrato del asistente». La plantilla publicada es funcional, con estilo mínimo.

## Estado actual — asistente de configuración de facturación (Claude, 11/10/2026)

- **Backend listo en `plataforma` y `frontend/etapa3`** (commits `db184cd` y `5175401`). Publicado después en `d275331` (ver la sección anterior).
- La plantilla `configuracion/asistente.html` es funcional y tiene un estilo mínimo (bloque `.fp-config` al final de `static/css/facturaporaqui.css`). El diseño y la marca quedan para Codex.
- **«Secuencia actual»** era el último número usado y se creaba en 1, así que la primera factura salía 000000002. Ahora:
  - se llama «Último número utilizado» y empieza en 0;
  - la interfaz muestra «Número del próximo documento» (último + 1).
- **Pruebas:** PostgreSQL 217/217 (incluye emisiones simultáneas); SQLite 212 más 5 omitidas (solo PostgreSQL).

## Pendiente para Codex — asistente de configuración

- [x] Diseñar `core/configuracion/templates/configuracion/asistente.html` y `_campos.html` (pasos, formularios, errores y progreso) siguiendo el contrato de abajo. Conservar los `name` de los campos, `action`, CSRF y los textos de error del servidor.
- [x] Diseñar el aviso `configuracion/_aviso.html` (cabecera) y el resumen de solo lectura `configuracion/_resumen_compania.html` (sección «Establecimiento y punto de emisión» de Compañía).
- [x] Revisar la lista de Comprobantes (solo consulta: `receipt/list.html` y `receipt/js/list.js`).
- [x] Opcional: vista previa del «Número del próximo documento» en el paso 3 mientras se escribe. El servidor recalcula y valida igual.

## Notas entre agentes — contrato del asistente (Claude → Codex)

### Rutas y permisos

| Ruta | Método | Respuesta |
|---|---|---|
| `/configuracion/facturacion/` | GET | 302 al primer paso pendiente (`paso_actual`); así se retoma |
| `/configuracion/facturacion/paso/<n>/` | GET, POST | n = 1…5 (otro valor → 404). Plantilla `configuracion/asistente.html` |
| `/configuracion/facturacion/estado.json` | GET | JSON del estado (ver «Estado») |

- **Permisos:** módulo «Configuración de facturación» (`/configuracion/facturacion/`). Solo **Propietario** y **Administrador** (y superusuario); Contador, Vendedor, Consulta y Cliente no lo tienen.
  - Sin permiso: un GET redirige con «Tu perfil no cuenta con el permiso necesario para ingresar».
  - Un POST responde 403 JSON `{"error": "Tu perfil no cuenta con el permiso necesario para ingresar"}`.
  - Se necesita empresa activa (selector).
- **Aislamiento:** todo se filtra por la empresa activa (ORM y seguridad por filas de PostgreSQL en `pos_establishment`, `pos_emissionpoint`, `pos_billingsetup` y `pos_receipt`). Un `point` de otra empresa → 404.
- **Mensajes del asistente:** usan la etiqueta `configuracion` y se muestran dentro de la página. `vtc_body.html` y `hzt_body.html` ya no los pasan al diálogo de error. Niveles: `success`, `warning` y `error`.

### Contexto común (todas las pantallas)
- `paso` (1–5), `titulo_paso`, `mensajes` (diccionario de textos exactos; ver «Mensajes»).
- `estado`, con estas claves:
  - `completo` (bool), `paso_actual` (int) y `pasos`: `[{numero, titulo, completo}]`.
  - `ambiente`: `{codigo: 1|2, nombre: 'PRUEBAS'|'PRODUCCIÓN'}`.
  - `punto` (objeto o None, con `full_code`, `establishment.code` y `establishment.address`) y `punto_codigo` (`'002-001'` o None).
  - `documentos`: `[{tipo: '01'|'04'|'08', nombre, existe, ultimo, ultimo_completo, proximo, proximo_completo, confirmado, utilizado, origen: 'nuevo'|'otro_sistema'|'existente'|None}]`.
  - `firma`: `{archivo: bool, clave: bool}`. Nunca se envía la clave.
  - `requisitos`: `{factura: [...], nota_credito: [...]}`, cada elemento `{codigo: 'configuracion'|'secuencia'|'firma', mensaje, paso, url}`.
- `/estado.json` devuelve lo mismo, con `punto` como texto (`'002-001'`).

### Progreso
- Se guarda en `BillingSetup.completed_steps` y se vuelve a validar al leerlo. Un paso deja de estar completo si cambian sus datos.
  - **Paso 1:** RUC válido, razón social y dirección matriz.
  - **Paso 2:** hay un punto predeterminado activo.
  - **Paso 3:** existen las secuencias de factura y de nota de crédito del ambiente actual en ese punto.
  - **Paso 4:** ambiente elegido; Producción, además, confirmado.
  - **Paso 5:** confirmado y con secuencias confirmadas.
- Cambiar el punto, la numeración o el ambiente quita el paso 5: hay que volver a confirmar. Los datos de la empresa y la firma no lo quitan.

### Paso 1 — Datos de la empresa
- **Formulario `form` (EmpresaForm):** `ruc`, `business_name`, `tradename`, `main_address`, `obligated_accounting`, `special_taxpayer`, `retention_agent`, `mobile`, `phone`, `email`.
- **POST** correcto → 302 `paso/2/`. Con errores → 200 y errores por campo.
- **RUC no válido:** «Ingresa un RUC válido de 13 dígitos.».

### Paso 2 — Establecimientos y puntos de emisión
- **Contexto:**
  - `establecimientos` (con `points`).
  - `form_establecimiento`: `code`, `point_code`, `address`, `name`, `point_description`. Así quedan juntos los dos códigos, como en 001-002.
  - `form_punto`: `establishment` = id, `code`, `description`.
  - `form_confirmar`: `point` = id, `confirm`.
  - `puede_agregar_punto` (bool): hay al menos un establecimiento activo. *(3348345)*
- **Sin establecimientos (`puede_agregar_punto` falso):**
  - Se muestra un único formulario, «Agrega tu establecimiento y su punto de emisión» (`.fp-config-primer-punto`); el formulario de punto suelto no se muestra.
  - `point_code` es obligatorio y su error es `mensajes.falta_codigo_punto`.
  - Con establecimientos, `point_code` es opcional y su etiqueta dice «(opcional)».
  - Un cliente real se bloqueó con el formulario de punto y la lista vacía, que solo decía «Este campo es obligatorio».
- **POST, campo `action`:**
  - `agregar_establecimiento` → 302 `paso/2/`. Con `point_code`, crea también el punto en la misma transacción. Avisos: «Establecimiento 001 y punto de emisión 001-002 agregados.» o «Establecimiento 002 agregado.».
  - `agregar_punto` → 302 `paso/2/` y aviso «Punto de emisión 002-001 agregado.».
    - Sin establecimiento elegido: `mensajes.elige_establecimiento`.
    - Si la empresa no tiene ninguno (página abierta antes): 302 `paso/2/` con ese mismo aviso.
  - `desactivar_punto` (+ `point`) → 302 `paso/2/`. No se puede con el punto predeterminado ni con uno de numeración usada.
  - `confirmar` (+ `point`, `confirm=on`) → 302 `paso/3/`, aviso «Emitirás desde 002-001.» y Compañía alineada.
  - Otro valor → 404.
- **No se asume 001-001:** las empresas nuevas llegan sin establecimientos y sin códigos.

### Paso 3 — Numeración (por ambiente)
- **Ambiente:** `?ambiente=1|2` (por defecto, el de la empresa).
- **Contexto:** `ambiente`, `ambientes`, `punto` y `documentos`: `[{tipo, nombre, secuencia, form, utilizada, proximo}]`, con `form` prefijado por el tipo.
- **POST:** `ambiente` y, para `tipo` en `01` y `04`:
  - `{tipo}-mode`: `nuevo`, `otro_sistema` o `mantener`;
  - `{tipo}-last_number`;
  - `{tipo}-confirm=on`.
- **Respuesta:**
  - Correcto en el ambiente actual → 302 `paso/4/`.
  - En el otro ambiente → 302 `paso/3/?ambiente=N`.
  - Errores → 200 con `form.non_field_errors` en cada documento.
- **Reglas:**
  - `nuevo`: empieza en 000000001. Exige `confirm`. No vale si la secuencia ya tiene comprobantes o un último número mayor que 0.
  - `otro_sistema`: acepta `125`, `000000125` o `EEE-PPP-000000125` (del mismo punto), entre 1 y 999999998. Exige `confirm`. No puede ser menor que el último número de la secuencia ni que el mayor ya emitido.
  - `mantener`: conserva la existente.
  - Tras guardar, la secuencia queda «Pendiente de confirmar en el paso 5».

### Paso 4 — Firma electrónica y ambiente
- **Formulario `form`:**
  - `environment_type` (1 PRUEBAS, 2 PRODUCCIÓN);
  - `confirm_production` (obligatorio en Producción);
  - `electronic_signature` (archivo `.p12`; requiere plan);
  - `electronic_signature_key` (contraseña: nunca se muestra y vacía conserva la guardada).
- **Contexto:** `firma_habilitada` (hay plan).
- **Validación:** el `.p12` se abre con la clave en el servidor antes de guardarlo.
- **Respuesta:**
  - Correcto → 302 `paso/5/`.
  - Si cambió el ambiente y falta su numeración → 302 `paso/3/` con aviso «Configura la numeración para el ambiente PRODUCCIÓN.».

### Paso 5 — Revisión y confirmación
- **Contexto:** `estado.documentos`, con último número y número del próximo documento, y `estado.requisitos.factura`. **Formulario `form`:** `confirm`.
- **POST** correcto → 302 `paso/5/` y aviso «Configuración confirmada. Ya puedes emitir con la numeración revisada.».
- Al confirmar se fijan las secuencias de factura y nota de crédito y se crea la de tickets (desde 1).

### Mensajes exactos (`servicios.MENSAJES`; `{…}` se sustituye)
- `ultimo_formato`: «Escribe el último número usado: 125, 000000125 o 001-002-000000125.»
- `ultimo_rango`: «El último número debe estar entre 1 y 999999998.»
- `ultimo_otro_punto`: «El número {numero} es de otro punto de emisión ({codigo}); aquí configuras {punto}.»
- `retroceso`: «El último número no puede ser menor que {minimo:09d}: esta numeración ya llegó a ese número.»
- `reinicio_usada`: «Esta numeración ya tiene comprobantes emitidos en FacturaPorAquí; no se puede reiniciar.»
- `reinicio_existente`: «Esta numeración ya existía (último {ultimo}). Para no repetir números, mantenla o indica un último número mayor.»
- `confirmar_nuevo`: «Confirma que nunca has emitido {documento} desde {punto} en {ambiente}.»
- `confirmar_ultimo`: «Confirma que el último número emitido fue {numero}.»
- `falta_punto`: «Primero registra y confirma tu establecimiento y punto de emisión (paso 2).»
- `confirmar_codigos`: «Confirma que estos códigos son los que el SRI asignó a tu RUC.»
- `establecimiento_duplicado`: «Ya existe el establecimiento {codigo}.»
- `punto_duplicado`: «El punto {codigo} ya existe en el establecimiento {establecimiento}.»
- `falta_codigo_punto`: «Escribe también el código del punto de emisión de este establecimiento.» *(3348345)*
- `elige_establecimiento`: «Elige el establecimiento al que pertenece el punto. Si no aparece en la lista, agrégalo primero.» *(3348345)*
- `punto_en_uso`: «Este punto de emisión ya tiene numeración usada o es el punto con el que emites; no se puede desactivar.»
- `confirmar_produccion`: «Confirma que entiendes que en Producción los comprobantes tienen validez tributaria.»
- `firma_sin_plan`: «Para subir tu firma electrónica (.p12) primero activa un plan en «Plan y pagos».»
- `firma_clave`: «La clave no abre este archivo .p12. Revisa la clave o el archivo.»
- `firma_sin_clave`: «Escribe la clave de la firma electrónica.»
- `pasos_pendientes`: «Antes de confirmar completa: {pasos}.»
- `confirmar_revision`: «Confirma que estos son los números con los que debes continuar.»
- Código de establecimiento o punto: «Usa tres dígitos, por ejemplo 001 (000 no es válido).»

### Emisión y pantallas relacionadas
- **Requisitos:** venta (`/pos/sale/admin/add/`, `action=add`), nota de crédito y ticket exigen la configuración confirmada; la emisión electrónica, además, firma y clave.
  - Si falta algo, el JSON trae `error`: «{mensaje} Ve a «Configuración de facturación»: {url}».
  - Ejemplo: «Para emitir facturas completa la configuración de facturación (paso 1). Ve a «Configuración de facturación»: /configuracion/facturacion/paso/1/».
  - **El inventario no se bloquea.**
- **Número en el formulario de venta:** `action=search_voucher_number` devuelve `voucher_number`, `voucher_number_full` (próximo, sin reservar) o `pending` (`{codigo, mensaje, paso, url}`).
- **Aviso de cabecera:** `fpa_config_pendiente` (`{codigo, mensaje, paso, url}`) en `configuracion/_aviso.html`. Solo aparece con plan pagado y para quien puede configurarlo; incluido en `vtc_body.html` y `hzt_body.html` después del aviso del plan.
- **Compañía:** ya no edita `establishment_code`, `issuing_point_code`, `establishment_address` ni `environment_type`. Muestra `configuracion/_resumen_compania.html` con `config=config_facturacion`, que es el mismo `estado`.
- **Comprobantes:** solo consulta.
  - El JSON de `search` añade `environment_type {id, name}`, `last_number_full`, `next_number_full`, `confirmed` y `confirmed_at`.
  - `add`, `update` y `delete` → GET 302 `paso/3/`; POST 403 `{"error": "La numeración de comprobantes se configura en «Configuración de facturación» (paso 3), …"}`.
- **Numeración segura:** la reserva del número es atómica, con bloqueo de fila en la transacción de la venta. Hay unicidad `(receipt, voucher_number)` en ventas y notas de crédito, y nunca se reutiliza un número ya registrado.

## Estado actual — Plan y pagos ajustado, publicado `af1f365` (Claude, 11/10/2026)

- **Publicado:** `af1f365` en app.facturaporaqui.com desde el 11/10/2026 a las 18:40 UTC.
  - Migración `suscripciones.0005`.
  - Respaldo previo: `pre-20261011-183959-af1f365c.dump`. Salud 200.
  - Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir`.
- **Cambios visuales** en `plan.html` y en `static/css/facturaporaqui.css` (bloque «Plan y pagos: resumen del plan actual…» al final; clases `fp-current-summary` y `fp-plan-col`):
  - «Cambiar desde el…» (cambio a ilimitado al vencer) pasa a **«Renovar con ilimitado por $85.00»**, con el precio del plan en el servidor. Debajo: «Nuevo período anual: del … al …. Es una renovación separada de la mejora.».
  - Tarjeta del plan actual con el recuadro «Tu plan actual»: vence el, días restantes, comprobantes usados, disponibles, barra de consumo y «¿Necesitas más? Pasa a ilimitado por $35.00 y conserva tu vencimiento» cuando la mejora aplica (`mejora_destacada` en el contexto).
  - Las tarjetas van lado a lado desde 1360 px, con el resumen de la mejora en dos columnas. Por debajo van apiladas.
  - Espacio vacío de la tarjeta Plan 1000: 415 → 72 px a 1440, 507 → 40 a 1024 y 480 → 40 a 768. Sin desbordamiento de 360 a 1920 px.
- **Regla:** la mejora exige al menos **30 días de calendario** (hora de Ecuador; `PlanUpgrade.min_days`, editable). Antes era «un mes», que hoy serían 31 días y dejaba fuera un plan que vence en 30. «Días restantes» usa la misma cuenta.
- **Verificación sin pagos:**
  - Simulación en el servidor publicado, en una transacción deshecha: plan que vence en 30 días → $35 y vencimiento conservado. PayPhone recibe `amount 3500` (3043 + 457). Ilimitado solo tras confirmar; el retorno duplicado llama una vez a Confirm y aplica una mejora; un solo período; la renovación anual queda aparte (10/11/2026 → 10/11/2027, $85).
  - En el dominio, con OTRA-DEMO y un período temporal de 30 días: tarjeta, botones y checkout «Pagar a Suprohosting $35.00». El período sigue en Plan 1000 sin confirmar. Limpieza hecha.
- **Pruebas:** PostgreSQL 190/190; SQLite 186 más 4 omitidas (solo PostgreSQL).

## Estado actual — mejora por diferencia (Codex, 10/10 Ecuador)

Diseño de mejora en Plan y pagos: importe destacado, IVA incluido, activación tras confirmación y vencimiento conservado. Sin cotización del servidor, la mejora inmediata está deshabilitada; renovación futura intacta. No desplegar aislado sin implementar la regla de cobro de Claude.

## Pendiente para Codex — mejora

- [x] Diseñar resumen responsive y separar mejora de renovación anual.
- [ ] Validar integrado con cotización y pago simulado del backend vigente.
  - *Nota de Claude:* backend publicado en `67f353a` con la cotización real; ya se puede validar en el dominio (sin pagar).

## Notas entre agentes — contrato de mejora para Claude
**11/10 · Claude → Codex:** contrato implementado.
- Además de `disponible`, `amount_cents` y `ends_at`, `o.mejora` trae:
  - `renovacion`: cupo agotado y menos de un mes; el botón «inmediato» es un año nuevo a precio completo.
  - `motivo`: texto del servidor cuando no hay mejora.
- Ajusté mínimamente `plan.html` (motivo en el resumen; «Renovar ahora con …» habilitado cuando `renovacion`), `retorno.html` («Tu plan pasó a … hasta …») y `pago.html` (fila «Operación» en una mejora). Tu prueba `test_upgrade_requires_server_quote_and_preserves_expiry` sigue pasando.
- Con menos de un mes, el plan ilimitado solo muestra «Cambiar desde…». El resumen explica el motivo.


En GET `/suscripcion/`, cada opción elegible debe exponer `o.mejora.disponible` (booleano), `o.mejora.amount_cents` (entero, IVA incluido) y `o.mejora.ends_at` (fecha del período actual). El POST existente `/suscripcion/pagar/` conserva `plan`, `modo=inmediato`, CSRF; no recibe importe del navegador. Cuando está habilitado, el servidor debe recalcular la diferencia, preservar vencimiento y consumo, y activar ilimitado solo al confirmar PayPhone. No marcar disponible antes de implementar esa lógica. Interpretación usada: diferencia completa $85 - $50 = $35 incluso con un mes restante, sin extender un año; no prorrateo por días. Si el usuario quiere prorrateo, confirmar regla antes de cobrar. Pago pendiente debe mantener cotización auditable y confirmar sin duplicar efectos; respetar empresa, permisos y concurrencia. Renovaciones/cambios futuros quedan separados. No se necesitan endpoints nuevos.
## Estado actual — mejora por diferencia publicada (Claude, 11/10/2026)

- **Publicado:** `67f353a` en app.facturaporaqui.com desde el 11/10/2026 a las 03:47 UTC. Es el diseño de Codex `5579ded` más la mejora en el backend.
  - Migraciones `suscripciones.0003` y `0004`.
  - Respaldo previo: `pre-20261011-034657-67f353a0.dump`. Salud 200.
  - Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir`. Las columnas nuevas admiten vacío, así que la versión anterior funciona con ellas.
- **Regla aplicada:**
  - El Plan 1000 pasa a ilimitado por **$35.00 con IVA** (base $30.43 + IVA $4.57) **si le queda al menos un mes de vigencia**. Se conservan inicio, vencimiento y consumo, y no empieza otro año.
  - **Con menos de un mes** no hay mejora: el cambio se hace como renovación, al vencer. Si además el cupo está agotado, «Renovar ahora con Plan ilimitado» abre un año nuevo a $85.
  - El importe y el mes mínimo se editan en /plataforma/ → «Mejoras de plan».
  - Interpretación de la petición «solo si el plazo es menos que un mes…; si quedan pocos días, renovación normal»: mejora con un mes o más, renovación con menos. Si la intención era la contraria, se cambia en la regla sin tocar código.
- **Contrato de Codex cumplido:**
  - `GET /suscripcion/` entrega `o.mejora.disponible`, `o.mejora.amount_cents` y `o.mejora.ends_at`, y además `o.mejora.renovacion` y `o.mejora.motivo`.
  - El POST sigue siendo `plan` + `modo=inmediato` + CSRF; el importe del navegador se ignora.
- **Seguridad del cobro:**
  - Ilimitado se activa solo al confirmar PayPhone.
  - Antes de confirmar se bloquean empresa y período y se revalida: vigente, no mejorado y regla activa. Si ya no aplica, no se confirma y PayPhone reversa el cobro solo.
  - Solo puede haber un pago de mejora en curso por período, y las confirmaciones duplicadas no repiten efectos.
  - Se conservan las correcciones de claves.
- **Pruebas:**
  - PostgreSQL 188/188; SQLite 184 más 4 omitidas (solo PostgreSQL).
  - 16 nuevas de la mejora: un mes justo, pocos días, plan vencido, pago rechazado o cancelado, confirmación duplicada, segundo pago, vencido antes de confirmar, importe distinto, permisos, empresa ajena y cupo agotado.
  - 1 de concurrencia real en PostgreSQL: tres confirmaciones en hilos aplican una sola mejora y llaman una sola vez a PayPhone. La misma prueba falla si se quitan los bloqueos.
- **Verificación en el dominio,** con OTRA-DEMO y un período Plan 1000 temporal sin pago, anulado después:
  - Tarjeta «Paga solo la diferencia $35.00», vencimiento conservado y botón activo, a 1366 y 390 px sin desbordamiento.
  - El checkout oficial dice «Pagar a Suprohosting $35.00». **No se pagó.**
  - Con 10 días restantes aparece el motivo y solo los botones de renovación.
  - En producción, solo el cliente real con Plan 1000 ve la mejora disponible (vence el 10/10/2027).

## Estado actual — publicado `a6b77d5` y landing `61f67f7` (Claude, 11/10/2026)

- **app.facturaporaqui.com:** commit `a6b77d5` desde el 11/10/2026 a las 02:16 UTC. Incluye:
  - los ajustes visuales de Codex `bf66b3e` (leyenda del pastel, barra lateral, logotipo sin ruta, acciones de compañía en móvil y enlace de cierre);
  - la landing de `61f67f7`;
  - la corrección `1b6785d` del listado de usuarios: daba error 500 de DataTables cuando un usuario había confirmado su correo, porque la fecha no se convertía a JSON en `User.toJSON`;
  - la mejora del guion de publicación de la landing (`a6b77d5`).

  Se mantienen la corrección de claves (`7eb9bd0`) y PayPhone en Producción.
  - Respaldo previo: `pre-20261011-021620-a6b77d52.dump`. Sin migraciones. Salud 200.
  - Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir`.
- **facturaporaqui.com:** landing de `61f67f7` con `assets/brand/isotipo.png` y `favicon.png`, publicada a las 02:17 UTC con `deploy/scripts/publicar-landing.sh --publicar 61f67f7`. El guion publica ahora también `landing/assets/` (sin los `.md`).
  - Copia previa del sitio: `private/landing-antes-20261011021701.tar.gz`.
  - `index.html` servido idéntico al del commit; cada recurso citado responde 200.
- **GitHub:** `plataforma` y `frontend/etapa3` apuntan al commit que registra esta publicación (solo documentación sobre `a6b77d5`).
- **Pruebas:** PostgreSQL 169/169; SQLite 166 más 3 omitidas. 2 nuevas en `tests/test_usuarios_json.py`.
- **Verificación en el dominio,** a través de Cloudflare y sin completar pagos:
  - Landing a 1366, 390 y 360 px: el colibrí carga en la cabecera (48×48), en el panel ilustrativo (29×29) y en el pie, con el favicon de marca. Sin desbordamiento, errores ni peticiones externas.
  - App, recorrido completo a las tres medidas: login, selector con dos empresas, panel con 2 gráficos, menú móvil con Escape, compañía con 5 secciones y claves vacías, planes con $50/$85 (botones no pulsados), cambio de empresa y retorno de PayPhone. 0 fallos, 0 errores de JavaScript y 309 estáticos por vista.
  - Además: el listado de usuarios responde 200 sin el aviso de DataTables; la leyenda nueva del pastel tiene 10 botones con `aria-pressed` que cambian al pulsar y ningún nombre cortado; el logotipo de compañía dice «Logotipo guardado.» sin ruta; los 10 usuarios reales se convierten a JSON sin error.

## Estado actual — colibrí de la landing (Codex)

`landing/index.html` usa el logo Ingenioso en cabecera, panel ilustrativo y pie, más favicon. Probado localmente a cinco anchos. Pendiente de publicación por Claude en facturaporaqui.com.

## Pendiente para Codex — logo solicitado

- [x] Incorporar el colibrí en los dos sitios señalados y comprobar responsive.

## Notas entre agentes — publicación de landing
**11/10 · Claude → Codex:** landing de `61f67f7` y ajustes de `bf66b3e` publicados (app en `a6b77d5`). Pendientes visuales:
- `isotipo.png` y `favicon.png` pesan unos 500 KB cada uno (1374×1145) y se muestran a 48 px y menos. Conviene una versión optimizada (WebP o PNG de unos 96 px) y un favicon de 32/180 px.
- La barra de guardado en un teléfono real sigue sin validar en un dispositivo físico. En la prueba automática a 390 px las acciones ya no son fijas.


Claude: publicar `landing/` completo, conservando `assets/brand/isotipo.png` y `assets/brand/favicon.png` en rutas relativas. No se necesita endpoint ni cambio del backend. Los ajustes visuales anteriores de la app están en `bf66b3e`; ambos cambios quedan en frontend/etapa3.

## Estado actual — ajustes visuales posteriores al despliegue (Codex, 11/10)

Sincronizada `frontend/etapa3` con `2199c14`, incluyendo las correcciones de secretos de Claude sin modificarlas. Ajustados leyenda del pastel con nombres completos y botones accesibles, texto de usuario en sidebar, logotipo sin ruta visible, acciones de compañía sin superposición fija en móvil y enlace de cierre con color de marca. Cambios locales pendientes de despliegue por Claude; el dominio publicado informado sigue en `7eb9bd0`.

## Pendiente para Codex — ajustes visuales

- [x] Revisar actualización y documentación de Claude en GitHub.
- [x] Ajustar leyenda, sidebar, logotipo, acciones móviles y cierre de sesión.

## Notas entre agentes — ajustes visuales

No se requieren endpoints nuevos. Se preservan los nombres de carga y borrado del logotipo (`image`, `image-clear`), ayuda de las claves, CSRF y controles del plan. Claude: desplegar esta entrega por el procedimiento habitual y revisar la barra de guardado en un teléfono real. Codex no ha validado táctil/teclado virtual en dispositivo físico ni ejecutado PostgreSQL en esta revisión.

## Estado actual — publicado en app.facturaporaqui.com (Claude)

- **Publicado:** commit `7eb9bd0` en app.facturaporaqui.com desde el 11/10/2026 a las 01:36 UTC (10/10, 20:36 en Ecuador). Es la integración de Codex `5cb91f1` más la corrección de claves de Claude.
  - Respaldo previo de la base: `pre-20261011-013604-7eb9bd01.dump`. Sin migraciones nuevas. Salud `/login/` → 200.
  - Revertir: `bash deploy/scripts/desplegar.sh pruebas --revertir`.
  - En GitHub, `plataforma` y `frontend/etapa3` apuntan a `7eb9bd0`, ambos por avance directo. El commit siguiente solo añade esta documentación y capturas.
- **Landing:** facturaporaqui.com sigue igual, con HTTP 200 y www redirigiendo al dominio principal.
- **Pendiente de backend resuelto:**
  - El formulario de compañía ya no devuelve al navegador la clave de la firma ni la del SMTP: los campos usan `PasswordInput` sin valor, un campo vacío conserva la clave guardada y uno con texto la reemplaza.
  - Además se corrigió una fuga mayor: `Company.toJSON()` viajaba dentro de cada venta y nota de crédito en los listados AJAX, también en el que ven los clientes de la empresa, con esas claves y la configuración SMTP. Ahora excluye `electronic_signature_key`, `email_host`, `email_port`, `email_host_user` y `email_host_password`, y la ruta del `.p12` pasa a ser un booleano.
  - «Ver certificado» usa la clave guardada si no se escribe otra.
- **Pruebas:** 167 en total. Con PostgreSQL 16 pasan las 167 (incluye RLS y concurrencia); con SQLite pasan 164 y se omiten 3 que solo corren en PostgreSQL. 5 son nuevas, en `tests/test_secretos_empresa.py`.
- **Verificación en el dominio** (Playwright a 1366, 390 y 360 px, a través de Cloudflare, con empresas ficticias):
  - Login con el colibrí.
  - Selector con dos empresas y cambio de empresa desde la cabecera.
  - Panel con 2 gráficos de Chart.js.
  - Menú móvil que se abre y se cierra con Escape.
  - Compañía con 5 secciones, firma bloqueada sin plan, claves de tipo `password` sin atributo `value` y sin `is_active`.
  - Ventas redirige a «Plan y pagos» con el aviso; precios $50/$85 con los botones de PayPhone activos y **sin pulsar**.
  - Retorno de PayPhone sin sesión.
  - 0 peticiones fallidas, 0 errores de JavaScript, 0 peticiones externas y 309 estáticos cargados por vista.
  - No se completó ningún pago.

## Estado actual — integración terminada por Codex

La rama `frontend/etapa3` incorpora el backend vigente del bundle `plataforma` (`817be35`) y el handoff/capturas del parche de Claude (`cb59e66`, aplicado con resolución conservando ambas entradas). Cambios de diseño adaptados a esa base: logo de marca en todas las pantallas de acceso, navegación multiempresa preservada, cinco secciones de compañía con firma deshabilitada sin plan, tema de planes/consumo/pagos/retornos, Chart.js y controles del servidor intactos.

Validación local final: 159 pruebas aprobadas, 3 omitidas exclusivas de PostgreSQL; sin migraciones pendientes. Login real, cambio entre dos empresas ficticias, planes gratuito/activo, compañía y categorías de 360 a 1440px, gráficos Chart.js, cierre del menú con Escape y retorno/cancelación anónimos. Sin errores JS, recursos faltantes ni solicitudes externas durante el recorrido. PayPhone deshabilitado en local y ninguna operación de cobro real. No desplegado.

## Pendiente para Codex — cierre de esta entrega
- [x] Importar y revisar documentación/backend vigentes.
- [x] Resolver conflictos conservando registro, selector de empresa y controles del plan.
- [x] Retirar el instalador obsoleto y referencias funcionales a Highcharts.
- [x] Aplicar branding a planes y pantallas de resultado de pago.
- [x] Ejecutar pruebas y registrar capturas.
- [ ] Revisar el despliegue cuando Claude lo publique; no afirmar que el dominio ya usa esta entrega.
  - *Nota de Claude:* publicado como `7eb9bd0` (11/10/2026 01:36 UTC); ya se puede revisar en el dominio.
- [ ] Detalles estéticos vistos en la verificación del dominio (no bloquean):
  - En escritorio, la leyenda del pastel «Stock de productos» corta los nombres largos en el borde de la tarjeta.
  - El nombre del rol se corta en la barra lateral («Propietario OTRA-DE…»).
  - El campo del logotipo de compañía muestra la ruta interna del archivo en vez de un nombre legible.
  - La barra fija «Guardar registro / Cancelar» de compañía tapa un campo en la captura de página completa en móvil; conviene comprobarlo en uso real.
  - El enlace «Cerrar sesión» del selector de empresa conserva el azul por defecto.

## Notas entre agentes — siguiente acción
**2026-10-11 · Claude → Codex:** integración revisada y publicada sin cambios de diseño. La única modificación de Claude encima de `5cb91f1` es backend:
- `core/pos/forms.py`, `core/pos/models.py` (`Company.toJSON`) y `core/pos/views/company/views.py`.
- La prueba nueva `tests/test_secretos_empresa.py`.

`company/field.html` sigue funcionando igual: los campos de clave ya llegan vacíos y con el aviso «Guardada. Déjala vacía para conservarla» en el `placeholder` y en el texto de ayuda. Si se cambia esa plantilla, mantener `{{ field.help_text }}`.

Claude: revisar esta integración y utilizar su procedimiento de despliegue con respaldo. Los modelos, migraciones, vistas/API, SRI, configuración y `.env` coinciden exactamente con la base del bundle; Codex no introdujo cambios de backend. La incorporación de sus commits conserva las eliminaciones de archivos sensibles originales, sin restaurarlos.

Sigue pendiente **backend**: `CompanyForm` no debe precargar `electronic_signature_key` ni `email_host_password` en el HTML de `/pos/company/update/`; un reemplazo vacío debe conservar el secreto anterior. El frontend actual solo oculta el valor que el backend envía. No hacen falta endpoints nuevos para esta entrega. Se conservaron `/suscripcion/`, `/suscripcion/pagar/` (POST con `plan`, `modo`, CSRF), `/suscripcion/pago/<uuid>/`, retorno/cancelación y cambio de empresa.

Las secciones siguientes son antecedentes de Claude y Codex; las menciones a FormValidation pendiente/instalador antiguo quedaron resueltas en esta integración.


## Estado actual (2026-10-10, Claude)

- **Aplicación en servicio:** rama `plataforma` en el commit `817be35`, desplegada en app.facturaporaqui.com. Incluye:
  - Multiempresa, con aislamiento por ORM y por filas en PostgreSQL, selector de empresa y roles.
  - Registro propio de empresas.
  - Gráficos con Chart.js.
  - `static/lib` versionado con verificación de integridad y FormValidation sustituido por una implementación propia compatible.
  - Desde hoy, planes y cobro con PayPhone.
- **PayPhone está en Producción:** cobra a nombre de la tienda Suprohosting y ya registró un pago real de un cliente. Las credenciales están solo en el servidor; nunca en el repositorio ni en estos documentos.
- **Regla de negocio:**
  - Sin plan pagado: inventario gratuito con límites.
  - Facturación y ventas: exigen un plan (Plan 1000 a $50 o Plan ilimitado a $85, IVA incluido).
  - Plan vencido: solo consulta.
  - Detalle en RESULTADOS-FRONTEND.md, entrada «Backend (Claude): planes…».
- **Esta rama (`frontend/etapa3`):**
  - Nace del checkout original y no está integrada ni desplegada.
  - Contiene la entrega de Codex (`b29f1de`) más este commit, que solo añade documentación y capturas.
  - En el servidor hay un ensayo de integración sin commit (rama `ensayo-integracion`), hecho sobre una versión anterior a los planes. No es la referencia para integrar.

## Pendiente para Codex

1. [x] **Integrar la etapa 3 sobre `plataforma`** (la tarea de esta rama). Partir de `plataforma`, no de `main` ni de esta rama tal cual. Al fusionar hay que conservar:
   - El aviso del plan en `vtc_body.html`/`hzt_body.html` y su hoja `suscripciones/css/aviso.css` en `base.html`.
   - El candado `bloqueado_por_plan` en `vtc_sidebar.html`, `hzt_header.html` y `hzt_dashboard.html`.
   - El filtro de mensajes con la etiqueta `plan` en el script de `message_error`.
   - En compañía: la firma deshabilitada sin plan (`firma_habilitada`), la ausencia del campo `is_active` y los campos de firma/SMTP opcionales (también en `company/js/form.js`).
   - El selector de empresa, las membresías y los permisos.
   - No ejecutar `deploy/python/install_frontend.py` en `plataforma`. Descarga Highcharts, que tiene licencia de pago y se sustituyó por Chart.js a pedido de la propietaria, y no verifica la integridad de lo que baja. En `plataforma`, `static/lib` ya está en el repositorio (`deploy/scripts/recuperar_static_lib.py` y `static/lib/MANIFIESTO.json`).
   - Archivos que tocaron las dos ramas: `templates/base.html`, `templates/vtc_sidebar.html`, `templates/hzt_header.html` y `core/pos/templates/company/create.html`.
2. [x] **Aplicar el tema a «Plan y pagos»:** `suscripciones/plan.html`, `pago.html`, `_aviso.html`, `retorno.html` y `cancelado.html`. Hay que conservar:
   - Los formularios POST con CSRF y los campos `plan` y `modo`.
   - Los precios tal como vienen del servidor («$50.00 al año, IVA incluido»).
   - El aviso «Tu plan actual termina hoy, sin prorrateo» en las mejoras inmediatas.
   - El texto que indica el ambiente de PRUEBAS del SRI.
   - Que `retorno.html` y `cancelado.html` funcionen sin sesión.
3. [x] **Probar sin cobrar:** abrir el checkout de PayPhone está bien; completar un pago no, porque sería un cobro real. Usar empresas ficticias. Si se cambian las clases `fpa-` a `fp-`, actualizar `tests/test_suscripciones.py`, que busca `fpa-candado` y `fpa-alerta-plan`.

## Notas entre agentes

- **2026-10-10 · Claude → Codex:** el error `FormValidation is not defined` ya no aplica en `plataforma`. Allí `static/lib/formvalidation-1.9.0` es una implementación propia compatible con la API que usan las plantillas:
  - `formValidation` y los plugins Trigger, SubmitButton, Bootstrap e Icon.
  - Los validadores notEmpty, stringLength, digits, numeric, regexp, callback, remote, date, file e identical.

  No hace falta recuperar el paquete con licencia.
- **2026-10-10 · Claude → Codex:** los archivos `.p12`, `.pfx`, `.key` y `.pem` nunca se entregan por `/media/`: la vista protegida los bloquea y nginx no lee los archivos subidos. Sigue pendiente en backend no devolver al formulario las claves guardadas. Ocultarlas en pantalla no basta, como ya indicó Codex.
- **2026-10-10 · Claude → Codex:** el formulario de compañía de `plataforma` ya permite guardar sin firma ni SMTP. La división en cinco secciones de `b29f1de` es compatible, siempre que el campo de firma conserve el estado deshabilitado y la ayuda cuando no hay plan.

## Entrega 2026-10-10 — rama `frontend/etapa3`

Codex implementó branding y base responsive para login, navegación, formularios y listados. Configuración de compañía dividida en cinco secciones; columnas adaptables, etiquetas asociadas, contraseñas ocultas con control accesible. Listados con acción principal superior y controles DataTables en español. Logo Ingenioso en login/sidebar y favicon. Tema compartido coral/celeste; gráficos conservan los datos y respetan movimiento reducido.

**Integración:** esta rama nace del checkout original y de la rama de landing; no contiene el backend multiempresa vigente de Claude. No reemplazar el despliegue completo ni sobrescribir las plantillas actuales sin adaptar los cambios. Conservar selector de empresa, membresías, aislamiento, campos añadidos y rutas del backend actual. La plantilla de compañía conserva campos adicionales mediante un bloque de respaldo, pero su integración requiere revisión.

**Backend / prerrequisitos pendientes:**
- Recuperar los archivos originales/licencia de FormValidation 1.9.0. No se han desactivado las validaciones. Sigue el error `FormValidation is not defined`; no declarar el guardado listo.
- No devolver claves guardadas de firma/correo al formulario: guardar un reemplazo solo si se aporta y mantener el secreto cuando el campo queda vacío. La implementación frontend actual solo oculta visualmente el valor recibido; no corrige almacenamiento ni exposición en HTML.
- Mantener las firmas fuera de descargas públicas. El cambio frontend no corrige los permisos del servidor ni la emisión SRI.
- Sin endpoints nuevos en esta etapa. Se conservan campos, acciones POST y CSRF existentes.
- Ejecutar `python deploy/python/install_frontend.py` para dependencias públicas faltantes, recuperar las privadas y realizar `collectstatic` en el despliegue.

**Validación:** Django check y diff check; Chromium con login, cinco secciones, mostrar/ocultar clave, compañía sin overflow a 360/390/768/1024/1440px; listado de categorías en español y sin overflow de página a 390px. Capturas en `entregas/facturaporaqui/capturas/`. No se emitió factura ni se probaron permisos multiempresa. No desplegado a producción.

Detalle y próximas entradas: `RESULTADOS-FRONTEND.md`. Claude debe actualizar este archivo conservando entradas relevantes de otras áreas.

## Estado actual
Revisión de coordinación: el usuario informa que PayPhone ya está integrado. No verificado por Codex: GitHub sigue en frontend/etapa3 b29f1de y main 52e51c9; el checkout disponible no contiene el backend vigente de Claude. Antes de adaptar sus pantallas, Claude debe sincronizar el código vigente y documentar sus rutas/datos sin valores secretos. Se mantienen las mejoras visuales locales entregadas previamente.

## Pendiente para Codex
- [x] Leer AGENTS.md y HANDOFF.md y comprobar las ramas remotas antes de preparar instrucciones.
- [x] Leer implementación vigente de Claude cuando esté disponible, incluidos templates y contratos de planes/PayPhone.
- [x] Adaptar y validar frontend sobre esa implementación, conservando aislamiento y comportamiento de pagos.

## Notas entre agentes
Claude: subir o indicar el commit/rama que contiene multiempresa y PayPhone. Registrar las rutas exactas ya implementadas para planes, suscripción, creación de pago, retorno y consulta de estado; nombres de campos, importes, moneda, fechas y cupos que entregan. No inventar endpoints ni compartir tokens. Codex queda limitado a templates, CSS, JavaScript y documentación en frontend/etapa3; modelos, migraciones, vistas de API, SRI y .env quedan fuera de alcance.
