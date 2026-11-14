"""Concurrencia real en PostgreSQL del plan de cuentas (core/contabilidad/cuentas.py): (a) el mismo envío varias veces a
la vez deja una sola cuenta; (b) el mismo código con claves distintas, una sola; (c) dos cambios simultáneos con la misma
versión: uno gana y el otro recibe 409 `version` con la cuenta como quedó; (d) dos movimientos cruzados no cierran un
ciclo; (e) colgar una hija de un grupo mientras ese grupo pasa a cuenta de movimiento: solo una de las dos cosas ocurre.

Casi todas se prueban dos veces: con la cola por empresa (`cuentas.serializar`) y sin ella, porque la garantía no puede
depender solo de la cola: sin ella deciden la fila bloqueada y las restricciones únicas. El ciclo cruzado es justo lo que
solo la cola impide. Transacciones reales (transaction=True) y una conexión por hilo; va al final (test_zz_*) y crea todos
sus datos, porque las pruebas transaccionales vacían la base."""
import threading
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Group, Permission
from django.db import connection, connections

from core.contabilidad import api, cuentas
from core.contabilidad.models import Cuenta
from core.pos.models import Company
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, AuditLog, Membership
from core.user.models import User

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]
CODIGOS = ('view_cuenta', 'add_cuenta', 'change_cuenta')
T = cuentas.TEXTOS


@pytest.fixture(params=[True, False], ids=['con_cola', 'sin_cola'])
def cola(request, monkeypatch):
    """Sin cola: como si otra parte del sistema escribiera el plan sin pasar por `cuentas.serializar`."""
    if not request.param:
        monkeypatch.setattr(cuentas, 'serializar', lambda empresa: None)
    return request.param


def preparar():
    empresa = Company.objects.create(ruc='0990000907001', business_name='CUENTAS S.A.', tradename='CUENTAS', main_address='x',
                                     establishment_address='x', establishment_code='001', issuing_point_code='001',
                                     special_taxpayer='000', mobile='0990000000', phone='042000000', email='e@example.com',
                                     website='https://example.com', electronic_signature_key='', email_host_user='',
                                     email_host_password='')
    grupo, _ = Group.objects.get_or_create(name=ROLE_OWNER)
    grupo.permissions.add(*Permission.objects.filter(content_type__app_label='contabilidad', codename__in=CODIGOS))
    usuarios = []
    for n in range(3):
        usuario = User.objects.create(username=f'ctas.conc.{n}', names=f'Usuario {n}', email=f'c{n}@example.com')
        usuarios.append((usuario, Membership.objects.create(user=usuario, company=empresa, group=grupo)))
    return empresa, usuarios


def peticion(empresa, usuario, membresia):
    return SimpleNamespace(user=usuario, company=empresa, membership=membresia, META={'REMOTE_ADDR': '127.0.0.1'}, method='POST')


def sembrar(empresa, codigo, tipo='grupo', padre=None):
    with company_context(empresa):
        return Cuenta.objects.create(codigo=codigo, nombre=f'Cuenta {codigo}', tipo=tipo, padre=padre)


def en_paralelo(tareas):
    """Ejecuta cada tarea en su hilo y su conexión, a la vez (barrera). Devuelve (resultados, errores)."""
    barrera, resultados, errores, cerrojo = threading.Barrier(len(tareas)), [], [], threading.Lock()

    def correr(tarea):
        try:
            barrera.wait()
            resultado = tarea()
            with cerrojo:
                resultados.append(resultado)
        except Exception as e:  # noqa: BLE001 - se informa en la aserción
            with cerrojo:
                errores.append(e)
        finally:
            connections.close_all()

    hilos = [threading.Thread(target=correr, args=(t,)) for t in tareas]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)
    return resultados, errores


def intentar(empresa, accion):
    """Tarea de un hilo: ejecuta `accion()` en la empresa y devuelve ('hecho', resultado) o el rechazo que recibió,
    (código, errores por campo, lo demás del cuerpo)."""
    def tarea():
        with company_context(empresa):
            try:
                return 'hecho', accion()
            except api.ErrorApi as e:
                return e.codigo, e.errores, e.extra
    return tarea


def alta(empresa, usuario, membresia, **datos):
    def accion():
        cuenta, repetido = cuentas.crear(peticion(empresa, usuario, membresia), {'nombre': 'Caja', 'tipo': 'movimiento', **datos})
        return cuenta.pk, repetido
    return intentar(empresa, accion)


def cambio(empresa, usuario, membresia, pk, **datos):
    def accion():
        cuenta = cuentas.modificar(peticion(empresa, usuario, membresia), pk, datos)
        return cuenta.version, cuenta.nombre
    return intentar(empresa, accion)


def test_misma_clave_una_sola_cuenta(cola):
    empresa, usuarios = preparar()
    tareas = [alta(empresa, *usuarios[n], clave='cuenta-simultanea-1', codigo='1.1.01') for n in range(3)]
    resultados, errores = en_paralelo(tareas)
    assert not errores, errores
    assert len(resultados) == 3 and {estado for estado, _ in resultados} == {'hecho'}
    assert len({pk for _, (pk, _) in resultados}) == 1                          # los tres recibieron la misma cuenta
    assert sorted(repetido for _, (_, repetido) in resultados) == [False, True, True]   # y solo uno la creó
    with company_context(empresa):
        assert Cuenta.objects.count() == 1
    assert AuditLog.objects.filter(action='cuenta_creada', company=empresa).count() == 1


def test_mismo_codigo_con_claves_distintas_una_sola_cuenta(cola):
    empresa, usuarios = preparar()
    codigos = ('1.1.01a', '1.1.01A', ' 1.1.01a ')   # el mismo código para la empresa: sin distinguir mayúsculas ni espacios
    tareas = [alta(empresa, *usuarios[n], clave=f'mismo-codigo-{n}', codigo=codigos[n]) for n in range(3)]
    resultados, errores = en_paralelo(tareas)
    assert not errores, errores
    assert sorted(estado for estado, *_ in resultados) == ['hecho', 'validacion', 'validacion']
    with company_context(empresa):
        guardada = Cuenta.objects.get()
    for estado, errores_de_campo, _ in (r for r in resultados if r[0] != 'hecho'):
        assert errores_de_campo == {'codigo': [T['codigo_repetido'].format(codigo=guardada.codigo)]}


def test_dos_cambios_con_la_misma_version_uno_gana(cola):
    empresa, usuarios = preparar()
    cuenta = sembrar(empresa, '1.1.01', 'movimiento')
    tareas = [cambio(empresa, *usuarios[n], cuenta.pk, version=1, nombre=f'Nombre {n}') for n in range(2)]
    resultados, errores = en_paralelo(tareas)
    assert not errores, errores
    assert sorted(r[0] for r in resultados) == ['hecho', 'version']
    (_, (version, nombre)), = [r for r in resultados if r[0] == 'hecho']
    (_, _, extra), = [r for r in resultados if r[0] == 'version']
    with company_context(empresa):
        guardada = Cuenta.objects.get(pk=cuenta.pk)
    assert (guardada.version, guardada.nombre) == (2, nombre) == (version, nombre)
    assert extra['cuenta'] == cuentas_dict(empresa, guardada)   # el que perdió recibe la cuenta como la dejó el otro
    assert AuditLog.objects.filter(action='cuenta_modificada', company=empresa).count() == 1


def cuentas_dict(empresa, cuenta):
    with company_context(empresa):
        return cuentas.dict_cuenta(cuenta)


def test_dos_movimientos_cruzados_no_cierran_un_ciclo():
    """A pasa bajo una hija de B mientras B pasa bajo una hija de A: cada movimiento, mirado solo, es válido, y bloquean
    filas distintas. La cola por empresa hace que el segundo vea el primero."""
    empresa, usuarios = preparar()
    a, b = sembrar(empresa, 'A'), sembrar(empresa, 'B')
    a1, b1 = sembrar(empresa, 'A.1', padre=a), sembrar(empresa, 'B.1', padre=b)
    resultados, errores = en_paralelo([cambio(empresa, *usuarios[0], a.pk, version=1, padre_id=b1.pk),
                                       cambio(empresa, *usuarios[1], b.pk, version=1, padre_id=a1.pk)])
    assert not errores, errores
    assert sorted(r[0] for r in resultados) == ['hecho', 'validacion']
    (_, errores_de_campo, _), = [r for r in resultados if r[0] == 'validacion']
    assert errores_de_campo == {'padre_id': [T['ciclo']]}
    with company_context(empresa):
        padres = dict(Cuenta.objects.values_list('pk', 'padre_id'))
    assert sorted(v is None for v in (padres[a.pk], padres[b.pk])) == [False, True]   # una se movió; la otra sigue en la raíz
    for inicio in padres:   # desde cualquier cuenta se llega a la raíz
        vistos, actual = set(), inicio
        while actual is not None:
            assert actual not in vistos, 'ciclo en el árbol'
            vistos.add(actual)
            actual = padres[actual]


def test_colgar_una_hija_mientras_el_padre_pasa_a_movimiento(cola):
    empresa, usuarios = preparar()
    grupo = sembrar(empresa, '1.1')
    resultados, errores = en_paralelo([alta(empresa, *usuarios[0], clave='hija-simultanea-1', codigo='1.1.01', padre_id=grupo.pk),
                                       cambio(empresa, *usuarios[1], grupo.pk, version=1, tipo='movimiento')])
    assert not errores, errores
    assert sorted(r[0] for r in resultados) == ['hecho', 'validacion']   # solo una de las dos cosas ocurre
    (_, errores_de_campo, _), = [r for r in resultados if r[0] == 'validacion']
    with company_context(empresa):
        tipo, hijas = Cuenta.objects.get(pk=grupo.pk).tipo, Cuenta.objects.filter(padre_id=grupo.pk).count()
    assert (tipo, hijas, errores_de_campo) in (('grupo', 1, {'tipo': [T['con_hijas']]}),          # ganó el alta
                                               ('movimiento', 0, {'padre_id': [T['padre']]}))    # ganó el cambio de tipo
