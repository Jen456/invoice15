"""Aislamiento entre empresas: ORM, escrituras, pantallas, cambio de empresa,
usuarios compartidos, roles y panel de plataforma."""
import json

import pytest
from django.db import IntegrityError, connection, transaction

from core.pos.models import Category, Client, Product, Sale
from core.tenancy.context import TenantScopeError, company_context, platform_scope
from core.tenancy.models import ROLE_ADMIN, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog, Membership
from tests import helpers

pytestmark = pytest.mark.django_db


@pytest.fixture
def datos(empresa, empresa_b):
    """Mismos códigos en las dos empresas, para que solo la empresa los distinga."""
    prod_a = helpers.crear_producto(empresa, 'COD-1')
    prod_b = helpers.crear_producto(empresa_b, 'COD-1')
    cli_a = helpers.crear_cliente('cli.a', empresa, '0911111111', '0991111111')
    cli_b = helpers.crear_cliente('cli.b', empresa_b, '0911111111', '0991111111')
    return {'prod_a': prod_a, 'prod_b': prod_b, 'cli_a': cli_a, 'cli_b': cli_b}


class TestORM:

    def test_sin_empresa_activa_falla_cerrado(self, datos):
        with pytest.raises(TenantScopeError):
            list(Product.objects.all())

    def test_cada_contexto_ve_solo_lo_suyo(self, datos, empresa, empresa_b):
        with company_context(empresa):
            assert list(Product.objects.values_list('id', flat=True)) == [datos['prod_a'].id]
        with company_context(empresa_b):
            assert list(Product.objects.values_list('id', flat=True)) == [datos['prod_b'].id]

    def test_queryset_creado_antes_se_resuelve_al_ejecutar(self, datos, empresa, empresa_b):
        queryset = Product.objects.all()  # como el de un ModelChoiceField, creado sin contexto
        with company_context(empresa_b):
            assert [p.id for p in queryset.all()] == [datos['prod_b'].id]

    def test_la_plataforma_ve_todo_de_forma_explicita(self, datos):
        with platform_scope():
            assert Product.all_companies.count() == 2

    def test_guardar_asigna_la_empresa_del_contexto(self, empresa):
        with company_context(empresa):
            categoria = Category.objects.create(name='NUEVA')
        assert categoria.company_id == empresa.id

    def test_referencia_a_dato_de_otra_empresa_rechazada(self, datos, empresa, admin):
        with company_context(empresa):
            venta = Sale(client_id=datos['cli_b'].id, receipt_id=None, employee=admin,
                         voucher_number='000000001', voucher_number_full='001-001-000000001')
            with pytest.raises(TenantScopeError):
                venta.check_tenant_references()

    def test_no_se_modifica_un_dato_de_otra_empresa(self, datos, empresa):
        with company_context(empresa):
            try:
                producto_b = Product.all_companies.get(pk=datos['prod_b'].pk)
            except Product.DoesNotExist:
                # PostgreSQL: la seguridad por filas ni siquiera deja leerlo.
                assert connection.vendor == 'postgresql'
                return
            producto_b.name = 'ALTERADO'
            with pytest.raises(TenantScopeError):
                producto_b.save()
            with pytest.raises(TenantScopeError):
                producto_b.delete()

    def test_unicidad_por_empresa(self, datos, empresa):
        with company_context(empresa):
            with pytest.raises(IntegrityError), transaction.atomic():
                Product.objects.create(name='DUP', code='COD-1', category=datos['prod_a'].category)


class TestPantallas:

    def test_busquedas_solo_de_la_empresa(self, client, admin, datos):
        helpers.iniciar_sesion(client, admin)
        productos = client.post('/pos/product/', {'action': 'search'}).json()
        assert [p['id'] for p in productos] == [datos['prod_a'].id]
        clientes = client.post('/pos/client/', {'action': 'search'}).json()
        assert [c['id'] for c in clientes] == [datos['cli_a'].id]

    @pytest.mark.parametrize('url', ['/pos/product/update/{}/', '/pos/product/delete/{}/'])
    def test_detalle_de_otra_empresa_es_404(self, client, admin, datos, url):
        helpers.iniciar_sesion(client, admin)
        assert client.get(url.format(datos['prod_b'].id)).status_code == 404

    def test_borrar_dato_de_otra_empresa_no_borra(self, client, admin, datos, empresa_b):
        helpers.iniciar_sesion(client, admin)
        respuesta = client.post(f'/pos/product/delete/{datos["prod_b"].id}/')
        # Las vistas de borrado responden JSON con 'error' (contrato del código original).
        assert respuesta.status_code == 404 or 'error' in respuesta.json()
        with company_context(empresa_b):
            assert Product.objects.filter(pk=datos['prod_b'].pk).exists()

    def test_venta_con_cliente_de_otra_empresa_no_se_crea(self, client, admin, datos, empresa):
        with company_context(empresa):
            from core.pos.models import Receipt
            Receipt.objects.create(voucher_type='08', establishment_code='001', issuing_point_code='001', sequence=0)
        helpers.iniciar_sesion(client, admin)
        respuesta = client.post('/pos/sale/admin/add/', {
            'action': 'add', 'date_joined': '2026-10-09', 'receipt': '08', 'client': datos['cli_b'].id,
            'payment_type': 'efectivo', 'cash': '20', 'change': '0', 'additional_info': '[]',
            'products': json.dumps([{'id': datos['prod_a'].id, 'cant': 1, 'price_current': '10', 'dscto': '0'}]),
        })
        assert 'error' in respuesta.json()
        with platform_scope():
            assert Sale.all_companies.count() == 0

    def test_formulario_no_ofrece_datos_de_otra_empresa(self, client, admin, datos):
        helpers.iniciar_sesion(client, admin)
        html = client.get('/pos/product/add/').content.decode()
        assert f'value="{datos["prod_a"].category_id}"' in html
        assert f'value="{datos["prod_b"].category_id}"' not in html


class TestCambioDeEmpresa:

    def test_con_varias_empresas_pide_elegir(self, client, empresa, empresa_b):
        user = helpers.crear_usuario('multi', empresa, ROLE_OWNER)
        Membership.objects.create(user=user, company=empresa_b, group=Membership.objects.get(user=user).group)
        helpers.iniciar_sesion(client, user)
        respuesta = client.get('/dashboard/')
        assert respuesta.status_code == 302 and respuesta['Location'] == '/empresas/'
        assert client.post('/pos/product/', {'action': 'search'}).status_code == 403

    def test_cambiar_de_empresa_cambia_los_datos(self, client, empresa, empresa_b, datos):
        user = helpers.crear_usuario('multi', empresa, ROLE_OWNER)
        Membership.objects.create(user=user, company=empresa_b, group=Membership.objects.get(user=user).group)
        helpers.iniciar_sesion(client, user, empresa=empresa)
        assert [p['id'] for p in client.post('/pos/product/', {'action': 'search'}).json()] == [datos['prod_a'].id]
        clave_antes = client.session.session_key
        client.post('/empresas/cambiar/', {'company': empresa_b.id})
        assert client.session.session_key != clave_antes
        assert [p['id'] for p in client.post('/pos/product/', {'action': 'search'}).json()] == [datos['prod_b'].id]
        assert AuditLog.objects.filter(user=user, action='company_switch', company=empresa_b).exists()

    def test_membresia_inactiva_o_empresa_inactiva_sin_acceso(self, client, empresa):
        user = helpers.crear_usuario('inactivo', empresa, ROLE_OWNER, activa=False)
        helpers.iniciar_sesion(client, user)
        assert client.get('/dashboard/')['Location'] == '/empresas/'
        activo = helpers.crear_usuario('activo', empresa, ROLE_OWNER)
        empresa.is_active = False
        empresa.save()
        client.logout()
        helpers.iniciar_sesion(client, activo)
        assert client.get('/dashboard/')['Location'] == '/empresas/'

    def test_superusuario_entra_y_queda_auditado(self, client, superusuario, empresa):
        helpers.iniciar_sesion(client, superusuario, empresa=empresa)
        assert AuditLog.objects.filter(user=superusuario, action='platform_enter', company=empresa).exists()


class TestUsuariosDeEmpresa:

    def test_listado_solo_miembros_de_la_empresa(self, client, admin, empresa, empresa_b):
        helpers.crear_usuario('de.a', empresa, ROLE_SELLER)
        helpers.crear_usuario('de.b', empresa_b, ROLE_SELLER)
        helpers.iniciar_sesion(client, admin)
        nombres = {u['username'] for u in client.post('/user/', {'action': 'search'}).json()}
        assert nombres == {'propietario.a', 'de.a'}

    def test_no_edita_usuarios_de_otra_empresa(self, client, admin, empresa_b):
        ajeno = helpers.crear_usuario('de.b', empresa_b, ROLE_SELLER)
        helpers.iniciar_sesion(client, admin)
        assert client.get(f'/user/update/{ajeno.id}/').status_code == 404
        assert client.post('/user/', {'action': 'reset_password', 'id': ajeno.id}).status_code == 404

    def test_usuario_compartido_no_cambia_de_clave_desde_una_empresa(self, client, admin, empresa, empresa_b):
        compartido = helpers.crear_usuario('compartido', empresa, ROLE_SELLER)
        Membership.objects.create(user=compartido, company=empresa_b, group=Membership.objects.get(user=compartido).group)
        helpers.iniciar_sesion(client, admin)
        assert client.post('/user/', {'action': 'reset_password', 'id': compartido.id}).status_code == 403
        compartido.refresh_from_db()
        assert compartido.check_password(helpers.CLAVE)

    def test_quitar_usuario_compartido_solo_retira_la_membresia(self, client, admin, empresa, empresa_b):
        compartido = helpers.crear_usuario('compartido', empresa, ROLE_SELLER)
        Membership.objects.create(user=compartido, company=empresa_b, group=Membership.objects.get(user=compartido).group)
        helpers.iniciar_sesion(client, admin)
        client.post(f'/user/delete/{compartido.id}/')
        assert list(Membership.objects.filter(user=compartido).values_list('company_id', flat=True)) == [empresa_b.id]

    def test_administrador_no_asigna_propietario(self, client, empresa):
        administrador = helpers.crear_usuario('administrador', empresa, ROLE_ADMIN)
        helpers.iniciar_sesion(client, administrador)
        html = client.get('/user/add/').content.decode()
        assert '>Propietario<' not in html and '>Vendedor<' in html


class TestRoles:

    def test_vendedor_ve_productos_pero_no_borra(self, client, empresa, datos):
        vendedor = helpers.crear_usuario('vendedor', empresa, ROLE_SELLER)
        helpers.iniciar_sesion(client, vendedor)
        assert client.post('/pos/product/', {'action': 'search'}).status_code == 200
        assert client.post(f'/pos/product/delete/{datos["prod_a"].id}/').status_code == 403

    def test_consulta_no_crea(self, client, empresa):
        consulta = helpers.crear_usuario('consulta', empresa, ROLE_READONLY)
        helpers.iniciar_sesion(client, consulta)
        assert client.post('/pos/category/add/', {'action': 'add', 'name': 'X'}).status_code == 403


class TestPanelPlataforma:

    def test_solo_superusuarios(self, client, admin, superusuario, empresa):
        helpers.iniciar_sesion(client, admin)
        assert client.get('/plataforma/').status_code == 302
        client.logout()
        helpers.iniciar_sesion(client, superusuario)
        assert client.get('/plataforma/').status_code == 200
        assert client.get('/plataforma/pos/company/').status_code == 200
        assert empresa.tradename in client.get('/plataforma/pos/company/').content.decode()

    def test_el_login_del_panel_pasa_por_el_login_con_limite(self, client):
        respuesta = client.get('/plataforma/login/')
        assert respuesta.status_code == 302 and respuesta['Location'].startswith('/login/?next=')

