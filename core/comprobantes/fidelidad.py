"""¿El RIDE (PDF) dice lo mismo que el XML autorizado? Antes de reemplazar un RIDE guardado por uno regenerado con la
plantilla actual: el PDF nuevo se arma con los datos de hoy (cliente, productos), que pueden haber cambiado después de
autorizar. Se comprueba que cada dato del XML autorizado aparezca en el texto del PDF: número, clave y autorización, fechas,
emisor y direcciones, comprador, cada detalle (código, descripción, cantidad, precios), totales por tarifa e información adicional.

Se compara sin espacios ni mayúsculas (los saltos de línea del PDF no cuentan) y se aceptan las formas en que la plantilla
escribe números (1440,00 / 1.440,00 / 1440.00) y fechas (24/10/2026 / 2026-10-24)."""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pypdfium2 as pdfium
from lxml import etree


def texto_del_pdf(contenido):
    pdf = pdfium.PdfDocument(contenido)
    try:
        return '\n'.join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
    finally:
        pdf.close()


def _plano(texto):
    return re.sub(r'\s+', '', texto or '').lower()


def _dinero(valor):
    try:
        numero = Decimal(valor)
    except (InvalidOperation, TypeError):
        return [valor]
    fijo = f'{numero:.2f}'
    entero, decimales = fijo.split('.')
    miles = f'{int(entero):,}'.replace(',', '.') if not entero.startswith('-') else entero
    return [f'{entero},{decimales}', f'{miles},{decimales}', fijo]


def _cantidad(valor):
    numero = Decimal(valor)
    formas = _dinero(valor)
    if numero == numero.to_integral_value():
        formas.insert(0, str(int(numero)))
    return formas


def _fecha(valor):
    texto = (valor or '').strip()[:10]
    try:
        fecha = datetime.strptime(texto, '%d/%m/%Y').date()
    except ValueError:
        return [texto]
    return [fecha.strftime('%d/%m/%Y'), fecha.isoformat()]


def datos_autorizados(xml_autorizado):
    """[(campo, [formas aceptadas])] del XML autorizado (formato <autorizacion> con el comprobante en CDATA)."""
    raiz = etree.fromstring(xml_autorizado)
    comprobante = raiz.findtext('comprobante') if raiz.tag == 'autorizacion' else None
    factura = etree.fromstring(comprobante.encode()) if comprobante else raiz
    datos = []

    def agregar(campo, valor, formas=None):
        if valor not in (None, ''):
            datos.append((campo, formas(valor) if formas else [valor]))

    it, info = factura.find('infoTributaria'), factura.find('infoFactura')
    agregar('número de autorización', raiz.findtext('numeroAutorizacion') or it.findtext('claveAcceso'))
    agregar('fecha de autorización', raiz.findtext('fechaAutorizacion'), _fecha)
    agregar('clave de acceso', it.findtext('claveAcceso'))
    agregar('número', f"{it.findtext('estab')}-{it.findtext('ptoEmi')}-{it.findtext('secuencial')}")
    agregar('RUC del emisor', it.findtext('ruc'))
    agregar('razón social del emisor', it.findtext('razonSocial'))
    agregar('dirección matriz', it.findtext('dirMatriz'))
    agregar('dirección del establecimiento', info.findtext('dirEstablecimiento'))
    agregar('fecha de emisión', info.findtext('fechaEmision'), _fecha)
    agregar('comprador', info.findtext('razonSocialComprador'))
    agregar('identificación del comprador', info.findtext('identificacionComprador'))
    for n, d in enumerate(factura.iterfind('detalles/detalle'), start=1):
        agregar(f'detalle {n}: código', d.findtext('codigoPrincipal'))
        agregar(f'detalle {n}: descripción', d.findtext('descripcion'))
        agregar(f'detalle {n}: cantidad', d.findtext('cantidad'), _cantidad)
        agregar(f'detalle {n}: precio unitario', d.findtext('precioUnitario'), _dinero)
        agregar(f'detalle {n}: descuento', d.findtext('descuento'), _dinero)
        agregar(f'detalle {n}: total sin impuestos', d.findtext('precioTotalSinImpuesto'), _dinero)
    agregar('total sin impuestos', info.findtext('totalSinImpuestos'), _dinero)
    agregar('total descuento', info.findtext('totalDescuento'), _dinero)
    for t in info.iterfind('totalConImpuestos/totalImpuesto'):
        agregar(f"base imponible (código {t.findtext('codigoPorcentaje')})", t.findtext('baseImponible'), _dinero)
        agregar(f"IVA (código {t.findtext('codigoPorcentaje')})", t.findtext('valor'), _dinero)
    agregar('importe total', info.findtext('importeTotal'), _dinero)
    for campo in factura.iterfind('infoAdicional/campoAdicional'):
        agregar(f"información adicional: {campo.get('nombre')}", (campo.text or '').strip())
    return datos


def diferencias(pdf, xml_autorizado):
    """Datos del XML autorizado que no aparecen en el PDF: [(campo, valor esperado)]. Vacío = fiel."""
    plano = _plano(texto_del_pdf(pdf))
    return [(campo, formas[0]) for campo, formas in datos_autorizados(xml_autorizado)
            if not any(_plano(forma) in plano for forma in formas)]
