"""Consultas de comprobantes por fecha de emisión, ambiente y estado (Etapa 2, O2; las reutilizará la Etapa 4).

- «Declarables»: producción, autorizados (en la factura también 'canceled': autorizada y cubierta por notas de crédito),
  sin la marca «Anulado en el SRI», por fecha efectiva de emisión.
- Fecha efectiva = emission_date, o la de autorización, o la de registro: las ventas autorizadas antes de la emisión en
  dos fases (pos 0012) no tienen emission_date. origen_fecha() informa de dónde salió (dato incompleto explícito); la
  orden completar_fecha_emision la completa desde el XML, con ensayo y decisión.
- «Todos» reproduce exactamente el comportamiento anterior (ningún filtro, por fecha de registro).
"""
from django.db.models import Case, DateField, F, Q, Subquery, When
from django.db.models.functions import Coalesce, TruncDate

from core.pos.choices import ESTADOS_DECLARABLES_VENTA

AUTORIZADOS = ('authorized', 'authorized_and_sent_by_email')
PRODUCCION, PRUEBAS = 2, 1
ALCANCES = (('declarables', 'Autorizados en producción (para declarar)'), ('anulados_sri', 'Anulados en el SRI'),
            ('no_autorizados', 'Sin autorizar, en proceso o rechazados'), ('pruebas', 'Ambiente de pruebas'),
            ('todos', 'Todos los registros (como antes, por fecha de registro)'))
MENSAJE_ALCANCE = 'Elige qué comprobantes mostrar.'


def _validar(alcance):
    if alcance not in dict(ALCANCES):
        raise ValueError(MENSAJE_ALCANCE)


def _autorizacion_como_fecha(Modelo, prefijo=''):
    campo = Modelo._meta.get_field('authorization_date')
    nombre = f'{prefijo}authorization_date'
    return F(nombre) if campo.get_internal_type() == 'DateField' else TruncDate(nombre)


def fecha_efectiva(Modelo, prefijo=''):
    """Coalesce(emission_date, autorización como fecha, date_joined). `prefijo` para recorrer una relación ('sale__')."""
    return Coalesce(f'{prefijo}emission_date', _autorizacion_como_fecha(Modelo, prefijo), f'{prefijo}date_joined',
                    output_field=DateField())


def origen_fecha(obj):
    if getattr(obj, 'emission_date', None):
        return 'sri'
    if getattr(obj, 'authorization_date', None):
        return 'autorizacion'
    return 'registro'


def _por_fecha(queryset, Modelo, desde, hasta):
    queryset = queryset.annotate(fecha_efectiva=fecha_efectiva(Modelo))
    if desde and hasta:
        queryset = queryset.filter(fecha_efectiva__range=[desde, hasta])
    return queryset.order_by('fecha_efectiva', 'id')


def ventas(alcance, desde=None, hasta=None):
    from core.pos.models import Sale
    _validar(alcance)
    if alcance == 'todos':
        queryset = Sale.objects.filter()
        if desde and hasta:
            queryset = queryset.filter(date_joined__range=[desde, hasta])
        return queryset
    filtros = {
        'declarables': Q(environment_type=PRODUCCION, receipt__voucher_type='01', status__in=ESTADOS_DECLARABLES_VENTA,
                         anulado_sri_fecha__isnull=True),
        'anulados_sri': Q(environment_type=PRODUCCION, anulado_sri_fecha__isnull=False),
        'no_autorizados': Q(environment_type=PRODUCCION, receipt__voucher_type='01') & ~Q(status__in=ESTADOS_DECLARABLES_VENTA),
        'pruebas': Q(environment_type=PRUEBAS),
    }
    return _por_fecha(Sale.objects.filter(filtros[alcance]), Sale, desde, hasta)


def notas_credito(alcance, desde=None, hasta=None):
    from core.pos.models import CreditNote
    _validar(alcance)
    if alcance == 'todos':
        queryset = CreditNote.objects.filter()
        if desde and hasta:
            queryset = queryset.filter(date_joined__range=[desde, hasta])
        return queryset
    filtros = {
        'declarables': Q(environment_type=PRODUCCION, status__in=AUTORIZADOS, anulado_sri_fecha__isnull=True),
        'anulados_sri': Q(environment_type=PRODUCCION, anulado_sri_fecha__isnull=False),
        'no_autorizados': Q(environment_type=PRODUCCION) & ~Q(status__in=AUTORIZADOS),
        'pruebas': Q(environment_type=PRUEBAS),
    }
    return _por_fecha(CreditNote.objects.filter(filtros[alcance]), CreditNote, desde, hasta)


def cuentas_por_cobrar(alcance, desde=None, hasta=None):
    """CxC con el criterio de su documento: la factura o, en una CxC de nota de débito, esa nota (por su fecha)."""
    from django.db.models import OuterRef
    from core.comprobantes.models import NotaDebito
    from core.pos import cxc
    from core.pos.models import Sale
    _validar(alcance)
    if alcance == 'todos':
        return cxc.listado(desde, hasta)
    nota = NotaDebito.all_companies.filter(cuenta_por_cobrar=OuterRef('pk'))
    queryset = cxc.listado().annotate(
        nd_ambiente=Subquery(nota.values('environment_type')[:1]), nd_estado=Subquery(nota.values('status')[:1]),
        nd_anulado=Subquery(nota.values('anulado_sri_fecha')[:1]),
        nd_fecha=Subquery(nota.annotate(f=fecha_efectiva(NotaDebito)).values('f')[:1]))
    queryset = queryset.annotate(fecha_efectiva=Case(When(nd_id__isnull=True, then=fecha_efectiva(Sale, 'sale__')),
                                                     default=F('nd_fecha'), output_field=DateField()))
    factura, de_nota = Q(nd_id__isnull=True), Q(nd_id__isnull=False)
    filtros = {
        'declarables': (factura & Q(sale__environment_type=PRODUCCION, sale__receipt__voucher_type='01',
                                    sale__status__in=ESTADOS_DECLARABLES_VENTA, sale__anulado_sri_fecha__isnull=True))
                       | (de_nota & Q(nd_ambiente=PRODUCCION, nd_estado__in=AUTORIZADOS, nd_anulado__isnull=True)),
        'anulados_sri': (factura & Q(sale__environment_type=PRODUCCION, sale__anulado_sri_fecha__isnull=False))
                        | (de_nota & Q(nd_ambiente=PRODUCCION, nd_anulado__isnull=False)),
        'no_autorizados': (factura & Q(sale__environment_type=PRODUCCION, sale__receipt__voucher_type='01')
                           & ~Q(sale__status__in=ESTADOS_DECLARABLES_VENTA))
                          | (de_nota & Q(nd_ambiente=PRODUCCION) & ~Q(nd_estado__in=AUTORIZADOS)),
        'pruebas': (factura & Q(sale__environment_type=PRUEBAS)) | (de_nota & Q(nd_ambiente=PRUEBAS)),
    }
    queryset = queryset.filter(filtros[alcance])
    if desde and hasta:
        queryset = queryset.filter(fecha_efectiva__range=[desde, hasta])
    return queryset.order_by('fecha_efectiva', 'id')


def declarables(Modelo, desde, hasta):
    """Comprobantes de producción autorizados (+'canceled' en la factura), sin anular, por fecha efectiva."""
    from core.pos.models import Sale
    filtro = Q(environment_type=PRODUCCION, anulado_sri_fecha__isnull=True)
    if Modelo is Sale:
        filtro &= Q(receipt__voucher_type='01', status__in=ESTADOS_DECLARABLES_VENTA)
    else:
        filtro &= Q(status__in=AUTORIZADOS)
    return _por_fecha(Modelo.objects.filter(filtro), Modelo, desde, hasta)


def anulados_sri(desde, hasta):
    """Comprobantes de producción marcados «Anulado en el SRI» con fecha de anulación en el rango, de los seis tipos.

    Se filtra por la fecha de anulación (la sección de anulados del ATS la confirmará la Etapa 4)."""
    from core.comprobantes.models import GuiaRemision, LiquidacionCompra, NotaDebito, Retencion
    from core.pos.models import CreditNote, Sale
    filas = []
    for Modelo in (Sale, CreditNote, Retencion, LiquidacionCompra, NotaDebito, GuiaRemision):
        queryset = (Modelo.objects.select_related('receipt')
                    .filter(environment_type=PRODUCCION, anulado_sri_fecha__range=[desde, hasta])
                    .annotate(fecha_efectiva=fecha_efectiva(Modelo)).order_by('anulado_sri_fecha', 'id'))
        for doc in queryset:
            filas.append({'modelo': doc._meta.model_name, 'id': doc.pk, 'cod_doc': doc.receipt.voucher_type,
                          'numero': doc.voucher_number_full, 'autorizacion': doc.access_code or '',
                          'fecha_emision': doc.fecha_efectiva, 'fecha_anulacion': doc.anulado_sri_fecha})
    return sorted(filas, key=lambda f: (f['fecha_anulacion'], f['cod_doc'], f['numero']))
