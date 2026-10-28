"""Compras desde documentos importados (espec-etapa2-compras §3.6): datos del XML que pasan a la compra.

En el XML autorizado mandan los importes (DC4): bases por tarifa, IVA, ICE, IRBPNR, propina y total. Este módulo los
entrega a compras.crear_compra (importes=…) y a la orden compras_incompletas --desde-xml (compras.completar_datos).
"""
from decimal import Decimal

from core.pos.catalogos_sri import BASE_POR_CODIGO, FORMAS_PAGO

BASES = ('base_0', 'base_gravada', 'base_5', 'base_no_objeto', 'base_exenta')


class DatoNoReconocido(ValueError):
    """El XML trae un dato que la compra no sabe guardar (p. ej. un código de tarifa desconocido)."""


def importes_de_documento(documento):
    """{base_0, base_gravada, base_5, base_no_objeto, base_exenta, total_descuento, total_iva, total_ice, total_irbpnr,
    propina, subtotal, total} en Decimal, tomados del documento y de su desglose de IVA (ImpuestoImportado, código 2)."""
    bases = {b: Decimal('0.00') for b in BASES}
    for impuesto in documento.impuestos.filter(codigo='2').order_by('id'):
        campo = BASE_POR_CODIGO.get(impuesto.codigo_porcentaje)
        if campo is None:
            raise DatoNoReconocido(f'El XML trae una tarifa de IVA desconocida (código {impuesto.codigo_porcentaje}).')
        bases[campo] += Decimal(impuesto.base_imponible)
    return {**bases, 'total_descuento': Decimal(documento.total_descuento), 'total_iva': Decimal(documento.total_iva),
            'total_ice': Decimal(documento.total_ice), 'total_irbpnr': Decimal(documento.total_irbpnr),
            'propina': Decimal(documento.propina), 'subtotal': Decimal(documento.total_sin_impuestos),
            'total': Decimal(documento.importe_total)}


def forma_pago_del_xml(documento):
    """Forma de pago (Tabla 13) del pago de mayor valor del XML, o '' si el XML no trae pagos (no se elige de oficio)."""
    pagos = ((documento.datos or {}).get('comprobante') or {}).get('pagos') or []
    validos = [p for p in pagos if (p.get('forma_pago') or '') in dict(FORMAS_PAGO)]
    if not validos:
        return ''
    return max(validos, key=lambda p: Decimal(p.get('total') or '0'))['forma_pago']


def cabecera_de_documento(documento):
    """Datos del comprobante que trae el documento: tipo, numeración, autorización (clave de acceso), fecha de emisión,
    forma de pago (si el XML trae pagos) y pago a residente (el emisor de un comprobante electrónico tiene RUC)."""
    return {'tipo_comprobante': documento.cod_doc, 'estab': documento.estab, 'pto_emi': documento.pto_emi,
            'secuencial': documento.secuencial, 'autorizacion': documento.clave_acceso,
            'fecha_emision': documento.fecha_emision, 'forma_pago': forma_pago_del_xml(documento), 'pago_loc_ext': '01'}
