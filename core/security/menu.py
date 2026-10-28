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
    )),
    ('Importación de documentos', 'fas fa-file-import', 40, (
        ('/importacion/nueva/', 'Nueva importación XML / RIDE', 1),
        ('/importacion/lotes/', 'Lotes e historial', 2),
        ('/importacion/pendientes/', 'Documentos pendientes de revisión', 3),
    )),
    ('Bodega', 'fas fa-boxes', 50, (
        ('/pos/category/', 'Categorías', 1),
        ('/pos/product/', 'Productos', 2),
        ('/pos/product/stock/adjustment/', 'Ajuste de stock', 3),
    )),
    ('Administrativo', 'fas fa-hand-holding-usd', 60, (
        ('/pos/ctas/collect/', 'Cuentas por cobrar', 1),
        ('/pos/debts/pay/', 'Cuentas por pagar', 2),
    )),
    ('Reportes', 'fas fa-chart-pie', 70, ()),   # sin cambios de nombre
    ('Configuración', 'fas fa-cogs', 80, (
        ('/pos/company/update/', 'Empresa', 1),
        ('/configuracion/facturacion/', 'Facturación y numeración', 2),
        ('/importacion/reglas/', 'Reglas de importación y contabilización', 3),
        ('/pos/receipt/', 'Numeraciones registradas', 4),
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
    ('importacion', '/importacion/pendientes/', 'fas fa-tasks', 'Documentos importados pendientes de revisión',
     ('view_documentoimportado', 'change_documentoimportado')),
    ('importacion', '/importacion/reglas/', 'fas fa-sliders-h', 'Reglas de importación y contabilización',
     ('view_reglaimportacion', 'change_reglaimportacion')),
)


def organizar_menu(ModuleType, Module, Permission):
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
        if not permisos.exists():
            continue   # app aún sin migrar: nunca se muestra un módulo sin implementar
        modulo = Module.objects.filter(url=url).first() or Module.objects.create(
            url=url, name=nombres[url][0], icon=icono, description=descripcion)
        modulo.permissions.set(permisos)
    for nombre, _, _, modulos in ESTRUCTURA:
        for url, visible, orden in modulos:
            Module.objects.filter(url=url).update(name=visible, orden=orden, module_type=tipos[nombre])
