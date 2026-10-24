"""Compradores del exterior (identificación de hasta 20 caracteres, como en el XML del SRI), varios correos por cliente
y teléfono opcional: formulario, factura autorizada y envío a todas las direcciones."""
import pytest
from django.core import mail

from core.pos.clientes import separar_correos, unir_correos
from core.pos.forms import ClientForm
from core.pos.models import Client
from tests.test_emision_sri import empresa, dueno, leer, p12, producto, sri, vender, venta_de, web  # noqa: F401

pytestmark = pytest.mark.django_db
VENTAS = '/pos/sale/admin/'
BASE = {'mobile': '', 'birthdate': '1990-01-01', 'address': 'Panamá', 'send_email_invoice': True}


@pytest.mark.parametrize('dni, valido, guardado', [
    ('155652251-2-2017 DV7', True, '155652251-2-2017 DV7'),
    (' 155652251-2-2017 dv7 ', True, '155652251-2-2017 DV7'),
    ('155652251-2-2017  DV7', True, '155652251-2-2017 DV7'),
    ('A1B2C3D4E5F6G7H8I9J0', True, 'A1B2C3D4E5F6G7H8I9J0'),     # 20
    ('A1B2C3D4E5F6G7H8I9J0K', False, None),                     # 21
    ('AB#123', False, None),
    ('-AB123', False, None),
    ('AB', False, None),
])
def test_identificacion_del_exterior(dni, valido, guardado):
    formulario = ClientForm({**BASE, 'identification_type': '08', 'dni': dni})
    assert formulario.is_valid() is valido, formulario.errors
    if valido:
        assert formulario.cleaned_data['dni'] == guardado


def test_las_identificaciones_de_ecuador_siguen_validandose():
    assert not ClientForm({**BASE, 'identification_type': '04', 'dni': '155652251-2-2017 DV7'}).is_valid()
    assert not ClientForm({**BASE, 'identification_type': '04', 'dni': '0993385639'}).is_valid()
    assert ClientForm({**BASE, 'identification_type': '04', 'dni': '0993385639 001'}).is_valid()   # espacios fuera
    assert not ClientForm({**BASE, 'identification_type': '08', 'dni': '9999999999999'}).is_valid()


def test_correos_adicionales_del_formulario():
    formulario = ClientForm({**BASE, 'identification_type': '08', 'dni': 'PA123', 'extra_emails': 'b@x.com; c@y.com  B@X.com,'})
    assert formulario.is_valid(), formulario.errors
    assert formulario.cleaned_data['extra_emails'] == 'b@x.com, c@y.com'
    malo = ClientForm({**BASE, 'identification_type': '08', 'dni': 'PA123', 'extra_emails': 'b@x.com, facturación@mendotel'})
    assert not malo.is_valid() and 'facturación@mendotel' in str(malo.errors['extra_emails'])


def test_unir_y_separar_correos():
    assert separar_correos('a@x.com, b@y.com', 'A@X.com;c@z.com') == ['a@x.com', 'b@y.com', 'c@z.com']
    assert unir_correos(['a@x.com', 'b@y.com', 'c@z.com'], 16) == 'a@x.com, b@y.com'
    assert unir_correos(['a@x.com', 'b@y.com'], 15) == 'a@x.com'


def test_factura_a_un_cliente_del_exterior_llega_a_todos_sus_correos(web, empresa, producto, sri):  # noqa: F811
    datos = {'action': 'create_client', 'names': 'PRILABSA LOGISTIC S,A', 'email': 'p@example.com',
             'extra_emails': 'c1@example.com, c2@example.com', 'dni': '155652251-2-2017 DV7', 'identification_type': '08',
             'mobile': '', 'birthdate': '1990-01-01', 'address': 'Panapark Free Zone, Panamá', 'send_email_invoice': 'on'}
    creado = web.post(f'{VENTAS}add/', datos).json()
    assert 'error' not in creado, creado
    cliente = leer(empresa, lambda: Client.objects.select_related('user').get(pk=creado['id']))
    assert (cliente.dni, cliente.mobile, cliente.correos()) == ('155652251-2-2017 DV7', '', ['p@example.com', 'c1@example.com', 'c2@example.com'])
    sri.respuestas_autorizacion = ['AUTORIZADO']
    vender(web, cliente, producto)
    venta = venta_de(empresa, 271)
    assert venta.status == 'authorized_and_sent_by_email'
    assert mail.outbox[-1].to == ['p@example.com', 'c1@example.com', 'c2@example.com']
    assert '<tipoIdentificacionComprador>08</tipoIdentificacionComprador>' in venta.xml_signed
    assert '<identificacionComprador>155652251-2-2017 DV7</identificacionComprador>' in venta.xml_signed
    assert 'p@example.com, c1@example.com, c2@example.com</campoAdicional>' in venta.xml_signed
    assert 'telfCliente' not in venta.xml_signed and 'nombre="Teléfono"' not in venta.xml_signed
