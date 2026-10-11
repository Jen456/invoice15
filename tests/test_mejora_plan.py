"""Mejora Plan 1000 → ilimitado pagando la diferencia ($35 con IVA), con PayPhone simulado.

Con al menos un mes de vigencia se paga la diferencia y se conserva el
vencimiento y el consumo (no empieza otro año). Con menos de un mes el cambio
es una renovación. Ilimitado se activa solo al confirmar PayPhone y una vez.
"""
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
import time_machine
from django.core import mail
from django.utils import timezone

from core.suscripciones import payphone
from core.suscripciones.models import Payment, Plan, PlanUpgrade, SubscriptionPeriod
from core.suscripciones.reglas import sumar_meses
from core.suscripciones.servicios import confirmar_pago, cotizar_mejora, estado_empresa, modos_de_pago, nuevo_pago
from core.tenancy.models import ROLE_OWNER, ROLE_SELLER
from tests import helpers

pytestmark = pytest.mark.django_db
GYE = ZoneInfo('America/Guayaquil')
ENLACE = 'https://pay.payphonetodoesposible.com/PayPhone/Index?paymentId=pp'


@pytest.fixture(autouse=True)
def payphone_configurado(settings):
    settings.PAYPHONE_TOKEN = 'token-de-prueba'
    settings.PAYPHONE_STORE_ID = ''
    settings.FPA_URL_APP = 'https://app.example.com'


@pytest.fixture
def empresa1000(db):
    empresa = helpers.crear_empresa('MEJORA', plan=None)
    return empresa


@pytest.fixture
def dueno(empresa1000):
    return helpers.crear_usuario('dueno.mejora', empresa1000, ROLE_OWNER)


def plan(codigo):
    return Plan.objects.get(code=codigo)


def periodo_1000(empresa, restante=timedelta(days=180), usados=120, ahora=None):
    ahora = ahora or timezone.now()
    return helpers.dar_plan(empresa, 'plan-1000', inicio=ahora - timedelta(days=30), ends_at=ahora + restante,
                            documents_used=usados)


def opcion(client, codigo):
    contexto = client.get('/suscripcion/').context[0].flatten()
    return next(o for o in contexto['opciones'] if o['plan'].code == codigo)


def pedir_mejora(client, **extra):
    with mock.patch.object(payphone, 'preparar', return_value={'paymentId': 'pp', 'payWithCard': ENLACE}) as preparar:
        respuesta = client.post('/suscripcion/pagar/', {'plan': 'ilimitado', 'modo': 'inmediato', **extra})
    return respuesta, preparar


def aprobado(pago, **cambios):
    datos = {'statusCode': 3, 'transactionStatus': 'Approved', 'transactionId': 880000 + pago.pk,
             'clientTransactionId': pago.client_tx_id, 'amount': pago.amount_cents, 'currency': 'USD',
             'authorizationCode': 'W1', 'cardBrand': 'Visa', 'lastDigits': '4242'}
    datos.update(cambios)
    return datos


def retorno(client, pago, datos):
    with mock.patch.object(payphone, 'confirmar', return_value=datos) as confirmar:
        respuesta = client.get('/suscripcion/pago/retorno/', {'id': str(datos.get('transactionId', 1)),
                                                             'clientTransactionId': pago.client_tx_id})
    return respuesta, confirmar


# ---------------------------------------------------------------- cotización (contrato o.mejora)

class TestCotizacion:

    def test_con_mas_de_un_mes_se_ofrece_la_diferencia(self, client, empresa1000, dueno):
        periodo = periodo_1000(empresa1000)
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        o = opcion(client, 'ilimitado')
        assert o['mejora']['disponible'] is True
        assert o['mejora']['amount_cents'] == 3500
        assert o['mejora']['ends_at'] == periodo.ends_at
        assert opcion(client, 'plan-1000')['mejora']['disponible'] is False
        html = client.get('/suscripcion/').content.decode()
        assert 'Mejorar por $35.00' in html and 'Esta mejora no renueva tu suscripción por otro año' in html

    def test_treinta_dias_justos_si_y_29_es_renovacion(self, empresa1000):
        ahora = datetime(2026, 10, 11, 10, 0, tzinfo=GYE)
        with time_machine.travel(ahora, tick=False):
            periodo = helpers.dar_plan(empresa1000, 'plan-1000', inicio=ahora - timedelta(days=335),
                                       ends_at=ahora + timedelta(days=30))
            assert cotizar_mejora(empresa1000, plan('ilimitado'))['disponible'] is True
            assert modos_de_pago(empresa1000, plan('ilimitado')) == ['inmediato', 'programado']
            SubscriptionPeriod.objects.filter(pk=periodo.pk).update(ends_at=ahora + timedelta(days=29))
            cotizacion = cotizar_mejora(empresa1000, plan('ilimitado'))
            assert cotizacion['disponible'] is False and 'menos de 30 días' in cotizacion['motivo']
            assert modos_de_pago(empresa1000, plan('ilimitado')) == ['programado']   # renovación al vencer

    def test_treinta_dias_cuenta_por_dia_de_calendario(self, empresa1000):
        # Creado a las 10:00 para vencer en 30 días: sigue disponible a las 23:59 del mismo día.
        ahora = datetime(2026, 10, 11, 10, 0, tzinfo=GYE)
        helpers.dar_plan(empresa1000, 'plan-1000', inicio=ahora - timedelta(days=335), ends_at=ahora + timedelta(days=30))
        with time_machine.travel(datetime(2026, 10, 11, 23, 59, tzinfo=GYE), tick=False):
            assert cotizar_mejora(empresa1000, plan('ilimitado'))['disponible'] is True
            assert estado_empresa(empresa1000).dias_restantes == 30
        with time_machine.travel(datetime(2026, 10, 12, 0, 1, tzinfo=GYE), tick=False):
            assert cotizar_mejora(empresa1000, plan('ilimitado'))['disponible'] is False

    def test_pocos_dias_no_permite_pagar_la_diferencia(self, client, empresa1000, dueno):
        periodo_1000(empresa1000, restante=timedelta(days=10))
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        respuesta, preparar = pedir_mejora(client)
        assert respuesta['Location'] == '/suscripcion/' and not preparar.called
        assert not Payment.objects.filter(company=empresa1000).exists()
        html = client.get('/suscripcion/').content.decode()
        assert 'se hace como renovación' in html and 'Renovar con ilimitado por $85.00' in html and 'Mejorar por' not in html

    def test_plan_vencido_no_tiene_mejora_y_compra_normal(self, client, empresa1000, dueno):
        helpers.dar_plan(empresa1000, 'plan-1000', inicio=timezone.now() - timedelta(days=400))
        assert estado_empresa(empresa1000).codigo == 'vencida'
        assert cotizar_mejora(empresa1000, plan('ilimitado'))['disponible'] is False
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        pedir_mejora(client)
        pago = Payment.objects.get(company=empresa1000)
        assert (pago.mode, pago.amount_cents, pago.target_period) == ('inmediato', 8500, None)

    def test_el_importe_sale_de_la_regla_editable(self, empresa1000):
        periodo_1000(empresa1000)
        PlanUpgrade.objects.filter(from_plan__code='plan-1000').update(price_cents=4000)
        assert cotizar_mejora(empresa1000, plan('ilimitado'))['amount_cents'] == 4000
        PlanUpgrade.objects.update(is_active=False)
        assert cotizar_mejora(empresa1000, plan('ilimitado'))['disponible'] is False

    def test_cupo_agotado_con_pocos_dias_renueva_al_instante(self, client, empresa1000, dueno):
        empresa1000.environment_type = 2
        empresa1000.save()
        periodo_1000(empresa1000, restante=timedelta(days=10), usados=1000)
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        o = opcion(client, 'ilimitado')
        assert o['mejora']['disponible'] is False and o['mejora']['renovacion'] is True
        assert 'Renovar ahora con Plan ilimitado' in client.get('/suscripcion/').content.decode()
        pedir_mejora(client)
        assert Payment.objects.get(company=empresa1000).amount_cents == 8500   # año nuevo a precio completo (D6)


# ---------------------------------------------------------------- pago y activación

class TestPagoDeMejora:

    def test_escenario_treinta_dias_de_punta_a_punta(self, client, empresa1000, dueno):
        """Empresa ficticia cuyo plan vence en 30 días: $35 exactos, PayPhone recibe 3500 centavos,
        ilimitado solo tras confirmar, sin doble aplicación y renovación anual aparte."""
        periodo = periodo_1000(empresa1000, restante=timedelta(days=30), usados=250)
        fin = periodo.ends_at
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        html = client.get('/suscripcion/').content.decode()
        assert 'Mejorar por $35.00' in html and f'Conservas tu vencimiento' in html
        assert timezone.localtime(fin).strftime('%d/%m/%Y') in html
        renovar = f'Renovar con ilimitado por $85.00'
        assert renovar in html and 'Cambiar desde el' not in html
        assert (f'Nuevo período anual: del {timezone.localtime(fin):%d/%m/%Y} al '
                f'{timezone.localtime(sumar_meses(fin, 12)):%d/%m/%Y}') in html

        with mock.patch('core.suscripciones.payphone.requests.post') as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {'paymentId': 'pp-30', 'payWithCard': ENLACE}
            respuesta = client.post('/suscripcion/pagar/', {'plan': 'ilimitado', 'modo': 'inmediato', 'amount': '100'})
        assert respuesta['Location'] == ENLACE
        cuerpo = post.call_args.kwargs['json']
        assert (cuerpo['amount'], cuerpo['amountWithTax'], cuerpo['tax'], cuerpo['amountWithoutTax']) == (3500, 3043, 457, 0)
        pago = Payment.objects.get(company=empresa1000)
        assert (pago.mode, pago.amount_cents, pago.target_period_id) == ('mejora', 3500, periodo.pk)
        periodo.refresh_from_db()
        assert periodo.plan.code == 'plan-1000' and periodo.document_limit == 1000   # aún sin confirmar

        _, primera = retorno(client, pago, aprobado(pago))
        _, segunda = retorno(client, pago, aprobado(pago))
        periodo.refresh_from_db()
        assert primera.call_count == 1 and segunda.call_count == 0
        assert (periodo.plan.code, periodo.document_limit, periodo.ends_at, periodo.documents_used) == ('ilimitado', None, fin, 250)
        assert pago.events.filter(kind='mejora_aplicada').count() == 1
        assert SubscriptionPeriod.objects.filter(company=empresa1000).count() == 1
        # La renovación anual sigue disponible como operación aparte: empieza al vencer y dura 12 meses.
        assert modos_de_pago(empresa1000, plan('ilimitado')) == ['programado']

    def test_flujo_completo_conserva_vencimiento_y_consumo(self, client, empresa1000, dueno, django_capture_on_commit_callbacks):
        periodo = periodo_1000(empresa1000, usados=120)
        inicio, fin = periodo.starts_at, periodo.ends_at
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        respuesta, preparar = pedir_mejora(client, amount_cents='1', amount='1')   # importes del navegador: ignorados
        assert respuesta['Location'] == ENLACE
        pago = Payment.objects.get(company=empresa1000)
        assert (pago.mode, pago.amount_cents, pago.base_cents, pago.iva_cents) == ('mejora', 3500, 3043, 457)
        assert pago.target_period == periodo and pago.plan.code == 'ilimitado'
        assert preparar.call_args.args[0].amount_cents == 3500
        periodo.refresh_from_db()
        assert periodo.plan.code == 'plan-1000'   # nada cambia antes de confirmar

        client.logout()
        with django_capture_on_commit_callbacks(execute=True):
            html, _ = retorno(client, pago, aprobado(pago))
        assert 'Tu plan pasó a' in html.content.decode()
        pago.refresh_from_db()
        periodo.refresh_from_db()
        assert pago.status == 'aprobado'
        assert (periodo.plan.code, periodo.document_limit, periodo.plan_original.code) == ('ilimitado', None, 'plan-1000')
        assert (periodo.starts_at, periodo.ends_at, periodo.documents_used) == (inicio, fin, 120)
        assert periodo.upgrade_payment == pago and periodo.status == 'activa'
        assert SubscriptionPeriod.objects.filter(company=empresa1000).count() == 1   # no empieza otro año
        assert estado_empresa(empresa1000).nombre == 'Plan ilimitado'
        assert any('ilimitados hasta' in m.body for m in mail.outbox)

    @pytest.mark.parametrize('estado, esperado', [(2, 'cancelado'), (1, 'rechazado')])
    def test_pago_rechazado_no_cambia_el_plan(self, client, empresa1000, dueno, estado, esperado):
        periodo = periodo_1000(empresa1000)
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        pedir_mejora(client)
        pago = Payment.objects.get(company=empresa1000)
        retorno(client, pago, aprobado(pago, statusCode=estado, transactionStatus='Canceled'))
        pago.refresh_from_db()
        periodo.refresh_from_db()
        assert pago.status == esperado and periodo.plan.code == 'plan-1000' and periodo.upgrade_payment is None

    def test_confirmacion_duplicada_aplica_una_vez(self, client, empresa1000, dueno):
        periodo = periodo_1000(empresa1000)
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        pedir_mejora(client)
        pago = Payment.objects.get(company=empresa1000)
        _, primera = retorno(client, pago, aprobado(pago))
        _, segunda = retorno(client, pago, aprobado(pago))
        assert primera.call_count == 1 and segunda.call_count == 0
        assert pago.events.filter(kind='mejora_aplicada').count() == 1
        periodo.refresh_from_db()
        assert periodo.upgrade_payment_id == pago.pk

    def test_segundo_pago_de_mejora_no_se_confirma(self, client, empresa1000, dueno):
        periodo = periodo_1000(empresa1000)
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        pedir_mejora(client)
        respuesta, preparar = pedir_mejora(client)   # mientras el primero sigue en PayPhone
        assert not preparar.called and Payment.objects.filter(company=empresa1000).count() == 1
        primero = Payment.objects.get(company=empresa1000)
        # Dos pagos pendientes a la vez (dos pestañas antes del bloqueo): solo uno se aplica
        segundo = nuevo_pago(empresa1000, plan('ilimitado'), dueno, 'mejora', precio_cents=3500, periodo_objetivo=periodo)
        Payment.objects.filter(pk=segundo.pk).update(status='redirigido')
        retorno(client, primero, aprobado(primero))
        _, confirmar = retorno(client, segundo, aprobado(segundo))
        segundo.refresh_from_db()
        assert not confirmar.called   # sin confirmar, PayPhone reversa el cobro
        assert segundo.status == 'rechazado' and 'ya fue mejorado' in segundo.note
        assert periodo.mejoras.filter(status='aprobado').count() == 1

    def test_periodo_vencido_antes_de_confirmar(self, client, empresa1000, dueno):
        periodo = periodo_1000(empresa1000, restante=timedelta(days=40))
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        pedir_mejora(client)
        pago = Payment.objects.get(company=empresa1000)
        with time_machine.travel(periodo.ends_at + timedelta(minutes=1)):
            _, confirmar = retorno(client, pago, aprobado(pago))
        pago.refresh_from_db()
        assert not confirmar.called and pago.status == 'rechazado' and 'ya no está vigente' in pago.note

    def test_importe_distinto_en_payphone_queda_en_revision(self, client, empresa1000, dueno):
        periodo = periodo_1000(empresa1000)
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        pedir_mejora(client)
        pago = Payment.objects.get(company=empresa1000)
        retorno(client, pago, aprobado(pago, amount=8500))
        pago.refresh_from_db()
        periodo.refresh_from_db()
        assert pago.status == 'en_revision' and periodo.plan.code == 'plan-1000'

    def test_solo_quien_gestiona_el_plan_puede_pagar(self, client, empresa1000):
        periodo_1000(empresa1000)
        vendedor = helpers.crear_usuario('vendedor.mejora', empresa1000, ROLE_SELLER)
        helpers.iniciar_sesion(client, vendedor, empresa=empresa1000)
        _, preparar = pedir_mejora(client)
        assert not preparar.called and not Payment.objects.exists()

    def test_cada_empresa_mejora_solo_su_periodo(self, client, empresa1000, dueno):
        otra = helpers.crear_empresa('OTRA MEJORA', plan=None)
        ajeno = periodo_1000(otra)
        propio = periodo_1000(empresa1000)
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        pedir_mejora(client, target_period=str(ajeno.pk), periodo=str(ajeno.pk))
        assert Payment.objects.get(company=empresa1000).target_period == propio

    def test_cupo_agotado_con_mas_de_un_mes_usa_la_mejora(self, client, empresa1000, dueno):
        empresa1000.environment_type = 2
        empresa1000.save()
        periodo = periodo_1000(empresa1000, usados=1000)
        assert estado_empresa(empresa1000).codigo == 'cupo_agotado'
        helpers.iniciar_sesion(client, dueno, empresa=empresa1000)
        pedir_mejora(client)
        pago = Payment.objects.get(company=empresa1000)
        assert pago.mode == 'mejora'
        retorno(client, pago, aprobado(pago))
        periodo.refresh_from_db()
        assert estado_empresa(empresa1000).codigo == 'activa' and periodo.documents_used == 1000
