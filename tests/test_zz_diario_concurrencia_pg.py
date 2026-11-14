"""Concurrencia real del libro diario en PostgreSQL (core/contabilidad/candado.py, diario.py y la reclasificación de
cuentas.py), con transacciones reales (transaction=True) y una conexión por hilo; va al final (test_zz_*) y crea todos sus
datos, porque las pruebas transaccionales vacían la base.

- ocho contabilizaciones a la vez, en dos empresas: cada empresa numera 1…4 sin huecos ni repetidos y sus acumulados
  cuadran (el candado es por empresa: la otra no espera);
- dos reversos simultáneos del mismo asiento: con la misma clave, un reverso y el otro `repetido`; con claves distintas, uno
  gana y el otro recibe `ya_reversado`;
- crear el inicio contable a la vez (patrón de carrera de `candado.libro(crear=…)`): una sola fila, y los dos siguen;
- reclasificar una cuenta espera al candado del libro que tiene otra transacción; cambiarle el nombre, no."""
import threading
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.db.models import Sum

from core.contabilidad import candado, cuentas, diario
from core.contabilidad.models import Asiento, Cuenta, EjercicioContable, InicioContable, LineaAsiento, SaldoCuentaMes
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, Membership
from core.user.models import User
from tests import ayudas_contables as ac
from tests import helpers

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]


@pytest.fixture
def libro():
    a, b = helpers.crear_empresa('DIARIO A', plan=None), helpers.crear_empresa('DIARIO B', plan=None)
    cuentas_a, cuentas_b = ac.plan_minimo(a), ac.plan_minimo(b)
    ac.inicio_directo(a)
    ac.inicio_directo(b)
    return a, cuentas_a, b, cuentas_b


def lineas(c, importe):
    return [(c['caja'], importe, 0), (c['capital'], 0, importe)]


def test_ocho_a_la_vez_en_dos_empresas(libro):
    a, ca, b, cb = libro
    tareas = [lambda e=e, c=c, n=n: (e.pk, ac.contabilizar(e, lineas(c, n + 1)).numero)
              for n in range(4) for e, c in ((a, ca), (b, cb))]
    resultados, errores = ac.en_paralelo(tareas)
    assert not errores, errores
    for empresa, plan in ((a, ca), (b, cb)):
        assert sorted(numero for pk, numero in resultados if pk == empresa.pk) == [1, 2, 3, 4]
        with company_context(empresa):
            assert EjercicioContable.objects.get(anio=2026).ultimo_numero == 4
            assert SaldoCuentaMes.objects.get(cuenta=plan['caja']).debe == Decimal(1 + 2 + 3 + 4)
            assert LineaAsiento.objects.aggregate(d=Sum('debe'))['d'] == Decimal(10)
            assert all(c['ok'] for c in diario.verificar(2026)['comprobaciones'])


@pytest.mark.parametrize('misma_clave', [True, False], ids=['misma_clave', 'claves_distintas'])
def test_dos_reversos_simultaneos(libro, misma_clave):
    a, ca, *_ = libro
    original = ac.contabilizar(a, lineas(ca, 50))
    claves = ['reverso-paralelo-1', 'reverso-paralelo-1' if misma_clave else 'reverso-paralelo-2']

    def reversar(clave):
        try:
            reverso, repetido = ac.reversar(a, original, clave=clave)
            return ('repetido' if repetido else 'reversado', reverso.pk)
        except diario.ErrorDiario as e:
            return (e.codigo, None)
    resultados, errores = ac.en_paralelo([lambda clave=clave: reversar(clave) for clave in claves])
    assert not errores, errores
    estados = sorted(estado for estado, _ in resultados)
    assert estados == (['repetido', 'reversado'] if misma_clave else ['reversado', 'ya_reversado'])
    with company_context(a):
        reversos = list(Asiento.objects.filter(reversa_de=original).values_list('pk', flat=True))
        assert len(reversos) == 1 and Asiento.objects.get(pk=original.pk).reversado_por_id == reversos[0]
        if misma_clave:
            assert {pk for _, pk in resultados} == set(reversos)
        assert all(c['ok'] for c in diario.verificar(2026)['comprobaciones'])


def test_crear_el_inicio_a_la_vez(libro):
    nueva = helpers.crear_empresa('DIARIO C', plan=None)
    from datetime import date
    datos = dict(modalidad='saldos', fecha_corte=date(2025, 12, 31), contabilidad_desde=date(2026, 1, 1),
                 operaciones_desde=date(2026, 1, 1), creado_por_nombre='x', actualizado_por_nombre='x')

    def crear():
        with company_context(nueva), candado.libro(crear=datos) as inicio:
            return inicio.pk
    resultados, errores = ac.en_paralelo([crear, crear, crear])
    assert not errores, errores
    with company_context(nueva):
        assert InicioContable.objects.count() == 1 and set(resultados) == {InicioContable.objects.get().pk}


def _dueno(empresa):
    grupo, _ = Group.objects.get_or_create(name=ROLE_OWNER)
    grupo.permissions.add(*Permission.objects.filter(content_type__app_label='contabilidad', codename__in=(
        'view_cuenta', 'add_cuenta', 'change_cuenta')))
    usuario = User.objects.create(username=f'diario.conc.{empresa.pk}', names='Dueño', email=f'd{empresa.pk}@example.com')
    Membership.objects.create(user=usuario, company=empresa, group=grupo)
    return ac.peticion(usuario, empresa, 'patch')


@pytest.mark.parametrize('cambio, espera', [({'clase': 'pasivo'}, True), ({'nombre': 'Caja general'}, False)],
                         ids=['clase', 'nombre'])
def test_reclasificar_espera_al_candado_y_renombrar_no(libro, cambio, espera):
    a, ca, *_ = libro
    peticion = _dueno(a)
    tomado, terminado, hubo_espera = threading.Event(), threading.Event(), []

    def sostener():
        with company_context(a), candado.libro():
            tomado.set()
            # Se suelta cuando el otro termina o, si espera al candado, cuando se le ve esperando un bloqueo.
            for _ in range(200):
                if terminado.wait(0.05):
                    break
                with connection.cursor() as cursor:
                    cursor.execute('SELECT count(*) FROM pg_locks l JOIN pg_stat_activity s ON s.pid = l.pid '
                                   'WHERE NOT l.granted AND s.datname = current_database() AND l.pid <> pg_backend_pid()')
                    if cursor.fetchone()[0]:
                        hubo_espera.append(True)
                        break
        return 'soltado'

    def cambiar():
        tomado.wait(10)
        with company_context(a):
            cuenta = Cuenta.objects.get(pk=ca['caja'].pk)
            resultado = cuentas.modificar(peticion, cuenta.pk, {'version': cuenta.version, **cambio})
        terminado.set()
        return resultado.version
    resultados, errores = ac.en_paralelo([sostener, cambiar])
    assert not errores, errores
    assert bool(hubo_espera) is espera
    with company_context(a):
        guardada = Cuenta.objects.get(pk=ca['caja'].pk)
        assert guardada.version == 2 and all(getattr(guardada, k) == v for k, v in cambio.items())
