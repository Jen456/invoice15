"""Lectura del libro diario (Parte A de contable/bloque-2-especificacion.md). Solo API: su pantalla la conecta la interfaz.

- GET /contabilidad/api/diario/?desde=&hasta=&tipo=&origen_tipo=&origen_id=&cuenta=&pagina=&por_pagina=&empresa=
  `view_asiento`: los asientos del rango por (fecha, número), con sus líneas, sus totales y la provisionalidad del rango.
  Sin fechas, el mes en curso. Sin inicio contable responde 200 (sin asientos) con la causa `inicio_sin_configurar`.
- GET /contabilidad/api/diario/<id>/   `view_asiento`: un asiento (404 `no_existe` si no es de la empresa).
- GET /contabilidad/api/integridad/?anio=   `view_asiento`: las comprobaciones del libro del año (sin `anio`, el año en
  curso); lo mismo que la orden `verificar_libro`.

Ver: Propietario, Administrador, Contador y Consulta. La sesión, la empresa de la pestaña y el permiso los comprueba
api.ApiContable; el complemento y el plan, PlanMiddleware (vencido: se consulta). Ninguna de estas rutas escribe.

Un diario cuyo rango pasa de la fecha de corte sigue provisional aunque la apertura esté confirmada (`motor_pendiente`):
ninguna venta, compra ni cobro ordinario se contabiliza todavía."""
import calendar
import re
from datetime import date

from django.db.models import Count, Exists, OuterRef, Sum
from django.http import JsonResponse
from django.utils import timezone

from core.contabilidad import api, capacidades, diario, paginacion, reportes
from core.contabilidad.diario import importe, referencia
from core.contabilidad.models import Asiento, Cuenta, LineaAsiento

VER = capacidades.funcion_de('diario_mayor').permisos['ver']
FECHA = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
TEXTOS = {
    'fecha': 'Escribe la fecha como AAAA-MM-DD.',
    'rango': 'La fecha final no puede ser anterior a la inicial.',
    'tipo': 'Tipo de asiento no reconocido.',
    'origen_tipo': 'El tipo de origen admite hasta 30 caracteres.',
    'id': 'Escribe un número entero.',
    'cuenta': 'La cuenta no existe o es de otra empresa.',
    'anio': 'Escribe un año entre 2000 y 2100.',
    'no_existe': 'El asiento no existe o es de otra empresa.',
}


# ---------------------------------------------------------------- forma del contrato

def _origen(asiento):
    if not asiento.origen_tipo:
        return None
    return {'tipo': asiento.origen_tipo, 'id': asiento.origen_id, 'evento': asiento.evento,
            'numero': asiento.origen_numero or None, 'fecha': asiento.origen_fecha.isoformat() if asiento.origen_fecha else None}


def _estado(asiento):
    if asiento.tipo == diario.REVERSO:
        return 'reverso'
    return 'reversado' if asiento.reversado_por_id is not None else 'vigente'


def _linea(linea):
    return {
        'orden': linea.orden,
        'cuenta': {'id': linea.cuenta_id, 'codigo': linea.cuenta.codigo, 'nombre': linea.cuenta.nombre},
        'concepto': linea.concepto, 'debe': importe(linea.debe), 'haber': importe(linea.haber),
        'tercero': {'tipo': linea.tercero_tipo, 'id': linea.tercero_id, 'identificacion': linea.tercero_identificacion,
                    'nombre': linea.tercero_nombre} if linea.tercero_tipo else None,
        'documento': {'tipo': linea.documento_tipo, 'id': linea.documento_id, 'numero': linea.documento_numero}
        if linea.documento_tipo else None,
    }


def dict_asiento(asiento, lineas):
    """El asiento con la forma del contrato. `lineas`: las suyas, ya ordenadas y con su cuenta."""
    return {
        'id': asiento.pk, 'numero': asiento.numero_completo, 'fecha': asiento.fecha.isoformat(), 'tipo': asiento.tipo,
        'concepto': asiento.concepto, 'motivo': asiento.motivo, 'origen': _origen(asiento), 'estado': _estado(asiento),
        'reversa_de': referencia(asiento.reversa_de) if asiento.reversa_de_id else None,
        'reversado_por': referencia(asiento.reversado_por) if asiento.reversado_por_id else None,
        'totales': {'debe': importe(asiento.total_debe), 'haber': importe(asiento.total_haber)},
        'lineas': [_linea(linea) for linea in lineas],
        'creado_por': asiento.creado_por_nombre, 'creado_en': asiento.creado_en.isoformat(), 'huella': asiento.huella,
    }


def _con_lineas(asientos):
    """Los asientos con sus líneas: una consulta para todas (con su cuenta), no una por asiento."""
    por_asiento = {asiento.pk: [] for asiento in asientos}
    for linea in (LineaAsiento.objects.filter(asiento_id__in=list(por_asiento)).select_related('cuenta')
                  .order_by('asiento_id', 'orden')):
        por_asiento[linea.asiento_id].append(linea)
    return [dict_asiento(asiento, por_asiento[asiento.pk]) for asiento in asientos]


def _asientos():
    return Asiento.objects.select_related('reversa_de', 'reversado_por')


# ---------------------------------------------------------------- filtros

def _fecha(consulta, campo, errores):
    """La fecha `AAAA-MM-DD` del campo (None si no viene); mal formada, su error en `errores`."""
    texto = (consulta.get(campo) or '').strip()
    if not texto:
        return None
    if FECHA.fullmatch(texto):
        try:
            valor = date.fromisoformat(texto)
        except ValueError:
            valor = None
        if valor is not None and diario.ANIO_MIN <= valor.year <= diario.ANIO_MAX:
            return valor
    errores.agregar(campo, TEXTOS['fecha'])
    return None


def _id(consulta, campo, errores):
    texto = (consulta.get(campo) or '').strip()
    if not texto:
        return None
    if texto.isascii() and texto.isdigit() and len(texto) <= 18:
        return int(texto)
    errores.agregar(campo, TEXTOS['id'])
    return None


def _filtros(consulta):
    """`(desde, hasta, consulta de asientos, pagina, por_pagina)` o el 400 con todos los errores de campo."""
    errores = api.Errores()
    hoy = timezone.localdate()
    desde, hasta = _fecha(consulta, 'desde', errores), _fecha(consulta, 'hasta', errores)
    desde = desde or hoy.replace(day=1)
    hasta = hasta or hoy.replace(day=calendar.monthrange(hoy.year, hoy.month)[1])
    if 'desde' not in errores and 'hasta' not in errores and hasta < desde:
        errores.agregar('hasta', TEXTOS['rango'])
    asientos = _asientos().filter(fecha__gte=desde, fecha__lte=hasta)
    tipo = (consulta.get('tipo') or '').strip()
    if tipo:
        if tipo not in diario.TIPOS:
            errores.agregar('tipo', TEXTOS['tipo'])
        asientos = asientos.filter(tipo=tipo)
    origen_tipo = (consulta.get('origen_tipo') or '').strip()
    if origen_tipo:
        if len(origen_tipo) > 30:
            errores.agregar('origen_tipo', TEXTOS['origen_tipo'])
        asientos = asientos.filter(origen_tipo=origen_tipo)
    origen_id = _id(consulta, 'origen_id', errores)
    if origen_id is not None:
        asientos = asientos.filter(origen_id=origen_id)
    cuenta_id = _id(consulta, 'cuenta', errores)
    if cuenta_id is not None:
        if not Cuenta.objects.filter(pk=cuenta_id).exists():
            errores.agregar('cuenta', TEXTOS['cuenta'])
        asientos = asientos.filter(Exists(LineaAsiento.objects.filter(asiento_id=OuterRef('pk'), cuenta_id=cuenta_id)))
    pagina, por_pagina = paginacion.pedida(consulta, errores)
    errores.comprobar()
    return desde, hasta, asientos, pagina, por_pagina


# ---------------------------------------------------------------- vistas

class DiarioApi(api.ApiContable):
    permisos = {'GET': VER}

    def get(self, request):
        desde, hasta, asientos, pagina, por_pagina = _filtros(request.GET)
        totales = asientos.order_by().aggregate(debe=Sum('total_debe'), haber=Sum('total_haber'), asientos=Count('id'))
        pagina_de_asientos = list(asientos.order_by('fecha', 'anio', 'numero')[paginacion.tramo(pagina, por_pagina)])
        provisional, causas, causas_detalle = reportes.provisionalidad('diario', desde, hasta)
        return JsonResponse({
            'desde': desde.isoformat(), 'hasta': hasta.isoformat(), 'asientos': _con_lineas(pagina_de_asientos),
            'totales': {'debe': importe(totales['debe'] or 0), 'haber': importe(totales['haber'] or 0),
                        'asientos': totales['asientos']},
            'provisional': provisional, 'causas': causas, 'causas_detalle': causas_detalle,
            'paginacion': paginacion.datos(pagina, por_pagina, totales['asientos']),
        })


class AsientoApi(api.ApiContable):
    permisos = {'GET': VER}

    def get(self, request, pk):
        asiento = _asientos().filter(pk=pk).first()
        if asiento is None:
            raise api.ErrorApi('no_existe', TEXTOS['no_existe'], 404)
        return JsonResponse({'asiento': _con_lineas([asiento])[0]})


class IntegridadApi(api.ApiContable):
    permisos = {'GET': VER}

    def get(self, request):
        texto = (request.GET.get('anio') or '').strip()
        anio = timezone.localdate().year
        if texto:
            anio = int(texto) if texto.isascii() and texto.isdigit() and len(texto) == 4 else 0
            if not diario.ANIO_MIN <= anio <= diario.ANIO_MAX:
                raise api.ErrorApi('validacion', errores={'anio': [TEXTOS['anio']]})
        return JsonResponse(diario.verificar(anio))
