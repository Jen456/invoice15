"""RIDE en PDF: procesar_ride_pdf(datos) → ResultadoPdf con la clave de acceso, si se puede leer sin ambigüedad.

- PDF real (cabecera %PDF-), tamaño y páginas limitados; el análisis corre en trabajador_pdf.py, un proceso aparte con
  límites de tiempo, CPU, memoria y resolución.
- Fuentes de la clave: QR y códigos de barras de las páginas renderizadas (la clave directa o dentro de una URL, que NO se
  visita) y, como respaldo, el texto incrustado del PDF (no es OCR). Solo cuentan secuencias de exactamente 49 dígitos con
  dígito verificador válido. Si hay más de una clave distinta, se rechaza por ambigua.
- El PDF nunca es fuente de importes: los datos contables salen del XML autorizado que se recupera del SRI.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field

from core.importacion import clave_acceso, limites
from core.importacion.xml_sri import Mensaje

TRABAJADOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trabajador_pdf.py')


@dataclass
class ResultadoPdf:
    aceptado: bool
    sha256: str
    tamano: int
    estado: str = 'sin_clave'       # clave_encontrada | sin_clave | ambigua | rechazado
    paginas: int = 0
    clave: str | None = None
    origen_clave: str = ''          # codigo_qr | codigo_barras | texto
    candidatas: list = field(default_factory=list)
    errores: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)

    def error(self, codigo, texto, estado='rechazado'):
        self.errores.append(Mensaje(codigo, texto))
        self.aceptado, self.estado = False, estado
        return self

    def to_dict(self):
        return asdict(self)


def _ejecutar_trabajador(datos):
    opciones = {'max_paginas': limites.MAX_PDF_PAGINAS, 'dpi': limites.PDF_DPI, 'max_pixeles': limites.PDF_MAX_PIXELES_PAGINA,
                'memoria': limites.PDF_MEMORIA_BYTES, 'cpu': limites.PDF_CPU_SEGUNDOS}
    proceso = subprocess.run([sys.executable, '-I', TRABAJADOR, json.dumps(opciones)], input=datos, capture_output=True,
                             timeout=limites.PDF_TIEMPO_SEGUNDOS, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, check=False)
    if proceso.returncode != 0:
        raise RuntimeError(f'trabajador terminó con código {proceso.returncode}')
    return json.loads(proceso.stdout.decode('utf-8'))


def _claves_de(texto):
    """Claves válidas en un texto; también si el RIDE la imprime en grupos separados por espacios o saltos."""
    encontradas = clave_acceso.candidatas(texto)
    compacto = re.sub(r'(?<=\d)[ \t\r\n\-]+(?=\d)', '', texto or '')
    for c in clave_acceso.candidatas(compacto):
        if c not in encontradas:
            encontradas.append(c)
    return encontradas


def procesar_ride_pdf(datos):
    datos = bytes(datos or b'')
    resultado = ResultadoPdf(aceptado=True, sha256=hashlib.sha256(datos).hexdigest(), tamano=len(datos))
    if not datos:
        return resultado.error('vacio', 'El archivo está vacío.')
    if len(datos) > limites.MAX_PDF_BYTES:
        return resultado.error('archivo_grande', f'El PDF supera {limites.MAX_PDF_BYTES // limites.MB} MB.')
    if not datos.lstrip(b'\x00\t\r\n ')[:5] == b'%PDF-':
        return resultado.error('no_es_pdf', 'El contenido no es un PDF (falta la cabecera %PDF-).')
    try:
        analisis = _ejecutar_trabajador(datos)
    except subprocess.TimeoutExpired:
        return resultado.error('pdf_tiempo', f'El PDF tardó más de {limites.PDF_TIEMPO_SEGUNDOS} s en analizarse.')
    except (RuntimeError, ValueError, OSError):
        return resultado.error('pdf_invalido', 'No se pudo analizar el PDF (dañado o demasiado complejo).')
    resultado.paginas = analisis.get('paginas', 0)
    error = analisis.get('error')
    if error == 'demasiadas_paginas':
        return resultado.error(error, f'El PDF tiene {resultado.paginas} páginas; un RIDE admite hasta {limites.MAX_PDF_PAGINAS}.')
    if error == 'pdf_protegido':
        return resultado.error(error, 'El PDF está protegido con contraseña.')
    if error:
        return resultado.error('pdf_invalido', 'No se pudo abrir el PDF (dañado o no es un PDF válido).')
    origen = {}
    for simbolo in analisis.get('simbolos', []):
        tipo = 'codigo_qr' if 'QR' in simbolo['formato'] else 'codigo_barras'
        for c in _claves_de(simbolo['texto']):
            origen.setdefault(c, tipo)
    for texto in analisis.get('textos', []):
        for c in _claves_de(texto):
            origen.setdefault(c, 'texto')
    resultado.candidatas = [{'clave': c, 'origen': o} for c, o in origen.items()]
    if not origen:
        resultado.estado, resultado.aceptado = 'sin_clave', False
        resultado.advertencias.append(Mensaje('sin_clave', 'No se encontró una clave de acceso válida: escríbela a mano o sube el XML.'))
        return resultado
    de_codigos = [c for c, o in origen.items() if o != 'texto']
    elegibles = de_codigos or list(origen)
    if len(set(elegibles)) > 1:
        return resultado.error('ambigua', 'El PDF contiene varias claves de acceso distintas: elige la correcta o sube el XML.',
                               estado='ambigua')
    resultado.clave = elegibles[0]
    resultado.origen_clave = origen[resultado.clave]
    resultado.estado = 'clave_encontrada'
    if de_codigos and any(c != resultado.clave for c in origen):
        resultado.advertencias.append(Mensaje('texto_distinto', 'El texto del PDF menciona otra clave; se usa la del código.'))
    return resultado


procesarRidePdf = procesar_ride_pdf   # nombre pedido en el contrato
