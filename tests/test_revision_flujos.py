"""Regresiones de la revisión de flujos de Codex (04/11/2026, entregas/facturaporaqui/REVISION-FLUJOS-20261104.md).

R1: el alta rápida de cliente solo escribe en la empresa en que se abrió el formulario: si la empresa activa cambió en
otra pestaña, 409 `empresa_cambiada` sin cliente, usuario ni membresía; las búsquedas del diálogo, igual; un formulario
sin empresa (versión anterior) no crea nada.
R3: importar el Excel de productos exige el permiso de cada efecto (alta, modificación, ajuste de stock, categoría nueva);
una fila prohibida rechaza el lote entero con 403 y sin escrituras, tampoco en el kardex."""
import re
from decimal import Decimal
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from core.contabilidad.models import AjusteInventario
from core.pos.models import Category, Client, Product
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_READONLY, ROLE_SELLER, Membership
from core.user.models import User
from tests import helpers

pytestmark = pytest.mark.django_db
VENTAS = '/pos/sale/admin/add/'
CLIENTE = {'action': 'create_client', 'identification_type': '04', 'dni': '0992560541001',
           'names': 'CLIENTE FICTICIO DE AUDITORIA', 'address': 'Direccion ficticia', 'mobile': '0990000011',
           'email': 'cliente@example.test', 'birthdate': '', 'extra_emails': ''}


def clientes(empresa):
    with company_context(empresa):
        return Client.objects.filter(dni=CLIENTE['dni']).count()


@pytest.fixture
def dos_empresas(client, empresa, empresa_b, admin):
    """El propietario de A también es propietario de B; la sesión empieza en A."""
    Membership.objects.create(user=admin, company=empresa_b, group=Membership.objects.get(user=admin, company=empresa).group)
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    return client


class TestClienteEnLaEmpresaDeOrigen:

    def test_el_formulario_conserva_la_empresa(self, dos_empresas, empresa):
        html = dos_empresas.get(VENTAS).content.decode()
        dialogo = re.search(r'<form\b[^>]*\bid="frmClient"[^>]*>(.*?)</form>', html, re.S).group(1)
        assert re.search(rf'name="empresa" value="{empresa.pk}"', dialogo)

    def test_alta_y_busqueda_en_la_empresa_activa(self, dos_empresas, empresa):
        r = dos_empresas.post(VENTAS, {**CLIENTE, 'empresa': empresa.pk})
        assert r.status_code == 200 and r.json().get('id'), r.json()
        assert clientes(empresa) == 1
        repetido = dos_empresas.post(VENTAS, {'action': 'validate_client', 'pattern': 'dni', 'parameter': CLIENTE['dni'],
                                              'empresa': empresa.pk}).json()
        assert repetido == {'valid': False, 'message': 'Ya existe un cliente con esta identificación. Puedes buscarlo aquí.'}
        # respuesta perdida: la búsqueda con la empresa de origen lo encuentra
        encontrados = dos_empresas.post(VENTAS, {'action': 'search_client', 'term': CLIENTE['dni'], 'empresa': empresa.pk}).json()
        assert [c['dni'] for c in encontrados] == [CLIENTE['dni']]

    def test_otra_pestana_no_crea_cliente_usuario_ni_membresia(self, dos_empresas, empresa, empresa_b):
        dos_empresas.post('/empresas/cambiar/', {'company': empresa_b.pk})
        usuarios, membresias = User.objects.count(), Membership.objects.count()
        r = dos_empresas.post(VENTAS, {**CLIENTE, 'empresa': empresa.pk})
        assert (r.status_code, r.json()['codigo']) == (409, 'empresa_cambiada')
        assert (clientes(empresa), clientes(empresa_b)) == (0, 0)
        assert (User.objects.count(), Membership.objects.count()) == (usuarios, membresias)

    def test_busquedas_del_dialogo_con_la_empresa_de_origen(self, dos_empresas, empresa, empresa_b):
        helpers.crear_cliente('cliente.de.b', empresa_b, '0912345675', '0990000003')
        dos_empresas.post('/empresas/cambiar/', {'company': empresa_b.pk})
        for datos in ({'action': 'search_client', 'term': '0912345675'},
                      {'action': 'validate_client', 'pattern': 'dni', 'parameter': '0912345675'}):
            r = dos_empresas.post(VENTAS, {**datos, 'empresa': empresa.pk})
            assert (r.status_code, r.json()['codigo']) == (409, 'empresa_cambiada')   # no muestra clientes de B
            if datos['action'] == 'validate_client':   # el validador remoto muestra este mensaje junto al campo
                assert r.json()['valid'] is False and 'empresa activa cambió' in r.json()['message']
            assert dos_empresas.post(VENTAS, datos).status_code == 200                  # sin empresa, como antes

    def test_formulario_sin_empresa_no_crea_nada(self, dos_empresas, empresa):
        usuarios = User.objects.count()
        r = dos_empresas.post(VENTAS, CLIENTE)
        assert (r.status_code, r.json()['codigo']) == (409, 'sin_empresa')
        assert clientes(empresa) == 0 and User.objects.count() == usuarios


def excel(*filas):
    libro = Workbook()
    libro.active.append(['Id', 'Nombre', 'Codigo', 'Categoria', 'Costo', 'PVP', 'Stock', 'Inventariado', 'IVA', 'Tarifa'])
    for fila in filas:
        libro.active.append(list(fila))
    contenido = BytesIO()
    libro.save(contenido)
    return SimpleUploadedFile('catalogo-ficticio.xlsx', contenido.getvalue())


def fila(producto, pvp=None, stock=None, categoria='CATEGORÍA FICTICIA', inventariado='si'):
    return [producto.pk, producto.name, producto.code, categoria, 5, pvp if pvp is not None else 10, stock if stock is not None else 100,
            inventariado, 'si', '15%']


def subir(client, empresa, usuario, *filas):
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    return client.post('/pos/product/', {'action': 'upload_excel', 'archive': excel(*filas)})


def catalogo(empresa):
    with company_context(empresa):
        return (sorted(Product.objects.values_list('code', 'pvp', 'stock', 'category__name')), AjusteInventario.objects.count(),
                Category.objects.count())


class TestImportacionDeProductos:

    @pytest.mark.parametrize('rol', [ROLE_READONLY, ROLE_SELLER])
    def test_consulta_y_vendedor_no_modifican_el_catalogo(self, client, empresa, rol):
        producto = helpers.crear_producto(empresa, 'AUD-PROD-01')
        usuario = helpers.crear_usuario(f'importa.{rol.lower()}', empresa, rol)
        antes = catalogo(empresa)
        r = subir(client, empresa, usuario, fila(producto, pvp=19.99, inventariado='no'))
        assert r.status_code == 403 and r.json()['codigo'] == 'sin_permiso' and 'No se cambió nada' in r.json()['error']
        assert catalogo(empresa) == antes

    def test_una_fila_prohibida_rechaza_el_lote_entero(self, client, empresa):
        """Puede modificar productos pero no ajustar stock: el cambio de precio de la fila 2 tampoco se guarda."""
        uno, otro = helpers.crear_producto(empresa, 'AUD-1'), helpers.crear_producto(empresa, 'AUD-2')
        grupo = helpers.crear_grupo('CATALOGO SIN AJUSTE', ['view_product', 'change_product'])
        antes = catalogo(empresa)
        r = subir(client, empresa, helpers.crear_usuario('catalogo.sin.ajuste', empresa, grupo),
                  fila(uno, pvp=12), fila(otro, stock=40))
        assert r.status_code == 403 and r.json()['faltan'] == {'adjust_product_stock': [3]}
        assert catalogo(empresa) == antes

    def test_alta_y_categoria_nueva_exigen_su_permiso(self, client, empresa):
        producto = helpers.crear_producto(empresa, 'AUD-3')
        grupo = helpers.crear_grupo('CATALOGO SIN ALTAS', ['view_product', 'change_product', 'adjust_product_stock'])
        usuario = helpers.crear_usuario('catalogo.sin.altas', empresa, grupo)
        antes = catalogo(empresa)
        nueva = [999999, 'PRODUCTO NUEVO', 'AUD-NUEVO', 'CATEGORÍA FICTICIA', 1, 2, 5, 'si', 'si', '15%']
        r = subir(client, empresa, usuario, nueva, fila(producto, categoria='CATEGORÍA NUEVA'))
        assert r.status_code == 403 and set(r.json()['faltan']) == {'add_product', 'add_category'}
        assert catalogo(empresa) == antes

    def test_el_propietario_crea_modifica_y_ajusta_con_kardex(self, client, empresa, admin):
        producto = helpers.crear_producto(empresa, 'AUD-4')
        nueva = [999999, 'PRODUCTO NUEVO', 'AUD-NUEVO', 'CATEGORÍA NUEVA', 1, 2, 5, 'si', 'si', '15%']
        r = subir(client, empresa, admin, fila(producto, pvp=19.99, stock=40), nueva)
        assert r.status_code == 200 and 'error' not in r.json(), r.json()
        with company_context(empresa):
            assert (Product.objects.get(pk=producto.pk).pvp, Product.objects.get(pk=producto.pk).stock) == (Decimal('19.99'), 40)
            assert Product.objects.get(code='AUD-NUEVO').category.name == 'CATEGORÍA NUEVA'
            assert list(AjusteInventario.objects.order_by('pk').values_list('anterior', 'nuevo', 'origen')) == [
                (100, 40, 'importacion'), (0, 5, 'importacion')]

    def test_un_id_de_otra_empresa_no_la_toca(self, client, empresa, empresa_b, admin):
        ajeno = helpers.crear_producto(empresa_b, 'AJENO-1', pvp='7.00')
        r = subir(client, empresa, admin, fila(ajeno, pvp=1))
        assert r.status_code == 200 and 'error' not in r.json(), r.json()
        with company_context(empresa_b):
            assert Product.objects.get(pk=ajeno.pk).pvp == Decimal('7.00')
        with company_context(empresa):
            assert Product.objects.get(code='AJENO-1').pvp == Decimal('1.00')   # se creó en la empresa activa
