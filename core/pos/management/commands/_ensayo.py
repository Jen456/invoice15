"""Opciones y comprobaciones comunes de las órdenes de datos de origen de Compras (espec-etapa2-compras §3.9).

Ensayo por defecto: sin --aplicar no se escribe nada en la base. --aplicar exige --empresa ID o --todas, la decisión escrita
(--decision, mínimo 10 caracteres) y el informe revisable (--csv RUTA); la decisión y la ruta del informe quedan en la
auditoría de cada cambio. No se ejecutan contra datos reales en esta fase.
"""
import csv
import re

from django.core.management.base import CommandError

MINIMO_DECISION = 10
INICIO_DE_FORMULA = ('=', '+', '-', '@', '\t', '\r')
NUMERO = re.compile(r'-?\d+(\.\d+)?')


def celda(valor):
    """Texto seguro para una hoja de cálculo: una celda que empieza como fórmula (=, +, -, @, tabulador o retorno) lleva
    un apóstrofo delante; los números con signo se dejan tal cual. Las razones sociales pueden venir del XML de un tercero."""
    if isinstance(valor, str) and valor.startswith(INICIO_DE_FORMULA) and not NUMERO.fullmatch(valor):
        return "'" + valor
    return valor


def agregar_opciones(parser):
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument('--empresa', type=int, help='Solo esta empresa (id).')
    grupo.add_argument('--todas', action='store_true', help='Todas las empresas.')
    parser.add_argument('--aplicar', action='store_true', help='Aplica los cambios (sin esta opción es un ensayo).')
    parser.add_argument('--decision', default='', help='Motivo y quién autorizó el cambio (obligatorio con --aplicar).')
    parser.add_argument('--csv', default='', help='Ruta del informe CSV (obligatorio con --aplicar).')


def comprobar(opciones):
    if not opciones['aplicar']:
        return
    if not (opciones['empresa'] or opciones['todas']):
        raise CommandError('--aplicar exige --empresa ID o --todas')
    if len((opciones['decision'] or '').strip()) < MINIMO_DECISION:
        raise CommandError('--aplicar exige --decision con el motivo y quién lo autorizó')
    if not opciones['csv']:
        raise CommandError('--aplicar exige --csv RUTA con el informe revisable')


def empresas(opciones):
    from core.pos.models import Company
    from core.tenancy.context import platform_scope
    with platform_scope():
        consulta = Company.objects.order_by('pk')
        if opciones['empresa']:
            consulta = consulta.filter(pk=opciones['empresa'])
        lista = list(consulta)
    if opciones['empresa'] and not lista:
        raise CommandError(f'No existe la empresa {opciones["empresa"]}.')
    return lista


class Informe:
    """Filas del informe: CSV (si se pidió) abierto desde el inicio, para fallar antes de cambiar nada."""

    def __init__(self, ruta, columnas):
        self.ruta, self.columnas, self.filas = ruta, columnas, []
        self._archivo = open(ruta, 'w', newline='', encoding='utf-8') if ruta else None
        self._escritor = csv.DictWriter(self._archivo, fieldnames=columnas) if self._archivo else None
        if self._escritor:
            self._escritor.writeheader()

    def agregar(self, fila):
        fila = {c: fila.get(c, '') for c in self.columnas}
        self.filas.append(fila)
        if self._escritor:
            self._escritor.writerow({c: celda(v) for c, v in fila.items()})
            self._archivo.flush()

    def cerrar(self):
        if self._archivo:
            self._archivo.close()
