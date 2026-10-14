"""Emisión electrónica de facturas y notas de crédito en dos fases (auditoría SRI, oct-2026).

1. preparar(comprobante): dentro de la transacción que crea el comprobante. Fija UNA sola vez la
   fecha de emisión y la clave de acceso, genera y firma el XML y lo guarda. Si algo falla, la
   transacción se deshace y nada salió hacia el SRI.
2. emitir(comprobante): después de confirmar esa transacción. Envía el XML firmado guardado y
   consulta la autorización con la misma clave. Un comprobante que pudo llegar al SRI nunca se
   borra ni se renumera: si el SRI tarda, queda «En proceso en el SRI» y se vuelve a consultar
   (botón del listado y tarea periódica `consultar_sri`).

Reenviar el mismo XML es seguro: si el SRI ya lo tiene responde 43 o 70 y se sigue consultando.
"""
import logging
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from lxml import etree

from core.login.identificacion import ruc_valido
from core.pos.utilities.firma import ErrorFirma, firmar_xml

logger = logging.getLogger(__name__)

PRODUCCION = 2
SIN_ENVIAR = 'without_authorizing'
AUTORIZADA = 'authorized'
ENVIADA = 'authorized_and_sent_by_email'
ANULADA = 'canceled'
SECUENCIAL_REGISTRADO = 'sequential_registered_error'
EN_PROCESO = 'in_process'
DEVUELTA = 'returned'
NO_AUTORIZADA = 'not_authorized'
AUTORIZADOS = (AUTORIZADA, ENVIADA)
# Estados en los que el SRI tiene (o pudo tener) el comprobante: no se borra ni se renumera.
BLOQUEAN_BORRADO = (EN_PROCESO, AUTORIZADA, ENVIADA, ANULADA)

URL_SRI = {1: 'https://celcer.sri.gob.ec/comprobantes-electronicos-ws/',
           2: 'https://cel.sri.gob.ec/comprobantes-electronicos-ws/'}
TIEMPO_RECEPCION = 20       # segundos por llamada (conexión y lectura)
TIEMPO_AUTORIZACION = 10
ESPERAS_AL_EMITIR = (1, 2, 3)   # consultas de autorización dentro de la misma petición
ESPERAS_AL_CONSULTAR = (2,)
YA_RECIBIDO = {'43', '70'}      # clave de acceso registrada / en procesamiento: el SRI ya lo tiene
SECUENCIAL_YA_REGISTRADO = '45'

MENSAJE_SIN_RUC_PROVEEDOR = ('La plataforma aún no tiene configurado el RUC del proveedor del sistema de facturación, '
                             'que el SRI exige en cada comprobante (Res. NAC-DGERCGC26-00000027). Escribe a soporte de '
                             'FacturaPorAquí; mientras tanto no se emite en Producción.')


class ErrorEmision(Exception):
    """El comprobante no se pudo preparar o enviar; el mensaje es para el usuario."""


def ruc_proveedor():
    """RUC del proveedor del sistema (Anexo 26 de la ficha técnica); vacío si falta o no es válido."""
    ruc = (getattr(settings, 'FPA_RUC_PROVEEDOR', '') or '').strip()
    if ruc and not ruc_valido(ruc):
        logger.error('FPA_RUC_PROVEEDOR no es un RUC válido; no se incluye en los comprobantes.')
        return ''
    return ruc


def datos_proveedor():
    """Proveedor del sistema para los documentos impresos (None si aún no hay RUC Proveedor)."""
    ruc = ruc_proveedor()
    if not ruc:
        return None
    return {'ruc': ruc, 'nombre': settings.FPA_PROVEEDOR_NOMBRE, 'email': settings.FPA_PROVEEDOR_EMAIL,
            'direccion': settings.FPA_PROVEEDOR_DIRECCION}


def _nombre(comprobante):
    return f'{comprobante.receipt.name.lower()} {comprobante.voucher_number_full}'


def _femenino(comprobante):
    return comprobante.receipt.name.lower().startswith(('factura', 'nota', 'liquidación', 'guía'))


def _la(comprobante):
    """«la factura 001-…» / «el comprobante de retención 001-…»."""
    return f'{"la" if _femenino(comprobante) else "el"} {_nombre(comprobante)}'


def _autorizado(comprobante):
    return 'autorizada' if _femenino(comprobante) else 'autorizado'


# ------------------------------------------------------------------ fase 1: preparar

def _fecha_de_clave(clave):
    if clave and len(clave) == 49:
        try:
            return datetime.strptime(clave[:8], '%d%m%Y').date()
        except ValueError:
            return None
    return None


def preparar(comprobante):
    """Fija fecha y clave (si aún no las tiene), genera el XML y lo guarda firmado. Lanza ErrorEmision o PlanRequerido."""
    from core.suscripciones.cupo import verificar_disponible
    verificar_disponible(comprobante)
    if comprobante.environment_type == PRODUCCION and not ruc_proveedor():
        raise ErrorEmision(MENSAJE_SIN_RUC_PROVEEDOR)
    company = comprobante.company
    if not company.electronic_signature:
        raise ErrorEmision('Sube tu firma electrónica (.p12) en «Configuración de facturación», paso 4.')
    if comprobante.emission_date is None:
        comprobante.emission_date = _fecha_de_clave(comprobante.access_code) or timezone.localdate()
    xml, clave = comprobante.generate_xml()
    if not clave or len(clave) != 49:
        raise ErrorEmision('No se pudo generar la clave de acceso del comprobante; revisa el RUC y la numeración.')
    try:
        with company.electronic_signature.open('rb') as archivo:
            firmado = firmar_xml(xml, archivo.read(), company.electronic_signature_key)
    except ErrorFirma as e:
        raise ErrorEmision(str(e))
    comprobante.access_code, comprobante.xml_signed, comprobante.signed_at = clave, firmado, timezone.now()
    type(comprobante).all_companies.filter(pk=comprobante.pk).update(
        emission_date=comprobante.emission_date, access_code=clave, xml_signed=firmado, signed_at=comprobante.signed_at)
    return comprobante


# ------------------------------------------------------------------ servicios web del SRI

def _cliente(url, timeout):
    from suds.client import Client
    return Client(url, timeout=timeout)


def _lista(valor):
    if valor is None:
        return []
    return list(valor) if isinstance(valor, (list, tuple)) else [valor]


def _mensajes(nodo):
    salida = []
    for m in _lista(getattr(getattr(nodo, 'mensajes', None), 'mensaje', None)):
        salida.append({k: str(getattr(m, k, '') or '') for k in ('identificador', 'mensaje', 'informacionAdicional', 'tipo')})
    return salida


def _texto_mensajes(mensajes):
    return '; '.join(f"[{m['identificador']}] {m['mensaje']}" + (f" ({m['informacionAdicional']})" if m['informacionAdicional'] else '')
                     for m in mensajes) or 'sin detalle'


def _recepcion(comprobante):
    """('recibida' | 'ya_recibida' | 'devuelta' | 'secuencial' | 'sin_respuesta', mensajes)."""
    import base64
    url = URL_SRI[comprobante.environment_type] + 'RecepcionComprobantesOffline?wsdl'
    try:
        respuesta = _cliente(url, TIEMPO_RECEPCION).service.validarComprobante(
            base64.b64encode(comprobante.xml_signed.encode('utf-8')).decode('ascii'))
    except Exception as e:   # red, tiempo de espera o respuesta inválida: el SRI pudo recibirlo
        logger.warning('Recepción SRI sin respuesta para %s: %s', comprobante.access_code, e.__class__.__name__)
        return 'sin_respuesta', [{'identificador': '', 'mensaje': 'Sin respuesta del SRI', 'informacionAdicional': e.__class__.__name__, 'tipo': ''}]
    estado = str(getattr(respuesta, 'estado', '') or '')
    mensajes = []
    for comp in _lista(getattr(getattr(respuesta, 'comprobantes', None), 'comprobante', None)):
        mensajes.extend(_mensajes(comp))
    if estado == 'RECIBIDA':
        return 'recibida', mensajes
    codigos = {m['identificador'] for m in mensajes}
    if codigos & YA_RECIBIDO:
        return 'ya_recibida', mensajes
    if SECUENCIAL_YA_REGISTRADO in codigos:
        return 'secuencial', mensajes
    return 'devuelta', mensajes


def _autorizacion(comprobante):
    """Primera autorización definitiva (AUTORIZADO / NO AUTORIZADO) o None si aún no hay respuesta."""
    url = URL_SRI[comprobante.environment_type] + 'AutorizacionComprobantesOffline?wsdl'
    try:
        respuesta = _cliente(url, TIEMPO_AUTORIZACION).service.autorizacionComprobante(comprobante.access_code)
    except Exception as e:
        logger.warning('Autorización SRI sin respuesta para %s: %s', comprobante.access_code, e.__class__.__name__)
        return None
    autorizaciones = _lista(getattr(getattr(respuesta, 'autorizaciones', None), 'autorizacion', None))
    for aut in autorizaciones:
        if str(getattr(aut, 'estado', '')) == 'AUTORIZADO':
            return aut
    for aut in autorizaciones:
        if str(getattr(aut, 'estado', '')) in ('NO AUTORIZADO', 'RECHAZADO'):
            return aut
    return None


# ------------------------------------------------------------------ fase 2: enviar y consultar

def _registrar_error(comprobante, etapa, detalle):
    from core.pos.utilities.sri import SRI
    SRI().create_voucher_errors(comprobante, {'stage': etapa, 'error': detalle})


def _guardar_autorizado(comprobante, aut):
    """XML autorizado (formato <autorizacion> con el comprobante en CDATA) y estado AUTORIZADA."""
    raiz = etree.Element('autorizacion')
    etree.SubElement(raiz, 'estado').text = str(aut.estado)
    etree.SubElement(raiz, 'numeroAutorizacion').text = str(getattr(aut, 'numeroAutorizacion', '') or comprobante.access_code)
    fecha = getattr(aut, 'fechaAutorizacion', None) or timezone.now()
    etree.SubElement(raiz, 'fechaAutorizacion').text = timezone.localtime(fecha).strftime('%d/%m/%Y %H:%M:%S') if timezone.is_aware(fecha) else fecha.strftime('%d/%m/%Y %H:%M:%S')
    etree.SubElement(raiz, 'ambiente').text = str(getattr(aut, 'ambiente', '') or '')
    etree.SubElement(raiz, 'comprobante').text = etree.CDATA(str(getattr(aut, 'comprobante', '') or comprobante.xml_signed))
    contenido = etree.tostring(raiz, encoding='UTF-8', xml_declaration=True)
    comprobante.xml_authorized.save(f'xml/{comprobante.receipt.get_name_xml()}_{comprobante.access_code}.xml', ContentFile(contenido), save=False)
    comprobante.authorization_date = fecha
    comprobante.status = AUTORIZADA
    type(comprobante).all_companies.filter(pk=comprobante.pk).update(
        xml_authorized=comprobante.xml_authorized.name, authorization_date=fecha, status=AUTORIZADA)


def _aplicar_autorizacion(comprobante, aut):
    estado = str(aut.estado)
    if estado == 'AUTORIZADO':
        _guardar_autorizado(comprobante, aut)
        return {'resp': True, 'estado': AUTORIZADA, 'mensaje': f'{_nombre(comprobante).capitalize()} {_autorizado(comprobante)} por el SRI.'}
    mensajes = _mensajes(aut)
    comprobante.status = NO_AUTORIZADA
    type(comprobante).all_companies.filter(pk=comprobante.pk).update(status=NO_AUTORIZADA)
    _registrar_error(comprobante, 'xml_authorized', {'access_code': comprobante.access_code, 'stage': estado, 'errors': mensajes})
    return {'resp': False, 'estado': NO_AUTORIZADA,
            'error': f'El SRI no autorizó {_la(comprobante)}: {_texto_mensajes(mensajes)}. Corrige los datos y '
                     'reenvíala desde el listado: se conservan el número y la clave de acceso.'}


def _en_proceso(comprobante):
    return {'resp': True, 'estado': EN_PROCESO, 'en_proceso': True,
            'mensaje': f'El SRI recibió {_la(comprobante)} y aún lo está autorizando. Quedó guardado como «En proceso en el SRI»: '
                       'consulta su estado en el listado. No lo vuelvas a emitir.'}


def _procesar(comprobante, esperas):
    """Con la fila del comprobante bloqueada: consulta, envía si hace falta y aplica la respuesta."""
    if comprobante.status == EN_PROCESO:
        aut = _autorizacion(comprobante)
        if aut is not None:
            return _aplicar_autorizacion(comprobante, aut)
    resultado, mensajes = _recepcion(comprobante)
    if resultado == 'devuelta':
        comprobante.status = DEVUELTA
        type(comprobante).all_companies.filter(pk=comprobante.pk).update(status=DEVUELTA)
        _registrar_error(comprobante, 'xml_validation', {'access_code': comprobante.access_code, 'errors': mensajes})
        return {'resp': False, 'estado': DEVUELTA,
                'error': f'El SRI devolvió {_la(comprobante)}: {_texto_mensajes(mensajes)}. Corrige los datos y reenvíalo '
                         'desde el listado: se conservan el número y la clave de acceso.'}
    if resultado == 'secuencial':
        comprobante.status = SECUENCIAL_REGISTRADO
        type(comprobante).all_companies.filter(pk=comprobante.pk).update(status=SECUENCIAL_REGISTRADO)
        _registrar_error(comprobante, 'xml_validation', {'access_code': comprobante.access_code, 'errors': mensajes})
        return {'resp': False, 'estado': SECUENCIAL_REGISTRADO,
                'error': f'El SRI ya tiene registrado el número {comprobante.voucher_number_full} con otra clave de acceso '
                         '(por ejemplo, emitido desde otro sistema). Revisa la numeración en «Configuración de facturación» '
                         'y escribe a soporte antes de volver a emitir.'}
    # recibida, ya recibida o sin respuesta: el SRI lo tiene o pudo tenerlo; nunca se deshace
    ahora = timezone.now()
    comprobante.status = EN_PROCESO
    comprobante.sri_sent_at = comprobante.sri_sent_at or ahora
    type(comprobante).all_companies.filter(pk=comprobante.pk).update(status=EN_PROCESO, sri_sent_at=comprobante.sri_sent_at)
    for espera in esperas:
        time.sleep(espera)
        aut = _autorizacion(comprobante)
        if aut is not None:
            return _aplicar_autorizacion(comprobante, aut)
    return _en_proceso(comprobante)


def _ejecutar(comprobante, esperas):
    Modelo = type(comprobante)
    with transaction.atomic():
        # Bloquea solo este comprobante (no la numeración ni el cupo): dos envíos a la vez no se pisan.
        actual = Modelo.all_companies.select_for_update().get(pk=comprobante.pk)
        if actual.status in AUTORIZADOS:
            resultado = {'resp': True, 'estado': actual.status, 'mensaje': 'Ya estaba autorizada por el SRI.'}
        elif actual.status == ANULADA:
            resultado = {'resp': False, 'estado': ANULADA, 'error': 'Este comprobante está anulado.'}
        elif actual.status == SECUENCIAL_REGISTRADO:
            resultado = {'resp': False, 'estado': SECUENCIAL_REGISTRADO,
                         'error': f'El SRI ya tiene registrado el número {actual.voucher_number_full} con otra clave de acceso. '
                                  'Escribe a soporte antes de volver a emitir.'}
        else:
            if not actual.xml_signed or actual.status in (DEVUELTA, NO_AUTORIZADA):
                preparar(actual)   # misma fecha y clave; el XML refleja los datos corregidos
            resultado = _procesar(actual, esperas)
    comprobante.refresh_from_db()
    if comprobante.status == AUTORIZADA:
        _despues_de_autorizar(comprobante)
    return resultado


def _despues_de_autorizar(comprobante):
    """RIDE, nota de crédito sobre la factura y correo: sus fallos no cambian el estado autorizado."""
    from core.pos.utilities.sri import SRI
    try:
        comprobante.generate_pdf_authorized()
        type(comprobante).all_companies.filter(pk=comprobante.pk).update(pdf_authorized=comprobante.pdf_authorized.name)
    except Exception as e:
        logger.exception('RIDE no generado para %s', comprobante.access_code)
        _registrar_error(comprobante, 'xml_authorized', f'Autorizada, pero no se pudo generar el RIDE ({e.__class__.__name__}).')
    if comprobante._meta.model_name == 'creditnote':
        from core.pos.notas_credito import actualizar_factura
        actualizar_factura(comprobante.sale_id)
        cliente = comprobante.sale.client
    elif hasattr(comprobante, 'get_destinatario'):
        # Comprobantes adicionales (retención…): el destinatario no es un cliente de ventas.
        from types import SimpleNamespace
        nombre, correo, enviar = comprobante.get_destinatario()
        cliente = SimpleNamespace(send_email_invoice=enviar, user=SimpleNamespace(names=nombre, email=correo))
    else:
        cliente = comprobante.client
    SRI().notify_by_email(instance=comprobante, company=comprobante.company, client=cliente)


def emitir(comprobante):
    """Envía (o reenvía) el comprobante; si ya está en proceso, solo consulta. Respuesta para la vista."""
    from core.suscripciones import cupo
    if comprobante.status == EN_PROCESO:
        resultado = _ejecutar(comprobante, ESPERAS_AL_CONSULTAR)
        cupo.cerrar_segun_estado(comprobante)
    else:
        resultado = cupo.emitir_con_cupo(comprobante, lambda: _ejecutar(comprobante, ESPERAS_AL_EMITIR))
    if resultado.get('resp') and comprobante.status in AUTORIZADOS:
        resultado['print_url'] = comprobante.get_pdf_authorized()
    return resultado


def consultar_pendientes(limite=200):
    """Para la tarea periódica: comprobantes en proceso o firmados sin enviar (todas las empresas)."""
    from core.comprobantes.models import Retencion
    from core.pos.models import CreditNote, Sale
    from core.tenancy.context import company_context, platform_scope
    resumen = {'consultados': 0, 'autorizados': 0, 'pendientes': 0, 'con_error': 0}
    hace_un_rato = timezone.now() - timedelta(minutes=2)
    for Modelo in (Sale, CreditNote, Retencion):
        with platform_scope():   # la lista abarca todas las empresas; cada comprobante se procesa en la suya
            pendientes = list(Modelo.all_companies.select_related('company')
                              .filter(create_electronic_invoice=True)
                              .filter(models_q_pendientes(hace_un_rato))
                              .order_by('pk')[:limite])
        for comprobante in pendientes:
            resumen['consultados'] += 1
            try:
                with company_context(comprobante.company):
                    resultado = emitir(comprobante)
            except Exception:
                logger.exception('Consulta SRI fallida para %s', comprobante.pk)
                resumen['con_error'] += 1
                continue
            if comprobante.status in AUTORIZADOS:
                resumen['autorizados'] += 1
            elif resultado.get('resp'):
                resumen['pendientes'] += 1
            else:
                resumen['con_error'] += 1
    return resumen


def models_q_pendientes(antes_de):
    from django.db.models import Q
    # En proceso (siempre) o firmados que no llegaron a enviarse (la petición murió tras confirmar la venta).
    return Q(status=EN_PROCESO) | Q(status=SIN_ENVIAR, xml_signed__isnull=False, sri_sent_at__isnull=True, signed_at__lt=antes_de)
