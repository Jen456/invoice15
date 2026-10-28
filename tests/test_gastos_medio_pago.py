"""Gastos sin comprobante con medio de pago y referencia (MEDIOS_DE_PAGO de B0), tipos de gasto con cuenta contable y
sustento sin valor de oficio, sugerencia del sustento (solo texto) y compras de gasto sin productos."""
from decimal import Decimal

import pytest

from core.pos import compras
from core.pos.models import Expenses, TypeExpense
from core.tenancy.context import company_context
from tests import ayuda_compras as ayuda, helpers

pytestmark = pytest.mark.django_db


def test_gasto_con_medio_de_pago_y_referencia(empresa):
    tipo = ayuda.crear_tipo_gasto(empresa, 'MOVILIZACIÓN')
    with company_context(empresa):
        gasto = Expenses.objects.create(type_expense=tipo, description='Taxi', valor=Decimal('8.50'), medio_pago='cheque',
                                        referencia='CH-0001')
        anterior = Expenses.objects.create(type_expense=tipo, description='Antes', valor=Decimal('3.00'))
    assert gasto.toJSON()['medio_pago'] == {'id': 'cheque', 'name': 'Cheque'} and gasto.toJSON()['referencia'] == 'CH-0001'
    assert anterior.medio_pago == '' and anterior.toJSON()['medio_pago'] == {'id': '', 'name': 'Sin dato'}


def test_tipo_de_gasto_con_cuenta_y_sustento_sin_indicar(empresa):
    with company_context(empresa):
        nuevo = TypeExpense.objects.create(name='ARRIENDO', cuenta_contable='5.2.01.03')
        con_sustento = TypeExpense.objects.create(name='SUMINISTROS', cod_sustento='01')
    assert nuevo.cod_sustento == '' and nuevo.toJSON()['nombre_sustento'] == 'Sin indicar'
    assert nuevo.toJSON()['cuenta_contable'] == '5.2.01.03'
    assert con_sustento.toJSON()['nombre_sustento'].startswith('Crédito tributario para declaración de IVA')


def test_sustento_sugerido_segun_lo_que_vende_la_empresa(empresa):
    assert ayuda.en(empresa, compras.sustento_gasto_sugerido, empresa) == '02'
    ayuda.crear_producto(empresa, tarifa='0')
    assert ayuda.en(empresa, compras.sustento_gasto_sugerido, empresa) == '02'
    ayuda.crear_producto(empresa, tarifa='5')
    assert ayuda.en(empresa, compras.sustento_gasto_sugerido, empresa) == '01'
    otra = helpers.crear_empresa('OTRA CON IVA')
    ayuda.crear_producto(otra, tarifa='4')
    assert ayuda.en(otra, compras.sustento_gasto_sugerido, otra) == '01'


def test_compra_de_gasto_sin_productos(empresa, admin):
    proveedor = ayuda.crear_proveedor(empresa, tipo='04')
    tipo = ayuda.crear_tipo_gasto(empresa, 'MANTENIMIENTO', cod_sustento='02')
    with company_context(empresa):
        compra = compras.crear_compra(empresa, admin, ayuda.datos_compra(proveedor, cod_sustento='02'),
                                      [ayuda.linea_gasto('Mantenimiento del local', price='60.00', type_expense=tipo)])
        linea = compra.purchasedetail_set.get()
        assert compra.clase == 'gasto' and linea.product_id is None and linea.type_expense_id == tipo.pk
        assert linea.toJSON()['type_expense'] == {'id': tipo.pk, 'name': 'MANTENIMIENTO'}
