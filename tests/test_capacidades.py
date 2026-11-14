"""Contrato de capacidades del Complemento Contable (core/contabilidad/capacidades.py) y ayudantes de las rutas nuevas de
/contabilidad/api/ (core/contabilidad/api.py).

La respuesta distingue licencia, permiso, módulo pendiente y datos por completar sin abrir el complemento a nadie nuevo:
GET /contabilidad/api/capacidades/ es la única ruta de /tributario/ y /contabilidad/ que responde con el complemento
cerrado, y los 403 de PlanMiddleware conservan `error`, `plan` y `codigo` (lo demás se añade).

Aquí la lista de revisión se fija de forma explícita en cada prueba (fixture `lista`): el «*» de conftest abre el
complemento a todas las empresas y no ejercitaría ni el cierre ni la lista."""
import json
import re
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Group, Permission
from django.http import JsonResponse
from django.urls import Resolver404, URLResolver, get_resolver, path, resolve
from django.utils import timezone

from config.urls import urlpatterns as rutas_del_proyecto
from core.contabilidad import api, capacidades
from core.contabilidad.capacidades import CONTABILIDAD, PENDIENTE, TRIBUTARIO, Funcion, dato
from core.suscripciones import reglas
from core.suscripciones.middleware import mensaje_de_bloqueo
from core.suscripciones.servicios import estado_empresa
from core.tenancy.models import (ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER,
                                 Membership)
from tests import helpers

pytestmark = pytest.mark.django_db

URL = '/contabilidad/api/capacidades/'
ECO = '/contabilidad/api/pruebas/eco/'
DATOS = '/contabilidad/api/pruebas/datos/'
INVENTARIO = '/contabilidad/api/inventario/'       # GET de API que ya existía
MOVIMIENTOS = '/contabilidad/api/kardex/movimientos/'   # envío que ya existía
CODIGOS = ['libros', 'revision', 'ats', 'formularios', 'kardex', 'inventario', 'plan_cuentas', 'importar_cuentas', 'inicio',
           'evidencias', 'apertura', 'cartera_inicial', 'historico', 'asientos', 'diario_mayor', 'bancos', 'cierre',
           'estados_financieros', 'formulario_101']
# Siguen pendientes al terminar el bloque 1 (las tres del bloque pasan a disponibles al publicar su ruta). Bloque 2 · Parte B:
# la apertura pasa a disponible y la cartera inicial y los históricos (corte 2) quedan pendientes.
PENDIENTES = ['evidencias', 'cartera_inicial', 'historico', 'asientos', 'diario_mayor', 'bancos', 'cierre', 'estados_financieros',
              'formulario_101']
TODO_FALSO = {'ver': False, 'registrar': False, 'anular': False}


# ---------------------------------------------------------------- vistas de prueba (solo en este archivo)

class Eco(api.ApiContable):
    """Una ruta como las que vienen (cuentas, importación): permiso por método, cuerpo, clave y errores por campo."""
    permisos = {'GET': 'view_kardex', 'POST': 'add_movimientomanual', 'PATCH': ('change_movimientomanual', 'view_libros')}

    def get(self, request):
        return JsonResponse({'ok': True})

    def post(self, request):
        datos = api.cuerpo(request)
        clave = api.clave_de(datos)
        errores = api.Errores()
        if not datos.get('codigo'):
            errores.agregar('codigo', 'Escribe el código.')
        if not datos.get('nombre'):
            errores.agregar('nombre', 'Escribe el nombre.')
        elif len(datos['nombre']) > 5:
            errores.agregar('nombre', 'Nombre demasiado largo.')
            errores.agregar('nombre', 'Usa hasta 5 caracteres.')
        errores.comprobar()
        if datos['codigo'] == 'usada':
            raise api.ErrorApi('clave_usada', 'Esta clave ya se usó para otra cuenta.', 409, cuenta={'id': 7})
        if datos['codigo'] == 'editar':
            api.exigir_permiso(request, 'change_movimientomanual')
        return JsonResponse({'clave': clave, 'codigo': datos['codigo']}, status=201)

    def patch(self, request):
        return JsonResponse({'version': api.cuerpo(request).get('version')})


class ConDatos(api.ApiContable):
    permisos = {'GET': 'view_kardex'}

    def get(self, request):
        faltan = capacidades.faltantes(request, 'de_prueba')
        if faltan:
            raise api.Rechazo(capacidades.rechazo_datos(faltan))
        return JsonResponse({'ok': True})


# `@pytest.mark.urls(__name__)`: las rutas del proyecto más las dos de prueba, bajo /contabilidad/ para que pasen por el
# mismo PlanMiddleware que las rutas contables de verdad.
urlpatterns = [path('contabilidad/api/pruebas/eco/', Eco.as_view()),
               path('contabilidad/api/pruebas/datos/', ConDatos.as_view())] + list(rutas_del_proyecto)
con_rutas_de_prueba = pytest.mark.urls(__name__)


# ---------------------------------------------------------------- ayudas

@pytest.fixture(autouse=True)
def lista(settings):
    """Lista de revisión vacía (como en producción). `lista(empresa, …)` la fija con los RUC de esas empresas."""
    settings.FPA_COMPLEMENTO_CONTABLE_REVISION = []

    def fijar(*empresas):
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [e.ruc for e in empresas]
    return fijar


def entrar(client, empresa, rol=ROLE_OWNER):
    usuario = helpers.crear_usuario(f'cap.{empresa.pk}.{rol.lower()}', empresa, rol)
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    return usuario


def vencer(empresa):
    from core.suscripciones.models import SubscriptionPeriod
    SubscriptionPeriod.objects.filter(company=empresa).update(ends_at=timezone.now() - timedelta(days=1))


def enviar(client, url, datos, metodo='post'):
    return getattr(client, metodo)(url, json.dumps(datos), content_type='application/json')


def rutas_del_complemento():
    """Todas las rutas de /tributario/ y /contabilidad/, con sus parámetros rellenados (el bloqueo corta antes de mirarlos)."""
    def recorrer(patrones, prefijo=''):
        for p in patrones:
            if isinstance(p, URLResolver):
                yield from recorrer(p.url_patterns, prefijo + str(p.pattern))
            else:
                yield prefijo + str(p.pattern)
    for ruta in sorted(set(recorrer(get_resolver().url_patterns))):
        if ruta.startswith(('tributario/', 'contabilidad/')):
            yield '/' + re.sub(r'<(?:(\w+):)?\w+>', lambda m: '1' if m.group(1) == 'int' else 'ventas', ruta)


def cerrada(respuesta):
    """El 403 del complemento cerrado, con lo que ya llevaba (tests/test_complemento_contable.py) y lo que se añade."""
    cuerpo = respuesta.json() if respuesta.status_code == 403 else {}
    return (cuerpo.get('codigo'), cuerpo.get('plan'), cuerpo.get('error'), cuerpo.get('causa')) == (
        'complemento_pendiente', 'complemento_contable', reglas.MENSAJE_COMPLEMENTO, 'licencia')


# ---------------------------------------------------------------- licencia

class TestLicencia:

    def test_sin_plan(self, client, lista):
        gratuita = helpers.crear_empresa('GRATIS CAPACIDADES', plan=None)
        lista(gratuita)
        entrar(client, gratuita)
        datos = client.get(URL).json()
        texto = mensaje_de_bloqueo(estado_empresa(gratuita))
        assert datos['licencia'] == {'estado': 'plan_requerido', 'solo_consulta': False, 'texto': texto, 'puede_gestionar': True,
                                     'url': '/suscripcion/'}
        assert 'se activan con un plan anual' in texto
        kardex = datos['funciones']['kardex']
        assert (kardex['estado'], kardex['causa'], kardex['texto']) == ('sin_licencia', 'licencia', texto)
        assert kardex['acciones'] == TODO_FALSO and kardex['faltan'] == []

    def test_sin_plan_quien_no_gestiona_el_plan_no_recibe_el_enlace(self, client, lista):
        gratuita = helpers.crear_empresa('GRATIS CONTADOR', plan=None)
        lista(gratuita)
        entrar(client, gratuita, ROLE_ACCOUNTANT)
        licencia = client.get(URL).json()['licencia']
        assert (licencia['estado'], licencia['puede_gestionar'], licencia['url']) == ('plan_requerido', False, None)

    def test_con_plan_y_fuera_de_la_lista(self, client, empresa, empresa_b, lista):
        lista(empresa_b)   # hay lista, pero esta empresa no está
        entrar(client, empresa)
        datos = client.get(URL).json()
        assert datos['licencia'] == {'estado': 'complemento_pendiente', 'solo_consulta': False, 'texto': reglas.MENSAJE_COMPLEMENTO,
                                     'puede_gestionar': True, 'url': None}   # el complemento no se contrata todavía: sin enlace
        for codigo in ('libros', 'revision', 'ats', 'formularios', 'kardex', 'inventario'):
            funcion = datos['funciones'][codigo]
            assert (funcion['estado'], funcion['causa'], funcion['texto']) == ('sin_licencia', 'licencia', reglas.MENSAJE_COMPLEMENTO)
            assert not any(funcion['acciones'].values())

    def test_sin_plan_y_fuera_de_la_lista_manda_el_complemento(self, client):
        """Mismo orden que el middleware: sin complemento no hay plan que lo abra, así que no se ofrece comprar un plan."""
        gratuita = helpers.crear_empresa('GRATIS SIN LISTA', plan=None)
        entrar(client, gratuita)
        licencia = client.get(URL).json()['licencia']
        assert (licencia['estado'], licencia['url']) == ('complemento_pendiente', None)

    def test_en_la_lista_con_plan(self, client, empresa, lista):
        lista(empresa)
        entrar(client, empresa)
        datos = client.get(URL).json()
        assert set(datos) == {'empresa', 'licencia', 'funciones'}   # ningún dato contable
        assert datos['empresa'] == {'id': empresa.pk, 'ruc': empresa.ruc, 'nombre': empresa.business_name}
        assert datos['licencia'] == {'estado': 'activa', 'solo_consulta': False, 'texto': None, 'puede_gestionar': True, 'url': None}
        assert list(datos['funciones']) == CODIGOS
        assert datos['funciones']['kardex'] == {
            'nombre': 'Kardex por producto', 'ambito': 'contabilidad', 'estado': 'disponible', 'causa': None, 'texto': None,
            'acciones': {'ver': True, 'registrar': True, 'anular': True}, 'faltan': [], 'avisos': []}
        assert datos['funciones']['libros'] == {
            'nombre': 'Libros mensuales', 'ambito': 'tributario', 'estado': 'disponible', 'causa': None, 'texto': None,
            'acciones': {'ver': True}, 'faltan': [], 'avisos': []}

    def test_plan_vencido_solo_consulta(self, client, empresa, lista):
        lista(empresa)
        vencer(empresa)
        entrar(client, empresa)
        datos = client.get(URL).json()
        licencia = datos['licencia']
        assert (licencia['estado'], licencia['solo_consulta'], licencia['url']) == ('plan_vencido', True, '/suscripcion/')
        assert 'venció' in licencia['texto'] and licencia['texto'] == mensaje_de_bloqueo(estado_empresa(empresa))
        kardex = datos['funciones']['kardex']
        assert (kardex['estado'], kardex['causa']) == ('disponible', None)   # se consulta
        assert kardex['acciones'] == {'ver': True, 'registrar': False, 'anular': False}   # pero no se guarda nada
        assert datos['funciones']['libros']['acciones'] == {'ver': True}

    def test_dice_lo_mismo_que_hace_el_middleware(self, client, empresa, empresa_b, lista):
        """La explicación y la puerta salen de las mismas reglas: en cada situación, lo que anuncia `licencia` es lo que
        PlanMiddleware hace con una consulta y con un envío de las rutas que ya existían."""
        gratuita = helpers.crear_empresa('GRATIS EN LISTA', plan=None)
        vencida = helpers.crear_empresa('VENCIDA EN LISTA')
        vencer(vencida)
        lista(empresa, gratuita, vencida)   # empresa_b tiene plan y no está en la lista
        usuario = helpers.crear_usuario('cap.cuatro.empresas', empresa, ROLE_OWNER)
        for otra in (empresa_b, gratuita, vencida):
            Membership.objects.create(user=usuario, company=otra, group=Group.objects.get(name=ROLE_OWNER))
        helpers.iniciar_sesion(client, usuario, empresa=empresa)
        visto = {}
        for e in (empresa, empresa_b, gratuita, vencida):
            client.post('/empresas/cambiar/', {'company': e.pk})
            datos = client.get(URL).json()
            licencia = datos['licencia']
            assert datos['empresa']['id'] == e.pk
            consulta, envio = client.get(INVENTARIO), client.post(MOVIMIENTOS, {'clave': 'capacidades-0001'})
            visto[e.pk] = (licencia['estado'], consulta.status_code, envio.status_code)
            for respuesta in (consulta, envio):
                if respuesta.status_code == 403:
                    cuerpo = respuesta.json()
                    assert cuerpo['licencia'] == licencia and cuerpo['error'] == licencia['texto'] and cuerpo['causa'] == 'licencia'
        assert visto == {
            empresa.pk: ('activa', 200, 400),                # el envío llega a la vista (400: le faltan los datos del movimiento)
            empresa_b.pk: ('complemento_pendiente', 403, 403),
            gratuita.pk: ('plan_requerido', 403, 403),
            vencida.pk: ('plan_vencido', 200, 403),          # solo consulta
        }


# ---------------------------------------------------------------- roles y empresa

class TestRolesYEmpresa:

    @pytest.mark.parametrize('rol, kardex, tributario', [
        (ROLE_OWNER, ('disponible', {'ver': True, 'registrar': True, 'anular': True}), 'disponible'),
        (ROLE_ADMIN, ('disponible', {'ver': True, 'registrar': True, 'anular': True}), 'disponible'),
        (ROLE_ACCOUNTANT, ('disponible', {'ver': True, 'registrar': True, 'anular': True}), 'disponible'),
        (ROLE_READONLY, ('disponible', {'ver': True, 'registrar': False, 'anular': False}), 'disponible'),
        (ROLE_SELLER, ('sin_permiso', TODO_FALSO), 'sin_permiso'),
    ])
    def test_cada_rol_de_personal(self, client, empresa, lista, rol, kardex, tributario):
        lista(empresa)
        entrar(client, empresa, rol)
        respuesta = client.get(URL)
        assert respuesta.status_code == 200
        funciones = respuesta.json()['funciones']
        assert (funciones['kardex']['estado'], funciones['kardex']['acciones']) == kardex
        assert funciones['inventario']['estado'] == kardex[0]
        for codigo in ('libros', 'revision', 'ats', 'formularios'):
            assert funciones[codigo]['estado'] == tributario, codigo
        if rol == ROLE_SELLER:
            assert funciones['kardex']['causa'] == 'permiso' and funciones['kardex']['texto'] == capacidades.TEXTO_SIN_PERMISO
        assert respuesta.json()['licencia']['puede_gestionar'] is (rol in (ROLE_OWNER, ROLE_ADMIN))

    @pytest.mark.parametrize('abierta', [True, False])
    def test_el_rol_cliente_no_la_consulta(self, client, empresa, lista, abierta):
        if abierta:
            lista(empresa)
        entrar(client, empresa, ROLE_CLIENT)
        respuesta = client.get(URL)   # GET: también JSON, no una redirección
        assert respuesta.status_code == 403 and respuesta['Content-Type'] == 'application/json'
        assert respuesta.json() == {'error': capacidades.TEXTO_SIN_PERMISO, 'codigo': 'sin_permiso', 'causa': 'permiso', 'permisos': []}

    def test_sin_sesion_va_al_inicio_de_sesion(self, client):
        respuesta = client.get(URL)
        assert respuesta.status_code == 302 and respuesta['Location'] == f'/login/?next={URL}'

    @pytest.mark.parametrize('caso', ['varias_sin_elegir', 'membresia_desactivada', 'superusuario'])
    def test_con_sesion_y_sin_empresa_activa_responde_el_proyecto(self, client, empresa, empresa_b, lista, caso):
        """La segunda excepción a «toda negativa es JSON», como la documenta el contrato: con sesión y sin empresa activa,
        CompanyMiddleware corta antes de llegar a la ruta, igual que en todo el proyecto. Una consulta va al selector de
        empresas (302, HTML) y un envío recibe un 403 sin `codigo` ni `causa`. Si esto cambia, cambia el contrato."""
        lista(empresa, empresa_b)
        if caso == 'superusuario':
            helpers.iniciar_sesion(client, helpers.crear_usuario('cap.plataforma', superusuario=True))
        elif caso == 'varias_sin_elegir':
            usuario = helpers.crear_usuario('cap.dos.empresas', empresa, ROLE_OWNER)
            Membership.objects.create(user=usuario, company=empresa_b, group=Group.objects.get(name=ROLE_OWNER))
            helpers.iniciar_sesion(client, usuario)
        else:
            usuario = entrar(client, empresa)
            assert client.get(URL).status_code == 200
            Membership.objects.filter(user=usuario, company=empresa).update(is_active=False)   # con la pestaña abierta
        for ruta in (URL, f'{URL}?empresa={empresa.pk}', '/contabilidad/api/inicio/', '/contabilidad/api/cuentas/',
                     '/contabilidad/api/cuentas/importar/1/'):
            respuesta = client.get(ruta)
            assert respuesta.status_code == 302 and respuesta['Location'] == '/empresas/', ruta
            assert not respuesta['Content-Type'].startswith('application/json'), ruta
        for metodo, ruta in (('post', '/contabilidad/api/cuentas/'), ('patch', '/contabilidad/api/cuentas/1/'),
                             ('post', '/contabilidad/api/cuentas/importar/'), ('post', '/contabilidad/api/cuentas/importar/1/confirmar/')):
            respuesta = enviar(client, ruta, {'empresa': empresa.pk, 'version': 1}, metodo)
            assert respuesta.status_code == 403 and respuesta['Content-Type'] == 'application/json', ruta
            assert respuesta.json() == {'error': 'Selecciona una empresa para continuar'}, ruta

    def test_empresa_de_otra_pestana(self, client, empresa, empresa_b, lista):
        lista(empresa)
        usuario = entrar(client, empresa)
        Membership.objects.create(user=usuario, company=empresa_b, group=Group.objects.get(name=ROLE_OWNER))
        assert client.get(f'{URL}?empresa={empresa.pk}').json()['licencia']['estado'] == 'activa'
        client.post('/empresas/cambiar/', {'company': empresa_b.pk})
        vieja = client.get(f'{URL}?empresa={empresa.pk}')   # la pestaña que quedó con la empresa A
        assert vieja.status_code == 409 and vieja.json()['codigo'] == 'empresa_cambiada' and 'licencia' not in vieja.json()
        nueva = client.get(f'{URL}?empresa={empresa_b.pk}').json()
        assert (nueva['empresa']['id'], nueva['licencia']['estado']) == (empresa_b.pk, 'complemento_pendiente')

    def test_solo_get(self, client, empresa, lista):
        lista(empresa)
        entrar(client, empresa)
        respuesta = enviar(client, URL, {'empresa': empresa.pk})
        assert respuesta.status_code == 405 and respuesta.json()['codigo'] == 'metodo' and respuesta['Allow'] == 'GET'

    def test_no_cambia_el_modulo_activo_del_menu(self, client, empresa, lista):
        """La consulta va en segundo plano desde cualquier pantalla: no puede quitarle al menú el módulo abierto."""
        lista(empresa)
        entrar(client, empresa)
        assert client.get('/contabilidad/inventario/').status_code == 200
        modulo = client.session['module_id']
        assert client.get(URL).status_code == 200 and client.session['module_id'] == modulo


# ---------------------------------------------------------------- registro de funciones

class TestFunciones:

    def test_registro(self):
        assert [f.codigo for f in capacidades.FUNCIONES] == CODIGOS
        existentes = set(Permission.objects.values_list('codename', flat=True))
        for f in capacidades.FUNCIONES:
            assert f.ambito in (TRIBUTARIO, CONTABILIDAD) and f.nombre and 'ver' in f.permisos, f.codigo
            if f.construccion == PENDIENTE:
                assert f.que_falta, f.codigo
                continue
            assert f.construccion == capacidades.DISPONIBLE and not f.que_falta and not f.decision, f.codigo
            pedidos = {c for p in f.permisos.values() for c in ([p] if isinstance(p, str) else p)}
            assert pedidos and pedidos <= existentes, f.codigo   # un codename mal escrito dejaría la función sin nadie
        assert [f.codigo for f in capacidades.FUNCIONES if f.construccion == PENDIENTE and not f.ruta] == PENDIENTES
        assert capacidades.funcion_de('importar_cuentas').requisitos == ()   # importar el plan no exige datos previos

    def test_disponible_solo_con_su_ruta_publicada(self):
        """Quien publique la ruta de una función pendiente la pasa a disponible en el registro (y al revés: nada se
        anuncia como disponible sin su ruta)."""
        def publicada(ruta):
            try:
                resolve(ruta)
            except Resolver404:
                return False
            return True
        con_ruta = [f for f in capacidades.FUNCIONES if f.ruta]
        assert len(con_ruta) >= 9
        for f in con_ruta:
            assert publicada(f.ruta) is (f.construccion == capacidades.DISPONIBLE), f.codigo

    def test_modulo_pendiente(self, client, empresa, lista):
        lista(empresa)
        entrar(client, empresa)
        funciones = client.get(URL).json()['funciones']
        for codigo in PENDIENTES:
            f = funciones[codigo]
            assert (f['estado'], f['causa'], f['acciones'], f['faltan']) == ('modulo_pendiente', 'modulo_pendiente', {'ver': False}, [])
            assert 'en construcción' in f['texto'], codigo
        # el texto dice qué falta y, si la hay, la decisión que espera
        assert funciones['asientos']['texto'] == ('Los asientos por comprobante están en construcción. La matriz de asientos está '
                                                  'por validar con un contador: una regla sin aprobar quedará como excepción, sin '
                                                  'contabilizar.')
        assert funciones['cartera_inicial']['texto'] == capacidades.funcion_de('cartera_inicial').que_falta

    def test_modulo_pendiente_va_antes_que_la_licencia_y_el_permiso(self, client, empresa):
        """Lo que no está construido no se anuncia como «te falta la licencia» ni «te falta el permiso»."""
        entrar(client, empresa, ROLE_SELLER)   # complemento cerrado y rol sin permisos contables
        funciones = client.get(URL).json()['funciones']
        assert {funciones[c]['estado'] for c in PENDIENTES} == {'modulo_pendiente'}
        assert funciones['kardex']['estado'] == 'sin_licencia'   # licencia antes que permiso

    def test_desde_un_servicio(self, empresa, lista):
        """Lo que usan las vistas y los servicios nuevos sin pasar por HTTP: una función resuelta, sus acciones o un permiso."""
        lista(empresa)
        usuario = helpers.crear_usuario('cap.servicio', empresa, ROLE_READONLY)
        peticion = SimpleNamespace(user=usuario, company=empresa, membership=Membership.objects.get(user=usuario, company=empresa))
        assert capacidades.acciones(peticion, 'kardex') == {'ver': True, 'registrar': False, 'anular': False}
        assert capacidades.estado_de(peticion, 'asientos')['estado'] == 'modulo_pendiente'
        assert capacidades.tiene(peticion, 'view_kardex') and capacidades.tiene(peticion, ('add_movimientomanual', 'view_libros'))
        assert not capacidades.tiene(peticion, 'add_movimientomanual') and not capacidades.tiene(peticion, None)
        assert capacidades.faltantes(peticion, 'kardex') == []
        with pytest.raises(KeyError):
            capacidades.funcion_de('no_existe')

    @pytest.fixture
    def de_prueba(self, monkeypatch):
        """Función de prueba con un requisito de datos (el mecanismo que usarán apertura o asientos con el plan de cuentas).
        Devuelve la lista de lo que falta, que la prueba vacía para «completar los datos», y las veces que se consultó."""
        faltan, consultas = [dato('sin_cuentas', 'Crea o importa el plan de cuentas.', '/contabilidad/cuentas/')], []

        def requisito(request):
            consultas.append(request.company.pk)
            return list(faltan)
        funcion = Funcion('de_prueba', 'Función de prueba', CONTABILIDAD, {'ver': 'view_kardex', 'guardar': 'add_movimientomanual'},
                          requisitos=(requisito,))
        monkeypatch.setattr(capacidades, 'FUNCIONES', capacidades.FUNCIONES + (funcion,))
        return faltan, consultas

    def test_datos_por_completar(self, client, empresa, lista, de_prueba):
        faltan, _ = de_prueba
        lista(empresa)
        entrar(client, empresa)
        f = client.get(URL).json()['funciones']['de_prueba']
        assert f == {'nombre': 'Función de prueba', 'ambito': 'contabilidad', 'estado': 'datos_por_completar', 'causa': 'datos',
                     'texto': capacidades.TEXTO_DATOS, 'acciones': {'ver': False, 'guardar': False},
                     'faltan': [{'codigo': 'sin_cuentas', 'texto': 'Crea o importa el plan de cuentas.', 'url': '/contabilidad/cuentas/'}],
                     'avisos': []}
        faltan.clear()   # los datos se completaron
        f = client.get(URL).json()['funciones']['de_prueba']
        assert (f['estado'], f['causa'], f['texto'], f['acciones'], f['faltan']) == (
            'disponible', None, None, {'ver': True, 'guardar': True}, [])

    def test_los_datos_van_despues_de_la_licencia_y_del_permiso(self, client, empresa, lista, de_prueba):
        """Y no se consultan para quien no puede ver la función: lo que falta no se le cuenta a quien no tiene acceso."""
        _, consultas = de_prueba
        entrar(client, empresa, ROLE_SELLER)
        assert client.get(URL).json()['funciones']['de_prueba']['estado'] == 'sin_licencia'   # complemento cerrado
        lista(empresa)
        f = client.get(URL).json()['funciones']['de_prueba']
        assert (f['estado'], f['faltan']) == ('sin_permiso', []) and consultas == []

    @con_rutas_de_prueba
    def test_rechazo_de_datos_en_una_vista(self, client, empresa, lista, de_prueba):
        faltan, _ = de_prueba
        lista(empresa)
        entrar(client, empresa)
        respuesta = client.get(DATOS)
        assert respuesta.status_code == 409
        assert respuesta.json() == {'error': capacidades.TEXTO_DATOS, 'codigo': 'datos_por_completar', 'causa': 'datos',
                                    'faltan': [{'codigo': 'sin_cuentas', 'texto': 'Crea o importa el plan de cuentas.',
                                                'url': '/contabilidad/cuentas/'}]}
        faltan.clear()
        assert client.get(DATOS).json() == {'ok': True}


# ---------------------------------------------------------------- el complemento sigue cerrado

class TestNoAbreNadaMas:

    def test_reglas(self):
        assert reglas.RUTAS_DE_CAPACIDADES == (URL,)
        assert not reglas.requiere_complemento(URL) and not reglas.requiere_plan(URL)
        # coincidencia exacta: nada que empiece igual queda abierto
        for ruta in (URL + 'cuentas/', URL.rstrip('/'), URL + '1/', '/contabilidad/api/', '/contabilidad/api/cuentas/', '/tributario/'):
            assert reglas.requiere_complemento(ruta) and reglas.requiere_plan(ruta), ruta

    def test_con_el_complemento_cerrado_solo_responde_capacidades(self, client, empresa):
        """Toda otra ruta de /tributario/ y /contabilidad/ (las de hoy y las que se añadan) sigue cerrada: las páginas
        vuelven al inicio y las API, descargas y envíos responden el 403 de siempre."""
        entrar(client, empresa)   # plan pagado, lista vacía
        assert client.get(URL).status_code == 200
        rutas = [r for r in rutas_del_complemento() if r != URL]
        assert len(rutas) >= 21 and URL in set(rutas_del_complemento())
        for ruta in rutas:
            consulta = client.get(f'{ruta}?empresa={empresa.pk}')
            if consulta.status_code == 302:
                assert consulta['Location'] == '/dashboard/', ruta
            else:
                assert cerrada(consulta), ruta
            assert cerrada(client.post(ruta, {'empresa': empresa.pk})), ruta
            assert cerrada(enviar(client, ruta, {'empresa': empresa.pk})), ruta

    def test_sin_plan_tampoco_abre_nada_mas(self, client, lista):
        gratuita = helpers.crear_empresa('GRATIS CERRADA', plan=None)
        lista(gratuita)
        entrar(client, gratuita)
        assert client.get(URL).status_code == 200
        for ruta in rutas_del_complemento():
            if ruta == URL:
                continue
            consulta = client.get(ruta)
            if consulta.status_code == 302:
                assert consulta['Location'] == '/suscripcion/', ruta
            else:
                assert consulta.status_code == 403 and consulta.json()['plan'] == 'requerido', ruta
            assert client.post(ruta, {'empresa': gratuita.pk}).json()['plan'] == 'requerido', ruta


# ---------------------------------------------------------------- 403 de PlanMiddleware: se añade, no se quita

class TestRechazosDeLicencia:

    def test_complemento_cerrado(self, client, empresa):
        entrar(client, empresa)
        respuesta = client.get(INVENTARIO)
        assert respuesta.status_code == 403
        assert respuesta.json() == {
            'error': reglas.MENSAJE_COMPLEMENTO, 'plan': 'complemento_contable', 'codigo': 'complemento_pendiente',   # lo de antes
            'causa': 'licencia', 'licencia': client.get(URL).json()['licencia']}                                     # lo añadido
        pagina = client.get('/contabilidad/inventario/')   # las páginas, como antes
        assert pagina.status_code == 302 and pagina['Location'] == '/dashboard/'

    def test_sin_plan_en_una_ruta_del_complemento(self, client, lista):
        gratuita = helpers.crear_empresa('GRATIS RECHAZO', plan=None)
        lista(gratuita)
        entrar(client, gratuita)
        respuesta = client.get(INVENTARIO)
        assert respuesta.status_code == 403
        assert respuesta.json() == {
            'error': mensaje_de_bloqueo(estado_empresa(gratuita)), 'plan': 'requerido',
            'codigo': 'plan', 'causa': 'licencia', 'licencia': client.get(URL).json()['licencia']}
        assert respuesta.json()['licencia']['estado'] == 'plan_requerido'
        pagina = client.get('/contabilidad/inventario/')
        assert pagina.status_code == 302 and pagina['Location'] == '/suscripcion/'

    def test_plan_vencido_en_un_envio(self, client, empresa, lista):
        lista(empresa)
        vencer(empresa)
        entrar(client, empresa)
        respuesta = client.post(MOVIMIENTOS, {'clave': 'capacidades-0002'})
        assert respuesta.status_code == 403
        cuerpo = respuesta.json()
        assert (cuerpo['plan'], cuerpo['codigo'], cuerpo['causa']) == ('requerido', 'plan', 'licencia') and 'venció' in cuerpo['error']
        assert (cuerpo['licencia']['estado'], cuerpo['licencia']['solo_consulta']) == ('plan_vencido', True)

    def test_fuera_del_complemento_no_se_habla_del_complemento(self, client):
        """Ventas e importación: el rechazo es del plan. Llevan la causa, pero no el estado de la licencia contable (con
        la lista vacía diría «complemento pendiente» en un rechazo que no tiene que ver con él)."""
        gratuita = helpers.crear_empresa('GRATIS VENTAS', plan=None)
        entrar(client, gratuita)
        ventas = client.post('/pos/sale/admin/', {'action': 'search', 'start_date': '', 'end_date': ''})
        assert ventas.status_code == 403
        assert ventas.json() == {'error': mensaje_de_bloqueo(estado_empresa(gratuita)), 'plan': 'requerido', 'codigo': 'plan',
                                 'causa': 'licencia'}
        plan_1000 = helpers.crear_empresa('PLAN 1000 IMPORTA', plan='plan-1000')
        usuario = helpers.crear_usuario('cap.plan1000', plan_1000, ROLE_OWNER)
        client.logout()
        helpers.iniciar_sesion(client, usuario, empresa=plan_1000)
        importacion = client.get('/importacion/api/documentos/')
        assert importacion.status_code == 403
        assert importacion.json() == {'error': reglas.MENSAJE_SOLO_ILIMITADO + ' Mejora tu plan para usarla.', 'plan': 'ilimitado',
                                      'codigo': 'plan', 'causa': 'licencia'}


# ---------------------------------------------------------------- ayudantes de API (core/contabilidad/api.py)

@con_rutas_de_prueba
class TestApi:

    @pytest.fixture
    def abierta(self, client, empresa, lista):
        lista(empresa)
        entrar(client, empresa)
        return client

    def test_sin_permiso_es_403_json_tambien_en_get(self, client, empresa, lista):
        lista(empresa)
        entrar(client, empresa, ROLE_SELLER)
        for respuesta in (client.get(ECO), client.get(f'{ECO}?empresa={empresa.pk}')):
            assert respuesta.status_code == 403 and respuesta['Content-Type'] == 'application/json'
            assert respuesta.json() == {'error': capacidades.TEXTO_SIN_PERMISO, 'codigo': 'sin_permiso', 'causa': 'permiso',
                                        'permisos': ['view_kardex']}
        respuesta = enviar(client, ECO, {'empresa': empresa.pk, 'version': 3}, 'patch')   # basta uno de los dos y no tiene ninguno
        assert respuesta.status_code == 403 and respuesta.json()['permisos'] == ['change_movimientomanual', 'view_libros']

    def test_permiso_por_metodo(self, client, empresa, lista):
        lista(empresa)
        entrar(client, empresa, ROLE_READONLY)   # ve el kardex y los libros; no registra
        assert client.get(ECO).json() == {'ok': True}
        respuesta = enviar(client, ECO, {'empresa': empresa.pk, 'clave': 'eco-0001', 'codigo': '1', 'nombre': 'Caja'})
        assert (respuesta.status_code, respuesta.json()['codigo'], respuesta.json()['permisos']) == (
            403, 'sin_permiso', ['add_movimientomanual'])
        respuesta = enviar(client, ECO, {'empresa': empresa.pk, 'version': 3}, 'patch')   # le basta `view_libros`
        assert respuesta.status_code == 200 and respuesta.json() == {'version': 3}

    def test_sin_sesion(self, client):
        for respuesta in (client.get(ECO), enviar(client, ECO, {'empresa': 1})):
            assert respuesta.status_code == 302 and respuesta['Location'].startswith('/login/')

    def test_metodo_sin_permiso_declarado_no_existe(self, abierta, empresa):
        respuesta = abierta.delete(f'{ECO}?empresa={empresa.pk}')
        assert respuesta.status_code == 405 and respuesta['Allow'] == 'GET, POST, PATCH'
        assert respuesta.json() == {'error': api.TEXTOS['metodo'], 'codigo': 'metodo'}

    def test_empresa_en_la_consulta(self, abierta, empresa, empresa_b):
        assert abierta.get(ECO).status_code == 200   # en una consulta es opcional
        assert abierta.get(f'{ECO}?empresa={empresa.pk}').status_code == 200
        respuesta = abierta.get(f'{ECO}?empresa={empresa_b.pk}')
        assert respuesta.status_code == 409 and respuesta.json()['codigo'] == 'empresa_cambiada'

    def test_empresa_en_un_envio_json(self, abierta, empresa, empresa_b):
        datos = {'clave': 'eco-0002', 'codigo': '1.1', 'nombre': 'Caja'}
        sin = enviar(abierta, ECO, datos)
        assert sin.status_code == 409 and sin.json() == {'error': api.SIN_EMPRESA, 'codigo': 'sin_empresa'}   # en un envío es obligatoria
        otra = enviar(abierta, ECO, {**datos, 'empresa': empresa_b.pk})
        assert otra.status_code == 409 and otra.json()['codigo'] == 'empresa_cambiada'
        for valor in (empresa.pk, str(empresa.pk), f' {empresa.pk} '):
            assert enviar(abierta, ECO, {**datos, 'empresa': valor}).json() == {'clave': 'eco-0002', 'codigo': '1.1'}
        assert enviar(abierta, f'{ECO}?empresa={empresa.pk}', datos).status_code == 201   # o en la consulta
        # basta que una de las dos nombre otra empresa
        assert enviar(abierta, f'{ECO}?empresa={empresa.pk}', {**datos, 'empresa': empresa_b.pk}).json()['codigo'] == 'empresa_cambiada'
        assert enviar(abierta, f'{ECO}?empresa={empresa_b.pk}', {**datos, 'empresa': empresa.pk}).json()['codigo'] == 'empresa_cambiada'

    def test_empresa_en_un_formulario_y_en_patch(self, abierta, empresa, empresa_b):
        datos = {'clave': 'eco-0003', 'codigo': '1.2', 'nombre': 'Banco'}
        assert abierta.post(ECO, datos).json()['codigo'] == 'sin_empresa'   # multipart, como la subida de un archivo
        assert abierta.post(ECO, {**datos, 'empresa': empresa_b.pk}).json()['codigo'] == 'empresa_cambiada'
        assert abierta.post(ECO, {**datos, 'empresa': empresa.pk}).status_code == 201
        assert enviar(abierta, ECO, {'version': 2}, 'patch').json()['codigo'] == 'sin_empresa'
        assert enviar(abierta, ECO, {'version': 2, 'empresa': empresa_b.pk}, 'patch').json()['codigo'] == 'empresa_cambiada'
        assert enviar(abierta, ECO, {'version': 2, 'empresa': empresa.pk}, 'patch').json() == {'version': 2}

    def test_la_empresa_va_antes_que_el_permiso_y_el_permiso_antes_que_los_datos(self, client, empresa, empresa_b, lista):
        lista(empresa)
        entrar(client, empresa, ROLE_READONLY)   # no puede enviar
        assert enviar(client, ECO, {'empresa': empresa_b.pk}).json()['codigo'] == 'empresa_cambiada'
        assert enviar(client, ECO, {}).json()['codigo'] == 'sin_empresa'
        assert enviar(client, ECO, {'empresa': empresa.pk}).json()['codigo'] == 'sin_permiso'   # y no «falta la clave»

    def test_clave(self, abierta, empresa):
        for clave in (None, '', 'corta', 'con espacios 1', 'x' * 41):
            respuesta = enviar(abierta, ECO, {'empresa': empresa.pk, 'clave': clave, 'codigo': '1', 'nombre': 'Caja'})
            assert respuesta.status_code == 400, clave
            assert respuesta.json() == {'error': api.TEXTOS['clave'], 'codigo': 'clave', 'errores': {'clave': [api.TEXTOS['clave']]}}
        for clave in ('abcd-123', 'A_b-9' * 8):
            assert enviar(abierta, ECO, {'empresa': empresa.pk, 'clave': clave, 'codigo': '1', 'nombre': 'Caja'}).status_code == 201

    def test_todos_los_errores_de_campo_a_la_vez(self, abierta, empresa):
        respuesta = enviar(abierta, ECO, {'empresa': empresa.pk, 'clave': 'eco-0004', 'nombre': 'Demasiado'})
        assert respuesta.status_code == 400
        assert respuesta.json() == {'error': api.TEXTOS['validacion'], 'codigo': 'validacion',
                                    'errores': {'codigo': ['Escribe el código.'],
                                                'nombre': ['Nombre demasiado largo.', 'Usa hasta 5 caracteres.']}}

    def test_cuerpo_ilegible(self, abierta, empresa):
        for cuerpo in ('{no es json', '[1, 2]', '"texto"', 'null', '[' * 100000):   # mal formado, no es un objeto o no se puede leer
            respuesta = abierta.post(f'{ECO}?empresa={empresa.pk}', cuerpo, content_type='application/json')
            assert respuesta.status_code == 400 and respuesta.json() == {'error': api.TEXTOS['cuerpo'], 'codigo': 'cuerpo'}, cuerpo[:20]
        # sin la empresa en la consulta no hay de dónde leerla
        assert abierta.post(ECO, '{no es json', content_type='application/json').json()['codigo'] == 'sin_empresa'

    def test_error_de_un_servicio_y_permiso_de_un_solo_envio(self, client, empresa, lista):
        lista(empresa)
        grupo = helpers.crear_grupo('Registra sin anular', ['view_kardex', 'add_movimientomanual'])
        helpers.iniciar_sesion(client, helpers.crear_usuario('cap.sin.anular', empresa, grupo), empresa=empresa)
        datos = {'empresa': empresa.pk, 'clave': 'eco-0005', 'nombre': 'Caja'}
        usada = enviar(client, ECO, {**datos, 'codigo': 'usada'})
        assert usada.status_code == 409
        assert usada.json() == {'error': 'Esta clave ya se usó para otra cuenta.', 'codigo': 'clave_usada', 'cuenta': {'id': 7}}
        editar = enviar(client, ECO, {**datos, 'codigo': 'editar'})
        assert editar.status_code == 403
        assert editar.json() == {'error': capacidades.TEXTO_SIN_PERMISO, 'codigo': 'sin_permiso', 'causa': 'permiso',
                                 'permisos': ['change_movimientomanual']}
        assert enviar(client, ECO, {**datos, 'codigo': '1.1'}).status_code == 201

    def test_complemento_cerrado(self, client, empresa, empresa_b):
        """Licencia: la corta el middleware antes de la vista. Un envío JSON armado para otra empresa recibe primero el
        409 (que recargue); el que no nombra empresa recibe el 403, porque el middleware no sabe qué rutas la exigen."""
        entrar(client, empresa)
        datos = {'clave': 'eco-0006', 'codigo': '1', 'nombre': 'Caja'}
        assert cerrada(client.get(ECO))
        assert cerrada(enviar(client, ECO, {**datos, 'empresa': empresa.pk}))
        assert cerrada(enviar(client, ECO, {'version': 1, 'empresa': empresa.pk}, 'patch'))
        for metodo in ('post', 'patch'):
            otra = enviar(client, ECO, {**datos, 'empresa': empresa_b.pk}, metodo)
            assert otra.status_code == 409 and otra.json()['codigo'] == 'empresa_cambiada', metodo
        assert cerrada(enviar(client, ECO, datos))

    def test_plan_vencido_consulta_si_envios_no(self, client, empresa, empresa_b, lista):
        lista(empresa)
        vencer(empresa)
        entrar(client, empresa)
        assert client.get(f'{ECO}?empresa={empresa.pk}').json() == {'ok': True}
        for metodo, datos in (('post', {'clave': 'eco-0007', 'codigo': '1', 'nombre': 'Caja'}), ('patch', {'version': 1})):
            respuesta = enviar(client, ECO, {**datos, 'empresa': empresa.pk}, metodo)
            assert respuesta.status_code == 403, metodo
            assert (respuesta.json()['codigo'], respuesta.json()['causa'], respuesta.json()['licencia']['estado']) == (
                'plan', 'licencia', 'plan_vencido')
            assert enviar(client, ECO, {**datos, 'empresa': empresa_b.pk}, metodo).json()['codigo'] == 'empresa_cambiada'

    @pytest.mark.parametrize('accion', ['search', 'search_x', 'send_invoice_by_email'])
    def test_plan_vencido_tampoco_pasa_un_formulario_con_action_de_consulta(self, client, empresa, empresa_b, lista, accion):
        """PlanMiddleware toma por consulta un formulario con ese `action` (así buscan por POST las pantallas de ventas) y
        lo deja pasar con el plan vencido. Estas rutas no consultan por POST: la vista base responde el mismo 403, cuerpo
        incluido, que el middleware le da al envío sin `action`."""
        lista(empresa)
        entrar(client, empresa)
        datos = {'empresa': empresa.pk, 'clave': 'eco-0008', 'codigo': '1', 'nombre': 'Caja'}
        assert client.post(ECO, {**datos, 'action': accion}).status_code == 201   # con el plan vigente ese formulario vale
        vencer(empresa)
        del_middleware = client.post(ECO, datos)
        assert del_middleware.status_code == 403 and del_middleware.json()['codigo'] == 'plan'
        for respuesta in (client.post(ECO, {**datos, 'action': accion}),
                          client.post(f'{ECO}?empresa={empresa.pk}', {'clave': 'eco-0008', 'action': accion})):
            assert respuesta.status_code == 403 and respuesta.json() == del_middleware.json()
        # la empresa de la pestaña sigue yendo antes que la licencia
        assert client.post(ECO, {**datos, 'empresa': empresa_b.pk, 'action': accion}).json()['codigo'] == 'empresa_cambiada'
        assert client.post(ECO, {'clave': 'eco-0008', 'action': accion}).json()['codigo'] == 'sin_empresa'
        assert client.get(f'{ECO}?empresa={empresa.pk}&action={accion}').json() == {'ok': True}   # y se sigue consultando

    def test_plan_vencido_con_action_de_consulta_la_licencia_va_antes_que_el_permiso(self, client, empresa, lista):
        lista(empresa)
        vencer(empresa)
        entrar(client, empresa, ROLE_READONLY)   # no puede enviar: con el plan vigente recibiría `sin_permiso`
        respuesta = client.post(ECO, {'empresa': empresa.pk, 'clave': 'eco-0009', 'codigo': '1', 'nombre': 'Caja', 'action': 'search'})
        assert respuesta.status_code == 403
        assert (respuesta.json()['codigo'], respuesta.json()['causa'], respuesta.json()['licencia']['estado']) == (
            'plan', 'licencia', 'plan_vencido')
