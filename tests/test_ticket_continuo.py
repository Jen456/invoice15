"""Ticket en papel continuo (printer.create_pdf_continuo): una sola hoja de 58 mm tan alta como el contenido, sin cortes
con muchas líneas o descripciones largas y sin papel en blanco al final (antes: 450 px + 10 px por línea, estimado)."""
from decimal import Decimal

import pypdfium2 as pdfium
import pytest

from core.pos.models import Product, SaleDetail
from core.tenancy.context import company_context
from tests import helpers
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, producto, web  # noqa: F401

pytestmark = pytest.mark.django_db
MM = 72 / 25.4


def ticket(web, empresa, comprador, dueno, lineas, descripcion='PRODUCTO', prefijo='T'):  # noqa: F811
    with company_context(empresa):
        base = helpers.crear_producto(empresa, f'{prefijo}000')
        venta = helpers.crear_venta(empresa, comprador, dueno, base, cantidad=1)
        for n in range(1, lineas):
            p = Product.objects.create(name=f'{descripcion} {n}', code=f'{prefijo}{n:03d}', category=base.category, price=Decimal('1'),
                                       pvp=Decimal('2.50'), stock=100)
            SaleDetail.objects.create(sale=venta, product=p, cant=2, price=Decimal('2.50'), subtotal=Decimal('5'), total=Decimal('5'))
    respuesta = web.get(f'/pos/sale/admin/print/invoice/{venta.pk}/')
    assert respuesta['Content-Type'] == 'application/pdf'
    return pdfium.PdfDocument(respuesta.content)


def medidas(pdf):
    """(páginas, ancho mm, alto mm, papel en blanco bajo el último carácter en mm, texto)."""
    pagina = pdf[0]
    ancho, alto = pagina.get_size()
    texto = pagina.get_textpage()
    abajo = min(texto.get_charbox(i)[1] for i in range(texto.count_chars()) if texto.get_text_range(i, 1).strip())
    return len(pdf), round(ancho / MM, 1), alto / MM, abajo / MM, texto.get_text_range()


class TestTicketContinuo:

    def test_una_hoja_de_58_mm_sin_papel_sobrante(self, web, empresa, comprador, dueno):  # noqa: F811
        paginas, ancho, alto, blanco, texto = medidas(ticket(web, empresa, comprador, dueno, 1))
        assert (paginas, ancho) == (1, 58.0)
        assert 0 < blanco < 12, blanco             # termina poco después del último renglón (antes quedaba un tercio vacío)
        assert 'TOTAL' in texto.upper()

    def test_muchas_lineas_largas_no_se_cortan(self, web, empresa, comprador, dueno):  # noqa: F811
        corta = medidas(ticket(web, empresa, comprador, dueno, 1))
        larga_desc = 'SERVICIO DE MANTENIMIENTO PREVENTIVO Y CORRECTIVO DE EQUIPOS DE CÓMPUTO CON REPUESTOS'
        paginas, ancho, alto, blanco, texto = medidas(ticket(web, empresa, comprador, dueno, 40, larga_desc, prefijo='L'))
        assert paginas == 1 and ancho == 58.0 and alto > corta[2] * 2
        assert 0 < blanco < 12                       # nada cae fuera de la hoja
        assert f'{larga_desc} 39'.replace(' ', '') in texto.upper().replace(' ', '').replace('\r', '').replace('\n', '')
