"""Catálogos del SRI para compras y el ATS (core/pos/catalogos_sri.py): conversiones, matrices de la Tabla 4 y la Tabla 5 y
tarifa general del IVA por fecha. Funciones puras: sin base de datos."""
from datetime import date
from decimal import Decimal

import pytest

from core.pos import catalogos_sri as cat

TIPOS = [codigo for codigo, _ in cat.TIPOS_COMPROBANTE_COMPRA]


@pytest.mark.parametrize('factura_electronica, ats', [('04', '01'), ('05', '02'), ('06', '03'), ('08', '03'), ('07', ''), ('', '')])
def test_tipo_de_identificacion_al_ats(factura_electronica, ats):
    assert cat.tipo_id_ats(factura_electronica) == ats


def test_matriz_sustento_por_tipo_de_comprobante():
    assert cat.sustento_admite('02', '02') and not cat.sustento_admite('01', '02')
    assert {t for t in TIPOS if cat.sustento_admite('09', t)} == {'01', '04', '05'}
    # La nota o boleta de venta (02) solo con sustentos sin crédito tributario.
    assert [c for c, _ in cat.sustentos_para('02')] == ['02', '04', '05', '07', '08', '14', '15']
    assert not cat.sustento_admite('12', '01') and not cat.sustento_admite('00', '01') and not cat.sustento_admite('', '01')
    assert all(tipos <= set(TIPOS) for tipos in cat.COMPROBANTES_POR_SUSTENTO.values())


def test_matriz_tipo_de_comprobante_por_identificacion():
    assert cat.tipo_id_admite('01', '01') and not cat.tipo_id_admite('01', '02') and not cat.tipo_id_admite('01', '03')
    assert cat.tipo_id_admite('03', '02') and cat.tipo_id_admite('03', '03') and not cat.tipo_id_admite('03', '01')
    assert cat.tipo_id_admite('15', '03') and not cat.tipo_id_admite('15', '01') and not cat.tipo_id_admite('15', '02')
    assert not cat.tipo_id_admite('01', '') and set(cat.TIPO_ID_POR_COMPROBANTE) == set(TIPOS)


@pytest.mark.parametrize('fecha, tarifa', [(date(2024, 3, 31), 12), (date(2024, 4, 1), 15), (date(2016, 6, 1), 14),
                                           (date(2017, 5, 31), 14), (date(2016, 5, 31), 12), (date(2017, 6, 1), 12)])
def test_tarifa_general_del_iva_por_fecha(fecha, tarifa):
    assert cat.tarifa_iva_general(fecha) == Decimal(tarifa)


def test_iva_diferenciado_sin_tarifa_fija():
    assert '8' not in cat.TARIFA_POR_CODIGO and cat.CODIGOS_CON_TARIFA_VARIABLE == ('8',)
    assert cat.BASE_POR_CODIGO['8'] == 'base_gravada' and cat.BASE_POR_CODIGO['5'] == 'base_5'
    assert set(cat.CODIGOS_IVA_COMPRA) <= set(cat.BASE_POR_CODIGO)


def test_forma_de_pago_es_la_tabla_13_y_nombres():
    assert [c for c, _ in cat.FORMAS_PAGO] == ['01', '15', '16', '17', '18', '19', '20', '21']
    assert cat.nombre(cat.SUSTENTOS, '06').startswith('Inventario') and cat.nombre(cat.SUSTENTOS, 'ZZ') == 'ZZ'
    assert cat.UMBRAL_BANCARIZACION == Decimal('1000.00') and cat.PLAZO_ATS_DIAS == 365
