"""Usuarios con el correo confirmado (registro propio) en los listados JSON.

email_verified_at es una fecha y hora: User.toJSON() debe enviarla como texto,
si no, el listado de usuarios y el de ventas (que incluye al vendedor) fallan.
"""
import json

import pytest
from django.utils import timezone

from tests import helpers

pytestmark = pytest.mark.django_db


def test_listado_de_usuarios_con_correo_confirmado(client, admin, empresa):
    admin.email_verified_at = timezone.now()
    admin.save(update_fields=['email_verified_at'])
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    respuesta = client.post('/user/', {'action': 'search'})
    assert respuesta.status_code == 200
    datos = respuesta.json()
    fila = next(u for u in datos if u['username'] == admin.username)
    assert isinstance(fila['email_verified_at'], str) and len(fila['email_verified_at']) == 10


def test_listado_de_ventas_con_vendedor_confirmado(client, admin, empresa):
    admin.email_verified_at = timezone.now()
    admin.save(update_fields=['email_verified_at'])
    cliente = helpers.crear_cliente('cli.json', empresa, '0911111111', '0991111111')
    producto = helpers.crear_producto(empresa, 'JSON')
    helpers.crear_venta(empresa, cliente, admin, producto)
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    respuesta = client.post('/pos/sale/admin/', {'action': 'search', 'start_date': '', 'end_date': ''})
    assert respuesta.status_code == 200
    assert json.loads(respuesta.content)[0]['employee']['username'] == admin.username
