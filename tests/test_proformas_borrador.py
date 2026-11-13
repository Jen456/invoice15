"""Primera entrega · «Convertir en factura» (primera-entrega/convertir-en-factura.md).

Convertir crea (o reabre) la factura en borrador de la proforma con cliente, líneas, cantidades, precios, descuentos, notas y
forma de pago, sin firmar ni enviar nada y sin gastar número, cupo ni stock. En el borrador se revisa la tarifa de IVA de
cada línea para esa operación: va a la venta, al XML y a los totales, y el producto del catálogo no cambia. Una proforma
tiene a lo sumo un borrador y una factura; solo «Emitir factura» firma y envía (SRI simulado). Descartar el borrador deja la
proforma como estaba. El PDF de la proforma puede ocultar al vendedor sin perder quién la preparó. Datos ficticios."""
import json
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.core import mail
from django.test import Client as ClienteWeb
from django.utils import timezone

from core.pos import emision, lineas_venta
from core.pos.models import Category, Product, Receipt, Sale, SaleDetail
from core.proformas import servicios
from core.proformas.models import BorradorFactura, Proforma
from core.suscripciones.models import QuotaReservation, SubscriptionPeriod
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, ROLE_SELLER, AuditLog, Membership
from core.user.models import User
from tests import helpers
from tests.ayudas_proformas import EJEMPLO, crear_proforma, datos_ejemplo, productos_por_tarifa, web_con_rol
from tests.test_emision_sri import (VENTAS, comprador, dueno, empresa, leer, p12, sri, vender,  # noqa: F401
                                    venta_de, web)
from tests.test_proformas import texto_pdf

pytestmark = pytest.mark.django_db
LISTA = '/proformas/'
M = servicios.MENSAJES
A = servicios.AVISOS


@pytest.fixture
def productos(empresa):  # noqa: F811
    return productos_por_tarifa(empresa)


@pytest.fixture
def aceptada(empresa, dueno, comprador, productos):  # noqa: F811
    """Proforma del Anexo B (cinco tarifas, cantidades > 1 y descuentos; total 75,24), aceptada."""
    return crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador), estado='aceptada')


def convertir(web, p):  # noqa: F811
    return web.post(LISTA, {'action': 'convertir', 'id': p.pk})


def mensajes(respuesta):
    return [str(m) for m in get_messages(respuesta.wsgi_request)]


def precarga(web, url):  # noqa: F811
    r = web.get(url)
    assert r.status_code == 200, (r.status_code, mensajes(r))
    return r.context['proforma_precarga']


def borrador(empresa, p):  # noqa: F811
    return leer(empresa, lambda: BorradorFactura.objects.filter(proforma_id=p.pk).first())


def formulario(datos, cliente, tarifas=None, **extra):
    """Lo que envía form.js de la venta abierta con el borrador; `tarifas` {código de producto: tarifa} cambia el IVA de
    esas líneas (el selector «IVA» de cada línea)."""
    lineas = [{'id': l['id'], 'cant': l['cant'], 'price_current': l['price_current'], 'dscto': l['dscto'],
               'codigo_porcentaje': (tarifas or {}).get(l['code'], l['codigo_porcentaje'])} for l in datos['lineas']]
    medio = datos['medio_cobro'] or 'efectivo'
    post = {'receipt': '01', 'client': cliente.pk, 'payment_type': datos['condicion_pago'] or 'efectivo',
            'date_joined': timezone.localdate().isoformat(), 'cash': '100' if medio == 'efectivo' else '0', 'change': '0',
            'time_limit': '0', 'payment_method': datos['forma_pago'] or '01', 'medio_cobro': medio,
            'nota_cobro': '' if medio == 'efectivo' else 'Transferencia ficticia 0001',
            'additional_info': json.dumps(datos['info_adicional']), 'products': json.dumps(lineas),
            'proforma_id': str(datos['proforma']['id']), 'borrador_id': str(datos['borrador']['id'])}
    post.update(extra)
    return post


def emitir(web, datos, cliente, tarifas=None, **extra):  # noqa: F811
    return web.post(f'{VENTAS}add/', {'action': 'add', **formulario(datos, cliente, tarifas, **extra)}).json()


def guardar(web, datos, cliente, tarifas=None, **extra):  # noqa: F811
    return web.post(f'{VENTAS}add/', {'action': 'guardar_borrador', **formulario(datos, cliente, tarifas, **extra)}).json()


def refrescar(empresa, p):  # noqa: F811
    return leer(empresa, lambda: Proforma.objects.get(pk=p.pk))


def secuencia(empresa):  # noqa: F811
    return leer(empresa, lambda: Receipt.objects.get(voucher_type='01', environment_type=empresa.environment_type,
                                                      issuing_point_code='002').sequence)


def stock(empresa):  # noqa: F811
    return leer(empresa, lambda: dict(Product.objects.values_list('code', 'stock')))


def cupo(empresa):  # noqa: F811
    return (QuotaReservation.objects.filter(company=empresa).count(),
            list(SubscriptionPeriod.objects.filter(company=empresa).values_list('documents_used', 'documents_reserved')))


def ventas(empresa):  # noqa: F811
    return leer(empresa, lambda: Sale.objects.count())


def fila_json(web, p):  # noqa: F811
    return web.post(LISTA, {'action': 'search_detalle', 'id': p.pk}).json()['proforma']


def conceptos(empresa):  # noqa: F811
    """Tres servicios (no inventariados) que el catálogo tiene con IVA 15 %, como los tres conceptos de la proforma real."""
    with company_context(empresa):
        categoria, _ = Category.objects.get_or_create(name='SERVICIOS FICTICIOS')
        return [Product.objects.create(name=f'CONCEPTO FICTICIO {i}', code=f'C{i}', category=categoria, price=Decimal('1.00'),
                                       pvp=Decimal(pvp), stock=0, inventoried=False, tarifa_iva='4')
                for i, pvp in ((1, '120.00'), (2, '45.50'), (3, '18.00'))]


# ---------------------------------------------------------------- convertir: borrador sin emitir

class TestConvertir:

    def test_convertir_crea_el_borrador_sin_firmar_ni_enviar(self, web, empresa, comprador, aceptada, sri,  # noqa: F811
                                                             monkeypatch):
        llamadas = []

        def prohibida(nombre):
            def llamada(*args, **kwargs):
                llamadas.append(nombre)
                raise AssertionError(f'{nombre} no se llama al convertir')
            return llamada
        for nombre in ('preparar', 'emitir', 'firmar_xml'):
            monkeypatch.setattr(emision, nombre, prohibida(nombre))
        antes = (stock(empresa), secuencia(empresa), cupo(empresa))
        r = convertir(web, aceptada)
        assert r.status_code == 200, r.content
        b = borrador(empresa, aceptada)
        assert r.json() == {'url': f'{VENTAS}add/?borrador={b.pk}', 'creado': True, 'borrador_id': b.pk,
                            'mensaje': M['borrador_creado'].format(numero=aceptada.numero_completo)}
        html = web.get(r.json()['url']).content.decode()           # abrir el borrador tampoco emite
        assert 'Guardar borrador' in html and 'Descartar borrador' in html and 'Emitir factura' in html
        assert f'name="borrador_id" value="{b.pk}"' in html and f'name="proforma_id" value="{aceptada.pk}"' in html
        assert f'Facturando la proforma {aceptada.numero_completo} (total USD 75.24)' in html
        assert 'data-tarifa-editable="1"' in html                  # el propietario puede revisar el IVA de cada línea
        assert llamadas == [] and sri.urls == [] and sri.recepciones == []
        assert ventas(empresa) == 0 and antes == (stock(empresa), secuencia(empresa), cupo(empresa))
        p = refrescar(empresa, aceptada)
        assert (p.estado, p.venta_id, p.facturada_en) == ('aceptada', None, None)
        registro = AuditLog.objects.get(action='proforma_convertida')
        assert registro.detail == {'proforma': p.numero_completo, 'proforma_id': p.pk, 'borrador_id': b.pk, 'lineas': 5}

    def test_el_borrador_lleva_cliente_lineas_precios_descuentos_notas_y_pago(self, web, empresa, dueno, comprador,  # noqa: F811
                                                                             productos, sri):
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador, medio_pago_sugerido='transferencia',
                                                          forma_pago_sugerida='',
                                                          condiciones='Entrega en 48 horas.\nPago por transferencia.'),
                           estado='aceptada')
        assert (p.forma_pago_sugerida, p.medio_pago_sugerido) == ('20', 'transferencia')
        url = convertir(web, p).json()['url']
        b = borrador(empresa, p)
        assert b.cliente_id == comprador.pk and (b.payment_type, b.payment_method, b.medio_cobro) == ('efectivo', '20',
                                                                                                    'transferencia')
        assert b.lineas == [{'product': productos[t].pk, 'nombre': f'PRODUCTO {codigo}', 'cant': cant, 'price': precio,
                             'dscto': dscto, 'codigo_porcentaje': t} for t, codigo, precio, cant, dscto in EJEMPLO]
        assert b.info_adicional == [{'name': 'Proforma', 'value': p.numero_completo},
                                    {'name': 'Notas', 'value': 'Entrega en 48 horas. Pago por transferencia.'}]
        datos = precarga(web, url)
        assert datos['cliente']['id'] == comprador.pk and datos['prospecto'] is None
        assert [(l['code'], l['cant'], l['price_current'], l['dscto'], l['codigo_porcentaje']) for l in datos['lineas']] == [
            ('P15', 3, 10.0, 10.0, '4'), ('P5', 2, 12.35, 0.0, '5'), ('P0', 1, 8.0, 0.0, '0'), ('PNO', 1, 5.5, 0.0, '6'),
            ('PEX', 4, 1.25, 5.0, '7')]
        assert (datos['forma_pago'], datos['medio_cobro'], datos['condicion_pago']) == ('20', 'transferencia', 'efectivo')
        assert datos['info_adicional'] == b.info_adicional and datos['avisos'] == [A['borrador']]
        assert datos['borrador']['totales']['total'] == '75.24' == datos['proforma']['total']
        assert [t['codigo'] for t in datos['tarifas']] == ['4', '5', '0', '7', '6']

    def test_notas_largas_y_prospecto(self, web, empresa, dueno, productos, sri):  # noqa: F811
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, condiciones='x' * 400), estado='enviada')
        datos = precarga(web, convertir(web, p).json()['url'])
        assert datos['info_adicional'][1] == {'name': 'Notas', 'value': 'x' * 300}
        assert datos['cliente'] is None and datos['prospecto']['nombre'] == 'PROSPECTO FICTICIO S.A.'
        assert datos['avisos'] == [A['borrador'], A['notas_recortadas'], A['prospecto']]

    @pytest.mark.parametrize('caso', ['borrador', 'rechazada', 'anulada', 'otra_empresa'])
    def test_no_se_convierte_lo_que_no_se_factura(self, web, empresa, empresa_b, dueno, comprador, productos, caso):  # noqa: F811
        if caso == 'otra_empresa':
            p = crear_proforma(empresa_b, helpers.crear_usuario('dueno.b.borrador', empresa_b, ROLE_OWNER), estado='aceptada')
            r = convertir(web, p)
            assert r.status_code == 404 and r.json() == {'error': M['no_existe']}
            assert not leer(empresa_b, lambda: BorradorFactura.objects.exists())
            return
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador),
                           estado=None if caso == 'borrador' else caso)
        r = convertir(web, p)
        assert r.status_code == 409 and r.json() == {'error': M['no_facturable'].format(numero=p.numero_completo, estado=caso)}
        assert borrador(empresa, p) is None

    def test_sin_permiso_o_sin_cupo_no_convierte(self, client, web, empresa, comprador, aceptada):  # noqa: F811
        grupo = helpers.crear_grupo('Cotiza sin vender (prueba)', ['view_proforma', 'change_proforma'])
        otro = ClienteWeb()
        helpers.iniciar_sesion(otro, helpers.crear_usuario('cotiza.sin.vender', empresa, grupo), empresa=empresa)
        r = convertir(otro, aceptada)
        assert r.status_code == 403 and r.json() == {'error': M['facturar_sin_permiso']}
        SubscriptionPeriod.objects.filter(company=empresa).update(document_limit=5, documents_used=5)
        r = convertir(web, aceptada)
        assert r.status_code == 403 and 'Usaste los 5 documentos' in r.json()['error']
        assert borrador(empresa, aceptada) is None


# ---------------------------------------------------------------- IVA por línea, transferencia y totales

class TestTarifaPorLinea:

    def test_tres_conceptos_con_iva_revisado_y_transferencia_llegan_a_la_factura(self, web, empresa, dueno, comprador,  # noqa: F811
                                                                                 sri):
        """El caso real (§13): tres conceptos que esta operación factura al 0 % y pago por transferencia. Revisar la tarifa
        en el borrador recalcula los totales y solo afecta a esta factura."""
        c1, c2, c3 = conceptos(empresa)
        lineas = [{'product': c1.pk, 'cant': 2, 'price': '120.00', 'dscto': 10, 'descripcion': ''},
                  {'product': c2.pk, 'cant': 3, 'price': '45.50', 'dscto': 0, 'descripcion': ''},
                  {'product': c3.pk, 'cant': 1, 'price': '18.00', 'dscto': 5, 'descripcion': ''}]
        p = crear_proforma(empresa, dueno, datos_ejemplo(None, cliente=comprador, lineas=lineas,
                                                          medio_pago_sugerido='transferencia'), estado='aceptada')
        assert p.total == Decimal('425.05')                       # con el 15 % del catálogo
        url = convertir(web, p).json()['url']
        datos = precarga(web, url)
        assert datos['borrador']['totales']['total'] == '425.05'
        assert guardar(web, datos, comprador, tarifas={'C1': '0', 'C2': '0', 'C3': '0'}) == {
            'mensaje': M['borrador_guardado'], 'borrador': {'id': datos['borrador']['id']}}
        datos = precarga(web, url)                                # reabrir: el mismo borrador, con lo guardado
        assert [(l['code'], l['cant'], l['price_current'], l['dscto'], l['codigo_porcentaje'], l['tarifa_catalogo'])
                for l in datos['lineas']] == [('C1', 2, 120.0, 10.0, '0', '4'), ('C2', 3, 45.5, 0.0, '0', '4'),
                                              ('C3', 1, 18.0, 5.0, '0', '4')]
        totales = datos['borrador']['totales']
        assert (totales['subtotal_gravado'], totales['subtotal_cero'], totales['total_descuento'], totales['total_iva'],
                totales['total']) == ('0.00', '369.60', '24.90', '0.00', '369.60')
        assert A['tarifa_revisada'].format(nombre='CONCEPTO FICTICIO 1', elegida='0 %', catalogo='15 %') in datos['avisos']
        assert sri.recepciones == [] and ventas(empresa) == 0      # guardar no emite
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = emitir(web, datos, comprador)
        assert r.get('resp') is True, r
        venta = venta_de(empresa, 271)
        assert (venta.payment_method, venta.medio_cobro, venta.payment_type) == ('20', 'transferencia', 'efectivo')
        assert venta.total == Decimal('369.60') and venta.total_iva == Decimal('0.00')   # mostrado = guardado = enviado
        xml = venta.xml_signed
        assert '<formaPago>20</formaPago>' in xml and '<importeTotal>369.60</importeTotal>' in xml
        assert xml.count('<codigoPorcentaje>0</codigoPorcentaje>') == 4 and '<codigoPorcentaje>4</codigoPorcentaje>' not in xml
        for cantidad, precio, descuento in (('2.00', '120.00', '24.00'), ('3.00', '45.50', '0.00'), ('1.00', '18.00', '0.90')):
            assert f'<cantidad>{cantidad}</cantidad><precioUnitario>{precio}</precioUnitario><descuento>{descuento}</descuento>' in xml
        assert sri.recepciones == [xml]
        with company_context(empresa):
            assert list(SaleDetail.objects.filter(sale=venta).values_list('codigo_porcentaje', flat=True)) == ['0', '0', '0']
            assert venta.impuestos_por_tarifa()[0]['codigo'] == '0' and len(venta.impuestos_por_tarifa()) == 1
            assert set(Product.objects.filter(code__in=['C1', 'C2', 'C3']).values_list('tarifa_iva', flat=True)) == {'4'}
        detalle = AuditLog.objects.get(action='proforma_facturada').detail
        assert detalle['tarifas_revisadas'] == ['C1: 15 % → 0 %', 'C2: 15 % → 0 %', 'C3: 15 % → 0 %']
        assert detalle['coincide'] is False and detalle['total_factura'] == '369.60'
        # Solo esa operación: la venta siguiente del mismo concepto lleva el 15 % del catálogo.
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert vender(web, comprador, c1, cantidad=1, cash='200')['resp'] is True
        siguiente = venta_de(empresa, 272)
        assert '<codigoPorcentaje>4</codigoPorcentaje>' in siguiente.xml_signed and siguiente.total == Decimal('138.00')

    def test_vendedor_sin_change_product_no_cambia_la_tarifa_pero_emite_la_revisada(self, client, web, empresa,  # noqa: F811
                                                                                     comprador, aceptada, sri):
        url = convertir(web, aceptada).json()['url']
        assert guardar(web, precarga(web, url), comprador, tarifas={'P15': '0'})['mensaje'] == M['borrador_guardado']
        web_con_rol(client, empresa, ROLE_SELLER)
        r = client.get(url)
        assert r.status_code == 200 and 'data-tarifa-editable="0"' in r.content.decode()
        datos = r.context['proforma_precarga']
        r = guardar(client, datos, comprador, tarifas={'P5': '0'})
        assert r == {'error': lineas_venta.TARIFA_SIN_PERMISO.format(nombre='PRODUCTO P5', tarifa='0 %', catalogo='5 %')}
        assert emitir(client, datos, comprador, tarifas={'P5': '0'})['error'] == r['error']
        assert ventas(empresa) == 0 and secuencia(empresa) == 270
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert emitir(client, datos, comprador).get('resp') is True   # la tarifa que revisó el propietario sí
        venta = venta_de(empresa, 271)
        with company_context(empresa):
            assert SaleDetail.objects.get(sale=venta, product__code='P15').codigo_porcentaje == '0'
            assert Product.objects.get(code='P15').tarifa_iva == '4'
        assert venta.total == Decimal('71.19')                     # 75,24 − 4,05 del IVA de P15

    def test_venta_de_siempre_ignora_la_tarifa_del_navegador(self, web, empresa, comprador, productos, sri):  # noqa: F811
        sri.respuestas_autorizacion = ['AUTORIZADO']
        lineas = [{'id': productos['4'].pk, 'cant': 1, 'price_current': '10.00', 'dscto': 0, 'codigo_porcentaje': '0'}]
        assert vender(web, comprador, productos['4'], products=json.dumps(lineas))['resp'] is True
        venta = venta_de(empresa, 271)
        with company_context(empresa):
            assert SaleDetail.objects.get(sale=venta).codigo_porcentaje == '4'
        assert venta.total == Decimal('11.50')

    def test_tarifa_no_valida_se_rechaza(self, web, empresa, comprador, aceptada, sri):  # noqa: F811
        datos = precarga(web, convertir(web, aceptada).json()['url'])
        r = emitir(web, datos, comprador, tarifas={'P15': '9'})
        assert r == {'error': f'Línea 1 (PRODUCTO P15): {lineas_venta.TARIFA_INVALIDA}'}
        assert ventas(empresa) == 0 and secuencia(empresa) == 270 and sri.recepciones == []


# ---------------------------------------------------------------- una sola factura, emisión explícita

class TestUnaSolaFactura:

    def test_convertir_otra_vez_o_doble_clic_abre_el_mismo_borrador(self, web, empresa, aceptada, sri):  # noqa: F811
        primera, segunda = convertir(web, aceptada).json(), convertir(web, aceptada).json()
        assert primera['url'] == segunda['url'] and (primera['creado'], segunda['creado']) == (True, False)
        assert segunda['mensaje'] == M['borrador_abierto'].format(numero=aceptada.numero_completo)
        assert leer(empresa, lambda: BorradorFactura.objects.count()) == 1
        assert AuditLog.objects.filter(action='proforma_convertida').count() == 1
        r = web.get(f'{VENTAS}add/?proforma={aceptada.pk}')       # el enlace de siempre lleva al mismo borrador
        assert r.status_code == 302 and r.url == primera['url']

    def test_carrera_sin_bloqueo_de_filas_devuelve_el_borrador_que_gano(self, empresa, dueno, aceptada, monkeypatch):  # noqa: F811
        """Sin hilos (vale en SQLite): la otra conversión insertó su borrador después de que esta comprobara que no había.
        La restricción OneToOne rechaza el segundo INSERT y se devuelve el que ganó (en PostgreSQL además lo evita el
        bloqueo de la proforma: test_zz_proformas_borrador_concurrencia_pg)."""
        with company_context(empresa):
            ganador, _ = servicios.convertir(aceptada.pk, dueno)
            real, vistas = servicios._borrador_guardado, []

            def sin_ver_el_primero(pk):
                vistas.append(pk)
                return None if len(vistas) == 1 else real(pk)
            monkeypatch.setattr(servicios, '_borrador_guardado', sin_ver_el_primero)
            otro, creado = servicios.convertir(aceptada.pk, dueno)
            assert (otro.pk, creado) == (ganador.pk, False) and BorradorFactura.objects.count() == 1
        assert AuditLog.objects.filter(action='proforma_convertida').count() == 1

    def test_emitir_factura_es_la_accion_explicita_y_deja_ya_facturada(self, web, empresa, dueno, comprador, aceptada,  # noqa: F811
                                                                       sri):
        url = convertir(web, aceptada).json()['url']
        datos = precarga(web, url)
        assert guardar(web, datos, comprador)['mensaje'] == M['borrador_guardado']
        assert sri.recepciones == [] and ventas(empresa) == 0 and cupo(empresa)[0] == 0
        sri.respuestas_autorizacion = ['AUTORIZADO']
        r = emitir(web, datos, comprador)
        assert r.get('resp') is True, r
        venta = venta_de(empresa, 271)
        assert venta.status == 'authorized' and len(sri.recepciones) == 1 and secuencia(empresa) == 271
        assert venta.total == Decimal('75.24') == Decimal(datos['borrador']['totales']['total'])
        assert '<importeTotal>75.24</importeTotal>' in venta.xml_signed
        assert f'<campoAdicional nombre="Proforma">{aceptada.numero_completo}</campoAdicional>' in venta.xml_signed
        assert cupo(empresa) == (1, [(1, 0)])                     # el cupo lo usa la emisión, una vez
        p = refrescar(empresa, aceptada)
        assert (p.estado, p.venta_id, p.facturada_por_id) == ('facturada', venta.pk, dueno.pk)
        assert borrador(empresa, aceptada) is None                # el borrador ya es esta factura
        detalle = AuditLog.objects.get(action='proforma_facturada').detail
        assert (detalle['borrador_id'], detalle['tarifas_revisadas'], detalle['coincide']) == (datos['borrador']['id'], [],
                                                                                              True)
        # «Ya facturada», con enlace directo a su factura; repetir no crea otra.
        f = fila_json(web, aceptada)
        assert 'facturar' not in f['acciones'] and f['borrador_factura'] is None
        assert f['venta']['url_factura'] == f'{VENTAS}print/a4/{venta.pk}/'
        html = web.get(f'{LISTA}ver/{aceptada.pk}/').content.decode()
        assert 'Ya facturada' in html and f'href="{VENTAS}print/a4/{venta.pk}/"' in html
        esperado = M['ya_facturada'].format(numero=aceptada.numero_completo, factura='001-002-000000271')
        r = convertir(web, aceptada)
        assert r.status_code == 409 and r.json() == {'error': esperado}
        assert emitir(web, datos, comprador) == {'error': esperado}   # doble clic en «Emitir factura»
        assert ventas(empresa) == 1 and secuencia(empresa) == 271 and len(sri.recepciones) == 1
        r = web.get(url)
        assert r.status_code == 302 and mensajes(r) == [M['borrador_no_existe']]

    def test_fallo_al_emitir_conserva_el_borrador(self, web, empresa, aceptada, sri):  # noqa: F811
        from core.pos.clientes import consumidor_final
        datos = precarga(web, convertir(web, aceptada).json()['url'])
        with company_context(empresa):
            final = consumidor_final(empresa)
        assert 'no puede superar USD 50,00' in emitir(web, datos, final)['error']
        assert ventas(empresa) == 0 and secuencia(empresa) == 270 and sri.recepciones == []
        assert borrador(empresa, aceptada) is not None and refrescar(empresa, aceptada).estado == 'aceptada'

    def test_factura_devuelta_eliminada_libera_y_se_convierte_otra_vez(self, web, empresa, comprador, aceptada, sri):  # noqa: F811
        datos = precarga(web, convertir(web, aceptada).json()['url'])
        sri.respuestas_recepcion = [('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])]
        assert emitir(web, datos, comprador)['resp'] is False
        venta = venta_de(empresa, 271)
        assert refrescar(empresa, aceptada).venta_id == venta.pk and borrador(empresa, aceptada) is None
        f = fila_json(web, aceptada)
        assert f['venta']['url_factura'] == f'{VENTAS}print/invoice/{venta.pk}/'   # sin RIDE: el comprobante impreso
        assert web.post(f'{VENTAS}delete/{venta.pk}/').json() == {}
        assert refrescar(empresa, aceptada).estado == 'aceptada'
        nuevo = convertir(web, aceptada).json()
        assert nuevo['creado'] is True and borrador(empresa, aceptada).pk == nuevo['borrador_id']


# ---------------------------------------------------------------- descartar

class TestDescartar:

    def test_con_borrador_no_se_edita_rechaza_ni_anula_y_descartar_la_libera(self, web, empresa, dueno, comprador,  # noqa: F811
                                                                             productos, sri):
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador), estado='enviada')
        acciones_antes = fila_json(web, p)['acciones']
        convertir(web, p)
        f = fila_json(web, p)
        assert f['acciones'] == ['ver', 'pdf', 'duplicar', 'enviar_correo', 'aceptar', 'facturar', 'descartar_borrador']
        assert f['borrador_factura']['url'] == f'{VENTAS}add/?borrador={borrador(empresa, p).pk}'
        for accion in ('anular', 'rechazar'):
            r = web.post(LISTA, {'action': accion, 'id': p.pk, 'motivo': 'x'})
            assert r.status_code == 409 and r.json()['error'] == M['con_borrador'].format(
                numero=p.numero_completo, accion=servicios.VERBOS[accion])
        r = web.post(f'{LISTA}update/{p.pk}/', {**datos_ejemplo(productos, cliente=comprador), 'action': 'edit'})
        assert r.status_code == 409 and r.json()['error'] == M['con_borrador'].format(numero=p.numero_completo,
                                                                                       accion='editar')
        r = web.get(f'{LISTA}update/{p.pk}/')
        assert r.status_code == 302 and r.url == f'{LISTA}ver/{p.pk}/'
        assert 'Factura en borrador sin emitir' in web.get(f'{LISTA}ver/{p.pk}/').content.decode()
        r = web.post(LISTA, {'action': 'descartar_borrador', 'id': p.pk})
        assert r.status_code == 200 and r.json()['mensaje'] == M['borrador_descartado'].format(numero=p.numero_completo,
                                                                                              estado='enviada')
        assert borrador(empresa, p) is None and refrescar(empresa, p).estado == 'enviada'
        assert fila_json(web, p)['acciones'] == acciones_antes
        registro = AuditLog.objects.get(action='proforma_borrador_descartado')
        assert registro.detail['proforma_id'] == p.pk and registro.user_id == dueno.pk
        r = web.post(LISTA, {'action': 'descartar_borrador', 'id': p.pk})
        assert r.status_code == 409 and r.json()['error'] == M['sin_borrador'].format(numero=p.numero_completo)
        assert convertir(web, p).json()['creado'] is True          # se puede convertir otra vez
        assert ventas(empresa) == 0 and sri.urls == []

    def test_descartar_desde_la_venta(self, web, empresa, aceptada, sri):  # noqa: F811
        datos = precarga(web, convertir(web, aceptada).json()['url'])
        r = web.post(f'{VENTAS}add/', {'action': 'descartar_borrador', 'borrador_id': datos['borrador']['id']}).json()
        assert r == {'mensaje': M['borrador_descartado'].format(numero=aceptada.numero_completo, estado='aceptada'),
                     'url': f'{LISTA}ver/{aceptada.pk}/'}
        assert borrador(empresa, aceptada) is None
        r = web.post(f'{VENTAS}add/', {'action': 'guardar_borrador', 'borrador_id': datos['borrador']['id']}).json()
        assert r == {'error': M['borrador_no_existe']}


# ---------------------------------------------------------------- medio de pago y vendedor en el PDF

class TestPdfYPago:

    def test_transferencia_bancaria_en_la_proforma_y_20_para_el_sri(self, web, empresa, dueno, comprador, productos):  # noqa: F811
        p = crear_proforma(empresa, dueno, datos_ejemplo(productos, cliente=comprador, medio_pago_sugerido='transferencia',
                                                          forma_pago_sugerida='01'))   # el medio manda: 20
        assert (p.medio_pago_sugerido, p.forma_pago_sugerida) == ('transferencia', '20')
        texto = texto_pdf(web.get(f'{LISTA}pdf/{p.pk}/').content)
        assert 'Transferencia bancaria' in texto and 'OTROS CON UTILIZACION' not in texto
        d = fila_json(web, p)
        assert d['medio_pago_sugerido'] == {'id': 'transferencia', 'nombre': 'Transferencia bancaria'}
        assert d['forma_pago'] == 'Transferencia bancaria' and d['forma_pago_sugerida']['id'] == '20'
        r = web.post(f'{LISTA}add/', {**datos_ejemplo(productos, medio_pago_sugerido='bitcoin'), 'action': 'add'})
        assert r.status_code == 400 and r.json()['campos'] == {'medio_pago_sugerido': servicios.CAMPOS['medio_pago_sugerido']}

    def test_ocultar_vendedor_con_una_cuenta_de_dos_empresas(self, client):
        """PRO-000001: la emisora era una empresa, pero el PDF decía «Vendedor: <la otra empresa>» porque la cuenta que la
        preparó, con acceso a dos empresas, se llama como la otra. Con «Ocultar el vendedor en el PDF», la vista previa, el
        PDF y su copia por correo muestran solo la identidad de la emisora; quién la preparó queda registrado."""
        otra = helpers.crear_empresa('PEDESTAL FICTICIA')
        emisora = helpers.crear_empresa('SUPROHOSTING FICTICIA')
        cuenta = helpers.crear_usuario('cuenta.dos.empresas', otra, ROLE_OWNER)
        Membership.objects.create(user=cuenta, company=emisora, group=Group.objects.get(name=ROLE_OWNER), is_active=True)
        User.objects.filter(pk=cuenta.pk).update(names='PEDESTAL FICTICIA S.A.')
        helpers.iniciar_sesion(client, cuenta, empresa=emisora)
        productos = productos_por_tarifa(emisora)
        r = client.post(f'{LISTA}add/', {**datos_ejemplo(productos), 'action': 'add', 'ocultar_vendedor': 'on'})
        assert r.status_code == 200, r.content
        creada = r.json()['proforma']
        p = leer(emisora, lambda: Proforma.objects.get(pk=creada['id']))
        assert (p.company_id, p.ocultar_vendedor, p.vendedor_id, p.creada_por_id) == (emisora.pk, True, cuenta.pk, cuenta.pk)

        def identidad_de_la_emisora(texto):
            assert 'SUPROHOSTING FICTICIA S.A.' in texto and emisora.ruc in texto
            assert 'PEDESTAL' not in texto and 'Vendedor' not in texto and otra.ruc not in texto
        r = client.get(f'{LISTA}pdf/{p.pk}/')
        assert r.status_code == 200 and r['Content-Disposition'] == f'inline; filename="{p.numero_completo}.pdf"'
        identidad_de_la_emisora(texto_pdf(r.content))
        assert client.post(LISTA, {'action': 'enviar_correo', 'id': p.pk}).status_code == 200
        nombre, adjunto, _ = mail.outbox[-1].attachments[0]
        assert nombre == f'{p.numero_completo}.pdf'
        identidad_de_la_emisora(texto_pdf(adjunto))
        html = client.get(f'{LISTA}ver/{p.pk}/').content.decode()   # la ficha (vista previa) conserva el registro interno
        assert 'SUPROHOSTING FICTICIA S.A. · RUC ' + emisora.ruc in html and 'oculto en el PDF' in html
        d = client.post(LISTA, {'action': 'search_detalle', 'id': p.pk}).json()['proforma']
        assert d['vendedor'] == {'id': cuenta.pk, 'nombre': 'PEDESTAL FICTICIA S.A.'}
        assert d['creada_por'] == 'PEDESTAL FICTICIA S.A.' and d['ocultar_vendedor'] is True
        # Duplicar conserva la opción; sin ella, el PDF muestra al vendedor como hasta ahora.
        copia = client.post(LISTA, {'action': 'duplicar', 'id': p.pk}).json()['proforma']
        assert copia['ocultar_vendedor'] is True
        r = client.post(f'{LISTA}update/{copia["id"]}/', {**datos_ejemplo(productos), 'action': 'edit'})
        assert r.status_code == 200 and r.json()['proforma']['ocultar_vendedor'] is False
        texto = texto_pdf(client.get(f'{LISTA}pdf/{copia["id"]}/').content)
        assert 'Vendedor' in texto and 'PEDESTAL FICTICIA S.A.' in texto and 'SUPROHOSTING FICTICIA S.A.' in texto
