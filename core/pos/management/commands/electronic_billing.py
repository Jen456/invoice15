import os

import django
from django.core.management import BaseCommand

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.pos.models import *
from core.tenancy.context import company_context


class Command(BaseCommand):
    help = "This microservice is responsible for authorizing electronic invoices and sending them by mail"

    def add_arguments(self, parser):
        parser.add_argument('--date_joined', nargs='?', type=str, default=None, help='Fecha de registro')

    def handle(self, *args, **options):
        date_joined = options['date_joined'] if options['date_joined'] else datetime.now().date()
        # Cada empresa en su propio contexto: sus comprobantes, su firma y su correo.
        for company in Company.objects.filter(is_active=True).order_by('id'):
            with company_context(company):
                self.process(date_joined)

    def process(self, date_joined):
        sri = SRI()
        excluded_invoice_states = [INVOICE_STATUS[2][0], INVOICE_STATUS[3][0], INVOICE_STATUS[4][0]]
        for instance in Sale.objects.filter(date_joined=date_joined, receipt__voucher_type=VOUCHER_TYPE[0][0], create_electronic_invoice=True).exclude(status__in=excluded_invoice_states):
            if instance.status == INVOICE_STATUS[0][0]:
                instance.generate_electronic_invoice()
            elif instance.status == INVOICE_STATUS[1][0]:
                sri.notify_by_email(instance=instance, company=instance.company, client=instance.client)
        for instance in CreditNote.objects.filter(date_joined=date_joined, create_electronic_invoice=True).exclude(status__in=excluded_invoice_states):
            if instance.status == INVOICE_STATUS[0][0]:
                instance.generate_electronic_invoice()
            elif instance.status == INVOICE_STATUS[1][0]:
                sri.notify_by_email(instance=instance, company=instance.company, client=instance.sale.client)
