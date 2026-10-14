"""Fecha de emisión y clave de acceso: la misma fecha, la de Ecuador, aunque el reloj del servidor
esté en UTC (desde las 19:00 de Ecuador la fecha UTC ya es la del día siguiente)."""
from datetime import datetime, timezone as dt_timezone

import pytest
from django.utils import timezone

from core.tenancy.context import company_context
from tests import helpers

pytestmark = pytest.mark.django_db


def test_factura_de_las_1950_lleva_la_fecha_de_ecuador(monkeypatch):
    empresa = helpers.crear_empresa('FECHAS')
    cliente = helpers.crear_cliente('cliente.fechas', empresa, '0912345678', '0990000001')
    venta = helpers.crear_venta(empresa, cliente, helpers.crear_usuario('vendedor.fechas', empresa),
                                helpers.crear_producto(empresa))
    instante = datetime(2026, 10, 12, 0, 50, tzinfo=dt_timezone.utc)   # 11/10/2026 19:50 en Ecuador
    monkeypatch.setattr(timezone, 'now', lambda: instante)
    with company_context(empresa):
        xml, clave = venta.generate_xml()
    assert '<fechaEmision>11/10/2026</fechaEmision>' in xml
    assert clave.startswith('11102026') and len(clave) == 49
    assert f'<claveAcceso>{clave}</claveAcceso>' in xml
