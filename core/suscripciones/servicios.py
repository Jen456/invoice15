"""Reglas de negocio de los planes: estado de la empresa, renovación y pagos.

- Sin plan pagado: inventario con los límites del plan «gratuito».
- Con plan vigente: facturación y ventas; el cupo se descuenta solo con
  comprobantes AUTORIZADOS en producción (ver cupo.py).
- Renovación sin prorrateo (D6): la anticipada empieza al terminar el período
  actual; con el Plan 1000 agotado se puede renovar o mejorar al instante; la
  mejora a ilimitado puede ser inmediata o al vencer; la bajada solo al vencer;
  sin días de gracia.
- Un pago solo activa el plan cuando PayPhone lo confirma desde el servidor;
  importe, moneda y referencia se comprueban contra lo guardado al prepararlo.
"""
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from core.suscripciones import payphone
from core.suscripciones.models import IvaRate, Payment, PaymentEvent, Plan, SubscriptionPeriod
from core.suscripciones.reglas import (DIAS_AVISO_VENCIMIENTO, LIMITES_GRATUITO_POR_DEFECTO, MINUTOS_PAGO_PENDIENTE,
                                       PLAN_GRATUITO, PORCENTAJE_AVISO_CUPO, sumar_meses)

logger = logging.getLogger(__name__)

PRODUCCION = 2
ESTADOS_CONFIRMABLES = ('creado', 'redirigido', 'error_comunicacion', 'expirado')


class ReglaPlan(Exception):
    """Operación no permitida por las reglas del plan (mensaje para el usuario)."""


# ---------------------------------------------------------------- estado

def periodo_vigente(company, ahora=None, bloquear=False):
    """Período pagado en curso (o None). Activa el programado cuando llega su fecha."""
    ahora = ahora or timezone.now()
    queryset = SubscriptionPeriod.objects.filter(company=company, status__in=('activa', 'programada'),
                                                 starts_at__lte=ahora, ends_at__gt=ahora)
    if bloquear:
        queryset = queryset.select_for_update()
    periodo = queryset.order_by('-starts_at', '-id').first()
    if periodo is not None and periodo.status == 'programada':
        periodo.status = 'activa'
        periodo.save(update_fields=['status'])
    return periodo


@dataclass
class EstadoPlan:
    codigo: str                 # gratuito | activa | cupo_agotado | vencida
    periodo: SubscriptionPeriod = None
    programado: SubscriptionPeriod = None
    ultimo: SubscriptionPeriod = None
    produccion: bool = False
    ahora: object = None

    @property
    def pagado(self):
        return self.periodo is not None

    @property
    def puede_emitir(self):
        return self.codigo == 'activa'

    @property
    def gratuito(self):
        return self.codigo == 'gratuito'

    @property
    def vencido(self):
        return self.codigo == 'vencida'

    @property
    def dias_restantes(self):
        if self.periodo is None:
            return None
        return max((self.periodo.ends_at - self.ahora).days, 0)

    @property
    def por_vencer(self):
        return self.periodo is not None and self.programado is None and self.dias_restantes <= DIAS_AVISO_VENCIMIENTO

    @property
    def cupo_bajo(self):
        p = self.periodo
        if p is None or p.document_limit is None or self.codigo == 'cupo_agotado':
            return False
        return p.available * 100 <= p.document_limit * PORCENTAJE_AVISO_CUPO

    @property
    def nombre(self):
        if self.periodo is not None:
            return self.periodo.plan.name
        return 'Plan gratuito' if self.codigo == 'gratuito' else 'Plan vencido'


def estado_empresa(company, ahora=None):
    ahora = ahora or timezone.now()
    produccion = company.environment_type == PRODUCCION
    periodo = periodo_vigente(company, ahora)
    if periodo is not None:
        programado = SubscriptionPeriod.objects.filter(company=company, status='programada', starts_at__gt=ahora) \
            .select_related('plan').order_by('starts_at').first()
        agotado = produccion and periodo.document_limit is not None and periodo.available == 0
        return EstadoPlan('cupo_agotado' if agotado else 'activa', periodo, programado, None, produccion, ahora)
    ultimo = SubscriptionPeriod.objects.filter(company=company, status__in=('activa', 'reemplazada'),
                                               ends_at__lte=ahora).select_related('plan').order_by('-ends_at').first()
    return EstadoPlan('vencida' if ultimo else 'gratuito', None, None, ultimo, produccion, ahora)


def estado_de_peticion(request):
    """Estado de la empresa activa, calculado una vez por petición."""
    if not hasattr(request, '_fpa_estado_plan'):
        company = getattr(request, 'company', None)
        request._fpa_estado_plan = estado_empresa(company) if company is not None else None
    return request._fpa_estado_plan


def tiene_plan(company):
    return periodo_vigente(company) is not None


def limites_gratuito():
    plan = Plan.objects.filter(code=PLAN_GRATUITO).first()
    if plan is None:
        return dict(LIMITES_GRATUITO_POR_DEFECTO)
    return {'product_limit': plan.product_limit, 'provider_limit': plan.provider_limit,
            'purchase_limit_month': plan.purchase_limit_month}


def planes_de_pago():
    return Plan.objects.filter(is_active=True, includes_billing=True, price_cents__gt=0)


# ---------------------------------------------------------------- reglas de renovación (D6)

def _documentos(limite):
    return float('inf') if limite is None else limite


def _modos(actual, agotado, plan):
    """Modos permitidos para contratar `plan` con el período `actual` en curso."""
    if actual is None or agotado:
        return ['inmediato']
    if _documentos(plan.document_limit) > _documentos(actual.document_limit):
        return ['inmediato', 'programado']   # mejora: ahora o al vencer
    return ['programado']                    # renovación anticipada o bajada: al vencer


def modos_de_pago(company, plan, ahora=None):
    """Modos permitidos para un pago nuevo; ReglaPlan si no se puede contratar."""
    if not plan.is_active or not plan.includes_billing or plan.price_cents <= 0:
        raise ReglaPlan('Ese plan no está disponible.')
    estado = estado_empresa(company, ahora)
    if estado.programado is not None:
        raise ReglaPlan(f'Ya tienes el {estado.programado.plan.name} programado desde el '
                        f'{timezone.localtime(estado.programado.starts_at):%d/%m/%Y}. '
                        'Podrás contratar otro cuando empiece.')
    return _modos(estado.periodo, estado.codigo == 'cupo_agotado', plan)


def fechas_del_nuevo_periodo(company, plan, modo, ahora=None):
    """(inicio, fin) que tendría un período nuevo; sirve para mostrarlo antes de pagar."""
    ahora = ahora or timezone.now()
    inicio = ahora
    if modo == 'programado':
        ultimo_fin = SubscriptionPeriod.objects.filter(company=company, status__in=('activa', 'programada'),
                                                       ends_at__gt=ahora).order_by('-ends_at').values_list('ends_at', flat=True).first()
        inicio = ultimo_fin or ahora
    return inicio, sumar_meses(inicio, plan.months)


# ---------------------------------------------------------------- pagos

def _evento(pago, tipo, **detalle):
    PaymentEvent.objects.create(payment=pago, kind=tipo, detail=detalle)


def nuevo_pago(company, plan, usuario, modo, metodo='payphone', ahora=None):
    """Crea el pago con el precio y el IVA del servidor (nunca del navegador)."""
    ahora = ahora or timezone.now()
    tarifa = IvaRate.current(timezone.localdate(ahora))
    if tarifa is None:
        raise ReglaPlan('No hay una tarifa de IVA vigente configurada.')
    base, iva = IvaRate.breakdown(plan.price_cents, tarifa.rate)
    prefijo = 'FPA' if metodo == 'payphone' else 'MAN'
    pago = Payment.objects.create(
        company=company, plan=plan, user=usuario, method=metodo, mode=modo,
        client_tx_id=f'{prefijo}{company.pk}-{secrets.token_hex(8)}',
        amount_cents=plan.price_cents, base_cents=base, iva_cents=iva, iva_rate=tarifa.rate, currency='USD',
        created_at=ahora,
    )
    _evento(pago, 'creado', plan=plan.code, modo=modo, total=plan.price_cents, base=base, iva=iva,
            tarifa=str(tarifa.rate))
    return pago


def iniciar_pago_payphone(company, plan, usuario, modo, url_respuesta, url_cancelacion):
    """Prepara el cobro en PayPhone y devuelve (pago, enlace al formulario de pago)."""
    if modo not in modos_de_pago(company, plan):
        raise ReglaPlan('Esa forma de inicio no está disponible para este plan.')
    recientes = Payment.objects.filter(company=company, created_at__gte=timezone.now() - timedelta(minutes=10)).count()
    if recientes >= 5:
        raise ReglaPlan('Demasiados intentos de pago seguidos. Espera unos minutos y vuelve a intentarlo.')
    pago = nuevo_pago(company, plan, usuario, modo)
    referencia = f'FacturaPorAqui {plan.name} - RUC {company.ruc}'
    url_cancelacion = f'{url_cancelacion}?ref={pago.client_tx_id}'
    try:
        datos = payphone.preparar(pago, url_respuesta, url_cancelacion, referencia)
    except (payphone.PayPhoneError, payphone.PayPhoneSinRespuesta, payphone.PayPhoneNoConfigurado) as e:
        pago.status = 'error_comunicacion' if isinstance(e, payphone.PayPhoneSinRespuesta) else 'rechazado'
        pago.note = f'No se pudo preparar el cobro: {e}'[:300]
        pago.save(update_fields=['status', 'note'])
        _evento(pago, 'preparar_error', tipo=type(e).__name__, mensaje=str(e)[:200])
        raise ReglaPlan('No pudimos conectar con PayPhone. Inténtalo de nuevo en unos minutos.') from None
    pago.status = 'redirigido'
    pago.payphone_payment_id = str(datos.get('paymentId', ''))[:60]
    pago.redirected_at = timezone.now()
    pago.save(update_fields=['status', 'payphone_payment_id', 'redirected_at'])
    _evento(pago, 'redirigido', paymentId=pago.payphone_payment_id)
    return pago, datos['payWithCard']


def confirmar_pago(client_tx_id, transaccion_id):
    """Confirma con PayPhone el resultado de un pago y, si es correcto, activa el plan.

    Idempotente: un pago ya resuelto se devuelve tal cual. Devuelve el pago o
    None si la referencia no existe.
    """
    try:
        transaccion_id = int(transaccion_id)
    except (TypeError, ValueError):
        return None
    with transaction.atomic():
        pago = Payment.objects.select_for_update().filter(client_tx_id=client_tx_id, method='payphone').first()
        if pago is None or pago.status not in ESTADOS_CONFIRMABLES:
            return pago
        try:
            datos = payphone.confirmar(transaccion_id, client_tx_id)
        except payphone.PayPhoneSinRespuesta as e:
            pago.status = 'error_comunicacion'
            pago.save(update_fields=['status'])
            _evento(pago, 'confirmar_sin_respuesta', transaccion=transaccion_id, error=str(e)[:200])
            return pago
        except payphone.PayPhoneError as e:
            # Transacción inexistente o ajena: no cambia el estado (podría ser un enlace manipulado).
            _evento(pago, 'confirmar_rechazado', transaccion=transaccion_id, codigo=e.codigo, mensaje=str(e)[:200])
            return pago
        _evento(pago, 'confirmacion', **payphone.saneado(datos))
        estado = datos.get('statusCode')
        if estado == 2:
            pago.status = 'cancelado'
            pago.confirmed_at = timezone.now()
            pago.save(update_fields=['status', 'confirmed_at'])
            return pago
        if estado != 3:
            pago.status = 'rechazado'
            pago.note = str(datos.get('message') or f'statusCode {estado}')[:300]
            pago.save(update_fields=['status', 'note'])
            return pago
        tx = str(datos.get('transactionId') or '')
        problemas = []
        if datos.get('transactionStatus') != 'Approved':
            problemas.append(f"transactionStatus={datos.get('transactionStatus')}")
        if str(datos.get('clientTransactionId')) != pago.client_tx_id:
            problemas.append('la referencia no coincide')
        if datos.get('amount') != pago.amount_cents:
            problemas.append(f"importe {datos.get('amount')} distinto de {pago.amount_cents}")
        if datos.get('currency') not in (None, '', pago.currency):
            problemas.append(f"moneda {datos.get('currency')}")
        if tx != str(transaccion_id):
            problemas.append('el identificador de transacción no coincide')
        if not tx or Payment.objects.filter(payphone_transaction_id=tx).exclude(pk=pago.pk).exists():
            problemas.append('transacción ya usada en otro pago')
        else:
            pago.payphone_transaction_id = tx
        pago.authorization_code = str(datos.get('authorizationCode') or '')[:60]
        pago.card_brand = str(datos.get('cardBrand') or '')[:40]
        pago.last_digits = str(datos.get('lastDigits') or '')[-4:]
        pago.confirmed_at = timezone.now()
        if problemas:
            pago.status = 'en_revision'
            pago.note = ('Revisar: ' + '; '.join(problemas))[:300]
            pago.save()
            _evento(pago, 'en_revision', problemas=problemas)
            transaction.on_commit(lambda: notificar_revision(pago.pk))
            return pago
        pago.status = 'aprobado'
        pago.save()
        activar_periodo(pago)
        transaction.on_commit(lambda: notificar_pago_aprobado(pago.pk))
        return pago


def activar_periodo(pago, ahora=None):
    """Crea el período pagado por `pago` aplicando las reglas de renovación."""
    from core.pos.models import Company
    ahora = ahora or timezone.now()
    Company.objects.select_for_update().filter(pk=pago.company_id).first()   # serializa por empresa
    company = pago.company
    plan = pago.plan
    actual = periodo_vigente(company, ahora, bloquear=True)
    agotado = actual is not None and actual.document_limit is not None and actual.available == 0
    modo = pago.mode if pago.mode in _modos(actual, agotado, plan) else 'programado'
    if modo == 'inmediato':
        if actual is not None:
            actual.status = 'reemplazada'
            actual.replaced_at = ahora
            actual.save(update_fields=['status', 'replaced_at'])
        inicio = ahora
    else:
        inicio, _ = fechas_del_nuevo_periodo(company, plan, 'programado', ahora)
    fin = sumar_meses(inicio, plan.months)
    periodo = SubscriptionPeriod.objects.create(
        company=company, plan=plan, payment=pago, status='activa' if inicio <= ahora else 'programada',
        starts_at=inicio, ends_at=fin, document_limit=plan.document_limit,
        note=f'Pago {pago.client_tx_id}' + ('' if modo == pago.mode else ' (encadenado al período en curso)'),
    )
    if modo == 'inmediato':
        # Un período ya programado pasa a empezar cuando termine el nuevo.
        for siguiente in SubscriptionPeriod.objects.filter(company=company, status='programada').exclude(pk=periodo.pk).order_by('starts_at'):
            siguiente.starts_at = fin
            siguiente.ends_at = sumar_meses(fin, siguiente.plan.months)
            siguiente.save(update_fields=['starts_at', 'ends_at'])
            fin = siguiente.ends_at
    if modo != pago.mode:
        pago.mode = modo
        pago.save(update_fields=['mode'])
    _evento(pago, 'periodo_activado', periodo=periodo.pk, inicio=periodo.starts_at.isoformat(),
            fin=periodo.ends_at.isoformat(), modo=modo)
    return periodo


def activar_manual(company, plan, usuario, modo, nota):
    """Activación desde la plataforma (pago recibido por otro medio). Queda auditada."""
    with transaction.atomic():
        pago = nuevo_pago(company, plan, usuario, modo, metodo='manual')
        pago.status = 'aprobado'
        pago.confirmed_at = timezone.now()
        pago.note = nota[:300]
        pago.save(update_fields=['status', 'confirmed_at', 'note'])
        periodo = activar_periodo(pago)
    return pago, periodo


def cancelar_por_usuario(pago):
    """El usuario cerró el formulario de PayPhone (sin pago)."""
    with transaction.atomic():
        pago = Payment.objects.select_for_update().get(pk=pago.pk)
        if pago.status in ('creado', 'redirigido'):
            pago.status = 'cancelado'
            pago.save(update_fields=['status'])
            _evento(pago, 'cancelado_por_usuario')
    return pago


def vencer_pendientes(ahora=None):
    """Pagos que nunca volvieron de PayPhone (el formulario dura 10 minutos)."""
    ahora = ahora or timezone.now()
    limite = ahora - timedelta(minutes=MINUTOS_PAGO_PENDIENTE)
    return Payment.objects.filter(status__in=('creado', 'redirigido'), created_at__lt=limite).update(status='expirado')


def solicitar_factura(pago, datos):
    """D8: la factura de la suscripción la emite la plataforma a mano cuando se pide."""
    pago.invoice_requested = True
    pago.invoice_data = datos
    pago.save(update_fields=['invoice_requested', 'invoice_data'])
    _evento(pago, 'factura_solicitada')
    transaction.on_commit(lambda: notificar_factura_solicitada(pago.pk))


# ---------------------------------------------------------------- avisos por correo

def _enviar(asunto, cuerpo, destinatarios):
    destinatarios = [d for d in destinatarios if d]
    if not destinatarios or not settings.EMAIL_HOST_USER and settings.EMAIL_BACKEND.endswith('smtp.EmailBackend'):
        logger.info('Aviso sin enviar (sin buzón configurado): %s', asunto)
        return
    try:
        send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, destinatarios)
    except Exception as e:  # el aviso nunca debe deshacer un pago ya confirmado
        logger.warning('No se pudo enviar el aviso «%s»: %s', asunto, type(e).__name__)


def _resumen(pago):
    return (f'Empresa: {pago.company.business_name} (RUC {pago.company.ruc})\n'
            f'Plan: {pago.plan.name}\nTotal: ${pago.amount:.2f} (base ${pago.base:.2f} + IVA {pago.iva_rate}% ${pago.iva:.2f})\n'
            f'Referencia: {pago.client_tx_id}\nTransacción PayPhone: {pago.payphone_transaction_id or "-"}\n')


def notificar_pago_aprobado(pago_id):
    pago = Payment.objects.select_related('company', 'plan', 'user').get(pk=pago_id)
    periodo = getattr(pago, 'period', None)
    vigencia = ''
    if periodo is not None:
        vigencia = (f'Vigencia: {timezone.localtime(periodo.starts_at):%d/%m/%Y} al '
                    f'{timezone.localtime(periodo.ends_at):%d/%m/%Y}\n')
    cuerpo = _resumen(pago) + vigencia
    if pago.user is not None and pago.user.email:
        _enviar(f'Pago recibido: {pago.plan.name} de FacturaPorAquí',
                'Gracias. Recibimos tu pago y tu plan ya está registrado.\n\n' + cuerpo +
                '\nSi necesitas factura por la suscripción, solicítala desde «Plan y pagos».', [pago.user.email])
    _enviar(f'[FacturaPorAquí] Pago aprobado {pago.client_tx_id}', cuerpo, [settings.FPA_CORREO_FACTURACION])


def notificar_revision(pago_id):
    pago = Payment.objects.select_related('company', 'plan').get(pk=pago_id)
    _enviar(f'[FacturaPorAquí] Pago EN REVISIÓN {pago.client_tx_id}',
            _resumen(pago) + f'\nMotivo: {pago.note}\nRevísalo en /plataforma/ antes de 24 h '
            '(PayPhone solo permite reversar el mismo día).', [settings.FPA_CORREO_FACTURACION])


def notificar_factura_solicitada(pago_id):
    pago = Payment.objects.select_related('company', 'plan').get(pk=pago_id)
    datos = '\n'.join(f'{k}: {v}' for k, v in pago.invoice_data.items())
    _enviar(f'[FacturaPorAquí] Factura solicitada {pago.client_tx_id}',
            _resumen(pago) + '\nDatos para la factura:\n' + datos, [settings.FPA_CORREO_FACTURACION])
