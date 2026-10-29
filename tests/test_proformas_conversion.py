"""Proformas (Etapa 1, paso 2): conversión en factura desde la pantalla de venta.

Abrir `?proforma=` precarga la venta sin guardar nada; «Emitir factura» crea la venta y vincula la proforma en la misma
transacción (bloqueo proforma → secuencia y UPDATE condicional); una segunda conversión no gasta número; eliminar la venta
(solo si no salió al SRI) libera la proforma. En PRUEBAS se factura igual que en PRODUCCIÓN y la proforma muestra que esa
factura no tiene validez tributaria (decisión de la propietaria del 28/10/2026). SRI simulado y datos ficticios."""
import json
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.db import transaction
from django.db.models import ProtectedError
from django.test import Client as ClienteWeb
from django.utils import timezone

from core.pos.choices import NOMBRE_TARIFA_IVA
from core.pos.clientes import consumidor_final
from core.pos.models import CtasCollect, PaymentsCtaCollect, Product, Receipt, Sale
from core.proformas import servicios
from core.proformas.models import Proforma
from core.security.mixins import PERMISSION_DENIED_MESSAGE
from core.suscripciones.models import QuotaReservation, SubscriptionPeriod
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_OWNER, ROLE_READONLY, AuditLog
from tests import helpers
from tests.ayudas_proformas import EJEMPLO, ayer, crear_proforma, datos_ejemplo, lineas_ejemplo, productos_por_tarifa
from tests.test_emision_sri import (VENTAS, comprador, dueno, empresa, leer, p12, producto, sri, vender,  # noqa: F401
                                    venta_de, web)

pytestmark = pytest.mark.django_db
LISTA = '/proformas/'
M = servicios.MENSAJES
A = servicios.AVISOS


@pytest.fixture
def productos(empresa):  # noqa: F811
    return productos_por_tarifa(empresa)


@pytest.fixture
def aceptada(empresa, dueno, comprador, productos):  # noqa: F811
    """Proforma del Anexo B (total 75,24) para el comprador registrado, aceptada."""
    return crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador), estado='aceptada')


@pytest.fixture
def pruebas(empresa):  # noqa: F811
    """La misma empresa, ahora en PRUEBAS, con la factura 001-002 configurada (último número 40)."""
    helpers.configurar_facturacion(empresa, estab='001', punto='002', ultimo_factura=40, ambiente=1)
    assert empresa.environment_type == 1
    return empresa


def abrir(web, proforma_id):  # noqa: F811
    return web.get(f'{VENTAS}add/?proforma={proforma_id}')


def precarga(web, p):  # noqa: F811
    r = abrir(web, p.pk)
    assert r.status_code == 200, (r.status_code, mensajes(r))
    return r.context['proforma_precarga']


def manual(productos):
    """Lo que enviaría el navegador sin pasar por la precarga (para estados que no la permiten)."""
    lineas = [{'id': productos[tarifa].pk, 'cant': cant, 'price_current': float(precio), 'dscto': float(dscto)}
              for tarifa, _, precio, cant, dscto in EJEMPLO]
    return {'lineas': lineas, 'forma_pago': '20', 'info_adicional': []}


def emitir(web, p, cliente, datos=None, **extra):  # noqa: F811
    """POST «Emitir factura» como lo arma form.js: líneas, forma de pago e información adicional de la precarga."""
    datos = datos or precarga(web, p)
    lineas = [{'id': l['id'], 'cant': l['cant'], 'price_current': l['price_current'], 'dscto': l['dscto']}
              for l in datos['lineas']]
    post = {'action': 'add', 'receipt': '01', 'client': cliente.pk, 'payment_type': 'efectivo',
            'date_joined': timezone.localdate().isoformat(), 'cash': '100', 'change': '0', 'time_limit': '0',
            'payment_method': datos['forma_pago'] or '01', 'additional_info': json.dumps(datos['info_adicional']),
            'products': json.dumps(lineas), 'proforma_id': str(p.pk)}
    post.update(extra)
    return web.post(f'{VENTAS}add/', post).json()


def a_credito():
    return {'payment_type': 'credito', 'end_credit': (timezone.localdate() + timedelta(days=30)).isoformat(),
            'cash': '0', 'change': '0'}


def mensajes(respuesta):
    return [str(m) for m in get_messages(respuesta.wsgi_request)]


def refrescar(empresa, p):  # noqa: F811
    return leer(empresa, lambda: Proforma.objects.get(pk=p.pk))


def secuencia(empresa, tipo='01'):  # noqa: F811
    return leer(empresa, lambda: Receipt.objects.get(voucher_type=tipo, environment_type=empresa.environment_type,
                                                      issuing_point_code='002').sequence)


def stock(empresa):  # noqa: F811
    return leer(empresa, lambda: dict(Product.objects.values_list('code', 'stock')))


def fila_json(web, p):  # noqa: F811
    return web.post(LISTA, {'action': 'search_detalle', 'id': p.pk}).json()['proforma']


def ventas(empresa):  # noqa: F811
    return leer(empresa, lambda: Sale.objects.count())


def sin_cambios(empresa, p, estado):  # noqa: F811
    actual = refrescar(empresa, p)
    assert (actual.estado, actual.venta_id, actual.facturada_en, actual.facturada_por_id) == (estado, None, None, None)
    assert not AuditLog.objects.filter(action='proforma_facturada').exists()


# ---------------------------------------------------------------- abrir la pantalla de venta

class TestAbrir:

    def test_facturar_abre_la_venta_precargada_sin_guardar_nada(self, web, empresa, comprador, aceptada, sri):  # noqa: F811
        antes = (stock(empresa), secuencia(empresa), QuotaReservation.objects.count(),
                 list(SubscriptionPeriod.objects.filter(company=empresa).values_list('documents_used', 'documents_reserved')))
        r = abrir(web, aceptada.pk)
        assert r.status_code == 200
        html = r.content.decode()
        p = aceptada
        assert f'name="proforma_id" value="{p.pk}"' in html and 'Emitir factura' in html and 'Generar Venta' not in html
        assert f'Facturar la proforma {p.numero_completo}' in html
        assert f'Facturando la proforma {p.numero_completo} (total USD 75.24)' in html and 'Volver a la proforma' in html
        assert 'var finalConsumer' not in html                       # no se preselecciona el consumidor final
        datos = r.context['proforma_precarga']
        incrustado = re.search(r'<script id="fp-proforma-precarga" type="application/json">(.*?)</script>', html, re.S)
        assert json.loads(incrustado.group(1)) == datos
        assert datos['proforma'] == {'id': p.pk, 'numero': p.numero_completo, 'total': '75.24',
                                     'valida_hasta': p.valida_hasta.isoformat(), 'url_ver': f'/proformas/ver/{p.pk}/'}
        assert datos['cliente']['id'] == comprador.pk and datos['cliente']['text'] and datos['prospecto'] is None
        assert [(l['code'], l['cant'], l['price_current'], l['dscto'], l['total_dscto']) for l in datos['lineas']] == [
            ('P15', 3, 10.0, 10.0, 0.0), ('P5', 2, 12.35, 0.0, 0.0), ('P0', 1, 8.0, 0.0, 0.0), ('PNO', 1, 5.5, 0.0, 0.0),
            ('PEX', 4, 1.25, 5.0, 0.0)]
        assert all(l['value'] and l['tarifa_iva'] for l in datos['lineas'])
        assert datos['forma_pago'] == '20'
        assert datos['info_adicional'] == [{'name': 'Proforma', 'value': p.numero_completo}]
        assert datos['avisos'] == [A['emitir']]
        # Nada se guardó: ni venta, ni número, ni cupo, ni stock; el SRI no se llamó y la proforma sigue igual.
        assert ventas(empresa) == 0 and secuencia(empresa) == 270
        assert antes == (stock(empresa), secuencia(empresa), QuotaReservation.objects.count(),
                         list(SubscriptionPeriod.objects.filter(company=empresa).values_list('documents_used',
                                                                                             'documents_reserved')))
        assert sri.urls == [] and sri.recepciones == []
        sin_cambios(empresa, p, 'aceptada')

    def test_precarga_avisos_stock_eliminado_tarifa_precio_descripcion(self, web, empresa, dueno, comprador, productos):  # noqa: F811
        lineas = lineas_ejemplo(productos)
        lineas[1]['descripcion'] = 'Producto 5 % con la descripción negociada'
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador, lineas=lineas), estado='aceptada')
        with company_context(empresa):
            Product.objects.filter(code='P15').update(stock=0)                  # sin stock: no se carga
            Product.objects.filter(code='P5').update(stock=1)                   # pedía 2: se carga 1
            p0 = Product.objects.get(code='P0')
            p0.tarifa_iva = '4'                                                 # 0 % → 15 %
            p0.save()
            Product.objects.filter(code='PNO').update(pvp=Decimal('6.00'))      # precio actual distinto
            Product.objects.get(code='PEX').delete()                            # eliminado
        datos = precarga(web, p)
        assert datos['avisos'] == [
            A['emitir'],
            A['sin_stock'].format(nombre='PRODUCTO P15', cant=3),
            A['stock_parcial'].format(nombre='PRODUCTO P5', stock=1, cant=2),
            A['tarifa_cambiada'].format(nombre='PRODUCTO P0', antes=NOMBRE_TARIFA_IVA['0'], ahora=NOMBRE_TARIFA_IVA['4']),
            A['precio_distinto'].format(nombre='PRODUCTO PNO', precio='5.50', actual='6.00'),
            A['producto_eliminado'].format(descripcion='PRODUCTO PEX'),
            A['descripcion'],
        ]
        assert [(l['code'], l['cant'], l['price_current']) for l in datos['lineas']] == [('P5', 1, 12.35), ('P0', 1, 8.0),
                                                                                         ('PNO', 1, 5.5)]
        assert [l['tarifa_iva'] for l in datos['lineas']] == ['5', '4', '6']   # la factura usa la tarifa actual
        with company_context(empresa):
            Product.objects.filter(code__in=['P5', 'P0', 'PNO']).update(stock=0)
        r = abrir(web, p.pk)
        assert r.status_code == 302 and r.url == f'/proformas/ver/{p.pk}/'
        assert mensajes(r) == [M['sin_lineas_facturables'].format(numero=p.numero_completo)]

    def test_precarga_prospecto_no_preselecciona_consumidor_final(self, web, empresa, dueno, productos):  # noqa: F811
        nombre = 'PROSPECTO </script><img src=x onerror=alert(1)>'
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente_nombre=nombre), estado='enviada')
        r = abrir(web, p.pk)
        html = r.content.decode()
        datos = r.context['proforma_precarga']
        assert datos['cliente'] is None and datos['prospecto'] == {
            'nombre': nombre, 'identificacion': '0990000001001', 'correo': 'compras@example.test',
            'telefono': '04 200-0000', 'direccion': 'Av. Ficticia 1'}
        assert datos['avisos'] == [A['emitir'], A['prospecto']]
        assert 'var finalConsumer' not in html
        assert '</script><img' not in html and '\\u003C/script\\u003E\\u003Cimg' in html   # json_script, sin |safe

    @pytest.mark.parametrize('caso', ['borrador', 'vencida', 'rechazada', 'anulada', 'facturada', 'otra_empresa',
                                      'no_numerico'])
    def test_precarga_rechazada(self, web, empresa, empresa_b, dueno, comprador, productos, caso):  # noqa: F811
        if caso == 'otra_empresa':
            ajena = crear_proforma(empresa_b, helpers.crear_usuario('dueno.b', empresa_b, ROLE_OWNER), estado='aceptada')
            r = abrir(web, ajena.pk)
            assert r.status_code == 302 and r.url == LISTA and mensajes(r) == [M['no_existe']]
            return
        if caso == 'no_numerico':
            r = abrir(web, '12abc')
            assert r.status_code == 302 and r.url == LISTA and mensajes(r) == [M['no_existe']]
            return
        estado = {'vencida': 'enviada'}.get(caso, caso)
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador),
                           estado=None if estado in ('borrador', 'facturada') else estado,
                           valida_hasta=ayer() if caso == 'vencida' else None)
        if caso == 'facturada':
            venta = helpers.crear_venta(empresa, comprador, dueno, productos['4'])
            with company_context(empresa):
                Proforma.objects.filter(pk=p.pk).update(estado='facturada', venta=venta)
            esperado = M['ya_facturada'].format(numero=p.numero_completo, factura=venta.voucher_number_full)
        elif caso == 'vencida':
            esperado = M['vencida'].format(numero=p.numero_completo, fecha=f'{ayer():%d/%m/%Y}', accion='facturar')
        else:
            esperado = M['no_facturable'].format(numero=p.numero_completo, estado=caso)
        r = abrir(web, p.pk)
        assert r.status_code == 302 and r.url == f'/proformas/ver/{p.pk}/'
        assert mensajes(r) == [esperado]
        assert ventas(empresa) == (1 if caso == 'facturada' else 0)

    def test_precarga_por_rol(self, empresa, aceptada):  # noqa: F811
        for rol in (ROLE_ACCOUNTANT, ROLE_READONLY):   # sin add_sale: los rechaza el permiso de la pantalla de venta
            client = ClienteWeb()
            helpers.iniciar_sesion(client, helpers.crear_usuario(f'{rol.lower()}.conversion', empresa, rol), empresa=empresa)
            r = abrir(client, aceptada.pk)
            assert r.status_code == 302 and mensajes(r) == [PERMISSION_DENIED_MESSAGE]
        client = ClienteWeb()
        grupo = helpers.crear_grupo('Vende sin proformas (prueba)', ['add_sale', 'view_sale'])
        helpers.iniciar_sesion(client, helpers.crear_usuario('vende.sin.proformas', empresa, grupo), empresa=empresa)
        r = abrir(client, aceptada.pk)
        assert r.status_code == 302 and r.url == LISTA and mensajes(r) == [M['facturar_sin_permiso']]
        assert client.get(f'{VENTAS}add/').status_code == 200   # sin ?proforma=, la venta de siempre


# ---------------------------------------------------------------- emitir

class TestEmitir:

    def test_emitir_vincula_y_marca_facturada(self, web, empresa, dueno, comprador, aceptada, sri):  # noqa: F811
        stock_antes = stock(empresa)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = emitir(web, aceptada, comprador)
        assert r.get('resp') is True, r
        venta = venta_de(empresa, 271)
        assert venta.voucher_number_full == '001-002-000000271' and venta.status == 'authorized'
        assert len(sri.recepciones) == 1 and secuencia(empresa) == 271 and venta.total == Decimal('75.24')
        assert f'<campoAdicional nombre="Proforma">{aceptada.numero_completo}</campoAdicional>' in venta.xml_signed
        p = refrescar(empresa, aceptada)
        assert (p.estado, p.venta_id, p.facturada_por_id) == ('facturada', venta.pk, dueno.pk) and p.facturada_en
        registro = AuditLog.objects.get(action='proforma_facturada')
        assert registro.detail == {'proforma': p.numero_completo, 'proforma_id': p.pk, 'venta_id': venta.pk,
                                   'factura': '001-002-000000271', 'total_proforma': '75.24', 'total_factura': '75.24',
                                   'coincide': True, 'ambiente': 2}
        assert registro.user_id == dueno.pk and registro.company_id == empresa.pk
        # El stock baja una sola vez (lo hace la venta) y el cupo lo usa la venta.
        assert stock(empresa) == {codigo: stock_antes[codigo] - cant for _, codigo, _, cant, _ in EJEMPLO}
        assert QuotaReservation.objects.filter(company=empresa).count() == 1
        assert SubscriptionPeriod.objects.get(company=empresa, status='activa').documents_used == 1
        f = fila_json(web, aceptada)
        assert f['estado']['id'] == 'facturada' and 'facturar' not in f['acciones'] and f['urls']['facturar'] is None
        assert f['venta']['numero'] == '001-002-000000271' and f['venta']['sin_validez_tributaria'] is False
        assert f['venta']['url_ride'] == f'{VENTAS}print/a4/{venta.pk}/' and f['venta']['aviso'] is None

    def test_coincide_falso_si_la_factura_cambia(self, web, empresa, comprador, aceptada, sri):  # noqa: F811
        datos = precarga(web, aceptada)
        datos['lineas'][0]['cant'] = 1                                   # se revisó antes de emitir
        assert emitir(web, aceptada, comprador, datos)['resp'] is True
        detalle = AuditLog.objects.get(action='proforma_facturada').detail
        assert (detalle['total_proforma'], detalle['coincide']) == ('75.24', False) and detalle['total_factura'] != '75.24'

    def test_segunda_conversion_rechazada_sin_consumir_numero(self, web, empresa, comprador, aceptada, sri):  # noqa: F811
        datos = precarga(web, aceptada)                                  # dos pestañas abiertas antes de emitir
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert emitir(web, aceptada, comprador, datos)['resp'] is True
        esperado = M['ya_facturada'].format(numero=aceptada.numero_completo, factura='001-002-000000271')
        assert emitir(web, aceptada, comprador, datos) == {'error': esperado}
        assert ventas(empresa) == 1 and secuencia(empresa) == 271 and len(sri.recepciones) == 1
        r = abrir(web, aceptada.pk)
        assert r.status_code == 302 and r.url == f'/proformas/ver/{aceptada.pk}/' and mensajes(r) == [esperado]

    @pytest.mark.parametrize('estado', ['borrador', 'vencida', 'rechazada', 'anulada'])
    def test_conversion_con_estado_no_permitido_no_crea_venta(self, web, empresa, dueno, comprador, productos, sri,  # noqa: F811
                                                              estado):
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador),
                           estado={'vencida': 'enviada', 'borrador': None}.get(estado, estado),
                           valida_hasta=ayer() if estado == 'vencida' else None)
        r = emitir(web, p, comprador, manual(productos))
        if estado == 'vencida':
            assert r == {'error': M['vencida'].format(numero=p.numero_completo, fecha=f'{ayer():%d/%m/%Y}', accion='facturar')}
        else:
            assert r == {'error': M['no_facturable'].format(numero=p.numero_completo, estado=estado)}
        assert ventas(empresa) == 0 and secuencia(empresa) == 270 and sri.recepciones == []
        sin_cambios(empresa, p, 'enviada' if estado == 'vencida' else estado)

    @pytest.mark.parametrize('dias, vigente', [(0, True), (1, False)], ids=['valida_hasta_hoy', 'valida_hasta_ayer'])
    def test_enviada_el_ultimo_dia_de_validez(self, web, empresa, dueno, comprador, productos, sri, dias, vigente):  # noqa: F811
        """Una enviada se factura hasta el último día de su validez, de punta a punta (abrir la venta precargada y
        emitir); al día siguiente ni se abre ni se emite."""
        valida_hasta = timezone.localdate() - timedelta(days=dias)
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador), estado='enviada',
                           valida_hasta=valida_hasta)
        vencida = M['vencida'].format(numero=p.numero_completo, fecha=f'{valida_hasta:%d/%m/%Y}', accion='facturar')
        if not vigente:
            r = abrir(web, p.pk)
            assert r.status_code == 302 and mensajes(r) == [vencida]
            assert emitir(web, p, comprador, manual(productos)) == {'error': vencida}
            assert ventas(empresa) == 0 and secuencia(empresa) == 270
            sin_cambios(empresa, p, 'enviada')
            return
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = emitir(web, p, comprador)                                     # precarga + «Emitir factura»
        assert r.get('resp') is True, r
        venta = venta_de(empresa, 271)
        actual = refrescar(empresa, p)
        assert (actual.estado, actual.venta_id) == ('facturada', venta.pk)
        assert AuditLog.objects.filter(action='proforma_facturada').count() == 1

    @pytest.mark.parametrize('fallo', ['consumidor_final', 'firma'])
    def test_fallo_dentro_de_la_transaccion_deja_la_proforma_igual(self, web, empresa, comprador, aceptada, sri, fallo):  # noqa: F811
        stock_antes = stock(empresa)
        cliente = comprador
        if fallo == 'consumidor_final':
            with company_context(empresa):
                cliente = consumidor_final(empresa)                       # 75,24 > USD 50
        else:
            empresa.electronic_signature_key = 'equivocada'               # falla preparar(), con el número ya reservado
            empresa.save()
        r = emitir(web, aceptada, cliente)
        assert ('no puede superar USD 50,00' if fallo == 'consumidor_final'
                else 'La clave no abre la firma electrónica') in r['error']
        assert ventas(empresa) == 0 and secuencia(empresa) == 270 and stock(empresa) == stock_antes
        assert sri.recepciones == [] and not leer(empresa, lambda: CtasCollect.objects.exists())
        sin_cambios(empresa, aceptada, 'aceptada')

    def test_sri_devuelve_queda_vinculada_y_al_eliminar_la_venta_se_libera(self, web, empresa, dueno, comprador,  # noqa: F811
                                                                           aceptada, sri):
        stock_antes = stock(empresa)
        sri.respuestas_recepcion = [('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])]
        assert emitir(web, aceptada, comprador)['resp'] is False
        venta = venta_de(empresa, 271)
        assert venta.status == 'returned' and refrescar(empresa, aceptada).venta_id == venta.pk
        f = fila_json(web, aceptada)
        assert f['estado']['id'] == 'facturada' and f['venta']['estado']['id'] == 'returned'
        assert f['venta']['aviso'] == servicios.AVISO_FACTURA_PENDIENTE.format(numero=venta.voucher_number_full,
                                                                              estado=venta.get_status_display())
        assert web.post(f'{VENTAS}delete/{venta.pk}/').json() == {}
        p = refrescar(empresa, aceptada)
        assert (p.estado, p.venta_id, p.facturada_en, p.facturada_por_id) == ('aceptada', None, None, None)
        assert stock(empresa) == stock_antes
        registro = AuditLog.objects.get(action='proforma_venta_eliminada')
        assert registro.detail == {'proforma': p.numero_completo, 'proforma_id': p.pk, 'venta_id': venta.pk,
                                   'factura': '001-002-000000271', 'estado': 'aceptada'}
        assert registro.user_id == dueno.pk and registro.company_id == empresa.pk
        assert 'facturar' in fila_json(web, aceptada)['acciones']
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert emitir(web, aceptada, comprador)['resp'] is True           # se factura de nuevo, con el número siguiente
        assert refrescar(empresa, aceptada).venta_id == venta_de(empresa, 272).pk

    def test_liberar_vuelve_a_enviada_si_no_fue_aceptada(self, web, empresa, dueno, comprador, productos, sri):  # noqa: F811
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador), estado='enviada')
        assert p.aceptada_en is None
        sri.respuestas_recepcion = [('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])]
        emitir(web, p, comprador)
        venta = venta_de(empresa, 271)
        assert refrescar(empresa, p).estado == 'facturada'
        assert web.post(f'{VENTAS}delete/{venta.pk}/').json() == {}
        p = refrescar(empresa, p)
        assert (p.estado, p.venta_id, p.aceptada_en) == ('enviada', None, None)
        assert AuditLog.objects.get(action='proforma_venta_eliminada').detail['estado'] == 'enviada'

    def test_venta_credito_devuelta_se_elimina_y_libera_la_proforma(self, web, empresa, comprador, aceptada, sri):  # noqa: F811
        stock_antes = stock(empresa)
        sri.respuestas_recepcion = [('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])]
        emitir(web, aceptada, comprador, **a_credito())
        venta = venta_de(empresa, 271)
        assert venta.status == 'returned' and leer(empresa, lambda: CtasCollect.objects.filter(sale=venta).count()) == 1
        assert stock(empresa) != stock_antes
        assert web.post(f'{VENTAS}delete/{venta.pk}/').json() == {}
        with company_context(empresa):
            assert not Sale.objects.filter(pk=venta.pk).exists() and not CtasCollect.objects.exists()
        assert stock(empresa) == stock_antes                              # exactamente el de antes de la venta
        p = refrescar(empresa, aceptada)
        assert (p.estado, p.venta_id) == ('aceptada', None)

    def test_eliminacion_fallida_no_libera_la_proforma(self, web, empresa, comprador, aceptada, sri):  # noqa: F811
        sri.respuestas_recepcion = [('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])]
        emitir(web, aceptada, comprador, **a_credito())
        venta = venta_de(empresa, 271)
        stock_con_venta = stock(empresa)
        with company_context(empresa):
            cuenta = CtasCollect.objects.get(sale=venta)
            PaymentsCtaCollect.objects.create(ctas_collect=cuenta, valor=Decimal('5.00'), description='Abono de prueba')
        assert 'cobros registrados' in web.post(f'{VENTAS}delete/{venta.pk}/').json()['error']
        with company_context(empresa):
            with pytest.raises(ProtectedError):                           # la cuenta por cobrar protege a la venta
                Sale.objects.get(pk=venta.pk).delete()
            assert Sale.objects.filter(pk=venta.pk).exists()
        p = refrescar(empresa, aceptada)
        assert (p.estado, p.venta_id) == ('facturada', venta.pk) and stock(empresa) == stock_con_venta
        assert not AuditLog.objects.filter(action='proforma_venta_eliminada').exists()

    def test_marcar_facturada_condicional_impide_segunda_factura(self, empresa, dueno, comprador, aceptada, productos):  # noqa: F811
        """Sin hilos (vale en SQLite): dos copias en memoria de la misma proforma, ambas todavía sin venta."""
        primera = helpers.crear_venta(empresa, comprador, dueno, productos['4'])
        segunda = helpers.crear_venta(empresa, comprador, dueno, productos['5'])
        with company_context(empresa):
            p1, p2 = Proforma.objects.get(pk=aceptada.pk), Proforma.objects.get(pk=aceptada.pk)
            servicios.marcar_facturada(p1, primera, dueno)
            assert p1.venta_id == primera.pk and p2.venta_id is None
            with pytest.raises(servicios.ErrorProforma) as error:
                with transaction.atomic():
                    servicios.marcar_facturada(p2, segunda, dueno)
            assert str(error.value) == M['ya_facturada'].format(numero=aceptada.numero_completo,
                                                                 factura=primera.voucher_number_full)
            assert error.value.estado_http == 409
            assert Proforma.objects.get(pk=aceptada.pk).venta_id == primera.pk
        assert AuditLog.objects.filter(action='proforma_facturada').count() == 1

    def test_facturar_en_pruebas_vincula_y_marca_facturada_como_en_produccion(self, web, pruebas, dueno, comprador,  # noqa: F811
                                                                             productos, sri):
        """Decisión de la propietaria (28/10/2026): en PRUEBAS la conversión es idéntica a PRODUCCIÓN. La proforma queda
        facturada con una factura sin validez tributaria, no admite otra y se duplica para volver a cotizar."""
        empresa = pruebas
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador), estado='aceptada')
        assert precarga(web, p)['avisos'][:2] == [A['emitir'], A['pruebas']]
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = emitir(web, p, comprador)
        assert r.get('resp') is True, r
        venta = leer(empresa, lambda: Sale.objects.get())
        assert (venta.environment_type, venta.voucher_number_full, venta.status) == (1, '001-002-000000041', 'authorized')
        assert all('celcer' in u for u in sri.urls)                       # el SRI de pruebas
        actual = refrescar(empresa, p)
        assert (actual.estado, actual.venta_id) == ('facturada', venta.pk)
        assert AuditLog.objects.get(action='proforma_facturada').detail['ambiente'] == 1
        esperado = M['ya_facturada'].format(numero=p.numero_completo, factura='001-002-000000041')
        assert emitir(web, p, comprador, manual(productos)) == {'error': esperado}
        assert ventas(empresa) == 1 and secuencia(empresa) == 41
        r = abrir(web, p.pk)
        assert r.status_code == 302 and mensajes(r) == [esperado]
        f = fila_json(web, p)
        assert f['venta']['ambiente'] == {'id': 1, 'nombre': 'PRUEBAS'} and f['venta']['sin_validez_tributaria'] is True
        assert f['venta']['aviso_ambiente'] == servicios.AVISO_FACTURA_PRUEBAS
        assert 'facturar' not in f['acciones'] and 'duplicar' in f['acciones']
        lista = web.post(LISTA, {'action': 'search'}).json()[0]
        assert lista['venta']['sin_validez_tributaria'] is True
        html = web.get(f'{LISTA}ver/{p.pk}/').content.decode()
        assert 'PRUEBAS · sin validez tributaria' in html and servicios.AVISO_FACTURA_PRUEBAS in html
        # Autorizada en PRUEBAS: no se puede eliminar, así que la proforma sigue facturada (para recotizar se duplica).
        assert 'no se puede eliminar' in web.post(f'{VENTAS}delete/{venta.pk}/').json()['error']
        assert refrescar(empresa, p).estado == 'facturada'

    def test_ticket_no_admitido_con_proforma(self, web, pruebas, dueno, comprador, aceptada, productos, sri):  # noqa: F811
        empresa = pruebas   # en PRUEBAS el ticket existe: el tipo se comprueba antes que todo lo demás
        r = emitir(web, aceptada, comprador, manual(productos), receipt='08')
        assert r == {'error': M['solo_factura']}
        assert ventas(empresa) == 0 and secuencia(empresa, '08') == 0
        sin_cambios(empresa, aceptada, 'aceptada')

    def test_prospecto_queda_ligado_al_cliente_de_la_factura(self, web, empresa, dueno, comprador, productos, sri):  # noqa: F811
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos), estado='aceptada')
        assert p.cliente_id is None
        assert emitir(web, p, comprador)['resp'] is not None
        actual = refrescar(empresa, p)
        assert actual.cliente_id == comprador.pk and actual.estado == 'facturada'
        assert actual.cliente_nombre == 'PROSPECTO FICTICIO S.A.' and actual.cliente_identificacion == '0990000001001'

    def test_prospecto_facturado_a_consumidor_final_sigue_como_prospecto(self, web, empresa, dueno, productos, sri):  # noqa: F811
        """Facturar a consumidor final no liga el prospecto a ese cliente: duplicar para volver a cotizar (decisiones 5
        y 11) conserva los datos del prospecto y no sale a nombre de «CONSUMIDOR FINAL»."""
        lineas = [{'product': productos['0'].pk, 'cant': 1, 'price': '8.00', 'dscto': 0, 'descripcion': ''}]   # USD 8
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, lineas=lineas), estado='aceptada')
        with company_context(empresa):
            final = consumidor_final(empresa)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = emitir(web, p, final)
        assert r.get('resp') is True, r
        venta = leer(empresa, lambda: Sale.objects.get())
        assert venta.client_id == final.pk
        actual = refrescar(empresa, p)
        assert (actual.estado, actual.venta_id, actual.cliente_id) == ('facturada', venta.pk, None)
        prospecto = {'id': None, 'nombre': 'PROSPECTO FICTICIO S.A.', 'identificacion': '0990000001001',
                     'correo': 'compras@example.test', 'telefono': '04 200-0000', 'direccion': 'Av. Ficticia 1',
                     'es_prospecto': True}
        assert fila_json(web, p)['cliente'] == prospecto
        copia = web.post(LISTA, {'action': 'duplicar', 'id': p.pk}).json()['proforma']
        assert copia['cliente'] == prospecto and copia['estado']['id'] == 'borrador'

    def test_proforma_de_otra_empresa_en_el_post(self, web, empresa, empresa_b, comprador, productos, sri):  # noqa: F811
        ajena = crear_proforma(empresa_b, helpers.crear_usuario('dueno.b', empresa_b, ROLE_OWNER), estado='aceptada')
        assert emitir(web, ajena, comprador, manual(productos)) == {'error': M['no_existe']}
        assert ventas(empresa) == 0 and secuencia(empresa) == 270 and sri.recepciones == []
        sin_cambios(empresa_b, ajena, 'aceptada')

    def test_sin_change_proforma_no_factura(self, client, empresa, comprador, aceptada, productos, sri):  # noqa: F811
        grupo = helpers.crear_grupo('Vende sin proformas (prueba)', ['add_sale', 'view_sale'])
        helpers.iniciar_sesion(client, helpers.crear_usuario('vende.sin.proformas', empresa, grupo), empresa=empresa)
        assert emitir(client, aceptada, comprador, manual(productos)) == {'error': M['facturar_sin_permiso']}
        assert ventas(empresa) == 0 and secuencia(empresa) == 270
        sin_cambios(empresa, aceptada, 'aceptada')


# ---------------------------------------------------------------- regresión y plan

class TestRegresion:

    def test_venta_sin_proforma_igual_que_antes(self, web, empresa, comprador, producto, sri):  # noqa: F811
        html = web.get(f'{VENTAS}add/').content.decode()
        assert 'Generar Venta' in html and 'fp-proforma-precarga' not in html and 'name="proforma_id"' not in html
        assert 'Facturando la proforma' not in html
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert vender(web, comprador, producto)['resp'] is True
        assert venta_de(empresa, 271).status == 'authorized'
        assert not AuditLog.objects.filter(action__startswith='proforma_').exists()
        assert web.post(f'{VENTAS}add/', {'action': 'add'}).json()['error']   # el POST incompleto sigue fallando igual

    def test_cupo_agotado_redirige_al_facturar(self, web, empresa, comprador, aceptada, productos, sri):  # noqa: F811
        SubscriptionPeriod.objects.filter(company=empresa).update(document_limit=5, documents_used=5)
        r = abrir(web, aceptada.pk)
        assert r.status_code == 302 and any('Usaste los 5 documentos' in m for m in mensajes(r))
        r = emitir(web, aceptada, comprador, manual(productos))
        assert 'Usaste los 5 documentos' in r['error'] and r['plan'] == 'requerido'
        assert ventas(empresa) == 0 and sri.recepciones == []
        sin_cambios(empresa, aceptada, 'aceptada')
