from django.core.management import BaseCommand

from core.suscripciones.servicios import vencer_pendientes


class Command(BaseCommand):
    help = 'Marca como expirados los pagos que no volvieron de PayPhone (el formulario dura 10 minutos).'

    def handle(self, *args, **options):
        self.stdout.write(f'Pagos expirados: {vencer_pendientes()}')
