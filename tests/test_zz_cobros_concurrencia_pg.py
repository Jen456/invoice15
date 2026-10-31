"""Doble envío real en PostgreSQL (core/cobros): dos peticiones simultáneas con la misma clave registran un solo abono y un
solo respaldo; con claves distintas, dos abonos con el saldo correcto. Transacciones reales (transaction=True) y una
conexión por hilo; va al final (test_zz_*) y crea todos sus datos, porque las pruebas transaccionales vacían la base."""
import threading
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Group, Permission
from django.db import connection, connections

from core.cobros import servicios as sv
from core.cobros.models import RespaldoCobro
from core.pos.models import Client, Company, CtasCollect, PaymentsCtaCollect, Receipt, Sale
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, Membership
from core.user.models import User

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]


def preparar():
    empresa = Company.objects.create(ruc='0990000904001', business_name='COBROS S.A.', tradename='COBROS', main_address='x',
                                     establishment_address='x', establishment_code='001', issuing_point_code='001',
                                     special_taxpayer='000', mobile='0990000000', phone='042000000', email='e@example.com',
                                     website='https://example.com', electronic_signature_key='', email_host_user='',
                                     email_host_password='')
    grupo, _ = Group.objects.get_or_create(name=ROLE_OWNER)
    grupo.permissions.add(*Permission.objects.filter(codename__in=(sv.PERMISO_REGISTRAR, sv.PERMISO_VER)))
    cajero = User.objects.create(username='cajero.conc', names='Cajero', email='c@example.com')
    membresia = Membership.objects.create(user=cajero, company=empresa, group=grupo)
    comprador = User.objects.create(username='cli.conc', names='Cliente', email='cli@example.com')
    with company_context(empresa):
        cliente = Client.objects.create(user=comprador, dni='0911111102', mobile='0991111102', birthdate=date(1990, 1, 1),
                                        address='x', send_email_invoice=False)
        receipt = Receipt.objects.create(voucher_type='01', establishment_code='001', issuing_point_code='001', sequence=1)
        venta = Sale.objects.create(client=cliente, receipt=receipt, employee=cajero, voucher_number='000000001',
                                    voucher_number_full='001-001-000000001', payment_type='credito', total=Decimal('23.00'))
        CtasCollect.objects.create(sale=venta, date_joined=date.today(), end_date=date.today(), debt=Decimal('23.00'),
                                   saldo=Decimal('23.00'))
    return empresa, cajero, membresia, venta


def test_misma_clave_un_abono_y_claves_distintas_dos():
    empresa, cajero, membresia, venta = preparar()
    barrera, errores, resultados, cerrojo = threading.Barrier(4), [], [], threading.Lock()

    def registrar(clave):
        try:
            barrera.wait()
            peticion = SimpleNamespace(user=cajero, company=empresa, membership=membresia, META={'REMOTE_ADDR': '127.0.0.1'},
                                       method='POST')
            with company_context(empresa):
                respaldo, repetido = sv.registrar(peticion, venta, clave=clave, medio='transferencia', importe='5.00',
                                                  referencia='TRX', nota='Cobro simultáneo')
            with cerrojo:
                resultados.append((clave, respaldo.pk, repetido))
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=registrar, args=(c,)) for c in ('clave-repetida-1', 'clave-repetida-1', 'clave-repetida-1', 'clave-distinta-2')]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    assert not errores, errores
    repetida = [r for r in resultados if r[0] == 'clave-repetida-1']
    assert len({pk for _, pk, _ in repetida}) == 1 and sum(1 for _, _, rep in repetida if not rep) == 1
    with company_context(empresa):
        assert PaymentsCtaCollect.objects.count() == 2 and RespaldoCobro.objects.count() == 2
        assert CtasCollect.objects.get(sale=venta).saldo_actual() == Decimal('13.00')
