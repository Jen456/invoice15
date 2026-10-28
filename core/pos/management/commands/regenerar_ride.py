"""Regenera con la plantilla actual el RIDE A4 (PDF) ya guardado de facturas autorizadas, solo si el PDF nuevo es fiel al
XML autorizado. Solo la representación: no toca XML, estado, numeración, cupo ni el SRI y no envía correos.

  manage.py regenerar_ride --empresa RUC [--numero 001-002-000000272 ...] [--salida DIR]
      ENSAYO (por defecto): genera en memoria, compara con el XML autorizado y deja los PDF nuevos en DIR para revisarlos.
  manage.py regenerar_ride --empresa RUC [--numero ...] --aplicar --respaldo DIR
      Copia antes los PDF actuales a DIR, guarda el nuevo como archivo NUEVO (nunca sobrescribe ni borra el anterior) y
      apunta la factura a él; deja registro en la auditoría. Las que no son fieles no se tocan.
"""
import shutil
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from core.comprobantes.fidelidad import diferencias
from core.pos import emision
from core.pos.models import Company, Sale
from core.tenancy.context import company_context
from core.tenancy.models import audit


class Command(BaseCommand):
    help = 'Regenera el RIDE A4 guardado de facturas autorizadas si el nuevo es fiel al XML autorizado (ensayo por defecto).'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', required=True, help='RUC de la empresa.')
        parser.add_argument('--numero', action='append', default=[], help='Número completo (001-002-000000272); repetible.')
        parser.add_argument('--salida', help='Carpeta donde dejar los PDF nuevos del ensayo.')
        parser.add_argument('--aplicar', action='store_true', help='Guarda los PDF nuevos fieles y apunta las facturas a ellos.')
        parser.add_argument('--respaldo', help='Carpeta donde copiar los PDF actuales antes de aplicar (obligatoria con --aplicar).')

    def handle(self, *args, empresa, numero, salida, aplicar, respaldo, **options):
        if aplicar and not respaldo:
            raise CommandError('Con --aplicar indica --respaldo DIR: ahí se copian los PDF actuales antes de cambiar nada.')
        company = Company.objects.filter(ruc=empresa).first()
        if company is None:
            raise CommandError(f'No hay una empresa con RUC {empresa}.')
        for carpeta in filter(None, (salida, respaldo)):
            Path(carpeta).mkdir(parents=True, exist_ok=True)
        resumen = {'fieles': 0, 'con diferencias': 0, 'aplicadas': 0}
        with company_context(company):
            facturas = (Sale.objects.select_related('receipt', 'client__user').filter(receipt__voucher_type='01',
                        status__in=emision.AUTORIZADOS + (emision.ANULADA,)).exclude(xml_authorized='').exclude(pdf_authorized='')
                        .order_by('pk'))
            if numero:
                facturas = facturas.filter(voucher_number_full__in=numero)
            for venta in facturas:
                resumen_venta = self._una(venta, salida, aplicar, respaldo)
                resumen[resumen_venta] += 1
                if resumen_venta == 'fieles' and aplicar:
                    resumen['aplicadas'] += 1
        modo = 'APLICADO' if aplicar else 'ENSAYO (no se cambió nada)'
        self.stdout.write(f'{modo}: ' + ', '.join(f'{k} {v}' for k, v in resumen.items()))

    def _una(self, venta, salida, aplicar, respaldo):
        with venta.xml_authorized.open('rb') as f:
            xml = f.read()
        with venta.pdf_authorized.open('rb') as f:
            anterior = f.read()
        nuevo = venta.ride_pdf()
        faltan = diferencias(nuevo, xml)
        faltan_antes = diferencias(anterior, xml)
        etiqueta = f'{venta.voucher_number_full} (emitida {venta.emission_date or venta.date_joined:%d/%m/%Y})'
        self.stdout.write(f'{etiqueta}: PDF guardado {venta.pdf_authorized.name} '
                          f'({len(anterior) // 1024} KB, fiel al XML: {"sí" if not faltan_antes else "no"}); '
                          f'nuevo {len(nuevo) // 1024} KB, fiel al XML: {"sí" if not faltan else "NO"}')
        for campo, esperado in faltan:
            self.stdout.write(f'    no coincide {campo}: el XML autorizado dice «{esperado}»')
        if salida:
            Path(salida, f'{venta.voucher_number_full}-nuevo.pdf').write_bytes(nuevo)
        if faltan:
            return 'con diferencias'
        if aplicar:
            copia = Path(respaldo, Path(venta.pdf_authorized.name).name)
            with venta.pdf_authorized.open('rb') as f, open(copia, 'wb') as destino:
                shutil.copyfileobj(f, destino)
            previo = venta.pdf_authorized.name
            venta.pdf_authorized.save('ride.pdf', ContentFile(nuevo), save=False)   # archivo nuevo (ruta y largo del campo); el anterior queda
            nombre = venta.pdf_authorized.name
            Sale.objects.filter(pk=venta.pk).update(pdf_authorized=nombre)
            audit(None, 'ride_regenerado', company=venta.company, comprobante=venta.voucher_number_full, anterior=previo, nuevo=nombre)
            self.stdout.write(f'    aplicado: ahora {nombre}; el anterior sigue en {previo} y copiado en {copia}')
        return 'fieles'
