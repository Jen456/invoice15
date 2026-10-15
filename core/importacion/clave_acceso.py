"""Clave de acceso de 49 dígitos (ficha técnica, tabla 1): estructura y dígito verificador módulo 11."""
import re
from dataclasses import dataclass
from datetime import date
from itertools import cycle

PATRON = re.compile(r'(?<!\d)\d{49}(?!\d)')


class ClaveInvalida(ValueError):
    """La clave no tiene 49 dígitos, la fecha no existe o el dígito verificador no coincide."""


@dataclass(frozen=True)
class ClaveAcceso:
    clave: str
    fecha_emision: date
    cod_doc: str
    ruc: str
    ambiente: int
    estab: str
    pto_emi: str
    secuencial: str
    codigo_numerico: str
    tipo_emision: str
    digito: str

    @property
    def serie(self):
        return f'{self.estab}-{self.pto_emi}'

    @property
    def numero(self):
        return f'{self.estab}-{self.pto_emi}-{self.secuencial}'


def digito_verificador(primeros_48):
    """Módulo 11 con factores 2..7 desde la derecha (11 → 0, 10 → 1), igual que al emitir."""
    suma = sum(int(d) * f for d, f in zip(reversed(primeros_48), cycle((2, 3, 4, 5, 6, 7))))
    resto = 11 - suma % 11
    return '0' if resto == 11 else '1' if resto == 10 else str(resto)


def es_valida(clave):
    try:
        analizar(clave)
        return True
    except ClaveInvalida:
        return False


def analizar(clave):
    clave = (clave or '').strip()
    if not re.fullmatch(r'\d{49}', clave):
        raise ClaveInvalida('La clave de acceso debe tener exactamente 49 dígitos.')
    if digito_verificador(clave[:48]) != clave[48]:
        raise ClaveInvalida('El dígito verificador de la clave de acceso no coincide.')
    try:
        fecha = date(int(clave[4:8]), int(clave[2:4]), int(clave[0:2]))
    except ValueError:
        raise ClaveInvalida('La fecha contenida en la clave de acceso no existe.')
    ambiente = int(clave[23])
    if ambiente not in (1, 2):
        raise ClaveInvalida('El ambiente de la clave de acceso debe ser 1 (pruebas) o 2 (producción).')
    return ClaveAcceso(clave=clave, fecha_emision=fecha, cod_doc=clave[8:10], ruc=clave[10:23], ambiente=ambiente,
                       estab=clave[24:27], pto_emi=clave[27:30], secuencial=clave[30:39], codigo_numerico=clave[39:47],
                       tipo_emision=clave[47], digito=clave[48])


def candidatas(texto):
    """Claves válidas (dígito verificador correcto) dentro de un texto, sin repetir y en orden de aparición."""
    vistas = []
    for encontrada in PATRON.findall(texto or ''):
        if encontrada not in vistas and es_valida(encontrada):
            vistas.append(encontrada)
    return vistas
