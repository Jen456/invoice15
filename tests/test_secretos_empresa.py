"""Las claves guardadas de la empresa (firma .p12 y SMTP) nunca vuelven al navegador
y un campo vacío al guardar conserva la anterior."""
import json
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core.pos.forms import CompanyForm
from core.tenancy.models import ROLE_CLIENT
from tests import helpers

pytestmark = pytest.mark.django_db

CLAVE_P12 = 'clave-p12-de-prueba-7Q2'
CLAVE_SMTP = 'smtp-de-prueba-9W4'


@pytest.fixture
def empresa_con_claves(empresa):
    empresa.electronic_signature_key = CLAVE_P12
    empresa.email_host_user = 'facturas@example.com'
    empresa.email_host_password = CLAVE_SMTP
    empresa.save()
    return empresa


def datos_del_formulario(empresa, **cambios):
    datos = {k: v for k, v in CompanyForm(instance=empresa).initial.items()
             if v is not None and k not in ('image', 'electronic_signature')}
    datos.update(electronic_signature_key='', email_host_password='', action='create_or_edit')
    datos.update(cambios)
    return datos


def test_el_formulario_no_devuelve_las_claves(client, admin, empresa_con_claves):
    helpers.iniciar_sesion(client, admin, empresa=empresa_con_claves)
    html = client.get('/pos/company/update/').content.decode()
    assert CLAVE_P12 not in html and CLAVE_SMTP not in html
    assert 'Guardada. Déjala vacía para conservarla' in html


def test_campo_vacio_conserva_y_valor_nuevo_reemplaza(client, admin, empresa_con_claves):
    helpers.iniciar_sesion(client, admin, empresa=empresa_con_claves)
    respuesta = client.post('/pos/company/update/', datos_del_formulario(empresa_con_claves, tradename='NUEVO NOMBRE'))
    assert 'error' not in respuesta.json(), respuesta.json()
    empresa_con_claves.refresh_from_db()
    assert empresa_con_claves.tradename == 'NUEVO NOMBRE'
    assert (empresa_con_claves.electronic_signature_key, empresa_con_claves.email_host_password) == (CLAVE_P12, CLAVE_SMTP)

    client.post('/pos/company/update/', datos_del_formulario(empresa_con_claves, email_host_password='otra-clave-smtp'))
    empresa_con_claves.refresh_from_db()
    assert empresa_con_claves.email_host_password == 'otra-clave-smtp'
    assert empresa_con_claves.electronic_signature_key == CLAVE_P12


def test_empresa_sin_claves_puede_guardar_vacio(empresa):
    form = CompanyForm(datos_del_formulario(empresa), instance=empresa)
    assert form.is_valid(), form.errors
    form.save()
    empresa.refresh_from_db()
    assert empresa.electronic_signature_key == '' and empresa.email_host_password == ''


def test_las_ventas_en_json_no_llevan_secretos(client, admin, empresa_con_claves):
    cliente = helpers.crear_cliente('cli.secretos', empresa_con_claves, '0911111111', '0991111111')
    producto = helpers.crear_producto(empresa_con_claves, 'SEC')
    helpers.crear_venta(empresa_con_claves, cliente, admin, producto)
    helpers.iniciar_sesion(client, admin, empresa=empresa_con_claves)
    cuerpo = client.post('/pos/sale/admin/', {'action': 'search', 'start_date': '', 'end_date': ''}).content.decode()
    datos = json.loads(cuerpo)
    assert datos and CLAVE_P12 not in cuerpo and CLAVE_SMTP not in cuerpo and 'facturas@example.com' not in cuerpo
    assert 'email_host_password' not in datos[0]['company'] and datos[0]['company']['electronic_signature'] is False

    # El cliente de la empresa ve sus compras sin datos privados de la empresa
    helpers.iniciar_sesion(client, cliente.user, empresa=empresa_con_claves)
    cuerpo = client.post('/pos/sale/client/', {'action': 'search', 'start_date': '', 'end_date': ''}).content.decode()
    assert CLAVE_P12 not in cuerpo and CLAVE_SMTP not in cuerpo


def test_ver_certificado_usa_la_clave_guardada(client, admin, empresa_con_claves):
    empresa_con_claves.electronic_signature = SimpleUploadedFile('firma.p12', b'contenido-ficticio')
    empresa_con_claves.save()
    certificado = mock.Mock(subject=[])
    certificado.public_key.return_value.public_bytes.return_value = b'-----BEGIN PUBLIC KEY-----'
    helpers.iniciar_sesion(client, admin, empresa=empresa_con_claves)
    with mock.patch('core.pos.views.company.views.pkcs12.load_key_and_certificates',
                    return_value=(None, certificado, None)) as cargar:
        respuesta = client.post('/pos/company/update/', {'action': 'load_certificate', 'electronic_signature_key': ''})
    assert 'error' not in respuesta.json()
    assert cargar.call_args.args[1] == CLAVE_P12.encode()
    assert CLAVE_P12 not in respuesta.content.decode()
