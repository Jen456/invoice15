"""Consulta de autorización al SRI para recuperar el XML de una clave (servicio AutorizacionComprobantesOffline).

Operación SOAP autorizacionComprobante(claveAccesoComprobante) del WSDL del ambiente que indica la propia clave
(dígito 24: 1 = pruebas, 2 = producción); el WSDL describe el servicio, no es una descarga. Reutiliza el cliente de la
emisión (core/pos/emision.py: _cliente y URL_SRI). El servicio puede rechazar la consulta por su límite de fechas.
Ese resultado es distinto de un rechazo de autorización del comprobante.
"""
import time
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from django.utils import timezone

from core.importacion import clave_acceso, limites

PAUSA_REINTENTO = 1.0
AUTORIZADOS = {'AUTORIZADO', 'AUT'}
NO_AUTORIZADOS = {'NO AUTORIZADO', 'NO AUTORIZADA', 'NAT'}
EN_PROCESO = {'EN PROCESO', 'EN PROCESAMIENTO', 'POR PROCESAR', 'PPR'}


@dataclass
class ResultadoConsulta:
    estado: str
    # autorizado | no_autorizado | en_proceso | sin_resultados | no_disponible | fuera_de_rango | clave_invalida
    clave: str
    xml: bytes | None = None          # <autorizacion> reconstruida con la respuesta, para procesar_xml_sri
    mensajes: list = field(default_factory=list)
    intentos: int = 0
    estados_sri: list = field(default_factory=list)


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


def _interpretar(respuesta, resultado):
    clave_consultada = str(getattr(respuesta, 'claveAccesoConsultada', '') or '').strip()
    if clave_consultada and clave_consultada != resultado.clave:
        resultado.mensajes.append('El SRI devolvió una clave distinta de la consultada.')
        return resultado

    autorizaciones = _lista(getattr(getattr(respuesta, 'autorizaciones', None), 'autorizacion', None))
    if not autorizaciones:
        cantidad = str(getattr(respuesta, 'numeroComprobantes', '')).strip()
        if cantidad == '0':
            resultado.estado = 'sin_resultados'
            resultado.mensajes = ['El SRI no encontró un comprobante con esa clave.']
        else:
            resultado.mensajes.append('El SRI devolvió una respuesta sin un resultado de autorización.')
        return resultado

    estados = [_estado(autorizacion) for autorizacion in autorizaciones]
    resultado.estados_sri = list(dict.fromkeys(estado[:60] for estado in estados))[:8]
    for autorizacion, estado in zip(autorizaciones, estados):
        if estado in AUTORIZADOS and str(getattr(autorizacion, 'comprobante', '') or '').strip():
            resultado.estado = 'autorizado'
            resultado.xml = _sobre(autorizacion, resultado.clave)
            resultado.mensajes = []
            return resultado

    if any(estado in AUTORIZADOS for estado in estados):
        resultado.mensajes.append('El SRI indicó autorización sin devolver el XML para compararlo.')
        return resultado

    mensajes = [m for autorizacion in autorizaciones
                for m in _lista(getattr(getattr(autorizacion, 'mensajes', None), 'mensaje', None))]
    for mensaje in mensajes[:8]:
        identificador = str(getattr(mensaje, 'identificador', '') or '')[:12]
        texto = str(getattr(mensaje, 'mensaje', '') or '')[:180]
        if identificador or texto:
            resultado.mensajes.append(f'[{identificador}] {texto}'.strip())
    # Se identifica por el detalle, porque el SRI usa códigos diferentes según el servicio.
    for mensaje in mensajes:
        detalle = ' '.join(str(getattr(mensaje, 'informacionAdicional', '') or '').upper().split())
        if 'FECHA' in detalle and 'FUERA DEL RANGO' in detalle:
            resultado.estado = 'fuera_de_rango'
            resultado.mensajes.append('La fecha de emisión está fuera del rango de la consulta automática.')
            return resultado

    if any(estado in EN_PROCESO for estado in estados):
        resultado.estado = 'en_proceso'
        resultado.mensajes.append('El SRI todavía está procesando el comprobante.')
    elif all(estado in NO_AUTORIZADOS for estado in estados):
        resultado.estado = 'no_autorizado'
    else:
        resultado.mensajes.append('El SRI no devolvió un estado de autorización concluyente.')
    return resultado


def consultar_autorizacion(clave):
    from core.pos import emision
    try:
        datos = clave_acceso.analizar(clave)
    except clave_acceso.ClaveInvalida as e:
        return ResultadoConsulta('clave_invalida', clave, mensajes=[str(e)])
    url = emision.URL_SRI[datos.ambiente] + 'AutorizacionComprobantesOffline?wsdl'
    resultado = ResultadoConsulta('no_disponible', clave)
    respuesta = None
    for intento in range(1 + limites.SRI_REINTENTOS):
        resultado.intentos = intento + 1
        try:
            respuesta = emision._cliente(url, limites.SRI_TIEMPO_SEGUNDOS).service.autorizacionComprobante(clave)
            break
        except Exception as e:   # red, tiempo o respuesta inválida: se reintenta pocas veces
            resultado.mensajes.append(f'Sin respuesta del SRI ({e.__class__.__name__}).')
            if intento < limites.SRI_REINTENTOS:
                time.sleep(PAUSA_REINTENTO)
    if respuesta is not None:
        return _interpretar(respuesta, resultado)
    return resultado
