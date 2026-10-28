"""Retención y liquidación sobre compras completas (compras.datos_sustento_retencion y liquidaciones.lineas_de_compra):
el documento sustento se precarga con el número, la autorización y la fecha de la factura, y las bases solo cuando la
factura tiene una única tarifa (el comprobante de retención actual admite una sola); las líneas de gasto no rompen la
liquidación."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.comprobantes import liquidaciones
from core.pos import compras
from core.tenancy.context import company_context
from tests import ayuda_compras as ayuda

pytestmark = pytest.mark.django_db


@pytest.fixture
def proveedor(empresa):
    return ayuda.crear_proveedor(empresa, tipo='04')


def compra_con(empresa, admin, proveedor, lineas, **cambios):
    datos = ayuda.datos_compra(proveedor, **{'secuencial': '271', 'autorizacion': '1' * 37, **cambios})
    with company_context(empresa):
        return compras.crear_compra(empresa, admin, datos, lineas)


def sustento(empresa, compra):
    with company_context(empresa):
        return compras.datos_sustento_retencion(compra)


def test_tarifa_unica_del_15_precarga_todo(empresa, admin, proveedor):
    compra = compra_con(empresa, admin, proveedor, [ayuda.linea_gasto(price='100.00'), ayuda.linea_gasto('Otro', price='20.00', codigo='0')],
                        forma_pago='20', parte_relacionada='si')
    iniciales, avisos = sustento(empresa, compra)
    assert avisos == []
    assert iniciales == {'cod_doc_sustento': '01', 'num_doc_sustento': '001002000000271', 'aut_doc_sustento': '1' * 37,
                         'fecha_doc_sustento': timezone.localdate() - timedelta(days=2), 'cod_sustento': '06', 'forma_pago': '20',
                         'parte_relacionada': True, 'base_0': Decimal('20.00'), 'base_iva': Decimal('100.00'),
                         'tarifa_iva': '15.00', 'valor_iva': Decimal('15.00')}


def test_tarifa_unica_del_5_y_solo_base_0(empresa, admin, proveedor):
    cinco, _ = sustento(empresa, compra_con(empresa, admin, proveedor, [ayuda.linea_gasto(price='40.00', codigo='5')]))
    assert (cinco['base_iva'], cinco['tarifa_iva'], cinco['valor_iva']) == (Decimal('40.00'), '5.00', Decimal('2.00'))
    cero, avisos = sustento(empresa, compra_con(empresa, admin, proveedor, [ayuda.linea_gasto(price='40.00', codigo='0')],
                                                secuencial='272'))
    assert avisos == [] and (cero['base_0'], cero['base_iva'], cero['valor_iva']) == (Decimal('40.00'), Decimal('0.00'),
                                                                                      Decimal('0.00'))
    assert 'tarifa_iva' not in cero


@pytest.mark.parametrize('lineas', [
    [('Servicio', '100.00', '4'), ('Alimentos', '50.00', '5')],
    [('Servicio', '100.00', '4'), ('Salud', '50.00', '7')],
    [('Servicio', '100.00', '4'), ('Tasa', '50.00', '6')],
], ids=['15_y_5', 'exenta', 'no_objeto'])
def test_varias_tarifas_o_bases_exentas_no_precargan_bases(empresa, admin, proveedor, lineas):
    compra = compra_con(empresa, admin, proveedor, [ayuda.linea_gasto(d, price=p, codigo=c) for d, p, c in lineas])
    iniciales, avisos = sustento(empresa, compra)
    assert [a['codigo'] for a in avisos] == ['sustento_varias_tarifas']
    assert iniciales['num_doc_sustento'] == '001002000000271' and iniciales['aut_doc_sustento'] == '1' * 37
    assert not {'base_0', 'base_iva', 'tarifa_iva', 'valor_iva'} & set(iniciales)


def test_compra_anterior_conserva_lo_de_hoy(empresa, proveedor):
    antigua = ayuda.compra_antigua(empresa, proveedor, '80.00')
    assert sustento(empresa, antigua) == ({'fecha_doc_sustento': antigua.date_joined, 'base_iva': Decimal('80.00')}, [])


def test_liquidacion_lista_lineas_de_gasto_con_su_tarifa(empresa, admin):
    productora = ayuda.crear_proveedor(empresa, tipo='05')
    producto = ayuda.crear_producto(empresa, codigo='CACAO-1', inventariado=False, tarifa='0')
    datos = {'provider': productora.pk, 'modo_comprobante': 'liquidacion', 'cod_sustento': '02', 'forma_pago': '01',
             'parte_relacionada': 'no', 'pago_loc_ext': '01', 'date_joined': timezone.localdate().isoformat()}
    with company_context(empresa):
        compra = compras.crear_compra(empresa, admin, datos, [
            ayuda.linea_producto(producto, cant=2, price='50.00', codigo='0'),
            {**ayuda.linea_gasto('Transporte de la cosecha', price='20.00', codigo='4'), 'codigo_proveedor': 'FLETE'}])
        lineas = liquidaciones.lineas_de_compra(compra)
    assert [(l['codigo'], l['descripcion'], l['cantidad'], l['precio_unitario'], l['tarifa']) for l in lineas] == [
        ('CACAO-1', 'PRODUCTO CACAO-1', Decimal('2'), Decimal('50.00'), Decimal('0.00')),
        ('FLETE', 'Transporte de la cosecha', Decimal('1'), Decimal('20.00'), Decimal('15.00'))]
