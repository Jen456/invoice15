"""Consultas por alcance y fecha efectiva de emisión (Etapa 2, O2), servicio core/pos/consultas.py: «declarables»
(producción, autorizados y 'canceled', sin anular), anulados en el SRI, no autorizados, pruebas y «todos» (exactamente lo
de antes, por fecha de registro); respaldo de la fecha (autorización o registro) con su origen; las CxC de nota de débito
por la fecha de la nota; notas de crédito para restar en «Resultados». La vista de los reportes es del paso siguiente."""
from datetime import date
from decimal import Decimal

import pytest

from core.comprobantes.models import NotaDebito
from core.pos import consultas
from core.pos.models import CreditNote, CtasCollect, Sale
from core.tenancy.context import company_context
from tests.ayudas_ventas import cxc_de, factura_autorizada, nota_credito_autorizada, nota_debito_autorizada
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, producto, sri  # noqa: F401

pytestmark = pytest.mark.django_db
SEP = (date(2026, 9, 1), date(2026, 9, 30))


@pytest.fixture
def factura(empresa, comprador, dueno, producto):  # noqa: F811
    def _factura(**extra):
        return factura_autorizada(empresa, comprador, dueno, producto, **extra)
    return _factura


def pks(queryset):
    return [o.pk for o in queryset]


class TestVentas:

    def test_cada_alcance_muestra_solo_lo_suyo(self, empresa, factura):
        registrada_en_octubre = factura(fecha=date(2026, 10, 2), emitida=date(2026, 9, 30))
        cubierta = factura(estado='canceled', fecha=date(2026, 9, 10))
        enviada = factura(estado='authorized_and_sent_by_email', fecha=date(2026, 9, 11))
        pruebas = factura(ambiente=1, fecha=date(2026, 9, 10))
        sin_autorizar = factura(estado='without_authorizing', fecha=date(2026, 9, 3), emitida=None)
        en_proceso = factura(estado='in_process', fecha=date(2026, 9, 4))
        rechazada = factura(estado='not_authorized', fecha=date(2026, 9, 5))
        anulada = factura(fecha=date(2026, 9, 12))
        ticket = factura(tipo='08', fecha=date(2026, 9, 13), estado='without_authorizing')
        agosto = factura(fecha=date(2026, 8, 31))
        leer(empresa, lambda: Sale.objects.filter(pk=anulada.pk).update(anulado_sri_fecha=date(2026, 9, 20)))
        with company_context(empresa):
            assert pks(consultas.ventas('declarables', *SEP)) == [cubierta.pk, enviada.pk, registrada_en_octubre.pk]
            assert pks(consultas.ventas('no_autorizados', *SEP)) == [sin_autorizar.pk, en_proceso.pk, rechazada.pk]
            assert pks(consultas.ventas('anulados_sri', *SEP)) == [anulada.pk]
            assert pks(consultas.ventas('pruebas', *SEP)) == [pruebas.pk]
            assert agosto.pk in pks(consultas.ventas('declarables')) and ticket.pk not in pks(consultas.ventas('declarables'))
            # «todos»: exactamente lo de antes (sin filtros, por fecha de registro)
            antes = list(Sale.objects.filter().filter(date_joined__range=[*SEP]))
            assert list(consultas.ventas('todos', *SEP)) == antes and registrada_en_octubre not in antes
            assert list(consultas.ventas('todos')) == list(Sale.objects.filter())
            assert pks(consultas.declarables(Sale, *SEP)) == pks(consultas.ventas('declarables', *SEP))

    def test_respaldo_de_la_fecha_y_su_origen(self, empresa, factura):
        por_autorizacion = factura(fecha=date(2026, 10, 1), emitida=None, autorizada=date(2026, 9, 5))
        por_registro = factura(fecha=date(2026, 9, 7), emitida=None)
        del_sri = factura(fecha=date(2026, 9, 9))
        with company_context(empresa):
            filas = list(consultas.ventas('declarables', *SEP))
        assert [(v.pk, v.fecha_efectiva, consultas.origen_fecha(v)) for v in filas] == [
            (por_autorizacion.pk, date(2026, 9, 5), 'autorizacion'), (por_registro.pk, date(2026, 9, 7), 'registro'),
            (del_sri.pk, date(2026, 9, 9), 'sri')]

    def test_alcance_invalido(self, empresa):
        with company_context(empresa):
            for funcion in (consultas.ventas, consultas.notas_credito, consultas.cuentas_por_cobrar):
                with pytest.raises(ValueError, match='^Elige qué comprobantes mostrar.$'):
                    funcion('otro')
        assert [a for a, _ in consultas.ALCANCES] == ['declarables', 'anulados_sri', 'no_autorizados', 'pruebas', 'todos']


class TestCuentasPorCobrar:

    def test_misma_logica_y_la_de_nota_de_debito_por_su_fecha(self, empresa, dueno, factura, sri):  # noqa: F811
        septiembre = factura(credito=True, fecha=date(2026, 9, 15))
        octubre = factura(credito=True, fecha=date(2026, 10, 1))
        pruebas = factura(credito=True, ambiente=1, fecha=date(2026, 9, 16))
        contado = factura(fecha=date(2026, 10, 2))
        nota = nota_debito_autorizada(contado, '5.00', dueno, sri=sri)
        leer(empresa, lambda: NotaDebito.objects.filter(pk=nota.pk).update(emission_date=date(2026, 9, 20)))
        with company_context(empresa):
            declarables = list(consultas.cuentas_por_cobrar('declarables', *SEP))
            assert [(c.pk, c.fecha_efectiva) for c in declarables] == [(cxc_de(septiembre).pk, date(2026, 9, 15)),
                                                                       (nota.cuenta_por_cobrar_id, date(2026, 9, 20))]
            assert declarables[1].toJSON()['documento'] == {'tipo': 'nota_debito', 'id': nota.pk,
                                                            'numero': nota.voucher_number_full}
            assert pks(consultas.cuentas_por_cobrar('pruebas', *SEP)) == [cxc_de(pruebas).pk]
            assert cxc_de(octubre).pk in pks(consultas.cuentas_por_cobrar('declarables'))
            # «todos»: lo de antes, por la fecha de registro de la CxC
            assert pks(consultas.cuentas_por_cobrar('todos', *SEP)) == pks(
                CtasCollect.objects.filter(date_joined__range=[*SEP]).order_by('id'))
            NotaDebito.objects.filter(pk=nota.pk).update(anulado_sri_fecha=date(2026, 9, 25))
            Sale.objects.filter(pk=septiembre.pk).update(anulado_sri_fecha=date(2026, 9, 25))
            assert pks(consultas.cuentas_por_cobrar('declarables', *SEP)) == []
            assert pks(consultas.cuentas_por_cobrar('anulados_sri', *SEP)) == [cxc_de(septiembre).pk, nota.cuenta_por_cobrar_id]
            NotaDebito.objects.filter(pk=nota.pk).update(anulado_sri_fecha=None, status='in_process')
            assert pks(consultas.cuentas_por_cobrar('no_autorizados', *SEP)) == [nota.cuenta_por_cobrar_id]


class TestNotasDeCreditoParaResultados:

    def test_ventas_menos_notas_del_mismo_alcance(self, empresa, factura, sri):  # noqa: F811
        venta = factura(credito=True)
        nota = nota_credito_autorizada(venta, sri=sri, lineas=[(leer(empresa, lambda: venta.saledetail_set.get().pk), 1)])
        cubierta = factura()
        total = nota_credito_autorizada(cubierta, sri=sri)
        pruebas = factura(ambiente=1)
        with company_context(empresa):
            assert Sale.objects.get(pk=cubierta.pk).status == 'canceled'
            ventas = sum(v.total for v in consultas.ventas('declarables'))
            notas = sum(n.total for n in consultas.notas_credito('declarables'))
            assert (ventas, notas, ventas - notas) == (Decimal('46.00'), Decimal('34.50'), Decimal('11.50'))
            assert pks(consultas.declarables(CreditNote, nota.emission_date, nota.emission_date)) == [nota.pk, total.pk]
            CreditNote.objects.filter(pk=nota.pk).update(anulado_sri_fecha=nota.emission_date)
            assert pks(consultas.notas_credito('declarables')) == [total.pk]          # la NC anulada ya no resta
            assert pks(consultas.notas_credito('anulados_sri')) == [nota.pk]
            assert list(consultas.notas_credito('todos')) == list(CreditNote.objects.filter())
            assert pruebas.pk in pks(consultas.ventas('pruebas'))


def test_anulados_sri_de_los_seis_tipos(empresa, factura, dueno, sri):  # noqa: F811
    venta = factura(fecha=date(2026, 9, 2))
    con_nota = factura(credito=True)
    nota = nota_credito_autorizada(con_nota, sri=sri)
    with company_context(empresa):
        Sale.objects.filter(pk=venta.pk).update(anulado_sri_fecha=date(2026, 9, 3))
        CreditNote.objects.filter(pk=nota.pk).update(anulado_sri_fecha=date(2026, 9, 4))
        filas = consultas.anulados_sri(*SEP)
    assert filas == [
        {'modelo': 'sale', 'id': venta.pk, 'cod_doc': '01', 'numero': venta.voucher_number_full, 'autorizacion': '',
         'fecha_emision': date(2026, 9, 2), 'fecha_anulacion': date(2026, 9, 3)},
        {'modelo': 'creditnote', 'id': nota.pk, 'cod_doc': '04', 'numero': nota.voucher_number_full,
         'autorizacion': nota.access_code, 'fecha_emision': nota.emission_date, 'fecha_anulacion': date(2026, 9, 4)}]
