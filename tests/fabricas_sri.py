"""Comprobantes y respuestas del SRI ficticios para las pruebas de importación (ningún documento real)."""
from datetime import date
from xml.sax.saxutils import escape

from core.importacion.clave_acceso import digito_verificador

RUC_EMISOR = '0990000001001'
RUC_RECEPTOR = '0991234567001'


def clave(fecha=date(2026, 10, 10), cod_doc='01', ruc=RUC_EMISOR, ambiente=2, estab='001', pto='002', secuencial='000000271',
          codigo='12345678', tipo_emision='1'):
    base = f'{fecha:%d%m%Y}{cod_doc}{ruc}{ambiente}{estab}{pto}{secuencial}{codigo}{tipo_emision}'
    return base + digito_verificador(base)


def factura(ruc=RUC_EMISOR, razon='PROVEEDOR FICTICIO S.A.', receptor_tipo='04', receptor_id=RUC_RECEPTOR,
            receptor_nombre="EMPRESA D'PRUEBA S.A.", fecha=date(2026, 10, 10), ambiente=2, estab='001', pto='002',
            secuencial='000000271', impuestos=(('2', '4', '15.00', '100.00', '15.00'), ('2', '0', '0.00', '20.00', '0.00')),
            total_sin='120.00', descuento='0.00', propina='0.00', importe='135.00', clave_acceso=None, ns='', version='2.1.0',
            cod_doc='01', lineas=(('Servicio ficticio', '100.00'), ('Producto sin IVA', '20.00')), pagos=(('20', '135.00'),)):
    clave_acceso = clave_acceso or clave(fecha, cod_doc, ruc, ambiente, estab, pto, secuencial)
    xmlns = f' xmlns="{ns}"' if ns else ''
    totales = ''.join(f'<totalImpuesto><codigo>{c}</codigo><codigoPorcentaje>{p}</codigoPorcentaje><descuentoAdicional>0.00'
                      f'</descuentoAdicional><baseImponible>{b}</baseImponible><tarifa>{t}</tarifa><valor>{v}</valor></totalImpuesto>'
                      for c, p, t, b, v in impuestos)
    detalles = ''.join(f'<detalle><codigoPrincipal>P{i}</codigoPrincipal><descripcion>{escape(d)}</descripcion><cantidad>1.00</cantidad>'
                       f'<precioUnitario>{v}</precioUnitario><descuento>0.00</descuento><precioTotalSinImpuesto>{v}</precioTotalSinImpuesto>'
                       f'<impuestos><impuesto><codigo>2</codigo><codigoPorcentaje>4</codigoPorcentaje><tarifa>15</tarifa>'
                       f'<baseImponible>{v}</baseImponible><valor>0.00</valor></impuesto></impuestos></detalle>'
                       for i, (d, v) in enumerate(lineas))
    pagos_xml = ''.join(f'<pago><formaPago>{f}</formaPago><total>{t}</total></pago>' for f, t in pagos)
    raiz = {'01': 'factura', '04': 'notaCredito', '05': 'notaDebito', '07': 'comprobanteRetencion'}[cod_doc]
    return (f'<?xml version="1.0" encoding="UTF-8"?><{raiz}{xmlns} id="comprobante" version="{version}"><infoTributaria>'
            f'<ambiente>{ambiente}</ambiente><tipoEmision>1</tipoEmision><razonSocial>{escape(razon)}</razonSocial>'
            f'<nombreComercial>FICTICIO</nombreComercial><ruc>{ruc}</ruc><claveAcceso>{clave_acceso}</claveAcceso>'
            f'<codDoc>{cod_doc}</codDoc><estab>{estab}</estab><ptoEmi>{pto}</ptoEmi><secuencial>{secuencial}</secuencial>'
            f'<dirMatriz>Av. Ficticia 1</dirMatriz></infoTributaria><infoFactura><fechaEmision>{fecha:%d/%m/%Y}</fechaEmision>'
            f'<dirEstablecimiento>Av. Ficticia 1</dirEstablecimiento><obligadoContabilidad>SI</obligadoContabilidad>'
            f'<tipoIdentificacionComprador>{receptor_tipo}</tipoIdentificacionComprador>'
            f'<razonSocialComprador>{escape(receptor_nombre)}</razonSocialComprador>'
            f'<identificacionComprador>{receptor_id}</identificacionComprador><totalSinImpuestos>{total_sin}</totalSinImpuestos>'
            f'<totalDescuento>{descuento}</totalDescuento><totalConImpuestos>{totales}</totalConImpuestos><propina>{propina}</propina>'
            f'<importeTotal>{importe}</importeTotal><moneda>DOLAR</moneda><pagos>{pagos_xml}</pagos></infoFactura>'
            f'<detalles>{detalles}</detalles><infoAdicional><campoAdicional nombre="Email">compras@example.com</campoAdicional>'
            f'</infoAdicional></{raiz}>')


def autorizacion(comprobante, modo='cdata', estado='AUTORIZADO', numero=None, ambiente='PRODUCCIÓN', fecha='2026-10-10T10:15:22-05:00'):
    """<autorizacion> como la entrega el SRI. modo: cdata | escapado | hijo."""
    numero = numero if numero is not None else _clave_de(comprobante)
    if modo == 'cdata':
        cuerpo = f'<![CDATA[{comprobante}]]>'
    elif modo == 'escapado':
        cuerpo = escape(comprobante)
    else:
        cuerpo = comprobante.split('?>', 1)[1]
    return (f'<?xml version="1.0" encoding="UTF-8"?><autorizacion><estado>{estado}</estado>'
            f'<numeroAutorizacion>{numero}</numeroAutorizacion><fechaAutorizacion>{fecha}</fechaAutorizacion>'
            f'<ambiente>{ambiente}</ambiente><comprobante>{cuerpo}</comprobante><mensajes/></autorizacion>')


def respuesta_sri(comprobantes, estado='AUTORIZADO', soap=False):
    """RespuestaAutorizacionComprobante con una <autorizacion> por comprobante (opcionalmente dentro de un sobre SOAP)."""
    autorizaciones = ''.join(autorizacion(c, estado=estado).split('?>', 1)[1] for c in comprobantes)
    clave_consultada = _clave_de(comprobantes[0]) if comprobantes else ''
    respuesta = (f'<ns2:RespuestaAutorizacionComprobante xmlns:ns2="http://ec.gob.sri.ws.autorizacion">'
                 f'<claveAccesoConsultada>{clave_consultada}</claveAccesoConsultada><numeroComprobantes>{len(comprobantes)}</numeroComprobantes>'
                 f'<autorizaciones>{autorizaciones}</autorizaciones></ns2:RespuestaAutorizacionComprobante>')
    if soap:
        return (f'<?xml version="1.0" encoding="UTF-8"?><soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
                f'<soap:Body><ns2:autorizacionComprobanteResponse xmlns:ns2="http://ec.gob.sri.ws.autorizacion">{respuesta}'
                f'</ns2:autorizacionComprobanteResponse></soap:Body></soap:Envelope>')
    return '<?xml version="1.0" encoding="UTF-8"?>' + respuesta


def _clave_de(comprobante):
    return comprobante.split('<claveAcceso>', 1)[1].split('</claveAcceso>', 1)[0]


def pdf(*simbolos, texto=None, paginas=1):
    """PDF ficticio con códigos (('qr'|'barras', contenido), …) y, opcionalmente, una línea de texto real incrustado."""
    import io

    import zxingcpp
    from PIL import Image
    formatos = {'qr': zxingcpp.BarcodeFormat.QRCode, 'barras': zxingcpp.BarcodeFormat.Code128}
    lienzo = Image.new('L', (1240, 1754), 255)
    y = 80
    for tipo, contenido in simbolos:
        imagen = zxingcpp.create_barcode(contenido, formatos[tipo]).to_image(scale=4 if tipo == 'qr' else 2)
        imagen = imagen if isinstance(imagen, Image.Image) else Image.fromarray(imagen)
        lienzo.paste(imagen, (80, y))
        y += imagen.size[1] + 60
    if texto is not None:   # texto incrustado (seleccionable), como en un RIDE generado por software
        from weasyprint import HTML
        return HTML(string=f'<p style="font-size:9pt">{texto}</p>').write_pdf()
    buffer = io.BytesIO()
    lienzo.save(buffer, 'PDF', resolution=150, save_all=True, append_images=[lienzo.copy() for _ in range(paginas - 1)])
    return buffer.getvalue()
