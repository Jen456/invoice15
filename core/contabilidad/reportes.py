"""Provisionalidad de los reportes contables en un solo sitio (decisión común 17 de contable/bloque-2-especificacion.md).

`provisionalidad(reporte, desde, hasta)` → `(provisional, causas, causas_detalle)`: el diario, el mayor, los estados
financieros y el 101 llaman a esta misma función, y ninguno mantiene una lista paralela. `causas` son los textos (la forma
de V9 C6 y de C6-A) y `causas_detalle`, `[{"codigo", "texto", "cantidad"?}]` con códigos estables.

Cada bloque **registra** sus causas en `CAUSAS` con `registrar` (y el bloque 3 retira `motor_pendiente` con `retirar`
cuando la sustituye por las suyas). Una causa es una función que recibe el contexto del reporte y devuelve si aplica:
`False`/`None` (no aplica), `True` (aplica) o un entero (aplica con esa cantidad; cero = no aplica). Se evalúan en el
orden en que se registraron.

Ningún rango se supone completo por tener la apertura confirmada: mientras la operación no se contabilice, todo reporte
cuyo rango pase de la fecha de corte sale provisional por `motor_pendiente`."""
from dataclasses import dataclass
from functools import cached_property

from django.db.models import Exists, OuterRef

from core.contabilidad.modelos_apertura import CONFIRMADA, VIGENTE
from core.contabilidad.modelos_libro import CONFIRMADO
from core.contabilidad.models import AplicacionAuxiliar, Apertura, Contabilizacion, InicioContable

# Reportes que leen el resultado de un ejercicio de sus cuentas de ingresos, costos y gastos (bloques 5 y 6).
DE_RESULTADOS = ('estado_resultados', 'resultado_anual_101')


@dataclass(frozen=True)
class Causa:
    codigo: str
    texto: str
    evaluar: object
    reportes: tuple = ()   # vacío: aplica a todos


CAUSAS = {}


def registrar(codigo, texto, reportes=()):
    """Decorador: registra la función como la causa `codigo` (código estable; uno por causa)."""
    def decorar(evaluar):
        if codigo in CAUSAS:
            raise ValueError(f'La causa {codigo} ya está registrada.')
        CAUSAS[codigo] = Causa(codigo, texto, evaluar, tuple(reportes))
        return evaluar
    return decorar


def retirar(codigo):
    """Quita una causa registrada (el bloque que la sustituye por las suyas)."""
    CAUSAS.pop(codigo)


@dataclass
class Contexto:
    """Lo que una causa necesita saber del reporte, leído una vez y solo si alguna lo pide."""
    reporte: str
    desde: object
    hasta: object

    @cached_property
    def inicio(self):
        return InicioContable.objects.first()

    @cached_property
    def apertura(self):
        return Apertura.objects.filter(estado=CONFIRMADA).first()

    def pasa_del_corte(self):
        """El rango llega más allá de la fecha de corte (sin corte configurado, no se sabe: se toma como que sí)."""
        return self.inicio is None or self.hasta is None or self.hasta > self.inicio.fecha_corte


def provisionalidad(reporte, desde, hasta, *, solo=None, **leido):
    """`(provisional, causas, causas_detalle)` del reporte `reporte` para el rango [desde, hasta], en la empresa activa.

    `solo`: los códigos que se evalúan (la cobertura de lo anterior al corte solo pregunta por el inicio y la apertura).
    `leido`: lo que quien llama ya leyó de la empresa activa (`inicio`, `apertura` confirmada o None), para no volver a
    consultarlo; nunca cambia qué se decide, solo de dónde sale."""
    contexto = Contexto(reporte, desde, hasta)
    for nombre in ('inicio', 'apertura'):
        if nombre in leido:
            contexto.__dict__[nombre] = leido[nombre]   # lo que cached_property habría leído
    detalle = []
    for causa in CAUSAS.values():
        if causa.reportes and reporte not in causa.reportes:
            continue
        if solo is not None and causa.codigo not in solo:
            continue
        resultado = causa.evaluar(contexto)
        if resultado is None or resultado is False or (resultado is not True and not resultado):
            continue
        entrada = {'codigo': causa.codigo, 'texto': causa.texto}
        if resultado is not True:
            entrada['cantidad'] = int(resultado)
        detalle.append(entrada)
    return bool(detalle), [entrada['texto'] for entrada in detalle], detalle


# ---------------------------------------------------------------- causas de este bloque (libro y apertura)

@registrar('inicio_sin_configurar', 'La empresa todavía no configuró su inicio contable: falta la modalidad y la fecha de '
           'corte.')
def _inicio_sin_configurar(contexto):
    return contexto.inicio is None


@registrar('apertura_sin_confirmar', 'La apertura contable no está confirmada: sin saldos iniciales confirmados no se '
           'supone que sean cero.')
def _apertura_sin_confirmar(contexto):
    return contexto.inicio is not None and contexto.inicio.modalidad == 'saldos' and contexto.apertura is None


@registrar('saldo_anterior_sin_confirmar', 'El saldo anterior al historial no está confirmado: no se supone que sea cero.')
def _saldo_anterior_sin_confirmar(contexto):
    return contexto.inicio is not None and contexto.inicio.modalidad == 'historial' and contexto.apertura is None


@registrar('resultados_acumulados_sin_detalle', 'El resultado del ejercicio del corte está en patrimonio, sin el detalle de '
           'sus ingresos, costos y gastos.', reportes=DE_RESULTADOS)
def _resultados_acumulados_sin_detalle(contexto):
    """Permanente para el ejercicio del corte cuando la apertura declara el resultado en patrimonio (regla 6 de la Parte B)."""
    apertura = contexto.apertura
    if apertura is None or apertura.resultado_ejercicio != 'en_patrimonio':
        return False
    anio = apertura.fecha_corte.year
    return (contexto.desde is None or contexto.desde.year <= anio) and (contexto.hasta is None or contexto.hasta.year >= anio)


@registrar('aplicaciones_sin_contabilizar', 'Hay cobros, pagos o descargos sobre saldos iniciales sin contabilizar.')
def _aplicaciones_sin_contabilizar(contexto):
    """Las aplicaciones vigentes del rango cuyo expediente no está confirmado (una consulta agregada)."""
    aplicaciones = AplicacionAuxiliar.objects.filter(estado=VIGENTE)
    if contexto.desde is not None:
        aplicaciones = aplicaciones.filter(fecha__gte=contexto.desde)
    if contexto.hasta is not None:
        aplicaciones = aplicaciones.filter(fecha__lte=contexto.hasta)
    contabilizada = Contabilizacion.objects.filter(origen_tipo='aplicacion_auxiliar', origen_id=OuterRef('pk'),
                                                   evento='registro', estado=CONFIRMADO)
    return aplicaciones.filter(~Exists(contabilizada)).count()


@registrar('motor_pendiente', 'Los documentos de la operación todavía no se contabilizan.')
def _motor_pendiente(contexto):
    """Obligatoria en todo reporte cuyo rango pase de la fecha de corte; el bloque 3 la sustituye por las suyas."""
    return contexto.pasa_del_corte()
