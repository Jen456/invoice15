"""Notas de crédito: reglas en el servidor (auditoría SRI, oct-2026).

- Solo sobre facturas autorizadas, del mismo ambiente y que no sean a consumidor final (desde 2026 el
  SRI no admite notas de crédito sobre ellas, Res. NAC-DGERCGC25-00000014).
- Cada línea no supera lo vendido menos lo ya acreditado; precio, descuento y tarifa salen de la
  factura, no del navegador. La factura se bloquea mientras se crea la nota: dos a la vez no se pisan.
- Motivo obligatorio. Solo vuelve al stock lo que se inventaría.
- La factura pasa a «Anulado» cuando las notas autorizadas cubren su total.
"""
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from core.pos.choices import VOUCHER_TYPE

AUTORIZADOS = ('authorized', 'authorized_and_sent_by_email')
# Notas que el SRI no aceptó: no cuentan como acreditadas.
NO_CUENTAN = ('returned', 'not_authorized', 'sequential_registered_error')
CONSUMIDOR_FINAL = '9999999999999'


class ErrorNotaCredito(Exception):
    """Mensaje para el usuario."""


def es_consumidor_final(cliente):
    return cliente.identification_type == '07' or cliente.dni == CONSUMIDOR_FINAL


def acreditado_por_detalle(venta):
    from core.pos.models import CreditNoteDetail
    filas = (CreditNoteDetail.objects.filter(sale_detail__sale=venta).exclude(credit_note__status__in=NO_CUENTAN)
             .values('sale_detail_id').annotate(cantidad=Sum('cant')))
    return {f['sale_detail_id']: f['cantidad'] or 0 for f in filas}


def validar_factura(venta, company):
    if venta.receipt.voucher_type != VOUCHER_TYPE[0][0]:
        raise ErrorNotaCredito('Las notas de crédito solo se emiten sobre facturas.')
    if venta.status not in AUTORIZADOS:
        raise ErrorNotaCredito('La factura debe estar autorizada por el SRI para emitir una nota de crédito.')
    if es_consumidor_final(venta.client):
        raise ErrorNotaCredito('El SRI no admite notas de crédito sobre facturas a consumidor final.')
    if venta.environment_type != company.environment_type:
        raise ErrorNotaCredito(f'La factura es del ambiente {venta.get_environment_type_display()} y la empresa emite '
                               f'en {company.get_environment_type_display()}.')


def crear(company, venta_id, lineas, motivo):
    """Nota de crédito guardada y aún sin firmar. lineas: [(id de detalle de la venta, cantidad)] o None = todo lo pendiente.

    Debe llamarse dentro de una transacción (la vista firma a continuación con emision.preparar).
    """
    from core.configuracion.servicios import receipt_para_emitir
    from core.pos.models import CreditNote, CreditNoteDetail, Sale
    motivo = ' '.join((motivo or '').split())
    if not motivo:
        raise ErrorNotaCredito('Escribe el motivo de la nota de crédito.')
    venta = Sale.objects.select_for_update().select_related('client', 'receipt').get(pk=venta_id)
    validar_factura(venta, company)
    acreditado = acreditado_por_detalle(venta)
    detalles = {d.pk: d for d in venta.saledetail_set.select_related('product')}
    if lineas is None:
        lineas = [(pk, d.cant - acreditado.get(pk, 0)) for pk, d in detalles.items()]
    a_acreditar = []
    for pk, cantidad in lineas:
        pk, cantidad = int(pk), int(cantidad)
        if cantidad <= 0:
            continue
        detalle = detalles.get(pk)
        if detalle is None:
            raise ErrorNotaCredito('Una de las líneas no pertenece a esta factura.')
        disponible = detalle.cant - acreditado.get(pk, 0)
        if cantidad > disponible:
            raise ErrorNotaCredito(f'«{detalle.product.name}»: solo quedan {disponible} por acreditar en esta factura.')
        a_acreditar.append((detalle, cantidad))
    if not a_acreditar:
        raise ErrorNotaCredito('No queda nada por acreditar en esta factura.' if not any(c > 0 for _, c in lineas or [])
                               else 'Indica al menos una cantidad mayor que cero.')
    nota = CreditNote(sale=venta, motive=motivo[:300], company=company, environment_type=venta.environment_type,
                      iva=venta.iva, create_electronic_invoice=True, date_joined=timezone.localdate())
    nota.receipt = receipt_para_emitir(company, VOUCHER_TYPE[1][0], electronica=True)
    nota.voucher_number = nota.generate_voucher_number()
    nota.voucher_number_full = nota.get_voucher_number_full()
    nota.save()
    for detalle, cantidad in a_acreditar:
        CreditNoteDetail.objects.create(credit_note=nota, sale_detail=detalle, product=detalle.product, cant=cantidad,
                                        price=detalle.price, dscto=detalle.dscto)
        if detalle.product.inventoried:   # devolución de mercadería
            detalle.product.stock += cantidad
            detalle.product.save(update_fields=['stock'])
    nota.calculate_detail()
    nota.calculate_invoice()
    return nota


def actualizar_factura(venta_id):
    """La factura queda «Anulado» cuando las notas de crédito autorizadas cubren su total."""
    from core.pos.models import CreditNote, Sale
    venta = Sale.all_companies.get(pk=venta_id)
    acreditado = (CreditNote.all_companies.filter(sale_id=venta_id, status__in=AUTORIZADOS)
                  .aggregate(total=Sum('total'))['total'] or Decimal('0'))
    if venta.status in AUTORIZADOS and Decimal(acreditado) >= Decimal(venta.total) - Decimal('0.005'):
        Sale.all_companies.filter(pk=venta_id).update(status='canceled')
