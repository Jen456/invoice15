"""Validación del archivo subido: tamaño, formato real (por el contenido, no por la extensión) e imágenes legibles."""
import hashlib
import io
import os
import re

from PIL import Image, UnidentifiedImageError

from core.adjuntos.models import FORMATOS

MB = 1024 * 1024
MAX_BYTES = 8 * MB                # nginx admite 10 MB por petición: cada comprobante viaja en su propia petición
MAX_POR_DOCUMENTO = 10
MAX_PIXELES = 50_000_000          # una foto de celular tiene entre 12 y 50 megapíxeles
FORMATOS_TEXTO = 'PDF, JPG, PNG o WEBP'


class ArchivoInvalido(ValueError):
    pass


def tipo_real(contenido):
    """Tipo de contenido por los primeros bytes, o None si no es uno admitido."""
    if contenido.startswith(b'%PDF-'):
        return 'application/pdf'
    if contenido.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if contenido.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if contenido[:4] == b'RIFF' and contenido[8:12] == b'WEBP':
        return 'image/webp'
    return None


def _nombre_saneado(nombre, extension):
    base = os.path.basename((nombre or '').replace('\\', '/'))
    base = re.sub(r'[\x00-\x1f\x7f]', '', base).strip()
    raiz, _ = os.path.splitext(base)
    raiz = ' '.join(raiz.split())[:150 - len(extension) - 1] or 'comprobante'
    return f'{raiz}.{extension}'


def _comprobar_imagen(contenido):
    try:
        with Image.open(io.BytesIO(contenido)) as imagen:
            ancho, alto = imagen.size
            if ancho * alto > MAX_PIXELES:
                raise ArchivoInvalido('La imagen es demasiado grande: reduce su resolución antes de subirla.')
            imagen.verify()
    except ArchivoInvalido:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        raise ArchivoInvalido('La imagen no se puede leer: vuelve a tomarla o expórtala como JPG, PNG o PDF.')


def validar(nombre, contenido):
    """(nombre saneado con la extensión real, tipo de contenido, sha256) o ArchivoInvalido."""
    if not contenido:
        raise ArchivoInvalido('El archivo está vacío.')
    if len(contenido) > MAX_BYTES:
        raise ArchivoInvalido(f'El archivo pesa más de {MAX_BYTES // MB} MB. Comprime el PDF o reduce la foto.')
    tipo = tipo_real(contenido)
    if tipo is None:
        raise ArchivoInvalido(f'Solo se admiten comprobantes en {FORMATOS_TEXTO}.')
    if tipo != 'application/pdf':
        _comprobar_imagen(contenido)
    return _nombre_saneado(nombre, FORMATOS[tipo]), tipo, hashlib.sha256(contenido).hexdigest()
