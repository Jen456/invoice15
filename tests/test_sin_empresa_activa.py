"""Sesión sin empresa activa: usuario con varias empresas recién ingresado.

Reportado el 06/11/2026: `/` respondía 500 (TenantScopeError) y un PDF de una
empresa propia, 404 sin explicación, al volver a entrar por un enlace directo.
"""
import pytest

from core.tenancy.models import ROLE_OWNER, Membership
from tests import helpers

pytestmark = pytest.mark.django_db


def usuario_con_dos_empresas(empresa, empresa_b):
    user = helpers.crear_usuario('multi', empresa, ROLE_OWNER)
    Membership.objects.create(user=user, company=empresa_b, group=Membership.objects.get(user=user).group)
    return user


@pytest.fixture
def pdf(settings, tmp_path, empresa):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.FPA_X_ACCEL_PREFIX = ''
    relativa = f'empresas/{empresa.uuid}/comprobantes/pdf/2026/11/ficticio.pdf'
    archivo = tmp_path / relativa
    archivo.parent.mkdir(parents=True)
    archivo.write_bytes(b'%PDF-1.4 ficticio')
    return f'/media/{relativa}'


class TestRaiz:

    def test_con_varias_empresas_lleva_al_selector(self, client, empresa, empresa_b):
        helpers.iniciar_sesion(client, usuario_con_dos_empresas(empresa, empresa_b))
        respuesta = client.get('/')
        assert respuesta.status_code == 302 and respuesta['Location'] == '/empresas/'

    def test_sin_empresas_lleva_al_selector_sin_bucle(self, client):
        helpers.iniciar_sesion(client, helpers.crear_usuario('sin.empresa'))
        assert client.get('/')['Location'] == '/empresas/'
        assert client.get('/empresas/').status_code == 200

    def test_superusuario_sin_empresa_lleva_al_selector(self, client, superusuario):
        helpers.iniciar_sesion(client, superusuario)
        assert client.get('/')['Location'] == '/empresas/'

    def test_post_sin_empresa_responde_403(self, client, empresa, empresa_b):
        helpers.iniciar_sesion(client, usuario_con_dos_empresas(empresa, empresa_b))
        assert client.post('/', {'action': 'get_graph_stock_products'}).status_code == 403

    def test_con_empresa_activa_muestra_el_panel(self, client, empresa, empresa_b):
        helpers.iniciar_sesion(client, usuario_con_dos_empresas(empresa, empresa_b), empresa=empresa)
        assert client.get('/').status_code == 200

    def test_con_una_sola_empresa_entra_directo(self, client, admin):
        helpers.iniciar_sesion(client, admin)
        assert client.get('/').status_code == 200

    def test_sin_sesion_pide_ingresar(self, client):
        assert client.get('/')['Location'] == '/login/?next=/'


class TestArchivoDeEmpresaSinEmpresaActiva:

    def test_pide_elegir_y_abre_el_archivo(self, client, empresa, empresa_b, pdf):
        helpers.iniciar_sesion(client, usuario_con_dos_empresas(empresa, empresa_b))
        respuesta = client.get(pdf)
        assert respuesta.status_code == 302 and respuesta['Location'].startswith('/empresas/?next=')
        selector = client.get(respuesta['Location'])
        assert f'name="next" value="{pdf}"' in selector.content.decode()
        elegida = client.post('/empresas/cambiar/', {'company': empresa.id, 'next': pdf})
        assert elegida.status_code == 302 and elegida['Location'] == pdf
        archivo = client.get(pdf)
        assert archivo.status_code == 200
        assert b''.join(archivo.streaming_content).startswith(b'%PDF')

    def test_el_selector_no_lleva_fuera_del_sitio(self, client, empresa, empresa_b):
        helpers.iniciar_sesion(client, usuario_con_dos_empresas(empresa, empresa_b))
        assert client.get('/empresas/?next=https://ejemplo.invalid/').status_code == 200
        elegida = client.post('/empresas/cambiar/', {'company': empresa.id, 'next': 'https://ejemplo.invalid/'})
        assert elegida['Location'] == '/dashboard/'

    def test_sin_destino_el_selector_no_lo_agrega(self, client, empresa, empresa_b):
        helpers.iniciar_sesion(client, usuario_con_dos_empresas(empresa, empresa_b))
        assert 'name="next"' not in client.get('/empresas/').content.decode()

    def test_empresa_ajena_sigue_en_404(self, client, empresa, empresa_b, pdf):
        otra = helpers.crear_empresa('EMPRESA C')
        user = helpers.crear_usuario('ajeno', empresa_b, ROLE_OWNER)
        Membership.objects.create(user=user, company=otra, group=Membership.objects.get(user=user).group)
        helpers.iniciar_sesion(client, user)
        assert client.get(pdf).status_code == 404

    def test_con_otra_empresa_activa_sigue_en_404(self, client, empresa, empresa_b, pdf):
        helpers.iniciar_sesion(client, usuario_con_dos_empresas(empresa, empresa_b), empresa=empresa_b)
        assert client.get(pdf).status_code == 404

    def test_archivo_inexistente_sigue_en_404(self, client, empresa, empresa_b, pdf):
        helpers.iniciar_sesion(client, usuario_con_dos_empresas(empresa, empresa_b))
        assert client.get(pdf.replace('ficticio', 'no-existe')).status_code == 404
