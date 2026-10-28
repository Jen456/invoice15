"""<contribuyenteEspecial> de la nota de crédito (Etapa 2, O2, §1.4): el XSD 1.1.0 exige de 3 a 13 caracteres, así que
solo se escribe si la empresa es contribuyente especial ('' de las empresas del registro y '000' no lo son). Las notas ya
firmadas conservan su XML: solo cambia el de las que se firmen después."""
from pathlib import Path

import pytest
from lxml import etree

from core.pos.models import Company
from tests.ayudas_ventas import factura_autorizada, nota_credito_autorizada
from tests.test_emision_sri import comprador, dueno, empresa, p12, producto, sri  # noqa: F401

pytestmark = pytest.mark.django_db
XSD = Path(__file__).parent / 'xsd' / 'notacredito' / 'NotaCredito_V1.1.0.xsd'


def validar(xml):
    parser = etree.XMLParser(no_network=True, load_dtd=True, resolve_entities=True)
    esquema = etree.XMLSchema(etree.parse(str(XSD), parser))
    documento = etree.fromstring(xml.encode())
    return esquema.validate(documento), [str(e) for e in esquema.error_log], documento


@pytest.mark.parametrize('especial, esperado', [('', None), ('000', None), (' 000 ', None), ('12345', '12345'),
                                                (' 5368 ', '5368')])
def test_contribuyente_especial_solo_si_lo_es(empresa, comprador, dueno, producto, sri, especial, esperado):  # noqa: F811
    Company.objects.filter(pk=empresa.pk).update(special_taxpayer=especial)
    empresa.refresh_from_db()
    venta = factura_autorizada(empresa, comprador, dueno, producto)
    nota = nota_credito_autorizada(venta, sri=sri)
    ok, errores, documento = validar(nota.xml_signed)
    assert ok, errores
    assert documento.findtext('infoNotaCredito/contribuyenteEspecial') == esperado
    assert nota.status == 'authorized'
