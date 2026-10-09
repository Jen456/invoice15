"""Inicio de sesión con usuario, correo o RUC/cédula.

- Usuario: coincidencia exacta.
- Correo: solo si pertenece a un único usuario (si no, hay que usar el usuario).
- RUC o cédula: solo si la empresa con ese número tiene un único propietario.
Las cuentas sin confirmar se autentican aquí para que el formulario pueda decir
«confirma tu correo»; el formulario es quien impide el ingreso. get_user() sigue
rechazando usuarios inactivos, así que una sesión no sobrevive a una desactivación.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from core.login.identificacion import solo_digitos


def buscar_usuario(identificador):
    User = get_user_model()
    identificador = (identificador or '').strip()
    if not identificador:
        return None
    usuario = User.objects.filter(username=identificador).first()
    if usuario is not None:
        return usuario
    if '@' in identificador:
        coincidencias = list(User.objects.filter(email__iexact=identificador)[:2])
        return coincidencias[0] if len(coincidencias) == 1 else None
    numero = solo_digitos(identificador)
    if numero == identificador and len(numero) in (10, 13):
        from core.pos.models import Company
        from core.tenancy.models import ROLE_OWNER, Membership
        empresas = Company.objects.filter(ruc=numero, is_active=True)
        duenos = list(Membership.objects.filter(company__in=empresas, group__name=ROLE_OWNER, is_active=True)
                      .values_list('user_id', flat=True).distinct()[:2])
        if len(duenos) == 1:
            return User.objects.filter(pk=duenos[0]).first()
    return None


class IdentifierBackend(ModelBackend):

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        usuario = buscar_usuario(username)
        if usuario is None:
            get_user_model()().set_password(password)  # mismo tiempo de respuesta que con un usuario existente
            return None
        if usuario.check_password(password):
            return usuario
        return None
