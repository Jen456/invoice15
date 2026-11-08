"""Regenera con la plantilla actual el RIDE A4 (PDF) ya guardado de facturas y notas de crédito autorizadas, solo si el
PDF nuevo es fiel al XML autorizado. Solo la representación: no toca XML, estado, numeración, cupo ni el SRI y no envía
correos.

  manage.py regenerar_ride --empresa RUC [--tipo factura|nota_credito|todos] [--numero 001-002-000000272 ...] [--salida DIR]
      ENSAYO (por defecto): genera en memoria, compara con el XML autorizado y deja los PDF nuevos en DIR para revisarlos.
  manage.py regenerar_ride --empresa RUC [--tipo ...] [--numero ...] --aplicar --respaldo DIR
      Copia antes los PDF actuales a DIR, guarda el nuevo como archivo NUEVO (nunca sobrescribe ni borra el anterior) y
      apunta el comprobante a él; deja registro en la auditoría. Los que no son fieles no se tocan.
"""
import shutil
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from core.comprobantes.fidelidad import diferencias
from core.pos import emision
from core.pos.models import Company, CreditNote, Sale
from core.tenancy.context import company_context
from core.tenancy.models import audit

# tipo: (modelo, código del comprobante, etiqueta en el informe, prefijo del PDF de ensayo)
TIPOS = {
    'factura': (Sale, '01', '', ''),
    'nota_credito': (CreditNote, '04', 'nota de crédito ', 'nc-'),
}


class Command(BaseCommand):
    help = ('Regenera el RIDE A4 guardado de facturas y notas de crédito autorizadas si el nuevo es fiel al XML autorizado '
            '(ensayo por defecto).')

    def add_arguments(self, parser):
        parser.add_argument('--empresa', required=True, help='RUC de la empresa.')
        parser.add_argument('--tipo', choices=(*TIPOS, 'todos'), default='todos', help='Tipo de comprobante (por defecto, todos).')
        parser.add_argument('--numero', action='append', default=[], help='Número completo (001-002-000000272); repetible.')
        parser.add_argument('--salida', help='Carpeta donde dejar los PDF nuevos del ensayo.')
        parser.add_argument('--aplicar', action='store_true', help='Guarda los PDF nuevos fieles y apunta los comprobantes a ellos.')
        parser.add_argument('--respaldo', help='Carpeta donde copiar los PDF actuales antes de aplicar (obligatoria con --aplicar).')

    def handle(self, *args, empresa, tipo, numero, salida, aplicar, respaldo, **options):
        if aplicar and not respaldo:
            raise CommandError('Con --aplicar indica --respaldo DIR: ahí se copian los PDF actuales antes de cambiar nada.')
        company = Company.objects.filter(ruc=empresa).first()
        if company is None:
            raise CommandError(f'No hay una empresa con RUC {empresa}.')
        for carpeta in filter(None, (salida, respaldo)):
            Path(carpeta).mkdir(parents=True, exist_ok=True)
        resumen = {'fieles': 0, 'con diferencias': 0, 'aplicadas': 0}
        with company_context(company):
            for clave in (TIPOS if tipo == 'todos' else (tipo,)):
                modelo, codigo = TIPOS[clave][:2]
                documentos = (modelo.objects.select_related('receipt').filter(receipt__voucher_type=codigo,
                              status__in=emision.AUTORIZADOS + (emision.ANULADA,))
                              .exclude(xml_authorized='').exclude(xml_authorized__isnull=True)
                              .exclude(pdf_authorized='').exclude(pdf_authorized__isnull=True).order_by('pk'))
                if numero:
                    documentos = documentos.filter(voucher_number_full__in=numero)
                for documento in documentos:
                    resultado = self._uno(clave, documento, salida, aplicar, respaldo)
                    resumen[resultado] += 1
                    if resultado == 'fieles' and aplicar:
                        resumen['aplicadas'] += 1
        modo = 'APLICADO' if aplicar else 'ENSAYO (no se cambió nada)'
        self.stdout.write(f'{modo}: ' + ', '.join(f'{k} {v}' for k, v in resumen.items()))

    @staticmethod
    def _para_comparar(documento, nuevo):
        """PDF que se compara con el XML: sin los textos libres del comercio (copia v2), que podrían contener justo el dato
        que se busca y ocultar una diferencia."""
        copia = getattr(documento, 'ride_diseno', None)
        if isinstance(copia, dict) and (copia.get('encabezado') or copia.get('pie_comercial')):
            return documento.ride_pdf(sin_textos_comerciales=True)
        return nuevo

    def _uno(self, clave, documento, salida, aplicar, respaldo):
        modelo, _, etiqueta, prefijo = TIPOS[clave]
        with documento.xml_authorized.open('rb') as f:
            xml = f.read()
        with documento.pdf_authorized.open('rb') as f:
            anterior = f.read()
        nuevo = documento.ride_pdf()
        faltan = diferencias(self._para_comparar(documento, nuevo), xml)
        faltan_antes = diferencias(anterior, xml)
        numero = documento.voucher_number_full
        self.stdout.write(f'{etiqueta}{numero} (emitida {documento.emission_date or documento.date_joined:%d/%m/%Y}): PDF guardado '
                          f'{documento.pdf_authorized.name} ({len(anterior) // 1024} KB, fiel al XML: {"sí" if not faltan_antes else "no"}); '
                          f'nuevo {len(nuevo) // 1024} KB, fiel al XML: {"sí" if not faltan else "NO"}')
        for campo, esperado in faltan:
            self.stdout.write(f'    no coincide {campo}: el XML autorizado dice «{esperado}»')
        if salida:
            Path(salida, f'{prefijo}{numero}-nuevo.pdf').write_bytes(nuevo)
        if faltan:
            return 'con diferencias'
        if aplicar:
            copia = Path(respaldo, Path(documento.pdf_authorized.name).name)
            with documento.pdf_authorized.open('rb') as f, open(copia, 'wb') as destino:
                shutil.copyfileobj(f, destino)
            previo = documento.pdf_authorized.name
            documento.pdf_authorized.save('ride.pdf', ContentFile(nuevo), save=False)   # archivo nuevo (ruta y largo del campo); el anterior queda
            nombre = documento.pdf_authorized.name
            modelo.objects.filter(pk=documento.pk).update(pdf_authorized=nombre)
            extra = {} if clave == 'factura' else {'tipo': clave}   # el registro de las facturas conserva su forma
            audit(None, 'ride_regenerado', company=documento.company, comprobante=numero, anterior=previo, nuevo=nombre, **extra)
            self.stdout.write(f'    aplicado: ahora {nombre}; el anterior sigue en {previo} y copiado en {copia}')
        return 'fieles'
