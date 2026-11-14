"""Períodos contables (meses) de la empresa: aquí solo la comprobación que necesita el diario. Cerrar y reabrir un mes son
del bloque 4, que añade aquí sus funciones con la misma regla: todo lo de este módulo va con el candado del libro
(decisión común 3), porque decide qué puede entrar en él.

Un mes sin fila `PeriodoContable` está abierto. En este bloque ninguna fila se cierra.

`exigir_abierto` no bloquea la fila del período: con el candado tomado nadie más la cambia (cerrar o reabrir también lo
toman), así que leerla basta y no se añade un paso al orden de bloqueos."""
from core.contabilidad import candado
from core.contabilidad.modelos_libro import CERRADO
from core.contabilidad.models import PeriodoContable


def mes_de(fecha):
    """El período de una fecha como lo muestra el contrato: `AAAA-MM`."""
    return f'{fecha:%Y-%m}'


def exigir_abierto(fecha):
    """Con el candado: `ErrorDiario('periodo_cerrado', periodo='AAAA-MM')` si el mes de `fecha` está cerrado."""
    from core.contabilidad.diario import ErrorDiario   # diario importa este módulo
    candado.exigir()
    if PeriodoContable.objects.filter(anio=fecha.year, mes=fecha.month, estado=CERRADO).exists():
        raise ErrorDiario('periodo_cerrado', periodo=mes_de(fecha))
