"""Estado del cifrado de las claves de firma (.p12) de todas las empresas, sin mostrarlas.

  manage.py claves_firma              cuenta cifradas, sin cifrar, ilegibles y vacías; sale con error si hay ilegibles
  manage.py claves_firma --recifrar   cifra las que falten y vuelve a cifrar todas con la primera llave (rotación)
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from core.pos.models import Company
from core.tenancy import cifrado


class Command(BaseCommand):
    help = 'Estado del cifrado de las claves de firma electrónica (y rotación con --recifrar).'

    def add_arguments(self, parser):
        parser.add_argument('--recifrar', action='store_true', help='Cifra con la primera llave de FPA_CLAVES_CIFRADO.')

    def handle(self, *args, recifrar=False, **options):
        tabla = Company._meta.db_table
        with transaction.atomic(), connection.cursor() as cursor:
            bloqueo = ' FOR UPDATE' if connection.features.has_select_for_update else ''
            cursor.execute(f'SELECT id, electronic_signature_key FROM {tabla} ORDER BY id{bloqueo}')
            filas = cursor.fetchall()
            cuenta = {'cifradas': 0, 'sin cifrar': 0, 'ilegibles': 0, 'vacías': 0}
            ilegibles = []
            for pk, guardado in filas:
                if not guardado:
                    cuenta['vacías'] += 1
                    continue
                if not guardado.startswith(cifrado.PREFIJO):
                    cuenta['sin cifrar'] += 1
                    nuevo = cifrado.cifrar(guardado)
                elif isinstance(cifrado.descifrar(guardado), cifrado.SecretoIlegible):
                    cuenta['ilegibles'] += 1
                    ilegibles.append(pk)
                    continue
                else:
                    cuenta['cifradas'] += 1
                    nuevo = cifrado.recifrar(guardado)
                if recifrar:
                    cursor.execute(f'UPDATE {tabla} SET electronic_signature_key = %s WHERE id = %s', [nuevo, pk])
        self.stdout.write(', '.join(f'{k} {v}' for k, v in cuenta.items()) + (' — recifradas con la primera llave' if recifrar else ''))
        if ilegibles:
            raise CommandError(f'Claves que no se pueden descifrar con FPA_CLAVES_CIFRADO (empresas {ilegibles}); '
                               'no se modificaron. Revisa la llave antes de activar esta versión.')
