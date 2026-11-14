"""Concurrencia real en PostgreSQL del plan de cuentas (core/contabilidad/cuentas.py): (a) el mismo envío varias veces a
la vez deja una sola cuenta; (b) el mismo código con claves distintas, una sola; (c) dos cambios simultáneos con la misma
versión: uno gana y el otro recibe 409 `version` con la cuenta como quedó; (d) dos movimientos cruzados no cierran un
ciclo; (e) colgar una hija de un grupo mientras ese grupo pasa a cuenta de movimiento: solo una de las dos cosas ocurre.

Y de su importación (core/contabilidad/importar_cuentas.py): (f) la misma subida varias veces a la vez deja un solo lote y
un solo archivo; (g) dos o tres confirmaciones a la vez crean las cuentas una sola vez (con la misma clave las demás reciben
el mismo resultado; con otra, 409 `lote_confirmado`); (h) confirmar mientras alguien da de alta uno de esos códigos deja una
sola cuenta con ese código; (i) actualizar nombres mientras alguien edita una de esas cuentas no pierde ningún cambio.

Casi todas se prueban dos veces: con la cola por empresa (`cuentas.serializar`) y sin ella, porque la garantía no puede
depender solo de la cola: sin ella deciden la fila bloqueada y las restricciones únicas. El ciclo cruzado es justo lo que
solo la cola impide. Transacciones reales (transaction=True) y una conexión por hilo; va al final (test_zz_*) y crea todos
sus datos, porque las pruebas transaccionales vacían la base."""
import os
import threading
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections

from core.contabilidad import api, cuentas, importar_cuentas
from core.contabilidad.models import Cuenta, ImportacionCuentas
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


# ---------------------------------------------------------------- importación del plan

PLAN = 'Código;Nombre\r\n1;Activo\r\n1.1;Activo corriente\r\n1.1.01;Caja\r\n1.1.02;Bancos\r\n2;Pasivo\r\n'.encode()


def subida(empresa, usuario, membresia, clave='subida-simultanea-1', contenido=PLAN):
    def accion():
        lote, repetido = importar_cuentas.subir(peticion(empresa, usuario, membresia), SimpleUploadedFile('plan.csv', contenido),
                                                {'clave': clave})
        return lote.pk, repetido
    return intentar(empresa, accion)


def confirmacion(empresa, usuario, membresia, pk, clave, duplicadas='omitir'):
    def accion():
        lote, repetido = importar_cuentas.confirmar(peticion(empresa, usuario, membresia), pk, {'clave': clave, 'duplicadas': duplicadas})
        return repetido, lote.resultado['creadas'], lote.resultado['actualizadas'], lote.resultado['omitidas']
    return intentar(empresa, accion)


def lote_en_vista_previa(empresa, usuario, membresia):
    estado, (pk, _) = subida(empresa, usuario, membresia, clave='lote-por-confirmar')()
    assert estado == 'hecho'
    return pk


def codigos(empresa):
    with company_context(empresa):
        return sorted(Cuenta.objects.values_list('codigo', flat=True))


def test_la_misma_subida_varias_veces_a_la_vez_deja_un_solo_lote():
    """La subida no pasa por la cola del plan (no escribe cuentas): decide la clave única del lote."""
    empresa, usuarios = preparar()
    resultados, errores = en_paralelo([subida(empresa, *usuarios[n]) for n in range(3)])
    assert not errores, errores
    assert len(resultados) == 3 and {estado for estado, _ in resultados} == {'hecho'}
    assert len({pk for _, (pk, _) in resultados}) == 1                                 # los tres recibieron el mismo lote
    assert sorted(repetido for _, (_, repetido) in resultados) == [False, True, True]   # y solo uno lo creó
    with company_context(empresa):
        lote = ImportacionCuentas.objects.get()
        assert Cuenta.objects.count() == 0
    carpeta = os.path.dirname(os.path.join(settings.MEDIA_ROOT, lote.archivo.name))
    assert os.listdir(carpeta) == [os.path.basename(lote.archivo.name)]   # los archivos de las subidas que perdieron se borraron


def test_varias_confirmaciones_con_la_misma_clave_crean_las_cuentas_una_sola_vez(cola):
    empresa, usuarios = preparar()
    lote = lote_en_vista_previa(empresa, *usuarios[0])
    resultados, errores = en_paralelo([confirmacion(empresa, *usuarios[n], lote, 'confirma-simultanea') for n in range(3)])
    assert not errores, errores
    assert len(resultados) == 3 and {estado for estado, _ in resultados} == {'hecho'}
    assert sorted(resultado for _, resultado in resultados) == [(False, 5, 0, 0), (True, 5, 0, 0), (True, 5, 0, 0)]
    assert codigos(empresa) == ['1', '1.1', '1.1.01', '1.1.02', '2']
    assert AuditLog.objects.filter(action='cuentas_importadas', company=empresa).count() == 1


def test_dos_confirmaciones_con_claves_distintas_solo_una_confirma(cola):
    empresa, usuarios = preparar()
    lote = lote_en_vista_previa(empresa, *usuarios[0])
    resultados, errores = en_paralelo([confirmacion(empresa, *usuarios[n], lote, f'confirma-distinta-{n}') for n in range(2)])
    assert not errores, errores
    assert sorted(r[0] for r in resultados) == ['hecho', 'lote_confirmado']
    (_, _, extra), = [r for r in resultados if r[0] == 'lote_confirmado']
    assert (extra['lote']['estado'], extra['lote']['creadas']) == ('confirmado', 5)   # el que perdió recibe el lote como quedó
    assert codigos(empresa) == ['1', '1.1', '1.1.01', '1.1.02', '2']
    assert AuditLog.objects.filter(action='cuentas_importadas', company=empresa).count() == 1


def test_confirmar_mientras_se_da_de_alta_uno_de_esos_codigos(cola):
    """Pase lo que pase queda una sola cuenta 1.1.02. Con la cola, el segundo ve lo que hizo el primero. Sin ella puede
    además decidir la restricción única: la confirmación se deshace entera (409 `plan_cambiado`) y basta repetirla."""
    empresa, usuarios = preparar()
    lote = lote_en_vista_previa(empresa, *usuarios[0])
    resultados, errores = en_paralelo([confirmacion(empresa, *usuarios[0], lote, 'confirma-con-alta-1'),
                                       alta(empresa, *usuarios[1], clave='alta-con-importacion', codigo='1.1.02', nombre='Bancos a mano')])
    assert not errores, errores
    estados = sorted(r[0] for r in resultados)
    assert estados in (['hecho', 'hecho'], ['hecho', 'validacion']) or (not cola and estados == ['hecho', 'plan_cambiado'])
    if estados == ['hecho', 'plan_cambiado']:       # ganó el alta por la restricción única: la importación no dejó nada
        assert codigos(empresa) == ['1.1.02']
        with company_context(empresa):
            assert ImportacionCuentas.objects.get(pk=lote).estado == 'vista_previa'
        assert confirmacion(empresa, *usuarios[0], lote, 'confirma-con-alta-2')() == ('hecho', (False, 4, 0, 1))
    elif estados == ['hecho', 'validacion']:        # ganó la importación: el alta encontró el código ya creado
        (_, errores_de_campo, _), = [r for r in resultados if r[0] == 'validacion']
        assert errores_de_campo == {'codigo': [T['codigo_repetido'].format(codigo='1.1.02')]}
        assert (False, 5, 0, 0) in [r[1] for r in resultados]
    else:                                           # el alta entró antes: la importación omitió esa cuenta
        assert (False, 4, 0, 1) in [r[1] for r in resultados]
    assert codigos(empresa) == ['1', '1.1', '1.1.01', '1.1.02', '2']
    assert AuditLog.objects.filter(action='cuentas_importadas', company=empresa).count() == 1


def test_actualizar_nombres_mientras_alguien_edita_una_de_esas_cuentas(cola):
    """La importación renombra «2» mientras otra persona la edita con la versión 1. Ningún cambio se pierde: o la edición
    entró antes (y la importación va sobre ella, versión 3) o llegó tarde y recibe 409 `version` (versión 2)."""
    empresa, usuarios = preparar()
    pasivo = sembrar(empresa, '2', 'movimiento')
    lote = lote_en_vista_previa(empresa, *usuarios[0])
    resultados, errores = en_paralelo([confirmacion(empresa, *usuarios[0], lote, 'confirma-y-renombra', 'actualizar_nombre'),
                                       cambio(empresa, *usuarios[1], pasivo.pk, version=1, nombre='Pasivos a mano')])
    assert not errores, errores
    assert sorted(r[0] for r in resultados) in (['hecho', 'hecho'], ['hecho', 'version'])
    assert ('hecho', (False, 4, 1, 0)) in resultados   # la importación siempre renombra: el nombre del archivo es otro
    edito = ('hecho', (2, 'Pasivos a mano')) in resultados
    with company_context(empresa):
        guardada = Cuenta.objects.get(pk=pasivo.pk)
    assert (guardada.nombre, guardada.version) == ('Pasivo', 3 if edito else 2)
    assert AuditLog.objects.filter(action='cuenta_modificada', company=empresa).count() == (1 if edito else 0)
