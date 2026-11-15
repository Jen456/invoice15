"""Lector tabular común de la contabilidad (CSV o XLSX con encabezados): el de la importación del plan de cuentas (C3,
core/contabilidad/importar_cuentas.py, bloque 1), sin nada que dependa del plan de cuentas.

Por qué existe: la apertura (apertura_importar.py) lee sus saldos con las mismas defensas que C3 —CSV en UTF-8 con `;` o
`,`, comillas estrictas, XLSX revisado parte por parte (tamaño descomprimido, DOCTYPE, lectura a trozos), topes de celdas,
filas, columnas y texto— y con los mismos límites (2 MB y 5 000 filas). Duplicarlas sería tener dos lectores que se
separan con la primera corrección; así cada corrección del lector de C3 (las del cierre del bloque 1 incluidas) vale aquí
sin tocar nada.

Lo único que cambia son los textos: los del lector de C3 hablan del plan de cuentas («deja solo la hoja del plan de
cuentas»). `leer(datos, textos)` llama al lector de C3 y, si rechaza el archivo, devuelve el mismo código con el texto que
el llamador da para ese caso (los que no da, como el de la codificación o las comillas, ya son generales).

PENDIENTE AL INTEGRAR EL BLOQUE 2: el código del lector debería vivir aquí y importar_cuentas.py importarlo de este módulo
(la especificación lo pide extraído, «sin cambiar C3»). En esta rama no se movió porque la Parte A edita
importar_cuentas.py a la vez (columna `clase`) y el cierre del bloque 1 corrige su lector: moverlo ahora chocaría con
las dos. La batería de C3 (tests/test_cuentas_importacion.py) es la red de ese movimiento."""
import openpyxl

from core.contabilidad import api
from core.contabilidad import importar_cuentas as _c3

MAX_BYTES = _c3.MAX_BYTES
MAX_FILAS = _c3.MAX_FILAS
# Las claves de los textos del lector, para que el llamador sepa cuáles puede cambiar.
CASOS = ('archivo_grande', 'descomprimido', 'demasiadas_celdas', 'demasiadas_filas', 'demasiadas_columnas',
         'demasiado_texto', 'formato', 'codificacion', 'xls', 'xlsx_declaraciones', 'vacio', 'sin_filas')
_CASO_DE_TEXTO = {_c3.TEXTOS[caso]: caso for caso in CASOS}


def leer(datos, textos=None):
    """`(extensión, encabezados, filas)` de un CSV o un XLSX, reconocidos por su contenido. Forma de cada fila:
    `{"n": número de fila en el archivo, "c": [texto de cada columna], "f": [columnas que la hoja alteró], "s": true si
    sobran celdas}` (`f` y `s` solo si aplican). Lanza el 400 del lector (`archivo_grande`, `demasiadas_filas`, `formato`)
    con el texto de `textos[caso]` si el llamador lo da."""
    try:
        return _c3.leer(datos)
    except api.ErrorApi as e:
        caso = _CASO_DE_TEXTO.get(str(e))
        if textos and caso in textos:
            raise api.ErrorApi(e.codigo, textos[caso], e.estado, e.errores, **e.extra) from None
        raise


def es_xlsx(datos):
    """True si `datos` es un libro XLSX que se abre: firma ZIP, partes revisadas como en C3 (ninguna bomba de
    descompresión ni entidades XML) y apertura con openpyxl en solo lectura con al menos una hoja. No lee sus celdas."""
    if not datos.startswith(b'PK\x03\x04'):
        return False
    try:
        revisado = _c3._xlsx_revisado(datos)
        libro = openpyxl.load_workbook(revisado, read_only=True, data_only=True)
    except Exception:   # noqa: BLE001 - no es un ZIP, trae DOCTYPE, ocupa demasiado o no es un libro
        return False
    try:
        return bool(libro.sheetnames)
    finally:
        libro.close()
