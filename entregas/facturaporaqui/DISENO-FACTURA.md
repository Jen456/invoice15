# Diseño de factura (piloto)

Rama `fase/diseno-factura`, desde `9584308` (producción). Paquete de origen: `Paquete_Estilos_FacturaPorAqui.zip`
(rama de entrega `codex/entrega-diseno-factura`), integrado con las decisiones del orquestador. **Publicado el 08/11/2026 a las 08:38 UTC en app.facturaporaqui.com
(`64c5416`), con el piloto solo en los comercios ficticios DEMOSTRACION (`0990000000001`) y OTRA-DEMO
(`0990000002001`); desde el 08/11 a las 15:28 UTC también en PEDESTAL-TEK S.A (`0993212164001`), a pedido de la
propietaria.** Ver «Publicación».

## Qué hace

- **Configuración → Diseño de factura** (`/configuracion/diseno-factura/`, justo después de «Facturación y numeración»):
  el Propietario o el Administrador eligen una de las cinco **plantillas de FacturaPorAquí** (Clásico, Corporativo,
  Minimalista, Banda de marca, Compacto) y los colores principal y secundario del comercio, ven una factura de muestra y
  guardan. Consulta, Contador y Vendedor no tienen el módulo (ni pantalla, ni guardado, ni vista previa).
- **Solo facturas nuevas.** En la primera firma (`core/pos/emision.preparar`), cada factura guarda una copia del diseño
  vigente en `Sale.ride_diseno` (`{id, version, primary, secondary}`), en el mismo `update()` que la fecha, la clave y el
  XML firmado. Los reintentos (devuelta, no autorizada) no la cambian aunque el comercio cambie su diseño. El RIDE se arma
  siempre desde esa copia (`Sale.ride_pdf`): `generate_pdf_authorized`, la descarga A4, `regenerar_ride` y el correo dan el
  mismo documento. Las facturas sin copia (todas las históricas) salen con el RIDE original, byte a byte el mismo HTML.
- **Solo presentación.** Cambian colores, bordes y espaciado (`static/css/ride_variants.css`). No cambia ningún dato del
  RIDE ni el XML, la firma, el envío al SRI, los impuestos, los secuenciales ni el cupo. Las notas de crédito, notas de
  débito, retenciones, liquidaciones, guías y el ticket no cambian.
- **Vista previa:** `muestra.pdf` arma en memoria una factura ficticia con la identidad del comercio de la sesión
  (`core/comprobantes/ride_muestra.py`): comprador, líneas, número y clave de acceso ficticios (ambiente PRUEBAS, 49
  dígitos con módulo 11), con la marca «MUESTRA · SIN VALIDEZ TRIBUTARIA» en cada página. No crea filas ni archivos ni
  toca secuencias o cupo. Responde `application/pdf` en línea, `Cache-Control: private, no-store` y
  `X-Frame-Options: SAMEORIGIN` (solo esa vista; el resto del sitio sigue en `DENY`; la aplicación no envía CSP
  `frame-ancestors`). La pantalla ofrece también el botón «Abrir la muestra en PDF»; en pantallas de hasta 850 px el
  iframe se oculta (en móviles no muestra PDF) y queda solo el botón.
- **Validación en el servidor:** estilo fuera de los cinco o color que no sea exactamente `#RRGGBB` → HTTP 400 con el
  error en el formulario y nada guardado. `normalize()` solo se usa para leer (pantalla, vista previa, copia).
- **Empresa siempre de la sesión** (`request.company`); un id de empresa en el formulario se ignora. El campo oculto
  `empresa` solo sirve para detectar una pestaña que cambió de empresa, también en la vista previa, y entonces no se
  guarda nada: «Guardar diseño» vuelve a la pantalla (302) con el aviso de empresa cambiada; la vista previa responde
  409 con el aviso en texto (se lee en el iframe), y fetch/XHR o `Accept: application/json`, 409 JSON `empresa_cambiada`.
- **Auditoría:** cada guardado deja `diseno_factura_guardado` con el estilo y los colores antes y después.

## Piloto e interruptor

`FPA_DISENO_FACTURA_PILOTO` (lista de RUC, separados por coma), con la regla del Complemento Contable: `*` solo vale en
desarrollo y en las pruebas automáticas, y un RUC que comparte otra empresa no habilita. Vacía (por defecto), nadie ve el
módulo: no aparece en ningún menú, la pantalla vuelve al tablero con un aviso, la vista previa y el guardado responden
404, y las facturas nuevas no reciben copia. Los PDF ya guardados se siguen sirviendo siempre.

Para el piloto en pruebas: añadir `FPA_DISENO_FACTURA_PILOTO=<RUC>` a `/etc/facturaporaqui/pruebas.env` y reiniciar
`facturaporaqui@pruebas`. Para apagarlo, quitar el RUC y reiniciar: las facturas ya emitidas con copia conservan su
diseño (su PDF ya está guardado) y las nuevas vuelven al RIDE original.

En producción hoy: `FPA_DISENO_FACTURA_PILOTO=0990000000001,0990000002001,0993212164001` (los dos comercios ficticios y
PEDESTAL-TEK S.A, añadido el 08/11 a las 15:28 UTC). Para sumar otro comercio se añade su RUC a esa lista, separado por
coma, y se reinicia el servicio. Mientras el comercio no guarde un diseño, sus facturas siguen con el RIDE original.
Respaldos del archivo en `/root/invoice15/credenciales/` (VM101): `pruebas.env.antes-diseno-20261108-083735` y
`pruebas.env.antes-pedestaltek-20261108-152823`.

## Migraciones (aditivas)

| Migración | Qué hace | Depende de |
|---|---|---|
| `configuracion/0004_diseno_factura` | tabla `DisenoFactura` (una por empresa) + RLS como `configuracion/0002` | `configuracion/0003`, `pos/0019` |
| `configuracion/0005_modulo_diseno_factura` | permisos, módulo del menú (`organizar_menu`) y roles (`sync_roles`) | `configuracion/0004`, `security/0003` |
| `pos/0035_sale_ride_diseno` | `Sale.ride_diseno` (JSON nulo, no editable) | `pos/0034` |
| `tenancy/0012_accion_diseno_factura` | acción `diseno_factura_guardado` en `AuditLog.action` | `tenancy/0011` |
| `configuracion/0006_personalizacion_factura` | v2: `fuente`, `encabezado` y `pie_comercial` en `DisenoFactura` (sin datos nuevos) | `configuracion/0005` |

Instalaciones nuevas: `start_installation` crea el módulo con `organizar_menu` (está en `MODULOS_NUEVOS`).

**Vuelta de v2 a v1** (conserva los diseños; las copias v2 ya emitidas conservan su PDF), antes de `desplegar.sh <entorno> --revertir` y
**con el código nuevo**: `migrate configuracion 0005_modulo_diseno_factura`. Ensayada sobre una copia de producción: esquema,
políticas y tablas iguales a los de la copia intacta. Un RIDE regenerado después con el código anterior pierde los textos comerciales.

**Vuelta completa**, antes de `desplegar.sh <entorno> --revertir` (que no toca la base) y **con el código nuevo** (el anterior no
conoce estas migraciones): `migrate configuracion 0003_modulo_puntos`, `migrate pos 0034_cliente_nacimiento_opcional` y
`migrate tenancy 0011_acciones_kardex` (también deshace 0006: con el código nuevo quedan 5 pendientes). Se pierden los diseños guardados y las copias de las facturas; los PDF ya
guardados no cambian. La vuelta de 0005 quita el módulo y solo los permisos de `DisenoFactura` de los grupos, y devuelve
«Locales y puntos», «Reglas» y «Numeraciones» a los órdenes 3, 4 y 5. Quedan las filas de `Permission` y `ContentType`,
como en las demás vueltas. Ensayado en SQLite (ida, vuelta y otra ida sobre una instalación con menú). Tras la vuelta
se puede volver a pasar por `configuracion 0003` (por ejemplo `migrate configuracion 0002_rls_puntos` y otra vez
`0003_modulo_puntos`): 0003 llama a `organizar_menu` con `apps=apps` y no recrea «Diseño de factura» sin su tabla,
aunque sus filas de `Permission` sigan en la base (antes de este arreglo lo recreaba, con la pantalla rota). Esa
pasada usa los órdenes del menú del código nuevo («Locales y puntos» en 4), lo que solo deja un hueco en el orden.

## Logo y nombre comercial

Se usan los de la empresa, como hoy. El paquete proponía tomarlos del establecimiento, pero `Establishment` solo tiene
nombre y dirección (sin logo ni nombre comercial), y el RIDE debe coincidir con el XML autorizado: `nombreComercial` es
`company.tradename` y `core/comprobantes/fidelidad.py` lo compara. La pantalla lo explica y enlaza a los datos de la
empresa.

## Limitaciones

- Los PDF de facturas ya emitidas no se regeneran con un estilo: las históricas no tienen copia.
- `regenerar_ride` usa la copia de cada factura (no el diseño actual), así que un cambio de diseño no altera un PDF
  regenerado.
- Los estilos y sus colores por defecto están en `core/comprobantes/ride_styles.py`; un estilo nuevo necesita su
  migración de `choices` y su CSS. La copia guarda `version` (1 o 2) para distinguir cambios futuros del CSS.
- Sin logo, la cabecera queda sin imagen, como hoy.
- v2: el pie del proveedor sale de `ride_styles.PROVEEDOR_FIJO` (hoy idéntico a `datos_proveedor()` y al RUC del XML). Si cambian los datos del
  proveedor en la configuración, hay que cambiar también esa constante.
- v2: con textos comerciales, una factura corta puede pasar a 2 páginas y la segunda llevar solo el pie comercial (pasa con
  Corporativo, Minimalista y Banda). No se pierde ningún dato y el pie del proveedor sale en todas; ninguna regla CSS sencilla lo evita.
- `fidelidad.py` busca cada dato en todo el texto del PDF, no campo por campo (viene de antes): un cambio de dirección matriz no se detecta si
  la antigua sigue como dirección del establecimiento. `regenerar_ride --aplicar` conserva siempre el PDF anterior.
- La vista previa usa la numeración configurada de facturas solo para mostrar el establecimiento y el punto; si falta,
  muestra 001-001.

## Pruebas

`tests/test_diseno_factura.py` (51) y `tests/test_zz_diseno_factura_pg.py` (1, solo PostgreSQL: dos primeros guardados
simultáneos dejan una fila y la RLS aísla el diseño de cada empresa). Cubren roles, cambio de comercio en la misma sesión
(id de empresa del formulario ignorado; pestaña vieja: 302 con aviso, 409 en texto en la vista previa y 409 JSON con
fetch/XHR), POST inválidos (400 sin guardar), piloto apagado y
encendido, copia en la primera firma y estable en el reintento (SRI simulado, firma con el .p12 de prueba), HTML de las
históricas idéntico al de `9584308` (hash de la plantilla), los cinco estilos con colores claros y oscuros (mismo texto
fiscal con pypdfium2 y clave legible con zxingcpp), 62 líneas en varias páginas, la vista previa (cabeceras, marca en cada
página, sin filas ni archivos nuevos), descarga A4 y adjunto del correo con los mismos bytes guardados y `regenerar_ride`
fiel con la copia. Ajustes en pruebas existentes: `test_b0_contratos` (lista de MODULOS_NUEVOS), `test_puntos_por_usuario`
(«Locales y puntos» pasa al orden 4), `test_rutas` (la vista previa responde 404 con el piloto apagado) y
`test_migracion_vuelta_fase` (41 pendientes tras la vuelta: + pos 0035 y tenancy 0012; y una prueba nueva: vuelta del
diseño, otra pasada por configuracion 0003 sin el módulo y otra ida igual a la instalación). `tests/conftest.py` apaga
el piloto en todas las pruebas (fixture `diseno_piloto_apagado`), aunque el entorno exporte
`FPA_DISENO_FACTURA_PILOTO`.

## Diseño de factura v2 (entrega de Codex `23ac7e0`)

Misma ruta, permisos, piloto y guardado por comercio. Añade cinco plantillas diferenciadas, tipografía (lista cerrada: original,
Liberation Serif, DejaVu Sans, DejaVu Serif), encabezado comercial (100 caracteres, solo en la página 1) y pie comercial (180, después
de los totales). Guardar desde la pantalla crea `version=2`; las filas y copias v1 siguen en v1 hasta que el comercio guarde, y la
pantalla se lo avisa, porque la vista previa ya dibuja v2. La copia v2 lleva `fuente`, `encabezado` y `pie_comercial`. «Original FacturaPorAquí»
guardado con su paleta, su letra y sin textos es idéntico píxel a píxel al RIDE original. El pie del proveedor sale en todas las páginas.

Ajustes de la integración: `regenerar_ride` compara con el XML sin los textos comerciales (un texto con los datos del emisor escondía un
cambio posterior); `validar` rechaza controles, separadores U+2028/U+2029 y marcas bidi; la marca de agua de la muestra no hereda la
tipografía; aviso para quien sigue en v1. Pruebas de la entrega en `tests/test_diseno_factura_v2.py` y `tests/test_diseno_factura_v2_cruces.py`.

## Publicación (08/11/2026)

- **Código:** `64c5416` = `8b1ba19` (integración) + correcciones de la revisión independiente (5 hallazgos de severidad
  baja: menú tras la vuelta, piloto en pruebas, pestaña vieja y vista previa en móvil). Suites completas sobre `64c5416`:
  SQLite 1791 passed + 55 skipped, PostgreSQL 1846 passed, 0 fallos.
- **Validación previa:** RIDE contra el Anexo 2 de la ficha técnica offline v2.34 (vigente al 08/11/2026; pág. 60 sin
  cambios desde v2.27): mismo texto fiscal que el original en los 36 PDF con estilo, clave de 49 dígitos completa, código
  de barras legible en color, gris y B/N a 200 y 300 ppp, 62 líneas en 5 páginas sin filas partidas, contraste mínimo
  4,69:1. Navegador con dos comercios ficticios (57/57) y ensayo de las migraciones sobre una copia del respaldo diario
  (4 pendientes, ida de 11 s, RLS forzada, 76 tablas previas idénticas).
- **Despliegue:** `desplegar.sh pruebas 64c5416` a las 08:37–08:38 UTC; volcado previo
  `respaldos/pre-20261108-083748-64c54164.dump`; migraciones configuracion 0004–0005, pos 0035 y tenancy 0012; salud 200.
- **Comprobado en producción:** los 34 PDF guardados conservan su sha256; 0 de 23 facturas con copia (no se emitió
  nada); el módulo solo aparece a Propietario y Administrador de las empresas 2 y 3 (oculto en las otras 8 y sin
  empresa); vista previa privada (`private, no-store`, `SAMEORIGIN`); diseño guardado y recargado en cada comercio
  ficticio (Corporativo y Compacto con colores propios); móvil sin recuadro vacío; regresiones de solo lectura 72/72 y
  14/14, sin errores de JavaScript ni respuestas 5xx. Guiones: `/root/capturas/fpa-diseno-publicado.mjs`,
  `fpa-verificar-publicado.mjs` y `fpa-verificar-cierre-op.mjs` (VM101).
- **Revertir:** con el código nuevo, `migrate configuracion 0003_modulo_puntos`, `pos 0034` y `tenancy 0011` (ver
  «Vuelta»), y después `desplegar.sh pruebas --revertir`. Solo apagar el piloto no requiere revertir.
