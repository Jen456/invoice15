"""Apertura en preparación en PostgreSQL con transacciones reales (bloque 2, Parte B, primera mitad): la seguridad por filas
de lo que escriben los servicios (también las líneas que mapear inserta por lotes, que no pasan por `TenantModel.save`) y
la concurrencia de crear y mapear:

- dos creaciones a la vez, sin inicio contable todavía, con claves distintas: una crea el inicio y el borrador y la otra
  recibe `apertura_existente` (el candado del libro las pone en fila; la carrera por crear la fila del candado la resuelve
  su UNIQUE);
- dos creaciones a la vez con la misma clave: una apertura y la otra `repetido`;
- dos mapeos a la vez con la misma versión: uno escribe y el otro recibe `version`, sin líneas de más.

Va al final (test_zz_*) y crea todos sus datos: las pruebas transaccionales vacían la base."""
import json

import pytest
from django.contrib.auth.models import Group, Permission
from django.db import DatabaseError, connection, transaction

from core.contabilidad import api, apertura as servicio
from core.contabilidad.models import Apertura, EventoApertura, InicioContable, LineaApertura
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER
from tests import ayudas_contables as ayudas
from tests import helpers

pytestmark = [
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='Bloqueos y seguridad por filas reales solo en PostgreSQL'),
    pytest.mark.django_db(transaction=True),
]
CODIGOS = ('view_apertura', 'add_apertura', 'view_cuenta')
DATOS = {'modalidad': 'saldos', 'fecha_corte': '2025-12-31', 'fuente': 'balance_comprobacion', 'fuente_detalle': 'Balance'}


def preparar(nombre='APERTURA PG'):
    helpers.restaurar_planes()   # una prueba transaccional anterior vació la base (planes de las migraciones incluidos)
    empresa = helpers.crear_empresa(nombre)
    grupo, _ = Group.objects.get_or_create(name=ROLE_OWNER)
    grupo.permissions.add(*Permission.objects.filter(codename__in=CODIGOS))
    usuarios = [helpers.crear_usuario(f'apertura.pg.{empresa.pk}.{n}', empresa, grupo) for n in range(2)]
    return empresa, usuarios, ayudas.plan_minimo(empresa)


def resultado(funcion):
    """El código de lo que respondió el servicio: 'ok', 'repetido' o el `codigo` de su negativa."""
    try:
        valor = funcion()
    except api.ErrorApi as e:
        return e.codigo or json.loads(e.respuesta().content)['codigo']
    return 'repetido' if isinstance(valor, tuple) and valor[-1] is True else 'ok'


def contar(tabla):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT count(*) FROM {connection.ops.quote_name(tabla)}')   # sin filtro de empresa, a propósito
        return cursor.fetchone()[0]


def test_lo_que_escribe_la_preparacion_queda_en_su_empresa():
    empresa, (usuario, _), cuentas = preparar()
    otra, _, cuentas_b = preparar('OTRA PG')
    with company_context(empresa):
        _, apertura, _ = servicio.crear(ayudas.peticion(usuario, empresa), {'clave': ayudas.clave('rls'), **DATOS})
        servicio.mapear(ayudas.peticion(usuario, empresa), apertura.pk, {'version': 1, 'lineas': [
            {'cuenta_id': cuentas['caja'].pk, 'debe': '10.00'}, {'cuenta_id': cuentas['capital'].pk, 'haber': '10.00'}]})
    tablas = ('contabilidad_iniciocontable', 'contabilidad_apertura', 'contabilidad_lineaapertura', 'contabilidad_eventoapertura')
    with company_context(empresa):
        assert [contar(t) for t in tablas] == [1, 1, 2, 3]
    with company_context(otra):
        assert [contar(t) for t in tablas] == [0, 0, 0, 0]
        assert Apertura.objects.filter(pk=apertura.pk).first() is None
    # una línea de otra empresa no entra, ni por SQL ni por el lote de mapear (bulk_create no pasa por TenantModel.save)
    with company_context(otra):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO contabilidad_lineaapertura (company_id, apertura_id, orden, cuenta_id, codigo_origen, '
                               'rubro_origen, detalle, es_resultado_ejercicio, incompleto_aceptado, retirada, filas_origen, nota) '
                               "VALUES (%s, %s, 9, %s, '', '', '', false, false, false, '[]', '')",
                               [empresa.pk, apertura.pk, cuentas['ventas'].pk])
        with pytest.raises(DatabaseError), transaction.atomic():
            LineaApertura.objects.bulk_create([LineaApertura(company_id=empresa.pk, apertura_id=apertura.pk, orden=10,
                                                             cuenta_id=cuentas['ventas'].pk)])
    with company_context(empresa):
        assert contar('contabilidad_lineaapertura') == 2


def test_dos_creaciones_a_la_vez_con_claves_distintas():
    empresa, usuarios, _ = preparar()

    def crear(usuario, n):
        def tarea():
            with company_context(empresa):
                return resultado(lambda: servicio.crear(ayudas.peticion(usuario, empresa), {'clave': f'crear-pg-{n:04d}', **DATOS}))
        return tarea
    resultados, errores = ayudas.en_paralelo([crear(usuario, n) for n, usuario in enumerate(usuarios)])
    assert errores == [] and sorted(resultados) == ['apertura_existente', 'ok']
    with company_context(empresa):
        assert InicioContable.objects.count() == 1 and Apertura.objects.count() == 1
        assert list(EventoApertura.objects.order_by('id').values_list('accion', flat=True)) == ['inicio_configurado', 'creada']


def test_dos_creaciones_a_la_vez_con_la_misma_clave():
    empresa, usuarios, _ = preparar()

    def crear(usuario):
        def tarea():
            with company_context(empresa):
                return resultado(lambda: servicio.crear(ayudas.peticion(usuario, empresa), {'clave': 'crear-pg-misma', **DATOS}))
        return tarea
    resultados, errores = ayudas.en_paralelo([crear(usuario) for usuario in usuarios])
    assert errores == [] and sorted(resultados) == ['ok', 'repetido']
    with company_context(empresa):
        assert Apertura.objects.count() == 1 and InicioContable.objects.count() == 1


def test_dos_mapeos_a_la_vez_con_la_misma_version():
    empresa, usuarios, cuentas = preparar()
    with company_context(empresa):
        _, apertura, _ = servicio.crear(ayudas.peticion(usuarios[0], empresa), {'clave': ayudas.clave('mapeo'), **DATOS})

    def mapear(usuario, importe):
        def tarea():
            with company_context(empresa):
                return resultado(lambda: servicio.mapear(ayudas.peticion(usuario, empresa), apertura.pk, {'version': 1, 'lineas': [
                    {'cuenta_id': cuentas['caja'].pk, 'debe': importe}, {'cuenta_id': cuentas['capital'].pk, 'haber': importe}]}))
        return tarea
    resultados, errores = ayudas.en_paralelo([mapear(usuarios[0], '10.00'), mapear(usuarios[1], '20.00')])
    assert errores == [] and sorted(resultados) == ['ok', 'version']
    with company_context(empresa):
        assert Apertura.objects.get(pk=apertura.pk).version == 2
        assert LineaApertura.objects.filter(apertura_id=apertura.pk).count() == 2
        assert EventoApertura.objects.filter(apertura_id=apertura.pk, accion='mapeada').count() == 1
