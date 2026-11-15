"""Lector tabular común de la contabilidad: CSV o XLSX con una fila de encabezados, reconocidos por su contenido. Lo usan la
importación del plan de cuentas (C3, core/contabilidad/importar_cuentas.py), la de los saldos de la apertura
(apertura_importar.py) y la validación de los respaldos de la apertura (respaldos.py, con `es_xlsx`).

Nació en importar_cuentas.py (bloque 1) y se movió aquí al unir el corte 1 del bloque 2 con el cierre del bloque 1, sin
cambiar lo que responde C3: las mismas defensas y los mismos límites (2 MB y 5 000 filas) para las dos importaciones, y
cada corrección vale para todas. Las defensas:

- CSV en UTF-8 (con o sin BOM), con `;` o `,` y comillas estrictas; no se adivina otra codificación;
- XLSX revisado parte por parte antes de dárselo al lector (`_xlsx_revisado`): tamaño descomprimido, compresión de un XLSX
  (sin bzip2 ni lzma), lectura entera a trozos (suma y cifrado de cada parte), DOCTYPE en las partes XML y el resto de
  partes (imágenes, objetos incrustados) vacías en la copia;
- topes de celdas, filas, columnas y texto.

Lo único que cambia entre las importaciones son los textos: los de cada caso (`TEXTOS`) son generales y el llamador da los
suyos (`leer(datos, textos)`): C3 habla del plan de cuentas («deja solo la hoja del plan de cuentas»), la apertura de los
saldos. Los que no da, como el de la codificación o las comillas, salen de aquí."""
import csv
import io
import math
import zipfile
from datetime import date, time, timedelta
from itertools import count, islice

from core.contabilidad import api

MB = 1024 * 1024
MAX_BYTES = 2 * MB
MAX_FILAS = 5000                 # filas de datos (sin la de encabezados ni las que están en blanco)
# Un XLSX es un ZIP: 2 MB pueden esconder gigas. Un plan de 5 000 cuentas ocupa, abierto, menos de 1 MB.
MAX_DESCOMPRIMIDO = 20 * MB
# Un XLSX tampoco declara entidades XML: ninguna hoja de cálculo escribe un DOCTYPE en las partes XML del libro. Con él, el
# tope de arriba no basta: una entidad de 270 caracteres citada millones de veces cabe en 25 KB comprimidos y en 20 MB
# descomprimidos, y el lector de XML la expande a gigas de memoria. Se busca en las codificaciones que ese lector entiende:
# las de un byte por carácter (UTF-8, ISO-8859-1…) lo escriben igual que ASCII, y UTF-16 en sus dos órdenes.
DOCTYPE = tuple('<!DOCTYPE'.encode(codificacion) for codificacion in ('ascii', 'utf-16-le', 'utf-16-be'))
# Las partes XML del libro, las únicas que el lector recibe con su contenido. Las demás son imágenes y objetos
# incrustados: un logo SVG va tal cual en xl/media y el que exporta un programa de dibujo trae su DOCTYPE. Van en la copia,
# pero vacías: aun en solo lectura, el lector abre las imágenes del dibujo de una hoja de gráfico, y una que falta en el
# archivo (KeyError) tumba el libro, mientras que una vacía la descarta como imagen que no se puede leer.
PARTES_XML = ('.xml', '.rels')
# Cómo comprime sus partes un XLSX (ECMA-376, parte 2, anexo C): tal cual o con deflate. Con bzip2 o lzma, `ZipFile`
# descomprime de una vez cada trozo que lee, sin tope, y leer a trozos no acota la memoria.
COMPRESIONES_XLSX = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
TROZO = 64 * 1024                # las partes de un XLSX se leen a trozos: ver _xlsx_revisado
MAX_FILAS_HOJA = 1_048_576       # las que admite una hoja de cálculo: una hoja que declare más está mal formada
MAX_COLUMNAS = 40
# Celdas que se llegan a mirar, con contenido o sin él (5 000 filas de 40 columnas son 200 000). Una hoja con formato hasta
# la última columna de cada fila, o hecha para agotar al lector, se corta aquí y no a los 60 s de gunicorn.
MAX_CELDAS = 2_000_000
CELDA_MAX = 300                  # se guarda un carácter más: un nombre o un código que no cabe sigue sin caber
# Texto que se guarda de las filas de un archivo (la suma de sus celdas, también las de columnas que nadie elija). Los topes
# de arriba se multiplican entre sí: 5 000 filas de 40 columnas de 300 caracteres son 60 millones de caracteres, y un XLSX
# los trae en 32 KB porque todas sus celdas citan la misma cadena. El lote los guardaba (hasta 352 MB de JSON, que cada
# consulta volvía a cargar) y no caduca. Con este tope un lote no guarda más texto que el que cabe en el archivo más grande
# que se acepta; a un CSV no lo rechaza nunca, porque no puede traer más caracteres que bytes.
MAX_CARACTERES = MAX_BYTES
ENCABEZADO_MAX = 80

# Los textos de cada caso en que el lector rechaza un archivo. Los que hablan de lo que trae la tabla los cambia cada
# importación; los de la forma del archivo (formato, codificación, comillas, XLS, DOCTYPE, vacío) valen para todas.
TEXTOS = {
    'archivo_grande': f'El archivo pesa más de {MAX_BYTES // MB} MB: deja solo la hoja de la tabla o divídelo.',
    'descomprimido': 'El XLSX ocupa demasiado al abrirlo: copia la tabla a un libro nuevo y sube ese.',
    'demasiadas_celdas': 'El archivo tiene demasiadas celdas fuera de la tabla: copia solo la tabla a un archivo nuevo y '
                         'sube ese.',
    'demasiadas_filas': f'El archivo tiene más de {MAX_FILAS:,} filas: divídelo e impórtalo por partes.'.replace(',', ' '),
    'demasiadas_columnas': f'El archivo tiene más de {MAX_COLUMNAS} columnas: deja solo las de la tabla.',
    'demasiado_texto': 'El archivo trae demasiado texto: deja solo las columnas de la tabla y súbelo de nuevo.',
    'formato': 'No se pudo leer el archivo: debe ser un CSV (UTF-8, separado por punto y coma o por coma) o un XLSX.',
    'codificacion': 'El CSV no está en UTF-8: en la hoja de cálculo, guárdalo como «CSV UTF-8» o sube el XLSX.',
    'comillas': 'El CSV no se pudo leer a partir de la fila {fila}: revisa sus comillas (unas que no se cierran o texto pegado '
                'después de cerrarlas) o guarda el archivo de nuevo desde la hoja de cálculo.',
    'xls': 'Es un XLS antiguo o un libro protegido con contraseña: guárdalo como XLSX sin contraseña o como CSV UTF-8.',
    'xlsx_declaraciones': 'El XLSX trae declaraciones que una hoja de cálculo no escribe (DOCTYPE): ábrelo y guárdalo de nuevo '
                          'como XLSX, o súbelo como CSV UTF-8.',
    'vacio': 'El archivo está vacío.',
    'sin_filas': 'El archivo solo tiene la fila de encabezados: no trae ninguna fila de datos.',
}
# Las claves de los textos del lector, para que el llamador sepa cuáles puede cambiar.
CASOS = tuple(TEXTOS)


def _textos(textos):
    return {**TEXTOS, **{caso: texto for caso, texto in (textos or {}).items() if caso in TEXTOS}}


def _ilegible(textos, caso='formato'):
    return api.ErrorApi('formato', textos[caso])


# ---------------------------------------------------------------- lectura del archivo

def _celda(valor):
    """`(texto, alterada)` de una celda. Siempre texto, sin espacios sobrantes: un número que es un código (1101) se lee
    sin `.0`. `alterada`: la hoja de cálculo guardó una fecha o un número que ya no dice lo que se escribió (un código
    1-1-01 convertido en fecha, uno de más de 15 cifras redondeado). Como nombre no importa; como código no es de fiar."""
    alterada = False
    if valor is None:
        return '', False
    if isinstance(valor, bool):
        texto = 'VERDADERO' if valor else 'FALSO'
    elif isinstance(valor, float):
        alterada = not math.isfinite(valor) or abs(valor) >= 1e15
        texto = str(int(valor)) if not alterada and valor.is_integer() else repr(valor)
    elif isinstance(valor, (date, time)):   # también fecha con hora
        texto, alterada = valor.isoformat(), True
    else:
        texto, alterada = ' '.join(str(valor).split()), isinstance(valor, timedelta)
    return texto[:CELDA_MAX + 1], alterada


def _separador(texto):
    """`;` o `,`: el que parte las primeras filas en las mismas columnas que el encabezado (y en más de una). Mirar solo
    cuál aparece más se equivoca con los nombres que llevan comas. Si empatan, `;`: es el que usan las hojas de cálculo
    en español."""
    mejor, puntos = ';', (0, 0)
    for separador in (';', ','):
        try:
            filas = [f for f in islice(csv.reader(io.StringIO(texto, newline=''), delimiter=separador), 60) if any(f)][:20]
        except csv.Error:
            continue
        ancho = len(filas[0]) if filas else 0
        candidato = (sum(1 for f in filas if len(f) == ancho), ancho) if ancho > 1 else (0, 0)
        if candidato > puntos:
            mejor, puntos = separador, candidato
    return mejor


def _filas_csv(datos, textos):
    """Filas `(número, celdas)` de un CSV en UTF-8 (con o sin BOM), con comillas. No se adivina otra codificación: un
    nombre con tildes mal leídas quedaría guardado mal sin que nadie lo note. Tampoco dónde terminaba un texto con las
    comillas mal puestas: el archivo se rechaza diciendo la fila."""
    try:
        texto = datos.decode('utf-8-sig')
    except UnicodeDecodeError:
        binario = any(b < 9 or 13 < b < 32 for b in datos[:4096])   # un texto en otra codificación no trae bytes de control
        raise _ilegible(textos, 'formato' if binario else 'codificacion') from None
    if '\x00' in texto or texto.lstrip()[:5] == '%PDF-' or texto.lstrip()[:1] == '<':   # PDF, XML o una página web
        raise _ilegible(textos)
    # `strict`: sin él, una comilla que se abre y no se cierra se traga las filas siguientes dentro de esa celda (y `_celda`
    # borra el rastro al cambiar los saltos de línea por espacios): la fila salía válida y las demás desaparecían sin un
    # solo error. También rechaza el texto pegado tras cerrar unas comillas, que se leía perdiéndolas. Un salto de línea
    # dentro de unas comillas bien cerradas sigue valiendo.
    lector, leidas = csv.reader(io.StringIO(texto, newline=''), delimiter=_separador(texto), strict=True), 0
    try:
        for leidas, celdas in enumerate(lector, 1):
            yield leidas, celdas
    except csv.Error:
        # La fila que no se pudo leer es la siguiente a la última que sí: donde se abrieron las comillas.
        raise api.ErrorApi('formato', textos['comillas'].format(fila=leidas + 1)) from None


def _xlsx_revisado(datos, textos=None):
    """El XLSX que se le da al lector: una copia sin comprimir de sus partes XML, ya revisadas, en la que las demás van
    vacías. Un XLSX es un ZIP y lo que declara no basta para fiarse de él:

    - el tamaño descomprimido se comprueba antes de leer nada, con lo que declara cada parte;
    - una parte comprimida de otra forma que la de un XLSX (ver COMPRESIONES_XLSX) no se abre;
    - cada parte se lee entera, a trozos y hasta lo que declara: así se comprueban su suma y su cifrado, también en las
      que el lector no va a recibir. `ZipFile.read`, que es lo que usa el lector, descomprime de una vez todo lo que trae
      la entrada y solo después lo recorta: una parte que declara 1 KB y trae 300 MB ocupaba 600 MB de memoria. Por eso
      el lector no recibe el archivo original sino esta copia, cuyas partes ocupan lo que dicen;
    - la copia lleva con su contenido solo las partes XML del libro (ver PARTES_XML), y ninguna puede declarar entidades
      XML (ver DOCTYPE). Se miran todas, se llamen como se llamen: cuál lee el lector como cadenas compartidas o como hoja
      lo dice el propio archivo. Las imágenes y los objetos incrustados van vacíos: el lector los encuentra (los busca
      en los dibujos de las hojas de gráfico) pero no lee nada de ellos, y una parte que no se revisó no le sirve de hoja,
      digan lo que digan las relaciones del libro, porque una parte vacía no es una hoja.

    Entre todas las partes no pasan de MAX_DESCOMPRIMIDO, y eso es lo más que ocupa la copia."""
    textos = _textos(textos)
    revisado = io.BytesIO()
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as original, zipfile.ZipFile(revisado, 'w', zipfile.ZIP_STORED) as copia:
            partes = original.infolist()
            if sum(parte.file_size for parte in partes) > MAX_DESCOMPRIMIDO:
                raise api.ErrorApi('archivo_grande', textos['descomprimido'])
            # Con nombres repetidos vale la última entrada, que es la que el lector encontraría por su nombre.
            for parte in {parte.filename: parte for parte in partes}.values():
                if parte.compress_type not in COMPRESIONES_XLSX:
                    raise _ilegible(textos)
                with original.open(parte) as abierta:
                    trozos = iter(lambda: abierta.read(TROZO), b'')
                    if not parte.filename.lower().endswith(PARTES_XML):
                        for _ in trozos:   # imagen u objeto incrustado: se lee por su suma y su cifrado...
                            pass
                        copia.writestr(parte.filename, b'')   # ...y su contenido no se copia nunca
                        continue
                    contenido = b''.join(trozos)
                if any(marca in contenido for marca in DOCTYPE):
                    raise _ilegible(textos, 'xlsx_declaraciones')
                copia.writestr(parte.filename, contenido)
    except api.ErrorApi:
        raise
    except Exception:   # noqa: BLE001 - no es un ZIP, o una parte está dañada, cifrada o comprimida de otra forma
        raise _ilegible(textos) from None
    revisado.seek(0)
    return revisado


def _filas_xlsx(datos, textos):
    """Filas `(número, valores)` de la primera hoja de un XLSX (con la fórmula ya calculada, si la hay). El lector no
    abre el archivo tal como llegó, sino su copia revisada."""
    import openpyxl
    revisado = _xlsx_revisado(datos, textos)
    try:
        libro = openpyxl.load_workbook(revisado, read_only=True, data_only=True)
        hoja = libro.worksheets[0]
        hoja.reset_dimensions()   # sin fiarse del tamaño que declara la hoja: algunos programas lo escriben mal
        filas = iter(hoja.iter_rows(values_only=True))
    except Exception:   # noqa: BLE001 - dañado, cifrado o sin hojas: openpyxl lanza errores distintos
        raise _ilegible(textos) from None
    try:
        for numero in count(1):
            try:
                valores = next(filas, None)
            except Exception:   # noqa: BLE001 - la hoja está dañada a medias
                raise _ilegible(textos) from None
            if valores is None:
                return
            if numero > MAX_FILAS_HOJA:
                raise _ilegible(textos)
            yield numero, valores
    finally:
        libro.close()


def _encabezados(textos):
    """Nombres de las columnas, únicos: con ellos se elige el mapeo. Una celda vacía pasa a «Columna 3» y un encabezado
    repetido lleva su número de orden, «Nombre (2)»."""
    nombres = []
    for posicion, texto in enumerate(textos, 1):
        base = texto[:ENCABEZADO_MAX] or f'Columna {posicion}'
        nombre, vez = base, 1
        while nombre in nombres:
            vez += 1
            nombre = f'{base} ({vez})'
        nombres.append(nombre)
    return nombres


def _tabla(origen, textos):
    """`(encabezados, filas)` de las filas crudas. La primera fila con contenido es la de encabezados; las que están en
    blanco se saltan sin perder la cuenta: cada fila guarda su número en el archivo. Forma de cada fila:
    `{"n": número, "c": [texto de cada columna], "f": [columnas alteradas por la hoja], "s": true si sobran celdas}`
    (`f` y `s` solo si aplican)."""
    encabezados, filas, vistas, guardados = None, [], 0, 0
    for numero, valores in origen:
        vistas += len(valores)
        if vistas > MAX_CELDAS:
            raise api.ErrorApi('archivo_grande', textos['demasiadas_celdas'])
        valores = list(valores)
        while valores and valores[-1] in (None, ''):   # antes de convertir nada: una fila ancha y vacía no cuesta
            valores.pop()
        celdas = [_celda(valor) for valor in valores]
        while celdas and not celdas[-1][0]:
            celdas.pop()
        if not celdas:
            continue
        if encabezados is None:
            if len(celdas) > MAX_COLUMNAS:
                raise _ilegible(textos, 'demasiadas_columnas')
            encabezados = _encabezados([texto for texto, _ in celdas])
            continue
        if len(filas) == MAX_FILAS:
            raise api.ErrorApi('demasiadas_filas', textos['demasiadas_filas'])
        ancho = len(encabezados)
        fila = {'n': numero, 'c': [texto for texto, _ in celdas[:ancho]] + [''] * (ancho - len(celdas))}
        guardados += sum(map(len, fila['c']))
        if guardados > MAX_CARACTERES:   # se corta aquí, sin terminar de leer ni llegar a guardar nada
            raise api.ErrorApi('archivo_grande', textos['demasiado_texto'])
        alteradas = [columna for columna, (_, alterada) in enumerate(celdas[:ancho]) if alterada]
        if alteradas:
            fila['f'] = alteradas
        if len(celdas) > ancho:   # un dato sin columna: no se puede elegir en el mapeo ni se debe perder en silencio
            fila['s'] = True
        filas.append(fila)
    if encabezados is None:
        raise _ilegible(textos, 'vacio')
    if not filas:
        raise _ilegible(textos, 'sin_filas')
    return encabezados, filas


def leer(datos, textos=None):
    """`(extensión, encabezados, filas)` de un CSV o un XLSX, reconocidos por su contenido y no por su nombre. Forma de cada
    fila: `{"n": número de fila en el archivo, "c": [texto de cada columna], "f": [columnas que la hoja alteró], "s": true
    si sobran celdas}` (`f` y `s` solo si aplican). Lanza el 400 que corresponda: `formato` (ilegible, vacío, otro tipo de
    archivo), `demasiadas_filas` o `archivo_grande` (por su peso, por lo que ocupa al abrirlo, por sus celdas o por el
    texto de su tabla), con el texto de `textos[caso]` si el llamador lo da (ver CASOS) y, si no, el de TEXTOS."""
    textos = _textos(textos)
    if len(datos) > MAX_BYTES:
        raise api.ErrorApi('archivo_grande', textos['archivo_grande'])
    if datos.startswith(b'PK\x03\x04'):
        return ('xlsx', *_tabla(_filas_xlsx(datos, textos), textos))
    if datos.startswith(b'\xd0\xcf\x11\xe0'):   # XLS de antes de 2007 o libro cifrado
        raise _ilegible(textos, 'xls')
    return ('csv', *_tabla(_filas_csv(datos, textos), textos))


def es_xlsx(datos):
    """True si `datos` es un libro XLSX que se abre: firma ZIP, partes revisadas como al importar (`_xlsx_revisado`: ninguna
    bomba de descompresión, ninguna parte en bzip2 o lzma, ninguna suma rota ni cifrado, ninguna entidad XML en sus partes
    XML) y apertura con openpyxl en solo lectura con al menos una hoja. No lee sus celdas."""
    import openpyxl
    if not datos.startswith(b'PK\x03\x04'):
        return False
    try:
        revisado = _xlsx_revisado(datos)
        libro = openpyxl.load_workbook(revisado, read_only=True, data_only=True)
    except Exception:   # noqa: BLE001 - no es un ZIP, trae DOCTYPE, ocupa demasiado o no es un libro
        return False
    try:
        return bool(libro.sheetnames)
    finally:
        libro.close()
