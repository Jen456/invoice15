"""Leyenda RIMPE (ficha técnica, Anexo 22): <contribuyenteRimpe> al final de <infoTributaria> y en el RIDE, para RIMPE
Emprendedor («CONTRIBUYENTE RÉGIMEN RIMPE») y Negocio Popular («CONTRIBUYENTE NEGOCIO POPULAR - RÉGIMEN RIMPE»). El SRI
aceptó las dos en el ambiente de pruebas; los XSD publicados solo traen la primera, así que el XSD se valida con ella."""
import json
from pathlib import Path

import pytest
from django.template.loader import render_to_string
from lxml import etree

from core.pos.models import Company, CreditNote, SaleDetail
from tests.test_emision_sri import (comprador, dueno, empresa, leer, p12, producto, sri, vender, venta_de,  # noqa: F401
                                    web)

pytestmark = pytest.mark.django_db
XSD = Path(__file__).parent / 'xsd'
EMPRENDEDOR = 'CONTRIBUYENTE RÉGIMEN RIMPE'
NEGOCIO_POPULAR = 'CONTRIBUYENTE NEGOCIO POPULAR - RÉGIMEN RIMPE'


def validar(xml, xsd):
    parser = etree.XMLParser(no_network=True, load_dtd=True, resolve_entities=True)
    esquema = etree.XMLSchema(etree.parse(str(xsd), parser))
    documento = etree.fromstring(xml.encode())
    return esquema.validate(documento), [str(e) for e in esquema.error_log], documento


def ultimos_de_info_tributaria(documento):
    return [etree.QName(n).localname for n in documento.find('infoTributaria')][-3:]


def factura(web, empresa, comprador, producto, sri, rimpe='', agente='NO'):  # noqa: F811
    Company.objects.filter(pk=empresa.pk).update(rimpe=rimpe, retention_agent=agente)
    sri.respuestas_autorizacion = ['AUTORIZADO']
    vender(web, comprador, producto, cantidad=2)
    return venta_de(empresa, 271)


class TestLeyenda:

    def test_textos(self):
        assert Company(rimpe='emprendedor').leyenda_rimpe == EMPRENDEDOR
        assert Company(rimpe='negocio_popular').leyenda_rimpe == NEGOCIO_POPULAR
        assert Company(rimpe='').leyenda_rimpe == ''

    def test_factura_emprendedor_valida_contra_el_xsd(self, web, empresa, comprador, producto, sri):  # noqa: F811
        venta = factura(web, empresa, comprador, producto, sri, 'emprendedor')
        ok, errores, documento = validar(venta.xml_signed, XSD / 'factura' / 'factura_V1.0.0.xsd')
        assert ok, errores
        assert documento.findtext('infoTributaria/contribuyenteRimpe') == EMPRENDEDOR
        assert ultimos_de_info_tributaria(documento)[-2:] == ['dirMatriz', 'contribuyenteRimpe']

    def test_factura_negocio_popular_y_agente_de_retencion(self, web, empresa, comprador, producto, sri):  # noqa: F811
        venta = factura(web, empresa, comprador, producto, sri, 'negocio_popular', agente='SI')
        documento = etree.fromstring(venta.xml_signed.encode())
        assert documento.findtext('infoTributaria/contribuyenteRimpe') == NEGOCIO_POPULAR
        assert ultimos_de_info_tributaria(documento) == ['dirMatriz', 'agenteRetencion', 'contribuyenteRimpe']   # orden del XSD

    def test_regimen_general_sin_leyenda(self, web, empresa, comprador, producto, sri):  # noqa: F811
        venta = factura(web, empresa, comprador, producto, sri, '')
        assert '<contribuyenteRimpe>' not in venta.xml_signed and '<agenteRetencion>' not in venta.xml_signed

    def test_nota_de_credito_valida_contra_el_xsd(self, web, empresa, comprador, producto, sri):  # noqa: F811
        venta = factura(web, empresa, comprador, producto, sri, 'emprendedor')
        detalle = leer(empresa, lambda: SaleDetail.objects.filter(sale=venta).first())
        sri.respuestas_autorizacion = ['AUTORIZADO']
        web.post('/pos/credit/note/admin/add/', {'action': 'add', 'sale': venta.pk, 'motive': 'Devolución', 'create_electronic_invoice': 'on',
                                                 'products': json.dumps([{'id': detalle.pk, 'quantity': 1, 'price': '1', 'dscto': 0}])})
        nota = leer(empresa, lambda: CreditNote.objects.get(sale=venta))
        ok, errores, documento = validar(nota.xml_signed, XSD / 'notacredito' / 'NotaCredito_V1.1.0.xsd')
        assert ok, errores
        assert documento.findtext('infoTributaria/contribuyenteRimpe') == EMPRENDEDOR

    def test_el_ride_de_la_factura_muestra_la_leyenda(self, web, empresa, comprador, producto, sri):  # noqa: F811
        venta = factura(web, empresa, comprador, producto, sri, 'negocio_popular')
        with __import__('core.tenancy.context', fromlist=['company_context']).company_context(empresa):
            venta.refresh_from_db()
            html = render_to_string('sale/format/invoice.html', {'sale': venta, 'company': venta.company})
        assert NEGOCIO_POPULAR in html

    def test_formulario_de_la_empresa_tiene_el_regimen(self, web):  # noqa: F811
        html = web.get('/configuracion/facturacion/paso/1/').content.decode()
        assert 'name="rimpe"' in html and 'RIMPE Negocio Popular' in html
