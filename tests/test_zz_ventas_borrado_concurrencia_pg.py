"""Dos borrados simultáneos de la misma venta en PostgreSQL (hilos con conexiones propias): SaleDeleteView bloquea la
venta, así que el stock vuelve una sola vez y el segundo borrado responde un error, de contado y a crédito (con su cuenta
por cobrar sin abonos). Usa transacciones reales (transaction=True), que al terminar vacían la base: por eso se llama
test_zz_ventas_* (corre después de test_zz_mejora_*, que usa los planes de las migraciones) y crea todos sus datos."""
import threading
import time
from datetime import date

import pytest
from django.db import connection, connections, transaction
from django.test import Client as ClienteWeb

from core.pos.models import Client, CtasCollect, Product, Sale, SaleDetail
from core.suscripciones.models import Plan
from core.tenancy.context import company_context
from core.user.models import User
from tests import helpers

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]
VENTAS = '/pos/sale/admin/'


def esperando_bloqueo():
    """Conexiones a esta base detenidas en un bloqueo (sin la copia de las estadísticas que guarda la transacción)."""
    with connection.cursor() as c:
        c.execute('SELECT pg_stat_clear_snapshot()')
        c.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'")
        return c.fetchone()[0]


@pytest.mark.parametrize('a_credito', [False, True], ids=['contado', 'credito'])
def test_dos_borrados_a_la_vez_devuelven_el_stock_una_sola_vez(client, a_credito):
    Plan.objects.get_or_create(code='prueba-borrado', defaults={'name': 'Plan de prueba', 'price_cents': 1000})
    empresa = helpers.crear_empresa('BORRADO CONC', plan='prueba-borrado')
    vendedor = helpers.crear_usuario('borra.ventas', empresa, helpers.crear_grupo('Borra ventas (prueba)', ['delete_sale']))
    producto = helpers.crear_producto(empresa)
    with company_context(empresa):
        usuario = User.objects.create(username='cliente.borrado', names='Cliente', email='cliente@example.com')
        cliente = Client.objects.create(user=usuario, dni='0911111111', mobile='0991111111', birthdate=date(1990, 1, 1),
                                        address='Guayaquil', send_email_invoice=False)
        venta = helpers.crear_venta(empresa, cliente, vendedor, producto, cantidad=3)
        Product.objects.filter(pk=producto.pk).update(stock=97)     # la venta ya descontó sus 3 unidades
        if a_credito:
            Sale.objects.filter(pk=venta.pk).update(payment_type='credito')
            CtasCollect.objects.create(sale=venta, debt=venta.total, saldo=venta.total)
    helpers.iniciar_sesion(client, vendedor, empresa=empresa)
    respuestas, errores = [], []

    def borrar():
        try:
            web = ClienteWeb()
            web.cookies.update(client.cookies)      # la misma sesión, otra conexión a la base
            respuestas.append(web.post(f'{VENTAS}delete/{venta.pk}/').json())
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=borrar) for _ in range(2)]
    with company_context(empresa), transaction.atomic():
        # Con la venta tomada aquí, los dos borrados se cruzan seguro: ambos esperan hasta que esta transacción termina.
        Sale.objects.select_for_update(of=('self',)).get(pk=venta.pk)
        for h in hilos:
            h.start()
        limite = time.monotonic() + 20
        while esperando_bloqueo() < 2 and time.monotonic() < limite:
            time.sleep(0.05)
        assert esperando_bloqueo() == 2, 'los dos borrados no llegaron a esperar un bloqueo'
    for h in hilos:
        h.join(30)
    assert not errores and not any(h.is_alive() for h in hilos), errores
    # Uno borra; el otro encuentra la venta ya borrada. Sin el bloqueo, de contado el stock quedaba en 103.
    assert len(respuestas) == 2 and {} in respuestas and any(set(r) == {'error'} for r in respuestas), respuestas
    with company_context(empresa):
        assert Product.objects.get(pk=producto.pk).stock == 100
        assert not Sale.objects.filter(pk=venta.pk).exists() and not SaleDetail.objects.exists()
        assert not CtasCollect.objects.exists()
