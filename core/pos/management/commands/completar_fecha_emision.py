"""Completa la fecha de emisión (emission_date) de facturas y notas de crédito autorizadas antes de la emisión en dos
fases (pos 0012), leyendo fechaEmision del XML autorizado (CDATA de <comprobante>) o del XML firmado, con el analizador
seguro de la importación. Nunca sobrescribe un valor existente ni toca XML, RIDE, estado ni el SRI. NO SE EJECUTA EN
PRODUCCIÓN EN ESTA FASE.

  manage.py completar_fecha_emision --empresa RUC [--informe ruta.csv]
      ENSAYO (por defecto): lista número, fecha de registro, fecha del XML o «sin XML». No cambia nada.
  ... --aplicar --decision "texto"
      Cambia el período al que pertenece cada documento en los reportes declarables: exige la decisión de la propietaria.
      update() solo donde emission_date sigue vacío; audita regularizacion_datos_origen.
"""
import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.pos.models import Company, CreditNote, Sale
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog

ESTADOS = ('authorized', 'authorized_and_sent_by_email', 'canceled')
NODOS_INFO = ('infoFactura', 'infoNotaCredito')


def fecha_emision_del_xml(datos):
    """fechaEmision (dd/mm/aaaa) del comprobante dentro de `datos` (bytes del XML autorizado o firmado), o None."""
    from core.importacion import xml_sri
    if not datos:
        return None
    cuerpo = bytes(datos).lstrip(b'\xef\xbb\xbf \t\r\n')
    resultado = xml_sri.ResultadoXml(aceptado=True, sha256='', tamano=len(cuerpo))
    try:
        raiz = xml_sri._desenvolver(resultado, xml_sri._analizar(cuerpo))
    except xml_sri._Rechazo:
        return None
    for nodo in NODOS_INFO:
        fecha = xml_sri._fecha(xml_sri._texto(raiz, f'{nodo}/fechaEmision'))
        if fecha is not None:
            return fecha
    return None


def _xml(doc):
    if doc.xml_authorized:
        try:
            with doc.xml_authorized.open('rb') as archivo:
                return archivo.read(), 'autorizado'
        except (OSError, ValueError):
            pass
    if doc.xml_signed:
        return doc.xml_signed.encode('utf-8'), 'firmado'
    return b'', ''


class Command(BaseCommand):
    help = 'Completa emission_date desde el XML autorizado (ensayo por defecto; --aplicar exige --decision).'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', required=True, help='RUC de la empresa.')
        parser.add_argument('--informe', help='Ruta del informe CSV.')
        parser.add_argument('--aplicar', action='store_true', help='Completa las fechas leídas (exige --decision).')
        parser.add_argument('--decision', default='', help='Texto de la decisión de la propietaria (obligatorio con --aplicar).')

    def handle(self, *args, empresa, informe=None, aplicar=False, decision='', **options):
        decision = ' '.join((decision or '').split())
        if aplicar and not decision:
            raise CommandError('Con --aplicar indica --decision "texto": esta orden cambia el período de las ventas en los '
                               'reportes declarables y exige la decisión de la propietaria.')
        company = Company.objects.filter(ruc=empresa).first()
        if company is None:
            raise CommandError(f'No hay una empresa con RUC {empresa}.')
        filas = []
        with company_context(company):
            for Modelo in (Sale, CreditNote):
                for doc in Modelo.objects.filter(status__in=ESTADOS, emission_date__isnull=True).order_by('pk'):
                    if Modelo is Sale and doc.receipt.voucher_type != '01':
                        continue
                    datos, origen = _xml(doc)
                    fecha = fecha_emision_del_xml(datos)
                    filas.append({'modelo': Modelo._meta.model_name, 'id': doc.pk, 'numero': doc.voucher_number_full,
                                  'fecha_registro': doc.date_joined.isoformat(), 'fecha_xml': fecha.isoformat() if fecha else '',
                                  'origen_xml': origen or 'sin XML', '_fecha': fecha})
            for f in filas:
                self.stdout.write(f"{f['modelo']} {f['numero']}: registro {f['fecha_registro']}, XML "
                                  f"{f['fecha_xml'] or '—'} ({f['origen_xml']})")
            if informe:
                with open(informe, 'w', newline='', encoding='utf-8') as archivo:
                    escritor = csv.DictWriter(archivo, fieldnames=('modelo', 'id', 'numero', 'fecha_registro', 'fecha_xml',
                                                                   'origen_xml'))
                    escritor.writeheader()
                    escritor.writerows({k: v for k, v in f.items() if not k.startswith('_')} for f in filas)
            completados = []
            if aplicar:
                with transaction.atomic():
                    for f in filas:
                        if f['_fecha'] is None:
                            continue
                        Modelo = Sale if f['modelo'] == 'sale' else CreditNote
                        if Modelo.objects.filter(pk=f['id'], emission_date__isnull=True).update(emission_date=f['_fecha']):
                            completados.append({'modelo': f['modelo'], 'id': int(f['id']), 'numero': f['numero'],
                                                'fecha': f['_fecha'].isoformat()})
                    AuditLog.objects.create(user=None, company=company, action='regularizacion_datos_origen',
                                            detail={'orden': 'completar_fecha_emision', 'decision': decision,
                                                    'informe': informe or '', 'documentos': completados})
        modo = 'APLICADO' if aplicar else 'ENSAYO (no se cambió nada)'
        sin_xml = sum(1 for f in filas if f['_fecha'] is None)
        self.stdout.write(f'{modo}: documentos {len(filas)}, sin fecha en el XML {sin_xml}, completados {len(completados)}')
