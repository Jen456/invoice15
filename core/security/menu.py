"""Organización del menú de empresa (tipos de módulo, nombres y orden), en un solo lugar.

La usan start_installation (instalaciones nuevas) y, en instalaciones existentes, las migraciones de las apps que
añaden módulos (importacion 0003 y 0004, y las de cada app que declare uno en MODULOS_NUEVOS). Recibe los modelos para
poder trabajar con los históricos de una migración. Los módulos se identifican por URL (las URL no cambian para no
romper enlaces); solo cambian el grupo, el nombre visible y el orden. Un módulo que no exista en la base no se crea aquí,
salvo los de MODULOS_NUEVOS y solo cuando su app ya tiene sus permisos (está migrada): nunca se muestra algo que no está
implementado.
"""

# (nombre del grupo, icono —único—, orden, [(url, nombre visible, orden)])
ESTRUCTURA = (
    ('Comprobantes Electrónicos', 'fas fa-file-invoice', 10, (
        ('/pos/sale/admin/', 'Facturas emitidas', 1),
        ('/pos/credit/note/admin/', 'Notas de crédito', 2),
        ('/comprobantes/retenciones/', 'Retenciones emitidas', 3),
        ('/comprobantes/notas-debito/', 'Notas de débito', 4),
        ('/comprobantes/guias/', 'Guías de remisión', 5),
        ('/comprobantes/liquidaciones/', 'Liquidaciones de compra', 6),
        ('/pos/voucher/errors/', 'Errores de comprobantes', 7),
    )),
    ('Cotizaciones', 'fas fa-file-alt', 15, (
        ('/proformas/', 'Proformas', 1),
    )),
    ('Clientes y promociones', 'fas fa-user-friends', 20, (
        ('/pos/client/', 'Clientes', 1),
        ('/pos/promotions/', 'Promociones', 2),
    )),
    ('Compras y gastos', 'fas fa-shopping-cart', 30, (
        ('/pos/purchase/', 'Compras registradas', 1),
        ('/importacion/recibidos/', 'Documentos recibidos', 2),
        ('/pos/provider/', 'Proveedores', 3),
        ('/pos/expenses/', 'Gastos', 4),
        ('/pos/type/expense/', 'Tipos de gastos', 5),
        ('/adjuntos/capturas/', 'Recibos por completar', 6),   # captura rápida de gastos (core/adjuntos)
    )),
    ('Importación de documentos', 'fas fa-file-import', 40, (
        ('/importacion/nueva/', 'Nueva importación XML / RIDE', 1),
        ('/importacion/claves/', 'Importar por claves o reporte del SRI', 2),
        ('/importacion/lotes/', 'Lotes e historial', 3),
        ('/importacion/pendientes/', 'Documentos pendientes de revisión', 4),
    )),
    ('Bodega', 'fas fa-boxes', 50, (
        ('/pos/category/', 'Categorías', 1),
        ('/pos/product/', 'Productos', 2),
        ('/pos/product/stock/adjustment/', 'Ajuste de stock', 3),
    )),
    ('Administrativo', 'fas fa-hand-holding-usd', 60, (
        ('/pos/ctas/collect/', 'Cuentas por cobrar', 1),
        ('/pos/debts/pay/', 'Cuentas por pagar', 2),
        ('/comprobantes/retenciones-recibidas/', 'Retenciones recibidas', 3),   # Etapa 2 (O2)
        ('/adjuntos/', 'Comprobantes de pago', 4),   # comprobantes de pago adjuntos (core/adjuntos)
    )),
    ('Tributario', 'fas fa-balance-scale', 65, (
        ('/tributario/libros/', 'Libros mensuales', 1),   # libros de ventas, compras y retenciones (core/tributario)
        ('/tributario/revision/', 'Revisión del mes', 2),
        ('/tributario/ats/', 'ATS del mes', 3),
        ('/tributario/formularios/', 'Borradores del 104 y del 103', 4),
        ('/tributario/empresas/', 'Revisión de mis empresas', 5),
    )),
    ('Reportes', 'fas fa-chart-pie', 70, ()),   # sin cambios de nombre
    ('Configuración', 'fas fa-cogs', 80, (
        ('/pos/company/update/', 'Empresa', 1),
        ('/configuracion/facturacion/', 'Facturación y numeración', 2),
        ('/configuracion/puntos/', 'Locales y puntos de emisión', 3),
        ('/importacion/reglas/', 'Reglas de importación y contabilización', 4),
        ('/pos/receipt/', 'Numeraciones registradas', 5),
    )),
    ('Seguridad', 'fas fa-lock', 90, ()),
)
# Grupos antiguos que se renombran (conservan su id y sus módulos que no se mueven)
RENOMBRAR = {'Facturación': 'Comprobantes Electrónicos'}

# Módulos que organizar_menu crea si faltan: (app, url, icono, descripción, codenames de la app). El nombre visible, el
# grupo y el orden salen de ESTRUCTURA.
MODULOS_NUEVOS = (
    ('importacion', '/importacion/recibidos/', 'fas fa-inbox', 'Facturas recibidas importadas desde XML o RIDE',
     ('view_documentoimportado', 'add_documentoimportado', 'change_documentoimportado')),
    ('importacion', '/importacion/nueva/', 'fas fa-file-upload', 'Importar comprobantes XML del SRI o RIDE en PDF',
     ('view_documentoimportado', 'add_documentoimportado')),
    ('importacion', '/importacion/lotes/', 'fas fa-layer-group', 'Lotes de importación y su historial',
     ('view_documentoimportado', 'add_documentoimportado')),
    # Importación masiva de comprobantes recibidos (importacion 0007 en instalaciones existentes)
    ('importacion', '/importacion/claves/', 'fas fa-list-ol',
     'Importar comprobantes recibidos pegando claves de acceso o subiendo el reporte del portal del SRI',
     ('view_documentoimportado', 'add_documentoimportado')),
    ('importacion', '/importacion/pendientes/', 'fas fa-tasks', 'Documentos importados pendientes de revisión',
     ('view_documentoimportado', 'change_documentoimportado')),
    ('importacion', '/importacion/reglas/', 'fas fa-sliders-h', 'Reglas de importación y contabilización',
     ('view_reglaimportacion', 'change_reglaimportacion')),
    ('proformas', '/proformas/', 'fas fa-file-contract', 'Cotizaciones sin validez tributaria que se convierten en factura',
     ('view_proforma', 'add_proforma', 'change_proforma', 'delete_proforma')),
    # Etapa 2 (O2): lo crea comprobantes 0023 en instalaciones existentes y start_installation en las nuevas.
    ('comprobantes', '/comprobantes/retenciones-recibidas/', 'fas fa-hand-holding-usd',
     'Retenciones que te hicieron tus clientes sobre tus facturas',
     ('view_retencionrecibida', 'add_retencionrecibida', 'change_retencionrecibida')),
    # Locales y puntos de emisión por usuario: lo crea configuracion 0003 en instalaciones existentes.
    ('configuracion', '/configuracion/puntos/', 'fas fa-store',
     'Locales (establecimientos), puntos de emisión, numeración por punto y puntos autorizados por usuario',
     ('view_puntoautorizado', 'add_puntoautorizado', 'delete_puntoautorizado')),
    # Comprobantes de pago adjuntos (core/adjuntos): lo crea adjuntos 0003 en instalaciones existentes.
    ('adjuntos', '/adjuntos/', 'fas fa-paperclip', 'Comprobantes de pago adjuntos a compras, gastos y pagos a proveedores (ventas y cobros: core/cobros)',
     ('view_adjunto', 'add_adjunto', 'delete_adjunto')),
    # Recibos y notas por completar (captura rápida de gastos): lo crea adjuntos 0006 en instalaciones existentes.
    ('adjuntos', '/adjuntos/capturas/', 'fas fa-camera',
     'Recibos y notas guardados para completar después como gasto o compra (sin efectos contables mientras están pendientes)',
     ('view_captura', 'add_captura', 'change_captura')),
    # Libros mensuales (core/tributario): lo crea tributario 0003 en instalaciones existentes.
    ('tributario', '/tributario/libros/', 'fas fa-book',
     'Libros de ventas, compras y retenciones del mes, por tarifa, exportables a XLSX y CSV', ('view_libros',)),
    ('tributario', '/tributario/revision/', 'fas fa-clipboard-check',
     'Lo que conviene revisar del mes antes de declarar, con su causa y el enlace a cada registro', ('view_revision',)),
    ('tributario', '/tributario/empresas/', 'fas fa-building',
     'Resumen de tus empresas: pendientes de la revisión del mes y acceso a cada una', ('view_revision',)),
    ('tributario', '/tributario/ats/', 'fas fa-file-code',
     'ATS del mes: XML validado contra el esquema oficial del SRI, con lo que queda fuera y por qué', ('view_libros',)),
    ('tributario', '/tributario/formularios/', 'fas fa-file-invoice-dollar',
     'Borradores por casillero del 104 y del 103 para revisar con el contador (no se presentan desde aquí)', ('view_libros',)),
)


def _sin_migrar(apps, app, permisos):
    """Con los modelos históricos de una migración (`apps`): algún modelo de esos permisos no existe en ese estado. Las
    filas de Permission no bastan para saberlo: una vuelta las deja (Django no las borra) y una ida parcial posterior
    crearía el módulo de una app sin sus tablas. Sin `apps` (start_installation, registro real) nunca."""
    if apps is None:
        return False
    for modelo in set(permisos.values_list('content_type__model', flat=True)):
        try:
            apps.get_model(app, modelo)
        except LookupError:
            return True
    return False


def organizar_menu(ModuleType, Module, Permission, apps=None):
    nombres = {url: (nombre, orden) for _, _, _, modulos in ESTRUCTURA for url, nombre, orden in modulos}
    for antiguo, nuevo in RENOMBRAR.items():
        ModuleType.objects.filter(name=antiguo).exclude(name=nuevo).update(name=nuevo)
    tipos = {}
    for nombre, icono, orden, _ in ESTRUCTURA:
        tipo = ModuleType.objects.filter(name=nombre).first()
        if tipo is None:
            ModuleType.objects.filter(icon=icono).exclude(name=nombre).update(icon=f'{icono}-x')   # el icono es único
            tipo = ModuleType.objects.create(name=nombre, icon=icono, orden=orden)
        else:
            tipo.orden = orden
            tipo.save(update_fields=['orden'])
        tipos[nombre] = tipo
    for app, url, icono, descripcion, codigos in MODULOS_NUEVOS:
        permisos = Permission.objects.filter(content_type__app_label=app, codename__in=codigos)
        if not permisos.exists() or _sin_migrar(apps, app, permisos):
            continue   # app aún sin migrar (o deshecha): nunca se muestra un módulo sin implementar
        modulo = Module.objects.filter(url=url).first() or Module.objects.create(
            url=url, name=nombres[url][0], icon=icono, description=descripcion)
        modulo.permissions.set(permisos)
    for nombre, _, _, modulos in ESTRUCTURA:
        for url, visible, orden in modulos:
            Module.objects.filter(url=url).update(name=visible, orden=orden, module_type=tipos[nombre])
