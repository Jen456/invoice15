# Panel y empresa activa (primera entrega: §12 y primer punto de §7)

Rama `fase/pe-panel-empresa` (sobre `96d39e1` = producción `e0f2902` + documentación), código en `1d85dd1`. Sin migraciones.

## Qué pasaba

**§12 — 500 al entrar al panel con varios comercios.** El registro de producción tiene 5 × `GET /` → 500 (12 y 13/11)
con `TenantScopeError: Consulta de datos de empresa sin empresa activa` en `core/dashboard/views.py:60`
(`Client.objects.all().count()`), justo después de iniciar sesión (referer `/login/authenticated/`).

Causa: `CompanyMiddleware` mandaba al selector de empresa a quien no tenía empresa activa, **salvo en `/`**
(`request.path != '/'`, desde el núcleo multiempresa `a4043d2`). Con una sola membresía la empresa se elige sola; con
varias y sin empresa en la sesión, `/` llegaba al panel, que consulta datos de empresa. A `/` llevan «Continuar» de
`/login/authenticated/`, el logo, «Inicio» (`{% url 'dashboard' %}` resuelve a `/`) y `/login/?next=/`. El ingreso
normal (`/dashboard/`) sí pasaba por el selector: por eso el listado de facturas funcionaba al elegir el comercio.

**§7 — la cabecera y la barra lateral mostraban empresas distintas.** No era la sesión: las dos salían de la misma
petición, pero de datos distintos. La cabecera mostraba la empresa activa (`request.company`, sin el RUC); la barra
lateral mostraba solo `request.user.get_short_name`, el nombre de la **cuenta**, que en la revisión era igual al de otra
empresa de la propietaria. Nada en la barra lateral decía qué empresa estaba activa.

**Revisión de «el mismo RUC activo» de punta a punta** (antes y después de `company_switch`):

| Dónde | Hallazgo | Estado |
|---|---|---|
| Pestaña abierta con otra empresa | Sus peticiones AJAX (filtros, listados, gráficos del panel, búsquedas, guardados) recibían los datos de la empresa activa nueva bajo la cabecera de la anterior. Solo algunos flujos mandaban `empresa=<id>` (`core/tenancy/pestanas.py`). | Corregido |
| Menú lateral | `static/js/main.js` recuerda en `localStorage` el grupo y el módulo abiertos **por posición**; con otra empresa (otro rol, otros módulos) quedaba abierto o marcado otro grupo. | Corregido |
| Id viejo de empresa en la sesión | El middleware quitaba `company_id`, pero dejaba `url_last` (página a la que vuelve un permiso denegado) y `module_id` de la empresa anterior. | Corregido |
| Gráficos del panel | En un error, `data` ya era una lista y `data['error'] = …` daba `TypeError` (500). | Corregido |
| Punto de emisión | Se guarda por usuario **y empresa** (`PuntoSeleccionado`) y los elegibles se filtran por la empresa activa: al cambiar se ve el de la empresa nueva (el elegido o su predeterminado), nunca el de la anterior; al volver, el que se había elegido en ella. | Ya estaba bien (probado) |
| Filtros con ids de la otra empresa | El filtro por punto de facturas y notas de crédito ofrece `fpa_puntos` (empresa activa); un id de otra empresa en el envío no devuelve nada (`TenantManager` + RLS). | Ya estaba bien (probado) |
| Memorias por petición | `_fpa_group`, `_fpa_urls_ocultas` (con la pk de la empresa), `_fpa_estado_plan`, etc. viven en el objeto `request`; `company_switch` redirige y la siguiente petición vuelve a calcularlas. No hay cachés por empresa a nivel de módulo (solo el `lru_cache` del esquema XSD del ATS) ni fragmentos de plantilla en caché. De la empresa, la sesión solo guarda `company_id`, `url_last` y `module_id`. | Ya estaba bien |
| Cifras y enlaces del panel | Clientes, proveedores, categorías, productos, últimas ventas y los dos gráficos usan los gestores de empresa; los enlaces del tablero son las URL de los módulos (sin ids). Ninguna vista sobrescribe `company` en el contexto. | Ya estaba bien (probado) |
| Reportes, proformas, importación | Sus filtros no ofrecen empresas ni locales; importación, tributario, contabilidad, adjuntos y el diálogo de cliente de la factura ya mandan `empresa=<id>`. | Ya estaba bien |

## Qué cambió

- `core/tenancy/middleware.py`: `/` ya no está exento; sin empresa activa, `GET` → `/empresas/` y el resto → 403 JSON
  («Selecciona una empresa para continuar»), como cualquier otra ruta de empresa. Si la empresa guardada en la sesión ya
  no vale (membresía o empresa desactivada, id ajeno o inexistente) se quitan también `url_last` y `module_id`. Una
  petición con la cabecera `X-FPA-Empresa` de otra empresa responde 409 `empresa_cambiada` (no en `/empresas/`, `/login/`,
  `/media/` ni las demás rutas sin empresa, así que volver a la empresa de la pestaña sigue funcionando).
- `core/tenancy/pestanas.py`: `CABECERA` y `cabecera_de_otra_empresa(request)`; el 409 es el mismo de siempre
  (`rechazo_empresa_cambiada`).
- `templates/base.html`: `<meta name="fpa-empresa" content="<pk>">` en toda página con empresa.
- `static/js/functions.js`: `jQuery.ajaxPrefilter` manda `X-FPA-Empresa` en cada petición AJAX de jQuery al mismo sitio
  (DataTables incluido) y, ante el 409, muestra el aviso «La empresa activa cambió en otra pestaña…» sin cierre automático.
  `static/js/facturaporaqui.js`: DataTables no suma su alerta técnica en inglés para ese 409.
- `static/js/main.js`: el menú recordado se olvida cuando la página es de otra empresa (`fpa_menu_empresa`), también si
  el cambio se hizo en otra pestaña.
- `core/tenancy/templates/tenancy/company_switcher.html` (cabecera de los dos diseños): el nombre comercial (recortado con
  «…» si es largo; completo en el `title`) sobre «RUC …»; también en el texto para lectores de pantalla y en el encabezado
  del menú (con el rol); las demás empresas, con su RUC. En el diseño horizontal, por debajo de 992 px solo el icono (como
  en móvil): ahí la barra superior ya va llena con «Módulos».
- `templates/vtc_sidebar.html` + `static/css/facturaporaqui.css`: la barra lateral muestra la **empresa activa** (logo,
  nombre comercial, RUC, enlace al selector) y debajo «Usuario: …»; sin empresa activa, el nombre del usuario como antes.
- Selector con `next` (arreglo pendiente del 06/11 en `wt-cierre`, incluido aquí): `core/tenancy/views.py`
  (`destino_interno`, la misma validación para el selector y para `company_switch`: solo rutas internas; otro sitio,
  `//`, `/\`, `javascript:` o vacío → sin `next` y `/dashboard/`), `tenancy/select.html` (campo `next`) y
  `core/security/views/files.py` (un archivo de una empresa del usuario sin empresa activa lleva al selector y, al
  elegir, se abre; de otra empresa o inexistente, 404 como antes).
- `core/dashboard/views.py`: el error de un gráfico responde `{"error": …}`.

## Casos límite

| Caso | Comportamiento | Prueba |
|---|---|---|
| Un comercio | Ingreso → `/dashboard/` 200; `/` 200; cabecera y barra lateral con su RUC (diseños vertical y horizontal). | `TestUnComercio::*` |
| Varios comercios, recién ingresado | Ingreso → `/dashboard/` → `/empresas/`; `/` y `/login/?next=/` → `/empresas/` (antes 500). | `test_ingreso_lleva_al_selector_y_no_al_error`, `test_sin_empresa_activa.py::TestRaiz` |
| Elegir A / cambiar a B | Cabecera, barra lateral, `meta`, menú del rol, punto activo y elegibles, filtro de puntos, listado, cifras y gráfico del panel: solo de la empresa activa; la otra solo aparece como botón «cambiar a». La clave de sesión cambia y queda auditado. | `test_elegir_a_…`, `test_cambiar_a_b_muestra_b_sin_nada_de_a` |
| Cambiar con `next` | Abre esa ruta en la empresa nueva; destinos externos o raros → `/dashboard/` y el selector no los copia. | `test_cambiar_con_next_…`, `test_el_selector_no_lleva_fuera_del_sitio` |
| Id viejo o ajeno en la sesión | Se quita con `url_last` y `module_id`; con varias empresas, al selector; con una, la suya. | `test_id_viejo_de_empresa_en_la_sesion` |
| Membresía desactivada en plena sesión | Con una restante la sesión pasa a ella (decisión ya probada en `test_revision.py`) y ya no queda la última página de la anterior; sin ninguna, al selector; no se puede volver a la desactivada (404). | `test_membresia_desactivada_en_plena_sesion` |
| Empresa desactivada | Sale del selector y de la sesión; con dos restantes, al selector. | `test_empresa_desactivada_en_plena_sesion` |
| Superusuario | Sin empresa → selector (con el enlace a la plataforma); al entrar en una, la ve con su RUC y actúa como Propietario (`platform_enter`). | `test_superusuario_elige_y_ve_esa_empresa`, `TestRaiz::test_superusuario_…` |
| Usuario sin empresas | `/`, `/dashboard/` y cualquier ruta → `/empresas/` una sola vez (sin bucle), con el aviso; POST → 403. | `test_sin_empresas_no_hay_bucle`, `TestRaiz::test_sin_empresas_…` |
| Dos pestañas | La pestaña armada para A, tras cambiar a B en otra, recibe 409 en sus AJAX (listado, filtro, gráficos, búsqueda); recargada, B. Sin cabecera (formularios normales, `fetch`, integraciones) todo sigue igual. | `TestDosPestanas::*` y la comprobación en navegador |
| Archivo de la empresa sin empresa activa | Al selector con `next` y luego el archivo; de otra empresa o inexistente, 404. | `test_sin_empresa_activa.py::TestArchivoDeEmpresaSinEmpresaActiva` |

## Cómo se verificó

- Pruebas nuevas: `tests/test_panel_empresa_activa.py` (16) y `tests/test_sin_empresa_activa.py` (13, la del 06/11
  tal cual). Contra el código de producción (`96d39e1`) fallan 14 de las 16 nuevas (las otras 2 comprueban que no cambia
  lo que ya funcionaba: volver a la empresa de la pestaña y el 403 sin empresa) y 5 de las 13 del 06/11; con la rama
  pasan todas.
- Pruebas existentes relacionadas, en SQLite y en PostgreSQL con RLS:
  - `herramientas/pytest_sqlite.sh wt-pe-panel tests/test_panel_empresa_activa.py tests/test_sin_empresa_activa.py
    tests/test_multiempresa.py tests/test_revision.py tests/test_revision_flujos.py tests/test_seguridad.py
    tests/test_rutas.py tests/test_puntos_por_usuario.py tests/test_archivos.py tests/test_b0_contratos.py
    tests/test_vistas_sin_sesion.py tests/test_plan_multiempresa.py tests/test_recorridos_cierre.py
    tests/test_complemento_contable.py tests/test_login_limite.py tests/test_login_marca.py tests/test_estaticos.py
    tests/test_frontend_integracion.py tests/test_frontend_cobros_puntos.py tests/test_importacion_flujo.py
    tests/test_suscripciones.py tests/test_registro.py tests/test_diseno_factura.py tests/test_escape_listados.py`:
    **426 passed**, 0 fallidas.
  - `herramientas/pytest_pg.sh wt-pe-panel tests/test_panel_empresa_activa.py tests/test_sin_empresa_activa.py
    tests/test_multiempresa.py tests/test_revision.py tests/test_revision_flujos.py tests/test_seguridad.py
    tests/test_rutas.py tests/test_puntos_por_usuario.py tests/test_archivos.py tests/test_rls.py
    tests/test_b0_contratos.py tests/test_plan_multiempresa.py tests/test_vistas_sin_sesion.py`: **183 passed**, 0 fallidas.
- `makemigrations --check --dry-run`: «No changes detected»; `manage.py check`: sin problemas.
- Navegador (Playwright/Chromium) contra un servidor **local** de la rama (`runserver 127.0.0.1:18765`, detenido al
  terminar), base SQLite desechable y datos ficticios (empresas ALFA, BETA y SOLO; usuarios `uno.comercio` y
  `multi.comercio`): **19/19 pasos** — ingreso con uno y con varios comercios, `/` sin empresa al selector, ALFA y luego
  BETA en cabecera, barra lateral, `meta`, menú del rol, punto y filtro de puntos, listado de facturas, nada de ALFA en BETA
  fuera del botón para volver, menú recordado olvidado, dos pestañas (409 con la cabecera de la pestaña, aviso en español,
  sin alerta técnica, sin filas de la otra empresa; recargada, la empresa activa), móvil a 390 px, sin errores de
  JavaScript ni respuestas 5xx. Con un nombre comercial de 39 caracteres, sin desborde a 360/390/768/1024/1440 px en el
  diseño vertical. Guiones, informe y capturas: `/root/capturas/pe-panel-empresa/` en VM101.

## Pendiente o para decidir

- Tras ingresar con varios comercios por un enlace profundo (`/login/?next=/pos/sale/admin/`), el selector lleva al
  panel, no a ese enlace: la redirección del middleware no agrega `next` (no se cambió para no tocar los demás flujos).
- Las llamadas con `fetch` (importación, selector de punto, diálogo de cliente) no llevan la cabecera; las que escriben ya
  mandan `empresa=<id>`.
- Con la membresía de la empresa activa revocada y una sola restante, la sesión pasa a ella sin aviso (comportamiento
  anterior); se podría mostrar un mensaje.
- Diseño horizontal (`hzt`, no es el de la revisión) a 768 px: la barra superior se desborda 19 px aunque la empresa vaya
  solo con su icono; viene de antes (marca, «Módulos», usuario y punto).
- `wt-cierre` tiene el mismo arreglo del 06/11 sin confirmar: esta rama lo incluye (igual en `files.py`, `select.html` y la
  prueba; ampliado en `middleware.py` y `views.py`). Conviene descartarlo allí para no mezclar las dos versiones.
