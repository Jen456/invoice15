"""Proveedores con los datos del ATS: tipo de identificación, tipo de sujeto y parte relacionada (espec-etapa2-compras §3.3).

- El número se valida con core.pos.clientes.validar_identificacion según el tipo (04 RUC, 05 cédula, 06 pasaporte,
  08 identificación del exterior). El 07 (consumidor final) no se admite.
- Tipo de sujeto derivado con RUC (tercer dígito 6 o 9 → sociedad; si no, persona natural) y cédula (persona natural);
  elegido con pasaporte o identificación del exterior.
- Parte relacionada: siempre la elige el usuario (DC12); nada la sugiere.
"""
import re

from core.login.identificacion import cedula_valida, ruc_valido
from core.pos.catalogos_sri import TIPOS_IDENTIFICACION_PROVEEDOR, TIPOS_SUJETO

CAMPOS = {'dni': 'ruc', 'identification_type': 'tipo_identificacion'}
LARGO_ATS = 13


def sujeto_de_ruc(ruc):
    """'02' (sociedad) si el tercer dígito del RUC es 6 (pública) o 9 (privada); si no, '01' (persona natural)."""
    ruc = re.sub(r'\s', '', ruc or '')
    return '02' if len(ruc) >= 3 and ruc[2] in '69' else '01'


def _parte_relacionada(valor):
    if valor is None or isinstance(valor, bool):
        return valor
    texto = str(valor).strip().lower()
    return True if texto in ('si', 'sí', 'true', '1') else False if texto in ('no', 'false', '0') else None


def validar_proveedor(tipo, numero, tipo_sujeto, parte_relacionada):
    """(número normalizado, tipo de sujeto final, errores [(campo, texto)], advertencias [(código, texto)])."""
    from core.pos.clientes import validar_identificacion
    errores, advertencias = [], []
    tipo = (tipo or '').strip()
    if tipo not in dict(TIPOS_IDENTIFICACION_PROVEEDOR):
        mensaje = ('Un proveedor no puede ser consumidor final: elige RUC, cédula, pasaporte o identificación del exterior.'
                   if tipo == '07' else 'Elige el tipo de identificación.')
        errores.append(('tipo_identificacion', mensaje))
        return (numero or '').strip(), (tipo_sujeto or '').strip(), errores, advertencias
    numero, errores_numero = validar_identificacion(tipo, numero)
    errores.extend((CAMPOS.get(campo, campo), texto) for campo, texto in errores_numero)
    tipo_sujeto = (tipo_sujeto or '').strip()
    if tipo == '04':
        tipo_sujeto = sujeto_de_ruc(numero)
    elif tipo == '05':
        tipo_sujeto = '01'
    elif tipo_sujeto not in dict(TIPOS_SUJETO):
        errores.append(('tipo_sujeto', 'Elige si es persona natural o sociedad'))
    if _parte_relacionada(parte_relacionada) is None:
        errores.append(('parte_relacionada', 'Indica si es parte relacionada'))
    if tipo in ('06', '08') and len(numero) > LARGO_ATS:
        advertencias.append(('ats_longitud', 'El ATS admite hasta 13 caracteres en la identificación del proveedor'))
    return numero, tipo_sujeto, errores, advertencias


def sugerencia(proveedor):
    """{'tipo_identificacion', 'tipo_sujeto'} solo si no hay ambigüedad (RUC válido de 13 dígitos o cédula válida de 10);
    si no, None. Nunca sugiere la parte relacionada."""
    numero = re.sub(r'\s', '', proveedor.ruc or '')
    if re.fullmatch(r'\d{13}', numero) and ruc_valido(numero):
        return {'tipo_identificacion': '04', 'tipo_sujeto': sujeto_de_ruc(numero)}
    if re.fullmatch(r'\d{10}', numero) and cedula_valida(numero):
        return {'tipo_identificacion': '05', 'tipo_sujeto': '01'}
    return None
