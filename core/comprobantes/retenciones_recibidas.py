"""Retenciones recibidas de clientes (Etapa 2, O2): comprobante de retención (07) que un cliente emitió a la empresa sobre
una de sus facturas, registrado a mano o desde un 07 importado (puente con core/importacion/recibidos.py de O1).

- Un registro por par (comprobante 07, factura sustento). Unicidad condicional (mientras esté registrada): se puede
  registrar de nuevo tras anular. documento_importado es una ForeignKey(PROTECT): el documento no se borra mientras lo
  referencie una retención.
- Abona la cuenta por cobrar de la factura (hasta su saldo) con un abono tipo 'retencion'; al anular, el abono se revierte
  (no se borra). No se llama al SRI, no se envían correos y no se consume cupo.
- El catálogo de retenciones se consulta solo con core.comprobantes.retenciones.codigo_retencion_vigente (B0; D0 le
  programa la vigencia), por la pareja (impuesto, código) y la fecha de emisión, activo o no: el cliente puede usar
  códigos que la empresa no emite. El detalle guarda una copia de código, concepto y porcentaje.
- Bloqueos con select_for_update(of=('self',)) y sin select_related; orden DocumentoImportado → Sale (por pk) →
  RetencionRecibida → CtasCollect → PaymentsCtaCollect.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.comprobantes import retenciones as catalogo
from core.comprobantes.models import RetencionRecibida, RetencionRecibidaDetalle, redondear
from core.importacion import clave_acceso, recibidos
from core.login.identificacion import ruc_valido
from core.pos import cxc
from core.pos.choices import ENVIRONMENT_TYPE, ESTADOS_DECLARABLES_VENTA

MAX_LINEAS = 10
TOLERANCIA = Decimal('0.01')
PLAZO_DIAS = 5   # LRTI art. 50: la retención se entrega dentro de los 5 días de recibida la factura
AMBIENTES = dict(ENVIRONMENT_TYPE)

MENSAJES = {
    # factura
    'no_es_factura': 'Las retenciones recibidas se registran sobre facturas (no sobre tickets).',
    'factura_no_autorizada': 'Solo se registran retenciones sobre facturas autorizadas por el SRI.',
    'factura_anulada': 'La factura {numero} está anulada en el SRI.',
    'consumidor_final': 'Una factura a consumidor final no admite retención: el comprador no está identificado.',
    # emisor
    'ruc_emisor': 'El agente de retención se identifica con un RUC válido de 13 dígitos; el cliente de esta factura tiene la '
                  'identificación {dni}.',
    'ruc_no_coincide': 'El RUC {ruc} del agente de retención no es el del cliente de la factura ({dni}).',
    # número y autorización
    'numero': 'Escribe el número de la retención con establecimiento, punto y secuencial: 001-001-000000123.',
    'autorizacion': 'La autorización de la retención tiene 49 dígitos (clave de acceso), o 10 o 37 en comprobantes antiguos.',
    'clave_invalida': 'La clave de acceso no es válida: {detalle}',
    'clave_tipo': 'La clave de acceso no corresponde a un comprobante de retención (tipo {tipo}).',
    'clave_ruc': 'La clave de acceso es de otro emisor (RUC {ruc}); el cliente es {dni}.',
    'clave_numero': 'La clave de acceso es del comprobante {numero_clave}, no del {numero}.',
    'clave_fecha': 'La fecha de la clave de acceso ({fecha_clave}) no coincide con la fecha de emisión.',
    'clave_ambiente': 'La clave de acceso es del ambiente {ambiente_clave}; la factura es de {ambiente}.',
    # fechas
    'fecha_futura': 'La fecha de emisión de la retención no puede ser futura.',
    'fecha_anterior': 'La retención no puede ser anterior a la factura ({fecha}).',
    # líneas
    'sin_lineas': 'Agrega al menos una retención (renta o IVA).',
    'max_lineas': 'Una retención admite hasta 10 líneas.',
    'codigo': 'El código {codigo} no está en el catálogo de retenciones vigente el {fecha}.',
    'repetido': 'El código {codigo} está repetido.',
    'base_cero': 'La base del código {codigo} debe ser mayor que cero.',
    'porcentaje': 'El porcentaje del código {codigo} debe estar entre 0 y 100.',
    'valor_no_coincide': 'El valor retenido del código {codigo} ({valor}) no coincide con base × porcentaje ({calculado}).',
    'impuesto_no_soportado': 'El sistema todavía no registra retenciones de ISD (código 6).',
    # topes
    'base_renta_excede': 'Las bases de renta ({base}) superan el subtotal sin impuestos de la factura ({tope}), sumando otras '
                         'retenciones registradas.',
    'base_iva_excede': 'Las bases de IVA ({base}) superan el IVA de la factura ({tope}), sumando otras retenciones registradas.',
    # registro y anulación
    'duplicada': 'Ya registraste la retención {numero} de {cliente} sobre esta factura.',
    'ya_anulada': 'Esta retención ya está anulada.',
    'motivo': 'Escribe el motivo (al menos 10 caracteres).',
    # 07 importado: documento
    'documento_no_corresponde': 'Los datos leídos no corresponden a este documento.',
    'no_es_retencion': 'Este documento no es un comprobante de retención.',
    'documento_descartado': 'El documento fue descartado.',
    'impuesto_no_soportado_documento': 'El sistema todavía no registra retenciones de ISD (código 6): registra a mano la parte '
                                       'de renta e IVA.',
    # 07 importado: sustentos
    'sustento_no_factura': 'El documento sustento {numero} no es una factura.',
    'sustento_no_encontrado': 'No hay una factura {numero} emitida por la empresa en el ambiente {ambiente}.',
    'sustento_ambiguo': 'Hay más de una factura con el número {numero}: regístrala a mano.',
}
# Clave del texto → código que se informa (el ISD tiene un texto propio a nivel de documento).
CODIGO_DE = {'impuesto_no_soportado_documento': 'impuesto_no_soportado'}

ADVERTENCIAS = {
    'porcentaje_catalogo': 'El código {c} tiene {x} % en el catálogo vigente y la retención usa {y} %. Revisa el comprobante '
                           'del cliente.',
    'excedente_cxc': 'La retención supera el saldo de la cuenta por cobrar en {excedente}: no se abona ese excedente.',
    'plazo_5_dias': 'La retención se emitió {d} días después de la factura (la ley da 5 días).',
    'ruc_de_cedula': 'El agente de retención usa el RUC {ruc}; la factura se emitió con su cédula {dni}.',
    'sin_verificar': 'Registrada a mano: no se verificó en el SRI.',
}


class ErrorRetencionRecibida(Exception):
    def __init__(self, mensaje, codigo='', sustento=''):
        super().__init__(mensaje)
        self.codigo = codigo
        self.sustento = sustento


def _error(clave, **datos):
    return ErrorRetencionRecibida(MENSAJES[clave].format(**datos), CODIGO_DE.get(clave, clave))


def _aviso(codigo, **datos):
    return {'codigo': codigo, 'texto': ADVERTENCIAS[codigo].format(**datos)}


@dataclass
class LineaRetencionRecibida:
    impuesto: str              # '1' renta | '2' IVA (el 07 trae 1/2/6; 6 = ISD → error 'impuesto_no_soportado')
    codigo: str                # codigoRetencion del XML o del catálogo
    base_imponible: Decimal
    porcentaje: Decimal | None = None         # None → el del catálogo vigente a fecha_emision
    valor_retenido: Decimal | None = None     # None → base × % / 100


@dataclass
class DatosRetencionRecibida:
    numero: str                # '001-001-000000123' o 15 dígitos
    autorizacion: str          # 49 (clave de acceso), 37 o 10 dígitos
    fecha_emision: date
    lineas: list = field(default_factory=list)   # [LineaRetencionRecibida]
    emisor_ruc: str = ''       # vacío en el registro manual → el RUC del cliente de la venta
    emisor_razon_social: str = ''
    periodo_fiscal: str = ''   # 'MM/AAAA'; vacío → fecha_emision
    ambiente: int | None = None   # None → el de la venta
    cod_doc_sustento: str = '01'
    num_doc_sustento: str = ''    # 15 dígitos; vacío → el de la venta
    fecha_doc_sustento: date | None = None
    verificacion: str = 'sin_verificar'
    notas: str = ''


# ------------------------------------------------------------------ utilidades

def normalizar_numero(texto):
    """15 dígitos sin guiones ni espacios, o '' si no son 15 dígitos."""
    digitos = re.sub(r'[\s-]', '', texto or '')
    return digitos if re.fullmatch(r'\d{15}', digitos) else ''


def con_guiones(numero15):
    return f'{numero15[:3]}-{numero15[3:6]}-{numero15[6:]}' if len(numero15) == 15 else numero15


def _texto(valor):
    return f'{redondear(valor):.2f}'


def _pct(valor):
    return f'{Decimal(valor).normalize():f}'


def _decimal(valor):
    if valor is None or valor == '':
        return None
    try:
        numero = Decimal(str(valor).strip().replace(',', '.'))
    except InvalidOperation:
        raise ValueError(valor)
    if not numero.is_finite():
        raise ValueError(valor)
    return numero


def fecha_efectiva(venta):
    return venta.emission_date or venta.authorization_date or venta.date_joined


def _validar_factura(venta):
    from core.pos.notas_credito import es_consumidor_final
    if venta.receipt.voucher_type != '01':
        raise _error('no_es_factura')
    if venta.status not in ESTADOS_DECLARABLES_VENTA:
        raise _error('factura_no_autorizada')
    if venta.anulado_sri_fecha is not None:
        raise _error('factura_anulada', numero=venta.voucher_number_full)
    if es_consumidor_final(venta.client):
        raise _error('consumidor_final')


def _emisor(venta, datos, advertencias):
    dni = re.sub(r'\s', '', venta.client.dni or '')
    ruc = re.sub(r'\s', '', datos.emisor_ruc or '') or dni
    if not ruc_valido(ruc):
        raise _error('ruc_emisor', dni=dni)
    if ruc != dni:
        if re.fullmatch(r'\d{10}', dni) and ruc == f'{dni}001':
            advertencias.append(_aviso('ruc_de_cedula', ruc=ruc, dni=dni))
        else:
            raise _error('ruc_no_coincide', ruc=ruc, dni=dni)
    razon = ' '.join((datos.emisor_razon_social or venta.client.user.names or '').split())[:300]
    return ruc, razon


def _numero_y_autorizacion(venta, datos, ruc):
    numero = normalizar_numero(datos.numero)
    if not numero or numero[:3] == '000' or numero[3:6] == '000' or int(numero[6:]) == 0:
        raise _error('numero')
    autorizacion = re.sub(r'\D', '', datos.autorizacion or '')
    if len(autorizacion) not in (10, 37, 49):
        raise _error('autorizacion')
    clave = ''
    if len(autorizacion) == 49:
        try:
            analizada = clave_acceso.analizar(autorizacion)
        except clave_acceso.ClaveInvalida as e:
            raise _error('clave_invalida', detalle=str(e))
        if analizada.cod_doc != '07':
            raise _error('clave_tipo', tipo=analizada.cod_doc)
        if analizada.ruc != ruc:
            raise _error('clave_ruc', ruc=analizada.ruc, dni=ruc)
        if (analizada.estab, analizada.pto_emi, analizada.secuencial) != (numero[:3], numero[3:6], numero[6:]):
            raise _error('clave_numero', numero_clave=analizada.numero, numero=con_guiones(numero))
        if analizada.fecha_emision != datos.fecha_emision:
            raise _error('clave_fecha', fecha_clave=f'{analizada.fecha_emision:%d/%m/%Y}')
        if analizada.ambiente != venta.environment_type:
            raise _error('clave_ambiente', ambiente_clave=AMBIENTES.get(analizada.ambiente, analizada.ambiente),
                         ambiente=AMBIENTES.get(venta.environment_type, venta.environment_type))
        clave = autorizacion
    return numero, autorizacion, clave


def _lineas(datos):
    lineas = list(datos.lineas or [])
    if not lineas:
        raise _error('sin_lineas')
    if len(lineas) > MAX_LINEAS:
        raise _error('max_lineas')
    detalle, usados = [], set()
    for linea in lineas:
        impuesto, codigo = str(linea.impuesto or '').strip(), str(linea.codigo or '').strip().upper()
        if impuesto not in ('1', '2'):
            raise _error('impuesto_no_soportado')
        if (impuesto, codigo) in usados:
            raise _error('repetido', codigo=codigo)
        usados.add((impuesto, codigo))
        fila = catalogo.codigo_retencion_vigente(impuesto, codigo, datos.fecha_emision, incluir_inactivos=True)
        if fila is None:
            raise _error('codigo', codigo=codigo, fecha=f'{datos.fecha_emision:%d/%m/%Y}')
        try:
            base = _decimal(linea.base_imponible)
        except ValueError:
            raise _error('base_cero', codigo=codigo)
        if base is None or redondear(base) <= 0:
            raise _error('base_cero', codigo=codigo)
        base = redondear(base)
        try:
            porcentaje = _decimal(linea.porcentaje)
        except ValueError:
            raise _error('porcentaje', codigo=codigo)
        porcentaje = Decimal(fila.porcentaje) if porcentaje is None else redondear(porcentaje)
        if not Decimal('0') <= porcentaje <= Decimal('100'):
            raise _error('porcentaje', codigo=codigo)
        calculado = redondear(base * porcentaje / 100)
        try:
            valor = _decimal(linea.valor_retenido)
        except ValueError:
            raise _error('valor_no_coincide', codigo=codigo, valor=linea.valor_retenido, calculado=_texto(calculado))
        if valor is None:
            valor = calculado
        elif abs(redondear(valor) - calculado) > TOLERANCIA:
            raise _error('valor_no_coincide', codigo=codigo, valor=_texto(valor), calculado=_texto(calculado))
        else:
            valor = redondear(valor)
        detalle.append({'impuesto': impuesto, 'codigo': codigo, 'concepto': (fila.concepto or '')[:300],
                        'base_imponible': base, 'porcentaje': porcentaje, 'valor_retenido': valor,
                        'porcentaje_catalogo': Decimal(fila.porcentaje), 'porcentaje_editable': fila.porcentaje_editable})
    return detalle


def _usado(venta):
    """Bases de renta y de IVA de las retenciones registradas de la venta."""
    filas = (RetencionRecibidaDetalle.objects.filter(retencion__venta=venta, retencion__estado='registrada')
             .values('impuesto').annotate(base=Sum('base_imponible')))
    usado = {f['impuesto']: f['base'] or Decimal('0') for f in filas}
    return redondear(usado.get('1', 0)), redondear(usado.get('2', 0))


# ------------------------------------------------------------------ cálculo y registro

def calcular(venta, datos, origen='manual'):
    """Valida y calcula sin guardar. Lanza ErrorRetencionRecibida con el código de MENSAJES."""
    advertencias = []
    _validar_factura(venta)
    ruc, razon = _emisor(venta, datos, advertencias)
    numero, autorizacion, clave = _numero_y_autorizacion(venta, datos, ruc)
    if _duplicada_existe({'emisor_ruc': ruc, 'establecimiento': numero[:3], 'punto_emision': numero[3:6],
                          'secuencial': numero[6:]}, venta):
        raise _error('duplicada', numero=con_guiones(numero), cliente=razon or venta.client.user.names)
    hoy = timezone.localdate()
    if datos.fecha_emision is None or datos.fecha_emision > hoy:
        raise _error('fecha_futura')
    fecha_factura = fecha_efectiva(venta)
    if datos.fecha_emision < fecha_factura:
        raise _error('fecha_anterior', fecha=f'{fecha_factura:%d/%m/%Y}')
    dias = (datos.fecha_emision - fecha_factura).days
    if dias > PLAZO_DIAS:
        advertencias.append(_aviso('plazo_5_dias', d=dias))
    lineas = _lineas(datos)
    for linea in lineas:
        if linea['porcentaje'] != linea['porcentaje_catalogo'] and not linea['porcentaje_editable']:
            advertencias.append(_aviso('porcentaje_catalogo', c=linea['codigo'], x=_pct(linea['porcentaje_catalogo']),
                                       y=_pct(linea['porcentaje'])))
    base_renta = redondear(sum((l['base_imponible'] for l in lineas if l['impuesto'] == '1'), Decimal('0')))
    base_iva = redondear(sum((l['base_imponible'] for l in lineas if l['impuesto'] == '2'), Decimal('0')))
    usado_renta, usado_iva = _usado(venta)
    tope_renta = redondear(Decimal(venta.subtotal_12) + Decimal(venta.subtotal_0))
    tope_iva = redondear(venta.total_iva)
    if base_renta and usado_renta + base_renta > tope_renta + TOLERANCIA:
        raise _error('base_renta_excede', base=_texto(usado_renta + base_renta), tope=_texto(tope_renta))
    if base_iva and usado_iva + base_iva > tope_iva + TOLERANCIA:
        raise _error('base_iva_excede', base=_texto(usado_iva + base_iva), tope=_texto(tope_iva))
    total_renta = redondear(sum((l['valor_retenido'] for l in lineas if l['impuesto'] == '1'), Decimal('0')))
    total_iva = redondear(sum((l['valor_retenido'] for l in lineas if l['impuesto'] == '2'), Decimal('0')))
    total = redondear(total_renta + total_iva)
    cuenta = cxc.cxc_de_factura(venta)
    abono, excedente = Decimal('0.00'), Decimal('0.00')
    if cuenta is None:
        cxc_estado = 'sin_cxc'
    else:
        saldo = cxc.saldo(cuenta)
        if cxc.tiene_anulacion(cuenta) or saldo <= 0:
            cxc_estado = 'sin_saldo'
            excedente = total
        else:
            abono = min(total, saldo)
            excedente = redondear(total - abono)
            cxc_estado = 'aplicada' if excedente <= 0 else 'parcial'
            if excedente > 0:
                advertencias.append(_aviso('excedente_cxc', excedente=_texto(excedente)))
    verificacion = datos.verificacion or 'sin_verificar'
    if verificacion == 'sin_verificar':
        advertencias.append(_aviso('sin_verificar'))
    periodo = datos.periodo_fiscal if re.fullmatch(r'(0[1-9]|1[0-2])/\d{4}', datos.periodo_fiscal or '') \
        else f'{datos.fecha_emision:%m/%Y}'
    doc = {'numero': con_guiones(numero), 'establecimiento': numero[:3], 'punto_emision': numero[3:6],
           'secuencial': numero[6:], 'autorizacion': autorizacion, 'clave_acceso': clave, 'fecha_emision': datos.fecha_emision,
           'periodo_fiscal': periodo, 'emisor_ruc': ruc, 'emisor_razon_social': razon,
           'ambiente': datos.ambiente or venta.environment_type, 'cod_doc_sustento': datos.cod_doc_sustento or '01',
           'num_doc_sustento': normalizar_numero(venta.voucher_number_full), 'fecha_doc_sustento': fecha_factura,
           'verificacion': verificacion, 'notas': ' '.join((datos.notas or '').split())[:300], 'origen': origen}
    return {'doc': doc,
            'lineas': [{k: l[k] for k in ('impuesto', 'codigo', 'concepto', 'base_imponible', 'porcentaje', 'valor_retenido')}
                       for l in lineas],
            'total_renta': total_renta, 'total_iva': total_iva, 'total_retenido': total, 'abono_previsto': abono,
            'excedente': excedente, 'cxc_estado': cxc_estado, 'advertencias': advertencias,
            'topes': {'renta': tope_renta, 'iva': tope_iva, 'usado_renta': usado_renta, 'usado_iva': usado_iva}}


def _auditar(request, usuario, company, accion, **detalle):
    from core.tenancy.models import AuditLog, audit
    if request is not None:
        audit(request, accion, company=company, **detalle)
    else:
        AuditLog.objects.create(user=usuario, company=company, action=accion, detail=detalle)


def _duplicada_existe(doc, venta):
    """La misma retención (emisor y número) ya está registrada sobre la venta, por cualquier origen."""
    return RetencionRecibida.objects.filter(emisor_identificacion=doc['emisor_ruc'], establecimiento=doc['establecimiento'],
                                            punto_emision=doc['punto_emision'], secuencial=doc['secuencial'], venta=venta,
                                            estado='registrada').exists()


def registrar(company, usuario, venta, datos, origen='manual', documento_importado=None, request=None):
    """Registra la retención y su abono. Llamar dentro de una transacción (la vista o registrar_desde_importacion)."""
    from core.pos.models import Sale
    with transaction.atomic():
        Sale.objects.select_for_update(of=('self',)).filter(pk=venta.pk).values_list('pk', flat=True).get()
        venta = Sale.objects.select_related('client__user', 'receipt').get(pk=venta.pk)
        if documento_importado is not None:
            existente = RetencionRecibida.objects.filter(documento_importado=documento_importado, venta=venta,
                                                         estado='registrada').first()
            if existente is not None:
                return existente   # idempotente: el mismo documento no registra dos veces la misma venta
        cuenta = cxc.cxc_de_factura(venta, bloquear=True)
        resultado = calcular(venta, datos, origen)
        doc = resultado['doc']
        duplicada = _error('duplicada', numero=doc['numero'], cliente=doc['emisor_razon_social'] or venta.client.user.names)
        if _duplicada_existe(doc, venta):
            raise duplicada
        ret = RetencionRecibida(
            venta=venta, cliente=venta.client, emisor_identificacion=doc['emisor_ruc'],
            emisor_razon_social=doc['emisor_razon_social'], establecimiento=doc['establecimiento'],
            punto_emision=doc['punto_emision'], secuencial=doc['secuencial'], numero=doc['numero'],
            autorizacion=doc['autorizacion'], clave_acceso=doc['clave_acceso'], fecha_emision=doc['fecha_emision'],
            periodo_fiscal=doc['periodo_fiscal'], ambiente=doc['ambiente'], cod_doc_sustento=doc['cod_doc_sustento'],
            num_doc_sustento=doc['num_doc_sustento'], fecha_doc_sustento=doc['fecha_doc_sustento'],
            total_renta=resultado['total_renta'], total_iva=resultado['total_iva'],
            total_retenido=resultado['total_retenido'], origen=origen, documento_importado=documento_importado,
            verificacion=doc['verificacion'], advertencias=[{'codigo': str(a['codigo']), 'texto': str(a['texto'])}
                                                             for a in resultado['advertencias']],
            notas=doc['notas'], registrado_por=usuario, registrado_en=timezone.now())
        try:
            with transaction.atomic():   # savepoint: una IntegrityError no deja abortada la transacción exterior (PG)
                ret.save()
        except IntegrityError:
            raise duplicada
        for linea in resultado['lineas']:
            RetencionRecibidaDetalle.objects.create(retencion=ret, **linea)
        abono = None
        if resultado['cxc_estado'] in ('aplicada', 'parcial'):
            abono = cxc.crear_abono(cuenta, 'retencion', resultado['abono_previsto'], doc['fecha_emision'],
                                    f'Retención {doc["numero"]}', usuario, referencia=doc['numero'])
        RetencionRecibida.objects.filter(pk=ret.pk).update(abono=abono, cxc_estado=resultado['cxc_estado'])
        ret.abono, ret.cxc_estado = abono, resultado['cxc_estado']
        _auditar(request, usuario, company, 'retencion_recibida_registro', id=int(ret.pk), numero=ret.numero,
                 venta=int(venta.pk), total=_texto(ret.total_retenido), origen=origen,
                 documento=int(documento_importado.pk) if documento_importado is not None else None)
        return ret


def anular(company, usuario, retencion, motivo, request=None):
    """Anula el registro (el cliente la anuló en el SRI o se registró por error): revierte su abono y, si era la última
    retención registrada de un documento importado, lo devuelve a «pendiente» en Importación (O1)."""
    from core.importacion.models import DocumentoImportado
    from core.pos.models import CtasCollect, PaymentsCtaCollect, Sale
    motivo = ' '.join((motivo or '').split())
    with transaction.atomic():
        fila = RetencionRecibida.objects.filter(pk=retencion.pk).values('documento_importado_id', 'venta_id').get()
        documento = None
        if fila['documento_importado_id']:
            documento = DocumentoImportado.objects.select_for_update(of=('self',)).get(pk=fila['documento_importado_id'])
        Sale.objects.select_for_update(of=('self',)).filter(pk=fila['venta_id']).values_list('pk', flat=True).get()
        ret = RetencionRecibida.objects.select_for_update(of=('self',)).get(pk=retencion.pk)
        if ret.estado == 'anulada':
            raise _error('ya_anulada')
        if len(motivo) < 10:
            raise _error('motivo')
        motivo = motivo[:300]
        ahora = timezone.now()
        revertido, cxc_estado = Decimal('0.00'), ret.cxc_estado
        if ret.abono_id:
            abono_cxc = PaymentsCtaCollect.objects.filter(pk=ret.abono_id).values_list('ctas_collect_id', flat=True).get()
            CtasCollect.objects.select_for_update(of=('self',)).filter(pk=abono_cxc).values_list('pk', flat=True).get()
            abono = PaymentsCtaCollect.objects.select_for_update(of=('self',)).get(pk=ret.abono_id)
            if abono.anulado_en is None:
                revertido = redondear(abono.valor)
                cxc.revertir_abono(abono, ahora, f'Retención {ret.numero} anulada: {motivo}')
            cxc_estado = 'revertida'
        RetencionRecibida.objects.filter(pk=ret.pk).update(
            estado='anulada', anulado_sri_fecha=timezone.localdate(), anulado_sri_motivo=motivo, anulado_sri_por=usuario,
            anulado_sri_registrado_en=ahora, cxc_estado=cxc_estado)
        desmarcado = False
        if documento is not None and not RetencionRecibida.objects.filter(documento_importado=documento,
                                                                          estado='registrada').exists():
            recibidos.desmarcar_incorporado(documento, usuario, motivo)
            desmarcado = True
        _auditar(request, usuario, company, 'retencion_recibida_anulacion', id=int(ret.pk), numero=ret.numero, motivo=motivo,
                 abono_revertido=_texto(revertido), documento_desmarcado=desmarcado)
        ret.refresh_from_db()
        return ret


# ------------------------------------------------------------------ puente del 07 importado

def _buscar_venta(num_doc_sustento, ambiente):
    """(venta, clave de error): la factura de la empresa con ese número (15 dígitos, con o sin guiones) y ambiente."""
    from core.pos.models import Sale
    n = normalizar_numero(num_doc_sustento)
    if not n:
        return None, 'sustento_no_encontrado'
    ventas = list(Sale.objects.filter(voucher_number_full=con_guiones(n), environment_type=ambiente,
                                      receipt__voucher_type='01').order_by('pk')[:2])
    if len(ventas) > 1:
        return None, 'sustento_ambiguo'
    if not ventas:
        return None, 'sustento_no_encontrado'
    return ventas[0], ''


def buscar_venta_sustento(num_doc_sustento, ambiente):
    return _buscar_venta(num_doc_sustento, ambiente)[0]


def _error_sustento(clave, sustento, ambiente):
    numero = sustento.numero_con_guiones
    return _error(clave, numero=numero, ambiente=AMBIENTES.get(ambiente, ambiente))


def _errores_documento(documento, leida):
    errores = []
    if leida.documento_id != documento.pk:
        errores.append('documento_no_corresponde')
    if documento.cod_doc != '07':
        errores.append('no_es_retencion')
    if documento.estado_revision == 'descartado':
        errores.append('documento_descartado')
    if any(str(linea.impuesto) == '6' for s in leida.sustentos for linea in s.retenciones):
        errores.append('impuesto_no_soportado_documento')
    return [_error(clave) for clave in errores]


def _datos_de_leida(leida, sustento):
    return DatosRetencionRecibida(
        numero=leida.numero, autorizacion=leida.clave_acceso, fecha_emision=leida.fecha_emision,
        emisor_ruc=leida.agente_ruc, emisor_razon_social=leida.agente_razon_social, periodo_fiscal=leida.periodo_fiscal,
        ambiente=leida.ambiente, cod_doc_sustento=sustento.cod_doc_sustento, num_doc_sustento=sustento.num_doc_sustento,
        fecha_doc_sustento=sustento.fecha_emision_doc_sustento,
        lineas=[LineaRetencionRecibida(impuesto=l.impuesto, codigo=l.codigo_retencion, base_imponible=l.base_imponible,
                                       porcentaje=l.porcentaje, valor_retenido=l.valor_retenido) for l in sustento.retenciones],
        verificacion='verificada_sri' if leida.verificado_sri else 'declarada_en_archivo')


def revisar_importacion(company, documento, leida):
    """Vista previa del registro desde un 07 importado (no escribe nada). Contrato de la pantalla de O1 (espec §6.13)."""
    errores_documento = [{'codigo': e.codigo, 'texto': str(e)} for e in _errores_documento(documento, leida)]
    sustentos = []
    for s in leida.sustentos:
        fila = {'num_doc_sustento': s.numero_con_guiones, 'venta_id': None, 'venta_numero': '', 'cliente': '',
                'ya_registrada_id': None, 'resultado': None, 'error': None}
        sustentos.append(fila)
        if s.cod_doc_sustento != '01':
            e = _error_sustento('sustento_no_factura', s, leida.ambiente)
            fila['error'] = {'codigo': e.codigo, 'texto': str(e)}
            continue
        venta, clave = _buscar_venta(s.num_doc_sustento, leida.ambiente)
        if venta is None:
            e = _error_sustento(clave, s, leida.ambiente)
            fila['error'] = {'codigo': e.codigo, 'texto': str(e)}
            continue
        fila.update(venta_id=venta.pk, venta_numero=venta.voucher_number_full, cliente=venta.client.user.names)
        existente = RetencionRecibida.objects.filter(documento_importado=documento, venta=venta, estado='registrada').first()
        if existente is not None:
            fila['ya_registrada_id'] = existente.pk
            continue
        try:
            resultado = calcular(venta, _datos_de_leida(leida, s), origen='importado')
        except ErrorRetencionRecibida as e:
            fila['error'] = {'codigo': e.codigo, 'texto': str(e)}
            continue
        fila['resultado'] = {k: v for k, v in resultado.items() if k != 'doc'}
    puede = bool(sustentos) and not errores_documento and all(f['venta_id'] and not f['error'] for f in sustentos)
    return {'documento_id': documento.pk, 'numero': leida.numero, 'agente_ruc': leida.agente_ruc,
            'agente_razon_social': leida.agente_razon_social, 'fecha_emision': leida.fecha_emision, 'ambiente': leida.ambiente,
            'verificacion': 'verificada_sri' if leida.verificado_sri else 'declarada_en_archivo', 'puede_registrar': puede,
            'errores_documento': errores_documento, 'sustentos': sustentos}


def registrar_desde_importacion(company, usuario, documento, leida, request=None):
    """Una retención recibida por sustento, todo o nada; idempotente por (documento, venta). Marca el documento como
    incorporado (O1) una sola vez al final."""
    from core.importacion.models import DocumentoImportado
    from core.pos.models import Sale
    with transaction.atomic():
        documento = DocumentoImportado.objects.select_for_update(of=('self',)).get(pk=documento.pk)
        errores = _errores_documento(documento, leida)
        if errores:
            raise errores[0]
        if not leida.sustentos:
            raise _error('sin_lineas')
        ventas = []
        for s in leida.sustentos:
            if s.cod_doc_sustento != '01':
                e = _error_sustento('sustento_no_factura', s, leida.ambiente)
                raise ErrorRetencionRecibida(f'Sustento {s.numero_con_guiones}: {e}', e.codigo, s.numero_con_guiones)
            venta, clave = _buscar_venta(s.num_doc_sustento, leida.ambiente)
            if venta is None:
                e = _error_sustento(clave, s, leida.ambiente)
                raise ErrorRetencionRecibida(f'Sustento {s.numero_con_guiones}: {e}', e.codigo, s.numero_con_guiones)
            ventas.append(venta)
        list(Sale.objects.select_for_update(of=('self',)).filter(pk__in=[v.pk for v in ventas]).order_by('pk')
             .values_list('pk', flat=True))
        registradas = []
        for s, venta in zip(leida.sustentos, ventas):
            existente = RetencionRecibida.objects.filter(documento_importado=documento, venta=venta,
                                                         estado='registrada').first()
            if existente is not None:
                registradas.append(existente)
                continue
            try:
                registradas.append(registrar(company, usuario, venta, _datos_de_leida(leida, s), origen='importado',
                                             documento_importado=documento, request=request))
            except ErrorRetencionRecibida as e:
                raise ErrorRetencionRecibida(f'Sustento {s.numero_con_guiones}: {e}', e.codigo, s.numero_con_guiones)
        recibidos.marcar_incorporado(documento, usuario,
                                     descripcion='Retenciones recibidas ' + ', '.join(f'#{r.pk}' for r in registradas))
        return registradas


# ------------------------------------------------------------------ para declarar (Etapa 4)

def del_periodo(desde, hasta, ambiente=2):
    """Retenciones registradas de ventas del ambiente (producción por defecto), por fecha de emisión de la retención."""
    return RetencionRecibida.objects.filter(estado='registrada', venta__environment_type=ambiente,
                                            fecha_emision__range=(desde, hasta))


def totales_para_formularios(desde, hasta):
    """Casillero 609 (IVA retenido), crédito de renta y totales por cliente para el ATS (valorRetIva / valorRetRenta)."""
    cero = Value(Decimal('0'), output_field=DecimalField(max_digits=14, decimal_places=2))
    filas = del_periodo(desde, hasta)
    totales = filas.aggregate(iva=Coalesce(Sum('total_iva'), cero), renta=Coalesce(Sum('total_renta'), cero))
    por_cliente = {}
    for fila in (filas.order_by().values('emisor_identificacion', 'cliente_id')
                 .annotate(iva=Coalesce(Sum('total_iva'), cero), renta=Coalesce(Sum('total_renta'), cero))
                 .order_by('emisor_identificacion', 'cliente_id')):
        actual = por_cliente.setdefault(fila['emisor_identificacion'], {'iva': Decimal('0.00'), 'renta': Decimal('0.00'),
                                                                        'cliente_id': fila['cliente_id']})
        actual['iva'] = redondear(actual['iva'] + fila['iva'])
        actual['renta'] = redondear(actual['renta'] + fila['renta'])
    return {'iva': redondear(totales['iva']), 'renta': redondear(totales['renta']), 'por_cliente': por_cliente}
