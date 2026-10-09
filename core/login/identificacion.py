"""Identificaciones y teléfonos de Ecuador (validación en el servidor).

- Cédula: 10 dígitos, provincia 01-24 o 30, tercer dígito < 6 y dígito
  verificador módulo 10.
- RUC de persona natural (tercer dígito < 6): cédula válida + establecimiento
  distinto de 000.
- RUC de sociedad privada (9) o entidad pública (6): se valida la estructura
  (provincia, tipo y establecimiento). El dígito verificador módulo 11 no se
  exige porque el SRI ha emitido RUC de sociedades que no lo cumplen.
"""
import re

PROVINCIAS = set(range(1, 25)) | {30}


def solo_digitos(valor):
    return re.sub(r'\D', '', valor or '')


def cedula_valida(cedula):
    if not re.fullmatch(r'\d{10}', cedula or ''):
        return False
    if int(cedula[:2]) not in PROVINCIAS or int(cedula[2]) >= 6:
        return False
    total = 0
    for i, coeficiente in enumerate((2, 1, 2, 1, 2, 1, 2, 1, 2)):
        producto = int(cedula[i]) * coeficiente
        total += producto - 9 if producto > 9 else producto
    return (10 - total % 10) % 10 == int(cedula[9])


def ruc_valido(ruc):
    if not re.fullmatch(r'\d{13}', ruc or ''):
        return False
    if int(ruc[:2]) not in PROVINCIAS:
        return False
    tipo = int(ruc[2])
    if tipo < 6:
        return cedula_valida(ruc[:10]) and ruc[10:] != '000'
    if tipo == 6:
        return ruc[9:] != '0000'
    if tipo == 9:
        return ruc[10:] != '000'
    return False


def tipo_identificacion(numero):
    """'cedula', 'ruc' o None."""
    if cedula_valida(numero):
        return 'cedula'
    if ruc_valido(numero):
        return 'ruc'
    return None


def normalizar_celular(valor):
    """Celular de Ecuador en formato 09XXXXXXXX; acepta +593 y separadores. None si no es válido."""
    digitos = solo_digitos(valor)
    if digitos.startswith('593') and len(digitos) == 12:
        digitos = '0' + digitos[3:]
    return digitos if re.fullmatch(r'09\d{8}', digitos) else None
