"""Consulta de autorización al SRI para recuperar el XML de una clave (servicio AutorizacionComprobantesOffline).

Operación SOAP autorizacionComprobante(claveAccesoComprobante) del WSDL del ambiente que indica la propia clave
(dígito 24: 1 = pruebas, 2 = producción); el WSDL describe el servicio, no es una descarga. Reutiliza el cliente de la
emisión (core/pos/emision.py: _cliente y URL_SRI). Respuestas: sin autorizaciones (el SRI no la tiene), una o varias
(se toma la AUTORIZADA), NO AUTORIZADO, o sin respuesta (red o tiempo: reintentos limitados).
"""
import time
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from django.utils import timezone

from core.importacion import clave_acceso, limites

PAUSA_REINTENTO = 1.0


@dataclass
class ResultadoConsulta:
    estado: str                       # autorizado | no_autorizado | sin_resultados | no_disponible | clave_invalida
    clave: str
    xml: bytes | None = None          # <autorizacion> reconstruida con la respuesta, para procesar_xml_sri
    mensajes: list = field(default_factory=list)
    intentos: int = 0


def _lista(valor):
    if valor is None:
        return []
    return list(valor) if isinstance(valor, (list, tuple)) else [valor]


def _sobre(aut, clave):
    fecha = getattr(aut, 'fechaAutorizacion', None)
    if hasattr(fecha, 'isoformat'):
        fecha = (timezone.localtime(fecha) if timezone.is_aware(fecha) else fecha).isoformat()
    partes = [('estado', aut.estado), ('numeroAutorizacion', getattr(aut, 'numeroAutorizacion', '') or clave),
              ('fechaAutorizacion', fecha or ''), ('ambiente', getattr(aut, 'ambiente', '') or '')]
    cuerpo = ''.join(f'<{k}>{escape(str(v))}</{k}>' for k, v in partes)
    comprobante = escape(str(getattr(aut, 'comprobante', '') or ''))
    return f'<?xml version="1.0" encoding="UTF-8"?><autorizacion>{cuerpo}<comprobante>{comprobante}</comprobante></autorizacion>'.encode()


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
    if respuesta is None:
        return resultado
    autorizaciones = _lista(getattr(getattr(respuesta, 'autorizaciones', None), 'autorizacion', None))
    if not autorizaciones:
        resultado.estado, resultado.mensajes = 'sin_resultados', ['El SRI no tiene un comprobante autorizado con esa clave.']
        return resultado
    autorizadas = [a for a in autorizaciones if str(getattr(a, 'estado', '')).upper() == 'AUTORIZADO']
    if autorizadas:
        resultado.estado, resultado.xml, resultado.mensajes = 'autorizado', _sobre(autorizadas[0], clave), []
        return resultado
    resultado.estado = 'no_autorizado'
    for aut in autorizaciones:
        for m in _lista(getattr(getattr(aut, 'mensajes', None), 'mensaje', None)):
            resultado.mensajes.append(f"[{getattr(m, 'identificador', '')}] {getattr(m, 'mensaje', '')}".strip())
    return resultado
