"""RIDE (representación impresa) de los comprobantes adicionales, con la clave de acceso en código de barras."""
import base64
from io import BytesIO

import barcode
from barcode.writer import ImageWriter
from django.core.files.base import ContentFile

from core.pos.utilities import printer


def codigo_de_barras(clave):
    salida = BytesIO()
    barcode.Code128(clave, writer=ImageWriter()).write(salida, options={'text_distance': 3.0, 'font_size': 6})
    return f'data:image/png;base64,{base64.b64encode(salida.getvalue()).decode("ascii")}'


def guardar_ride(comprobante, plantilla):
    from core.pos.choices import PAYMENT_METHOD
    contexto = {'c': comprobante, 'empresa': comprobante.company, 'proveedor': comprobante.get_proveedor(),
                'access_code_barcode': codigo_de_barras(comprobante.access_code),
                'forma_pago': dict(PAYMENT_METHOD).get(getattr(comprobante, 'forma_pago', ''), '')}
    pdf = printer.create_pdf(context=contexto, template_name=plantilla)
    comprobante.pdf_authorized.save(f'{comprobante.receipt.get_name_xml()}_{comprobante.access_code}.pdf', ContentFile(pdf), save=False)
