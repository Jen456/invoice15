"""XML de la nota de débito versión 1.0.0 (ficha técnica offline, formato XML nota de débito).

El orden de los nodos sigue el XSD oficial. Montos con 2 decimales; numDocModificado con guiones (001-001-000000001).
"""
from xml.etree import ElementTree

from django.utils import timezone

from core.comprobantes.xml_retencion import CODIGO_PORCENTAJE_IVA, _m, _sub
from core.pos.choices import RETENTION_AGENT
from core.pos.models import informacion_adicional
from core.pos.utilities.sri import SRI


def generar_xml(nota):
    """(xml, clave de acceso) de la nota de débito `nota`, con su fecha de emisión y clave fijas si ya las tiene."""
    company = nota.company
    fecha = nota.emission_date or timezone.localdate()
    clave = nota.access_code or SRI().create_access_key(nota, fecha)
    raiz = ElementTree.Element('notaDebito', id='comprobante', version='1.0.0')

    it = ElementTree.SubElement(raiz, 'infoTributaria')
    for tag, valor in (('ambiente', nota.environment_type), ('tipoEmision', company.emission_type),
                       ('razonSocial', company.business_name), ('nombreComercial', company.tradename or company.business_name),
                       ('ruc', company.ruc), ('claveAcceso', clave), ('codDoc', nota.receipt.voucher_type),
                       ('estab', nota.receipt.establishment_code), ('ptoEmi', nota.receipt.issuing_point_code),
                       ('secuencial', nota.voucher_number), ('dirMatriz', company.main_address)):
        _sub(it, tag, valor)
    if company.retention_agent == RETENTION_AGENT[0][0]:
        _sub(it, 'agenteRetencion', '1')   # igual que en la factura y la nota de crédito

    info = ElementTree.SubElement(raiz, 'infoNotaDebito')
    _sub(info, 'fechaEmision', fecha.strftime('%d/%m/%Y'))
    _sub(info, 'dirEstablecimiento', nota.receipt.establishment_address() or company.establishment_address or company.main_address)
    _sub(info, 'tipoIdentificacionComprador', nota.tipo_identificacion)
    _sub(info, 'razonSocialComprador', nota.razon_social)
    _sub(info, 'identificacionComprador', nota.identificacion)
    especial = (company.special_taxpayer or '').strip()
    if especial != '000' and 3 <= len(especial) <= 13 and especial.isalnum():
        _sub(info, 'contribuyenteEspecial', especial)
    _sub(info, 'obligadoContabilidad', company.obligated_accounting)
    _sub(info, 'codDocModificado', nota.cod_doc_modificado)
    _sub(info, 'numDocModificado', nota.num_doc_modificado)
    _sub(info, 'fechaEmisionDocSustento', nota.fecha_doc_sustento.strftime('%d/%m/%Y'))
    _sub(info, 'totalSinImpuestos', _m(nota.total_sin_impuestos))
    imp = ElementTree.SubElement(ElementTree.SubElement(info, 'impuestos'), 'impuesto')
    for tag, valor in (('codigo', 2), ('codigoPorcentaje', CODIGO_PORCENTAJE_IVA[_m(nota.tarifa_iva)]), ('tarifa', _m(nota.tarifa_iva)),
                       ('baseImponible', _m(nota.total_sin_impuestos)), ('valor', _m(nota.valor_iva))):
        _sub(imp, tag, valor)
    _sub(info, 'valorTotal', _m(nota.valor_total))
    pago = ElementTree.SubElement(ElementTree.SubElement(info, 'pagos'), 'pago')
    _sub(pago, 'formaPago', nota.forma_pago)
    _sub(pago, 'total', _m(nota.valor_total))

    motivos = ElementTree.SubElement(raiz, 'motivos')
    for m in nota.motivos.all():
        motivo = ElementTree.SubElement(motivos, 'motivo')
        _sub(motivo, 'razon', m.razon)
        _sub(motivo, 'valor', _m(m.valor))

    informacion_adicional(raiz, [('Dirección', nota.direccion), ('Email', nota.correo)])
    return '<?xml version="1.0" encoding="UTF-8"?>' + ElementTree.tostring(raiz, encoding='unicode'), clave
