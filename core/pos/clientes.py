"""Compradores por empresa.

El usuario de un comprador usaba su identificación como nombre de usuario, único en toda la plataforma:
si otra empresa ya lo había registrado (o el «CONSUMIDOR FINAL» 9999999999999 de las empresas de
demostración), la empresa no podía crearlo. Cada empresa tiene ahora su propio consumidor final y, si la
identificación ya está tomada por otra empresa, se crea un usuario aparte (no se comparten datos).
"""
import re
import uuid

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from config import settings
from core.login.identificacion import cedula_valida, ruc_valido

CONSUMIDOR_FINAL = '9999999999999'
# Pasaporte e identificación del exterior: hasta 20 caracteres como en el XML del SRI (identificacionComprador),
# p. ej. el RUC panameño 155652251-2-2017 DV7.
EXTRANJERA = re.compile(r'[A-Z0-9][A-Z0-9 -]{1,18}[A-Z0-9]')


def validar_identificacion(tipo, numero):
    """(número normalizado, [(campo, error)]) según el tipo (tabla 6 de la ficha técnica del SRI)."""
    if tipo in ('06', '08'):
        numero = ' '.join((numero or '').split()).upper()
    else:
        numero = re.sub(r'\s', '', numero or '').upper()
    errores = []
    if tipo == '05' and not cedula_valida(numero):
        errores.append(('dni', 'La cédula no es válida: revisa los 10 dígitos.'))
    elif tipo == '04' and not ruc_valido(numero):
        errores.append(('dni', 'El RUC no es válido: revisa los 13 dígitos.'))
    elif tipo == '07' and numero != CONSUMIDOR_FINAL:
        errores.append(('dni', 'Para consumidor final la identificación es 9999999999999.'))
    elif tipo in ('06', '08') and not EXTRANJERA.fullmatch(numero):
        errores.append(('dni', 'El pasaporte o la identificación del exterior admite de 3 a 20 letras, números, guiones y espacios.'))
    if tipo and tipo != '07' and numero == CONSUMIDOR_FINAL:
        errores.append(('identification_type', 'El 9999999999999 solo se usa con «Venta a consumidor final».'))
    return numero, errores


def separar_correos(*textos):
    """Direcciones en orden y sin repetir (sin distinguir mayúsculas), separadas por comas, punto y coma o espacios."""
    vistos, correos = set(), []
    for texto in textos:
        for correo in re.split(r'[,;\s]+', (texto or '').strip()):
            if correo and correo.casefold() not in vistos:
                vistos.add(correo.casefold())
                correos.append(correo)
    return correos


def correo_valido(correo):
    try:
        validate_email(correo)
        return True
    except ValidationError:
        return False


def unir_correos(correos, largo):
    """Las direcciones que caben enteras en `largo` caracteres, separadas por «, »."""
    texto = ''
    for correo in correos:
        candidato = f'{texto}, {correo}' if texto else correo
        if len(candidato) > largo:
            break
        texto = candidato
    return texto


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
