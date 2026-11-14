"""Candado del libro por empresa (decisión común 3 de contable/bloque-2-especificacion.md): la fila `InicioContable` de la
empresa, tomada con `select_for_update(of=('self',))`.

Lo toma primero toda transacción que cambie el libro o lo que decide qué puede entrar en él: contabilizar, reversar,
confirmar, sustituir, reversar o ajustar una apertura, cambiar el corte, cerrar o reabrir un período o un ejercicio. Con la
fila bloqueada no hay otro escritor del libro de esa empresa: el número siguiente, los acumulados por cuenta y mes y la
decisión «¿este período está abierto?» no cambian entre que se leen y se escriben.

Orden global de bloqueos (decisión común 4): el candado es el paso 1. Antes solo van, cuando una acción contable necesita
leer de forma estable una fila de la operación, esas filas en su orden existente; después, Apertura, auxiliares,
expediente, asiento original, ejercicio, período y acumulados, en ese orden.

`diario.contabilizar`, `diario.reversar` y `periodos.*` exigen la marca que deja `libro()` (variable de contexto): llamados
fuera de él fallan con `SinCandado`, un error de programación y no una respuesta para el usuario."""
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import IntegrityError, connection, transaction

from core.contabilidad import api
from core.contabilidad import capacidades as cap
from core.contabilidad.models import InicioContable
from core.tenancy.context import current_company_id

INICIO_SIN_CONFIGURAR = 'inicio_sin_configurar'
TEXTO_SIN_INICIO = ('La empresa todavía no configuró su inicio contable (modalidad y fecha de corte): configúralo antes '
                    'de registrar algo en el libro.')

# La fila del candado tomada en esta transacción (o None). Una variable de contexto, no un atributo de la conexión: cada
# hilo y cada petición tienen la suya, y al salir de `libro()` vuelve a lo que había.
_marca = ContextVar('fpa_candado_del_libro', default=None)


class SinCandado(RuntimeError):
    """Se llamó a una función que escribe en el libro sin `candado.libro()`. Error de programación."""


def rechazo_sin_inicio():
    """409 `datos_por_completar` con `inicio_sin_configurar`: la forma de capacidades.rechazo_datos."""
    return api.Rechazo(cap.rechazo_datos([cap.dato(INICIO_SIN_CONFIGURAR, TEXTO_SIN_INICIO)]))


def _bloquear():
    return InicioContable.objects.select_for_update(of=('self',)).filter().first()


def _crear(datos):
    """Crea la fila del candado con el patrón de carrera de `reglas_de` (core/importacion/servicios.py:53-61): si otra
    transacción la creó a la vez, la restricción única decide y se toma la suya (esperando a que confirme)."""
    try:
        with transaction.atomic():
            inicio = InicioContable(**datos)
            inicio.save()
            return inicio
    except IntegrityError:
        inicio = _bloquear()
        if inicio is None:   # el IntegrityError era otro (un CHECK): no se esconde
            raise
        return inicio


@contextmanager
def libro(crear=None):
    """Abre `transaction.atomic()`, bloquea la fila `InicioContable` de la empresa activa y deja la marca de contexto que
    exigen el diario y los períodos. Devuelve la fila bloqueada.

    Sin fila: 409 `datos_por_completar` (`inicio_sin_configurar`), salvo con `crear={campos}`, que solo usa
    `inicio_contable.configurar`: entonces la crea. Si la fila ya existe, `crear` no se usa (quien configura la cambia
    después, con la fila ya bloqueada)."""
    with transaction.atomic():
        inicio = _bloquear()
        if inicio is None:
            if crear is None:
                raise rechazo_sin_inicio()
            inicio = _crear(crear)
        token = _marca.set(inicio)
        try:
            yield inicio
        finally:
            _marca.reset(token)


def tomar_si_existe():
    """Dentro de una transacción ya abierta: bloquea la fila del candado si la empresa tiene inicio contable y la devuelve
    (None si no lo tiene). No deja la marca, porque quien lo llama no escribe en el libro: es para lo que no puede cruzarse
    con él, como reclasificar una cuenta (lo validado con su clase no cambia mientras se contabiliza o se confirma una
    apertura). Sin inicio contable no hay libro con el que cruzarse."""
    if not connection.in_atomic_block:
        raise SinCandado('candado.tomar_si_existe() va dentro de transaction.atomic().')
    return _bloquear()


def exigir():
    """La fila del candado de esta transacción. Lanza `SinCandado` fuera de `libro()`, fuera de una transacción o si la
    marca es de otra empresa que la activa."""
    inicio = _marca.get()
    if inicio is None or not connection.in_atomic_block:
        raise SinCandado('El libro solo se escribe dentro de candado.libro().')
    if inicio.company_id != current_company_id():
        raise SinCandado('El candado tomado es de otra empresa que la activa.')
    return inicio


def tomado():
    """True si esta transacción tiene el candado del libro (para las comprobaciones que lo dan por supuesto)."""
    try:
        exigir()
    except SinCandado:
        return False
    return True
