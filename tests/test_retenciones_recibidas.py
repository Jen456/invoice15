"""Retenciones recibidas de clientes (Etapa 2, O2), servicio core/comprobantes/retenciones_recibidas.py: registro manual
con abono a la cuenta por cobrar, cada validación con su código, advertencias, catálogo por pareja y fecha, clave de
acceso, duplicados (también la IntegrityError en un savepoint), anulación, puente del 07 importado (todo o nada,
idempotente, con los dobles de recibidos de O1), totales para los formularios y seguridad por filas en PostgreSQL; y sus
pantallas: flujo revisar → registrar → anular, opciones del catálogo por pareja y fecha, permisos por rol, 404 de otra
empresa, planes (gratuito, vencido y cupo agotado) y consultas constantes del listado."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import DatabaseError, connection, transaction
from django.db.models import ProtectedError
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.comprobantes import retenciones as catalogo
from core.comprobantes import retenciones_recibidas as rr
from core.comprobantes.models import CodigoRetencion, RetencionRecibida, RetencionRecibidaDetalle
from core.importacion.models import DocumentoImportado
from core.pos import cxc
from core.pos.clientes import consumidor_final
from core.pos.models import CtasCollect, PaymentsCtaCollect, Receipt, Sale
from core.suscripciones.models import SubscriptionPeriod
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog
from tests import helpers
from tests.ayudas_ventas import (RUC_AGENTE, clave_acceso_ficticia, cxc_de, documento_07, factura_autorizada, linea,
                                 recibidos_falsos, retencion_datos, retencion_leida, sustento)
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, producto, sri  # noqa: F401

pytestmark = pytest.mark.django_db
HOY = timezone.localdate()


@pytest.fixture
def venta(empresa, comprador, dueno, producto):  # noqa: F811
    """Factura a crédito de ayer: subtotal 20,00, IVA 3,00, total 23,00."""
    return factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=HOY - timedelta(days=1))


def registrar(empresa, usuario, venta, datos=None, **extra):
    with company_context(empresa), transaction.atomic():
        return rr.registrar(empresa, usuario, venta, datos or retencion_datos(), **extra)


def calcular(empresa, venta, datos=None, origen='manual'):
    with company_context(empresa):
        return rr.calcular(Sale.objects.get(pk=venta.pk), datos or retencion_datos(), origen)


def codigo_de(funcion):
    with pytest.raises(rr.ErrorRetencionRecibida) as error:
        funcion()
    return error.value.codigo, str(error.value)


def cuenta(empresa, venta):
    return leer(empresa, lambda: CtasCollect.objects.get(pk=cxc_de(venta).pk))


class TestRegistroManual:

    def test_renta_e_iva_con_abono(self, empresa, dueno, venta, sri):  # noqa: F811
        usados = SubscriptionPeriod.objects.get(company=empresa, status='activa').documents_used
        ret = registrar(empresa, dueno, venta, retencion_datos(notas='  Recibida  por correo '))
        with company_context(empresa):
            ret = RetencionRecibida.objects.get(pk=ret.pk)
            detalles = list(ret.detalles.values_list('impuesto', 'codigo', 'concepto', 'base_imponible', 'porcentaje',
                                                     'valor_retenido'))
            abono = PaymentsCtaCollect.objects.get(pk=ret.abono_id)
        assert (ret.estado, ret.origen, ret.verificacion, ret.cxc_estado) == ('registrada', 'manual', 'sin_verificar', 'aplicada')
        assert (ret.total_renta, ret.total_iva, ret.total_retenido) == (Decimal('0.40'), Decimal('0.90'), Decimal('1.30'))
        assert (ret.numero, ret.establecimiento, ret.punto_emision, ret.secuencial) == ('001-001-000000123', '001', '001', '000000123')
        assert (ret.emisor_identificacion, ret.cliente_id, ret.periodo_fiscal) == (RUC_AGENTE, venta.client_id, f'{HOY:%m/%Y}')
        assert ret.num_doc_sustento == venta.voucher_number_full.replace('-', '') and ret.fecha_doc_sustento == venta.emission_date
        assert ret.notas == 'Recibida por correo' and ret.clave_acceso == '' and ret.autorizacion == '1234567890'
        assert detalles == [('1', '312', CodigoRetencion.objects.get(impuesto='1', codigo='312').concepto, Decimal('20.00'),
                             Decimal('2.00'), Decimal('0.40')),
                            ('2', '1', CodigoRetencion.objects.get(impuesto='2', codigo='1').concepto, Decimal('3.00'),
                             Decimal('30.00'), Decimal('0.90'))]
        assert (abono.tipo, abono.valor, abono.referencia, abono.date_joined) == ('retencion', Decimal('1.30'), ret.numero, HOY)
        assert abono.description == 'Retención 001-001-000000123' and cuenta(empresa, venta).saldo == Decimal('21.70')
        assert [a['codigo'] for a in ret.advertencias] == ['sin_verificar']
        registro = AuditLog.objects.get(action='retencion_recibida_registro')
        assert registro.detail == {'id': ret.pk, 'numero': ret.numero, 'venta': venta.pk, 'total': '1.30', 'origen': 'manual',
                                   'documento': None} and registro.user == dueno
        # Sin SRI, sin correo y sin cupo
        assert sri.recepciones == [] and sri.consultas == [] and mail.outbox == []
        assert SubscriptionPeriod.objects.get(company=empresa, status='activa').documents_used == usados

    def test_venta_de_contado_sin_cxc(self, empresa, dueno, comprador, producto):  # noqa: F811
        contado = factura_autorizada(empresa, comprador, dueno, producto, fecha=HOY - timedelta(days=1))
        ret = registrar(empresa, dueno, contado)
        assert ret.cxc_estado == 'sin_cxc' and ret.abono_id is None
        assert not leer(empresa, lambda: PaymentsCtaCollect.objects.exists())

    def test_cxc_saldada_y_excedente(self, empresa, dueno, venta):  # noqa: F811
        with company_context(empresa):
            cxc.registrar_cobro(empresa, dueno, cxc_de(venta).pk, HOY, '22.00', 'efectivo')
        resultado = calcular(empresa, venta)
        assert (resultado['cxc_estado'], resultado['abono_previsto'], resultado['excedente']) == ('parcial', Decimal('1.00'),
                                                                                                 Decimal('0.30'))
        assert {'codigo': 'excedente_cxc', 'texto': 'La retención supera el saldo de la cuenta por cobrar en 0.30: no se abona '
                                                    'ese excedente.'} in resultado['advertencias']
        ret = registrar(empresa, dueno, venta)
        assert ret.cxc_estado == 'parcial' and ret.abono.valor == Decimal('1.00') and cuenta(empresa, venta).saldo == 0

    def test_cxc_ya_saldada(self, empresa, dueno, venta):  # noqa: F811
        with company_context(empresa):
            cxc.registrar_cobro(empresa, dueno, cxc_de(venta).pk, HOY, '23.00', 'efectivo')
        ret = registrar(empresa, dueno, venta)
        assert ret.cxc_estado == 'sin_saldo' and ret.abono_id is None and cuenta(empresa, venta).saldo == 0

    def test_resumen_de_calcular(self, empresa, venta):  # noqa: F811
        r = calcular(empresa, venta)
        assert r['doc']['numero'] == '001-001-000000123' and r['doc']['emisor_ruc'] == RUC_AGENTE
        assert r['lineas'][0] == {'impuesto': '1', 'codigo': '312', 'concepto': CodigoRetencion.objects.get(
            impuesto='1', codigo='312').concepto, 'base_imponible': Decimal('20.00'), 'porcentaje': Decimal('2.00'),
            'valor_retenido': Decimal('0.40')}
        assert r['topes'] == {'renta': Decimal('20.00'), 'iva': Decimal('3.00'), 'usado_renta': Decimal('0.00'),
                              'usado_iva': Decimal('0.00')}
        assert (r['total_retenido'], r['abono_previsto'], r['cxc_estado']) == (Decimal('1.30'), Decimal('1.30'), 'aplicada')
        assert not leer(empresa, lambda: RetencionRecibida.objects.exists())        # calcular no guarda nada


class TestValidaciones:

    @pytest.mark.parametrize('cambios, codigo', [
        ({'emisor_ruc': '123'}, 'ruc_emisor'),
        ({'emisor_ruc': '0990000001001'}, 'ruc_no_coincide'),
        ({'numero': '001-001-12'}, 'numero'),
        ({'numero': '000-001-000000123'}, 'numero'),
        ({'numero': '001-001-000000000'}, 'numero'),
        ({'autorizacion': '123'}, 'autorizacion'),
        ({'fecha_emision': HOY + timedelta(days=1)}, 'fecha_futura'),
        ({'fecha_emision': HOY - timedelta(days=2)}, 'fecha_anterior'),
        ({'lineas': []}, 'sin_lineas'),
        ({'lineas': [linea('1', c, '1.00') for c in ('303', '304', '307', '309', '310', '311', '312', '319', '320', '322', '323')]},
         'max_lineas'),
        ({'lineas': [linea('6', '4580', '20.00')]}, 'impuesto_no_soportado'),
        ({'lineas': [linea('1', '312', '10.00'), linea('1', '312', '5.00')]}, 'repetido'),
        ({'lineas': [linea('1', '99999', '10.00')]}, 'codigo'),
        ({'lineas': [linea('2', '312', '1.00')]}, 'codigo'),               # el código es por pareja (impuesto, código)
        ({'lineas': [linea('1', '312', '0')]}, 'base_cero'),
        ({'lineas': [linea('1', '312', '10.00', porcentaje='150')]}, 'porcentaje'),
        ({'lineas': [linea('1', '312', '10.00', valor='5.00')]}, 'valor_no_coincide'),
        ({'lineas': [linea('1', '312', '20.02')]}, 'base_renta_excede'),
        ({'lineas': [linea('2', '1', '3.02')]}, 'base_iva_excede'),
    ])
    def test_cada_error_con_su_codigo(self, empresa, venta, cambios, codigo):  # noqa: F811
        obtenido, texto = codigo_de(lambda: calcular(empresa, venta, retencion_datos(**cambios)))
        mensaje = rr.MENSAJES[codigo].split('{')[0]
        assert obtenido == codigo and texto.startswith(mensaje), texto

    def test_topes_suman_las_retenciones_registradas(self, empresa, dueno, venta):  # noqa: F811
        """Revisión O2-T3 (§3.2.7): los topes cuentan las bases de las otras retenciones registradas de la factura, y se
        liberan al anular."""
        primera = registrar(empresa, dueno, venta, retencion_datos(lineas=[linea('1', '312', '15.00'), linea('2', '1', '2.00')]))
        otra = {'numero': '001-001-000000124'}
        assert codigo_de(lambda: calcular(empresa, venta, retencion_datos(lineas=[linea('1', '312', '10.00')], **otra))) == (
            'base_renta_excede', 'Las bases de renta (25.00) superan el subtotal sin impuestos de la factura (20.00), sumando '
                                 'otras retenciones registradas.')
        assert codigo_de(lambda: calcular(empresa, venta, retencion_datos(lineas=[linea('2', '1', '1.50')], **otra))) == (
            'base_iva_excede', 'Las bases de IVA (3.50) superan el IVA de la factura (3.00), sumando otras retenciones '
                               'registradas.')
        justo = calcular(empresa, venta, retencion_datos(lineas=[linea('1', '312', '5.00'), linea('2', '1', '1.00')], **otra))
        assert justo['topes'] == {'renta': Decimal('20.00'), 'iva': Decimal('3.00'), 'usado_renta': Decimal('15.00'),
                                  'usado_iva': Decimal('2.00')}
        with company_context(empresa):
            rr.anular(empresa, dueno, RetencionRecibida.objects.get(pk=primera.pk), 'Registrada por error en la prueba')
        libre = calcular(empresa, venta, retencion_datos(lineas=[linea('1', '312', '20.00'), linea('2', '1', '3.00')], **otra))
        assert (libre['topes']['usado_renta'], libre['topes']['usado_iva']) == (Decimal('0.00'), Decimal('0.00'))

    def test_tolerancias(self, empresa, venta):  # noqa: F811
        r = calcular(empresa, venta, retencion_datos(lineas=[linea('1', '312', '20.01', valor='0.41'), linea('2', '1', '3.01')]))
        assert r['total_renta'] == Decimal('0.41') and r['total_iva'] == Decimal('0.90')

    def test_textos_con_datos(self, empresa, venta):  # noqa: F811
        assert codigo_de(lambda: calcular(empresa, venta, retencion_datos(emisor_ruc='0990000001001'))) == (
            'ruc_no_coincide', f'El RUC 0990000001001 del agente de retención no es el del cliente de la factura ({RUC_AGENTE}).')
        assert codigo_de(lambda: calcular(empresa, venta, retencion_datos(lineas=[linea('1', '312', '10.00', valor='5.00')])))[1] \
            == 'El valor retenido del código 312 (5.00) no coincide con base × porcentaje (0.20).'
        assert codigo_de(lambda: calcular(empresa, venta, retencion_datos(fecha_emision=HOY - timedelta(days=2))))[1] == \
            f'La retención no puede ser anterior a la factura ({venta.emission_date:%d/%m/%Y}).'
        assert codigo_de(lambda: calcular(empresa, venta, retencion_datos(lineas=[linea('6', '4580', '1')])))[1] == \
            'El sistema todavía no registra retenciones de ISD (código 6).'

    def test_factura(self, empresa, dueno, comprador, producto, venta):  # noqa: F811
        ticket = factura_autorizada(empresa, comprador, dueno, producto, tipo='08', fecha=HOY - timedelta(days=1))
        assert codigo_de(lambda: calcular(empresa, ticket))[0] == 'no_es_factura'
        en_proceso = factura_autorizada(empresa, comprador, dueno, producto, estado='in_process', fecha=HOY - timedelta(days=1))
        assert codigo_de(lambda: calcular(empresa, en_proceso))[0] == 'factura_no_autorizada'
        cubierta = factura_autorizada(empresa, comprador, dueno, producto, estado='canceled', fecha=HOY - timedelta(days=1))
        assert calcular(empresa, cubierta)['total_retenido'] == Decimal('1.30')       # 'canceled' sigue siendo válida
        leer(empresa, lambda: Sale.objects.filter(pk=venta.pk).update(anulado_sri_fecha=HOY))
        assert codigo_de(lambda: calcular(empresa, venta)) == ('factura_anulada',
                                                              f'La factura {venta.voucher_number_full} está anulada en el SRI.')
        with company_context(empresa):
            cf = consumidor_final(empresa)
        final = factura_autorizada(empresa, cf, dueno, producto, fecha=HOY - timedelta(days=1))
        assert codigo_de(lambda: calcular(empresa, final))[0] == 'consumidor_final'

    def test_cliente_con_cedula(self, empresa, dueno, producto):  # noqa: F811
        cliente = helpers.crear_cliente('cliente.cedula', empresa, '0912345675', '0990000003')
        venta = factura_autorizada(empresa, cliente, dueno, producto, credito=True, fecha=HOY - timedelta(days=1))
        assert codigo_de(lambda: calcular(empresa, venta))[0] == 'ruc_emisor'
        assert codigo_de(lambda: calcular(empresa, venta, retencion_datos(emisor_ruc='0990000001001')))[0] == 'ruc_no_coincide'
        ret = registrar(empresa, dueno, venta, retencion_datos(emisor_ruc='0912345675001'))
        assert ret.emisor_identificacion == '0912345675001' and {
            'codigo': 'ruc_de_cedula', 'texto': 'El agente de retención usa el RUC 0912345675001; la factura se emitió con su '
                                                'cédula 0912345675.'} in ret.advertencias

    def test_advertencias(self, empresa, dueno, comprador, producto):  # noqa: F811
        vieja = factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=HOY - timedelta(days=10))
        r = calcular(empresa, vieja, retencion_datos(lineas=[linea('1', '312', '20.00', porcentaje='1.75')]))
        codigos = {a['codigo']: a['texto'] for a in r['advertencias']}
        assert codigos['porcentaje_catalogo'] == ('El código 312 tiene 2 % en el catálogo vigente y la retención usa 1.75 %. '
                                                  'Revisa el comprobante del cliente.')
        assert codigos['plazo_5_dias'] == 'La retención se emitió 10 días después de la factura (la ley da 5 días).'
        assert r['total_renta'] == Decimal('0.35')
        # El 310 es de porcentaje variable: otro porcentaje no es advertencia
        r = calcular(empresa, vieja, retencion_datos(lineas=[linea('1', '310', '20.00', porcentaje='1.50')]))
        assert 'porcentaje_catalogo' not in {a['codigo'] for a in r['advertencias']}

    def test_codigo_inactivo_del_catalogo_aceptado(self, empresa, dueno, venta):  # noqa: F811
        assert not CodigoRetencion.objects.get(impuesto='1', codigo='340').activo
        ret = registrar(empresa, dueno, venta, retencion_datos(lineas=[linea('1', '340', '10.00')]))
        assert leer(empresa, lambda: list(ret.detalles.values_list('codigo', 'porcentaje', 'valor_retenido'))) == [
            ('340', Decimal('3.00'), Decimal('0.30'))]

    def test_catalogo_por_pareja_y_fecha_de_emision(self, empresa, venta, monkeypatch):  # noqa: F811
        llamadas, original = [], catalogo.codigo_retencion_vigente

        def espia(impuesto, codigo, fecha, incluir_inactivos=False):
            llamadas.append((impuesto, codigo, fecha, incluir_inactivos))
            return original(impuesto, codigo, fecha, incluir_inactivos=incluir_inactivos)
        monkeypatch.setattr(catalogo, 'codigo_retencion_vigente', espia)
        calcular(empresa, venta, retencion_datos(fecha_emision=HOY))
        assert llamadas == [('1', '312', HOY, True), ('2', '1', HOY, True)]

    def test_clave_de_acceso(self, empresa, dueno, venta):  # noqa: F811
        def clave(**cambios):
            datos = dict(fecha=HOY, cod_doc='07', ruc=RUC_AGENTE, ambiente=2, estab='001', pto='001', sec='000000123')
            datos.update(cambios)
            return clave_acceso_ficticia(**datos)
        casos = [({'cod_doc': '01'}, 'clave_tipo'), ({'ruc': '0990000001001'}, 'clave_ruc'), ({'sec': '000000124'}, 'clave_numero'),
                 ({'fecha': HOY - timedelta(days=1)}, 'clave_fecha'), ({'ambiente': 1}, 'clave_ambiente')]
        for cambios, codigo in casos:
            assert codigo_de(lambda: calcular(empresa, venta, retencion_datos(autorizacion=clave(**cambios))))[0] == codigo
        mala = clave()[:-1] + str((int(clave()[-1]) + 1) % 10)
        assert codigo_de(lambda: calcular(empresa, venta, retencion_datos(autorizacion=mala))) == (
            'clave_invalida', 'La clave de acceso no es válida: El dígito verificador de la clave de acceso no coincide.')
        assert codigo_de(lambda: calcular(empresa, venta, retencion_datos(autorizacion=clave(ambiente=1))))[1] == \
            'La clave de acceso es del ambiente PRUEBAS; la factura es de PRODUCCIÓN.'
        ret = registrar(empresa, dueno, venta, retencion_datos(autorizacion=clave()))
        assert ret.clave_acceso == ret.autorizacion == clave()


class TestDuplicadosYAnulacion:

    def test_duplicada_y_de_nuevo_tras_anular(self, empresa, dueno, venta):  # noqa: F811
        primera = registrar(empresa, dueno, venta)
        assert codigo_de(lambda: registrar(empresa, dueno, venta, retencion_datos(numero='001001000000123'))) == (
            'duplicada', f'Ya registraste la retención 001-001-000000123 de {primera.emisor_razon_social} sobre esta factura.')
        with company_context(empresa):
            anulada = rr.anular(empresa, dueno, primera, '  Registrada por error  en otra factura ')
        assert (anulada.estado, anulada.cxc_estado, anulada.anulado_sri_fecha) == ('anulada', 'revertida', HOY)
        assert anulada.anulado_sri_motivo == 'Registrada por error en otra factura' and anulada.anulado_sri_por == dueno
        assert cuenta(empresa, venta).saldo == Decimal('23.00')
        with company_context(empresa):
            abono = PaymentsCtaCollect.objects.get(pk=primera.abono_id)
        assert abono.anulado_en is not None and 'Registrada por error' in abono.anulado_motivo
        registro = AuditLog.objects.get(action='retencion_recibida_anulacion')
        assert registro.detail == {'id': primera.pk, 'numero': primera.numero, 'motivo': 'Registrada por error en otra factura',
                                   'abono_revertido': '1.30', 'documento_desmarcado': False}
        segunda = registrar(empresa, dueno, venta)                                  # las restricciones son condicionales
        assert segunda.pk != primera.pk and cuenta(empresa, venta).saldo == Decimal('21.70')

    def test_anular_errores(self, empresa, dueno, venta):  # noqa: F811
        ret = registrar(empresa, dueno, venta)
        with company_context(empresa):
            assert codigo_de(lambda: rr.anular(empresa, dueno, ret, 'corto'))[0] == 'motivo'
            rr.anular(empresa, dueno, ret, 'El cliente la anuló en el SRI')
            assert codigo_de(lambda: rr.anular(empresa, dueno, ret, 'El cliente la anuló en el SRI')) == (
                'ya_anulada', 'Esta retención ya está anulada.')

    def test_integrity_error_en_savepoint_no_aborta_la_transaccion(self, empresa, dueno, venta, monkeypatch):  # noqa: F811
        pequena = retencion_datos(lineas=[linea('1', '312', '5.00')])
        registrar(empresa, dueno, venta, pequena)
        monkeypatch.setattr(rr, '_duplicada_existe', lambda doc, v: False)     # como si otra petición la registrara a la vez
        with company_context(empresa), transaction.atomic():
            with pytest.raises(rr.ErrorRetencionRecibida) as error:
                rr.registrar(empresa, dueno, venta, pequena)
            assert error.value.codigo == 'duplicada'
            assert RetencionRecibida.objects.count() == 1          # la transacción exterior sigue usable (PostgreSQL)
            assert PaymentsCtaCollect.objects.filter(tipo='retencion').count() == 1

    def test_restricciones_de_la_base(self, empresa, dueno, venta):  # noqa: F811
        ret = registrar(empresa, dueno, venta)
        with company_context(empresa):
            with pytest.raises(Exception), transaction.atomic():
                RetencionRecibidaDetalle.objects.create(retencion=ret, impuesto='1', codigo='312', base_imponible=0,
                                                        porcentaje=2, valor_retenido=0)
            with pytest.raises(Exception), transaction.atomic():
                RetencionRecibida.objects.filter(pk=ret.pk).update(total_retenido=Decimal('-1'))


class TestBuscarVenta:

    def test_con_y_sin_guiones_y_por_ambiente(self, empresa, dueno, comprador, producto, venta):  # noqa: F811
        with company_context(empresa):
            assert rr.buscar_venta_sustento(venta.voucher_number_full.replace('-', ''), 2).pk == venta.pk
            assert rr.buscar_venta_sustento(venta.voucher_number_full, 2).pk == venta.pk
            assert rr.buscar_venta_sustento(venta.voucher_number_full, 1) is None
            assert rr.buscar_venta_sustento('123', 2) is None
            otra = Receipt.objects.create(voucher_type='01', environment_type=2, establishment_code='001',
                                          issuing_point_code='003', sequence=0)
            gemela = Sale(client=comprador, receipt=otra, employee=dueno, voucher_number='000000999',
                          voucher_number_full=venta.voucher_number_full, environment_type=2, status='authorized')
            gemela.save()
            assert rr._buscar_venta(venta.voucher_number_full, 2) == (None, 'sustento_ambiguo')


class TestPuenteDel07:

    @pytest.fixture
    def ventas(self, empresa, comprador, dueno, producto):  # noqa: F811
        return [factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=HOY - timedelta(days=1))
                for _ in range(2)]

    @pytest.fixture
    def documento(self, empresa, dueno):  # noqa: F811
        return documento_07(empresa, dueno)

    def registrar_07(self, empresa, dueno, documento, leida):
        with company_context(empresa):
            return rr.registrar_desde_importacion(empresa, dueno, documento, leida)

    def conteos(self, empresa):
        return leer(empresa, lambda: (RetencionRecibida.objects.count(), RetencionRecibidaDetalle.objects.count(),
                                      PaymentsCtaCollect.objects.count(), AuditLog.objects.count()))

    def test_dos_sustentos_dos_retenciones_y_una_marca(self, empresa, dueno, ventas, documento, monkeypatch):  # noqa: F811
        llamadas = recibidos_falsos(monkeypatch)
        leida = retencion_leida(documento, [sustento(v) for v in ventas])
        rets = self.registrar_07(empresa, dueno, documento, leida)
        assert [r.venta_id for r in rets] == [v.pk for v in ventas]
        assert all((r.origen, r.verificacion, r.documento_importado_id, r.clave_acceso, r.cxc_estado)
                   == ('importado', 'verificada_sri', documento.pk, documento.clave_acceso, 'aplicada') for r in rets)
        assert llamadas == [('marcar', documento.pk, f'Retenciones recibidas #{rets[0].pk}, #{rets[1].pk}')]
        assert [cuenta(empresa, v).saldo for v in ventas] == [Decimal('21.70')] * 2
        assert AuditLog.objects.filter(action='retencion_recibida_registro', detail__documento=documento.pk).count() == 2
        # Repetir: las mismas filas y ningún abono nuevo
        otra_vez = self.registrar_07(empresa, dueno, documento, leida)
        assert [r.pk for r in otra_vez] == [r.pk for r in rets]
        assert leer(empresa, lambda: PaymentsCtaCollect.objects.filter(tipo='retencion').count()) == 2

    def test_dos_sustentos_de_la_misma_factura_rechazan_el_documento(self, empresa, dueno, ventas, documento,
                                                                     monkeypatch):  # noqa: F811
        """Revisión O2-T1: renta en un docSustento e IVA en otro, de la misma factura. Antes se guardaba solo el primero
        (se perdían los 0,90 de IVA) y el documento quedaba incorporado."""
        llamadas = recibidos_falsos(monkeypatch)
        from core.importacion.recibidos import RetencionLineaLeida
        renta = sustento(ventas[0], lineas=(RetencionLineaLeida('1', '312', Decimal('20.00'), Decimal('2.00'), Decimal('0.40')),))
        iva = sustento(ventas[0], lineas=(RetencionLineaLeida('2', '1', Decimal('3.00'), Decimal('30.00'), Decimal('0.90')),))
        leida = retencion_leida(documento, [renta, sustento(ventas[1]), iva])
        texto = (f'La factura {ventas[0].voucher_number_full} aparece en varios sustentos de esta retención: regístrala a '
                 'mano con todas sus líneas.')
        with company_context(empresa):
            revision = rr.revisar_importacion(empresa, documento, leida)
        assert revision['puede_registrar'] is False
        assert [s['error'] for s in revision['sustentos']] == [
            {'codigo': 'sustento_repetido', 'texto': texto}, None, {'codigo': 'sustento_repetido', 'texto': texto}]
        antes = self.conteos(empresa)
        with company_context(empresa), pytest.raises(rr.ErrorRetencionRecibida) as error:
            rr.registrar_desde_importacion(empresa, dueno, documento, leida)
        numero = ventas[0].voucher_number_full
        assert (error.value.codigo, error.value.sustento, str(error.value)) == ('sustento_repetido', numero,
                                                                                f'Sustento {numero}: {texto}')
        assert self.conteos(empresa) == antes and llamadas == []          # nada a medias y el documento no se incorpora

    def test_declarada_en_archivo(self, empresa, dueno, ventas, documento, monkeypatch):  # noqa: F811
        recibidos_falsos(monkeypatch)
        rets = self.registrar_07(empresa, dueno, documento, retencion_leida(documento, [sustento(ventas[0])], verificado_sri=False))
        assert rets[0].verificacion == 'declarada_en_archivo'

    def test_un_sustento_sin_venta_no_registra_nada(self, empresa, dueno, ventas, documento, monkeypatch):  # noqa: F811
        llamadas = recibidos_falsos(monkeypatch)
        antes = self.conteos(empresa)
        leida = retencion_leida(documento, [sustento(ventas[0]), sustento(ventas[1], numero='001-002-000999999')])
        with pytest.raises(rr.ErrorRetencionRecibida) as error:
            self.registrar_07(empresa, dueno, documento, leida)
        assert str(error.value) == ('Sustento 001-002-000999999: No hay una factura 001-002-000999999 emitida por la empresa en el '
                                    'ambiente PRODUCCIÓN.')
        assert error.value.codigo == 'sustento_no_encontrado' and error.value.sustento == '001-002-000999999'
        assert self.conteos(empresa) == antes and llamadas == []

    def test_error_de_calculo_en_el_segundo_sustento_deshace_todo(self, empresa, dueno, ventas, documento, monkeypatch):  # noqa: F811
        recibidos_falsos(monkeypatch)
        antes = self.conteos(empresa)
        excesiva = sustento(ventas[1], lineas=[recibidos_linea('1', '312', '25.00', '2.00', '0.50')])
        with pytest.raises(rr.ErrorRetencionRecibida, match=f'^Sustento {ventas[1].voucher_number_full}: Las bases de renta'):
            self.registrar_07(empresa, dueno, documento, retencion_leida(documento, [sustento(ventas[0]), excesiva]))
        assert self.conteos(empresa) == antes

    def test_isd_rechaza_el_documento(self, empresa, dueno, ventas, documento, monkeypatch):  # noqa: F811
        recibidos_falsos(monkeypatch)
        antes = self.conteos(empresa)
        leida = retencion_leida(documento, [sustento(ventas[0])], isd=True)
        with pytest.raises(rr.ErrorRetencionRecibida) as error:
            self.registrar_07(empresa, dueno, documento, leida)
        assert error.value.codigo == 'impuesto_no_soportado'
        assert str(error.value) == ('El sistema todavía no registra retenciones de ISD (código 6): registra a mano la parte de '
                                    'renta e IVA.')
        assert self.conteos(empresa) == antes
        with company_context(empresa):
            revision = rr.revisar_importacion(empresa, documento, leida)
        assert revision['puede_registrar'] is False and revision['errores_documento'][0]['codigo'] == 'impuesto_no_soportado'

    def test_errores_de_documento(self, empresa, dueno, ventas, documento, monkeypatch):  # noqa: F811
        recibidos_falsos(monkeypatch)
        leida = retencion_leida(documento, [sustento(ventas[0])])
        otro = documento_07(empresa, dueno, sec='000000777')
        assert codigo_de(lambda: self.registrar_07(empresa, dueno, otro, leida)) == (
            'documento_no_corresponde', 'Los datos leídos no corresponden a este documento.')
        leer(empresa, lambda: DocumentoImportado.objects.filter(pk=documento.pk).update(estado_revision='descartado'))
        assert codigo_de(lambda: self.registrar_07(empresa, dueno, documento, leida))[0] == 'documento_descartado'
        leer(empresa, lambda: DocumentoImportado.objects.filter(pk=documento.pk).update(estado_revision='aprobado', cod_doc='01'))
        assert codigo_de(lambda: self.registrar_07(empresa, dueno, documento, leida)) == (
            'no_es_retencion', 'Este documento no es un comprobante de retención.')
        leer(empresa, lambda: DocumentoImportado.objects.filter(pk=documento.pk).update(cod_doc='07'))
        nc = sustento(ventas[0], cod_doc='04')
        assert codigo_de(lambda: self.registrar_07(empresa, dueno, documento, retencion_leida(documento, [nc]))) == (
            'sustento_no_factura', f'Sustento {ventas[0].voucher_number_full}: El documento sustento '
                                   f'{ventas[0].voucher_number_full} no es una factura.')

    def test_revisar_no_escribe_nada(self, empresa, dueno, ventas, documento, monkeypatch):  # noqa: F811
        recibidos_falsos(monkeypatch)
        leida = retencion_leida(documento, [sustento(ventas[0]), sustento(ventas[1], numero='001-002-000999999')])
        antes = self.conteos(empresa)
        with company_context(empresa):
            revision = rr.revisar_importacion(empresa, documento, leida)
        assert self.conteos(empresa) == antes
        assert (revision['documento_id'], revision['numero'], revision['agente_ruc'], revision['ambiente'],
                revision['verificacion'], revision['puede_registrar']) == (documento.pk, '001-001-000000123', RUC_AGENTE, 2,
                                                                           'verificada_sri', False)
        primero, segundo = revision['sustentos']
        assert (primero['venta_id'], primero['venta_numero'], primero['error'], primero['ya_registrada_id']) == (
            ventas[0].pk, ventas[0].voucher_number_full, None, None)
        assert primero['resultado']['total_retenido'] == Decimal('1.30') and 'doc' not in primero['resultado']
        assert segundo['venta_id'] is None and segundo['error']['codigo'] == 'sustento_no_encontrado'
        leida = retencion_leida(documento, [sustento(ventas[0])])
        self.registrar_07(empresa, dueno, documento, leida)
        with company_context(empresa):
            revision = rr.revisar_importacion(empresa, documento, leida)
        assert revision['puede_registrar'] is True and revision['sustentos'][0]['ya_registrada_id'] is not None

    def test_anular_la_ultima_desmarca_el_documento(self, empresa, dueno, ventas, documento, monkeypatch):  # noqa: F811
        llamadas = recibidos_falsos(monkeypatch)
        rets = self.registrar_07(empresa, dueno, documento, retencion_leida(documento, [sustento(v) for v in ventas]))
        with company_context(empresa):
            rr.anular(empresa, dueno, rets[0], 'El cliente anuló la retención')
            assert [ll[0] for ll in llamadas] == ['marcar']
            rr.anular(empresa, dueno, rets[1], 'El cliente anuló la retención')
        assert llamadas[1:] == [('desmarcar', documento.pk, 'El cliente anuló la retención')]
        assert AuditLog.objects.filter(action='retencion_recibida_anulacion').order_by('id').last().detail['documento_desmarcado']

    def test_el_documento_con_retenciones_no_se_borra(self, empresa, dueno, ventas, documento, monkeypatch):  # noqa: F811
        recibidos_falsos(monkeypatch)
        ret = self.registrar_07(empresa, dueno, documento, retencion_leida(documento, [sustento(ventas[0])]))[0]
        with company_context(empresa):
            rr.anular(empresa, dueno, ret, 'El cliente anuló la retención')
            with pytest.raises(ProtectedError):
                DocumentoImportado.objects.get(pk=documento.pk).delete()      # también si la retención está anulada

    def test_registrada_a_mano_antes_es_duplicada(self, empresa, dueno, ventas, documento, monkeypatch):  # noqa: F811
        recibidos_falsos(monkeypatch)
        registrar(empresa, dueno, ventas[0])
        with pytest.raises(rr.ErrorRetencionRecibida, match='^Sustento .*: Ya registraste la retención 001-001-000000123'):
            self.registrar_07(empresa, dueno, documento, retencion_leida(documento, [sustento(ventas[0])]))


def recibidos_linea(impuesto, codigo, base, porcentaje, valor):
    from core.importacion.recibidos import RetencionLineaLeida
    return RetencionLineaLeida(impuesto, codigo, Decimal(base), Decimal(porcentaje), Decimal(valor))


class TestTotalesParaFormularios:

    def test_excluye_anuladas_pruebas_y_fuera_de_rango(self, empresa, dueno, comprador, producto, venta):  # noqa: F811
        vigente = registrar(empresa, dueno, venta)
        anulable = factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=HOY - timedelta(days=1))
        anulada = registrar(empresa, dueno, anulable)
        with company_context(empresa):
            rr.anular(empresa, dueno, anulada, 'Registrada por error')
        pruebas = factura_autorizada(empresa, comprador, dueno, producto, ambiente=1, fecha=HOY - timedelta(days=1))
        registrar(empresa, dueno, pruebas)
        vieja = factura_autorizada(empresa, comprador, dueno, producto, fecha=HOY - timedelta(days=40))
        registrar(empresa, dueno, vieja, retencion_datos(fecha_emision=HOY - timedelta(days=35)))
        with company_context(empresa):
            totales = rr.totales_para_formularios(HOY - timedelta(days=10), HOY)
            assert list(rr.del_periodo(HOY - timedelta(days=10), HOY)) == [vigente]
        assert totales == {'iva': Decimal('0.90'), 'renta': Decimal('0.40'), 'por_cliente': {
            RUC_AGENTE: {'iva': Decimal('0.90'), 'renta': Decimal('0.40'), 'cliente_id': comprador.pk}}}


@pytest.mark.skipif(connection.vendor != 'postgresql', reason='La seguridad por filas es de PostgreSQL')
class TestSeguridadPorFilas:

    def test_solo_ve_su_empresa_y_no_inserta_en_otra(self, empresa, dueno, venta):  # noqa: F811
        registrar(empresa, dueno, venta)
        empresa_b = helpers.crear_empresa('EMPRESA B RETENCIONES', environment_type=2)
        dueno_b = helpers.crear_usuario('dueno.b.retenciones', empresa_b)
        cliente_b = helpers.crear_cliente('cliente.b.retenciones', empresa_b, RUC_AGENTE, '0990000004')
        producto_b = helpers.crear_producto(empresa_b, 'B-1')
        venta_b = factura_autorizada(empresa_b, cliente_b, dueno_b, producto_b, credito=True, fecha=HOY - timedelta(days=1))
        ret_b = registrar(empresa_b, dueno_b, venta_b, retencion_datos(lineas=[linea('1', '312', '20.00')]))

        def contar(tabla):
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT count(*) FROM {tabla}')   # sin filtro de empresa a propósito
                return cursor.fetchone()[0]
        with company_context(empresa):
            assert contar('comprobantes_retencionrecibida') == 1 and contar('comprobantes_retencionrecibidadetalle') == 2
            with pytest.raises(DatabaseError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('INSERT INTO comprobantes_retencionrecibidadetalle (company_id, retencion_id, impuesto, codigo, '
                                   'concepto, base_imponible, porcentaje, valor_retenido) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
                                   [empresa_b.id, ret_b.pk, '1', '312', 'Intrusa', 1, 2, 0.02])
        with company_context(empresa_b):
            assert contar('comprobantes_retencionrecibida') == 1 and contar('comprobantes_retencionrecibidadetalle') == 1
        with connection.cursor() as cursor:
            cursor.execute("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname IN "
                           "('comprobantes_retencionrecibida', 'comprobantes_retencionrecibidadetalle') ORDER BY relname")
            assert cursor.fetchall() == [('comprobantes_retencionrecibida', True, True),
                                         ('comprobantes_retencionrecibidadetalle', True, True)]


# ---------------------------------------------------------------- pantallas (paso 2): vistas, formulario, permisos y planes

LISTA = '/comprobantes/retenciones-recibidas/'
BUSCAR = '/comprobantes/retenciones-recibidas/add/'


def nueva(venta):
    return f'/comprobantes/retenciones-recibidas/add/{venta.pk}/'


def ficha(ret):
    return f'/comprobantes/retenciones-recibidas/{ret.pk}/'


def entrar(client, usuario, empresa):  # noqa: F811
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    return client


def formulario(numero='001-001-000000123', fecha=None, lineas=(('1:312', '20.00'), ('2:1', '3.00')), action='calcular', **extra):
    """POST del formulario de registro manual (3 filas extra en el formset, como en la pantalla sin JavaScript)."""
    datos = {'action': action, 'numero': numero, 'autorizacion': '1234567890', 'fecha_emision': (fecha or HOY).isoformat(),
             'notas': '', 'lineas-TOTAL_FORMS': '3', 'lineas-INITIAL_FORMS': '0', 'lineas-MIN_NUM_FORMS': '0',
             'lineas-MAX_NUM_FORMS': '10'}
    for i in range(3):
        codigo, base = lineas[i] if i < len(lineas) else ('', '')
        datos.update({f'lineas-{i}-codigo': codigo, f'lineas-{i}-base_imponible': base, f'lineas-{i}-porcentaje': '',
                      f'lineas-{i}-valor_retenido': ''})
    datos.update(extra)
    return datos


class TestPantallas:

    def test_flujo_completo_sin_sri_ni_correo(self, client, empresa, dueno, venta, sri):  # noqa: F811
        entrar(client, dueno, empresa)
        assert client.get(LISTA).status_code == 200
        buscar = client.get(BUSCAR)
        assert buscar.status_code == 200 and [v.pk for v in buscar.context['ventas']] == [venta.pk]
        assert buscar.context['ventas'][0].saldo == Decimal('23.00')
        assert [v.pk for v in client.get(BUSCAR, {'q': venta.voucher_number_full.replace('-', '')}).context['ventas']] == [venta.pk]
        pagina = client.get(nueva(venta))
        assert pagina.status_code == 200 and pagina.context['impedimento'] is None
        assert len(pagina.context['lineas'].forms) == 3 and pagina.context['pide_emisor_ruc'] is False
        assert 'emisor_ruc' not in pagina.context['form'].fields
        assert pagina.context['topes'] == {'renta': Decimal('20.00'), 'iva': Decimal('3.00'), 'usado_renta': Decimal('0.00'),
                                           'usado_iva': Decimal('0.00')}
        revisada = client.post(nueva(venta), formulario())
        assert revisada.status_code == 200 and revisada.context['resumen']['total_retenido'] == Decimal('1.30')
        assert revisada.context['resumen']['abono_previsto'] == Decimal('1.30')
        assert not leer(empresa, lambda: RetencionRecibida.objects.exists())             # revisar no guarda
        registrada = client.post(nueva(venta), formulario(action='registrar'))
        ret = leer(empresa, lambda: RetencionRecibida.objects.get())
        assert registrada.status_code == 302 and registrada['Location'] == ficha(ret)
        pagina = client.get(ficha(ret))
        assert pagina.status_code == 200 and pagina.context['puede_anular'] is True
        assert 'Retención 001-001-000000123 registrada: se abonaron $1.30 a la cuenta por cobrar.' in pagina.content.decode()
        repetida = client.post(nueva(venta), formulario(action='registrar'))
        nombre = leer(empresa, lambda: Sale.objects.select_related('client__user').get(pk=venta.pk).client.user.names)
        assert repetida.status_code == 200 and repetida.context['form'].non_field_errors() == [
            f'Ya registraste la retención 001-001-000000123 de {nombre} sobre esta factura.']
        corto = client.post(ficha(ret), {'action': 'anular', 'motivo': 'corto'})
        assert corto.status_code == 200 and 'Escribe el motivo (al menos 10 caracteres).' in corto.content.decode()
        anulada = client.post(ficha(ret), {'action': 'anular', 'motivo': 'El cliente la anuló en el SRI'}, follow=True)
        assert anulada.status_code == 200
        assert 'Retención 001-001-000000123 anulada: se revirtió su abono de $1.30 en la cuenta por cobrar.' in anulada.content.decode()
        assert leer(empresa, lambda: RetencionRecibida.objects.get().estado) == 'anulada'
        assert cuenta(empresa, venta).saldo == Decimal('23.00')
        assert (sri.recepciones, sri.consultas, mail.outbox) == ([], [], [])

    def test_errores_en_el_formulario_y_venta_de_contado(self, client, empresa, dueno, comprador, producto, venta):  # noqa: F811
        entrar(client, dueno, empresa)
        sin_lineas = client.post(nueva(venta), formulario(lineas=()))
        assert sin_lineas.context['form'].non_field_errors() == ['Agrega al menos una retención (renta o IVA).']
        sin_codigo = client.post(nueva(venta), formulario(lineas=(('', '5.00'),)))
        assert sin_codigo.context['lineas'].forms[0].errors['codigo'] == ['Elige el código de la retención de esta línea.']
        contado = factura_autorizada(empresa, comprador, dueno, producto, fecha=HOY - timedelta(days=1))
        respuesta = client.post(nueva(contado), formulario(action='registrar'), follow=True)
        assert ('Retención 001-001-000000123 registrada. La venta fue de contado: la retención no abona ninguna cuenta por '
                'cobrar.') in respuesta.content.decode()

    def test_impedimento_y_cliente_con_cedula(self, client, empresa, dueno, producto):  # noqa: F811
        with company_context(empresa):
            cf = consumidor_final(empresa)
        final = factura_autorizada(empresa, cf, dueno, producto, fecha=HOY - timedelta(days=1))
        cliente = helpers.crear_cliente('cedula.pantalla', empresa, '0912345675', '0990000005')
        con_cedula = factura_autorizada(empresa, cliente, dueno, producto, credito=True, fecha=HOY - timedelta(days=1))
        entrar(client, dueno, empresa)
        pagina = client.get(nueva(final))
        assert pagina.context['impedimento'] == 'Una factura a consumidor final no admite retención: el comprador no está identificado.'
        assert 'value="calcular"' not in pagina.content.decode() and 'value="registrar"' not in pagina.content.decode()
        assert final.pk not in [v.pk for v in client.get(BUSCAR, {'q': final.voucher_number_full}).context['ventas']]
        pagina = client.get(nueva(con_cedula))
        assert pagina.context['pide_emisor_ruc'] is True and 'emisor_ruc' in pagina.context['form'].fields
        respuesta = client.post(nueva(con_cedula), formulario(action='registrar', emisor_ruc='0912345675001'))
        assert respuesta.status_code == 302
        assert leer(empresa, lambda: RetencionRecibida.objects.get(venta=con_cedula).emisor_identificacion) == '0912345675001'

    def test_listado_filtra_y_suma_las_registradas(self, client, empresa, dueno, comprador, producto, venta):  # noqa: F811
        registrar(empresa, dueno, venta)
        otra = factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=HOY - timedelta(days=1))
        segunda = registrar(empresa, dueno, otra, retencion_datos(numero='001-001-000000124'))
        with company_context(empresa):
            rr.anular(empresa, dueno, segunda, 'Registrada por error')
        entrar(client, dueno, empresa)
        pagina = client.get(LISTA)
        assert [r.numero for r in pagina.context['retenciones']] == ['001-001-000000123']
        assert pagina.context['totales'] == {'renta': Decimal('0.40'), 'iva': Decimal('0.90'), 'total': Decimal('1.30')}
        assert pagina.context['puede_registrar'] is True
        todas = client.get(LISTA, {'estado': 'todas'}).context['retenciones']
        assert sorted(r.numero for r in todas) == ['001-001-000000123', '001-001-000000124']
        assert [r.numero for r in client.get(LISTA, {'estado': 'anulada'}).context['retenciones']] == ['001-001-000000124']
        assert [r.numero for r in client.get(LISTA, {'estado': 'todas', 'q': '001001000000124'}).context['retenciones']] == [
            '001-001-000000124']
        manana = (HOY + timedelta(days=1)).isoformat()
        assert list(client.get(LISTA, {'desde': manana, 'hasta': manana}).context['retenciones']) == []

    def test_consultas_constantes_del_listado(self, client, empresa, dueno, venta):  # noqa: F811
        def crear(desde, hasta):
            for n in range(desde, hasta):
                registrar(empresa, dueno, venta, retencion_datos(numero=f'001-001-{n:09d}', lineas=[linea('1', '312', '1.00')]))

        def contar():
            with CaptureQueriesContext(connection) as capturadas:
                assert client.get(LISTA).status_code == 200
            return len(capturadas)
        entrar(client, dueno, empresa)
        crear(1, 3)
        con_2 = contar()
        crear(3, 13)
        assert leer(empresa, lambda: RetencionRecibida.objects.count()) == 12
        assert contar() == con_2


class TestOpcionesDelCatalogo:

    def test_una_opcion_por_pareja_con_la_vigencia_de_la_fecha(self, monkeypatch):
        """Doble de codigos_retencion_vigentes con dos vigencias del 310 (como tras D0): una sola opción, la de la fecha."""
        from types import SimpleNamespace

        from core.comprobantes import forms_recibidas
        antes, despues = date(2026, 1, 1), date(2026, 6, 1)
        filas = {
            'vieja': SimpleNamespace(impuesto='1', codigo='310', concepto='Transporte privado de pasajeros',
                                     porcentaje=Decimal('1.00'), activo=True),
            'nueva': SimpleNamespace(impuesto='1', codigo='310', concepto='Transporte privado de pasajeros',
                                     porcentaje=Decimal('2.00'), activo=True),
            'iva': SimpleNamespace(impuesto='2', codigo='1', concepto='IVA 30 %', porcentaje=Decimal('30.00'), activo=False),
        }
        llamadas = []

        def doble(fecha, incluir_inactivos=False):
            llamadas.append((fecha, incluir_inactivos))
            return [filas['vieja'] if fecha < despues else filas['nueva'], filas['iva']]
        monkeypatch.setattr(catalogo, 'codigos_retencion_vigentes', doble)
        assert forms_recibidas.LineaRecibidaForm(fecha=antes).fields['codigo'].choices == [
            ('', '— Sin retención en esta línea —'), ('1:310', 'Renta · 310 · Transporte privado de pasajeros (1 %)'),
            ('2:1', 'IVA · 1 · 30 % (no disponible para emitir)')]
        opciones = forms_recibidas.LineaRecibidaForm(fecha=despues).fields['codigo'].choices
        assert [o for o in opciones if o[0] == '1:310'] == [('1:310', 'Renta · 310 · Transporte privado de pasajeros (2 %)')]
        assert llamadas == [(antes, True), (despues, True)]
        # Aunque la función devolviera las dos filas de la pareja, el formulario no repite la opción.
        monkeypatch.setattr(catalogo, 'codigos_retencion_vigentes', lambda fecha, incluir_inactivos=False: [
            filas['nueva'], filas['vieja']])
        assert forms_recibidas.LineaRecibidaForm(fecha=despues).fields['codigo'].choices[1:] == [
            ('1:310', 'Renta · 310 · Transporte privado de pasajeros (2 %)')]

    def test_la_pantalla_arma_las_opciones_con_la_fecha_escrita(self, client, empresa, dueno, venta, monkeypatch):  # noqa: F811
        fechas, original = [], catalogo.codigos_retencion_vigentes

        def espia(fecha, incluir_inactivos=False):
            fechas.append((fecha, incluir_inactivos))
            return original(fecha, incluir_inactivos=incluir_inactivos)
        monkeypatch.setattr(catalogo, 'codigos_retencion_vigentes', espia)
        entrar(client, dueno, empresa)
        client.get(nueva(venta))
        assert set(fechas) == {(HOY, True)}
        fechas.clear()
        client.post(nueva(venta), formulario(fecha=HOY - timedelta(days=1)))
        assert set(fechas) == {(HOY - timedelta(days=1), True)}
        opciones = dict(client.get(nueva(venta)).context['lineas'].forms[0].fields['codigo'].choices)
        assert opciones['1:340'].endswith('(no disponible para emitir)')            # el cliente puede usar códigos inactivos


class TestPermisosYPlanes:

    @pytest.mark.parametrize('rol', [ROLE_OWNER, ROLE_ADMIN])
    def test_propietario_y_administrador_registran(self, client, empresa, dueno, venta, rol):  # noqa: F811
        usuario = dueno if rol == ROLE_OWNER else helpers.crear_usuario('admin.retenciones', empresa, rol)
        entrar(client, usuario, empresa)
        assert client.get(BUSCAR).status_code == 200 and client.get(nueva(venta)).status_code == 200
        assert client.post(nueva(venta), formulario(action='registrar')).status_code == 302

    @pytest.mark.parametrize('rol', [ROLE_ACCOUNTANT, ROLE_READONLY])
    def test_contador_y_consulta_solo_ven(self, client, empresa, dueno, venta, rol):  # noqa: F811
        ret = registrar(empresa, dueno, venta)
        lector = helpers.crear_usuario(f'lector.rr.{rol.lower()}', empresa, rol)
        entrar(client, lector, empresa)
        pagina = client.get(LISTA)
        assert pagina.status_code == 200 and pagina.context['puede_registrar'] is False
        assert client.get(ficha(ret)).context['puede_anular'] is False
        assert client.get(BUSCAR).status_code == 302 and client.get(nueva(venta)).status_code == 302
        assert client.post(nueva(venta), formulario(action='registrar', numero='001-001-000000555')).status_code == 403
        negado = client.post(ficha(ret), {'action': 'anular', 'motivo': 'Intento sin permiso de anular'})
        assert negado.status_code == 403 and 'Tu perfil no puede realizar esta acción.' in negado.content.decode()
        assert leer(empresa, lambda: RetencionRecibida.objects.get().estado) == 'registrada'
        assert leer(empresa, lambda: RetencionRecibida.objects.count()) == 1

    def test_vendedor_no_entra(self, client, empresa, venta):  # noqa: F811
        vendedor = helpers.crear_usuario('vendedor.retenciones', empresa, ROLE_SELLER)
        entrar(client, vendedor, empresa)
        assert client.get(LISTA).status_code == 302 and client.get(BUSCAR).status_code == 302

    def test_otra_empresa_responde_404(self, client, empresa, dueno, venta):  # noqa: F811
        empresa_b = helpers.crear_empresa('EMPRESA B PANTALLA', environment_type=2)
        dueno_b = helpers.crear_usuario('dueno.b.pantalla', empresa_b)
        cliente_b = helpers.crear_cliente('cliente.b.pantalla', empresa_b, RUC_AGENTE, '0990000006')
        venta_b = factura_autorizada(empresa_b, cliente_b, dueno_b, helpers.crear_producto(empresa_b, 'B-2'), credito=True,
                                     fecha=HOY - timedelta(days=1))
        ret_b = registrar(empresa_b, dueno_b, venta_b)
        entrar(client, dueno, empresa)
        assert client.get(nueva(venta_b)).status_code == 404 and client.get(ficha(ret_b)).status_code == 404
        assert client.post(nueva(venta_b), formulario(action='registrar')).status_code == 404
        assert client.post(ficha(ret_b), {'action': 'anular', 'motivo': 'De otra empresa, no se toca'}).status_code == 404
        assert list(client.get(LISTA).context['retenciones']) == []
        assert leer(empresa_b, lambda: RetencionRecibida.objects.get().estado) == 'registrada'

    def test_plan_gratuito_bloqueado(self, client):
        gratuita = helpers.crear_empresa('GRATUITA RETENCIONES', plan=None)
        entrar(client, helpers.crear_usuario('dueno.gratuita.rr', gratuita), gratuita)
        assert client.get(LISTA)['Location'] == '/suscripcion/' and client.get(BUSCAR).status_code == 302

    def test_plan_vencido_solo_consulta(self, client, empresa, dueno, venta):  # noqa: F811
        ret = registrar(empresa, dueno, venta)
        SubscriptionPeriod.objects.filter(company=empresa).update(ends_at=timezone.now() - timedelta(days=1))
        entrar(client, dueno, empresa)
        assert client.get(LISTA).status_code == 200 and client.get(ficha(ret)).status_code == 200
        assert client.get(BUSCAR).status_code == 302 and client.get(nueva(venta)).status_code == 302
        for datos in (formulario(), formulario(action='registrar', numero='001-001-000000777')):
            assert client.post(nueva(venta), datos).status_code == 403
        assert client.post(ficha(ret), {'action': 'anular', 'motivo': 'Intento con el plan vencido'}).status_code == 403
        assert leer(empresa, lambda: (RetencionRecibida.objects.count(), RetencionRecibida.objects.get().estado)) == (1, 'registrada')

    def test_cupo_agotado_registra_sin_consumir_cupo(self, client, empresa, dueno, venta, sri):  # noqa: F811
        from core.suscripciones.servicios import estado_empresa
        SubscriptionPeriod.objects.filter(company=empresa).update(document_limit=5, documents_used=5)
        assert estado_empresa(empresa).codigo == 'cupo_agotado'
        entrar(client, dueno, empresa)
        assert client.post(nueva(venta), formulario(action='registrar')).status_code == 302
        periodo = SubscriptionPeriod.objects.get(company=empresa, status='activa')
        assert (periodo.documents_used, periodo.documents_reserved) == (5, 0) and sri.recepciones == []
