"""Ayudas de las pruebas de precios con IVA (core/pos/precios_iva.py; datos ficticios)."""
import re
from pathlib import Path

from lxml import etree

XSD_FACTURA_100 = Path(__file__).parent / 'xsd' / 'factura' / 'factura_V1.0.0.xsd'


def esquema_factura_110():
    """XSD de la factura 1.0.0 del repositorio con `cantidad` y `precioUnitario` como en la versión 1.1.0 (totalDigits 18,
    fractionDigits 6). NO es el archivo oficial 1.1.0 del SRI (no está en el repositorio): comprueba la estructura del
    comprobante y los 6 decimales del detalle."""
    texto = XSD_FACTURA_100.read_text(encoding='utf-8')
    for tipo in ('cantidad', 'precioUnitario'):
        patron = re.compile(r'(<xsd:simpleType name="' + tipo + r'">\s*<xsd:restriction base="xsd:decimal">\s*)'
                            r'<xsd:totalDigits value="14"/>(\s*)<xsd:fractionDigits value="2"/>')
        texto, cambios = patron.subn(r'\1<xsd:totalDigits value="18"/>\2<xsd:fractionDigits value="6"/>', texto)
        assert cambios == 1, tipo
    parser = etree.XMLParser(no_network=True, load_dtd=True, resolve_entities=True)
    return etree.XMLSchema(etree.fromstring(texto.encode('utf-8'), parser, base_url=str(XSD_FACTURA_100)))


def validar_factura_110(xml):
    esquema = esquema_factura_110()
    documento = etree.fromstring(xml.encode())
    return esquema.validate(documento), [str(e) for e in esquema.error_log], documento
