"""Emisiones simultáneas en PostgreSQL: cada venta recibe un número distinto y consecutivo.

Transacciones reales (transaction=True) y una conexión por hilo. Se ejecuta al
final (test_zz_*) y crea todos sus datos, porque las pruebas transaccionales
vacían la base al terminar.
"""
import threading
import time
from datetime import date

import pytest
from django.db import connection, connections, transaction

from core.pos.models import Client, Company, Receipt, Sale
from core.tenancy.context import company_context
from core.user.models import User

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]


def empresa_ficticia(nombre, ruc):
    return Company.objects.create(ruc=ruc, business_name=f'{nombre} S.A.', tradename=nombre, main_address='x',
                                  establishment_address='x', establishment_code='001', issuing_point_code='001',
                                  special_taxpayer='000', mobile='0990000000', phone='042000000', email='e@example.com',
                                  website='https://example.com', electronic_signature_key='', email_host_user='',
                                  email_host_password='')


def test_ocho_emisiones_simultaneas_numeros_unicos_y_aislados():
    a, b = empresa_ficticia('CONC A', '0990000901001'), empresa_ficticia('CONC B', '0990000902001')
    vendedor = User.objects.create(username='vendedor.conc', names='Vendedor', email='v@example.com')
    secuencias, clientes = {}, {}
    for i, (empresa, ultimo) in enumerate(((a, 125), (b, 0)), start=1):
        with company_context(empresa):
            secuencias[empresa.pk] = Receipt.objects.create(voucher_type='01', establishment_code='001', issuing_point_code='002',
                                                            sequence=ultimo, origin='otro_sistema')
            usuario = User.objects.create(username=f'cli.{empresa.pk}', names='Cliente', email=f'c{empresa.pk}@example.com')
            clientes[empresa.pk] = Client.objects.create(user=usuario, dni=f'091111110{i}', mobile=f'099111110{i}',
                                                         birthdate=date(1990, 1, 1), address='x', send_email_invoice=False)
    barrera, errores, numeros, cerrojo = threading.Barrier(8), [], [], threading.Lock()

    def emitir(empresa):
        try:
            barrera.wait()
            with company_context(empresa), transaction.atomic():
                receipt = Receipt.objects.get(pk=secuencias[empresa.pk].pk)
                numero = receipt.reservar_numero()
                time.sleep(0.2)   # la venta tarda: otros hilos esperan el bloqueo de la secuencia
                Sale.objects.create(client=clientes[empresa.pk], receipt=receipt, employee=vendedor, voucher_number=numero,
                                    voucher_number_full=f'001-002-{numero}')
            with cerrojo:
                numeros.append((empresa.pk, numero))
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=emitir, args=(a if i < 6 else b,)) for i in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    assert not errores, errores
    de_a = sorted(n for e, n in numeros if e == a.pk)
    de_b = sorted(n for e, n in numeros if e == b.pk)
    assert de_a == [f'{n:09d}' for n in range(126, 132)]   # continúa desde 125, sin huecos ni repetidos
    assert de_b == ['000000001', '000000002']              # la otra empresa tiene su propia numeración
    for empresa, esperado in ((a, 131), (b, 2)):
        with company_context(empresa):
            assert Receipt.objects.get(pk=secuencias[empresa.pk].pk).sequence == esperado
            assert Sale.objects.count() == (6 if empresa == a else 2)
