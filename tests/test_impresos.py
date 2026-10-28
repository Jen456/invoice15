"""Documentos impresos: el ticket de una factura no muestra usuario ni clave del portal (la clave era la
cédula), identifica la factura y su número, y el ticket y el RIDE muestran los datos del proveedor sin teléfono.
La cabecera del ticket usa los mismos datos que el XML (direcciones y fecha de emisión) y no imprime «None»."""
import io
from datetime import date, datetime
from xml.etree import ElementTree

import pytest
from django.template.loader import render_to_string
from pypdf import PdfReader

from core.pos.models import Company, Establishment, Sale
from core.tenancy.context import company_context
from core.user.models import User
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
    # Normalizar espacios y caja; el diseño usa texto natural y la abreviatura «N.º».
    texto = " ".join(PdfReader(io.BytesIO(respuesta.content)).pages[0].extract_text().split()).upper()
    assert f"FACTURA N.º {venta.voucher_number_full}" in texto and "TICKET N.º" not in texto
    assert "FACTURAPORAQUI" in texto and "0941609729001" in texto and "SOPORTE@FACTURAPORAQUI.COM" in texto
    assert "MILAGRO, MANTA Y RUMIÑAHUI" in texto
    assert " Y CLAVE " not in texto and "SU USUARIO" not in texto and "PORTAL" not in texto
    assert "%%" not in texto and "CONTRIBUYENTE ESPECIAL" not in texto   # la empresa no es contribuyente especial


def test_ticket_de_factura_sin_firmar_con_los_datos_del_xml(client, admin, empresa, settings):
    """Reimpresión de una factura aún sin firmar después de cambiar el establecimiento de la empresa: dirección matriz y
    la del establecimiento de su numeración (dirMatriz y dirEstablecimiento del XML), fechaEmision, aviso de pendiente
    en lugar de la clave de acceso y ningún «None» (la clave y los nombres del comprador pueden ser NULL)."""
    settings.FPA_RUC_PROVEEDOR = "0941609729001"
    Company.objects.filter(pk=empresa.pk).update(main_address="Av. Matriz 100, Guayaquil")
    punto = helpers.configurar_facturacion(empresa)
    with company_context(empresa):
        Establishment.objects.filter(pk=punto.establishment_id).update(address="Av. Local 200, Guayaquil")
    cliente = helpers.crear_cliente("cliente.pendiente", empresa, "0912345675", "0990000009")
    venta = helpers.crear_venta(empresa, cliente, admin, helpers.crear_producto(empresa))
    with company_context(empresa):
        # Registrada el 20 y preparada para firmar el 21: el XML lleva la fecha de emisión, no la de registro.
        Sale.objects.filter(pk=venta.pk).update(date_joined=date(2026, 10, 20), emission_date=date(2026, 10, 21))
        xml = ElementTree.fromstring(Sale.objects.get(pk=venta.pk).generate_xml()[0].encode())
    Company.objects.filter(pk=empresa.pk).update(establishment_address="Av. Sucursal 300, Daule")
    User.objects.filter(pk=cliente.user_id).update(names=None)
    helpers.iniciar_sesion(client, admin)
    respuesta = client.get(f"/pos/sale/admin/print/invoice/{venta.id}/")
    texto = "".join(PdfReader(io.BytesIO(respuesta.content)).pages[0].extract_text().split())
    assert venta.access_code is None and "None" not in texto
    assert "Comprobantependientedeautorización" in texto and "Clavedeacceso:" not in texto
    assert "Direcciónmatriz:" + "".join(xml.findtext("infoTributaria/dirMatriz").split()) in texto
    assert "Establecimiento:" + "".join(xml.findtext("infoFactura/dirEstablecimiento").split()) in texto
    assert "Sucursal300" not in texto
    fecha = datetime.strptime(xml.findtext("infoFactura/fechaEmision"), "%d/%m/%Y")
    assert f"Fechadeemisión:{fecha:%Y-%m-%d}" in texto and "2026-10-20" not in texto


def test_ride_con_datos_del_proveedor(venta):
    with company_context(venta.company):
        html = render_to_string("sale/format/invoice.html", {"sale": venta, "access_code_barcode": ""})
    for dato in ("RUC Proveedor", "0941609729001", "FACTURAPORAQUI", "soporte@facturaporaqui.com", "Milagro, Manta y Rumiñahui"):
        assert dato in html
    assert "Contribuyente Especial" not in html
