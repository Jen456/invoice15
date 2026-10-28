"""Concurrencia real en PostgreSQL de la Etapa 2 · ventas (O2): hilos con conexiones propias contra cuentas por cobrar,
notas de crédito y de débito, retenciones recibidas y la marca «Anulado en el SRI». Los bloqueos llevan of=('self',) y van
en el orden de la especificación (§3.8): nada se duplica, no hay interbloqueos ni errores de «FOR UPDATE … outer join».

Usa transacciones reales (transaction=True), que al terminar vacían la base: por eso se llama test_zz_ventas_cxc_* (corre
después de test_zz_mejora_*, que usa los planes de las migraciones) y crea todos sus datos, también los códigos del catálogo
de retenciones que usa."""
import threading
import time
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection, connections, transaction
from django.utils import timezone

from core.comprobantes import retenciones_recibidas as rr
from core.comprobantes.models import CodigoRetencion, NotaDebito, RetencionRecibida
from core.pos import anulados, cxc
from core.pos.models import Client, CreditNote, CtasCollect, PaymentsCtaCollect, Receipt, Sale
from core.tenancy.context import company_context
from core.user.models import User
from tests import helpers
from tests.ayudas_ventas import (RUC_AGENTE, documento_07, factura_autorizada, recibidos_falsos, retencion_datos,
                                 retencion_leida, sustento)

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]
HOY = timezone.localdate()
ERRORES = (cxc.ErrorCxC, anulados.ErrorAnulacion, rr.ErrorRetencionRecibida)


def esperando_bloqueo():
    """Conexiones a esta base detenidas en un bloqueo (sin la copia de las estadísticas que guarda la transacción)."""
    with connection.cursor() as c:
        c.execute('SELECT pg_stat_clear_snapshot()')
        c.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'")
        return c.fetchone()[0]


@pytest.fixture
def datos():
    empresa = helpers.crear_empresa('CXC CONCURRENCIA', plan=None, environment_type=2)
    usuario = helpers.crear_usuario('cxc.concurrencia')
    with company_context(empresa):
        persona = User.objects.create(username='cliente.cxc.conc', names='CLIENTE CONCURRENTE S.A.', email='c@example.com')
        cliente = Client.objects.create(user=persona, dni=RUC_AGENTE, identification_type='04', mobile='0990000001',
                                        address='Guayaquil', send_email_invoice=False)
    producto = helpers.crear_producto(empresa, 'CONC-1')
    for impuesto, codigo, porcentaje in (('1', '312', '2.00'), ('2', '1', '30.00')):
        CodigoRetencion.objects.get_or_create(impuesto=impuesto, codigo=codigo, defaults={
            'concepto': f'Código {codigo} de prueba', 'porcentaje': Decimal(porcentaje), 'activo': True})

    def factura(**extra):
        extra.setdefault('fecha', HOY - timedelta(days=1))
        return factura_autorizada(empresa, cliente, usuario, producto, **extra)
    return empresa, usuario, factura


def a_la_vez(empresa, funciones, tomar=None):
    """Corre las funciones en hilos (cada uno con su conexión y la empresa activa). Con `tomar` = (Modelo, pk), esta
    transacción retiene antes esa fila hasta que todos los hilos esperan su bloqueo: se cruzan seguro."""
    resultados, errores = [None] * len(funciones), []
    barrera = threading.Barrier(len(funciones))

    def correr(i, funcion):
        try:
            with company_context(empresa):
                barrera.wait(timeout=30)
                resultados[i] = ('ok', funcion())
        except ERRORES as e:
            resultados[i] = ('error', e.codigo)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=correr, args=(i, f)) for i, f in enumerate(funciones)]
    if tomar is None:
        for h in hilos:
            h.start()
    else:
        Modelo, pk = tomar
        with company_context(empresa), transaction.atomic():
            Modelo.objects.select_for_update(of=('self',)).get(pk=pk)
            for h in hilos:
                h.start()
            limite = time.monotonic() + 20
            while esperando_bloqueo() < len(hilos) and time.monotonic() < limite:
                time.sleep(0.05)
            assert esperando_bloqueo() == len(hilos), 'los hilos no llegaron a esperar el bloqueo'
    for h in hilos:
        h.join(60)
    assert not errores and not any(h.is_alive() for h in hilos), errores
    return resultados


def nota_credito(empresa, venta, total='11.50'):
    """Nota de crédito autorizada con ajuste pendiente, sin pasar por el SRI."""
    with company_context(empresa):
        receipt, _ = Receipt.objects.get_or_create(voucher_type='04', environment_type=2, establishment_code='001',
                                                   issuing_point_code='002', defaults={'sequence': 0})
        numero = receipt.reservar_numero()
        nota = CreditNote(sale=venta, receipt=receipt, voucher_number=numero, voucher_number_full=f'001-002-{numero}',
                          motive='Devolución de prueba', total=Decimal(total), environment_type=2, status='authorized',
                          emission_date=HOY)
        nota.save()
        return nota


def nota_debito(empresa, usuario, venta, valor='5.00'):
    with company_context(empresa):
        receipt, _ = Receipt.objects.get_or_create(voucher_type='05', environment_type=2, establishment_code='001',
                                                   issuing_point_code='002', defaults={'sequence': 0})
        numero = receipt.reservar_numero()
        nota = NotaDebito(receipt=receipt, voucher_number=numero, voucher_number_full=f'001-002-{numero}', employee=usuario,
                          environment_type=2, status='authorized', emission_date=HOY, sale=venta, tipo_identificacion='04',
                          identificacion=RUC_AGENTE, razon_social='CLIENTE', num_doc_modificado=venta.voucher_number_full,
                          fecha_doc_sustento=venta.emission_date, tarifa_iva=Decimal('0'), total_sin_impuestos=Decimal(valor),
                          valor_total=Decimal(valor))
        nota.save()
        return nota


def test_a_dos_cobros_sobre_la_misma_deuda(datos):
    empresa, usuario, factura = datos
    venta = factura()
    with company_context(empresa):
        cuenta = CtasCollect.objects.create(sale=venta, date_joined=venta.date_joined, debt=Decimal('100.00'),
                                            saldo=Decimal('100.00'))

    def cobrar():
        return cxc.registrar_cobro(empresa, usuario, cuenta.pk, HOY, '60.00', 'efectivo').pk
    resultados = a_la_vez(empresa, [cobrar, cobrar], tomar=(CtasCollect, cuenta.pk))
    assert sorted(r[0] for r in resultados) == ['error', 'ok'] and ('error', 'valor_excede') in resultados
    with company_context(empresa):
        assert CtasCollect.objects.get(pk=cuenta.pk).saldo == Decimal('40.00') and PaymentsCtaCollect.objects.count() == 1


def test_b_aplicar_la_misma_nota_de_credito_dos_veces(datos):
    empresa, usuario, factura = datos
    venta = factura(credito=True)
    nota = nota_credito(empresa, venta)
    resultados = a_la_vez(empresa, [lambda: cxc.aplicar_nota_credito(nota.pk)] * 2, tomar=(CreditNote, nota.pk))
    assert resultados == [('ok', 'aplicada')] * 2
    with company_context(empresa):
        assert PaymentsCtaCollect.objects.filter(tipo='nota_credito').count() == 1
        assert CtasCollect.objects.get(sale=venta).saldo == Decimal('11.50')


def test_c_la_misma_retencion_registrada_a_la_vez(datos):
    empresa, usuario, factura = datos
    venta = factura(credito=True)

    def registrar():
        with transaction.atomic():
            return rr.registrar(empresa, usuario, venta, retencion_datos()).pk
    resultados = a_la_vez(empresa, [registrar, registrar], tomar=(Sale, venta.pk))
    assert sorted(r[0] for r in resultados) == ['error', 'ok'] and ('error', 'duplicada') in resultados
    with company_context(empresa):
        assert RetencionRecibida.objects.count() == 1 and PaymentsCtaCollect.objects.filter(tipo='retencion').count() == 1


def test_d_marcar_la_factura_y_cobrar_a_la_vez(datos):
    empresa, usuario, factura = datos
    venta = factura(credito=True)
    with company_context(empresa):
        cuenta = CtasCollect.objects.get(sale=venta)

    def marcar():
        return anulados.marcar(empresa, usuario, 'factura', venta, HOY, 'Anulada en SRI en línea, prueba de concurrencia')

    def cobrar():
        return cxc.registrar_cobro(empresa, usuario, cuenta.pk, HOY, '5.00', 'efectivo').pk
    resultados = a_la_vez(empresa, [marcar, cobrar], tomar=(CtasCollect, cuenta.pk))
    with company_context(empresa):
        anulada = Sale.objects.get(pk=venta.pk).anulado_sri_fecha is not None
        cobros = PaymentsCtaCollect.objects.filter(tipo='cobro').count()
        anulaciones = PaymentsCtaCollect.objects.filter(tipo='anulacion').count()
    if anulada:   # la anulación ganó: el cobro ve la CxC anulada
        assert resultados[0][0] == 'ok' and resultados[1] == ('error', 'cxc_anulada') and (cobros, anulaciones) == (0, 1)
    else:         # el cobro ganó: la anulación se detiene por el cobro
        assert resultados[0] == ('error', 'cobros') and resultados[1][0] == 'ok' and (cobros, anulaciones) == (1, 0)


def test_e_cobro_y_nota_de_debito_sobre_la_misma_venta(datos):
    empresa, usuario, factura = datos
    venta = factura(credito=True)
    nota = nota_debito(empresa, usuario, venta)
    with company_context(empresa):
        cuenta = cxc.cxc_de_factura(venta)
    resultados = a_la_vez(empresa, [lambda: cxc.registrar_cobro(empresa, usuario, cuenta.pk, HOY, '3.00', 'efectivo').pk,
                                    lambda: cxc.aplicar_nota_debito(nota.pk)])
    assert resultados[0][0] == 'ok' and resultados[1] == ('ok', 'aplicada')
    with company_context(empresa):
        assert CtasCollect.objects.get(pk=cuenta.pk).saldo == Decimal('20.00')
        assert NotaDebito.objects.get(pk=nota.pk).cuenta_por_cobrar.debt == Decimal('5.00')


def test_f_marcar_la_nota_y_su_factura_a_la_vez(datos):
    empresa, usuario, factura = datos
    venta = factura()
    nota = nota_credito(empresa, venta)
    motivo = 'Anulada en SRI en línea, prueba de concurrencia'
    resultados = a_la_vez(empresa, [lambda: anulados.marcar(empresa, usuario, 'nota-credito', nota, HOY, motivo),
                                    lambda: anulados.marcar(empresa, usuario, 'factura', venta, HOY, motivo)],
                          tomar=(Sale, venta.pk))
    assert resultados[0][0] == 'ok'
    with company_context(empresa):
        factura_marcada = Sale.objects.get(pk=venta.pk).anulado_sri_fecha is not None
        assert CreditNote.objects.get(pk=nota.pk).anulado_sri_fecha == HOY
    assert (resultados[1][0] == 'ok') == factura_marcada
    if not factura_marcada:
        assert resultados[1] == ('error', 'nc_vigente')


def test_g_el_mismo_07_importado_a_la_vez(datos, monkeypatch):
    empresa, usuario, factura = datos
    llamadas = recibidos_falsos(monkeypatch)
    ventas = [factura(credito=True), factura(credito=True)]
    documento = documento_07(empresa, usuario)
    leida = retencion_leida(documento, [sustento(v) for v in ventas])

    def registrar():
        return [r.pk for r in rr.registrar_desde_importacion(empresa, usuario, documento, leida)]
    from core.importacion.models import DocumentoImportado
    resultados = a_la_vez(empresa, [registrar, registrar], tomar=(DocumentoImportado, documento.pk))
    assert resultados[0] == resultados[1] and resultados[0][0] == 'ok' and len(resultados[0][1]) == 2
    with company_context(empresa):
        assert RetencionRecibida.objects.count() == 2 and PaymentsCtaCollect.objects.filter(tipo='retencion').count() == 2
    assert [ll[0] for ll in llamadas] == ['marcar', 'marcar']      # O1 lo hace idempotente
