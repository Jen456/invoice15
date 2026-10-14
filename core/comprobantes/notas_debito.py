"""Nota de débito (05) emitida sobre una factura: reglas en el servidor.

- Solo sobre facturas autorizadas por el SRI, del mismo ambiente y que no sean a consumidor final (el comprador debe
  estar identificado, como en las notas de crédito).
- Uno o varios motivos (razón y valor, p. ej. intereses de mora); el XSD 1.0.0 admite varios <motivo>.
- La tarifa de IVA es la de la fecha de la factura (nota de la ficha técnica) o 0 % si el cargo no grava IVA; nunca
  la que mande el navegador. IVA = base × tarifa (HALF_UP).
- Una factura admite varias notas de débito; cada una cuenta 1 del cupo.
"""
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from core.comprobantes.models import NotaDebito, NotaDebitoMotivo, redondear

TIPO_NOTA_DEBITO = '05'
MAX_MOTIVOS = 10
AUTORIZADOS = ('authorized', 'authorized_and_sent_by_email')


class ErrorNotaDebito(Exception):
    """Mensaje para el usuario."""


def tarifa_de_factura(venta):
    """Tarifa de IVA de la factura en porcentaje (Sale.iva se guarda como fracción: 0.15)."""
    tarifa = Decimal(str(venta.iva or 0))
    return redondear(tarifa * 100 if tarifa <= 1 else tarifa)


def tarifas_permitidas(venta):
    tarifa = tarifa_de_factura(venta)
    return [tarifa, Decimal('0.00')] if tarifa > 0 else [Decimal('0.00')]


def validar_factura(venta, company):
    from core.pos.choices import VOUCHER_TYPE
    from core.pos.notas_credito import es_consumidor_final
    if venta.receipt.voucher_type != VOUCHER_TYPE[0][0]:
        raise ErrorNotaDebito('Las notas de débito solo se emiten sobre facturas.')
    if venta.status not in AUTORIZADOS:
        raise ErrorNotaDebito('La factura debe estar autorizada por el SRI para emitir una nota de débito.')
    if es_consumidor_final(venta.client):
        raise ErrorNotaDebito('No se emiten notas de débito sobre facturas a consumidor final: el comprador debe estar identificado.')
    if venta.environment_type != company.environment_type:
        raise ErrorNotaDebito(f'La factura es del ambiente {venta.get_environment_type_display()} y la empresa emite '
                              f'en {company.get_environment_type_display()}.')


def calcular(venta, datos, motivos):
    """Valida y calcula sin guardar. motivos: [(razón, valor)]. Devuelve (documento normalizado, [motivo], totales)."""
    try:
        tarifa = redondear(Decimal(str(datos.get('tarifa_iva') if datos.get('tarifa_iva') not in (None, '') else tarifa_de_factura(venta))))
    except InvalidOperation:
        raise ErrorNotaDebito('Elige la tarifa de IVA de la nota de débito.')
    if tarifa not in tarifas_permitidas(venta):
        raise ErrorNotaDebito(f'La tarifa de IVA debe ser la de la factura ({tarifa_de_factura(venta).normalize():f} %) o 0 %.')
    limpios = []
    for razon, valor in motivos:
        razon = ' '.join((razon or '').split())[:300]
        if not razon and valor in (None, ''):
            continue
        if not razon:
            raise ErrorNotaDebito('Escribe la razón de cada valor (por ejemplo, «Interés por mora»).')
        try:
            valor = Decimal(str(valor))
        except InvalidOperation:
            raise ErrorNotaDebito(f'El valor de «{razon}» no es un número.')
        if valor <= 0:
            raise ErrorNotaDebito(f'El valor de «{razon}» debe ser mayor que cero.')
        limpios.append({'razon': razon, 'valor': redondear(valor)})
    if not limpios:
        raise ErrorNotaDebito('Agrega al menos un motivo con su valor.')
    if len(limpios) > MAX_MOTIVOS:
        raise ErrorNotaDebito(f'Una nota de débito admite hasta {MAX_MOTIVOS} motivos.')
    base = redondear(sum(m['valor'] for m in limpios))
    iva = redondear(base * tarifa / 100)
    doc = {'tarifa_iva': tarifa, 'forma_pago': datos.get('forma_pago') or venta.payment_method or '20'}
    return doc, limpios, {'total_sin_impuestos': base, 'valor_iva': iva, 'valor_total': redondear(base + iva)}


def crear(company, usuario, venta, datos, motivos):
    """Nota de débito guardada (aún sin firmar). Llamar dentro de una transacción; la vista firma después."""
    from core.configuracion.servicios import receipt_para_emitir
    from core.pos.models import Sale
    venta = Sale.objects.select_for_update().select_related('client__user', 'receipt').get(pk=venta.pk)
    validar_factura(venta, company)
    doc, limpios, totales = calcular(venta, datos, motivos)
    cliente = venta.client
    receipt = receipt_para_emitir(company, TIPO_NOTA_DEBITO, electronica=True)
    numero = receipt.reservar_numero()
    correo = (cliente.user.email or '').strip()
    nota = NotaDebito(
        company=company, receipt=receipt, voucher_number=numero,
        voucher_number_full=f'{receipt.establishment_code}-{receipt.issuing_point_code}-{numero}',
        employee=usuario, environment_type=company.environment_type, date_joined=timezone.localdate(), sale=venta,
        tipo_identificacion=cliente.identification_type, identificacion=cliente.dni.strip(),
        razon_social=' '.join(cliente.user.names.split())[:300], direccion=' '.join((cliente.address or '').split())[:300],
        correo=correo if '@' in correo else '', enviar_correo=cliente.send_email_invoice,
        cod_doc_modificado=venta.receipt.voucher_type, num_doc_modificado=venta.voucher_number_full,
        fecha_doc_sustento=venta.emission_date or venta.date_joined, **doc, **totales)
    nota.save()
    for m in limpios:
        NotaDebitoMotivo.objects.create(nota=nota, razon=m['razon'], valor=m['valor'])
    return nota
