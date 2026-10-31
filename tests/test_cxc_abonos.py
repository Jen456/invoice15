"""Cuentas por cobrar (Etapa 2, O2), servicio core/pos/cxc.py: cobros con medio de pago y referencia, saldo con abonos
vigentes en Decimal, eliminación de cobros con permiso y auditoría, eliminación de la CxC, claves nuevas de toJSON y
listados con número constante de consultas; y sus pantallas: 403 al eliminar sin permiso, registro de cobros por la
vista, JSON sin interpretar, consultas constantes por la vista y planes vencido y gratuito."""
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.db.models import ProtectedError
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.pos import cxc
from core.pos.models import CtasCollect, PaymentsCtaCollect
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_OWNER, ROLE_READONLY, AuditLog
from core.user.models import User
from tests import helpers
from tests.ayudas_ventas import cxc_de, factura_autorizada, nota_credito_autorizada, nota_debito_autorizada, peticion
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, producto, sri  # noqa: F401

pytestmark = pytest.mark.django_db
HOY = timezone.localdate()


@pytest.fixture
def venta(empresa, comprador, dueno, producto):  # noqa: F811
    """Factura a crédito de $23,00 emitida hace 5 días, con su CxC."""
    return factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=HOY - timedelta(days=5))


@pytest.fixture
def cuenta(venta):
    return cxc_de(venta)


def cobrar(empresa, usuario, cuenta, valor='10.00', medio='transferencia', referencia='TRX-1', fecha=HOY, **extra):
    with company_context(empresa):
        return cxc.registrar_cobro(empresa, usuario, cuenta.pk, fecha, valor, medio, referencia, 'Abono de prueba', **extra)


def recargar(empresa, cuenta):
    return leer(empresa, lambda: CtasCollect.objects.get(pk=cuenta.pk))


class TestRegistrarCobro:

    def test_cobro_valido_guarda_tipo_medio_referencia_y_usuario(self, empresa, dueno, cuenta):  # noqa: F811
        abono = cobrar(empresa, dueno, cuenta, ' 10 ', referencia='  TRX  123 ')
        assert (abono.tipo, abono.medio_pago, abono.referencia, abono.valor) == ('cobro', 'transferencia', 'TRX 123', Decimal('10.00'))
        assert abono.registrado_por == dueno and abono.registrado_en is not None and abono.anulado_en is None
        cuenta = recargar(empresa, cuenta)
        assert cuenta.saldo == Decimal('13.00') and cuenta.state is True

    @pytest.mark.parametrize('valor, codigo', [('0', 'valor'), ('-5', 'valor'), ('abc', 'valor'), ('', 'valor'),
                                               ('23.01', 'valor_excede')])
    def test_valores_invalidos(self, empresa, dueno, cuenta, valor, codigo):  # noqa: F811
        with pytest.raises(cxc.ErrorCxC) as error:
            cobrar(empresa, dueno, cuenta, valor)
        assert error.value.codigo == codigo
        if codigo == 'valor_excede':
            assert str(error.value) == 'El valor (23.01) supera el saldo de la cuenta por cobrar (23.00).'
        assert not leer(empresa, lambda: PaymentsCtaCollect.objects.exists())

    def test_fechas(self, empresa, dueno, cuenta, venta):  # noqa: F811
        with pytest.raises(cxc.ErrorCxC, match='no puede ser futura') as error:
            cobrar(empresa, dueno, cuenta, fecha=HOY + timedelta(days=1))
        assert error.value.codigo == 'fecha_futura'
        with pytest.raises(cxc.ErrorCxC) as error:
            cobrar(empresa, dueno, cuenta, fecha=HOY - timedelta(days=6))
        assert error.value.codigo == 'fecha_anterior' and f'({venta.date_joined:%d/%m/%Y})' in str(error.value)
        with pytest.raises(cxc.ErrorCxC) as error:
            cobrar(empresa, dueno, cuenta, fecha='28-10-2026')
        assert error.value.codigo == 'fecha'
        assert cobrar(empresa, dueno, cuenta, fecha=(HOY - timedelta(days=5)).isoformat()).date_joined == HOY - timedelta(days=5)

    @pytest.mark.parametrize('medio', ['', 'bitcoin', None])
    def test_sin_medio_de_pago(self, empresa, dueno, cuenta, medio):  # noqa: F811
        with pytest.raises(cxc.ErrorCxC, match='Elige el medio de pago.') as error:
            cobrar(empresa, dueno, cuenta, medio=medio)
        assert error.value.codigo == 'medio_pago'

    def test_cheque_exige_referencia(self, empresa, dueno, cuenta):  # noqa: F811
        with pytest.raises(cxc.ErrorCxC) as error:
            cobrar(empresa, dueno, cuenta, medio='cheque', referencia='   ')
        assert error.value.codigo == 'referencia_cheque' and str(error.value) == 'Escribe el número del cheque en «Referencia».'
        assert cobrar(empresa, dueno, cuenta, medio='cheque', referencia='CH-0045').referencia == 'CH-0045'

    def test_cxc_saldada(self, empresa, dueno, cuenta):  # noqa: F811
        cobrar(empresa, dueno, cuenta, '23.00', medio='efectivo', referencia='')
        assert recargar(empresa, cuenta).state is False
        with pytest.raises(cxc.ErrorCxC) as error:
            cobrar(empresa, dueno, cuenta, '1.00')
        assert error.value.codigo == 'cxc_saldada'

    def test_cuenta_reservada_para_la_etapa_3(self, empresa, dueno, cuenta):  # noqa: F811
        with company_context(empresa), pytest.raises(ValueError, match='Etapa 3'):
            cxc.registrar_cobro(empresa, dueno, cuenta.pk, HOY, '1.00', 'efectivo', cuenta=7)

    def test_decimal_exacto_sin_float(self, empresa, dueno, cuenta):  # noqa: F811
        cobrar(empresa, dueno, cuenta, '0.10')
        cobrar(empresa, dueno, cuenta, 0.2)                     # aunque llegue un float, se guarda 0.20
        cuenta = recargar(empresa, cuenta)
        assert cuenta.saldo == Decimal('22.70') and leer(empresa, cuenta.saldo_actual) == Decimal('22.70')
        assert sorted(leer(empresa, lambda: list(PaymentsCtaCollect.objects.values_list('valor', flat=True)))) == \
            [Decimal('0.10'), Decimal('0.20')]

    def test_el_saldo_ignora_los_abonos_anulados(self, empresa, dueno, cuenta):  # noqa: F811
        cobrar(empresa, dueno, cuenta, '5.00')
        with company_context(empresa):
            automatico = cxc.crear_abono(cuenta, 'retencion', Decimal('3.00'), HOY, 'Retención de prueba')
            assert CtasCollect.objects.get(pk=cuenta.pk).saldo == Decimal('15.00')
            cxc.revertir_abono(automatico, timezone.now(), 'Anulada en el SRI por el cliente')
            cuenta = CtasCollect.objects.get(pk=cuenta.pk)
            assert cuenta.saldo == Decimal('18.00') == cuenta.saldo_actual()
            assert PaymentsCtaCollect.objects.get(pk=automatico.pk).anulado_motivo == 'Anulada en el SRI por el cliente'

    def test_cxc_anulada_no_admite_cobros(self, empresa, dueno, cuenta):  # noqa: F811
        with company_context(empresa):
            cxc.crear_abono(cuenta, 'anulacion', Decimal('20.00'), HOY, 'Anulación de prueba')
        with pytest.raises(cxc.ErrorCxC) as error:
            cobrar(empresa, dueno, cuenta, '1.00')
        assert error.value.codigo == 'cxc_anulada'


class TestEliminar:

    @pytest.mark.parametrize('rol', [ROLE_READONLY, ROLE_ACCOUNTANT])
    def test_consulta_y_contador_no_eliminan_cobros(self, empresa, dueno, cuenta, rol):  # noqa: F811
        abono = cobrar(empresa, dueno, cuenta)
        lector = helpers.crear_usuario(f'lector.{rol.lower()}', empresa, rol)
        with company_context(empresa), pytest.raises(cxc.ErrorCxC, match='Tu perfil no puede eliminar cobros.') as error:
            cxc.eliminar_cobro(peticion(lector, empresa), abono.pk)
        assert error.value.codigo == 'sin_permiso_eliminar'
        assert leer(empresa, lambda: PaymentsCtaCollect.objects.filter(pk=abono.pk).exists())

    def test_propietario_elimina_un_cobro_auditado(self, empresa, dueno, cuenta):  # noqa: F811
        abono = cobrar(empresa, dueno, cuenta, '10.00', medio='cheque', referencia='CH-1')
        with company_context(empresa):
            cxc.eliminar_cobro(peticion(dueno, empresa), abono.pk)
            assert not PaymentsCtaCollect.objects.exists()
            assert CtasCollect.objects.get(pk=cuenta.pk).saldo == Decimal('23.00')
        registro = AuditLog.objects.get(action='cxc_cobro_eliminado')
        assert registro.user == dueno and registro.company == empresa
        assert registro.detail == {'cxc': cuenta.pk, 'valor': '10.00', 'fecha': HOY.isoformat(), 'medio_pago': 'cheque',
                                   'referencia': 'CH-1', 'descripcion': 'Abono de prueba'}

    def test_los_abonos_automaticos_no_se_eliminan(self, empresa, dueno, venta, sri):  # noqa: F811
        nota = nota_credito_autorizada(venta, [(leer(empresa, lambda: venta.saledetail_set.get().pk), 1)], sri=sri)
        assert nota.cxc_ajuste == 'aplicada'
        with company_context(empresa):
            abono = PaymentsCtaCollect.objects.get(tipo='nota_credito')
            with pytest.raises(cxc.ErrorCxC) as error:
                cxc.eliminar_cobro(peticion(dueno, empresa), abono.pk)
            assert error.value.codigo == 'no_es_cobro'
            with pytest.raises(ProtectedError):
                PaymentsCtaCollect.objects.get(pk=abono.pk).delete()     # la NC lo protege
            assert PaymentsCtaCollect.objects.filter(pk=abono.pk).exists()

    def test_eliminar_cxc(self, empresa, dueno, comprador, producto, venta, cuenta, sri):  # noqa: F811
        cobro = cobrar(empresa, dueno, cuenta)
        with company_context(empresa), pytest.raises(cxc.ErrorCxC) as error:
            cxc.eliminar_cxc(cuenta.pk)
        assert error.value.codigo == 'cxc_con_cobros'
        with company_context(empresa):
            cxc.eliminar_cobro(peticion(dueno, empresa), cobro.pk)
            automatico = cxc.crear_abono(cuenta, 'retencion', Decimal('1.00'), HOY, 'Retención')
            cxc.revertir_abono(automatico, timezone.now(), 'Anulada por el cliente')
            with pytest.raises(cxc.ErrorCxC) as error:
                cxc.eliminar_cxc(cuenta.pk)            # aunque esté anulado, el abono automático conserva la historia
            assert error.value.codigo == 'cxc_con_automaticos'
        otra = factura_autorizada(empresa, comprador, dueno, producto, credito=True)
        nota = nota_debito_autorizada(otra, '5.00', dueno, sri=sri)
        with company_context(empresa):
            with pytest.raises(cxc.ErrorCxC, match='es de una nota de débito'):
                cxc.eliminar_cxc(nota.cuenta_por_cobrar_id)
            libre = cxc_de(otra)
            cxc.eliminar_cxc(libre.pk)
            assert not CtasCollect.objects.filter(pk=libre.pk).exists()


class TestJson:

    def test_claves_nuevas_de_la_cxc_y_de_los_abonos(self, empresa, dueno, cuenta, venta):  # noqa: F811
        abono = cobrar(empresa, dueno, cuenta, '3.50', medio='efectivo', referencia='')
        with company_context(empresa):
            fila = CtasCollect.objects.get(pk=cuenta.pk).toJSON()
            sin_dato = PaymentsCtaCollect.objects.create(ctas_collect=cuenta, valor=Decimal('1.00'), description='legado')
            datos = [a.toJSON() for a in cxc.abonos(cuenta.pk)]
        json.dumps(fila), json.dumps(datos)                             # sin fechas ni Decimal sueltos
        assert fila['documento'] == {'tipo': 'factura', 'id': venta.pk, 'numero': venta.voucher_number_full}
        assert fila['estado'] == {'id': 'pendiente', 'name': 'Pendiente'} and fila['saldo_texto'] == '19.50'
        assert fila['saldo'] == 19.5 and fila['debt'] == 23.0                          # las claves de antes siguen en float
        assert datos[0]['tipo'] == {'id': 'cobro', 'name': 'Cobro registrado'}
        assert datos[0]['medio_pago'] == {'id': 'efectivo', 'name': 'Efectivo'} and datos[0]['valor_texto'] == '3.50'
        assert datos[0]['referencia'] == '' and datos[0]['documento'] == '' and datos[0]['anulado'] is False
        assert datos[1]['id'] == sin_dato.pk and datos[1]['medio_pago'] == {'id': '', 'name': 'Sin dato'}
        assert str(abono) == f'Abono {abono.pk} de la cuenta {cuenta.pk}'

    def test_estado_pagada_y_anulada(self, empresa, dueno, cuenta):  # noqa: F811
        cobrar(empresa, dueno, cuenta, '23.00', medio='efectivo', referencia='')
        with company_context(empresa):
            assert CtasCollect.objects.get(pk=cuenta.pk).toJSON()['estado']['id'] == 'pagada'
            assert cxc.listado().get(pk=cuenta.pk).toJSON()['estado'] == {'id': 'pagada', 'name': 'Pagada'}
            otra = CtasCollect.objects.create(sale_id=cuenta.sale_id, debt=Decimal('5.00'), saldo=Decimal('5.00'))
            cxc.crear_abono(otra, 'anulacion', Decimal('5.00'), HOY, 'Anulación')
            assert cxc.listado().get(pk=otra.pk).toJSON()['estado'] == {'id': 'anulada', 'name': 'Anulada en el SRI'}

    def test_texto_de_terceros_sin_interpretar(self, empresa, dueno, comprador, producto):  # noqa: F811
        malicioso = '<img src=x onerror=alert(1)>'
        User.objects.filter(pk=comprador.user_id).update(names=malicioso)
        venta = factura_autorizada(empresa, comprador, dueno, producto, credito=True)
        cuenta = cxc_de(venta)
        with company_context(empresa):
            cxc.registrar_cobro(empresa, dueno, cuenta.pk, HOY, '1.00', 'otro', malicioso, malicioso)
            fila = cxc.listado().get(pk=cuenta.pk).toJSON()
            abono = cxc.abonos(cuenta.pk).get().toJSON()
            nombre = CtasCollect.objects.get(pk=cuenta.pk).get_full_name()
        assert fila['sale']['client']['user']['names'] == malicioso
        assert nombre.startswith(f'{venta.voucher_number_full} · {malicioso}')
        assert abono['description'] == malicioso and abono['referencia'] == malicioso[:100]

    def test_save_respeta_update_fields(self, empresa, dueno, cuenta):  # noqa: F811
        abono = cobrar(empresa, dueno, cuenta)
        with company_context(empresa):
            abono.description, abono.referencia = 'cambiada', 'no se guarda'
            abono.save(update_fields=['description'])
            abono = PaymentsCtaCollect.objects.get(pk=abono.pk)
        assert (abono.description, abono.referencia) == ('cambiada', 'TRX-1')


class TestConsultasConstantes:

    def consultas(self, funcion):
        with CaptureQueriesContext(connection) as capturadas:
            funcion()
        return len(capturadas)

    def test_listado_y_abonos(self, empresa, dueno, comprador, producto):  # noqa: F811
        def crear(n):
            for _ in range(n):
                factura_autorizada(empresa, comprador, dueno, producto, credito=True)
        crear(2)
        with company_context(empresa):
            cuenta = CtasCollect.objects.order_by('id').first()
            for _ in range(2):
                cxc.crear_abono(cuenta, 'cobro', Decimal('0.10'), HOY, 'x', dueno, 'efectivo')
            con_2 = self.consultas(lambda: [c.toJSON() for c in cxc.listado()])
            abonos_2 = self.consultas(lambda: [a.toJSON() for a in cxc.abonos(cuenta.pk)])
        crear(10)
        with company_context(empresa):
            for _ in range(10):
                cxc.crear_abono(cuenta, 'cobro', Decimal('0.10'), HOY, 'x', dueno, 'efectivo')
            assert CtasCollect.objects.count() == 12 and cuenta.paymentsctacollect_set.count() == 12
            assert self.consultas(lambda: [c.toJSON() for c in cxc.listado()]) == con_2
            assert self.consultas(lambda: [a.toJSON() for a in cxc.abonos(cuenta.pk)]) == abonos_2


def test_rol_propietario_tiene_permiso_de_eliminar(empresa, dueno):  # noqa: F811
    assert dueno.memberships.get(company=empresa).group.name == ROLE_OWNER
    assert cxc.puede_eliminar_cobros(peticion(dueno, empresa))


# ---------------------------------------------------------------- pantallas (paso 2): vistas, permisos y planes

LISTA, NUEVO = '/pos/ctas/collect/', '/pos/ctas/collect/add/'


def entrar(client, usuario, empresa):  # noqa: F811
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    return client


class TestVistas:

    @pytest.mark.parametrize('rol', [ROLE_READONLY, ROLE_ACCOUNTANT])
    def test_delete_pay_responde_403_a_consulta_y_contador(self, client, empresa, dueno, cuenta, rol):  # noqa: F811
        abono = cobrar(empresa, dueno, cuenta)
        lector = helpers.crear_usuario(f'web.{rol.lower()}', empresa, rol)
        entrar(client, lector, empresa)
        respuesta = client.post(LISTA, {'action': 'delete_pay', 'id': abono.pk})
        assert respuesta.status_code == 403 and respuesta.json() == {'error': 'Tu perfil no puede eliminar cobros.'}
        assert client.post(LISTA, {'action': 'search', 'start_date': '', 'end_date': ''}).status_code == 200
        assert leer(empresa, lambda: PaymentsCtaCollect.objects.filter(pk=abono.pk).exists())
        assert not AuditLog.objects.filter(action='cxc_cobro_eliminado').exists()

    def test_propietario_elimina_y_no_puede_borrar_automaticos(self, client, empresa, dueno, cuenta):  # noqa: F811
        abono = cobrar(empresa, dueno, cuenta)
        with company_context(empresa):
            automatico = cxc.crear_abono(cuenta, 'retencion', Decimal('1.00'), HOY, 'Retención')
        entrar(client, dueno, empresa)
        assert client.post(LISTA, {'action': 'delete_pay', 'id': abono.pk}).json() == {}
        assert AuditLog.objects.filter(action='cxc_cobro_eliminado', user=dueno).count() == 1
        respuesta = client.post(LISTA, {'action': 'delete_pay', 'id': automatico.pk})
        assert respuesta.status_code == 200 and respuesta.json()['error'].startswith('Este abono lo generó una nota de crédito')
        assert leer(empresa, lambda: PaymentsCtaCollect.objects.filter(pk=automatico.pk).exists())

    def test_registrar_cobro_por_la_pantalla(self, client, empresa, dueno, cuenta):  # noqa: F811
        entrar(client, dueno, empresa)
        pagina = client.get(NUEVO)
        assert pagina.status_code == 200
        form = pagina.context['form']
        assert list(form.fields) == ['ctas_collect', 'date_joined', 'valor', 'medio_pago', 'referencia', 'description', 'archivo']
        assert form['medio_pago'].value() in ('', None) and form.fields['medio_pago'].required
        datos = {'action': 'add', 'ctas_collect': cuenta.pk, 'date_joined': HOY.isoformat(), 'valor': '5.25',
                 'medio_pago': '', 'referencia': '', 'description': 'Abono en ventanilla'}
        assert client.post(NUEVO, datos).json() == {'error': 'Elige el medio de pago.'}
        assert client.post(NUEVO, {**datos, 'medio_pago': 'cheque'}).json() == {
            'error': 'Escribe el número del cheque en «Referencia».'}
        assert client.post(NUEVO, {**datos, 'valor': '30'}).json() == {
            'error': 'El valor (30.00) supera el saldo de la cuenta por cobrar (23.00).'}
        assert client.post(NUEVO, {**datos, 'ctas_collect': ''}).json() == {'error': 'Elige la cuenta por cobrar.'}
        assert client.post(NUEVO, {**datos, 'medio_pago': 'deposito', 'referencia': 'DEP-77'}).json() == {}
        with company_context(empresa):
            abono = PaymentsCtaCollect.objects.get()
            assert (abono.tipo, abono.medio_pago, abono.referencia, abono.valor, abono.registrado_por) == (
                'cobro', 'deposito', 'DEP-77', Decimal('5.25'), dueno)
            assert CtasCollect.objects.get(pk=cuenta.pk).saldo == Decimal('17.75')

    def test_search_ctas_collect_excluye_anuladas_y_saldadas(self, client, empresa, dueno, comprador, producto, cuenta,
                                                            venta):  # noqa: F811
        otra = cxc_de(factura_autorizada(empresa, comprador, dueno, producto, credito=True))
        saldada = cxc_de(factura_autorizada(empresa, comprador, dueno, producto, credito=True))
        with company_context(empresa):
            cxc.crear_abono(otra, 'anulacion', Decimal('23.00'), HOY, 'Anulación')
        cobrar(empresa, dueno, saldada, '23.00', medio='efectivo', referencia='')
        entrar(client, dueno, empresa)
        filas = client.post(NUEVO, {'action': 'search_ctas_collect', 'term': comprador.dni[:6]}).json()
        assert [f['id'] for f in filas] == [cuenta.pk]
        assert filas[0]['text'].startswith(venta.voucher_number_full) and filas[0]['saldo_texto'] == '23.00'
        por_numero = client.post(NUEVO, {'action': 'search_ctas_collect', 'term': venta.voucher_number_full}).json()
        assert [f['id'] for f in por_numero] == [cuenta.pk]

    def test_eliminar_cxc_con_cobros_por_la_pantalla(self, client, empresa, dueno, cuenta):  # noqa: F811
        cobrar(empresa, dueno, cuenta)
        entrar(client, dueno, empresa)
        respuesta = client.post(f'{LISTA}delete/{cuenta.pk}/')
        assert respuesta.json() == {'error': 'Esta cuenta por cobrar tiene cobros registrados: elimínalos antes de eliminarla.'}
        assert leer(empresa, lambda: CtasCollect.objects.filter(pk=cuenta.pk).exists())

    def test_json_sin_interpretar(self, client, empresa, dueno, comprador, producto):  # noqa: F811
        malicioso = '<img src=x onerror=alert(1)>'
        User.objects.filter(pk=comprador.user_id).update(names=malicioso)
        cuenta = cxc_de(factura_autorizada(empresa, comprador, dueno, producto, credito=True))
        cobrar(empresa, dueno, cuenta, '1.00', medio='otro', referencia=malicioso)
        with company_context(empresa):
            PaymentsCtaCollect.objects.update(description=malicioso)
        entrar(client, dueno, empresa)
        filas = client.post(LISTA, {'action': 'search', 'start_date': '', 'end_date': ''}).json()
        abonos = client.post(LISTA, {'action': 'search_pays', 'id': cuenta.pk}).json()
        assert filas[0]['sale']['client']['user']['names'] == malicioso          # tal cual: lo escapa el JS
        assert abonos[0]['description'] == malicioso and abonos[0]['referencia'] == malicioso
        assert abonos[0]['index'] == 1 and abonos[0]['tipo']['id'] == 'cobro' and abonos[0]['valor_texto'] == '1.00'

    def test_consultas_constantes_por_la_pantalla(self, client, empresa, dueno, comprador, producto):  # noqa: F811
        def crear(n):
            for _ in range(n):
                cuenta = cxc_de(factura_autorizada(empresa, comprador, dueno, producto, credito=True))
                cobrar(empresa, dueno, cuenta, '0.10', medio='efectivo', referencia='')

        def contar(datos):
            with CaptureQueriesContext(connection) as capturadas:
                assert client.post(LISTA, datos).status_code == 200
            return len(capturadas)
        entrar(client, dueno, empresa)
        crear(2)
        primera = leer(empresa, lambda: CtasCollect.objects.order_by('id').first())
        busqueda = {'action': 'search', 'start_date': '', 'end_date': ''}
        con_2, abonos_1 = contar(busqueda), contar({'action': 'search_pays', 'id': primera.pk})
        crear(10)
        for _ in range(11):
            cobrar(empresa, dueno, primera, '0.10', medio='efectivo', referencia='')
        assert contar(busqueda) == con_2
        assert contar({'action': 'search_pays', 'id': primera.pk}) == abonos_1


class TestPlanes:

    def test_plan_vencido_solo_consulta(self, client, empresa, dueno, cuenta):  # noqa: F811
        from core.suscripciones.models import SubscriptionPeriod
        abono = cobrar(empresa, dueno, cuenta)
        SubscriptionPeriod.objects.filter(company=empresa).update(ends_at=timezone.now() - timedelta(days=1))
        entrar(client, dueno, empresa)
        assert client.get(LISTA).status_code == 200
        assert client.post(LISTA, {'action': 'search', 'start_date': '', 'end_date': ''}).status_code == 200
        assert client.post(LISTA, {'action': 'search_pays', 'id': cuenta.pk}).status_code == 200
        assert client.get(NUEVO).status_code == 302
        datos = {'action': 'add', 'ctas_collect': cuenta.pk, 'date_joined': HOY.isoformat(), 'valor': '1.00',
                 'medio_pago': 'efectivo', 'referencia': '', 'description': ''}
        assert client.post(NUEVO, datos).status_code == 403
        assert client.post(LISTA, {'action': 'delete_pay', 'id': abono.pk}).status_code == 403
        assert leer(empresa, lambda: PaymentsCtaCollect.objects.count()) == 1

    def test_plan_gratuito_bloqueado(self, client):
        gratuita = helpers.crear_empresa('GRATUITA CXC', plan=None)
        propietario = helpers.crear_usuario('dueno.gratuita.cxc', gratuita)
        entrar(client, propietario, gratuita)
        respuesta = client.get(LISTA)
        assert respuesta.status_code == 302 and respuesta['Location'] == '/suscripcion/'
        assert client.post(LISTA, {'action': 'search', 'start_date': '', 'end_date': ''}).status_code == 403
