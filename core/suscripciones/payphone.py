"""Cliente del Botón de Pagos de PayPhone (redirección).

Prepare crea el formulario de pago (dura 10 minutos) y Confirm consulta el
resultado; si un pago aprobado no se confirma en 5 minutos, PayPhone lo reversa.
El token y el storeId salen de las variables de entorno y nunca se registran.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class PayPhoneNoConfigurado(RuntimeError):
    """Faltan PAYPHONE_TOKEN o PAYPHONE_STORE_ID en el entorno."""


class PayPhoneError(RuntimeError):
    """PayPhone respondió con un error (datos rechazados, transacción inexistente...)."""

    def __init__(self, mensaje, status=None, codigo=None):
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo


class PayPhoneSinRespuesta(RuntimeError):
    """No se pudo hablar con PayPhone (red, tiempo de espera, error 5xx)."""


def configurado():
    return bool(settings.PAYPHONE_TOKEN and settings.PAYPHONE_STORE_ID)


def _post(ruta, cuerpo):
    if not configurado():
        raise PayPhoneNoConfigurado('El cobro con PayPhone no está configurado en este entorno')
    url = settings.PAYPHONE_API_BASE.rstrip('/') + ruta
    try:
        respuesta = requests.post(url, json=cuerpo, timeout=settings.PAYPHONE_TIMEOUT, headers={
            'Authorization': f'Bearer {settings.PAYPHONE_TOKEN}',
            'Content-Type': 'application/json',
        })
    except requests.RequestException as e:
        logger.warning('PayPhone %s sin respuesta: %s', ruta, type(e).__name__)
        raise PayPhoneSinRespuesta(type(e).__name__) from None
    if respuesta.status_code >= 500:
        logger.warning('PayPhone %s respondió HTTP %s', ruta, respuesta.status_code)
        raise PayPhoneSinRespuesta(f'HTTP {respuesta.status_code}')
    try:
        datos = respuesta.json()
    except ValueError:
        raise PayPhoneSinRespuesta(f'Respuesta no JSON (HTTP {respuesta.status_code})') from None
    if respuesta.status_code >= 400:
        mensaje = datos.get('message') if isinstance(datos, dict) else None
        codigo = datos.get('errorCode') if isinstance(datos, dict) else None
        logger.warning('PayPhone %s rechazó la petición: HTTP %s código %s', ruta, respuesta.status_code, codigo)
        raise PayPhoneError(mensaje or f'HTTP {respuesta.status_code}', respuesta.status_code, codigo)
    return datos


def preparar(pago, url_respuesta, url_cancelacion, referencia):
    """Crea el formulario de pago y devuelve {paymentId, payWithCard, payWithPayPhone}."""
    datos = _post('/api/button/Prepare', {
        'amount': pago.amount_cents,
        'amountWithoutTax': 0,
        'amountWithTax': pago.base_cents,
        'tax': pago.iva_cents,
        'service': 0,
        'tip': 0,
        'currency': pago.currency,
        'clientTransactionId': pago.client_tx_id,
        'storeId': settings.PAYPHONE_STORE_ID,
        'reference': referencia[:100],
        'responseUrl': url_respuesta,
        'cancellationUrl': url_cancelacion,
        'lang': 'es',
        'timeZone': -5,
    })
    if not isinstance(datos, dict) or not datos.get('payWithCard'):
        raise PayPhoneError('PayPhone no devolvió el enlace de pago')
    return datos


def confirmar(transaccion_id, client_tx_id):
    """Resultado de la transacción (statusCode 3 aprobada, 2 cancelada)."""
    datos = _post('/api/button/V2/Confirm', {'id': int(transaccion_id), 'clientTxId': client_tx_id})
    if not isinstance(datos, dict):
        raise PayPhoneSinRespuesta('Respuesta inesperada')
    return datos


# Campos de la confirmación que se guardan en el historial (sin datos personales del titular).
CAMPOS_REGISTRABLES = ('statusCode', 'transactionStatus', 'transactionId', 'clientTransactionId', 'amount',
                       'currency', 'authorizationCode', 'cardBrand', 'lastDigits', 'message', 'messageCode',
                       'date', 'storeName', 'reference')


def saneado(datos):
    return {k: datos.get(k) for k in CAMPOS_REGISTRABLES if isinstance(datos, dict) and k in datos}
