"""Planes y pagos: acceso por plan, límites del plan gratuito, PayPhone (simulado),
reglas de renovación sin prorrateo, cupo de comprobantes y firma electrónica."""
import json
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
import time_machine
from django.contrib.auth.models import Group
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from core.pos.forms import CompanyForm
from core.pos.models import Product, Provider, Purchase
from core.suscripciones import payphone
from core.suscripciones.cupo import PlanRequerido, emitir_con_cupo
from core.suscripciones.models import IvaRate, Payment, Plan, QuotaReservation, SubscriptionPeriod
from core.suscripciones.reglas import sumar_meses
from core.suscripciones.senales import LimitePlanGratuito
from core.suscripciones.servicios import (ReglaPlan, activar_periodo, estado_empresa, modos_de_pago, nuevo_pago,
                                          vencer_pendientes)
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog
from tests import helpers

pytestmark = pytest.mark.django_db
GYE = ZoneInfo('America/Guayaquil')


@pytest.fixture
def gratuita(db):
    return helpers.crear_empresa('GRATUITA', plan=None)


@pytest.fixture
def dueno_gratuita(gratuita):
    return helpers.crear_usuario('dueno.gratuita', gratuita, ROLE_OWNER)


@pytest.fixture
def payphone_configurado(settings):
    settings.PAYPHONE_TOKEN = 'token-de-prueba'
    settings.PAYPHONE_STORE_ID = 'store-de-prueba'
    settings.FPA_URL_APP = 'https://app.example.com'


def plan(codigo):
    return Plan.objects.get(code=codigo)


def entrar(client, user, empresa):
    helpers.iniciar_sesion(client, user, empresa=empresa)


# ---------------------------------------------------------------- precios e IVA

class TestPrecios:

    def test_desglose_de_los_planes_publicados(self):
        assert IvaRate.breakdown(5000, 15) == (4348, 652)
        assert IvaRate.breakdown(8500, 15) == (7391, 1109)

    def test_la_base_mas_el_iva_siempre_da_el_total(self):
        for total in range(1, 20000, 37):
            base, iva = IvaRate.breakdown(total, 15)
            assert base + iva == total

    def test_planes_y_tarifa_de_la_migracion(self):
        assert plan('plan-1000').price_cents == 5000 and plan('plan-1000').document_limit == 1000
        assert plan('ilimitado').price_cents == 8500 and plan('ilimitado').document_limit is None
        assert not plan('gratuito').includes_billing
        assert IvaRate.current().rate == 15

    def test_sumar_meses_ajusta_el_fin_de_mes(self):
        assert sumar_meses(datetime(2028, 2, 29, 10, tzinfo=GYE), 12) == datetime(2029, 2, 28, 10, tzinfo=GYE)
        assert sumar_meses(datetime(2026, 1, 31, tzinfo=GYE), 1) == datetime(2026, 2, 28, tzinfo=GYE)
        assert sumar_meses(datetime(2026, 11, 15, tzinfo=GYE), 12) == datetime(2027, 11, 15, tzinfo=GYE)


# ---------------------------------------------------------------- acceso por plan

class TestAcceso:

    def test_gratuita_usa_el_inventario(self, client, gratuita, dueno_gratuita):
        entrar(client, dueno_gratuita, gratuita)
        for ruta in ('/pos/product/', '/pos/category/', '/pos/provider/', '/pos/purchase/', '/pos/debts/pay/',
                     '/reports/purchase/', '/pos/company/update/', '/suscripcion/'):
            assert client.get(ruta).status_code == 200, ruta

    def test_gratuita_no_abre_facturacion_ni_ventas(self, client, gratuita, dueno_gratuita):
        entrar(client, dueno_gratuita, gratuita)
        for ruta in ('/pos/sale/admin/', '/pos/sale/admin/add/', '/pos/client/', '/pos/credit/note/admin/',
                     '/pos/receipt/', '/reports/sale/', '/reports/results/'):
            respuesta = client.get(ruta)
            assert respuesta.status_code == 302 and respuesta['Location'] == '/suscripcion/', ruta
        respuesta = client.post('/pos/sale/admin/', {'action': 'search', 'start_date': '', 'end_date': ''})
        assert respuesta.status_code == 403 and respuesta.json()['plan'] == 'requerido'

    def test_el_aviso_se_ve_en_la_pagina_de_planes(self, client, gratuita, dueno_gratuita):
        entrar(client, dueno_gratuita, gratuita)
        html = client.get('/pos/sale/admin/', follow=True).content.decode()
        assert 'fpa-alerta-plan' in html and 'se activan con un plan anual' in html
        assert 'message_error(errors)' in html and "errors += 'La facturación" not in html   # sin diálogo de error

    def test_rol_sin_gestion_del_plan_vuelve_al_panel(self, client, gratuita):
        vendedor = helpers.crear_usuario('vendedor.gratuita', gratuita, ROLE_SELLER)
        entrar(client, vendedor, gratuita)
        respuesta = client.get('/pos/sale/admin/')
        assert respuesta.status_code == 302 and respuesta['Location'] == '/dashboard/'
        assert client.get('/suscripcion/').status_code == 302   # sin el módulo «Plan y pagos»

    def test_con_plan_se_abre_todo(self, client, empresa, admin):
        entrar(client, admin, empresa)
        for ruta in ('/pos/sale/admin/', '/pos/sale/admin/add/', '/pos/client/', '/reports/sale/', '/suscripcion/'):
            assert client.get(ruta).status_code == 200, ruta

    def test_vencido_solo_consulta(self, client, gratuita, dueno_gratuita):
        hace_un_anio = timezone.now() - timedelta(days=400)
        helpers.dar_plan(gratuita, 'plan-1000', inicio=hace_un_anio)
        entrar(client, dueno_gratuita, gratuita)
        assert estado_empresa(gratuita).codigo == 'vencida'
        assert client.get('/pos/sale/admin/').status_code == 200
        assert client.post('/pos/sale/admin/', {'action': 'search', 'start_date': '', 'end_date': ''}).status_code == 200
        assert client.get('/pos/sale/admin/add/').status_code == 302
        assert client.get('/pos/client/add/').status_code == 302
        assert client.post('/pos/sale/admin/', {'action': 'generate_invoice', 'id': '1'}).status_code == 403

    def test_cupo_agotado_en_produccion_bloquea_solo_emitir(self, client, gratuita, dueno_gratuita):
        gratuita.environment_type = 2
        gratuita.save()
        helpers.dar_plan(gratuita, 'plan-1000', documents_used=1000)
        entrar(client, dueno_gratuita, gratuita)
        assert estado_empresa(gratuita).codigo == 'cupo_agotado'
        assert client.get('/pos/client/').status_code == 200
        assert client.get('/pos/sale/admin/add/').status_code == 302
        assert client.post('/pos/sale/admin/', {'action': 'create_credit_note', 'id': '1'}).status_code == 403

    def test_menu_marca_con_candado_lo_que_exige_plan(self, client, gratuita, dueno_gratuita):
        entrar(client, dueno_gratuita, gratuita)
        html = client.get('/pos/product/').content.decode()
        assert 'fpa-candado' in html and 'Plan gratuito: inventario con límites' in html

    def test_modulo_plan_solo_para_propietario_y_administrador(self):
        assert Group.objects.get(name=ROLE_OWNER).groupmodule_set.filter(module__url='/suscripcion/').exists()
        assert not Group.objects.get(name=ROLE_READONLY).groupmodule_set.filter(module__url='/suscripcion/').exists()
        assert not Group.objects.get(name=ROLE_SELLER).groupmodule_set.filter(module__url='/suscripcion/').exists()


# ---------------------------------------------------------------- límites del plan gratuito

class TestLimitesGratuitos:

    @pytest.fixture(autouse=True)
    def limites_pequenos(self):
        Plan.objects.filter(code='gratuito').update(product_limit=2, provider_limit=1, purchase_limit_month=1)

    def test_productos(self, gratuita):
        helpers.crear_producto(gratuita, 'P1')
        helpers.crear_producto(gratuita, 'P2')
        with pytest.raises(LimitePlanGratuito, match='hasta 2 productos'):
            helpers.crear_producto(gratuita, 'P3')
        with company_context(gratuita):
            producto = Product.objects.get(code='P1')
            producto.name = 'EDITAR SIGUE PERMITIDO'
            producto.save()

    def test_con_plan_no_hay_limites(self, empresa):
        for codigo in ('P1', 'P2', 'P3', 'P4'):
            helpers.crear_producto(empresa, codigo)

    def test_proveedores_y_compras(self, gratuita):
        with company_context(gratuita):
            proveedor = Provider.objects.create(name='PROV 1', ruc='0990000000001', mobile='0990000001', email='p1@example.com')
            with pytest.raises(LimitePlanGratuito, match='proveedores'):
                Provider.objects.create(name='PROV 2', ruc='0990000000002', mobile='0990000002', email='p2@example.com')
            Purchase.objects.create(number='00000001', provider=proveedor)
            with pytest.raises(LimitePlanGratuito, match='compras por mes'):
                Purchase.objects.create(number='00000002', provider=proveedor)

    def test_el_mensaje_llega_a_la_pantalla(self, client, gratuita, dueno_gratuita):
        helpers.crear_producto(gratuita, 'P1')
        helpers.crear_producto(gratuita, 'P2')
        entrar(client, dueno_gratuita, gratuita)
        with company_context(gratuita):
            categoria = Product.objects.first().category_id
        respuesta = client.post('/pos/product/add/', {'action': 'add', 'name': 'NUEVO', 'code': 'P3', 'category': categoria,
                                                      'price': '1.00', 'pvp': '2.00', 'stock': '0', 'inventoried': 'on'})
        assert 'plan gratuito permite hasta 2 productos' in respuesta.json()['error']


# ---------------------------------------------------------------- pagos con PayPhone (simulado)

def respuesta_confirm(pago, **cambios):
    datos = {'statusCode': 3, 'transactionStatus': 'Approved', 'transactionId': 777001,
             'clientTransactionId': pago.client_tx_id, 'amount': pago.amount_cents, 'currency': 'USD',
             'authorizationCode': 'W12345', 'cardBrand': 'Visa', 'lastDigits': '4242', 'email': 'titular@example.com'}
    datos.update(cambios)
    return datos


@pytest.fixture
def pago_redirigido(client, gratuita, dueno_gratuita, payphone_configurado):
    entrar(client, dueno_gratuita, gratuita)
    with mock.patch.object(payphone, 'preparar', return_value={
            'paymentId': 'pp-1', 'payWithCard': 'https://pay.payphonetodoesposible.com/PayPhone/Index?paymentId=pp-1'}) as preparar:
        respuesta = client.post('/suscripcion/pagar/', {'plan': 'plan-1000', 'modo': 'inmediato'})
    assert respuesta.status_code == 302 and respuesta['Location'].startswith('https://pay.payphonetodoesposible.com/')
    pago = Payment.objects.get(company=gratuita)
    args = preparar.call_args.args
    assert args[1] == 'https://app.example.com/suscripcion/pago/retorno/'
    assert args[2] == f'https://app.example.com/suscripcion/pago/cancelado/?ref={pago.client_tx_id}'
    return pago


class TestPagos:

    def test_preparar_usa_el_precio_del_servidor(self, pago_redirigido):
        pago = pago_redirigido
        assert (pago.amount_cents, pago.base_cents, pago.iva_cents, pago.status) == (5000, 4348, 652, 'redirigido')
        assert pago.plan.code == 'plan-1000' and pago.mode == 'inmediato'
        assert AuditLog.objects.filter(action='plan_payment_start', company=pago.company).exists()

    def test_cuerpo_de_prepare(self, settings, gratuita, payphone_configurado):
        pago = nuevo_pago(gratuita, plan('ilimitado'), None, 'inmediato')
        with mock.patch('core.suscripciones.payphone.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {'paymentId': 'x', 'payWithCard': 'https://pay/x'}
            payphone.preparar(pago, 'https://r', 'https://c', 'ref')
        cuerpo = post.call_args.kwargs['json']
        assert cuerpo['amount'] == 8500 == cuerpo['amountWithoutTax'] + cuerpo['amountWithTax'] + cuerpo['tax']
        assert (cuerpo['amountWithTax'], cuerpo['tax'], cuerpo['storeId']) == (7391, 1109, 'store-de-prueba')
        assert post.call_args.kwargs['headers']['Authorization'] == 'Bearer token-de-prueba'

    @pytest.mark.parametrize('error, estado', [
        (payphone.PayPhoneError('La tienda asociada no existe. Verifique su store id', 404, 100), 'rechazado'),
        (payphone.PayPhoneSinRespuesta('Timeout'), 'error_comunicacion'),
    ])
    def test_prepare_fallido_vuelve_con_mensaje(self, client, gratuita, dueno_gratuita, payphone_configurado, error, estado):
        entrar(client, dueno_gratuita, gratuita)
        with mock.patch.object(payphone, 'preparar', side_effect=error):
            respuesta = client.post('/suscripcion/pagar/', {'plan': 'plan-1000', 'modo': 'inmediato'}, follow=True)
        assert respuesta.status_code == 200 and 'No pudimos conectar con PayPhone' in respuesta.content.decode()
        pago = Payment.objects.get(company=gratuita)
        assert pago.status == estado
        assert pago.events.filter(kind='preparar_error', detail__tipo=type(error).__name__).exists()

    def test_sin_credenciales_no_se_cobra(self, client, gratuita, dueno_gratuita, settings):
        settings.PAYPHONE_TOKEN = ''
        entrar(client, dueno_gratuita, gratuita)
        respuesta = client.post('/suscripcion/pagar/', {'plan': 'plan-1000', 'modo': 'inmediato'})
        assert respuesta['Location'] == '/suscripcion/' and not Payment.objects.exists()

    def test_aprobado_activa_el_plan(self, client, pago_redirigido, django_capture_on_commit_callbacks):
        pago = pago_redirigido
        client.logout()   # el retorno no depende de la sesión
        with mock.patch.object(payphone, 'confirmar', return_value=respuesta_confirm(pago)) as confirmar, \
                django_capture_on_commit_callbacks(execute=True):
            respuesta = client.get('/suscripcion/pago/retorno/', {'id': '777001', 'clientTransactionId': pago.client_tx_id})
            client.get('/suscripcion/pago/retorno/', {'id': '777001', 'clientTransactionId': pago.client_tx_id})
        assert confirmar.call_count == 1   # idempotente
        assert '¡Pago aprobado!' in respuesta.content.decode()
        pago.refresh_from_db()
        assert pago.status == 'aprobado' and pago.payphone_transaction_id == '777001' and pago.last_digits == '4242'
        periodo = pago.period
        assert periodo.status == 'activa' and periodo.document_limit == 1000
        assert periodo.ends_at == sumar_meses(periodo.starts_at, 12)
        assert estado_empresa(pago.company).codigo == 'activa'
        assert any('bill@facturaporaqui.com' in m.to for m in mail.outbox)
        assert 'titular@example.com' not in json.dumps(list(pago.events.values_list('detail', flat=True)))

    def test_importe_distinto_queda_en_revision(self, client, pago_redirigido):
        pago = pago_redirigido
        with mock.patch.object(payphone, 'confirmar', return_value=respuesta_confirm(pago, amount=100)):
            client.get('/suscripcion/pago/retorno/', {'id': '777001', 'clientTransactionId': pago.client_tx_id})
        pago.refresh_from_db()
        assert pago.status == 'en_revision' and 'importe' in pago.note
        assert not SubscriptionPeriod.objects.filter(company=pago.company).exists()

    def test_transaccion_reutilizada_queda_en_revision(self, client, pago_redirigido, gratuita):
        otro = nuevo_pago(gratuita, plan('plan-1000'), None, 'inmediato')
        Payment.objects.filter(pk=otro.pk).update(status='aprobado', payphone_transaction_id='777001')
        pago = pago_redirigido
        with mock.patch.object(payphone, 'confirmar', return_value=respuesta_confirm(pago)):
            client.get('/suscripcion/pago/retorno/', {'id': '777001', 'clientTransactionId': pago.client_tx_id})
        pago.refresh_from_db()
        assert pago.status == 'en_revision' and pago.payphone_transaction_id is None

    def test_cancelado(self, client, pago_redirigido):
        pago = pago_redirigido
        with mock.patch.object(payphone, 'confirmar', return_value=respuesta_confirm(pago, statusCode=2, transactionStatus='Canceled')):
            client.get('/suscripcion/pago/retorno/', {'id': '777001', 'clientTransactionId': pago.client_tx_id})
        pago.refresh_from_db()
        assert pago.status == 'cancelado' and not SubscriptionPeriod.objects.exists()

    def test_sin_respuesta_y_reintento(self, client, pago_redirigido):
        pago = pago_redirigido
        parametros = {'id': '777001', 'clientTransactionId': pago.client_tx_id}
        with mock.patch.object(payphone, 'confirmar', side_effect=payphone.PayPhoneSinRespuesta('Timeout')):
            respuesta = client.get('/suscripcion/pago/retorno/', parametros)
        assert 'Volver a comprobar' in respuesta.content.decode()
        pago.refresh_from_db()
        assert pago.status == 'error_comunicacion'
        with mock.patch.object(payphone, 'confirmar', return_value=respuesta_confirm(pago)):
            client.get('/suscripcion/pago/retorno/', parametros)
        pago.refresh_from_db()
        assert pago.status == 'aprobado'

    def test_transaccion_ajena_no_cambia_nada(self, client, pago_redirigido):
        pago = pago_redirigido
        with mock.patch.object(payphone, 'confirmar', side_effect=payphone.PayPhoneError('No existe', 400, 20)):
            client.get('/suscripcion/pago/retorno/', {'id': '1', 'clientTransactionId': pago.client_tx_id})
        pago.refresh_from_db()
        assert pago.status == 'redirigido'

    def test_referencia_desconocida(self, client):
        with mock.patch.object(payphone, 'confirmar') as confirmar:
            respuesta = client.get('/suscripcion/pago/retorno/', {'id': '1', 'clientTransactionId': 'FPA0-inventada'})
        assert 'No encontramos ese pago' in respuesta.content.decode() and not confirmar.called

    def test_cerrar_el_formulario_cancela(self, client, pago_redirigido):
        pago = pago_redirigido
        client.get('/suscripcion/pago/cancelado/', {'ref': pago.client_tx_id})
        pago.refresh_from_db()
        assert pago.status == 'cancelado'

    def test_pendientes_expiran(self, gratuita):
        pago = nuevo_pago(gratuita, plan('plan-1000'), None, 'inmediato')
        assert vencer_pendientes(timezone.now() + timedelta(minutes=16)) == 1
        pago.refresh_from_db()
        assert pago.status == 'expirado'

    def test_solicitar_factura(self, client, empresa, admin, django_capture_on_commit_callbacks):
        pago = nuevo_pago(empresa, plan('plan-1000'), admin, 'programado')
        Payment.objects.filter(pk=pago.pk).update(status='aprobado')
        entrar(client, admin, empresa)
        with django_capture_on_commit_callbacks(execute=True):
            respuesta = client.post(f'/suscripcion/pago/{pago.uuid}/', {
                'razon_social': 'EMPRESA A S.A.', 'identificacion': '0912345675', 'direccion': 'Guayaquil',
                'correo': 'conta@example.com'})
        assert respuesta.status_code == 302
        pago.refresh_from_db()
        assert pago.invoice_requested and pago.invoice_data['correo'] == 'conta@example.com'
        assert any('Factura solicitada' in m.subject for m in mail.outbox)

    def test_detalle_de_pago_de_otra_empresa_no_se_ve(self, client, empresa, empresa_b, admin):
        pago = nuevo_pago(empresa_b, plan('plan-1000'), None, 'inmediato')
        entrar(client, admin, empresa)
        assert client.get(f'/suscripcion/pago/{pago.uuid}/').status_code == 404


# ---------------------------------------------------------------- renovación (D6)

def pagar(empresa, codigo, modo, ahora=None):
    pago = nuevo_pago(empresa, plan(codigo), None, modo)
    pago.status = 'aprobado'
    pago.save()
    with transaction.atomic():
        return activar_periodo(pago, ahora)


class TestRenovacion:

    def test_sin_plan_solo_inmediato(self, gratuita):
        assert modos_de_pago(gratuita, plan('plan-1000')) == ['inmediato']

    def test_renovacion_anticipada_al_vencer(self, gratuita):
        actual = pagar(gratuita, 'plan-1000', 'inmediato')
        assert modos_de_pago(gratuita, plan('plan-1000')) == ['programado']
        siguiente = pagar(gratuita, 'plan-1000', 'programado')
        assert siguiente.status == 'programada' and siguiente.starts_at == actual.ends_at
        with pytest.raises(ReglaPlan, match='programado'):
            modos_de_pago(gratuita, plan('ilimitado'))
        with time_machine.travel(actual.ends_at + timedelta(minutes=1)):
            estado = estado_empresa(gratuita)
            assert estado.periodo.pk == siguiente.pk and estado.periodo.status == 'activa'

    def test_mejora_ahora_o_al_vencer_y_bajada_solo_al_vencer(self, gratuita):
        actual = pagar(gratuita, 'plan-1000', 'inmediato')
        assert modos_de_pago(gratuita, plan('ilimitado')) == ['inmediato', 'programado']
        nuevo = pagar(gratuita, 'ilimitado', 'inmediato')
        actual.refresh_from_db()
        assert actual.status == 'reemplazada' and nuevo.status == 'activa' and nuevo.document_limit is None
        assert modos_de_pago(gratuita, plan('plan-1000')) == ['programado']

    def test_plan_1000_agotado_renueva_o_mejora_al_instante(self, gratuita):
        gratuita.environment_type = 2
        gratuita.save()
        actual = pagar(gratuita, 'plan-1000', 'inmediato')
        SubscriptionPeriod.objects.filter(pk=actual.pk).update(documents_used=1000)
        assert modos_de_pago(gratuita, plan('plan-1000')) == ['inmediato']
        assert modos_de_pago(gratuita, plan('ilimitado')) == ['inmediato']
        nuevo = pagar(gratuita, 'plan-1000', 'inmediato')
        assert nuevo.status == 'activa' and estado_empresa(gratuita).codigo == 'activa'

    def test_doble_pago_inmediato_se_encadena(self, gratuita):
        primero = pagar(gratuita, 'plan-1000', 'inmediato')
        segundo = pagar(gratuita, 'plan-1000', 'inmediato')   # p. ej. dos pestañas pagando a la vez
        primero.refresh_from_db()
        assert primero.status == 'activa' and segundo.status == 'programada' and segundo.starts_at == primero.ends_at
        assert segundo.payment.mode == 'programado'

    def test_sin_dias_de_gracia(self, gratuita):
        periodo = pagar(gratuita, 'plan-1000', 'inmediato')
        with time_machine.travel(periodo.ends_at + timedelta(seconds=1)):
            assert estado_empresa(gratuita).codigo == 'vencida'
            assert modos_de_pago(gratuita, plan('plan-1000')) == ['inmediato']


# ---------------------------------------------------------------- cupo (D5)

@pytest.fixture
def venta(empresa, admin):
    cliente = helpers.crear_cliente('cli.cupo', empresa, '0911111111', '0991111111')
    producto = helpers.crear_producto(empresa, 'CUPO')
    return helpers.crear_venta(empresa, cliente, admin, producto)


def autoriza(comprobante):
    def emitir():
        comprobante.status = 'authorized'
        return {'resp': True}
    return emitir


def periodo_de(empresa):
    return SubscriptionPeriod.objects.get(company=empresa, status='activa')


class TestCupo:

    @pytest.fixture(autouse=True)
    def produccion_con_plan_1000(self, empresa):
        empresa.environment_type = 2
        empresa.save()
        SubscriptionPeriod.objects.filter(company=empresa).update(document_limit=2)

    def test_autorizado_consume_una_vez(self, empresa, venta):
        with company_context(empresa):
            emitir_con_cupo(venta, autoriza(venta))
            emitir_con_cupo(venta, autoriza(venta))   # reintento del mismo comprobante
        periodo = periodo_de(empresa)
        assert (periodo.documents_used, periodo.documents_reserved) == (1, 0)
        assert QuotaReservation.objects.get(voucher_id=venta.pk).status == 'consumida'

    def test_rechazo_o_error_libera(self, empresa, venta):
        with company_context(empresa):
            emitir_con_cupo(venta, lambda: {'resp': False, 'error': 'DEVUELTA'})
            with pytest.raises(RuntimeError):
                emitir_con_cupo(venta, mock.Mock(side_effect=RuntimeError('caída del SRI')))
        periodo = periodo_de(empresa)
        assert (periodo.documents_used, periodo.documents_reserved) == (0, 0)
        assert QuotaReservation.objects.get(voucher_id=venta.pk).status == 'liberada'

    def test_sin_cupo_no_emite(self, empresa, venta):
        SubscriptionPeriod.objects.filter(company=empresa).update(documents_used=2)
        emitir = mock.Mock()
        with company_context(empresa), pytest.raises(PlanRequerido, match='Usaste los 2 documentos'):
            emitir_con_cupo(venta, emitir)
        assert not emitir.called

    def test_rollback_de_la_vista_deshace_la_reserva(self, empresa, venta):
        with company_context(empresa):
            with transaction.atomic():
                emitir_con_cupo(venta, autoriza(venta))
                transaction.set_rollback(True)
        assert periodo_de(empresa).documents_used == 0 and not QuotaReservation.objects.exists()

    def test_borrar_comprobante_devuelve_la_reserva(self, empresa, venta):
        periodo = periodo_de(empresa)
        QuotaReservation.objects.create(company=empresa, period=periodo, voucher_model='pos.sale', voucher_id=venta.pk)
        SubscriptionPeriod.objects.filter(pk=periodo.pk).update(documents_reserved=1)
        venta_id = venta.pk
        with company_context(empresa):
            venta.delete()
        assert periodo_de(empresa).documents_reserved == 0
        assert QuotaReservation.objects.get(voucher_id=venta_id).status == 'liberada'

    def test_pruebas_del_sri_no_descuenta_pero_exige_plan(self, empresa, venta, gratuita):
        empresa.environment_type = 1
        empresa.save()
        with company_context(empresa):
            emitir_con_cupo(venta, autoriza(venta))
        assert periodo_de(empresa).documents_used == 0 and not QuotaReservation.objects.exists()
        SubscriptionPeriod.objects.filter(company=empresa).update(status='anulada')
        with company_context(empresa), pytest.raises(PlanRequerido, match='activa un plan'):
            emitir_con_cupo(venta, autoriza(venta))

    def test_la_emision_real_pasa_por_el_cupo(self, empresa, venta):
        with company_context(empresa), mock.patch('core.pos.models.Sale._emitir_electronicamente',
                                                  autospec=True, side_effect=lambda self: autoriza(self)()):
            venta.generate_electronic_invoice()
        assert periodo_de(empresa).documents_used == 1


# ---------------------------------------------------------------- firma electrónica y datos de empresa

class TestFirma:

    def test_sin_plan_no_se_sube_el_p12(self, gratuita):
        archivo = SimpleUploadedFile('firma.p12', b'contenido', content_type='application/x-pkcs12')
        datos = CompanyForm(instance=gratuita).initial
        form = CompanyForm({k: v for k, v in datos.items() if v is not None}, {'electronic_signature': archivo}, instance=gratuita)
        assert not form.is_valid() and 'activa un plan' in str(form.errors['electronic_signature'])

    def test_con_plan_si(self, empresa):
        archivo = SimpleUploadedFile('firma.p12', b'contenido', content_type='application/x-pkcs12')
        datos = CompanyForm(instance=empresa).initial
        form = CompanyForm({k: v for k, v in datos.items() if v is not None}, {'electronic_signature': archivo}, instance=empresa)
        assert form.is_valid(), form.errors

    def test_datos_de_empresa_sin_firma_ni_correo(self, gratuita):
        datos = {k: v for k, v in CompanyForm(instance=gratuita).initial.items() if v is not None}
        datos.update(electronic_signature_key='', email_host_user='', email_host_password='', tradename='NUEVO NOMBRE')
        form = CompanyForm(datos, instance=gratuita)
        assert form.is_valid(), form.errors
        assert 'is_active' not in form.fields   # la empresa no se desactiva a sí misma

    def test_cargar_certificado_exige_plan(self, client, gratuita, dueno_gratuita):
        entrar(client, dueno_gratuita, gratuita)
        respuesta = client.post('/pos/company/update/', {'action': 'load_certificate', 'electronic_signature_key': 'x'})
        assert 'activa un plan' in respuesta.json()['error']


# ---------------------------------------------------------------- activación manual

class TestActivacionManual:

    def test_desde_la_plataforma(self, client, superusuario, gratuita):
        helpers.iniciar_sesion(client, superusuario)
        respuesta = client.post('/plataforma/suscripciones/payment/activar/', {
            'company': gratuita.pk, 'plan': plan('ilimitado').pk, 'mode': 'inmediato', 'note': 'Transferencia 123'})
        assert respuesta.status_code == 302
        estado = estado_empresa(gratuita)
        assert estado.codigo == 'activa' and estado.periodo.plan.code == 'ilimitado'
        pago = estado.periodo.payment
        assert pago.method == 'manual' and pago.status == 'aprobado' and pago.amount_cents == 8500
        assert AuditLog.objects.filter(action='plan_manual', company=gratuita).exists()

    def test_listados_de_la_plataforma(self, client, superusuario, empresa):
        helpers.iniciar_sesion(client, superusuario)
        for ruta in ('payment', 'subscriptionperiod', 'plan', 'ivarate', 'quotareservation'):
            assert client.get(f'/plataforma/suscripciones/{ruta}/').status_code == 200, ruta
        assert client.get('/plataforma/suscripciones/payment/activar/').status_code == 200
