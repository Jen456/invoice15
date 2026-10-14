"""Las pantallas de edición sin sesión llevan al login (antes cargaban el registro antes de comprobar la sesión: error 500)."""
import pytest

from tests import helpers

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("ruta", ["/pos/client/update/{cliente}/", "/pos/product/update/{producto}/"])
def test_edicion_sin_sesion_redirige_al_login(client, ruta):
    empresa = helpers.crear_empresa("SINSESION")
    cliente = helpers.crear_cliente("cliente.sinsesion", empresa, "0912345675", "0990000001")
    producto = helpers.crear_producto(empresa)
    url = ruta.format(cliente=cliente.pk, producto=producto.pk)
    for metodo in (client.get, client.post):
        respuesta = metodo(url)
        assert respuesta.status_code == 302 and "/login/" in respuesta["Location"]
