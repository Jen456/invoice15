"""Secretos guardados cifrados en la base (la clave de la firma electrónica .p12).

Fernet (AES-128-CBC + HMAC-SHA256) con llaves que viven fuera de la base y del repositorio: FPA_CLAVES_CIFRADO en el
entorno del servicio, separadas por comas. La primera cifra; las demás solo descifran (rotación: se agrega una nueva al
inicio y se ejecuta `manage.py claves_firma --recifrar`). Un volcado o una lectura de la base ya no revela la clave.

ClaveCifrada guarda 'fernet:<token>' y entrega el texto en claro al leer, así que el resto del código no cambia. El vacío
se guarda vacío (para saber si hay clave sin descifrar). Un valor anterior sin prefijo se lee tal cual y se cifra al
guardarse. Si un valor no se puede descifrar (llave equivocada o perdida) se entrega como vacío, pero al guardar se
conserva el original: un error de configuración no borra las claves.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django import forms
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

PREFIJO = 'fernet:'
log = logging.getLogger(__name__)


class SecretoIlegible(str):
    """Valor que no se pudo descifrar: se comporta como '' y conserva lo guardado (`crudo`)."""

    def __new__(cls, crudo):
        objeto = super().__new__(cls, '')
        objeto.crudo = crudo
        return objeto


def llaves():
    """Llaves configuradas; en desarrollo (DEBUG) sin llave, una derivada de SECRET_KEY."""
    configuradas = [k.strip() for k in getattr(settings, 'FPA_CLAVES_CIFRADO', []) if k.strip()]
    if configuradas:
        return configuradas
    if settings.DEBUG:
        return [base64.urlsafe_b64encode(hashlib.sha256(f'fpa-cifrado:{settings.SECRET_KEY}'.encode()).digest()).decode()]
    raise ImproperlyConfigured('Falta FPA_CLAVES_CIFRADO (llave Fernet) en el entorno del servicio.')


def _fernet():
    return MultiFernet([Fernet(k.encode()) for k in llaves()])


def cifrar(texto):
    if isinstance(texto, SecretoIlegible):
        return texto.crudo
    if not texto:
        return texto
    return PREFIJO + _fernet().encrypt(texto.encode()).decode()


def descifrar(guardado):
    if not guardado or not guardado.startswith(PREFIJO):
        return guardado   # vacío o valor anterior al cifrado
    try:
        return _fernet().decrypt(guardado[len(PREFIJO):].encode()).decode()
    except InvalidToken:
        log.error('Un secreto guardado no se puede descifrar con FPA_CLAVES_CIFRADO (¿llave equivocada o perdida?).')
        return SecretoIlegible(guardado)


def recifrar(guardado):
    """Mismo secreto cifrado con la primera llave (rotación). Lo vacío, lo anterior al cifrado y lo ilegible no cambian."""
    if not guardado or not guardado.startswith(PREFIJO):
        return guardado
    return PREFIJO + _fernet().rotate(guardado[len(PREFIJO):].encode()).decode()


class ClaveCifrada(models.TextField):
    """Texto cifrado en la base y en claro en el modelo. No sirve para buscar por su valor (cada cifrado es distinto)."""

    def __init__(self, *args, longitud_maxima=100, **kwargs):
        self.longitud_maxima = longitud_maxima
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.longitud_maxima != 100:
            kwargs['longitud_maxima'] = self.longitud_maxima
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        return descifrar(value)

    def get_prep_value(self, value):
        return cifrar(super().get_prep_value(value))

    def formfield(self, **kwargs):
        return super().formfield(**{'max_length': self.longitud_maxima, 'widget': forms.PasswordInput(render_value=False),
                                    **kwargs})
