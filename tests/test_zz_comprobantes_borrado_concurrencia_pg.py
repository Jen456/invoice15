"""Borrado de una retención mientras otra transacción la está enviando al SRI (PostgreSQL, hilos con conexiones propias):
ComprobanteListView decide con el estado de la fila bloqueada, así que si el envío la dejó enviada no se borra (antes
decidía con el estado leído antes de bloquear y podía borrar un comprobante ya enviado). Transacciones reales
(transaction=True): va al final (test_zz_*) y crea todos sus datos."""
import threading
import time
from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.db import connection, connections, transaction
from django.test import Client as ClienteWeb
from django.utils import timezone

from core.comprobantes.models import Retencion
from core.pos.models import Provider, Purchase, Receipt
from core.suscripciones.models import Plan
from core.tenancy.context import company_context
from tests import ayuda_compras as ayuda, helpers

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]
LISTA = '/comprobantes/retenciones/'


def esperando_bloqueo():
    with connection.cursor() as c:
        c.execute('SELECT pg_stat_clear_snapshot()')
        c.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'")
        return c.fetchone()[0]


def retencion_sin_enviar(empresa, usuario):
    with company_context(empresa):
        proveedor = Provider.objects.create(name='PROVEEDOR BORRADO', ruc='0992560541001', mobile='0990000001', email='p@example.com', address='x')
        compra = Purchase.objects.create(number='77', provider=proveedor, subtotal=Decimal('100'), total=Decimal('115'))
        receipt = Receipt.objects.create(voucher_type='07', establishment_code='001', issuing_point_code='001', sequence=3)
        return Retencion.objects.create(receipt=receipt, voucher_number='000000004', voucher_number_full='001-001-000000004', employee=usuario,
                                        environment_type=1, purchase=compra, provider=proveedor, tipo_identificacion='04',
                                        identificacion=proveedor.ruc, razon_social=proveedor.name, date_joined=timezone.localdate(),
                                        cod_doc_sustento='01', num_doc_sustento='001002000000001', fecha_doc_sustento=timezone.localdate(),
                                        aut_doc_sustento='1234567890', base_iva=Decimal('100'), valor_iva=Decimal('15'))


def test_borrar_mientras_se_envia_respeta_el_estado_final(client):
    Plan.objects.get_or_create(code='prueba-borrado-07', defaults={'name': 'Plan de prueba', 'price_cents': 1000})
    empresa = helpers.crear_empresa('BORRADO 07 CONC', plan='prueba-borrado-07')
    usuario = helpers.crear_usuario('borra.retenciones', empresa, helpers.crear_grupo('Borra retenciones (prueba)', ['view_retencion', 'delete_retencion']))
    ret = retencion_sin_enviar(empresa, usuario)
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    mensajes, errores = [], []

    def borrar():
        try:
            web = ClienteWeb()
            web.cookies.update(client.cookies)
            respuesta = web.post(LISTA, {'action': 'delete', 'id': ret.pk})
            mensajes.extend(str(m) for m in get_messages(respuesta.wsgi_request))
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    hilo = threading.Thread(target=borrar)
    with company_context(empresa), transaction.atomic():
        # Como emision._ejecutar: la fila bloqueada mientras se envía; el envío la deja en proceso antes de soltar el bloqueo.
        actual = Retencion.objects.select_for_update().get(pk=ret.pk)
        hilo.start()
        limite = time.monotonic() + 20
        while esperando_bloqueo() < 1 and time.monotonic() < limite:
            time.sleep(0.05)
        assert esperando_bloqueo() == 1, 'el borrado no llegó a esperar el bloqueo'
        actual.status = 'in_process'
        actual.save(update_fields=['status'])
    hilo.join(30)
    assert not errores and not hilo.is_alive(), errores
    assert mensajes and 'ya fue enviada al SRI y no se puede eliminar' in mensajes[0], mensajes
    with company_context(empresa):
        assert Retencion.objects.filter(pk=ret.pk, status='in_process').exists()
    # Sin envío en curso, el borrado de una no enviada sigue funcionando
    with company_context(empresa):
        Retencion.objects.filter(pk=ret.pk).update(status='without_authorizing')
    respuesta = client.post(LISTA, {'action': 'delete', 'id': ret.pk})
    assert any('eliminada' in str(m) for m in get_messages(respuesta.wsgi_request))
    with company_context(empresa):
        assert not Retencion.objects.filter(pk=ret.pk).exists()
