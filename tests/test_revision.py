"""Revisión del mes (core/tributario/revision.py) y resumen del contador por empresas.

Cada observación con su causa y su enlace; «revisar» nunca como incumplimiento; nada se bloquea ni se certifica. Resumen del
contador por membresías activas, cada empresa leída en su contexto; membresía revocada; cambio de empresa con pestañas
abiertas (el enlace de otra empresa responde 409); `next` del cambio de empresa solo hacia rutas internas."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.utils import timezone

from core.adjuntos import capturas as cp
from core.pos.models import Company, CtasCollect, DebtsPay, Expenses, Provider, Sale
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, Membership
from core.tributario import libros as lb, revision as rv
from tests import ayuda_compras, helpers
from tests.ayudas_ventas import factura_autorizada, peticion

pytestmark = pytest.mark.django_db
MES = (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)
DIA = MES.replace(day=12)


def leer(empresa, funcion):
    with company_context(empresa):
        return funcion()


def codigos(resultado, categoria=None):
    return sorted(o['codigo'] for o in resultado['observaciones'] if categoria is None or o['categoria'] == categoria)


@pytest.fixture
def cliente(empresa):
    return helpers.crear_cliente('cliente.rev', empresa, '0912345678', '0990000001')


@pytest.fixture
def producto(empresa):
    return helpers.crear_producto(empresa, 'REV1', pvp='10.00')


class TestObservaciones:

    def test_devueltos_solo_produccion_con_causa_y_enlace(self, empresa, admin, cliente, producto):
        devuelta = factura_autorizada(empresa, cliente, admin, producto, fecha=DIA, estado='returned')
        factura_autorizada(empresa, cliente, admin, producto, fecha=DIA, estado='returned', ambiente=1)   # pruebas: no
        factura_autorizada(empresa, cliente, admin, producto, fecha=DIA)                                   # autorizada: no
        resultado = leer(empresa, lambda: rv.revisar(MES, empresa))
        [obs] = [o for o in resultado['observaciones'] if o['categoria'] == 'devueltos']
        assert obs['codigo'] == 'returned' and obs['nivel'] == 'revisar' and 'devolvió' in obs['causa']
        assert obs['documento'] == {'tipo': '01', 'id': devuelta.pk, 'numero': devuelta.voucher_number_full, 'url': '/pos/sale/admin/'}

    def test_datos_ats_de_compras_y_proveedores(self, empresa):
        proveedor = ayuda_compras.crear_proveedor(empresa)
        with company_context(empresa):
            Provider.objects.filter(pk=proveedor.pk).update(tipo_identificacion='')
        compra = ayuda_compras.compra_antigua(empresa, proveedor, '40.00', fecha=DIA)
        resultado = leer(empresa, lambda: rv.revisar(MES, empresa))
        assert codigos(resultado, 'datos_ats') == ['compra_incompleta', 'proveedor_incompleto']
        obs = next(o for o in resultado['observaciones'] if o['codigo'] == 'compra_incompleta')
        assert obs['causa'].startswith('Faltan para el ATS: ') and obs['documento']['url'] == f'/pos/purchase/complete/{compra.pk}/'

    def test_respaldos_pendientes(self, empresa, admin):
        tipo = ayuda_compras.crear_tipo_gasto(empresa, 'TAXI')
        with company_context(empresa):
            gasto = Expenses.objects.create(type_expense=tipo, description='Taxi', valor=Decimal('5.00'), medio_pago='transferencia',
                                            date_joined=DIA)
            captura, _ = cp.registrar(peticion(admin, empresa), clave='clave-revision-01', nota='Peaje')
            type(captura).objects.filter(pk=captura.pk).update(creado_en=timezone.make_aware(datetime(DIA.year, DIA.month, DIA.day, 10)))
        resultado = leer(empresa, lambda: rv.revisar(MES, empresa))
        assert codigos(resultado, 'respaldos') == ['recibo_por_completar', 'sin_respaldo']
        sin = next(o for o in resultado['observaciones'] if o['codigo'] == 'sin_respaldo')
        assert sin['documento']['id'] == gasto.pk and 'transferencia' in sin['causa']

    def test_salto_de_numeracion_no_es_una_omision(self, empresa, admin, cliente, producto):
        ventas = [factura_autorizada(empresa, cliente, admin, producto, fecha=DIA) for _ in range(3)]
        with company_context(empresa):
            Sale.objects.filter(pk=ventas[2].pk).update(voucher_number=f'{int(ventas[2].voucher_number) + 3:09d}')
        resultado = leer(empresa, lambda: rv.revisar(MES, empresa))
        [salto] = [o for o in resultado['observaciones'] if o['categoria'] == 'numeracion']
        desde = int(ventas[1].voucher_number) + 1
        assert f'{desde:09d} a {desde + 2:09d}' in salto['titulo'] and 'no prueba una omisión' in salto['causa']
        assert salto['nivel'] == 'revisar'

    def test_cuentas_vencidas_a_la_fecha_de_corte(self, empresa, admin, cliente, producto):
        venta = factura_autorizada(empresa, cliente, admin, producto, fecha=DIA - timedelta(days=40), credito=True,
                                   vence=DIA - timedelta(days=5))
        proveedor = ayuda_compras.crear_proveedor(empresa)
        compra = ayuda_compras.compra_antigua(empresa, proveedor, '30.00', credito=True, fecha=DIA - timedelta(days=60))
        with company_context(empresa):
            DebtsPay.objects.filter(purchase=compra).update(end_date=DIA - timedelta(days=2))
        resultado = leer(empresa, lambda: rv.revisar(MES, empresa))
        assert codigos(resultado, 'vencidas') == ['cxc_vencida', 'cxp_vencida']
        cxc = next(o for o in resultado['observaciones'] if o['codigo'] == 'cxc_vencida')
        assert cxc['importe'] == f'{venta.total:.2f}' and cxc['nivel'] == 'informativo'
        assert resultado['corte'] == (lb.siguiente_mes(MES) - timedelta(days=1)).isoformat()   # fin del mes pasado

    def test_compra_sin_retencion_solo_si_es_agente_y_como_revision(self, empresa):
        proveedor = ayuda_compras.crear_proveedor(empresa)
        with company_context(empresa):
            compra = ayuda_compras.compra_antigua(empresa, proveedor, '100.00', fecha=DIA)
            type(compra).objects.filter(pk=compra.pk).update(tipo_comprobante='01')
        Company.objects.filter(pk=empresa.pk).update(retention_agent='NO')
        empresa.refresh_from_db()
        assert leer(empresa, lambda: codigos(rv.revisar(MES, empresa), 'retenciones')) == []
        Company.objects.filter(pk=empresa.pk).update(retention_agent='SI')
        empresa.refresh_from_db()
        resultado = leer(empresa, lambda: rv.revisar(MES, empresa))
        [obs] = [o for o in resultado['observaciones'] if o['categoria'] == 'retenciones']
        assert obs['nivel'] == 'revisar' and 'No es un incumplimiento automático' in obs['causa'] and resultado['agente_retencion']

    def test_resumen_y_aislamiento(self, empresa, empresa_b, admin, cliente, producto):
        factura_autorizada(empresa, cliente, admin, producto, fecha=DIA, estado='returned')
        resultado_b = leer(empresa_b, lambda: rv.revisar(MES, empresa_b))
        assert resultado_b['pendientes'] == 0 and resultado_b['observaciones'] == []
        resultado = leer(empresa, lambda: rv.revisar(MES, empresa))
        assert resultado['por_categoria']['devueltos']['revisar'] == 1 and resultado['pendientes'] >= 1


class TestPantallasYPermisos:

    @pytest.mark.parametrize('rol, estado', [(ROLE_OWNER, 200), (ROLE_ADMIN, 200), (ROLE_ACCOUNTANT, 200), (ROLE_READONLY, 200),
                                             (ROLE_SELLER, 302), (ROLE_CLIENT, 302)])
    def test_por_rol(self, client, empresa, rol, estado):
        usuario = helpers.crear_usuario(f'rev.{rol.lower()}', empresa, rol)
        helpers.iniciar_sesion(client, usuario, empresa=empresa)
        for url in ('/tributario/revision/', '/tributario/empresas/', '/tributario/api/revision/', '/tributario/api/empresas/'):
            assert client.get(url).status_code == estado, (rol, url)

    def test_pagina_y_api(self, client, empresa, admin, cliente, producto):
        factura_autorizada(empresa, cliente, admin, producto, fecha=DIA, estado='returned')
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        pagina = client.get(f'/tributario/revision/?mes={MES:%Y-%m}')
        assert pagina.status_code == 200 and 'El SRI devolvió el comprobante' in pagina.content.decode()
        datos = client.get(f'/tributario/api/revision/?mes={MES:%Y-%m}').json()
        assert datos['mes'] == f'{MES:%Y-%m}' and datos['por_categoria']['devueltos']['revisar'] == 1


class TestContador:

    @pytest.fixture
    def contador(self, empresa, empresa_b):
        usuario = helpers.crear_usuario('contador.varias', empresa, ROLE_ACCOUNTANT)
        Membership.objects.create(user=usuario, company=empresa_b, group=Group.objects.get(name=ROLE_ACCOUNTANT))
        return usuario

    def test_resumen_por_empresa_y_membresia_revocada(self, client, empresa, empresa_b, admin, contador):
        cliente_b = helpers.crear_cliente('cliente.rev.b', empresa_b, '0912345679', '0990000002')
        factura_autorizada(empresa_b, cliente_b, admin, helpers.crear_producto(empresa_b, 'RB1'), fecha=DIA, estado='returned')
        helpers.iniciar_sesion(client, contador, empresa=empresa)
        filas = {f['empresa_id']: f for f in client.get(f'/tributario/api/empresas/?mes={MES:%Y-%m}').json()['empresas']}
        assert set(filas) == {empresa.pk, empresa_b.pk}
        assert filas[empresa_b.pk]['pendientes'] == 1 and filas[empresa.pk]['pendientes'] == 0 and filas[empresa_b.pk]['rol'] == ROLE_ACCOUNTANT
        Membership.objects.filter(user=contador, company=empresa_b).update(is_active=False)        # revocada
        filas = client.get(f'/tributario/api/empresas/?mes={MES:%Y-%m}').json()['empresas']
        assert [f['empresa_id'] for f in filas] == [empresa.pk]
        assert client.post('/empresas/cambiar/', {'company': empresa_b.pk}).status_code == 404     # ya no puede entrar

    def test_abrir_la_revision_de_otra_empresa_y_pestanas_abiertas(self, client, empresa, empresa_b, contador):
        helpers.iniciar_sesion(client, contador, empresa=empresa)
        destino = f'/tributario/revision/?mes={MES:%Y-%m}'
        respuesta = client.post('/empresas/cambiar/', {'company': empresa_b.pk, 'next': destino})
        assert respuesta.status_code == 302 and respuesta['Location'] == destino and client.session['company_id'] == empresa_b.pk
        # la pestaña que seguía con la empresa A: su enlace dice empresa=A y la activa es B → 409, nada de B con apariencia de A
        assert client.get(f'/tributario/api/revision/?empresa={empresa.pk}').status_code == 409
        assert client.get(f'/tributario/api/libros/ventas/?empresa={empresa.pk}').json()['codigo'] == 'empresa_cambiada'
        assert client.get(f'/tributario/libros/exportar/?libro=ventas&formato=csv&empresa={empresa.pk}').status_code == 409
        assert client.get(f'/tributario/api/revision/?empresa={empresa_b.pk}').status_code == 200

    @pytest.mark.parametrize('destino', ['https://ejemplo.com/', '//ejemplo.com/x', 'javascript:alert(1)', ''])
    def test_next_solo_rutas_internas(self, client, empresa, empresa_b, contador, settings, destino):
        helpers.iniciar_sesion(client, contador, empresa=empresa)
        respuesta = client.post('/empresas/cambiar/', {'company': empresa_b.pk, 'next': destino})
        assert respuesta['Location'] == settings.LOGIN_REDIRECT_URL

    def test_membresia_activa_revocada_en_plena_sesion(self, client, empresa, empresa_b, contador):
        """El middleware revalida la membresía en cada petición: revocada la de la empresa activa, la sesión pasa a la única
        membresía activa que queda (B), nunca sigue en A; el enlace armado para A responde 409; sin ninguna, al selector."""
        helpers.iniciar_sesion(client, contador, empresa=empresa)
        assert client.get('/tributario/revision/').status_code == 200
        Membership.objects.filter(user=contador, company=empresa).update(is_active=False)
        assert client.get('/tributario/revision/').status_code == 200 and client.session['company_id'] == empresa_b.pk
        assert client.get(f'/tributario/api/revision/?empresa={empresa.pk}').status_code == 409
        Membership.objects.filter(user=contador, company=empresa_b).update(is_active=False)
        respuesta = client.get('/tributario/revision/')
        assert respuesta.status_code == 302 and respuesta['Location'] == '/empresas/'
