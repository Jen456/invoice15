"""Imágenes de código de barras que ningún producto usa (huérfanas) y productos cuya imagen falta, por empresa.

  manage.py limpiar_codigos_barra [--empresa RUC]              informe (no cambia nada)
  manage.py limpiar_codigos_barra [--empresa RUC] --aplicar    borra las huérfanas y rehace las que faltan

Solo borra huérfanas con más de --minutos (60): una imagen recién escrita puede ser de un producto que aún se está guardando.
"""
import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.pos.models import Company, Product
from core.tenancy.context import company_context, platform_scope
from core.tenancy.storage import TENANT_ROOT


class Command(BaseCommand):
    help = 'Borra las imágenes de código de barras huérfanas y rehace las que faltan (informe salvo --aplicar).'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', help='RUC de una sola empresa (por defecto, todas).')
        parser.add_argument('--aplicar', action='store_true', help='Borra y rehace (sin esto, solo informa).')
        parser.add_argument('--minutos', type=int, default=60, help='Antigüedad mínima de una huérfana para borrarla.')

    def handle(self, *args, empresa=None, aplicar=False, minutos=60, **options):
        empresas = Company.objects.order_by('pk')
        if empresa:
            empresas = empresas.filter(ruc=empresa)
            if not empresas.exists():
                raise CommandError(f'No hay una empresa con el RUC {empresa}.')
        limite = time.time() - minutos * 60
        total = {'huérfanas': 0, 'borradas': 0, 'faltan': 0, 'rehechas': 0}
        for company in empresas:
            with platform_scope():
                usadas = dict(Product.all_companies.filter(company=company).exclude(barcode='').exclude(barcode__isnull=True)
                              .values_list('barcode', 'pk'))
            raiz = os.path.join(settings.MEDIA_ROOT, TENANT_ROOT, str(company.uuid), 'codigos')
            huerfanas = []
            for carpeta, _, archivos in os.walk(raiz):
                for archivo in archivos:
                    ruta = os.path.join(carpeta, archivo)
                    if os.path.relpath(ruta, settings.MEDIA_ROOT) not in usadas:
                        huerfanas.append(ruta)
            viejas = [r for r in huerfanas if os.path.getmtime(r) < limite]
            faltan = [pk for nombre, pk in usadas.items() if not os.path.exists(os.path.join(settings.MEDIA_ROOT, nombre))]
            if not huerfanas and not faltan:
                continue
            total['huérfanas'] += len(huerfanas)
            total['faltan'] += len(faltan)
            if aplicar:
                for ruta in viejas:
                    os.remove(ruta)
                total['borradas'] += len(viejas)
                with company_context(company):
                    for producto in Product.objects.filter(pk__in=faltan):
                        producto.generate_barcode()
                        Product.objects.filter(pk=producto.pk).update(barcode=producto.barcode.name)
                total['rehechas'] += len(faltan)
            self.stdout.write(f'empresa {company.pk} {company.business_name}: {len(huerfanas)} huérfanas '
                              f'({len(viejas)} con más de {minutos} min), {len(faltan)} productos sin imagen')
        self.stdout.write(('APLICADO' if aplicar else 'INFORME (no se cambió nada)') + ' — ' +
                          ', '.join(f'{k} {v}' for k, v in total.items()))
