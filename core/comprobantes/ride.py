"""RIDE (representación impresa) de los comprobantes adicionales, con la clave de acceso en código de barras."""
import base64
from io import BytesIO

import barcode
from barcode.writer import ImageWriter
from django.core.files.base import ContentFile

from core.pos.utilities import printer


def codigo_de_barras(clave):
    """Code 128 de la clave de acceso con módulos de 0,254 mm = 3 px exactos a 300 ppp y zona libre de 10 módulos. Con el
    valor por defecto (0,2 mm = 2,36 px) las barras salían de 2 o 3 px y la lectura dependía de la resolución. El RIDE lo
    coloca a su tamaño natural de 86,6 mm (.barcode en facturaporaqui-ride.css)."""
    salida = BytesIO()
    barcode.Code128(clave, writer=ImageWriter(dpi=300)).write(salida, options={
        'module_width': 0.254, 'module_height': 13.0, 'quiet_zone': 2.54, 'text_distance': 3.0, 'font_size': 6})
    return f'data:image/png;base64,{base64.b64encode(salida.getvalue()).decode("ascii")}'


def guardar_ride(comprobante, plantilla):
    from core.pos.choices import PAYMENT_METHOD
    contexto = {'c': comprobante, 'empresa': comprobante.company, 'proveedor': comprobante.get_proveedor(),
                'access_code_barcode': codigo_de_barras(comprobante.access_code),
                'forma_pago': dict(PAYMENT_METHOD).get(getattr(comprobante, 'forma_pago', ''), '')}
    pdf = printer.create_pdf(context=contexto, template_name=plantilla)
    comprobante.pdf_authorized.save(f'{comprobante.receipt.get_name_xml()}_{comprobante.access_code}.pdf', ContentFile(pdf), save=False)
