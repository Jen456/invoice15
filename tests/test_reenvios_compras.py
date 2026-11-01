"""Reenvíos inconsistentes de la revisión (DECISION-ENTREGA-COMERCIAL-2026-10-31.md, entrega 1), lado compras: una
liquidación devuelta no se reenvía si «Completar datos» ya tipificó la compra (04 u otro comprobante); una retención devuelta
cuyo sustento (liquidación 03) se anuló en el SRI no se reenvía, y la liquidación no se puede marcar anulada mientras tenga
encima una retención devuelta, en proceso o sin enviar. Nada se anula ni se cambia; SRI simulado y datos ficticios."""
from decimal import Decimal

import pytest
from django.db import transaction
from django.utils import timezone

from core.comprobantes import liquidaciones as sl
from core.comprobantes import retenciones as sr
from core.comprobantes.models import LiquidacionCompra, Retencion
from core.configuracion import servicios as cfg
from core.pos import anulados, compras, emision
from core.pos.models import Purchase
from core.tenancy.context import company_context
from tests import ayuda_compras as ayuda
from tests.test_retencion_sobre_compra import usuario  # noqa: F401
from tests.test_retenciones import codigos, empresa, leer, numeracion, p12, sri  # noqa: F401

pytestmark = pytest.mark.django_db
DEVUELTA = ('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])


@pytest.fixture
def proveedor(empresa):  # noqa: F811
    """Persona natural con cédula: la liquidación de compra se emite a quien no puede dar factura."""
    return ayuda.crear_proveedor(empresa, tipo='05', ruc=ayuda.cedula(7))


@pytest.fixture
def numeracion_03(empresa):  # noqa: F811
    with company_context(empresa):
        return cfg.configurar_otro_documento(empresa, '03', 'otro_sistema', '001-002-000000007', True)


@pytest.fixture
def sin_tipo(empresa, usuario, proveedor):  # noqa: F811
    datos = {'provider': proveedor.pk, 'modo_comprobante': 'despues', 'date_joined': timezone.localdate().isoformat(),
             'payment_type': 'efectivo'}
    with company_context(empresa):
        compra = compras.crear_compra(empresa, usuario, datos, [ayuda.linea_gasto(price='100.00')])
    assert compra.tipo_comprobante == ''
    return compra


def liquidar(empresa, usuario, compra):  # noqa: F811
    with company_context(empresa), transaction.atomic():
        compra = Purchase.objects.select_related('provider').get(pk=compra.pk)
        detalle = compra.purchasedetail_set.order_by('pk').first()
        liq = sl.crear(empresa, usuario, compra, {'tipo_identificacion': '05', 'forma_pago': '01', 'concepto': 'Servicio de prueba'},
                       {detalle.pk: ('15.00', '')})
        emision.preparar(liq)
        return liq


def retener_sobre(empresa, usuario, compra, liquidacion, codigos):  # noqa: F811
    datos = {'cod_doc_sustento': '03', 'num_doc_sustento': liquidacion.voucher_number_full, 'aut_doc_sustento': liquidacion.access_code,
             'fecha_doc_sustento': liquidacion.emission_date, 'base_0': Decimal('0'), 'base_iva': Decimal('100.00'),
             'tarifa_iva': '15.00', 'valor_iva': Decimal('15.00'), 'cod_sustento': '01', 'forma_pago': '01'}
    with company_context(empresa), transaction.atomic():
        ret = sr.crear(empresa, usuario, Purchase.objects.select_related('provider').get(pk=compra.pk), datos,
                       [(codigos['bienes'].pk, None, None)], huella_revisada=sr.SIN_REVISION)
        emision.preparar(ret)
        return ret


class TestLiquidacionDevuelta:

    def test_no_se_reenvia_si_la_compra_paso_a_04(self, empresa, usuario, proveedor, sin_tipo, numeracion_03, sri):  # noqa: F811
        sri.respuestas_recepcion = [DEVUELTA]
        liq = liquidar(empresa, usuario, sin_tipo)
        with company_context(empresa):
            assert emision.emitir(LiquidacionCompra.objects.get(pk=liq.pk))['estado'] == 'returned'
            assert sl.liquidacion_vigente(sin_tipo) is None
            # Mientras la liquidación estaba devuelta, «Completar datos» tipificó la compra como 04 (se fija el estado directamente:
            # completar_datos exige proveedor con RUC para un 04 y la liquidación se emite a quien no tiene RUC).
            Purchase.objects.filter(pk=sin_tipo.pk).update(tipo_comprobante='04')
            enviados = len(sri.recepciones)
            sri.respuestas_autorizacion = ['AUTORIZADO']
            resultado = emision.emitir(LiquidacionCompra.objects.get(pk=liq.pk))
            assert (resultado['resp'], resultado['estado']) == (False, 'returned')
            assert f'La compra #{sin_tipo.pk} ya es un comprobante 04' in resultado['error']
            assert resultado['error'].endswith('No se anuló ni se cambió nada.')
            assert LiquidacionCompra.objects.get(pk=liq.pk).status == 'returned'
            assert Purchase.objects.get(pk=sin_tipo.pk).tipo_comprobante == '04'
        assert len(sri.recepciones) == enviados

    def test_si_se_reenvia_si_la_compra_sigue_sin_tipo(self, empresa, usuario, sin_tipo, numeracion_03, sri):  # noqa: F811
        sri.respuestas_recepcion = [DEVUELTA]
        liq = liquidar(empresa, usuario, sin_tipo)
        with company_context(empresa):
            assert emision.emitir(LiquidacionCompra.objects.get(pk=liq.pk))['estado'] == 'returned'
            sri.respuestas_autorizacion = ['AUTORIZADO']
            assert emision.emitir(LiquidacionCompra.objects.get(pk=liq.pk))['resp'] is True
            assert Purchase.objects.get(pk=sin_tipo.pk).tipo_comprobante == '03'   # al autorizar, la compra sin tipo pasa a 03
        assert len(sri.recepciones) == 2


class TestRetencionSobreLiquidacionAnulada:

    @pytest.fixture
    def autorizada(self, empresa, usuario, sin_tipo, numeracion_03, sri):  # noqa: F811
        liq = liquidar(empresa, usuario, sin_tipo)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        with company_context(empresa):
            assert emision.emitir(LiquidacionCompra.objects.get(pk=liq.pk))['resp'] is True
            return LiquidacionCompra.objects.get(pk=liq.pk)

    def test_la_liquidacion_no_se_anula_con_una_retencion_devuelta_encima(self, empresa, usuario, sin_tipo, autorizada, codigos,  # noqa: F811
                                                                          numeracion, sri):  # noqa: F811
        sri.respuestas_recepcion = [DEVUELTA]
        ret = retener_sobre(empresa, usuario, sin_tipo, autorizada, codigos)
        with company_context(empresa):
            assert emision.emitir(Retencion.objects.get(pk=ret.pk))['estado'] == 'returned'
            plan = anulados.revisar(LiquidacionCompra.objects.get(pk=autorizada.pk), timezone.localdate())
            mensajes = [str(e) for e in plan['impedimentos']]
            assert mensajes == [f'Elimina antes la retención {ret.voucher_number_full} sobre esta liquidación, que el SRI no autorizó o no se envió.']
            Retencion.objects.filter(pk=ret.pk).update(status='in_process')
            plan = anulados.revisar(LiquidacionCompra.objects.get(pk=autorizada.pk), timezone.localdate())
            assert 'está en proceso en el SRI' in str(plan['impedimentos'][0])
            Retencion.objects.filter(pk=ret.pk).update(status='authorized')
            plan = anulados.revisar(LiquidacionCompra.objects.get(pk=autorizada.pk), timezone.localdate())
            assert 'Primero marca como anulada la retención' in str(plan['impedimentos'][0])

    def test_una_retencion_devuelta_no_se_reenvia_si_su_liquidacion_se_anulo(self, empresa, usuario, sin_tipo, autorizada, codigos,  # noqa: F811
                                                                             numeracion, sri):  # noqa: F811
        sri.respuestas_recepcion = [DEVUELTA]
        ret = retener_sobre(empresa, usuario, sin_tipo, autorizada, codigos)
        with company_context(empresa):
            assert emision.emitir(Retencion.objects.get(pk=ret.pk))['estado'] == 'returned'
            # Como quedó una liquidación anulada antes de esta regla (o por fuera): la retención devuelta no vuelve a salir.
            LiquidacionCompra.objects.filter(pk=autorizada.pk).update(anulado_sri_fecha=timezone.localdate())
            enviados = len(sri.recepciones)
            sri.respuestas_autorizacion = ['AUTORIZADO']
            resultado = emision.emitir(Retencion.objects.get(pk=ret.pk))
            assert resultado['resp'] is False and f'La liquidación {autorizada.voucher_number_full}' in resultado['error']
            assert 'está anulada en el SRI' in resultado['error'] and resultado['error'].endswith('No se anuló ni se cambió nada.')
            assert Retencion.objects.get(pk=ret.pk).status == 'returned'
        assert len(sri.recepciones) == enviados

    def test_control_la_retencion_devuelta_se_reenvia_con_la_liquidacion_vigente(self, empresa, usuario, sin_tipo, autorizada, codigos,  # noqa: F811
                                                                                numeracion, sri):  # noqa: F811
        sri.respuestas_recepcion = [DEVUELTA]
        ret = retener_sobre(empresa, usuario, sin_tipo, autorizada, codigos)
        with company_context(empresa):
            assert emision.emitir(Retencion.objects.get(pk=ret.pk))['estado'] == 'returned'
            sri.respuestas_autorizacion = ['AUTORIZADO']
            assert emision.emitir(Retencion.objects.get(pk=ret.pk))['resp'] is True
