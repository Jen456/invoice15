"""`empresa` en el cuerpo de un envío JSON (core/tenancy/pestanas.py). La pestaña que quedó abierta con otra empresa recibe
409 `empresa_cambiada` antes que el 403 del complemento, del plan o del permiso del rol, igual que ya pasaba con
`?empresa=` o con el campo de un formulario. Un envío JSON que no trae `empresa`, o que no se puede leer, sigue como antes.

La lista de revisión del complemento se fija en cada prueba (el «*» de conftest lo abriría a todas las empresas)."""
import json

import pytest
from django.test import RequestFactory

from core.suscripciones.models import SubscriptionPeriod
from core.tenancy import pestanas
from core.tenancy.models import ROLE_SELLER
from tests import helpers

pytestmark = pytest.mark.django_db

MOVIMIENTOS = '/contabilidad/api/kardex/movimientos/'
CLAVES = '/importacion/api/lotes/claves/'


def enviar(client, url, datos, metodo='post'):
    return getattr(client, metodo)(url, json.dumps(datos), content_type='application/json')


def cambiada(respuesta):
    return respuesta.status_code == 409 and respuesta.json() == {'error': pestanas.EMPRESA_CAMBIADA, 'codigo': 'empresa_cambiada'}


def test_antes_que_el_complemento_cerrado(client, empresa, empresa_b, admin, settings):
    settings.FPA_COMPLEMENTO_CONTABLE_REVISION = []
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    assert cambiada(enviar(client, MOVIMIENTOS, {'clave': 'pestana-json-01', 'empresa': empresa_b.pk}))
    for cuerpo in ({'clave': 'pestana-json-01', 'empresa': empresa.pk}, {'clave': 'pestana-json-01'}):   # la activa, o ninguna
        respuesta = enviar(client, MOVIMIENTOS, cuerpo)
        assert respuesta.status_code == 403 and respuesta.json()['codigo'] == 'complemento_pendiente'
    ilegible = client.post(MOVIMIENTOS, '{"empresa": ', content_type='application/json')   # como si no viniera
    assert ilegible.status_code == 403 and ilegible.json()['codigo'] == 'complemento_pendiente'


def test_antes_que_el_plan(client, empresa, empresa_b, admin, settings):
    settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [empresa.ruc]
    SubscriptionPeriod.objects.filter(company=empresa).delete()   # sin plan pagado
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    assert cambiada(enviar(client, MOVIMIENTOS, {'clave': 'pestana-json-02', 'empresa': empresa_b.pk}))
    respuesta = enviar(client, MOVIMIENTOS, {'clave': 'pestana-json-02', 'empresa': empresa.pk})
    assert respuesta.status_code == 403 and respuesta.json()['plan'] == 'requerido'


def test_antes_que_el_permiso_del_rol(client, empresa, empresa_b, settings):
    settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [empresa.ruc]
    vendedor = helpers.crear_usuario('vendedor.pestana.json', empresa, ROLE_SELLER)   # sin `view_kardex`
    helpers.iniciar_sesion(client, vendedor, empresa=empresa)
    assert cambiada(enviar(client, MOVIMIENTOS, {'clave': 'pestana-json-03', 'empresa': empresa_b.pk}))
    assert enviar(client, MOVIMIENTOS, {'clave': 'pestana-json-03', 'empresa': empresa.pk}).status_code == 403


def test_en_una_vista_que_ya_comprobaba_la_pestana(client, empresa, empresa_b, admin):
    """Las claves pegadas admiten JSON: con `empresa` de otra pestaña no se crea el lote; con la activa, todo sigue igual."""
    from core.importacion.models import LoteImportacion
    from core.tenancy.context import company_context
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    assert cambiada(enviar(client, CLAVES, {'texto': 'nada', 'empresa': empresa_b.pk}))
    for cuerpo in ({'texto': 'nada', 'empresa': empresa.pk}, {'texto': 'nada'}):
        respuesta = enviar(client, CLAVES, cuerpo)
        assert respuesta.status_code == 400 and respuesta.json()['error'] == 'No se encontró ninguna clave de acceso.'
    with company_context(empresa):
        assert LoteImportacion.objects.count() == 0


class TestLectura:
    """Qué empresa se lee de cada petición (sin pasar por las vistas)."""

    def peticion(self, metodo, cuerpo=None, consulta='', tipo='application/json', empresa=7):
        datos = {} if cuerpo is None else {'data': cuerpo if isinstance(cuerpo, str) else json.dumps(cuerpo), 'content_type': tipo}
        request = getattr(RequestFactory(), metodo)(f'/ruta/{consulta}', **datos)
        request.company = type('Empresa', (), {'pk': empresa})()
        return request

    @pytest.mark.parametrize('metodo', ['post', 'patch', 'put', 'delete'])
    def test_cualquier_envio_json(self, metodo):
        assert pestanas.empresa_cambiada(self.peticion(metodo, {'empresa': 8}))
        assert not pestanas.empresa_cambiada(self.peticion(metodo, {'empresa': 7}))
        assert not pestanas.empresa_cambiada(self.peticion(metodo, {'otro': 8}))

    @pytest.mark.parametrize('valor, cambio', [(7, False), ('7', False), (' 7 ', False), (8, True), ('8', True), ('07', True),
                                                (True, True), ([7], True), (None, False), ('', False), (0, False)])
    def test_valores(self, valor, cambio):
        assert pestanas.empresa_cambiada(self.peticion('post', {'empresa': valor})) is cambio

    @pytest.mark.parametrize('cuerpo', ['{"empresa": ', '[8]', '"8"', 'null', '8', '[' * 100000])
    def test_cuerpo_que_no_es_un_objeto(self, cuerpo):
        request = self.peticion('post', cuerpo)
        assert pestanas.cuerpo_json(request) is None and not pestanas.empresa_cambiada(request)

    def test_solo_si_el_envio_es_json(self):
        assert not pestanas.empresa_cambiada(self.peticion('post', '{"empresa": 8}', tipo='text/plain'))
        assert pestanas.cuerpo_json(self.peticion('post', '{"empresa": 8}', tipo='text/plain')) is None
        assert pestanas.empresa_cambiada(self.peticion('post', {'empresa': 8}, tipo='application/json; charset=utf-8'))

    def test_una_consulta_no_lee_el_cuerpo(self):
        request = RequestFactory().generic('GET', '/ruta/', json.dumps({'empresa': 8}), content_type='application/json')
        request.company = type('Empresa', (), {'pk': 7})()
        assert pestanas.cuerpo_json(request) is None and not pestanas.empresa_cambiada(request)

    def test_la_consulta_y_el_formulario_mandan_como_antes(self):
        """`?empresa=` o el campo del formulario se leen primero; el cuerpo JSON solo cuando no vienen."""
        assert pestanas.empresa_pedida(self.peticion('post', {'empresa': 8}, consulta='?empresa=7')) == '7'
        assert not pestanas.empresa_cambiada(self.peticion('post', {'empresa': 8}, consulta='?empresa=7'))
        assert pestanas.empresa_cambiada(self.peticion('post', {'empresa': 7}, consulta='?empresa=8'))
        formulario = RequestFactory().post('/ruta/', {'empresa': '8'})
        formulario.company = type('Empresa', (), {'pk': 7})()
        assert pestanas.empresa_pedida(formulario) == '8' and pestanas.empresa_cambiada(formulario)

    def test_el_cuerpo_se_lee_una_vez_y_la_vista_lo_sigue_teniendo(self):
        request = self.peticion('post', {'empresa': 7, 'texto': 'x'})
        assert pestanas.cuerpo_json(request) is pestanas.cuerpo_json(request) == {'empresa': 7, 'texto': 'x'}
        assert json.loads(request.body) == {'empresa': 7, 'texto': 'x'}
