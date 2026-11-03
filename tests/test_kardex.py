"""Kardex con costo promedio ponderado (core/contabilidad): calculado desde los documentos con las mismas reglas con que
cambia el stock (compras, ventas, notas de crédito, anulaciones con ajuste, ajustes de stock registrados), completable con
movimientos manuales (saldo inicial, entradas y salidas) que no cambian el stock; costo desconocido sin inventarlo;
inventario valorizado; XLSX sin fórmulas; API idempotente; permisos y separación entre empresas."""
import io
import json
from datetime import timedelta
from decimal import Decimal

import openpyxl
import pytest
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.contabilidad import kardex as kx
from core.contabilidad.models import AjusteInventario, MovimientoManual
from core.pos import compras, notas_credito
from core.pos.models import Product, Purchase, Sale
from core.security.models import Module, ModuleType
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER
from tests import ayuda_compras, helpers
from tests.ayudas_ventas import factura_autorizada
from tests.test_emision_sri import empresa, p12  # noqa: F401 - empresa firmada y configurada en producción

pytestmark = pytest.mark.django_db
HOY = timezone.localdate()
D1, D2, D3 = HOY - timedelta(days=30), HOY - timedelta(days=20), HOY - timedelta(days=10)


def en(empresa, funcion):
    with company_context(empresa):
        return funcion()


def comprar(empresa, usuario, producto, cantidad, precio, fecha):
    proveedor = ayuda_compras.crear_proveedor(empresa)
    datos = ayuda_compras.datos_compra(proveedor, fecha_emision=fecha.isoformat(), date_joined=fecha.isoformat())
    with company_context(empresa):
        return compras.crear_compra(empresa, usuario, datos, [ayuda_compras.linea_producto(producto, cant=cantidad, price=precio)])


def stock(empresa, producto):
    return en(empresa, lambda: Product.objects.get(pk=producto.pk).stock)


def ver(empresa, producto, desde=D1 - timedelta(days=5), hasta=HOY):
    return en(empresa, lambda: kx.kardex(Product.objects.get(pk=producto.pk), desde, hasta))


@pytest.fixture
def producto(empresa):
    return ayuda_compras.crear_producto(empresa, 'KDX1', stock=0)


@pytest.fixture
def cliente(empresa):
    return helpers.crear_cliente('cliente.kardex', empresa, '0912345678', '0990000001')


@pytest.fixture
def recorrido(client, empresa, admin, producto, cliente):
    """Compra 10 × 2.00, compra 10 × 3.00, venta de 5, nota de crédito por toda la venta y ajuste de stock de 20 a 18."""
    comprar(empresa, admin, producto, 10, '2.00', D1)
    comprar(empresa, admin, producto, 10, '3.00', D2)
    venta = factura_autorizada(empresa, cliente, admin, producto, cantidad=5, fecha=D3)
    with company_context(empresa):
        with transaction.atomic():
            nota = notas_credito.crear(empresa, venta.pk, None, 'Devolución de prueba')
    assert stock(empresa, producto) == 20
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    respuesta = client.post('/pos/product/stock/adjustment/', {'action': 'create', 'products': json.dumps([{'id': producto.pk, 'newstock': 18}])})
    assert respuesta.status_code == 200 and 'error' not in respuesta.json(), respuesta.content
    return {'venta': venta, 'nota': nota}


class TestPromedioPonderado:

    def test_recorrido_completo_cuadra_con_el_stock(self, empresa, producto, recorrido):
        k = ver(empresa, producto)
        assert [m['tipo'] for m in k['movimientos']] == ['compra', 'compra', 'venta', 'ajuste_salida', 'devolucion']
        compra1, compra2, venta, ajuste, devolucion = k['movimientos']
        assert (compra1['costo_unitario'], compra1['saldo_cantidad'], compra1['saldo_valor']) == (Decimal('2.000000'), 10, Decimal('20.00'))
        assert compra2['costo_promedio'] == Decimal('2.500000') and compra2['saldo_valor'] == Decimal('50.00')
        assert (venta['salida'], venta['costo_unitario'], venta['costo_total'], venta['saldo_cantidad']) == (5, Decimal('2.500000'), Decimal('12.50'), 15)
        assert (ajuste['salida'], ajuste['costo_total'], ajuste['saldo_cantidad']) == (2, Decimal('5.00'), 13)
        assert (devolucion['entrada'], devolucion['costo_unitario'], devolucion['saldo_cantidad']) == (5, Decimal('2.500000'), 18)
        assert devolucion['documento']['id'] == recorrido['nota'].pk and venta['documento']['url'].endswith(f'/{recorrido["venta"].pk}/')
        final = k['saldo_final']
        assert (final['cantidad'], final['valor'], final['costo_promedio'], final['conocido']) == (18, Decimal('45.00'), Decimal('2.500000'), True)
        assert k['diferencia_stock'] == 0 and stock(empresa, producto) == 18 and k['advertencias'] == []
        ajuste_guardado = en(empresa, lambda: AjusteInventario.objects.get(producto=producto))
        assert (ajuste_guardado.anterior, ajuste_guardado.nuevo, ajuste_guardado.origen) == (20, 18, 'ajuste')

    def test_periodo_con_saldo_anterior(self, empresa, producto, recorrido):
        k = ver(empresa, producto, desde=D3, hasta=HOY)
        assert k['saldo_anterior'] == {'cantidad': 20, 'valor': Decimal('50.00'), 'costo_promedio': Decimal('2.500000'), 'conocido': True}
        assert [m['tipo'] for m in k['movimientos']] == ['venta', 'ajuste_salida', 'devolucion']
        pasado = ver(empresa, producto, desde=D1, hasta=D2)
        assert pasado['saldo_final']['cantidad'] == 20 and pasado['diferencia_stock'] is None   # sin comparar con el stock de hoy

    def test_un_documento_borrado_recalcula_lo_posterior(self, empresa, admin, producto):
        primera = comprar(empresa, admin, producto, 10, '2.00', D1)
        comprar(empresa, admin, producto, 10, '4.00', D2)
        assert ver(empresa, producto)['saldo_final']['costo_promedio'] == Decimal('3.000000')
        with company_context(empresa):
            compras.eliminar_compra(Purchase.objects.get(pk=primera.pk), admin)
        k = ver(empresa, producto)
        assert (k['saldo_final']['cantidad'], k['saldo_final']['costo_promedio'], k['diferencia_stock']) == (10, Decimal('4.000000'), 0)


class TestCompletarAMano:

    def test_saldo_inicial_reinicia_el_kardex(self, empresa, admin, producto):
        comprar(empresa, admin, producto, 10, '2.00', D1)
        comprar(empresa, admin, producto, 10, '3.00', D2)
        with company_context(empresa):
            MovimientoManual.objects.create(clave='saldo-inicial-0001', producto=producto, tipo='saldo_inicial', fecha=D2, cantidad=7,
                                            costo_unitario=Decimal('4.000000'), documento='Inventario físico al corte')
        k = ver(empresa, producto)
        assert [m['tipo'] for m in k['movimientos']] == ['saldo_inicial', 'compra']   # la compra anterior al saldo no cuenta
        assert (k['saldo_final']['cantidad'], k['saldo_final']['valor']) == (17, Decimal('58.00'))
        assert k['saldo_final']['costo_promedio'] == (Decimal('58') / 17).quantize(kx.SEIS)
        assert k['diferencia_stock'] == 20 - 17 and any(a['codigo'] == 'diferencia_stock' for a in k['advertencias'])
        assert stock(empresa, producto) == 20   # los movimientos manuales no cambian el stock

    def test_costo_desconocido_sin_inventarlo(self, empresa, admin, producto, cliente):
        factura_autorizada(empresa, cliente, admin, producto, cantidad=3, fecha=D1)    # vende sin entradas registradas
        comprar(empresa, admin, producto, 5, '2.00', D2)
        k = ver(empresa, producto)
        venta, compra = k['movimientos']
        assert venta['costo_unitario'] is None and venta['saldo_cantidad'] == -3 and venta['conocido'] is False
        assert compra['saldo_cantidad'] == 2 and compra['conocido'] is False and k['saldo_final']['valor'] is None
        assert {a['codigo'] for a in k['advertencias']} >= {'saldo_negativo', 'costo_desconocido'}
        with company_context(empresa):   # el contador completa: saldo inicial antes de la venta
            MovimientoManual.objects.create(clave='saldo-inicial-0002', producto=producto, tipo='saldo_inicial', fecha=D1, cantidad=3,
                                            costo_unitario=Decimal('1.500000'), documento='Conteo inicial')
        k = ver(empresa, producto)
        assert k['saldo_final'] == {'cantidad': 5, 'valor': Decimal('10.00'), 'costo_promedio': Decimal('2.000000'), 'conocido': True}

    def test_salida_y_entrada_manuales(self, empresa, admin, producto):
        comprar(empresa, admin, producto, 10, '2.00', D1)
        with company_context(empresa):
            MovimientoManual.objects.create(clave='entrada-manual-001', producto=producto, tipo='entrada', fecha=D2, cantidad=10,
                                            costo_unitario=Decimal('4.000000'), documento='Factura 001-001-77 (antigua)')
            MovimientoManual.objects.create(clave='salida-manual-0001', producto=producto, tipo='salida', fecha=D3, cantidad=4,
                                            documento='Acta de baja 3', nota='Mercadería dañada')
        movimientos = ver(empresa, producto)['movimientos']
        assert [m['tipo'] for m in movimientos] == ['compra', 'entrada_manual', 'salida_manual']
        assert movimientos[2]['costo_unitario'] == Decimal('3.000000') and movimientos[2]['saldo_valor'] == Decimal('48.00')


class TestOtrosDocumentos:

    def test_factura_anulada_con_ajuste_vuelve_al_costo_de_su_venta(self, empresa, admin, producto, cliente):
        comprar(empresa, admin, producto, 10, '2.00', D1)
        venta = factura_autorizada(empresa, cliente, admin, producto, cantidad=4, fecha=D2)
        comprar(empresa, admin, producto, 6, '5.00', D3)   # el promedio cambia después de la venta
        with company_context(empresa):   # lo que deja anulados.marcar con ajustar_stock=True
            Sale.objects.filter(pk=venta.pk).update(anulado_sri_fecha=HOY, anulado_sri_motivo='Error', anulado_sri_stock=True)
            Product.objects.filter(pk=producto.pk).update(stock=F('stock') + 4)
        k = ver(empresa, producto)
        anulacion = k['movimientos'][-1]
        assert anulacion['tipo'] == 'anulacion_venta' and (anulacion['entrada'], anulacion['costo_unitario']) == (4, Decimal('2.000000'))
        assert (k['saldo_final']['cantidad'], k['saldo_final']['valor'], k['diferencia_stock']) == (16, Decimal('50.00'), 0)

    def test_nota_de_credito_del_proveedor_avisa(self, empresa, admin, producto):
        compra = comprar(empresa, admin, producto, 3, '2.00', D1)
        en(empresa, lambda: Purchase.objects.filter(pk=compra.pk).update(tipo_comprobante='04'))
        k = ver(empresa, producto)
        assert k['movimientos'][0]['entrada'] == 3 and 'nc_proveedor' in {a['codigo'] for a in k['advertencias']}

    def test_otra_empresa_no_cuenta(self, empresa, empresa_b, admin, producto):
        comprar(empresa, admin, producto, 10, '2.00', D1)
        ajeno = ayuda_compras.crear_producto(empresa_b, 'KDX1', stock=0)
        comprar(empresa_b, admin, ajeno, 7, '9.00', D1)
        assert ver(empresa, producto)['saldo_final']['cantidad'] == 10
        assert en(empresa, lambda: kx.cargar([ajeno.pk], HOY)) == {}


class TestInventario:

    def test_inventario_valorizado(self, empresa, admin, producto, cliente):
        comprar(empresa, admin, producto, 10, '2.00', D1)
        otro = ayuda_compras.crear_producto(empresa, 'KDX2', stock=0)
        factura_autorizada(empresa, cliente, admin, otro, cantidad=2, fecha=D2)   # sin entradas: costo desconocido
        ayuda_compras.crear_producto(empresa, 'KDX3', stock=0)                    # sin movimientos ni stock: no aparece
        hoy = en(empresa, lambda: kx.inventario(HOY))
        filas = {f['producto']['codigo']: f for f in hoy['filas']}
        assert set(filas) >= {'KDX1', 'KDX2'} and 'KDX3' not in filas
        assert (filas['KDX1']['cantidad'], filas['KDX1']['valor'], filas['KDX1']['diferencia_stock']) == (10, Decimal('20.00'), 0)
        assert filas['KDX2']['conocido'] is False and filas['KDX2']['valor'] is None
        assert hoy['totales']['sin_costo'] >= 1 and hoy['totales']['valor_conocido'] >= Decimal('20.00')
        antes = en(empresa, lambda: kx.inventario(D1 - timedelta(days=1)))
        assert 'KDX1' not in {f['producto']['codigo'] for f in antes['filas']}


class TestPantallasYApi:

    def test_paginas_api_y_xlsx_sin_formulas(self, client, empresa, admin, producto, recorrido):
        with company_context(empresa):
            MovimientoManual.objects.create(clave='entrada-formula-1', producto=producto, tipo='entrada', fecha=D1, cantidad=1,
                                            costo_unitario=Decimal('1.000000'), documento='=HYPERLINK("http://example.com")')
        pagina = client.get(f'/contabilidad/kardex/?producto={producto.pk}&desde={D1 - timedelta(days=5)}&hasta={HOY}')
        assert pagina.status_code == 200 and 'data-tipo="devolucion"' in pagina.content.decode()
        datos = client.get(f'/contabilidad/api/kardex/{producto.pk}/?desde={D1 - timedelta(days=5)}').json()
        assert datos['saldo_final']['cantidad'] == 19 and datos['movimientos'][0]['costo_unitario'] == '1.000000'
        assert datos['capacidades'] == {'ver': True, 'registrar': True, 'anular': True, 'bloqueo': None}
        archivo = client.get(f'/contabilidad/kardex/exportar/?producto={producto.pk}&desde={D1 - timedelta(days=5)}&empresa={empresa.pk}')
        assert archivo.status_code == 200 and archivo['Content-Disposition'].startswith('attachment; filename="kardex-KDX1-')
        libro = openpyxl.load_workbook(io.BytesIO(archivo.content))
        assert not [c for h in libro for f in h.iter_rows() for c in f if c.data_type == 'f']
        assert any(c.value == '=HYPERLINK("http://example.com")' for f in libro.active.iter_rows() for c in f)
        inventario = client.get(f'/contabilidad/inventario/exportar/?fecha={HOY}')
        assert inventario.status_code == 200 and not [c for h in openpyxl.load_workbook(io.BytesIO(inventario.content))
                                                      for f in h.iter_rows() for c in f if c.data_type == 'f']
        assert client.get(f'/contabilidad/inventario/?fecha={HOY}').status_code == 200
        assert client.get(f'/contabilidad/api/inventario/?empresa={empresa.pk + 999}').status_code == 409
        assert client.get(f'/contabilidad/api/kardex/{producto.pk}/?empresa={empresa.pk + 999}').status_code == 409
        buscados = client.get('/contabilidad/api/kardex/productos/?q=KDX').json()['productos']
        assert [p['id'] for p in buscados] == [producto.pk]

    def test_api_de_movimientos_manuales(self, client, empresa, admin, producto):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        datos = {'clave': 'mov-manual-0001', 'producto': producto.pk, 'tipo': 'entrada', 'fecha': D1.isoformat(), 'cantidad': '4',
                 'costo_unitario': '2.5', 'documento': 'Factura antigua 77', 'nota': ''}
        creado = client.post('/contabilidad/api/kardex/movimientos/', datos)
        assert creado.status_code == 201 and creado.json()['movimiento']['costo_unitario'] == '2.500000'
        otra_vez = client.post('/contabilidad/api/kardex/movimientos/', datos)
        assert otra_vez.status_code == 200 and otra_vez.json()['repetido'] is True
        assert client.post('/contabilidad/api/kardex/movimientos/', {**datos, 'cantidad': '5'}).json()['codigo'] == 'clave_usada'
        errores = {
            'costo': {**datos, 'clave': 'mov-manual-0002', 'costo_unitario': ''},
            'costo_salida': {**datos, 'clave': 'mov-manual-0003', 'tipo': 'salida'},
            'fecha': {**datos, 'clave': 'mov-manual-0004', 'fecha': (HOY + timedelta(days=1)).isoformat()},
            'cantidad': {**datos, 'clave': 'mov-manual-0005', 'cantidad': '0'},
            'documento': {**datos, 'clave': 'mov-manual-0006', 'documento': '  '},
            'clave': {**datos, 'clave': 'x'},
        }
        for codigo, cuerpo in errores.items():
            respuesta = client.post('/contabilidad/api/kardex/movimientos/', cuerpo)
            assert (respuesta.status_code, respuesta.json()['codigo']) == (400, codigo), (codigo, respuesta.content)
        servicio = ayuda_compras.crear_producto(empresa, 'SRV1', inventariado=False)
        assert client.post('/contabilidad/api/kardex/movimientos/', {**datos, 'clave': 'mov-manual-0007', 'producto': servicio.pk}).status_code == 404
        pk = creado.json()['movimiento']['id']
        assert client.post(f'/contabilidad/api/kardex/movimientos/{pk}/anular/', {'motivo': ''}).json()['codigo'] == 'motivo'
        anulado = client.post(f'/contabilidad/api/kardex/movimientos/{pk}/anular/', {'motivo': 'Duplicado con la compra'})
        assert anulado.status_code == 200 and anulado.json()['movimiento']['anulado'] is True
        segunda = client.post(f'/contabilidad/api/kardex/movimientos/{pk}/anular/', {'motivo': 'Otra vez'})
        assert (segunda.status_code, segunda.json()['codigo']) == (409, 'ya_anulado')
        assert ver(empresa, producto)['movimientos'] == []   # anulado: el kardex ya no lo cuenta
        assert client.post('/contabilidad/api/kardex/movimientos/999999/anular/', {'motivo': 'x'}).status_code == 404

    def test_formulario_de_la_pagina(self, client, empresa, admin, producto):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        pagina = client.get(f'/contabilidad/kardex/?producto={producto.pk}')
        clave = pagina.context['clave_sugerida']
        respuesta = client.post('/contabilidad/kardex/', {'accion': 'registrar', 'clave': clave, 'producto': producto.pk, 'tipo': 'saldo_inicial',
                                                           'fecha': D1.isoformat(), 'cantidad': '3', 'costo_unitario': '1.25',
                                                           'documento': 'Conteo físico', 'desde': D1.isoformat(), 'hasta': HOY.isoformat()})
        assert respuesta.status_code == 302 and f'producto={producto.pk}' in respuesta['Location']
        movimiento = en(empresa, lambda: MovimientoManual.objects.get(clave=clave))
        client.post('/contabilidad/kardex/', {'accion': 'anular', 'movimiento': movimiento.pk, 'motivo': 'Conteo repetido', 'producto': producto.pk})
        assert en(empresa, lambda: MovimientoManual.objects.get(pk=movimiento.pk).anulado_en) is not None

    def test_ajuste_desde_la_importacion_de_productos(self, client, empresa, admin, producto):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.append(['id', 'nombre', 'código', 'categoría', 'precio', 'pvp', 'stock', 'inventariado', 'impuesto', 'tarifa'])
        hoja.append([producto.pk, producto.name, producto.code, 'CATEGORÍA DE COMPRAS', 5, 10, 12, 'si', 'si', '15'])
        archivo = io.BytesIO()
        libro.save(archivo)
        archivo.seek(0)
        archivo.name = 'productos.xlsx'
        respuesta = client.post('/pos/product/', {'action': 'upload_excel', 'archive': archivo})
        assert respuesta.status_code == 200 and 'error' not in respuesta.json(), respuesta.content
        ajuste = en(empresa, lambda: AjusteInventario.objects.get(producto=producto))
        assert (ajuste.anterior, ajuste.nuevo, ajuste.origen) == (0, 12, 'importacion')
        k = ver(empresa, producto)
        assert k['movimientos'][0]['tipo'] == 'ajuste_entrada' and k['saldo_final']['conocido'] is False   # entró sin costo

    @pytest.mark.parametrize('rol, estado', [(ROLE_OWNER, 200), (ROLE_ADMIN, 200), (ROLE_ACCOUNTANT, 200), (ROLE_READONLY, 200),
                                             (ROLE_SELLER, 302), (ROLE_CLIENT, 302)])
    def test_permisos_por_rol(self, client, empresa, producto, rol, estado):
        usuario = helpers.crear_usuario(f'kardex.{rol.lower()}', empresa, rol)
        helpers.iniciar_sesion(client, usuario, empresa=empresa)
        assert client.get(f'/contabilidad/kardex/?producto={producto.pk}').status_code == estado
        assert client.get('/contabilidad/inventario/').status_code == estado
        if rol == ROLE_READONLY:
            respuesta = client.post('/contabilidad/api/kardex/movimientos/', {'clave': 'consulta-0001', 'producto': producto.pk})
            assert (respuesta.status_code, respuesta.json()['codigo']) == (403, 'sin_permiso')

    def test_plan_gratuito(self, client):
        gratuita = helpers.crear_empresa('GRATIS KARDEX', plan=None)
        dueno = helpers.crear_usuario('dueno.kardex.gratis', gratuita, ROLE_OWNER)
        helpers.iniciar_sesion(client, dueno, empresa=gratuita)
        respuesta = client.get('/contabilidad/kardex/')
        assert respuesta.status_code == 302 and '/suscripcion/' in respuesta['Location']


def test_modulos_del_menu_y_roles():
    kardex = Module.objects.get(url='/contabilidad/kardex/')
    assert (kardex.name, kardex.module_type.name) == ('Kardex por producto', 'Contabilidad')
    # el icono de un grupo es único: uno repetido renombra el del otro grupo con «-x» (icono roto en el menú)
    assert kardex.module_type.icon == 'fas fa-book-open' and not ModuleType.objects.filter(icon__endswith='-x').exists()
    assert set(kardex.permissions.values_list('codename', flat=True)) == {'view_kardex', 'add_movimientomanual', 'change_movimientomanual'}

    def permisos(rol):
        return set(Group.objects.get(name=rol).permissions.filter(content_type__app_label='contabilidad').values_list('codename', flat=True))
    assert permisos(ROLE_ACCOUNTANT) == permisos(ROLE_OWNER) == {'view_kardex', 'add_movimientomanual', 'change_movimientomanual'}
    assert permisos(ROLE_READONLY) == {'view_kardex'} and permisos(ROLE_SELLER) == set() == permisos(ROLE_CLIENT)


class TestPlanYPestanas:

    def test_plan_vencido_solo_consulta(self, client, empresa, admin, producto):
        from core.suscripciones.models import SubscriptionPeriod
        SubscriptionPeriod.objects.filter(company=empresa).update(ends_at=timezone.now() - timedelta(days=1))
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        pagina = client.get(f'/contabilidad/kardex/?producto={producto.pk}')
        assert pagina.status_code == 200
        capacidades = pagina.context['capacidades']
        assert capacidades['registrar'] is False and capacidades['anular'] is False and 'venció' in capacidades['bloqueo']
        assert capacidades['bloqueo'] in pagina.content.decode() and 'name="accion" value="registrar"' not in pagina.content.decode()

    def test_busqueda_de_productos_con_pestana_de_otra_empresa(self, client, empresa, admin):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        respuesta = client.get(f'/contabilidad/api/kardex/productos/?q=K&empresa={empresa.pk + 999}')
        assert respuesta.status_code == 409 and respuesta.json()['codigo'] == 'empresa_cambiada'


def test_plan_vencido_tampoco_guarda_con_action_search(client, empresa, admin, producto):
    from core.suscripciones.models import SubscriptionPeriod
    SubscriptionPeriod.objects.filter(company=empresa).update(ends_at=timezone.now() - timedelta(days=1))
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    datos = {'action': 'search', 'clave': 'plan-vencido-001', 'producto': producto.pk, 'tipo': 'entrada', 'fecha': D1.isoformat(),
             'cantidad': '1', 'costo_unitario': '1.00', 'documento': 'Prueba'}
    r = client.post('/contabilidad/api/kardex/movimientos/', datos)
    assert r.status_code == 403 and r.json()['codigo'] == 'plan'
    assert en(empresa, lambda: MovimientoManual.objects.count()) == 0
