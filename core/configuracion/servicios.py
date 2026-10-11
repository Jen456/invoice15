"""Configuración inicial de facturación por empresa (asistente en 5 pasos).

Fuente única de: establecimiento y punto de emisión, numeración por tipo de
documento y ambiente, firma y ambiente. «Compañía» y «Comprobantes» muestran
estos datos pero no los editan.

Numeración: Receipt.sequence es el ÚLTIMO número utilizado; el «Número del
próximo documento» es sequence + 1. Las secuencias son independientes por
empresa, ambiente, establecimiento, punto de emisión y tipo; nunca retroceden
ni se reinician si ya tienen comprobantes.
"""
import re

from django.db import transaction
from django.utils import timezone

from core.pos.choices import ENVIRONMENT_TYPE, VOUCHER_TYPE
from core.pos.models import MAX_SECUENCIAL, BillingSetup, EmissionPoint, Receipt
from core.tenancy.models import audit

URL = '/configuracion/facturacion/'
PASOS = (
    (1, 'Datos de la empresa'),
    (2, 'Establecimientos y puntos de emisión'),
    (3, 'Numeración de facturas y notas de crédito'),
    (4, 'Firma electrónica y ambiente'),
    (5, 'Revisión y confirmación'),
)
FACTURA, NOTA_CREDITO, TICKET = VOUCHER_TYPE[0][0], VOUCHER_TYPE[1][0], VOUCHER_TYPE[2][0]
DOCUMENTOS = ((FACTURA, 'Factura'), (NOTA_CREDITO, 'Nota de crédito'))
NOMBRE_DOCUMENTO = {FACTURA: 'facturas', NOTA_CREDITO: 'notas de crédito', TICKET: 'tickets de venta'}
AMBIENTES = dict(ENVIRONMENT_TYPE)
PRODUCCION = 2

# Mensajes exactos (documentados en HANDOFF para el frontend).
MENSAJES = {
    'ultimo_formato': 'Escribe el último número usado: 125, 000000125 o 001-002-000000125.',
    'ultimo_rango': 'El último número debe estar entre 1 y 999999998.',
    'ultimo_otro_punto': 'El número {numero} es de otro punto de emisión ({codigo}); aquí configuras {punto}.',
    'retroceso': 'El último número no puede ser menor que {minimo:09d}: esta numeración ya llegó a ese número.',
    'reinicio_usada': 'Esta numeración ya tiene comprobantes emitidos en FacturaPorAquí; no se puede reiniciar.',
    'reinicio_existente': 'Esta numeración ya existía (último {ultimo}). Para no repetir números, mantenla o indica un último número mayor.',
    'confirmar_nuevo': 'Confirma que nunca has emitido {documento} desde {punto} en {ambiente}.',
    'confirmar_ultimo': 'Confirma que el último número emitido fue {numero}.',
    'falta_punto': 'Primero registra y confirma tu establecimiento y punto de emisión (paso 2).',
    'confirmar_codigos': 'Confirma que estos códigos son los que el SRI asignó a tu RUC.',
    'establecimiento_duplicado': 'Ya existe el establecimiento {codigo}.',
    'punto_duplicado': 'El punto {codigo} ya existe en el establecimiento {establecimiento}.',
    'punto_en_uso': 'Este punto de emisión ya tiene numeración usada o es el punto con el que emites; no se puede desactivar.',
    'confirmar_produccion': 'Confirma que entiendes que en Producción los comprobantes tienen validez tributaria.',
    'firma_sin_plan': 'Para subir tu firma electrónica (.p12) primero activa un plan en «Plan y pagos».',
    'firma_clave': 'La clave no abre este archivo .p12. Revisa la clave o el archivo.',
    'firma_sin_clave': 'Escribe la clave de la firma electrónica.',
    'pasos_pendientes': 'Antes de confirmar completa: {pasos}.',
    'confirmar_revision': 'Confirma que estos son los números con los que debes continuar.',
}


class ConfiguracionPendiente(Exception):
    """Falta un requisito para emitir (mensaje para el usuario con el paso que lo resuelve)."""


class ErrorConfiguracion(Exception):
    """Dato inválido en el asistente (mensaje para el usuario)."""


# ---------------------------------------------------------------- consultas

def obtener_setup(company):
    setup = BillingSetup.all_companies.filter(company=company).first()
    if setup is None:
        setup = BillingSetup(company=company)
        setup.save()
    return setup


def punto_predeterminado(company):
    return EmissionPoint.all_companies.select_related('establishment').filter(
        company=company, is_default=True, is_active=True).first()


def secuencia(company, punto, ambiente, tipo):
    if punto is None:
        return None
    return Receipt.all_companies.filter(company=company, environment_type=ambiente, voucher_type=tipo,
                                        establishment_code=punto.establishment.code, issuing_point_code=punto.code).first()


def datos_empresa_completos(company):
    from core.login.identificacion import ruc_valido
    return bool(ruc_valido(company.ruc or '') and company.business_name and company.main_address)


def paso_completo(company, setup, n, punto=None):
    punto = punto if punto is not None else punto_predeterminado(company)
    hechos = set(setup.completed_steps or [])
    if n == 1:
        return 1 in hechos and datos_empresa_completos(company)
    if n == 2:
        return 2 in hechos and punto is not None
    if n == 3:
        return 3 in hechos and all(secuencia(company, punto, company.environment_type, t) is not None for t, _ in DOCUMENTOS)
    if n == 4:
        return 4 in hechos and (company.environment_type != PRODUCCION or setup.production_confirmed)
    if n == 5:
        return setup.completed_at is not None and all(
            getattr(secuencia(company, punto, company.environment_type, t), 'confirmed_at', None) for t, _ in DOCUMENTOS)
    return False


def estado(company):
    """Estado completo del asistente (contexto de las pantallas y /estado.json)."""
    setup = obtener_setup(company)
    punto = punto_predeterminado(company)
    pasos = [{'numero': n, 'titulo': t, 'completo': paso_completo(company, setup, n, punto)} for n, t in PASOS]
    actual = next((p['numero'] for p in pasos if not p['completo']), 5)
    documentos = []
    for tipo, nombre in DOCUMENTOS + ((TICKET, 'Ticket de venta'),):
        r = secuencia(company, punto, company.environment_type, tipo)
        documentos.append({
            'tipo': tipo, 'nombre': nombre, 'existe': r is not None,
            'ultimo': r.sequence if r else None,
            'ultimo_completo': r.last_number_full() if r else '',
            'proximo': r.next_number if r else None,
            'proximo_completo': r.next_number_full() if r else '',
            'confirmado': bool(r and r.confirmed_at), 'utilizado': bool(r and r.is_used),
            'origen': r.origin if r else None,
        })
    return {
        'setup': setup, 'pasos': pasos, 'paso_actual': actual, 'completo': all(p['completo'] for p in pasos),
        'ambiente': {'codigo': company.environment_type, 'nombre': AMBIENTES.get(company.environment_type)},
        'punto': punto, 'punto_codigo': punto.full_code if punto else None, 'documentos': documentos,
        'firma': {'archivo': bool(company.electronic_signature), 'clave': bool(company.electronic_signature_key)},
        'requisitos': {'factura': requisitos_de_emision(company, FACTURA, True),
                       'nota_credito': requisitos_de_emision(company, NOTA_CREDITO, True)},
    }


def secuencia_configurada(company, tipo):
    """Secuencia confirmada para emitir `tipo` en el ambiente y punto actuales, o None."""
    setup = BillingSetup.all_companies.filter(company=company).first()
    if setup is None or setup.completed_at is None:
        return None
    r = secuencia(company, punto_predeterminado(company), company.environment_type, tipo)
    return r if r is not None and r.confirmed_at else None


def requisitos_de_emision(company, tipo, electronica):
    """Lo que falta para emitir `tipo`: [{codigo, mensaje, paso, url}] (vacío = se puede)."""
    faltan = []
    setup = BillingSetup.all_companies.filter(company=company).first()
    nombre = NOMBRE_DOCUMENTO.get(tipo, 'comprobantes')
    if setup is None or setup.completed_at is None:
        paso = next((n for n, _ in PASOS if setup is None or not paso_completo(company, setup, n)), 5)
        faltan.append({'codigo': 'configuracion', 'paso': paso, 'url': f'{URL}paso/{paso}/',
                       'mensaje': f'Para emitir {nombre} completa la configuración de facturación (paso {paso}).'})
    elif secuencia_configurada(company, tipo) is None:
        faltan.append({'codigo': 'secuencia', 'paso': 3, 'url': f'{URL}paso/3/',
                       'mensaje': (f'Configura y confirma la numeración de {nombre} para el ambiente '
                                   f'{AMBIENTES.get(company.environment_type)} (paso 3).')})
    if electronica and not (company.electronic_signature and company.electronic_signature_key):
        faltan.append({'codigo': 'firma', 'paso': 4, 'url': f'{URL}paso/4/',
                       'mensaje': 'Para emitir comprobantes electrónicos sube tu firma electrónica (.p12) y su clave (paso 4).'})
    return faltan


def receipt_para_emitir(company, tipo, electronica):
    """Secuencia con la que se emite `tipo`; ConfiguracionPendiente explica cómo resolverlo."""
    faltan = requisitos_de_emision(company, tipo, electronica)
    if faltan:
        raise ConfiguracionPendiente(f'{faltan[0]["mensaje"]} Ve a «Configuración de facturación»: {faltan[0]["url"]}')
    return secuencia_configurada(company, tipo)


# ---------------------------------------------------------------- progreso

def marcar_paso(company, n, request=None, completo=True, invalida=False):
    """Guarda el progreso. invalida=True (cambio de punto, numeración o ambiente) exige volver a confirmar."""
    setup = obtener_setup(company)
    hechos = set(setup.completed_steps or [])
    hechos.add(n) if completo else hechos.discard(n)
    if invalida:
        hechos.discard(5)
        setup.completed_at = None
    setup.completed_steps = sorted(hechos)
    setup.current_step = next((p for p, _ in PASOS if not paso_completo(company, setup, p)), 5)
    setup.save()
    audit(request, 'billing_setup_step', company=company, paso=n, completo=completo, invalida=invalida)
    return setup


# ---------------------------------------------------------------- paso 2

def confirmar_punto(company, punto, request=None):
    """Marca el punto con el que se emite y alinea los datos de «Compañía» con él."""
    anterior = punto_predeterminado(company)
    with transaction.atomic():
        EmissionPoint.all_companies.filter(company=company, is_default=True).exclude(pk=punto.pk).update(is_default=False)
        punto.is_default = True
        punto.save(update_fields=['is_default'])
        company.establishment_code = punto.establishment.code
        company.issuing_point_code = punto.code
        company.establishment_address = punto.establishment.address
        company.save(update_fields=['establishment_code', 'issuing_point_code', 'establishment_address'])
    audit(request, 'billing_point_change', company=company, punto=punto.full_code, accion='predeterminado')
    return marcar_paso(company, 2, request, invalida=anterior is None or anterior.pk != punto.pk)


# ---------------------------------------------------------------- paso 3

def interpretar_ultimo(texto, punto):
    """Último número usado a partir de «125», «000000125» o «001-002-000000125»."""
    texto = (texto or '').strip()
    m = re.fullmatch(r'(\d{3})-(\d{3})-(\d{1,9})', texto) or re.fullmatch(r'(\d{1,9})', texto)
    if not m:
        raise ErrorConfiguracion(MENSAJES['ultimo_formato'])
    if m.lastindex == 3:
        codigo = f'{m.group(1)}-{m.group(2)}'
        if codigo != punto.full_code:
            raise ErrorConfiguracion(MENSAJES['ultimo_otro_punto'].format(numero=texto, codigo=codigo, punto=punto.full_code))
        numero = int(m.group(3))
    else:
        numero = int(m.group(1))
    if not 1 <= numero <= MAX_SECUENCIAL - 1:
        raise ErrorConfiguracion(MENSAJES['ultimo_rango'])
    return numero


def configurar_secuencia(company, punto, ambiente, tipo, modo, ultimo_texto='', confirmado=False, usuario=None, request=None):
    """Crea o ajusta la numeración de `tipo` (sin retroceder ni reiniciar lo ya usado). Devuelve la secuencia."""
    if punto is None:
        raise ErrorConfiguracion(MENSAJES['falta_punto'])
    nombre = NOMBRE_DOCUMENTO[tipo]
    with transaction.atomic():
        filtro = dict(company=company, environment_type=ambiente, voucher_type=tipo,
                      establishment_code=punto.establishment.code, issuing_point_code=punto.code)
        r = Receipt.all_companies.select_for_update().filter(**filtro).first()
        antes = r.sequence if r else None
        if modo == 'mantener':
            if r is None:
                raise ErrorConfiguracion(MENSAJES['ultimo_formato'])
            nuevo, origen = r.sequence, r.origin
        elif modo == 'nuevo':
            if r is not None and r.is_used:
                raise ErrorConfiguracion(MENSAJES['reinicio_usada'])
            if r is not None and r.sequence > 0:
                raise ErrorConfiguracion(MENSAJES['reinicio_existente'].format(ultimo=r.last_number_full()))
            if not confirmado:
                raise ErrorConfiguracion(MENSAJES['confirmar_nuevo'].format(documento=nombre, punto=punto.full_code,
                                                                            ambiente=AMBIENTES[ambiente]))
            nuevo, origen = 0, 'nuevo'
        elif modo == 'otro_sistema':
            numero = interpretar_ultimo(ultimo_texto, punto)
            minimo = max(r.sequence, r.max_used()) if r else 0
            if numero < minimo:
                raise ErrorConfiguracion(MENSAJES['retroceso'].format(minimo=minimo))
            if not confirmado:
                raise ErrorConfiguracion(MENSAJES['confirmar_ultimo'].format(numero=f'{punto.full_code}-{numero:09d}'))
            nuevo, origen = numero, 'otro_sistema'
        else:
            raise ErrorConfiguracion(MENSAJES['ultimo_formato'])
        if r is None:
            r = Receipt(**filtro)
        cambio = antes != nuevo or r.origin != origen or r.emission_point_id != punto.pk
        r.sequence, r.origin, r.emission_point = nuevo, origen, punto
        if cambio:
            r.confirmed_at, r.confirmed_by = None, None
        r.save()
    if cambio:
        audit(request, 'billing_sequence_change', company=company, tipo=tipo, punto=punto.full_code,
              ambiente=ambiente, antes=antes, ultimo=nuevo, proximo=nuevo + 1, origen=origen)
    return r


# ---------------------------------------------------------------- paso 5

def confirmar_configuracion(company, usuario=None, request=None):
    """Confirma la revisión: fija las secuencias del ambiente y punto actuales y habilita la emisión."""
    setup = obtener_setup(company)
    punto = punto_predeterminado(company)
    pendientes = [t for n, t in PASOS[:4] if not paso_completo(company, setup, n, punto)]
    if pendientes:
        raise ErrorConfiguracion(MENSAJES['pasos_pendientes'].format(pasos=', '.join(pendientes)))
    ahora = timezone.now()
    with transaction.atomic():
        resumen = {}
        for tipo, _ in DOCUMENTOS:
            r = Receipt.all_companies.select_for_update().get(pk=secuencia(company, punto, company.environment_type, tipo).pk)
            r.confirmed_at, r.confirmed_by = ahora, usuario
            r.save(update_fields=['confirmed_at', 'confirmed_by'])
            resumen[tipo] = r.next_number_full()
        ticket = secuencia(company, punto, company.environment_type, TICKET)
        if ticket is None:   # tickets internos (no SRI): empiezan en 1
            ticket = Receipt(company=company, environment_type=company.environment_type, voucher_type=TICKET,
                             establishment_code=punto.establishment.code, issuing_point_code=punto.code,
                             emission_point=punto, sequence=0, origin='nuevo')
        ticket.confirmed_at, ticket.confirmed_by = ahora, usuario
        ticket.save()
        setup.completed_at, setup.completed_by = ahora, usuario
        setup.completed_steps = sorted(set(setup.completed_steps or []) | {5})
        setup.current_step = 5
        setup.save()
    audit(request, 'billing_setup_confirm', company=company, punto=punto.full_code, ambiente=company.environment_type,
          proximos=resumen)
    return setup
