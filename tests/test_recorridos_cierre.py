"""Defectos confirmados en la verificación de recorridos del cierre operativo (04/11/2026), con datos ficticios.

- Importar XML desde una pantalla abierta con otra empresa: 409 empresa_cambiada, el lote no se crea en la activa.
- Gasto suelto con valor 0 o negativo: rechazado en el servidor, como al completar un recibo.
- Al negar una página, la vuelta es a la última PÁGINA, nunca a una API que responde JSON.
- Proveedor repetido (razón social, identificación, celular o correo, únicos por empresa): mensaje claro en el campo.
Revisión independiente del mismo día: la vuelta tampoco va a JSON de /cobros/, descargas ni 404; la pestaña de otra
empresa recibe 409 antes que «Mejora tu plan» o el permiso del rol nuevo; el cambio de empresa desde el diálogo de la
factura se confirma en JSON."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from django.contrib.auth.models import Group

from core.importacion import servicios as sv_importacion
from core.importacion.models import LoteImportacion
from core.pos.models import Expenses, Provider
from core.tenancy.context import company_context
from core.suscripciones.models import SubscriptionPeriod
from core.tenancy.models import ROLE_READONLY, Membership
from tests import ayuda_compras as ayuda, helpers
from tests.test_proveedores_ats import _datos_proveedor
from tests.test_revision_flujos import dos_empresas  # noqa: F401 (fixture)

pytestmark = pytest.mark.django_db


def xml():
    return SimpleUploadedFile('factura-ficticia.xml', b'<factura/>', content_type='text/xml')


def lotes(empresa):
    with company_context(empresa):
        return LoteImportacion.objects.count()


def test_importar_xml_desde_una_pantalla_de_otra_empresa(dos_empresas, empresa, empresa_b):
    dos_empresas.post('/empresas/cambiar/', {'company': empresa_b.pk})
    r = dos_empresas.post('/importacion/api/lotes/', {'archivos': xml(), 'empresa': empresa.pk})
    assert (r.status_code, r.json()['codigo']) == (409, 'empresa_cambiada')
    r = dos_empresas.post('/importacion/api/lotes/999999/archivos/', {'archivos': xml(), 'empresa': empresa.pk})
    assert r.status_code == 409
    r = dos_empresas.post('/importacion/nueva/', {'archivos': xml(), 'empresa': empresa.pk})
    assert r.status_code == 302 and r['Location'].endswith('/importacion/nueva/')
    assert (lotes(empresa), lotes(empresa_b)) == (0, 0)
    pagina = dos_empresas.get('/importacion/nueva/').content.decode()
    assert f'name="empresa" value="{empresa_b.pk}"' in pagina   # la pantalla nueva ya lleva la empresa activa


@pytest.mark.parametrize('valor', ['0', '0.00', '-5.00'])
def test_gasto_suelto_con_valor_cero_o_negativo(client, empresa, admin, valor):
    tipo = ayuda.crear_tipo_gasto(empresa, 'MOVILIZACIÓN')
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    datos = {'action': 'add', 'type_expense': tipo.pk, 'description': 'Taxi ficticio', 'date_joined': '2026-11-04',
             'valor': valor, 'medio_pago': 'efectivo', 'referencia': ''}
    error = client.post('/pos/expenses/add/', datos).json()['error']
    assert error['valor'] == ['Escribe el valor del gasto, mayor que cero.']
    with company_context(empresa):
        assert not Expenses.objects.exists()


def test_al_negar_una_pagina_se_vuelve_a_una_pagina_y_no_a_una_api(client, empresa):
    consulta = helpers.crear_usuario('consulta.recorridos', empresa, ROLE_READONLY)
    helpers.iniciar_sesion(client, consulta, empresa=empresa)
    assert client.get('/importacion/pendientes/').status_code == 200
    assert client.get('/importacion/api/documentos/?bandeja=pendientes').status_code == 200
    assert client.session.get('url_last') == '/importacion/pendientes/'
    negada = client.get('/importacion/claves/')
    assert negada.status_code == 302 and negada['Location'] == '/importacion/pendientes/'


@pytest.mark.parametrize('campo, mensaje', [
    ('email', 'Ya existe un proveedor con este correo en tu empresa.'),
    ('name', 'Ya existe un proveedor con esta razón social en tu empresa.'),
])
def test_proveedor_repetido_con_mensaje_claro(client, empresa, admin, campo, mensaje):
    datos = _datos_proveedor()
    existente = ayuda.crear_proveedor(empresa, correo=datos['email'] if campo == 'email' else None,
                                      nombre=datos['name'] if campo == 'name' else None)
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    error = client.post('/pos/provider/add/', {**datos, 'action': 'add'}).json()['error']
    assert error[campo] == [mensaje]
    with company_context(empresa):
        assert list(Provider.objects.values_list('pk', flat=True)) == [existente.pk]


def test_importar_desde_otra_pestana_con_la_empresa_nueva_sin_ilimitado(dos_empresas, empresa, empresa_b):
    SubscriptionPeriod.objects.filter(company=empresa_b).update(document_limit=1000)   # B con plan de límite
    dos_empresas.post('/empresas/cambiar/', {'company': empresa_b.pk})
    r = dos_empresas.post('/importacion/api/lotes/', {'archivos': xml(), 'empresa': empresa.pk})
    assert (r.status_code, r.json()['codigo']) == (409, 'empresa_cambiada')   # no «Mejora tu plan»
    assert (lotes(empresa), lotes(empresa_b)) == (0, 0)


def test_importar_desde_otra_pestana_con_un_rol_sin_importar_en_la_nueva(client, empresa, empresa_b, admin):
    Membership.objects.create(user=admin, company=empresa_b, group=Group.objects.get(name=ROLE_READONLY))
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    client.post('/empresas/cambiar/', {'company': empresa_b.pk})
    for ruta in ('/importacion/api/lotes/', '/importacion/api/lotes/1/archivos/'):
        r = client.post(ruta, {'archivos': xml(), 'empresa': empresa.pk})
        assert (r.status_code, r.json()['codigo']) == (409, 'empresa_cambiada'), ruta   # no «Tu perfil no puede importar»
    sin_pestana = client.post('/importacion/api/lotes/', {'archivos': xml()})
    assert sin_pestana.status_code == 403   # sin empresa en el envío, el permiso de B sigue mandando
    assert (lotes(empresa), lotes(empresa_b)) == (0, 0)


def test_al_negar_una_pagina_no_se_vuelve_a_json_de_cobros_descargas_ni_errores(client, empresa):
    consulta = helpers.crear_usuario('consulta.vuelta', empresa, ROLE_READONLY)
    with company_context(empresa):
        archivo, _ = sv_importacion.guardar_archivo(empresa, consulta, 'factura.xml', b'<factura>ficticia</factura>', 'xml')
    cliente = helpers.crear_cliente('cliente.vuelta', empresa, '0912345675', '0990001112')
    venta = helpers.crear_venta(empresa, cliente, consulta, helpers.crear_producto(empresa))
    helpers.iniciar_sesion(client, consulta, empresa=empresa)
    assert client.get('/importacion/pendientes/').status_code == 200
    assert client.get(f'/cobros/factura/{venta.pk}/')['Content-Type'].startswith('application/json')
    client.get(f'/importacion/archivos/{archivo.pk}/descargar/')
    assert client.get('/importacion/documentos/999999/').status_code == 404
    assert client.session.get('url_last') == '/importacion/pendientes/'
    negada = client.get('/importacion/claves/')
    assert negada.status_code == 302 and negada['Location'] == '/importacion/pendientes/'


def test_volver_a_la_empresa_desde_el_dialogo_se_confirma_en_json(dos_empresas, empresa, empresa_b):
    r = dos_empresas.post('/empresas/cambiar/', {'company': empresa_b.pk, 'next': '/pos/sale/admin/add/'},
                          HTTP_ACCEPT='application/json')
    assert r.status_code == 200 and r.json() == {'ok': True, 'company': empresa_b.pk}
    assert dos_empresas.post('/empresas/cambiar/', {'company': empresa.pk}).status_code == 302   # formulario normal: igual
    dos_empresas.logout()
    sin_sesion = dos_empresas.post('/empresas/cambiar/', {'company': empresa.pk}, HTTP_ACCEPT='application/json')
    assert sin_sesion.status_code == 302 and '/login' in sin_sesion['Location']   # el diálogo no lo toma como confirmación

