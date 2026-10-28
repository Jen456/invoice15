"""Compras y cuentas por pagar simultáneas en PostgreSQL (hilos con conexiones propias): un solo registro por comprobante,
stock exacto con F(), pagos que no superan el saldo y borrado o ajuste de la cuenta por pagar que no se cruzan con un pago.

Usa transacciones reales (transaction=True), que al terminar vacían la base: por eso se llama test_zzz_* (corre después de
test_zz_mejora_*, que usa los planes de las migraciones) y crea todos sus datos. Los casos de «crear la compra desde el
mismo documento importado» llegan con la pantalla de importación."""
import threading
from datetime import timedelta
from decimal import Decimal
from itertools import count

import pytest
from django.db import connection, connections
from django.utils import timezone

from core.pos import compras, cuentas_por_pagar as cxp
from core.pos.models import DebtsPay, PaymentsDebtsPay, Product, Purchase
from core.suscripciones.models import Plan
from core.tenancy.context import company_context
from tests import ayuda_compras as ayuda, helpers

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]
_n = count(1)


def en_hilos(n, trabajo):
    barrera, errores = threading.Barrier(n), []

    def hilo(i):
        try:
            barrera.wait()
            trabajo(i)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=hilo, args=(i,)) for i in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(60)
    assert not any(h.is_alive() for h in hilos), 'un hilo quedó bloqueado'
    return errores


def preparar():
    Plan.objects.get_or_create(code='prueba-compras', defaults={'name': 'Plan de prueba', 'price_cents': 1000})
    n = next(_n)
    empresa = helpers.crear_empresa(f'COMPRAS CONC {n}', plan='prueba-compras')
    return empresa, helpers.crear_usuario(f'dueno.compras.conc.{n}'), ayuda.crear_proveedor(empresa, tipo='04')


def a_credito(proveedor, **cambios):
    return ayuda.datos_compra(proveedor, payment_type='credito',
                              end_credit=(timezone.localdate() + timedelta(days=30)).isoformat(), **cambios)


def test_cuatro_registros_del_mismo_comprobante_dejan_una_compra():
    empresa, usuario, proveedor = preparar()
    producto = ayuda.crear_producto(empresa, stock=0)
    datos, resultados = a_credito(proveedor, secuencial='271'), []

    def registrar(_):
        with company_context(empresa):
            try:
                compras.crear_compra(empresa, usuario, datos, [ayuda.linea_producto(producto, cant=2)])
                resultados.append('ok')
            except compras.ErrorCompra as e:
                resultados.append(str(e))

    assert en_hilos(4, registrar) == []
    assert resultados.count('ok') == 1 and sum('Ya registraste factura 001-002-000000271' in r for r in resultados) == 3
    with company_context(empresa):
        assert Purchase.objects.count() == 1 and DebtsPay.objects.count() == 1
        assert Product.objects.get(pk=producto.pk).stock == 2


def test_diez_compras_simultaneas_del_mismo_producto_suben_el_stock_exacto():
    empresa, usuario, proveedor = preparar()
    producto = ayuda.crear_producto(empresa, stock=5)

    def registrar(i):
        with company_context(empresa):
            compras.crear_compra(empresa, usuario, ayuda.datos_compra(proveedor, secuencial=str(300 + i)),
                                 [ayuda.linea_producto(producto, cant=3)])

    assert en_hilos(10, registrar) == []
    with company_context(empresa):
        assert Purchase.objects.count() == 10 and Product.objects.get(pk=producto.pk).stock == 35


def test_dos_pagos_que_juntos_superan_el_saldo():
    empresa, usuario, proveedor = preparar()
    with company_context(empresa):
        compra = compras.crear_compra(empresa, usuario, a_credito(proveedor), [ayuda.linea_gasto(price='100.00', codigo='0')])
        deuda = DebtsPay.objects.get(purchase=compra)
    resultados = []

    def pagar(_):
        with company_context(empresa):
            try:
                cxp.registrar_pago(deuda.pk, usuario, fecha=timezone.localdate(), valor='60.00', medio_pago='transferencia',
                                   referencia='TRX')
                resultados.append('ok')
            except cxp.ErrorPago as e:
                resultados.append(str(e))

    assert en_hilos(2, pagar) == []
    assert sorted(resultados) == ['El pago ($60.00) supera el saldo pendiente ($40.00).', 'ok']
    with company_context(empresa):
        assert PaymentsDebtsPay.objects.count() == 1 and DebtsPay.objects.get(pk=deuda.pk).saldo == Decimal('40.00')


@pytest.mark.parametrize('ronda', range(3))
def test_borrar_la_compra_y_pagar_a_la_vez(ronda):
    empresa, usuario, proveedor = preparar()
    producto = ayuda.crear_producto(empresa, stock=0)
    with company_context(empresa):
        compra = compras.crear_compra(empresa, usuario, a_credito(proveedor), [ayuda.linea_producto(producto, cant=4, codigo='0')])
        deuda = DebtsPay.objects.get(purchase=compra)
    resultados = {}

    def trabajo(i):
        with company_context(empresa):
            try:
                if i == 0:
                    compras.eliminar_compra(compra, usuario)
                else:
                    cxp.registrar_pago(deuda.pk, usuario, fecha=timezone.localdate(), valor='10.00', medio_pago='efectivo')
                resultados[i] = 'ok'
            except (compras.ErrorCompra, cxp.ErrorPago) as e:
                resultados[i] = str(e)

    assert en_hilos(2, trabajo) == []
    with company_context(empresa):
        existe = Purchase.objects.filter(pk=compra.pk).exists()
        pagos = PaymentsDebtsPay.objects.count()
        stock = Product.objects.get(pk=producto.pk).stock
    if existe:      # pagó primero: la compra no se borra y conserva su pago
        assert resultados == {0: 'Tiene pagos registrados: elimínalos primero en Cuentas por pagar.', 1: 'ok'}
        assert pagos == 1 and stock == 4
    else:           # borró primero: el pago no queda huérfano ni se pierde sin aviso
        assert resultados == {0: 'ok', 1: 'La cuenta por pagar no existe.'}
        assert pagos == 0 and stock == 0 and not ayuda.en(empresa, DebtsPay.objects.exists)


@pytest.mark.parametrize('ronda', range(3))
def test_ajustar_la_cuenta_y_pagar_a_la_vez(ronda):
    empresa, usuario, proveedor = preparar()
    antigua = ayuda.compra_antigua(empresa, proveedor, '100.00', credito=True)
    with company_context(empresa):
        deuda = DebtsPay.objects.get(purchase=antigua)
    fecha = (antigua.date_joined - timedelta(days=1)).isoformat()
    datos = {'tipo_comprobante': '01', 'cod_sustento': '02', 'estab': '001', 'pto_emi': '001', 'secuencial': '9',
             'autorizacion': '1234567890', 'fecha_emision': fecha, 'forma_pago': '20', 'parte_relacionada': 'no',
             'pago_loc_ext': '01', 'base_0': '90.00', 'base_gravada': '0', 'base_5': '0', 'base_no_objeto': '0',
             'base_exenta': '0', 'total_descuento': '0', 'total_iva': '0', 'total_ice': '0', 'propina': '0',
             'confirmar_diferencia': '1', 'ajustar_cxp': '1'}
    resultados = {}

    def trabajo(i):
        with company_context(empresa):
            try:
                if i == 0:
                    compras.completar_datos(antigua, usuario, datos)
                else:
                    cxp.registrar_pago(deuda.pk, usuario, fecha=timezone.localdate(), valor='95.00', medio_pago='efectivo')
                resultados[i] = 'ok'
            except (compras.ErrorCompra, cxp.ErrorPago) as e:
                resultados[i] = str(e)

    assert en_hilos(2, trabajo) == []
    assert sum(r == 'ok' for r in resultados.values()) == 1, resultados
    with company_context(empresa):
        actual = DebtsPay.objects.get(pk=deuda.pk)
        pagado = actual.pagado()
    assert actual.debt >= pagado and actual.saldo == actual.debt - pagado
