"""XML de la guía de remisión versión 1.1.0 (ficha técnica offline, formato XML guía de remisión).

El orden de los nodos sigue el XSD oficial. Fechas dd/mm/aaaa; cantidad con hasta 6 decimales; un destinatario por guía.
"""
from xml.etree import ElementTree

from django.utils import timezone

from core.comprobantes.xml_retencion import _sub
from core.pos.choices import RETENTION_AGENT
from core.pos.models import informacion_adicional
from core.pos.utilities.sri import SRI


def generar_xml(guia):
    """(xml, clave de acceso) de la guía `guia`, con su fecha de emisión y clave fijas si ya las tiene."""
    company = guia.company
    fecha = guia.emission_date or timezone.localdate()
    clave = guia.access_code or SRI().create_access_key(guia, fecha)
    raiz = ElementTree.Element('guiaRemision', id='comprobante', version='1.1.0')

    it = ElementTree.SubElement(raiz, 'infoTributaria')
    for tag, valor in (('ambiente', guia.environment_type), ('tipoEmision', company.emission_type),
                       ('razonSocial', company.business_name), ('nombreComercial', company.tradename or company.business_name),
                       ('ruc', company.ruc), ('claveAcceso', clave), ('codDoc', guia.receipt.voucher_type),
                       ('estab', guia.receipt.establishment_code), ('ptoEmi', guia.receipt.issuing_point_code),
                       ('secuencial', guia.voucher_number), ('dirMatriz', company.main_address)):
        _sub(it, tag, valor)
    if company.retention_agent == RETENTION_AGENT[0][0]:
        _sub(it, 'agenteRetencion', '1')   # igual que en la factura y la nota de crédito

    info = ElementTree.SubElement(raiz, 'infoGuiaRemision')
    _sub(info, 'dirEstablecimiento', guia.receipt.establishment_address() or company.establishment_address or company.main_address)
    _sub(info, 'dirPartida', guia.dir_partida)
    _sub(info, 'razonSocialTransportista', guia.transportista_razon_social)
    _sub(info, 'tipoIdentificacionTransportista', guia.transportista_tipo_identificacion)
    _sub(info, 'rucTransportista', guia.transportista_identificacion)
    _sub(info, 'obligadoContabilidad', company.obligated_accounting)
    especial = (company.special_taxpayer or '').strip()
    if especial != '000' and 3 <= len(especial) <= 13 and especial.isalnum():
        _sub(info, 'contribuyenteEspecial', especial)
    _sub(info, 'fechaIniTransporte', guia.fecha_inicio.strftime('%d/%m/%Y'))
    _sub(info, 'fechaFinTransporte', guia.fecha_fin.strftime('%d/%m/%Y'))
    _sub(info, 'placa', guia.placa)

    destinatario = ElementTree.SubElement(ElementTree.SubElement(raiz, 'destinatarios'), 'destinatario')
    for tag, valor in (('identificacionDestinatario', guia.identificacion), ('razonSocialDestinatario', guia.razon_social),
                       ('dirDestinatario', guia.direccion), ('motivoTraslado', guia.motivo)):
        _sub(destinatario, tag, valor)
    for tag, valor in (('docAduaneroUnico', guia.doc_aduanero), ('codEstabDestino', guia.cod_estab_destino), ('ruta', guia.ruta)):
        if valor:
            _sub(destinatario, tag, valor)
    if guia.num_doc_sustento:
        _sub(destinatario, 'codDocSustento', guia.cod_doc_sustento)
        _sub(destinatario, 'numDocSustento', guia.num_doc_sustento)
        if guia.aut_doc_sustento:
            _sub(destinatario, 'numAutDocSustento', guia.aut_doc_sustento)
        if guia.fecha_doc_sustento:
            _sub(destinatario, 'fechaEmisionDocSustento', guia.fecha_doc_sustento.strftime('%d/%m/%Y'))
    detalles = ElementTree.SubElement(destinatario, 'detalles')
    for d in guia.detalles.all():
        detalle = ElementTree.SubElement(detalles, 'detalle')
        if d.codigo:
            _sub(detalle, 'codigoInterno', d.codigo)
        _sub(detalle, 'descripcion', d.descripcion)
        _sub(detalle, 'cantidad', f'{d.cantidad:.6f}')

    informacion_adicional(raiz, [('Email', guia.correo)])
    return '<?xml version="1.0" encoding="UTF-8"?>' + ElementTree.tostring(raiz, encoding='unicode'), clave
