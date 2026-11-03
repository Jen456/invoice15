"""Acceso al Complemento Contable en el servidor (core/suscripciones): /tributario/ y /contabilidad/ exigen, además del plan
pagado, que la empresa activa esté en la lista de revisión FPA_COMPLEMENTO_CONTABLE_REVISION (D9 pendiente: no se habilita
comercialmente). Páginas, API, descargas y envíos; cambio de empresa; resumen del contador; «*» solo en local; la captura
rápida de recibos no se bloquea. El resto de las pruebas corre con «*» (conftest)."""
import pytest
from django.contrib.auth.models import Group

from core.suscripciones import reglas
from core.suscripciones.templatetags.suscripciones import bloqueado_por_plan
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_OWNER, Membership
from tests import helpers

pytestmark = pytest.mark.django_db

PAGINAS = ('/tributario/libros/', '/tributario/revision/', '/tributario/empresas/', '/tributario/ats/', '/tributario/formularios/',
           '/contabilidad/kardex/', '/contabilidad/inventario/')
JSON = ('/tributario/api/libros/ventas/', '/tributario/api/revision/', '/tributario/api/empresas/', '/tributario/api/ats/',
        '/tributario/api/formularios/', '/tributario/libros/exportar/', '/tributario/ats/descargar/', '/tributario/formularios/exportar/',
        '/contabilidad/api/inventario/', '/contabilidad/api/kardex/productos/', '/contabilidad/inventario/exportar/')


@pytest.fixture
def entrar(client, empresa, admin):
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    return client


def bloqueada(respuesta):
    return respuesta.status_code == 403 and respuesta.json()['codigo'] == 'complemento_pendiente' \
        and respuesta.json()['plan'] == 'complemento_contable' and 'por anunciar' in respuesta.json()['error']


class TestCerrado:

    @pytest.fixture(autouse=True)
    def sin_lista(self, settings):
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = []

    def test_paginas_vuelven_al_inicio_con_el_aviso(self, entrar):
        for url in PAGINAS:
            respuesta = entrar.get(url)
            assert respuesta.status_code == 302 and respuesta['Location'] == '/dashboard/', url
        mensajes = [str(m) for m in entrar.get('/dashboard/').context['messages']]
        assert any(reglas.MENSAJE_COMPLEMENTO == m for m in mensajes)

    def test_api_descargas_y_envios_responden_403(self, entrar, empresa):
        for url in JSON:
            assert bloqueada(entrar.get(f'{url}?empresa={empresa.pk}')), url
        assert bloqueada(entrar.post('/contabilidad/api/kardex/movimientos/', {'clave': 'complemento-0001'}))
        assert bloqueada(entrar.post('/contabilidad/kardex/', {'accion': 'registrar'}))
        assert bloqueada(entrar.post('/contabilidad/api/kardex/movimientos/1/anular/', {'motivo': 'x'}))

    def test_la_captura_rapida_y_lo_demas_siguen_abiertos(self, entrar):
        assert entrar.get('/adjuntos/capturas/').status_code == 200
        assert entrar.get('/adjuntos/api/capturas/').status_code == 200
        assert entrar.get('/adjuntos/').status_code == 200
        assert entrar.get('/pos/sale/admin/').status_code == 200

    def test_comodin_no_vale_en_un_despliegue(self, entrar, settings):
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = ['*']
        settings.FPA_ENTORNO = 'pruebas'   # el sitio publicado se llama así: el comodín no lo abre
        assert entrar.get('/tributario/libros/').status_code == 302
        settings.FPA_ENTORNO = 'produccion'
        assert bloqueada(entrar.get('/tributario/api/revision/'))

    def test_el_menu_muestra_el_candado(self, entrar):
        estado = entrar.get('/dashboard/').context['fpa_plan']
        assert estado.complemento is False and bloqueado_por_plan('/tributario/libros/', estado)
        assert bloqueado_por_plan('/contabilidad/kardex/', estado) and not bloqueado_por_plan('/adjuntos/capturas/', estado)


class TestRevision:

    def test_empresa_de_la_lista(self, entrar, empresa, settings):
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [empresa.ruc]
        for url in PAGINAS:
            assert entrar.get(url).status_code == 200, url
        assert entrar.get('/tributario/api/revision/').status_code == 200
        assert entrar.get('/dashboard/').context['fpa_plan'].complemento is True

    def test_sin_lista_ni_el_plan_gratuito_ve_una_oferta(self, client, settings):
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = []
        gratuita = helpers.crear_empresa('GRATIS SIN COMPLEMENTO', plan=None)
        dueno = helpers.crear_usuario('dueno.sin.complemento', gratuita, ROLE_OWNER)
        helpers.iniciar_sesion(client, dueno, empresa=gratuita)
        respuesta = client.get('/tributario/libros/')
        assert respuesta.status_code == 302 and respuesta['Location'] == '/dashboard/'   # no lleva a comprar un plan

    def test_la_lista_no_salta_el_plan_pagado(self, client, settings):
        gratuita = helpers.crear_empresa('GRATIS COMPLEMENTO', plan=None)
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [gratuita.ruc]
        dueno = helpers.crear_usuario('dueno.complemento.gratis', gratuita, ROLE_OWNER)
        helpers.iniciar_sesion(client, dueno, empresa=gratuita)
        respuesta = client.get('/tributario/libros/')
        assert respuesta.status_code == 302 and '/suscripcion/' in respuesta['Location']

    def test_cambio_de_empresa_y_resumen_del_contador(self, client, empresa, empresa_b, settings):
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [empresa.ruc]
        contador = helpers.crear_usuario('contador.complemento', empresa, ROLE_ACCOUNTANT)
        Membership.objects.create(user=contador, company=empresa_b, group=Group.objects.get(name=ROLE_ACCOUNTANT))
        helpers.iniciar_sesion(client, contador, empresa=empresa)
        datos = client.get('/tributario/api/empresas/').json()
        assert [e['empresa_id'] for e in datos['empresas']] == [empresa.pk]   # la otra empresa no está cubierta
        client.post('/empresas/cambiar/', {'company': empresa_b.pk, 'next': '/tributario/revision/'})
        assert client.get('/tributario/revision/').status_code == 302
        assert bloqueada(client.get('/tributario/api/revision/'))
        assert client.get('/adjuntos/capturas/').status_code == 200

    def test_comodin_solo_en_local(self, entrar, settings):
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = ['*']
        settings.FPA_ENTORNO = 'pruebas_automaticas'
        assert entrar.get('/contabilidad/inventario/').status_code == 200


class TestRucDeLaLista:

    def test_un_ruc_compartido_no_abre_el_complemento(self, empresa, empresa_b, settings):
        from core.pos.models import Company
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [empresa.ruc]
        assert reglas.complemento_habilitado(empresa) is True
        Company.objects.filter(pk=empresa_b.pk).update(ruc=empresa.ruc)   # como si otra empresa copiara el RUC
        assert reglas.complemento_habilitado(Company.objects.get(pk=empresa_b.pk)) is False
        assert reglas.complemento_habilitado(empresa) is False

    def test_la_empresa_no_toma_el_ruc_de_otra(self, empresa, empresa_b):
        from core.pos.forms import CompanyForm
        form = CompanyForm(data={'ruc': empresa.ruc}, instance=empresa_b)
        assert not form.is_valid() and form.errors['ruc'] == ['Ya existe una empresa con este RUC o cédula. Pide acceso a su propietario.']

    def test_pestana_de_una_empresa_cubierta_tras_cambiar_a_otra(self, client, empresa, empresa_b, settings):
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [empresa.ruc]
        contador = helpers.crear_usuario('contador.pestana', empresa, ROLE_ACCOUNTANT)
        Membership.objects.create(user=contador, company=empresa_b, group=Group.objects.get(name=ROLE_ACCOUNTANT))
        helpers.iniciar_sesion(client, contador, empresa=empresa)
        assert client.get(f'/tributario/api/revision/?empresa={empresa.pk}').status_code == 200
        client.post('/empresas/cambiar/', {'company': empresa_b.pk, 'next': '/'})
        r = client.get(f'/tributario/api/revision/?empresa={empresa.pk}')   # la pestaña vieja
        assert r.status_code == 409 and r.json()['codigo'] == 'empresa_cambiada'
        assert bloqueada(client.get('/tributario/api/revision/'))           # sin `empresa`: el complemento sigue cerrado

    def test_menu_dice_por_anunciar(self, entrar, settings):
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = []
        pagina = entrar.get('/dashboard/').content.decode()
        assert '(Complemento Contable, por anunciar)' in pagina
