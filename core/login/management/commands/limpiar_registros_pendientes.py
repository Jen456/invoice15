"""Borra los registros propios que nadie confirmó a tiempo.

Así un RUC, un usuario o un correo no quedan ocupados por un registro abandonado.
Solo toca usuarios inactivos, sin correo confirmado, con registro propio, más
antiguos que --horas, y su empresa si no tiene otros miembros ni datos.
"""
from datetime import timedelta

from django.core.management import BaseCommand
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone

from config import settings
from core.login.forms import registro_pendiente
from core.tenancy.context import platform_scope
from core.tenancy.models import Membership
from core.user.models import User


class Command(BaseCommand):
    help = 'Borra registros propios sin confirmar más antiguos que --horas (por defecto, el doble de la validez del enlace).'

    def add_arguments(self, parser):
        parser.add_argument('--horas', type=int, default=settings.FPA_REGISTRO_HORAS_ENLACE * 2)
        parser.add_argument('--ensayo', action='store_true', help='Solo lista lo que se borraría.')

    def handle(self, *args, **options):
        limite = timezone.now() - timedelta(hours=options['horas'])
        candidatos = [u for u in User.objects.filter(is_active=False, email_verified_at__isnull=True,
                                                     date_joined__lt=limite) if registro_pendiente(u)]
        borrados = 0
        with platform_scope():
            for user in candidatos:
                empresas = [m.company for m in Membership.objects.filter(user=user).select_related('company')
                            if not Membership.objects.filter(company=m.company).exclude(user=user).exists()]
                self.stdout.write(f'{"(ensayo) " if options["ensayo"] else ""}{user.username} '
                                  f'({user.date_joined:%Y-%m-%d %H:%M}) y {len(empresas)} empresa(s)')
                if options['ensayo']:
                    continue
                try:
                    with transaction.atomic():
                        for empresa in empresas:
                            empresa.delete()
                        user.delete()
                    borrados += 1
                except ProtectedError:
                    self.stdout.write(f'  se conserva {user.username}: su empresa ya tiene datos')
        self.stdout.write(f'Registros sin confirmar borrados: {borrados} de {len(candidatos)}')
