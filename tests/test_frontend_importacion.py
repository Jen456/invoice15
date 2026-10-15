"""Regresiones de presentación: candidatos con campos distintos y consentimiento visible."""
import pytest
from lxml import html

from core.importacion import servicios as sv
from core.tenancy.context import company_context
from tests import fabricas_sri as f, helpers

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('tipo', ['compra', 'venta'])
def test_revision_renderiza_candidato_y_pide_consentimiento(client, settings, tmp_path, monkeypatch, tipo):
    settings.MEDIA_ROOT = str(tmp_path)
    empresa = helpers.crear_empresa('REVISIÓN FICTICIA', ruc=f.RUC_RECEPTOR)
    usuario = helpers.crear_usuario('revision.frontend', empresa)
    cambios = {} if tipo == 'compra' else {'ruc': empresa.ruc, 'receptor_id': '0998888888001'}
    with company_context(empresa):
        lote = sv.crear_lote(empresa, usuario, [('ficticia.xml', f.autorizacion(f.factura(**cambios)).encode())])
        documento = lote.documentos.get()
    # El contrato no devuelve total en compras ni subtotal/fecha en ventas.
    candidato = {'tipo': tipo, 'id': 900, 'numero': '271', 'razones': ['mismo número'], 'exacto': True,
                 **({'subtotal': '120.00', 'fecha': '2026-10-10'} if tipo == 'compra' else {'total': '135.00'})}
    monkeypatch.setattr(sv, 'candidatos_conciliacion', lambda d: [candidato])
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    response = client.get(f'/importacion/documentos/{documento.pk}/')
    assert response.status_code == 200
    tree = html.fromstring(response.content)
    assert 'Probable duplicado' in tree.text_content()
    assert ('120.00' if tipo == 'compra' else '135.00') in tree.text_content()
    assert not tree.xpath('//input[@name="confirmar_sin_verificar"][@type="hidden" or @checked]')
    assert tree.xpath('//div[contains(@class,"fp-import-confirm")]//input[@type="checkbox"][@required]')
