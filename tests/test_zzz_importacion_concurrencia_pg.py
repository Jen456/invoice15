"""Importaciones simultáneas en PostgreSQL (hilos con conexiones propias): las restricciones de base de datos dejan un
solo archivo y un solo documento por empresa+hash y empresa+ambiente+clave, y dos procesamientos del mismo lote no
toman la misma entrada. Usa transacciones reales (transaction=True), que al terminar vacían la base: por eso se llama
test_zzz_* (corre después de los demás) y no depende de datos de las migraciones (planes, grupos)."""
import threading

import pytest
from django.db import connection, connections

from core.importacion import servicios as sv, sri_autorizacion
from core.importacion.models import ArchivoImportado, DocumentoImportado, EntradaLote
from core.pos import emision
from core.tenancy.context import company_context
from tests import fabricas_sri as f, helpers
from tests.test_importacion_xml_pdf import SRISimulado

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]


def en_hilos(n, trabajo):
    barrera, errores = threading.Barrier(n), []

    def hilo(i):
        try:
            barrera.wait()
            trabajo(i)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            errores.append(repr(e))
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=hilo, args=(i,)) for i in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(30)
    return errores


def test_misma_factura_importada_a_la_vez(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    empresa = helpers.crear_empresa('CONCURRENTE', plan=None, ruc=f.RUC_RECEPTOR)
    usuario = helpers.crear_usuario('dueno.concurrente')
    xml_cdata = f.autorizacion(f.factura()).encode()
    xml_escapado = f.autorizacion(f.factura(), modo='escapado').encode()   # otro archivo, misma clave

    def importar(i):
        with company_context(empresa):
            sv.crear_lote(empresa, usuario, [(f'{i}.xml', xml_cdata if i % 2 == 0 else xml_escapado)])

    assert en_hilos(4, importar) == []
    with company_context(empresa):
        assert DocumentoImportado.objects.count() == 1
        assert ArchivoImportado.objects.count() == 2
        estados = sorted(EntradaLote.objects.values_list('estado', flat=True))
    assert estados == ['duplicado', 'duplicado', 'duplicado', 'procesado']


def test_dos_procesamientos_del_mismo_lote_no_repiten_entradas(settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path)
    monkeypatch.setattr(sri_autorizacion, 'PAUSA_REINTENTO', 0)
    monkeypatch.setattr(emision, '_cliente', SRISimulado({f.clave(secuencial=f'{n:09d}'): f.factura(secuencial=f'{n:09d}')
                                                          for n in range(1, 7)}))
    empresa = helpers.crear_empresa('LOTE CONCURRENTE', plan=None, ruc=f.RUC_RECEPTOR)
    usuario = helpers.crear_usuario('dueno.lote.concurrente')
    with company_context(empresa):
        lote = sv.crear_lote(empresa, usuario, [(f'{n}.pdf', f.pdf(('barras', f.clave(secuencial=f'{n:09d}')))) for n in range(1, 7)])

    def procesar(_):
        with company_context(empresa):
            sv.procesar_lote(lote, usuario, maximo=6)

    assert en_hilos(3, procesar) == []
    with company_context(empresa):
        entradas = list(EntradaLote.objects.filter(lote=lote))
        assert sorted(e.estado for e in entradas) == ['procesado'] * 6
        assert all(e.intentos == 1 for e in entradas)               # ninguna entrada se procesó dos veces
        assert DocumentoImportado.objects.filter(estado_verificacion='verificada_sri').count() == 6
