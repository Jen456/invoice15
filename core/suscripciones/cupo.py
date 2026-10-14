"""Cupo de comprobantes (D5).

Al emitir se reserva un documento del período vigente; solo se consume cuando
el SRI responde AUTORIZADO. Un rechazo o un error lo libera; mientras el SRI lo
tiene «En proceso» la reserva se mantiene hasta que responda. Un comprobante
tiene como máximo una reserva (reintentar no descuenta dos veces) y uno ya
autorizado no vuelve a contar. Las anulaciones siguen contando. En el ambiente
de PRUEBAS del SRI se exige plan vigente, pero no se descuenta nada.
"""
from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

from core.suscripciones.models import QuotaReservation, SubscriptionPeriod
from core.suscripciones.servicios import PRODUCCION, periodo_vigente

AUTORIZADOS = ('authorized', 'authorized_and_sent_by_email')
EN_PROCESO = 'in_process'


class PlanRequerido(Exception):
    """No hay plan vigente o no queda cupo (mensaje para el usuario)."""


def _clave(comprobante):
    return comprobante._meta.label_lower


def reservar(periodo, comprobante):
    """Reserva un documento para `comprobante`; None si ya estaba autorizado y contado."""
    reserva = QuotaReservation.objects.select_for_update().filter(
        company_id=comprobante.company_id, voucher_model=_clave(comprobante), voucher_id=comprobante.pk).first()
    if reserva is not None and reserva.status == 'consumida':
        return None
    if reserva is not None and reserva.status == 'reservada':
        return reserva
    if periodo.available is not None and periodo.available <= 0:
        raise PlanRequerido(f'Usaste los {periodo.document_limit} documentos de tu {periodo.plan.name}. '
                            'Renueva o pasa al plan ilimitado en «Plan y pagos» para seguir emitiendo.')
    SubscriptionPeriod.objects.filter(pk=periodo.pk).update(documents_reserved=F('documents_reserved') + 1)
    if reserva is None:
        reserva = QuotaReservation.objects.create(
            company_id=comprobante.company_id, period=periodo, voucher_model=_clave(comprobante),
            voucher_id=comprobante.pk, voucher_label=getattr(comprobante, 'voucher_number_full', '')[:40])
    else:
        reserva.status, reserva.period, reserva.released_at = 'reservada', periodo, None
        reserva.save(update_fields=['status', 'period', 'released_at'])
    return reserva


def _cerrar(reserva, estado):
    with transaction.atomic():
        reserva = QuotaReservation.objects.select_for_update().get(pk=reserva.pk)
        if reserva.status != 'reservada':
            return reserva
        cambios = {'documents_reserved': Greatest(F('documents_reserved') - 1, 0)}
        if estado == 'consumida':
            cambios['documents_used'] = F('documents_used') + 1
            reserva.consumed_at = timezone.now()
        else:
            reserva.released_at = timezone.now()
        SubscriptionPeriod.objects.filter(pk=reserva.period_id).update(**cambios)
        reserva.status = estado
        reserva.save(update_fields=['status', 'consumed_at', 'released_at'])
    return reserva


def consumir(reserva):
    return _cerrar(reserva, 'consumida')


def liberar(reserva):
    return _cerrar(reserva, 'liberada')


def verificar_disponible(comprobante):
    """Antes de guardar un comprobante: plan vigente y, en Producción, cupo (sin bloquear; se reserva al enviar).

    Así una venta sin cupo se deshace entera en vez de quedar guardada sin poder enviarse.
    """
    periodo = periodo_vigente(comprobante.company)
    if periodo is None:
        raise PlanRequerido('Para emitir comprobantes electrónicos activa un plan en «Plan y pagos».')
    if comprobante.environment_type == PRODUCCION and periodo.available is not None and periodo.available <= 0:
        raise PlanRequerido(f'Usaste los {periodo.document_limit} documentos de tu {periodo.plan.name}. '
                            'Renueva o pasa al plan ilimitado en «Plan y pagos» para seguir emitiendo.')


def emitir_con_cupo(comprobante, emitir):
    """Envuelve la emisión electrónica de una venta o nota de crédito.

    Si la vista ya está dentro de una transacción, deshacerla también deshace
    la reserva; si no, la reserva se libera aquí cuando la emisión no termina
    autorizada.
    """
    company = comprobante.company
    with transaction.atomic():
        periodo = periodo_vigente(company, bloquear=True)
        if periodo is None:
            raise PlanRequerido('Para emitir comprobantes electrónicos activa un plan en «Plan y pagos».')
        reserva = reservar(periodo, comprobante) if comprobante.environment_type == PRODUCCION else None
    try:
        resultado = emitir()
    except BaseException:
        if reserva is not None:
            liberar(reserva)
        raise
    if reserva is not None:
        if comprobante.status in AUTORIZADOS:
            consumir(reserva)
        elif comprobante.status != EN_PROCESO:
            liberar(reserva)
    return resultado


def cerrar_segun_estado(comprobante):
    """Tras consultar un comprobante en proceso: consume si quedó autorizado y libera si el SRI lo rechazó.

    Un autorizado siempre cuenta, aunque su reserva se hubiera liberado (por ejemplo, si la petición que lo
    envió terminó con un error después de que el SRI lo recibiera).
    """
    if comprobante.environment_type != PRODUCCION or comprobante.status == EN_PROCESO:
        return
    reserva = QuotaReservation.objects.filter(company_id=comprobante.company_id, voucher_model=_clave(comprobante),
                                              voucher_id=comprobante.pk).first()
    if comprobante.status in AUTORIZADOS:
        if reserva is not None and reserva.status == 'consumida':
            return
        if reserva is None or reserva.status == 'liberada':
            with transaction.atomic():
                periodo = periodo_vigente(comprobante.company, bloquear=True)
                if periodo is None:
                    return
                SubscriptionPeriod.objects.filter(pk=periodo.pk).update(documents_reserved=F('documents_reserved') + 1)
                if reserva is None:
                    reserva = QuotaReservation.objects.create(
                        company_id=comprobante.company_id, period=periodo, voucher_model=_clave(comprobante),
                        voucher_id=comprobante.pk, voucher_label=getattr(comprobante, 'voucher_number_full', '')[:40])
                else:
                    reserva.status, reserva.period, reserva.released_at = 'reservada', periodo, None
                    reserva.save(update_fields=['status', 'period', 'released_at'])
        consumir(reserva)
    elif reserva is not None and reserva.status == 'reservada':
        liberar(reserva)


def liberar_de_comprobante(comprobante):
    """Al borrar un comprobante sin autorizar, su reserva pendiente vuelve al cupo."""
    reserva = QuotaReservation.objects.filter(company_id=comprobante.company_id, voucher_model=_clave(comprobante),
                                              voucher_id=comprobante.pk, status='reservada').first()
    if reserva is not None:
        liberar(reserva)
