"""Proformas en PostgreSQL con hilos y conexiones propias: cuatro conversiones simultáneas dejan una sola factura (las
demás fallan sin gastar número), la numeración PRO- no tiene huecos ni repetidos y anular y facturar a la vez nunca dejan
las dos cosas. Cada hilo ejecuta la misma sección crítica que SaleCreateView (bloquear_para_facturar → reservar_numero →
venta → marcar_facturada), sin red ni SRI.

Usa transacciones reales (transaction=True), que al terminar vacían la base: por eso se llama test_zz_* (corre después de
test_zz_mejora_*, que usa los planes de las migraciones) y crea todos sus datos (empresas, secuencias, cliente, productos)."""
import threading
import time
from datetime import date

import pytest
from django.db import connection, connections, transaction

from core.pos.models import Client, Company, Receipt, Sale
from core.proformas import servicios
from core.proformas.models import ContadorProforma, Proforma
from core.tenancy.context import company_context
from core.user.models import User
from tests.ayudas_proformas import datos_ejemplo, productos_por_tarifa

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]


def empresa_ficticia(nombre, ruc):
    return Company.objects.create(ruc=ruc, business_name=f'{nombre} S.A.', tradename=nombre, main_address='x',
                                  establishment_address='x', establishment_code='001', issuing_point_code='001',
                                  special_taxpayer='000', mobile='0990000000', phone='042000000', email='e@example.com',
                                  website='https://example.com', electronic_signature_key='', email_host_user='',
                                  email_host_password='', environment_type=2)


def preparar(nombre, ruc, i):
    """Empresa en PRODUCCIÓN con su secuencia 001-002 (último 270), un cliente, productos y un vendedor."""
    empresa = empresa_ficticia(nombre, ruc)
    with company_context(empresa):
        receipt = Receipt.objects.create(voucher_type='01', environment_type=2, establishment_code='001',
                                         issuing_point_code='002', sequence=270, origin='otro_sistema')
        usuario = User.objects.create(username=f'cli.proformas.{i}', names='Cliente', email=f'c{i}@example.com')
        cliente = Client.objects.create(user=usuario, dni=f'09222222{i:02d}', mobile=f'09922222{i:02d}',
                                        birthdate=date(1990, 1, 1), address='x', send_email_invoice=False)
    vendedor = User.objects.create(username=f'vendedor.proformas.{i}', names='Vendedor', email=f'v{i}@example.com')
    productos_por_tarifa(empresa)
    return empresa, receipt, cliente, vendedor


def aceptada(empresa, vendedor):
    with company_context(empresa):
        p = servicios.crear(datos_ejemplo(productos_por_tarifa(empresa)), vendedor)
        Proforma.objects.filter(pk=p.pk).update(estado='aceptada')
        return p


def esperando_bloqueo():
    """Conexiones a esta base detenidas en un bloqueo (sin la copia de las estadísticas que guarda la transacción)."""
    with connection.cursor() as c:
        c.execute('SELECT pg_stat_clear_snapshot()')
        c.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'")
        return c.fetchone()[0]


def con_la_proforma_tomada(empresa, p, hilos):
    """Arranca los hilos con la proforma bloqueada aquí: todos llegan a esperarla y se cruzan seguro al soltarla."""
    with company_context(empresa), transaction.atomic():
        Proforma.objects.select_for_update(of=('self',)).get(pk=p.pk)
        for h in hilos:
            h.start()
        limite = time.monotonic() + 20
        while esperando_bloqueo() < len(hilos) and time.monotonic() < limite:
            time.sleep(0.05)
        assert esperando_bloqueo() == len(hilos), 'los hilos no llegaron a esperar la proforma'
    for h in hilos:
        h.join(60)
    assert not any(h.is_alive() for h in hilos)


def facturar(empresa, receipt, cliente, vendedor, p):
    """La sección crítica de SaleCreateView.post: proforma → secuencia → venta → UPDATE condicional."""
    with company_context(empresa), transaction.atomic():
        proforma = servicios.bloquear_para_facturar(p.pk, '01')
        secuencia = Receipt.objects.get(pk=receipt.pk)
        numero = secuencia.reservar_numero()
        venta = Sale.objects.create(client=cliente, receipt=secuencia, employee=vendedor, voucher_number=numero,
                                    voucher_number_full=f'001-002-{numero}', environment_type=2)
        time.sleep(0.2)   # la venta tarda: los demás esperan la proforma, no la secuencia
        servicios.marcar_facturada(proforma, venta, vendedor)
        return venta.pk


def test_cuatro_conversiones_simultaneas_una_sola_factura():
    empresa, receipt, cliente, vendedor = preparar('PROFORMAS CONC', '0990000911001', 1)
    p = aceptada(empresa, vendedor)
    resultados, errores, cerrojo = [], [], threading.Lock()

    def convertir():
        try:
            venta_id = facturar(empresa, receipt, cliente, vendedor, p)
            with cerrojo:
                resultados.append(('ok', venta_id))
        except servicios.ErrorProforma as e:
            with cerrojo:
                resultados.append(('error', str(e)))
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    con_la_proforma_tomada(empresa, p, [threading.Thread(target=convertir) for _ in range(4)])
    assert not errores, errores
    exitos = [v for r, v in resultados if r == 'ok']
    fallos = [v for r, v in resultados if r == 'error']
    assert len(exitos) == 1 and len(fallos) == 3, resultados
    assert all(f == f'La proforma {p.numero_completo} ya se facturó con la factura 001-002-000000271.' for f in fallos)
    with company_context(empresa):
        assert Sale.objects.count() == 1 and Sale.objects.get().pk == exitos[0]
        assert Receipt.objects.get(pk=receipt.pk).sequence == 271           # los que fallaron no gastaron número
        actual = Proforma.objects.get(pk=p.pk)
        assert (actual.estado, actual.venta_id) == ('facturada', exitos[0])


def test_numeracion_simultanea_sin_huecos_ni_repetidos():
    a, _, _, vendedor_a = preparar('PROFORMAS NUM A', '0990000912001', 2)
    b, _, _, vendedor_b = preparar('PROFORMAS NUM B', '0990000913001', 3)
    datos = {e.pk: datos_ejemplo(productos_por_tarifa(e)) for e in (a, b)}
    barrera, errores = threading.Barrier(8), []

    def crear(empresa, vendedor):
        try:
            barrera.wait()
            with company_context(empresa):
                servicios.crear(datos[empresa.pk], vendedor)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=crear, args=(a, vendedor_a) if i < 6 else (b, vendedor_b)) for i in range(8)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(60)
    assert not errores and not any(h.is_alive() for h in hilos), errores
    for empresa, cantidad in ((a, 6), (b, 2)):
        with company_context(empresa):
            assert sorted(Proforma.objects.values_list('numero_completo', flat=True)) == [
                f'PRO-{n:06d}' for n in range(1, cantidad + 1)]
            assert ContadorProforma.objects.get().ultimo == cantidad


def test_anular_y_facturar_a_la_vez_gana_uno():
    empresa, receipt, cliente, vendedor = preparar('PROFORMAS ANULAR', '0990000914001', 4)
    p = aceptada(empresa, vendedor)
    resultados, errores = {}, []

    def anular():
        try:
            servicios_en(empresa, lambda: servicios.cambiar_estado(p.pk, 'anular', vendedor, motivo='Cliente desistió'))
            resultados['anular'] = 'ok'
        except servicios.ErrorProforma as e:
            resultados['anular'] = str(e)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    def convertir():
        try:
            facturar(empresa, receipt, cliente, vendedor, p)
            resultados['facturar'] = 'ok'
        except servicios.ErrorProforma as e:
            resultados['facturar'] = str(e)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    con_la_proforma_tomada(empresa, p, [threading.Thread(target=anular), threading.Thread(target=convertir)])
    assert not errores, errores
    assert sorted(resultados) == ['anular', 'facturar'] and list(resultados.values()).count('ok') == 1, resultados
    with company_context(empresa):
        actual = Proforma.objects.get(pk=p.pk)
        if resultados['anular'] == 'ok':        # ganó anular: no hay venta ni número gastado
            assert (actual.estado, actual.venta_id) == ('anulada', None)
            assert Sale.objects.count() == 0 and Receipt.objects.get(pk=receipt.pk).sequence == 270
            assert resultados['facturar'] == f'La proforma {p.numero_completo} está anulada: solo se facturan las ' \
                                             'proformas enviadas y vigentes, o las aceptadas.'
        else:                                   # ganó facturar: la proforma facturada ya no se anula
            assert actual.estado == 'facturada' and actual.venta_id == Sale.objects.get().pk
            assert resultados['anular'] == f'La proforma {p.numero_completo} está facturada: no se puede anular.'


def servicios_en(empresa, trabajo):
    with company_context(empresa):
        return trabajo()
