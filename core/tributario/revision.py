"""Revisión del mes (entrega C): lo que conviene mirar antes de declarar, con su causa y el enlace a cada registro.

No es un cierre contable ni certifica nada, y no bloquea ninguna operación. Cada observación dice POR QUÉ aparece. Las que
dependen de un criterio tributario se presentan como «revisar», nunca como incumplimiento: una compra sin retención puede no
requerirla, y un salto de numeración puede deberse a comprobantes de otro sistema o a un cambio de numeración (no prueba una
omisión). Categorías:
- comprobantes emitidos en producción que el SRI devolvió, no autorizó o siguen en proceso o sin enviar;
- datos del ATS incompletos en compras y proveedores (compras.faltantes, Provider.faltantes_ats);
- respaldos pendientes (consulta mensual de core/adjuntos: pagos sin comprobante ni nota, recibos por completar, respaldos de
  cobro por revisar o rechazados);
- saltos de numeración por punto y tipo de comprobante (producción);
- cuentas por cobrar y por pagar vencidas a la fecha de corte (fin del mes, o hoy si el mes no ha terminado);
- compras sin comprobante de retención, solo si la empresa está marcada como agente de retención.
"""
from collections import OrderedDict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from core.tributario import libros as lb

CATEGORIAS = OrderedDict([
    ('devueltos', 'Comprobantes devueltos o sin autorizar'),
    ('datos_ats', 'Datos del ATS incompletos'),
    ('respaldos', 'Respaldos pendientes'),
    ('numeracion', 'Numeración'),
    ('vencidas', 'Cuentas vencidas'),
    ('retenciones', 'Compras sin retención'),
])
NIVELES = {'revisar': 'Revisar', 'informativo': 'Informativo'}
NO_AUTORIZADOS = {
    'returned': 'El SRI devolvió el comprobante: todavía no es válido. Corrígelo y vuelve a enviarlo, o elimínalo si no corresponde.',
    'not_authorized': 'El SRI no lo autorizó: no tiene validez tributaria. Revisa el motivo en «Errores de comprobantes».',
    'in_process': 'Quedó en proceso en el SRI: consulta su estado antes de declarar.',
    'without_authorizing': 'Está guardado pero no se envió al SRI.',
    'sequential_registered_error': 'El SRI indicó que el secuencial ya estaba registrado: revisa la numeración de ese punto.',
}
TIPOS_EMITIDOS = {'01': 'Factura', '04': 'Nota de crédito', '03': 'Liquidación de compra', '05': 'Nota de débito',
                  '06': 'Guía de remisión', '07': 'Comprobante de retención'}
LISTAS = {'01': '/pos/sale/admin/', '04': '/pos/credit/note/admin/', '03': '/comprobantes/liquidaciones/',
          '05': '/comprobantes/notas-debito/', '06': '/comprobantes/guias/', '07': '/comprobantes/retenciones/'}


def _obs(categoria, codigo, titulo, causa, nivel='revisar', documento=None, fecha='', importe=None):
    return {'categoria': categoria, 'categoria_nombre': CATEGORIAS[categoria], 'codigo': codigo, 'nivel': nivel,
            'nivel_nombre': NIVELES[nivel], 'titulo': titulo, 'causa': causa, 'documento': documento,
            'fecha': fecha.isoformat() if hasattr(fecha, 'isoformat') else (fecha or ''),
            'importe': f'{Decimal(str(importe)):.2f}' if importe is not None else ''}


def _doc(tipo, id_, numero, url):
    return {'tipo': tipo, 'id': id_, 'numero': numero, 'url': url}


def _emitidos():
    """[(código del tipo, consulta)] de los comprobantes que emite la empresa."""
    from core.comprobantes.models import GuiaRemision, LiquidacionCompra, NotaDebito, Retencion
    from core.pos.models import CreditNote, Sale
    return [('01', Sale.objects.filter(receipt__voucher_type='01')), ('04', CreditNote.objects.all()),
            ('03', LiquidacionCompra.objects.all()), ('05', NotaDebito.objects.all()), ('06', GuiaRemision.objects.all()),
            ('07', Retencion.objects.all())]


def devueltos(inicio):
    resultado = []
    mes = lb._en_mes(inicio, 'emission_date', 'date_joined')
    for tipo, consulta in _emitidos():
        for doc in consulta.filter(mes, environment_type=lb.PRODUCCION, status__in=list(NO_AUTORIZADOS)).order_by('date_joined', 'id'):
            resultado.append(_obs('devueltos', doc.status, f'{TIPOS_EMITIDOS[tipo]} {doc.voucher_number_full}: {doc.get_status_display()}',
                                  NO_AUTORIZADOS[doc.status], documento=_doc(tipo, doc.pk, doc.voucher_number_full, LISTAS[tipo]),
                                  fecha=doc.emission_date or doc.date_joined))
    return resultado


def datos_ats(inicio):
    from core.pos.models import Purchase
    resultado, proveedores = [], {}
    for compra in (Purchase.objects.select_related('provider').filter(lb._en_mes(inicio, 'date_joined'))
                   .order_by('date_joined', 'id')):
        faltan = compra.faltantes()
        if faltan:
            resultado.append(_obs('datos_ats', 'compra_incompleta', f'Compra {compra.numero_comprobante} de {compra.provider.name}',
                                  'Faltan para el ATS: ' + '; '.join(texto for _, texto in faltan) + '.',
                                  documento=_doc('compra', compra.pk, compra.numero_comprobante, f'/pos/purchase/complete/{compra.pk}/'),
                                  fecha=compra.fecha_emision or compra.date_joined, importe=compra.total))
        proveedores.setdefault(compra.provider_id, compra.provider)
    for proveedor in proveedores.values():
        faltan = proveedor.faltantes_ats()
        if faltan:
            resultado.append(_obs('datos_ats', 'proveedor_incompleto', f'Proveedor {proveedor.name} ({proveedor.ruc})',
                                  'Faltan para el ATS: ' + '; '.join(texto for _, texto in faltan) + '.',
                                  documento=_doc('proveedor', proveedor.pk, proveedor.ruc, f'/pos/provider/update/{proveedor.pk}/')))
    return resultado


def respaldos(inicio, request=None):
    from core.adjuntos import servicios as adjuntos
    resumen = adjuntos.resumen_mes(inicio, request)
    resultado = []
    for fila in resumen['faltantes']:
        url = fila['url_cobros'] or f'/adjuntos/?mes={inicio:%Y-%m}'
        resultado.append(_obs('respaldos', 'sin_respaldo', f'{fila["titulo"]}',
                              f'Pagado por {fila["medio"].lower()} y sin comprobante ni nota de respaldo.',
                              documento=_doc(fila['tipo'], fila['id'], fila['numero'], url), fecha=fila['fecha'], importe=fila['importe'] or None))
    for fila in resumen['filas']:
        for respaldo in fila['adjuntos']:
            revision = respaldo.get('revision')
            if revision and revision['id'] == 'rechazado':
                resultado.append(_obs('respaldos', 'respaldo_rechazado', f'Respaldo rechazado de {fila["titulo"]}',
                                      'El respaldo del cobro se marcó como rechazado' + (f': {revision["motivo"]}' if revision['motivo'] else '')
                                      + '. Revisa el cobro: el rechazo no cambia el saldo.',
                                      documento=_doc(fila['tipo'], fila['id'], fila['numero'], fila['url_cobros']), fecha=fila['fecha']))
            elif revision and revision['id'] == 'pendiente':
                resultado.append(_obs('respaldos', 'respaldo_por_revisar', f'Respaldo por revisar de {fila["titulo"]}',
                                      'El respaldo del cobro todavía no se revisa.', nivel='informativo',
                                      documento=_doc(fila['tipo'], fila['id'], fila['numero'], fila['url_cobros']), fecha=fila['fecha']))
    for fila in resumen['capturas']:
        resultado.append(_obs('respaldos', 'recibo_por_completar', f'Recibo {fila["numero"]} por completar',
                              'Se guardó un recibo o una nota que todavía no se registró como gasto o compra: no cuenta en los libros.',
                              documento=_doc('captura', fila['id'], fila['numero'], fila['url_captura']), fecha=fila['fecha']))
    return resultado


def _numeros(consulta, mes):
    for doc in consulta.filter(mes, environment_type=lb.PRODUCCION).select_related('receipt').only(
            'voucher_number', 'receipt__establishment_code', 'receipt__issuing_point_code', 'receipt__voucher_type'):
        try:
            yield doc.receipt.establishment_code, doc.receipt.issuing_point_code, int(doc.voucher_number)
        except (TypeError, ValueError):
            continue


def numeracion(inicio):
    """Saltos entre los secuenciales usados en el mes, por tipo y punto (producción). Un salto no prueba una omisión."""
    resultado = []
    mes = lb._en_mes(inicio, 'emission_date', 'date_joined')
    for tipo, consulta in _emitidos():
        por_punto = {}
        for estab, punto, numero in _numeros(consulta, mes):
            por_punto.setdefault((estab, punto), set()).add(numero)
        for (estab, punto), numeros in sorted(por_punto.items()):
            ordenados = sorted(numeros)
            for anterior, siguiente in zip(ordenados, ordenados[1:]):
                if siguiente - anterior > 1:
                    desde, hasta = anterior + 1, siguiente - 1
                    rango = f'{desde:09d}' if desde == hasta else f'{desde:09d} a {hasta:09d}'
                    resultado.append(_obs(
                        'numeracion', 'salto', f'{TIPOS_EMITIDOS[tipo]} {estab}-{punto}: no aparecen los secuenciales {rango}',
                        'Entre los comprobantes del mes faltan esos números. Puede deberse a comprobantes emitidos en otro sistema, '
                        'eliminados antes de enviarse o a un cambio de numeración. Un salto no prueba una omisión: confírmalo.',
                        documento=_doc(tipo, None, f'{estab}-{punto}', LISTAS[tipo])))
    return resultado


def corte_de(inicio):
    """Fecha de corte de las cuentas vencidas: fin del mes, o hoy si el mes no ha terminado."""
    return min(timezone.localdate(), lb.siguiente_mes(inicio) - timedelta(days=1))


def vencidas(inicio):
    from core.pos.models import CtasCollect, DebtsPay
    corte = corte_de(inicio)
    resultado = []
    for cuenta in CtasCollect.objects.select_related('sale__client__user').filter(end_date__lt=corte, saldo__gt=0).order_by('end_date', 'id'):
        saldo = cuenta.saldo_actual()
        if saldo <= 0:
            continue
        resultado.append(_obs('vencidas', 'cxc_vencida', f'Cuenta por cobrar de {cuenta.sale.voucher_number_full} ({cuenta.sale.client.user.names})',
                              f'Venció el {cuenta.end_date:%d/%m/%Y} y al {corte:%d/%m/%Y} conserva saldo.', nivel='informativo',
                              documento=_doc('cxc', cuenta.pk, cuenta.sale.voucher_number_full, '/pos/ctas/collect/'),
                              fecha=cuenta.end_date, importe=saldo))
    for deuda in DebtsPay.objects.select_related('purchase__provider').filter(end_date__lt=corte, saldo__gt=0).order_by('end_date', 'id'):
        resultado.append(_obs('vencidas', 'cxp_vencida', f'Cuenta por pagar de {deuda.purchase.numero_comprobante} ({deuda.purchase.provider.name})',
                              f'Venció el {deuda.end_date:%d/%m/%Y} y al {corte:%d/%m/%Y} conserva saldo.', nivel='informativo',
                              documento=_doc('cxp', deuda.pk, deuda.purchase.numero_comprobante, '/pos/debts/pay/'),
                              fecha=deuda.end_date, importe=deuda.saldo))
    return resultado


def retenciones(inicio, company):
    """Facturas y liquidaciones de compra del mes sin comprobante de retención autorizado, si la empresa es agente de
    retención. Revisión posible: puede no corresponder (proveedor o compra no sujetos, montos, exenciones)."""
    from core.pos.models import Purchase
    if getattr(company, 'retention_agent', 'NO') != 'SI':
        return []
    resultado = []
    compras = (Purchase.objects.select_related('provider').filter(lb._en_mes(inicio, 'date_joined'),
                                                                     tipo_comprobante__in=('01', '03'))
               .exclude(retenciones__in=_retenciones_validas()).order_by('fecha_emision', 'date_joined', 'id').distinct())
    for compra in compras:
        resultado.append(_obs('retenciones', 'compra_sin_retencion', f'Compra {compra.numero_comprobante} de {compra.provider.name}',
                              'No hay un comprobante de retención autorizado para esta compra. Si la operación está sujeta a retención, '
                              'revisa por qué no se emitió; puede no corresponder (proveedor o compra no sujetos, exenciones o montos). '
                              'No es un incumplimiento automático: confírmalo con tu contador.',
                              documento=_doc('compra', compra.pk, compra.numero_comprobante, f'/pos/purchase/complete/{compra.pk}/'),
                              fecha=compra.fecha_emision or compra.date_joined, importe=compra.total))
    return resultado


def _retenciones_validas():
    from core.comprobantes.models import Retencion
    return Retencion.objects.filter(environment_type=lb.PRODUCCION, status__in=lb.AUTORIZADOS, anulado_sri_fecha__isnull=True)


def revisar(inicio, company, request=None):
    """Observaciones del mes por categoría y su resumen. Lee solo la empresa activa (gestor por empresa y RLS)."""
    observaciones = (devueltos(inicio) + datos_ats(inicio) + respaldos(inicio, request) + numeracion(inicio) + vencidas(inicio)
                     + retenciones(inicio, company))
    por_categoria = OrderedDict((c, {'nombre': n, 'revisar': 0, 'informativo': 0}) for c, n in CATEGORIAS.items())
    for o in observaciones:
        por_categoria[o['categoria']][o['nivel']] += 1
    return {'mes': f'{inicio:%Y-%m}', 'corte': corte_de(inicio).isoformat(), 'observaciones': observaciones,
            'por_categoria': por_categoria, 'pendientes': sum(1 for o in observaciones if o['nivel'] == 'revisar'),
            'informativas': sum(1 for o in observaciones if o['nivel'] == 'informativo'),
            'agente_retencion': getattr(company, 'retention_agent', 'NO') == 'SI'}
