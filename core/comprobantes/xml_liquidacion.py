"""XML de la liquidación de compra versión 1.1.0 (Anexo 17 de la ficha técnica offline).

El orden de los nodos sigue el XSD oficial. Montos con 2 decimales; cantidad y precio unitario con hasta 6 (versión 1.1.0).
"""
from xml.etree import ElementTree

from django.utils import timezone

from core.comprobantes.xml_retencion import CODIGO_PORCENTAJE_IVA, _m, _sub
from core.pos.choices import RETENTION_AGENT
from core.pos.models import informacion_adicional
from core.pos.utilities.sri import SRI


def _d6(valor):
    return f'{valor:.6f}'


def _codigo_porcentaje(tarifa):
    return CODIGO_PORCENTAJE_IVA[_m(tarifa)]


def generar_xml(liq):
    """(xml, clave de acceso) de la liquidación `liq`, con su fecha de emisión y clave fijas si ya las tiene."""
    company = liq.company
    fecha = liq.emission_date or timezone.localdate()
    clave = liq.access_code or SRI().create_access_key(liq, fecha)
    raiz = ElementTree.Element('liquidacionCompra', id='comprobante', version='1.1.0')

    it = ElementTree.SubElement(raiz, 'infoTributaria')
    for tag, valor in (('ambiente', liq.environment_type), ('tipoEmision', company.emission_type),
                       ('razonSocial', company.business_name), ('nombreComercial', company.tradename or company.business_name),
                       ('ruc', company.ruc), ('claveAcceso', clave), ('codDoc', liq.receipt.voucher_type),
                       ('estab', liq.receipt.establishment_code), ('ptoEmi', liq.receipt.issuing_point_code),
                       ('secuencial', liq.voucher_number), ('dirMatriz', company.main_address)):
        _sub(it, tag, valor)
    if company.retention_agent == RETENTION_AGENT[0][0]:
        _sub(it, 'agenteRetencion', '1')   # igual que en la factura y la nota de crédito

    info = ElementTree.SubElement(raiz, 'infoLiquidacionCompra')
    _sub(info, 'fechaEmision', fecha.strftime('%d/%m/%Y'))
    _sub(info, 'dirEstablecimiento', liq.receipt.establishment_address() or company.establishment_address or company.main_address)
    especial = (company.special_taxpayer or '').strip()
    if especial != '000' and 3 <= len(especial) <= 13 and especial.isalnum():
        _sub(info, 'contribuyenteEspecial', especial)
    _sub(info, 'obligadoContabilidad', company.obligated_accounting)
    _sub(info, 'tipoIdentificacionProveedor', liq.tipo_identificacion)
    _sub(info, 'razonSocialProveedor', liq.razon_social)
    _sub(info, 'identificacionProveedor', liq.identificacion)
    if liq.direccion:
        _sub(info, 'direccionProveedor', liq.direccion)
    _sub(info, 'totalSinImpuestos', _m(liq.total_sin_impuestos))
    _sub(info, 'totalDescuento', _m(liq.total_descuento))
    impuestos = ElementTree.SubElement(info, 'totalConImpuestos')
    for tarifa, base, iva in liq.impuestos_por_tarifa():
        imp = ElementTree.SubElement(impuestos, 'totalImpuesto')
        for tag, valor in (('codigo', 2), ('codigoPorcentaje', _codigo_porcentaje(tarifa)), ('baseImponible', _m(base)),
                           ('tarifa', _m(tarifa)), ('valor', _m(iva))):
            _sub(imp, tag, valor)
    _sub(info, 'importeTotal', _m(liq.importe_total))
    _sub(info, 'moneda', 'DOLAR')
    pago = ElementTree.SubElement(ElementTree.SubElement(info, 'pagos'), 'pago')
    _sub(pago, 'formaPago', liq.forma_pago)
    _sub(pago, 'total', _m(liq.importe_total))

    detalles = ElementTree.SubElement(raiz, 'detalles')
    for d in liq.detalles.all():
        det = ElementTree.SubElement(detalles, 'detalle')
        if d.codigo:
            _sub(det, 'codigoPrincipal', d.codigo)
        for tag, valor in (('descripcion', d.descripcion), ('cantidad', _d6(d.cantidad)), ('precioUnitario', _d6(d.precio_unitario)),
                           ('descuento', _m(d.descuento)), ('precioTotalSinImpuesto', _m(d.precio_total_sin_impuesto))):
            _sub(det, tag, valor)
        imp = ElementTree.SubElement(ElementTree.SubElement(det, 'impuestos'), 'impuesto')
        for tag, valor in (('codigo', 2), ('codigoPorcentaje', _codigo_porcentaje(d.tarifa_iva)), ('tarifa', _m(d.tarifa_iva)),
                           ('baseImponible', _m(d.precio_total_sin_impuesto)), ('valor', _m(d.valor_iva))):
            _sub(imp, tag, valor)

    informacion_adicional(raiz, [('Email', liq.correo), ('Concepto', liq.concepto)])
    return '<?xml version="1.0" encoding="UTF-8"?>' + ElementTree.tostring(raiz, encoding='unicode'), clave
