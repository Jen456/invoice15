"""Disparadores del libro en PostgreSQL (contabilidad 0014 `libro_inmutable`), a nivel SQL: lo que rechazan aunque se
escriba sin los modelos. Transacciones reales (transaction=True), porque `fpa_asiento_sellado` se comprueba al confirmar;
va al final (test_zz_*) y crea todos sus datos, porque las pruebas transaccionales vacían la base.

- UPDATE y DELETE directos de una línea o de un asiento, y de la historia de la apertura;
- el sello: una vez, solo si las líneas cuadran con los totales; el asiento nace sin sellar;
- una línea en un asiento sellado, en un asiento de otra empresa o con una cuenta de otra empresa;
- el asiento sin sellar al confirmar (también con otra empresa activa al confirmar) y el sellado en la misma transacción;
- el par `reversado_por`/`reversado_en`: los dos juntos, una vez, en uno sellado y hacia su reverso;
- borrar al usuario autor no toca el libro;
- las migraciones de los disparadores y de la seguridad por filas se deshacen y se rehacen.

Y a nivel de servicio (core/contabilidad/diario.py), con transacciones reales: `contabilizar` sella en la misma
transacción y el disparador diferido lo deja confirmar; `reversar` fija el par del reverso que el disparador admite; un
fallo a medio escribir no deja nada ni consume número; dos contabilizaciones simultáneas numeran sin hueco ni repetición."""
import importlib
from datetime import date

import pytest
from django.apps import apps
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from core.contabilidad import diario
from core.contabilidad.models import Asiento, EjercicioContable, EventoApertura, LineaAsiento, SaldoCuentaMes
from core.tenancy.context import company_context, platform_scope
from core.user.models import User
from tests import ayudas_contables as ac
from tests import helpers

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Los disparadores son de PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]
DISPARADORES = {'fpa_linea_solo_insercion', 'fpa_linea_en_asiento_abierto', 'fpa_asiento_solo_sello_o_reverso',
                'fpa_asiento_nace_abierto', 'fpa_asiento_sellado', 'fpa_evento_solo_insercion'}


@pytest.fixture
def libro():
    a, b = helpers.crear_empresa('LIBRO A', plan=None), helpers.crear_empresa('LIBRO B', plan=None)
    cuentas_a, cuentas_b = ac.plan_minimo(a), ac.plan_minimo(b)
    return a, cuentas_a, b, cuentas_b


def lineas(cuentas, importe=10):
    return [(cuentas['caja'], importe, 0), (cuentas['capital'], 0, importe)]


def sql(consulta, params=()):
    """Una sentencia en su propio punto de guardado: si falla, la transacción sigue usable y el error que se ve es el del
    disparador (al salir de un company_context se fija la empresa con otra consulta, que en una transacción abortada
    taparía el error con «current transaction is aborted»)."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(consulta, params)
        return cursor.rowcount


def por_lotes(gestor, filas):
    with transaction.atomic():   # como sql(): el error que se ve es el del disparador
        return gestor.bulk_create(filas)


def rechaza(disparador, accion, *args):
    """La acción falla en la base con el mensaje del disparador, y nada queda (punto de guardado propio)."""
    with pytest.raises(DatabaseError) as error, transaction.atomic():
        accion(*args)
    assert disparador in str(error.value), str(error.value)
    return str(error.value)


def linea_suelta(empresa, asiento, cuenta, orden=9):
    """Una línea insertada por lotes: sin `save()` ni `check_tenant_references`, como lo hará diario.py."""
    return LineaAsiento(company=empresa, asiento_id=asiento.pk, orden=orden, cuenta=cuenta, debe=1, haber=0, fecha=asiento.fecha,
                        anio=asiento.anio, mes=asiento.mes)


def test_lineas_y_asientos_no_se_cambian_ni_se_borran_por_sql(libro):
    a, cuentas, *_ = libro
    asiento = ac.asiento_directo(a, lineas(cuentas))
    for contexto in (company_context(a), platform_scope()):   # no es la seguridad por filas la que lo impide
        with contexto:
            rechaza('fpa_linea_solo_insercion', sql, 'UPDATE contabilidad_lineaasiento SET concepto = %s WHERE asiento_id = %s',
                    ['cambiado', asiento.pk])
            rechaza('fpa_linea_solo_insercion', sql, 'DELETE FROM contabilidad_lineaasiento WHERE asiento_id = %s', [asiento.pk])
            for cambio in ("concepto = 'cambiado'", "creado_por_nombre = 'otro'", 'total_debe = total_debe',
                           'sellado = false', 'sellado = true', 'numero = numero + 1'):
                rechaza('fpa_asiento_solo_sello_o_reverso', sql, f'UPDATE contabilidad_asiento SET {cambio} WHERE id = %s',
                        [asiento.pk])
            rechaza('fpa_asiento_solo_sello_o_reverso', sql, 'DELETE FROM contabilidad_asiento WHERE id = %s', [asiento.pk])
    with company_context(a):
        guardado = Asiento.objects.get(pk=asiento.pk)
        assert guardado.sellado and guardado.concepto == 'Asiento de prueba' and guardado.lineas.count() == 2


def test_el_sello_exige_que_las_lineas_cuadren(libro):
    a, cuentas, *_ = libro

    def con_una_linea_de_mas():
        abierto = ac.asiento_directo(a, lineas(cuentas), sellar=False)
        with company_context(a):
            por_lotes(LineaAsiento.objects, [linea_suelta(a, abierto, cuentas['caja'], orden=3)])
            sql('UPDATE contabilidad_asiento SET sellado = true WHERE id = %s', [abierto.pk])
    rechaza('fpa_asiento_solo_sello_o_reverso', con_una_linea_de_mas)

    def sin_sus_lineas():   # un asiento con totales y sin ninguna línea no se sella
        ejercicio = ac.ejercicio(a, 2026)
        with company_context(a):
            vacio = Asiento.objects.create(ejercicio=ejercicio, anio=2026, mes=1, numero=777, fecha=date(2026, 1, 15), tipo='manual',
                                           concepto='Sin líneas', total_debe=10, total_haber=10, lineas_n=2, huella='0' * 64,
                                           motivo='Prueba', creado_por_nombre='prueba')
            sql('UPDATE contabilidad_asiento SET sellado = true WHERE id = %s', [vacio.pk])
    assert 'no cuadran' in rechaza('fpa_asiento_solo_sello_o_reverso', sin_sus_lineas)
    with transaction.atomic():   # con sus líneas cuadradas, por SQL también se sella
        abierto = ac.asiento_directo(a, lineas(cuentas, 3), sellar=False)
        with company_context(a):
            assert sql('UPDATE contabilidad_asiento SET sellado = true WHERE id = %s', [abierto.pk]) == 1
    with company_context(a):
        assert Asiento.objects.get(pk=abierto.pk).sellado


def test_el_asiento_nace_abierto(libro):
    a, cuentas, *_ = libro
    asiento = ac.asiento_directo(a, lineas(cuentas))
    with company_context(a):
        base = {c.attname: getattr(asiento, c.attname) for c in Asiento._meta.concrete_fields if not c.primary_key}
        base.update(numero=500, clave=None, origen_id=None)
        for cambio in ({'sellado': True}, {'reversado_por_id': asiento.pk, 'reversado_en': timezone.now()}):
            rechaza('fpa_asiento_nace_abierto', por_lotes, Asiento.objects, [Asiento(**{**base, 'sellado': False, **cambio})])
        assert Asiento.objects.count() == 1


def test_linea_en_asiento_sellado_o_de_otra_empresa(libro):
    a, cuentas_a, b, cuentas_b = libro
    sellado = ac.asiento_directo(a, lineas(cuentas_a))
    with company_context(a):
        assert 'ya está sellado' in rechaza('fpa_linea_en_asiento_abierto', por_lotes, LineaAsiento.objects,
                                            [linea_suelta(a, sellado, cuentas_a['caja'])])

    def en_asiento_de_otra_empresa(contexto):
        abierto_b = ac.asiento_directo(b, lineas(cuentas_b), sellar=False)
        with contexto:
            por_lotes(LineaAsiento.all_companies, [linea_suelta(a, abierto_b, cuentas_a['caja'])])

    def con_cuenta_de_otra_empresa(contexto):
        abierto_a = ac.asiento_directo(a, lineas(cuentas_a), sellar=False)
        with contexto:
            por_lotes(LineaAsiento.all_companies, [linea_suelta(a, abierto_a, cuentas_b['caja'])])
    # Con la empresa A activa la seguridad por filas esconde lo de B; con la plataforma lo ve todo: el disparador compara
    # la empresa en los dos casos.
    for contexto in (lambda: company_context(a), platform_scope):
        assert 'otra empresa' in rechaza('fpa_linea_en_asiento_abierto', en_asiento_de_otra_empresa, contexto())
        assert 'la cuenta' in rechaza('fpa_linea_en_asiento_abierto', con_cuenta_de_otra_empresa, contexto())
    with platform_scope():
        assert LineaAsiento.all_companies.filter(company=a).count() == 2 and LineaAsiento.all_companies.filter(company=b).count() == 0


def test_asiento_sin_sellar_al_confirmar(libro):
    a, cuentas, b, _ = libro
    for activa in (a, b):   # al confirmar puede estar activa otra empresa: la lectura del disparador no depende de ella
        with pytest.raises(DatabaseError) as error:
            with company_context(activa), transaction.atomic():
                ac.asiento_directo(a, lineas(cuentas), sellar=False)
        assert 'fpa_asiento_sellado' in str(error.value)
        with company_context(activa), transaction.atomic():
            ac.asiento_directo(a, lineas(cuentas))   # sellado en la misma transacción: pasa
    with company_context(a):
        assert list(Asiento.objects.values_list('sellado', flat=True)) == [True, True]
        assert LineaAsiento.objects.count() == 4


def test_el_par_del_reverso(libro):
    a, cuentas, *_ = libro
    original, otro = ac.asiento_directo(a, lineas(cuentas)), ac.asiento_directo(a, lineas(cuentas, 20))
    reverso = ac.asiento_directo(a, [(cuentas['capital'], 10, 0), (cuentas['caja'], 0, 10)], tipo='reverso', reversa_de=original,
                                 motivo='Reverso de prueba')
    actualizar = 'UPDATE contabilidad_asiento SET {} WHERE id = %s'
    with company_context(a):
        rechaza('fpa_asiento_solo_sello_o_reverso', sql, actualizar.format('reversado_por_id = %s'), [reverso.pk, original.pk])
        rechaza('fpa_asiento_solo_sello_o_reverso', sql, actualizar.format('reversado_en = now()'), [original.pk])
        assert 'no es el reverso' in rechaza('fpa_asiento_solo_sello_o_reverso', sql,
                                             actualizar.format('reversado_por_id = %s, reversado_en = now()'), [reverso.pk, otro.pk])
        assert sql(actualizar.format('reversado_por_id = %s, reversado_en = now()'), [reverso.pk, original.pk]) == 1
        rechaza('fpa_asiento_solo_sello_o_reverso', sql, actualizar.format("reversado_en = now() + interval '1 day'"), [original.pk])
        rechaza('fpa_asiento_solo_sello_o_reverso', sql, actualizar.format('reversado_por_id = NULL, reversado_en = NULL'),
                [original.pk])

    def en_uno_abierto():
        abierto = ac.asiento_directo(a, lineas(cuentas, 5), sellar=False)
        r = ac.asiento_directo(a, [(cuentas['capital'], 5, 0), (cuentas['caja'], 0, 5)], tipo='reverso', reversa_de=abierto,
                               motivo='Reverso de prueba')
        with company_context(a):
            sql(actualizar.format('reversado_por_id = %s, reversado_en = now()'), [r.pk, abierto.pk])
    rechaza('fpa_asiento_solo_sello_o_reverso', en_uno_abierto)
    with company_context(a):
        guardado = Asiento.objects.get(pk=original.pk)
        assert guardado.reversado_por_id == reverso.pk and guardado.reversado_en is not None


def test_la_historia_de_la_apertura_solo_se_inserta(libro):
    a, *_ = libro
    apertura = ac.apertura_directa(a)
    with company_context(a):
        evento = EventoApertura.objects.create(apertura=apertura, accion='creada', a_estado='borrador', usuario_nombre='x')
        for consulta in ("UPDATE contabilidad_eventoapertura SET accion = 'otra' WHERE id = %s",
                         'DELETE FROM contabilidad_eventoapertura WHERE id = %s'):
            rechaza('fpa_evento_solo_insercion', sql, consulta, [evento.pk])
        assert EventoApertura.objects.get(pk=evento.pk).accion == 'creada'


def test_borrar_al_usuario_autor_no_toca_el_libro(libro):
    """Como lo hace UserDeleteView cuando el usuario se queda sin membresías (sin transacción por petición), con otra
    empresa activa: no falla, no llega ningún UPDATE al libro (el disparador lo rechazaría) y el nombre se conserva."""
    a, cuentas, b, _ = libro
    usuario = User.objects.create(username='autor.del.libro', names='Autor', email='autor.libro@example.com')
    asiento = ac.asiento_directo(a, lineas(cuentas), autor=ac.autor(usuario))
    apertura = ac.apertura_directa(a)
    with company_context(a):
        evento = EventoApertura.objects.create(apertura=apertura, accion='creada', usuario_id=usuario.pk,
                                               usuario_nombre=usuario.username)
        antes = Asiento.objects.filter(pk=asiento.pk).values().get()
    id_usuario = usuario.pk
    with company_context(b):
        usuario.delete()
    with company_context(a):
        assert Asiento.objects.filter(pk=asiento.pk).values().get() == antes
        assert (antes['creado_por_id'], antes['creado_por_nombre']) == (id_usuario, 'autor.del.libro')
        assert EventoApertura.objects.filter(pk=evento.pk, usuario_id=id_usuario, usuario_nombre='autor.del.libro').exists()
    assert not User.objects.filter(pk=id_usuario).exists()


def nombres(consulta):
    with connection.cursor() as cursor:
        cursor.execute(consulta)
        return {fila[0] for fila in cursor.fetchall()}


def disparadores():
    return nombres("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'fpa\\_%'")


def funciones():
    return nombres("SELECT proname FROM pg_proc WHERE proname LIKE 'fpa\\_%'")


def test_la_migracion_de_los_disparadores_se_deshace_y_se_rehace(libro):
    a, cuentas, *_ = libro
    asiento = ac.asiento_directo(a, lineas(cuentas))
    migracion = importlib.import_module('core.contabilidad.migrations.0014_libro_inmutable')
    assert disparadores() == DISPARADORES and funciones() == DISPARADORES
    with connection.cursor() as cursor:
        cursor.execute("SELECT tgdeferrable, tginitdeferred FROM pg_trigger WHERE tgname = 'fpa_asiento_sellado'")
        assert cursor.fetchone() == (True, True)
    with transaction.atomic():
        with connection.schema_editor() as editor:
            migracion.backwards(apps, editor)
        assert disparadores() == set() and funciones() == set()
        with company_context(a):   # sin ellos, el UPDATE directo pasa: la vuelta los quitó de verdad
            assert sql("UPDATE contabilidad_lineaasiento SET concepto = 'sin disparadores' WHERE asiento_id = %s", [asiento.pk]) == 2
        with connection.schema_editor() as editor:
            migracion.forwards(apps, editor)
        assert disparadores() == DISPARADORES and funciones() == DISPARADORES
        with company_context(a):
            rechaza('fpa_linea_solo_insercion', sql, "UPDATE contabilidad_lineaasiento SET concepto = 'x' WHERE asiento_id = %s",
                    [asiento.pk])
        transaction.set_rollback(True)
    assert disparadores() == DISPARADORES
    with company_context(a):
        assert set(LineaAsiento.objects.filter(asiento=asiento).values_list('concepto', flat=True)) == {''}


def test_la_migracion_de_la_seguridad_por_filas_se_deshace_y_se_rehace(libro):
    migracion = importlib.import_module('core.contabilidad.migrations.0013_rls_libro_apertura')
    tablas = [m._meta.db_table for m in ac.MODELOS_DEL_BLOQUE]
    assert sorted(migracion.TABLAS) == sorted(tablas) and len(tablas) == 19

    def estado():
        with connection.cursor() as cursor:
            cursor.execute('SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, '
                           "(SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid AND p.polname = 'fpa_empresa') "
                           'FROM pg_class c WHERE c.relname = ANY(%s)', [tablas])
            return {fila[0]: fila[1:] for fila in cursor.fetchall()}
    assert set(estado().values()) == {(True, True, 1)}
    with transaction.atomic():
        with connection.schema_editor() as editor:
            migracion.backwards(apps, editor)
        assert set(estado().values()) == {(False, False, 0)}
        with connection.schema_editor() as editor:
            migracion.forwards(apps, editor)
        assert set(estado().values()) == {(True, True, 1)}
        transaction.set_rollback(True)
    assert set(estado().values()) == {(True, True, 1)}


# ---------------------------------------------------------------- a nivel de servicio

def test_contabilizar_y_reversar_por_el_servicio_pasan_los_disparadores(libro):
    a, cuentas, b, _ = libro
    ac.inicio_directo(a)
    for activa in (a, b):   # al confirmar puede estar activa otra empresa
        with company_context(activa):
            asiento = ac.contabilizar(a, lineas(cuentas, 25))   # su propia transacción: confirma al salir
    reverso, repetido = ac.reversar(a, asiento, clave='reverso-servicio-1')
    with company_context(a):
        assert set(Asiento.objects.values_list('sellado', flat=True)) == {True} and Asiento.objects.count() == 3
        assert Asiento.objects.get(pk=asiento.pk).reversado_por_id == reverso.pk and not repetido
        assert LineaAsiento.objects.count() == 6
        assert all(c['ok'] for c in diario.verificar(2026)['comprobaciones'])
    assert ac.reversar(a, asiento, clave='reverso-servicio-1') == (reverso, True)


def test_un_fallo_a_medio_escribir_no_deja_nada_ni_consume_numero(libro, monkeypatch):
    a, cuentas, *_ = libro
    ac.inicio_directo(a)
    primero = ac.contabilizar(a, lineas(cuentas, 1))

    def falla(*args, **kwargs):
        raise RuntimeError('fallo a propósito después de insertar el asiento, sus líneas y el sello')
    monkeypatch.setattr(diario, '_acumular', falla)
    with pytest.raises(RuntimeError):
        ac.contabilizar(a, lineas(cuentas, 2))
    monkeypatch.undo()
    with company_context(a):
        assert Asiento.objects.count() == 1 and LineaAsiento.objects.count() == 2
        assert EjercicioContable.objects.get(anio=2026).ultimo_numero == 1
        assert SaldoCuentaMes.objects.get(cuenta=cuentas['caja']).debe == 1
    assert ac.contabilizar(a, lineas(cuentas, 3)).numero == primero.numero + 1


def test_dos_contabilizaciones_simultaneas_numeran_sin_hueco_ni_repeticion(libro):
    a, cuentas, *_ = libro
    ac.inicio_directo(a)
    ac.contabilizar(a, lineas(cuentas, 1))
    resultados, errores = ac.en_paralelo([lambda n=n: ac.contabilizar(a, lineas(cuentas, 10 + n)).numero for n in range(2)])
    assert not errores, errores
    assert sorted(resultados) == [2, 3]
    with company_context(a):
        assert sorted(Asiento.objects.values_list('numero', flat=True)) == [1, 2, 3]
        assert EjercicioContable.objects.get(anio=2026).ultimo_numero == 3
        assert SaldoCuentaMes.objects.get(cuenta=cuentas['caja']).debe == 1 + 10 + 11   # ningún acumulado se pisó
