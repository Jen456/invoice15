"""Seguridad por filas de PostgreSQL en las 19 tablas del bloque 2 (contabilidad 0013), tabla por tabla y por SQL: activa y
forzada con la política `fpa_empresa`; una consulta sin filtro solo ve la empresa fijada; una fila de otra empresa no se
ve, no se cambia, no se inserta y no se le pasa a otra empresa una fila propia. (La prueba genérica de todo TenantModel es
tests/test_rls_modelos_de_empresa.py.)"""
import pytest
from django.db import DatabaseError, connection, transaction

from core.tenancy.context import company_context, platform_scope
from tests import ayudas_contables as ac

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='La seguridad por filas es de PostgreSQL'),
]
MODELOS = ac.MODELOS_DEL_BLOQUE
# Tablas cuyo disparador rechaza el cambio antes que la política (lo que se comprueba es que no pasa).
CON_DISPARADOR = {'contabilidad_asiento', 'contabilidad_lineaasiento', 'contabilidad_eventoapertura'}


@pytest.fixture
def dos(empresa, empresa_b):
    return ac.filas_de_cada_tabla(empresa), ac.filas_de_cada_tabla(empresa_b)


def una(filas, modelo):
    return next(v for v in filas.values() if type(v) is modelo)


def sql(consulta, params=()):
    with connection.cursor() as cursor:
        cursor.execute(consulta, params)
        return cursor.fetchall() if cursor.description else cursor.rowcount


@pytest.mark.parametrize('modelo', MODELOS, ids=[m._meta.db_table for m in MODELOS])
def test_politica_activa_y_forzada(modelo):
    tabla = modelo._meta.db_table
    filas = sql('SELECT c.relrowsecurity, c.relforcerowsecurity, p.polname, p.polcmd FROM pg_class c '
                'JOIN pg_policy p ON p.polrelid = c.oid WHERE c.relname = %s', [tabla])
    assert filas == [(True, True, 'fpa_empresa', '*')], filas


@pytest.mark.parametrize('modelo', MODELOS, ids=[m._meta.db_table for m in MODELOS])
def test_cada_empresa_solo_ve_y_escribe_lo_suyo(dos, empresa, empresa_b, modelo):
    tabla = modelo._meta.db_table
    propia, ajena = una(dos[0], modelo), una(dos[1], modelo)
    with platform_scope():
        por_empresa = dict(sql(f'SELECT company_id, count(*) FROM {tabla} GROUP BY company_id'))
    assert por_empresa[empresa.pk] >= 1 and por_empresa[empresa_b.pk] >= 1
    columnas = [c.column for c in modelo._meta.concrete_fields if not c.primary_key]
    lista = ', '.join(connection.ops.quote_name(c) for c in columnas)
    copia = ', '.join('%s' if c == 'company_id' else connection.ops.quote_name(c) for c in columnas)
    with company_context(empresa):
        assert sql(f'SELECT count(*) FROM {tabla}') == [(por_empresa[empresa.pk],)]   # sin filtro de empresa
        assert sql(f'SELECT count(*) FROM {tabla} WHERE id = %s', [ajena.pk]) == [(0,)]
        assert sql(f'UPDATE {tabla} SET company_id = company_id WHERE id = %s', [ajena.pk]) == 0
        assert sql(f'DELETE FROM {tabla} WHERE id = %s', [ajena.pk]) == 0
        for consulta, params in ((f'UPDATE {tabla} SET company_id = %s WHERE id = %s', [empresa_b.pk, propia.pk]),
                                 (f'INSERT INTO {tabla} ({lista}) SELECT {copia} FROM {tabla} WHERE id = %s',
                                  [empresa_b.pk, propia.pk])):
            with pytest.raises(DatabaseError) as error, transaction.atomic():
                sql(consulta, params)
            assert tabla in CON_DISPARADOR or 'row-level security' in str(error.value), str(error.value)
    with company_context(empresa_b):
        assert sql(f'SELECT count(*) FROM {tabla}') == [(por_empresa[empresa_b.pk],)]
        assert sql(f'SELECT count(*) FROM {tabla} WHERE id = %s', [ajena.pk]) == [(1,)]
