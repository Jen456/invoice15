from django.core.management.base import BaseCommand

from core.pos.emision import consultar_pendientes


class Command(BaseCommand):
    help = ('Consulta en el SRI los comprobantes «En proceso» y envía los firmados que no llegaron a enviarse '
            '(todas las empresas). Lo ejecuta el temporizador facturaporaqui-sri@<entorno>.timer.')

    def add_arguments(self, parser):
        parser.add_argument('--limite', type=int, default=200, help='Máximo de comprobantes por tipo en cada pasada')

    def handle(self, *args, **options):
        resumen = consultar_pendientes(limite=options['limite'])
        self.stdout.write('consultados {consultados}, autorizados {autorizados}, en proceso {pendientes}, '
                          'con error {con_error}'.format(**resumen))
