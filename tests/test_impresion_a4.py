"""«Imprimir factura A4» en el listado de ventas: abre el RIDE A4 guardado al autorizarse la factura (también si luego
se anuló), sin reemplazarlo; si faltara, se genera esa única vez. Antes de la autorización no hay RIDE. Mismos permisos
que el ticket; el comprador lo abre desde su listado."""
import pytest
from django.conf import settings
from django.contrib.auth.models import Group

from core.pos.models import Client, Sale
from core.tenancy.models import ROLE_CLIENT, Membership
from tests import helpers
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, producto, sri, vender, venta_de, web  # noqa: F401

pytestmark = pytest.mark.django_db
A4 = '/pos/sale/admin/print/a4/{}/'
LISTA = '/pos/sale/admin/'


@pytest.fixture
def autorizada(web, empresa, comprador, producto, sri):  # noqa: F811
    sri.respuestas_autorizacion = ['AUTORIZADO']
    vender(web, comprador, producto)
    venta = venta_de(empresa, 271)
    assert venta.status in ('authorized', 'authorized_and_sent_by_email') and venta.pdf_authorized
    return venta


def contenido(venta):
    with venta.pdf_authorized.open('rb') as archivo:
        return archivo.read()


def test_abre_el_ride_guardado_sin_reemplazarlo(web, empresa, autorizada):  # noqa: F811
    antes = (autorizada.pdf_authorized.name, contenido(autorizada))
    respuesta = web.get(A4.format(autorizada.pk))
    assert respuesta.status_code == 302 and respuesta['Location'] == autorizada.get_pdf_authorized()
    pdf = web.get(respuesta['Location'])
    assert pdf.status_code == 200 and pdf['Content-Type'] == 'application/pdf'
    assert 'attachment' not in pdf.get('Content-Disposition', '')   # se abre en el navegador para imprimir
    despues = leer(empresa, lambda: Sale.objects.get(pk=autorizada.pk))
    assert (despues.pdf_authorized.name, contenido(despues)) == antes


def test_si_falta_el_pdf_se_genera_una_sola_vez(web, empresa, autorizada):  # noqa: F811
    autorizada.pdf_authorized.storage.delete(autorizada.pdf_authorized.name)
    leer(empresa, lambda: Sale.objects.filter(pk=autorizada.pk).update(pdf_authorized=''))
    respuesta = web.get(A4.format(autorizada.pk))
    generado = leer(empresa, lambda: Sale.objects.get(pk=autorizada.pk))
    assert generado.pdf_authorized and respuesta['Location'] == generado.get_pdf_authorized()
    assert contenido(generado).startswith(b'%PDF') and generado.status == autorizada.status
    web.get(A4.format(autorizada.pk))
    assert leer(empresa, lambda: Sale.objects.get(pk=autorizada.pk)).pdf_authorized.name == generado.pdf_authorized.name


def test_si_falla_al_guardar_el_campo_no_queda_el_archivo(web, empresa, autorizada, monkeypatch):  # noqa: F811
    from django.db.models.query import QuerySet
    autorizada.pdf_authorized.storage.delete(autorizada.pdf_authorized.name)
    leer(empresa, lambda: Sale.objects.filter(pk=autorizada.pk).update(pdf_authorized=''))
    escritos = []
    original = Sale.generate_pdf_authorized

    def generar(self):
        original(self)
        escritos.append(self.pdf_authorized.name)

    actualizar = QuerySet.update

    def falla(self, **campos):
        if self.model is Sale and 'pdf_authorized' in campos:
            raise RuntimeError('fallo simulado al guardar')
        return actualizar(self, **campos)

    monkeypatch.setattr(Sale, 'generate_pdf_authorized', generar)
    monkeypatch.setattr(QuerySet, 'update', falla)
    respuesta = web.get(A4.format(autorizada.pk))
    assert respuesta['Location'] == LISTA and len(escritos) == 1
    assert not autorizada.pdf_authorized.storage.exists(escritos[0])


def test_factura_anulada_por_nota_de_credito_se_imprime(web, empresa, autorizada):  # noqa: F811
    leer(empresa, lambda: Sale.objects.filter(pk=autorizada.pk).update(status='canceled'))
    respuesta = web.get(A4.format(autorizada.pk))
    assert respuesta['Location'] == autorizada.get_pdf_authorized()


def test_el_comprador_imprime_su_factura_desde_su_listado(client, empresa, autorizada):  # noqa: F811
    comprador = leer(empresa, lambda: Client.objects.select_related('user').get(pk=autorizada.client_id))
    comprador.user.set_password(helpers.CLAVE)
    comprador.user.is_active = True
    comprador.user.save()
    comprador.user.groups.add(Group.objects.get(name=ROLE_CLIENT))
    Membership.objects.get_or_create(user=comprador.user, company=empresa, defaults={'group': Group.objects.get(name=ROLE_CLIENT)})
    helpers.iniciar_sesion(client, comprador.user, empresa=empresa)
    respuesta = client.get(f'/pos/sale/client/print/a4/{autorizada.pk}/')
    assert respuesta['Location'] == autorizada.get_pdf_authorized()
    assert client.get(respuesta['Location'])['Content-Type'] == 'application/pdf'


def test_sin_autorizacion_no_hay_ride(web, empresa, comprador, producto, sri):  # noqa: F811
    vender(web, comprador, producto)                                   # RECIBIDA, aún sin autorización
    venta = venta_de(empresa, 271)
    assert venta.status == 'in_process'
    respuesta = web.get(A4.format(venta.pk))
    assert respuesta.status_code == 302 and respuesta['Location'] == LISTA
    assert not leer(empresa, lambda: Sale.objects.get(pk=venta.pk)).pdf_authorized


def test_sin_permiso_de_ventas_o_de_otra_empresa_no_abre(client, empresa, autorizada):  # noqa: F811
    sin_permiso = helpers.crear_usuario('solo.categorias', empresa, helpers.crear_grupo('Solo categorías A4', ['view_category']))
    helpers.iniciar_sesion(client, sin_permiso, empresa=empresa)
    assert client.get(A4.format(autorizada.pk))['Location'] == LISTA
    client.logout()
    otra = helpers.crear_empresa('OTRA A4')
    ajeno = helpers.crear_usuario('dueno.otra.a4', otra)
    helpers.iniciar_sesion(client, ajeno, empresa=otra)
    assert client.get(A4.format(autorizada.pk))['Location'] == LISTA


def test_los_menus_ofrecen_ticket_y_a4():
    js = settings.BASE_DIR / 'core' / 'pos' / 'static' / 'sale'
    admin = (js / 'admin' / 'js' / 'list.js').read_text(encoding='utf-8')
    assert "print/invoice/" in admin and "print/a4/" in admin and 'Imprimir factura A4' in admin and '(anulada)' in admin
    assert 'disponible cuando el SRI la autorice' in admin and 'Imprimir pdf' not in admin
    comprador = (js / 'client' / 'js' / 'list.js').read_text(encoding='utf-8')
    assert "print/a4/" in comprador and 'Imprimir pdf' not in comprador and 'row.pdf_authorized' not in comprador
