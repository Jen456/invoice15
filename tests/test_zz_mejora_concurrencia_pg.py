"""Confirmaciones simultáneas de la mejora en PostgreSQL (hilos con conexiones propias).

Usa transacciones reales (transaction=True), que al terminar vacían la base de
pruebas: por eso este archivo se llama test_zz_* y se ejecuta el último.
"""
import threading
import time
from datetime import timedelta
from unittest import mock

import pytest
from django.db import connection, connections
from django.utils import timezone

from core.suscripciones import payphone
from core.suscripciones.models import Payment, Plan
from core.suscripciones.servicios import confirmar_pago, nuevo_pago
from tests import helpers

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]


def test_tres_confirmaciones_simultaneas_aplican_una_sola_mejora(settings):
    settings.PAYPHONE_TOKEN = 'token-de-prueba'
    empresa = helpers.crear_empresa('CONCURRENCIA', plan=None)
    ahora = timezone.now()
    periodo = helpers.dar_plan(empresa, 'plan-1000', inicio=ahora - timedelta(days=30), ends_at=ahora + timedelta(days=200))
    ilimitado = Plan.objects.get(code='ilimitado')
    pagos = [nuevo_pago(empresa, ilimitado, None, 'mejora', precio_cents=3500, periodo_objetivo=periodo) for _ in range(2)]
    Payment.objects.filter(pk__in=[p.pk for p in pagos]).update(status='redirigido')
    llamadas, cerrojo = [], threading.Lock()

    def confirmar_lento(transaccion, referencia):
        with cerrojo:
            llamadas.append(referencia)
        time.sleep(0.6)   # ensancha la ventana de carrera mientras se tienen los bloqueos
        pago = Payment.objects.get(client_tx_id=referencia)
        return {'statusCode': 3, 'transactionStatus': 'Approved', 'transactionId': transaccion,
                'clientTransactionId': referencia, 'amount': pago.amount_cents, 'currency': 'USD'}

    barrera = threading.Barrier(3)
    errores = []

    def hilo(pago, transaccion):
        try:
            barrera.wait()
            confirmar_pago(pago.client_tx_id, transaccion)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    trabajos = [(pagos[0], 9101), (pagos[0], 9101), (pagos[1], 9102)]   # el mismo retorno dos veces y otra pestaña
    with mock.patch.object(payphone, 'confirmar', side_effect=confirmar_lento):
        hilos = [threading.Thread(target=hilo, args=t) for t in trabajos]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=30)
    assert not errores, errores
    estados = sorted(Payment.objects.filter(pk__in=[p.pk for p in pagos]).values_list('status', flat=True))
    periodo.refresh_from_db()
    assert estados == ['aprobado', 'rechazado']
    assert len(llamadas) == 1   # PayPhone se confirmó una sola vez; el otro cobro se reversa solo
    assert periodo.plan.code == 'ilimitado' and periodo.upgrade_payment_id is not None
    assert periodo.mejoras.filter(status='aprobado').count() == 1
