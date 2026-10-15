"""Guía de remisión (06) que ampara el traslado de lo vendido en una factura: reglas en el servidor.

- Solo sobre facturas autorizadas, del mismo ambiente y a un destinatario identificado (no consumidor final).
- Transportista identificado (RUC y cédula validados; pasaporte o identificación del exterior de 3 a 20 caracteres),
  placa y fechas de inicio y fin del transporte (el fin no antes del inicio).
- Las líneas son las de la factura: se puede trasladar todo o una parte. Entre todas las guías vigentes de la factura
  no se traslada más de lo vendido (entregas parciales en varias guías).
- La guía no tiene importes; cada guía cuenta 1 del cupo.
"""
import re
from decimal import Decimal, InvalidOperation

from django.db.models import Sum
from django.utils import timezone

from core.comprobantes.models import GuiaDetalle, GuiaRemision
from core.login.identificacion import cedula_valida, ruc_valido

TIPO_GUIA = '06'
NO_CUENTAN = ('returned', 'not_authorized', 'sequential_registered_error')
AUTORIZADOS = ('authorized', 'authorized_and_sent_by_email')


class ErrorGuia(Exception):
    """Mensaje para el usuario."""


def validar_factura(venta, company):
    from core.pos.choices import VOUCHER_TYPE
    from core.pos.notas_credito import es_consumidor_final
    if venta.receipt.voucher_type != VOUCHER_TYPE[0][0]:
        raise ErrorGuia('Las guías de remisión se emiten sobre facturas.')
    if venta.status not in AUTORIZADOS:
        raise ErrorGuia('La factura debe estar autorizada por el SRI para emitir su guía de remisión.')
    if es_consumidor_final(venta.client):
        raise ErrorGuia('La guía de remisión necesita un destinatario identificado: la factura es a consumidor final.')
    if venta.environment_type != company.environment_type:
        raise ErrorGuia(f'La factura es del ambiente {venta.get_environment_type_display()} y la empresa emite '
                        f'en {company.get_environment_type_display()}.')


def trasladado_por_detalle(venta):
    filas = (GuiaDetalle.objects.filter(sale_detail__sale=venta).exclude(guia__status__in=NO_CUENTAN)
             .values('sale_detail_id').annotate(cantidad=Sum('cantidad')))
    return {f['sale_detail_id']: f['cantidad'] or Decimal('0') for f in filas}


def lineas_de_factura(venta):
    """Líneas de la factura con lo vendido, lo ya trasladado en guías vigentes y lo pendiente."""
    trasladado = trasladado_por_detalle(venta)
    lineas = []
    for d in venta.saledetail_set.select_related('product').order_by('pk'):
        vendido = Decimal(d.cant)
        enviado = trasladado.get(d.pk, Decimal('0'))
        lineas.append({'detalle': d.pk, 'codigo': (d.product.code or '')[:25], 'descripcion': d.product.name[:300], 'vendido': vendido,
                       'trasladado': enviado, 'pendiente': max(vendido - enviado, Decimal('0'))})
    return lineas


def _transportista(tipo, numero):
    numero = re.sub(r'\s', '', numero or '')
    if tipo == '04' and not ruc_valido(numero):
        raise ErrorGuia('El RUC del transportista no es válido.')
    if tipo == '05' and not cedula_valida(numero):
        raise ErrorGuia('La cédula del transportista no es válida.')
    if tipo in ('06', '08') and not 3 <= len(numero) <= 20:
        raise ErrorGuia('La identificación del transportista debe tener entre 3 y 20 caracteres.')
    if tipo not in ('04', '05', '06', '08'):
        raise ErrorGuia('Elige el tipo de identificación del transportista.')
    return numero


def _texto(valor, largo=300):
    return ' '.join((valor or '').split())[:largo]


def calcular(venta, datos, cantidades):
    """Valida sin guardar. cantidades: {id de detalle de la factura: cantidad a trasladar}. Devuelve (documento, [línea])."""
    cliente = venta.client
    doc = {
        'transportista_tipo_identificacion': datos.get('transportista_tipo_identificacion') or '',
        'transportista_razon_social': _texto(datos.get('transportista_razon_social')),
        'placa': re.sub(r'\s', '', (datos.get('placa') or '').upper())[:20],
        'fecha_inicio': datos.get('fecha_inicio'), 'fecha_fin': datos.get('fecha_fin'),
        'dir_partida': _texto(datos.get('dir_partida')), 'direccion': _texto(datos.get('direccion') or cliente.address),
        'motivo': _texto(datos.get('motivo')) or 'Venta', 'ruta': _texto(datos.get('ruta')),
        'cod_estab_destino': (datos.get('cod_estab_destino') or '').strip(), 'doc_aduanero': _texto(datos.get('doc_aduanero'), 20),
    }
    doc['transportista_identificacion'] = _transportista(doc['transportista_tipo_identificacion'], datos.get('transportista_identificacion'))
    if not doc['transportista_razon_social']:
        raise ErrorGuia('Escribe el nombre o la razón social del transportista.')
    if not re.fullmatch(r'[A-Z0-9-]{3,20}', doc['placa']):
        raise ErrorGuia('Escribe la placa del vehículo (letras, números y guion; sin espacios).')
    if not doc['fecha_inicio'] or not doc['fecha_fin']:
        raise ErrorGuia('Indica las fechas de inicio y fin del transporte.')
    if doc['fecha_fin'] < doc['fecha_inicio']:
        raise ErrorGuia('La fecha de fin del transporte no puede ser anterior a la de inicio.')
    if not doc['dir_partida']:
        raise ErrorGuia('Escribe la dirección de partida.')
    if not doc['direccion']:
        raise ErrorGuia('Escribe la dirección de destino.')
    if doc['cod_estab_destino'] and not re.fullmatch(r'\d{3}', doc['cod_estab_destino']):
        raise ErrorGuia('El establecimiento de destino tiene 3 dígitos (por ejemplo, 001).')
    lineas = []
    for linea in lineas_de_factura(venta):
        valor = cantidades.get(linea['detalle'])
        if valor in (None, ''):
            continue
        try:
            cantidad = Decimal(str(valor))
        except InvalidOperation:
            raise ErrorGuia(f'La cantidad de «{linea["descripcion"]}» no es un número.')
        if cantidad < 0:
            raise ErrorGuia(f'La cantidad de «{linea["descripcion"]}» no puede ser negativa.')
        if cantidad == 0:
            continue
        if cantidad > linea['pendiente']:
            raise ErrorGuia(f'De «{linea["descripcion"]}» solo quedan {linea["pendiente"].normalize():f} por trasladar '
                            f'(vendido {linea["vendido"].normalize():f}, ya en guías {linea["trasladado"].normalize():f}).')
        lineas.append({**linea, 'cantidad': cantidad})
    if not lineas:
        raise ErrorGuia('Indica qué se traslada: al menos una línea con cantidad mayor que cero.')
    return doc, lineas


def crear(company, usuario, venta, datos, cantidades):
    """Guía guardada (aún sin firmar). Llamar dentro de una transacción; la vista firma después."""
    from core.configuracion.servicios import receipt_para_emitir
    from core.pos.models import Sale
    venta = Sale.objects.select_for_update().select_related('client__user', 'receipt').get(pk=venta.pk)   # una guía a la vez
    validar_factura(venta, company)
    doc, lineas = calcular(venta, datos, cantidades)
    cliente = venta.client
    receipt = receipt_para_emitir(company, TIPO_GUIA, electronica=True)
    numero = receipt.reservar_numero()
    correo = (cliente.user.email or '').strip()
    guia = GuiaRemision(
        company=company, receipt=receipt, voucher_number=numero,
        voucher_number_full=f'{receipt.establishment_code}-{receipt.issuing_point_code}-{numero}',
        employee=usuario, environment_type=company.environment_type, date_joined=timezone.localdate(), sale=venta,
        identificacion=cliente.dni.strip(), razon_social=_texto(cliente.user.names), correo=correo if '@' in correo else '',
        enviar_correo=cliente.send_email_invoice, cod_doc_sustento=venta.receipt.voucher_type,
        num_doc_sustento=venta.voucher_number_full, aut_doc_sustento=venta.access_code or '',
        fecha_doc_sustento=venta.emission_date or venta.date_joined, **doc)
    guia.save()
    for linea in lineas:
        GuiaDetalle.objects.create(guia=guia, sale_detail_id=linea['detalle'], codigo=linea['codigo'], descripcion=linea['descripcion'],
                                   cantidad=linea['cantidad'])
    return guia
