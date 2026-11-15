"""Inicio contable y apertura en preparación (bloque 2 del cierre contable, Parte B, primera mitad: todo lo que ocurre en
borrador): core/contabilidad/inicio_contable.py, apertura.py, cobertura.py y vistas_apertura.py.

GET y POST /contabilidad/api/apertura/, GET y PATCH …/<id>/, POST …/<id>/mapear/ (captura directa del conjunto completo),
GET …/<id>/lineas/ y POST …/<id>/descartar/: formas exactas de las respuestas; configuración por saldos y por historial
(reglas 1 a 3: fechas, corte no futuro, solapamiento con asientos y aplicaciones); clave (`repetido`, `clave_usada`),
versión, estados y la precedencia de las negativas; mapear dos veces sin borrar líneas (ids conservados, retiradas,
reutilizadas, sin cuenta por orden, con auxiliares vigentes → 409); ámbitos que no aplican; cobertura (`pendiente` sin
confirmar, `no_aplica` solo por declaración, `sin_cuenta_declarada`); descartar; historia y auditoría; capacidades de la
apertura y del registro (requisito y avisos); etapa del inicio contable; el punto de unión con el candado; dos empresas,
pestaña vieja, matriz de los seis roles, plan vencido y complemento cerrado en cada ruta; 5 000 líneas sin N+1.

La importación de saldos y los respaldos van en tests/test_apertura_importar.py; la seguridad por filas y la concurrencia
en PostgreSQL, en tests/test_zz_apertura_concurrencia_pg.py. Datos ficticios."""
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import Resolver404, resolve
from django.utils import timezone

from core.contabilidad import api, apertura as servicio, capacidades, cobertura, inicio_contable
from core.contabilidad.models import (AplicacionAuxiliar, Apertura, AuxiliarApertura, Cuenta, EventoApertura,
                                      InicioContable, LineaApertura, norma_codigo)
from core.suscripciones.models import SubscriptionPeriod
from core.tenancy.context import company_context
from core.tenancy.models import (ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog,
                                 Membership)
from tests import ayudas_contables as ayudas
from tests import helpers

pytestmark = pytest.mark.django_db

API = '/contabilidad/api/apertura/'
CAPACIDADES = '/contabilidad/api/capacidades/'
DATOS = {'modalidad': 'saldos', 'fecha_corte': '2025-12-31', 'fuente': 'balance_comprobacion',
         'fuente_detalle': 'Balance de comprobación firmado'}
T = servicio.TEXTOS
TI = inicio_contable.TEXTOS
SIN_PENDIENTES = {'sin_cuenta': 0, 'importe_pendiente': 0, 'de_grupo': 0, 'sin_clase': 0}


# ---------------------------------------------------------------- ayudas

def en(empresa, funcion):
    with company_context(empresa):
        return funcion()


def con_empresa(ruta, empresa):
    return f'{ruta}{"&" if "?" in ruta else "?"}empresa={empresa.pk}'


def enviar(client, ruta, empresa, datos=None, metodo='post'):
    """Envío JSON con la empresa de la pestaña en la consulta (decisión común 6) y en el cuerpo."""
    cuerpo = {'empresa': empresa.pk, **(datos or {})}
    return getattr(client, metodo)(con_empresa(ruta, empresa), json.dumps(cuerpo, default=str), content_type='application/json')


def leer(client, ruta, empresa):
    respuesta = client.get(con_empresa(ruta, empresa))
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()


def crear(client, empresa, **cambios):
    return enviar(client, API, empresa, {'clave': ayudas.clave('crear'), **DATOS, **cambios})


def creada(client, empresa, **cambios):
    respuesta = crear(client, empresa, **cambios)
    assert respuesta.status_code == 201, respuesta.content
    return respuesta.json()['apertura']


def mapear(client, empresa, apertura, lineas, version=None):
    return enviar(client, f'{API}{apertura["id"]}/mapear/', empresa,
                  {'version': version if version is not None else apertura['version'], 'lineas': lineas})


def mapeada(client, empresa, apertura, lineas):
    respuesta = mapear(client, empresa, apertura, lineas)
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()


def linea(cuenta, debe=None, haber=None, **extra):
    return {'cuenta_id': cuenta.pk if cuenta is not None else None, 'rubro': cuenta.nombre if cuenta is not None else 'Sin cuenta',
            'debe': debe, 'haber': haber, **extra}


def balance(cuentas):
    """El balance didáctico de C6-A: caja 10 000 al debe y capital social 10 000 al haber."""
    return [linea(cuentas['caja'], '10000.00'), linea(cuentas['capital'], None, '10000.00')]


def rechazo(respuesta, estado, codigo):
    assert respuesta.status_code == estado, respuesta.content
    assert respuesta.json()['codigo'] == codigo, respuesta.json()
    return respuesta.json()


def errores(respuesta, codigo='validacion'):
    return rechazo(respuesta, 400, codigo)['errores']


def aperturas(empresa):
    return en(empresa, lambda: list(Apertura.objects.order_by('id').values_list('id', 'estado')))


def acciones(empresa, accion):
    return list(AuditLog.objects.filter(company=empresa, action=accion).order_by('id').values_list('detail', flat=True))


def eventos(empresa, apertura_id=None):
    return en(empresa, lambda: list(EventoApertura.objects.filter(apertura_id=apertura_id).order_by('id')
                                    .values_list('accion', 'de_estado', 'a_estado')))


def vencer(empresa):
    SubscriptionPeriod.objects.filter(company=empresa).update(ends_at=timezone.now() - timedelta(days=1))


def hoy():
    return timezone.localdate()


@pytest.fixture
def cuentas(empresa):
    return ayudas.plan_minimo(empresa)


@pytest.fixture
def web(client, empresa, admin, cuentas):
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    return client


def entrar_como(client, empresa, rol):
    usuario = helpers.crear_usuario(f'apertura.{empresa.pk}.{rol.lower()}', empresa, rol)
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    return usuario


# ---------------------------------------------------------------- consulta

class TestConsulta:

    def test_sin_configurar_responde_200_con_todo_en_null(self, web, empresa):
        datos = leer(web, API, empresa)
        assert list(datos) == ['empresa', 'configuracion', 'modalidad', 'fecha_corte', 'operaciones_desde', 'apertura', 'vigente',
                               'cobertura', 'capacidades', 'acceso']
        assert datos['empresa'] == {'id': empresa.pk, 'ruc': empresa.ruc, 'nombre': empresa.business_name}
        assert (datos['configuracion'], datos['modalidad'], datos['fecha_corte'], datos['operaciones_desde'], datos['apertura'],
                datos['vigente']) == (None,) * 6
        assert datos['cobertura']['contabilidad'] == {
            'estado': 'pendiente', 'causas': [cobertura.TEXTOS['inicio_sin_configurar']],
            'causas_detalle': [{'codigo': 'inicio_sin_configurar', 'texto': cobertura.TEXTOS['inicio_sin_configurar']}]}
        assert datos['cobertura']['periodos'] == []
        assert set(datos['capacidades']) == set(servicio.REGLAS_CAPACIDAD) and not any(datos['capacidades'].values())
        assert datos['acceso'] == web.get(CAPACIDADES).json()   # el contrato de capacidades del bloque 1, entero

    def test_con_borrador(self, web, empresa):
        creada(web, empresa)
        datos = leer(web, API, empresa)
        assert datos['configuracion'] == {'version': 1, 'modalidad': 'saldos', 'fecha_corte': '2025-12-31',
                                          'contabilidad_desde': '2026-01-01', 'operaciones_desde': '2026-01-01',
                                          'historial_desde': None, 'historial_hasta': None, 'guarda_importacion': False}
        assert (datos['modalidad'], datos['fecha_corte'], datos['operaciones_desde']) == ('saldos', '2025-12-31', '2026-01-01')
        apertura = datos['apertura']
        assert apertura == {
            'id': apertura['id'], 'version': 1, 'estado': 'borrador', 'fuente': 'balance_comprobacion',
            'fuente_detalle': 'Balance de comprobación firmado', 'sin_saldos': False, 'fecha_corte': '2025-12-31', 'moneda': 'USD',
            'debe': '0.00', 'haber': '0.00', 'diferencia': '0.00', 'lineas': 0, 'pendientes': SIN_PENDIENTES,
            'resultado_ejercicio': '', 'resultado_acumulado': None, 'inventario_modo': 'solo_conciliar', 'ambitos_no_aplican': [],
            'sustituye': None, 'ajustes': 0, 'asiento': None, 'enviado_por': None, 'enviado_en': None, 'revisado_por': None,
            'confirmado_por': None, 'confirmado_en': None, 'creado_por': 'propietario.a', 'creado_en': apertura['creado_en'],
            'motivo': ''}
        assert datos['vigente'] is None
        # Sin saldo anterior no se supone cero: la contabilidad sigue pendiente mientras no se confirme.
        assert datos['cobertura']['contabilidad']['causas_detalle'] == [
            {'codigo': 'apertura_sin_confirmar', 'texto': cobertura.TEXTOS['apertura_sin_confirmar']}]
        # En borrador: editar, validar, enviar y descartar; devolver y confirmar son de la revisión, y sustituir, ajustar,
        # reversar y cobrar, de una confirmada (y del corte 2: se anuncian al publicarse su ruta).
        assert datos['capacidades'] == {**dict.fromkeys(servicio.REGLAS_CAPACIDAD, False), 'editar': True, 'validar': True,
                                        'enviar': True, 'descartar': True}

    def test_cobertura_por_ambito_sin_auxiliares(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        mapeada(web, empresa, apertura, [linea(cuentas['clientes'], '300.00'), linea(cuentas['bancos'], None, None),
                                         linea(cuentas['capital'], None, '300.00')])
        datos = leer(web, API, empresa)['cobertura']
        assert list(datos) == ['contabilidad', 'cartera', 'inventario', 'bancos', 'activos', 'tributario', 'periodos']
        # clientes: hay saldo y no hay detalle; proveedores: ninguna línea con ese detalle (no se deduce que no haya)
        assert datos['cartera']['clientes'] == {'estado': 'pendiente', 'cuenta': '300.00', 'detallado': '0.00', 'documentos': 0}
        assert datos['cartera']['proveedores'] == {'estado': 'pendiente', 'cuenta': None, 'detallado': None, 'documentos': 0}
        assert [c['codigo'] for c in datos['cartera']['causas_detalle']] == ['sin_detalle', 'sin_cuenta_declarada']
        assert datos['cartera']['causas'][1] == 'Ninguna cuenta de la apertura está declarada como de proveedores.'
        # bancos con el saldo pendiente: la suma no se presenta como el saldo
        assert datos['bancos']['cuenta'] is None and [c['codigo'] for c in datos['bancos']['causas_detalle']] == [
            'importe_pendiente', 'sin_detalle']
        assert datos['inventario']['causas_detalle'][0]['codigo'] == 'sin_cuenta_declarada'
        assert datos['tributario'] == {'estado': 'pendiente', 'causas': [cobertura.TEXTOS['tributario_sin_saldos']],
                                       'causas_detalle': [{'codigo': 'tributario_sin_saldos',
                                                           'texto': cobertura.TEXTOS['tributario_sin_saldos']}],
                                       'saldos_anteriores': None}   # nunca "0.00"
        meses = [p['mes'] for p in datos['periodos']]   # del año en curso, desde contabilidad_desde (01/01/2026)
        assert meses == [f'{hoy().year}-{m:02d}' for m in range(1, hoy().month + 1)]
        assert datos['periodos'][0]['ambitos']['contabilidad'] == {'estado': 'sin_cobertura', 'fuente_tipo': None,
                                                                   'declarado_por': None, 'declarado_en': None}

    def test_cobertura_con_detalle_y_no_aplica_declarado(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        r = mapeada(web, empresa, apertura, [linea(cuentas['clientes'], '300.00'), linea(cuentas['capital'], None, '300.00')])
        clientes = next(l for l in r['lineas'] if l['detalle'] == 'cliente')
        assert clientes['auxiliares'] == {'estado': 'sin_detalle', 'detallado': '0.00', 'filas': 0}
        def detallar(importe):
            with company_context(empresa):
                return AuxiliarApertura.objects.create(
                    apertura_id=apertura['id'], linea_id=clientes['id'], cuenta=cuentas['clientes'], naturaleza='cliente',
                    saldo_inicial=Decimal(importe), tercero_identificacion=f'09{importe[:3]}', tercero_nombre='CLIENTE FICTICIO',
                    documento_tipo='01', documento_numero=f'001-001-{importe[:3]}', creado_por_nombre=ayudas.AUTOR[1])
        detallar('100.00')
        datos = leer(web, API, empresa)
        assert datos['cobertura']['cartera']['clientes'] == {'estado': 'parcial', 'cuenta': '300.00', 'detallado': '100.00',
                                                             'documentos': 1}
        detallar('200.00')
        assert leer(web, API, empresa)['cobertura']['cartera']['clientes']['estado'] == 'conciliada'
        lineas = leer(web, f'{API}{apertura["id"]}/lineas/', empresa)['lineas']
        assert next(l for l in lineas if l['id'] == clientes['id'])['auxiliares'] == {
            'estado': 'conciliada', 'detallado': '300.00', 'filas': 2}
        # no_aplica solo por declaración expresa, con su nota
        version = leer(web, API, empresa)['apertura']['version']
        r = enviar(web, f'{API}{apertura["id"]}/', empresa, {'version': version, 'ambitos_no_aplican': [
            {'ambito': 'proveedores', 'nota': 'La empresa compra al contado.'}]}, 'patch')
        assert r.status_code == 200, r.content
        datos = leer(web, API, empresa)['cobertura']
        assert datos['cartera']['proveedores']['estado'] == 'no_aplica'
        assert datos['cartera']['estado'] == 'conciliada'   # clientes conciliada y proveedores no aplica

    def test_historial(self, web, empresa):
        respuesta = crear(web, empresa, modalidad='historial', fecha_corte=None, historial_desde='2025-07-01',
                          historial_hasta='2025-09-30')
        assert respuesta.status_code == 201, respuesta.content
        assert respuesta.json()['configuracion'] == {
            'version': 1, 'modalidad': 'historial', 'fecha_corte': '2025-06-30', 'contabilidad_desde': '2025-07-01',
            'operaciones_desde': '2025-10-01', 'historial_desde': '2025-07-01', 'historial_hasta': '2025-09-30',
            'guarda_importacion': False}
        assert respuesta.json()['apertura']['fecha_corte'] == '2025-06-30'   # la apertura es el saldo anterior al rango
        assert leer(web, API, empresa)['cobertura']['contabilidad']['causas_detalle'][0]['codigo'] == 'saldo_anterior_sin_confirmar'

    def test_con_una_confirmada(self, web, empresa, cuentas):
        _, confirmada = ayudas.apertura_confirmada_directa(empresa, cuentas)
        datos = leer(web, API, empresa)
        assert datos['apertura']['id'] == datos['vigente']['id'] == confirmada.pk
        assert datos['apertura']['estado'] == 'confirmada'
        assert (datos['apertura']['debe'], datos['apertura']['haber'], datos['apertura']['diferencia']) == (
            '10000.00', '10000.00', '0.00')
        assert datos['vigente']['asiento'] == {'id': confirmada.asiento_id, 'numero': '2025-000001', 'fecha': '2025-12-31',
                                               'debe': '10000.00', 'haber': '10000.00'}
        assert datos['cobertura']['contabilidad'] == {'estado': 'conciliada', 'causas': [], 'causas_detalle': []}
        assert not any(datos['capacidades'].values())   # sustituir, ajustar, reversar y cobrar son del corte 2


# ---------------------------------------------------------------- crear

class TestCrear:

    def test_crea_la_configuracion_y_el_borrador(self, web, empresa, admin):
        respuesta = crear(web, empresa, clave='crear-apertura-1')
        assert respuesta.status_code == 201
        datos = respuesta.json()
        assert list(datos) == ['configuracion', 'apertura', 'repetido'] and datos['repetido'] is False
        assert datos['apertura']['estado'] == 'borrador' and datos['apertura']['asiento'] is None
        inicio = en(empresa, InicioContable.objects.get)
        assert (inicio.modalidad, inicio.fecha_corte, inicio.contabilidad_desde, inicio.operaciones_desde, inicio.version) == (
            'saldos', date(2025, 12, 31), date(2026, 1, 1), date(2026, 1, 1), 1)
        assert (inicio.creado_por_id, inicio.creado_por_nombre) == (admin.pk, 'propietario.a')
        apertura = en(empresa, lambda: Apertura.objects.get(pk=datos['apertura']['id']))
        assert (apertura.clave, apertura.creado_por_id, apertura.creado_por_nombre) == ('crear-apertura-1', admin.pk, 'propietario.a')
        # historia (la del inicio no cuelga de una apertura) y auditoría, dentro de la misma transacción
        assert eventos(empresa) == [('inicio_configurado', '', '')]
        assert eventos(empresa, apertura.pk) == [('creada', '', 'borrador')]
        assert acciones(empresa, 'inicio_contable_configurado')[0]['cambios']['fecha_corte'] == [None, '2025-12-31']
        assert acciones(empresa, 'apertura_creada') == [{'apertura': apertura.pk, 'inicio': inicio.pk, 'modalidad': 'saldos',
                                                         'fecha_corte': '2025-12-31', 'fuente': 'balance_comprobacion',
                                                         'sin_saldos': False}]

    def test_misma_clave(self, web, empresa):
        primera = crear(web, empresa, clave='crear-repetida-1')
        otra_vez = crear(web, empresa, clave='crear-repetida-1')
        assert otra_vez.status_code == 200 and otra_vez.json()['repetido'] is True
        assert otra_vez.json()['apertura'] == primera.json()['apertura']
        usada = rechazo(crear(web, empresa, clave='crear-repetida-1', fuente='estado_situacion'), 409, 'clave_usada')
        assert usada['apertura']['id'] == primera.json()['apertura']['id']
        assert len(aperturas(empresa)) == 1 and len(acciones(empresa, 'apertura_creada')) == 1

    def test_otra_en_preparacion(self, web, empresa):
        primera = creada(web, empresa)
        datos = rechazo(crear(web, empresa), 409, 'apertura_existente')
        assert datos['apertura']['id'] == primera['id'] and len(aperturas(empresa)) == 1

    def test_con_una_confirmada_la_configuracion_solo_cambia_sustituyendo(self, web, empresa, cuentas):
        ayudas.apertura_confirmada_directa(empresa, cuentas)
        rechazo(crear(web, empresa, fecha_corte='2025-11-30'), 409, 'apertura_confirmada')
        assert en(empresa, InicioContable.objects.get).fecha_corte == date(2025, 12, 31)
        # también con un envío mal escrito: lo que impide crearla va antes que la validación
        rechazo(crear(web, empresa, fuente='otra'), 409, 'apertura_confirmada')

    def test_plan_de_cuentas_vacio(self, client, empresa, admin):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        en(empresa, lambda: Cuenta.objects.create(codigo='1', nombre='ACTIVO', tipo='grupo'))   # un grupo no recibe saldos
        datos = rechazo(crear(client, empresa), 409, 'datos_por_completar')
        assert [f['codigo'] for f in datos['faltan']] == ['plan_cuentas_vacio'] and datos['causa'] == 'datos'
        # datos por completar va antes que la clave
        assert rechazo(enviar(client, API, empresa, {**DATOS}), 409, 'datos_por_completar')
        assert aperturas(empresa) == [] and not en(empresa, InicioContable.objects.exists)

    def test_validacion_con_todos_los_errores(self, web, empresa):
        manana = (hoy() + timedelta(days=1)).isoformat()
        assert errores(crear(web, empresa, fecha_corte=manana, fuente='otra', fuente_detalle='x' * 301,
                             historial_hasta='2025-01-01')) == {
            'fecha_corte': [TI['corte_futuro']], 'historial_hasta': [TI['solo_historial']], 'fuente': [T['fuente']],
            'fuente_detalle': [T['fuente_detalle_largo']]}
        assert errores(crear(web, empresa, modalidad='otra')) == {'modalidad': [TI['modalidad']]}
        assert errores(crear(web, empresa, fecha_corte='31/12/2025')) == {'fecha_corte': [TI['fecha']]}
        assert errores(crear(web, empresa, fecha_corte='1999-12-31')) == {'fecha_corte': [TI['corte_antiguo']]}
        assert errores(crear(web, empresa, fecha_corte=None)) == {'fecha_corte': [TI['fecha_corte']]}
        ayer = (hoy() - timedelta(days=1)).isoformat()
        assert errores(crear(web, empresa, modalidad='historial', fecha_corte=None, historial_desde='2025-07-01',
                             historial_hasta=hoy().isoformat())) == {'historial_hasta': [TI['hasta_futuro']]}
        assert errores(crear(web, empresa, modalidad='historial', fecha_corte=None, historial_desde='2025-07-01',
                             historial_hasta='2025-06-01')) == {'historial_hasta': [TI['hasta_antes']]}
        assert errores(crear(web, empresa, modalidad='historial', fecha_corte=None)) == {
            'historial_desde': [TI['historial_desde']], 'historial_hasta': [TI['historial_hasta']]}
        assert errores(crear(web, empresa, modalidad='historial', historial_desde='2025-07-01', historial_hasta=ayer,
                             fecha_corte='2025-12-31')) == {'fecha_corte': [TI['corte_historial']]}
        assert errores(crear(web, empresa, sin_saldos=True, fuente_detalle='')) == {
            'sin_saldos': [T['sin_saldos_fuente']], 'fuente_detalle': [T['sin_saldos_detalle']]}
        assert errores(crear(web, empresa, sin_saldos='quizá')) == {'sin_saldos': [T['sin_saldos']]}
        assert rechazo(crear(web, empresa, clave='corta'), 400, 'clave')['errores'] == {'clave': [api.TEXTOS['clave']]}
        assert aperturas(empresa) == [] and not en(empresa, InicioContable.objects.exists)

    def test_el_corte_de_hoy_se_prepara(self, web, empresa):
        """Futuro es mañana: el corte de hoy se prepara (confirmarlo exige el día terminado: es de la confirmación)."""
        assert creada(web, empresa, fecha_corte=hoy().isoformat())['fecha_corte'] == hoy().isoformat()

    def test_sin_saldos_es_una_declaracion_de_inicio_de_actividades(self, web, empresa):
        apertura = creada(web, empresa, fuente='inicio_actividades', sin_saldos=True,
                          fuente_detalle='Empresa constituida el 01/01/2026, sin movimientos anteriores.')
        assert (apertura['sin_saldos'], apertura['fuente'], apertura['lineas']) == (True, 'inicio_actividades', 0)

    def test_rango_solapado_con_un_asiento_ordinario(self, web, empresa, cuentas):
        ayudas.asiento_directo(empresa, [(cuentas['caja'], '50.00', '0'), (cuentas['ventas'], '0', '50.00')],
                               fecha=date(2026, 1, 15))
        datos = rechazo(crear(web, empresa, fecha_corte='2026-01-31'), 409, 'rango_solapado')
        assert (datos['asientos'], datos['aplicaciones'], datos['primera_fecha']) == (1, 0, '2026-01-15')
        rechazo(crear(web, empresa, fecha_corte='2026-01-15'), 409, 'rango_solapado')   # igual a la fecha también
        assert aperturas(empresa) == [] and not en(empresa, InicioContable.objects.exists)
        assert creada(web, empresa, fecha_corte='2026-01-14')['fecha_corte'] == '2026-01-14'

    def test_rango_solapado_con_una_aplicacion_vigente(self, web, empresa, cuentas):
        filas = ayudas.filas_de_apertura(empresa, cuentas, ayudas.asiento_directo(
            empresa, [(cuentas['caja'], '1.00', '0'), (cuentas['ventas'], '0', '1.00')], fecha=date(2025, 6, 1)))
        en(empresa, lambda: Apertura.objects.filter(pk=filas['apertura'].pk).update(estado='descartada', motivo='prueba'))
        assert en(empresa, lambda: inicio_contable.solapamiento(date(2026, 1, 31))) == {
            'asientos': 1, 'aplicaciones': 1, 'primera_fecha': '2025-06-01'}
        datos = rechazo(crear(web, empresa, fecha_corte='2026-01-31'), 409, 'rango_solapado')
        assert (datos['asientos'], datos['aplicaciones']) == (1, 1)
        en(empresa, lambda: AplicacionAuxiliar.objects.update(estado='anulado', anulado_en=timezone.now(), motivo_anulacion='x'))
        assert en(empresa, lambda: inicio_contable.solapamiento(date(2026, 1, 31)))['aplicaciones'] == 0

    def test_la_apertura_y_su_reverso_no_son_asientos_ordinarios(self, web, empresa, cuentas):
        original = ayudas.asiento_directo(empresa, [(cuentas['caja'], '5.00', '0'), (cuentas['capital'], '0', '5.00')],
                                          fecha=date(2025, 6, 30), tipo='apertura', motivo='', origen=('apertura', 1, 'confirmacion'))
        ayudas.reverso_directo(empresa, original)
        assert creada(web, empresa, fecha_corte='2025-12-31')['estado'] == 'borrador'


# ---------------------------------------------------------------- editar

class TestEditar:

    def editar(self, web, empresa, apertura, **datos):
        datos.setdefault('version', apertura['version'])
        return enviar(web, f'{API}{apertura["id"]}/', empresa, datos, 'patch')

    def test_cambia_el_encabezado_y_sube_la_version(self, web, empresa):
        apertura = creada(web, empresa)
        respuesta = self.editar(web, empresa, apertura, fuente='estado_situacion', fuente_detalle='Estado de situación 2025',
                                resultado_ejercicio='en_patrimonio', resultado_acumulado='-150.25', inventario_modo='reiniciar_kardex')
        assert respuesta.status_code == 200, respuesta.content
        datos = respuesta.json()
        assert list(datos) == ['apertura', 'configuracion']
        assert {k: datos['apertura'][k] for k in ('version', 'fuente', 'fuente_detalle', 'resultado_ejercicio',
                                                   'resultado_acumulado', 'inventario_modo')} == {
            'version': 2, 'fuente': 'estado_situacion', 'fuente_detalle': 'Estado de situación 2025',
            'resultado_ejercicio': 'en_patrimonio', 'resultado_acumulado': '-150.25', 'inventario_modo': 'reiniciar_kardex'}
        assert datos['configuracion']['version'] == 1   # el corte no cambió
        detalle = en(empresa, lambda: EventoApertura.objects.filter(apertura_id=apertura['id'], accion='modificada').get().detalle)
        assert detalle == {'version': 2, 'cambios': {'fuente': ['balance_comprobacion', 'estado_situacion'],
                                                      'fuente_detalle': ['Balance de comprobación firmado', 'Estado de situación 2025'],
                                                      'resultado_ejercicio': ['', 'en_patrimonio'],
                                                      'resultado_acumulado': [None, '-150.25'],
                                                      'inventario_modo': ['solo_conciliar', 'reiniciar_kardex']}}
        assert acciones(empresa, 'apertura_modificada') == [{'apertura': apertura['id'], 'version': 2, 'campos': [
            'fuente', 'fuente_detalle', 'inventario_modo', 'resultado_acumulado', 'resultado_ejercicio']}]

    def test_sin_cambios_no_sube_la_version(self, web, empresa):
        apertura = creada(web, empresa)
        respuesta = self.editar(web, empresa, apertura, fuente=apertura['fuente'], fecha_corte=apertura['fecha_corte'])
        assert respuesta.status_code == 200 and respuesta.json()['apertura']['version'] == 1
        assert acciones(empresa, 'apertura_modificada') == [] and len(acciones(empresa, 'inicio_contable_configurado')) == 1

    def test_mover_el_corte_cambia_la_configuracion(self, web, empresa):
        apertura = creada(web, empresa)
        datos = self.editar(web, empresa, apertura, fecha_corte='2025-11-30').json()
        assert datos['apertura']['fecha_corte'] == '2025-11-30' and datos['apertura']['version'] == 2
        assert {k: datos['configuracion'][k] for k in ('version', 'fecha_corte', 'contabilidad_desde', 'operaciones_desde')} == {
            'version': 2, 'fecha_corte': '2025-11-30', 'contabilidad_desde': '2025-12-01', 'operaciones_desde': '2025-12-01'}
        assert acciones(empresa, 'inicio_contable_configurado')[-1]['cambios'] == {
            'fecha_corte': ['2025-12-31', '2025-11-30'], 'contabilidad_desde': ['2026-01-01', '2025-12-01'],
            'operaciones_desde': ['2026-01-01', '2025-12-01']}

    def test_mover_el_corte_sobre_un_asiento(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        ayudas.asiento_directo(empresa, [(cuentas['caja'], '50.00', '0'), (cuentas['ventas'], '0', '50.00')],
                               fecha=date(2026, 2, 10))
        datos = rechazo(self.editar(web, empresa, apertura, fecha_corte='2026-02-28'), 409, 'rango_solapado')
        assert (datos['asientos'], datos['primera_fecha']) == (1, '2026-02-10')
        assert en(empresa, InicioContable.objects.get).fecha_corte == date(2025, 12, 31)
        assert leer(web, f'{API}{apertura["id"]}/', empresa)['apertura']['version'] == 1

    def test_historial_hasta(self, web, empresa):
        apertura = creada(web, empresa)
        assert errores(self.editar(web, empresa, apertura, historial_hasta='2025-12-31')) == {
            'historial_hasta': [TI['solo_historial']]}
        servicio_descartar(web, empresa, apertura)
        historial = creada(web, empresa, modalidad='historial', fecha_corte=None, historial_desde='2025-07-01',
                           historial_hasta='2025-09-30')
        datos = self.editar(web, empresa, historial, historial_hasta='2025-10-31').json()
        assert (datos['configuracion']['operaciones_desde'], datos['configuracion']['fecha_corte']) == ('2025-11-01', '2025-06-30')
        assert datos['apertura']['version'] == historial['version']   # el corte de la apertura no cambió
        datos = self.editar(web, empresa, historial, fecha_corte='2025-05-31').json()   # mover el corte mueve el inicio
        assert (datos['configuracion']['historial_desde'], datos['apertura']['fecha_corte']) == ('2025-06-01', '2025-05-31')
        assert errores(self.editar(web, empresa, datos['apertura'], fecha_corte='2025-12-31')) == {
            'historial_hasta': [TI['hasta_antes']]}

    def test_lo_que_no_se_cambia_en_un_borrador(self, web, empresa):
        apertura = creada(web, empresa)
        assert errores(self.editar(web, empresa, apertura, modalidad='historial', sin_saldos=True)) == {
            'modalidad': [T['fijo']], 'sin_saldos': [T['fijo']]}

    def test_validacion(self, web, empresa):
        apertura = creada(web, empresa)
        assert errores(self.editar(web, empresa, apertura, fuente='otra', resultado_ejercicio='otro', resultado_acumulado='1,234.567',
                                   inventario_modo='otro', fecha_corte='2099-01-01')) == {
            'fecha_corte': [TI['corte_futuro']], 'fuente': [T['fuente']], 'resultado_ejercicio': [T['resultado_ejercicio']],
            'resultado_acumulado': [T['resultado_acumulado']], 'inventario_modo': [T['inventario_modo']]}
        assert errores(enviar(web, f'{API}{apertura["id"]}/', empresa, {'fuente': 'estado_situacion'}, 'patch')) == {
            'version': [T['version_falta']]}

    def test_version_vieja(self, web, empresa):
        apertura = creada(web, empresa)
        self.editar(web, empresa, apertura, fuente='estado_situacion')
        datos = rechazo(self.editar(web, empresa, apertura, fuente='sistema_anterior'), 409, 'version')
        assert datos['apertura']['version'] == 2 and datos['apertura']['fuente'] == 'estado_situacion'
        # la versión va antes que la validación: con la vieja, los demás errores hablarían de otro estado
        rechazo(self.editar(web, empresa, apertura, fuente='otra'), 409, 'version')

    def test_solo_el_borrador_se_edita(self, web, empresa):
        apertura = creada(web, empresa)
        en(empresa, lambda: Apertura.objects.filter(pk=apertura['id']).update(estado='en_revision'))
        datos = rechazo(self.editar(web, empresa, apertura, fuente='estado_situacion'), 409, 'estado')
        assert (datos['estado'], datos['permitidos']) == ('en_revision', ['borrador'])
        rechazo(self.editar(web, empresa, apertura, fuente='otra'), 409, 'estado')   # el estado antes que la validación

    def test_ambitos_que_no_aplican(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        apertura = mapeada(web, empresa, apertura, [linea(cuentas['clientes'], '10.00'), linea(cuentas['capital'], None, '10.00')])
        apertura = apertura['apertura']
        assert errores(self.editar(web, empresa, apertura, ambitos_no_aplican=[
            {'ambito': 'clientes', 'nota': 'No vende a crédito.'}, {'ambito': 'proveedores', 'nota': ''},
            {'ambito': 'otro', 'nota': 'x'}, {'ambito': 'proveedores', 'nota': 'Otra vez.'}, 'texto'])) == {
            'ambitos_no_aplican.0.ambito': [T['ambito_con_cuentas']], 'ambitos_no_aplican.1.nota': [T['nota_ambito']],
            'ambitos_no_aplican.2.ambito': [T['ambito']], 'ambitos_no_aplican.3.ambito': [T['ambito_repetido']],
            'ambitos_no_aplican.4': [T['ambitos']]}
        assert errores(self.editar(web, empresa, apertura, ambitos_no_aplican={'ambito': 'bancos'})) == {
            'ambitos_no_aplican': [T['ambitos']]}
        datos = self.editar(web, empresa, apertura, ambitos_no_aplican=[{'ambito': 'activos', 'nota': '  Sin activos fijos.  '}])
        assert datos.json()['apertura']['ambitos_no_aplican'] == [{'ambito': 'activos', 'nota': 'Sin activos fijos.'}]
        # con la declaración, una cuenta de ese detalle no entra a la apertura sin quitarla antes
        actual = datos.json()['apertura']
        assert errores(mapear(web, empresa, actual, [linea(cuentas['equipos'], '10.00'), linea(cuentas['capital'], None, '10.00')])) == {
            'lineas.0.cuenta_id': [T['cuenta_no_aplica'].format(ambito='activos fijos', codigo='1.2.01')]}


def servicio_descartar(web, empresa, apertura, motivo='Se rehace con otra modalidad.'):
    version = leer(web, f'{API}{apertura["id"]}/', empresa)['apertura']['version']
    respuesta = enviar(web, f'{API}{apertura["id"]}/descartar/', empresa, {'version': version, 'motivo': motivo})
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()['apertura']


# ---------------------------------------------------------------- mapear (captura directa)

class TestMapear:

    def test_alta_con_la_forma_de_la_respuesta(self, web, empresa, cuentas, admin):
        apertura = creada(web, empresa)
        datos = mapeada(web, empresa, apertura, [*balance(cuentas), linea(cuentas['clientes'])])
        assert list(datos) == ['apertura', 'lineas', 'retiradas'] and datos['retiradas'] == 0
        assert datos['apertura'] == {'id': apertura['id'], 'version': 2, 'estado': 'borrador', 'debe': None, 'haber': None,
                                     'diferencia': None,   # un importe desconocido: los totales también lo son
                                     'pendientes': {**SIN_PENDIENTES, 'importe_pendiente': 1}}
        caja, capital, clientes = datos['lineas']
        assert caja == {'id': caja['id'], 'orden': 1, 'cuenta': {'id': cuentas['caja'].pk, 'codigo': '1.1.01', 'nombre': 'Caja',
                                                                 'clase': 'activo'},
                        'rubro': 'Caja', 'codigo_origen': '', 'debe': '10000.00', 'haber': '0.00', 'detalle': '',
                        'es_resultado_ejercicio': False, 'retirada': False,
                        'auxiliares': {'estado': 'sin_declarar', 'detallado': '0.00', 'filas': 0}, 'filas_origen': []}
        assert (capital['debe'], capital['haber']) == ('0.00', '10000.00')
        assert (clientes['debe'], clientes['haber'], clientes['detalle'], clientes['auxiliares']['estado']) == (
            None, None, 'cliente', 'sin_detalle')   # desconocido es null, nunca cero; el detalle se copia de la cuenta
        assert eventos(empresa, apertura['id'])[-1] == ('mapeada', '', '')
        assert acciones(empresa, 'apertura_modificada') == [{'apertura': apertura['id'], 'version': 2, 'accion': 'mapear',
                                                             'altas': 3, 'cambios': 0, 'retiradas': 0, 'lote_id': None}]
        # con el importe conocido cuadra; la diferencia la calcula el servidor (debe − haber)
        datos = mapeada(web, empresa, datos['apertura'], [*balance(cuentas), linea(cuentas['clientes'], '50.00')])
        assert (datos['apertura']['debe'], datos['apertura']['haber'], datos['apertura']['diferencia']) == (
            '10050.00', '10000.00', '50.00')

    def test_mapear_dos_veces_no_borra_ni_cambia_ids(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        primera = mapeada(web, empresa, apertura, [*balance(cuentas), linea(cuentas['bancos'], '500.00'),
                                                   linea(cuentas['proveedores'], None, '500.00')])
        ids = {l['cuenta']['codigo']: l['id'] for l in primera['lineas']}
        segunda = mapeada(web, empresa, primera['apertura'], [linea(cuentas['caja'], '9000.00'), linea(cuentas['capital'], None, '9500.00'),
                                                              linea(cuentas['bancos'], '500.00')])
        assert segunda['retiradas'] == 1
        por_codigo = {l['cuenta']['codigo']: l for l in segunda['lineas']}
        assert {c: l['id'] for c, l in por_codigo.items()} == ids   # las que siguen conservan su id; ninguna se borró
        assert (por_codigo['2.1.01']['retirada'], por_codigo['2.1.01']['debe'], por_codigo['2.1.01']['haber']) == (True, None, None)
        assert (segunda['apertura']['debe'], segunda['apertura']['haber']) == ('9500.00', '9500.00')   # la retirada no suma
        assert acciones(empresa, 'apertura_modificada')[-1]['cambios'] == 2
        # volver a incluir su cuenta reutiliza la línea retirada
        tercera = mapeada(web, empresa, segunda['apertura'], [linea(cuentas['caja'], '9000.00'),
                                                              linea(cuentas['capital'], None, '9500.00'),
                                                              linea(cuentas['bancos'], '500.00'), linea(cuentas['proveedores'], None, '1.00')])
        proveedores = next(l for l in tercera['lineas'] if l['cuenta']['codigo'] == '2.1.01')
        assert (proveedores['id'], proveedores['retirada'], proveedores['haber']) == (ids['2.1.01'], False, '1.00')
        assert en(empresa, lambda: LineaApertura.objects.filter(apertura_id=apertura['id']).count()) == 4

    def test_las_lineas_sin_cuenta_se_emparejan_por_orden(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        primera = mapeada(web, empresa, apertura, [linea(None, '10.00', rubro='Fondo rotativo'), linea(None, None, '10.00', rubro='Otros')])
        ids = [l['id'] for l in primera['lineas']]
        segunda = mapeada(web, empresa, primera['apertura'], [linea(None, '20.00', rubro='Fondo'), linea(None, None, '20.00', rubro='Otros')])
        assert [l['id'] for l in segunda['lineas']] == ids and segunda['apertura']['pendientes']['sin_cuenta'] == 2
        tercera = mapeada(web, empresa, segunda['apertura'], [linea(None, '20.00')])
        assert [(l['id'], l['retirada']) for l in tercera['lineas']] == [(ids[0], False), (ids[1], True)]

    def test_quitar_una_linea_con_auxiliares_vigentes(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        datos = mapeada(web, empresa, apertura, [linea(cuentas['clientes'], '100.00'), linea(cuentas['capital'], None, '100.00')])
        clientes = datos['lineas'][0]
        with company_context(empresa):
            auxiliar = AuxiliarApertura.objects.create(
                apertura_id=apertura['id'], linea_id=clientes['id'], cuenta=cuentas['clientes'], naturaleza='cliente',
                saldo_inicial=Decimal('100.00'), tercero_nombre='CLIENTE FICTICIO', creado_por_nombre=ayudas.AUTOR[1])
        # cambiar su importe no la quita: una sustituta, que nace con auxiliares, se mapea igual
        datos = mapeada(web, empresa, datos['apertura'], [linea(cuentas['clientes'], '120.00'), linea(cuentas['capital'], None, '120.00')])
        quitar = mapear(web, empresa, datos['apertura'], [linea(cuentas['caja'], '120.00'), linea(cuentas['capital'], None, '120.00')])
        cuerpo = rechazo(quitar, 409, 'linea_con_auxiliares')
        assert (cuerpo['linea_id'], cuerpo['auxiliares']) == (clientes['id'], 1)
        # un envío que no se puede leer no «quita» nada: es un 400, no el 409 de la línea con auxiliares
        assert errores(mapear(web, empresa, datos['apertura'], 'no es una lista')) == {'lineas': [T['lineas']]}
        assert en(empresa, lambda: LineaApertura.objects.get(pk=clientes['id']).debe) == Decimal('120.00')
        # con solo auxiliares anulados, la línea queda retirada (no se borra: sus auxiliares la referencian)
        with company_context(empresa):
            AuxiliarApertura.objects.filter(pk=auxiliar.pk).update(estado='anulado', anulado_en=timezone.now(), motivo_anulacion='x')
        datos = mapeada(web, empresa, datos['apertura'], [linea(cuentas['caja'], '120.00'), linea(cuentas['capital'], None, '120.00')])
        assert next(l for l in datos['lineas'] if l['id'] == clientes['id'])['retirada'] is True

    def test_validacion_por_posicion(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        inactiva = en(empresa, lambda: Cuenta.objects.create(codigo='1.1.99', nombre='Antigua', tipo='movimiento', activa=False,
                                                             clase='activo'))
        respuesta = mapear(web, empresa, apertura, [
            linea(cuentas['caja'], '10.001'), linea(cuentas['bancos'], '-5.00'), linea(cuentas['clientes'], '5.00', '5.00'),
            linea(cuentas['proveedores'], '0', None), linea(inactiva, '1.00'), linea(cuentas['caja'], '1.00'),
            linea(cuentas['ventas'], None, '1.00', es_resultado_ejercicio=True), linea(cuentas['resultados'], 'abc'),
            {'cuenta_id': 'x', 'debe': '1.00'}, 'texto', linea(cuentas['capital'], None, '1.00', rubro='r' * 201),
            linea(cuentas['capital'], None, '1.00', es_resultado_ejercicio='quizá')])
        assert errores(respuesta) == {
            'lineas.0.debe': [T['decimales']], 'lineas.1.debe': [T['negativo']], 'lineas.2.haber': [T['dos_lados']],
            'lineas.3.debe': [T['cero']], 'lineas.4.cuenta_id': [T['cuenta_inactiva'].format(codigo='1.1.99')],
            'lineas.5.cuenta_id': ['La cuenta 1.1.01 ya está en la línea 1.'],
            'lineas.6.es_resultado_ejercicio': [T['resultado_patrimonio']], 'lineas.7.debe': [T['importe']],
            'lineas.8.cuenta_id': [T['cuenta_id']], 'lineas.9': [T['linea']], 'lineas.10.rubro': [T['rubro_largo']],
            'lineas.11.cuenta_id': ['La cuenta 3.1.01 ya está en la línea 11.'],
            'lineas.11.es_resultado_ejercicio': [T['es_resultado']]}
        # nada escrito y la versión sigue
        assert en(empresa, lambda: LineaApertura.objects.count()) == 0
        assert leer(web, f'{API}{apertura["id"]}/', empresa)['apertura']['version'] == 1

    def test_una_cuenta_de_grupo_da_su_codigo(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        assert errores(mapear(web, empresa, apertura, [linea(cuentas['activo'], '1.00'), linea(cuentas['capital'], None, '1.00')]),
                       'cuenta_de_grupo') == {'lineas.0.cuenta_id': [T['cuenta_de_grupo'].format(codigo='1')]}

    def test_importes_escritos_de_varias_formas(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        datos = mapeada(web, empresa, apertura, [linea(cuentas['caja'], '1.234,56'), linea(cuentas['bancos'], '1,000.44'),
                                                 linea(cuentas['clientes'], 765), linea(cuentas['capital'], None, '$ 3000,00')])
        assert [(l['debe'], l['haber']) for l in datos['lineas']] == [('1234.56', '0.00'), ('1000.44', '0.00'), ('765.00', '0.00'),
                                                                      ('0.00', '3000.00')]
        assert datos['apertura']['diferencia'] == '0.00'
        assert errores(mapear(web, empresa, datos['apertura'], [linea(cuentas['caja'], True)])) == {'lineas.0.debe': [T['importe']]}

    def test_el_resultado_del_ejercicio_va_en_patrimonio(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        datos = mapeada(web, empresa, apertura, [linea(cuentas['caja'], '100.00'),
                                                 linea(cuentas['resultados'], None, '100.00', es_resultado_ejercicio=True)])
        assert [l['es_resultado_ejercicio'] for l in datos['lineas']] == [False, True]

    def test_lineas_y_lote_a_la_vez_o_sin_lista(self, web, empresa):
        apertura = creada(web, empresa)
        assert errores(enviar(web, f'{API}{apertura["id"]}/mapear/', empresa, {'version': 1, 'lineas': 'x'})) == {
            'lineas': [T['lineas']]}
        assert errores(enviar(web, f'{API}{apertura["id"]}/mapear/', empresa, {'version': 1, 'lineas': [], 'lote_id': 999})) == {
            'lineas': [T['lineas_y_lote']]}
        assert errores(enviar(web, f'{API}{apertura["id"]}/mapear/', empresa, {'lineas': []})) == {
            'version': [T['version_falta']]}
        assert errores(enviar(web, f'{API}{apertura["id"]}/mapear/', empresa, {'version': 1, 'lineas': [{}] * 5001})) == {
            'lineas': [T['demasiadas_lineas']]}

    def test_cuenta_de_otra_empresa(self, web, empresa, empresa_b, cuentas):
        ajena = ayudas.plan_minimo(empresa_b)['caja']
        apertura = creada(web, empresa)
        datos = rechazo(mapear(web, empresa, apertura, [linea(cuentas['capital'], None, '1.00'), linea(ajena, '1.00')]), 404, 'no_existe')
        assert datos['errores'] == {'lineas.1.cuenta_id': [T['cuenta_no_existe']]}
        assert en(empresa, lambda: LineaApertura.objects.count()) == 0

    def test_version_y_estado_antes_que_la_validacion(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        mapeada(web, empresa, apertura, balance(cuentas))
        rechazo(mapear(web, empresa, apertura, [linea(cuentas['caja'], 'x')], version=1), 409, 'version')
        en(empresa, lambda: Apertura.objects.filter(pk=apertura['id']).update(estado='en_revision'))
        datos = rechazo(mapear(web, empresa, apertura, [linea(cuentas['caja'], 'x')], version=2), 409, 'estado')
        assert datos['permitidos'] == ['borrador']


# ---------------------------------------------------------------- líneas y detalle

class TestLineasYDetalle:

    def test_lineas_paginadas(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        mapeada(web, empresa, apertura, [*balance(cuentas), linea(cuentas['bancos'], '1.00'), linea(cuentas['proveedores'], None, '1.00')])
        datos = leer(web, f'{API}{apertura["id"]}/lineas/?pagina=2&por_pagina=3', empresa)
        assert list(datos) == ['apertura', 'lineas', 'paginacion']
        assert datos['paginacion'] == {'pagina': 2, 'por_pagina': 3, 'total': 4, 'paginas': 2}
        assert [l['orden'] for l in datos['lineas']] == [4]
        assert leer(web, f'{API}{apertura["id"]}/lineas/', empresa)['paginacion'] == {'pagina': 1, 'por_pagina': 100, 'total': 4,
                                                                                      'paginas': 1}
        for consulta, campo in (('pagina=0', 'pagina'), ('pagina=x', 'pagina'), ('por_pagina=501', 'por_pagina')):
            assert list(errores(web.get(con_empresa(f'{API}{apertura["id"]}/lineas/?{consulta}', empresa)))) == [campo]

    def test_detalle_con_su_historia(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        mapeada(web, empresa, apertura, balance(cuentas))
        datos = leer(web, f'{API}{apertura["id"]}/', empresa)
        assert list(datos) == ['apertura', 'archivos', 'ajustes', 'historial', 'capacidades']
        assert (datos['apertura']['debe'], datos['apertura']['lineas'], datos['archivos'], datos['ajustes']) == ('10000.00', 2, [], [])
        assert [(h['accion'], h['de_estado'], h['a_estado'], h['usuario']) for h in datos['historial']] == [
            ('creada', '', 'borrador', 'propietario.a'), ('mapeada', '', '', 'propietario.a')]
        assert datos['historial'][1]['detalle'] == {'version': 2, 'altas': 2, 'cambios': 0, 'retiradas': 0, 'lote_id': None}
        assert datos['capacidades']['editar'] is True

    def test_de_otra_empresa_no_existe(self, client, empresa, empresa_b, admin):
        ayudas.plan_minimo(empresa_b)
        ajena = ayudas.apertura_directa(empresa_b)
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        for metodo, ruta in (('get', f'{API}{ajena.pk}/'), ('get', f'{API}{ajena.pk}/lineas/'), ('patch', f'{API}{ajena.pk}/'),
                             ('post', f'{API}{ajena.pk}/mapear/'), ('post', f'{API}{ajena.pk}/descartar/')):
            respuesta = client.get(con_empresa(ruta, empresa)) if metodo == 'get' else enviar(client, ruta, empresa,
                                                                                              {'version': 1, 'lineas': [], 'motivo': 'x'}, metodo)
            assert rechazo(respuesta, 404, 'no_existe')['error'] == T['no_existe'], ruta
        assert en(empresa_b, lambda: Apertura.objects.get(pk=ajena.pk).version) == 1


# ---------------------------------------------------------------- descartar

class TestDescartar:

    def descartar(self, web, empresa, apertura, **datos):
        return enviar(web, f'{API}{apertura["id"]}/descartar/', empresa, {'version': apertura['version'], **datos})

    def test_descartar_libera_el_lugar_y_anula_los_auxiliares(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        datos = mapeada(web, empresa, apertura, [linea(cuentas['clientes'], '100.00'), linea(cuentas['capital'], None, '100.00')])
        with company_context(empresa):
            auxiliar = AuxiliarApertura.objects.create(
                apertura_id=apertura['id'], linea_id=datos['lineas'][0]['id'], cuenta=cuentas['clientes'], naturaleza='cliente',
                saldo_inicial=Decimal('100.00'), tercero_nombre='CLIENTE FICTICIO', creado_por_nombre=ayudas.AUTOR[1])
        assert errores(self.descartar(web, empresa, datos['apertura'])) == {'motivo': [T['motivo']]}
        respuesta = self.descartar(web, empresa, datos['apertura'], motivo='Se rehace con el balance firmado.')
        assert respuesta.status_code == 200, respuesta.content
        descartada = respuesta.json()['apertura']
        assert (descartada['estado'], descartada['version'], descartada['motivo']) == (
            'descartada', 3, 'Se rehace con el balance firmado.')
        with company_context(empresa):
            auxiliar.refresh_from_db()
            fila = Apertura.objects.get(pk=apertura['id'])
            assert (auxiliar.estado, auxiliar.motivo_anulacion) == ('anulado', servicio.MOTIVO_DESCARTE_AUXILIAR)
            assert fila.cerrado_por_nombre == 'propietario.a' and fila.cerrado_en is not None
            assert LineaApertura.objects.filter(apertura=fila).count() == 2   # nada se borra
        assert eventos(empresa, apertura['id'])[-1] == ('descartada', 'borrador', 'descartada')
        assert acciones(empresa, 'apertura_descartada')[0]['auxiliares_anulados'] == 1
        # el lugar de la apertura en preparación queda libre
        assert creada(web, empresa)['estado'] == 'borrador'
        assert leer(web, API, empresa)['apertura']['id'] != apertura['id']
        # descartada ya no está en preparación
        datos = rechazo(self.descartar(web, empresa, descartada, motivo='Otra vez.'), 409, 'estado')
        assert datos['permitidos'] == ['borrador', 'en_revision']

    def test_una_en_revision_tambien_se_descarta(self, web, empresa):
        apertura = creada(web, empresa)
        en(empresa, lambda: Apertura.objects.filter(pk=apertura['id']).update(estado='en_revision'))
        descartada = self.descartar(web, empresa, apertura, motivo='Falta el balance firmado.').json()['apertura']
        assert descartada['estado'] == 'descartada'
        assert eventos(empresa, apertura['id'])[-1] == ('descartada', 'en_revision', 'descartada')

    def test_version_vieja(self, web, empresa):
        apertura = creada(web, empresa)
        rechazo(self.descartar(web, empresa, {**apertura, 'version': 7}, motivo='x'), 409, 'version')
        rechazo(self.descartar(web, empresa, {**apertura, 'version': 7}), 409, 'version')   # antes que la validación
        assert aperturas(empresa) == [(apertura['id'], 'borrador')]


# ---------------------------------------------------------------- capacidades, registro y etapa del inicio

RUTA_DE_ACCION = {
    'editar': ('PATCH', f'{API}1/'), 'descartar': ('POST', f'{API}1/descartar/'), 'validar': ('POST', f'{API}1/validar/'),
    'enviar': ('POST', f'{API}1/enviar/'), 'devolver': ('POST', f'{API}1/devolver/'), 'confirmar': ('POST', f'{API}1/confirmar/'),
    'sustituir': ('POST', f'{API}1/sustituir/'), 'ajustar': ('POST', f'{API}1/ajustes/'), 'reversar': ('POST', f'{API}1/reversar/'),
    'cobrar': ('POST', f'{API}cartera/1/aplicaciones/'),
}


class TestCapacidades:

    def test_capacidades_solo_con_su_ruta(self):
        """Punto de unión con la parte siguiente y el corte 2: una acción se anuncia si y solo si su ruta existe (quien la
        publique la quita de apertura.SIN_CONSTRUIR)."""
        assert set(RUTA_DE_ACCION) == set(servicio.REGLAS_CAPACIDAD)
        for accion, (metodo, ruta) in RUTA_DE_ACCION.items():
            try:
                vista = resolve(ruta).func.view_class
                publicada = metodo in vista.permisos
            except Resolver404:
                publicada = False
            assert publicada is (accion not in servicio.SIN_CONSTRUIR), accion

    def test_por_rol_y_con_el_plan_vencido(self, client, empresa, cuentas):
        apertura = ayudas.apertura_directa(empresa)
        entrar_como(client, empresa, ROLE_READONLY)
        assert not any(leer(client, f'{API}{apertura.pk}/', empresa)['capacidades'].values())
        entrar_como(client, empresa, ROLE_ACCOUNTANT)
        assert leer(client, f'{API}{apertura.pk}/', empresa)['capacidades']['editar'] is True
        vencer(empresa)
        assert not any(leer(client, f'{API}{apertura.pk}/', empresa)['capacidades'].values())

    def test_la_funcion_en_el_registro(self, web):
        funcion = capacidades.funcion_de('apertura')
        assert (funcion.construccion, funcion.ruta, funcion.permisos) == (
            capacidades.DISPONIBLE, API, {'ver': 'view_apertura', 'preparar': 'add_apertura',
                                          'confirmar': 'change_confirmacion_apertura'})
        for codigo in ('cartera_inicial', 'historico'):
            assert capacidades.funcion_de(codigo).construccion == capacidades.PENDIENTE
        anunciada = web.get(CAPACIDADES).json()['funciones']['apertura']
        assert anunciada == {'nombre': 'Apertura contable', 'ambito': 'contabilidad', 'estado': 'disponible', 'causa': None,
                             'texto': None, 'acciones': {'ver': True, 'preparar': True, 'confirmar': True}, 'faltan': [],
                             'avisos': []}

    def test_plan_de_cuentas_vacio_es_un_dato_por_completar(self, client, empresa, admin):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        funcion = client.get(CAPACIDADES).json()['funciones']['apertura']
        assert (funcion['estado'], [f['codigo'] for f in funcion['faltan']], funcion['avisos']) == (
            'datos_por_completar', ['plan_cuentas_vacio'], [])
        assert leer(client, API, empresa)['apertura'] is None   # la consulta responde igual

    def test_avisos(self, web, empresa, cuentas):
        def avisos():
            return {a['codigo']: a for a in web.get(CAPACIDADES).json()['funciones']['apertura']['avisos']}
        assert avisos() == {}
        en(empresa, lambda: Cuenta.objects.create(codigo='1.1.50', nombre='Sin clase', tipo='movimiento'))
        sin_clase = avisos()['cuentas_sin_clase']
        assert {k: sin_clase[k] for k in ('cantidad', 'url', 'decision')} == {'cantidad': 1, 'url': None, 'decision': None}
        assert sin_clase['recurso'] == {'tipo': 'plan_cuentas', 'id': None, 'api': '/contabilidad/api/cuentas/'}
        apertura = creada(web, empresa)
        mapeada(web, empresa, apertura, [linea(cuentas['clientes'], '100.00'), linea(cuentas['capital'], None, '100.00')])
        assert avisos()['auxiliares_incompletos']['cantidad'] == 1
        en(empresa, lambda: Cuenta.objects.filter(auxiliar__in=('banco', 'activo')).update(auxiliar=''))
        assert avisos()['cuentas_sin_auxiliar']['texto'].startswith('Ninguna cuenta está declarada como de bancos, activos fijos')
        with company_context(empresa):
            linea_ = LineaApertura.objects.get(apertura_id=apertura['id'], cuenta=cuentas['clientes'])
            AuxiliarApertura.objects.create(apertura_id=apertura['id'], linea=linea_, cuenta=cuentas['clientes'],
                                            naturaleza='cliente', saldo_inicial=Decimal('100.00'), tercero_nombre='CLIENTE',
                                            cxc_id=987_654_321, creado_por_nombre=ayudas.AUTOR[1])
        sin = avisos()
        assert 'auxiliares_incompletos' not in sin and sin['vinculos_rotos']['cantidad'] == 1


class TestEtapaDelInicio:

    def etapa(self, web):
        return web.get('/contabilidad/api/inicio/').json()['etapas']['apertura']

    def test_cada_estado(self, web, empresa, cuentas):
        assert self.etapa(web) == {'estado': 'sin_configurar', 'fecha': None, 'causa': None}
        apertura = creada(web, empresa)
        assert self.etapa(web) == {'estado': 'pendiente', 'fecha': '2025-12-31', 'causa': None}
        en(empresa, lambda: Apertura.objects.filter(pk=apertura['id']).update(estado='en_revision'))
        assert self.etapa(web)['estado'] == 'en_revision'
        en(empresa, lambda: Apertura.objects.filter(pk=apertura['id']).update(estado='descartada', motivo='x'))
        assert self.etapa(web)['estado'] == 'pendiente'   # configurada, sin apertura en curso ni confirmada
        ayudas.apertura_confirmada_directa(empresa, cuentas)
        assert self.etapa(web) == {'estado': 'confirmada', 'fecha': '2025-12-31', 'causa': None}


# ---------------------------------------------------------------- punto de unión con el candado

class TestCandado:

    def test_sin_fila_es_un_dato_por_completar(self, empresa):
        with company_context(empresa), pytest.raises(api.Rechazo) as error:
            with inicio_contable.libro():
                pass
        cuerpo = json.loads(error.value.respuesta().content)
        assert (error.value.estado, cuerpo['codigo'], [f['codigo'] for f in cuerpo['faltan']]) == (
            409, 'datos_por_completar', ['inicio_sin_configurar'])

    def test_crea_la_fila_y_la_devuelve(self, empresa):
        ahora = timezone.now()
        campos = {**inicio_contable.fechas('saldos', date(2025, 12, 31)), 'creado_en': ahora, 'creado_por_nombre': 'x'}
        with company_context(empresa):
            with inicio_contable.libro(crear=campos) as inicio:
                assert inicio_contable.creada(inicio, ahora)
            with inicio_contable.libro(crear={**campos, 'fecha_corte': date(2024, 1, 1)}) as otra:
                assert otra.pk == inicio.pk and otra.fecha_corte == date(2025, 12, 31)   # con fila, `crear` no hace nada
                assert not inicio_contable.creada(otra, timezone.now())

    def test_la_configuracion_pasa_por_el_candado(self, web, empresa, monkeypatch):
        llamadas = []
        original = inicio_contable.libro

        def espia(crear=None):
            llamadas.append(crear is not None)
            return original(crear=crear)
        monkeypatch.setattr(inicio_contable, 'libro', espia)
        apertura = creada(web, empresa)
        enviar(web, f'{API}{apertura["id"]}/', empresa, {'version': 1, 'fuente': 'estado_situacion'}, 'patch')
        enviar(web, f'{API}{apertura["id"]}/', empresa, {'version': 2, 'fecha_corte': '2025-11-30'}, 'patch')
        assert llamadas == [True, False]   # crear (con `crear`) y mover el corte; cambiar la fuente no toma el candado


# ---------------------------------------------------------------- roles, pestaña, licencia

def rutas_de(apertura_id, lote_id=1, respaldo_id=1):
    return [('get', API, servicio.VER), ('post', API, servicio.PREPARAR),
            ('get', f'{API}{apertura_id}/', servicio.VER), ('patch', f'{API}{apertura_id}/', servicio.PREPARAR),
            ('post', f'{API}{apertura_id}/importar/', servicio.PREPARAR), ('get', f'{API}importar/{lote_id}/', servicio.VER),
            ('post', f'{API}{apertura_id}/mapear/', servicio.PREPARAR), ('get', f'{API}{apertura_id}/lineas/', servicio.VER),
            ('post', f'{API}{apertura_id}/respaldos/', servicio.PREPARAR),
            ('get', f'{API}respaldos/{respaldo_id}/descargar/', servicio.VER),
            ('post', f'{API}respaldos/{respaldo_id}/anular/', servicio.PREPARAR),
            ('post', f'{API}{apertura_id}/descartar/', servicio.PREPARAR)]


class TestAcceso:

    @pytest.mark.parametrize('rol, ver, preparar', [(ROLE_OWNER, True, True), (ROLE_ADMIN, True, True),
                                                    (ROLE_ACCOUNTANT, True, True), (ROLE_READONLY, True, False),
                                                    (ROLE_SELLER, False, False), (ROLE_CLIENT, False, False)])
    def test_matriz_de_los_seis_roles(self, client, empresa, cuentas, rol, ver, preparar):
        apertura = ayudas.apertura_directa(empresa)
        entrar_como(client, empresa, rol)
        for metodo, ruta, permiso in rutas_de(apertura.pk):
            respuesta = (client.get(con_empresa(ruta, empresa)) if metodo == 'get'
                         else enviar(client, ruta, empresa, {'version': 1}, metodo))
            permitido = ver if permiso == servicio.VER else preparar
            sin_permiso = respuesta.status_code == 403 and respuesta.json().get('codigo') == 'sin_permiso'
            assert sin_permiso is not permitido, (rol, metodo, ruta, respuesta.status_code, respuesta.content[:200])
        assert en(empresa, lambda: Apertura.objects.get(pk=apertura.pk).version) == 1   # ningún envío de prueba escribió

    def test_pestana_de_otra_empresa(self, web, empresa, empresa_b):
        apertura = creada(web, empresa)
        otra = empresa.pk + 999
        for metodo, ruta, _ in rutas_de(apertura['id']):
            if metodo == 'get':
                respuesta = web.get(f'{ruta}?empresa={otra}')
            else:
                respuesta = getattr(web, metodo)(f'{ruta}?empresa={otra}', json.dumps({'empresa': empresa.pk}),
                                                 content_type='application/json')
            assert rechazo(respuesta, 409, 'empresa_cambiada'), ruta
            if metodo != 'get':   # la empresa solo en el cuerpo, o en ningún lado
                cuerpo = getattr(web, metodo)(ruta, json.dumps({'empresa': otra}), content_type='application/json')
                assert rechazo(cuerpo, 409, 'empresa_cambiada'), ruta
                assert rechazo(getattr(web, metodo)(ruta, json.dumps({}), content_type='application/json'), 409, 'sin_empresa'), ruta
        # multipart (importar y respaldos): la empresa como campo del formulario
        respuesta = web.post(f'{API}{apertura["id"]}/importar/', {'empresa': otra, 'clave': ayudas.clave('pestana')})
        rechazo(respuesta, 409, 'empresa_cambiada')
        assert leer(web, f'{API}{apertura["id"]}/', empresa)['apertura']['version'] == 1

    def test_dos_empresas_y_la_pestana_vieja(self, client, empresa, empresa_b, admin, cuentas):
        ayudas.plan_minimo(empresa_b)
        Membership.objects.create(user=admin, company=empresa_b, group=Group.objects.get(name=ROLE_OWNER))
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        de_a = creada(client, empresa)
        client.post('/empresas/cambiar/', {'company': empresa_b.pk})
        # la pestaña de A sigue abierta: ni lee ni escribe en B
        rechazo(client.get(f'{API}?empresa={empresa.pk}'), 409, 'empresa_cambiada')
        rechazo(enviar(client, f'{API}{de_a["id"]}/mapear/', empresa, {'version': 1, 'lineas': []}), 409, 'empresa_cambiada')
        rechazo(client.get(con_empresa(f'{API}{de_a["id"]}/', empresa_b)), 404, 'no_existe')
        de_b = creada(client, empresa_b)   # cada empresa tiene su propia apertura en preparación
        assert (aperturas(empresa), aperturas(empresa_b)) == ([(de_a['id'], 'borrador')], [(de_b['id'], 'borrador')])

    def test_plan_vencido_consulta_y_no_guarda(self, web, empresa, cuentas):
        apertura = creada(web, empresa)
        vencer(empresa)
        for metodo, ruta, permiso in rutas_de(apertura['id']):
            if metodo == 'get':
                assert web.get(con_empresa(ruta, empresa)).status_code in (200, 404), ruta
                continue
            respuesta = enviar(web, ruta, empresa, {'version': 1, 'clave': ayudas.clave('vencido'), **DATOS}, metodo)
            assert respuesta.status_code == 403 and respuesta.json()['codigo'] == 'plan', ruta
        assert leer(web, API, empresa)['apertura']['version'] == 1 and len(aperturas(empresa)) == 1

    def test_complemento_cerrado(self, web, empresa, settings):
        apertura = creada(web, empresa)
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = []
        for metodo, ruta, _ in rutas_de(apertura['id']):
            respuesta = web.get(con_empresa(ruta, empresa)) if metodo == 'get' else enviar(web, ruta, empresa, {'version': 1}, metodo)
            cuerpo = respuesta.json()
            assert (respuesta.status_code, cuerpo['codigo'], cuerpo['causa']) == (403, 'complemento_pendiente', 'licencia'), ruta
        # Pestaña vieja con el complemento cerrado: 409 antes que la licencia, con la empresa en la consulta y también solo en
        # el cuerpo JSON. La excepción de la decisión común 6 (solo en el cuerpo → 403 de licencia) ya no se da: el bloque 1
        # lee `empresa` también del cuerpo JSON (core/tenancy/pestanas.py), y manda el código real.
        rechazo(web.post(f'{API}{apertura["id"]}/descartar/?empresa={empresa.pk + 999}', json.dumps({'version': 1}),
                         content_type='application/json'), 409, 'empresa_cambiada')
        rechazo(web.post(f'{API}{apertura["id"]}/descartar/', json.dumps({'empresa': empresa.pk + 999, 'version': 1}),
                         content_type='application/json'), 409, 'empresa_cambiada')


# ---------------------------------------------------------------- rendimiento

def plan_grande(empresa, n):
    """`n` cuentas de movimiento con clase (inserción directa: es preparación de datos, no el servicio)."""
    with company_context(empresa):
        grupo = Cuenta.objects.create(codigo='9', nombre='GRUPO DE PRUEBA', tipo='grupo', clase='activo')
        Cuenta.objects.bulk_create([Cuenta(company=empresa, codigo=f'9.{i:05d}', codigo_norm=norma_codigo(f'9.{i:05d}'),
                                           nombre=f'Cuenta {i}', tipo='movimiento', clase='activo', padre=grupo)
                                    for i in range(n)], batch_size=1000)
        return list(Cuenta.objects.filter(padre=grupo).order_by('codigo').values_list('pk', flat=True))


def consultas(funcion):
    with CaptureQueriesContext(connection) as capturadas:
        resultado = funcion()
    return len(capturadas), resultado


class TestRendimiento:

    def test_5000_lineas_sin_consultas_por_linea(self, web, empresa, cuentas):
        ids = plan_grande(empresa, 5000)
        apertura = creada(web, empresa)

        def lineas(n, importe):
            return [{'cuenta_id': pk, 'rubro': f'R{i}', 'debe': importe, 'haber': None} for i, pk in enumerate(ids[:n])]
        n_pocas, r = consultas(lambda: mapear(web, empresa, apertura, lineas(10, '1.00')))
        assert r.status_code == 200
        n_todas, r = consultas(lambda: mapear(web, empresa, r.json()['apertura'], lineas(5000, '2.00')))
        assert r.status_code == 200 and len(r.json()['lineas']) == 5000 and r.json()['apertura']['debe'] == '10000.00'
        # Las inserciones y los cambios van por lotes: en PostgreSQL, uno cada 1 000 filas; SQLite los parte además por
        # su límite de variables por sentencia. Lo que nunca crece es una consulta por línea.
        lotes = 5 if connection.vendor == 'postgresql' else 5000 * 16 // 999 + 5
        assert n_todas <= n_pocas + 2 * lotes, (n_pocas, n_todas)
        version = r.json()['apertura']['version']
        n_retiro, r = consultas(lambda: mapear(web, empresa, {'id': apertura['id'], 'version': version}, lineas(1, '3.00')))
        assert r.status_code == 200 and r.json()['retiradas'] == 4999 and n_retiro <= n_pocas + 2 * lotes
        n_consulta, datos = consultas(lambda: leer(web, API, empresa))
        n_lineas, _ = consultas(lambda: leer(web, f'{API}{apertura["id"]}/lineas/?por_pagina=500', empresa))
        n_detalle, _ = consultas(lambda: leer(web, f'{API}{apertura["id"]}/', empresa))
        assert max(n_consulta, n_lineas, n_detalle) <= 30, (n_consulta, n_lineas, n_detalle)
