"""Contratos de presentación: formularios sin duplicación, permisos y numeración de consulta."""
from collections import Counter
from html.parser import HTMLParser
import json

import pytest
from tests import helpers
from core.pos.models import Receipt
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, ROLE_READONLY

pytestmark = pytest.mark.django_db


class HTML(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.elements = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@pytest.mark.parametrize('path', ['/pos/sale/admin/', '/pos/ctas/collect/', '/adjuntos/'])
def test_panel_compartido_una_sola_instancia_y_csrf(client, path):
    empresa = helpers.crear_empresa('PANEL FICTICIO')
    owner = helpers.crear_usuario('panel.owner', empresa)
    helpers.iniciar_sesion(client, owner, empresa=empresa)
    response = client.get(path)
    assert response.status_code == 200
    html = response.content.decode()
    nodes = HTML(html).elements
    ids = Counter(attrs.get('id') for _, attrs in nodes if attrs.get('id'))
    assert ids['fpConsultaCobro'] == ids['fpCobroFormulario'] == 1
    assert not [key for key, value in ids.items() if key.startswith('fpCobro') and value != 1]
    assert any(tag == 'input' and attrs.get('name') == 'csrfmiddlewaretoken' for tag, attrs in nodes)
    assert any(tag == 'form' and attrs.get('id') == 'fpCobroFormulario' and attrs['enctype'] == 'multipart/form-data'
               for tag, attrs in nodes)
    assert html.count('/static/cobros/js/cobros.js') == 1
    assert 'data-adjuntos-tipo="venta"' not in html and 'data-adjuntos-tipo="cobro"' not in html


@pytest.mark.parametrize('rol', [ROLE_OWNER, ROLE_READONLY])
def test_listado_entrega_permiso_real_de_ver_respaldos(client, rol):
    empresa = helpers.crear_empresa('PERMISO FICTICIO')
    usuario = helpers.crear_usuario('panel.usuario', empresa, rol)
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    html = client.get('/pos/sale/admin/').content.decode()
    datos = html.split('id="fpa-permisos" type="application/json">', 1)[1].split('</script>', 1)[0]
    assert json.loads(datos)['view_respaldocobro'] is True


def test_locales_consulta_dos_ambientes_sin_consumir_secuencias(client):
    empresa = helpers.crear_empresa('LOCALES FICTICIOS', environment_type=1)
    helpers.configurar_facturacion(empresa, ambiente=1)
    usuario = helpers.crear_usuario('local.owner', empresa)
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    with company_context(empresa):
        antes = list(Receipt.objects.order_by('id').values_list('id', 'sequence'))
    response = client.get('/configuracion/puntos/')
    assert response.status_code == 200
    html = response.content.decode()
    assert 'aria-label="Pruebas"' in html and 'aria-label="Producción"' in html
    assert 'Si quitas la última autorización' in html
    # Los códigos repetidos de alta de local/punto deben conservar etiquetas únicas.
    nodes = HTML(html).elements
    ids = Counter(a.get('id') for _, a in nodes if a.get('id'))
    assert ids['id_code-establecimiento'] == ids['id_code-punto'] == 1
    with company_context(empresa):
        assert list(Receipt.objects.order_by('id').values_list('id', 'sequence')) == antes
