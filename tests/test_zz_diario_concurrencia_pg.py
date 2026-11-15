"""Concurrencia real del libro diario en PostgreSQL (core/contabilidad/candado.py, diario.py y la reclasificación de
cuentas.py), con transacciones reales (transaction=True) y una conexión por hilo; va al final (test_zz_*) y crea todos sus
datos, porque las pruebas transaccionales vacían la base.

- ocho contabilizaciones a la vez, en dos empresas: cada empresa numera 1…4 sin huecos ni repetidos y sus acumulados
  cuadran (el candado es por empresa: la otra no espera);
- dos reversos simultáneos del mismo asiento: con la misma clave, un reverso y el otro `repetido`; con claves distintas, uno
  gana y el otro recibe `ya_reversado`;
- crear el inicio contable a la vez (patrón de carrera de `candado.libro(crear=…)`): una sola fila, y los dos siguen;
- reclasificar una cuenta espera al candado del libro que tiene otra transacción; cambiarle el nombre, no;
- el plan de cuentas no se cruza con el libro (C2A-1): confirmar una importación del plan mientras se contabiliza un asiento
  o se confirma la apertura con el capital como primera línea, y mover una cuenta bajo otra que el asiento usa antes que a
  ella. Las FK hacia `contabilidad_cuenta` (líneas del asiento y de la apertura, acumulados, padre de la cuenta…) son
  DEFERRABLE INITIALLY DEFERRED: PostgreSQL toma su FOR KEY SHARE de cada cuenta al confirmar, en el orden en que se
  insertaron las filas (el de las líneas). Con FOR UPDATE en las cuentas, la importación (que las bloquea todas por id) o
  el cambio (la cuenta y después el padre) y el libro se esperaban en cruz y PostgreSQL abortaba uno (40P01, un 500); con
  FOR NO KEY UPDATE el libro ni siquiera espera. Una conexión auxiliar retiene una cuenta solo para fijar el momento y la
  suelta antes de que el ciclo se cierre: si hay interbloqueo, lo forman el plan y el libro."""
import threading
import time
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection, connections, transaction
from django.db.models import Sum

from core.contabilidad import api, candado, cuentas, diario, importar_cuentas
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


# ---------------------------------------------------------------- el plan de cuentas frente al libro (C2A-1)

PLAN_DE_UNA_CUENTA = 'Código;Nombre\r\n9;Cuentas de orden\r\n'.encode()
CODIGOS_DEL_PLAN = ('view_cuenta', 'add_cuenta', 'change_cuenta', 'view_apertura', 'add_apertura',
                    'change_confirmacion_apertura', 'view_asiento')


def _quien_escribe_el_plan(empresa):
    grupo, _ = Group.objects.get_or_create(name=ROLE_OWNER)
    grupo.permissions.add(*Permission.objects.filter(codename__in=CODIGOS_DEL_PLAN))
    return helpers.crear_usuario(f'plan.libro.{empresa.pk}', empresa, grupo)


def _pid():
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_backend_pid()')
        return cursor.fetchone()[0]


def _espera_un_bloqueo(pid):
    with connection.cursor() as cursor:
        cursor.execute('SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = %s AND NOT granted)', [pid])
        return cursor.fetchone()[0]


def _hasta(condicion, segundos=30):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return False


def _resultado(funcion):
    """('hecho', lo que devolvió), ('rechazo', código, errores) o, si la base abortó la transacción, ('error', clase,
    SQLSTATE, primera línea del mensaje): un interbloqueo es ('error', 'OperationalError', '40P01', 'deadlock detected')."""
    try:
        return ('hecho', funcion())
    except api.ErrorApi as e:
        return ('rechazo', e.codigo, e.errores)
    except DatabaseError as e:
        return ('error', type(e).__name__, getattr(e.__cause__, 'sqlstate', None), str(e).splitlines()[0])


def _cruce(empresa, retenida, modo, plan, libro):
    """Carrera con el momento fijado entre una escritura del plan (`plan`) y una del libro (`libro`), funciones sin
    argumentos que corren cada una en su hilo y su conexión. Una conexión auxiliar H retiene la cuenta `retenida` (FOR
    UPDATE o, con `modo='no_key'`, FOR NO KEY UPDATE) solo para fijar el momento:

    1. H bloquea `retenida`; el plan arranca, bloquea lo que le toca antes y se queda esperando a H;
    2. el libro arranca y, en cuanto espera un bloqueo (o si termina antes), H suelta;
    3. el plan sigue.

    H ya soltó cuando el ciclo se cerraría. Devuelve `(resultados {'plan', 'libro'}, el libro esperó)`."""
    pids, resultados, retenida_ya, soltar = {}, {}, threading.Event(), threading.Event()

    def retener():
        try:
            with company_context(empresa), transaction.atomic():
                list(Cuenta.objects.select_for_update(no_key=modo == 'no_key').filter(pk=retenida.pk).values_list('pk'))
                retenida_ya.set()
                soltar.wait(60)
        finally:
            connections.close_all()

    def hilo(nombre, funcion):
        def correr():
            try:
                pids[nombre] = _pid()
                with company_context(empresa):
                    resultados[nombre] = _resultado(funcion)
            finally:
                connections.close_all()
        return threading.Thread(target=correr)

    hilos = [threading.Thread(target=retener), hilo('plan', plan), hilo('libro', libro)]
    hilos[0].start()
    assert retenida_ya.wait(30), 'H no llegó a bloquear la cuenta'
    hilos[1].start()
    assert _hasta(lambda: 'plan' in pids and _espera_un_bloqueo(pids['plan'])), 'el plan no llegó a esperar a H'
    hilos[2].start()
    _hasta(lambda: 'libro' in resultados or ('libro' in pids and _espera_un_bloqueo(pids['libro'])))
    libro_espero = 'libro' not in resultados
    soltar.set()
    for h in hilos:
        h.join(60)
    return resultados, libro_espero


def _importar(empresa, usuario):
    """Un lote del plan en vista previa con una cuenta nueva y la función que confirma su importación (devuelve cuántas
    creó). La confirmación bloquea todas las cuentas de la empresa por id."""
    with company_context(empresa):
        lote, _ = importar_cuentas.subir(ac.peticion(usuario, empresa), SimpleUploadedFile('plan.csv', PLAN_DE_UNA_CUENTA),
                                         {'clave': ac.clave('subida-plan')})

    def confirmar():
        hecho, _ = importar_cuentas.confirmar(ac.peticion(usuario, empresa), lote.pk,
                                              {'clave': ac.clave('confirma-plan'), 'duplicadas': 'omitir'})
        return hecho.resultado['creadas']
    return confirmar


def test_las_fk_hacia_la_cuenta_son_diferidas():
    """Lo que suponen las carreras de abajo: el FOR KEY SHARE de cada FK hacia la cuenta se toma al confirmar."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT conrelid::regclass::text, condeferrable AND condeferred FROM pg_constraint "
                       "WHERE contype = 'f' AND confrelid = 'contabilidad_cuenta'::regclass")
        fk = dict(cursor.fetchall())
    assert {'contabilidad_lineaasiento', 'contabilidad_saldocuentames', 'contabilidad_lineaapertura',
            'contabilidad_cuenta'} <= set(fk) and all(fk.values()), fk


def test_importar_el_plan_mientras_se_contabiliza_con_el_capital_primero():
    """La importación bloquea caja y espera a H en bancos; el asiento (capital al haber como línea 1, caja al debe) confirma
    y toma el FOR KEY SHARE de capital y luego el de caja. Antes: el asiento esperaba a la importación por caja, la
    importación llegaba a capital y esperaba al asiento, y PostgreSQL abortaba el asiento (40P01)."""
    a = helpers.crear_empresa('PLAN Y ASIENTO', plan=None)
    c = ac.plan_minimo(a)
    ac.inicio_directo(a)
    importar = _importar(a, _quien_escribe_el_plan(a))
    assert c['caja'].pk < c['bancos'].pk < c['capital'].pk
    resultados, libro_espero = _cruce(a, c['bancos'], 'update', importar,
                                      lambda: ac.contabilizar(a, [(c['capital'], 0, 25), (c['caja'], 25, 0)]).numero)
    assert resultados == {'plan': ('hecho', 1), 'libro': ('hecho', 1)}
    assert not libro_espero   # FOR NO KEY UPDATE no excluye el FOR KEY SHARE de las líneas


def test_importar_el_plan_mientras_se_confirma_la_apertura_con_el_capital_primero():
    """Lo mismo con apertura.confirmar: su asiento lleva las líneas en el orden de la apertura (capital primero)."""
    a = helpers.crear_empresa('PLAN Y APERTURA', plan=None)
    c = ac.plan_minimo(a)
    usuario = _quien_escribe_el_plan(a)
    apertura = ac.apertura_en_revision(a, [(c['capital'], None, '25.00'), (c['caja'], '25.00', None)], usuario=usuario)
    importar = _importar(a, usuario)
    resultados, libro_espero = _cruce(a, c['bancos'], 'update', importar,
                                      lambda: ac.confirmar(a, apertura, usuario=usuario)[0].estado)
    assert resultados == {'plan': ('hecho', 1), 'libro': ('hecho', 'confirmada')}
    assert not libro_espero


def test_mover_una_cuenta_bajo_otra_que_el_asiento_usa_antes():
    """`cuentas.modificar` bloquea la cuenta (bancos) y después el padre pedido (caja), que H retiene con FOR NO KEY UPDATE:
    no excluye el FOR KEY SHARE del asiento (caja al debe como línea 1, bancos al haber). Caja es de movimiento, así que el
    cambio acaba en 400 `padre`; antes, el asiento esperaba al cambio por bancos, el cambio esperaba al asiento por caja y
    PostgreSQL abortaba uno de los dos (40P01). Sin el candado del libro: el envío solo trae el padre."""
    a = helpers.crear_empresa('MOVER Y ASIENTO', plan=None)
    c = ac.plan_minimo(a)
    ac.inicio_directo(a)
    peticion, bancos = ac.peticion(_quien_escribe_el_plan(a), a, 'patch'), c['bancos']
    resultados, libro_espero = _cruce(
        a, c['caja'], 'no_key', lambda: cuentas.modificar(peticion, bancos.pk, {'version': bancos.version,
                                                                                 'padre_id': c['caja'].pk}).version,
        lambda: ac.contabilizar(a, [(c['caja'], 25, 0), (c['bancos'], 0, 25)]).numero)
    assert resultados == {'plan': ('rechazo', 'validacion', {'padre_id': [cuentas.TEXTOS['padre']]}), 'libro': ('hecho', 1)}
    assert not libro_espero
