"""Concurrencia real en PostgreSQL de «Verificar en el SRI» (core/importacion/servicios.py): tres clics o pestañas a la vez
sobre el mismo documento hacen UNA sola consulta al SRI y dejan un solo intento; las demás peticiones responden «consulta
en curso» sin consultar ni crear nada. Transacciones reales (transaction=True) y una conexión por hilo; va al final
(test_zz_*) y crea todos sus datos, porque las pruebas transaccionales vacían la base. SRI simulado, sin red."""
import threading
import time
from types import SimpleNamespace

import pytest
from django.db import connection, connections

from core.importacion import servicios as sv
from core.importacion.models import DocumentoImportado, EventoImportacion
from core.pos import emision
from core.pos.models import Company
from core.tenancy.context import company_context
from core.user.models import User
from tests import fabricas_sri as f
from tests.test_importacion_xml_pdf import SRISimulado

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]


def en_paralelo(tareas):
    """Ejecuta cada tarea en su hilo y su conexión, a la vez (barrera). Devuelve (resultados, errores)."""
    barrera, resultados, errores, cerrojo = threading.Barrier(len(tareas)), [], [], threading.Lock()

    def correr(tarea):
        try:
            barrera.wait()
            resultado = tarea()
            with cerrojo:
                resultados.append(resultado)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            with cerrojo:
                errores.append(e)
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=correr, args=(t,)) for t in tareas]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    return resultados, errores


def test_tres_verificaciones_a_la_vez_una_sola_consulta(monkeypatch, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / 'media')
    empresa = Company.objects.create(ruc=f.RUC_RECEPTOR, business_name='VERIFICA CONCURRENCIA S.A.', tradename='VERIFICA',
                                     main_address='x', establishment_address='x', establishment_code='001',
                                     issuing_point_code='001', special_taxpayer='000', mobile='0990000000', phone='042000000',
                                     email='e@example.com', website='https://example.com', electronic_signature_key='',
                                     email_host_user='', email_host_password='')
    usuario = User.objects.create(username='verifica.conc', names='Verifica Concurrencia', email='v@example.com')
    with company_context(empresa):
        sv.crear_lote(empresa, usuario, [('f.xml', f.autorizacion(f.factura()).encode())])
        documento = DocumentoImportado.objects.get()
    llamadas, cerrojo = [], threading.Lock()

    class SRILento:   # tarda: las otras peticiones llegan mientras la primera consulta
        def __call__(self, url, timeout):
            return SimpleNamespace(service=self)

        def autorizacionComprobante(self, clave):
            with cerrojo:
                llamadas.append(clave)
            time.sleep(0.5)
            return SRISimulado({clave: f.factura()}).autorizacionComprobante(clave)

    monkeypatch.setattr(emision, '_cliente', SRILento())

    def verificar():
        with company_context(empresa):
            try:
                return sv.verificar_en_sri(DocumentoImportado.objects.get(pk=documento.pk), usuario).estado_verificacion
            except sv.ErrorImportacion as e:
                return e.codigo

    resultados, errores = en_paralelo([verificar, verificar, verificar])
    assert errores == []
    assert sorted(resultados) == ['consulta_en_curso', 'consulta_en_curso', 'verificada_sri']
    assert len(llamadas) == 1
    with company_context(empresa):
        assert DocumentoImportado.objects.count() == 1
        assert EventoImportacion.objects.filter(documento_id=documento.pk, tipo='verificacion').count() == 1
        final = DocumentoImportado.objects.get()
        assert final.consulta_en_curso is None and final.ultima_consulta_resultado == 'autorizado'
        assert final.ultima_consulta_por_id == usuario.pk
