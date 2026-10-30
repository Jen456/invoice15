"""Excedentes de notas de crédito y retenciones recibidas en la cuenta por cobrar (Etapa 2, O2; revisión O2-F1).

Una NC o una retención que encontró poco saldo abona solo hasta el saldo ('parcial' / 'sin_saldo'). Si el saldo vuelve a
subir (se elimina un cobro, se anula otra NC en el SRI o se anula otra retención), cxc.aplicar_excedentes abona lo que
faltaba, en orden de fecha, y la CxC cuadra en cualquier orden. Cada documento conserva un solo abono vigente: el anterior
queda anulado («sustituido»), no se borra."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.utils import timezone

from core.comprobantes import retenciones_recibidas as rr
from core.comprobantes.models import RetencionRecibida
from core.pos import anulados, cxc
from core.pos.models import CreditNote, CtasCollect, PaymentsCtaCollect, Sale, SaleDetail
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog
from tests.ayudas_ventas import (cxc_de, factura_autorizada, nota_credito_autorizada, nota_debito_autorizada, peticion,
                                 retencion_datos)
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, producto, sri  # noqa: F401

pytestmark = pytest.mark.django_db
HOY = timezone.localdate()
MOTIVO = 'Anulada en SRI en línea: error en el valor'


@pytest.fixture
def venta(empresa, comprador, dueno, producto):  # noqa: F811
    """Factura a crédito de ayer: 2 × 10 + IVA 15 % = 23,00, con su CxC."""
    return factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=HOY - timedelta(days=1))


def saldo(empresa, venta):
    return leer(empresa, lambda: cxc.saldo(CtasCollect.objects.get(pk=cxc_de(venta).pk)))


def cobrar(empresa, usuario, venta, valor):
    with company_context(empresa):
        return cxc.registrar_cobro(empresa, usuario, cxc_de(venta).pk, HOY, valor, 'efectivo')


def eliminar(empresa, usuario, cobro):
    with company_context(empresa):
        cxc.eliminar_cobro(peticion(usuario, empresa), cobro.pk)


def una_unidad(empresa, venta):
    """Líneas de una NC de 1 unidad: 11,50."""
    return [(leer(empresa, lambda: SaleDetail.objects.get(sale=venta).pk), 1)]


def retener(empresa, usuario, venta, **cambios):
    """Retención manual de 1,30 (renta 0,40 + IVA 0,90)."""
    with company_context(empresa), transaction.atomic():
        return rr.registrar(empresa, usuario, Sale.objects.get(pk=venta.pk), retencion_datos(**cambios))


def nota(empresa, pk):
    return leer(empresa, lambda: CreditNote.objects.select_related('abono_cxc').get(pk=pk))


def retencion(empresa, pk):
    return leer(empresa, lambda: RetencionRecibida.objects.select_related('abono').get(pk=pk))


def historia(empresa, tipo):
    """[(valor, vigente)] de los abonos de ese tipo, en orden."""
    return leer(empresa, lambda: [(a.valor, a.anulado_en is None)
                                  for a in PaymentsCtaCollect.objects.filter(tipo=tipo).order_by('id')])


class TestSaldoQueVuelveASubir:

    def test_eliminar_el_cobro_abona_la_nc_parcial_y_la_retencion_sin_saldo(self, empresa, dueno, venta, sri):  # noqa: F811
        """Cobro 20 → NC 11,50 'parcial' (3,00) → retención 1,30 'sin_saldo' → se elimina el cobro: 23 − 11,50 − 1,30."""
        cobro = cobrar(empresa, dueno, venta, '20.00')
        nc = nota_credito_autorizada(venta, una_unidad(empresa, venta), sri=sri)
        ret = retener(empresa, dueno, venta)
        assert (nc.cxc_ajuste, ret.cxc_estado, saldo(empresa, venta)) == ('parcial', 'sin_saldo', Decimal('0.00'))
        eliminar(empresa, dueno, cobro)
        assert saldo(empresa, venta) == Decimal('10.20')
        nc, ret = nota(empresa, nc.pk), retencion(empresa, ret.pk)
        assert (nc.cxc_ajuste, nc.abono_cxc.valor, nc.excedente_cxc()) == ('aplicada', Decimal('11.50'), Decimal('0.00'))
        assert (ret.cxc_estado, ret.abono.valor, ret.abono.referencia) == ('aplicada', Decimal('1.30'), ret.numero)
        # El abono anterior de la NC no se borra: queda anulado y sustituido por el nuevo.
        assert historia(empresa, 'nota_credito') == [(Decimal('3.00'), False), (Decimal('11.50'), True)]
        anterior = leer(empresa, lambda: PaymentsCtaCollect.objects.filter(tipo='nota_credito').order_by('id').first())
        assert anterior.anulado_motivo == 'Sustituido por un abono de 11.50: se liberó saldo en la cuenta por cobrar.'
        registro = AuditLog.objects.get(action='cxc_cobro_eliminado')
        assert registro.detail['excedentes_aplicados'] == [
            {'tipo': 'nota_credito', 'numero': nc.voucher_number_full, 'valor': '8.50'},
            {'tipo': 'retencion', 'numero': ret.numero, 'valor': '1.30'}]

    def test_el_saldo_liberado_se_reparte_por_partes(self, empresa, dueno, venta, sri):  # noqa: F811
        """Cobros 20 + 2 → NC 'parcial' (1,00) y retención 'sin_saldo'. Eliminar el de 2 alcanza solo para la NC."""
        grande, chico = cobrar(empresa, dueno, venta, '20.00'), cobrar(empresa, dueno, venta, '2.00')
        nc = nota_credito_autorizada(venta, una_unidad(empresa, venta), sri=sri)
        ret = retener(empresa, dueno, venta)
        eliminar(empresa, dueno, chico)
        nc, ret = nota(empresa, nc.pk), retencion(empresa, ret.pk)
        assert (nc.cxc_ajuste, nc.abono_cxc.valor, nc.excedente_cxc()) == ('parcial', Decimal('3.00'), Decimal('8.50'))
        assert (ret.cxc_estado, ret.abono_id, saldo(empresa, venta)) == ('sin_saldo', None, Decimal('0.00'))
        eliminar(empresa, dueno, grande)
        assert saldo(empresa, venta) == Decimal('10.20')
        assert historia(empresa, 'nota_credito') == [(Decimal('1.00'), False), (Decimal('3.00'), False),
                                                     (Decimal('11.50'), True)]
        assert retencion(empresa, ret.pk).cxc_estado == 'aplicada'

    def test_anular_la_nc_en_el_sri_abona_la_retencion_sin_saldo(self, empresa, dueno, venta, sri):  # noqa: F811
        """NC total 23 → retención 1,30 'sin_saldo' → se marca la NC anulada: la deuda real es 23 − 1,30."""
        nc = nota_credito_autorizada(venta, None, sri=sri)
        ret = retener(empresa, dueno, venta)
        assert (nc.cxc_ajuste, ret.cxc_estado, saldo(empresa, venta)) == ('aplicada', 'sin_saldo', Decimal('0.00'))
        texto = f'de la retención {ret.numero}, que antes superaba el saldo de la cuenta por cobrar.'
        with company_context(empresa):
            assert f'Se abonarán $1,30 {texto}' in anulados.revisar(CreditNote.objects.get(pk=nc.pk))['efectos']
            resultado = anulados.marcar(empresa, dueno, 'nota-credito', CreditNote.objects.get(pk=nc.pk), HOY, MOTIVO)
        assert f'Se abonaron $1,30 {texto}' in resultado['efectos']
        assert saldo(empresa, venta) == Decimal('21.70')
        ret = retencion(empresa, ret.pk)
        assert (ret.cxc_estado, ret.abono.valor) == ('aplicada', Decimal('1.30'))
        assert nota(empresa, nc.pk).cxc_ajuste == 'revertida'

    def test_anular_la_retencion_abona_la_nc_parcial(self, empresa, dueno, venta, sri):  # noqa: F811
        """Cobro 12 → retención 1,30 → NC 11,50 'parcial' (9,70) → se anula la retención: la NC recibe esos 1,30."""
        cobrar(empresa, dueno, venta, '12.00')
        ret = retener(empresa, dueno, venta)
        nc = nota(empresa, nota_credito_autorizada(venta, una_unidad(empresa, venta), sri=sri).pk)
        assert (nc.cxc_ajuste, nc.abono_cxc.valor) == ('parcial', Decimal('9.70'))
        with company_context(empresa):
            rr.anular(empresa, dueno, RetencionRecibida.objects.get(pk=ret.pk), 'El cliente la anuló en el SRI')
        nc = nota(empresa, nc.pk)
        assert (nc.cxc_ajuste, nc.abono_cxc.valor, nc.excedente_cxc()) == ('parcial', Decimal('11.00'), Decimal('0.50'))
        assert saldo(empresa, venta) == Decimal('0.00')
        registro = AuditLog.objects.get(action='retencion_recibida_anulacion')
        assert registro.detail['excedentes_aplicados'] == [
            {'tipo': 'nota_credito', 'numero': nc.voucher_number_full, 'valor': '1.30'}]
        assert retencion(empresa, ret.pk).cxc_estado == 'revertida'

    def test_sin_excedentes_la_auditoria_no_cambia(self, empresa, dueno, venta):  # noqa: F811
        cobro = cobrar(empresa, dueno, venta, '5.00')
        eliminar(empresa, dueno, cobro)
        assert 'excedentes_aplicados' not in AuditLog.objects.get(action='cxc_cobro_eliminado').detail
        assert saldo(empresa, venta) == Decimal('23.00')

    def test_la_cxc_de_una_nota_de_debito_no_reparte_excedentes(self, empresa, dueno, venta, sri):  # noqa: F811
        cobrar(empresa, dueno, venta, '20.00')
        nc = nota_credito_autorizada(venta, una_unidad(empresa, venta), sri=sri)
        nd = nota_debito_autorizada(venta, '5.00', dueno, sri=sri)
        with company_context(empresa):
            cobro_nd = cxc.registrar_cobro(empresa, dueno, nd.cuenta_por_cobrar_id, HOY, '5.00', 'efectivo')
        eliminar(empresa, dueno, cobro_nd)
        nc = nota(empresa, nc.pk)
        assert (nc.cxc_ajuste, nc.abono_cxc.valor) == ('parcial', Decimal('3.00'))
        assert leer(empresa, lambda: CtasCollect.objects.get(pk=nd.cuenta_por_cobrar_id).saldo) == Decimal('5.00')
