"""Importación del plan de cuentas con vista previa (C3 del contrato contable v9). Todo ocurre en la empresa activa.

Tres pasos, y nada se crea hasta el último:

1. `subir`: lee el archivo (CSV o XLSX), lo guarda en la carpeta privada de la empresa con su huella y deja un lote
   `ImportacionCuentas` con los encabezados, las filas leídas y las columnas elegidas por su encabezado;
2. `mapear`: el usuario corrige qué columna trae cada dato (código, nombre, padre, tipo y clase);
3. `confirmar`: vuelve a calcular la vista previa contra las cuentas que existan en ese momento y, si ninguna fila tiene
   errores, crea las cuentas por niveles (los padres antes que sus hijas).

La vista previa (`vista_previa`) no se guarda: sale de las filas leídas, del mapeo y de las cuentas de la empresa, y por eso
dice siempre lo que pasaría si se confirmara ahora. Cada fila queda `valida` (se creará), `duplicada` (su código ya existe
en la empresa, sin distinguir mayúsculas: se omite o se le actualiza el nombre, nunca el padre, el tipo ni la clase) o
`error`. La columna «clase» (bloque 2) es opcional: uno de los seis valores (activo, pasivo, patrimonio, ingreso, costo,
gasto) o vacía; cualquier otro valor es un error de la fila. Nunca se deduce del código.

Las reglas son las del plan de cuentas (cuentas.py) y de ahí salen: la forma del código y del nombre, el código único sin
distinguir mayúsculas, el padre grupo, «sin ciclos» y la cola por empresa de toda escritura del plan. Las del árbol se
aplican a las filas que se van a crear; a una duplicada solo se le revisa lo que se lee de ella.

Sin duplicados: la subida lleva su `clave` (repetida con el mismo archivo devuelve el mismo lote) y la confirmación la
suya, que queda en el lote (repetida devuelve el mismo resultado). Con el lote bloqueado, dos confirmaciones a la vez
crean las cuentas una sola vez.

El plan pagado y el complemento los decide PlanMiddleware antes de llegar aquí. Con el plan vencido solo se consulta: los
envíos los corta el middleware y, por si llegan como un formulario que él toma por consulta (la subida lo es por fuerza),
también api.ApiContable."""
import csv
import hashlib
import io
import math
import zipfile
from datetime import date, time, timedelta
from itertools import count, islice

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from core.contabilidad import api, cuentas
from core.contabilidad.models import Cuenta, ImportacionCuentas, limpiar_codigo, norma_codigo
from core.importacion.reporte_sri import normalizar_encabezado
from core.tenancy.models import audit

MB = 1024 * 1024
MAX_BYTES = 2 * MB
MAX_FILAS = 5000                 # filas de cuentas (sin la de encabezados ni las que están en blanco)
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
MUESTRA = 5                      # filas de muestra para elegir las columnas
POR_INSERCION = 500              # cuentas por sentencia al crear o actualizar

VISTA_PREVIA, CONFIRMADO = 'vista_previa', 'confirmado'
OMITIR, ACTUALIZAR_NOMBRE = 'omitir', 'actualizar_nombre'
VALIDA, DUPLICADA, ERROR = 'valida', 'duplicada', 'error'
CAMPOS = ('codigo', 'nombre', 'padre', 'tipo', 'clase')
OBLIGATORIOS = ('codigo', 'nombre')
# Encabezados (normalizados: sin tildes ni mayúsculas) que señalan cada dato, por orden de preferencia. Una columna sirve
# para un solo dato: «Cuenta» es el código salvo que otra columna ya lo sea; entonces es el nombre («Código» y «Cuenta»).
SINONIMOS = {
    'codigo': ('CODIGO', 'CUENTA', 'CODE'),
    'nombre': ('NOMBRE', 'DESCRIPCION', 'DETALLE', 'NAME', 'CUENTA'),
    'padre': ('PADRE', 'CUENTA_PADRE', 'PARENT'),
    'tipo': ('TIPO', 'TYPE'),
    'clase': ('CLASE', 'CLASS'),
}
TIPOS_LEIDOS = {'G': cuentas.GRUPO, 'GRUPO': cuentas.GRUPO,
                'M': cuentas.MOVIMIENTO, 'MOVIMIENTO': cuentas.MOVIMIENTO, 'DETALLE': cuentas.MOVIMIENTO}
NOMBRES_DE_CAMPO = {'codigo': 'el código', 'nombre': 'el nombre', 'padre': 'el padre', 'tipo': 'el tipo', 'clase': 'la clase'}
# La clase como se escribe en la hoja (sin tildes ni mayúsculas): solo sus seis valores, en singular.
CLASES_LEIDAS = {normalizar_encabezado(clase): clase for clase in cuentas.CLASES if clase}

TEXTOS = {
    'archivo': 'Elige el archivo del plan de cuentas (CSV o XLSX).',
    'archivo_grande': f'El archivo pesa más de {MAX_BYTES // MB} MB: deja solo la hoja del plan de cuentas o divídelo.',
    'descomprimido': 'El XLSX ocupa demasiado al abrirlo: copia las cuentas a un libro nuevo y sube ese.',
    'demasiadas_celdas': 'El archivo tiene demasiadas celdas fuera de la tabla de cuentas: copia solo la tabla a un archivo '
                         'nuevo y sube ese.',
    'demasiadas_filas': f'El archivo tiene más de {MAX_FILAS:,} filas de cuentas: divídelo e impórtalo por partes.'.replace(',', ' '),
    'demasiadas_columnas': f'El archivo tiene más de {MAX_COLUMNAS} columnas: deja solo las del plan de cuentas.',
    'demasiado_texto': 'El archivo trae demasiado texto para un plan de cuentas: deja solo las columnas del plan (código, '
                       'nombre, padre y tipo) y súbelo de nuevo.',
    'formato': 'No se pudo leer el archivo: debe ser un CSV (UTF-8, separado por punto y coma o por coma) o un XLSX.',
    'codificacion': 'El CSV no está en UTF-8: en la hoja de cálculo, guárdalo como «CSV UTF-8» o sube el XLSX.',
    'comillas': 'El CSV no se pudo leer a partir de la fila {fila}: revisa sus comillas (unas que no se cierran o texto pegado '
                'después de cerrarlas) o guarda el archivo de nuevo desde la hoja de cálculo.',
    'xls': 'Es un XLS antiguo o un libro protegido con contraseña: guárdalo como XLSX sin contraseña o como CSV UTF-8.',
    'xlsx_declaraciones': 'El XLSX trae declaraciones que una hoja de cálculo no escribe (DOCTYPE): ábrelo y guárdalo de nuevo '
                          'como XLSX, o súbelo como CSV UTF-8.',
    'vacio': 'El archivo está vacío.',
    'sin_filas': 'El archivo solo tiene la fila de encabezados: no trae ninguna cuenta.',
    'clave_usada': 'Esta clave ya se usó para subir otro archivo: vuelve a cargar la página e inténtalo de nuevo.',
    'lote': 'La importación no existe o es de otra empresa.',
    'lote_confirmado': 'Esta importación ya se confirmó: sus cuentas ya están en el plan.',
    'clave_confirmacion': 'Esta importación ya se confirmó con esa clave y otra opción para las cuentas que ya existían.',
    'columna': 'Esa columna no está en el archivo.',
    'columna_repetida': 'Esa columna ya está elegida para otro dato.',
    'faltan_columnas': 'Elige qué columna del archivo trae {datos} de cada cuenta.',
    'filas_con_error': 'Hay filas con errores: corrige el archivo o las columnas elegidas. No se creó ninguna cuenta.',
    'duplicadas': 'Indica qué hacer con las cuentas que ya existen: omitirlas o actualizar su nombre.',
    'plan_cambiado': 'El plan de cuentas cambió mientras se confirmaba la importación: revisa la vista previa y vuelve a '
                     'intentarlo. No se creó ninguna cuenta.',
    # de cada fila
    'repetido': 'El código {codigo} está repetido en el archivo: ya aparece en la fila {fila}.',
    'padre_no_existe': 'El padre {codigo} no existe.',
    'padre_movimiento': 'El padre {codigo} ya existe en esta empresa como cuenta de movimiento: pásalo a grupo antes de importar.',
    'movimiento_con_hijas': 'Es de movimiento y el archivo le cuelga cuentas hijas: debe ser grupo.',
    'tipo': 'Tipo no reconocido («{valor}»): escribe grupo o movimiento.',
    'clase': 'Clase no reconocida («{valor}»): escribe activo, pasivo, patrimonio, ingreso, costo o gasto, o déjala vacía.',
    'alterada': 'La hoja de cálculo cambió {dato} (lo guardó como fecha o como un número que ya no es exacto): '
                'escríbelo como texto.',
    'sobran': 'La fila tiene más celdas que columnas el encabezado: revisa si un texto con el separador va sin comillas.',
}
# Lo que le falta a una fila se dice como de un archivo; el resto de fallas del código y del nombre, como en el alta.
FALLAS_DE_FILA = {'codigo': 'Falta el código.', 'nombre': 'Falta el nombre.'}


def _ilegible(texto='formato'):
    return api.ErrorApi('formato', TEXTOS[texto])


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


def _filas_csv(datos):
    """Filas `(número, celdas)` de un CSV en UTF-8 (con o sin BOM), con comillas. No se adivina otra codificación: un
    nombre con tildes mal leídas quedaría guardado mal sin que nadie lo note. Tampoco dónde terminaba un texto con las
    comillas mal puestas: el archivo se rechaza diciendo la fila."""
    try:
        texto = datos.decode('utf-8-sig')
    except UnicodeDecodeError:
        binario = any(b < 9 or 13 < b < 32 for b in datos[:4096])   # un texto en otra codificación no trae bytes de control
        raise _ilegible('formato' if binario else 'codificacion') from None
    if '\x00' in texto or texto.lstrip()[:5] == '%PDF-' or texto.lstrip()[:1] == '<':   # PDF, XML o una página web
        raise _ilegible()
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
        raise api.ErrorApi('formato', TEXTOS['comillas'].format(fila=leidas + 1)) from None


def _xlsx_revisado(datos):
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
    revisado = io.BytesIO()
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as original, zipfile.ZipFile(revisado, 'w', zipfile.ZIP_STORED) as copia:
            partes = original.infolist()
            if sum(parte.file_size for parte in partes) > MAX_DESCOMPRIMIDO:
                raise api.ErrorApi('archivo_grande', TEXTOS['descomprimido'])
            # Con nombres repetidos vale la última entrada, que es la que el lector encontraría por su nombre.
            for parte in {parte.filename: parte for parte in partes}.values():
                if parte.compress_type not in COMPRESIONES_XLSX:
                    raise _ilegible()
                with original.open(parte) as abierta:
                    trozos = iter(lambda: abierta.read(TROZO), b'')
                    if not parte.filename.lower().endswith(PARTES_XML):
                        for _ in trozos:   # imagen u objeto incrustado: se lee por su suma y su cifrado...
                            pass
                        copia.writestr(parte.filename, b'')   # ...y su contenido no se copia nunca
                        continue
                    contenido = b''.join(trozos)
                if any(marca in contenido for marca in DOCTYPE):
                    raise _ilegible('xlsx_declaraciones')
                copia.writestr(parte.filename, contenido)
    except api.ErrorApi:
        raise
    except Exception:   # noqa: BLE001 - no es un ZIP, o una parte está dañada, cifrada o comprimida de otra forma
        raise _ilegible() from None
    revisado.seek(0)
    return revisado


def _filas_xlsx(datos):
    """Filas `(número, valores)` de la primera hoja de un XLSX (con la fórmula ya calculada, si la hay). El lector no
    abre el archivo tal como llegó, sino su copia revisada."""
    import openpyxl
    revisado = _xlsx_revisado(datos)
    try:
        libro = openpyxl.load_workbook(revisado, read_only=True, data_only=True)
        hoja = libro.worksheets[0]
        hoja.reset_dimensions()   # sin fiarse del tamaño que declara la hoja: algunos programas lo escriben mal
        filas = iter(hoja.iter_rows(values_only=True))
    except Exception:   # noqa: BLE001 - dañado, cifrado o sin hojas: openpyxl lanza errores distintos
        raise _ilegible() from None
    try:
        for numero in count(1):
            try:
                valores = next(filas, None)
            except Exception:   # noqa: BLE001 - la hoja está dañada a medias
                raise _ilegible() from None
            if valores is None:
                return
            if numero > MAX_FILAS_HOJA:
                raise _ilegible()
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


def _tabla(origen):
    """`(encabezados, filas)` de las filas crudas. La primera fila con contenido es la de encabezados; las que están en
    blanco se saltan sin perder la cuenta: cada fila guarda su número en el archivo. Forma de cada fila:
    `{"n": número, "c": [texto de cada columna], "f": [columnas alteradas por la hoja], "s": true si sobran celdas}`
    (`f` y `s` solo si aplican)."""
    encabezados, filas, vistas, guardados = None, [], 0, 0
    for numero, valores in origen:
        vistas += len(valores)
        if vistas > MAX_CELDAS:
            raise api.ErrorApi('archivo_grande', TEXTOS['demasiadas_celdas'])
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
                raise _ilegible('demasiadas_columnas')
            encabezados = _encabezados([texto for texto, _ in celdas])
            continue
        if len(filas) == MAX_FILAS:
            raise api.ErrorApi('demasiadas_filas', TEXTOS['demasiadas_filas'])
        ancho = len(encabezados)
        fila = {'n': numero, 'c': [texto for texto, _ in celdas[:ancho]] + [''] * (ancho - len(celdas))}
        guardados += sum(map(len, fila['c']))
        if guardados > MAX_CARACTERES:   # se corta aquí, sin terminar de leer ni llegar a guardar nada
            raise api.ErrorApi('archivo_grande', TEXTOS['demasiado_texto'])
        alteradas = [columna for columna, (_, alterada) in enumerate(celdas[:ancho]) if alterada]
        if alteradas:
            fila['f'] = alteradas
        if len(celdas) > ancho:   # un dato sin columna: no se puede elegir en el mapeo ni se debe perder en silencio
            fila['s'] = True
        filas.append(fila)
    if encabezados is None:
        raise _ilegible('vacio')
    if not filas:
        raise _ilegible('sin_filas')
    return encabezados, filas


def leer(datos):
    """`(extensión, encabezados, filas)` de un CSV o un XLSX, reconocidos por su contenido y no por su nombre. Lanza el
    400 que corresponda: `formato` (ilegible, vacío, otro tipo de archivo), `demasiadas_filas` o `archivo_grande` (por su
    peso, por lo que ocupa al abrirlo, por sus celdas o por el texto de su tabla)."""
    if len(datos) > MAX_BYTES:
        raise api.ErrorApi('archivo_grande', TEXTOS['archivo_grande'])
    if datos.startswith(b'PK\x03\x04'):
        return ('xlsx', *_tabla(_filas_xlsx(datos)))
    if datos.startswith(b'\xd0\xcf\x11\xe0'):   # XLS de antes de 2007 o libro cifrado
        raise _ilegible('xls')
    return ('csv', *_tabla(_filas_csv(datos)))


def detectar(encabezados):
    """Qué columna trae cada dato, por su encabezado (sin distinguir mayúsculas ni tildes): `{campo: encabezado o None}`."""
    normales = [normalizar_encabezado(encabezado) for encabezado in encabezados]
    mapeo, usadas = {}, set()
    for campo in CAMPOS:
        mapeo[campo] = None
        for sinonimo in SINONIMOS[campo]:
            columna = next((i for i, normal in enumerate(normales) if normal == sinonimo and i not in usadas), None)
            if columna is not None:
                mapeo[campo] = encabezados[columna]
                usadas.add(columna)
                break
    return mapeo


# ---------------------------------------------------------------- vista previa

class _Fila:
    """Una fila del archivo mientras se revisa. `existente`: la cuenta de la empresa con su mismo código (duplicada).
    El padre es, como mucho, una de dos cosas: una cuenta que ya existe (`padre_existente`) u otra fila que se va a
    crear (`padre_nuevo`)."""
    __slots__ = ('numero', 'codigo', 'norma', 'nombre', 'padre', 'tipo', 'tipo_escrito', 'clase', 'errores', 'primera',
                 'existente', 'padre_existente', 'padre_nuevo')

    def __init__(self, numero, codigo, nombre):
        self.numero, self.codigo, self.nombre, self.clase = numero, codigo, nombre, ''
        self.norma = norma_codigo(codigo) if codigo else None
        self.padre = self.tipo = self.tipo_escrito = self.existente = self.padre_existente = self.padre_nuevo = None
        self.errores, self.primera = [], True

    @property
    def se_crea(self):
        """Tiene código, no existe en la empresa y es su primera aparición en el archivo: a ella se le aplican las
        reglas del árbol."""
        return self.norma is not None and self.existente is None and self.primera

    @property
    def estado(self):
        return ERROR if self.errores else (DUPLICADA if self.existente is not None else VALIDA)


class Previa:
    """Vista previa de un lote: `filas` y `resumen` con la forma del contrato; `revisadas`, las filas por dentro (lo que
    usa la confirmación)."""

    def __init__(self, revisadas=(), faltan=()):
        self.revisadas = list(revisadas)
        self.filas = [{'fila': f.numero, 'codigo': f.codigo, 'nombre': f.nombre, 'padre': f.padre, 'tipo': f.tipo,
                       'clase': f.clase, 'estado': f.estado, 'errores': f.errores} for f in self.revisadas]
        estados = [f['estado'] for f in self.filas]
        self.resumen = {
            'validas': estados.count(VALIDA), 'con_error': estados.count(ERROR), 'duplicadas': estados.count(DUPLICADA),
            # Sin la columna del código o la del nombre no hay nada que revisar: la lista de filas va vacía.
            'faltan_columnas': list(faltan),
            'texto': TEXTOS['faltan_columnas'].format(datos=' y '.join(NOMBRES_DE_CAMPO[c] for c in faltan)) if faltan else None,
        }


def cuentas_de_la_empresa(bloqueadas=False):
    """Las cuentas de la empresa activa por su código comparable, con lo que la vista previa necesita de cada una. Una
    consulta. `bloqueadas` (al confirmar, dentro de la transacción): con sus filas bloqueadas, para que ni el tipo de un
    padre ni un nombre cambien entre lo que se revisa y lo que se escribe, tampoco desde quien no pase por la cola."""
    consulta = Cuenta.objects.order_by('pk')
    if bloqueadas:
        consulta = consulta.select_for_update()
    return {c['codigo_norm']: c for c in consulta.values('id', 'codigo', 'codigo_norm', 'nombre', 'tipo', 'padre_id')}


def _prefijos(codigo):
    """Los códigos de los que `codigo` podría colgar según sus puntos, del más largo al más corto: de 1.1.01, 1.1 y 1. Vale
    también para quien termina cada nivel en punto (de 1.1.01., «1.1.» y «1.»): se prueban las dos formas."""
    tramos = codigo.rstrip('.').split('.')
    for corte in range(len(tramos) - 1, 0, -1):
        prefijo = '.'.join(tramos[:corte])
        yield prefijo + '.'
        yield prefijo


def vista_previa(lote, existentes=None):
    """Qué pasaría con cada fila del lote si se confirmara ahora, contra las cuentas de la empresa (`existentes`; si no
    se pasan, se leen). No escribe nada."""
    if existentes is None:
        existentes = cuentas_de_la_empresa()
    mapeo = lote.mapeo or {}
    columna = {campo: lote.encabezados.index(mapeo[campo]) if mapeo.get(campo) in lote.encabezados else None for campo in CAMPOS}
    faltan = [campo for campo in OBLIGATORIOS if columna[campo] is None]
    if faltan:
        return Previa(faltan=faltan)

    # 1. Lo que se lee de cada fila: código, nombre y tipo, y el código repetido dentro del archivo.
    revisadas, primeras = [], {}
    for cruda in lote.filas:
        celdas, alteradas = cruda['c'], cruda.get('f', ())
        fila = _Fila(cruda['n'], limpiar_codigo(celdas[columna['codigo']]), celdas[columna['nombre']])
        if cruda.get('s'):
            fila.errores.append(TEXTOS['sobran'])
        falla = cuentas.falla_del_codigo(fila.codigo)
        if falla:
            fila.errores.append(FALLAS_DE_FILA.get(falla) or cuentas.TEXTOS[falla])
        elif columna['codigo'] in alteradas:
            fila.errores.append(TEXTOS['alterada'].format(dato='el código'))
        falla = cuentas.falla_del_nombre(fila.nombre)
        if falla:
            fila.errores.append(FALLAS_DE_FILA.get(falla) or cuentas.TEXTOS[falla])
        if fila.norma is not None:
            primera = primeras.setdefault(fila.norma, fila)
            if primera is not fila:
                fila.primera = False
                fila.errores.append(TEXTOS['repetido'].format(codigo=fila.codigo, fila=primera.numero))
            fila.existente = existentes.get(fila.norma)
        escrito = celdas[columna['tipo']] if columna['tipo'] is not None else ''
        if escrito:
            fila.tipo_escrito = TIPOS_LEIDOS.get(normalizar_encabezado(escrito))
            if fila.tipo_escrito is None:
                fila.errores.append(TEXTOS['tipo'].format(valor=escrito[:30]))
                fila.tipo_escrito = ERROR   # escrito y no reconocido: no se deduce otro
        clase = celdas[columna['clase']] if columna['clase'] is not None else ''
        if clase:
            fila.clase = CLASES_LEIDAS.get(normalizar_encabezado(clase), '')
            if not fila.clase:
                fila.errores.append(TEXTOS['clase'].format(valor=clase[:30]))
        revisadas.append((fila, celdas, alteradas))

    # 2. El padre: el de su columna o, sin ella, el prefijo más largo del código que exista (en la empresa o en el archivo).
    con_hijas = set()   # códigos de los que cuelga alguna fila del archivo
    for fila, celdas, alteradas in revisadas:
        escrito = limpiar_codigo(celdas[columna['padre']]) if columna['padre'] is not None else ''
        if fila.norma is None:   # sin código no cuelga de nadie: se muestra lo que trae y nada más
            fila.padre = escrito or None
            continue
        candidatos = ([escrito] if escrito else []) if columna['padre'] is not None else _prefijos(fila.codigo)
        for candidato in candidatos:
            norma = norma_codigo(candidato)
            fila.padre_existente = existentes.get(norma)   # la cuenta que ya existe manda sobre la fila que la repite
            fila.padre_nuevo = primeras.get(norma) if fila.padre_existente is None else None
            if fila.padre_existente is not None or fila.padre_nuevo is not None:
                con_hijas.add(norma)
                break
        if fila.padre_existente is not None:
            fila.padre = fila.padre_existente['codigo']
        else:
            fila.padre = fila.padre_nuevo.codigo if fila.padre_nuevo is not None else (escrito or None)
        if not fila.se_crea:
            continue
        if escrito and columna['padre'] in alteradas:
            fila.errores.append(TEXTOS['alterada'].format(dato='el padre'))
        elif escrito and fila.padre_existente is None and fila.padre_nuevo is None:
            fila.errores.append(TEXTOS['padre_no_existe'].format(codigo=escrito))
        elif fila.padre_existente is not None and fila.padre_existente['tipo'] != cuentas.GRUPO:
            fila.errores.append(TEXTOS['padre_movimiento'].format(codigo=fila.padre_existente['codigo']))

    # 3. El tipo (el escrito o, si falta, grupo cuando tiene hijas) y las reglas del árbol entre las filas que se crean.
    con_hijas_en_la_empresa = {c['padre_id'] for c in existentes.values()}
    padres = {fila.norma: fila.padre_nuevo.norma if fila.padre_nuevo is not None else None
              for fila, _, _ in revisadas if fila.se_crea}
    for fila, _, _ in revisadas:
        tiene_hijas = fila.norma in con_hijas or (fila.existente is not None and fila.existente['id'] in con_hijas_en_la_empresa)
        if fila.tipo_escrito is None:
            fila.tipo = cuentas.GRUPO if tiene_hijas else cuentas.MOVIMIENTO
        elif fila.tipo_escrito != ERROR:
            fila.tipo = fila.tipo_escrito
        if not fila.se_crea:
            continue
        if fila.tipo_escrito == cuentas.MOVIMIENTO and fila.norma in con_hijas:
            fila.errores.append(TEXTOS['movimiento_con_hijas'])
        if fila.padre_nuevo is not None and cuentas.cuelga_de(padres, fila.padre_nuevo.norma, fila.norma):
            fila.errores.append(cuentas.TEXTOS['ciclo'])
    return Previa(fila for fila, _, _ in revisadas)


# ---------------------------------------------------------------- el lote, con la forma del contrato

def dict_lote(lote):
    """El lote como lo devuelve la API. En vista previa, con sus filas revisadas ahora; confirmado, con su resultado."""
    datos = {'id': lote.pk, 'estado': lote.estado, 'archivo': lote.nombre_original}
    if lote.estado == CONFIRMADO:
        datos.update(duplicadas=lote.duplicadas, creadas=lote.resultado['creadas'], actualizadas=lote.resultado['actualizadas'],
                     omitidas=lote.resultado['omitidas'], confirmado_en=timezone.localtime(lote.confirmado_en).date().isoformat())
        return datos
    previa = vista_previa(lote)
    datos.update(columnas={campo: (lote.mapeo or {}).get(campo) for campo in CAMPOS}, encabezados=lote.encabezados,
                 # Las primeras filas tal como se leyeron, columna por columna: para elegir el mapeo viendo qué trae cada una.
                 muestra=[fila['c'] for fila in lote.filas[:MUESTRA]], filas=previa.filas, resumen=previa.resumen)
    return datos


def _lote(pk, bloqueado=False):
    """El lote de la empresa activa (404 si no existe o es de otra). `bloqueado`: dentro de una transacción, para
    cambiarlo."""
    consulta = ImportacionCuentas.objects.select_for_update() if bloqueado else ImportacionCuentas.objects
    lote = consulta.filter(pk=pk).first()
    if lote is None:
        raise api.ErrorApi('lote', TEXTOS['lote'], 404)
    return lote


def consultar(request, pk):
    api.exigir_permiso(request, cuentas.CREAR)
    return _lote(pk)


# ---------------------------------------------------------------- 1. subir

def _nombre_original(archivo, extension):
    nombre = ''.join(c for c in str(getattr(archivo, 'name', '') or '') if c.isprintable()).strip()
    return nombre[-255:] or f'plan.{extension}'


def _subida_repetida(existente, sha256):
    if existente.sha256 == sha256:
        return existente, True
    raise api.ErrorApi('clave_usada', TEXTOS['clave_usada'], 409)


def subir(request, archivo, datos):
    """Lee el archivo y deja el lote en vista previa. Devuelve (lote, repetido). No crea ninguna cuenta."""
    api.exigir_permiso(request, cuentas.CREAR)
    clave = api.clave_de(datos)
    if archivo is None:
        raise api.ErrorApi('validacion', errores={'archivo': [TEXTOS['archivo']]})
    if archivo.size > MAX_BYTES:   # antes de leerlo: no se carga en memoria un archivo que no se va a aceptar
        raise api.ErrorApi('archivo_grande', TEXTOS['archivo_grande'])
    contenido = archivo.read()
    sha256 = hashlib.sha256(contenido).hexdigest()
    existente = ImportacionCuentas.objects.filter(clave=clave).first()
    if existente is not None:
        return _subida_repetida(existente, sha256)
    extension, encabezados, filas = leer(contenido)
    lote = ImportacionCuentas(company=request.company, clave=clave, nombre_original=_nombre_original(archivo, extension),
                              tamano=len(contenido), sha256=sha256, encabezados=encabezados, filas=filas,
                              mapeo=detectar(encabezados), creado_por=request.user)
    lote.archivo.save(f'plan.{extension}', ContentFile(contenido), save=False)
    guardado = lote.archivo.name
    try:
        with transaction.atomic():
            lote.save()
    except IntegrityError:
        # Otra subida simultánea guardó antes la misma clave: vale la suya y este archivo sobra.
        lote.archivo.storage.delete(guardado)
        existente = ImportacionCuentas.objects.filter(clave=clave).first()
        if existente is None:
            raise
        return _subida_repetida(existente, sha256)
    except Exception:
        lote.archivo.storage.delete(guardado)
        raise
    return lote, False


# ---------------------------------------------------------------- 2. mapear

def mapear(request, pk, datos):
    """Fija qué columna trae cada dato: `{codigo, nombre, padre, tipo, clase}`, cada uno un encabezado del archivo o nulo (el que
    no venga queda sin columna). Devuelve el lote; su vista previa se recalcula al leerlo."""
    api.exigir_permiso(request, cuentas.CREAR)
    with transaction.atomic():
        lote = _lote(pk, bloqueado=True)
        if lote.estado == CONFIRMADO:
            raise api.ErrorApi('lote_confirmado', TEXTOS['lote_confirmado'], 409, lote=dict_lote(lote))
        errores, mapeo = api.Errores(), {}
        for campo in CAMPOS:
            pedido = datos.get(campo)
            mapeo[campo] = None
            if pedido is None or pedido == '':
                continue
            if not isinstance(pedido, str) or pedido not in lote.encabezados:
                errores.agregar(campo, TEXTOS['columna'])
            elif pedido in mapeo.values():   # la misma columna para dos datos: una cuenta sería su propio padre
                errores.agregar(campo, TEXTOS['columna_repetida'])
            else:
                mapeo[campo] = pedido
        errores.comprobar()
        lote.mapeo = mapeo
        lote.save(update_fields=['mapeo'])
    return lote


# ---------------------------------------------------------------- 3. confirmar

def _por_niveles(nuevas):
    """Las filas que se crean, en tandas: primero las que cuelgan de una cuenta que ya existe o de la raíz y después, en
    cada tanda, las hijas de la anterior. Así cada una se inserta con su padre ya creado. Sin recursión: la profundidad
    la pone el archivo. Solo se llama sin filas en error, es decir, sin ciclos."""
    nivel = {}
    for fila in nuevas:
        camino = []
        while fila is not None and fila.norma not in nivel:
            camino.append(fila)
            fila = fila.padre_nuevo
        siguiente = nivel[fila.norma] + 1 if fila is not None else 0
        for paso in reversed(camino):
            nivel[paso.norma] = siguiente
            siguiente += 1
    tandas = [[] for _ in range(max(nivel.values(), default=-1) + 1)]
    for fila in nuevas:
        tandas[nivel[fila.norma]].append(fila)
    return tandas


def _crear(request, lote, nuevas, ahora):
    """Inserta las cuentas por tandas. Sin `save()` por fila (serían miles de consultas): por eso aquí se fija a mano lo
    que `Cuenta.save()` haría (empresa, código limpio y comparable) y solo se usan padres que salen de las cuentas de la
    empresa activa o de este mismo lote. La seguridad por filas de la base sigue valiendo para cada inserción."""
    ids = {}
    for tanda in _por_niveles(nuevas):
        creadas = Cuenta.objects.bulk_create([
            Cuenta(company=request.company, lote=lote, codigo=fila.codigo, codigo_norm=fila.norma, nombre=fila.nombre,
                   tipo=fila.tipo, clase=fila.clase, auxiliar='', version=1, clave=None, creada_por=request.user, creada_en=ahora,
                   actualizada_por=request.user, actualizada_en=ahora,
                   padre_id=fila.padre_existente['id'] if fila.padre_existente is not None
                   else (ids[fila.padre_nuevo.norma] if fila.padre_nuevo is not None else None))
            for fila in tanda], batch_size=POR_INSERCION)
        if any(cuenta.pk is None for cuenta in creadas):   # sin los ids, las hijas quedarían en la raíz sin avisar
            raise RuntimeError('La base de datos no devolvió los ids de las cuentas creadas.')
        ids.update((cuenta.codigo_norm, cuenta.pk) for cuenta in creadas)


def _renombrar(request, cambios, ahora):
    """Actualiza el nombre de las cuentas que ya existían (sus filas están bloqueadas) y sube su versión, como todo
    cambio de una cuenta. Devuelve `[[id, nombre anterior, nombre nuevo]]`: el rastro que queda en el lote.

    El nombre es lo único distinto en cada cuenta y va en una sentencia por tanda; lo que es igual para todas (la
    versión siguiente, quién y cuándo) va en otra. Armar las cuatro columnas cuenta por cuenta tardaba cuatro veces más."""
    Cuenta.objects.bulk_update([Cuenta(pk=fila.existente['id'], nombre=fila.nombre) for fila in cambios], ['nombre'],
                               batch_size=POR_INSERCION)
    ids = [fila.existente['id'] for fila in cambios]
    for desde in range(0, len(ids), POR_INSERCION):
        Cuenta.objects.filter(pk__in=ids[desde:desde + POR_INSERCION]).update(
            version=F('version') + 1, actualizada_por=request.user, actualizada_en=ahora)
    return [[fila.existente['id'], fila.existente['nombre'], fila.nombre] for fila in cambios]


def _alguna_existe(normas):
    return any(Cuenta.objects.filter(codigo_norm__in=normas[desde:desde + POR_INSERCION]).exists()
               for desde in range(0, len(normas), POR_INSERCION))


def confirmar(request, pk, datos):
    """Crea las cuentas del lote: `{clave, duplicadas: "omitir" | "actualizar_nombre"}`. Devuelve (lote, repetido).

    Todo en una transacción, en la cola de escrituras del plan de la empresa y con el lote bloqueado. La vista previa se
    vuelve a calcular dentro, contra las cuentas de ese momento: con una sola fila en error no se crea nada."""
    api.exigir_permiso(request, cuentas.CREAR)
    duplicadas = datos.get('duplicadas')
    if duplicadas == ACTUALIZAR_NOMBRE:   # cambiar el nombre de una cuenta que ya existe es editarla
        api.exigir_permiso(request, cuentas.EDITAR)
    clave = api.clave_de(datos)
    if duplicadas not in (OMITIR, ACTUALIZAR_NOMBRE):
        raise api.ErrorApi('validacion', errores={'duplicadas': [TEXTOS['duplicadas']]})
    intentadas = []
    try:
        with transaction.atomic():
            cuentas.serializar(request.company)
            lote = _lote(pk, bloqueado=True)
            if lote.estado == CONFIRMADO:
                if lote.clave_confirmacion != clave:
                    raise api.ErrorApi('lote_confirmado', TEXTOS['lote_confirmado'], 409, lote=dict_lote(lote))
                if lote.duplicadas != duplicadas:
                    raise api.ErrorApi('clave_usada', TEXTOS['clave_confirmacion'], 409, lote=dict_lote(lote))
                return lote, True
            previa = vista_previa(lote, cuentas_de_la_empresa(bloqueadas=True))
            if previa.resumen['faltan_columnas']:
                raise api.ErrorApi('faltan_columnas', previa.resumen['texto'], resumen=previa.resumen)
            if previa.resumen['con_error']:
                raise api.ErrorApi('filas_con_error', TEXTOS['filas_con_error'], resumen=previa.resumen)
            ahora = timezone.now()
            nuevas = [fila for fila in previa.revisadas if fila.existente is None]
            intentadas.extend(fila.norma for fila in nuevas)
            _crear(request, lote, nuevas, ahora)
            renombradas = []
            if duplicadas == ACTUALIZAR_NOMBRE:   # si el nombre ya es el mismo no hay cambio: cuenta como omitida
                renombradas = _renombrar(request, [fila for fila in previa.revisadas if fila.existente is not None
                                                   and fila.nombre != fila.existente['nombre']], ahora)
            lote.estado, lote.clave_confirmacion, lote.duplicadas = CONFIRMADO, clave, duplicadas
            lote.confirmado_por, lote.confirmado_en = request.user, ahora
            lote.resultado = {'creadas': len(nuevas), 'actualizadas': len(renombradas),
                              'omitidas': previa.resumen['duplicadas'] - len(renombradas), 'renombradas': renombradas}
            lote.save(update_fields=['estado', 'clave_confirmacion', 'duplicadas', 'confirmado_por', 'confirmado_en', 'resultado'])
            audit(request, 'cuentas_importadas', company=request.company, lote=lote.pk, creadas=lote.resultado['creadas'],
                  actualizadas=lote.resultado['actualizadas'], omitidas=lote.resultado['omitidas'], duplicadas=duplicadas,
                  archivo=lote.nombre_original, sha256=lote.sha256)
            return lote, False
    except IntegrityError:
        # Alguien creó una de esas cuentas sin esperar en la cola, entre la revisión y la inserción: decide la restricción
        # única, la transacción se deshizo entera y basta repetir la confirmación.
        if not _alguna_existe(intentadas):
            raise
        raise api.ErrorApi('plan_cambiado', TEXTOS['plan_cambiado'], 409) from None
