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


# ---------------------------------------------------------------- formularios y pantallas (paso 2: §6.B y §6.F)

def entrar(client, empresa, usuario):
    helpers.iniciar_sesion(client, usuario, empresa=empresa)


def post_json(client, url, datos):
    import json
    respuesta = client.post(url, datos)
    return respuesta.status_code, json.loads(respuesta.content)


def test_formulario_de_gasto_medio_obligatorio_sin_inicial(empresa):
    from core.pos.forms import ExpensesForm
    tipo = ayuda.crear_tipo_gasto(empresa, 'COMBUSTIBLE')
    assert ExpensesForm()['medio_pago'].value() in (None, '')
    datos = {'type_expense': tipo.pk, 'description': 'Gasolina', 'date_joined': '2026-10-20', 'valor': '20.00',
             'medio_pago': '', 'referencia': ''}
    with company_context(empresa):
        form = ExpensesForm(datos)
        assert not form.is_valid() and form.errors['medio_pago'] == ['Elige el medio de pago']
        form = ExpensesForm({**datos, 'medio_pago': 'cheque'})
        assert not form.is_valid() and form.errors['referencia'] == ['Escribe el número del cheque']
        form = ExpensesForm({**datos, 'medio_pago': '20'})                 # la Tabla 13 no es un medio de pago
        assert not form.is_valid() and 'medio_pago' in form.errors
        assert ExpensesForm({**datos, 'medio_pago': 'efectivo'}).is_valid()


def test_gasto_por_la_pantalla_con_aviso_de_compra_de_gasto(client, empresa, admin):
    tipo = ayuda.crear_tipo_gasto(empresa, 'MOVILIZACIÓN')
    entrar(client, empresa, admin)
    respuesta = client.get('/pos/expenses/add/')
    assert respuesta.status_code == 200 and respuesta.context['url_gasto'] == '/pos/purchase/add/?tipo=gasto'
    assert '¿Tienes factura?' in respuesta.content.decode()
    datos = {'action': 'add', 'type_expense': tipo.pk, 'description': 'Taxi', 'date_joined': '2026-10-20', 'valor': '8.50',
             'medio_pago': 'transferencia', 'referencia': ' TRX   55 '}
    _, data = post_json(client, '/pos/expenses/add/', datos)
    assert data == {}
    with company_context(empresa):
        gasto = Expenses.objects.get()
        assert (gasto.medio_pago, gasto.referencia) == ('transferencia', 'TRX 55')
    _, filas = post_json(client, '/pos/expenses/', {'action': 'search', 'start_date': '', 'end_date': ''})
    assert filas[0]['medio_pago'] == {'id': 'transferencia', 'name': 'Transferencia'} and filas[0]['referencia'] == 'TRX 55'
    _, filas = post_json(client, '/reports/expenses/', {'action': 'search_report', 'start_date': '', 'end_date': ''})
    assert filas[0]['medio_pago']['name'] == 'Transferencia'


def test_tipo_de_gasto_nuevo_queda_sin_sustento_y_muestra_la_sugerencia(client, empresa, admin):
    entrar(client, empresa, admin)
    respuesta = client.get('/pos/type/expense/add/')
    assert respuesta.context['form']['cod_sustento'].value() in (None, '')
    assert respuesta.context['sustento_gasto_sugerido'] == '02' and 'Usar sugerencia' in respuesta.content.decode()
    _, data = post_json(client, '/pos/type/expense/add/', {'action': 'add', 'name': 'ARRIENDO', 'cuenta_contable': '5.2.01.03',
                                                           'cod_sustento': ''})
    assert data == {}
    with company_context(empresa):
        tipo = TypeExpense.objects.get(name='ARRIENDO')
        assert (tipo.cod_sustento, tipo.cuenta_contable) == ('', '5.2.01.03')
    _, filas = post_json(client, '/pos/type/expense/', {'action': 'search'})
    assert filas[0]['nombre_sustento'] == 'Sin indicar'


def test_compra_de_gasto_sin_sustento_preseleccionado(client, empresa, admin):
    sin_sustento = ayuda.crear_tipo_gasto(empresa, 'VARIOS')
    con_sustento = ayuda.crear_tipo_gasto(empresa, 'SUMINISTROS', cod_sustento='01')
    entrar(client, empresa, admin)
    respuesta = client.get('/pos/purchase/add/?tipo=gasto')
    assert respuesta.context['tipo_inicial'] == 'gasto' and respuesta.context['form']['cod_sustento'].value() in (None, '')
    assert respuesta.context['sustento_gasto_sugerido'] == '02' and 'Usar sugerencia' in respuesta.content.decode()
    ayuda.crear_producto(empresa, tarifa='4')
    assert client.get('/pos/purchase/add/?tipo=gasto').context['sustento_gasto_sugerido'] == '01'
    _, data = post_json(client, '/pos/purchase/add/', {'action': 'search_type_expense', 'term': ''})
    assert {d['id']: d['cod_sustento'] for d in data} == {sin_sustento.pk: '', con_sustento.pk: '01'}
    assert 'Usar sugerencia' not in client.get('/pos/purchase/add/').content.decode()


def test_con_el_plan_vencido_gastos_solo_consulta_y_compras_sigue(client):
    from datetime import timedelta

    from django.utils import timezone

    from core.tenancy.models import ROLE_OWNER
    empresa = helpers.crear_empresa('VENCIDA', plan=None)
    helpers.dar_plan(empresa, 'plan-1000', inicio=timezone.now() - timedelta(days=400))
    dueno = helpers.crear_usuario('dueno.vencida', empresa, ROLE_OWNER)
    tipo = ayuda.crear_tipo_gasto(empresa, 'LUZ')
    entrar(client, empresa, dueno)
    assert client.get('/pos/expenses/').status_code == 200
    assert client.post('/pos/expenses/', {'action': 'search', 'start_date': '', 'end_date': ''}).status_code == 200
    assert client.get('/pos/expenses/add/').status_code == 302
    estado, _ = post_json(client, '/pos/expenses/add/', {'action': 'add', 'type_expense': tipo.pk, 'valor': '5.00',
                                                         'medio_pago': 'efectivo', 'date_joined': '2026-10-20'})
    assert estado == 403 and not ayuda.en(empresa, Expenses.objects.exists)
    assert client.get('/pos/type/expense/add/').status_code == 302
    assert client.get('/pos/purchase/add/?tipo=gasto').status_code == 200          # P3: Compras sigue sin plan
