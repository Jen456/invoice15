"""«Convertir en factura» en PostgreSQL con hilos y conexiones propias: cuatro conversiones simultáneas de la misma proforma
(doble clic, varias pestañas) dejan UN solo borrador y todas reciben ese mismo; ninguna toca la secuencia ni crea una venta.
Los hilos esperan la PROFORMA (convertir la bloquea antes de buscar el borrador), como en la conversión de
test_zz_proformas_concurrencia_pg, de la que se reutilizan la preparación y la espera de los bloqueos.

Usa transacciones reales (transaction=True), que al terminar vacían la base: por eso se llama test_zz_* (después de
test_zz_mejora_*) y crea todos sus datos."""
import threading

import pytest
from django.db import connection, connections

from core.pos.models import Receipt, Sale
from core.proformas import servicios
from core.proformas.models import BorradorFactura, Proforma
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog
from tests.test_zz_proformas_concurrencia_pg import aceptada, con_la_proforma_tomada, preparar

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]


def test_cuatro_conversiones_simultaneas_un_solo_borrador():
    empresa, receipt, cliente, vendedor = preparar('BORRADOR CONC', '0990000931001', 31)
    p = aceptada(empresa, vendedor)
    resultados, errores, cerrojo = [], [], threading.Lock()

    def convertir():
        try:
            with company_context(empresa):
                borrador, creado = servicios.convertir(p.pk, vendedor)
            with cerrojo:
                resultados.append((borrador.pk, creado))
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    con_la_proforma_tomada(empresa, p, [threading.Thread(target=convertir) for _ in range(4)], receipt)
    assert not errores, errores
    assert len(resultados) == 4 and len({pk for pk, _ in resultados}) == 1, resultados
    assert sorted(creado for _, creado in resultados) == [False, False, False, True]
    with company_context(empresa):
        assert BorradorFactura.objects.count() == 1 and BorradorFactura.objects.get().pk == resultados[0][0]
        assert Receipt.objects.get(pk=receipt.pk).sequence == 270 and Sale.objects.count() == 0
        assert Proforma.objects.get(pk=p.pk).estado == 'aceptada'
    assert AuditLog.objects.filter(action='proforma_convertida').count() == 1


def test_descartar_y_emitir_a_la_vez_nunca_dejan_las_dos_cosas():
    """Descartar el borrador mientras otra pestaña emite: gana quien toma primero la proforma. Si gana la emisión, el
    descarte no encuentra borrador; si gana el descarte, la emisión falla sin gastar número."""
    empresa, receipt, cliente, vendedor = preparar('BORRADOR DESC', '0990000932001', 32)
    p = aceptada(empresa, vendedor)
    with company_context(empresa):
        borrador, _ = servicios.convertir(p.pk, vendedor)
    resultados, errores, cerrojo = [], [], threading.Lock()

    def descartar():
        try:
            with company_context(empresa):
                servicios.descartar_borrador(p.pk, vendedor)
            with cerrojo:
                resultados.append(('descartado', None))
        except servicios.ErrorProforma as e:
            with cerrojo:
                resultados.append(('descartar_fallo', str(e)))
        except Exception as e:  # noqa: BLE001
            errores.append(repr(e))
        finally:
            connections.close_all()

    def emitir():
        from django.db import transaction
        try:
            with company_context(empresa), transaction.atomic():
                proforma = servicios.bloquear_para_facturar(p.pk, '01')
                b = servicios.borrador_para_emitir(proforma, borrador.pk)
                secuencia = Receipt.objects.get(pk=receipt.pk)
                numero = secuencia.reservar_numero()
                venta = Sale.objects.create(client=cliente, receipt=secuencia, employee=vendedor, voucher_number=numero,
                                            voucher_number_full=f'001-002-{numero}', environment_type=2)
                servicios.marcar_facturada(proforma, venta, vendedor, borrador=b)
            with cerrojo:
                resultados.append(('emitida', venta.pk))
        except servicios.ErrorProforma as e:
            with cerrojo:
                resultados.append(('emitir_fallo', str(e)))
        except Exception as e:  # noqa: BLE001
            errores.append(repr(e))
        finally:
            connections.close_all()

    con_la_proforma_tomada(empresa, p, [threading.Thread(target=emitir), threading.Thread(target=descartar)], receipt)
    assert not errores, errores
    estados = sorted(r for r, _ in resultados)
    assert estados == ['descartar_fallo', 'emitida'], resultados   # la emisión llegó primero a la proforma
    with company_context(empresa):
        assert Sale.objects.count() == 1 and BorradorFactura.objects.count() == 0
        assert Proforma.objects.get(pk=p.pk).estado == 'facturada'
    assert dict(resultados)['descartar_fallo'] == servicios.MENSAJES['sin_borrador'].format(numero=p.numero_completo)
