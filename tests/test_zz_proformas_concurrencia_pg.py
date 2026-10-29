"""Proformas en PostgreSQL con hilos y conexiones propias: cuatro conversiones simultáneas dejan una sola factura (las
demás fallan sin gastar número), la numeración PRO- no tiene huecos ni repetidos, anular o editar a la vez que se factura
nunca dejan las dos cosas (gana quien toma primero la proforma) y dos correos simultáneos no pasan juntos el último cupo
del límite por hora. Cada hilo que factura ejecuta la misma sección crítica que SaleCreateView (bloquear_para_facturar →
reservar_numero → venta → marcar_facturada), sin red ni SRI; los hilos esperan la PROFORMA, nunca la secuencia.

Usa transacciones reales (transaction=True), que al terminar vacían la base: por eso se llama test_zz_* (corre después de
test_zz_mejora_*, que usa los planes de las migraciones) y crea todos sus datos (empresas, secuencias, cliente, productos)."""
import threading
import time
from datetime import date

import pytest
from django.core import mail
from django.core.mail import EmailMessage
from django.db import DatabaseError, connection, connections, transaction
from django.utils import timezone

from core.pos.models import Client, Company, Receipt, Sale
from core.proformas import servicios
from core.proformas.models import ContadorProforma, Proforma
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog
from core.user.models import User
from tests.ayudas_proformas import datos_ejemplo, lineas_ejemplo, productos_por_tarifa

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


def esperar_bloqueados(cuantos):
    limite = time.monotonic() + 20
    while esperando_bloqueo() < cuantos and time.monotonic() < limite:
        time.sleep(0.05)
    return esperando_bloqueo() == cuantos


def con_la_proforma_tomada(empresa, p, hilos, receipt):
    """Arranca los hilos DE UNO EN UNO con la proforma bloqueada aquí y espera a que cada uno quede detenido antes de
    arrancar el siguiente: PostgreSQL entrega el bloqueo de una fila en el orden de llegada, así que el primer hilo de la
    lista es el primero en obtenerla. Antes de soltarla comprueba que esperan la PROFORMA y no la secuencia: la fila de
    Receipt sigue libre (nadie reservó número). Si bloquear() no hiciera SELECT … FOR UPDATE, un hilo que factura
    reservaría el número y se detendría después, con la secuencia tomada."""
    with company_context(empresa), transaction.atomic():
        Proforma.objects.select_for_update(of=('self',)).get(pk=p.pk)
        for n, h in enumerate(hilos, 1):
            h.start()
            assert esperar_bloqueados(n), 'los hilos no llegaron a esperar la proforma'
        try:
            with transaction.atomic():
                list(Receipt.objects.select_for_update(nowait=True, of=('self',)).filter(pk=receipt.pk)
                     .values_list('pk', flat=True))
        except DatabaseError as e:
            pytest.fail(f'un hilo tomó la secuencia antes que la proforma: {e}')
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

    con_la_proforma_tomada(empresa, p, [threading.Thread(target=convertir) for _ in range(4)], receipt)
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


def hilo(nombre, trabajo, resultados, errores, al_terminar=None):
    """Hilo que guarda 'ok' o el texto de ErrorProforma en resultados[nombre]; cualquier otra excepción va a errores.
    `al_terminar` (threading.Event) se activa cuando el hilo acaba, con éxito o sin él."""
    def correr():
        try:
            trabajo()
            resultados[nombre] = 'ok'
        except servicios.ErrorProforma as e:
            resultados[nombre] = str(e)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()
            if al_terminar is not None:
                al_terminar.set()
    return threading.Thread(target=correr)


@pytest.mark.parametrize('primero', ['anular', 'facturar'])
def test_anular_y_facturar_a_la_vez_gana_el_primero(primero):
    """Los dos órdenes, forzados: gana quien toma primero la proforma y el otro recibe el error de su estado. Sin el
    bloqueo, anular guardaría sin condición sobre la proforma ya facturada (y violaría la CHECK «facturada ⇔ con venta»)."""
    empresa, receipt, cliente, vendedor = preparar('PROFORMAS ANULAR', '0990000914001', 4)
    p = aceptada(empresa, vendedor)
    resultados, errores = {}, []
    hilos = {'anular': hilo('anular', lambda: servicios_en(empresa, lambda: servicios.cambiar_estado(
                 p.pk, 'anular', vendedor, motivo='Cliente desistió')), resultados, errores),
             'facturar': hilo('facturar', lambda: facturar(empresa, receipt, cliente, vendedor, p), resultados, errores)}
    segundo = 'facturar' if primero == 'anular' else 'anular'
    con_la_proforma_tomada(empresa, p, [hilos[primero], hilos[segundo]], receipt)
    assert not errores, errores
    with company_context(empresa):
        actual = Proforma.objects.get(pk=p.pk)
        if primero == 'anular':                 # no hay venta ni número gastado
            assert resultados == {'anular': 'ok', 'facturar': f'La proforma {p.numero_completo} está anulada: solo se '
                                                              'facturan las proformas enviadas y vigentes, o las aceptadas.'}
            assert (actual.estado, actual.venta_id) == ('anulada', None)
            assert Sale.objects.count() == 0 and Receipt.objects.get(pk=receipt.pk).sequence == 270
        else:                                   # la proforma facturada ya no se anula
            assert resultados == {'facturar': 'ok',
                                  'anular': f'La proforma {p.numero_completo} está facturada: no se puede anular.'}
            assert (actual.estado, actual.venta_id) == ('facturada', Sale.objects.get().pk)
            assert Receipt.objects.get(pk=receipt.pk).sequence == 271


def test_editar_mientras_se_factura_no_desvincula_la_factura():
    """Facturar toma la proforma (enviada) y editar espera: al soltarla, la edición ve la proforma facturada y se rechaza
    con no_editable. Sin el bloqueo de editar, su save escribiría «borrador» (y venta nula) sobre la proforma recién
    facturada: quedaría desvinculada y lista para una segunda factura."""
    empresa, receipt, cliente, vendedor = preparar('PROFORMAS EDITAR', '0990000916001', 6)
    productos = productos_por_tarifa(empresa)
    with company_context(empresa):
        p = servicios.crear(datos_ejemplo(productos), vendedor)
        Proforma.objects.filter(pk=p.pk).update(estado='enviada', enviada_en=timezone.now())
    cambios = datos_ejemplo(productos, lineas=lineas_ejemplo(productos)[:2], condiciones='Editada a la vez')
    resultados, errores = {}, []
    hilos = [hilo('facturar', lambda: facturar(empresa, receipt, cliente, vendedor, p), resultados, errores),
             hilo('editar', lambda: servicios_en(empresa, lambda: servicios.editar(p.pk, cambios, vendedor)),
                  resultados, errores)]
    con_la_proforma_tomada(empresa, p, hilos, receipt)
    assert not errores, errores
    assert resultados == {'facturar': 'ok', 'editar': servicios.MENSAJES['no_editable'].format(
        numero=p.numero_completo, estado='facturada')}
    with company_context(empresa):
        actual = Proforma.objects.get(pk=p.pk)
        assert (actual.estado, actual.venta_id) == ('facturada', Sale.objects.get().pk)
        assert actual.condiciones == 'Entrega inmediata.' and actual.detalles.count() == 5   # la edición no se aplicó


def test_limite_de_envios_no_lo_pasan_dos_correos_simultaneos(monkeypatch):
    """Con 59 envíos en la última hora, dos envíos a la vez: el segundo espera el bloqueo de envíos de la empresa, cuenta
    el primero y recibe limite_envios. Sin ese bloqueo los dos contarían 59 y saldrían 61 correos en la hora."""
    empresa, _, _, vendedor = preparar('PROFORMAS CORREO', '0990000915001', 5)
    with company_context(empresa):
        p = servicios.crear(datos_ejemplo(productos_por_tarifa(empresa)), vendedor)
    for _ in range(servicios.LIMITE_ENVIOS_POR_HORA - 1):
        AuditLog.objects.create(company=empresa, action='proforma_enviada', detail={})
    enviar_de_verdad, llamadas, cerrojo = EmailMessage.send, [], threading.Lock()
    primero_enviando, segundo_termino = threading.Event(), threading.Event()

    def enviar_lento(correo, *args, **kwargs):
        """El primer correo tarda hasta que el segundo envío espera un bloqueo o termina."""
        with cerrojo:
            llamadas.append(correo.to)
            es_el_primero = len(llamadas) == 1
        if es_el_primero:
            primero_enviando.set()
            limite = time.monotonic() + 20
            while not segundo_termino.is_set() and esperando_bloqueo() < 1 and time.monotonic() < limite:
                time.sleep(0.05)
        return enviar_de_verdad(correo, *args, **kwargs)
    monkeypatch.setattr(EmailMessage, 'send', enviar_lento)
    resultados, errores = {}, []

    def enviar(nombre):
        return lambda: servicios_en(empresa, lambda: servicios.enviar_por_correo(p.pk, vendedor, f'{nombre}@example.test'))
    primero = hilo('primero', enviar('primero'), resultados, errores)
    segundo = hilo('segundo', enviar('segundo'), resultados, errores, al_terminar=segundo_termino)
    primero.start()
    assert primero_enviando.wait(30), 'el primer envío no llegó a enviar'
    segundo.start()
    for h in (primero, segundo):
        h.join(60)
    assert not errores and not any(h.is_alive() for h in (primero, segundo)), errores
    assert resultados == {'primero': 'ok', 'segundo': servicios.MENSAJES['limite_envios']}
    assert [c.to for c in mail.outbox] == [['primero@example.test']]
    assert AuditLog.objects.filter(company=empresa, action='proforma_enviada').count() == servicios.LIMITE_ENVIOS_POR_HORA
    with company_context(empresa):
        assert Proforma.objects.get(pk=p.pk).envios == 1


def servicios_en(empresa, trabajo):
    with company_context(empresa):
        return trabajo()
