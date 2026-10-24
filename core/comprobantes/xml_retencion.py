"""XML del comprobante de retención versión 2.0.0 (Anexo 10 de la ficha técnica offline v2.34).

El orden de los nodos sigue el XSD oficial. Montos con 2 decimales; fechas dd/mm/aaaa; período fiscal mm/aaaa.
"""
from xml.etree import ElementTree

from django.utils import timezone

from core.pos.models import info_tributaria_final, informacion_adicional
from core.pos.utilities.sri import SRI

# Tabla 17 de la ficha: código de porcentaje de IVA según la tarifa.
CODIGO_PORCENTAJE_IVA = {'0.00': '0', '12.00': '2', '14.00': '3', '15.00': '4', '5.00': '5', '13.00': '10', '8.00': '8'}


def _sub(padre, tag, texto):
    nodo = ElementTree.SubElement(padre, tag)
    nodo.text = str(texto)
    return nodo


def _m(valor):
    return f'{valor:.2f}'


def generar_xml(ret):
    """(xml, clave de acceso) de la retención `ret`, con su fecha de emisión y clave fijas si ya las tiene."""
    company = ret.company
    fecha = ret.emission_date or timezone.localdate()
    clave = ret.access_code or SRI().create_access_key(ret, fecha)
    raiz = ElementTree.Element('comprobanteRetencion', id='comprobante', version='2.0.0')

    it = ElementTree.SubElement(raiz, 'infoTributaria')
    for tag, valor in (('ambiente', ret.environment_type), ('tipoEmision', company.emission_type),
                       ('razonSocial', company.business_name), ('nombreComercial', company.tradename or company.business_name),
                       ('ruc', company.ruc), ('claveAcceso', clave), ('codDoc', ret.receipt.voucher_type),
                       ('estab', ret.receipt.establishment_code), ('ptoEmi', ret.receipt.issuing_point_code),
                       ('secuencial', ret.voucher_number), ('dirMatriz', company.main_address)):
        _sub(it, tag, valor)
    info_tributaria_final(company, it)   # agenteRetencion y contribuyenteRimpe (Anexo 22)

    info = ElementTree.SubElement(raiz, 'infoCompRetencion')
    _sub(info, 'fechaEmision', fecha.strftime('%d/%m/%Y'))
    _sub(info, 'dirEstablecimiento', ret.receipt.establishment_address() or company.establishment_address or company.main_address)
    especial = (company.special_taxpayer or '').strip()
    if especial != '000' and 3 <= len(especial) <= 5:   # el XSD 2.0.0 admite de 3 a 5 caracteres
        _sub(info, 'contribuyenteEspecial', especial)
    _sub(info, 'obligadoContabilidad', company.obligated_accounting)
    _sub(info, 'tipoIdentificacionSujetoRetenido', ret.tipo_identificacion)
    if ret.tipo_identificacion == '08':
        _sub(info, 'tipoSujetoRetenido', ret.tipo_sujeto or '01')
    _sub(info, 'parteRel', 'SI' if ret.parte_relacionada else 'NO')
    _sub(info, 'razonSocialSujetoRetenido', ret.razon_social)
    _sub(info, 'identificacionSujetoRetenido', ret.identificacion)
    _sub(info, 'periodoFiscal', fecha.strftime('%m/%Y'))

    doc = ElementTree.SubElement(ElementTree.SubElement(raiz, 'docsSustento'), 'docSustento')
    _sub(doc, 'codSustento', ret.cod_sustento)
    _sub(doc, 'codDocSustento', ret.cod_doc_sustento)
    _sub(doc, 'numDocSustento', ret.num_doc_sustento)
    _sub(doc, 'fechaEmisionDocSustento', ret.fecha_doc_sustento.strftime('%d/%m/%Y'))
    _sub(doc, 'numAutDocSustento', ret.aut_doc_sustento)
    _sub(doc, 'pagoLocExt', '01')   # pago local
    _sub(doc, 'totalSinImpuestos', _m(ret.total_sin_impuestos))
    _sub(doc, 'importeTotal', _m(ret.importe_total))
    impuestos = ElementTree.SubElement(doc, 'impuestosDocSustento')
    if ret.base_0 > 0:
        imp = ElementTree.SubElement(impuestos, 'impuestoDocSustento')
        for tag, valor in (('codImpuestoDocSustento', 2), ('codigoPorcentaje', '0'), ('baseImponible', _m(ret.base_0)),
                           ('tarifa', '0.00'), ('valorImpuesto', '0.00')):
            _sub(imp, tag, valor)
    if ret.base_iva > 0:
        imp = ElementTree.SubElement(impuestos, 'impuestoDocSustento')
        for tag, valor in (('codImpuestoDocSustento', 2), ('codigoPorcentaje', CODIGO_PORCENTAJE_IVA.get(_m(ret.tarifa_iva), '4')),
                           ('baseImponible', _m(ret.base_iva)), ('tarifa', _m(ret.tarifa_iva)), ('valorImpuesto', _m(ret.valor_iva))):
            _sub(imp, tag, valor)
    retenciones = ElementTree.SubElement(doc, 'retenciones')
    for d in ret.detalles.all():
        r = ElementTree.SubElement(retenciones, 'retencion')
        for tag, valor in (('codigo', d.impuesto), ('codigoRetencion', d.codigo), ('baseImponible', _m(d.base_imponible)),
                           ('porcentajeRetener', _m(d.porcentaje)), ('valorRetenido', _m(d.valor_retenido))):
            _sub(r, tag, valor)
    pago = ElementTree.SubElement(ElementTree.SubElement(doc, 'pagos'), 'pago')
    _sub(pago, 'formaPago', ret.forma_pago)
    _sub(pago, 'total', _m(ret.importe_total))

    informacion_adicional(raiz, [('Dirección', ret.provider.address), ('Email', ret.correo)])
    return '<?xml version="1.0" encoding="UTF-8"?>' + ElementTree.tostring(raiz, encoding='unicode'), clave
