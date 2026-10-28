"""Marca «Anulado en el SRI» de los seis comprobantes emitidos (Etapa 2, O2).

Registra en FacturaPorAquí una anulación que la empresa ya hizo en SRI en línea. No llama al SRI, no cambia el status
(sigue siendo la respuesta real del SRI), no regenera XML ni RIDE, no borra ni libera el secuencial, no devuelve cupo y no
envía correos. No se desmarca desde la interfaz.

Efectos por tipo (todo en una transacción): la factura deja su cuenta por cobrar en cero con un abono de anulación (antes
hay que anular sus notas de crédito y de débito, su retención recibida y eliminar o reubicar sus cobros) y, si se pide,
devuelve al inventario lo que no siguió devuelto por notas de crédito; la nota de crédito revierte su abono, deshace la
devolución si se pide y la factura vuelve a «Autorizada» si deja de estar cubierta; la nota de débito anula su cuenta por
cobrar; la retención y la liquidación dejan de contar para su compra (O1 recibe la señal anulado_en_sri) y la guía deja
de amparar el traslado.

Bloqueos con select_for_update(of=('self',)) y sin select_related: Sale → CreditNote / NotaDebito → CtasCollect.
"""
import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.apps import apps
from django.db import transaction
from django.db.models import F, Sum
from django.http import Http404
from django.utils import timezone

from core.pos.choices import CONSUMIDOR_FINAL_NO_ANULABLE_DESDE
from core.pos.senales_comprobantes import anulado_en_sri   # señal de B0: sender=Modelo; kwargs instance, usuario, fecha

AUTORIZADOS = ('authorized', 'authorized_and_sent_by_email')
EN_PROCESO = 'in_process'
NO_CUENTAN = ('returned', 'not_authorized', 'sequential_registered_error')
CENTAVO = Decimal('0.01')

MODELOS = {   # slug → (app_label, model_name, nombre visible, femenino, url de la lista)
    'factura': ('pos', 'sale', 'factura', True, '/pos/sale/admin/'),
    'nota-credito': ('pos', 'creditnote', 'nota de crédito', True, '/pos/credit/note/admin/'),
    'retencion': ('comprobantes', 'retencion', 'retención', True, '/comprobantes/retenciones/'),
    'liquidacion': ('comprobantes', 'liquidacioncompra', 'liquidación de compra', True, '/comprobantes/liquidaciones/'),
    'nota-debito': ('comprobantes', 'notadebito', 'nota de débito', True, '/comprobantes/notas-debito/'),
    'guia': ('comprobantes', 'guiaremision', 'guía de remisión', True, '/comprobantes/guias/'),
}

MENSAJES = {
    'no_autorizado': 'Solo se marca como anulado un comprobante autorizado por el SRI.',
    'ya_anulado': 'Este comprobante ya está marcado como anulado en el SRI desde el {fecha}.',
    'ticket': 'El ticket de venta no es un comprobante del SRI: no se anula en el SRI.',
    'fecha': 'Escribe la fecha de anulación.',
    'fecha_futura': 'La fecha de anulación no puede ser futura.',
    'fecha_anterior': 'La fecha de anulación no puede ser anterior a la emisión ({fecha}).',
    'motivo': 'Escribe el motivo de la anulación (al menos 10 caracteres).',
    'plazo_sin_confirmar': 'La fecha pasa del plazo del SRI ({limite}): confirma que el SRI aceptó la anulación.',
    'consumidor_final': 'El SRI no permite anular facturas emitidas a consumidor final (Res. NAC-DGERCGC25-00000014, desde el '
                        '01/01/2026).',
    'nc_vigente': 'Primero marca como anulada la nota de crédito {numero}: modifica esta factura.',
    'nc_en_proceso': 'La nota de crédito {numero} está en proceso en el SRI: espera su respuesta.',
    'nc_sin_enviar': 'Elimina antes la nota de crédito {numero}, que el SRI no autorizó o no se envió.',
    'nd_vigente': 'Primero marca como anulada la nota de débito {numero}.',
    'nd_en_proceso': 'La nota de débito {numero} está en proceso en el SRI: espera su respuesta.',
    'nd_sin_enviar': 'Elimina antes la nota de débito {numero}, que el SRI no autorizó o no se envió.',
    'retencion_recibida': 'Primero anula el registro de la retención {numero} que te hizo el cliente.',
    'retencion_sobre_liquidacion': 'Primero marca como anulada la retención {numero} emitida sobre esta liquidación.',
    'cobros': 'La cuenta por cobrar tiene cobros por {valor}. Elimínalos o regístralos en el comprobante que la reemplace '
              'antes de marcarla como anulada.',
}
AVISOS = {
    'guias': 'La factura tiene guías de remisión autorizadas ({numeros}): anúlalas también en SRI en línea si corresponde.',
    'stock_negativo': 'El inventario de {producto} quedará en {n}.',
}


class ErrorAnulacion(Exception):
    """Mensaje para el usuario (texto de MENSAJES[codigo])."""

    def __init__(self, codigo, **datos):
        super().__init__(MENSAJES[codigo].format(**datos))
        self.codigo = codigo


def _dinero(valor):
    return f'${Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP):.2f}'.replace('.', ',')


def _modelo(slug):
    if slug not in MODELOS:
        raise Http404('Tipo de comprobante desconocido.')
    app_label, model_name = MODELOS[slug][:2]
    return apps.get_model(app_label, model_name)


def permiso(slug):
    if slug not in MODELOS:
        raise Http404('Tipo de comprobante desconocido.')
    return f'change_anulado_sri_{MODELOS[slug][1]}'


def obtener(slug, pk, bloquear=False):
    """Comprobante de la empresa activa (Http404 si el slug no existe o es de otra empresa)."""
    Modelo = _modelo(slug)
    queryset = Modelo.objects.all()
    if bloquear:
        queryset = queryset.select_for_update(of=('self',))
    doc = queryset.filter(pk=pk).first()
    if doc is None:
        raise Http404('El comprobante no existe.')
    return doc


def slug_de(doc):
    for slug, (app_label, model_name, *_resto) in MODELOS.items():
        if doc._meta.app_label == app_label and doc._meta.model_name == model_name:
            return slug
    raise ValueError(f'{doc._meta.label} no se marca como anulado en el SRI.')


def esta_anulado(doc):
    return getattr(doc, 'anulado_sri_fecha', None) is not None


def fecha_emision(doc):
    """Fecha efectiva de emisión: la del SRI, la de autorización o la de registro (ventas antiguas sin emission_date)."""
    if doc.emission_date:
        return doc.emission_date
    autorizada = doc.authorization_date
    if autorizada:
        if hasattr(autorizada, 'hour'):
            return timezone.localtime(autorizada).date() if timezone.is_aware(autorizada) else autorizada.date()
        return autorizada
    return doc.date_joined


def limite_plazo_sri(fecha):
    """Día 7 del mes siguiente a la emisión (la norma del repo no documenta el paso al siguiente día hábil)."""
    anio, mes = (fecha.year + 1, 1) if fecha.month == 12 else (fecha.year, fecha.month + 1)
    return date(anio, mes, min(7, calendar.monthrange(anio, mes)[1]))


def _fecha(valor):
    if valor is None or isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor).strip())
    except ValueError:
        raise ErrorAnulacion('fecha')


# ------------------------------------------------------------------ revisión (impedimentos, avisos y efectos)

def _requisitos(slug, doc, fecha):
    errores = []
    if slug == 'factura' and doc.receipt.voucher_type == '08':
        return [ErrorAnulacion('ticket')]
    permitidos = AUTORIZADOS + (('canceled',) if slug == 'factura' else ())
    if doc.status not in permitidos:
        errores.append(ErrorAnulacion('no_autorizado'))
    if esta_anulado(doc):
        errores.append(ErrorAnulacion('ya_anulado', fecha=f'{doc.anulado_sri_fecha:%d/%m/%Y}'))
    if fecha is not None:
        if fecha > timezone.localdate():
            errores.append(ErrorAnulacion('fecha_futura'))
        elif fecha < fecha_emision(doc):
            errores.append(ErrorAnulacion('fecha_anterior', fecha=f'{fecha_emision(doc):%d/%m/%Y}'))
    return errores


def _por_estado(documentos, codigo):
    """Impedimento de cada NC o ND no anulada de la factura, según su estado en el SRI."""
    errores = []
    for d in documentos:
        if d.anulado_sri_fecha is not None:
            continue
        if d.status in AUTORIZADOS:
            errores.append(ErrorAnulacion(f'{codigo}_vigente', numero=d.voucher_number_full))
        elif d.status == EN_PROCESO:
            errores.append(ErrorAnulacion(f'{codigo}_en_proceso', numero=d.voucher_number_full))
        else:   # sin enviar, devuelta, no autorizada o con secuencial registrado: se elimina antes
            errores.append(ErrorAnulacion(f'{codigo}_sin_enviar', numero=d.voucher_number_full))
    return errores


def _cobros_vigentes(cuenta):
    from core.pos.models import PaymentsCtaCollect
    total = (PaymentsCtaCollect.objects.filter(ctas_collect=cuenta, tipo='cobro', anulado_en__isnull=True)
             .aggregate(total=Sum('valor'))['total'])
    return Decimal(total or 0)


def _stock_factura(venta):
    """[(producto, cantidad)] que vuelve al inventario: lo vendido menos lo que siguió devuelto por NC anuladas sin ajuste."""
    from core.pos.models import CreditNoteDetail
    devuelto = dict(CreditNoteDetail.objects.filter(sale_detail__sale=venta, credit_note__anulado_sri_fecha__isnull=False,
                                                    credit_note__anulado_sri_stock=False)
                    .values_list('sale_detail_id').annotate(total=Sum('cant')))
    por_producto = {}
    for d in venta.saledetail_set.select_related('product').filter(product__inventoried=True).order_by('id'):
        cantidad = d.cant - (devuelto.get(d.pk) or 0)
        if cantidad > 0:
            producto, acumulado = por_producto.get(d.product_id, (d.product, 0))
            por_producto[d.product_id] = (producto, acumulado + cantidad)
    return list(por_producto.values())


def _stock_nota(nota):
    """[(producto, cantidad)] que se descuenta del inventario al deshacer la devolución de la nota de crédito."""
    por_producto = {}
    for d in nota.creditnotedetail_set.select_related('product').filter(product__inventoried=True).order_by('id'):
        producto, acumulado = por_producto.get(d.product_id, (d.product, 0))
        por_producto[d.product_id] = (producto, acumulado + d.cant)
    return list(por_producto.values())


def _plan(slug, doc, fecha=None):
    """Impedimentos (ErrorAnulacion), avisos, efectos y movimientos previstos. Sin escribir nada."""
    from core.comprobantes.models import GuiaRemision, NotaDebito, Retencion, RetencionRecibida
    from core.pos import cxc
    from core.pos.models import CreditNote, Sale
    from core.pos.notas_credito import es_consumidor_final
    plan = {'impedimentos': _requisitos(slug, doc, fecha), 'avisos': [], 'efectos': [], 'stock': [], 'signo': 1,
            'cxc': None, 'saldo': Decimal('0'), 'abono': None}
    if plan['impedimentos'] and plan['impedimentos'][0].codigo == 'ticket':
        return plan
    if slug == 'factura':
        if es_consumidor_final(doc.client) and fecha_emision(doc) >= CONSUMIDOR_FINAL_NO_ANULABLE_DESDE:
            plan['impedimentos'].append(ErrorAnulacion('consumidor_final'))
        plan['impedimentos'] += _por_estado(CreditNote.objects.filter(sale=doc).order_by('id'), 'nc')
        plan['impedimentos'] += _por_estado(NotaDebito.objects.filter(sale=doc).order_by('id'), 'nd')
        for ret in RetencionRecibida.objects.filter(venta=doc, estado='registrada').order_by('id'):
            plan['impedimentos'].append(ErrorAnulacion('retencion_recibida', numero=ret.numero))
        cuenta = cxc.cxc_de_factura(doc)
        if cuenta is not None:
            cobros = _cobros_vigentes(cuenta)
            if cobros > 0:
                plan['impedimentos'].append(ErrorAnulacion('cobros', valor=_dinero(cobros)))
            saldo = cxc.saldo(cuenta)
            plan.update(cxc=cuenta, saldo=saldo)
            if saldo > 0 and not cxc.tiene_anulacion(cuenta):
                plan['efectos'].append(f'Se registrará un abono de anulación de {_dinero(saldo)} en la cuenta por cobrar.')
        plan['stock'] = _stock_factura(doc)
        for producto, cantidad in plan['stock']:
            plan['efectos'].append(f'Si ajustas el inventario, se devolverán al inventario {cantidad} unidades de {producto.name}.')
        guias = list(GuiaRemision.objects.filter(sale=doc, status__in=AUTORIZADOS, anulado_sri_fecha__isnull=True)
                     .order_by('id').values_list('voucher_number_full', flat=True))
        if guias:
            plan['avisos'].append(AVISOS['guias'].format(numeros=', '.join(guias)))
        plan['efectos'].append('La factura ya no admitirá notas de crédito, notas de débito, guías de remisión ni retenciones '
                               'recibidas nuevas.')
    elif slug == 'nota-credito':
        if doc.cxc_ajuste in ('aplicada', 'parcial') and doc.abono_cxc_id:
            abono = doc.abono_cxc
            if abono.anulado_en is None:
                plan['abono'] = abono
                plan['efectos'].append(f'Se revertirá el abono de {_dinero(abono.valor)} de esta nota en la cuenta por cobrar.')
        plan['stock'], plan['signo'] = _stock_nota(doc), -1
        for producto, cantidad in plan['stock']:
            plan['efectos'].append(f'Si ajustas el inventario, se descontarán del inventario {cantidad} unidades de {producto.name} '
                                   '(se deshace la devolución).')
        venta = Sale.objects.get(pk=doc.sale_id)
        if venta.status == 'canceled':
            otras = (CreditNote.objects.filter(sale_id=doc.sale_id, status__in=AUTORIZADOS, anulado_sri_fecha__isnull=True)
                     .exclude(pk=doc.pk).aggregate(total=Sum('total'))['total'] or Decimal('0'))
            if Decimal(otras) < Decimal(venta.total) - Decimal('0.005'):
                plan['efectos'].append(f'La factura {venta.voucher_number_full} volverá a «Autorizada»: deja de estar cubierta '
                                       'por notas de crédito.')
        plan['efectos'].append('Sus cantidades podrán acreditarse otra vez en la factura.')
    elif slug == 'nota-debito':
        if doc.cuenta_por_cobrar_id:
            cuenta = doc.cuenta_por_cobrar
            cobros = _cobros_vigentes(cuenta)
            if cobros > 0:
                plan['impedimentos'].append(ErrorAnulacion('cobros', valor=_dinero(cobros)))
            saldo = cxc.saldo(cuenta)
            plan.update(cxc=cuenta, saldo=saldo)
            if saldo > 0 and not cxc.tiene_anulacion(cuenta):
                plan['efectos'].append(f'Se registrará un abono de anulación de {_dinero(saldo)} en la cuenta por cobrar de la '
                                       'nota de débito.')
    elif slug == 'retencion':
        plan['efectos'].append('La compra podrá tener una nueva retención.')
    elif slug == 'liquidacion':
        numero = (doc.voucher_number_full or '').replace('-', '')
        for ret in (Retencion.objects.filter(cod_doc_sustento='03', num_doc_sustento=numero, anulado_sri_fecha__isnull=True)
                    .exclude(status__in=NO_CUENTAN).order_by('id')):
            plan['impedimentos'].append(ErrorAnulacion('retencion_sobre_liquidacion', numero=ret.voucher_number_full))
        plan['efectos'].append('La compra volverá a necesitar una liquidación de compra.')
    elif slug == 'guia':
        plan['efectos'].append('Las cantidades de esta guía vuelven a quedar pendientes de traslado.')
    for producto, cantidad in plan['stock']:
        final = producto.stock + plan['signo'] * cantidad
        if final < 0:
            plan['avisos'].append(AVISOS['stock_negativo'].format(producto=producto.name, n=final))
    return plan


def revisar(doc, fecha=None):
    """Lo que pasaría al marcar `doc` (sin escribir nada), para la pantalla de confirmación."""
    fecha = _fecha(fecha)
    plan = _plan(slug_de(doc), doc, fecha)
    limite = limite_plazo_sri(fecha_emision(doc))
    return {'impedimentos': [str(e) for e in plan['impedimentos']], 'avisos': plan['avisos'], 'efectos': plan['efectos'],
            'stock': plan['stock'], 'pide_confirmar_plazo': fecha is not None and fecha > limite, 'limite_plazo': limite}


# ------------------------------------------------------------------ marcar

def _bloquear(slug, doc):
    """Bloqueos en el orden de la especificación (§3.8) y el documento releído bajo bloqueo."""
    from core.comprobantes.models import NotaDebito
    from core.pos import cxc
    from core.pos.models import CreditNote, CtasCollect, PaymentsCtaCollect, Sale
    Modelo = type(doc)
    if slug == 'factura':
        Sale.objects.select_for_update(of=('self',)).filter(pk=doc.pk).values_list('pk', flat=True).get()
        list(CreditNote.objects.select_for_update(of=('self',)).filter(sale_id=doc.pk).order_by('pk').values_list('pk', flat=True))
        list(NotaDebito.objects.select_for_update(of=('self',)).filter(sale_id=doc.pk).order_by('pk').values_list('pk', flat=True))
        cxc.cxc_de_factura(doc.pk, bloquear=True)
    elif slug in ('nota-credito', 'nota-debito'):
        Sale.objects.select_for_update(of=('self',)).filter(pk=doc.sale_id).values_list('pk', flat=True).get()
        Modelo.objects.select_for_update(of=('self',)).filter(pk=doc.pk).values_list('pk', flat=True).get()
        if slug == 'nota-credito':
            fila = Modelo.objects.filter(pk=doc.pk).values_list('abono_cxc_id', flat=True).get()
            cuenta_id = PaymentsCtaCollect.objects.filter(pk=fila).values_list('ctas_collect_id', flat=True).first() if fila else None
        else:
            cuenta_id = Modelo.objects.filter(pk=doc.pk).values_list('cuenta_por_cobrar_id', flat=True).get()
        if cuenta_id:
            CtasCollect.objects.select_for_update(of=('self',)).filter(pk=cuenta_id).values_list('pk', flat=True).get()
    else:
        Modelo.objects.select_for_update(of=('self',)).filter(pk=doc.pk).values_list('pk', flat=True).get()
    return Modelo.objects.get(pk=doc.pk)


def _auditar(request, usuario, company, **detalle):
    from core.tenancy.models import AuditLog, audit
    if request is not None:
        audit(request, 'comprobante_anulado_sri', company=company, **detalle)
    else:
        AuditLog.objects.create(user=usuario, company=company, action='comprobante_anulado_sri', detail=detalle)


def marcar(company, usuario, slug, doc, fecha, motivo, ajustar_stock=False, confirmo_plazo=False, request=None):
    """Marca el comprobante como anulado en el SRI con sus efectos. Devuelve {'efectos': [...], 'avisos': [...]}."""
    from core.pos import cxc
    from core.pos.models import Product
    from core.pos.notas_credito import actualizar_factura
    fecha = _fecha(fecha)
    if fecha is None:
        raise ErrorAnulacion('fecha')
    motivo = ' '.join((motivo or '').split())
    if slug_de(doc) != slug:
        raise Http404('El comprobante no es de ese tipo.')
    with transaction.atomic():
        doc = _bloquear(slug, doc)
        plan = _plan(slug, doc, fecha)
        if plan['impedimentos']:
            raise plan['impedimentos'][0]
        if not 10 <= len(motivo) <= 300:
            raise ErrorAnulacion('motivo')
        limite = limite_plazo_sri(fecha_emision(doc))
        if fecha > limite and not confirmo_plazo:
            raise ErrorAnulacion('plazo_sin_confirmar', limite=f'{limite:%d/%m/%Y}')
        ahora = timezone.now()
        efectos, Modelo = [], type(doc)
        cambios = {'anulado_sri_fecha': fecha, 'anulado_sri_motivo': motivo, 'anulado_sri_por': usuario,
                   'anulado_sri_registrado_en': ahora}
        ajusta = bool(ajustar_stock) and bool(plan['stock'])
        if slug in ('factura', 'nota-credito'):
            cambios['anulado_sri_stock'] = ajusta
        Modelo.objects.filter(pk=doc.pk).update(**cambios)
        for campo, valor in cambios.items():
            setattr(doc, campo, valor)
        if slug in ('factura', 'nota-debito') and plan['cxc'] is not None and plan['saldo'] > 0 \
                and not cxc.tiene_anulacion(plan['cxc']):
            cxc.crear_abono(plan['cxc'], 'anulacion', plan['saldo'], fecha,
                            f'Anulación en el SRI de la {MODELOS[slug][2]} {doc.voucher_number_full}', usuario)
            efectos.append(f'Abono de anulación de {_dinero(plan["saldo"])} en la cuenta por cobrar.')
        if slug == 'nota-debito' and doc.cxc_ajuste == 'aplicada':
            Modelo.objects.filter(pk=doc.pk).update(cxc_ajuste='revertida')
            doc.cxc_ajuste = 'revertida'
        if slug == 'nota-credito':
            if plan['abono'] is not None:
                cxc.revertir_abono(plan['abono'], ahora, f'Nota de crédito {doc.voucher_number_full} anulada en el SRI: {motivo}')
                efectos.append(f'Abono de {_dinero(plan["abono"].valor)} revertido en la cuenta por cobrar.')
            if doc.cxc_ajuste in ('aplicada', 'parcial'):
                Modelo.objects.filter(pk=doc.pk).update(cxc_ajuste='revertida')
                doc.cxc_ajuste = 'revertida'
            antes = type(doc.sale).objects.filter(pk=doc.sale_id).values_list('status', flat=True).get()
            actualizar_factura(doc.sale_id)
            despues = type(doc.sale).objects.filter(pk=doc.sale_id).values_list('status', flat=True).get()
            if antes != despues:
                efectos.append(f'La factura {doc.sale.voucher_number_full} volvió a «Autorizada».')
        if ajusta:
            for producto, cantidad in plan['stock']:
                Product.objects.filter(pk=producto.pk).update(stock=F('stock') + plan['signo'] * cantidad)
                verbo = 'Devueltas al' if plan['signo'] > 0 else 'Descontadas del'
                efectos.append(f'{verbo} inventario {cantidad} unidades de {producto.name}.')
        # Dentro de la transacción: si un receptor (O1: cuenta por pagar, compra de la liquidación) falla, la marca se deshace.
        anulado_en_sri.send(sender=Modelo, instance=doc, usuario=usuario, fecha=fecha)
        _auditar(request, usuario, company, modelo=slug, id=int(doc.pk), numero=doc.voucher_number_full,
                 fecha=fecha.isoformat(), motivo=motivo, ajustar_stock=ajusta, confirmo_plazo=bool(confirmo_plazo),
                 efectos=[str(e) for e in efectos])
        return {'efectos': efectos, 'avisos': plan['avisos']}
