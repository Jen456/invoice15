"""Cruces de «Anulado en el SRI» (Ventas, core.pos.anulados.marcar) con Compras, sin dobles. Datos ficticios; SRI falso.

(a) Una retención emitida sobre una compra a crédito y autorizada por el SRI falso abona su cuenta por pagar; al marcarla
    «Anulado en el SRI», la cuenta por pagar se recalcula y la retención deja de abonar.
(b) Una liquidación de compra autorizada completa la compra 03; al marcarla «Anulado en el SRI», la compra vuelve a
    mostrar liquidacion_pendiente.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.utils import timezone

from core.comprobantes import liquidaciones as sl
from core.comprobantes import retenciones as sv
from core.configuracion import servicios as cfg
from core.pos import anulados, compras, emision
from core.pos.models import DebtsPay, Purchase
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, AuditLog
from tests import ayuda_compras as ayuda, helpers
from tests.test_retenciones import codigos, empresa, leer, numeracion, p12, sri  # noqa: F401 (fixtures compartidos)

pytestmark = pytest.mark.django_db
HOY = timezone.localdate()
MOTIVO = 'Anulada en SRI en línea: error en la base'


@pytest.fixture
def usuario(empresa):  # noqa: F811
    return helpers.crear_usuario('dueno.cruces', empresa, ROLE_OWNER)


def marcar(empresa, usuario, slug, doc):  # noqa: F811
    with company_context(empresa):
        return anulados.marcar(empresa, usuario, slug, type(doc).objects.get(pk=doc.pk), HOY, MOTIVO)


def compra_de(empresa, compra):  # noqa: F811
    return leer(empresa, lambda: Purchase.objects.select_related('provider').get(pk=compra.pk))


class TestRetencionSobreLaCompra:

    @pytest.fixture
    def deuda(self, empresa, usuario):  # noqa: F811
        """Compra a crédito de $100 + IVA 15 % = $115 (cuenta por pagar sobre el total con IVA)."""
        proveedor = ayuda.crear_proveedor(empresa, tipo='04', correo='sin-correo-proveedor')   # sin correo: «Autorizada»
        datos = ayuda.datos_compra(proveedor, secuencial='901', autorizacion='1' * 37, payment_type='credito',
                                   end_credit=(HOY + timedelta(days=30)).isoformat())
        with company_context(empresa):
            compra = compras.crear_compra(empresa, usuario, datos, [ayuda.linea_gasto(price='100.00')])
            deuda = DebtsPay.objects.get(purchase=compra)
        assert (deuda.base_calculo, deuda.saldo) == ('total', Decimal('115.00'))
        return deuda

    def emitir(self, empresa, usuario, compra, codigos, sri):  # noqa: F811
        datos = {'cod_doc_sustento': '01', 'num_doc_sustento': '001-002-000000901', 'aut_doc_sustento': '1' * 37,
                 'fecha_doc_sustento': compra.fecha_emision, 'base_0': Decimal('0'), 'base_iva': Decimal('100.00'),
                 'tarifa_iva': '15.00', 'valor_iva': Decimal('15.00'), 'cod_sustento': '01', 'forma_pago': '20'}
        sri.respuestas_autorizacion = ['AUTORIZADO']
        with company_context(empresa):
            with transaction.atomic():
                ret = sv.crear(empresa, usuario, compra, datos, [(codigos['bienes'].pk, None, None),
                                                                 (codigos['iva30'].pk, None, None)],
                               huella_revisada=sv.SIN_REVISION)
                emision.preparar(ret)
            resultado = emision.emitir(ret)
            ret.refresh_from_db()
        assert resultado['resp'] is True and ret.status == 'authorized'
        return ret

    def test_anulada_en_el_sri_deja_de_abonar_la_cuenta_por_pagar(self, empresa, usuario, deuda, codigos, numeracion,  # noqa: F811
                                                                  sri):  # noqa: F811
        compra = compra_de(empresa, deuda.purchase)
        ret = self.emitir(empresa, usuario, compra, codigos, sri)
        retenido = Decimal(ret.total_retenido)
        assert retenido > 0 and len(sri.recepciones) == 1
        with company_context(empresa):
            cuenta = DebtsPay.objects.get(pk=deuda.pk)
            assert cuenta.saldo == Decimal('115.00') - retenido
            assert [(a['tipo'], a['id'], a['valor']) for a in cuenta.abonos()] == [('retencion', ret.pk, retenido)]

        resultado = marcar(empresa, usuario, 'retencion', ret)

        assert resultado['efectos'] == []
        with company_context(empresa):
            cuenta = DebtsPay.objects.get(pk=deuda.pk)
            assert cuenta.saldo == Decimal('115.00') and cuenta.state is True and cuenta.abonos() == []
            assert sv.retencion_vigente(compra) is None and not sv.retenciones_autorizadas(compra).exists()
            assert type(ret).objects.get(pk=ret.pk).status == 'authorized'     # el estado del SRI no cambia
        registro = AuditLog.objects.get(action='comprobante_anulado_sri')
        assert (registro.detail['modelo'], registro.detail['id']) == ('retencion', ret.pk)
        assert len(sri.recepciones) == 1                                        # no se llamó al SRI


class TestLiquidacionDeLaCompra:

    @pytest.fixture
    def compra(self, empresa, usuario):  # noqa: F811
        """Compra registrada en modo liquidación (03) a una productora con cédula: le falta la liquidación."""
        with company_context(empresa):
            cfg.configurar_otro_documento(empresa, '03', 'otro_sistema', '001-002-000000007', True)
        productora = ayuda.crear_proveedor(empresa, tipo='05', correo='sin-correo-productora')
        datos = {'provider': productora.pk, 'modo_comprobante': 'liquidacion', 'cod_sustento': '02', 'forma_pago': '01',
                 'parte_relacionada': 'no', 'pago_loc_ext': '01', 'date_joined': HOY.isoformat()}
        with company_context(empresa):
            compra = compras.crear_compra(empresa, usuario, datos, [ayuda.linea_gasto('Cacao en grano', price='100.00',
                                                                                      codigo='0')])
        assert compra.tipo_comprobante == '03' and self.faltan(empresa, compra) == ['liquidacion_pendiente']
        return compra

    @staticmethod
    def faltan(empresa, compra):  # noqa: F811
        return [c for c, _ in leer(empresa, lambda: compras.faltantes(compra_de(empresa, compra)))]

    def test_anulada_en_el_sri_vuelve_liquidacion_pendiente(self, empresa, usuario, compra, sri):  # noqa: F811
        sri.respuestas_autorizacion = ['AUTORIZADO']
        with company_context(empresa):
            with transaction.atomic():
                liq = sl.crear(empresa, usuario, compra, {'tipo_identificacion': '05', 'forma_pago': '01'}, {})
                emision.preparar(liq)
            assert emision.emitir(liq)['resp'] is True
            liq.refresh_from_db()
        assert liq.status == 'authorized'
        completa = compra_de(empresa, compra)
        assert not completa.datos_incompletos and self.faltan(empresa, compra) == []

        marcar(empresa, usuario, 'liquidacion', liq)

        anulada = compra_de(empresa, compra)
        assert anulada.datos_incompletos and anulada.tipo_comprobante == '03'
        assert self.faltan(empresa, compra) == ['liquidacion_pendiente']
        with company_context(empresa):
            assert sl.liquidacion_vigente(anulada) is None
            assert [f['codigo'] for f in anulada.toJSON(detalle=True)['faltantes']] == ['liquidacion_pendiente']
            assert type(liq).objects.get(pk=liq.pk).status == 'authorized'
