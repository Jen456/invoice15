"""Comprueba el libro diario de una empresa y un año: lo mismo que GET /contabilidad/api/integridad/?anio=.

    python manage.py verificar_libro --empresa ID [--anio AAAA] [--json]

Comprobaciones: cuadre de cada asiento, numeración sin huecos, huellas, acumulados por cuenta y mes (totales, de apertura y
de cierre), un solo asiento de apertura vigente y ningún asiento sin sellar. Solo lee. Termina con error (código 1) si
alguna comprobación falla, para que un guion de mantenimiento lo note."""
import json

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = 'Comprueba el libro diario de una empresa en un año (cuadre, numeración, huellas, acumulados, apertura, sellos).'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', type=int, required=True, help='Id de la empresa.')
        parser.add_argument('--anio', type=int, default=None, help='Año del ejercicio (por defecto, el año en curso).')
        parser.add_argument('--json', action='store_true', help='Escribe el resultado como JSON.')

    def handle(self, *args, **opciones):
        from core.contabilidad import diario
        from core.pos.models import Company
        from core.tenancy.context import company_context
        anio = opciones['anio'] or timezone.localdate().year
        if not diario.ANIO_MIN <= anio <= diario.ANIO_MAX:
            raise CommandError(f'El año va de {diario.ANIO_MIN} a {diario.ANIO_MAX}.')
        empresa = Company.objects.filter(pk=opciones['empresa']).first()
        if empresa is None:
            raise CommandError(f'No existe la empresa {opciones["empresa"]}.')
        with company_context(empresa):
            resultado = diario.verificar(anio)
        if opciones['json']:
            self.stdout.write(json.dumps(resultado, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(f'Empresa {empresa.pk} ({empresa.business_name}), año {anio}: {resultado["asientos"]} asientos.')
            for comprobacion in resultado['comprobaciones']:
                estado = 'bien' if comprobacion['ok'] else f'FALLA ({len(comprobacion["detalle"])} casos)'
                self.stdout.write(f'  {comprobacion["codigo"]}: {estado}')
                for caso in comprobacion['detalle']:
                    self.stdout.write(f'    {json.dumps(caso, ensure_ascii=False)}')
        fallidas = [c['codigo'] for c in resultado['comprobaciones'] if not c['ok']]
        if fallidas:
            raise CommandError(f'El libro no pasa: {", ".join(fallidas)}.')
