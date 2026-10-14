"""Compradores por empresa.

El usuario de un comprador usaba su identificación como nombre de usuario, único en toda la plataforma:
si otra empresa ya lo había registrado (o el «CONSUMIDOR FINAL» 9999999999999 de las empresas de
demostración), la empresa no podía crearlo. Cada empresa tiene ahora su propio consumidor final y, si la
identificación ya está tomada por otra empresa, se crea un usuario aparte (no se comparten datos).
"""
import uuid

from django.contrib.auth.models import Group

from config import settings

CONSUMIDOR_FINAL = '9999999999999'


def consumidor_final(company):
    """Cliente «CONSUMIDOR FINAL» de la empresa activa; se crea la primera vez que hace falta."""
    from core.pos.models import Client
    from core.user.models import User
    cliente = Client.objects.filter(dni=CONSUMIDOR_FINAL).select_related('user').first()
    if cliente is not None:
        return cliente
    usuario = User(username=f'consumidor-final-{company.uuid.hex}', names='CONSUMIDOR FINAL', email=None, is_active=False)
    usuario.set_unusable_password()
    usuario.save()
    return Client.objects.create(user=usuario, dni=CONSUMIDOR_FINAL, identification_type='07', mobile='0000000000',
                                 address='S/N', send_email_invoice=False)


def usuario_de_cliente(form_usuario, dni):
    """Usuario nuevo para un comprador: con su identificación como nombre si está libre; si no, uno distinto."""
    from core.user.models import User
    usuario = form_usuario.save(commit=False)
    usuario.username = dni if not User.objects.filter(username=dni).exists() else f'{dni}-{uuid.uuid4().hex[:8]}'
    usuario.set_password(dni)
    usuario.save()
    usuario.groups.add(Group.objects.get(pk=settings.GROUPS['client']))
    return usuario
