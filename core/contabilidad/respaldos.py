"""Validación por contenido de los archivos de respaldo de la contabilidad (decisión común 12): el de la apertura en este
bloque y, después, las evidencias de presentación del bloque 5, que lo reutilizan.

`validar(nombre, contenido, admitidos)` → `(nombre saneado, tipo, sha256)` o `ArchivoInvalido` con el texto para el
usuario. El tipo se decide por lo que el archivo trae, nunca por su nombre ni por el tipo que declara el navegador:

- PDF, JPG y PNG por su firma (`core.adjuntos.archivos.tipo_real`), con las imágenes abiertas por Pillow (las de los
  comprobantes de pago: `archivos.validar`, que además limita su resolución);
- WEBP se reconoce para rechazarlo con su propio texto: `archivos.validar` lo admite para los comprobantes, pero un
  respaldo contable se guarda en un formato que cualquier programa de contabilidad abre;
- XLSX por la firma ZIP y abriéndolo en solo lectura, con las mismas defensas que la importación del plan de cuentas
  (lectura_tabular.es_xlsx): un ZIP que no es un libro, o que trae una bomba de descompresión, no pasa;
- CSV por decodificación: texto UTF-8 (con o sin BOM) o Windows-1252 sin caracteres de control, que no sea un PDF ni
  una página web o un XML.

Tope de 8 MB por archivo: nginx admite 10 MB por petición y cada archivo viaja en la suya."""
import hashlib
import os
import re

from core.adjuntos import archivos
from core.contabilidad import lectura_tabular

MB = 1024 * 1024
MAX_BYTES = 8 * MB
PDF, JPG, PNG, XLSX, CSV = 'pdf', 'jpg', 'png', 'xlsx', 'csv'
TIPOS = {PDF: 'application/pdf', JPG: 'image/jpeg', PNG: 'image/png',
         XLSX: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', CSV: 'text/csv'}
NOMBRES = {PDF: 'PDF', JPG: 'JPG', PNG: 'PNG', XLSX: 'XLSX', CSV: 'CSV'}
_POR_TIPO_REAL = {'application/pdf': PDF, 'image/jpeg': JPG, 'image/png': PNG}
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
NOMBRE_MAX = 150


class ArchivoInvalido(ValueError):
    """El archivo no se acepta; el mensaje es para el usuario."""


def formatos(admitidos):
    """«PDF, JPG, PNG, XLSX o CSV»: los admitidos, como se le dicen al usuario."""
    nombres = [NOMBRES[a] for a in admitidos]
    return nombres[0] if len(nombres) == 1 else f'{", ".join(nombres[:-1])} o {nombres[-1]}'


def nombre_saneado(nombre, extension):
    """El nombre original sin ruta, sin caracteres de control ni espacios sobrantes, con la extensión del tipo real."""
    base = os.path.basename(str(nombre or '').replace('\\', '/'))
    raiz, _ = os.path.splitext(_CONTROL.sub('', base).strip())
    raiz = ' '.join(raiz.split())[:NOMBRE_MAX - len(extension) - 1] or 'respaldo'
    return f'{raiz}.{extension}'


def _es_csv(contenido):
    cuerpo = contenido[3:] if contenido.startswith(b'\xef\xbb\xbf') else contenido
    for codificacion in ('utf-8', 'cp1252'):
        try:
            texto = cuerpo.decode(codificacion)
        except UnicodeDecodeError:
            continue
        inicio = texto.lstrip()[:5]
        return not _CONTROL.search(texto) and inicio[:5] != '%PDF-' and inicio[:1] != '<'
    return False


def _tipo(contenido):
    """El tipo por el contenido (una de las claves de TIPOS, 'webp') o None."""
    real = archivos.tipo_real(contenido)
    if real == 'image/webp':
        return 'webp'
    if real is not None:
        return _POR_TIPO_REAL[real]
    if contenido.startswith(b'PK\x03\x04'):
        return XLSX if lectura_tabular.es_xlsx(contenido) else None
    return CSV if _es_csv(contenido) else None


def validar(nombre, contenido, admitidos=(PDF, JPG, PNG, XLSX, CSV)):
    """`(nombre saneado con la extensión real, tipo de contenido, sha256)` o ArchivoInvalido."""
    if not contenido:
        raise ArchivoInvalido('El archivo está vacío.')
    if len(contenido) > MAX_BYTES:
        raise ArchivoInvalido(f'El archivo pesa más de {MAX_BYTES // MB} MB: comprime el PDF, reduce la imagen o divide la hoja.')
    tipo = _tipo(contenido)
    if tipo == 'webp':
        raise ArchivoInvalido(f'Las imágenes WEBP no se admiten como respaldo contable: guárdala como JPG o PNG. Formatos '
                              f'admitidos: {formatos(admitidos)}.')
    if tipo not in admitidos:
        raise ArchivoInvalido(f'Solo se admiten respaldos en {formatos(admitidos)}: este archivo no es ninguno de ellos o '
                              'está dañado.')
    if tipo in (PDF, JPG, PNG):
        try:
            archivos.validar(nombre, contenido)   # abre la imagen y limita su resolución
        except archivos.ArchivoInvalido as e:
            raise ArchivoInvalido(str(e)) from None
    return nombre_saneado(nombre, tipo), TIPOS[tipo], hashlib.sha256(contenido).hexdigest()
