"""Guía de remisión (06, XML 1.1.0) del traslado de lo vendido en una factura autorizada: reglas en el servidor, XML válido
contra el XSD oficial del SRI, entregas parciales, numeración en «Otros comprobantes», emisión en dos fases, cupo,
permisos y correo."""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core import mail
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone
from lxml import etree

from core.comprobantes import guias as sg
from core.comprobantes.models import GuiaRemision
from core.configuracion import servicios as cfg
from core.pos import emision
from core.pos.models import Client, SaleDetail
from core.suscripciones.models import SubscriptionPeriod
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_OWNER, ROLE_SELLER
from tests import helpers
from tests.test_emision_sri import (comprador, dueno, empresa, leer, p12, producto, sri, vender, venta_de,  # noqa: F401
                                    web)

pytestmark = pytest.mark.django_db
XSD = Path(__file__).parent / 'xsd' / 'guia' / 'GuiaRemision_V1.1.0.xsd'
LISTA = '/comprobantes/guias/'
RUC_TRANSPORTISTA = '0912345600001'


@pytest.fixture
def numeracion(empresa):  # noqa: F811
    """Numeración de guías confirmada en «Otros comprobantes»: continúa desde la 9 de otro sistema."""
    with company_context(empresa):
        return cfg.configurar_otro_documento(empresa, '06', 'otro_sistema', '001-002-000000009', True)


@pytest.fixture
def factura(web, empresa, comprador, producto, sri):  # noqa: F811
    """Factura autorizada 001-002-000000271 con 2 unidades del producto P100."""
    sri.respuestas_autorizacion = ['AUTORIZADO']
    vender(web, comprador, producto, cantidad=2)
    return venta_de(empresa, 271)


def detalle_de(factura):
    return leer(factura.company, lambda: SaleDetail.objects.get(sale=factura))


DATOS = {'transportista_tipo_identificacion': '04', 'transportista_identificacion': RUC_TRANSPORTISTA,
         'transportista_razon_social': "TRANSPORTES D'LA COSTA", 'placa': 'gba-1234', 'dir_partida': 'Av. Ficticia 1, Guayaquil',
         'direccion': 'Km 5 vía a Daule', 'motivo': 'Venta', 'ruta': 'Guayaquil - Daule', 'cod_estab_destino': '', 'doc_aduanero': ''}


def datos(**cambios):
    hoy = timezone.localdate()
    return {**DATOS, 'fecha_inicio': hoy, 'fecha_fin': hoy + timedelta(days=1), **cambios}


def formulario(factura, cantidad='2', **cambios):
    detalle = detalle_de(factura)
    post = {k: (v.isoformat() if hasattr(v, 'isoformat') else v) for k, v in datos(**cambios).items()}
    post.update({'lineas-TOTAL_FORMS': '1', 'lineas-INITIAL_FORMS': '1', 'lineas-MIN_NUM_FORMS': '0', 'lineas-MAX_NUM_FORMS': '1000',
                 'lineas-0-detalle': detalle.pk, 'lineas-0-cantidad': cantidad})
    return post


class TestReglas:

    def test_traslado_total_y_parcial(self, empresa, factura):  # noqa: F811
        detalle = detalle_de(factura)
        with company_context(empresa):
            doc, lineas = sg.calcular(factura, datos(), {detalle.pk: '2'})
            assert doc['placa'] == 'GBA-1234' and doc['transportista_identificacion'] == RUC_TRANSPORTISTA
            assert [(l['descripcion'], l['cantidad']) for l in lineas] == [('PRODUCTO P100', Decimal('2'))]
            _, lineas = sg.calcular(factura, datos(), {detalle.pk: '1.5'})
            assert lineas[0]['cantidad'] == Decimal('1.5')

    @pytest.mark.parametrize('cambios, cantidad, mensaje', [
        ({'transportista_identificacion': '0912345678001'}, '1', 'RUC del transportista no es válido'),
        ({'transportista_tipo_identificacion': '05', 'transportista_identificacion': '0912345678'}, '1', 'cédula del transportista'),
        ({'transportista_tipo_identificacion': '06', 'transportista_identificacion': 'X1'}, '1', 'entre 3 y 20'),
        ({'transportista_razon_social': '  '}, '1', 'razón social del transportista'),
        ({'placa': 'G B'}, '1', 'placa'),
        ({'fecha_fin': timezone.localdate() - timedelta(days=1)}, '1', 'no puede ser anterior'),
        ({'cod_estab_destino': '1'}, '1', '3 dígitos'),
        ({}, '3', 'solo quedan 2'),
        ({}, '0', 'al menos una línea'),
        ({}, '-1', 'negativa'),
    ])
    def test_validaciones(self, empresa, factura, cambios, cantidad, mensaje):  # noqa: F811
        with company_context(empresa), pytest.raises(sg.ErrorGuia, match=mensaje):
            sg.calcular(factura, datos(**cambios), {detalle_de(factura).pk: cantidad})

    @pytest.mark.parametrize('cambios, mensaje', [
        ({'client': SimpleNamespace(identification_type='07', dni='9999999999999')}, 'consumidor final'),
        ({'status': 'in_process'}, 'autorizada por el SRI'),
        ({'receipt': SimpleNamespace(voucher_type='08')}, 'sobre facturas'),
        ({'environment_type': 1, 'get_environment_type_display': lambda: 'PRUEBAS'}, 'ambiente PRUEBAS'),
    ])
    def test_solo_facturas_autorizadas_identificadas_y_del_mismo_ambiente(self, cambios, mensaje):
        venta = SimpleNamespace(receipt=SimpleNamespace(voucher_type='01'), status='authorized', environment_type=2,
                                client=SimpleNamespace(identification_type='04', dni='0991234567001'))
        for k, v in cambios.items():
            setattr(venta, k, v)
        with pytest.raises(sg.ErrorGuia, match=mensaje):
            sg.validar_factura(venta, SimpleNamespace(environment_type=2, get_environment_type_display=lambda: 'PRODUCCIÓN'))


class TestEmision:

    def test_revisar_no_guarda_y_emitir_autoriza(self, web, empresa, comprador, factura, numeracion, sri):  # noqa: F811
        leer(empresa, lambda: Client.objects.filter(pk=comprador.pk).update(send_email_invoice=True))
        html = web.get(f'{LISTA}nueva/{factura.pk}/').content.decode()
        assert 'Guía de la factura 001-002-000000271' in html and 'pendiente 2' in html and 'value="Av. Ficticia 1"' in html
        revision = web.post(f'{LISTA}nueva/{factura.pk}/', {**formulario(factura), 'action': 'calcular'}).content.decode()
        assert 'Revisa antes de emitir' in revision and 'GBA-1234' in revision and not leer(empresa, lambda: GuiaRemision.objects.exists())
        mail.outbox.clear()
        sri.respuestas_autorizacion = ['AUTORIZADO']
        respuesta = web.post(f'{LISTA}nueva/{factura.pk}/', {**formulario(factura), 'action': 'emitir'}, follow=True)
        guia = leer(empresa, lambda: GuiaRemision.objects.get())
        assert guia.voucher_number_full == '001-002-000000010' and guia.status in emision.AUTORIZADOS
        assert 'autorizada por el SRI' in respuesta.content.decode()
        assert '<codDoc>06</codDoc>' in guia.xml_signed and '<numDocSustento>001-002-000000271</numDocSustento>' in guia.xml_signed
        assert f'<numAutDocSustento>{factura.access_code}</numAutDocSustento>' in guia.xml_signed and '<placa>GBA-1234</placa>' in guia.xml_signed
        assert guia.xml_authorized and guia.pdf_authorized
        assert SubscriptionPeriod.objects.get(company=empresa, status='activa').documents_used == 2   # factura + guía
        enviado = mail.outbox[-1]
        assert enviado.to == [leer(empresa, lambda: Client.objects.get(pk=comprador.pk).user.email)]
        assert enviado.subject.startswith('Guía de remisión 001-002-000000010') and 'Total' not in enviado.body

    def test_xml_firmado_valido_contra_el_xsd_oficial(self, empresa, factura, numeracion):  # noqa: F811
        empresa.retention_agent, empresa.special_taxpayer = 'SI', '12345'
        empresa.save()
        with company_context(empresa):
            with transaction.atomic():
                guia = sg.crear(empresa, helpers.crear_usuario('firmante.guia', empresa), factura,
                                datos(cod_estab_destino='001', doc_aduanero='DAU-1'), {detalle_de(factura).pk: '1.25'})
                emision.preparar(guia)
            guia.refresh_from_db()
        parser = etree.XMLParser(no_network=True, load_dtd=True, resolve_entities=True)
        esquema = etree.XMLSchema(etree.parse(str(XSD), parser))
        documento = etree.fromstring(guia.xml_signed.encode())
        assert esquema.validate(documento), [str(e) for e in esquema.error_log]
        assert documento.get('version') == '1.1.0' and documento.findtext('infoGuiaRemision/rucTransportista') == RUC_TRANSPORTISTA
        assert documento.findtext('destinatarios/destinatario/detalles/detalle/cantidad') == '1.250000'
        assert documento.findtext('destinatarios/destinatario/codEstabDestino') == '001'
        assert documento.findtext('infoTributaria/agenteRetencion') == '1'

    def test_entregas_parciales_no_superan_lo_vendido(self, web, empresa, factura, numeracion, sri):  # noqa: F811
        for _ in range(2):
            sri.respuestas_autorizacion = ['AUTORIZADO']
            web.post(f'{LISTA}nueva/{factura.pk}/', {**formulario(factura, cantidad='1'), 'action': 'emitir'})
        assert leer(empresa, lambda: GuiaRemision.objects.count()) == 2
        html = web.post(f'{LISTA}nueva/{factura.pk}/', {**formulario(factura, cantidad='1'), 'action': 'emitir'}).content.decode()
        assert 'solo quedan 0' in html and leer(empresa, lambda: GuiaRemision.objects.count()) == 2
        assert 'Guías anteriores de esta factura' in web.get(f'{LISTA}nueva/{factura.pk}/').content.decode()

    def test_en_proceso_no_se_borra_y_la_tarea_la_autoriza(self, web, empresa, factura, numeracion, sri):  # noqa: F811
        web.post(f'{LISTA}nueva/{factura.pk}/', {**formulario(factura), 'action': 'emitir'})
        guia = leer(empresa, lambda: GuiaRemision.objects.get())
        assert guia.status == 'in_process'
        assert 'no se puede eliminar' in web.post(LISTA, {'action': 'delete', 'id': guia.pk}, follow=True).content.decode()
        sri.respuestas_autorizacion = ['AUTORIZADO']
        call_command('consultar_sri')
        assert leer(empresa, lambda: GuiaRemision.objects.get(pk=guia.pk).status) in emision.AUTORIZADOS

    def test_sin_numeracion_explica_donde_configurarla(self, web, empresa, factura, sri):  # noqa: F811
        respuesta = web.post(f'{LISTA}nueva/{factura.pk}/', {**formulario(factura), 'action': 'emitir'})
        assert 'Otros comprobantes' in respuesta.content.decode() and not leer(empresa, lambda: GuiaRemision.objects.exists())

    def test_otros_comprobantes_muestra_la_guia(self, web):  # noqa: F811
        html = web.get('/configuracion/facturacion/otros/').content.decode()
        assert 'Guía de remisión' in html and 'name="tipo" value="06"' in html


class TestPermisos:

    def test_contador_consulta_pero_no_emite_y_vendedor_no_entra(self, client, empresa, factura):  # noqa: F811
        helpers.iniciar_sesion(client, helpers.crear_usuario('contador.guia', empresa, ROLE_ACCOUNTANT), empresa=empresa)
        assert client.get(LISTA).status_code == 200
        assert client.get(f'{LISTA}nueva/{factura.pk}/').status_code in (302, 403)
        client.logout()
        helpers.iniciar_sesion(client, helpers.crear_usuario('vendedor.guia', empresa, ROLE_SELLER), empresa=empresa)
        assert client.get(LISTA).status_code in (302, 403)

    def test_otra_empresa_no_ve_la_factura(self, client, factura):
        otra = helpers.crear_empresa('AJENA GUIA', plan='ilimitado')
        helpers.iniciar_sesion(client, helpers.crear_usuario('dueno.ajena.guia', otra, ROLE_OWNER), empresa=otra)
        assert client.get(f'{LISTA}nueva/{factura.pk}/').status_code == 404
