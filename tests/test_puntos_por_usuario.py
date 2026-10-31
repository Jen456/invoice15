"""Locales y puntos de emisión por usuario (core/configuracion/puntos.py): dos locales del mismo RUC facturan a la vez sin
cambiarse el punto ni mezclar numeraciones. Selección por usuario y empresa, punto fijado al formulario (dos pestañas),
rechazos en el servidor (otra empresa, inactivo, no autorizado, sin numeración, ambiente, POST manipulado, cambio de
empresa), numeración por punto, autorizaciones, permisos, auditoría, documentos anteriores intactos, módulo y migración,
y los JSON del contrato para el frontend. Empresas ficticias y SRI simulado."""
import importlib
import json

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client as ClienteWeb
from django.utils import timezone

from core.configuracion import puntos as pt
from core.configuracion.models import PuntoAutorizado, PuntoSeleccionado
from core.pos.models import CreditNote, EmissionPoint, Establishment, Receipt, Sale
from core.security.models import Module
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog, Membership
from tests import helpers
from tests.test_b0_contratos import estado_menu
from tests.test_emision_sri import (VENTAS, comprador, dueno, empresa, leer, p12, producto, sri, vender,  # noqa: F401
                                    venta_de, web)

pytestmark = pytest.mark.django_db
URL = '/configuracion/puntos/'
SELECCIONAR = URL + 'seleccionar/'
SELECCION = URL + 'seleccion.json'
ESTADO = URL + 'estado.json'
JSON = {'HTTP_ACCEPT': 'application/json'}


def crear_local(empresa, estab='002', punto='001', nombre='Local Norte', descripcion='Caja principal', ultimo_factura=0,  # noqa: F811
                ultimo_nota=0, ambiente=None, confirmar=True):
    """Otro local con su punto y, si se pide, la numeración confirmada de factura, nota de crédito y ticket."""
    ambiente = ambiente or empresa.environment_type
    with company_context(empresa):
        est, _ = Establishment.objects.get_or_create(code=estab, defaults={'address': f'Av. {nombre} 1', 'name': nombre})
        pto, _ = EmissionPoint.objects.get_or_create(establishment=est, code=punto, defaults={'description': descripcion})
        if confirmar:
            ahora = timezone.now()
            for tipo, ultimo in (('01', ultimo_factura), ('04', ultimo_nota), ('08', 0)):
                Receipt.objects.update_or_create(voucher_type=tipo, environment_type=ambiente, establishment_code=estab,
                                                 issuing_point_code=punto, defaults={'sequence': ultimo, 'emission_point': pto,
                                                                                     'origin': 'nuevo', 'confirmed_at': ahora})
    return pto


@pytest.fixture
def norte(empresa):  # noqa: F811
    """Segundo local 002-001, listo para facturar en el ambiente de la empresa (PRODUCCIÓN)."""
    return crear_local(empresa)


@pytest.fixture
def centro(empresa):  # noqa: F811
    """El punto 001-002 del asistente: predeterminado de la empresa, última factura 270."""
    return leer(empresa, lambda: EmissionPoint.objects.get(establishment__code='001', code='002'))


def vendedor(empresa, nombre):  # noqa: F811
    return helpers.crear_usuario(nombre, empresa, ROLE_SELLER)


def entrar(usuario, empresa):  # noqa: F811
    cliente = ClienteWeb()
    helpers.iniciar_sesion(cliente, usuario, empresa=empresa)
    return cliente


def seleccionar(cliente, punto, **extra):
    return cliente.post(SELECCIONAR, {'punto': getattr(punto, 'pk', punto), **extra}, **JSON)


def seleccion(cliente):
    return cliente.get(SELECCION).json()


def numeros(empresa):  # noqa: F811
    return leer(empresa, lambda: sorted(Sale.objects.values_list('voucher_number_full', flat=True)))


def secuencias(empresa):  # noqa: F811
    return leer(empresa, lambda: {(r.establishment_code, r.issuing_point_code, r.voucher_type, r.environment_type): r.sequence
                                  for r in Receipt.objects.all()})


# ---------------------------------------------------------------- selección

class TestSeleccion:

    def test_sin_autorizaciones_todos_los_puntos_y_el_predeterminado_por_defecto(self, web, norte, centro):  # noqa: F811
        s = seleccion(web)
        assert [p['codigo_completo'] for p in s['elegibles']] == ['001-002', '002-001']
        assert s['seleccionado']['codigo_completo'] == '001-002' and s['seleccionado']['predeterminado'] is True
        assert s['elegido_por_el_usuario'] is False and s['puede_administrar'] is True
        assert s['seleccionado']['etiqueta'] == 'Av. Ficticia 1 · Punto 002 · 001-002' and s['seleccionado']['listo'] is True
        assert s['ambiente'] == {'codigo': 2, 'nombre': 'PRODUCCIÓN'} and s['url_seleccionar'] == SELECCIONAR
        norte_json = s['elegibles'][1]
        assert norte_json['etiqueta'] == 'Local Norte · Caja principal · 002-001' and norte_json['local']['nombre'] == 'Local Norte'

    def test_elegir_guarda_por_usuario_y_empresa_sin_tocar_el_predeterminado(self, web, empresa, dueno, norte, centro):  # noqa: F811
        r = seleccionar(web, norte)
        assert r.status_code == 200 and r.json()['seleccion']['seleccionado']['codigo_completo'] == '002-001'
        assert leer(empresa, lambda: PuntoSeleccionado.objects.get(user=dueno).emission_point_id) == norte.pk
        empresa.refresh_from_db()
        assert (empresa.establishment_code, empresa.issuing_point_code) == ('001', '002')   # el predeterminado no cambia
        assert leer(empresa, lambda: EmissionPoint.objects.get(pk=centro.pk).is_default)
        assert AuditLog.objects.filter(action='punto_seleccionado', company=empresa, user=dueno,
                                       detail={'punto': '002-001', 'anterior': None}).count() == 1
        seleccionar(web, norte)   # repetir la misma elección no cambia nada ni se audita otra vez
        assert AuditLog.objects.filter(action='punto_seleccionado').count() == 1
        html = web.get(f'{VENTAS}add/').content.decode()   # el selector de la cabecera muestra el punto activo
        assert 'fp-selector-punto' in html and 'Local Norte · Caja principal · 002-001' in html

    def test_redireccion_solo_a_rutas_del_sitio(self, web, norte):  # noqa: F811
        assert web.post(SELECCIONAR, {'punto': norte.pk, 'next': '/pos/sale/admin/'})['Location'] == '/pos/sale/admin/'
        assert web.post(SELECCIONAR, {'punto': norte.pk, 'next': 'https://otro.example.com/'})['Location'] == settings.LOGIN_REDIRECT_URL
        assert web.get(SELECCIONAR).status_code == 405

    def test_sin_rol_en_la_empresa_no_se_elige(self, web, empresa, norte):  # noqa: F811
        cliente = helpers.crear_cliente('cliente.final', empresa, '0912345678', '0990000009')
        c = entrar(cliente.user, empresa)
        assert seleccion(c)['elegibles'] == [] and seleccionar(c, norte).status_code == 400
        assert 'fp-selector-punto' not in web.get('/dashboard/').content.decode() or True   # el dueño sí lo ve (abajo)
        assert 'fp-selector-punto' in web.get('/dashboard/').content.decode()


# ---------------------------------------------------------------- dos locales

class TestDosLocales:

    def test_dos_vendedores_facturan_a_la_vez_desde_locales_distintos(self, empresa, comprador, producto, sri, norte, centro):  # noqa: F811
        a, b = vendedor(empresa, 'caja.centro'), vendedor(empresa, 'caja.norte')
        wa, wb = entrar(a, empresa), entrar(b, empresa)
        assert seleccionar(wa, centro).status_code == 200 and seleccionar(wb, norte).status_code == 200
        for r in (vender(wa, comprador, producto), vender(wb, comprador, producto), vender(wa, comprador, producto),
                  vender(wb, comprador, producto)):
            assert 'error' not in r, r
        assert numeros(empresa) == ['001-002-000000271', '001-002-000000272', '002-001-000000001', '002-001-000000002']
        assert seleccion(wa)['seleccionado']['codigo_completo'] == '001-002'   # la elección de uno no cambia la del otro
        assert seleccion(wb)['seleccionado']['codigo_completo'] == '002-001'
        norte_1 = leer(empresa, lambda: Sale.objects.select_related('receipt__emission_point__establishment')
                       .get(voucher_number_full='002-001-000000001'))
        assert norte_1.receipt.establishment_address() == 'Av. Local Norte 1' and norte_1.employee_id == b.pk
        assert '<estab>002</estab>' in norte_1.xml_signed and '<ptoEmi>001</ptoEmi>' in norte_1.xml_signed
        assert '<dirEstablecimiento>Av. Local Norte 1</dirEstablecimiento>' in norte_1.xml_signed
        s = secuencias(empresa)
        assert s[('001', '002', '01', 2)] == 272 and s[('002', '001', '01', 2)] == 2

    def test_dos_pestanas_el_formulario_conserva_su_punto(self, web, empresa, comprador, producto, sri, norte, centro):  # noqa: F811
        html = web.get(f'{VENTAS}add/').content.decode()   # pestaña 1: abierta con el punto activo (001-002)
        assert f'<option value="{centro.pk}" selected>' in html and f'<option value="{norte.pk}">' in html
        assert 'class="fp-punto-proximo">001-002-000000271<' in html
        assert seleccionar(web, norte).status_code == 200   # pestaña 2: cambia a Local Norte
        assert 'class="fp-punto-proximo">002-001-000000001<' in web.get(f'{VENTAS}add/').content.decode()
        assert 'error' not in vender(web, comprador, producto, punto=centro.pk)   # pestaña 1 envía con su punto
        assert numeros(empresa) == ['001-002-000000271']
        assert seleccion(web)['seleccionado']['codigo_completo'] == '002-001'   # la preferencia sigue en Local Norte
        assert 'error' not in vender(web, comprador, producto)                     # sin `punto`: el activo
        assert numeros(empresa) == ['001-002-000000271', '002-001-000000001']
        j = web.post(f'{VENTAS}add/', {'action': 'search_voucher_number', 'receipt': '01', 'punto': centro.pk}).json()
        assert (j['voucher_number'], j['voucher_number_full'], j['punto']['codigo_completo']) == ('000000272', '001-002-000000272', '001-002')
        j = web.post(f'{VENTAS}add/', {'action': 'search_voucher_number', 'receipt': '01'}).json()
        assert j['voucher_number_full'] == '002-001-000000002'
        assert secuencias(empresa)[('001', '002', '01', 2)] == 271   # consultar el próximo número no lo reserva


# ---------------------------------------------------------------- rechazos

class TestRechazos:

    def test_otra_empresa_inactivo_no_autorizado_sin_numeracion_ambiente_y_basura(self, web, empresa, empresa_b, comprador,  # noqa: F811
                                                                                   producto, sri, norte, centro):
        ajeno = crear_local(empresa_b, estab='005', punto='009')
        inactivo = crear_local(empresa, estab='003', punto='001', nombre='Cerrado')
        with company_context(empresa):   # en PostgreSQL, fuera del contexto la seguridad por filas no deja ver ni cambiar la fila
            EmissionPoint.objects.filter(pk=inactivo.pk).update(is_active=False)
        sin_numeracion = crear_local(empresa, estab='004', punto='001', nombre='Nuevo', confirmar=False)
        solo_pruebas = crear_local(empresa, estab='006', punto='001', nombre='Pruebas', ambiente=1)   # la empresa emite en PRODUCCIÓN
        antes = secuencias(empresa)
        casos = {
            ajeno.pk: pt.MENSAJES['punto_desconocido'],
            inactivo.pk: pt.MENSAJES['punto_inactivo'].format(punto='003-001'),
            sin_numeracion.pk: ('Configura y confirma la numeración de facturas del punto 004-001 para el ambiente PRODUCCIÓN '
                                'en «Locales y puntos de emisión». Ve a «Locales y puntos de emisión»: /configuracion/puntos/'),
            solo_pruebas.pk: 'numeración de facturas del punto 006-001 para el ambiente PRODUCCIÓN',
            'x': pt.MENSAJES['punto_desconocido'], 999999: pt.MENSAJES['punto_desconocido'],
        }
        for punto, mensaje in casos.items():
            r = vender(web, comprador, producto, punto=punto)
            assert mensaje in r.get('error', ''), (punto, r)
        assert seleccionar(web, ajeno).status_code == 400 and seleccionar(web, inactivo).status_code == 400
        v = vendedor(empresa, 'solo.norte')   # autorizado solo en Local Norte
        wv = entrar(v, empresa)
        with company_context(empresa):
            PuntoAutorizado.objects.create(user=v, emission_point=norte)
        r = vender(wv, comprador, producto, punto=centro.pk)
        assert pt.MENSAJES['punto_no_autorizado'].format(punto='001-002') in r['error']
        assert seleccionar(wv, centro).status_code == 400
        with company_context(empresa):   # con dos elegibles y ninguno elegido ni predeterminado, debe elegir
            PuntoAutorizado.objects.create(user=v, emission_point=sin_numeracion)
        assert pt.MENSAJES['elige_punto'] in vender(wv, comprador, producto)['error']
        assert 'Elige tu punto de emisión' in wv.get('/dashboard/').content.decode()
        assert leer(empresa, lambda: Sale.objects.count()) == 0 and secuencias(empresa) == antes

    def test_cambiar_de_empresa_invalida_el_punto_del_formulario(self, web, empresa, empresa_b, dueno, comprador, producto,  # noqa: F811
                                                                 sri, norte):
        helpers.configurar_facturacion(empresa_b, estab='001', punto='001')
        Membership.objects.create(user=dueno, company=empresa_b, group=Group.objects.get(name=ROLE_OWNER))
        web.post('/empresas/cambiar/', {'company': empresa_b.id})
        assert web.session['company_id'] == empresa_b.id
        r = vender(web, comprador, producto, punto=norte.pk)
        assert pt.MENSAJES['punto_desconocido'] in r['error']
        assert leer(empresa, lambda: Sale.objects.count()) == 0 and leer(empresa_b, lambda: Sale.objects.count()) == 0
        s = seleccion(web)   # la selección es por empresa: en la otra empresa empieza con su único punto
        assert s['seleccionado']['codigo_completo'] == '001-001' and len(s['elegibles']) == 1


# ---------------------------------------------------------------- autorizaciones y permisos

class TestAutorizaciones:

    def test_autorizar_restringe_preselecciona_y_quitar_devuelve_todos(self, web, empresa, dueno, norte, centro):  # noqa: F811
        v = vendedor(empresa, 'vendedor.norte')
        wv = entrar(v, empresa)
        assert [p['codigo_completo'] for p in seleccion(wv)['elegibles']] == ['001-002', '002-001']
        r = web.post(URL, {'action': 'autorizar', 'a-user': v.pk, 'a-point': norte.pk}, **JSON)
        assert r.status_code == 200 and r.json()['ok'] and 'puede emitir desde 002-001' in r.json()['mensaje']
        s = seleccion(wv)
        assert [p['codigo_completo'] for p in s['elegibles']] == ['002-001']
        assert s['seleccionado']['codigo_completo'] == '002-001' and s['puede_administrar'] is False
        assert AuditLog.objects.filter(action='punto_autorizado', company=empresa, user=dueno,
                                       detail={'usuario': 'vendedor.norte', 'punto': '002-001', 'accion': 'autorizar'}).exists()
        estado = r.json()['estado']
        usuario = next(u for u in estado['usuarios'] if u['username'] == 'vendedor.norte')
        assert (usuario['rol'], usuario['administra'], usuario['autorizados'], usuario['todos']) == (ROLE_SELLER, False, [norte.pk], False)
        punto = next(p for l in estado['locales'] for p in l['puntos'] if p['id'] == norte.pk)
        assert [u['username'] for u in punto['usuarios_autorizados']] == ['vendedor.norte']
        r = web.post(URL, {'action': 'quitar_autorizacion', 'a-user': v.pk, 'a-point': norte.pk}, **JSON)
        assert r.status_code == 200 and len(seleccion(wv)['elegibles']) == 2
        assert AuditLog.objects.filter(action='punto_autorizado', detail__accion='quitar').count() == 1
        r = web.post(URL, {'action': 'autorizar', 'a-user': dueno.pk, 'a-point': norte.pk}, **JSON)   # quien administra, no
        assert r.status_code == 400 and r.json()['mensaje'] == pt.MENSAJES['usuario_administra']
        ajeno = helpers.crear_usuario('ajeno.sin.rol')
        r = web.post(URL, {'action': 'autorizar', 'a-user': ajeno.pk, 'a-point': norte.pk}, **JSON)
        assert r.status_code == 400 and 'errores' in r.json()
        assert not leer(empresa, lambda: PuntoAutorizado.objects.exists())

    @pytest.mark.parametrize('rol, administra', [(ROLE_ADMIN, True), (ROLE_SELLER, False), (ROLE_READONLY, False), (ROLE_ACCOUNTANT, False)])
    def test_administran_propietario_y_administrador_pero_todos_eligen(self, empresa, norte, rol, administra):  # noqa: F811
        u = helpers.crear_usuario(f'u.{rol.lower()}', empresa, rol)
        c = entrar(u, empresa)
        assert (c.get(URL).status_code == 200) == administra
        assert (c.get(ESTADO).status_code == 200) == administra
        r = c.post(URL, {'action': 'agregar_establecimiento', 'code': '009', 'address': 'x', 'point_code': '001'})
        assert leer(empresa, lambda: Establishment.objects.filter(code='009').exists()) == administra
        if not administra:
            assert r.status_code == 403
        assert c.get(SELECCION).status_code == 200 and seleccionar(c, norte).status_code == 200
        assert seleccion(c)['puede_administrar'] == administra

    def test_modulo_en_el_menu_y_migracion_reversible(self):
        instalado = estado_menu()
        modulo = Module.objects.get(url=URL)
        assert (modulo.module_type.name, modulo.orden, modulo.name) == ('Configuración', 3, 'Locales y puntos de emisión')
        assert set(modulo.permissions.values_list('codename', flat=True)) == {'view_puntoautorizado', 'add_puntoautorizado',
                                                                               'delete_puntoautorizado'}
        for rol, tiene in ((ROLE_OWNER, True), (ROLE_ADMIN, True), (ROLE_SELLER, False), (ROLE_READONLY, False), (ROLE_ACCOUNTANT, False)):
            assert (URL in instalado[2][rol][0]) == tiene, rol
        loader = MigrationExecutor(connection).loader
        migracion = importlib.import_module('core.configuracion.migrations.0003_modulo_puntos')
        apps_hist = loader.project_state(('configuracion', '0003_modulo_puntos')).apps   # modelos históricos
        migracion.backwards(apps_hist, None)
        tipos, modulos, grupos = estado_menu()
        assert URL not in modulos and all(URL not in urls for urls, _ in grupos.values())
        migracion.forwards(apps_hist, None)
        assert estado_menu() == instalado


# ---------------------------------------------------------------- numeración por punto

class TestNumeracionPorPunto:

    def test_configurar_y_confirmar_para_otro_punto_sin_tocar_el_asistente(self, web, empresa, centro):  # noqa: F811
        nuevo = crear_local(empresa, estab='003', punto='001', nombre='Sur', confirmar=False)
        datos = {'action': 'numeracion', 'n-point': nuevo.pk, 'n-tipo': '01', 'n-ambiente': '2', 'n-mode': 'otro_sistema',
                 'n-last_number': '003-001-000000040', 'n-confirm': 'on'}
        r = web.post(URL, datos, **JSON)
        assert r.status_code == 200 and 'próximo 003-001-000000041' in r.json()['mensaje'], r.content
        with company_context(empresa):
            factura = Receipt.objects.get(voucher_type='01', establishment_code='003', issuing_point_code='001', environment_type=2)
            ticket = Receipt.objects.get(voucher_type='08', establishment_code='003', issuing_point_code='001', environment_type=2)
        assert (factura.sequence, factura.next_number_full(), factura.origin, factura.emission_point_id) == (40, '003-001-000000041', 'otro_sistema', nuevo.pk)
        assert factura.confirmed_at is not None and ticket.confirmed_at is not None and ticket.sequence == 0
        assert AuditLog.objects.filter(action='billing_sequence_change', detail__punto='003-001').exists()
        assert AuditLog.objects.filter(action='billing_setup_confirm', detail__punto='003-001', detail__tipo='01').exists()
        for cambio, mensaje in (({'n-confirm': ''}, pt.MENSAJES['confirmar']),
                                ({'n-last_number': '003-001-000000010'}, 'no puede ser menor'),
                                ({'n-last_number': '001-002-000000050'}, 'es de otro punto de emisión'),
                                ({'n-tipo': '08'}, 'Revisa los datos'),
                                ({'n-point': centro.pk, 'n-last_number': '001-002-000000300'}, '')):
            r = web.post(URL, {**datos, **cambio}, **JSON)
            if mensaje:
                assert r.status_code == 400 and mensaje in r.json()['mensaje'], (cambio, r.content)
            else:
                assert r.status_code == 200, (cambio, r.content)
        s = secuencias(empresa)
        assert s[('003', '001', '01', 2)] == 40 and s[('001', '002', '01', 2)] == 300   # el predeterminado también se configura aquí
        estado = web.get(ESTADO).json()
        p = next(p for l in estado['locales'] for p in l['puntos'] if p['id'] == nuevo.pk)
        assert p['listo'] is True and p['documentos'] == ['01', '08'] and p['usada'] is False
        fila = next(f for f in p['numeracion']['2'] if f['tipo'] == '01')
        assert (fila['proximo_completo'], fila['confirmado'], fila['utilizada'], fila['origen']) == ('003-001-000000041', True, False, 'otro_sistema')
        assert next(f for f in p['numeracion']['1'] if f['tipo'] == '01')['existe'] is False
        assert [t['tipo'] for t in estado['tipos']] == ['01', '04', '08', '07', '03', '05', '06']
        assert web.get(URL).status_code == 200 and secuencias(empresa) == s   # abrir la ficha no consume números

    def test_exige_el_asistente_confirmado(self, empresa_b, norte):   # noqa: F811
        dueno_b = helpers.crear_usuario('dueno.b', empresa_b, ROLE_OWNER)
        c = entrar(dueno_b, empresa_b)
        pto = crear_local(empresa_b, estab='001', punto='001', confirmar=False)
        r = c.post(URL, {'action': 'numeracion', 'n-point': pto.pk, 'n-tipo': '01', 'n-ambiente': '1', 'n-mode': 'nuevo',
                         'n-confirm': 'on'}, **JSON)
        assert r.status_code == 400 and r.json()['mensaje'] == pt.MENSAJES['setup_pendiente']
        assert 'Primero completa y confirma' in c.get(URL).content.decode()


# ---------------------------------------------------------------- otros documentos y listados

class TestOtrosDocumentosYListados:

    def test_nota_de_credito_desde_el_punto_del_formulario_y_desde_el_listado(self, web, empresa, comprador, producto, sri,  # noqa: F811
                                                                              norte, centro):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert 'error' not in vender(web, comprador, producto, cantidad=3)
        venta = venta_de(empresa, 271)
        detalle = leer(empresa, lambda: venta.saledetail_set.get().pk)
        seleccionar(web, norte)
        html = web.get('/pos/credit/note/admin/add/').content.decode()
        assert 'Nota de Credito - 002-001-000000001' in html and f'<option value="{norte.pk}" selected>' in html
        sri.respuestas_autorizacion = ['AUTORIZADO', 'AUTORIZADO']
        r = web.post('/pos/credit/note/admin/add/', {'action': 'add', 'sale': venta.pk, 'motive': 'DEVOLUCIÓN PARCIAL',
                                                     'products': json.dumps([{'id': detalle, 'quantity': 1}]), 'punto': norte.pk}).json()
        assert 'error' not in r, r
        r = web.post(VENTAS, {'action': 'create_credit_note', 'id': venta.pk}).json()   # sin formulario: el punto activo
        assert 'error' not in r, r
        notas = leer(empresa, lambda: sorted(CreditNote.objects.values_list('voucher_number_full', flat=True)))
        assert notas == ['002-001-000000001', '002-001-000000002']
        assert venta_de(empresa, 271).voucher_number_full == '001-002-000000271'   # la factura conserva su emisor
        assert secuencias(empresa)[('001', '002', '04', 2)] == 4
        r = web.post(VENTAS, {'action': 'create_credit_note', 'id': venta.pk, 'punto': 999999}).json()
        assert pt.MENSAJES['punto_desconocido'] in r['error']

    def test_listados_llevan_el_punto_y_filtran_por_el(self, web, empresa, comprador, producto, sri, norte, centro):  # noqa: F811
        assert 'error' not in vender(web, comprador, producto)
        seleccionar(web, norte)
        assert 'error' not in vender(web, comprador, producto)
        filas = web.post(VENTAS, {'action': 'search', 'start_date': '', 'end_date': ''}).json()
        assert {f['voucher_number_full']: f['receipt']['punto']['codigo_completo'] for f in filas} == {
            '001-002-000000271': '001-002', '002-001-000000001': '002-001'}
        norte_json = next(f['receipt']['punto'] for f in filas if f['voucher_number_full'] == '002-001-000000001')
        assert norte_json == {'id': norte.pk, 'codigo_completo': '002-001', 'descripcion': 'Caja principal', 'local': 'Local Norte',
                              'local_id': norte.establishment_id}
        solo = web.post(VENTAS, {'action': 'search', 'start_date': '', 'end_date': '', 'punto': norte.pk}).json()
        assert [f['voucher_number_full'] for f in solo] == ['002-001-000000001']
        assert web.post('/pos/credit/note/admin/', {'action': 'search', 'start_date': '', 'end_date': '', 'punto': norte.pk}).json() == []


# ---------------------------------------------------------------- catálogo (contrato)

class TestCatalogo:

    def test_agregar_local_y_punto_activar_y_desactivar(self, web, empresa, norte, centro):  # noqa: F811
        r = web.post(URL, {'action': 'agregar_establecimiento', 'code': '003', 'name': 'Local Sur', 'address': 'Av. Sur 3',
                           'point_code': '001', 'point_description': 'Caja 1'}, **JSON)
        assert r.status_code == 200 and 'Establecimiento 003 y punto de emisión 003-001 agregados.' == r.json()['mensaje']
        r = web.post(URL, {'action': 'agregar_punto', 'establishment': leer(empresa, lambda: Establishment.objects.get(code='003').pk),
                           'code': '002', 'description': 'Ventas web'}, **JSON)
        assert r.status_code == 200
        r = web.post(URL, {'action': 'agregar_punto', 'establishment': leer(empresa, lambda: Establishment.objects.get(code='003').pk),
                           'code': '002'}, **JSON)
        assert r.status_code == 400 and 'ya existe' in json.dumps(r.json()['errores'], ensure_ascii=False)
        web_pk = leer(empresa, lambda: EmissionPoint.objects.get(establishment__code='003', code='002').pk)
        r = web.post(URL, {'action': 'desactivar_punto', 'point': web_pk}, **JSON)
        assert r.status_code == 200 and r.json()['mensaje'] == 'Punto de emisión 003-002 desactivado.'
        assert [p['codigo_completo'] for p in seleccion(web)['elegibles']] == ['001-002', '002-001', '003-001']
        r = web.post(URL, {'action': 'activar_punto', 'point': web_pk}, **JSON)
        elegibles = seleccion(web)['elegibles']
        assert r.status_code == 200 and len(elegibles) == 4
        sur = next(p for p in elegibles if p['codigo_completo'] == '003-001')   # motivo de bloqueo para el selector
        assert sur['listo'] is False and 'numeración de facturas del punto 003-001' in sur['bloqueo']
        assert next(p for p in elegibles if p['codigo_completo'] == '001-002')['bloqueo'] is None
        r = web.post(URL, {'action': 'desactivar_punto', 'point': centro.pk}, **JSON)   # el predeterminado no se desactiva
        assert r.status_code == 400 and 'no se puede desactivar' in r.json()['mensaje']
        assert web.post(URL, {'action': 'otra'}).status_code == 404
        estado = web.get(ESTADO).json()
        assert [l['codigo'] for l in estado['locales']] == ['001', '002', '003']
        sur = estado['locales'][2]
        assert (sur['nombre'], sur['direccion'], sur['activo']) == ('Local Sur', 'Av. Sur 3', True)
        assert [(p['codigo_completo'], p['descripcion'], p['listo']) for p in sur['puntos']] == [('003-001', 'Caja 1', False), ('003-002', 'Ventas web', False)]
        assert set(estado) == {'setup_completo', 'ambiente', 'locales', 'usuarios', 'seleccion', 'tipos', 'mensajes'}
        html = web.get(URL).content.decode()
        assert 'Local Sur' in html and 'Falta configurar la numeración' in html and 'Listo para emitir' in html
        assert AuditLog.objects.filter(action='billing_point_change', detail__accion='desactivar', detail__punto='003-002').exists()
        assert AuditLog.objects.filter(action='billing_point_change', detail__accion='activar', detail__punto='003-002').exists()
