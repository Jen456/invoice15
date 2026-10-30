"""Cuentas por pagar: pagos con medio de pago y referencia, saldo en Decimal y borrados auditados (espec-etapa2-compras §3.2).

- El saldo es deuda − pagos − abonos (DebtsPay.recalcular). Los abonos (retenciones emitidas que cuentan y notas de
  crédito del proveedor) se calculan, no se guardan: no hay filas que duplicar ni borrar si una retención cambia.
- Una cuenta con base «subtotal» (anterior a la Etapa 2) nunca recibe abonos automáticos (DC6).
- Borrar un pago exige el permiso delete_debts_pay del perfil (hoy bastaba con ver la lista): Contador y Consulta no.
- Preparado para la Etapa 3: registrar_pago reserva el parámetro `cuenta` (cuenta bancaria), hoy siempre None.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from core.pos.choices import MEDIOS_DE_PAGO
from core.pos.compras import dinero, para_auditoria


class ErrorPago(Exception):
    """Mensaje para el usuario."""


class SinPermiso(ErrorPago):
    """El perfil no tiene el permiso necesario: la vista responde 403."""


def _auditar(request, accion, company, **detalle):
    from core.tenancy.models import audit
    audit(request, accion, company, **{k: para_auditoria(v) for k, v in detalle.items()})


def _valor(valor):
    texto = '' if valor is None else str(valor).strip()
    if ',' in texto and '.' not in texto:
        texto = texto.replace(',', '.')
    try:
        numero = valor if isinstance(valor, Decimal) else Decimal(texto)
    except InvalidOperation:
        raise ErrorPago('Escribe el valor del pago.')
    if not numero.is_finite() or numero <= 0:
        raise ErrorPago('El valor del pago debe ser mayor que cero.')
    if numero != numero.quantize(Decimal('0.01')):
        raise ErrorPago('El valor del pago admite hasta 2 decimales.')
    return numero.quantize(Decimal('0.01'))


def _fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor or '').strip()[:10])
    except ValueError:
        raise ErrorPago('Escribe la fecha del pago (AAAA-MM-DD).')


def registrar_pago(deuda_id, usuario, *, fecha, valor, medio_pago, referencia='', descripcion='', cuenta=None):
    """Registra un pago de la cuenta por pagar (bloqueada) y recalcula su saldo. Firma paralela a cxc.registrar_cobro."""
    from core.pos.models import DebtsPay, PaymentsDebtsPay
    if cuenta is not None:
        raise ErrorPago('Las cuentas bancarias llegan en la Etapa 3.')
    valor = _valor(valor)
    medio_pago = (medio_pago or '').strip()
    if not medio_pago:
        raise ErrorPago('Elige el medio de pago.')
    if medio_pago not in dict(MEDIOS_DE_PAGO):
        raise ErrorPago('Medio de pago no válido.')
    referencia = ' '.join((referencia or '').split())
    if len(referencia) > 100:
        raise ErrorPago('La referencia admite hasta 100 caracteres.')
    if medio_pago == 'cheque' and not referencia:
        raise ErrorPago('Escribe el número del cheque.')
    fecha = _fecha(fecha)
    if fecha > timezone.localdate():
        raise ErrorPago('La fecha del pago no puede ser futura.')
    with transaction.atomic():
        deuda = DebtsPay.objects.select_for_update(of=('self',)).filter(pk=deuda_id).first()
        if deuda is None:
            raise ErrorPago('La cuenta por pagar no existe.')
        if fecha < deuda.date_joined:
            raise ErrorPago(f'La fecha del pago no puede ser anterior a la de la cuenta por pagar ({deuda.date_joined:%d/%m/%Y}).')
        saldo = deuda.recalcular(guardar=False)
        if valor > saldo:
            raise ErrorPago(f'El pago ({dinero(valor)}) supera el saldo pendiente ({dinero(saldo)}).')
        pago = PaymentsDebtsPay(debts_pay=deuda, date_joined=fecha, valor=valor, medio_pago=medio_pago, referencia=referencia,
                                description=(descripcion or '').strip()[:500],
                                registrado_por=usuario if getattr(usuario, 'pk', None) else None,
                                registrado_en=timezone.now())
        pago.save()
        deuda.recalcular()
    return pago


def puede_eliminar(request):
    """True si el perfil del usuario en la empresa activa tiene delete_debts_pay."""
    from core.security.session import get_group
    grupo = get_group(request)
    return grupo is not None and grupo.permissions.filter(codename='delete_debts_pay').exists()


def eliminar_pago(request, pago_id):
    """Borra un pago (exige delete_debts_pay), auditado (debt_payment_delete), y recalcula el saldo."""
    from core.pos.models import DebtsPay, PaymentsDebtsPay
    if not puede_eliminar(request):
        raise SinPermiso('Tu perfil no puede eliminar pagos.')
    with transaction.atomic():
        pago = PaymentsDebtsPay.objects.filter(pk=pago_id).first()
        if pago is None:
            raise ErrorPago('El pago no existe.')
        deuda = DebtsPay.objects.select_for_update(of=('self',)).filter(pk=pago.debts_pay_id).first()
        pago = PaymentsDebtsPay.objects.filter(pk=pago_id).first()     # pudo borrarse mientras se esperaba el bloqueo
        if deuda is None or pago is None:
            raise ErrorPago('El pago no existe.')
        _auditar(request, 'debt_payment_delete', deuda.company, deuda=deuda.pk, pago=pago.pk, valor=Decimal(pago.valor),
                 fecha=pago.date_joined, medio_pago=pago.medio_pago, referencia=pago.referencia)
        pago.delete()
        deuda.recalcular()


def eliminar_deuda(request, deuda_id):
    """Borra una cuenta por pagar sin pagos ni abonos, auditado (debt_delete). Antes se borraba en cascada con sus pagos."""
    from core.pos.models import DebtsPay, PaymentsDebtsPay
    if not puede_eliminar(request):
        raise SinPermiso('Tu perfil no puede eliminar cuentas por pagar.')
    with transaction.atomic():
        deuda = DebtsPay.objects.select_for_update(of=('self',)).filter(pk=deuda_id).first()
        if deuda is None:
            raise ErrorPago('La cuenta por pagar no existe.')
        if PaymentsDebtsPay.objects.filter(debts_pay=deuda).exists():
            raise ErrorPago('Tiene pagos registrados: elimínalos primero.')
        if deuda.abonos():
            raise ErrorPago('Tiene retenciones o notas de crédito aplicadas.')
        _auditar(request, 'debt_delete', deuda.company, deuda=deuda.pk, compra=deuda.purchase_id, debt=Decimal(deuda.debt),
                 saldo=Decimal(deuda.saldo))
        deuda.delete()


def recalcular_de_compra(compra_id, company_id):
    """Recalcula (con bloqueo) las cuentas por pagar de una compra. Idempotente; transacción propia (receptores de señales)."""
    from core.pos.models import DebtsPay
    with transaction.atomic():
        for deuda in DebtsPay.all_companies.select_for_update(of=('self',)).filter(purchase_id=compra_id,
                                                                                    company_id=company_id).order_by('pk'):
            deuda.recalcular()
