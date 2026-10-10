"""Empresa activa del contexto de ejecución (petición web o tarea en segundo plano).

La empresa nunca se toma de un parámetro del navegador: la fija el middleware a
partir de la sesión (tras comprobar la membresía) o una tarea con
`company_context()`. Las consultas a modelos de empresa la leen al ejecutarse.
En PostgreSQL además se fija `app.company_id` para las políticas de seguridad
por filas (RLS) y `app.platform` para el panel de plataforma.
"""
import contextvars
from contextlib import contextmanager

from django.db import connections

_company = contextvars.ContextVar('fpa_company', default=None)
_platform = contextvars.ContextVar('fpa_platform', default=False)


class TenantScopeError(RuntimeError):
    """Consulta o escritura de datos de empresa sin empresa activa."""


def current_company():
    return _company.get()


def current_company_id():
    company = _company.get()
    return company.pk if company is not None else None


def is_platform_scope():
    return _platform.get()


def require_company():
    company = _company.get()
    if company is None:
        raise TenantScopeError('Operación con datos de empresa sin empresa activa')
    return company


def set_db_scope(company_id=None, platform=False, using='default'):
    """Fija las variables de sesión de PostgreSQL que leen las políticas RLS."""
    connection = connections[using]
    if connection.vendor != 'postgresql':
        return
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.company_id', %s, false), set_config('app.platform', %s, false)",
            ['' if company_id is None else str(company_id), 'on' if platform else 'off'],
        )


def activate(company=None, platform=False):
    """Activa el contexto y devuelve los tokens para restaurarlo."""
    tokens = (_company.set(company), _platform.set(platform))
    set_db_scope(company.pk if company is not None else None, platform)
    return tokens


def deactivate(tokens):
    _company.reset(tokens[0])
    _platform.reset(tokens[1])
    company = _company.get()
    set_db_scope(company.pk if company is not None else None, _platform.get())


@contextmanager
def company_context(company):
    """Ejecuta un bloque (tarea, comando, prueba) con una empresa activa."""
    tokens = activate(company, platform=False)
    try:
        yield company
    finally:
        deactivate(tokens)


@contextmanager
def platform_scope():
    """Bloque del panel de plataforma: acceso explícito a todas las empresas."""
    tokens = activate(None, platform=True)
    try:
        yield
    finally:
        deactivate(tokens)
