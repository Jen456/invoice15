"""Cruces de versión en un reintento: factura firmada SIN diseño o con diseño v1; el comercio guarda un diseño v2 antes
del reintento (DEVUELTA / NO AUTORIZADO / EN PROCESO). La factura conserva lo de su primera firma (sin copia, o la v1) y
su RIDE autorizado se arma con eso. Datos ficticios, SRI simulado."""
import pytest

from core.comprobantes import ride_styles
from tests.test_diseno_factura_v2 import (FACTURA, V1_A, V2_B, contextos, copia_esperada, empresa,  # noqa: F401
                                               guardar_diseno, piloto)
from tests.test_emision_sri import accion, comprador, dueno, p12, producto, refrescar, sri, vender, venta_de, web  # noqa: F401

pytestmark = pytest.mark.django_db
PRIMERAS = {'devuelta': ([('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])], []),
            'no-autorizado': ([], ['NO AUTORIZADO']), 'en-proceso': ([], [])}


@pytest.mark.parametrize('flujo', PRIMERAS)
@pytest.mark.parametrize('antes', ['sin-diseno', 'v1'])
def test_reintento_tras_guardar_v2_conserva_lo_de_la_primera_firma(piloto, web, empresa, comprador, producto, sri,  # noqa: F811
                                                                  contextos, antes, flujo):
    if antes == 'v1':
        guardar_diseno(web, empresa, V1_A)
    sri.respuestas_recepcion, sri.respuestas_autorizacion = (list(x) for x in PRIMERAS[flujo])
    vender(web, comprador, producto)
    venta = venta_de(empresa, 271)
    assert venta.status != 'authorized' and venta.signed_at is not None
    esperada = copia_esperada(V1_A) if antes == 'v1' else None
    assert venta.ride_diseno == esperada
    assert guardar_diseno(web, empresa, V2_B).version == 2
    sri.respuestas_autorizacion = ['AUTORIZADO']
    accion(web, 'generate_invoice', venta)
    refrescar(venta)
    assert venta.status == 'authorized' and venta.ride_diseno == esperada
    assert [c.get('ride_style') for p, c in contextos if p == FACTURA] == [
        ride_styles.context_from_copy(esperada) if esperada else None]
