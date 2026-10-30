"""Documentos que admiten comprobantes de pago: modelo, módulo del que heredan permisos y regla de plan, y descripción.

El permiso de ver un adjunto es el de ver su documento; subir exige `add_adjunto` del rol o un permiso de escritura del
documento; quitar exige `delete_adjunto` o el de eliminar el documento (reparto en core/tenancy/roles.py).
"""
from dataclasses import dataclass
from decimal import Decimal

from core.pos.models import Expenses, PaymentsCtaCollect, PaymentsDebtsPay, Purchase, Sale


@dataclass(frozen=True)
class Documento:
    tipo: str
    modelo: type
    modulo: str          # URL del módulo: permisos del rol y regla de plan (RUTAS_DE_PAGO)
    ver: str
    escribir: tuple
    borrar: tuple
    nombre: str
    carpeta: str         # carpeta dentro del ZIP del mes


DOCUMENTOS = {d.tipo: d for d in (
    Documento('venta', Sale, '/pos/sale/admin/', 'view_sale', ('add_sale',), ('delete_sale',), 'Factura emitida', 'facturas-emitidas'),
    Documento('compra', Purchase, '/pos/purchase/', 'view_purchase', ('add_purchase', 'change_purchase'), ('delete_purchase',),
              'Compra', 'compras'),
    Documento('gasto', Expenses, '/pos/expenses/', 'view_expenses', ('add_expenses', 'change_expenses'), ('delete_expenses',),
              'Gasto', 'gastos'),
    Documento('cobro', PaymentsCtaCollect, '/pos/ctas/collect/', 'view_ctas_collect', ('add_ctas_collect',), ('delete_ctas_collect',),
              'Cobro de cuenta por cobrar', 'cobros'),
    Documento('pago', PaymentsDebtsPay, '/pos/debts/pay/', 'view_debts_pay', ('add_debts_pay',), ('delete_debts_pay',),
              'Pago de cuenta por pagar', 'pagos'),
)}
SIN_COMPROBANTE_ESPERADO = ('', 'efectivo', '01')   # medios que no dejan comprobante bancario


def obtener(tipo, documento_id):
    """Documento de la empresa activa (gestor acotado + RLS) o None."""
    doc = DOCUMENTOS[tipo]
    consulta = doc.modelo.objects
    if tipo == 'venta':
        consulta = consulta.select_related('client__user')
    elif tipo == 'compra':
        consulta = consulta.select_related('provider')
    elif tipo == 'gasto':
        consulta = consulta.select_related('type_expense')
    elif tipo == 'cobro':
        consulta = consulta.select_related('ctas_collect__sale__client__user')
    elif tipo == 'pago':
        consulta = consulta.select_related('debts_pay__purchase__provider')
    return consulta.filter(pk=documento_id).first()


def _decimal(valor):
    return Decimal(valor) if valor is not None else None


def describir(tipo, obj):
    """Datos comunes del documento para las pantallas y el índice del ZIP (texto de terceros: escapar al dibujar)."""
    if tipo == 'venta':
        numero = obj.voucher_number_full
        datos = dict(numero=numero, tercero=obj.client.user.names, identificacion=obj.client.dni, fecha=obj.date_joined,
                     importe=_decimal(obj.total), medio_id=obj.payment_method, medio=obj.get_payment_method_display(),
                     contado=obj.payment_type == 'efectivo', titulo=f'Factura {numero}')
    elif tipo == 'compra':
        numero = obj.numero_comprobante
        datos = dict(numero=numero, tercero=obj.provider.name, identificacion=obj.provider.ruc, fecha=obj.fecha_emision or obj.date_joined,
                     importe=_decimal(obj.total if obj.total is not None else obj.subtotal), medio_id=obj.forma_pago,
                     medio=obj.get_forma_pago_display() if obj.forma_pago else 'Sin dato', contado=obj.payment_type == 'efectivo',
                     titulo=f'Compra {numero}')
    elif tipo == 'gasto':
        numero = f'#{obj.pk}'
        datos = dict(numero=numero, tercero=obj.type_expense.name, identificacion='', fecha=obj.date_joined, importe=_decimal(obj.valor),
                     medio_id=obj.medio_pago, medio=obj.get_medio_pago_display() if obj.medio_pago else 'Sin dato', contado=True,
                     titulo=f'Gasto {numero} · {obj.type_expense.name}')
    elif tipo == 'cobro':
        cuenta = obj.ctas_collect
        numero = cuenta.documento()['numero']
        datos = dict(numero=numero, tercero=cuenta.sale.client.user.names, identificacion=cuenta.sale.client.dni, fecha=obj.date_joined,
                     importe=_decimal(obj.valor), medio_id=obj.medio_pago,
                     medio=obj.get_medio_pago_display() if obj.medio_pago else 'Sin dato', contado=True,
                     titulo=f'Cobro de {numero}', abono=obj.tipo, anulado=obj.anulado_en is not None)
    else:
        compra = obj.debts_pay.purchase
        numero = compra.numero_comprobante
        datos = dict(numero=numero, tercero=compra.provider.name, identificacion=compra.provider.ruc, fecha=obj.date_joined,
                     importe=_decimal(obj.valor), medio_id=obj.medio_pago,
                     medio=obj.get_medio_pago_display() if obj.medio_pago else 'Sin dato', contado=True,
                     titulo=f'Pago de {numero}')
    datos.update(tipo=tipo, id=obj.pk, tipo_nombre=DOCUMENTOS[tipo].nombre)
    # Un comprobante bancario se espera cuando el pago no fue en efectivo (o no se sabe el medio: compras y cobros antiguos).
    datos['requiere'] = datos['contado'] and datos['medio_id'] not in SIN_COMPROBANTE_ESPERADO
    if tipo == 'cobro' and (datos['abono'] != 'cobro' or datos['anulado']):
        datos['requiere'] = False
    return datos
