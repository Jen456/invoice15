"""Incorporación en lote simultánea en PostgreSQL (dos pestañas confirman los mismos documentos): una sola compra por documento
y un solo proveedor por RUC; el que pierde ve «ya incorporado», nunca un duplicado. Transacciones reales (transaction=True):
corre al final (test_zzz_*) y no depende de datos de las migraciones."""
import pytest
from django.db import connection

from core.importacion import reporte_sri, servicios as sv, sri_autorizacion
from core.importacion.models import DocumentoImportado
from core.pos import emision
from core.pos.models import Provider, Purchase
from core.tenancy.context import company_context
from tests import fabricas_recibidos as r, fabricas_sri as f, helpers
from tests.test_importacion_xml_pdf import SRISimulado
from tests.test_zzz_importacion_concurrencia_pg import en_hilos

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]
NUEVO = '0990000002001'


def test_dos_confirmaciones_simultaneas_crean_una_compra_y_un_proveedor(settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path)
    monkeypatch.setattr(sri_autorizacion, 'PAUSA_REINTENTO', 0)
    monkeypatch.setattr(sv, '_permisos', lambda request: {'change_documentoimportado', 'add_purchase', 'add_retencionrecibida'})
    claves = {f.clave(ruc=NUEVO, secuencial=f'{n:09d}'): r.factura(ruc=NUEVO, razon='PROVEEDOR NUEVO S.A.', secuencial=f'{n:09d}')
              for n in range(1, 5)}
    monkeypatch.setattr(emision, '_cliente', SRISimulado(claves))
    empresa = helpers.crear_empresa('INCORPORA CONCURRENTE', plan=None, ruc=f.RUC_RECEPTOR)
    usuario = helpers.crear_usuario('dueno.incorpora.concurrente')
    with company_context(empresa):
        lote = sv.crear_lote_de_claves(empresa, usuario, reporte_sri.filas_de_texto('\n'.join(claves)), 'claves')
        sv.procesar_lote(lote, usuario, maximo=10, presupuesto=None)
        ids = list(DocumentoImportado.objects.filter(estado_procesamiento='procesado').order_by('pk').values_list('pk', flat=True))
    assert len(ids) == 4
    resultados = {}

    def confirmar(i):
        with company_context(empresa):
            resultados[i] = sv.incorporar_lote(lote, usuario, None, ids, proveedores={NUEVO: {'mobile': '0990000097', 'email': 'c@example.com'}},
                                               maximo=10, presupuesto=None)

    assert en_hilos(2, confirmar) == []
    with company_context(empresa):
        assert Purchase.objects.count() == 4 and Provider.objects.filter(ruc=NUEVO).count() == 1
        assert DocumentoImportado.objects.filter(estado_revision='vinculado', compra__isnull=False).count() == 4
    por_documento = {}
    for res in resultados.values():
        for item in res['resultados']:
            por_documento.setdefault(item['documento_id'], []).append(item['resultado'])
    assert all(sorted(v) == ['compra_creada', 'ya_incorporado'] for v in por_documento.values()), por_documento
