"""Seguridad por filas genérica (solo PostgreSQL): la tabla de cada modelo que hereda de TenantModel tiene la seguridad
por filas activada y forzada (relrowsecurity y relforcerowsecurity) y al menos una política. Un modelo de empresa nuevo
cuya migración olvide la RLS hace fallar esta prueba. Sin transaction=True: solo lee el catálogo de PostgreSQL."""
import pytest
from django.apps import apps
from django.db import connection

from core.tenancy.models_base import TenantModel

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != 'postgresql', reason='La seguridad por filas es de PostgreSQL'),
]


def tablas_de_empresa():
    """{tabla: etiqueta del modelo} de los modelos concretos y gestionados que heredan de TenantModel."""
    return {m._meta.db_table: m._meta.label for m in apps.get_models()
            if issubclass(m, TenantModel) and m._meta.managed and not m._meta.proxy and not m._meta.abstract}


def test_toda_tabla_de_empresa_tiene_rls_forzada_y_politica():
    tablas = tablas_de_empresa()
    assert len(tablas) > 30, sorted(tablas.values())       # el recorrido encuentra los modelos de todas las apps
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, '
            '(SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) '
            'FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace '
            "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p') AND c.relname = ANY(%s)", [list(tablas)])
        estado = {nombre: (rls, forzada, politicas) for nombre, rls, forzada, politicas in cursor.fetchall()}
    assert not set(tablas) - set(estado), f'tablas que no existen: {sorted(set(tablas) - set(estado))}'
    fallan = sorted(f'{tablas[t]} ({t}): rls={rls}, forzada={forzada}, políticas={politicas}'
                    for t, (rls, forzada, politicas) in estado.items() if not (rls and forzada and politicas >= 1))
    assert not fallan, fallan
