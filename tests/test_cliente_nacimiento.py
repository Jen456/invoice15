"""Fecha de nacimiento del cliente opcional (hallazgo de Codex, 30/10/2026): antes el modelo la exigía y el formulario la
precargaba con la fecha de hoy, también para empresas con RUC. Ahora el servidor admite vacío, no inventa una fecha, no
infiere el tipo de persona y no toca los valores guardados."""
import pytest

from core.pos.models import Client
from tests import helpers
from tests.test_emision_sri import VENTAS, dueno, empresa, leer, p12, web  # noqa: F401

pytestmark = pytest.mark.django_db
EMPRESA = {'action': 'create_client', 'names': 'IMPORTADORA SIN CUMPLEAÑOS S.A.', 'email': 'empresa.sin.fecha@example.com',
           'identification_type': '04', 'dni': '0992560541001', 'mobile': '0990000011', 'birthdate': '', 'address': 'Guayaquil',
           'send_email_invoice': 'on'}


def test_alta_desde_la_factura_sin_fecha_de_nacimiento(web, empresa):  # noqa: F811
    datos = web.post(f'{VENTAS}add/', {**EMPRESA, 'empresa': empresa.pk}).json()
    assert 'error' not in datos, datos
    cliente = leer(empresa, lambda: Client.objects.get(dni='0992560541001'))
    assert cliente.birthdate is None and datos['birthdate'] == '' and cliente.identification_type == '04'
    assert cliente.birthdate_format() == '' and leer(empresa, lambda: cliente.toJSON())['birthdate'] == ''
    # con fecha sigue funcionando igual
    con_fecha = web.post(f'{VENTAS}add/', {**EMPRESA, 'empresa': empresa.pk, 'names': 'PERSONA NATURAL', 'identification_type': '05', 'dni': '1710034065',
                                           'email': 'persona@example.com', 'mobile': '0990000012', 'birthdate': '1990-01-01'}).json()
    assert 'error' not in con_fecha, con_fecha
    assert con_fecha['birthdate'] == '1990-01-01'


def test_el_formulario_no_precarga_la_fecha_de_hoy(web):  # noqa: F811
    html = web.get(f'{VENTAS}add/').content.decode()
    campo = next(linea for linea in html.splitlines() if 'name="birthdate"' in linea)
    assert 'value=' not in campo and 'La fecha es obligatoria' not in html
    assert 'Fecha de nacimiento (opcional)' in html or 'opcional' in html.lower()


def test_los_clientes_guardados_no_cambian(empresa):  # noqa: F811
    cliente = helpers.crear_cliente('con.fecha', empresa, '0912345675', '0990000013')
    assert leer(empresa, lambda: Client.objects.get(pk=cliente.pk).birthdate.isoformat()) == '1990-01-01'
