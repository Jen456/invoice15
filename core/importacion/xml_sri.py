"""Ingesta segura de XML de comprobantes electrónicos del SRI: procesar_xml_sri(datos) → ResultadoXml.

- Tamaño limitado y contenido real (no se confía en la extensión ni en el MIME).
- Sin DTD, sin entidades, sin red, con límites de elementos, profundidad y anidamiento.
- Envolturas admitidas: <autorizacion> suelta; <RespuestaAutorizacionComprobante> (con o sin sobre SOAP) con una o varias
  <autorizacion>; y el comprobante solo (sin autorización declarada). El comprobante puede venir en CDATA, como texto
  escapado o como elemento hijo. Los espacios de nombres se ignoran (se comparan nombres locales).
- Solo se acepta como autorizado lo que declara estado AUTORIZADO. Eso es lo que DICE el archivo: no prueba autenticidad.
  La verificación contra el SRI es otro paso (sri_autorizacion.py) y se registra aparte.
- Primera entrega: facturas (01). Otros tipos se informan como «tipo no soportado» y no se interpretan como facturas.
- Todo importe es Decimal; to_dict() los serializa como texto.
"""
import hashlib
import html
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.utils import timezone
from lxml import etree

from core.importacion import clave_acceso, limites

CENTAVO = Decimal('0.01')
TOLERANCIA = Decimal('0.02')
COMPROBANTES = {'factura': '01', 'liquidacionCompra': '03', 'notaCredito': '04', 'notaDebito': '05', 'guiaRemision': '06',
                'comprobanteRetencion': '07'}
NOMBRES = {'01': 'Factura', '03': 'Liquidación de compra', '04': 'Nota de crédito', '05': 'Nota de débito',
           '06': 'Guía de remisión', '07': 'Comprobante de retención'}
SOPORTADOS = ('01',)
TIPOS_IDENTIFICACION = {'04': 'RUC', '05': 'Cédula', '06': 'Pasaporte', '07': 'Consumidor final', '08': 'Identificación del exterior'}
# Tabla 17 de la ficha (IVA): código de porcentaje → (categoría, tarifa conocida)
IVA = {'0': ('iva_0', Decimal('0')), '2': ('iva_tarifa', Decimal('12')), '3': ('iva_tarifa', Decimal('14')),
       '4': ('iva_tarifa', Decimal('15')), '5': ('iva_tarifa', Decimal('5')), '6': ('iva_no_objeto', None),
       '7': ('iva_exento', None), '8': ('iva_diferenciado', None), '10': ('iva_tarifa', Decimal('13'))}
IMPUESTOS = {'2': 'IVA', '3': 'ICE', '5': 'IRBPNR'}


@dataclass
class Mensaje:
    codigo: str
    texto: str


@dataclass
class ImpuestoXml:
    codigo: str
    codigo_porcentaje: str
    impuesto: str
    categoria: str
    tarifa: Decimal | None
    base_imponible: Decimal
    valor: Decimal
    descuento_adicional: Decimal = Decimal('0.00')
    valor_devolucion_iva: Decimal | None = None


@dataclass
class BaseTarifa:
    categoria: str
    tarifa: Decimal | None
    base_imponible: Decimal
    valor: Decimal


@dataclass
class DatosComprobante:
    clave_acceso: str
    cod_doc: str
    tipo_documento: str
    version: str
    ambiente: int
    tipo_emision: str
    estab: str
    pto_emi: str
    secuencial: str
    numero: str
    fecha_emision: date
    emisor_ruc: str
    emisor_razon_social: str
    emisor_nombre_comercial: str = ''
    dir_matriz: str = ''
    dir_establecimiento: str = ''
    obligado_contabilidad: str = ''
    contribuyente_especial: str = ''
    receptor_tipo_identificacion: str = ''
    receptor_tipo_nombre: str = ''
    receptor_identificacion: str = ''
    receptor_razon_social: str = ''
    receptor_direccion: str = ''
    moneda: str = ''
    total_sin_impuestos: Decimal = Decimal('0.00')
    total_descuento: Decimal = Decimal('0.00')
    propina: Decimal = Decimal('0.00')
    importe_total: Decimal = Decimal('0.00')
    total_iva: Decimal = Decimal('0.00')
    total_ice: Decimal = Decimal('0.00')
    total_irbpnr: Decimal = Decimal('0.00')
    impuestos: list = field(default_factory=list)
    bases_por_tarifa: list = field(default_factory=list)
    pagos: list = field(default_factory=list)
    lineas: int = 0
    info_adicional: dict = field(default_factory=dict)


@dataclass
class ResultadoXml:
    aceptado: bool
    sha256: str
    tamano: int
    envoltura: str = ''
    autorizacion_declarada: str | None = None      # AUTORIZADO / NO AUTORIZADO / None (el archivo no trae autorización)
    numero_autorizacion: str = ''
    fecha_autorizacion: datetime | None = None
    ambiente_autorizacion: str = ''
    verificacion: str = 'sin_autorizacion'         # declarada_en_archivo | sin_autorizacion (nunca «verificada» desde el archivo)
    tipo_soportado: bool = False
    comprobante: DatosComprobante | None = None
    errores: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)
    xml_comprobante: str = ''

    def error(self, codigo, texto):
        self.errores.append(Mensaje(codigo, texto))
        self.aceptado = False
        return self

    def aviso(self, codigo, texto):
        self.advertencias.append(Mensaje(codigo, texto))

    def to_dict(self):
        datos = _serializable(asdict(self))
        datos.pop('xml_comprobante', None)
        return datos


def _serializable(valor):
    if isinstance(valor, Decimal):
        return format(valor, 'f')
    if isinstance(valor, datetime):
        return valor.isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {k: _serializable(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_serializable(v) for v in valor]
    return valor


class _Rechazo(Exception):
    def __init__(self, codigo, texto):
        super().__init__(texto)
        self.codigo, self.texto = codigo, texto


# ------------------------------------------------------------------ análisis seguro

_PARSER = dict(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False, huge_tree=False,
               remove_comments=True, remove_pis=True, collect_ids=False)
_PELIGROSOS = re.compile(rb'<!\s*(DOCTYPE|ENTITY|ELEMENT|ATTLIST|NOTATION)', re.IGNORECASE)


def _analizar(datos):
    """Árbol XML de `datos` (bytes) o _Rechazo. No resuelve nada externo ni acepta declaraciones de tipo."""
    if datos[:2] in (b'\xff\xfe', b'\xfe\xff') or datos[:4] in (b'\x00\x00\xfe\xff', b'\xff\xfe\x00\x00') or b'\x00' in datos[:200]:
        raise _Rechazo('codificacion', 'El XML debe estar en UTF-8 (o una codificación compatible con ASCII).')
    if _PELIGROSOS.search(datos):
        raise _Rechazo('dtd_prohibida', 'El XML contiene una declaración DOCTYPE o ENTITY: se rechaza por seguridad.')
    try:
        raiz = etree.fromstring(datos, etree.XMLParser(**_PARSER))
    except etree.XMLSyntaxError as e:
        raise _Rechazo('xml_malformado', f'El archivo no es un XML válido ({str(e)[:120]}).')
    arbol = raiz.getroottree()
    if arbol.docinfo.doctype or arbol.docinfo.internalDTD is not None:
        raise _Rechazo('dtd_prohibida', 'El XML contiene una declaración DOCTYPE: se rechaza por seguridad.')
    total = 0
    for elemento in raiz.iter():
        total += 1
        if total > limites.MAX_ELEMENTOS_XML:
            raise _Rechazo('xml_excesivo', f'El XML tiene más de {limites.MAX_ELEMENTOS_XML} elementos.')
        if isinstance(elemento, etree._Entity) or (isinstance(elemento.tag, str) and elemento.tag == etree.Entity):
            raise _Rechazo('dtd_prohibida', 'El XML contiene entidades: se rechaza por seguridad.')
    if _profundidad(raiz) > limites.MAX_PROFUNDIDAD_XML:
        raise _Rechazo('xml_excesivo', f'El XML tiene más de {limites.MAX_PROFUNDIDAD_XML} niveles de anidamiento.')
    return raiz


def _profundidad(raiz):
    maxima, pila = 0, [(raiz, 1)]
    while pila:
        nodo, nivel = pila.pop()
        maxima = max(maxima, nivel)
        if maxima > limites.MAX_PROFUNDIDAD_XML:
            return maxima
        pila.extend((h, nivel + 1) for h in nodo if isinstance(h.tag, str))
    return maxima


def _local(elemento):
    return etree.QName(elemento).localname if isinstance(elemento.tag, str) else ''


def _hijo(elemento, nombre):
    if elemento is None:
        return None
    for h in elemento:
        if _local(h) == nombre:
            return h
    return None


def _hijos(elemento, nombre):
    return [h for h in (elemento if elemento is not None else []) if _local(h) == nombre]


def _ruta(elemento, ruta):
    for parte in ruta.split('/'):
        elemento = _hijo(elemento, parte)
        if elemento is None:
            return None
    return elemento


def _texto(elemento, ruta=None):
    nodo = _ruta(elemento, ruta) if ruta else elemento
    return ' '.join((nodo.text or '').split()) if nodo is not None else ''


def _buscar(elemento, nombre):
    """Primer descendiente con ese nombre local (para sobres SOAP)."""
    for nodo in elemento.iter():
        if _local(nodo) == nombre:
            return nodo
    return None


# ------------------------------------------------------------------ montos y fechas

def _decimal(resultado, texto, campo, obligatorio=True):
    texto = (texto or '').strip().replace(',', '.') if texto else ''
    if not texto:
        if obligatorio:
            resultado.error('importe_faltante', f'Falta el valor de «{campo}».')
        return Decimal('0.00')
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        resultado.error('importe_invalido', f'El valor de «{campo}» no es un número ({texto[:20]}).')
        return Decimal('0.00')
    if not valor.is_finite() or valor < 0:
        resultado.error('importe_invalido', f'El valor de «{campo}» debe ser un número positivo.')
        return Decimal('0.00')
    return valor


def _redondear(valor):
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _fecha(texto):
    try:
        return datetime.strptime(texto.strip(), '%d/%m/%Y').date()
    except (ValueError, AttributeError):
        return None


def _fecha_hora(texto):
    texto = (texto or '').strip()
    if not texto:
        return None
    for formato in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y'):
        try:
            return timezone.make_aware(datetime.strptime(texto, formato))
        except ValueError:
            pass
    try:
        valor = datetime.fromisoformat(texto.replace('Z', '+00:00'))
    except ValueError:
        return None
    return valor if timezone.is_aware(valor) else timezone.make_aware(valor)


# ------------------------------------------------------------------ envolturas

def _comprobante_interno(resultado, nodo_comprobante, nivel):
    """Elemento raíz del comprobante contenido en <comprobante> (CDATA, texto escapado o elemento hijo)."""
    hijos = [h for h in nodo_comprobante if isinstance(h.tag, str)]
    if hijos:
        resultado.xml_comprobante = etree.tostring(hijos[0], encoding='unicode')
        return hijos[0]
    texto = (nodo_comprobante.text or '').strip()
    if texto.startswith('&lt;'):
        texto = html.unescape(texto)   # escapado dos veces por el sistema de origen: se deshace una sola vez
    if not texto.startswith('<'):
        raise _Rechazo('comprobante_vacio', 'La autorización no contiene el comprobante.')
    if nivel >= limites.MAX_ANIDAMIENTOS_CDATA:
        raise _Rechazo('xml_excesivo', 'El comprobante está anidado demasiadas veces.')
    texto = re.sub(r'^\s*<\?xml[^>]*\?>', '', texto)   # la declaración interna (y su codificación) ya no aplica: es texto
    resultado.xml_comprobante = texto
    return _analizar(texto.encode('utf-8'))


def _autorizacion(resultado, nodo, nivel=1):
    estado = _texto(nodo, 'estado').upper()
    resultado.autorizacion_declarada = estado or None
    resultado.numero_autorizacion = _texto(nodo, 'numeroAutorizacion')
    resultado.fecha_autorizacion = _fecha_hora(_texto(nodo, 'fechaAutorizacion'))
    resultado.ambiente_autorizacion = _texto(nodo, 'ambiente')
    if estado != 'AUTORIZADO':
        detalle = '; '.join(filter(None, (f'[{_texto(m, "identificador")}] {_texto(m, "mensaje")}'.strip()
                                          for m in _hijos(_hijo(nodo, 'mensajes'), 'mensaje'))))
        raise _Rechazo('no_autorizado', f'El archivo declara el estado «{estado or "sin estado"}», no AUTORIZADO.'
                       + (f' Mensajes: {detalle}' if detalle else ''))
    resultado.verificacion = 'declarada_en_archivo'
    comprobante = _hijo(nodo, 'comprobante')
    if comprobante is None:
        raise _Rechazo('comprobante_vacio', 'La autorización no contiene el comprobante.')
    return _comprobante_interno(resultado, comprobante, nivel)


def _desenvolver(resultado, raiz):
    """Elemento raíz del comprobante según la envoltura del archivo."""
    nombre = _local(raiz)
    if nombre in COMPROBANTES:
        resultado.envoltura = 'comprobante'
        resultado.xml_comprobante = etree.tostring(raiz, encoding='unicode')
        resultado.aviso('sin_autorizacion', 'El archivo trae el comprobante sin la autorización del SRI: hay que verificarlo en el SRI.')
        return raiz
    if nombre == 'autorizacion':
        resultado.envoltura = 'autorizacion'
        return _autorizacion(resultado, raiz)
    respuesta = None
    if nombre == 'RespuestaAutorizacionComprobante':
        respuesta = raiz
    elif nombre == 'Envelope':   # sobre SOAP: la respuesta (o al menos sus autorizaciones) va dentro del Body
        respuesta = _buscar(raiz, 'RespuestaAutorizacionComprobante')
        if respuesta is None and _buscar(raiz, 'autorizacion') is not None:
            respuesta = raiz
    if respuesta is not None:
        resultado.envoltura = 'soap' if nombre == 'Envelope' else 'respuesta_autorizacion'
        autorizaciones = [a for a in respuesta.iter() if _local(a) == 'autorizacion']
        if not autorizaciones:
            raise _Rechazo('sin_autorizaciones', 'La respuesta del SRI no contiene autorizaciones (el SRI no devolvió el comprobante).')
        autorizadas = [a for a in autorizaciones if _texto(a, 'estado').upper() == 'AUTORIZADO']
        if len(autorizadas) > 1 and len({_texto(a, 'numeroAutorizacion') for a in autorizadas}) > 1:
            raise _Rechazo('ambiguo', 'La respuesta contiene varias autorizaciones distintas: impórtalas por separado.')
        if len(autorizaciones) > 1:
            resultado.aviso('varias_autorizaciones', f'La respuesta trae {len(autorizaciones)} autorizaciones; se usa la AUTORIZADA.')
        return _autorizacion(resultado, autorizadas[0] if autorizadas else autorizaciones[0])
    raise _Rechazo('estructura_desconocida', 'El XML no es un comprobante electrónico ni una autorización del SRI.')


# ------------------------------------------------------------------ factura

def _impuestos(resultado, contenedor, nombre_nodo):
    impuestos = []
    for nodo in _hijos(contenedor, nombre_nodo):
        codigo, porcentaje = _texto(nodo, 'codigo'), _texto(nodo, 'codigoPorcentaje')
        base = _decimal(resultado, _texto(nodo, 'baseImponible'), 'baseImponible')
        valor = _decimal(resultado, _texto(nodo, 'valor'), 'valor')
        tarifa_xml = _texto(nodo, 'tarifa')
        tarifa = _decimal(resultado, tarifa_xml, 'tarifa', obligatorio=False) if tarifa_xml else None
        if codigo == '2':
            categoria, conocida = IVA.get(porcentaje, ('iva_desconocido', None))
            if categoria == 'iva_desconocido':
                resultado.aviso('iva_desconocido', f'Código de porcentaje de IVA {porcentaje!r} no reconocido: se conserva tal cual.')
            if tarifa is None:
                tarifa = conocida
            elif conocida is not None and tarifa != conocida:
                resultado.aviso('tarifa_incoherente', f'La tarifa {tarifa} no corresponde al código de porcentaje {porcentaje} ({conocida} %).')
            if categoria == 'iva_tarifa' and tarifa is not None and tarifa == 0:
                categoria = 'iva_0'
        else:
            categoria = {'3': 'ice', '5': 'irbpnr'}.get(codigo, 'otro')
        impuesto = ImpuestoXml(codigo=codigo, codigo_porcentaje=porcentaje, impuesto=IMPUESTOS.get(codigo, f'Código {codigo}'),
                               categoria=categoria, tarifa=tarifa, base_imponible=base, valor=valor,
                               descuento_adicional=_decimal(resultado, _texto(nodo, 'descuentoAdicional'), 'descuentoAdicional', False))
        devolucion = _texto(nodo, 'valorDevolucionIva')
        if devolucion:
            impuesto.valor_devolucion_iva = _decimal(resultado, devolucion, 'valorDevolucionIva', False)
        if codigo == '2' and tarifa and categoria == 'iva_tarifa':
            esperado = _redondear(base * tarifa / 100)
            if abs(esperado - valor) > TOLERANCIA:
                resultado.aviso('iva_descuadrado', f'IVA {tarifa} %: {valor} no coincide con {base} × {tarifa} % = {esperado}.')
        impuestos.append(impuesto)
    return impuestos


def _bases(impuestos):
    grupos = {}
    for i in impuestos:
        clave = (i.categoria, i.tarifa)
        base, valor = grupos.get(clave, (Decimal('0'), Decimal('0')))
        grupos[clave] = (base + i.base_imponible, valor + i.valor)
    orden = {'iva_tarifa': 0, 'iva_diferenciado': 1, 'iva_0': 2, 'iva_exento': 3, 'iva_no_objeto': 4, 'ice': 5, 'irbpnr': 6}
    return [BaseTarifa(categoria=c, tarifa=t, base_imponible=b, valor=v)
            for (c, t), (b, v) in sorted(grupos.items(), key=lambda x: (orden.get(x[0][0], 9), -(x[0][1] or 0)))]


def _validar_identificacion(resultado, tipo, numero):
    if tipo and tipo not in TIPOS_IDENTIFICACION:
        resultado.aviso('tipo_identificacion', f'Tipo de identificación del receptor {tipo!r} no reconocido.')
    reglas = {'04': (r'\d{13}', 'un RUC de 13 dígitos'), '05': (r'\d{10}', 'una cédula de 10 dígitos'),
              '07': (r'9{13}', '9999999999999 (consumidor final)')}
    if tipo in reglas and not re.fullmatch(reglas[tipo][0], numero or ''):
        resultado.aviso('identificacion_formato', f'La identificación del receptor no tiene el formato de {reglas[tipo][1]}.')


def _factura(resultado, raiz, cod_doc):
    tributaria, info = _hijo(raiz, 'infoTributaria'), _hijo(raiz, 'infoFactura')
    if tributaria is None or info is None:
        raise _Rechazo('estructura_invalida', 'La factura no tiene infoTributaria o infoFactura.')
    clave = _texto(tributaria, 'claveAcceso')
    fecha = _fecha(_texto(info, 'fechaEmision'))
    if fecha is None:
        resultado.error('fecha_invalida', 'La fecha de emisión no tiene el formato dd/mm/aaaa.')
    ambiente_txt = _texto(tributaria, 'ambiente')
    datos = DatosComprobante(
        clave_acceso=clave, cod_doc=cod_doc, tipo_documento=NOMBRES[cod_doc], version=raiz.get('version', ''),
        ambiente=int(ambiente_txt) if ambiente_txt in ('1', '2') else 0, tipo_emision=_texto(tributaria, 'tipoEmision'),
        estab=_texto(tributaria, 'estab'), pto_emi=_texto(tributaria, 'ptoEmi'), secuencial=_texto(tributaria, 'secuencial'),
        numero='', fecha_emision=fecha, emisor_ruc=_texto(tributaria, 'ruc'), emisor_razon_social=_texto(tributaria, 'razonSocial'),
        emisor_nombre_comercial=_texto(tributaria, 'nombreComercial'), dir_matriz=_texto(tributaria, 'dirMatriz'),
        dir_establecimiento=_texto(info, 'dirEstablecimiento'), obligado_contabilidad=_texto(info, 'obligadoContabilidad'),
        contribuyente_especial=_texto(info, 'contribuyenteEspecial'),
        receptor_tipo_identificacion=_texto(info, 'tipoIdentificacionComprador'),
        receptor_identificacion=_texto(info, 'identificacionComprador'), receptor_razon_social=_texto(info, 'razonSocialComprador'),
        receptor_direccion=_texto(info, 'direccionComprador'), moneda=_texto(info, 'moneda') or 'DOLAR')
    datos.numero = f'{datos.estab}-{datos.pto_emi}-{datos.secuencial}'
    datos.receptor_tipo_nombre = TIPOS_IDENTIFICACION.get(datos.receptor_tipo_identificacion, '')
    for campo, valor in (('ambiente', ambiente_txt), ('ruc', datos.emisor_ruc), ('razonSocial', datos.emisor_razon_social),
                         ('estab', datos.estab), ('ptoEmi', datos.pto_emi), ('secuencial', datos.secuencial),
                         ('identificacionComprador', datos.receptor_identificacion)):
        if not valor:
            resultado.error('campo_faltante', f'Falta «{campo}» en la factura.')
    if datos.emisor_ruc and not re.fullmatch(r'\d{13}', datos.emisor_ruc):
        resultado.error('ruc_emisor', 'El RUC del emisor debe tener 13 dígitos.')
    _validar_identificacion(resultado, datos.receptor_tipo_identificacion, datos.receptor_identificacion)
    datos.total_sin_impuestos = _decimal(resultado, _texto(info, 'totalSinImpuestos'), 'totalSinImpuestos')
    datos.total_descuento = _decimal(resultado, _texto(info, 'totalDescuento'), 'totalDescuento', False)
    datos.propina = _decimal(resultado, _texto(info, 'propina'), 'propina', False)
    datos.importe_total = _decimal(resultado, _texto(info, 'importeTotal'), 'importeTotal')
    datos.impuestos = _impuestos(resultado, _hijo(info, 'totalConImpuestos'), 'totalImpuesto')
    if not datos.impuestos:
        resultado.aviso('sin_impuestos', 'La factura no detalla impuestos (totalConImpuestos vacío).')
    datos.bases_por_tarifa = _bases(datos.impuestos)
    datos.total_iva = sum((i.valor for i in datos.impuestos if i.codigo == '2'), Decimal('0.00'))
    datos.total_ice = sum((i.valor for i in datos.impuestos if i.codigo == '3'), Decimal('0.00'))
    datos.total_irbpnr = sum((i.valor for i in datos.impuestos if i.codigo == '5'), Decimal('0.00'))
    datos.pagos = [{'forma_pago': _texto(p, 'formaPago'), 'total': _decimal(resultado, _texto(p, 'total'), 'pago', False),
                    'plazo': _texto(p, 'plazo'), 'unidad_tiempo': _texto(p, 'unidadTiempo')} for p in _hijos(_hijo(info, 'pagos'), 'pago')]
    detalles = _hijos(_hijo(raiz, 'detalles'), 'detalle')
    datos.lineas = len(detalles)
    datos.info_adicional = {c.get('nombre', '')[:100]: ' '.join((c.text or '').split())[:300]
                            for c in _hijos(_hijo(raiz, 'infoAdicional'), 'campoAdicional')}
    _conciliar(resultado, datos, info, detalles)
    _coherencia_clave(resultado, datos)
    return datos


def _conciliar(resultado, datos, info, detalles):
    bases_iva = sum((i.base_imponible for i in datos.impuestos if i.codigo == '2'), Decimal('0'))
    if datos.impuestos and abs(bases_iva - datos.total_sin_impuestos) > TOLERANCIA:
        resultado.aviso('bases_descuadradas', f'Las bases de IVA suman {bases_iva} y el total sin impuestos es {datos.total_sin_impuestos}.')
    compensaciones = sum((_decimal(resultado, _texto(c, 'valor'), 'compensación', False)
                          for c in _hijos(_hijo(info, 'compensaciones'), 'compensacion')), Decimal('0'))
    esperado = datos.total_sin_impuestos + sum((i.valor for i in datos.impuestos), Decimal('0')) + datos.propina - compensaciones
    if abs(esperado - datos.importe_total) > TOLERANCIA:
        resultado.aviso('total_descuadrado', f'El importe total {datos.importe_total} no coincide con bases + impuestos + propina = {esperado}.')
    pagado = sum((p['total'] for p in datos.pagos), Decimal('0'))
    if datos.pagos and abs(pagado - datos.importe_total) > TOLERANCIA:
        resultado.aviso('pagos_descuadrados', f'Los pagos suman {pagado} y el importe total es {datos.importe_total}.')
    if detalles:
        lineas = sum((_decimal(resultado, _texto(d, 'precioTotalSinImpuesto'), 'precioTotalSinImpuesto', False) for d in detalles), Decimal('0'))
        if abs(lineas - datos.total_sin_impuestos) > TOLERANCIA:
            resultado.aviso('lineas_descuadradas', f'Las líneas suman {lineas} y el total sin impuestos es {datos.total_sin_impuestos}.')


def _coherencia_clave(resultado, datos):
    try:
        clave = clave_acceso.analizar(datos.clave_acceso)
    except clave_acceso.ClaveInvalida as e:
        resultado.error('clave_invalida', str(e))
        return
    diferencias = [nombre for nombre, de_la_clave, del_xml in (
        ('fecha de emisión', clave.fecha_emision, datos.fecha_emision), ('tipo de comprobante', clave.cod_doc, datos.cod_doc),
        ('RUC del emisor', clave.ruc, datos.emisor_ruc), ('ambiente', clave.ambiente, datos.ambiente),
        ('establecimiento', clave.estab, datos.estab), ('punto de emisión', clave.pto_emi, datos.pto_emi),
        ('secuencial', clave.secuencial, datos.secuencial), ('tipo de emisión', clave.tipo_emision, datos.tipo_emision),
    ) if de_la_clave != del_xml]
    if diferencias:
        resultado.error('clave_incoherente', 'La clave de acceso no coincide con el comprobante en: ' + ', '.join(diferencias) + '.')
    if resultado.numero_autorizacion:
        if re.fullmatch(r'\d{49}', resultado.numero_autorizacion) and resultado.numero_autorizacion != datos.clave_acceso:
            resultado.error('autorizacion_incoherente', 'El número de autorización no coincide con la clave de acceso del comprobante.')
        elif not re.fullmatch(r'\d{49}', resultado.numero_autorizacion):
            resultado.aviso('autorizacion_antigua', 'El número de autorización no es una clave de 49 dígitos (esquema anterior).')
    ambiente_aut = resultado.ambiente_autorizacion.upper()
    if ambiente_aut and (('PRODUC' in ambiente_aut) != (datos.ambiente == 2)):
        resultado.aviso('ambiente_autorizacion', f'La autorización dice «{resultado.ambiente_autorizacion}» y el comprobante es del ambiente {datos.ambiente}.')


# ------------------------------------------------------------------ entrada pública

def procesar_xml_sri(datos):
    """Analiza los bytes de un XML del SRI. Nunca lanza por contenido del archivo: los problemas van en `errores`."""
    datos = bytes(datos or b'')
    resultado = ResultadoXml(aceptado=True, sha256=hashlib.sha256(datos).hexdigest(), tamano=len(datos))
    if not datos.strip():
        return resultado.error('vacio', 'El archivo está vacío.')
    if len(datos) > limites.MAX_XML_BYTES:
        return resultado.error('archivo_grande', f'El XML supera {limites.MAX_XML_BYTES // limites.MB} MB.')
    if datos[:2] in (b'\xff\xfe', b'\xfe\xff') or b'\x00' in datos[:200]:
        return resultado.error('codificacion', 'El XML debe estar en UTF-8 (o una codificación compatible con ASCII).')
    cuerpo = datos.lstrip(b'\xef\xbb\xbf \t\r\n')
    if not cuerpo.startswith(b'<'):
        return resultado.error('no_es_xml', 'El contenido no es XML (no empieza con «<»).')
    try:
        raiz = _desenvolver(resultado, _analizar(cuerpo))
        nombre = _local(raiz)
        cod_doc = COMPROBANTES.get(nombre)
        if cod_doc is None:
            raise _Rechazo('estructura_desconocida', f'«{nombre}» no es un comprobante electrónico del SRI.')
        cod_xml = _texto(raiz, 'infoTributaria/codDoc')
        if cod_xml and cod_xml != cod_doc:
            raise _Rechazo('estructura_invalida', f'El elemento «{nombre}» declara el código de documento {cod_xml}.')
        if cod_doc not in SOPORTADOS:
            resultado.comprobante = None
            resultado.tipo_soportado = False
            return resultado.error('tipo_no_soportado', f'{NOMBRES[cod_doc]} ({cod_doc}): tipo no soportado todavía. '
                                                         'Por ahora solo se importan facturas (01).')
        resultado.tipo_soportado = True
        resultado.comprobante = _factura(resultado, raiz, cod_doc)
    except _Rechazo as e:
        resultado.error(e.codigo, e.texto)
    if resultado.errores:
        resultado.aceptado = False
    return resultado


procesarXmlSri = procesar_xml_sri   # nombre pedido en el contrato
