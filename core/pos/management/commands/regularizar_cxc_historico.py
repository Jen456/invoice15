"""Regulariza la cuenta por cobrar de las notas de crédito y de débito históricas ('no_aplica': anteriores a la regla de
la Etapa 2), autorizadas y sin anular. Lo histórico no se recalcula sin una decisión de la propietaria y un procedimiento
revisable. NO SE EJECUTA EN PRODUCCIÓN EN ESTA FASE.

  manage.py regularizar_cxc_historico --empresa RUC [--desde AAAA-MM-DD] [--hasta AAAA-MM-DD] [--tipo nc|nd|todos]
                                      [--informe ruta.csv]
      ENSAYO (por defecto): informe con empresa, tipo, número, fecha, factura, cxc_id, deuda, saldo actual, valor a abonar,
      excedente y «revisar» con su motivo (cobros cuya descripción cita el número del documento o con su mismo valor:
      posible doble abono). No cambia nada.
  ... --aplicar --decision "texto" [--incluir-revisar]
      Aplica solo las filas sin «revisar» (salvo --incluir-revisar): la NC abona la CxC de su factura y la ND crea su CxC;
      deja cxc_ajuste en aplicada / parcial / sin_cxc / sin_saldo y audita regularizacion_datos_origen.
"""
import csv
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from core.comprobantes.models import NotaDebito
from core.pos import consultas, cxc
from core.pos.models import Company, CreditNote, PaymentsCtaCollect
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog

AUTORIZADOS = ('authorized', 'authorized_and_sent_by_email')
COLUMNAS = ('empresa', 'tipo', 'numero', 'fecha', 'factura', 'cxc_id', 'deuda', 'saldo_actual', 'valor_a_abonar', 'excedente',
            'efecto', 'revisar', 'motivo')


def _fecha(texto, opcion):
    if not texto:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise CommandError(f'{opcion}: usa el formato AAAA-MM-DD.')


def _revisar(cuenta, doc, total):
    """Motivo para revisar a mano (posible doble abono) o ''."""
    if cuenta is None:
        return ''
    cobros = PaymentsCtaCollect.objects.filter(ctas_collect=cuenta, tipo='cobro', anulado_en__isnull=True)
    if cobros.filter(Q(description__icontains=doc.voucher_number_full) | Q(description__contains=doc.voucher_number)).exists():
        return f'un cobro de la cuenta {cuenta.pk} cita el número {doc.voucher_number_full}'
    if cobros.filter(valor=cxc.redondear(total)).exists():
        return f'un cobro de la cuenta {cuenta.pk} tiene el mismo valor ({total:.2f})'
    return ''


class Command(BaseCommand):
    help = 'Regulariza la CxC de NC y ND históricas (no_aplica). Ensayo por defecto; --aplicar exige --decision.'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', required=True, help='RUC de la empresa.')
        parser.add_argument('--desde', help='Fecha de emisión desde (AAAA-MM-DD).')
        parser.add_argument('--hasta', help='Fecha de emisión hasta (AAAA-MM-DD).')
        parser.add_argument('--tipo', choices=('nc', 'nd', 'todos'), default='todos')
        parser.add_argument('--informe', help='Ruta del informe CSV.')
        parser.add_argument('--aplicar', action='store_true', help='Aplica las filas sin «revisar» (exige --decision).')
        parser.add_argument('--decision', default='', help='Texto de la decisión de la propietaria (obligatorio con --aplicar).')
        parser.add_argument('--incluir-revisar', action='store_true', dest='incluir_revisar',
                            help='Con --aplicar, aplica también las filas marcadas «revisar».')

    def handle(self, *args, empresa, desde=None, hasta=None, tipo='todos', informe=None, aplicar=False, decision='',
               incluir_revisar=False, **options):
        decision = ' '.join((decision or '').split())
        if aplicar and not decision:
            raise CommandError('Con --aplicar indica --decision "texto": esta orden cambia saldos históricos y exige la '
                               'decisión de la propietaria.')
        desde, hasta = _fecha(desde, '--desde'), _fecha(hasta, '--hasta')
        company = Company.objects.filter(ruc=empresa).first()
        if company is None:
            raise CommandError(f'No hay una empresa con RUC {empresa}.')
        with company_context(company):
            filas = self._filas(company, tipo, desde, hasta)
            if informe:
                with open(informe, 'w', newline='', encoding='utf-8') as archivo:
                    escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS)
                    escritor.writeheader()
                    escritor.writerows({k: v for k, v in f.items() if k in COLUMNAS} for f in filas)
            for f in filas:
                self.stdout.write(f"{f['tipo'].upper()} {f['numero']} ({f['fecha']}) factura {f['factura']}: {f['efecto']} "
                                  f"{f['valor_a_abonar']}" + (f" · REVISAR: {f['motivo']}" if f['revisar'] == 'sí' else ''))
            aplicados = []
            if aplicar:
                with transaction.atomic():
                    for f in filas:
                        if f['revisar'] == 'sí' and not incluir_revisar:
                            continue
                        if f['tipo'] == 'nc':
                            efecto = cxc.aplicar_nota_credito(f['id'], desde='no_aplica')
                        else:
                            efecto = cxc.aplicar_nota_debito(f['id'], desde='no_aplica')
                        aplicados.append({'tipo': f['tipo'], 'id': int(f['id']), 'numero': f['numero'], 'efecto': efecto,
                                          'valor': f['valor_a_abonar']})
                    AuditLog.objects.create(user=None, company=company, action='regularizacion_datos_origen',
                                            detail={'orden': 'regularizar_cxc_historico', 'decision': decision,
                                                    'informe': informe or '', 'documentos': aplicados})
        modo = 'APLICADO' if aplicar else 'ENSAYO (no se cambió nada)'
        revisar = sum(1 for f in filas if f['revisar'] == 'sí')
        self.stdout.write(f'{modo}: documentos {len(filas)}, para revisar {revisar}, aplicados {len(aplicados)}')

    def _filas(self, company, tipo, desde, hasta):
        filas = []
        base = {'anulado_sri_fecha__isnull': True, 'status__in': AUTORIZADOS, 'cxc_ajuste': 'no_aplica'}
        if tipo in ('nc', 'todos'):
            notas = CreditNote.objects.filter(**base).select_related('sale').annotate(
                fecha_efectiva=consultas.fecha_efectiva(CreditNote)).order_by('fecha_efectiva', 'pk')
            if desde:
                notas = notas.filter(fecha_efectiva__gte=desde)
            if hasta:
                notas = notas.filter(fecha_efectiva__lte=hasta)
            for nota in notas:
                efecto, cuenta, valor, excedente = cxc.prever_nota_credito(nota)
                motivo = _revisar(cuenta, nota, nota.total)
                filas.append(self._fila(company, 'nc', nota, nota.fecha_efectiva, cuenta, efecto, valor, excedente, motivo))
        if tipo in ('nd', 'todos'):
            notas = NotaDebito.objects.filter(**base).select_related('sale').annotate(
                fecha_efectiva=consultas.fecha_efectiva(NotaDebito)).order_by('fecha_efectiva', 'pk')
            if desde:
                notas = notas.filter(fecha_efectiva__gte=desde)
            if hasta:
                notas = notas.filter(fecha_efectiva__lte=hasta)
            for nota in notas:
                de_factura = cxc.cxc_de_factura(nota.sale_id)
                motivo = _revisar(de_factura, nota, nota.valor_total)
                fila = self._fila(company, 'nd', nota, nota.fecha_efectiva, None, 'aplicada',
                                  cxc.redondear(nota.valor_total), cxc.redondear(0), motivo)
                filas.append(fila)
        return filas

    @staticmethod
    def _fila(company, tipo, doc, fecha, cuenta, efecto, valor, excedente, motivo):
        return {'id': doc.pk, 'empresa': company.ruc, 'tipo': tipo, 'numero': doc.voucher_number_full,
                'fecha': fecha.isoformat() if fecha else '', 'factura': doc.sale.voucher_number_full,
                'cxc_id': cuenta.pk if cuenta is not None else '',
                'deuda': f'{cuenta.debt:.2f}' if cuenta is not None else '',
                'saldo_actual': f'{cxc.saldo(cuenta):.2f}' if cuenta is not None else '',
                'valor_a_abonar': f'{valor:.2f}', 'excedente': f'{excedente:.2f}', 'efecto': efecto,
                'revisar': 'sí' if motivo else 'no', 'motivo': motivo}
