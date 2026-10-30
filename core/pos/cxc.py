"""Cuentas por cobrar (Etapa 2, O2): saldo con abonos vigentes, cobros con medio de pago y ajuste por notas de crédito y
de débito al autorizarse.

- Saldo = deuda − abonos vigentes (anulado_en nulo). Los abonos automáticos (nota de crédito, retención recibida,
  anulación en el SRI) no se borran: se anulan con fecha y motivo y la cuenta conserva su historia. Solo los cobros
  manuales se eliminan, con el permiso de eliminar del rol y auditados.
- La nota de crédito autorizada abona la CxC de su factura (hasta su saldo); la nota de débito autorizada crea su propia
  CxC, con sale = la factura modificada. Lo hacen los receptores de comprobante_autorizado (core/comprobantes/
  receptores.py); son idempotentes (la emisión vuelve a enviar la señal al reenviar o consultar).
- Excedentes: la NC o la retención que encontró poco saldo abona solo hasta el saldo ('parcial' / 'sin_saldo'). Si el
  saldo vuelve a subir (se elimina un cobro o se revierte otro abono), aplicar_excedentes abona lo que faltaba, en orden
  de fecha; así la CxC cuadra en cualquier orden de las operaciones.
- Importes en Decimal con 2 decimales y ROUND_HALF_UP; nada de float.
- Bloqueos: select_for_update(of=('self',)) y sin select_related (en PostgreSQL, FOR UPDATE con un LEFT OUTER JOIN falla
  y con un INNER JOIN bloquea también la fila unida). Orden: Sale → CreditNote / NotaDebito / RetencionRecibida →
  CtasCollect → PaymentsCtaCollect.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import DecimalField, Exists, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.pos.choices import MEDIOS_DE_PAGO

CENTAVO = Decimal('0.01')
AUTORIZADOS = ('authorized', 'authorized_and_sent_by_email')

MENSAJES = {
    'valor': 'El valor debe ser mayor que cero.',
    'valor_excede': 'El valor ({valor}) supera el saldo de la cuenta por cobrar ({saldo}).',
    'fecha': 'Escribe la fecha del cobro (AAAA-MM-DD).',
    'fecha_futura': 'La fecha del cobro no puede ser futura.',
    'fecha_anterior': 'La fecha del cobro no puede ser anterior a la venta ({fecha}).',
    'medio_pago': 'Elige el medio de pago.',
    'referencia_cheque': 'Escribe el número del cheque en «Referencia».',
    'cxc_saldada': 'Esta cuenta por cobrar ya no tiene saldo.',
    'cxc_anulada': 'Esta cuenta por cobrar es de un comprobante anulado en el SRI.',
    'no_existe': 'El cobro ya no existe: actualiza la página.',
    'no_es_cobro': 'Este abono lo generó una nota de crédito, una retención o una anulación: se revierte anulando ese '
                   'documento, no aquí.',
    'sin_permiso_eliminar': 'Tu perfil no puede eliminar cobros.',
    'cxc_con_automaticos': 'Esta cuenta por cobrar tiene abonos de notas de crédito, retenciones o anulaciones, o es de una '
                           'nota de débito: no se puede eliminar.',
    'cxc_con_cobros': 'Esta cuenta por cobrar tiene cobros registrados: elimínalos antes de eliminarla.',
}


class ErrorCxC(Exception):
    """Mensaje para el usuario (texto de MENSAJES[codigo])."""

    def __init__(self, codigo, **datos):
        super().__init__(MENSAJES[codigo].format(**datos))
        self.codigo = codigo


def redondear(valor):
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _texto(valor):
    return f'{redondear(valor):.2f}'


def _modelos():
    from core.comprobantes.models import NotaDebito
    from core.pos.models import CreditNote, CtasCollect, PaymentsCtaCollect
    return CtasCollect, PaymentsCtaCollect, CreditNote, NotaDebito


def _sin_nota_debito(queryset):
    """Excluye las CxC creadas por notas de débito con ~Exists (sin el JOIN del reverso, que rompe FOR UPDATE en PG)."""
    from core.comprobantes.models import NotaDebito
    return queryset.filter(~Exists(NotaDebito.all_companies.filter(cuenta_por_cobrar=OuterRef('pk'))))


def cxc_de_factura(venta, bloquear=False):
    """CxC de la factura (venta o su pk), no la de una nota de débito sobre ella; None si la venta fue de contado."""
    CtasCollect = _modelos()[0]
    queryset = _sin_nota_debito(CtasCollect.objects.filter(sale=venta)).order_by('id')
    if bloquear:
        queryset = queryset.select_for_update(of=('self',))
    return queryset.first()


def listado(desde=None, hasta=None):
    """CxC del listado con lo que necesita toJSON() anotado: número constante de consultas, sin importar las filas."""
    CtasCollect, PaymentsCtaCollect, _, NotaDebito = _modelos()
    nota = NotaDebito.all_companies.filter(cuenta_por_cobrar=OuterRef('pk'))
    vigentes = PaymentsCtaCollect.all_companies.filter(ctas_collect=OuterRef('pk'), anulado_en__isnull=True)
    suma = vigentes.order_by().values('ctas_collect').annotate(total=Sum('valor')).values('total')[:1]
    queryset = (CtasCollect.objects
                .select_related('sale__company', 'sale__client__user', 'sale__receipt__emission_point__establishment', 'sale__employee')
                .prefetch_related('sale__client__user__groups', 'sale__employee__groups')
                .annotate(nd_id=Subquery(nota.values('pk')[:1]), nd_numero=Subquery(nota.values('voucher_number_full')[:1]),
                          tiene_anulacion=Exists(vigentes.filter(tipo='anulacion')),
                          abonado=Coalesce(Subquery(suma), Value(Decimal('0')),
                                           output_field=DecimalField(max_digits=12, decimal_places=2))))
    if desde and hasta:
        queryset = queryset.filter(date_joined__range=[desde, hasta])
    return queryset.order_by('id')


def abonos(cxc_id):
    """Abonos de una CxC con su documento (nota de crédito o retención) en la misma consulta."""
    PaymentsCtaCollect = _modelos()[1]
    return (PaymentsCtaCollect.objects.filter(ctas_collect_id=cxc_id)
            .select_related('nota_credito', 'retencion_recibida').order_by('id'))


def saldo(cxc):
    return cxc.saldo_actual()


def tiene_anulacion(cxc):
    return cxc.paymentsctacollect_set.filter(tipo='anulacion', anulado_en__isnull=True).exists()


def recalcular(cxc):
    """Guarda el saldo (deuda − abonos vigentes) y el estado (saldo > 0) con update(): no toca nada más."""
    CtasCollect = _modelos()[0]
    nuevo = saldo(cxc)
    CtasCollect.objects.filter(pk=cxc.pk).update(saldo=nuevo, state=nuevo > 0)
    cxc.saldo, cxc.state = nuevo, nuevo > 0


def crear_abono(cxc, tipo, valor, fecha, descripcion, usuario=None, medio_pago='', referencia=''):
    PaymentsCtaCollect = _modelos()[1]
    abono = PaymentsCtaCollect(ctas_collect=cxc, tipo=tipo, valor=redondear(valor), date_joined=fecha,
                               description=(descripcion or '')[:500], medio_pago=medio_pago, referencia=(referencia or '')[:100],
                               registrado_por=usuario, registrado_en=timezone.now())
    abono.save()
    recalcular(cxc)
    return abono


def _fecha(valor):
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor or '').strip())
    except ValueError:
        raise ErrorCxC('fecha')


def registrar_cobro(company, usuario, cxc_id, fecha, valor, medio_pago, referencia='', descripcion='', cuenta=None):
    """Cobro manual (tipo 'cobro'). `cuenta` queda reservada para la Etapa 3 (cuenta bancaria o caja)."""
    if cuenta is not None:
        raise ValueError('La cuenta bancaria o de caja del cobro llega en la Etapa 3: hoy debe ser None.')
    CtasCollect = _modelos()[0]
    try:
        valor = redondear(Decimal(str(valor).strip()))
    except (InvalidOperation, ValueError):
        raise ErrorCxC('valor')
    if not valor.is_finite() or valor <= 0:
        raise ErrorCxC('valor')
    fecha = _fecha(fecha)
    referencia = ' '.join((referencia or '').split())
    with transaction.atomic():
        cxc = CtasCollect.objects.select_for_update(of=('self',)).get(pk=int(cxc_id))
        if tiene_anulacion(cxc):
            raise ErrorCxC('cxc_anulada')
        actual = saldo(cxc)
        if actual <= 0:
            raise ErrorCxC('cxc_saldada')
        if valor > actual:
            raise ErrorCxC('valor_excede', valor=_texto(valor), saldo=_texto(actual))
        if fecha > timezone.localdate():
            raise ErrorCxC('fecha_futura')
        if fecha < cxc.date_joined:
            raise ErrorCxC('fecha_anterior', fecha=f'{cxc.date_joined:%d/%m/%Y}')
        if medio_pago not in dict(MEDIOS_DE_PAGO):
            raise ErrorCxC('medio_pago')
        if medio_pago == 'cheque' and not referencia:
            raise ErrorCxC('referencia_cheque')
        return crear_abono(cxc, 'cobro', valor, fecha, ' '.join((descripcion or '').split()), usuario, medio_pago, referencia)


def puede_eliminar_cobros(request):
    from core.security.session import get_group
    grupo = get_group(request)
    return grupo is not None and grupo.permissions.filter(codename='delete_ctas_collect').exists()


def eliminar_cobro(request, abono_id):
    """Elimina un cobro manual vigente (permiso delete_ctas_collect del rol), auditado. Los automáticos se anulan desde
    su documento. El saldo liberado se abona a las NC y retenciones que tenían excedente (aplicar_excedentes); por eso
    bloquea antes la venta y esos documentos (§3.8)."""
    from core.pos.models import Sale
    from core.tenancy.context import current_company
    from core.tenancy.models import audit
    if not puede_eliminar_cobros(request):
        raise ErrorCxC('sin_permiso_eliminar')
    CtasCollect, PaymentsCtaCollect, _, _ = _modelos()
    with transaction.atomic():
        fila = PaymentsCtaCollect.objects.filter(pk=abono_id).values('ctas_collect_id', 'ctas_collect__sale_id').first()
        if fila is None:
            raise ErrorCxC('no_existe')
        Sale.objects.select_for_update(of=('self',)).filter(pk=fila['ctas_collect__sale_id']).values_list('pk', flat=True).get()
        bloquear_excedentes(fila['ctas_collect__sale_id'])
        cxc = CtasCollect.objects.select_for_update(of=('self',)).get(pk=fila['ctas_collect_id'])
        abono = PaymentsCtaCollect.objects.select_for_update(of=('self',)).filter(pk=abono_id).first()
        if abono is None:
            raise ErrorCxC('no_existe')
        if abono.tipo != 'cobro' or abono.anulado_en is not None:
            raise ErrorCxC('no_es_cobro')
        datos = {'cxc': int(cxc.pk), 'valor': _texto(abono.valor), 'fecha': abono.date_joined.isoformat(),
                 'medio_pago': abono.medio_pago, 'referencia': abono.referencia, 'descripcion': abono.description or ''}
        abono.delete()
        recalcular(cxc)
        aplicados = aplicar_excedentes(cxc, getattr(request, 'user', None))
        if aplicados:
            datos['excedentes_aplicados'] = aplicados
        audit(request, 'cxc_cobro_eliminado', company=current_company(), **datos)


def eliminar_cxc(cxc_id):
    """Borra una CxC sin abonos. Con abonos automáticos o de nota de débito, o con cobros, se rechaza (antes los cobros se
    borraban en cascada sin auditoría)."""
    CtasCollect, PaymentsCtaCollect, _, NotaDebito = _modelos()
    with transaction.atomic():
        cxc = CtasCollect.objects.select_for_update(of=('self',)).get(pk=cxc_id)
        de_nota = NotaDebito.all_companies.filter(cuenta_por_cobrar_id=cxc.pk).exists()
        if de_nota or PaymentsCtaCollect.objects.filter(ctas_collect=cxc).exclude(tipo='cobro').exists():
            raise ErrorCxC('cxc_con_automaticos')
        if PaymentsCtaCollect.objects.filter(ctas_collect=cxc).exists():
            raise ErrorCxC('cxc_con_cobros')
        cxc.delete()


def revertir_abono(abono, ahora, motivo):
    """Anula un abono automático (sin borrarlo) y recalcula su CxC."""
    CtasCollect, PaymentsCtaCollect, _, _ = _modelos()
    PaymentsCtaCollect.objects.filter(pk=abono.pk, anulado_en__isnull=True).update(anulado_en=ahora,
                                                                                  anulado_motivo=(motivo or '')[:300])
    abono.anulado_en, abono.anulado_motivo = ahora, (motivo or '')[:300]
    recalcular(CtasCollect.objects.get(pk=abono.ctas_collect_id))


# ------------------------------------------------------------------ excedentes de NC y retenciones

EXCEDENTE = ('parcial', 'sin_saldo')


def _con_excedente(sale_id):
    """NC vigentes y retenciones recibidas registradas de la factura que no se abonaron enteras."""
    from core.comprobantes.models import RetencionRecibida
    CreditNote = _modelos()[2]
    notas = CreditNote.objects.filter(sale_id=sale_id, cxc_ajuste__in=EXCEDENTE, status__in=AUTORIZADOS,
                                      anulado_sri_fecha__isnull=True)
    retenciones = RetencionRecibida.objects.filter(venta_id=sale_id, estado='registrada', cxc_estado__in=EXCEDENTE)
    return notas, retenciones


def bloquear_excedentes(sale_id):
    """Bloquea esas NC y retenciones (§3.8: después de la venta y antes de la CxC) para que aplicar_excedentes las cambie
    sin cruzarse con marcar o anular."""
    notas, retenciones = _con_excedente(sale_id)
    list(notas.select_for_update(of=('self',)).order_by('pk').values_list('pk', flat=True))
    list(retenciones.select_for_update(of=('self',)).order_by('pk').values_list('pk', flat=True))


def reparto_excedentes(cuenta, disponible=None, excluir=()):
    """[(tipo, documento, abono vigente o None, valor que se suma, nuevo total abonado, total)] en orden de fecha, sin
    escribir nada. `disponible` = saldo que se reparte (por defecto, el actual); `excluir` = [(tipo, pk)] que no cuentan
    (la vista previa de marcar excluye la NC que se anula). Solo para la CxC de la factura y si no tiene una anulación."""
    if cuenta is None or tiene_anulacion(cuenta):
        return []
    factura = cxc_de_factura(cuenta.sale_id)
    if factura is None or factura.pk != cuenta.pk:   # la CxC de una nota de débito no recibe NC ni retenciones
        return []
    disponible = saldo(cuenta) if disponible is None else redondear(disponible)
    notas, retenciones = _con_excedente(cuenta.sale_id)
    documentos = sorted(
        [((n.emission_date or n.date_joined), 0, n.pk, 'nota_credito', n, n.abono_cxc, redondear(n.total))
         for n in notas.select_related('abono_cxc')] +
        [(r.fecha_emision, 1, r.pk, 'retencion', r, r.abono, redondear(r.total_retenido))
         for r in retenciones.select_related('abono')], key=lambda d: d[:3])
    reparto = []
    for _, _, pk, tipo, doc, abono, total in documentos:
        if disponible <= 0:
            break
        if (tipo, pk) in excluir:
            continue
        vigente = abono if abono is not None and abono.anulado_en is None else None
        abonado = redondear(vigente.valor) if vigente is not None else Decimal('0.00')
        suma = min(redondear(total - abonado), disponible)
        if suma <= 0:
            continue
        reparto.append((tipo, doc, vigente, suma, redondear(abonado + suma), total))
        disponible = redondear(disponible - suma)
    return reparto


def aplicar_excedentes(cuenta, usuario=None, ahora=None):
    """Abona a las NC y retenciones con excedente lo que les faltaba, cuando el saldo de la CxC subió (se eliminó un cobro
    o se revirtió otro abono). Quien llama ya bloqueó la venta, esos documentos (bloquear_excedentes) y la CxC.

    Cada documento conserva un solo abono vigente con todo lo abonado: el anterior se anula («sustituido», no se borra) y
    el nuevo lleva el total. Devuelve [{'tipo', 'numero', 'valor'}] con lo que se abonó de más (para la auditoría)."""
    from core.comprobantes.models import RetencionRecibida
    CtasCollect, PaymentsCtaCollect, CreditNote, _ = _modelos()
    ahora = ahora or timezone.now()
    cuenta = CtasCollect.objects.get(pk=cuenta.pk)
    aplicados = []
    for tipo, doc, vigente, suma, nuevo, total in reparto_excedentes(cuenta):
        if vigente is not None:
            PaymentsCtaCollect.objects.filter(pk=vigente.pk, anulado_en__isnull=True).update(
                anulado_en=ahora, anulado_motivo=f'Sustituido por un abono de {_texto(nuevo)}: se liberó saldo en la cuenta '
                                                 'por cobrar.')
        estado = 'aplicada' if nuevo >= total else 'parcial'
        if tipo == 'nota_credito':
            numero = doc.voucher_number_full
            abono = crear_abono(cuenta, tipo, nuevo, doc.emission_date or timezone.localdate(), f'Nota de crédito {numero}',
                                usuario)
            CreditNote.objects.filter(pk=doc.pk).update(abono_cxc=abono, cxc_ajuste=estado)
        else:
            numero = doc.numero
            abono = crear_abono(cuenta, tipo, nuevo, doc.fecha_emision, f'Retención {numero}', usuario, referencia=numero)
            RetencionRecibida.objects.filter(pk=doc.pk).update(abono=abono, cxc_estado=estado)
        aplicados.append({'tipo': tipo, 'numero': numero, 'valor': _texto(suma)})
    return aplicados


def texto_excedente(tipo, numero, valor, hecho=True):
    nombre = 'nota de crédito' if tipo == 'nota_credito' else 'retención'
    verbo = 'Se abonaron' if hecho else 'Se abonarán'
    return f'{verbo} {valor} de la {nombre} {numero}, que antes superaba el saldo de la cuenta por cobrar.'


def prever_nota_credito(nota, disponible=None):
    """(cxc_ajuste, cxc, valor a abonar, excedente) que dejaría la nota de crédito, sin escribir nada. `disponible`
    reemplaza el saldo actual (el ensayo de regularizar_cxc_historico descuenta las NC anteriores de la misma CxC)."""
    cuenta = cxc_de_factura(nota.sale_id)
    total = redondear(nota.total)
    if cuenta is None:
        return 'sin_cxc', None, Decimal('0.00'), total
    actual = saldo(cuenta) if disponible is None else redondear(disponible)
    if tiene_anulacion(cuenta) or actual <= 0:
        return 'sin_saldo', cuenta, Decimal('0.00'), total
    valor = min(total, actual)
    return ('aplicada' if valor >= total else 'parcial'), cuenta, valor, redondear(total - valor)


def aplicar_nota_credito(nota_id, desde='pendiente'):
    """Abona la CxC de la factura con la nota de crédito autorizada. Devuelve el cxc_ajuste final; idempotente.

    `desde` = estado de ajuste que se aplica: 'pendiente' (receptor y aplicar_ajustes_cxc) o 'no_aplica' (solo la orden
    regularizar_cxc_historico, con la decisión de la propietaria)."""
    CtasCollect, _, CreditNote, _ = _modelos()
    with transaction.atomic():
        nota = CreditNote.objects.select_for_update(of=('self',)).get(pk=nota_id)
        if nota.cxc_ajuste != desde or nota.status not in AUTORIZADOS or nota.anulado_sri_fecha is not None:
            return nota.cxc_ajuste
        cxc_de_factura(nota.sale_id, bloquear=True)
        estado, cuenta, valor, _ = prever_nota_credito(nota)
        abono = None
        if estado in ('aplicada', 'parcial'):
            abono = crear_abono(cuenta, 'nota_credito', valor, nota.emission_date or timezone.localdate(),
                                f'Nota de crédito {nota.voucher_number_full}')
        CreditNote.objects.filter(pk=nota.pk).update(cxc_ajuste=estado, abono_cxc=abono)
        return estado


def aplicar_nota_debito(nota_id, desde='pendiente'):
    """Crea la CxC propia de la nota de débito autorizada (también sobre una factura de contado). Idempotente.
    `desde` como en aplicar_nota_credito.

    Bloquea primero la factura modificada y después la ND, como marcar('nota-debito') y marcar('factura') (§3.8): al
    insertar la CxC, su clave foránea sale_id toma FOR KEY SHARE sobre la venta, y con la ND tomada antes que la venta
    había un interbloqueo en PostgreSQL con marcar (Sale → ND)."""
    from core.pos.models import Sale
    CtasCollect, _, _, NotaDebito = _modelos()
    with transaction.atomic():
        sale_id = NotaDebito.objects.filter(pk=nota_id).values_list('sale_id', flat=True).get()
        Sale.objects.select_for_update(of=('self',)).filter(pk=sale_id).values_list('pk', flat=True).get()
        nota = NotaDebito.objects.select_for_update(of=('self',)).get(pk=nota_id)
        if nota.cxc_ajuste != desde or nota.status not in AUTORIZADOS or nota.anulado_sri_fecha is not None:
            return nota.cxc_ajuste
        fecha = nota.emission_date or timezone.localdate()
        de_factura = cxc_de_factura(nota.sale_id)
        vence = max(fecha, de_factura.end_date) if de_factura is not None else fecha
        total = redondear(nota.valor_total)
        cuenta = CtasCollect(sale_id=nota.sale_id, date_joined=fecha, end_date=vence, debt=total, saldo=total, state=total > 0)
        cuenta.save()
        NotaDebito.objects.filter(pk=nota.pk).update(cuenta_por_cobrar=cuenta, cxc_ajuste='aplicada')
        return 'aplicada'


def pendientes(company=None):
    """NC y ND autorizadas, sin anular, cuyo ajuste quedó pendiente (un receptor falló o la petición murió)."""
    _, _, CreditNote, NotaDebito = _modelos()
    filtro = {'cxc_ajuste': 'pendiente', 'status__in': AUTORIZADOS, 'anulado_sri_fecha__isnull': True}
    if company is not None:
        filtro['company'] = company
    return {'notas_credito': CreditNote.objects.filter(**filtro).order_by('pk'),
            'notas_debito': NotaDebito.objects.filter(**filtro).order_by('pk')}
