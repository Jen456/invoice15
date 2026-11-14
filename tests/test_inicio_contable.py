"""Inicio contable (C1 del contrato contable v9): core/contabilidad/inicio.py y vistas_inicio.py.

GET /contabilidad/api/inicio/: quién lo abre (cada uno de sus tres permisos por separado, ninguno y cada rol); la forma de
la respuesta; `capacidades` y `acceso`, que salen del contrato de capacidades; las etapas (plan de cuentas sin configurar,
configurado a mano e importado; apertura y conciliación, todavía no disponibles); los pendientes de cada origen con datos
ficticios (revisión del mes en curso, recibos por completar y documentos importados), solo los que el usuario puede
consultar y sin devolver en cero lo que no puede; dos empresas; empresa de la pestaña; complemento cerrado, sin plan y plan
vencido."""
import json
from datetime import datetime, timedelta, timezone as zona
from itertools import count

import pytest
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.adjuntos.models import Captura
from core.contabilidad import capacidades, inicio
from core.contabilidad.capacidades import PENDIENTE
from core.contabilidad.models import Cuenta, ImportacionCuentas
from core.pos.models import Provider
from core.security.models import Module
from core.suscripciones import reglas
from core.tenancy.context import company_context
from core.tenancy.models import (ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER,
                                 Membership)
from tests import ayuda_compras, helpers
from tests.ayudas_ventas import documento_07, factura_autorizada

pytestmark = pytest.mark.django_db

URL = '/contabilidad/api/inicio/'
CAPACIDADES = '/contabilidad/api/capacidades/'
CUENTAS = '/contabilidad/api/cuentas/'
IMPORTAR = '/contabilidad/api/cuentas/importar/'
SIN_PLAN_DE_CUENTAS = {'estado': 'sin_configurar', 'cuentas': None, 'importado_en': None, 'causa': None}
TODOS = ['revision', 'capturas', 'importacion']
_n = count(1)


# ---------------------------------------------------------------- ayudas

def en(empresa, funcion):
    with company_context(empresa):
        return funcion()


def hoy():
    return timezone.localdate()


def mes():
    return f'{hoy():%Y-%m}'


def enviar(client, url, datos):
    return client.post(url, json.dumps(datos), content_type='application/json')


def leer(client, consulta=''):
    respuesta = client.get(f'{URL}{consulta}')
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()


def entrar_con(client, empresa, *codigos):
    """Sesión con un rol a medida que tiene exactamente esos permisos."""
    grupo = helpers.crear_grupo(f'Inicio {next(_n)}: ' + ', '.join(codigos), codigos)
    usuario = helpers.crear_usuario(f'inicio.medida.{grupo.pk}', empresa, grupo)
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    return usuario


def entrar_como(client, empresa, rol):
    usuario = helpers.crear_usuario(f'inicio.{empresa.pk}.{rol.lower()}', empresa, rol)
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    return usuario


def vencer(empresa):
    from core.suscripciones.models import SubscriptionPeriod
    SubscriptionPeriod.objects.filter(company=empresa).update(ends_at=timezone.now() - timedelta(days=1))


def cuenta_nueva(client, empresa, codigo, tipo='movimiento'):
    respuesta = enviar(client, CUENTAS, {'empresa': empresa.pk, 'clave': f'inicio-cuenta-{next(_n):05d}', 'codigo': codigo,
                                         'nombre': f'Cuenta {codigo}', 'tipo': tipo, 'padre_id': None})
    assert respuesta.status_code == 201, respuesta.content
    return respuesta.json()['cuenta']


def subir_plan(client, empresa, *codigos):
    """Sube un CSV con esas cuentas y devuelve el lote en vista previa (todavía no crea nada)."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    contenido = 'Código;Nombre\r\n' + ''.join(f'{codigo};Cuenta {codigo}\r\n' for codigo in codigos)
    respuesta = client.post(IMPORTAR, {'empresa': empresa.pk, 'clave': f'inicio-subida-{next(_n):05d}',
                                       'archivo': SimpleUploadedFile('plan.csv', contenido.encode('utf-8'))})
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()['lote']


def confirmar_plan(client, empresa, lote):
    respuesta = enviar(client, f'{IMPORTAR}{lote["id"]}/confirmar/',
                       {'empresa': empresa.pk, 'clave': f'inicio-confirma-{next(_n):05d}', 'duplicadas': 'omitir'})
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()['lote']


def recibo(client, empresa, nota='Peaje de prueba'):
    """Un recibo por completar guardado por la API de captura rápida (solo una nota: sin archivo)."""
    respuesta = client.post('/adjuntos/api/capturas/', {'empresa': empresa.pk, 'clave': f'inicio-recibo-{next(_n):05d}', 'nota': nota})
    assert respuesta.status_code == 201, respuesta.content
    return respuesta.json()['captura']


def importado(empresa, usuario, **cambios):
    """Un comprobante recibido importado, pendiente de revisión salvo que `cambios` diga otra cosa."""
    return documento_07(empresa, usuario, sec=f'{next(_n) + 500:09d}', **{'estado_revision': 'pendiente', **cambios})


def factura_devuelta(empresa, empleado, fecha=None):
    n = next(_n)
    cliente = helpers.crear_cliente(f'inicio.cliente.{n}', empresa, f'09{n:08d}', f'099{n:07d}')
    producto = helpers.crear_producto(empresa, f'INI{n}')
    return factura_autorizada(empresa, cliente, empleado, producto, fecha=fecha or hoy(), estado='returned')


def compra_con_datos_incompletos(empresa):
    """Una compra de este mes a la que le faltan datos del ATS, de un proveedor al que también le faltan."""
    proveedor = ayuda_compras.crear_proveedor(empresa)
    en(empresa, lambda: Provider.objects.filter(pk=proveedor.pk).update(tipo_identificacion=''))
    return ayuda_compras.compra_antigua(empresa, proveedor, '40.00', fecha=hoy())


def por_origen(datos, origen):
    return [p for p in datos['pendientes'] if p['origen'] == origen]


@pytest.fixture
def entrar(client, empresa, admin):
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    return client


# ---------------------------------------------------------------- quién lo abre

class TestQuienLoAbre:

    @pytest.mark.parametrize('permiso, puede', [
        ('view_kardex', {'revision': False, 'libros': False, 'kardex': True, 'plan_cuentas': {'ver': False, 'editar': False}}),
        ('view_revision', {'revision': True, 'libros': False, 'kardex': False, 'plan_cuentas': {'ver': False, 'editar': False}}),
        ('view_cuenta', {'revision': False, 'libros': False, 'kardex': False, 'plan_cuentas': {'ver': True, 'editar': False}}),
    ])
    def test_basta_uno_de_sus_tres_permisos(self, client, empresa, permiso, puede):
        entrar_con(client, empresa, permiso)
        datos = leer(client)
        assert datos['capacidades'] == puede
        assert datos['acceso']['funciones']['inicio']['estado'] == 'disponible'

    def test_con_ninguno_de_los_tres_es_403_json(self, client, empresa):
        entrar_con(client, empresa, 'view_libros', 'add_cuenta', 'change_cuenta', 'view_captura')   # nada de lo que pide
        respuesta = client.get(URL)
        assert respuesta.status_code == 403 and respuesta['Content-Type'] == 'application/json'
        assert respuesta.json() == {'error': capacidades.TEXTO_SIN_PERMISO, 'codigo': 'sin_permiso', 'causa': 'permiso',
                                    'permisos': ['view_kardex', 'view_revision', 'view_cuenta']}

    @pytest.mark.parametrize('rol, editar', [(ROLE_OWNER, True), (ROLE_ADMIN, True), (ROLE_ACCOUNTANT, True), (ROLE_READONLY, False)])
    def test_roles_que_lo_abren(self, client, empresa, rol, editar):
        entrar_como(client, empresa, rol)
        assert leer(client)['capacidades'] == {'revision': True, 'libros': True, 'kardex': True,
                                               'plan_cuentas': {'ver': True, 'editar': editar}}

    @pytest.mark.parametrize('rol', [ROLE_SELLER, ROLE_CLIENT])
    def test_roles_que_no(self, client, empresa, rol):
        entrar_como(client, empresa, rol)
        respuesta = client.get(f'{URL}?empresa={empresa.pk}')
        assert respuesta.status_code == 403 and respuesta.json()['codigo'] == 'sin_permiso'
        assert set(respuesta.json()) == {'error', 'codigo', 'causa', 'permisos'}   # ni etapas ni pendientes

    def test_sin_sesion(self, client):
        respuesta = client.get(URL)
        assert respuesta.status_code == 302 and respuesta['Location'] == f'/login/?next={URL}'

    def test_solo_get(self, entrar, empresa):
        respuesta = enviar(entrar, URL, {'empresa': empresa.pk})
        assert respuesta.status_code == 405 and respuesta.json()['codigo'] == 'metodo' and respuesta['Allow'] == 'GET'

    def test_el_registro_y_la_vista_piden_lo_mismo(self):
        assert inicio.PERMISOS == ('view_kardex', 'view_revision', 'view_cuenta')
        assert capacidades.funcion_de('inicio').permisos == {'ver': inicio.PERMISOS}


# ---------------------------------------------------------------- forma de la respuesta

class TestRespuesta:

    def test_empresa_recien_creada(self, entrar, empresa):
        datos = leer(entrar, f'?empresa={empresa.pk}')
        assert list(datos) == ['empresa', 'capacidades', 'acceso', 'etapas', 'pendientes', 'origenes']
        assert datos['empresa'] == {'id': empresa.pk, 'ruc': empresa.ruc, 'nombre': empresa.business_name}
        assert datos['capacidades'] == {'revision': True, 'libros': True, 'kardex': True, 'plan_cuentas': {'ver': True, 'editar': True}}
        assert datos['etapas'] == {
            'plan_cuentas': SIN_PLAN_DE_CUENTAS,   # desconocido es null, nunca cero
            'apertura': {'estado': 'no_disponible', 'fecha': None,
                         'causa': 'La apertura contable (por saldos de apertura o por historial detallado) está en construcción.'},
            'conciliacion': {'estado': 'no_disponible',
                             'causa': 'Bancos y conciliación están en construcción. Los formatos de extracto de cada banco '
                                      'esperan muestras reales; un CSV con columnas a elegir no depende de ellas.'}}
        assert datos['pendientes'] == [] and datos['origenes'] == TODOS   # se consultó todo y no hay nada pendiente

    def test_acceso_es_el_contrato_de_capacidades(self, entrar):
        datos = leer(entrar)
        assert datos['acceso'] == entrar.get(CAPACIDADES).json()
        assert datos['acceso']['empresa'] == datos['empresa']
        assert datos['acceso']['funciones']['inicio'] == {
            'nombre': 'Inicio contable', 'ambito': 'contabilidad', 'estado': 'disponible', 'causa': None, 'texto': None,
            'acciones': {'ver': True}, 'faltan': []}

    @pytest.mark.parametrize('rol', [ROLE_OWNER, ROLE_ACCOUNTANT, ROLE_READONLY])
    def test_capacidades_dice_lo_mismo_que_acceso(self, client, empresa, rol):
        entrar_como(client, empresa, rol)
        datos = leer(client)
        funciones = datos['acceso']['funciones']
        assert datos['capacidades'] == {
            'revision': funciones['revision']['acciones']['ver'], 'libros': funciones['libros']['acciones']['ver'],
            'kardex': funciones['kardex']['acciones']['ver'],
            'plan_cuentas': {'ver': funciones['plan_cuentas']['acciones']['ver'],
                             'editar': funciones['plan_cuentas']['acciones']['editar']}}

    def test_no_cambia_el_modulo_activo_del_menu(self, entrar):
        """El inicio se consulta en segundo plano: no le quita al menú el módulo que el usuario tiene abierto."""
        assert entrar.get('/contabilidad/inventario/').status_code == 200
        modulo = entrar.session['module_id']
        leer(entrar)
        assert entrar.session['module_id'] == modulo


# ---------------------------------------------------------------- etapas

class TestEtapas:

    def test_configurado_a_mano(self, entrar, empresa):
        grupo = cuenta_nueva(entrar, empresa, '1', 'grupo')
        cuenta_nueva(entrar, empresa, '2')
        assert leer(entrar)['etapas']['plan_cuentas'] == {'estado': 'configurado', 'cuentas': 2, 'importado_en': None, 'causa': None}
        # una cuenta desactivada sigue en el plan
        cambio = entrar.patch(f'{CUENTAS}{grupo["id"]}/', content_type='application/json',
                              data=json.dumps({'empresa': empresa.pk, 'version': grupo['version'], 'activa': False}))
        assert cambio.status_code == 200 and cambio.json()['cuenta']['activa'] is False
        assert leer(entrar)['etapas']['plan_cuentas']['cuentas'] == 2

    def test_una_vista_previa_no_configura_nada(self, entrar, empresa):
        """Subir el archivo y mirar su vista previa no crea cuentas: la etapa no avanza por haber abierto la pantalla."""
        lote = subir_plan(entrar, empresa, '1', '1.1', '1.1.01')
        assert lote['estado'] == 'vista_previa' and lote['resumen']['validas'] == 3
        assert leer(entrar)['etapas']['plan_cuentas'] == SIN_PLAN_DE_CUENTAS
        cuenta_nueva(entrar, empresa, '9')   # con una cuenta a mano y el lote sin confirmar, sigue siendo «configurado»
        assert leer(entrar)['etapas']['plan_cuentas']['estado'] == 'configurado'

    def test_importado(self, entrar, empresa):
        confirmado = confirmar_plan(entrar, empresa, subir_plan(entrar, empresa, '1', '1.1', '1.1.01'))
        assert (confirmado['estado'], confirmado['creadas']) == ('confirmado', 3)
        etapa = leer(entrar)['etapas']['plan_cuentas']
        assert etapa == {'estado': 'importado', 'cuentas': 3, 'importado_en': hoy().isoformat(), 'causa': None}
        assert etapa['importado_en'] == confirmado['confirmado_en']
        cuenta_nueva(entrar, empresa, '2')   # añadir cuentas a mano después no deshace que el plan vino de un archivo
        assert leer(entrar)['etapas']['plan_cuentas'] == {**etapa, 'cuentas': 4}
        subir_plan(entrar, empresa, '3')     # ni otro archivo que se queda en vista previa (no tiene fecha de confirmación)
        assert leer(entrar)['etapas']['plan_cuentas'] == {**etapa, 'cuentas': 4}

    def test_la_fecha_es_la_del_ultimo_lote_confirmado_en_hora_local(self, entrar, empresa):
        primero = confirmar_plan(entrar, empresa, subir_plan(entrar, empresa, '1'))
        segundo = confirmar_plan(entrar, empresa, subir_plan(entrar, empresa, '2'))
        # 02/11 a las 03:30 UTC son las 22:30 del 01/11 en Ecuador; el otro lote se confirmó dos días antes
        en(empresa, lambda: ImportacionCuentas.objects.filter(pk=segundo['id']).update(
            confirmado_en=datetime(2026, 11, 2, 3, 30, tzinfo=zona.utc)))
        en(empresa, lambda: ImportacionCuentas.objects.filter(pk=primero['id']).update(
            confirmado_en=datetime(2026, 10, 30, 15, 0, tzinfo=zona.utc)))
        assert leer(entrar)['etapas']['plan_cuentas'] == {'estado': 'importado', 'cuentas': 2, 'importado_en': '2026-11-01', 'causa': None}

    def test_sin_permiso_para_ver_el_plan_no_se_cuenta_nada(self, client, empresa, admin):
        """Ni el número de cuentas ni «sin configurar»: a quien no ve el plan se le dice que no puede verlo."""
        en(empresa, lambda: Cuenta.objects.create(codigo='1', nombre='Activo', tipo='grupo'))
        entrar_con(client, empresa, 'view_kardex', 'view_revision')
        datos = leer(client)
        assert datos['etapas']['plan_cuentas'] == {'estado': 'no_disponible', 'cuentas': None, 'importado_en': None,
                                                   'causa': capacidades.TEXTO_SIN_PERMISO}
        assert datos['acceso']['funciones']['plan_cuentas']['estado'] == 'sin_permiso'
        assert datos['etapas']['apertura']['estado'] == 'no_disponible'   # las demás etapas, igual que para todos

    def test_apertura_y_conciliacion_esperan_a_sus_bloques(self, entrar):
        """Mientras `apertura` y `bancos` sigan pendientes en el registro de funciones. Quien construya uno de esos
        bloques cambia su etapa en inicio.etapas: esta prueba deja de pasar en cuanto el registro lo dé por construido."""
        etapas = leer(entrar)['etapas']
        for etapa, funcion in (('apertura', 'apertura'), ('conciliacion', 'bancos')):
            registrada = capacidades.funcion_de(funcion)
            assert registrada.construccion == PENDIENTE, funcion
            assert etapas[etapa]['estado'] == 'no_disponible' and etapas[etapa]['causa'] == registrada.texto_pendiente
            assert 'en construcción' in etapas[etapa]['causa']
        assert etapas['apertura']['fecha'] is None and set(etapas['conciliacion']) == {'estado', 'causa'}
        # nunca «completado»
        assert {e['estado'] for e in etapas.values()} <= {'sin_configurar', 'configurado', 'importado', 'no_disponible'}


# ---------------------------------------------------------------- pendientes

class TestPendientes:

    @pytest.fixture
    def con_pendientes(self, entrar, empresa, admin):
        """Datos ficticios de los tres orígenes: una factura devuelta, una compra y su proveedor con datos del ATS
        incompletos, un recibo por completar y dos documentos importados sin revisar (más tres que no cuentan)."""
        factura_devuelta(empresa, admin)
        compra_con_datos_incompletos(empresa)
        recibo(entrar, empresa)
        importado(empresa, admin)
        importado(empresa, admin)
        importado(empresa, admin, estado_revision='aprobado')          # ya revisado
        importado(empresa, admin, clasificacion='ajeno')               # de otro contribuyente: no está en la bandeja
        importado(empresa, admin, estado_procesamiento='pendiente_xml')   # todavía sin su XML
        return entrar

    def test_de_cada_origen(self, con_pendientes):
        datos = leer(con_pendientes)
        revision = f'/tributario/revision/?mes={mes()}'
        assert datos['pendientes'] == [
            {'origen': 'revision', 'codigo': 'devueltos', 'titulo': 'Comprobantes devueltos o sin autorizar', 'cantidad': 1,
             'url': f'{revision}#fp-rev-devueltos'},
            {'origen': 'revision', 'codigo': 'datos_ats', 'titulo': 'Datos del ATS incompletos', 'cantidad': 2,
             'url': f'{revision}#fp-rev-datos_ats'},
            {'origen': 'revision', 'codigo': 'respaldos', 'titulo': 'Respaldos pendientes', 'cantidad': 1,
             'url': f'{revision}#fp-rev-respaldos'},
            {'origen': 'capturas', 'codigo': 'recibo_por_completar', 'titulo': 'Recibos por completar', 'cantidad': 1,
             'url': '/adjuntos/capturas/'},
            {'origen': 'importacion', 'codigo': 'documento_por_revisar', 'titulo': 'Documentos importados pendientes de revisión',
             'cantidad': 2, 'url': '/importacion/pendientes/'},
        ]
        assert datos['origenes'] == TODOS

    def test_la_revision_cuenta_lo_mismo_que_su_pantalla(self, con_pendientes, empresa, admin):
        """Las categorías con algo «por revisar» del mes en curso, con su nombre y su cuenta; lo informativo no es pendiente."""
        cliente = helpers.crear_cliente('inicio.cliente.vencida', empresa, '0912345678', '0990000001')
        factura_autorizada(empresa, cliente, admin, helpers.crear_producto(empresa, 'INIV'), fecha=hoy() - timedelta(days=70),
                           credito=True, vence=hoy() - timedelta(days=40))   # cuenta por cobrar vencida: informativa
        revision = con_pendientes.get('/tributario/api/revision/').json()
        assert revision['mes'] == mes()
        assert revision['por_categoria']['vencidas'] == {'nombre': 'Cuentas vencidas', 'revisar': 0, 'informativo': 1}
        esperado = [(clave, c['nombre'], c['revisar']) for clave, c in revision['por_categoria'].items() if c['revisar']]
        del_inicio = por_origen(leer(con_pendientes), 'revision')
        assert [(p['codigo'], p['titulo'], p['cantidad']) for p in del_inicio] == esperado
        assert sum(p['cantidad'] for p in del_inicio) == revision['pendientes'] == 4
        assert 'vencidas' not in {p['codigo'] for p in del_inicio}

    def test_solo_el_mes_en_curso(self, entrar, empresa, admin):
        factura_devuelta(empresa, admin, fecha=hoy().replace(day=1) - timedelta(days=3))   # del mes pasado
        assert por_origen(leer(entrar), 'revision') == []
        factura_devuelta(empresa, admin)
        assert [(p['codigo'], p['cantidad']) for p in por_origen(leer(entrar), 'revision')] == [('devueltos', 1)]

    def test_los_recibos_son_los_de_cualquier_mes(self, entrar, empresa):
        """El origen `capturas` cuenta todo lo que sigue sin completar; la revisión, solo lo guardado este mes."""
        viejo = recibo(entrar, empresa, 'Recibo de hace meses')
        recibo(entrar, empresa)
        en(empresa, lambda: Captura.objects.filter(pk=viejo['id']).update(creado_en=timezone.now() - timedelta(days=95)))
        datos = leer(entrar)
        assert [p['cantidad'] for p in por_origen(datos, 'capturas')] == [2]
        assert [(p['codigo'], p['cantidad']) for p in por_origen(datos, 'revision')] == [('respaldos', 1)]

    @pytest.mark.parametrize('permisos, origenes, con_entradas', [
        (('view_kardex',), [], []),
        (('view_cuenta',), [], []),
        (('view_revision',), ['revision'], ['revision']),
        # sin `view_adjunto` solo se ven los recibos propios (regla de la captura rápida): consultado y sin pendientes
        (('view_kardex', 'view_captura'), ['capturas'], []),
        (('view_kardex', 'view_captura', 'view_adjunto'), ['capturas'], ['capturas']),
        (('view_cuenta', 'view_documentoimportado'), ['importacion'], ['importacion']),
        (('view_revision', 'view_captura', 'view_adjunto', 'view_documentoimportado'), TODOS, TODOS),
    ])
    def test_cada_origen_solo_con_su_permiso(self, client, con_pendientes, empresa, permisos, origenes, con_entradas):
        """Lo que no le corresponde no aparece, ni siquiera en cero: no figura entre los orígenes consultados. Un origen
        consultado sin nada pendiente figura en `origenes` y no deja entradas."""
        con_pendientes.logout()
        entrar_con(client, empresa, *permisos)
        datos = leer(client)
        assert datos['origenes'] == origenes
        assert sorted({p['origen'] for p in datos['pendientes']}, key=TODOS.index) == con_entradas
        assert all(p['cantidad'] > 0 for p in datos['pendientes'])

    def test_quien_no_ve_los_recibos_tampoco_los_recibe_dentro_de_la_revision(self, client, con_pendientes, empresa):
        """La revisión se calcula con el rol del usuario, como en su pantalla: sin `view_captura`, sin recibos."""
        con_pendientes.logout()
        entrar_con(client, empresa, 'view_revision')
        assert [(p['codigo'], p['cantidad']) for p in leer(client)['pendientes']] == [('devueltos', 1), ('datos_ats', 2)]

    def test_los_importados_solo_con_un_plan_que_los_incluya(self, client):
        """Con el Plan 1000 la importación no se abre (PlanMiddleware): sus pendientes no se consultan ni se anuncian."""
        empresa = helpers.crear_empresa('PLAN 1000 INICIO', plan='plan-1000')
        usuario = entrar_como(client, empresa, ROLE_OWNER)
        importado(empresa, usuario)
        assert client.get('/importacion/api/documentos/').status_code == 403
        datos = leer(client)
        assert datos['origenes'] == ['revision', 'capturas'] and datos['pendientes'] == []

    def test_los_enlaces_llevan_a_pantallas_que_abren(self, con_pendientes):
        for pendiente in leer(con_pendientes)['pendientes']:
            pagina = con_pendientes.get(pendiente['url'].split('#')[0])
            assert pagina.status_code == 200, pendiente['url']
            if pendiente['origen'] == 'revision':   # el ancla es el título de la categoría en esa pantalla
                assert f'id="fp-rev-{pendiente["codigo"]}"' in pagina.content.decode(), pendiente['url']

    def test_los_titulos_son_los_del_menu(self):
        assert inicio.TITULOS['capturas'] == Module.objects.get(url=inicio.URL_CAPTURAS).name
        assert inicio.TITULOS['importacion'] == Module.objects.get(url=inicio.URL_IMPORTADOS).description

    def test_contar_no_cuesta_mas_consultas_con_mas_datos(self, entrar, empresa, admin):
        """Cuentas, recibos de otros meses y documentos importados se cuentan en la base: con cincuenta de cada uno el
        inicio hace las mismas consultas que con uno. (La revisión del mes hace las suyas, las de su pantalla.)"""
        def sembrar(desde, hasta):
            def crear():
                for i in range(desde, hasta):
                    Cuenta.objects.create(codigo=f'9.{i}', nombre=f'Cuenta 9.{i}', tipo='movimiento')
                    Captura.objects.create(clave=f'inicio-muchas-{i:05d}', nota=f'Recibo {i}', creado_por=admin,
                                           creado_en=timezone.now() - timedelta(days=95))
            en(empresa, crear)
            for _ in range(desde, hasta):
                importado(empresa, admin)

        def consultas():
            with CaptureQueriesContext(connection) as capturadas:
                datos = leer(entrar)
            return len(capturadas), datos

        sembrar(0, 1)
        con_uno, datos = consultas()
        assert datos['etapas']['plan_cuentas']['cuentas'] == 1 and [p['cantidad'] for p in datos['pendientes']] == [1, 1]
        sembrar(1, 50)
        con_cincuenta, datos = consultas()
        assert datos['etapas']['plan_cuentas']['cuentas'] == 50 and [p['cantidad'] for p in datos['pendientes']] == [50, 50]
        assert con_cincuenta == con_uno


# ---------------------------------------------------------------- dos empresas

class TestDosEmpresas:

    def test_cada_empresa_ve_lo_suyo(self, client, empresa, empresa_b, admin):
        Membership.objects.create(user=admin, company=empresa_b, group=Group.objects.get(name=ROLE_OWNER))
        helpers.iniciar_sesion(client, admin, empresa=empresa_b)
        confirmar_plan(client, empresa_b, subir_plan(client, empresa_b, '1', '1.1'))
        recibo(client, empresa_b)
        importado(empresa_b, admin)
        factura_devuelta(empresa_b, admin)
        en_b = leer(client, f'?empresa={empresa_b.pk}')
        assert en_b['empresa']['id'] == empresa_b.pk and en_b['etapas']['plan_cuentas']['estado'] == 'importado'
        assert [(p['origen'], p['codigo'], p['cantidad']) for p in en_b['pendientes']] == [
            ('revision', 'devueltos', 1), ('revision', 'respaldos', 1), ('capturas', 'recibo_por_completar', 1),
            ('importacion', 'documento_por_revisar', 1)]

        client.post('/empresas/cambiar/', {'company': empresa.pk})
        en_a = leer(client, f'?empresa={empresa.pk}')   # nada de B: ni cuentas, ni lote, ni pendientes
        assert en_a['empresa'] == {'id': empresa.pk, 'ruc': empresa.ruc, 'nombre': empresa.business_name}
        assert en_a['etapas']['plan_cuentas'] == SIN_PLAN_DE_CUENTAS and en_a['pendientes'] == [] and en_a['origenes'] == TODOS

    def test_pestana_que_quedo_con_la_otra_empresa(self, client, empresa, empresa_b, admin):
        Membership.objects.create(user=admin, company=empresa_b, group=Group.objects.get(name=ROLE_OWNER))
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        en(empresa_b, lambda: Cuenta.objects.create(codigo='1', nombre='Activo', tipo='grupo'))
        assert leer(client, f'?empresa={empresa.pk}')['empresa']['id'] == empresa.pk
        client.post('/empresas/cambiar/', {'company': empresa_b.pk})
        vieja = client.get(f'{URL}?empresa={empresa.pk}')   # la pestaña que se armó para la empresa A
        assert vieja.status_code == 409 and vieja.json()['codigo'] == 'empresa_cambiada'
        assert set(vieja.json()) == {'error', 'codigo'}   # nada de la empresa B con apariencia de A
        assert leer(client, f'?empresa={empresa_b.pk}')['etapas']['plan_cuentas']['cuentas'] == 1


# ---------------------------------------------------------------- licencia

class TestLicencia:

    def test_complemento_cerrado(self, entrar, empresa, settings):
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = []
        respuesta = entrar.get(f'{URL}?empresa={empresa.pk}')
        assert respuesta.status_code == 403
        cuerpo = respuesta.json()
        assert (cuerpo['codigo'], cuerpo['plan'], cuerpo['causa'], cuerpo['error']) == (
            'complemento_pendiente', 'complemento_contable', 'licencia', reglas.MENSAJE_COMPLEMENTO)
        assert cuerpo['licencia']['estado'] == 'complemento_pendiente'
        assert set(cuerpo) == {'error', 'plan', 'codigo', 'causa', 'licencia'}   # ni etapas ni pendientes
        # la ruta de capacidades sigue explicándolo, y allí el inicio figura sin licencia
        assert entrar.get(CAPACIDADES).json()['funciones']['inicio']['estado'] == 'sin_licencia'

    def test_solo_abre_la_empresa_de_la_lista(self, entrar, empresa, empresa_b, settings):
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [empresa_b.ruc]
        assert entrar.get(URL).status_code == 403
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [empresa.ruc]
        assert leer(entrar)['acceso']['licencia']['estado'] == 'activa'

    def test_sin_plan_pagado(self, client):
        gratuita = helpers.crear_empresa('GRATIS INICIO', plan=None)
        entrar_como(client, gratuita, ROLE_OWNER)
        respuesta = client.get(URL)
        assert respuesta.status_code == 403
        assert (respuesta.json()['codigo'], respuesta.json()['causa'], respuesta.json()['licencia']['estado']) == (
            'plan', 'licencia', 'plan_requerido')

    def test_plan_vencido_se_consulta_y_no_ofrece_editar(self, entrar, empresa, admin):
        cuenta_nueva(entrar, empresa, '1')
        importado(empresa, admin)
        vencer(empresa)
        datos = leer(entrar)
        assert (datos['acceso']['licencia']['estado'], datos['acceso']['licencia']['solo_consulta']) == ('plan_vencido', True)
        assert datos['capacidades'] == {'revision': True, 'libros': True, 'kardex': True, 'plan_cuentas': {'ver': True, 'editar': False}}
        assert datos['etapas']['plan_cuentas'] == {'estado': 'configurado', 'cuentas': 1, 'importado_en': None, 'causa': None}
        # la importación de un plan ilimitado vencido también se sigue consultando
        assert [(p['origen'], p['cantidad']) for p in datos['pendientes']] == [('importacion', 1)] and datos['origenes'] == TODOS
