"""Cuentas por pagar (core/pos/cuentas_por_pagar.py y DebtsPay): pagos con medio de pago y referencia, saldo en Decimal,
borrados con permiso y auditados, y abonos por retención emitida que se recalculan con las señales de B0 (autorizada por
emision.emitir con el SRI simulado, por la vista y por consultar_sri; anulada en el SRI; borrada). Datos ficticios."""
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.comprobantes import retenciones
from core.comprobantes.models import Retencion
from core.pos import compras, cuentas_por_pagar as cxp, emision
from core.pos.models import DebtsPay, PaymentsDebtsPay
from core.pos.senales_comprobantes import anulado_en_sri
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_READONLY, AuditLog
from tests import ayuda_compras as ayuda, helpers
from tests.test_retenciones import (LISTA, codigos, empresa, formulario, numeracion, p12, sri,  # noqa: F401 (fixtures)
                                    web)

pytestmark = pytest.mark.django_db
RUC = '0990000001001'


def hoy():
    return timezone.localdate()


@pytest.fixture
def proveedor(empresa):  # noqa: F811
    # Sin correo válido: la retención queda «Autorizada» (no «enviada») y reenviarla vuelve a emitir la señal.
    return ayuda.crear_proveedor(empresa, tipo='04', ruc=RUC, correo='sin-correo-proveedor')


def compra_a_credito(empresa, usuario, proveedor, precio='100.00', codigo='4', **cambios):  # noqa: F811
    datos = ayuda.datos_compra(proveedor, payment_type='credito', end_credit=(hoy() + timedelta(days=30)).isoformat(), **cambios)
    with company_context(empresa):
        compra = compras.crear_compra(empresa, usuario, datos, [ayuda.linea_gasto(price=precio, codigo=codigo)])
        return compra, DebtsPay.objects.get(purchase=compra)


@pytest.fixture
def deuda(empresa, admin, proveedor):  # noqa: F811
    return compra_a_credito(empresa, admin, proveedor)[1]


def saldo(empresa, deuda):  # noqa: F811
    with company_context(empresa):
        return DebtsPay.objects.get(pk=deuda.pk).saldo


def pagar(empresa, deuda, usuario, **datos):  # noqa: F811
    datos = {'fecha': hoy(), 'valor': '15.00', 'medio_pago': 'transferencia', 'referencia': 'TRX-001', **datos}
    with company_context(empresa):
        return cxp.registrar_pago(deuda.pk, usuario, **datos)


class TestPagos:

    def test_pago_con_medio_referencia_y_quien_lo_registro(self, empresa, admin, deuda):  # noqa: F811
        pago = pagar(empresa, deuda, admin, descripcion='Abono de octubre')
        assert (pago.medio_pago, pago.referencia, pago.registrado_por_id, pago.valor) == (
            'transferencia', 'TRX-001', admin.pk, Decimal('15.00'))
        assert pago.registrado_en is not None and str(pago) == f'Pago {pago.pk} de la cuenta {deuda.pk}'
        assert saldo(empresa, deuda) == Decimal('100.00')
        assert pago.toJSON()['medio_pago'] == {'id': 'transferencia', 'name': 'Transferencia'}

    @pytest.mark.parametrize('datos, mensaje', [
        ({'medio_pago': 'cheque', 'referencia': ''}, 'Escribe el número del cheque.'),
        ({'medio_pago': ''}, 'Elige el medio de pago.'),
        ({'medio_pago': '20'}, 'Medio de pago no válido.'),             # la Tabla 13 no es el medio del pago
        ({'valor': '200.00'}, 'El pago ($200.00) supera el saldo pendiente ($115.00).'),
        ({'valor': '0'}, 'mayor que cero'),
        ({'valor': '1.234'}, 'hasta 2 decimales'),
        ({'fecha': timezone.localdate() - timedelta(days=1)}, 'anterior a la de la cuenta por pagar'),
        ({'fecha': timezone.localdate() + timedelta(days=1)}, 'no puede ser futura'),
        ({'cuenta': 7}, 'Las cuentas bancarias llegan en la Etapa 3.'),
        ({'referencia': 'x' * 101}, 'hasta 100 caracteres'),
    ])
    def test_validaciones(self, empresa, admin, deuda, datos, mensaje):  # noqa: F811
        with pytest.raises(cxp.ErrorPago, match=re.escape(mensaje)):
            pagar(empresa, deuda, admin, **datos)
        assert not ayuda.en(empresa, PaymentsDebtsPay.objects.exists) and saldo(empresa, deuda) == Decimal('115.00')

    def test_saldo_en_decimal(self, empresa, admin, proveedor):  # noqa: F811
        _, deuda = compra_a_credito(empresa, admin, proveedor, precio='0.30', codigo='0')  # noqa: F811
        pagar(empresa, deuda, admin, valor='0.10', medio_pago='efectivo', referencia='')
        pagar(empresa, deuda, admin, valor='0.20', medio_pago='efectivo', referencia='')
        with company_context(empresa):
            actual = DebtsPay.objects.get(pk=deuda.pk)
            pagado = actual.toJSON()['pagado']
        assert actual.saldo == Decimal('0.00') and actual.state is False and pagado == '0.30'


class TestBorrados:

    def peticion(self, empresa, rol):  # noqa: F811
        return ayuda.peticion(helpers.crear_usuario(f'{rol.lower()}.cxp', empresa, rol), empresa)

    def test_borrar_un_pago_exige_el_permiso_de_eliminar(self, empresa, admin, deuda):  # noqa: F811
        pago = pagar(empresa, deuda, admin)
        for rol in (ROLE_ACCOUNTANT, ROLE_READONLY):
            request = self.peticion(empresa, rol)
            assert not cxp.puede_eliminar(request)
            with company_context(empresa), pytest.raises(cxp.SinPermiso, match='Tu perfil no puede eliminar pagos.'):
                cxp.eliminar_pago(request, pago.pk)
        assert ayuda.en(empresa, PaymentsDebtsPay.objects.filter(pk=pago.pk).exists)
        dueno = ayuda.peticion(admin, empresa)
        assert cxp.puede_eliminar(dueno)
        with company_context(empresa):
            cxp.eliminar_pago(dueno, pago.pk)
        assert not ayuda.en(empresa, PaymentsDebtsPay.objects.exists) and saldo(empresa, deuda) == Decimal('115.00')
        registro = AuditLog.objects.get(action='debt_payment_delete', company=empresa)
        assert registro.user_id == admin.pk and registro.detail == {
            'deuda': deuda.pk, 'pago': pago.pk, 'valor': '15.00', 'fecha': hoy().isoformat(), 'medio_pago': 'transferencia',
            'referencia': 'TRX-001'}

    def test_borrar_la_cuenta_solo_sin_pagos_ni_abonos(self, empresa, admin, proveedor, deuda):  # noqa: F811
        dueno = ayuda.peticion(admin, empresa)
        pago = pagar(empresa, deuda, admin)
        with company_context(empresa), pytest.raises(cxp.ErrorPago, match='Tiene pagos registrados: elimínalos primero'):
            cxp.eliminar_deuda(dueno, deuda.pk)
        with company_context(empresa):
            cxp.eliminar_pago(dueno, pago.pk)
            factura = deuda.purchase
        nota = ayuda.datos_compra(proveedor, tipo_comprobante='04', tipo_doc_modificado='01',
                                  num_doc_modificado=factura.numero_comprobante, aut_doc_modificado=factura.autorizacion,
                                  fecha_doc_modificado=factura.fecha_emision.isoformat(), compra_modificada=factura.pk)
        with company_context(empresa):
            nota = compras.crear_compra(empresa, admin, nota, [ayuda.linea_gasto(price='10.00', codigo='0')])
            with pytest.raises(cxp.ErrorPago, match='Tiene retenciones o notas de crédito aplicadas'):
                cxp.eliminar_deuda(dueno, deuda.pk)
            compras.eliminar_compra(nota, admin)
            cxp.eliminar_deuda(dueno, deuda.pk)
            assert not DebtsPay.objects.exists()
        assert AuditLog.objects.get(action='debt_delete', company=empresa).detail == {
            'deuda': deuda.pk, 'compra': factura.pk, 'debt': '115.00', 'saldo': '115.00'}


class TestAbonosPorRetencion:

    def lineas(self, codigos):  # noqa: F811
        return [(codigos['bienes'], '', ''), (codigos['iva30'], '', '')]          # 2 % de 100 + 30 % de 15 = 6,50

    def retencion_de(self, empresa, compra):  # noqa: F811
        with company_context(empresa):
            return Retencion.objects.get(purchase=compra)

    def test_autorizada_por_la_vista_abona_una_cuenta_total_una_sola_vez(self, web, empresa, admin, proveedor, deuda, codigos,  # noqa: F811
                                                                         numeracion, sri):  # noqa: F811
        sri.respuestas_autorizacion = ['AUTORIZADO']
        web.post(f'{LISTA}nueva/{deuda.purchase_id}/', {**formulario(self.lineas(codigos)), 'action': 'emitir'})
        retencion = self.retencion_de(empresa, deuda.purchase_id)
        assert retencion.status == 'authorized' and retencion.total_retenido == Decimal('6.50')
        assert saldo(empresa, deuda) == Decimal('108.50')
        with company_context(empresa):
            assert emision.emitir(retencion)['mensaje'] == 'Ya estaba autorizada por el SRI.'    # la señal se repite
            abonos = DebtsPay.objects.get(pk=deuda.pk).toJSON(detalle=True)
        assert saldo(empresa, deuda) == Decimal('108.50')
        assert abonos['abonado'] == '6.50' and [(a['tipo'], a['valor']) for a in abonos['abonos']] == [('retencion', '6.50')]

    def test_una_cuenta_calculada_sin_iva_no_recibe_el_abono(self, web, empresa, proveedor, codigos, numeracion, sri):  # noqa: F811
        antigua = ayuda.compra_antigua(empresa, proveedor, '100.00', credito=True)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        web.post(f'{LISTA}nueva/{antigua.pk}/', {**formulario(self.lineas(codigos)), 'action': 'emitir'})
        assert self.retencion_de(empresa, antigua).status == 'authorized'
        with company_context(empresa):
            assert DebtsPay.objects.get(purchase=antigua).saldo == Decimal('100.00')

    def test_autorizada_por_la_tarea_periodica(self, web, empresa, deuda, codigos, numeracion, sri):  # noqa: F811
        web.post(f'{LISTA}nueva/{deuda.purchase_id}/', {**formulario(self.lineas(codigos)), 'action': 'emitir'})
        assert self.retencion_de(empresa, deuda.purchase_id).status == 'in_process' and saldo(empresa, deuda) == Decimal('115.00')
        sri.respuestas_autorizacion = ['AUTORIZADO']
        call_command('consultar_sri')
        assert self.retencion_de(empresa, deuda.purchase_id).status == 'authorized'
        assert saldo(empresa, deuda) == Decimal('108.50')

    @pytest.mark.parametrize('respuesta', ['no_autorizada', 'devuelta'])
    def test_no_autorizada_o_devuelta_no_abona(self, web, empresa, deuda, codigos, numeracion, sri, respuesta):  # noqa: F811
        if respuesta == 'devuelta':
            sri.respuestas_recepcion = [('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])]
        else:
            sri.respuestas_autorizacion = ['NO AUTORIZADO']
        web.post(f'{LISTA}nueva/{deuda.purchase_id}/', {**formulario(self.lineas(codigos)), 'action': 'emitir'})
        assert self.retencion_de(empresa, deuda.purchase_id).status in ('not_authorized', 'returned')
        assert saldo(empresa, deuda) == Decimal('115.00')

    def test_anulada_en_el_sri_o_borrada_recalcula(self, web, empresa, deuda, codigos, numeracion, sri, monkeypatch):  # noqa: F811
        sri.respuestas_autorizacion = ['AUTORIZADO']
        web.post(f'{LISTA}nueva/{deuda.purchase_id}/', {**formulario(self.lineas(codigos)), 'action': 'emitir'})
        retencion = self.retencion_de(empresa, deuda.purchase_id)
        assert saldo(empresa, deuda) == Decimal('108.50')
        # O2 añade a retenciones_autorizadas el filtro de anuladas en el SRI; aquí se simula para probar el receptor.
        with monkeypatch.context() as m:
            m.setattr(retenciones, 'retenciones_autorizadas', lambda compra: Retencion.objects.none())
            with company_context(empresa):
                anulado_en_sri.send(sender=Retencion, instance=retencion, usuario=None, fecha=hoy())
            assert saldo(empresa, deuda) == Decimal('115.00')
        with company_context(empresa):
            DebtsPay.objects.filter(pk=deuda.pk).update(saldo=Decimal('108.50'))
            Retencion.objects.filter(pk=retencion.pk).delete()                    # post_delete
        assert saldo(empresa, deuda) == Decimal('115.00')


def test_el_listado_no_consulta_por_fila(empresa, admin, proveedor):  # noqa: F811
    def listar():
        with company_context(empresa), CaptureQueriesContext(connection) as consultas:
            filas = [d.toJSON() for d in DebtsPay.con_pagado(DebtsPay.objects.select_related('purchase__provider'))]
        return filas, len(consultas)

    _, deuda = compra_a_credito(empresa, admin, proveedor)   # noqa: F811
    pagar(empresa, deuda, admin, valor='15.00')
    una, consultas_una = listar()
    for _ in range(19):
        compra_a_credito(empresa, admin, proveedor)
    veinte, consultas_veinte = listar()
    assert len(una) == 1 and len(veinte) == 20 and consultas_una == consultas_veinte
    fila = next(f for f in veinte if f['id'] == deuda.pk)
    assert (fila['pagado'], fila['abonado'], fila['saldo_a_favor']) == ('15.00', '0.00', False)
    assert fila['base_calculo'] == {'id': 'total', 'name': 'Total con IVA'} and fila['saldo'] == 100.0
