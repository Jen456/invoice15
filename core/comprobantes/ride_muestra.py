"""Factura de MUESTRA para la vista previa de «Diseño de factura»: un comprobante ficticio armado en memoria.

Lleva la identidad del comercio de la sesión (razón social, nombre comercial, RUC, direcciones, logo, contabilidad,
contribuyente especial y RIMPE) y comprador, líneas, totales, número y clave de acceso ficticios (ambiente PRUEBAS). No
crea filas (Sale, Receipt, secuencias, cupo) ni archivos, no firma ni envía nada al SRI, y la plantilla imprime la marca
«MUESTRA · SIN VALIDEZ TRIBUTARIA» en cada página (ride_muestra=True). Usa la misma plantilla que las facturas reales
(sale/format/invoice.html), así que la muestra es fiel al RIDE que saldrá con ese estilo.
"""
from decimal import Decimal
from types import SimpleNamespace as NS

from django.utils import timezone

from core.comprobantes import ride_styles

SECUENCIAL = '000000001'
CODIGO_NUMERICO = '12345678'
AMBIENTE_PRUEBAS = 1
RUC_RESPALDO = '9999999999999'
# (código, descripción, cantidad, precio, código de tarifa, nombre de la tarifa, %)
LINEAS = (
    ('MUE-001', 'Producto de muestra con IVA', 2, Decimal('25.00'), '4', '15 %', Decimal('15')),
    ('MUE-002', 'Servicio de muestra con descripción larga para ver el ajuste del texto en la tabla', 1,
     Decimal('40.00'), '4', '15 %', Decimal('15')),
    ('MUE-003', 'Producto de muestra con tarifa 0 %', 3, Decimal('5.00'), '0', '0 %', Decimal('0')),
)


class _Filas(list):
    def all(self):
        return self


def digito_verificador(clave_48):
    """Módulo 11 de la ficha técnica del SRI (factores 2 a 7 de derecha a izquierda; 11 → 0, 10 → 1)."""
    suma = sum(int(d) * f for d, f in zip(reversed(clave_48), (2, 3, 4, 5, 6, 7) * 8))
    resto = 11 - suma % 11
    return '0' if resto == 11 else '1' if resto == 10 else str(resto)


def clave_ficticia(ruc, fecha, estab, pto):
    """Clave de acceso de 49 dígitos con dígito verificador, en ambiente PRUEBAS (1) y emisión normal (1)."""
    ruc = ruc if isinstance(ruc, str) and len(ruc) == 13 and ruc.isdigit() else RUC_RESPALDO
    base = f'{fecha:%d%m%Y}01{ruc}{AMBIENTE_PRUEBAS}{estab}{pto}{SECUENCIAL}{CODIGO_NUMERICO}1'
    return base + digito_verificador(base)


def _punto(company):
    """(estab, pto, dirección) de la numeración de facturas configurada, solo para leerla; 001-001 si no hay."""
    from core.configuracion.servicios import secuencia_configurada
    try:
        receipt = secuencia_configurada(company, '01')
    except Exception:   # la muestra no depende de que la configuración esté completa
        receipt = None
    if receipt is None:
        return '001', '001', company.establishment_address
    return receipt.establishment_code, receipt.issuing_point_code, receipt.establishment_address() or company.establishment_address


def contexto(company, style=None, primary=None, secondary=None):
    """Contexto de sale/format/invoice.html para la muestra (style/primary/secondary se normalizan aquí)."""
    from core.comprobantes.ride import codigo_de_barras
    from core.pos.emision import datos_proveedor
    hoy = timezone.localdate()
    estab, pto, direccion = _punto(company)
    clave = clave_ficticia(company.ruc, hoy, estab, pto)
    filas, tarifas = _Filas(), {}
    for codigo, descripcion, cantidad, precio, tarifa, nombre, porcentaje in LINEAS:
        total = (precio * cantidad).quantize(Decimal('.01'))
        filas.append(NS(product=NS(code=codigo, get_short_name=descripcion), cant=cantidad, price=precio,
                        total_dscto=Decimal('0.00'), total=total))
        base, _, _ = tarifas.get(tarifa, (Decimal('0'), nombre, porcentaje))
        tarifas[tarifa] = (base + total, nombre, porcentaje)
    impuestos = [NS(codigo=c, nombre=n, tarifa=p, base=b, valor=(b * p / 100).quantize(Decimal('.01')))
                 for c, (b, n, p) in tarifas.items()]
    subtotal = sum(f.total for f in filas)
    total = subtotal + sum(t.valor for t in impuestos)
    sale = NS(
        company=company,   # solo se leen sus datos de identidad; nada se guarda
        client=NS(user=NS(names='COMPRADOR FICTICIO DE MUESTRA', email='comprador@example.test'), dni=RUC_RESPALDO,
                  address='Dirección ficticia del comprador', mobile=''),
        receipt=NS(establishment_address=direccion),
        voucher_number_full=f'{estab}-{pto}-{SECUENCIAL}', access_code=clave, authorization_date=None,
        emission_date=hoy, date_joined=hoy, get_environment_type_display='PRUEBAS',
        get_proveedor=datos_proveedor(), saledetail_set=filas, impuestos_por_tarifa=impuestos,
        get_subtotal_without_taxes=subtotal, total_dscto=Decimal('0.00'), total=total, time_limit=0,
        get_payment_method_display='SIN UTILIZACION DEL SISTEMA FINANCIERO',
        additional_info=[NS(name='Observación', value='Factura de muestra sin validez tributaria')],
    )
    return {'sale': sale, 'access_code_barcode': codigo_de_barras(clave), 'ride_muestra': True,
            'ride_style': ride_styles.template_context(style, primary, secondary)}
