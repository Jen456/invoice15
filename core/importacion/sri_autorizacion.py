"""Consulta de autorización al SRI para recuperar el XML de una clave (servicio AutorizacionComprobantesOffline).

Operación SOAP autorizacionComprobante(claveAccesoComprobante) del WSDL del ambiente que indica la propia clave
(dígito 24: 1 = pruebas, 2 = producción); el WSDL describe el servicio, no es una descarga. Reutiliza el cliente de la
emisión (core/pos/emision.py: _cliente y URL_SRI).

Solo tres respuestas del SRI son concluyentes: AUTORIZADO con el comprobante (`autorizado`), NO AUTORIZADO en todas las
autorizaciones devueltas (`no_autorizado`) y ningún comprobante con esa clave, con numeroComprobantes = 0
(`sin_resultados`). EN PROCESO (`en_proceso`) todavía no es un resultado. Todo lo demás es una consulta fallida
(`no_disponible`, con `motivo`): sin respuesta, error SOAP o HTTP, respuesta inesperada. El rechazo de la CONSULTA por
la fecha de emisión (RECHAZADA, «fecha fuera del rango») es `fuera_de_rango`: el SRI no se pronunció sobre el
comprobante. Ninguna consulta fallida se presenta como un rechazo del comprobante
(entregas/facturaporaqui/primera-entrega/verificar-sri.md).
"""
import socket
import time
import urllib.error
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from django.utils import timezone

from core.importacion import clave_acceso, limites

PAUSA_REINTENTO = 1.0
AUTORIZADOS = {'AUTORIZADO', 'AUT'}
NO_AUTORIZADOS = {'NO AUTORIZADO', 'NO AUTORIZADA', 'NAT'}
EN_PROCESO = {'EN PROCESO', 'EN PROCESAMIENTO', 'POR PROCESAR', 'PPR'}
# Motivo de una consulta fallida (estado no_disponible): lo que se muestra como «no se pudo verificar».
MOTIVOS_FALLO = {
    'tiempo_agotado': 'el SRI no respondió a tiempo (tiempo de espera agotado)',
    'sin_conexion': 'no se pudo conectar con el SRI (error de red)',
    'servicio_no_disponible': 'el servicio del SRI no está disponible (error HTTP)',
    'error_sri': 'el servicio del SRI devolvió un error (SOAP)',
    'respuesta_inesperada': 'el SRI devolvió una respuesta inesperada o no concluyente',
}


@dataclass
class ResultadoConsulta:
    estado: str
    # autorizado | no_autorizado | sin_resultados (concluyentes) · en_proceso · no_disponible | fuera_de_rango |
    # clave_invalida (no se pudo consultar)
    clave: str
    xml: bytes | None = None          # <autorizacion> reconstruida con la respuesta, para procesar_xml_sri
    mensajes: list = field(default_factory=list)
    intentos: int = 0
    estados_sri: list = field(default_factory=list)
    motivo: str = ''                  # con no_disponible: una clave de MOTIVOS_FALLO


def _lista(valor):
    if valor is None:
        return []
    return list(valor) if isinstance(valor, (list, tuple)) else [valor]


def _sobre(aut, clave):
    fecha = getattr(aut, 'fechaAutorizacion', None)
    if hasattr(fecha, 'isoformat'):
        fecha = (timezone.localtime(fecha) if timezone.is_aware(fecha) else fecha).isoformat()
    partes = [('estado', 'AUTORIZADO'), ('numeroAutorizacion', getattr(aut, 'numeroAutorizacion', '') or clave),
              ('fechaAutorizacion', fecha or ''), ('ambiente', getattr(aut, 'ambiente', '') or '')]
    cuerpo = ''.join(f'<{k}>{escape(str(v))}</{k}>' for k, v in partes)
    comprobante = escape(str(getattr(aut, 'comprobante', '') or ''))
    return f'<?xml version="1.0" encoding="UTF-8"?><autorizacion>{cuerpo}<comprobante>{comprobante}</comprobante></autorizacion>'.encode()


def _estado(autorizacion):
    return ' '.join(str(getattr(autorizacion, 'estado', '') or '').upper().split())


def motivo_de_excepcion(error):
    """Motivo (MOTIVOS_FALLO) de una excepción del cliente SOAP: suds usa urllib, así que el tiempo agotado llega como
    TimeoutError (socket.timeout) o como URLError cuya razón es un TimeoutError."""
    try:
        from suds import WebFault
        from suds.transport import TransportError
    except ImportError:   # pragma: no cover - suds está en requirements
        WebFault = TransportError = ()
    if WebFault and isinstance(error, WebFault):
        return 'error_sri'
    if TransportError and isinstance(error, TransportError):
        return 'servicio_no_disponible'
    if isinstance(error, (TimeoutError, socket.timeout)):
        return 'tiempo_agotado'
    if isinstance(error, urllib.error.URLError):
        return 'tiempo_agotado' if isinstance(error.reason, (TimeoutError, socket.timeout)) else 'sin_conexion'
    if isinstance(error, (ConnectionError, OSError)):
        return 'sin_conexion'
    return 'respuesta_inesperada'


def _no_concluyente(resultado, texto):
    resultado.estado, resultado.motivo = 'no_disponible', 'respuesta_inesperada'
    resultado.mensajes.append(texto)
    return resultado


def _interpretar(respuesta, resultado):
    clave_consultada = str(getattr(respuesta, 'claveAccesoConsultada', '') or '').strip()
    if clave_consultada and clave_consultada != resultado.clave:
        return _no_concluyente(resultado, 'El SRI devolvió una clave distinta de la consultada.')

    autorizaciones = _lista(getattr(getattr(respuesta, 'autorizaciones', None), 'autorizacion', None))
    if not autorizaciones:
        cantidad = str(getattr(respuesta, 'numeroComprobantes', '')).strip()
        if cantidad == '0':
            resultado.estado, resultado.motivo = 'sin_resultados', ''
            resultado.mensajes = ['El SRI no encontró un comprobante con esa clave.']
            return resultado
        return _no_concluyente(resultado, 'El SRI devolvió una respuesta sin un resultado de autorización.')

    estados = [_estado(autorizacion) for autorizacion in autorizaciones]
    resultado.estados_sri = list(dict.fromkeys(estado[:60] for estado in estados))[:8]
    for autorizacion, estado in zip(autorizaciones, estados):
        if estado in AUTORIZADOS and str(getattr(autorizacion, 'comprobante', '') or '').strip():
            resultado.estado, resultado.motivo = 'autorizado', ''
            resultado.xml = _sobre(autorizacion, resultado.clave)
            resultado.mensajes = []
            return resultado

    if any(estado in AUTORIZADOS for estado in estados):
        return _no_concluyente(resultado, 'El SRI indicó autorización sin devolver el XML para compararlo.')

    mensajes = [m for autorizacion in autorizaciones
                for m in _lista(getattr(getattr(autorizacion, 'mensajes', None), 'mensaje', None))]
    for mensaje in mensajes[:8]:
        identificador = str(getattr(mensaje, 'identificador', '') or '')[:12]
        texto = str(getattr(mensaje, 'mensaje', '') or '')[:180]
        adicional = str(getattr(mensaje, 'informacionAdicional', '') or '')[:180].strip().rstrip('.')
        if identificador or texto:
            resultado.mensajes.append((f'[{identificador}] {texto}'.strip() + (f' ({adicional})' if adicional else '')))
    # Se identifica por el detalle, porque el SRI usa códigos diferentes según el servicio (80 y 99 observados).
    for mensaje in mensajes:
        detalle = ' '.join(' '.join(str(getattr(mensaje, campo, '') or '') for campo in ('informacionAdicional', 'mensaje'))
                           .upper().split())
        if 'FECHA' in detalle and 'FUERA DEL RANGO' in detalle:
            resultado.estado, resultado.motivo = 'fuera_de_rango', ''
            resultado.mensajes.append('La fecha de emisión está fuera del rango de la consulta automática.')
            return resultado

    if any(estado in EN_PROCESO for estado in estados):
        resultado.estado, resultado.motivo = 'en_proceso', ''
        resultado.mensajes.append('El SRI todavía está procesando el comprobante.')
    elif all(estado in NO_AUTORIZADOS for estado in estados):
        resultado.estado, resultado.motivo = 'no_autorizado', ''
    else:   # p. ej. RECHAZADA sin otro detalle, vacío o un estado nuevo: no es un rechazo del comprobante
        _no_concluyente(resultado, 'El SRI no devolvió un estado de autorización concluyente.')
    return resultado


def consultar_autorizacion(clave):
    from core.pos import emision
    try:
        datos = clave_acceso.analizar(clave)
    except clave_acceso.ClaveInvalida as e:
        return ResultadoConsulta('clave_invalida', clave, mensajes=[str(e)])
    url = emision.URL_SRI[datos.ambiente] + 'AutorizacionComprobantesOffline?wsdl'
    resultado = ResultadoConsulta('no_disponible', clave, motivo='sin_conexion')
    respuesta = None
    for intento in range(1 + limites.SRI_REINTENTOS):
        resultado.intentos = intento + 1
        try:
            respuesta = emision._cliente(url, limites.SRI_TIEMPO_SEGUNDOS).service.autorizacionComprobante(clave)
            break
        except Exception as e:   # red, tiempo, error SOAP o respuesta inválida: se reintenta pocas veces
            resultado.motivo = motivo_de_excepcion(e)
            detalle = ' '.join(str(e).split())[:120]
            resultado.mensajes.append(f'Intento {intento + 1}: {e.__class__.__name__}' + (f' ({detalle})' if detalle else ''))
            if intento < limites.SRI_REINTENTOS:
                time.sleep(PAUSA_REINTENTO)
    if respuesta is not None:
        return _interpretar(respuesta, resultado)
    return resultado
