"""Ajuste de la cuenta por cobrar por notas de crédito y de débito al autorizarse (Etapa 2, O2), por la emisión real con
el SRI falso (emision.emitir dispara comprobante_autorizado), y las órdenes aplicar_ajustes_cxc y
regularizar_cxc_historico (ensayo por defecto; la regularización exige --decision)."""
import csv
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.core.management import CommandError, call_command
from django.db import transaction
from django.utils import timezone

from core.comprobantes.models import NotaDebito
from core.pos import cxc, emision
from core.pos.models import CreditNote, CtasCollect, PaymentsCtaCollect, SaleDetail, VoucherErrors
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog
from tests.ayudas_ventas import cxc_de, nota_credito_autorizada, nota_debito_autorizada
from tests.test_emision_sri import (comprador, dueno, empresa, leer, p12, producto, sri, vender, venta_de,  # noqa: F401
                                    web)

pytestmark = pytest.mark.django_db
HOY = timezone.localdate()


@pytest.fixture
def credito(web, empresa, comprador, producto, sri):  # noqa: F811
    """Factura 001-002-000000271 a crédito, autorizada: 2 × $10 + IVA = $23, con su CxC."""
    sri.respuestas_autorizacion = ['AUTORIZADO']
    vender(web, comprador, producto, cantidad=2, payment_type='credito', end_credit=(HOY + timedelta(days=30)).isoformat())
    venta = venta_de(empresa, 271)
    assert venta.status == 'authorized' and cxc_de(venta).debt == Decimal('23.00')
    return venta


@pytest.fixture
def contado(web, empresa, comprador, producto, sri):  # noqa: F811
    sri.respuestas_autorizacion = ['AUTORIZADO']
    vender(web, comprador, producto, cantidad=2)
    return venta_de(empresa, 271)


def detalle(venta):
    return leer(venta.company, lambda: SaleDetail.objects.get(sale=venta).pk)


def una(venta):
    """Nota de crédito de 1 unidad: $11,50."""
    return [(detalle(venta), 1)]


def abonos(empresa, **filtro):
    return leer(empresa, lambda: list(PaymentsCtaCollect.objects.filter(**filtro).order_by('id')))


class TestNotaCredito:

    def test_autorizada_sobre_credito_abona_la_cxc(self, empresa, credito, sri):  # noqa: F811
        nota = nota_credito_autorizada(credito, una(credito), sri=sri)
        assert nota.status == 'authorized' and nota.cxc_ajuste == 'aplicada' and nota.total == Decimal('11.50')
        [abono] = abonos(empresa)
        assert (abono.tipo, abono.valor, abono.description) == ('nota_credito', Decimal('11.50'),
                                                                f'Nota de crédito {nota.voucher_number_full}')
        assert nota.abono_cxc_id == abono.pk and cxc_de(credito).saldo == Decimal('11.50')
        assert leer(empresa, lambda: CreditNote.objects.get(pk=nota.pk).toJSON())['excedente_cxc'] == '0.00'
        assert mail.outbox == []

    def test_mayor_que_el_saldo_queda_parcial(self, empresa, dueno, credito, sri):  # noqa: F811
        with company_context(empresa):
            cxc.registrar_cobro(empresa, dueno, cxc_de(credito).pk, HOY, '20.00', 'efectivo')
        nota = nota_credito_autorizada(credito, una(credito), sri=sri)
        assert nota.cxc_ajuste == 'parcial'
        assert abonos(empresa, tipo='nota_credito')[0].valor == Decimal('3.00') and cxc_de(credito).saldo == Decimal('0.00')
        json_nota = leer(empresa, lambda: CreditNote.objects.get(pk=nota.pk).toJSON())
        assert json_nota['excedente_cxc'] == '8.50' and json_nota['cxc_ajuste'] == {
            'id': 'parcial', 'name': 'Aplicada en parte: el resto excede el saldo'}

    def test_sobre_contado_sin_cxc(self, empresa, contado, sri):  # noqa: F811
        nota = nota_credito_autorizada(contado, una(contado), sri=sri)
        assert nota.cxc_ajuste == 'sin_cxc' and nota.abono_cxc_id is None and abonos(empresa) == []

    def test_sobre_cxc_saldada(self, empresa, dueno, credito, sri):  # noqa: F811
        with company_context(empresa):
            cxc.registrar_cobro(empresa, dueno, cxc_de(credito).pk, HOY, '23.00', 'efectivo')
        nota = nota_credito_autorizada(credito, una(credito), sri=sri)
        assert nota.cxc_ajuste == 'sin_saldo' and abonos(empresa, tipo='nota_credito') == []
        assert leer(empresa, lambda: CreditNote.objects.get(pk=nota.pk).toJSON())['excedente_cxc'] == '11.50'

    def test_reenvio_y_doble_aplicacion_dejan_un_solo_abono(self, empresa, credito, sri):  # noqa: F811
        nota = nota_credito_autorizada(credito, una(credito), sri=sri)
        with company_context(empresa):
            resultado = emision.emitir(nota)              # reenviar una nota ya autorizada vuelve a enviar la señal
            assert 'Ya estaba autorizada' in resultado['mensaje']
            assert cxc.aplicar_nota_credito(nota.pk) == 'aplicada'
        assert len(abonos(empresa, tipo='nota_credito')) == 1 and cxc_de(credito).saldo == Decimal('11.50')

    def test_devuelta_sigue_pendiente(self, empresa, credito, sri):  # noqa: F811
        sri.respuestas_recepcion = [('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])]
        nota = nota_credito_autorizada(credito, una(credito), sri=sri, autorizar=False)
        assert nota.status == 'returned' and nota.cxc_ajuste == 'pendiente' and abonos(empresa) == []
        with company_context(empresa):
            assert cxc.aplicar_nota_credito(nota.pk) == 'pendiente' and abonos(empresa) == []

    def test_historica_no_aplica_no_se_toca_al_autorizarse(self, empresa, credito, sri):  # noqa: F811
        nota = nota_credito_autorizada(credito, una(credito), sri=sri, autorizar=False)   # el SRI tarda: en proceso
        assert nota.status == 'in_process'
        leer(empresa, lambda: CreditNote.objects.filter(pk=nota.pk).update(cxc_ajuste='no_aplica'))
        sri.respuestas_autorizacion = ['AUTORIZADO']
        with company_context(empresa):
            emision.emitir(nota)
            nota.refresh_from_db()
        assert nota.status == 'authorized' and nota.cxc_ajuste == 'no_aplica' and abonos(empresa) == []

    def test_receptor_que_falla_deja_pendiente_y_la_orden_lo_aplica(self, empresa, credito, sri, monkeypatch, capsys):  # noqa: F811
        def falla(nota_id, desde='pendiente'):
            raise RuntimeError('ajuste de prueba')
        with monkeypatch.context() as m:
            m.setattr(cxc, 'aplicar_nota_credito', falla)
            nota = nota_credito_autorizada(credito, una(credito), sri=sri)
        assert nota.status == 'authorized' and nota.cxc_ajuste == 'pendiente' and abonos(empresa) == []
        errores = leer(empresa, lambda: list(VoucherErrors.objects.filter(reference=nota.voucher_number_full)
                                             .values_list('stage', 'errors')))
        assert len(errores) == 1 and errores[0][0] == 'xml_authorized' and 'RuntimeError' in errores[0][1]['error']
        call_command('aplicar_ajustes_cxc', '--empresa', empresa.ruc)
        salida = capsys.readouterr().out
        assert f'NC {nota.voucher_number_full}: aplicada (abono 11.50' in salida and 'ENSAYO' in salida
        assert abonos(empresa) == []
        call_command('aplicar_ajustes_cxc', '--aplicar')
        assert 'APLICADO: pendientes 1, aplicados 1' in capsys.readouterr().out
        assert leer(empresa, lambda: CreditNote.objects.get(pk=nota.pk).cxc_ajuste) == 'aplicada'
        assert len(abonos(empresa, tipo='nota_credito')) == 1
        call_command('aplicar_ajustes_cxc', '--aplicar')
        assert 'pendientes 0' in capsys.readouterr().out
        with pytest.raises(CommandError, match='No hay una empresa'):
            call_command('aplicar_ajustes_cxc', '--empresa', '0999999999001')


class TestNotaDebito:

    def test_crea_su_propia_cxc(self, empresa, dueno, credito, sri):  # noqa: F811
        nota = nota_debito_autorizada(credito, '5.00', dueno, sri=sri)
        assert nota.status == 'authorized' and nota.cxc_ajuste == 'aplicada'
        with company_context(empresa):
            propia = CtasCollect.objects.get(pk=nota.cuenta_por_cobrar_id)
            factura = cxc.cxc_de_factura(credito)
            assert (propia.sale_id, propia.debt, propia.saldo, propia.state) == (credito.pk, Decimal('5.00'), Decimal('5.00'), True)
            assert propia.date_joined == nota.emission_date and propia.end_date == factura.end_date   # vence como la factura
            assert factura.debt == Decimal('23.00') and factura.saldo == Decimal('23.00')            # la de la factura no cambia
            assert propia.toJSON()['documento'] == {'tipo': 'nota_debito', 'id': nota.pk, 'numero': nota.voucher_number_full}
            assert cxc.listado().get(pk=propia.pk).toJSON()['documento']['tipo'] == 'nota_debito'
            assert cxc.aplicar_nota_debito(nota.pk) == 'aplicada' and CtasCollect.objects.filter(sale=credito).count() == 2

    def test_tambien_sobre_contado(self, empresa, dueno, contado, sri):  # noqa: F811
        nota = nota_debito_autorizada(contado, '7.25', dueno, sri=sri)
        with company_context(empresa):
            propia = CtasCollect.objects.get(sale=contado)
        assert nota.cuenta_por_cobrar_id == propia.pk and propia.debt == Decimal('7.25') and propia.end_date == nota.emission_date

    def test_cxc_de_factura_ignora_la_de_la_nota_y_se_bloquea(self, empresa, dueno, credito, sri):  # noqa: F811
        nota = nota_debito_autorizada(credito, '5.00', dueno, sri=sri)
        with company_context(empresa), transaction.atomic():
            bloqueada = cxc.cxc_de_factura(credito, bloquear=True)     # en PG: sin «FOR UPDATE … outer join»
            assert bloqueada.pk == cxc_de(credito).pk != nota.cuenta_por_cobrar_id
            assert cxc.cxc_de_factura(credito.pk).pk == bloqueada.pk

    def test_no_autorizada_sigue_pendiente(self, empresa, dueno, credito, sri):  # noqa: F811
        sri.respuestas_recepcion = [('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])]
        nota = nota_debito_autorizada(credito, '5.00', dueno, sri=sri, autorizar=False)
        assert nota.status == 'returned' and nota.cxc_ajuste == 'pendiente' and nota.cuenta_por_cobrar_id is None


class TestRegularizarHistorico:

    @pytest.fixture
    def historica(self, empresa, credito, sri):  # noqa: F811
        """NC autorizada antes de la regla: 'no_aplica' y sin abono."""
        nota = nota_credito_autorizada(credito, una(credito), sri=sri, autorizar=False)
        leer(empresa, lambda: CreditNote.objects.filter(pk=nota.pk).update(cxc_ajuste='no_aplica'))
        sri.respuestas_autorizacion = ['AUTORIZADO']
        with company_context(empresa):
            emision.emitir(nota)
            nota.refresh_from_db()
        assert nota.status == 'authorized' and nota.cxc_ajuste == 'no_aplica'
        return nota

    def test_ensayo_informe_y_aplicar_con_decision(self, empresa, credito, historica, tmp_path, capsys):  # noqa: F811
        informe = tmp_path / 'informe.csv'
        call_command('regularizar_cxc_historico', '--empresa', empresa.ruc, '--informe', str(informe))
        salida = capsys.readouterr().out
        assert 'ENSAYO (no se cambió nada): documentos 1, para revisar 0, aplicados 0' in salida
        with open(informe, encoding='utf-8') as archivo:
            filas = list(csv.DictReader(archivo))
        assert len(filas) == 1 and filas[0]['tipo'] == 'nc' and filas[0]['numero'] == historica.voucher_number_full
        assert (filas[0]['deuda'], filas[0]['saldo_actual'], filas[0]['valor_a_abonar'], filas[0]['excedente'],
                filas[0]['efecto'], filas[0]['revisar']) == ('23.00', '23.00', '11.50', '0.00', 'aplicada', 'no')
        assert abonos(empresa) == [] and leer(empresa, lambda: CreditNote.objects.get(pk=historica.pk).cxc_ajuste) == 'no_aplica'
        with pytest.raises(CommandError, match='--decision'):
            call_command('regularizar_cxc_historico', '--empresa', empresa.ruc, '--aplicar')
        call_command('regularizar_cxc_historico', '--empresa', empresa.ruc, '--aplicar', '--decision',
                     'Decisión de prueba de la propietaria', '--informe', str(informe))
        assert leer(empresa, lambda: CreditNote.objects.get(pk=historica.pk).cxc_ajuste) == 'aplicada'
        assert [a.valor for a in abonos(empresa, tipo='nota_credito')] == [Decimal('11.50')]
        registro = AuditLog.objects.get(action='regularizacion_datos_origen')
        json.dumps(registro.detail)
        assert registro.detail == {'orden': 'regularizar_cxc_historico', 'decision': 'Decisión de prueba de la propietaria',
                                   'informe': str(informe), 'documentos': [
                                       {'tipo': 'nc', 'id': historica.pk, 'numero': historica.voucher_number_full,
                                        'efecto': 'aplicada', 'valor': '11.50'}]}

    def test_revisar_si_un_cobro_cita_la_nota(self, empresa, dueno, credito, historica, capsys):  # noqa: F811
        with company_context(empresa):
            cxc.registrar_cobro(empresa, dueno, cxc_de(credito).pk, HOY, '2.00', 'efectivo',
                                descripcion=f'Cruce con NC {historica.voucher_number_full}')
        call_command('regularizar_cxc_historico', '--empresa', empresa.ruc, '--tipo', 'nc', '--aplicar', '--decision', 'Prueba')
        salida = capsys.readouterr().out
        assert 'REVISAR: un cobro de la cuenta' in salida and 'para revisar 1, aplicados 0' in salida
        assert leer(empresa, lambda: CreditNote.objects.get(pk=historica.pk).cxc_ajuste) == 'no_aplica'
        call_command('regularizar_cxc_historico', '--empresa', empresa.ruc, '--aplicar', '--decision', 'Prueba',
                     '--incluir-revisar')
        assert leer(empresa, lambda: CreditNote.objects.get(pk=historica.pk).cxc_ajuste) == 'aplicada'

    def test_nota_de_debito_historica(self, empresa, dueno, credito, sri, capsys):  # noqa: F811
        nota = nota_debito_autorizada(credito, '5.00', dueno, sri=sri, autorizar=False)
        leer(empresa, lambda: NotaDebito.objects.filter(pk=nota.pk).update(cxc_ajuste='no_aplica', status='authorized'))
        call_command('regularizar_cxc_historico', '--empresa', empresa.ruc, '--tipo', 'nd')
        assert f'ND {nota.voucher_number_full}' in capsys.readouterr().out
        assert leer(empresa, lambda: CtasCollect.objects.filter(sale=credito).count()) == 1
        call_command('regularizar_cxc_historico', '--empresa', empresa.ruc, '--tipo', 'nd', '--aplicar', '--decision', 'Prueba')
        with company_context(empresa):
            nota = NotaDebito.objects.get(pk=nota.pk)
            assert nota.cxc_ajuste == 'aplicada' and nota.cuenta_por_cobrar.debt == Decimal('5.00')
