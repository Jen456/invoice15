"""Calendario de vencimientos del 104 (IVA) y del 103 (retenciones) de la empresa (Etapa 2, O2).

Solo calcula lo que confirma NORMA-CONTABLE-TRIBUTARIA-2026-10.md (§1–§2, RLRTI art. 102): el día de vencimiento sale del
noveno dígito del RUC, en el mes siguiente al período, y pasa al siguiente día hábil si cae en sábado, domingo o en un
feriado conocido. El 104 semestral y los plazos de contribuyentes especiales se muestran con confirmado=False. Los
feriados nacionales no tienen fuente oficial en el repo (FERIADOS_NACIONALES vacío, decisión 5): el resultado lo advierte.
El ATS es de la Etapa 4. Las sugerencias de tipo de contribuyente y periodicidad nunca se guardan solas.
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from core.login.identificacion import ruc_valido

DIA_POR_NOVENO_DIGITO = {'1': 10, '2': 12, '3': 14, '4': 16, '5': 18, '6': 20, '7': 22, '8': 24, '9': 26, '0': 28}
FERIADOS_NACIONALES: dict[int, tuple[date, ...]] = {}   # sin fuente oficial en el repo: vacío a propósito (§10)
FUENTE = 'NORMA-CONTABLE-TRIBUTARIA-2026-10.md §1–§2 (RLRTI art. 102)'

NOTA_SEMESTRAL = 'Plazo semestral por confirmar (RLRTI art. 158, no verificado en la norma del repo).'
NOTA_ESPECIAL = 'Contribuyente especial: confirma tu plazo.'
NOTA_FERIADOS = 'Si la fecha cae en feriado nacional, el plazo pasa al siguiente día hábil.'
NOTA_SUGERIDA = 'Periodicidad sugerida ({periodicidad}): complétala en Empresa.'
AUTORIZADOS = ('authorized', 'authorized_and_sent_by_email')


@dataclass(frozen=True)
class Vencimiento:
    obligacion: str           # '104' | '103'
    periodo: str              # '2026-09' | '2026-S1'
    desde: date
    hasta: date
    fecha_nominal: date       # día según el 9.º dígito
    fecha_limite: date        # tras pasar sábados, domingos y feriados conocidos
    confirmado: bool          # la regla está en la norma del repo y los datos de la empresa están completos
    feriados_cargados: bool   # hay feriados para ese año
    nota: str                 # texto para el usuario


def noveno_digito(ruc):
    ruc = (ruc or '').strip()
    if not ruc_valido(ruc):
        raise ValueError(f'RUC inválido: {ruc!r} no es un RUC de 13 dígitos válido.')
    return ruc[8]


def dia_de_vencimiento(ruc):
    return DIA_POR_NOVENO_DIGITO[noveno_digito(ruc)]


def siguiente_dia_habil(fecha, feriados=()):
    feriados = set(feriados or ())
    while fecha.weekday() >= 5 or fecha in feriados:
        fecha += timedelta(days=1)
    return fecha


def _mes_siguiente(anio, mes):
    return (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def _vencimiento(obligacion, periodo, desde, hasta, anio_venc, mes_venc, ruc, feriados, notas, confirmado):
    dia = dia_de_vencimiento(ruc)
    nominal = date(anio_venc, mes_venc, min(dia, calendar.monthrange(anio_venc, mes_venc)[1]))
    if feriados is None:
        cargados = anio_venc in FERIADOS_NACIONALES
        feriados = FERIADOS_NACIONALES.get(anio_venc, ())
    else:
        cargados = True
    if not cargados:
        notas = notas + [NOTA_FERIADOS]
    return Vencimiento(obligacion=obligacion, periodo=periodo, desde=desde, hasta=hasta, fecha_nominal=nominal,
                       fecha_limite=siguiente_dia_habil(nominal, feriados), confirmado=confirmado,
                       feriados_cargados=cargados, nota=' '.join(notas))


def _mensual(obligacion, ruc, anio, mes, feriados, especial):
    mes = int(mes)
    if not 1 <= mes <= 12:
        raise ValueError('El mes del período va de 1 a 12.')
    desde, hasta = date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])
    notas = [NOTA_ESPECIAL] if especial else []
    return _vencimiento(obligacion, f'{anio}-{mes:02d}', desde, hasta, *_mes_siguiente(anio, mes), ruc, feriados, notas,
                        confirmado=not especial)


def vencimiento_104(ruc, periodicidad, anio, periodo, feriados=None, especial=False):
    """periodicidad 'mensual' (periodo = mes 1–12) o 'semestral' (periodo 'S1' o 'S2')."""
    if periodicidad == 'mensual':
        return _mensual('104', ruc, anio, periodo, feriados, especial)
    if periodicidad != 'semestral' or periodo not in ('S1', 'S2'):
        raise ValueError('Periodicidad del IVA desconocida: usa mensual (1–12) o semestral (S1 / S2).')
    if periodo == 'S1':
        desde, hasta, anio_venc, mes_venc = date(anio, 1, 1), date(anio, 6, 30), anio, 7
    else:
        desde, hasta, anio_venc, mes_venc = date(anio, 7, 1), date(anio, 12, 31), anio + 1, 1
    notas = [NOTA_SEMESTRAL] + ([NOTA_ESPECIAL] if especial else [])
    return _vencimiento('104', f'{anio}-{periodo}', desde, hasta, anio_venc, mes_venc, ruc, feriados, notas, confirmado=False)


def vencimiento_103(ruc, anio, mes, feriados=None, especial=False):
    return _mensual('103', ruc, anio, mes, feriados, especial)


def _meses(desde, hasta):
    """Períodos mensuales cuyo vencimiento (mes siguiente) puede caer en [desde, hasta]."""
    anio, mes = (desde.year - 1, 12) if desde.month == 1 else (desde.year, desde.month - 1)
    while (anio, mes) <= (hasta.year, hasta.month):
        yield anio, mes
        anio, mes = _mes_siguiente(anio, mes)


def _emitio_retencion(company, anio, mes):
    """La empresa emitió en el mes una retención autorizada y sin anular (consulta en su contexto: en PostgreSQL rige la
    seguridad por filas)."""
    from core.comprobantes.models import Retencion
    from core.tenancy.context import company_context, current_company_id
    desde, hasta = date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])

    def consulta():
        return Retencion.objects.filter(status__in=AUTORIZADOS, anulado_sri_fecha__isnull=True,
                                        emission_date__range=(desde, hasta)).exists()
    if current_company_id() == company.pk:
        return consulta()
    with company_context(company):
        return consulta()


def vencimientos_de_empresa(company, desde, hasta, feriados=None):
    """104 y 103 de la empresa con fecha límite en [desde, hasta]. Sin periodicidad guardada, el 104 sale con la sugerida,
    solo para mostrar (confirmado=False). ValueError si el RUC no es válido."""
    especial = company.es_contribuyente_especial
    periodicidad, sugerida = company.periodicidad_iva, False
    if not periodicidad:
        periodicidad, sugerida = sugerir_periodicidad_iva(company)[0], True
    salida = []
    if periodicidad == 'mensual':
        for anio, mes in _meses(desde, hasta):
            salida.append(vencimiento_104(company.ruc, 'mensual', anio, mes, feriados, especial))
    else:
        for anio in range(desde.year - 1, hasta.year + 1):
            for periodo in ('S1', 'S2'):
                salida.append(vencimiento_104(company.ruc, 'semestral', anio, periodo, feriados, especial))
    if sugerida:
        salida = [Vencimiento(**{**v.__dict__, 'confirmado': False,
                                 'nota': ' '.join(filter(None, (NOTA_SUGERIDA.format(periodicidad=periodicidad), v.nota)))})
                  for v in salida]
    for anio, mes in _meses(desde, hasta):
        if company.retention_agent == 'SI' or _emitio_retencion(company, anio, mes):
            salida.append(vencimiento_103(company.ruc, anio, mes, feriados, especial))
    salida = [v for v in salida if desde <= v.fecha_limite <= hasta]
    return sorted(salida, key=lambda v: (v.fecha_limite, v.obligacion, v.periodo))


def sugerir_tipo_contribuyente(company):
    """(código, motivo) según el tercer dígito del RUC y «Obligado a llevar contabilidad». No se guarda nunca."""
    ruc = (company.ruc or '').strip()
    tercero = ruc[2] if len(ruc) >= 3 else ''
    if tercero in ('6', '9'):
        return 'sociedad', 'RUC de sociedad o entidad pública'
    if tercero and tercero in '012345':
        if company.obligated_accounting == 'SI':
            return 'pn_obligada', f'RUC de persona natural (tercer dígito {tercero}) obligada a llevar contabilidad'
        return 'pn_no_obligada', f'RUC de persona natural (tercer dígito {tercero}) no obligada a llevar contabilidad'
    return '', 'No se puede sugerir: revisa el RUC de la empresa.'


def sugerir_periodicidad_iva(company):
    """(código, motivo) según agente de retención y RIMPE. No se guarda nunca."""
    if company.retention_agent == 'SI':
        return 'mensual', 'Eres agente de retención: declaras el IVA cada mes'
    if company.rimpe:
        return 'semestral', 'Estás en el RIMPE: puedes declarar el IVA cada semestre'
    return 'mensual', 'Régimen general: el IVA se declara cada mes'
