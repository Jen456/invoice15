"""Seguridad por filas de PostgreSQL: aísla aunque la consulta no filtre."""
import pytest
from django.db import DatabaseError, connection, transaction

from core.tenancy.context import company_context, platform_scope, set_db_scope
from tests import helpers

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='La seguridad por filas es de PostgreSQL'),
]


def contar_productos():
    with connection.cursor() as cursor:
        cursor.execute('SELECT count(*) FROM pos_product')  # sin filtro de empresa a propósito
        return cursor.fetchone()[0]


def test_sql_directo_solo_ve_la_empresa_fijada(empresa, empresa_b):
    helpers.crear_producto(empresa, 'A-1')
    helpers.crear_producto(empresa_b, 'B-1')
    helpers.crear_producto(empresa_b, 'B-2')
    with company_context(empresa):
        assert contar_productos() == 1
    with company_context(empresa_b):
        assert contar_productos() == 2
    with platform_scope():
        assert contar_productos() == 3
    set_db_scope(None)
    assert contar_productos() == 0


def test_no_se_inserta_una_fila_de_otra_empresa(empresa, empresa_b):
    with company_context(empresa):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO pos_category (name, company_id) VALUES (%s, %s)', ['INTRUSA', empresa_b.id])


def test_las_politicas_estan_activas_y_forzadas():
    from core.pos.migrations import TENANT_MODELS_FOR_RLS
    with connection.cursor() as cursor:
        cursor.execute("SELECT relname FROM pg_class WHERE relrowsecurity AND relforcerowsecurity AND relname LIKE 'pos\\_%%'")
        protegidas = {fila[0] for fila in cursor.fetchall()}
    esperadas = {f'pos_{m.lower()}' for m in TENANT_MODELS_FOR_RLS}
    assert esperadas <= protegidas
