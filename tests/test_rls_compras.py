"""Seguridad por filas de PostgreSQL en la tabla nueva de Compras (importacion_equivalenciaproducto): activa y forzada, una
consulta sin filtro solo ve la empresa fijada y no se inserta una fila de otra empresa. (La prueba genérica de todas las
tablas TenantModel es del integrador.)"""
import pytest
from django.db import DatabaseError, connection, transaction

from core.importacion.models import EquivalenciaProducto
from core.tenancy.context import company_context
from tests import ayuda_compras as ayuda

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='La seguridad por filas es de PostgreSQL'),
]
TABLA = 'importacion_equivalenciaproducto'


def equivalencia(empresa, codigo):
    proveedor, producto = ayuda.crear_proveedor(empresa, tipo='04'), ayuda.crear_producto(empresa)
    with company_context(empresa):
        return EquivalenciaProducto.objects.create(proveedor=proveedor, codigo_proveedor=codigo, producto=producto)


def contar():
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT count(*) FROM {TABLA}')      # sin filtro de empresa a propósito
        return cursor.fetchone()[0]


def test_politica_activa_y_forzada():
    with connection.cursor() as cursor:
        cursor.execute('SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s', [TABLA])
        assert cursor.fetchone() == (True, True)


def test_consulta_sin_filtro_solo_ve_la_empresa_fijada(empresa, empresa_b):
    equivalencia(empresa, 'A-1')
    equivalencia(empresa, 'A-2')
    equivalencia(empresa_b, 'B-1')
    with company_context(empresa):
        assert contar() == 2
    with company_context(empresa_b):
        assert contar() == 1


def test_no_se_inserta_una_fila_de_otra_empresa(empresa, empresa_b):
    ajena = equivalencia(empresa_b, 'B-1')
    with company_context(empresa):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'INSERT INTO {TABLA} (company_id, proveedor_id, codigo_proveedor, producto_id, creado, actualizado) '
                               'VALUES (%s, %s, %s, %s, now(), now())',
                               [empresa_b.id, ajena.proveedor_id, 'INTRUSA', ajena.producto_id])
