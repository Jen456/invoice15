"""Documentos impresos: el ticket de una factura no muestra usuario ni clave del portal (la clave era la
cédula), dice «FACTURA N°», y el ticket y el RIDE muestran los datos del proveedor sin teléfono."""
import io

import pytest
from django.template.loader import render_to_string
from pypdf import PdfReader

from core.tenancy.context import company_context
from tests import helpers

pytestmark = pytest.mark.django_db


@pytest.fixture
def venta(settings, empresa, admin):
    settings.FPA_RUC_PROVEEDOR = "0941609729001"
    cliente = helpers.crear_cliente("cliente.impreso", empresa, "0912345675", "0990000009")
    return helpers.crear_venta(empresa, cliente, admin, helpers.crear_producto(empresa))


def test_ticket_de_factura(client, admin, venta):
    helpers.iniciar_sesion(client, admin)
    respuesta = client.get(f"/pos/sale/admin/print/invoice/{venta.id}/")
    texto = " ".join(PdfReader(io.BytesIO(respuesta.content)).pages[0].extract_text().split()).upper()   # el ticket imprime en mayúsculas
    assert f"FACTURA N° {venta.voucher_number_full}" in texto and "TICKET N°" not in texto
    assert "FACTURAPORAQUI" in texto and "0941609729001" in texto and "SOPORTE@FACTURAPORAQUI.COM" in texto
    assert "MILAGRO, MANTA Y RUMIÑAHUI" in texto
    assert " Y CLAVE " not in texto and "SU USUARIO" not in texto and "PORTAL" not in texto
    assert "%%" not in texto and "CONTRIBUYENTE ESPECIAL" not in texto   # la empresa no es contribuyente especial


def test_ride_con_datos_del_proveedor(venta):
    with company_context(venta.company):
        html = render_to_string("sale/format/invoice.html", {"sale": venta, "access_code_barcode": ""})
    for dato in ("RUC Proveedor", "0941609729001", "FACTURAPORAQUI", "soporte@facturaporaqui.com", "Milagro, Manta y Rumiñahui"):
        assert dato in html
    assert "Contribuyente Especial" not in html
