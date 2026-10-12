"""Firma XAdES-BES de comprobantes electrónicos según la ficha técnica del SRI (esquema offline).

Sustituye al jar Java original (sus bibliotecas MITyC nunca llegaron al repositorio): firma
enveloped con RSA-SHA1, resúmenes SHA-1 y canonicalización C14N inclusiva, con las tres
referencias que espera el SRI (propiedades firmadas, certificado y comprobante). La clave del
.p12 no sale del proceso: no pasa por la línea de órdenes ni por archivos temporales.
"""
import base64
import hashlib
import secrets

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from django.utils import timezone
from lxml import etree

DS = 'http://www.w3.org/2000/09/xmldsig#'
ETSI = 'http://uri.etsi.org/01903/v1.3.2#'
C14N = 'http://www.w3.org/TR/2001/REC-xml-c14n-20010315'
NSMAP = {'ds': DS, 'etsi': ETSI}


class ErrorFirma(Exception):
    """La firma no se pudo generar; el mensaje es para el usuario."""


def _ds(tag):
    return f'{{{DS}}}{tag}'


def _etsi(tag):
    return f'{{{ETSI}}}{tag}'


def _c14n(nodo):
    return etree.tostring(nodo, method='c14n', exclusive=False, with_comments=False)


def _b64(datos):
    return base64.b64encode(datos).decode('ascii')


def _sha1_b64(datos):
    return _b64(hashlib.sha1(datos).digest())


def _entero_b64(numero):
    return _b64(numero.to_bytes((numero.bit_length() + 7) // 8, 'big'))


def cargar_p12(contenido, clave, ahora=None):
    """Clave privada RSA y su certificado vigente. Lanza ErrorFirma con un mensaje claro."""
    ahora = ahora or timezone.now()
    try:
        p12 = pkcs12.load_pkcs12(contenido, clave.encode() if clave else None)
    except ValueError:
        raise ErrorFirma('La clave no abre la firma electrónica (.p12). Revísala en «Configuración de facturación», paso 4.')
    clave_privada = p12.key
    if not isinstance(clave_privada, rsa.RSAPrivateKey):
        raise ErrorFirma('La firma electrónica (.p12) no contiene una clave RSA para firmar.')
    publica = clave_privada.public_key().public_numbers()
    candidatos = [c.certificate for c in [p12.cert, *p12.additional_certs] if c is not None]
    certificado = next((c for c in candidatos if isinstance(c.public_key(), rsa.RSAPublicKey)
                        and c.public_key().public_numbers() == publica), None)
    if certificado is None:
        raise ErrorFirma('La firma electrónica (.p12) no contiene el certificado de su clave privada.')
    if ahora < certificado.not_valid_before_utc:
        raise ErrorFirma(f'La firma electrónica es válida recién desde el {timezone.localtime(certificado.not_valid_before_utc):%d/%m/%Y}.')
    if ahora > certificado.not_valid_after_utc:
        raise ErrorFirma(f'La firma electrónica venció el {timezone.localtime(certificado.not_valid_after_utc):%d/%m/%Y}. '
                         'Renuévala y súbela en «Configuración de facturación», paso 4.')
    return clave_privada, certificado


def firmar_xml(xml, contenido_p12, clave, ahora=None):
    """Devuelve el comprobante (raíz con id="comprobante") firmado en XAdES-BES, como texto UTF-8."""
    ahora = timezone.localtime(ahora or timezone.now())
    clave_privada, certificado = cargar_p12(contenido_p12, clave, ahora)
    datos = xml.encode('utf-8') if isinstance(xml, str) else xml
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    raiz = etree.fromstring(datos, parser)
    if raiz.get('id') != 'comprobante':
        raise ErrorFirma('El comprobante no tiene el atributo id="comprobante" que exige el SRI.')

    # Referencia al comprobante con transformación enveloped: se resume antes de añadir la firma.
    resumen_comprobante = _sha1_b64(_c14n(raiz))

    def ident():
        return str(secrets.randbelow(900000) + 100000)
    id_firma = f'Signature{ident()}'
    id_propiedades = f'{id_firma}-SignedProperties{ident()}'
    id_certificado = f'Certificate{ident()}'
    id_ref_comprobante = f'Reference-ID-{ident()}'

    firma = etree.SubElement(raiz, _ds('Signature'), nsmap=NSMAP, Id=id_firma)
    signed_info = etree.SubElement(firma, _ds('SignedInfo'), Id=f'Signature-SignedInfo{ident()}')
    etree.SubElement(signed_info, _ds('CanonicalizationMethod'), Algorithm=C14N)
    etree.SubElement(signed_info, _ds('SignatureMethod'), Algorithm=f'{DS}rsa-sha1')

    def referencia(uri, transformada=False, **atributos):
        ref = etree.SubElement(signed_info, _ds('Reference'), **atributos, URI=uri)
        if transformada:
            transforms = etree.SubElement(ref, _ds('Transforms'))
            etree.SubElement(transforms, _ds('Transform'), Algorithm=f'{DS}enveloped-signature')
        etree.SubElement(ref, _ds('DigestMethod'), Algorithm=f'{DS}sha1')
        return etree.SubElement(ref, _ds('DigestValue'))

    resumen_propiedades = referencia(f'#{id_propiedades}', Id=f'SignedPropertiesID{ident()}',
                                     Type='http://uri.etsi.org/01903#SignedProperties')
    resumen_certificado = referencia(f'#{id_certificado}')
    referencia('#comprobante', transformada=True, Id=id_ref_comprobante).text = resumen_comprobante

    valor = etree.SubElement(firma, _ds('SignatureValue'), Id=f'SignatureValue{ident()}')

    der = certificado.public_bytes(serialization.Encoding.DER)
    key_info = etree.SubElement(firma, _ds('KeyInfo'), Id=id_certificado)
    etree.SubElement(etree.SubElement(key_info, _ds('X509Data')), _ds('X509Certificate')).text = _b64(der)
    numeros = certificado.public_key().public_numbers()
    rsa_valor = etree.SubElement(etree.SubElement(key_info, _ds('KeyValue')), _ds('RSAKeyValue'))
    etree.SubElement(rsa_valor, _ds('Modulus')).text = _entero_b64(numeros.n)
    etree.SubElement(rsa_valor, _ds('Exponent')).text = _entero_b64(numeros.e)

    objeto = etree.SubElement(firma, _ds('Object'), Id=f'{id_firma}-Object{ident()}')
    calificadoras = etree.SubElement(objeto, _etsi('QualifyingProperties'), Target=f'#{id_firma}')
    propiedades = etree.SubElement(calificadoras, _etsi('SignedProperties'), Id=id_propiedades)
    firmadas = etree.SubElement(propiedades, _etsi('SignedSignatureProperties'))
    etree.SubElement(firmadas, _etsi('SigningTime')).text = ahora.isoformat(timespec='seconds')
    cert = etree.SubElement(etree.SubElement(firmadas, _etsi('SigningCertificate')), _etsi('Cert'))
    resumen_cert = etree.SubElement(cert, _etsi('CertDigest'))
    etree.SubElement(resumen_cert, _ds('DigestMethod'), Algorithm=f'{DS}sha1')
    etree.SubElement(resumen_cert, _ds('DigestValue')).text = _sha1_b64(der)
    emisor = etree.SubElement(cert, _etsi('IssuerSerial'))
    etree.SubElement(emisor, _ds('X509IssuerName')).text = certificado.issuer.rfc4514_string()
    etree.SubElement(emisor, _ds('X509SerialNumber')).text = str(certificado.serial_number)
    formato = etree.SubElement(etree.SubElement(propiedades, _etsi('SignedDataObjectProperties')),
                               _etsi('DataObjectFormat'), ObjectReference=f'#{id_ref_comprobante}')
    etree.SubElement(formato, _etsi('Description')).text = 'contenido comprobante'
    etree.SubElement(formato, _etsi('MimeType')).text = 'text/xml'

    # Los resúmenes de KeyInfo y SignedProperties se calculan ya dentro del documento (C14N
    # inclusiva lleva los espacios de nombres ds y etsi declarados en Signature).
    resumen_certificado.text = _sha1_b64(_c14n(key_info))
    resumen_propiedades.text = _sha1_b64(_c14n(propiedades))
    valor.text = _b64(clave_privada.sign(_c14n(signed_info), padding.PKCS1v15(), hashes.SHA1()))
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + etree.tostring(raiz, encoding='unicode')
