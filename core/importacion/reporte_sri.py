"""Listas de claves de acceso y reportes del portal del SRI («Comprobantes electrónicos recibidos») para la importación masiva.

Solo localiza claves y toma datos orientativos (emisor, fecha, importes) como TEXTO: la fuente de cada documento es el XML
autorizado que luego se pide al SRI con la clave (servicios.recuperar_xml). Nunca convierte claves ni RUC a número (una hoja
de cálculo los altera: notación científica, ceros a la izquierda perdidos) y no inventa ningún dato.
"""
import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from core.importacion import clave_acceso, limites

# Encabezado normalizado del reporte → dato que orienta. Los nombres del TXT del portal del SRI (COMPROBANTE, SERIE_COMPROBANTE,
# RUC_EMISOR, RAZON_SOCIAL_EMISOR, FECHA_EMISION, FECHA_AUTORIZACION, TIPO_EMISION, IDENTIFICACION_RECEPTOR, CLAVE_ACCESO,
# NUMERO_AUTORIZACION, IMPORTE_TOTAL, IVA, VALOR_SIN_IMPUESTOS) más sinónimos habituales de quien lo retoca en Excel.
COLUMNAS = {
    'CLAVE_ACCESO': 'clave', 'CLAVE_DE_ACCESO': 'clave', 'CLAVEACCESO': 'clave', 'CLAVE': 'clave', 'CLAVE_ACCESO_COMPROBANTE': 'clave',
    'RUC_EMISOR': 'emisor_ruc', 'RUC_DEL_EMISOR': 'emisor_ruc', 'RUC': 'emisor_ruc', 'RUC_PROVEEDOR': 'emisor_ruc',
    'RAZON_SOCIAL_EMISOR': 'emisor_razon_social', 'RAZON_SOCIAL': 'emisor_razon_social', 'EMISOR': 'emisor_razon_social',
    'PROVEEDOR': 'emisor_razon_social', 'RAZON_SOCIAL_DEL_EMISOR': 'emisor_razon_social',
    'FECHA_EMISION': 'fecha_emision', 'FECHA_DE_EMISION': 'fecha_emision', 'FECHA': 'fecha_emision',
    'FECHA_AUTORIZACION': 'fecha_autorizacion', 'FECHA_DE_AUTORIZACION': 'fecha_autorizacion',
    'TIPO_EMISION': 'tipo_emision',
    'IDENTIFICACION_RECEPTOR': 'receptor_identificacion', 'RUC_RECEPTOR': 'receptor_identificacion',
    'IDENTIFICACION_DEL_RECEPTOR': 'receptor_identificacion', 'RECEPTOR': 'receptor_identificacion',
    'NUMERO_AUTORIZACION': 'numero_autorizacion', 'NUMERO_DE_AUTORIZACION': 'numero_autorizacion', 'AUTORIZACION': 'numero_autorizacion',
    'IMPORTE_TOTAL': 'importe_total', 'TOTAL': 'importe_total', 'VALOR_TOTAL': 'importe_total',
    'IVA': 'total_iva', 'VALOR_IVA': 'total_iva',
    'VALOR_SIN_IMPUESTOS': 'total_sin_impuestos', 'SUBTOTAL': 'total_sin_impuestos', 'BASE': 'total_sin_impuestos',
    'COMPROBANTE': 'tipo_comprobante', 'TIPO_COMPROBANTE': 'tipo_comprobante', 'TIPO_DE_COMPROBANTE': 'tipo_comprobante',
    'TIPO': 'tipo_comprobante',
    'SERIE_COMPROBANTE': 'numero', 'NUMERO': 'numero', 'NUMERO_COMPROBANTE': 'numero', 'SERIE': 'numero', 'NRO': 'numero',
}
TEXTO_COLUMNAS = {'clave': 'clave de acceso', 'emisor_ruc': 'RUC del emisor', 'emisor_razon_social': 'razón social del emisor',
                  'fecha_emision': 'fecha de emisión', 'fecha_autorizacion': 'fecha de autorización', 'tipo_emision': 'tipo de emisión',
                  'receptor_identificacion': 'identificación del receptor', 'numero_autorizacion': 'número de autorización',
                  'importe_total': 'importe total', 'total_iva': 'IVA', 'total_sin_impuestos': 'valor sin impuestos',
                  'tipo_comprobante': 'tipo de comprobante', 'numero': 'número del comprobante'}
IMPORTES = ('importe_total', 'total_iva', 'total_sin_impuestos')
FECHAS = ('fecha_emision', 'fecha_autorizacion')
# Tipo de comprobante tal como lo escribe el portal → código
TIPOS_TEXTO = {'FACTURA': '01', 'LIQUIDACION_DE_COMPRA': '03', 'LIQUIDACION_DE_COMPRA_DE_BIENES_Y_PRESTACION_DE_SERVICIOS': '03',
               'NOTA_DE_CREDITO': '04', 'NOTA_DE_DEBITO': '05', 'GUIA_DE_REMISION': '06', 'COMPROBANTE_DE_RETENCION': '07'}
CIENTIFICA = re.compile(r'^\d(?:[.,]\d+)?E[+-]?\d+$', re.IGNORECASE)
DIGITOS_LARGOS = re.compile(r'\d{40,60}')
MAX_TEXTO_FILA = 160


class ListaInvalida(ValueError):
    """El archivo o el texto no se pueden leer como lista de claves (formato, tamaño o cantidad)."""


@dataclass
class Fila:
    orden: int
    clave: str = ''
    texto: str = ''                 # lo leído, recortado, para mostrar qué se rechazó
    sugerencias: dict = field(default_factory=dict)
    errores: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)

    def error(self, codigo, texto):
        self.errores.append({'codigo': codigo, 'texto': texto})

    def advertencia(self, codigo, texto):
        self.advertencias.append({'codigo': codigo, 'texto': texto})


@dataclass
class Lista:
    filas: list
    formato: str                    # texto | txt | csv | xlsx
    columnas: dict = field(default_factory=dict)      # dato → encabezado original reconocido
    desconocidas: list = field(default_factory=list)  # encabezados que no se usan
    omitidas: int = 0               # filas vacías o sin ningún dato

    def resumen(self):
        return {'formato': self.formato, 'filas': len(self.filas), 'con_clave': sum(1 for f in self.filas if f.clave and not f.errores),
                'rechazadas': sum(1 for f in self.filas if f.errores), 'omitidas': self.omitidas,
                'columnas': {k: v for k, v in self.columnas.items()}, 'columnas_desconocidas': list(self.desconocidas),
                'columnas_texto': {k: TEXTO_COLUMNAS.get(k, k) for k in self.columnas}}


# ------------------------------------------------------------------ utilidades de texto

def normalizar_encabezado(texto):
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c)).upper()
    return re.sub(r'_+', '_', re.sub(r'[^A-Z0-9]+', '_', texto)).strip('_')


def _texto_celda(valor):
    """Siempre texto. Un número (celda numérica de Excel) se devuelve como lo mostraría la hoja, sin ceros ni notación."""
    if valor is None:
        return ''
    if isinstance(valor, bool):
        return 'SI' if valor else 'NO'
    if isinstance(valor, float):
        if valor.is_integer() and abs(valor) < 1e15:
            return str(int(valor))
        return repr(valor)
    if isinstance(valor, (int, Decimal)):
        return str(valor)
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor).strip()


def _fecha_texto(texto):
    """dd/mm/aaaa (portal del SRI), aaaa-mm-dd o dd-mm-aaaa → ISO; si no se entiende, el texto tal cual."""
    texto = (texto or '').strip()[:25]
    m = re.match(r'^(\d{1,2})[/-](\d{1,2})[/-](\d{4})', texto)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return texto
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', texto)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return texto
    return texto


def _importe_texto(texto):
    """'1.234,56' o '1234.56' → '1234.56'; si no es un importe, el texto tal cual (nunca se calcula nada con él)."""
    texto = (texto or '').strip().replace('$', '').replace(' ', '')
    if not texto:
        return ''
    candidato = texto
    if ',' in candidato and '.' in candidato:
        candidato = candidato.replace('.', '').replace(',', '.') if candidato.rfind(',') > candidato.rfind('.') else candidato.replace(',', '')
    elif ',' in candidato:
        candidato = candidato.replace(',', '.')
    try:
        return f'{Decimal(candidato):.2f}'
    except InvalidOperation:
        return texto[:30]


def _tipo_texto(texto):
    codigo = normalizar_encabezado(texto)
    if re.fullmatch(r'0?[1-7]', codigo):
        return codigo.zfill(2)
    return TIPOS_TEXTO.get(codigo, texto.strip()[:60])


def clave_en_texto(texto):
    """(clave, error) de un fragmento de texto: la única clave de 49 dígitos (admite espacios o guiones intercalados) o el
    motivo por el que no hay una: alterada por hoja de cálculo, longitud distinta, varias claves o ninguna."""
    texto = (texto or '').strip()
    if not texto:
        return '', ('sin_clave', 'Fila vacía.')
    compacto = re.sub(r'[\s\-]', '', texto)
    if re.fullmatch(r'\d{49}', compacto):
        return compacto, None
    if CIENTIFICA.match(compacto):
        return '', ('clave_alterada', 'La clave llegó como número en notación científica (la hoja de cálculo la alteró): exporta la '
                                      'columna como texto o copia la clave del comprobante.')
    encontradas = []
    for run in clave_acceso.PATRON.findall(texto):
        if run not in encontradas:
            encontradas.append(run)
    if len(encontradas) == 1:
        return encontradas[0], None
    if len(encontradas) > 1:
        return '', ('varias_claves', f'La fila trae {len(encontradas)} claves distintas: una por fila.')
    largo = DIGITOS_LARGOS.search(compacto)
    if largo:
        return '', ('longitud', f'Se leyeron {len(largo.group(0))} dígitos y la clave de acceso tiene 49.')
    if re.fullmatch(r'\d+', compacto):
        return '', ('longitud', f'Se leyeron {len(compacto)} dígitos y la clave de acceso tiene 49.')
    return '', ('sin_clave', 'No hay una clave de acceso de 49 dígitos en la fila.')


def validar(fila):
    """Formato de la clave (dígito verificador, fecha, ambiente): el resto (tipo soportado, empresa) lo decide servicios."""
    if fila.errores or not fila.clave:
        return
    try:
        clave_acceso.analizar(fila.clave)
    except clave_acceso.ClaveInvalida as e:
        fila.error('clave_invalida', str(e))


# ------------------------------------------------------------------ texto pegado

def filas_de_texto(texto):
    """Una clave por línea (o varias separadas por espacios, comas o punto y coma). Las líneas sin dígitos se omiten (títulos,
    comentarios); las que traen dígitos pero no una clave válida quedan como filas rechazadas, con su motivo."""
    if texto is None or len(texto) > limites.MAX_TEXTO_CLAVES:
        raise ListaInvalida(f'Pega como máximo {limites.MAX_TEXTO_CLAVES:,} caracteres por vez.'.replace(',', '.'))
    filas, omitidas, orden = [], 0, 0
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        if not re.search(r'\d', linea):
            omitidas += 1
            continue
        fragmentos = [t for t in re.split(r'[,;|\t]+|\s{2,}', linea) if t.strip()]
        if len(fragmentos) > 1 and sum(1 for f in fragmentos if clave_acceso.PATRON.search(re.sub(r'[\s\-]', '', f))) > 1:
            piezas = fragmentos                      # varias claves en la misma línea, separadas
        else:
            piezas = [linea]
        for pieza in piezas:
            fila = Fila(orden=orden, texto=pieza[:MAX_TEXTO_FILA])
            fila.clave, error = clave_en_texto(pieza)
            if error:
                fila.error(*error)
            validar(fila)
            filas.append(fila)
            orden += 1
            if len(filas) > limites.MAX_CLAVES_POR_LOTE:
                raise ListaInvalida(f'Un lote admite hasta {limites.MAX_CLAVES_POR_LOTE} claves: divide la lista.')
    return Lista(filas=filas, formato='texto', omitidas=omitidas)


# ------------------------------------------------------------------ reporte del portal del SRI (TXT, CSV o XLSX)

def _decodificar(datos):
    for codificacion in ('utf-8-sig', 'utf-16'):
        try:
            texto = datos.decode(codificacion)
            if codificacion == 'utf-16' and not datos.startswith((b'\xff\xfe', b'\xfe\xff')):
                raise UnicodeDecodeError('utf-16', b'', 0, 1, 'sin BOM')
            return texto
        except UnicodeDecodeError:
            continue
    return datos.decode('cp1252', errors='replace')


def _separador(linea):
    cuentas = {sep: linea.count(sep) for sep in ('\t', ';', '|', ',')}
    return max(cuentas, key=cuentas.get) if max(cuentas.values()) else '\t'


def _filas_xlsx(datos):
    import openpyxl
    try:
        libro = openpyxl.load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    except Exception:   # archivo corrupto o cifrado: openpyxl lanza distintas excepciones
        raise ListaInvalida('No se pudo leer el archivo XLSX (¿está dañado o protegido con contraseña?).')
    hoja = libro.worksheets[0]
    filas = []
    for fila in hoja.iter_rows(values_only=False):
        celdas = []
        for celda in fila:
            valor = celda.value
            texto = _texto_celda(valor)
            celdas.append((texto, isinstance(valor, (int, float)) and not isinstance(valor, bool)))
        filas.append(celdas)
        if len(filas) > limites.MAX_CLAVES_POR_LOTE + 50:
            break
    libro.close()
    return filas


def _filas_texto_tabulado(datos):
    texto = _decodificar(datos)
    lineas = [l for l in texto.splitlines() if l.strip()]
    if not lineas:
        return [], 'txt'
    separador = _separador(lineas[0])
    lector = csv.reader(io.StringIO('\n'.join(lineas)), delimiter=separador, quotechar='"')
    filas = [[(c.strip(), False) for c in fila] for fila in lector]
    return filas, ('csv' if separador in (';', ',') else 'txt')


def _encabezados(primera):
    """{indice: dato} de la primera fila si parece un encabezado del reporte; {} si no (sin fila de títulos)."""
    mapa, desconocidas = {}, []
    for i, (texto, _) in enumerate(primera):
        dato = COLUMNAS.get(normalizar_encabezado(texto))
        if dato and dato not in mapa.values():
            mapa[i] = dato
        elif texto:
            desconocidas.append(texto[:40])
    if 'clave' not in mapa.values():
        return {}, []
    return mapa, desconocidas


def filas_de_reporte(nombre, datos):
    """Filas del reporte exportado del portal del SRI. Formato por el contenido (no por la extensión): XLSX (openpyxl, celdas
    como texto), o texto separado por tabuladores, punto y coma, barra o coma. Con encabezado reconocido toma la columna de la
    clave y las que orientan; sin encabezado busca la clave de 49 dígitos en cada fila."""
    if len(datos) > limites.MAX_REPORTE_BYTES:
        raise ListaInvalida(f'El reporte supera {limites.MAX_REPORTE_BYTES // limites.MB} MB.')
    cuerpo = datos.lstrip(b'\xef\xbb\xbf\x00\t\r\n ')
    if cuerpo.startswith(b'PK\x03\x04'):
        filas, formato = _filas_xlsx(datos), 'xlsx'
    elif cuerpo.startswith(b'\xd0\xcf\x11\xe0'):
        raise ListaInvalida('El archivo es un XLS antiguo: guárdalo como XLSX o descarga el reporte en TXT.')
    elif cuerpo.startswith((b'%PDF-', b'<')):
        raise ListaInvalida('Ese archivo no es el reporte del portal (TXT, CSV o XLSX): los XML y PDF se importan en «Nueva importación».')
    else:
        filas, formato = _filas_texto_tabulado(datos)
    filas = [f for f in filas if any(texto for texto, _ in f)]
    if not filas:
        raise ListaInvalida('El reporte está vacío.')
    mapa, desconocidas = _encabezados(filas[0])
    cuerpo_filas = filas[1:] if mapa else filas
    if len(cuerpo_filas) > limites.MAX_CLAVES_POR_LOTE:
        raise ListaInvalida(f'El reporte tiene {len(cuerpo_filas)} filas y un lote admite {limites.MAX_CLAVES_POR_LOTE}: '
                            'descárgalo por períodos más cortos.')
    lista = Lista(filas=[], formato=formato, desconocidas=desconocidas,
                  columnas={dato: filas[0][i][0] for i, dato in mapa.items()} if mapa else {})
    indice_clave = next((i for i, d in mapa.items() if d == 'clave'), None)
    for orden, celdas in enumerate(cuerpo_filas):
        fila = Fila(orden=orden, texto=' | '.join(t for t, _ in celdas if t)[:MAX_TEXTO_FILA])
        if indice_clave is not None:
            texto, numerica = celdas[indice_clave] if indice_clave < len(celdas) else ('', False)
            if numerica:
                fila.error('clave_alterada', 'La celda de la clave es numérica: la hoja de cálculo la alteró. Exporta la columna como '
                                             'texto o descarga el reporte en TXT.')
            else:
                fila.clave, error = clave_en_texto(texto)
                if error:
                    fila.error(*error)
            for i, dato in mapa.items():
                if dato == 'clave' or i >= len(celdas):
                    continue
                texto, numerica = celdas[i]
                if not texto:
                    continue
                if dato in FECHAS:
                    texto = _fecha_texto(texto)
                elif dato in IMPORTES:
                    texto = _importe_texto(texto)
                elif dato == 'tipo_comprobante':
                    texto = _tipo_texto(texto)
                elif dato in ('emisor_ruc', 'receptor_identificacion') and numerica:
                    fila.advertencia('identificacion_alterada', f'La columna «{TEXTO_COLUMNAS[dato]}» es numérica en la hoja: pudo '
                                                                'perder ceros a la izquierda; se usa la del comprobante.')
                fila.sugerencias[dato] = texto[:300]
        else:
            fila.clave, error = clave_en_texto(fila.texto)
            if error:
                fila.error(*error)
        validar(fila)
        if fila.clave and fila.sugerencias.get('emisor_ruc') and fila.sugerencias['emisor_ruc'] != fila.clave[10:23]:
            if not any(a['codigo'] == 'identificacion_alterada' for a in fila.advertencias):
                fila.advertencia('ruc_no_coincide', 'El RUC del emisor del reporte no coincide con el de la clave; manda la clave.')
        lista.filas.append(fila)
    lista.omitidas = len(filas) - 1 - len(cuerpo_filas) if mapa else 0
    return lista


# ------------------------------------------------------------------ comparación con el XML autorizado

def comparar_con_documento(sugerencias, documento):
    """{'coincide': bool, 'diferencias': [dato]} entre lo que decía el reporte y el XML autorizado (solo informa)."""
    diferencias = []
    if not sugerencias:
        return {'coincide': True, 'diferencias': []}
    ruc = sugerencias.get('emisor_ruc')
    if ruc and ruc != documento.emisor_ruc:
        diferencias.append('emisor_ruc')
    fecha = sugerencias.get('fecha_emision')
    if fecha and documento.fecha_emision and fecha != documento.fecha_emision.isoformat():
        diferencias.append('fecha_emision')
    for dato in IMPORTES:
        texto = sugerencias.get(dato)
        if not texto:
            continue
        try:
            if abs(Decimal(texto) - Decimal(getattr(documento, dato))) > Decimal('0.01'):
                diferencias.append(dato)
        except InvalidOperation:
            diferencias.append(dato)
    numero = re.sub(r'\D', '', sugerencias.get('numero') or '')
    if numero and numero != documento.numero.replace('-', ''):
        diferencias.append('numero')
    tipo = sugerencias.get('tipo_comprobante')
    if tipo and re.fullmatch(r'\d{2}', tipo) and tipo != documento.cod_doc:
        diferencias.append('tipo_comprobante')
    return {'coincide': not diferencias, 'diferencias': diferencias}
