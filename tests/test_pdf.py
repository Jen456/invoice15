import io

import pytest
from pypdf import PdfReader

from core.pos.utilities import printer
from tests import helpers

pytestmark = pytest.mark.django_db


def test_pdf_de_venta(client, empresa, admin):
    cliente = helpers.crear_cliente('cliente.pdf', empresa, '0900000009', '0990000009')
    venta = helpers.crear_venta(empresa, cliente, admin, helpers.crear_producto(empresa))
    helpers.iniciar_sesion(client, admin)
    respuesta = client.get(f'/pos/sale/admin/print/invoice/{venta.id}/')
    assert respuesta.status_code == 200
    assert respuesta['Content-Type'] == 'application/pdf'
    assert respuesta.content.startswith(b'%PDF')
    pdf = PdfReader(io.BytesIO(respuesta.content))
    assert len(pdf.pages) == 1
    texto = pdf.pages[0].extract_text()
    assert 'EMPRESA A' in texto
    assert venta.voucher_number in texto


@pytest.mark.parametrize('url', ['https://example.org/logo.png', 'http://169.254.169.254/latest/', 'file:///etc/passwd'])
def test_el_pdf_no_lee_recursos_ajenos(url):
    with pytest.raises(ValueError):
        printer.LocalOnlyURLFetcher().fetch(url)


def test_el_pdf_lee_estaticos_del_disco():
    recurso = printer.LocalOnlyURLFetcher().fetch('https://app.facturaporaqui.com/static/img/default/logo.png')
    assert recurso.read(4) == b'\x89PNG'
