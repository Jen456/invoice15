"""Nota de débito (05, XML 1.0.0) sobre una factura autorizada: cálculo y reglas en el servidor, XML válido contra el XSD
oficial del SRI, numeración en «Otros comprobantes», emisión en dos fases, cupo, permisos y correo."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core import mail
from django.core.management import call_command
from django.db import transaction
from lxml import etree

from core.comprobantes import notas_debito as snd
from core.comprobantes.models import NotaDebito
from core.configuracion import servicios as cfg
from core.pos import emision
from core.pos.models import Client
from core.suscripciones.models import SubscriptionPeriod
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_OWNER, ROLE_SELLER
from tests import helpers
from tests.test_emision_sri import (comprador, dueno, empresa, leer, p12, producto, sri, vender, venta_de,  # noqa: F401
                                    web)

pytestmark = pytest.mark.django_db
XSD = Path(__file__).parent / 'xsd' / 'notadebito' / 'NotaDebito_V1.0.0.xsd'
LISTA = '/comprobantes/notas-debito/'


@pytest.fixture
def numeracion(empresa):  # noqa: F811
    """Numeración de notas de débito confirmada en «Otros comprobantes»: continúa desde la 3 de otro sistema."""
    with company_context(empresa):
        return cfg.configurar_otro_documento(empresa, '05', 'otro_sistema', '001-002-000000003', True)


@pytest.fixture
def factura(web, empresa, comprador, producto, sri):  # noqa: F811
    """Factura autorizada 001-002-000000271: 2 × $10 + IVA 15 % = $23."""
    sri.respuestas_autorizacion = ['AUTORIZADO']
    vender(web, comprador, producto, cantidad=2)
    return venta_de(empresa, 271)


def formulario(motivos=(('Interés por mora', '10.00'), ('Gastos de cobranza', '5.50')), tarifa='15.00', **cambios):
    post = {'tarifa_iva': tarifa, 'forma_pago': '20', 'motivos-TOTAL_FORMS': '3', 'motivos-INITIAL_FORMS': '0',
            'motivos-MIN_NUM_FORMS': '0', 'motivos-MAX_NUM_FORMS': '10'}
    for i, (razon, valor) in enumerate(motivos):
        post.update({f'motivos-{i}-razon': razon, f'motivos-{i}-valor': valor})
    post.update(cambios)
    return post


class TestCalculo:

    def test_tarifa_de_la_factura_y_redondeo(self, empresa, factura):  # noqa: F811
        with company_context(empresa):
            assert snd.tarifa_de_factura(factura) == Decimal('15.00') and snd.tarifas_permitidas(factura) == [Decimal('15.00'), Decimal('0.00')]
            doc, motivos, totales = snd.calcular(factura, {'tarifa_iva': '15.00'}, [('Interés  por mora', '10.00'), ('Gastos de cobranza', '5.50'), ('', None)])
        assert [m['razon'] for m in motivos] == ['Interés por mora', 'Gastos de cobranza']
        assert totales == {'total_sin_impuestos': Decimal('15.50'), 'valor_iva': Decimal('2.33'), 'valor_total': Decimal('17.83')}   # 2,325 → 2,33
        assert doc['forma_pago'] == '01'   # la de la factura cuando no se indica

    def test_cero_por_ciento_y_tarifas_no_permitidas(self, empresa, factura):  # noqa: F811
        with company_context(empresa):
            _, _, totales = snd.calcular(factura, {'tarifa_iva': '0.00'}, [('Interés por mora', '10')])
            assert totales['valor_iva'] == Decimal('0.00') and totales['valor_total'] == Decimal('10.00')
            with pytest.raises(snd.ErrorNotaDebito, match='la de la factura'):
                snd.calcular(factura, {'tarifa_iva': '12.00'}, [('Interés por mora', '10')])

    @pytest.mark.parametrize('motivos, mensaje', [
        ([('', '10.00')], 'razón de cada valor'),
        ([('Interés por mora', '0')], 'mayor que cero'),
        ([('', None)], 'al menos un motivo'),
        ([('Cargo', '1')] * 11, 'hasta 10 motivos'),
    ])
    def test_motivos_invalidos(self, empresa, factura, motivos, mensaje):  # noqa: F811
        with company_context(empresa):
            with pytest.raises(snd.ErrorNotaDebito, match=mensaje):
                snd.calcular(factura, {'tarifa_iva': '15.00'}, motivos)

    @pytest.mark.parametrize('cambios, mensaje', [
        ({'client': SimpleNamespace(identification_type='07', dni='9999999999999')}, 'consumidor final'),
        ({'status': 'in_process'}, 'autorizada por el SRI'),
        ({'receipt': SimpleNamespace(voucher_type='08')}, 'solo se emiten sobre facturas'),
        ({'environment_type': 1, 'get_environment_type_display': lambda: 'PRUEBAS'}, 'ambiente PRUEBAS'),
    ])
    def test_solo_facturas_autorizadas_identificadas_y_del_mismo_ambiente(self, cambios, mensaje):
        venta = SimpleNamespace(receipt=SimpleNamespace(voucher_type='01'), status='authorized', environment_type=2,
                                client=SimpleNamespace(identification_type='04', dni='0991234567001'))
        for k, v in cambios.items():
            setattr(venta, k, v)
        company = SimpleNamespace(environment_type=2, get_environment_type_display=lambda: 'PRODUCCIÓN')
        with pytest.raises(snd.ErrorNotaDebito, match=mensaje):
            snd.validar_factura(venta, company)


class TestEmision:

    def test_revisar_no_guarda_y_emitir_autoriza(self, web, empresa, comprador, factura, numeracion, sri):  # noqa: F811
        leer(empresa, lambda: Client.objects.filter(pk=comprador.pk).update(send_email_invoice=True))   # el cliente acepta correos
        html = web.get(f'{LISTA}nueva/{factura.pk}/').content.decode()
        assert 'Nota de débito de la factura 001-002-000000271' in html and 'value="15.00" selected' in html
        revision = web.post(f'{LISTA}nueva/{factura.pk}/', {**formulario(), 'action': 'calcular'}).content.decode()
        assert 'Revisa antes de emitir' in revision and '$17,83' in revision and not leer(empresa, lambda: NotaDebito.objects.exists())
        sri.respuestas_autorizacion = ['AUTORIZADO']
        respuesta = web.post(f'{LISTA}nueva/{factura.pk}/', {**formulario(), 'action': 'emitir'}, follow=True)
        nota = leer(empresa, lambda: NotaDebito.objects.get())
        assert nota.voucher_number_full == '001-002-000000004' and nota.status in emision.AUTORIZADOS
        assert nota.valor_total == Decimal('17.83') and 'autorizada por el SRI' in respuesta.content.decode()
        assert '<codDoc>05</codDoc>' in nota.xml_signed and '<numDocModificado>001-002-000000271</numDocModificado>' in nota.xml_signed
        assert '<razon>Interés por mora</razon>' in nota.xml_signed and nota.xml_authorized and nota.pdf_authorized
        assert SubscriptionPeriod.objects.get(company=empresa, status='activa').documents_used == 2   # factura + nota de débito
        correo = leer(empresa, lambda: Client.objects.get(pk=comprador.pk).user.email)
        enviados = [m for m in mail.outbox if 'Total: USD 17.83' in m.body]
        assert len(enviados) == 1 and enviados[0].to == [correo] and nota.enviar_correo

    def test_xml_firmado_valido_contra_el_xsd_oficial(self, empresa, factura, numeracion):  # noqa: F811
        empresa.retention_agent, empresa.special_taxpayer, empresa.rimpe = 'SI', '12345', 'emprendedor'
        empresa.save()
        with company_context(empresa):
            with transaction.atomic():
                nota = snd.crear(empresa, helpers.crear_usuario('firmante.nd', empresa), factura, {'tarifa_iva': '15.00', 'forma_pago': '20'},
                                 [('Interés por mora', '10.00'), ("Gastos d'cobranza", '5.50')])
                emision.preparar(nota)
            nota.refresh_from_db()
        parser = etree.XMLParser(no_network=True, load_dtd=True, resolve_entities=True)
        esquema = etree.XMLSchema(etree.parse(str(XSD), parser))
        documento = etree.fromstring(nota.xml_signed.encode())
        assert esquema.validate(documento), [str(e) for e in esquema.error_log]
        assert documento.findtext('infoNotaDebito/impuestos/impuesto/codigoPorcentaje') == '4'
        assert documento.findtext('infoNotaDebito/valorTotal') == '17.83' and len(documento.findall('motivos/motivo')) == 2
        assert documento.findtext('infoTributaria/agenteRetencion') == '1'
        assert documento.findtext('infoTributaria/contribuyenteRimpe') == 'CONTRIBUYENTE RÉGIMEN RIMPE'

    def test_varias_notas_por_factura(self, web, empresa, factura, numeracion, sri):  # noqa: F811
        for _ in range(2):
            sri.respuestas_autorizacion = ['AUTORIZADO']
            web.post(f'{LISTA}nueva/{factura.pk}/', {**formulario(motivos=[('Interés por mora', '1.00')]), 'action': 'emitir'})
        numeros = leer(empresa, lambda: sorted(NotaDebito.objects.values_list('voucher_number_full', flat=True)))
        assert numeros == ['001-002-000000004', '001-002-000000005']
        html = web.get(f'{LISTA}nueva/{factura.pk}/').content.decode()
        assert 'Notas de débito anteriores de esta factura' in html

    def test_en_proceso_no_se_borra_y_la_tarea_la_autoriza(self, web, empresa, factura, numeracion, sri):  # noqa: F811
        web.post(f'{LISTA}nueva/{factura.pk}/', {**formulario(), 'action': 'emitir'})
        nota = leer(empresa, lambda: NotaDebito.objects.get())
        assert nota.status == 'in_process'
        respuesta = web.post(LISTA, {'action': 'delete', 'id': nota.pk}, follow=True)
        assert 'no se puede eliminar' in respuesta.content.decode()
        sri.respuestas_autorizacion = ['AUTORIZADO']
        call_command('consultar_sri')
        assert leer(empresa, lambda: NotaDebito.objects.get(pk=nota.pk).status) in emision.AUTORIZADOS

    def test_sin_numeracion_explica_donde_configurarla(self, web, empresa, factura, sri):  # noqa: F811
        respuesta = web.post(f'{LISTA}nueva/{factura.pk}/', {**formulario(), 'action': 'emitir'})
        assert 'Otros comprobantes' in respuesta.content.decode() and not leer(empresa, lambda: NotaDebito.objects.exists())

    def test_otros_comprobantes_muestra_la_nota_de_debito(self, web):  # noqa: F811
        html = web.get('/configuracion/facturacion/otros/').content.decode()
        assert 'Nota de débito' in html and 'name="tipo" value="05"' in html


class TestPermisos:

    def test_contador_consulta_pero_no_emite_y_vendedor_no_entra(self, client, empresa, factura):  # noqa: F811
        helpers.iniciar_sesion(client, helpers.crear_usuario('contador.nd', empresa, ROLE_ACCOUNTANT), empresa=empresa)
        assert client.get(LISTA).status_code == 200
        assert client.get(f'{LISTA}nueva/{factura.pk}/').status_code in (302, 403)
        client.logout()
        helpers.iniciar_sesion(client, helpers.crear_usuario('vendedor.nd', empresa, ROLE_SELLER), empresa=empresa)
        assert client.get(LISTA).status_code in (302, 403)

    def test_otra_empresa_no_ve_la_factura(self, client, factura):
        otra = helpers.crear_empresa('AJENA ND', plan='ilimitado')
        helpers.iniciar_sesion(client, helpers.crear_usuario('dueno.ajena.nd', otra, ROLE_OWNER), empresa=otra)
        assert client.get(f'{LISTA}nueva/{factura.pk}/').status_code == 404
