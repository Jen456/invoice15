"""Plan de cuentas por empresa (C2 del contrato contable v9): core/contabilidad/cuentas.py y vistas_cuentas.py.

GET y POST /contabilidad/api/cuentas/ y PATCH /contabilidad/api/cuentas/<id>/: quién ve, crea y edita (y su reparto exacto
por rol, sin página nueva); toda negativa en JSON; empresa de la pestaña; alta idempotente con `clave`; `version`; código
único sin distinguir mayúsculas; árbol (padre grupo, ciclos, hijas); búsqueda con antepasadas sin consultas por fila; dos
empresas aisladas; complemento cerrado y plan vencido; auditoría; seguridad por filas (PostgreSQL) y la migración que
reparte los permisos, de ida y de vuelta. La concurrencia real va en tests/test_zz_cuentas_concurrencia_pg.py."""
import importlib
import json
from datetime import timedelta
from itertools import count
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from django.apps import apps as registro
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.contabilidad import api, capacidades, cuentas
from core.contabilidad.models import Cuenta, ImportacionCuentas
from core.security.models import Module
from core.tenancy import pestanas
from core.tenancy.context import company_context
from core.tenancy.models import (ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog,
                                 Membership)
from tests import helpers

pytestmark = pytest.mark.django_db

API = '/contabilidad/api/cuentas/'
T = cuentas.TEXTOS
DEL_KARDEX = {'view_kardex', 'add_movimientomanual', 'change_movimientomanual'}
DEL_PLAN = {'view_cuenta', 'add_cuenta', 'change_cuenta'}
_claves = count(1)


# ---------------------------------------------------------------- ayudas

def en(empresa, funcion):
    with company_context(empresa):
        return funcion()


def enviar(client, url, datos, metodo='post'):
    return getattr(client, metodo)(url, json.dumps(datos), content_type='application/json')


def alta(client, empresa, codigo, nombre=None, tipo='movimiento', padre=None, **extra):
    """POST de una cuenta con una clave nueva; devuelve la respuesta."""
    datos = {'empresa': empresa.pk, 'clave': f'alta-cuenta-{next(_claves):05d}', 'codigo': codigo,
             'nombre': f'Cuenta {codigo}' if nombre is None else nombre, 'tipo': tipo, 'padre_id': padre}
    datos.update(extra)
    return enviar(client, API, datos)


def nueva(client, empresa, codigo, nombre=None, tipo='movimiento', padre=None):
    respuesta = alta(client, empresa, codigo, nombre, tipo, padre['id'] if padre else None)
    assert respuesta.status_code == 201, respuesta.content
    return respuesta.json()['cuenta']


def cambiar(client, empresa, cuenta, **cambios):
    """PATCH con la versión que trae `cuenta` (el diccionario que devolvió la API)."""
    return enviar(client, f'{API}{cuenta["id"]}/', {'empresa': empresa.pk, 'version': cuenta['version'], **cambios}, 'patch')


def errores_de(respuesta):
    assert respuesta.status_code == 400 and respuesta.json()['codigo'] == 'validacion', respuesta.content
    return respuesta.json()['errores']


def guardada(empresa, pk):
    return en(empresa, lambda: Cuenta.objects.get(pk=pk))


def cuantas(empresa):
    return en(empresa, Cuenta.objects.count)


def sembrar(empresa, codigo, nombre=None, tipo='movimiento', padre=None, **extra):
    """Una cuenta guardada sin pasar por la API (como las que deja la importación: sin clave)."""
    return en(empresa, lambda: Cuenta.objects.create(codigo=codigo, nombre=nombre or f'Cuenta {codigo}', tipo=tipo, padre=padre,
                                                    **extra))


def lista(client, consulta=''):
    respuesta = client.get(f'{API}{consulta}')
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()


def codigos(client, consulta=''):
    return [c['codigo'] for c in lista(client, consulta)['cuentas']]


def vencer(empresa):
    from core.suscripciones.models import SubscriptionPeriod
    SubscriptionPeriod.objects.filter(company=empresa).update(ends_at=timezone.now() - timedelta(days=1))


@pytest.fixture
def entrar(client, empresa, admin):
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    return client


@pytest.fixture
def arbol(entrar, empresa):
    """1 Activo ▸ 1.1 Activo corriente ▸ (1.1.01 Caja, 1.1.02 Bancos); 1 ▸ 1.2 Activo no corriente; 2 Pasivo."""
    c = {}
    c['1'] = nueva(entrar, empresa, '1', 'Activo', 'grupo')
    c['1.1'] = nueva(entrar, empresa, '1.1', 'Activo corriente', 'grupo', c['1'])
    c['1.1.01'] = nueva(entrar, empresa, '1.1.01', 'Caja', 'movimiento', c['1.1'])
    c['1.1.02'] = nueva(entrar, empresa, '1.1.02', 'Bancos', 'movimiento', c['1.1'])
    c['1.2'] = nueva(entrar, empresa, '1.2', 'Activo no corriente', 'grupo', c['1'])
    c['2'] = nueva(entrar, empresa, '2', 'Pasivo', 'grupo')
    return c


# ---------------------------------------------------------------- permisos

ROLES = [(ROLE_OWNER, True, True), (ROLE_ADMIN, True, True), (ROLE_ACCOUNTANT, True, True), (ROLE_READONLY, True, False),
         (ROLE_SELLER, False, False), (ROLE_CLIENT, False, False)]


def sin_permiso(respuesta, codename):
    """403 en JSON (también en GET, donde las pantallas redirigen) con la causa y el permiso que faltó."""
    return respuesta.status_code == 403 and respuesta['Content-Type'] == 'application/json' and respuesta.json() == {
        'error': capacidades.TEXTO_SIN_PERMISO, 'codigo': 'sin_permiso', 'causa': 'permiso', 'permisos': [codename]}


class TestPermisos:

    @pytest.mark.parametrize('rol, ve, escribe', ROLES)
    def test_ver_crear_y_editar_por_rol(self, client, empresa, rol, ve, escribe):
        existente = sembrar(empresa, '1', 'Activo', 'grupo')
        helpers.iniciar_sesion(client, helpers.crear_usuario(f'cuentas.{rol.lower()}', empresa, rol), empresa=empresa)
        consulta = client.get(f'{API}?empresa={empresa.pk}')
        if ve:
            assert consulta.status_code == 200 and [c['codigo'] for c in consulta.json()['cuentas']] == ['1']
            assert consulta.json()['capacidades'] == {'crear': escribe, 'editar': escribe, 'importar': escribe}
        else:
            assert sin_permiso(consulta, 'view_cuenta') and sin_permiso(client.get(API), 'view_cuenta')
        creada = alta(client, empresa, '2', 'Pasivo', 'grupo')
        editada = enviar(client, f'{API}{existente.pk}/', {'empresa': empresa.pk, 'version': 1, 'nombre': 'Activos'}, 'patch')
        if escribe:
            assert creada.status_code == 201 and editada.status_code == 200
            assert cuantas(empresa) == 2 and guardada(empresa, existente.pk).nombre == 'Activos'
        else:
            assert sin_permiso(creada, 'add_cuenta') and sin_permiso(editada, 'change_cuenta')
            assert cuantas(empresa) == 1 and guardada(empresa, existente.pk).version == 1

    @pytest.mark.parametrize('rol, ve, escribe', ROLES[:5])   # el rol Cliente no consulta las capacidades (403)
    def test_el_contrato_de_capacidades_anuncia_lo_mismo(self, client, empresa, rol, ve, escribe):
        helpers.iniciar_sesion(client, helpers.crear_usuario(f'cuentas.cap.{rol.lower()}', empresa, rol), empresa=empresa)
        funcion = client.get('/contabilidad/api/capacidades/').json()['funciones']['plan_cuentas']
        assert funcion['estado'] == ('disponible' if ve else 'sin_permiso') and funcion['nombre'] == 'Plan de cuentas'
        assert funcion['acciones'] == {'ver': ve, 'crear': escribe, 'editar': escribe}

    def test_reparto_exacto_por_rol_sin_modulo_nuevo(self):
        """Los tres permisos viajan con el módulo del kardex: ningún módulo ni entrada de menú nuevos."""
        kardex = Module.objects.get(url='/contabilidad/kardex/')
        assert set(kardex.permissions.values_list('codename', flat=True)) == DEL_KARDEX | DEL_PLAN
        assert set(Module.objects.filter(url__startswith='/contabilidad/').values_list('url', flat=True)) == {
            '/contabilidad/kardex/', '/contabilidad/inventario/'}
        assert list(Module.objects.filter(permissions__codename__in=DEL_PLAN).distinct()) == [kardex]

        def del_plan(rol):
            return set(Group.objects.get(name=rol).permissions.filter(content_type__app_label='contabilidad',
                                                                     content_type__model='cuenta').values_list('codename', flat=True))
        assert del_plan(ROLE_OWNER) == del_plan(ROLE_ADMIN) == del_plan(ROLE_ACCOUNTANT) == DEL_PLAN
        assert del_plan(ROLE_READONLY) == {'view_cuenta'}
        assert del_plan(ROLE_SELLER) == del_plan(ROLE_CLIENT) == set()

    def test_el_servicio_tambien_exige_el_permiso(self, empresa):
        """Quien llame al servicio sin pasar por la vista (otra vista, una importación) tampoco escribe sin permiso."""
        usuario = helpers.crear_usuario('cuentas.servicio', empresa, ROLE_READONLY)
        peticion = SimpleNamespace(user=usuario, company=empresa, membership=Membership.objects.get(user=usuario, company=empresa),
                                   META={}, method='POST')
        existente = sembrar(empresa, '1', 'Activo', 'grupo')
        with company_context(empresa):
            for intento in (lambda: cuentas.crear(peticion, {'clave': 'servicio-0001', 'codigo': '2', 'nombre': 'Pasivo', 'tipo': 'grupo'}),
                            lambda: cuentas.modificar(peticion, existente.pk, {'version': 1, 'nombre': 'Activos'})):
                with pytest.raises(api.Rechazo) as rechazo:
                    intento()
                assert rechazo.value.estado == 403
        assert cuantas(empresa) == 1 and guardada(empresa, existente.pk).nombre == 'Activo'

    def test_sin_sesion(self, client, empresa):
        for respuesta in (client.get(API), alta(client, empresa, '1'), enviar(client, f'{API}1/', {'version': 1}, 'patch')):
            assert respuesta.status_code == 302 and respuesta['Location'].startswith('/login/')

    def test_no_se_borra_ni_hay_otros_metodos(self, entrar, empresa, arbol):
        caja = arbol['1.1.01']
        borrar = entrar.delete(f'{API}{caja["id"]}/?empresa={empresa.pk}')
        assert borrar.status_code == 405 and borrar.json()['codigo'] == 'metodo' and borrar['Allow'] == 'PATCH'
        assert entrar.get(f'{API}{caja["id"]}/').status_code == 405
        assert entrar.delete(f'{API}?empresa={empresa.pk}').status_code == 405
        assert cuantas(empresa) == 6


# ---------------------------------------------------------------- empresa de la pestaña

class TestEmpresaDeLaPestana:

    def test_envios_sin_empresa_o_para_otra(self, entrar, empresa, empresa_b):
        caja = nueva(entrar, empresa, '1.1.01', 'Caja')
        datos = {'clave': 'pestana-cuenta-01', 'codigo': '2', 'nombre': 'Pasivo', 'tipo': 'grupo'}
        sin = enviar(entrar, API, datos)
        assert sin.status_code == 409 and sin.json() == {'error': api.SIN_EMPRESA, 'codigo': 'sin_empresa'}
        otra = enviar(entrar, API, {**datos, 'empresa': empresa_b.pk})
        assert otra.status_code == 409 and otra.json() == {'error': pestanas.EMPRESA_CAMBIADA, 'codigo': 'empresa_cambiada'}
        cambio = {'version': 1, 'nombre': 'Caja general'}
        assert enviar(entrar, f'{API}{caja["id"]}/', cambio, 'patch').json()['codigo'] == 'sin_empresa'
        assert enviar(entrar, f'{API}{caja["id"]}/', {**cambio, 'empresa': empresa_b.pk}, 'patch').json()['codigo'] == 'empresa_cambiada'
        assert cuantas(empresa) == 1 and guardada(empresa, caja['id']).nombre == 'Caja'   # nada se creó ni cambió
        assert enviar(entrar, f'{API}?empresa={empresa.pk}', datos).status_code == 201   # también vale en la consulta

    def test_consulta_de_una_pestana_que_quedo_con_otra_empresa(self, entrar, empresa, empresa_b, admin):
        Membership.objects.create(user=admin, company=empresa_b, group=Group.objects.get(name=ROLE_OWNER))
        nueva(entrar, empresa, '1', 'Activo', 'grupo')
        assert codigos(entrar, f'?empresa={empresa.pk}') == ['1']
        entrar.post('/empresas/cambiar/', {'company': empresa_b.pk})
        vieja = entrar.get(f'{API}?empresa={empresa.pk}')
        assert vieja.status_code == 409 and vieja.json()['codigo'] == 'empresa_cambiada' and 'cuentas' not in vieja.json()
        assert codigos(entrar) == []   # sin `empresa` responde la activa, que no tiene cuentas


# ---------------------------------------------------------------- alta

class TestAlta:

    def test_alta(self, entrar, empresa, admin):
        grupo = alta(entrar, empresa, '1', 'Activo', 'grupo')
        assert grupo.status_code == 201
        raiz = grupo.json()['cuenta']
        assert grupo.json() == {'cuenta': {'id': raiz['id'], 'codigo': '1', 'nombre': 'Activo', 'padre_id': None, 'tipo': 'grupo',
                                           'activa': True, 'hijas': 0, 'version': 1}, 'repetido': False}
        hija = alta(entrar, empresa, '  1.1.01 ', '  Caja   general ', 'movimiento', raiz['id'], clave='alta-con-espacios')
        assert hija.status_code == 201
        assert (hija.json()['cuenta']['codigo'], hija.json()['cuenta']['nombre'], hija.json()['cuenta']['padre_id']) == (
            '1.1.01', 'Caja general', raiz['id'])   # sin espacios sobrantes
        fila = guardada(empresa, hija.json()['cuenta']['id'])
        assert (fila.company_id, fila.clave, fila.codigo_norm, fila.version, fila.activa) == (empresa.pk, 'alta-con-espacios', '1.1.01', 1, True)
        assert fila.creada_por == admin and fila.actualizada_por == admin
        assert lista(entrar)['cuentas'][0]['hijas'] == 1

    def test_idempotencia(self, entrar, empresa):
        datos = {'empresa': empresa.pk, 'clave': 'cuenta-repetida-1', 'codigo': '1.1.01', 'nombre': 'Caja', 'tipo': 'movimiento',
                 'padre_id': None}
        creada = enviar(entrar, API, datos)
        assert creada.status_code == 201 and creada.json()['repetido'] is False
        otra_vez = enviar(entrar, API, {**datos, 'codigo': ' 1.1.01 ', 'nombre': 'Caja '})   # el mismo contenido, tal como se guarda
        assert otra_vez.status_code == 200 and otra_vez.json() == {'cuenta': creada.json()['cuenta'], 'repetido': True}
        for otro_contenido in ({'nombre': 'Bancos'}, {'codigo': '1.1.02'}, {'tipo': 'grupo'}, {'codigo': '1.1.01A'}, {'nombre': ''}):
            usada = enviar(entrar, API, {**datos, **otro_contenido})
            assert usada.status_code == 409, otro_contenido
            assert usada.json() == {'error': T['clave_usada'], 'codigo': 'clave_usada', 'cuenta': creada.json()['cuenta']}
        assert cuantas(empresa) == 1
        assert AuditLog.objects.filter(action='cuenta_creada', company=empresa).count() == 1   # el repetido no deja otro registro

    def test_repetir_el_alta_de_una_cuenta_que_ya_cambio(self, entrar, empresa):
        """Se compara con la cuenta como está ahora: tras un cambio, el envío repetido recibe 409 con la cuenta actual
        (nunca una segunda cuenta ni un «repetido» que no coincide con lo enviado)."""
        datos = {'empresa': empresa.pk, 'clave': 'cuenta-cambiada-1', 'codigo': '1.1.01', 'nombre': 'Caja', 'tipo': 'movimiento'}
        creada = enviar(entrar, API, datos).json()['cuenta']
        actual = cambiar(entrar, empresa, creada, nombre='Caja general').json()['cuenta']
        repetida = enviar(entrar, API, datos)
        assert (repetida.status_code, repetida.json()['codigo'], repetida.json()['cuenta']) == (409, 'clave_usada', actual)
        assert cuantas(empresa) == 1

    @pytest.mark.parametrize('nombre, estado, repetido', [('Caja', 200, True), ('Bancos', 409, None)])
    def test_el_envio_repetido_que_se_cruza_con_el_primero(self, entrar, empresa, monkeypatch, nombre, estado, repetido):
        """Quien escriba el plan sin esperar en la cola por empresa puede guardar un envío entre que su repetición busca
        la clave (todavía nada) y busca el código (ya está). Ese «ya existe» sería su propia cuenta: la repetición recibe
        lo de siempre, la cuenta con `repetido` o, si traía otro contenido, 409 `clave_usada`. Aquí el cruce se simula;
        el de verdad, con dos conexiones, está en tests/test_zz_cuentas_concurrencia_pg.py."""
        datos = {'empresa': empresa.pk, 'clave': 'cuenta-cruzada-01', 'codigo': '1.1.01', 'nombre': nombre, 'tipo': 'movimiento'}
        buscar_el_codigo = cuentas._codigo_repetido

        def el_primero_se_guarda_justo_antes(codigo, errores):
            if not Cuenta.objects.filter(clave='cuenta-cruzada-01').exists():   # la lectura por clave no la encontró
                Cuenta.objects.create(clave='cuenta-cruzada-01', codigo='1.1.01', nombre='Caja', tipo='movimiento')
            return buscar_el_codigo(codigo, errores)
        monkeypatch.setattr(cuentas, '_codigo_repetido', el_primero_se_guarda_justo_antes)
        respuesta = enviar(entrar, API, datos)
        assert respuesta.status_code == estado, respuesta.content
        cuerpo = respuesta.json()
        assert (cuerpo['cuenta']['codigo'], cuerpo['cuenta']['nombre'], cuerpo['cuenta']['version']) == ('1.1.01', 'Caja', 1)
        assert cuerpo.get('repetido') is repetido and cuerpo.get('codigo') == (None if repetido else 'clave_usada')
        # el mismo código con otra clave sigue siendo «ya existe»
        otra = enviar(entrar, API, {**datos, 'clave': 'cuenta-cruzada-02'})
        assert errores_de(otra) == {'codigo': [T['codigo_repetido'].format(codigo='1.1.01')]}
        # Ninguno de estos envíos creó nada. (El cruce simulado ocurre dentro de la transacción del envío: cuando este
        # termina en un rechazo se deshace con él, así que aquí no se cuentan las cuentas.)
        assert not AuditLog.objects.filter(action='cuenta_creada').exists()

    def test_formulario(self, entrar, empresa):
        """El alta admite también un formulario (multipart), como la subida del archivo de importación."""
        datos = {'empresa': empresa.pk, 'clave': 'cuenta-formulario', 'codigo': '3', 'nombre': 'Patrimonio', 'tipo': 'grupo'}
        assert entrar.post(API, datos).status_code == 201
        hija = entrar.post(API, {**datos, 'clave': 'cuenta-formulario-2', 'codigo': '3.1', 'padre_id': str(codigos_a_id(empresa)['3'])})
        assert hija.status_code == 201 and hija.json()['cuenta']['padre_id'] == codigos_a_id(empresa)['3']
        assert entrar.post(API, datos).json()['repetido'] is True

    @pytest.mark.parametrize('clave', [None, '', 'corta', 'con espacios 12', 'x' * 41])
    def test_clave_obligatoria(self, entrar, empresa, clave):
        respuesta = alta(entrar, empresa, '1', 'Activo', 'grupo', clave=clave)
        assert respuesta.status_code == 400 and respuesta.json()['codigo'] == 'clave' and cuantas(empresa) == 0

    def test_todos_los_errores_de_campo_a_la_vez(self, entrar, empresa):
        vacia = alta(entrar, empresa, '', ' ', 'otro', 'abc')
        assert vacia.json()['error'] == api.TEXTOS['validacion']
        assert errores_de(vacia) == {'codigo': [T['codigo']], 'nombre': [T['nombre']], 'tipo': [T['tipo']], 'padre_id': [T['padre']]}
        sin_campos = enviar(entrar, API, {'empresa': empresa.pk, 'clave': 'sin-campos-01'})
        assert errores_de(sin_campos) == {'codigo': [T['codigo']], 'nombre': [T['nombre']], 'tipo': [T['tipo']]}   # sin padre: raíz
        nueva(entrar, empresa, '1.1.01', 'Caja')
        # los que salen de la base (código repetido, padre inexistente) llegan junto con los de forma
        varios = alta(entrar, empresa, '1.1.01', '', 'movimiento', 999999)
        assert errores_de(varios) == {'codigo': [T['codigo_repetido'].format(codigo='1.1.01')], 'nombre': [T['nombre']],
                                      'padre_id': [T['padre']]}
        assert cuantas(empresa) == 1

    @pytest.mark.parametrize('campo, valor, texto', [
        ('codigo', 'x' * 31, 'codigo_largo'), ('codigo', '1.1​.01', 'codigo_caracteres'), ('codigo', '1\x00', 'codigo_caracteres'),
        ('codigo', 1.10, 'codigo'), ('codigo', ['1'], 'codigo'), ('codigo', True, 'codigo'),
        ('nombre', 'n' * 201, 'nombre_largo'), ('nombre', 'Caja\x00', 'nombre_caracteres'), ('nombre', {'a': 1}, 'nombre'),
        ('tipo', 'GRUPO', 'tipo'), ('tipo', None, 'tipo'), ('tipo', 1, 'tipo'),
        ('padre_id', True, 'padre'), ('padre_id', -1, 'padre'), ('padre_id', 1.5, 'padre'), ('padre_id', 10 ** 30, 'padre'),
        ('padre_id', '9' * 40, 'padre'), ('padre_id', [1], 'padre'),
    ])
    def test_valores_que_no_se_aceptan(self, entrar, empresa, campo, valor, texto):
        datos = {'codigo': '1', 'nombre': 'Activo', 'tipo': 'grupo', 'padre': None}
        datos['padre' if campo == 'padre_id' else campo] = valor
        respuesta = alta(entrar, empresa, datos['codigo'], datos['nombre'], datos['tipo'], datos['padre'])
        assert errores_de(respuesta) == {campo: [T[texto]]} and cuantas(empresa) == 0

    def test_limites_que_si_caben(self, entrar, empresa):
        larga = alta(entrar, empresa, 'x' * 30, 'n' * 200, 'grupo')
        assert larga.status_code == 201
        numero = alta(entrar, empresa, 1101, 'Caja')   # un entero vale como código: no pierde nada al pasar a texto
        assert numero.status_code == 201 and numero.json()['cuenta']['codigo'] == '1101'
        # «ß» se compara como «ss»: la forma con la que se compara es más larga que el código y también cabe
        assert alta(entrar, empresa, 'ß' * 30, 'Eszett', 'grupo').status_code == 201
        assert alta(entrar, empresa, 'Straße', 'Calle').status_code == 201
        assert errores_de(alta(entrar, empresa, 'STRASSE', 'Otra calle')) == {'codigo': ['Ya existe la cuenta Straße en esta empresa.']}

    def test_codigo_unico_sin_distinguir_mayusculas(self, entrar, empresa):
        nueva(entrar, empresa, '1.1.01a', 'Caja')
        for repetido in ('1.1.01a', '1.1.01A', '  1.1.01A  '):
            respuesta = alta(entrar, empresa, repetido, 'Otra caja')
            assert errores_de(respuesta) == {'codigo': ['Ya existe la cuenta 1.1.01a en esta empresa.']}, repetido
        assert alta(entrar, empresa, '1.1.01b', 'Bancos').status_code == 201
        assert cuantas(empresa) == 2

    def test_la_base_tampoco_admite_el_codigo_repetido_ni_la_clave(self, empresa):
        """La garantía final es de la base: vale también para quien inserte sin pasar por el servicio."""
        sembrar(empresa, 'Caja-1', clave='clave-unica-0001')
        rechazadas = ({'codigo': 'CAJA-1'}, {'codigo': 'Caja-2', 'clave': 'clave-unica-0001'}, {'codigo': 'Caja-3', 'tipo': 'otro'})
        with company_context(empresa):
            for datos in rechazadas:
                # El punto de guardado se deshace antes de salir del contexto de la empresa (en PostgreSQL, salir consulta la base).
                with pytest.raises(IntegrityError), transaction.atomic():
                    Cuenta.objects.create(**{'nombre': 'No entra', 'tipo': 'movimiento', **datos})
        sembrar(empresa, 'Caja-4')
        sembrar(empresa, 'Caja-5')   # varias sin clave (las importadas) conviven
        assert cuantas(empresa) == 3


def codigos_a_id(empresa):
    return en(empresa, lambda: dict(Cuenta.objects.values_list('codigo', 'pk')))


# ---------------------------------------------------------------- árbol

class TestArbol:

    def test_el_padre_es_un_grupo_de_la_empresa(self, entrar, empresa, arbol):
        caja = arbol['1.1.01']
        assert errores_de(alta(entrar, empresa, '1.1.01.1', 'Caja chica', 'movimiento', caja['id'])) == {'padre_id': [T['padre']]}
        assert errores_de(alta(entrar, empresa, '9', 'Sin padre', 'grupo', 999999)) == {'padre_id': [T['padre']]}
        assert errores_de(cambiar(entrar, empresa, arbol['1.1.02'], padre_id=caja['id'])) == {'padre_id': [T['padre']]}
        assert errores_de(cambiar(entrar, empresa, arbol['1.1.02'], padre_id=999999)) == {'padre_id': [T['padre']]}
        assert cuantas(empresa) == 6 and guardada(empresa, arbol['1.1.02']['id']).version == 1

    def test_mover_a_otro_grupo_y_a_la_raiz(self, entrar, empresa, arbol):
        movida = cambiar(entrar, empresa, arbol['1.1.02'], padre_id=arbol['1.2']['id'])
        assert movida.status_code == 200 and movida.json()['cuenta']['padre_id'] == arbol['1.2']['id']
        assert movida.json()['cuenta']['version'] == 2
        a_la_raiz = cambiar(entrar, empresa, arbol['1.2'], padre_id=None)
        assert a_la_raiz.status_code == 200 and a_la_raiz.json()['cuenta']['padre_id'] is None
        assert a_la_raiz.json()['cuenta']['hijas'] == 1
        por_codigo = {c['codigo']: c for c in lista(entrar)['cuentas']}
        assert (por_codigo['1']['hijas'], por_codigo['1.1']['hijas'], por_codigo['1.2']['hijas']) == (1, 1, 1)

    def test_sin_ciclos(self, entrar, empresa, arbol):
        directo = cambiar(entrar, empresa, arbol['1'], padre_id=arbol['1']['id'])           # de sí misma
        hija = cambiar(entrar, empresa, arbol['1'], padre_id=arbol['1.1']['id'])            # de una hija
        nieta = cambiar(entrar, empresa, arbol['1'], padre_id=arbol['1.1.01']['id'])        # de una nieta (que además no es grupo)
        assert errores_de(directo) == errores_de(hija) == errores_de(nieta) == {'padre_id': ['Crearía un ciclo.']}
        assert errores_de(cambiar(entrar, empresa, arbol['1.1'], padre_id=arbol['1.1']['id'])) == {'padre_id': [T['ciclo']]}
        assert guardada(empresa, arbol['1']['id']).padre_id is None and guardada(empresa, arbol['1']['id']).version == 1
        # bajo otra rama no hay ciclo
        assert cambiar(entrar, empresa, arbol['1.1'], padre_id=arbol['2']['id']).status_code == 200
        # y ahora «2» cuelga… de nadie: pasarla bajo 1.1 (su hija) sí lo sería
        assert errores_de(cambiar(entrar, empresa, arbol['2'], padre_id=arbol['1.1']['id'])) == {'padre_id': [T['ciclo']]}

    def test_con_hijas_sigue_siendo_grupo(self, entrar, empresa, arbol):
        con_hijas = cambiar(entrar, empresa, arbol['1.1'], tipo='movimiento')
        assert errores_de(con_hijas) == {'tipo': ['Tiene cuentas hijas: debe seguir siendo grupo.']}
        sin_hijas = cambiar(entrar, empresa, arbol['1.2'], tipo='movimiento')
        assert sin_hijas.status_code == 200 and sin_hijas.json()['cuenta']['tipo'] == 'movimiento'
        # y una cuenta de movimiento pasa a grupo para poder tener hijas
        caja = cambiar(entrar, empresa, arbol['1.1.01'], tipo='grupo').json()['cuenta']
        assert alta(entrar, empresa, '1.1.01.1', 'Caja chica', 'movimiento', caja['id']).status_code == 201

    def test_desactivar(self, entrar, empresa, arbol):
        grupo = cambiar(entrar, empresa, arbol['1.1'], activa=False)
        assert errores_de(grupo) == {'activa': ['Desactiva primero sus cuentas hijas.']}
        for codigo in ('1.1.01', '1.1.02'):
            inactiva = cambiar(entrar, empresa, arbol[codigo], activa=False)
            assert inactiva.status_code == 200 and inactiva.json()['cuenta']['activa'] is False
            assert inactiva.json()['cuenta']['version'] == 2
        grupo = cambiar(entrar, empresa, arbol['1.1'], activa=False)
        assert grupo.status_code == 200 and grupo.json()['cuenta'] == {**arbol['1.1'], 'activa': False, 'hijas': 2, 'version': 2}
        assert cuantas(empresa) == 6   # desactivar no borra: siguen en la lista
        assert {c['codigo'] for c in lista(entrar)['cuentas'] if not c['activa']} == {'1.1', '1.1.01', '1.1.02'}
        activa = cambiar(entrar, empresa, grupo.json()['cuenta'], activa=True)
        assert activa.status_code == 200 and activa.json()['cuenta']['version'] == 3

    def test_con_movimientos_ni_pasa_a_grupo_ni_se_desactiva(self, entrar, empresa, arbol, monkeypatch):
        """`tiene_movimientos` es el punto que completarán la apertura y los asientos: cuando diga que sí, estas reglas ya rigen."""
        assert cuentas.tiene_movimientos(guardada(empresa, arbol['1.1.01']['id'])) is False   # hoy nada los registra
        monkeypatch.setattr(cuentas, 'tiene_movimientos', lambda cuenta: cuenta.codigo == '1.1.01')
        caja, bancos = arbol['1.1.01'], arbol['1.1.02']
        assert errores_de(cambiar(entrar, empresa, caja, tipo='grupo')) == {'tipo': [T['con_movimientos_grupo']]}
        assert errores_de(cambiar(entrar, empresa, caja, activa=False)) == {'activa': [T['con_movimientos_desactivar']]}
        assert errores_de(cambiar(entrar, empresa, caja, tipo='grupo', activa=False)) == {
            'tipo': [T['con_movimientos_grupo']], 'activa': [T['con_movimientos_desactivar']]}
        assert cambiar(entrar, empresa, caja, nombre='Caja general').status_code == 200   # lo demás sí se corrige
        assert cambiar(entrar, empresa, bancos, activa=False).status_code == 200          # y la que no tiene, se desactiva


# ---------------------------------------------------------------- versión y cambios

class TestVersion:

    def test_sube_en_cada_cambio_y_rechaza_la_vieja(self, entrar, empresa):
        v1 = nueva(entrar, empresa, '1.1.01', 'Caja')
        v2 = cambiar(entrar, empresa, v1, nombre='Caja general')
        assert v2.status_code == 200 and v2.json() == {'cuenta': {**v1, 'nombre': 'Caja general', 'version': 2}}
        vieja = cambiar(entrar, empresa, v1, nombre='Caja chica')   # otra pestaña que se quedó con la versión 1
        assert vieja.status_code == 409
        assert vieja.json() == {'error': T['version'], 'codigo': 'version', 'cuenta': v2.json()['cuenta']}   # la cuenta actual
        assert guardada(empresa, v1['id']).nombre == 'Caja general'
        v3 = cambiar(entrar, empresa, v2.json()['cuenta'], activa=False).json()['cuenta']
        v4 = cambiar(entrar, empresa, v3, activa=True).json()['cuenta']
        v5 = cambiar(entrar, empresa, v4, tipo='grupo', nombre='Cajas').json()['cuenta']   # dos campos, un cambio
        assert (v3['version'], v4['version'], v5['version']) == (3, 4, 5)
        fila = guardada(empresa, v1['id'])
        assert (fila.version, fila.nombre, fila.tipo, fila.activa) == (5, 'Cajas', 'grupo', True)
        assert fila.actualizada_en > fila.creada_en

    def test_sin_cambios_no_sube_ni_deja_registro(self, entrar, empresa):
        cuenta = nueva(entrar, empresa, '1.1.01', 'Caja')
        igual = cambiar(entrar, empresa, cuenta, nombre=' Caja ', tipo='movimiento', activa=True, padre_id=None, codigo='1.1.01')
        assert igual.status_code == 200 and igual.json() == {'cuenta': cuenta}
        assert cambiar(entrar, empresa, cuenta).json() == {'cuenta': cuenta}   # solo la versión
        assert not AuditLog.objects.filter(action='cuenta_modificada').exists()

    def test_la_version_es_obligatoria(self, entrar, empresa):
        cuenta = nueva(entrar, empresa, '1.1.01', 'Caja')
        url = f'{API}{cuenta["id"]}/'
        for version in (None, '', 'dos', 0, -1, 1.5, True, [1]):
            respuesta = enviar(entrar, url, {'empresa': empresa.pk, 'version': version, 'nombre': 'Otra'}, 'patch')
            assert errores_de(respuesta) == {'version': [T['version_falta']]}, version
        # falta la versión y además hay otro error: los dos a la vez
        assert errores_de(enviar(entrar, url, {'empresa': empresa.pk, 'nombre': ''}, 'patch')) == {
            'version': [T['version_falta']], 'nombre': [T['nombre']]}
        assert enviar(entrar, url, {'empresa': empresa.pk, 'version': '1', 'nombre': 'Caja general'}, 'patch').status_code == 200
        assert guardada(empresa, cuenta['id']).version == 2

    def test_todos_los_errores_de_un_cambio_a_la_vez(self, entrar, empresa, arbol):
        respuesta = cambiar(entrar, empresa, arbol['1.1'], nombre='', tipo='otro', activa='no', padre_id=arbol['1.1']['id'],
                            codigo='1.9')
        assert errores_de(respuesta) == {'nombre': [T['nombre']], 'tipo': [T['tipo']], 'activa': [T['activa']],
                                        'padre_id': [T['ciclo']], 'codigo': [T['codigo_fijo']]}
        dos_reglas = cambiar(entrar, empresa, arbol['1.1'], tipo='movimiento', activa=False)
        assert errores_de(dos_reglas) == {'tipo': [T['con_hijas']], 'activa': [T['hijas_activas']]}
        assert guardada(empresa, arbol['1.1']['id']).version == 1

    def test_la_version_vieja_va_antes_que_la_validacion(self, entrar, empresa):
        v1 = nueva(entrar, empresa, '1.1.01', 'Caja')
        cambiar(entrar, empresa, v1, nombre='Caja general')
        assert cambiar(entrar, empresa, v1, nombre='').status_code == 409

    def test_el_codigo_no_se_cambia(self, entrar, empresa):
        cuenta = nueva(entrar, empresa, '1.1.01', 'Caja')
        assert errores_de(cambiar(entrar, empresa, cuenta, codigo='1.1.02')) == {'codigo': [T['codigo_fijo']]}
        assert guardada(empresa, cuenta['id']).codigo == '1.1.01'

    def test_cuenta_que_no_existe(self, entrar, empresa):
        for pk in (999999, 10 ** 30):
            respuesta = enviar(entrar, f'{API}{pk}/', {'empresa': empresa.pk, 'nombre': 'Nada'}, 'patch')   # ni siquiera trae versión
            assert respuesta.status_code == 404 and respuesta.json() == {'error': T['cuenta'], 'codigo': 'cuenta'}

    def test_cuerpo_que_no_es_json(self, entrar, empresa):
        cuenta = nueva(entrar, empresa, '1.1.01', 'Caja')
        respuesta = entrar.patch(f'{API}{cuenta["id"]}/?empresa={empresa.pk}', '{mal', content_type='application/json')
        assert respuesta.status_code == 400 and respuesta.json()['codigo'] == 'cuerpo'

    def test_cuerpo_ilegible_con_la_empresa_dentro(self, entrar, empresa):
        """Como dice el contrato: si la empresa iba dentro de un JSON que no se puede leer o que no es un objeto, el envío
        no dice para qué empresa se preparó y recibe 409 `sin_empresa`, que va antes en el orden de las negativas. El 400
        `cuerpo` sale cuando la empresa va en la consulta."""
        cuenta = nueva(entrar, empresa, '1.1.01', 'Caja')
        for metodo, ruta in (('post', API), ('patch', f'{API}{cuenta["id"]}/')):
            for cuerpo in ('{no es json', '[1, 2]', f'{{"empresa": {empresa.pk}, "version": 1, "nombre": "Ot'):
                sin_consulta = getattr(entrar, metodo)(ruta, cuerpo, content_type='application/json')
                assert sin_consulta.status_code == 409 and sin_consulta.json()['codigo'] == 'sin_empresa', (metodo, cuerpo)
                con_consulta = getattr(entrar, metodo)(f'{ruta}?empresa={empresa.pk}', cuerpo, content_type='application/json')
                assert con_consulta.status_code == 400 and con_consulta.json()['codigo'] == 'cuerpo', (metodo, cuerpo)
        assert guardada(empresa, cuenta['id']).nombre == 'Caja' and cuantas(empresa) == 1

    def test_un_cambio_va_siempre_en_json(self, entrar, empresa):
        """Como dice el contrato: el formulario vale en POST (alta y subida del archivo), no en PATCH. Django no lee un
        cuerpo de formulario en PATCH, así que ese envío llega vacío: ni la empresa ni la versión que traía cuentan, y
        no cambia nada."""
        cuenta = nueva(entrar, empresa, '1.1.01', 'Caja')
        cuerpo, formulario = f'empresa={empresa.pk}&version=1&nombre=Otro', 'application/x-www-form-urlencoded'
        sin_consulta = entrar.patch(f'{API}{cuenta["id"]}/', cuerpo, content_type=formulario)
        assert sin_consulta.status_code == 409 and sin_consulta.json()['codigo'] == 'sin_empresa'
        con_consulta = entrar.patch(f'{API}{cuenta["id"]}/?empresa={empresa.pk}', cuerpo, content_type=formulario)
        assert errores_de(con_consulta) == {'version': [T['version_falta']]}
        assert guardada(empresa, cuenta['id']).nombre == 'Caja'
        assert cambiar(entrar, empresa, cuenta, nombre='Otro').json()['cuenta']['version'] == 2   # el mismo cambio, en JSON


# ---------------------------------------------------------------- lista y búsqueda

class TestLista:

    def test_orden_natural_e_hijas(self, entrar, empresa, arbol):
        datos = lista(entrar)
        assert [c['codigo'] for c in datos['cuentas']] == ['1', '1.1', '1.1.01', '1.1.02', '1.2', '2']
        assert datos['cuentas'][1] == {'id': arbol['1.1']['id'], 'codigo': '1.1', 'nombre': 'Activo corriente',
                                       'padre_id': arbol['1']['id'], 'tipo': 'grupo', 'activa': True, 'hijas': 2, 'version': 1}
        assert [c['hijas'] for c in datos['cuentas']] == [2, 2, 0, 0, 0, 0]
        assert datos['capacidades'] == {'crear': True, 'editar': True, 'importar': True}
        for codigo in ('1.10', '10', '1.9', 'B', 'a', '1.1.1'):
            sembrar(empresa, codigo)
        # las cifras, por su valor (1.9 antes que 1.10 y 2 antes que 10); las letras, sin distinguir mayúsculas
        assert codigos(entrar) == ['1', '1.1', '1.1.01', '1.1.1', '1.1.02', '1.2', '1.9', '1.10', '2', '10', 'a', 'B']

    def test_busqueda_con_antepasadas(self, entrar, empresa, arbol):
        assert codigos(entrar, '?q=caja') == ['1', '1.1', '1.1.01']              # la coincidencia y sus antepasadas
        assert codigos(entrar, '?q=CORRIENTE') == ['1', '1.1', '1.2']            # por nombre, sin distinguir mayúsculas
        assert codigos(entrar, '?q=1.1.0') == ['1', '1.1', '1.1.01', '1.1.02']   # por código
        assert codigos(entrar, '?q=pasivo') == ['2'] and codigos(entrar, '?q=no+existe') == []
        assert codigos(entrar, '?q=') == codigos(entrar) == codigos(entrar, '?q=+')
        sembrar(empresa, '1.2.01', 'Depreciación acumulada', padre=guardada(empresa, arbol['1.2']['id']))
        assert codigos(entrar, '?q=depreciacion') == codigos(entrar, f'?q={quote("DEPRECIACIÓN")}') == ['1', '1.2', '1.2.01']   # ni tildes
        # `hijas` cuenta todas las que tiene, no solo las que salen en la búsqueda
        assert {c['codigo']: c['hijas'] for c in lista(entrar, '?q=caja')['cuentas']} == {'1': 2, '1.1': 2, '1.1.01': 0}

    def test_sin_consultas_por_fila(self, entrar, empresa):
        raiz = sembrar(empresa, '1', 'Activo', 'grupo')

        def consultas(consulta=''):
            with CaptureQueriesContext(connection) as capturadas:
                assert entrar.get(f'{API}{consulta}').status_code == 200
            return len(capturadas)
        consultas()   # la primera petición llena lo que la sesión guarda en caché
        con_una = consultas()
        grupos = en(empresa, lambda: Cuenta.objects.bulk_create(
            [Cuenta(company=empresa, codigo=f'1.{n}', codigo_norm=f'1.{n}', nombre=f'Grupo {n}', tipo='grupo', padre=raiz)
             for n in range(1, 101)]))
        en(empresa, lambda: Cuenta.objects.bulk_create(
            [Cuenta(company=empresa, codigo=f'{g.codigo}.{n:02d}', codigo_norm=f'{g.codigo}.{n:02d}', nombre=f'Cuenta {n}',
                    tipo='movimiento', padre=g) for g in grupos for n in range(1, 50)][:4899]))
        assert consultas() == con_una and consultas('?q=cuenta+7') == con_una   # con 5 000 cuentas, las mismas consultas
        assert con_una <= 12   # sesión, usuario, membresía, plan, permisos del rol y la lista (PostgreSQL añade fijar la empresa)
        assert len(lista(entrar)['cuentas']) == 5000
        assert len(lista(entrar, '?q=cuenta+7')['cuentas']) == 201   # «Cuenta 7» de cada grupo, los 100 grupos y la raíz


# ---------------------------------------------------------------- dos empresas

class TestDosEmpresas:

    def test_la_otra_empresa_ni_ve_ni_edita(self, entrar, empresa, empresa_b, admin):
        Membership.objects.create(user=admin, company=empresa_b, group=Group.objects.get(name=ROLE_OWNER))
        activo = nueva(entrar, empresa, '1', 'Activo', 'grupo')
        ajena = sembrar(empresa_b, '1', 'Activo de B', 'grupo')
        assert [c['id'] for c in lista(entrar)['cuentas']] == [activo['id']]
        # ni se edita ni sirve de padre una cuenta de la otra empresa
        respuesta = enviar(entrar, f'{API}{ajena.pk}/', {'empresa': empresa.pk, 'version': 1, 'nombre': 'Mía'}, 'patch')
        assert respuesta.status_code == 404 and respuesta.json()['codigo'] == 'cuenta'
        assert errores_de(alta(entrar, empresa, '1.1', 'Corriente', 'grupo', ajena.pk)) == {'padre_id': [T['padre']]}
        assert errores_de(cambiar(entrar, empresa, activo, padre_id=ajena.pk)) == {'padre_id': [T['padre']]}
        assert guardada(empresa_b, ajena.pk).nombre == 'Activo de B' and cuantas(empresa_b) == 1
        # el mismo código y la misma clave en cada empresa no chocan
        datos = {'clave': 'misma-clave-ab', 'codigo': '2', 'nombre': 'Pasivo', 'tipo': 'grupo'}
        assert enviar(entrar, API, {**datos, 'empresa': empresa.pk}).status_code == 201
        entrar.post('/empresas/cambiar/', {'company': empresa_b.pk})
        en_b = enviar(entrar, API, {**datos, 'empresa': empresa_b.pk})
        assert en_b.status_code == 201 and en_b.json()['repetido'] is False
        assert codigos(entrar) == ['1', '2'] and lista(entrar)['cuentas'][0]['id'] == ajena.pk
        assert enviar(entrar, f'{API}{activo["id"]}/', {'empresa': empresa_b.pk, 'version': 1, 'nombre': 'De B'}, 'patch').status_code == 404
        assert guardada(empresa, activo['id']).nombre == 'Activo'
        assert (cuantas(empresa), cuantas(empresa_b)) == (2, 2)


# ---------------------------------------------------------------- licencia

class TestLicencia:

    def test_complemento_cerrado(self, entrar, empresa, settings):
        cuenta = sembrar(empresa, '1', 'Activo', 'grupo')
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = []
        cambio = enviar(entrar, f'{API}{cuenta.pk}/', {'empresa': empresa.pk, 'version': 1, 'nombre': 'Activos'}, 'patch')
        for respuesta in (entrar.get(API), entrar.get(f'{API}?empresa={empresa.pk}'), alta(entrar, empresa, '2', 'Pasivo', 'grupo'), cambio):
            assert respuesta.status_code == 403
            cuerpo = respuesta.json()
            assert (cuerpo['codigo'], cuerpo['plan'], cuerpo['causa']) == ('complemento_pendiente', 'complemento_contable', 'licencia')
            assert cuerpo['licencia']['estado'] == 'complemento_pendiente' and 'cuentas' not in cuerpo
        assert cuantas(empresa) == 1 and guardada(empresa, cuenta.pk).nombre == 'Activo'
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [empresa.ruc]   # en la lista de revisión: abre
        assert codigos(entrar) == ['1']

    def test_plan_vencido_consulta_si_envios_no(self, entrar, empresa):
        cuenta = sembrar(empresa, '1', 'Activo', 'grupo')
        vencer(empresa)
        datos = lista(entrar, f'?empresa={empresa.pk}')
        assert [c['codigo'] for c in datos['cuentas']] == ['1']
        assert datos['capacidades'] == {'crear': False, 'editar': False, 'importar': False}   # solo consulta
        cambio = enviar(entrar, f'{API}{cuenta.pk}/', {'empresa': empresa.pk, 'version': 1, 'nombre': 'Activos'}, 'patch')
        for respuesta in (alta(entrar, empresa, '2', 'Pasivo', 'grupo'), cambio):
            assert respuesta.status_code == 403
            cuerpo = respuesta.json()
            assert (cuerpo['codigo'], cuerpo['causa'], cuerpo['licencia']['estado']) == ('plan', 'licencia', 'plan_vencido')
        assert cuantas(empresa) == 1 and guardada(empresa, cuenta.pk).version == 1

    @pytest.mark.parametrize('accion', ['search', 'search_x', 'send_invoice_by_email'])
    def test_plan_vencido_tampoco_guarda_con_action_de_consulta(self, entrar, empresa, settings, accion):
        """La gemela de la prueba del kardex (tests/test_kardex.py). PlanMiddleware toma por consulta un formulario con
        ese `action` y lo deja pasar con el plan vencido: el alta responde el mismo 403 que sin él y no guarda nada."""
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [empresa.ruc]   # en la lista de revisión, no por el «*» de las pruebas
        formulario = {'empresa': empresa.pk, 'clave': 'alta-con-action-01', 'codigo': '1', 'nombre': 'Activo', 'tipo': 'grupo'}
        assert entrar.post(API, {**formulario, 'action': accion}).status_code == 201   # con el plan vigente el formulario vale
        vencer(empresa)
        formulario.update(clave='alta-con-action-02', codigo='2', nombre='Pasivo')
        sin_action = entrar.post(API, formulario)
        assert sin_action.status_code == 403 and sin_action.json()['codigo'] == 'plan'
        con_action = entrar.post(API, {**formulario, 'action': accion})
        assert con_action.status_code == 403 and con_action.json() == sin_action.json()
        assert con_action.json()['licencia']['estado'] == 'plan_vencido'
        assert codigos(entrar) == ['1'] and AuditLog.objects.filter(action='cuenta_creada').count() == 1

    def test_sin_plan_pagado(self, client):
        gratuita = helpers.crear_empresa('GRATIS CUENTAS', plan=None)
        helpers.iniciar_sesion(client, helpers.crear_usuario('dueno.cuentas.gratis', gratuita, ROLE_OWNER), empresa=gratuita)
        for respuesta in (client.get(API), alta(client, gratuita, '1', 'Activo', 'grupo')):
            assert respuesta.status_code == 403 and respuesta.json()['plan'] == 'requerido' and respuesta.json()['causa'] == 'licencia'
        assert cuantas(gratuita) == 0


# ---------------------------------------------------------------- auditoría

class TestAuditoria:

    def test_alta_y_cambios(self, entrar, empresa, admin):
        grupo = nueva(entrar, empresa, '1', 'Activo', 'grupo')
        caja = nueva(entrar, empresa, '1.1.01', 'Caja', 'movimiento', grupo)
        altas = list(AuditLog.objects.filter(action='cuenta_creada').order_by('id'))
        assert [(r.user, r.company, r.detail) for r in altas] == [
            (admin, empresa, {'cuenta': grupo['id'], 'codigo': '1', 'nombre': 'Activo', 'tipo': 'grupo', 'padre': None}),
            (admin, empresa, {'cuenta': caja['id'], 'codigo': '1.1.01', 'nombre': 'Caja', 'tipo': 'movimiento', 'padre': grupo['id']})]
        assert altas[0].get_action_display() == 'Plan de cuentas: cuenta creada'
        cambiada = cambiar(entrar, empresa, caja, nombre='Caja general', activa=False, padre_id=None).json()['cuenta']
        registro = AuditLog.objects.get(action='cuenta_modificada')
        assert (registro.user, registro.company) == (admin, empresa)
        assert registro.detail == {'cuenta': caja['id'], 'codigo': '1.1.01', 'version': 2,   # los campos que cambiaron: antes y después
                                   'cambios': {'nombre': ['Caja', 'Caja general'], 'activa': [True, False], 'padre_id': [grupo['id'], None]}}
        # un cambio rechazado no deja registro
        assert cambiar(entrar, empresa, cambiada, tipo='otro').status_code == 400
        assert cambiar(entrar, empresa, caja, nombre='Vieja').status_code == 409
        assert AuditLog.objects.filter(action='cuenta_modificada').count() == 1


# ---------------------------------------------------------------- seguridad por filas (PostgreSQL)

@pytest.mark.skipif(connection.vendor != 'postgresql', reason='La seguridad por filas es de PostgreSQL')
class TestSeguridadPorFilas:
    TABLA = 'contabilidad_cuenta'

    def contar(self):
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM {self.TABLA}')   # sin filtro de empresa a propósito
            return cursor.fetchone()[0]

    def test_politica_activa_y_forzada(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s', [self.TABLA])
            assert cursor.fetchone() == (True, True)
            cursor.execute('SELECT polname FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid WHERE c.relname = %s', [self.TABLA])
            assert [fila[0] for fila in cursor.fetchall()] == ['fpa_empresa']

    def test_consulta_sin_filtro_solo_ve_la_empresa_fijada(self, empresa, empresa_b):
        sembrar(empresa, '1')
        sembrar(empresa, '2')
        sembrar(empresa_b, '1')
        with company_context(empresa):
            assert self.contar() == 2
        with company_context(empresa_b):
            assert self.contar() == 1

    def test_no_se_inserta_ni_se_cambia_una_fila_de_otra_empresa(self, empresa, empresa_b):
        ajena = sembrar(empresa_b, '1', 'Activo de B', 'grupo')
        with company_context(empresa):
            with pytest.raises(DatabaseError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'INSERT INTO {self.TABLA} (company_id, codigo, codigo_norm, nombre, tipo, activa, version, '
                                   "creada_en, actualizada_en) VALUES (%s, 'X', 'x', 'Intrusa', 'grupo', true, 1, now(), now())",
                                   [empresa_b.id])
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE {self.TABLA} SET nombre = 'Cambiada desde A' WHERE id = %s", [ajena.pk])
                assert cursor.rowcount == 0   # la fila no existe para la empresa A
        assert guardada(empresa_b, ajena.pk).nombre == 'Activo de B'


# ---------------------------------------------------------------- borrar al usuario que creó cuentas (PostgreSQL)

@pytest.mark.skipif(connection.vendor != 'postgresql', reason='La seguridad por filas es de PostgreSQL')
class TestBorrarAlAutor:
    """Cuentas y lotes guardan quién los creó, editó, subió y confirmó (`SET_NULL`). Django anula esas referencias con un
    UPDATE antes de borrar al usuario, pero con la seguridad por filas forzada ese UPDATE solo alcanza a la empresa
    activa: las cuentas de otra empresa seguían apuntando al usuario y el borrado fallaba al confirmar, con la membresía
    ya quitada (ensayo del bloque 1). La versión publicada (e0f2902), que no conoce estas tablas, ni lo intenta. La base
    anula las referencias por su cuenta (contabilidad 0009). Las pruebas corren dentro de una transacción que nunca se
    confirma: las comprobaciones de las claves foráneas, diferidas, se hacen inmediatas para que fallen donde fallaban."""

    CLAVES = {('contabilidad_cuenta', 'creada_por_id'), ('contabilidad_cuenta', 'actualizada_por_id'),
              ('contabilidad_importacioncuentas', 'creado_por_id'), ('contabilidad_importacioncuentas', 'confirmado_por_id')}

    def test_las_claves_hacia_el_usuario_anulan_en_la_base_y_siguen_diferidas(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT c.conrelid::regclass::text, a.attname, c.confdeltype, c.condeferrable, c.condeferred
                FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
                WHERE c.contype = 'f' AND c.confrelid = %s::regclass
                  AND c.conrelid::regclass::text IN ('contabilidad_cuenta', 'contabilidad_importacioncuentas')""",
                           [get_user_model()._meta.db_table])
            filas = cursor.fetchall()
        assert {(tabla, columna) for tabla, columna, *_ in filas} == self.CLAVES and len(filas) == 4
        assert {fila[2:] for fila in filas} == {('n', True, True)}   # ON DELETE SET NULL, DEFERRABLE INITIALLY DEFERRED

    def autorias(self, empresa, autor):
        with company_context(empresa):
            Cuenta.objects.create(codigo='1', nombre='Activo', tipo='grupo', creada_por=autor, actualizada_por=autor)
            ImportacionCuentas.objects.create(clave='lote-del-autor-01', nombre_original='plan.csv', tamano=1, sha256='0' * 64,
                                              creado_por=autor, confirmado_por=autor, estado='confirmado',
                                              confirmado_en=timezone.now())

    def anuladas(self, empresa):
        with company_context(empresa):
            return (list(Cuenta.objects.values_list('creada_por_id', 'actualizada_por_id')),
                    list(ImportacionCuentas.objects.values_list('creado_por_id', 'confirmado_por_id')))

    def comprobar_ya(self):
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')

    def test_quitar_de_su_ultima_empresa_a_quien_creo_cuentas_en_otra(self, client, empresa, empresa_b):
        autor = helpers.crear_usuario('autor.plan', empresa, ROLE_ACCOUNTANT)
        Membership.objects.create(user=autor, company=empresa_b, group=Group.objects.get(name=ROLE_ACCOUNTANT))
        self.autorias(empresa, autor)
        Membership.objects.filter(user=autor, company=empresa).delete()   # ya lo quitaron de la empresa A
        propietario_b = helpers.crear_usuario('propietario.b', empresa_b, ROLE_OWNER)
        helpers.iniciar_sesion(client, propietario_b, empresa=empresa_b)
        self.comprobar_ya()
        respuesta = client.post(f'/user/delete/{autor.pk}/')
        assert respuesta.status_code == 200 and respuesta.json() == {}, respuesta.content
        assert not get_user_model().objects.filter(pk=autor.pk).exists()
        assert self.anuladas(empresa) == ([(None, None)], [(None, None)])

    def test_borrar_al_usuario_sin_pasar_por_django(self, empresa, empresa_b):
        """Lo que hace una versión del código que no conoce estas tablas: borrar al usuario sin anular nada antes."""
        autor = helpers.crear_usuario('autor.plan')   # sin membresías ni otras referencias
        self.autorias(empresa, autor)
        with company_context(empresa_b):
            self.comprobar_ya()
            with connection.cursor() as cursor:
                cursor.execute(f'DELETE FROM {get_user_model()._meta.db_table} WHERE id = %s', [autor.pk])
                assert cursor.rowcount == 1
        assert self.anuladas(empresa) == ([(None, None)], [(None, None)])


# ---------------------------------------------------------------- migración que reparte los permisos

def reparto():
    """Permisos del módulo del kardex y, por rol, los de la app contabilidad."""
    modulo = set(Module.objects.get(url='/contabilidad/kardex/').permissions.values_list('codename', flat=True))
    return modulo, {g.name: set(g.permissions.filter(content_type__app_label='contabilidad').values_list('codename', flat=True))
                    for g in Group.objects.order_by('name')}


def test_migracion_de_los_permisos_de_vuelta_y_de_ida():
    """contabilidad 0006 con el registro real: la vuelta deja el módulo del kardex y los roles como estaban antes del plan
    de cuentas (lo publicado); la ida los reparte otra vez, y repetirla no cambia nada."""
    migracion = importlib.import_module('core.contabilidad.migrations.0006_permisos_plan_cuentas')
    instalado = reparto()
    assert instalado[0] == DEL_KARDEX | DEL_PLAN and instalado[1][ROLE_READONLY] == {'view_kardex', 'view_cuenta'}
    modulos = Module.objects.count()
    migracion.backwards(registro, None)
    modulo, roles = reparto()
    assert modulo == DEL_KARDEX
    assert roles[ROLE_OWNER] == roles[ROLE_ADMIN] == roles[ROLE_ACCOUNTANT] == DEL_KARDEX
    assert roles[ROLE_READONLY] == {'view_kardex'} and roles[ROLE_SELLER] == roles[ROLE_CLIENT] == set()
    for _ in range(2):
        migracion.forwards(registro, None)
        assert reparto() == instalado and Module.objects.count() == modulos
    assert registro.get_app_config('contabilidad').models_module is importlib.import_module('core.contabilidad.models')
