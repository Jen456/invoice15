"""Reglas para gestionar usuarios desde una empresa.

Los usuarios son globales (una persona puede pertenecer a varias empresas).
Desde una empresa solo se gestiona su membresía; la identidad (nombre, correo,
usuario, contraseña) solo si el usuario pertenece únicamente a esa empresa y no
es de la plataforma: si no, el administrador de una empresa podría tomar el
control de la cuenta en otra empresa.
"""
from django.contrib.auth.models import Group

from core.security.session import get_group
from core.tenancy.models import ROLE_CLIENT, ROLE_OWNER, Membership


def company_members(company):
    return Membership.objects.filter(company=company).exclude(group__name=ROLE_CLIENT).select_related('user', 'group')


def can_manage_identity(user, company):
    if user.pk is None:
        return True
    return not user.is_superuser and not Membership.objects.filter(user=user).exclude(company=company).exists()


def assignable_roles(request):
    """Roles que el usuario actual puede asignar: nunca Cliente (se crean en
    Clientes) y Propietario solo si él mismo es propietario o de la plataforma."""
    roles = Group.objects.exclude(name=ROLE_CLIENT).order_by('name')
    group = get_group(request)
    if not request.user.is_superuser and (group is None or group.name != ROLE_OWNER):
        roles = roles.exclude(name=ROLE_OWNER)
    return roles
