"""Panel y empresa activa (primera entrega, §12 y §7 primer punto).

§12: tras iniciar sesión con varios comercios la página inicial respondía 500 (TenantScopeError en el panel: «/» no pasaba
por el selector de empresa). §7: la cabecera mostraba una empresa y la barra lateral otro nombre (el del usuario). Aquí se
prueba el ingreso con uno y con varios comercios y que, al elegir o cambiar de RUC, la cabecera, la barra lateral, el menú,
el punto de emisión, los filtros y las cifras del panel sean de la empresa activa; también el id viejo en la sesión, la
membresía o la empresa desactivadas, el superusuario, el usuario sin empresas, `next` y dos pestañas. Datos ficticios.
"""
import re

import pytest
from django.contrib.auth.models import Group

from core.configuracion.models import PuntoSeleccionado
from core.pos.models import Company, EmissionPoint, Establishment, Product
from core.security.models import Dashboard
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, ROLE_SELLER, AuditLog, Membership
from core.tenancy.pestanas import EMPRESA_CAMBIADA
from tests import helpers

pytestmark = pytest.mark.django_db

SELECTOR = '/empresas/'
CAMBIAR = '/empresas/cambiar/'
VENTAS = '/pos/sale/admin/'
BUSCAR = {'action': 'search', 'start_date': '', 'end_date': ''}


# ---------------------------------------------------------------- lectura de la página

def rucs_activos(html):
    """RUC de la empresa activa en la cabecera (selector de empresa) y en la barra lateral, en ese orden."""
    return re.findall(r'class="[^"]*fp-empresa-activa[^"]*" data-empresa-ruc="([^"]*)"', html)


def empresa_de_la_pagina(html):
    """Empresa con la que se armó la página (la cabecera X-FPA-Empresa de sus peticiones AJAX)."""
    m = re.search(r'<meta name="fpa-empresa" content="(\d+)">', html)
    return int(m.group(1)) if m else None


def sin_botones_de_cambio(html):
    """La página sin los botones «cambiar a…» de la cabecera, que listan las demás empresas del usuario."""
    return re.sub(r'<form method="post" action="/empresas/cambiar/".*?</form>', '', html, flags=re.S)


def filtro_de_puntos(html):
    m = re.search(r'<select id="fpFiltroPunto".*?</select>', html, flags=re.S)
    return m.group(0) if m else ''


def html_de(respuesta):
    assert respuesta.status_code == 200, respuesta.status_code
    return respuesta.content.decode()


def assert_solo_empresa(respuesta, activa, otra):
    """Cabecera, barra lateral y página: solo `activa` (la `otra` solo aparece como botón para cambiar a ella)."""
    html = html_de(respuesta)
    assert rucs_activos(html) == [activa.ruc, activa.ruc]
    assert f'<span class="fp-empresa-nombre">{activa.tradename}</span><small class="fp-empresa-ruc">RUC {activa.ruc}</small>' in html
    assert f'{activa.tradename} · RUC {activa.ruc}' in html and f'<small class="d-block">RUC {activa.ruc}</small>' in html
    assert empresa_de_la_pagina(html) == activa.pk and respuesta.context['company'].pk == activa.pk
    resto = sin_botones_de_cambio(html)
    assert otra.ruc not in resto and otra.tradename not in resto   # tampoco sus locales («Matriz ALFA»…) ni productos
    return html


# ---------------------------------------------------------------- datos ficticios

def nombrar_matriz(empresa, nombre):
    with company_context(empresa):
        Establishment.objects.filter(code='001').update(name=nombre)


def otro_local(empresa, nombre, estab='002'):
    with company_context(empresa):
        est = Establishment.objects.create(code=estab, name=nombre, address=f'Calle {nombre}')
        return EmissionPoint.objects.create(establishment=est, code='001', description='Caja')


@pytest.fixture
def alfa(db):
    empresa = helpers.crear_empresa('ALFA')
    helpers.configurar_facturacion(empresa)
    nombrar_matriz(empresa, 'Matriz ALFA')
    return empresa


@pytest.fixture
def beta(db):
    empresa = helpers.crear_empresa('BETA')
    helpers.configurar_facturacion(empresa)
    nombrar_matriz(empresa, 'Matriz BETA')
    return empresa


@pytest.fixture
def multi(alfa, beta):
    """Propietaria en ALFA y Vendedora en BETA (otro rol, otro menú)."""
    user = helpers.crear_usuario('multi.comercio', alfa, ROLE_OWNER)
    Membership.objects.create(user=user, company=beta, group=Group.objects.get(name=ROLE_SELLER))
    return user


@pytest.fixture
def datos(alfa, beta, multi):
    """Dos clientes, un producto y una venta en ALFA; un cliente, un producto y una venta en BETA."""
    cli_a = helpers.crear_cliente('cli.alfa', alfa, '0911111111', '0991111111')
    helpers.crear_cliente('cli.alfa.2', alfa, '0922222222', '0992222222')
    cli_b = helpers.crear_cliente('cli.beta', beta, '0911111111', '0991111111')
    prod_a = helpers.crear_producto(alfa, 'ALFA-1')
    prod_b = helpers.crear_producto(beta, 'BETA-1')
    with company_context(alfa):
        Product.objects.filter(pk=prod_a.pk).update(name='PRODUCTO ALFA')
    with company_context(beta):
        Product.objects.filter(pk=prod_b.pk).update(name='PRODUCTO BETA')
    return {'venta_a': helpers.crear_venta(alfa, cli_a, multi, prod_a), 'venta_b': helpers.crear_venta(beta, cli_b, multi, prod_b),
            'norte_a': otro_local(alfa, 'Local Norte ALFA')}


@pytest.fixture(autouse=True)
def menu_lateral(db):
    Dashboard.objects.update(layout=1)   # vtc: cabecera y barra lateral (el diseño de la revisión)


# ---------------------------------------------------------------- un comercio

class TestUnComercio:

    def test_ingreso_entra_al_panel_con_su_ruc(self, client, alfa):
        user = helpers.crear_usuario('uno.comercio', alfa, ROLE_OWNER)
        respuesta = client.post('/login/', {'username': user.username, 'password': helpers.CLAVE}, follow=True)
        assert respuesta.redirect_chain == [('/dashboard/', 302)]
        html_de(respuesta)
        assert rucs_activos(respuesta.content.decode()) == [alfa.ruc, alfa.ruc]
        assert client.session['company_id'] == alfa.pk
        inicio = client.get('/')   # «Inicio», el logo y «Continuar» de /login/authenticated/ llevan a «/»
        assert rucs_activos(html_de(inicio)) == [alfa.ruc, alfa.ruc]
        assert 'href="/"' in html_de(client.get('/login/authenticated/'))

    @pytest.mark.parametrize('layout, lateral', [(1, True), (2, False)])
    def test_la_cabecera_muestra_el_ruc_en_los_dos_disenos(self, client, alfa, layout, lateral):
        Dashboard.objects.update(layout=layout)
        helpers.iniciar_sesion(client, helpers.crear_usuario('uno.comercio', alfa, ROLE_OWNER))
        html = html_de(client.get('/'))
        assert rucs_activos(html) == [alfa.ruc] * (2 if lateral else 1)
        assert f'<span class="fp-empresa-nombre">ALFA</span><small class="fp-empresa-ruc">RUC {alfa.ruc}</small>' in html
        assert f'ALFA · RUC {alfa.ruc}' in html and f'Empresa activa: ALFA, RUC {alfa.ruc}' in html


# ---------------------------------------------------------------- varios comercios

class TestVariosComercios:

    def test_ingreso_lleva_al_selector_y_no_al_error(self, client, multi, alfa, beta):
        respuesta = client.post('/login/', {'username': multi.username, 'password': helpers.CLAVE}, follow=True)
        assert respuesta.redirect_chain == [('/dashboard/', 302), (SELECTOR, 302)]
        html = html_de(respuesta)
        assert f'RUC {alfa.ruc}' in html and f'RUC {beta.ruc}' in html and rucs_activos(html) == []
        assert client.get('/')['Location'] == SELECTOR   # antes: 500 TenantScopeError
        client.logout()
        respuesta = client.post('/login/?next=/', {'username': multi.username, 'password': helpers.CLAVE}, follow=True)
        assert respuesta.redirect_chain == [('/', 302), (SELECTOR, 302)]

    def test_elegir_a_muestra_a_en_cabecera_menu_filtros_y_panel(self, client, multi, alfa, beta, datos):
        helpers.iniciar_sesion(client, multi)
        eleccion = client.post(CAMBIAR, {'company': alfa.pk})
        assert eleccion['Location'] == '/dashboard/'
        panel = client.get('/')
        html = assert_solo_empresa(panel, alfa, beta)
        assert 'href="/pos/company/update/"' in html   # menú de Propietaria
        assert panel.context['clients'] == 2 and [v.pk for v in panel.context['sales']] == [datos['venta_a'].pk]
        assert {p.company_id for p in panel.context['fpa_puntos']} == {alfa.pk} and panel.context['fpa_punto'].company_id == alfa.pk
        grafico = client.post('/', {'action': 'get_graph_stock_products'}).json()
        assert [nombre for nombre, _ in grafico] == ['PRODUCTO ALFA']
        ventas = client.get(VENTAS)
        filtro = filtro_de_puntos(assert_solo_empresa(ventas, alfa, beta))
        assert 'Matriz ALFA' in filtro and 'Local Norte ALFA' in filtro and 'BETA' not in filtro
        assert [v['id'] for v in client.post(VENTAS, BUSCAR).json()] == [datos['venta_a'].pk]

    def test_cambiar_a_b_muestra_b_sin_nada_de_a(self, client, multi, alfa, beta, datos):
        helpers.iniciar_sesion(client, multi, empresa=alfa)
        with company_context(alfa):   # punto elegido en ALFA: no debe seguir al cambiar
            PuntoSeleccionado.objects.create(user=multi, emission_point=datos['norte_a'])
        assert client.get('/').context['fpa_punto'].pk == datos['norte_a'].pk
        clave = client.session.session_key
        cambio = client.post(CAMBIAR, {'company': beta.pk})
        assert cambio['Location'] == '/dashboard/' and client.session.session_key != clave
        assert AuditLog.objects.filter(user=multi, action='company_switch', company=beta).exists()
        panel = client.get('/')
        html = assert_solo_empresa(panel, beta, alfa)
        assert 'href="/pos/company/update/"' not in html and f'RUC {beta.ruc} · {ROLE_SELLER}' in html   # menú y rol de BETA
        assert panel.context['clients'] == 1 and [v.pk for v in panel.context['sales']] == [datos['venta_b'].pk]
        assert {p.company_id for p in panel.context['fpa_puntos']} == {beta.pk}
        assert panel.context['fpa_punto'].company_id == beta.pk and 'Matriz BETA' in html and 'Local Norte' not in html
        assert [nombre for nombre, _ in client.post('/', {'action': 'get_graph_stock_products'}).json()] == ['PRODUCTO BETA']
        ventas = client.get(VENTAS)
        filtro = filtro_de_puntos(assert_solo_empresa(ventas, beta, alfa))
        assert 'Matriz BETA' in filtro and 'ALFA' not in filtro
        assert [v['id'] for v in client.post(VENTAS, BUSCAR).json()] == [datos['venta_b'].pk]
        # un id de ALFA en el filtro (pestaña vieja, enlace copiado) no muestra nada de ALFA
        assert client.post(VENTAS, {**BUSCAR, 'punto': datos['norte_a'].pk}).json() == []
        assert client.post(VENTAS, {**BUSCAR, 'punto': datos['venta_a'].receipt.emission_point_id}).json() == []
        # de vuelta en ALFA, su punto elegido sigue siendo el suyo
        client.post(CAMBIAR, {'company': alfa.pk})
        assert client.get('/').context['fpa_punto'].pk == datos['norte_a'].pk

    def test_cambiar_con_next_abre_esa_pagina_en_la_empresa_nueva(self, client, multi, alfa, beta):
        helpers.iniciar_sesion(client, multi, empresa=alfa)
        assert client.post(CAMBIAR, {'company': beta.pk, 'next': VENTAS})['Location'] == VENTAS
        assert_solo_empresa(client.get(VENTAS), beta, alfa)
        for ajeno in ('https://ejemplo.invalid/', '//ejemplo.invalid/', '/\\ejemplo.invalid/', 'javascript:alert(1)', ''):
            assert client.post(CAMBIAR, {'company': alfa.pk, 'next': ajeno})['Location'] == '/dashboard/', ajeno
            assert 'name="next"' not in html_de(client.get(SELECTOR, {'next': ajeno})), ajeno
        assert f'name="next" value="{VENTAS}"' in html_de(client.get(SELECTOR, {'next': VENTAS}))

    def test_id_viejo_de_empresa_en_la_sesion(self, client, multi, alfa, beta):
        ajena = helpers.crear_empresa('AJENA')
        helpers.iniciar_sesion(client, multi, empresa=alfa)
        for viejo in (ajena.pk, 999999):
            sesion = client.session
            sesion.update({'company_id': viejo, 'url_last': VENTAS, 'module_id': 1})
            sesion.save()
            assert client.get('/')['Location'] == SELECTOR
            assert not {'company_id', 'url_last', 'module_id'} & set(client.session.keys())
        uno = helpers.crear_usuario('uno.comercio', alfa, ROLE_OWNER)
        client.logout()
        helpers.iniciar_sesion(client, uno)
        sesion = client.session
        sesion['company_id'] = ajena.pk
        sesion.save()
        assert rucs_activos(html_de(client.get('/'))) == [alfa.ruc, alfa.ruc]   # con una sola empresa, la suya

    def test_membresia_desactivada_en_plena_sesion(self, client, multi, alfa, beta):
        helpers.iniciar_sesion(client, multi, empresa=alfa)
        client.get(VENTAS)
        assert client.session['url_last'] == VENTAS
        Membership.objects.filter(user=multi, company=alfa).update(is_active=False)
        assert_solo_empresa(client.get('/'), beta, alfa)   # le queda una: la sesión pasa a BETA, nunca sigue en ALFA
        assert client.session['company_id'] == beta.pk and 'url_last' not in client.session   # ni la última página de ALFA
        assert client.post(CAMBIAR, {'company': alfa.pk}).status_code == 404
        Membership.objects.filter(user=multi, company=beta).update(is_active=False)
        assert client.get('/')['Location'] == SELECTOR

    def test_empresa_desactivada_en_plena_sesion(self, client, multi, alfa, beta):
        tercera = helpers.crear_empresa('GAMMA')
        Membership.objects.create(user=multi, company=tercera, group=Membership.objects.get(user=multi, company=alfa).group)
        helpers.iniciar_sesion(client, multi, empresa=alfa)
        Company.objects.filter(pk=alfa.pk).update(is_active=False)
        assert client.get('/')['Location'] == SELECTOR   # le quedan dos: elige otra vez
        selector = html_de(client.get(SELECTOR))
        assert f'RUC {alfa.ruc}' not in selector and f'RUC {beta.ruc}' in selector and f'RUC {tercera.ruc}' in selector
        assert client.post(CAMBIAR, {'company': alfa.pk}).status_code == 404

    def test_sin_empresas_no_hay_bucle(self, client):
        helpers.iniciar_sesion(client, helpers.crear_usuario('sin.comercio'))
        for ruta in ('/', '/dashboard/', VENTAS):
            respuesta = client.get(ruta, follow=True)
            assert respuesta.redirect_chain == [(SELECTOR, 302)]
            assert 'no pertenece a ninguna empresa activa' in html_de(respuesta)
        assert client.post('/', {'action': 'get_graph_stock_products'}).status_code == 403

    def test_superusuario_elige_y_ve_esa_empresa(self, client, superusuario, alfa, beta):
        helpers.iniciar_sesion(client, superusuario)
        assert client.get('/')['Location'] == SELECTOR
        assert 'Ir al panel de la plataforma' in html_de(client.get(SELECTOR))
        client.post(CAMBIAR, {'company': beta.pk})
        html = assert_solo_empresa(client.get('/'), beta, alfa)
        assert 'href="/pos/company/update/"' in html   # actúa como Propietario (auditado como platform_enter)
        assert AuditLog.objects.filter(user=superusuario, action='platform_enter', company=beta).exists()


# ---------------------------------------------------------------- dos pestañas

class TestDosPestanas:
    """La pestaña 1 se armó con ALFA; en la pestaña 2 se cambió a BETA. Lo que la 1 pide por AJAX (filtros, listados,
    gráficos, guardados) lleva X-FPA-Empresa=ALFA: 409 empresa_cambiada, sin datos de BETA bajo la cabecera de ALFA."""

    def test_ajax_de_la_pestana_vieja_responde_409(self, client, multi, alfa, beta, datos):
        helpers.iniciar_sesion(client, multi, empresa=alfa)
        pestana_1 = empresa_de_la_pagina(html_de(client.get(VENTAS)))
        assert pestana_1 == alfa.pk
        client.post(CAMBIAR, {'company': beta.pk})   # pestaña 2
        vieja = {'HTTP_X_FPA_EMPRESA': str(pestana_1)}
        for ruta, datos_post in ((VENTAS, BUSCAR), ('/', {'action': 'get_graph_stock_products'}),
                                 ('/pos/product/', {'action': 'search'})):
            respuesta = client.post(ruta, datos_post, **vieja)
            assert respuesta.status_code == 409, ruta
            assert respuesta.json() == {'error': EMPRESA_CAMBIADA, 'codigo': 'empresa_cambiada'}
        assert client.get('/pos/product/', **vieja).status_code == 409
        # la pestaña recargada (BETA) y las peticiones sin cabecera siguen como siempre
        assert [v['id'] for v in client.post(VENTAS, BUSCAR, HTTP_X_FPA_EMPRESA=str(beta.pk)).json()] == [datos['venta_b'].pk]
        assert [v['id'] for v in client.post(VENTAS, BUSCAR).json()] == [datos['venta_b'].pk]

    def test_volver_a_la_empresa_de_la_pestana_no_se_bloquea(self, client, multi, alfa, beta):
        helpers.iniciar_sesion(client, multi, empresa=beta)
        respuesta = client.post(CAMBIAR, {'company': alfa.pk}, HTTP_X_FPA_EMPRESA=str(beta.pk), HTTP_ACCEPT='application/json')
        assert respuesta.json() == {'ok': True, 'company': alfa.pk}
        assert client.post('/', {'action': 'get_graph_stock_products'}, HTTP_X_FPA_EMPRESA=str(alfa.pk)).status_code == 200

    def test_sin_empresa_activa_la_cabecera_no_cambia_el_403(self, client, multi, alfa):
        helpers.iniciar_sesion(client, multi)
        respuesta = client.post(VENTAS, BUSCAR, HTTP_X_FPA_EMPRESA=str(alfa.pk))
        assert respuesta.status_code == 403 and respuesta.json()['error'] == 'Selecciona una empresa para continuar'


def test_error_en_un_grafico_del_panel_responde_json(client, alfa, monkeypatch):
    """data era una lista y data['error'] daba TypeError (500)."""
    class Falla:
        class objects:
            @staticmethod
            def filter(**_):
                raise RuntimeError('fallo ficticio')
    monkeypatch.setattr('core.dashboard.views.Product', Falla)
    helpers.iniciar_sesion(client, helpers.crear_usuario('uno.comercio', alfa, ROLE_OWNER))
    respuesta = client.post('/', {'action': 'get_graph_stock_products'})
    assert respuesta.status_code == 200 and respuesta.json() == {'error': 'fallo ficticio'}
