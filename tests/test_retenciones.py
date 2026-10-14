"""Comprobante de retención (07, XML 2.0.0) desde Compras: cálculo y validaciones en el servidor, XML válido contra
el XSD oficial del SRI, numeración en «Otros comprobantes», emisión en dos fases, cupo, permisos y correo."""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone
from lxml import etree

from core.comprobantes import retenciones as sv
from core.comprobantes.models import CodigoRetencion, Retencion
from core.configuracion import servicios as cfg
from core.pos import emision
from core.pos.models import Provider, Purchase, Receipt
from core.suscripciones.models import SubscriptionPeriod
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_OWNER, ROLE_SELLER
from tests import helpers
from tests.test_emision_sri import SRIFalso
from tests.test_firma_sri import CLAVE, generar_p12

pytestmark = pytest.mark.django_db
XSD = Path(__file__).parent / 'xsd' / 'retencion' / 'ComprobanteRetencion_V2.0.0.xsd'
LISTA = '/comprobantes/retenciones/'


def leer(empresa, consulta):
    with company_context(empresa):
        return consulta()


@pytest.fixture(scope='module')
def p12():
    return generar_p12()[0]


@pytest.fixture
def codigos(db):
    """Códigos del catálogo que carga la migración 0004."""
    def codigo(impuesto, numero):
        return CodigoRetencion.objects.get(impuesto=impuesto, codigo=numero, activo=True)
    return {'bienes': codigo('1', '312'), 'honorarios': codigo('1', '303'), 'variable': codigo('1', '346'),
            'iva30': codigo('2', '1'), 'iva100': codigo('2', '3')}


@pytest.fixture
def empresa(settings, p12):
    settings.FPA_RUC_PROVEEDOR = '0941609729001'
    empresa = helpers.crear_empresa('RETENEDORA', plan='plan-1000', environment_type=2)
    helpers.configurar_facturacion(empresa, estab='001', punto='002', ambiente=2)
    empresa.electronic_signature.save('firma.p12', ContentFile(p12), save=False)
    empresa.electronic_signature_key = CLAVE
    empresa.save()
    return empresa


@pytest.fixture
def numeracion(empresa):
    """Numeración de retenciones confirmada en «Otros comprobantes»: continúa desde la 40 de otro sistema."""
    with company_context(empresa):
        return cfg.configurar_otro_documento(empresa, '07', 'otro_sistema', '001-002-000000040', True)


@pytest.fixture
def compra(empresa):
    with company_context(empresa):
        proveedor = Provider.objects.create(name="FERRETERÍA D'LUJO S.A.", ruc='0990000001001', mobile='0990000000',
                                            email='compras@proveedor.example', address='Av. Quito 100')
        return Purchase.objects.create(number='123', provider=proveedor, subtotal=Decimal('100.00'))


@pytest.fixture
def sri(monkeypatch):
    falso = SRIFalso()
    monkeypatch.setattr(emision, '_cliente', falso)
    monkeypatch.setattr(emision, 'ESPERAS_AL_EMITIR', (0, 0, 0))
    monkeypatch.setattr(emision, 'ESPERAS_AL_CONSULTAR', (0,))
    return falso


@pytest.fixture
def web(client, empresa):
    helpers.iniciar_sesion(client, helpers.crear_usuario('dueno.retenedora', empresa, ROLE_OWNER), empresa=empresa)
    return client


DATOS = {'num_doc_sustento': '001-001-000000123', 'aut_doc_sustento': '1' * 49, 'base_0': '0', 'base_iva': '100.00',
         'tarifa_iva': '15.00', 'valor_iva': '', 'cod_sustento': '01', 'forma_pago': '20'}


def datos(**cambios):
    base = dict(DATOS, fecha_doc_sustento=timezone.localdate() - timedelta(days=1))
    base.update(cambios)
    return base


def formulario(codigos_lineas, **cambios):
    """POST del formulario: documento sustento + líneas [(código, base, %)]."""
    post = {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in datos(**cambios).items()}
    post.update({'lineas-TOTAL_FORMS': '3', 'lineas-INITIAL_FORMS': '0', 'lineas-MIN_NUM_FORMS': '0', 'lineas-MAX_NUM_FORMS': '10'})
    for i, (codigo, base, pct) in enumerate(codigos_lineas):
        post.update({f'lineas-{i}-codigo': codigo.pk, f'lineas-{i}-base': base, f'lineas-{i}-porcentaje': pct})
    return post


class TestCatalogo:

    def test_porcentajes_vigentes_desde_marzo_2026(self, db):
        vigentes = {c.codigo: c.porcentaje for c in CodigoRetencion.objects.filter(impuesto='1', activo=True)}
        assert vigentes['312'] == Decimal('2.00') and vigentes['3440'] == Decimal('3.00') and vigentes['303A'] == Decimal('5.00')
        assert vigentes['343B'] == Decimal('2.00') and vigentes['312A'] == Decimal('1.00') and vigentes['332'] == Decimal('0.00')
        assert '345' not in vigentes and '344' not in vigentes and not any(c.startswith('5') for c in vigentes)
        assert not CodigoRetencion.objects.get(impuesto='1', codigo='327').activo   # dividendos: falta el nodo <dividendos>
        iva = dict(CodigoRetencion.objects.filter(impuesto='2', activo=True).values_list('codigo', 'porcentaje'))
        assert iva == {'9': Decimal('10.00'), '10': Decimal('20.00'), '1': Decimal('30.00'), '2': Decimal('70.00'),
                       '3': Decimal('100.00'), '8': Decimal('0.00')}


class TestCalculo:

    def test_renta_sobre_la_base_e_iva_sobre_el_iva(self, codigos):
        doc, detalle, total = sv.calcular(datos(), [(codigos['bienes'].pk, None, None), (codigos['iva30'].pk, None, None)])
        assert doc['valor_iva'] == Decimal('15.00') and doc['num_doc_sustento'] == '001001000000123'
        assert [(d['codigo'], d['base_imponible'], d['valor_retenido']) for d in detalle] == [
            ('312', Decimal('100.00'), Decimal('2.00')), ('1', Decimal('15.00'), Decimal('4.50'))]
        assert total == Decimal('6.50')

    def test_redondeo_y_porcentaje_variable(self, codigos):
        _, detalle, _ = sv.calcular(datos(base_iva='33.33'), [(codigos['variable'].pk, None, '2.00'), (codigos['honorarios'].pk, '10.05', '99')])
        assert detalle[0]['porcentaje'] == Decimal('2.00') and detalle[0]['valor_retenido'] == Decimal('0.67')
        assert detalle[1]['porcentaje'] == Decimal('10.00')   # el % de un código fijo no se puede cambiar
        assert detalle[1]['valor_retenido'] == Decimal('1.01')   # 10.05 × 10 % = 1.005 → 1.01 (HALF_UP)

    @pytest.mark.parametrize('cambios, lineas, mensaje', [
        ({'num_doc_sustento': '001-001-123'}, ['bienes'], 'número de la factura'),
        ({'aut_doc_sustento': '123'}, ['bienes'], 'autorización'),
        ({'fecha_doc_sustento': timezone.localdate() + timedelta(days=1)}, ['bienes'], 'no puede ser futura'),
        ({}, [], 'al menos una retención'),
        ({}, ['bienes', 'bienes'], 'está repetido'),
        ({'base_iva': '0', 'base_0': '50'}, ['iva30'], 'la factura no tiene IVA'),
    ])
    def test_validaciones(self, codigos, cambios, lineas, mensaje):
        with pytest.raises(sv.ErrorRetencion, match=mensaje):
            sv.calcular(datos(**cambios), [(codigos[n].pk, None, None) for n in lineas])

    def test_base_mayor_que_la_factura(self, codigos):
        with pytest.raises(sv.ErrorRetencion, match='supera la base sin impuestos'):
            sv.calcular(datos(), [(codigos['bienes'].pk, '100.01', None)])


class TestNumeracion:

    def test_sin_numeracion_explica_donde_configurarla(self, web, compra, codigos, sri):
        respuesta = web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario([(codigos['bienes'], '', '')]), 'action': 'emitir'})
        assert 'Otros comprobantes' in respuesta.content.decode() and not leer(compra.company, lambda: Retencion.objects.exists())

    def test_configuracion_enlaza_otros_comprobantes(self, web, empresa):
        assert 'href="/configuracion/facturacion/otros/"' in web.get('/configuracion/facturacion/', follow=True).content.decode()

    def test_otros_comprobantes_configura_y_confirma(self, web, empresa):
        from core.pos.models import BillingSetup
        antes = leer(empresa, lambda: BillingSetup.objects.get())
        pagina = web.get('/configuracion/facturacion/otros/').content.decode()
        assert 'Comprobante de retención' in pagina
        web.post('/configuracion/facturacion/otros/', {'tipo': '07', '07-mode': 'otro_sistema', '07-last_number': '40', '07-confirm': 'on'})
        r = leer(empresa, lambda: Receipt.objects.get(voucher_type='07', environment_type=2))
        assert r.confirmed_at and r.next_number_full() == '001-002-000000041'
        # La retención es opcional: no reabre el paso 5 del asistente ya confirmado.
        despues = leer(empresa, lambda: BillingSetup.objects.get())
        assert despues.completed_at == antes.completed_at and 5 in despues.completed_steps


class TestEmision:

    def test_revisar_no_guarda_y_emitir_autoriza(self, web, empresa, compra, codigos, numeracion, sri):
        lineas = [(codigos['bienes'], '', ''), (codigos['iva30'], '', '')]
        revision = web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario(lineas), 'action': 'calcular'}).content.decode()
        assert 'Revisa antes de emitir' in revision and '$6,50' in revision and not leer(empresa, lambda: Retencion.objects.exists())
        sri.respuestas_autorizacion = ['AUTORIZADO']
        respuesta = web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario(lineas), 'action': 'emitir'}, follow=True)
        ret = leer(empresa, lambda: Retencion.objects.get())
        assert ret.voucher_number_full == '001-002-000000041' and ret.status == 'authorized_and_sent_by_email'
        assert ret.total_retenido == Decimal('6.50') and 'autorizado por el SRI' in respuesta.content.decode()
        assert '<codDoc>07</codDoc>' in ret.xml_signed and '<campoAdicional nombre="RUC Proveedor">0941609729001</campoAdicional>' in ret.xml_signed
        assert "FERRETERÍA D'LUJO S.A." in ret.xml_signed and ret.xml_authorized and ret.pdf_authorized
        assert SubscriptionPeriod.objects.get(company=empresa, status='activa').documents_used == 1   # cuenta 1 del cupo
        assert mail.outbox[0].to == ['compras@proveedor.example'] and len(mail.outbox[0].attachments) == 2

    def test_xml_firmado_valido_contra_el_xsd_oficial(self, empresa, compra, codigos, numeracion):
        empresa.retention_agent, empresa.special_taxpayer = 'SI', '12345'
        empresa.save()
        with company_context(empresa):
            from django.db import transaction
            with transaction.atomic():
                ret = sv.crear(empresa, helpers.crear_usuario('firmante.ret', empresa), compra, datos(base_0='20.00'),
                               [(codigos['bienes'].pk, None, None), (codigos['iva100'].pk, None, None)])
                emision.preparar(ret)
            ret.refresh_from_db()
        parser = etree.XMLParser(no_network=True, load_dtd=True, resolve_entities=True)
        esquema = etree.XMLSchema(etree.parse(str(XSD), parser))
        documento = etree.fromstring(ret.xml_signed.encode())
        assert esquema.validate(documento), [str(e) for e in esquema.error_log]
        assert documento.findtext('infoCompRetencion/periodoFiscal') == f'{timezone.localdate():%m/%Y}'
        assert [i.findtext('codigoPorcentaje') for i in documento.iter('impuestoDocSustento')] == ['0', '4']
        assert documento.findtext('infoTributaria/agenteRetencion') == '1'
        assert documento.findtext('infoCompRetencion/contribuyenteEspecial') == '12345'

    def test_una_retencion_por_compra(self, web, empresa, compra, codigos, numeracion, sri):
        lineas = [(codigos['bienes'], '', '')]
        web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario(lineas), 'action': 'emitir'})   # queda en proceso
        respuesta = web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario(lineas), 'action': 'emitir'})
        html = respuesta.content.decode()
        assert 'ya tiene la retención' in html and '001-002-000000041' in html
        assert leer(empresa, lambda: Retencion.objects.count()) == 1

    def test_en_proceso_no_se_borra_y_la_tarea_la_autoriza(self, web, empresa, compra, codigos, numeracion, sri):
        web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario([(codigos['bienes'], '', '')]), 'action': 'emitir'})
        ret = leer(empresa, lambda: Retencion.objects.get())
        assert ret.status == 'in_process'
        web.post(LISTA, {'action': 'delete', 'id': ret.pk})
        assert leer(empresa, lambda: Retencion.objects.filter(pk=ret.pk).exists())
        sri.respuestas_autorizacion = ['AUTORIZADO']
        call_command('consultar_sri')
        assert leer(empresa, lambda: Retencion.objects.get(pk=ret.pk).status) in emision.AUTORIZADOS

    def test_numero_usado_no_se_repite(self, empresa, compra, codigos, numeracion):
        with company_context(empresa):
            r = Receipt.objects.get(voucher_type='07', environment_type=2)
            Retencion.objects.create(company=empresa, receipt=r, voucher_number='000000041', voucher_number_full='001-002-000000041',
                                     employee=helpers.crear_usuario('otro.ret', empresa), environment_type=2, purchase=compra,
                                     provider=compra.provider, tipo_identificacion='04', identificacion='0990000001001',
                                     razon_social='X', num_doc_sustento='001001000000999', fecha_doc_sustento=timezone.localdate(),
                                     aut_doc_sustento='1' * 49)
            Receipt.objects.filter(pk=r.pk).update(sequence=40)   # aunque la secuencia quedara atrás
            assert r.is_used and r.max_used() == 41 and Receipt.objects.get(pk=r.pk).reservar_numero() == '000000042'


class TestPermisos:

    def test_contador_consulta_pero_no_emite_y_vendedor_no_entra(self, client, empresa, compra):
        helpers.iniciar_sesion(client, helpers.crear_usuario('contador.ret', empresa, ROLE_ACCOUNTANT), empresa=empresa)
        assert client.get(LISTA).status_code == 200
        assert client.get(f'{LISTA}nueva/{compra.pk}/').status_code in (302, 403)
        client.logout()
        helpers.iniciar_sesion(client, helpers.crear_usuario('vendedor.ret', empresa, ROLE_SELLER), empresa=empresa)
        assert client.get(LISTA).status_code in (302, 403)

    def test_otra_empresa_no_ve_ni_usa_la_compra(self, client, compra):
        otra = helpers.crear_empresa('AJENA', plan='ilimitado')
        helpers.iniciar_sesion(client, helpers.crear_usuario('dueno.ajena', otra, ROLE_OWNER), empresa=otra)
        assert client.get(f'{LISTA}nueva/{compra.pk}/').status_code == 404
