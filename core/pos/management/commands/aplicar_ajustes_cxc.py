"""Aplica a la cuenta por cobrar las notas de crédito y de débito AUTORIZADAS cuyo ajuste quedó pendiente (un receptor de
comprobante_autorizado falló o la petición murió tras autorizar). Nunca toca las 'no_aplica' (históricas: las regulariza
regularizar_cxc_historico con decisión de la propietaria).

  manage.py aplicar_ajustes_cxc [--empresa RUC]
      ENSAYO (por defecto): lista cada documento pendiente y el efecto previsto; no cambia nada.
  manage.py aplicar_ajustes_cxc [--empresa RUC] --aplicar
      Aplica la regla que ya debió aplicarse al autorizar (idempotente): por eso no pide --decision. El abono o la cuenta
      por cobrar creados son el registro; no se audita por documento.
"""
from django.core.management.base import BaseCommand, CommandError

from core.pos import cxc
from core.pos.models import Company
from core.tenancy.context import company_context


class Command(BaseCommand):
    help = 'Aplica a la CxC las NC y ND autorizadas con ajuste pendiente (ensayo por defecto).'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', help='RUC de la empresa (por defecto, todas las activas).')
        parser.add_argument('--aplicar', action='store_true', help='Aplica los ajustes (sin esta opción solo se informa).')

    def handle(self, *args, empresa=None, aplicar=False, **options):
        empresas = Company.objects.filter(is_active=True).order_by('pk')
        if empresa:
            empresas = empresas.filter(ruc=empresa)
            if not empresas.exists():
                raise CommandError(f'No hay una empresa activa con RUC {empresa}.')
        resumen = {'pendientes': 0, 'aplicados': 0}
        for company in empresas:
            with company_context(company):
                pendientes = cxc.pendientes(company)
                for nota in pendientes['notas_credito']:
                    resumen['pendientes'] += 1
                    efecto, _, valor, excedente = cxc.prever_nota_credito(nota)
                    texto = f'{company.ruc} NC {nota.voucher_number_full}: {efecto} (abono {valor:.2f}, excedente {excedente:.2f})'
                    if aplicar:
                        texto += f' → {cxc.aplicar_nota_credito(nota.pk)}'
                        resumen['aplicados'] += 1
                    self.stdout.write(texto)
                for nota in pendientes['notas_debito']:
                    resumen['pendientes'] += 1
                    texto = f'{company.ruc} ND {nota.voucher_number_full}: aplicada (cuenta por cobrar de {nota.valor_total:.2f})'
                    if aplicar:
                        texto += f' → {cxc.aplicar_nota_debito(nota.pk)}'
                        resumen['aplicados'] += 1
                    self.stdout.write(texto)
        modo = 'APLICADO' if aplicar else 'ENSAYO (no se cambió nada)'
        self.stdout.write(f'{modo}: pendientes {resumen["pendientes"]}, aplicados {resumen["aplicados"]}')
