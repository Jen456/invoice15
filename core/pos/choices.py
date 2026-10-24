from decimal import Decimal

PAYMENT_TYPE = (
    ('efectivo', 'Efectivo'),
    ('credito', 'Credito'),
)

ENVIRONMENT_TYPE = (
    (1, 'PRUEBAS'),
    (2, 'PRODUCCIÓN'),
)

VOUCHER_TYPE = (
    ('01', 'FACTURA'),
    ('04', 'NOTA DE CRÉDITO'),
    ('08', 'TICKET DE VENTA'),
    # Comprobantes electrónicos adicionales (core/comprobantes); el orden de los tres primeros no cambia.
    ('03', 'LIQUIDACIÓN DE COMPRA'),
    ('05', 'NOTA DE DÉBITO'),
    ('06', 'GUÍA DE REMISIÓN'),
    ('07', 'COMPROBANTE DE RETENCIÓN'),
)

EMISSION_TYPE = (
    (1, 'Emisión Normal'),
)

RETENTION_AGENT = (
    ('SI', 'Si'),
    ('NO', 'No'),
)

# Régimen RIMPE (LRTI art. 97.2 y siguientes). La leyenda va en <contribuyenteRimpe> y en el RIDE (ficha técnica,
# Anexo 22); el SRI acepta las dos (verificado en el ambiente de pruebas el 16/10/2026).
RIMPE = (
    ('', 'No (régimen general)'),
    ('emprendedor', 'RIMPE Emprendedor'),
    ('negocio_popular', 'RIMPE Negocio Popular'),
)
LEYENDAS_RIMPE = {'emprendedor': 'CONTRIBUYENTE RÉGIMEN RIMPE', 'negocio_popular': 'CONTRIBUYENTE NEGOCIO POPULAR - RÉGIMEN RIMPE'}

OBLIGATED_ACCOUNTING = (
    ('SI', 'Si'),
    ('NO', 'No'),
)

IDENTIFICATION_TYPE = (
    ('05', 'CEDULA'),
    ('04', 'RUC'),
    ('06', 'PASAPORTE'),
    ('07', 'VENTA A CONSUMIDOR FINAL*'),
    ('08', 'IDENTIFICACION DEL EXTERIOR*'),
)

TAX_CODES = (
    (2, 'IVA'),
    (3, 'ICE'),
    (5, 'IRBPNR'),
)

VAT_PERCENTAGE = (
    (0, '0%'),
    (2, '12%'),
    (3, '14%'),
    (4, '15%'),
    (5, '5%'),
    (6, 'No Objeto de Impuesto'),
    (7, 'Exento de IVA'),
    (8, 'IVA diferenciado'),
    (10, '13%'),
)

PAYMENT_METHOD = (
    ('01', 'SIN UTILIZACION DEL SISTEMA FINANCIERO'),
    ('15', 'COMPENSACIÓN DE DEUDAS'),
    ('16', 'TARJETA DE DÉBITO'),
    ('17', 'DINERO ELECTRÓNICO'),
    ('18', 'TARJETA PREPAGO'),
    ('19', 'TARJETA DE CRÉDITO'),
    ('20', 'OTROS CON UTILIZACION DEL SISTEMA FINANCIERO'),
    ('21', 'ENDOSO DE TÍTULOS'),
)

VOUCHER_STAGE = (
    ('xml_creation', 'Creación del XML'),
    ('xml_signature', 'Firma del XML'),
    ('xml_validation', 'Validación del XML'),
    ('xml_authorized', 'Autorización del XML'),
    ('sent_by_email', 'Enviado por email'),
)

INVOICE_STATUS = (
    ('without_authorizing', 'Sin Autorizar'),
    ('authorized', 'Autorizada'),
    ('authorized_and_sent_by_email', 'Autorizada y enviada por email'),
    ('canceled', 'Anulado'),
    ('sequential_registered_error', 'Error de secuencial registrado'),
    # Emisión en dos fases (auditoría SRI, oct-2026): el comprobante se guarda firmado antes de enviarlo.
    ('in_process', 'En proceso en el SRI'),
    ('returned', 'Devuelta por el SRI'),
    ('not_authorized', 'No autorizada por el SRI'),
)


# Tarifa de IVA de cada producto (tabla 17 de la ficha: código de porcentaje). Vacío = derivar de «¿Se cobra impuesto?».
TARIFAS_IVA = (
    ('4', '15 %'),
    ('5', '5 %'),
    ('0', '0 %'),
    ('7', 'Exento de IVA'),
    ('6', 'No objeto de IVA'),
)
PORCENTAJE_IVA = {'0': Decimal('0'), '2': Decimal('12'), '3': Decimal('14'), '4': Decimal('15'), '5': Decimal('5'),
                  '6': Decimal('0'), '7': Decimal('0'), '10': Decimal('13')}
NOMBRE_TARIFA_IVA = {'4': '15 %', '5': '5 %', '0': '0 %', '7': 'exento de IVA', '6': 'no objeto de IVA', '2': '12 %', '3': '14 %',
                     '10': '13 %'}
ORDEN_TARIFAS_IVA = ('4', '10', '3', '2', '5', '0', '6', '7')
