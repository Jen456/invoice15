"""Configuración de facturación para las empresas existentes, sin reiniciar ni sobrescribir numeraciones.

- Cada secuencia existente toma el ambiente de su empresa y queda como «existente».
  Su último número (sequence) NO cambia.
- Si la empresa ya tenía comprobantes, su establecimiento y punto se registran a
  partir de los códigos de la empresa, y las secuencias usadas quedan confirmadas.
  La configuración se da por confirmada para no bloquear a quien ya emite.
- Si no tenía comprobantes, la configuración queda pendiente. Si tenía secuencias
  sin usar, el establecimiento y el punto se registran desde sus códigos, pero
  hay que confirmarlos en el asistente. A las empresas sin secuencias no se les
  asigna 001-001.
"""
import re

from django.db import migrations
from django.utils import timezone

CODIGO = re.compile(r'(?!000)\d{3}')


def forwards(apps, schema_editor):
    Company = apps.get_model('pos', 'Company')
    Receipt = apps.get_model('pos', 'Receipt')
    Sale = apps.get_model('pos', 'Sale')
    CreditNote = apps.get_model('pos', 'CreditNote')
    Establishment = apps.get_model('pos', 'Establishment')
    EmissionPoint = apps.get_model('pos', 'EmissionPoint')
    BillingSetup = apps.get_model('pos', 'BillingSetup')
    ahora = timezone.now()
    for company in Company.objects.all():
        setup = BillingSetup.objects.filter(company=company).first() or BillingSetup.objects.create(company=company)
        secuencias = list(Receipt.objects.filter(company=company))
        emitio = Sale.objects.filter(company=company).exists() or CreditNote.objects.filter(company=company).exists()
        punto = None
        codigos = CODIGO.fullmatch(company.establishment_code or '') and CODIGO.fullmatch(company.issuing_point_code or '')
        if secuencias and codigos:
            establecimiento, _ = Establishment.objects.get_or_create(
                company=company, code=company.establishment_code,
                defaults={'address': company.establishment_address or company.main_address or 'PENDIENTE'})
            punto, _ = EmissionPoint.objects.get_or_create(company=company, establishment=establecimiento,
                                                           code=company.issuing_point_code, defaults={'is_default': True})
        for r in secuencias:
            r.environment_type = company.environment_type
            r.origin = 'existente'
            if punto is not None and (r.establishment_code, r.issuing_point_code) == (company.establishment_code, company.issuing_point_code):
                r.emission_point = punto
            if Sale.objects.filter(receipt=r).exists() or CreditNote.objects.filter(receipt=r).exists():
                r.confirmed_at = ahora
            r.save()
        if emitio and punto is not None:
            setup.completed_steps, setup.current_step, setup.completed_at = [1, 2, 3, 4, 5], 5, ahora
            setup.production_confirmed = company.environment_type == 2
            setup.save()


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0008_configuracion_facturacion'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
