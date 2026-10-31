"""Dos locales del mismo RUC emitiendo a la vez en PostgreSQL (core/configuracion/puntos.py): cada punto numera consecutivo
sin repetir ni mezclar con el otro, cada emisión sale del punto del usuario (o del que fijó su formulario) y cambiar la
selección de un usuario mientras los demás emiten no altera la de ellos.

Transacciones reales (transaction=True) y una conexión por hilo. Se ejecuta al final (test_zz_*) y crea todos sus datos,
porque las pruebas transaccionales vacían la base al terminar.
"""
import threading
import time
from datetime import date
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Group
from django.db import connection, connections, transaction

from core.configuracion import puntos as pt
from core.configuracion.models import PuntoSeleccionado
from core.pos.models import BillingSetup, Client, Company, EmissionPoint, Establishment, Receipt, Sale
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_SELLER, Membership
from core.user.models import User

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]


def empresa_ficticia():
    return Company.objects.create(ruc='0990000903001', business_name='DOS LOCALES S.A.', tradename='DOS LOCALES', main_address='x',
                                  establishment_address='Av. Centro 1', establishment_code='001', issuing_point_code='001',
                                  special_taxpayer='000', mobile='0990000000', phone='042000000', email='e@example.com',
                                  website='https://example.com', electronic_signature_key='', email_host_user='',
                                  email_host_password='')


def punto_listo(empresa, estab, punto, nombre, ultimo, predeterminado=False):
    from django.utils import timezone
    with company_context(empresa):
        est = Establishment.objects.create(code=estab, name=nombre, address=f'Av. {nombre} 1')
        pto = EmissionPoint.objects.create(establishment=est, code=punto, description='Caja', is_default=predeterminado)
        Receipt.objects.create(voucher_type='01', environment_type=1, establishment_code=estab, issuing_point_code=punto,
                               emission_point=pto, sequence=ultimo, origin='otro_sistema', confirmed_at=timezone.now())
    return pto


def test_ocho_emisiones_simultaneas_en_dos_locales_sin_mezclar_numeraciones():
    from django.utils import timezone
    empresa = empresa_ficticia()
    grupo, _ = Group.objects.get_or_create(name=ROLE_SELLER)
    centro = punto_listo(empresa, '001', '001', 'Centro', 125, predeterminado=True)
    norte = punto_listo(empresa, '002', '001', 'Norte', 0)
    with company_context(empresa):
        BillingSetup.objects.create(completed_steps=[1, 2, 3, 4, 5], current_step=5, completed_at=timezone.now())
    usuarios, clientes_web = {}, {}
    for nombre, punto in (('caja.centro', centro), ('caja.norte', norte)):
        u = User.objects.create(username=nombre, names=nombre, email=f'{nombre}@example.com')
        Membership.objects.create(user=u, company=empresa, group=grupo)
        with company_context(empresa):
            PuntoSeleccionado.objects.create(user=u, emission_point=punto)
        usuarios[nombre] = u
    comprador = User.objects.create(username='cli.dos', names='Cliente', email='cli@example.com')
    with company_context(empresa):
        cliente = Client.objects.create(user=comprador, dni='0911111101', mobile='0991111101', birthdate=date(1990, 1, 1),
                                        address='x', send_email_invoice=False)
    barrera, errores, resultados, cerrojo = threading.Barrier(8), [], [], threading.Lock()

    def emitir(nombre, punto_del_formulario=None):
        """Como la vista de venta: el punto del formulario (o el activo del usuario) validado, número reservado y venta guardada."""
        try:
            barrera.wait()
            peticion = SimpleNamespace(user=usuarios[nombre], company=empresa)
            with company_context(empresa), transaction.atomic():
                receipt = pt.receipt_para_emitir(peticion, '01', False, punto_del_formulario)
                numero = receipt.reservar_numero()
                time.sleep(0.2)   # la venta tarda: otros hilos del mismo punto esperan el bloqueo de su secuencia
                Sale.objects.create(client=cliente, receipt=receipt, employee=usuarios[nombre], voucher_number=numero,
                                    voucher_number_full=f'{receipt.establishment_code}-{receipt.issuing_point_code}-{numero}')
            with cerrojo:
                resultados.append((nombre, f'{receipt.establishment_code}-{receipt.issuing_point_code}', numero))
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    # 3 del centro con su punto activo, 1 del centro con el punto fijado por un formulario abierto en Norte (autorizado:
    # sin autorizaciones puede usar todos), 4 del norte con su punto activo.
    hilos = [threading.Thread(target=emitir, args=('caja.centro',)) for _ in range(3)]
    hilos.append(threading.Thread(target=emitir, args=('caja.centro', norte.pk)))
    hilos += [threading.Thread(target=emitir, args=('caja.norte',)) for _ in range(4)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    assert not errores, errores
    del_centro = sorted(n for _, p, n in resultados if p == '001-001')
    del_norte = sorted(n for _, p, n in resultados if p == '002-001')
    assert del_centro == [f'{n:09d}' for n in range(126, 129)]   # continúa desde 125, sin huecos ni repetidos
    assert del_norte == [f'{n:09d}' for n in range(1, 6)]        # 4 del norte + 1 del formulario abierto en Norte
    assert len([1 for u, p, _ in resultados if u == 'caja.centro' and p == '002-001']) == 1   # el formulario fijó Norte
    with company_context(empresa):
        assert Receipt.objects.get(pk=centro.sequences.get().pk).sequence == 128
        assert Receipt.objects.get(pk=norte.sequences.get().pk).sequence == 5
        assert Sale.objects.count() == 8
        # las selecciones de cada usuario no cambiaron
        assert PuntoSeleccionado.objects.get(user=usuarios['caja.centro']).emission_point_id == centro.pk
        assert PuntoSeleccionado.objects.get(user=usuarios['caja.norte']).emission_point_id == norte.pk
