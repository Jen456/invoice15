"""Libro diario mínimo (Parte A de contable/bloque-2-especificacion.md), con los servicios:

- el candado (`candado.libro`, su marca y su creación) y lo que exige el candado;
- `diario.contabilizar`: cada rechazo no escribe ni consume número; fechas (ordinario, apertura, cierre del ejercicio del
  corte, futura, período cerrado); huella canónica v1; acumulados por cuenta y mes con sus columnas de apertura y de cierre;
- `diario.reversar`: una vez, la misma clave es `repetido`, el reverso no se reversa, los acumulados vuelven a su valor y la
  cuenta desactivada se admite;
- propiedad: tras una secuencia aleatoria de contabilizar y reversar, Σ debe = Σ haber, acumulados = Σ líneas (total y por
  tipo), numeración sin huecos y `verificar` en verde;
- lectura: GET diario/, diario/<id>/ e integridad/, la orden `verificar_libro`, y la provisionalidad (`reportes`);
- cuentas: clase y auxiliar en GET y PATCH, `cuentas/clasificar/`, las reglas de reclasificar, `tiene_movimientos` y la
  columna «clase» de la importación;
- matriz de roles y negativas comunes (pestaña vieja, método, plan vencido), la función `diario_mayor` de capacidades y
  `registro_clave`;
- recorridos ast: solo diario.py escribe en el libro; ningún literal de código de cuenta ni `get_or_create` de `Cuenta`.

Corre en SQLite y en PostgreSQL. La concurrencia y los disparadores van en tests/test_zz_diario_concurrencia_pg.py y en
tests/test_zz_libro_inmutable_pg.py."""
import ast
import hashlib
import json
import random
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone

from core.contabilidad import api, candado, capacidades, cuentas, diario, periodos, registro_clave, reportes
from core.contabilidad.models import (Apertura, Asiento, AuxiliarApertura, Cuenta, EjercicioContable, InicioContable,
                                      LineaApertura, LineaAsiento, PeriodoContable, RegistroClave, SaldoCuentaMes)
from core.tenancy.context import company_context
from core.tenancy.models import (ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog)
from tests import ayudas_contables as ac
from tests import helpers

pytestmark = pytest.mark.django_db

BASE = Path(settings.BASE_DIR)
DIARIO, INTEGRIDAD, CLASIFICAR, CUENTAS = ('/contabilidad/api/diario/', '/contabilidad/api/integridad/',
                                           '/contabilidad/api/cuentas/clasificar/', '/contabilidad/api/cuentas/')
CORTE = date(2025, 12, 31)
ENERO = date(2026, 1, 15)


@pytest.fixture
def f(empresa):
    """Plan mínimo e inicio contable por saldos (corte 31/12/2025) en la empresa A, con la empresa activa."""
    cuentas_a = ac.plan_minimo(empresa)
    inicio = ac.inicio_directo(empresa, CORTE)
    with company_context(empresa):
        yield SimpleNamespace(empresa=empresa, c=cuentas_a, inicio=inicio)


def venta(f, importe=100, **otros):
    """Un asiento `origen` de una venta ficticia: clientes al debe, ventas al haber."""
    otros.setdefault('origen', ('venta', 9000 + Asiento.objects.count(), 'emision'))
    return ac.contabilizar(f.empresa, [(f.c['clientes'], importe, 0), (f.c['ventas'], 0, importe)], tipo='origen', **otros)


def libro_intacto(f):
    """Lo que el libro tiene ahora: si un rechazo escribiera algo (o consumiera un número), cambiaría."""
    return (Asiento.objects.count(), LineaAsiento.objects.count(), list(SaldoCuentaMes.objects.order_by('pk').values()),
            list(EjercicioContable.objects.order_by('pk').values('anio', 'ultimo_numero')))


def saldo(cuenta, anio=2026, mes=1):
    fila = SaldoCuentaMes.objects.filter(cuenta=cuenta, anio=anio, mes=mes).values(
        'debe', 'haber', 'apertura_debe', 'apertura_haber', 'cierre_debe', 'cierre_haber').first()
    return {k: f'{v:.2f}' for k, v in fila.items()} if fila else None


def apertura_confirmada(f, importe=10000, resultado_ejercicio=''):
    """Una apertura confirmada con su asiento por diario.contabilizar (la confirmación real es de la Parte B)."""
    apertura = ac.apertura_directa(f.empresa, fecha_corte=f.inicio.fecha_corte)
    LineaApertura.objects.create(apertura=apertura, orden=1, cuenta=f.c['caja'], debe=Decimal(importe), rubro_origen='Caja')
    LineaApertura.objects.create(apertura=apertura, orden=2, cuenta=f.c['capital'], haber=Decimal(importe), rubro_origen='Capital')
    asiento = ac.contabilizar(f.empresa, [(f.c['caja'], importe, 0), (f.c['capital'], 0, importe)], tipo='apertura',
                              fecha=f.inicio.fecha_corte, concepto='Apertura contable', motivo='',
                              origen=('apertura', apertura.pk, 'confirmacion'))
    Apertura.objects.filter(pk=apertura.pk).update(estado='confirmada', asiento=asiento, total_debe=Decimal(importe),
                                                   total_haber=Decimal(importe), confirmado_en=timezone.now(),
                                                   resultado_ejercicio=resultado_ejercicio)
    return apertura, asiento


def cerrar_mes(anio, mes):
    return PeriodoContable.objects.create(anio=anio, mes=mes, estado='cerrado', cerrado_en=timezone.now(), cerrado_por_nombre='x')


def entrar(client, empresa, rol=ROLE_OWNER, nombre=None):
    usuario = helpers.crear_usuario(nombre or f'diario.{empresa.pk}.{rol.lower()}', empresa, rol)
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    return usuario


def enviar(client, url, datos, metodo='post'):
    return getattr(client, metodo)(url, json.dumps(datos), content_type='application/json')


# ---------------------------------------------------------------- candado

class TestCandado:

    def test_sin_inicio_contable_responde_datos_por_completar(self, empresa):
        with company_context(empresa), pytest.raises(api.ErrorApi) as error:
            with candado.libro():
                pass
        respuesta = error.value.respuesta()
        assert respuesta.status_code == 409
        assert json.loads(respuesta.content) == {
            'error': capacidades.TEXTO_DATOS, 'codigo': 'datos_por_completar', 'causa': 'datos',
            'faltan': [{'codigo': 'inicio_sin_configurar', 'texto': candado.TEXTO_SIN_INICIO, 'url': None}]}

    def test_crear_solo_la_primera_vez(self, empresa):
        datos = dict(modalidad='saldos', fecha_corte=CORTE, contabilidad_desde=date(2026, 1, 1), operaciones_desde=date(2026, 1, 1),
                     creado_por_nombre='x', actualizado_por_nombre='x')
        with company_context(empresa):
            with candado.libro(crear=datos) as inicio:
                assert candado.exigir() == inicio and candado.tomado()
            otro = dict(datos, fecha_corte=date(2024, 12, 31), contabilidad_desde=date(2025, 1, 1))
            with candado.libro(crear=otro) as segundo:   # ya existe: no se crea otra ni se cambia la que hay
                assert segundo.pk == inicio.pk and segundo.fecha_corte == CORTE
            assert InicioContable.objects.count() == 1
            assert not candado.tomado()   # la marca se va al salir

    def test_lo_que_escribe_el_libro_exige_el_candado(self, f):
        with pytest.raises(candado.SinCandado):
            diario.contabilizar(tipo='manual', fecha=ENERO, concepto='x', lineas=[], autor=ac.AUTOR, motivo='x')
        with pytest.raises(candado.SinCandado):
            diario.reversar(1, motivo='x', autor=ac.AUTOR)
        with pytest.raises(candado.SinCandado):
            periodos.exigir_abierto(ENERO)
        with transaction.atomic(), pytest.raises(candado.SinCandado):   # una transacción sin candado tampoco vale
            periodos.exigir_abierto(ENERO)

    def test_la_marca_es_de_la_empresa_que_lo_tomo(self, f, empresa_b):
        with candado.libro():
            with company_context(empresa_b), pytest.raises(candado.SinCandado):
                candado.exigir()

    def test_un_rechazo_dentro_del_candado_no_deja_nada(self, f):
        antes = libro_intacto(f)
        with pytest.raises(diario.ErrorDiario):
            with candado.libro():
                diario.contabilizar(tipo='manual', fecha=ENERO, concepto='x', motivo='x', autor=ac.AUTOR,
                                    lineas=ac.lineas_de((f.c['caja'], 10, 0), (f.c['capital'], 0, 9)))
        assert libro_intacto(f) == antes


# ---------------------------------------------------------------- contabilizar

class TestContabilizar:

    def test_asiento_lineas_sello_acumulados_y_numero(self, f):
        a = venta(f, 115, fecha=ENERO, concepto='Venta 001-001-000000001',
                  origen=('venta', 77, 'emision', '001-001-000000001', ENERO))
        assert (a.anio, a.numero, a.numero_completo, a.sellado, a.lineas_n) == (2026, 1, '2026-000001', True, 2)
        assert (a.total_debe, a.total_haber, a.creado_por_nombre) == (Decimal('115.00'), Decimal('115.00'), 'prueba.esquema')
        assert (a.origen_tipo, a.origen_id, a.evento, a.origen_numero, a.origen_fecha) == (
            'venta', 77, 'emision', '001-001-000000001', ENERO)
        guardado = Asiento.objects.get(pk=a.pk)
        assert guardado.sellado and guardado.huella == a.huella and len(a.huella) == 64
        assert list(guardado.lineas.order_by('orden').values_list('orden', 'cuenta_id', 'debe', 'haber', 'fecha', 'anio', 'mes')) == [
            (1, f.c['clientes'].pk, Decimal('115.00'), Decimal('0.00'), ENERO, 2026, 1),
            (2, f.c['ventas'].pk, Decimal('0.00'), Decimal('115.00'), ENERO, 2026, 1)]
        assert saldo(f.c['clientes']) == {'debe': '115.00', 'haber': '0.00', 'apertura_debe': '0.00', 'apertura_haber': '0.00',
                                          'cierre_debe': '0.00', 'cierre_haber': '0.00'}
        assert saldo(f.c['ventas'])['haber'] == '115.00'
        segundo = venta(f, 5, fecha=date(2026, 1, 20))
        assert segundo.numero == 2 and saldo(f.c['clientes'])['debe'] == '120.00'
        assert EjercicioContable.objects.get(anio=2026).ultimo_numero == 2
        assert SaldoCuentaMes.objects.count() == 2   # una fila por cuenta y mes, que crece

    def test_tercero_documento_y_varias_lineas_de_la_misma_cuenta(self, f):
        tercero = {'tipo': 'cliente', 'id': 5, 'identificacion': '0912345678', 'nombre': 'CLIENTE FICTICIO'}
        documento = {'tipo': 'venta', 'id': 77, 'numero': '001-001-000000001'}
        a = ac.contabilizar(f.empresa, [(f.c['clientes'], 60, 0, {'tercero': tercero, 'documento': documento, 'concepto': 'A'}),
                                        (f.c['clientes'], 40, 0), (f.c['ventas'], 0, 100)])
        linea = a.lineas.get(orden=1)
        assert (linea.tercero_tipo, linea.tercero_id, linea.tercero_identificacion, linea.tercero_nombre, linea.concepto) == (
            'cliente', 5, '0912345678', 'CLIENTE FICTICIO', 'A')
        assert (linea.documento_tipo, linea.documento_id, linea.documento_numero) == ('venta', 77, '001-001-000000001')
        assert saldo(f.c['clientes'])['debe'] == '100.00' and a.lineas_n == 3

    @pytest.mark.parametrize('caso, codigo', [
        ('una_linea', 'lineas_insuficientes'), ('dos_lados', 'importe'), ('ningun_lado', 'importe'), ('tres_decimales', 'importe'),
        ('negativo', 'importe'), ('float', 'importe'), ('descuadre', 'asiento_descuadrado'),
        ('cuenta_de_otra_empresa', 'cuenta_no_existe'), ('cuenta_de_grupo', 'cuenta_de_grupo'), ('cuenta_inactiva', 'cuenta_inactiva'),
        ('tercero_sin_tipo', 'linea'), ('fecha_futura', 'fecha_futura'), ('fecha_de_corte', 'anterior_al_corte'),
        ('periodo_cerrado', 'periodo_cerrado'), ('ejercicio_cerrado', 'ejercicio_cerrado'), ('sin_motivo', 'motivo'),
        ('sin_origen', 'origen'), ('sin_concepto', 'concepto'), ('tipo', 'tipo'), ('reverso_suelto', 'tipo'),
        ('sin_autor', 'autor'), ('fecha_que_no_es_fecha', 'fecha'), ('clave_usada', 'clave_usada'),
        ('origen_ya_contabilizado', 'origen_ya_contabilizado'), ('apertura_fuera_del_corte', 'fecha_de_corte'),
        ('apertura_repetida', 'apertura_ya_contabilizada'),
    ])
    def test_cada_rechazo_no_escribe_ni_consume_numero(self, f, empresa_b, caso, codigo):
        c = f.c
        base = dict(tipo='manual', fecha=ENERO, concepto='Prueba', motivo='Prueba', autor=ac.AUTOR, origen=None, clave=None,
                    lineas=ac.lineas_de((c['caja'], 10, 0), (c['capital'], 0, 10)))
        previo = venta(f, 1, origen=('venta', 1, 'emision'), clave='asiento-previo-01')   # el número 1
        if caso == 'apertura_repetida':
            apertura_confirmada(f)
        otra = ac.plan_minimo(empresa_b)['caja'] if caso == 'cuenta_de_otra_empresa' else None
        if caso == 'cuenta_inactiva':
            Cuenta.objects.filter(pk=c['capital'].pk).update(activa=False)
        if caso == 'periodo_cerrado':
            cerrar_mes(2026, 1)
        if caso == 'ejercicio_cerrado':
            EjercicioContable.objects.filter(anio=2026).update(estado='cerrado', cerrado_en=timezone.now())
        cambios = {
            'una_linea': dict(lineas=ac.lineas_de((c['caja'], 10, 0))),
            'dos_lados': dict(lineas=ac.lineas_de((c['caja'], 10, 10), (c['capital'], 0, 10))),
            'ningun_lado': dict(lineas=ac.lineas_de((c['caja'], 0, 0), (c['capital'], 0, 10))),
            'tres_decimales': dict(lineas=ac.lineas_de((c['caja'], '10.001', 0), (c['capital'], 0, '10.001'))),
            'negativo': dict(lineas=ac.lineas_de((c['caja'], -10, 0), (c['capital'], 0, -10))),
            'float': dict(lineas=[{'cuenta_id': c['caja'].pk, 'debe': 10.0}, {'cuenta_id': c['capital'].pk, 'haber': 10.0}]),
            'descuadre': dict(lineas=ac.lineas_de((c['caja'], 10, 0), (c['capital'], 0, '9.50'))),
            'cuenta_de_otra_empresa': dict(lineas=[{'cuenta_id': otra.pk if otra else 0, 'debe': Decimal(10)},
                                                   {'cuenta_id': c['capital'].pk, 'haber': Decimal(10)}]),
            'cuenta_de_grupo': dict(lineas=ac.lineas_de((c['activo'], 10, 0), (c['capital'], 0, 10))),
            'cuenta_inactiva': {},
            'tercero_sin_tipo': dict(lineas=ac.lineas_de((c['caja'], 10, 0, {'tercero': {'id': 1}}), (c['capital'], 0, 10))),
            'fecha_futura': dict(fecha=timezone.localdate() + timedelta(days=1)),
            'fecha_de_corte': dict(fecha=CORTE),
            'periodo_cerrado': {}, 'ejercicio_cerrado': {},
            'sin_motivo': dict(motivo=''),
            'sin_origen': dict(tipo='origen'),
            'sin_concepto': dict(concepto='  '),
            'tipo': dict(tipo='otro'),
            'reverso_suelto': dict(tipo='reverso'),
            'sin_autor': dict(autor=(None, '')),
            'fecha_que_no_es_fecha': dict(fecha='2026-01-15'),
            'clave_usada': dict(clave='asiento-previo-01'),
            'origen_ya_contabilizado': dict(tipo='origen', origen=('venta', 1, 'emision')),
            'apertura_fuera_del_corte': dict(tipo='apertura', fecha=date(2026, 1, 1), origen=('apertura', 1, 'confirmacion')),
            'apertura_repetida': dict(tipo='apertura', fecha=CORTE, origen=('apertura', 99, 'confirmacion')),
        }[caso]
        antes = libro_intacto(f)
        with pytest.raises(diario.ErrorDiario) as error, candado.libro():
            diario.contabilizar(**{**base, **cambios})
        assert error.value.codigo == codigo, (error.value.codigo, str(error.value))
        assert error.value.estado == (409 if codigo in diario.CONFLICTOS else 400)
        assert libro_intacto(f) == antes
        if caso in ('periodo_cerrado', 'ejercicio_cerrado'):   # lo que se preparó también impide el siguiente
            return
        assert venta(f, 3).numero == previo.numero + 1   # el rechazo no consumió el número

    def test_errores_por_linea_todos_a_la_vez(self, f):
        with pytest.raises(diario.ErrorDiario) as error, candado.libro():
            diario.contabilizar(tipo='manual', fecha=ENERO, concepto='x', motivo='x', autor=ac.AUTOR, lineas=[
                {'cuenta_id': f.c['activo'].pk, 'debe': Decimal('1')}, {'cuenta_id': f.c['caja'].pk, 'debe': '1.234'},
                {'cuenta_id': 0, 'haber': Decimal('1')}, 'no es una línea'])
        e = error.value
        assert e.codigo == 'importe' and e.estado == 400   # el primero por precedencia; los demás, en `errores`
        assert e.errores == {'lineas.0.cuenta_id': [diario.LINEA['cuenta_de_grupo']], 'lineas.1.debe': [diario.LINEA['importe_formato']],
                             'lineas.2.cuenta_id': [diario.LINEA['cuenta_no_existe']], 'lineas.3': [diario.LINEA['linea']]}
        with pytest.raises(diario.ErrorDiario) as error, candado.libro():
            diario.contabilizar(tipo='manual', fecha=ENERO, concepto='x', motivo='x', autor=ac.AUTOR,
                                lineas=ac.lineas_de((f.c['caja'], '10.00', 0), (f.c['capital'], 0, '9.99')))
        assert json.loads(error.value.respuesta().content) == {
            'error': 'El asiento no cuadra: el debe suma 10.00 y el haber 9.99.', 'codigo': 'asiento_descuadrado',
            'debe': '10.00', 'haber': '9.99', 'diferencia': '0.01'}

    def test_conflicto_antes_que_validacion(self, f):
        """Decisión común 6: el conflicto con otros datos (409) va antes que la validación (400)."""
        with pytest.raises(diario.ErrorDiario) as error, candado.libro():
            diario.contabilizar(tipo='manual', fecha=CORTE, concepto='', motivo='', autor=ac.AUTOR, lineas=[])
        assert error.value.codigo == 'anterior_al_corte' and error.value.detalle == {
            'fecha_corte': '2025-12-31', 'contabilidad_desde': '2026-01-01'}

    def test_periodo_cerrado_dice_el_mes_y_los_demas_meses_siguen(self, f):
        cerrar_mes(2026, 2)
        with pytest.raises(diario.ErrorDiario) as error:
            venta(f, fecha=date(2026, 2, 10))
        assert (error.value.codigo, error.value.detalle) == ('periodo_cerrado', {'periodo': '2026-02'})
        assert venta(f, fecha=date(2026, 3, 1)).numero == 1

    def test_apertura_en_la_fecha_de_corte_sin_mirar_el_periodo(self, f):
        cerrar_mes(2025, 12)   # los meses hasta el corte no se gestionan: un período cerrado ahí no la detiene
        apertura, asiento = apertura_confirmada(f, 10000)
        assert (asiento.tipo, asiento.fecha, asiento.numero_completo) == ('apertura', CORTE, '2025-000001')
        assert saldo(f.c['caja'], 2025, 12) == {'debe': '10000.00', 'haber': '0.00', 'apertura_debe': '10000.00',
                                                'apertura_haber': '0.00', 'cierre_debe': '0.00', 'cierre_haber': '0.00'}
        assert saldo(f.c['capital'], 2025, 12)['apertura_haber'] == '10000.00'
        assert venta(f).numero_completo == '2026-000001'   # cada ejercicio numera desde 1

    @pytest.mark.parametrize('corte, origen, admitido', [
        (date(2025, 12, 31), ('ejercicio', 2025, 'cierre_resultados'), True),
        (date(2025, 12, 31), ('ejercicio', 2024, 'cierre_resultados'), False),
        (date(2025, 12, 31), ('ejercicio', 2025, 'otro_evento'), False),
        (date(2025, 6, 30), ('ejercicio', 2025, 'cierre_resultados'), False),
    ])
    def test_cierre_en_la_fecha_de_corte_solo_del_ejercicio_del_corte(self, empresa, corte, origen, admitido):
        c = ac.plan_minimo(empresa)
        ac.inicio_directo(empresa, corte)
        with company_context(empresa):
            if not admitido:
                with pytest.raises(diario.ErrorDiario) as error:
                    ac.contabilizar(empresa, [(c['ventas'], 500, 0), (c['resultados'], 0, 500)], tipo='cierre', fecha=corte,
                                    origen=origen, motivo='')
                assert error.value.codigo == 'anterior_al_corte'
                return
            cierre = ac.contabilizar(empresa, [(c['ventas'], 500, 0), (c['resultados'], 0, 500)], tipo='cierre', fecha=corte,
                                     origen=origen, motivo='')
            assert saldo(c['ventas'], 2025, 12) == {'debe': '500.00', 'haber': '0.00', 'apertura_debe': '0.00',
                                                    'apertura_haber': '0.00', 'cierre_debe': '500.00', 'cierre_haber': '0.00'}
            reverso, _ = ac.reversar(empresa, cierre)   # su reverso, también en la fecha de corte y en las columnas de cierre
            assert reverso.fecha == corte and saldo(c['ventas'], 2025, 12)['cierre_haber'] == '500.00'

    def test_huella_canonica_v1(self, f):
        a = ac.contabilizar(f.empresa, [(f.c['caja'], '12.50', 0), (f.c['capital'], 0, '12.50')], tipo='origen',
                            origen=('venta', 4, 'emision'), motivo='')
        contenido = {'v': 1, 'empresa': f.empresa.pk, 'anio': 2026, 'numero': 1, 'fecha': '2026-01-15', 'tipo': 'origen',
                     'origen': ['venta', 4, 'emision'],
                     'lineas': [[1, f.c['caja'].pk, '12.50', '0.00', '', None, '', None],
                                [2, f.c['capital'].pk, '0.00', '12.50', '', None, '', None]]}
        texto = json.dumps(contenido, separators=(',', ':'), sort_keys=True)
        assert a.huella == hashlib.sha256(texto.encode()).hexdigest()
        lineas = [(l.orden, l.cuenta_id, l.debe, l.haber, l.tercero_tipo, l.tercero_id, l.documento_tipo, l.documento_id)
                  for l in a.lineas.all()]
        assert diario.huella(f.empresa.pk, 2026, 1, ENERO, 'origen', 'venta', 4, 'emision', reversed(lineas)) == a.huella


# ---------------------------------------------------------------- reversar

class TestReversar:

    def test_una_vez_con_su_espejo_y_los_acumulados_vuelven(self, f):
        original = venta(f, 80, clave='asiento-original-1')
        reverso, repetido = ac.reversar(f.empresa, original, clave='reverso-del-uno-01')
        assert not repetido and (reverso.tipo, reverso.reversa_de_id, reverso.numero, reverso.fecha) == ('reverso', original.pk, 2, ENERO)
        assert (reverso.origen_tipo, reverso.origen_id, reverso.evento) == (original.origen_tipo, original.origen_id, original.evento)
        assert reverso.motivo == 'Reverso de prueba' and reverso.concepto.startswith('Reverso del asiento 2026-000001')
        assert list(reverso.lineas.values_list('cuenta_id', 'debe', 'haber')) == [
            (f.c['clientes'].pk, Decimal('0.00'), Decimal('80.00')), (f.c['ventas'].pk, Decimal('80.00'), Decimal('0.00'))]
        guardado = Asiento.objects.get(pk=original.pk)
        assert guardado.reversado_por_id == reverso.pk and guardado.reversado_en is not None
        assert saldo(f.c['clientes'])[('debe')] == saldo(f.c['clientes'])['haber'] == '80.00'   # neto cero: solo crece
        # otra vez con la misma clave: el mismo reverso; con otra, ya reversado; el reverso no se reversa
        assert ac.reversar(f.empresa, original, clave='reverso-del-uno-01') == (reverso, True)
        with pytest.raises(diario.ErrorDiario) as error:
            ac.reversar(f.empresa, original, clave='reverso-del-uno-02')
        assert (error.value.codigo, error.value.estado, error.value.detalle) == (
            'ya_reversado', 409, {'reverso': {'id': reverso.pk, 'numero': '2026-000002'}})
        with pytest.raises(diario.ErrorDiario) as error:
            ac.reversar(f.empresa, reverso)
        assert error.value.codigo == 'no_reversable'
        with pytest.raises(diario.ErrorDiario) as error:   # una clave que ya es de otro asiento
            ac.reversar(f.empresa, venta(f), clave='asiento-original-1')
        assert error.value.codigo == 'clave_usada'
        assert Asiento.objects.count() == 3 and EjercicioContable.objects.get(anio=2026).ultimo_numero == 3

    def test_el_mismo_hecho_se_vuelve_a_contabilizar_tras_reversarlo(self, f):
        original = venta(f, origen=('venta', 50, 'emision'))
        with pytest.raises(diario.ErrorDiario):
            venta(f, origen=('venta', 50, 'emision'))
        ac.reversar(f.empresa, original)
        assert venta(f, origen=('venta', 50, 'emision')).numero == 3

    def test_cuenta_desactivada_solo_en_el_reverso(self, f):
        original = venta(f, 10)
        Cuenta.objects.filter(pk=f.c['ventas'].pk).update(activa=False)
        with pytest.raises(diario.ErrorDiario) as error:
            venta(f, 10)
        assert error.value.codigo == 'cuenta_inactiva'
        reverso, _ = ac.reversar(f.empresa, original)
        assert reverso.lineas.filter(cuenta=f.c['ventas']).exists()

    def test_fecha_del_reverso(self, f):
        original = venta(f, 10, fecha=date(2026, 2, 10))
        with pytest.raises(diario.ErrorDiario) as error:
            ac.reversar(f.empresa, original, fecha=date(2026, 2, 9))
        assert error.value.codigo == 'fecha_del_reverso'
        cerrar_mes(2026, 2)
        with pytest.raises(diario.ErrorDiario) as error:   # sin fecha, la del original: su período está cerrado
            ac.reversar(f.empresa, original)
        assert (error.value.codigo, error.value.detalle) == ('periodo_cerrado', {'periodo': '2026-02'})
        with pytest.raises(diario.ErrorDiario) as error:
            ac.reversar(f.empresa, original, fecha=timezone.localdate() + timedelta(days=1))
        assert error.value.codigo == 'fecha_futura'
        reverso, _ = ac.reversar(f.empresa, original, fecha=date(2026, 3, 1))
        assert (reverso.fecha, reverso.mes) == (date(2026, 3, 1), 3)
        assert saldo(f.c['clientes'], 2026, 3) == {'debe': '0.00', 'haber': '10.00', 'apertura_debe': '0.00', 'apertura_haber': '0.00',
                                                   'cierre_debe': '0.00', 'cierre_haber': '0.00'}

    def test_reverso_de_la_apertura_en_sus_columnas(self, f):
        apertura, asiento = apertura_confirmada(f, 300)
        reverso, _ = ac.reversar(f.empresa, asiento)
        assert reverso.fecha == CORTE   # la del original: el corte, sin mirar el período
        assert saldo(f.c['caja'], 2025, 12) == {'debe': '300.00', 'haber': '300.00', 'apertura_debe': '300.00',
                                                'apertura_haber': '300.00', 'cierre_debe': '0.00', 'cierre_haber': '0.00'}
        otro = ac.contabilizar(f.empresa, [(f.c['caja'], 5, 0), (f.c['capital'], 0, 5)], tipo='apertura', fecha=CORTE,
                               origen=('apertura', apertura.pk + 1, 'confirmacion'), motivo='')
        cerrar_mes(2026, 1)
        with pytest.raises(diario.ErrorDiario) as error:   # fechado tras el corte vuelve a ser ordinario: período abierto
            ac.reversar(f.empresa, otro, fecha=date(2026, 1, 5))
        assert error.value.codigo == 'periodo_cerrado'

    def test_no_existe(self, f, empresa_b):
        otras = ac.plan_minimo(empresa_b)
        ac.inicio_directo(empresa_b)
        ajeno = ac.contabilizar(empresa_b, [(otras['caja'], 1, 0), (otras['capital'], 0, 1)])
        with pytest.raises(diario.ErrorDiario) as error:
            ac.reversar(f.empresa, ajeno)
        assert (error.value.codigo, error.value.estado) == ('no_existe', 404)


# ---------------------------------------------------------------- propiedad

@pytest.mark.parametrize('semilla', [1, 7, 2026])
def test_secuencia_aleatoria_cuadra_acumula_y_numera_sin_huecos(f, semilla):
    azar = random.Random(semilla)
    movimiento = [f.c[n] for n in ('caja', 'bancos', 'clientes', 'inventario', 'proveedores', 'capital', 'ventas', 'costo_ventas',
                                   'gastos_generales')]
    apertura_confirmada(f, azar.randint(1, 50000))
    cierre_hecho = False
    for paso in range(40):
        # El asiento de la apertura confirmada no: reversarlo es de la apertura (Parte E), que deja de estar confirmada.
        vigentes = list(Asiento.objects.filter(reversado_por__isnull=True).exclude(tipo__in=('reverso', 'apertura'))
                        .values_list('pk', flat=True))
        accion = azar.random()
        if accion < 0.25 and vigentes:
            original = Asiento.objects.get(pk=azar.choice(vigentes))
            ac.reversar(f.empresa, original, fecha=max(original.fecha, date(2026, 1, 1)) if original.fecha > CORTE else None)
            continue
        if accion < 0.3 and not cierre_hecho:
            ac.contabilizar(f.empresa, [(f.c['ventas'], 1, 0), (f.c['resultados'], 0, 1)], tipo='cierre', fecha=CORTE,
                            origen=('ejercicio', 2025, 'cierre_resultados'), motivo='')
            cierre_hecho = True
            continue
        cuentas_del_asiento = azar.sample(movimiento, azar.randint(2, 5))
        importes = [Decimal(azar.randint(1, 100000)) / 100 for _ in cuentas_del_asiento[1:]]
        filas = [(cuenta, imp, 0) for cuenta, imp in zip(cuentas_del_asiento[1:], importes)]
        filas.append((cuentas_del_asiento[0], 0, sum(importes)))
        azar.shuffle(filas)
        fecha = date(2026, azar.randint(1, 10), azar.randint(1, 28))
        ac.contabilizar(f.empresa, filas, tipo=azar.choice(['manual', 'ajuste', 'origen']), fecha=fecha,
                        origen=('prueba', 100 + paso, 'evento'))
    # Σ debe = Σ haber en todo el libro
    totales = LineaAsiento.objects.aggregate(d=Sum('debe'), h=Sum('haber'))
    assert totales['d'] == totales['h'] > 0
    # acumulados = Σ líneas, total y por tipo (apertura y cierre con sus reversos)
    for fila in SaldoCuentaMes.objects.all():
        lineas = LineaAsiento.objects.filter(cuenta_id=fila.cuenta_id, anio=fila.anio, mes=fila.mes)
        assert (fila.debe, fila.haber) == tuple(lineas.aggregate(d=Sum('debe'), h=Sum('haber')).values())
        for tipo in ('apertura', 'cierre'):
            del_tipo = [l for l in lineas.select_related('asiento__reversa_de') if l.asiento.tipo == tipo
                        or (l.asiento.tipo == 'reverso' and l.asiento.reversa_de.tipo == tipo)]
            assert getattr(fila, f'{tipo}_debe') == sum((l.debe for l in del_tipo), Decimal('0'))
            assert getattr(fila, f'{tipo}_haber') == sum((l.haber for l in del_tipo), Decimal('0'))
    # numeración sin huecos ni repetidos en cada ejercicio
    for ejercicio in EjercicioContable.objects.all():
        numeros = sorted(Asiento.objects.filter(anio=ejercicio.anio).values_list('numero', flat=True))
        assert numeros == list(range(1, ejercicio.ultimo_numero + 1))
    for anio in (2025, 2026):
        assert all(c['ok'] for c in diario.verificar(anio)['comprobaciones']), diario.verificar(anio)


# ---------------------------------------------------------------- verificación del libro

class TestVerificar:

    def test_en_verde_y_cada_alteracion_se_detecta(self, f):
        venta(f, 10)
        venta(f, 20)
        resultado = diario.verificar(2026)
        assert resultado['anio'] == 2026 and resultado['asientos'] == 2
        assert [(c['codigo'], c['ok'], c['detalle']) for c in resultado['comprobaciones']] == [
            (codigo, True, []) for codigo in ('cuadre', 'numeracion', 'huellas', 'acumulados', 'acumulados_por_tipo',
                                              'apertura_unica', 'sellados')]
        primero = Asiento.objects.get(numero=1)
        alteraciones = {
            'cuadre': ("UPDATE contabilidad_lineaasiento SET debe = 11 WHERE asiento_id = %s AND orden = 1", [primero.pk]),
            'acumulados': ('UPDATE contabilidad_saldocuentames SET debe = debe + 1 WHERE cuenta_id = %s', [f.c['clientes'].pk]),
            'acumulados_por_tipo': ('UPDATE contabilidad_saldocuentames SET apertura_debe = 1 WHERE cuenta_id = %s',
                                    [f.c['clientes'].pk]),
            'numeracion': ('UPDATE contabilidad_ejerciciocontable SET ultimo_numero = 3 WHERE anio = 2026', []),
            'sellados': ('UPDATE contabilidad_asiento SET sellado = %s WHERE id = %s', [False, primero.pk]),
            'apertura_unica': ("UPDATE contabilidad_asiento SET tipo = 'apertura' WHERE id = %s", [primero.pk]),
        }
        for codigo, (sql, params) in alteraciones.items():
            with ac.sin_disparadores('contabilidad_asiento', 'contabilidad_lineaasiento'):
                with connection.cursor() as cursor:
                    cursor.execute(sql, params)
                fallidas = {c['codigo'] for c in diario.verificar(2026)['comprobaciones'] if not c['ok']}
                assert codigo in fallidas, (codigo, fallidas)
                if codigo == 'cuadre':
                    assert 'huellas' in fallidas   # la huella cubre los importes de las líneas
                    detalle = next(c for c in diario.verificar(2026)['comprobaciones'] if c['codigo'] == 'cuadre')['detalle']
                    assert detalle == [{'asiento': {'id': primero.pk, 'numero': '2026-000001'},
                                        'totales': {'debe': '10.00', 'haber': '10.00'},
                                        'lineas': {'n': 2, 'esperadas': 2, 'debe': '11.00', 'haber': '10.00'}}]
                if codigo == 'numeracion':
                    detalle = next(c for c in diario.verificar(2026)['comprobaciones'] if c['codigo'] == 'numeracion')['detalle']
                    assert detalle[0]['faltantes'] == [3]
        assert all(c['ok'] for c in diario.verificar(2026)['comprobaciones'])   # cada alteración se deshizo

    def test_la_orden_verificar_libro(self, f):
        venta(f, 10)
        salida = StringIO()
        call_command('verificar_libro', '--empresa', str(f.empresa.pk), '--anio', '2026', stdout=salida)
        assert '1 asientos' in salida.getvalue() and 'cuadre: bien' in salida.getvalue()
        salida = StringIO()
        call_command('verificar_libro', '--empresa', str(f.empresa.pk), '--anio', '2026', '--json', stdout=salida)
        assert json.loads(salida.getvalue()) == diario.verificar(2026)
        with ac.sin_disparadores('contabilidad_asiento'):
            with connection.cursor() as cursor:
                cursor.execute('UPDATE contabilidad_ejerciciocontable SET ultimo_numero = 5')
            with pytest.raises(CommandError, match='numeracion'):
                call_command('verificar_libro', '--empresa', str(f.empresa.pk), '--anio', '2026', stdout=StringIO())
        with pytest.raises(CommandError):
            call_command('verificar_libro', '--empresa', '999999', stdout=StringIO())


# ---------------------------------------------------------------- provisionalidad

class TestProvisionalidad:

    def codigos(self, reporte='diario', desde=date(2026, 1, 1), hasta=date(2026, 1, 31)):
        provisional, causas, detalle = reportes.provisionalidad(reporte, desde, hasta)
        assert provisional is bool(detalle) and causas == [d['texto'] for d in detalle]
        return [d['codigo'] for d in detalle]

    def test_sin_inicio(self, empresa):
        with company_context(empresa):
            assert self.codigos() == ['inicio_sin_configurar', 'motor_pendiente']

    def test_por_saldos_y_por_historial_sin_apertura(self, f, empresa_b):
        assert self.codigos() == ['apertura_sin_confirmar', 'motor_pendiente']
        assert self.codigos(desde=date(2025, 12, 1), hasta=CORTE) == ['apertura_sin_confirmar']
        ac.inicio_directo(empresa_b, CORTE, modalidad='historial')
        with company_context(empresa_b):
            assert self.codigos() == ['saldo_anterior_sin_confirmar', 'motor_pendiente']

    def test_con_la_apertura_confirmada_sigue_provisional_tras_el_corte(self, f):
        apertura_confirmada(f)
        assert self.codigos() == ['motor_pendiente']   # ningún rango se supone completo por tener la apertura
        assert self.codigos(desde=date(2025, 12, 1), hasta=CORTE) == []

    def test_resultados_acumulados_sin_detalle_solo_en_los_de_resultados_de_ese_ejercicio(self, f):
        apertura_confirmada(f, resultado_ejercicio='en_patrimonio')
        assert self.codigos('estado_resultados', date(2025, 1, 1), CORTE) == ['resultados_acumulados_sin_detalle']
        assert self.codigos('estado_resultados', date(2026, 1, 1), date(2026, 12, 31)) == ['motor_pendiente']
        assert self.codigos('diario', date(2025, 1, 1), CORTE) == []

    def test_aplicaciones_sin_contabilizar_con_su_cantidad(self, f):
        filas = ac.filas_de_apertura(f.empresa, f.c, venta(f))   # una aplicación vigente del 10/01/2026, sin expediente
        assert filas['aplicacion'].fecha == date(2026, 1, 10)
        _, _, detalle = reportes.provisionalidad('diario', date(2026, 1, 1), date(2026, 1, 31))
        assert {'codigo': 'aplicaciones_sin_contabilizar', 'texto': reportes.CAUSAS['aplicaciones_sin_contabilizar'].texto,
                'cantidad': 1} in detalle
        assert 'aplicaciones_sin_contabilizar' not in self.codigos(desde=date(2026, 2, 1), hasta=date(2026, 2, 28))

    def test_registro_de_causas(self):
        assert list(reportes.CAUSAS) == ['inicio_sin_configurar', 'apertura_sin_confirmar', 'saldo_anterior_sin_confirmar',
                                         'resultados_acumulados_sin_detalle', 'aplicaciones_sin_contabilizar', 'motor_pendiente']
        assert reportes.CAUSAS['motor_pendiente'].texto == 'Los documentos de la operación todavía no se contabilizan.'
        with pytest.raises(ValueError):
            reportes.registrar('motor_pendiente', 'otra')(lambda contexto: True)


# ---------------------------------------------------------------- lectura por API

@pytest.fixture
def api_f(client, f):
    entrar(client, f.empresa)
    return SimpleNamespace(**vars(f), client=client)


class TestDiarioApi:

    def test_forma_del_asiento_y_totales(self, api_f):
        f = api_f
        tercero = {'tipo': 'cliente', 'id': 5, 'identificacion': '0912345678', 'nombre': 'CLIENTE FICTICIO'}
        documento = {'tipo': 'venta', 'id': 77, 'numero': '001-001-000000001'}
        a = ac.contabilizar(f.empresa, [(f.c['clientes'], 115, 0, {'tercero': tercero, 'documento': documento}),
                                        (f.c['ventas'], 0, 115, {'concepto': 'Venta'})],
                            tipo='origen', concepto='Venta 001-001-000000001', motivo='',
                            origen=('venta', 77, 'emision', '001-001-000000001', ENERO))
        reverso, _ = ac.reversar(f.empresa, a, fecha=date(2026, 1, 20))
        respuesta = f.client.get(f'{DIARIO}?desde=2026-01-01&hasta=2026-01-31&empresa={f.empresa.pk}')
        assert respuesta.status_code == 200, respuesta.content
        datos = respuesta.json()
        assert (datos['desde'], datos['hasta']) == ('2026-01-01', '2026-01-31')
        assert datos['totales'] == {'debe': '230.00', 'haber': '230.00', 'asientos': 2}
        assert datos['paginacion'] == {'pagina': 1, 'por_pagina': 100, 'total': 2, 'paginas': 1}
        assert datos['provisional'] is True and [d['codigo'] for d in datos['causas_detalle']] == [
            'apertura_sin_confirmar', 'motor_pendiente']
        primero = datos['asientos'][0]
        assert primero == {
            'id': a.pk, 'numero': '2026-000001', 'fecha': '2026-01-15', 'tipo': 'origen', 'concepto': 'Venta 001-001-000000001',
            'motivo': '', 'origen': {'tipo': 'venta', 'id': 77, 'evento': 'emision', 'numero': '001-001-000000001',
                                     'fecha': '2026-01-15'},
            'estado': 'reversado', 'reversa_de': None, 'reversado_por': {'id': reverso.pk, 'numero': '2026-000002'},
            'totales': {'debe': '115.00', 'haber': '115.00'},
            'lineas': [{'orden': 1, 'cuenta': {'id': f.c['clientes'].pk, 'codigo': '1.1.03', 'nombre': 'Clientes'}, 'concepto': '',
                        'debe': '115.00', 'haber': '0.00', 'tercero': tercero, 'documento': documento},
                       {'orden': 2, 'cuenta': {'id': f.c['ventas'].pk, 'codigo': '4.1.01', 'nombre': 'Ventas'}, 'concepto': 'Venta',
                        'debe': '0.00', 'haber': '115.00', 'tercero': None, 'documento': None}],
            'creado_por': 'prueba.esquema', 'creado_en': Asiento.objects.get(pk=a.pk).creado_en.isoformat(), 'huella': a.huella}
        segundo = datos['asientos'][1]
        assert (segundo['estado'], segundo['reversa_de'], segundo['motivo']) == (
            'reverso', {'id': a.pk, 'numero': '2026-000001'}, 'Reverso de prueba')
        assert f.client.get(f'{DIARIO}{a.pk}/').json() == {'asiento': primero}

    def test_filtros_orden_y_paginas(self, api_f):
        f = api_f
        tercero_mes = venta(f, 3, fecha=date(2026, 1, 25))
        primero = venta(f, 1, fecha=date(2026, 1, 5), origen=('venta', 41, 'emision'))
        manual = ac.contabilizar(f.empresa, [(f.c['caja'], 2, 0), (f.c['capital'], 0, 2)], fecha=date(2026, 1, 5))

        def numeros(consulta):
            r = f.client.get(f'{DIARIO}?desde=2026-01-01&hasta=2026-01-31&{consulta}')
            assert r.status_code == 200, r.content
            return [a['numero'] for a in r.json()['asientos']]
        assert numeros('') == ['2026-000002', '2026-000003', '2026-000001']   # por fecha y número
        assert numeros('tipo=manual') == [manual.numero_completo]
        assert numeros('origen_tipo=venta&origen_id=41') == [primero.numero_completo]
        assert numeros(f'cuenta={f.c["caja"].pk}') == [manual.numero_completo]
        assert numeros('por_pagina=2&pagina=2') == [tercero_mes.numero_completo]
        assert numeros('por_pagina=2&pagina=9') == []
        r = f.client.get(f'{DIARIO}?desde=2026-01-01&hasta=2026-01-31&por_pagina=2').json()
        assert r['paginacion'] == {'pagina': 1, 'por_pagina': 2, 'total': 3, 'paginas': 2} and r['totales']['asientos'] == 3

    def test_sin_fechas_el_mes_en_curso(self, api_f):
        hoy = timezone.localdate()
        datos = api_f.client.get(DIARIO).json()
        assert datos['desde'] == hoy.replace(day=1).isoformat() and datos['hasta'][:7] == hoy.isoformat()[:7]
        assert date.fromisoformat(datos['hasta']).month != (date.fromisoformat(datos['hasta']) + timedelta(days=1)).month

    @pytest.mark.parametrize('consulta, campos', [
        ('desde=2026-13-01', ['desde']), ('hasta=15/01/2026', ['hasta']), ('desde=2026-02-01&hasta=2026-01-01', ['hasta']),
        ('tipo=otro', ['tipo']), ('origen_id=abc', ['origen_id']), ('cuenta=999999', ['cuenta']), ('pagina=0', ['pagina']),
        ('por_pagina=501', ['por_pagina']), ('desde=x&tipo=y&por_pagina=0', ['desde', 'tipo', 'por_pagina']),
    ])
    def test_400_por_campo(self, api_f, consulta, campos):
        r = api_f.client.get(f'{DIARIO}?{consulta}')
        assert r.status_code == 400 and r.json()['codigo'] == 'validacion' and sorted(r.json()['errores']) == sorted(campos)

    def test_cuenta_de_otra_empresa_y_asiento_de_otra_empresa(self, api_f, empresa_b):
        otras = ac.plan_minimo(empresa_b)
        ac.inicio_directo(empresa_b)
        ajeno = ac.contabilizar(empresa_b, [(otras['caja'], 1, 0), (otras['capital'], 0, 1)])
        r = api_f.client.get(f'{DIARIO}?cuenta={otras["caja"].pk}')
        assert r.status_code == 400 and 'cuenta' in r.json()['errores']
        r = api_f.client.get(f'{DIARIO}{ajeno.pk}/')
        assert r.status_code == 404 and r.json() == {'error': 'El asiento no existe o es de otra empresa.', 'codigo': 'no_existe'}

    def test_sin_inicio_contable_responde_200(self, client, empresa):
        entrar(client, empresa)
        datos = client.get(DIARIO).json()
        assert datos['asientos'] == [] and datos['provisional'] is True
        assert [d['codigo'] for d in datos['causas_detalle']] == ['inicio_sin_configurar', 'motor_pendiente']
        integridad = client.get(INTEGRIDAD)
        assert integridad.status_code == 200 and integridad.json()['asientos'] == 0

    def test_diario_tras_el_corte_con_la_apertura_confirmada_sigue_provisional(self, api_f):
        apertura_confirmada(api_f)
        datos = api_f.client.get(f'{DIARIO}?desde=2025-12-01&hasta=2026-01-31').json()
        assert datos['provisional'] is True and [d['codigo'] for d in datos['causas_detalle']] == ['motor_pendiente']
        assert [a['tipo'] for a in datos['asientos']] == ['apertura']
        antes = api_f.client.get(f'{DIARIO}?desde=2025-12-01&hasta=2025-12-31').json()
        assert (antes['provisional'], antes['causas'], antes['causas_detalle']) == (False, [], [])

    def test_integridad(self, api_f):
        venta(api_f, 10)
        datos = api_f.client.get(f'{INTEGRIDAD}?anio=2026').json()
        assert datos['anio'] == 2026 and datos['asientos'] == 1 and all(c['ok'] for c in datos['comprobaciones'])
        assert api_f.client.get(INTEGRIDAD).json()['anio'] == timezone.localdate().year
        for malo in ('abc', '1999', '20260'):
            r = api_f.client.get(f'{INTEGRIDAD}?anio={malo}')
            assert r.status_code == 400 and r.json()['errores'] == {'anio': ['Escribe un año entre 2000 y 2100.']}


# ---------------------------------------------------------------- roles y negativas comunes

class TestRolesYNegativas:

    @pytest.mark.parametrize('rol, ver, clasificar', [
        (ROLE_OWNER, 200, 200), (ROLE_ADMIN, 200, 200), (ROLE_ACCOUNTANT, 200, 200), (ROLE_READONLY, 200, 403),
        (ROLE_SELLER, 403, 403), (ROLE_CLIENT, 403, 403),
    ])
    def test_matriz_de_roles(self, client, f, rol, ver, clasificar):
        a = venta(f, 10)
        entrar(client, f.empresa, rol)
        for url in (DIARIO, f'{DIARIO}{a.pk}/', INTEGRIDAD):
            r = client.get(f'{url}?empresa={f.empresa.pk}')
            assert r.status_code == ver, (rol, url)
            if ver == 403:
                assert r.json()['codigo'] == 'sin_permiso' and r.json()['permisos'] == ['view_asiento']
        cuenta = Cuenta.objects.get(pk=f.c['caja'].pk)
        r = enviar(client, CLASIFICAR, {'empresa': f.empresa.pk, 'cuenta_id': cuenta.pk, 'version': cuenta.version, 'clase': 'pasivo'})
        assert r.status_code == clasificar, (rol, r.content)
        if clasificar == 403:
            assert r.json()['codigo'] == 'sin_permiso' and Cuenta.objects.get(pk=cuenta.pk).clase == 'activo'

    def test_pestana_vieja_metodo_y_sin_empresa(self, api_f, empresa_b):
        f = api_f
        from django.contrib.auth.models import Group
        from core.tenancy.models import Membership
        usuario = helpers.crear_usuario('diario.dos.empresas', f.empresa, ROLE_OWNER)
        Membership.objects.create(user=usuario, company=empresa_b, group=Group.objects.get(name=ROLE_OWNER))
        helpers.iniciar_sesion(f.client, usuario, empresa=f.empresa)
        f.client.post('/empresas/cambiar/', {'company': empresa_b.pk})
        for url in (f'{DIARIO}?empresa={f.empresa.pk}', f'{INTEGRIDAD}?empresa={f.empresa.pk}'):
            r = f.client.get(url)
            assert r.status_code == 409 and r.json()['codigo'] == 'empresa_cambiada', url
        cuenta = f.c['caja']
        for url, cuerpo in ((f'{CLASIFICAR}?empresa={f.empresa.pk}', {}), (CLASIFICAR, {'empresa': f.empresa.pk})):
            r = enviar(f.client, url, {**cuerpo, 'cuenta_id': cuenta.pk, 'version': 1, 'clase': 'pasivo'})
            assert r.status_code == 409 and r.json()['codigo'] == 'empresa_cambiada'
        f.client.post('/empresas/cambiar/', {'company': f.empresa.pk})
        r = enviar(f.client, CLASIFICAR, {'cuenta_id': cuenta.pk, 'version': 1, 'clase': 'pasivo'})
        assert r.status_code == 409 and r.json()['codigo'] == 'sin_empresa'
        assert f.client.get(CLASIFICAR).status_code == 405
        r = enviar(f.client, DIARIO, {'empresa': f.empresa.pk})
        assert r.status_code == 405 and r.json()['codigo'] == 'metodo' and r['Allow'] == 'GET'
        assert Cuenta.objects.get(pk=cuenta.pk).clase == 'activo'

    def test_plan_vencido_consulta_si_envios_no(self, api_f):
        from core.suscripciones.models import SubscriptionPeriod
        SubscriptionPeriod.objects.filter(company=api_f.empresa).update(ends_at=timezone.now() - timedelta(days=1))
        assert api_f.client.get(DIARIO).status_code == 200 and api_f.client.get(INTEGRIDAD).status_code == 200
        r = enviar(api_f.client, CLASIFICAR, {'empresa': api_f.empresa.pk, 'cuenta_id': api_f.c['caja'].pk, 'version': 1,
                                              'clase': 'pasivo'})
        assert r.status_code == 403 and r.json()['codigo'] == 'plan'
        assert Cuenta.objects.get(pk=api_f.c['caja'].pk).clase == 'activo'

    def test_la_funcion_diario_mayor(self, client, f):
        funcion = capacidades.funcion_de('diario_mayor')
        assert (funcion.construccion, funcion.permisos, funcion.ruta) == (
            capacidades.DISPONIBLE, {'ver': 'view_asiento'}, '/contabilidad/api/diario/')
        entrar(client, f.empresa, ROLE_READONLY)
        resuelta = client.get('/contabilidad/api/capacidades/').json()['funciones']['diario_mayor']
        assert (resuelta['estado'], resuelta['acciones'], resuelta['faltan']) == ('disponible', {'ver': True}, [])
        client.logout()
        entrar(client, f.empresa, ROLE_SELLER)
        assert client.get('/contabilidad/api/capacidades/').json()['funciones']['diario_mayor']['estado'] == 'sin_permiso'


# ---------------------------------------------------------------- cuentas: clase, auxiliar, clasificar

@pytest.fixture
def plan_api(client, f):
    """El plan mínimo por la API, con el propietario."""
    entrar(client, f.empresa)

    def cuenta(nombre):
        return next(c for c in client.get(CUENTAS).json()['cuentas'] if c['id'] == f.c[nombre].pk)
    return SimpleNamespace(**vars(f), client=client, cuenta=cuenta)


def cambiar(p, cual, **cambios):
    cuenta = p.cuenta(cual)
    return enviar(p.client, f'{CUENTAS}{cuenta["id"]}/', {'empresa': p.empresa.pk, 'version': cuenta['version'], **cambios}, 'patch')


class TestClaseYAuxiliar:

    def test_get_y_patch(self, plan_api):
        p = plan_api
        clientes = p.cuenta('clientes')
        assert (clientes['clase'], clientes['auxiliar']) == ('activo', 'cliente')
        r = cambiar(p, 'gastos_generales', clase='costo', auxiliar='')
        assert r.status_code == 200 and r.json()['cuenta']['clase'] == 'costo' and r.json()['cuenta']['version'] == 2
        registro = AuditLog.objects.filter(action='cuenta_modificada', company=p.empresa).latest('id')
        assert registro.detail['cambios'] == {'clase': ['gasto', 'costo']}
        assert cambiar(p, 'caja', auxiliar='banco').json()['cuenta']['auxiliar'] == 'banco'
        assert cambiar(p, 'caja', clase=None).json()['cuenta']['clase'] == ''   # quitarle la clase (sin líneas)

    @pytest.mark.parametrize('nombre, cambios, errores', [
        ('activo', {'auxiliar': 'cliente'}, {'auxiliar': ['Solo las cuentas de movimiento llevan auxiliar.']}),
        ('clientes', {'tipo': 'grupo'}, {'auxiliar': ['Solo las cuentas de movimiento llevan auxiliar.']}),
        ('caja', {'clase': 'activos'}, {'clase': [cuentas.TEXTOS['clase_vacia']]}),
        ('caja', {'auxiliar': 'otro', 'clase': 3}, {'auxiliar': [cuentas.TEXTOS['auxiliar']], 'clase': [cuentas.TEXTOS['clase_vacia']]}),
    ])
    def test_400(self, plan_api, nombre, cambios, errores):
        r = cambiar(plan_api, nombre, **cambios)
        assert r.status_code == 400 and r.json()['errores'] == errores
        assert plan_api.cuenta(nombre)['version'] == 1

    def test_reclasificar_con_un_ejercicio_cerrado(self, plan_api):
        p = plan_api
        venta(p, 10)
        EjercicioContable.objects.filter(anio=2026).update(estado='cerrado', cerrado_en=timezone.now())
        r = cambiar(p, 'ventas', clase='activo')   # de resultados a balance
        assert r.status_code == 409 and r.json()['codigo'] == 'ejercicio_cerrado' and r.json()['ejercicios'] == [2026]
        assert r.json()['cuenta']['clase'] == 'ingreso'
        assert cambiar(p, 'ventas', clase=None).json()['codigo'] == 'ejercicio_cerrado'   # quitarle la clase también cruza
        assert cambiar(p, 'ventas', clase='costo').status_code == 200   # dentro de resultados, sí
        assert cambiar(p, 'clientes', clase='pasivo').status_code == 200   # dentro del balance, sí
        assert cambiar(p, 'caja', clase='gasto').status_code == 200   # sin líneas en ese ejercicio, sí

    def test_reclasificar_una_cuenta_de_la_apertura_confirmada(self, plan_api):
        p = plan_api
        apertura_confirmada(p)
        r = cambiar(p, 'capital', clase='ingreso')
        assert r.status_code == 409 and r.json()['codigo'] == 'apertura_confirmada'
        r = enviar(p.client, CLASIFICAR, {'empresa': p.empresa.pk, 'cuenta_id': p.c['capital'].pk, 'version': 1, 'clase': 'gasto'})
        assert r.status_code == 409 and r.json()['codigo'] == 'apertura_confirmada'
        assert cambiar(p, 'capital', clase='pasivo').status_code == 200

    def test_auxiliar_con_detalle_no_cambia(self, plan_api):
        p = plan_api
        tercero = {'tipo': 'cliente', 'id': 1, 'identificacion': '0912345678', 'nombre': 'CLIENTE'}
        ac.contabilizar(p.empresa, [(p.c['clientes'], 5, 0, {'tercero': tercero}), (p.c['ventas'], 0, 5)])
        r = cambiar(p, 'clientes', auxiliar='')
        assert r.status_code == 409 and (r.json()['codigo'], r.json()['auxiliares'], r.json()['lineas_con_tercero']) == (
            'cuenta_con_detalle', 0, 1)
        ac.filas_de_apertura(p.empresa, p.c, venta(p))   # un auxiliar vigente en una línea de proveedores
        r = cambiar(p, 'proveedores', auxiliar='banco')
        assert (r.json()['codigo'], r.json()['auxiliares'], r.json()['lineas_con_tercero']) == ('cuenta_con_detalle', 1, 0)
        AuxiliarApertura.objects.filter(cuenta=p.c['proveedores']).update(estado='anulado', anulado_en=timezone.now(),
                                                                         motivo_anulacion='x')
        assert cambiar(p, 'proveedores', auxiliar='').status_code == 200
        assert cambiar(p, 'clientes', clase='pasivo').status_code == 200   # la clase no depende del detalle

    def test_reclasificar_espera_al_candado(self, plan_api, monkeypatch):
        """Lo que depende del libro toma el candado (antes que la cola del plan); un cambio de nombre, no."""
        tomas = []
        original = candado.tomar_si_existe
        monkeypatch.setattr(candado, 'tomar_si_existe', lambda: tomas.append(1) or original())
        assert cambiar(plan_api, 'caja', nombre='Caja general').status_code == 200 and tomas == []
        assert cambiar(plan_api, 'caja', clase='activo', activa=True).status_code == 200 and tomas == [1]


class TestTieneMovimientos:

    def test_lineas_del_libro_y_de_la_apertura_viva(self, f):
        caja = f.c['caja']
        assert cuentas.tiene_movimientos(caja) is False
        apertura = ac.apertura_directa(f.empresa)
        linea = LineaApertura.objects.create(apertura=apertura, orden=1, cuenta=caja, debe=Decimal(1))
        assert cuentas.tiene_movimientos(caja) is True   # borrador
        for estado, tiene in (('en_revision', True), ('descartada', False)):
            Apertura.objects.filter(pk=apertura.pk).update(estado=estado, motivo='x')
            assert cuentas.tiene_movimientos(caja) is tiene, estado
        Apertura.objects.filter(pk=apertura.pk).update(estado='borrador')
        LineaApertura.objects.filter(pk=linea.pk).update(retirada=True, debe=None)
        assert cuentas.tiene_movimientos(caja) is False   # retirada
        ac.contabilizar(f.empresa, [(caja, 1, 0), (f.c['capital'], 0, 1)])
        assert cuentas.tiene_movimientos(caja) is True and cuentas.tiene_movimientos(f.c['bancos']) is False

    def test_con_movimientos_no_se_desactiva_ni_pasa_a_grupo(self, plan_api):
        venta(plan_api, 10)
        assert cambiar(plan_api, 'clientes', activa=False).json()['errores'] == {'activa': [cuentas.TEXTOS['con_movimientos_desactivar']]}
        assert cambiar(plan_api, 'ventas', tipo='grupo').json()['errores'] == {'tipo': [cuentas.TEXTOS['con_movimientos_grupo']]}
        assert cambiar(plan_api, 'bancos', activa=False).status_code == 200


class TestClasificar:

    @pytest.fixture
    def arbol(self, plan_api):
        p = plan_api
        Cuenta.objects.update(clase='')
        Cuenta.objects.filter(pk=p.c['bancos'].pk).update(clase='pasivo')   # una ya clasificada (a propósito distinta)
        return p

    def clasificar(self, p, nombre, clase='activo', incluir=True, **otros):
        cuenta = Cuenta.objects.get(pk=p.c[nombre].pk)
        datos = {'empresa': p.empresa.pk, 'cuenta_id': cuenta.pk, 'version': cuenta.version, 'clase': clase,
                 'incluir_descendientes': incluir, **otros}
        return enviar(p.client, CLASIFICAR, datos)

    def test_la_cuenta_y_sus_descendientes_sin_clase(self, arbol):
        p = arbol
        r = self.clasificar(p, 'activo')
        assert r.status_code == 200, r.content
        hijas = ('caja', 'clientes', 'inventario', 'credito_iva', 'equipos')
        assert r.json()['clasificadas'] == 1 + len(hijas) and r.json()['cuenta']['clase'] == 'activo'
        assert r.json()['cuenta']['version'] == 2
        assert {n: Cuenta.objects.get(pk=p.c[n].pk).clase for n in (*hijas, 'bancos', 'pasivo', 'proveedores')} == {
            **dict.fromkeys(hijas, 'activo'), 'bancos': 'pasivo', 'pasivo': '', 'proveedores': ''}   # nunca pisa ni sale del árbol
        assert Cuenta.objects.get(pk=p.c['caja'].pk).version == 2 and Cuenta.objects.get(pk=p.c['bancos'].pk).version == 1
        registro = AuditLog.objects.get(action='cuentas_clasificadas', company=p.empresa)
        assert registro.detail == {'cuenta': p.c['activo'].pk, 'codigo': '1', 'clase': ['', 'activo'],
                                   'incluir_descendientes': True, 'descendientes': 5, 'clasificadas': 6}
        otra_vez = self.clasificar(p, 'activo')   # nada que clasificar: ni versión ni auditoría
        assert otra_vez.json()['clasificadas'] == 0 and otra_vez.json()['cuenta']['version'] == 2
        assert AuditLog.objects.filter(action='cuentas_clasificadas').count() == 1

    def test_sin_descendientes_solo_la_cuenta(self, arbol):
        r = self.clasificar(arbol, 'pasivo', clase='pasivo', incluir=False)
        assert r.json()['clasificadas'] == 1 and Cuenta.objects.get(pk=arbol.c['proveedores'].pk).clase == ''

    def test_version_cuenta_y_validacion(self, arbol, empresa_b):
        p = arbol
        r = self.clasificar(p, 'activo', version=7)
        assert r.status_code == 409 and r.json()['codigo'] == 'version' and r.json()['cuenta']['clase'] == ''
        ajena = ac.plan_minimo(empresa_b)['activo']
        r = enviar(p.client, CLASIFICAR, {'empresa': p.empresa.pk, 'cuenta_id': ajena.pk, 'version': 1, 'clase': 'activo'})
        assert r.status_code == 404 and r.json()['codigo'] == 'cuenta'
        r = self.clasificar(p, 'activo', clase='', incluir='si')
        assert r.status_code == 400 and r.json()['errores'] == {'clase': [cuentas.TEXTOS['clase']],
                                                                'incluir_descendientes': [cuentas.TEXTOS['incluir_descendientes']]}
        r = enviar(p.client, CLASIFICAR, {'empresa': p.empresa.pk, 'clase': 'activo'})
        assert r.status_code == 400 and set(r.json()['errores']) == {'cuenta_id', 'version'}
        assert Cuenta.objects.exclude(clase='').count() == 1   # nada cambió


class TestImportacionConClase:

    def test_columna_clase(self, client, empresa):
        entrar(client, empresa)
        contenido = ('Código;Nombre;Clase\r\n1;Activo;Activo\r\n1.1;Caja;ACTIVO\r\n2;Pasivo;pasivo\r\n4;Ingresos;\r\n'
                     '5;Costos;Costos\r\n').encode()
        from django.core.files.uploadedfile import SimpleUploadedFile
        r = client.post('/contabilidad/api/cuentas/importar/', {'empresa': empresa.pk, 'clave': 'importar-clase-01',
                                                               'archivo': SimpleUploadedFile('plan.csv', contenido)})
        lote = r.json()['lote']
        assert lote['columnas'] == {'codigo': 'Código', 'nombre': 'Nombre', 'padre': None, 'tipo': None, 'clase': 'Clase'}
        assert [(f['codigo'], f['clase'], f['estado']) for f in lote['filas']] == [
            ('1', 'activo', 'valida'), ('1.1', 'activo', 'valida'), ('2', 'pasivo', 'valida'), ('4', '', 'valida'),
            ('5', '', 'error')]
        from core.contabilidad import importar_cuentas
        assert lote['filas'][4]['errores'] == [importar_cuentas.TEXTOS['clase'].format(valor='Costos')]
        sin_error = enviar(client, f'/contabilidad/api/cuentas/importar/{lote["id"]}/mapeo/',
                           {'empresa': empresa.pk, 'codigo': 'Código', 'nombre': 'Nombre'}).json()['lote']
        assert sin_error['resumen']['con_error'] == 0 and {f['clase'] for f in sin_error['filas']} == {''}
        enviar(client, f'/contabilidad/api/cuentas/importar/{lote["id"]}/mapeo/',
               {'empresa': empresa.pk, 'codigo': 'Código', 'nombre': 'Nombre', 'clase': 'Clase'})
        contenido = 'Código;Nombre;Class\r\n1;Activo;Activo\r\n2;Pasivo;\r\n'.encode()
        r = client.post('/contabilidad/api/cuentas/importar/', {'empresa': empresa.pk, 'clave': 'importar-clase-02',
                                                               'archivo': SimpleUploadedFile('plan.csv', contenido)})
        confirmado = enviar(client, f'/contabilidad/api/cuentas/importar/{r.json()["lote"]["id"]}/confirmar/',
                            {'empresa': empresa.pk, 'clave': 'confirmar-clase-1', 'duplicadas': 'omitir'})
        assert confirmado.status_code == 200, confirmado.content
        with company_context(empresa):
            assert dict(Cuenta.objects.values_list('codigo', 'clase')) == {'1': 'activo', '2': ''}


# ---------------------------------------------------------------- registro de claves

class TestRegistroClave:

    def test_previo_guardar_repetido_y_clave_usada(self, f):
        contenido = {'linea_id': 3, 'auxiliares': [{'saldo_inicial': Decimal('10.00')}]}
        with transaction.atomic():
            assert registro_clave.previo('lote-aux-0001', 'apertura_auxiliares', 'apertura', 5, contenido) is None
            registro_clave.guardar('lote-aux-0001', 'apertura_auxiliares', 'apertura', 5, contenido, {'creados': [1, 2]}, ac.AUTOR)
        assert registro_clave.previo('lote-aux-0001', 'apertura_auxiliares', 'apertura', 5, contenido) == {'creados': [1, 2]}
        for otro in (('apertura_auxiliares', 'apertura', 6, contenido), ('otra', 'apertura', 5, contenido),
                     ('apertura_auxiliares', 'apertura', 5, {**contenido, 'linea_id': 4})):
            with pytest.raises(api.ErrorApi) as error:
                registro_clave.previo('lote-aux-0001', *otro)
            assert (error.value.codigo, error.value.estado) == ('clave_usada', 409)
        with pytest.raises(api.ErrorApi) as error, transaction.atomic():
            registro_clave.guardar('lote-aux-0001', 'otra', 'apertura', 9, {}, {}, ac.AUTOR)
        assert error.value.codigo == 'clave_usada' and RegistroClave.objects.count() == 1
        assert registro_clave.huella({'b': 1, 'a': Decimal('1.50')}) == registro_clave.huella({'a': Decimal('1.50'), 'b': 1})


# ---------------------------------------------------------------- recorridos ast

ESCRITURAS = {'save', 'create', 'bulk_create', 'update', 'delete', 'bulk_update', 'get_or_create', 'update_or_create'}
DEL_LIBRO = {'Asiento', 'LineaAsiento'}


def _raiz(nodo):
    while isinstance(nodo, (ast.Attribute, ast.Call, ast.Subscript)):
        nodo = nodo.value if not isinstance(nodo, ast.Call) else nodo.func
    return nodo.id if isinstance(nodo, ast.Name) else None


def escrituras_del_libro(fuente):
    """Líneas donde un módulo escribe en Asiento o LineaAsiento: los construye (`Asiento(…)`) o llama a un método de
    escritura sobre una cadena que empieza en ellos (también con otro nombre importado: `import … as L`)."""
    arbol = ast.parse(fuente)
    nombres = set(DEL_LIBRO)
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom):
            nombres |= {a.asname for a in nodo.names if a.name in DEL_LIBRO and a.asname}
    lineas = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        if isinstance(nodo.func, ast.Name) and nodo.func.id in nombres:
            lineas.add(nodo.lineno)
        elif isinstance(nodo.func, ast.Attribute) and nodo.func.attr in ESCRITURAS and _raiz(nodo.func) in nombres:
            lineas.add(nodo.lineno)
        elif isinstance(nodo.func, ast.Attribute) and nodo.func.attr in DEL_LIBRO and nodo.func.attr in nombres:
            lineas.add(nodo.lineno)   # models.Asiento(…)
    return sorted(lineas)


def _codigo_literal(valor):
    return (isinstance(valor, ast.Constant) and isinstance(valor.value, str)) or (
        isinstance(valor, (ast.List, ast.Tuple, ast.Set)) and any(_codigo_literal(e) for e in valor.elts))


def cuentas_por_codigo_o_creadas(fuente):
    """Líneas donde se elige una cuenta por un código escrito en el programa (`codigo='1.1.01'`, `cuenta__codigo__in=[…]`,
    `cuenta.codigo == '…'`) o se crea una cuenta con `get_or_create`/`update_or_create` de `Cuenta`."""
    lineas = set()
    for nodo in ast.walk(ast.parse(fuente)):
        if isinstance(nodo, ast.Call):
            for argumento in nodo.keywords:
                if argumento.arg and (argumento.arg in ('codigo', 'codigo_norm') or argumento.arg.startswith(('codigo__',
                                      'codigo_norm__')) or '__codigo' in argumento.arg) and _codigo_literal(argumento.value):
                    lineas.add(nodo.lineno)
            if isinstance(nodo.func, ast.Attribute) and nodo.func.attr in ('get_or_create', 'update_or_create') \
                    and _raiz(nodo.func) == 'Cuenta':
                lineas.add(nodo.lineno)
        elif isinstance(nodo, ast.Compare):
            lados = [nodo.left, *nodo.comparators]
            if any(isinstance(l, ast.Attribute) and l.attr in ('codigo', 'codigo_norm') for l in lados) \
                    and any(_codigo_literal(l) for l in lados):
                lineas.add(nodo.lineno)
    return sorted(lineas)


def modulos(*carpetas):
    for carpeta in carpetas:
        for ruta in sorted((BASE / carpeta).rglob('*.py')):
            if 'migrations' not in ruta.parts:
                yield ruta.relative_to(BASE).as_posix(), ruta.read_text(encoding='utf-8')


class TestRecorridos:

    def test_solo_diario_escribe_en_el_libro(self):
        permitidos = {'core/contabilidad/diario.py', 'core/contabilidad/modelos_libro.py'}
        malos = {ruta: lineas for ruta, fuente in modulos('core') if ruta not in permitidos
                 for lineas in [escrituras_del_libro(fuente)] if lineas}
        assert not malos, malos
        assert escrituras_del_libro((BASE / 'core/contabilidad/diario.py').read_text(encoding='utf-8'))   # sí ve las de diario

    def test_el_recorrido_del_libro_ve_todas_las_formas(self):
        fuente = ('from core.contabilidad.models import Asiento, LineaAsiento as L, Cuenta\n'
                  'Asiento.objects.create(x=1)\n'
                  'L.objects.bulk_create([])\n'
                  'Asiento.objects.filter(pk=1).update(sellado=True)\n'
                  'a = Asiento(numero=1)\n'
                  'Asiento.all_companies.filter(pk=1).delete()\n'
                  'Asiento.objects.filter(pk=1).count()\n'          # leer no es escribir
                  'Cuenta.objects.create(codigo=x)\n'
                  'LineaAsiento.objects.get_or_create(orden=1)\n'
                  'from core.contabilidad import models\nmodels.Asiento(numero=2)\n')
        assert escrituras_del_libro(fuente) == [2, 3, 4, 5, 6, 9, 11]

    def test_ningun_codigo_de_cuenta_escrito_ni_get_or_create_de_cuenta(self):
        malos = {ruta: lineas for ruta, fuente in modulos('core/contabilidad') for lineas in [cuentas_por_codigo_o_creadas(fuente)]
                 if lineas}
        assert not malos, malos

    def test_el_recorrido_de_cuentas_ve_todas_las_formas(self):
        fuente = ('Cuenta.objects.get(codigo="1.1.01")\n'
                  'Cuenta.objects.filter(codigo__in=["1", x])\n'
                  'LineaAsiento.objects.filter(cuenta__codigo="4.1")\n'
                  'Cuenta.objects.get_or_create(nombre=x)\n'
                  'if cuenta.codigo == "1.1.01": pass\n'
                  'Cuenta.objects.filter(codigo=codigo)\n'          # un código que viene de los datos: bien
                  'Cuenta(codigo=fila.codigo)\n'
                  'Cuenta.objects.filter(codigo_norm__startswith="1.")\n')
        assert cuentas_por_codigo_o_creadas(fuente) == [1, 2, 3, 4, 5, 8]
