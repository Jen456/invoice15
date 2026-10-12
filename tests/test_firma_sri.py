"""Firma XAdES-BES nativa (sustituye al jar Java): estructura que exige el SRI, resúmenes y firma
verificables de forma independiente, errores claros y uso desde el flujo de emisión."""
import base64
import hashlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone as dt_tz
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from django.core.files.base import ContentFile
from lxml import etree

from core.pos.utilities.firma import C14N, DS, ETSI, ErrorFirma, firmar_xml
from core.pos.utilities.sri import SRI
from tests import helpers

NS = {'ds': DS, 'etsi': ETSI}
CLAVE = 'clave-de-prueba'
XML = ('<?xml version="1.0" encoding="UTF-8"?>\n<factura id="comprobante" version="1.0.0"><infoTributaria>'
       '<razonSocial>PEÑA &amp; ASOCIADOS CÍA. LTDA.</razonSocial><ruc>0991234567001</ruc></infoTributaria>'
       '<infoFactura><importeTotal>11.50</importeTotal></infoFactura></factura>')


def generar_p12(dias_inicio=-1, dias_fin=365):
    """Certificado ficticio (no sirve ante el SRI, solo para verificar la firma localmente)."""
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ahora = datetime.now(dt_tz.utc)
    emisor = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, 'EC'),
                        x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'ENTIDAD DE PRUEBA'),
                        x509.NameAttribute(NameOID.COMMON_NAME, 'AC DE PRUEBA')])
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'FIRMANTE FICTICIO')]))
            .issuer_name(emisor).public_key(clave.public_key()).serial_number(1312833444)
            .not_valid_before(ahora + timedelta(days=dias_inicio)).not_valid_after(ahora + timedelta(days=dias_fin))
            .sign(clave, hashes.SHA256()))
    p12 = pkcs12.serialize_key_and_certificates(b'firmante', clave, cert, None,
                                                serialization.BestAvailableEncryption(CLAVE.encode()))
    return p12, cert


@pytest.fixture(scope='module')
def firma():
    return generar_p12()


@pytest.fixture(scope='module')
def firmado(firma):
    p12, cert = firma
    return firmar_xml(XML, p12, CLAVE), cert


def uno(nodo, ruta):
    resultado = nodo.xpath(ruta, namespaces=NS)
    assert len(resultado) == 1, ruta
    return resultado[0]


def sha1_c14n(nodo):
    return base64.b64encode(hashlib.sha1(etree.tostring(nodo, method='c14n')).digest()).decode()


class TestEstructura:

    def test_firma_enveloped_con_lo_que_pide_la_ficha_tecnica(self, firmado):
        texto, cert = firmado
        raiz = etree.fromstring(texto.encode())
        firma = raiz[-1]
        assert firma.tag == f'{{{DS}}}Signature' and len(raiz.xpath('//ds:Signature', namespaces=NS)) == 1
        assert [etree.QName(h).localname for h in firma] == ['SignedInfo', 'SignatureValue', 'KeyInfo', 'Object']
        assert uno(firma, 'ds:SignedInfo/ds:CanonicalizationMethod').get('Algorithm') == C14N
        assert uno(firma, 'ds:SignedInfo/ds:SignatureMethod').get('Algorithm') == f'{DS}rsa-sha1'
        refs = firma.xpath('ds:SignedInfo/ds:Reference', namespaces=NS)
        assert len(refs) == 3
        assert all(uno(r, 'ds:DigestMethod').get('Algorithm') == f'{DS}sha1' for r in refs)
        propiedades = uno(firma, 'ds:Object/etsi:QualifyingProperties/etsi:SignedProperties')
        assert refs[0].get('Type') == 'http://uri.etsi.org/01903#SignedProperties'
        assert refs[0].get('URI') == f'#{propiedades.get("Id")}'
        assert refs[1].get('URI') == f'#{uno(firma, "ds:KeyInfo").get("Id")}' and not refs[1].xpath('ds:Transforms', namespaces=NS)
        assert refs[2].get('URI') == '#comprobante'
        assert [t.get('Algorithm') for t in refs[2].xpath('ds:Transforms/ds:Transform', namespaces=NS)] == [f'{DS}enveloped-signature']
        assert uno(firma, 'ds:Object/etsi:QualifyingProperties').get('Target') == f'#{firma.get("Id")}'
        formato = uno(propiedades, 'etsi:SignedDataObjectProperties/etsi:DataObjectFormat')
        assert formato.get('ObjectReference') == f'#{refs[2].get("Id")}'
        assert uno(formato, 'etsi:MimeType').text == 'text/xml'

    def test_certificado_y_propiedades_firmadas(self, firmado):
        texto, cert = firmado
        raiz = etree.fromstring(texto.encode())
        der = cert.public_bytes(serialization.Encoding.DER)
        assert uno(raiz, '//ds:X509Certificate').text == base64.b64encode(der).decode()
        numeros = cert.public_key().public_numbers()
        assert base64.b64decode(uno(raiz, '//ds:Modulus').text) == numeros.n.to_bytes(256, 'big')
        assert uno(raiz, '//ds:Exponent').text == 'AQAB'
        assert uno(raiz, '//etsi:CertDigest/ds:DigestValue').text == base64.b64encode(hashlib.sha1(der).digest()).decode()
        assert uno(raiz, '//ds:X509SerialNumber').text == '1312833444'
        assert uno(raiz, '//ds:X509IssuerName').text == 'CN=AC DE PRUEBA,O=ENTIDAD DE PRUEBA,C=EC'
        assert uno(raiz, '//etsi:SigningTime').text.endswith('-05:00')   # hora de Ecuador

    def test_contenido_intacto(self, firmado):
        texto, _ = firmado
        assert texto.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<factura id="comprobante" version="1.0.0">')
        assert 'PEÑA &amp; ASOCIADOS CÍA. LTDA.' in texto and '<importeTotal>11.50</importeTotal>' in texto


class TestVerificacionIndependiente:
    """Se recalcula todo desde el XML serializado, como haría el SRI."""

    def test_resumenes_y_valor_de_firma(self, firmado):
        texto, cert = firmado
        raiz = etree.fromstring(texto.encode())
        refs = raiz.xpath('//ds:SignedInfo/ds:Reference', namespaces=NS)
        sin_firma = deepcopy(raiz)
        sin_firma.remove(sin_firma[-1])
        assert uno(refs[2], 'ds:DigestValue').text == sha1_c14n(sin_firma)
        for ref in refs[:2]:
            destino = uno(raiz, f'//*[@Id="{ref.get("URI")[1:]}"]')
            assert uno(ref, 'ds:DigestValue').text == sha1_c14n(destino)
        # C14N inclusiva: el elemento referenciado lleva los espacios de nombres heredados.
        propiedades = etree.tostring(uno(raiz, '//etsi:SignedProperties'), method='c14n')
        assert b'xmlns:ds="http://www.w3.org/2000/09/xmldsig#"' in propiedades and b'xmlns:etsi=' in propiedades
        signed_info = etree.tostring(uno(raiz, '//ds:SignedInfo'), method='c14n')
        cert.public_key().verify(base64.b64decode(uno(raiz, '//ds:SignatureValue').text), signed_info,
                                 padding.PKCS1v15(), hashes.SHA1())

    def test_alterar_el_comprobante_rompe_el_resumen(self, firmado):
        texto, _ = firmado
        raiz = etree.fromstring(texto.replace('<importeTotal>11.50<', '<importeTotal>1.50<').encode())
        sin_firma = deepcopy(raiz)
        sin_firma.remove(sin_firma[-1])
        assert uno(raiz, '//ds:Reference[@URI="#comprobante"]/ds:DigestValue').text != sha1_c14n(sin_firma)


class TestErrores:

    def test_clave_incorrecta(self, firma):
        with pytest.raises(ErrorFirma, match='La clave no abre la firma electrónica'):
            firmar_xml(XML, firma[0], 'otra')

    def test_firma_vencida_o_aun_no_vigente(self):
        with pytest.raises(ErrorFirma, match='La firma electrónica venció el'):
            firmar_xml(XML, generar_p12(dias_inicio=-400, dias_fin=-1)[0], CLAVE)
        with pytest.raises(ErrorFirma, match='válida recién desde'):
            firmar_xml(XML, generar_p12(dias_inicio=2, dias_fin=30)[0], CLAVE)

    def test_comprobante_sin_id(self, firma):
        with pytest.raises(ErrorFirma, match='id="comprobante"'):
            firmar_xml('<factura version="1.0.0"/>', firma[0], CLAVE)


@pytest.mark.django_db
class TestFlujoDeEmision:

    def test_firm_xml_usa_la_firma_guardada_de_la_empresa(self, firma):
        empresa = helpers.crear_empresa('FIRMA')
        empresa.electronic_signature.save('firma.p12', ContentFile(firma[0]), save=False)
        empresa.electronic_signature_key = CLAVE
        empresa.save()
        comprobante = SimpleNamespace(company=empresa)
        respuesta = SRI().firm_xml(comprobante, XML)
        assert respuesta['resp'] is True and '<ds:SignatureValue' in respuesta['xml']
        empresa.electronic_signature_key = 'equivocada'
        respuesta = SRI().firm_xml(comprobante, XML)
        assert respuesta['resp'] is False
        assert respuesta['error'].startswith('La clave no abre la firma electrónica') and 'java' not in respuesta['error'].lower()

    def test_sin_firma_explica_donde_subirla(self):
        empresa = helpers.crear_empresa('SINFIRMA')
        respuesta = SRI().firm_xml(SimpleNamespace(company=empresa), XML)
        assert respuesta['error'] == 'Sube tu firma electrónica (.p12) en «Configuración de facturación», paso 4.'
