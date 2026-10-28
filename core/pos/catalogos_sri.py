"""Catálogos del SRI para compras y el ATS (Catálogo ATS, hoja «TABLAS REFERENCIALES»).
Fuente: Catalogo_ATS.xls, SHA-256 bd3f7834f2cd31187af39cd2f4c685a646d7e49316e92ee493da5f2dd9776e3e (copia del 28/10/2026).
Cambiar solo copiando del catálogo vigente; anotar aquí la fuente y la fecha.

Constantes literales del catálogo oficial (subconjunto de compras) y funciones puras: sin base de datos.
"""
from datetime import date
from decimal import Decimal

from core.pos.choices import PAYMENT_METHOD

# Tabla 2 (transacción COMPRA): 01 RUC, 02 cédula, 03 pasaporte / identificación tributaria del exterior
TIPO_ID_COMPRA = (('01', 'RUC'), ('02', 'Cédula'), ('03', 'Pasaporte / identificación tributaria del exterior'))
# Tipo de identificación de la factura electrónica (tabla 6 de la ficha) → Tabla 2 del ATS. El 07 no aplica a proveedores.
TIPO_ID_FE_A_ATS = {'04': '01', '05': '02', '06': '03', '08': '03'}
TIPOS_IDENTIFICACION_PROVEEDOR = (('04', 'RUC'), ('05', 'Cédula'), ('06', 'Pasaporte'), ('08', 'Identificación del exterior'))

# Tabla 4: tipos admitidos en Compras en esta etapa
TIPOS_COMPROBANTE_COMPRA = (
    ('01', 'Factura'), ('02', 'Nota o boleta de venta'),
    ('03', 'Liquidación de compra de bienes o prestación de servicios'),
    ('04', 'Nota de crédito'), ('05', 'Nota de débito'),
    ('09', 'Tiquetes o vales emitidos por máquinas registradoras'),
    ('11', 'Pasajes expedidos por empresas de aviación'), ('12', 'Documentos emitidos por instituciones financieras'),
    ('15', 'Comprobante de venta emitido en el exterior'), ('19', 'Comprobantes de pago de cuotas o aportes'),
    ('20', 'Documentos por servicios administrativos emitidos por instituciones del Estado'), ('21', 'Carta de porte aéreo'),
)
# Tabla 4, columna «Código secuenciales transacción» restringida a compras (01 con RUC, 02 con cédula, 03 con pasaporte/exterior)
TIPO_ID_POR_COMPROBANTE = {'01': {'01'}, '02': {'01'}, '03': {'02', '03'}, '04': {'01', '02', '03'}, '05': {'01', '02', '03'},
                           '09': {'01', '02', '03'}, '11': {'01'}, '12': {'01', '02', '03'}, '15': {'03'},
                           '19': {'01', '02', '03'}, '20': {'01'}, '21': {'01'}}
TIPOS_CON_DOC_MODIFICADO = ('04', '05')
TIPOS_SIN_FORMA_PAGO = ('04',)                     # «No aplica para notas de crédito (04)»
TIPOS_SIN_RETENCION = ('04',)                      # «Al registrar notas de crédito 04… no se registrará comprobante de retención»
# Tabla 4, fila «Nota o boleta de venta»: solo sustentos sin crédito (02, 04, 05, 07, 08, 14, 15). No discrimina IVA.
TIPOS_SIN_IVA_DISCRIMINADO = ('02',)
CODIGOS_IVA_NOTA_VENTA = ('0', '6')                # sus valores se registran con tarifa 0 % (o no objeto); a confirmar en D7

# Tabla 5 (vigentes). El 12 exige el tipo 42 (no admitido); el 00 venció el 28/02/2015.
SUSTENTOS = (
    ('01', 'Crédito tributario para declaración de IVA (servicios y bienes distintos de inventarios y activos fijos)'),
    ('02', 'Costo o gasto para declaración de IR (servicios y bienes distintos de inventarios y activos fijos)'),
    ('03', 'Activo fijo - Crédito tributario para declaración de IVA'),
    ('04', 'Activo fijo - Costo o gasto para declaración de IR'),
    ('05', 'Liquidación de gastos de viaje, hospedaje y alimentación, gastos IR (a nombre de empleados y no de la empresa)'),
    ('06', 'Inventario - Crédito tributario para declaración de IVA'),
    ('07', 'Inventario - Costo o gasto para declaración de IR'),
    ('08', 'Valor pagado para solicitar reembolso de gasto (intermediario)'),
    ('09', 'Reembolso por siniestros'),
    ('10', 'Distribución de dividendos, beneficios o utilidades'),
    ('11', 'Convenios de débito o recaudación para IFIs'),
    ('13', 'Valores reconocidos por entidades del sector público a favor de sujetos pasivos'),
    ('14', 'Valores facturados por socios a operadoras de transporte (que no constituyen gasto de dicha operadora)'),
    ('15', 'Pagos efectuados por consumos propios y de terceros de servicios digitales'),
)
# Tabla 5, columna «Código tipo comprobante», restringida a TIPOS_COMPROBANTE_COMPRA
COMPROBANTES_POR_SUSTENTO = {
    '01': {'01', '03', '04', '05', '11', '12', '21'},
    '02': {'01', '02', '03', '04', '05', '09', '11', '12', '15', '19', '20', '21'},
    '03': {'01', '03', '04', '05'}, '04': {'01', '02', '03', '04', '05', '15'},
    '05': {'01', '02', '03', '04', '05', '11', '15'}, '06': {'01', '03', '04', '05'},
    '07': {'01', '02', '03', '04', '05', '15'}, '08': {'01', '02', '03', '04', '05', '21'}, '09': {'01', '04', '05'},
    '10': {'19'}, '11': {'12'}, '13': {'19'}, '14': {'01', '02', '03', '04', '05'},
    '15': {'01', '02', '03', '04', '05', '12', '15'},
}
FORMAS_PAGO = PAYMENT_METHOD                        # Tabla 13 vigente: 01, 15, 16, 17, 18, 19, 20, 21 (igual a choices.py).
                                                    # SOLO para Purchase.forma_pago (dato del comprobante para el ATS).
                                                    # Pagos y gastos usan MEDIOS_DE_PAGO de core/pos/choices.py (B0), DC13.
# Hoja «ESQUEMA TIPO 1 Y 2», fila formaPago: obligatoria cuando bases + impuestos > USD 1.000. Un pago mayor sin el sistema
# financiero no es deducible ni da crédito de IVA (bancarización): se avisa, no se bloquea.
UMBRAL_BANCARIZACION = Decimal('1000.00')
# Hoja «ESQUEMA TIPO 1 Y 2», filas fechaRegistro/fechaEmision: el DIMM rechaza registros más de un año después de la emisión.
PLAZO_ATS_DIAS = 365
TIPOS_SUJETO = (('01', 'Persona natural'), ('02', 'Sociedad'))            # Tabla 14
PAGO_LOC_EXT = (('01', 'Pago a residente / establecimiento permanente'), ('02', 'Pago a no residente'))   # Tabla 15

# Tarifas de IVA admitidas en líneas de compra (código de porcentaje, tabla 17 de la ficha). '2' (12 %) solo para
# comprobantes emitidos antes del 01/04/2024; '4' (15 %) desde esa fecha (RO S.525, 25/03/2024).
# '8' = IVA diferenciado (p. ej. turismo en feriados): su tarifa NO es fija; la da el XML o la escribe el usuario.
CODIGOS_IVA_COMPRA = ('4', '5', '0', '6', '7', '2', '8')
CODIGOS_CON_TARIFA_VARIABLE = ('8',)
INICIO_IVA_15 = date(2024, 4, 1)
# Tarifa fija por código (no se usa PORCENTAJE_IVA de choices.py, que no tiene '8'). Para '8' la tarifa va en la línea.
TARIFA_POR_CODIGO = {'4': Decimal('15'), '2': Decimal('12'), '3': Decimal('14'), '10': Decimal('13'), '5': Decimal('5'),
                     '0': Decimal('0'), '6': Decimal('0'), '7': Decimal('0')}
# Código de porcentaje → campo de base de la compra
BASE_POR_CODIGO = {'4': 'base_gravada', '2': 'base_gravada', '3': 'base_gravada', '10': 'base_gravada', '8': 'base_gravada',
                   '5': 'base_5', '0': 'base_0', '6': 'base_no_objeto', '7': 'base_exenta'}

# Tabla 12 (tarifa general del IVA por período): 14 % del 01/06/2016 al 31/05/2017; 15 % desde el 01/04/2024; 12 % en otro caso.
INICIO_IVA_14 = date(2016, 6, 1)
FIN_IVA_14 = date(2017, 5, 31)


def tipo_id_ats(tipo_fe):
    """Tipo de identificación de la factura electrónica → Tabla 2 del ATS ('04' → '01'); '' si no hay equivalencia."""
    return TIPO_ID_FE_A_ATS.get(tipo_fe or '', '')


def sustento_admite(cod_sustento, tipo):
    """True si el sustento tributario admite el tipo de comprobante (Tabla 5)."""
    return (tipo or '') in COMPROBANTES_POR_SUSTENTO.get(cod_sustento or '', ())


def sustentos_para(tipo):
    """[(código, nombre)] de los sustentos que admiten el tipo de comprobante (para el selector)."""
    return [(codigo, texto) for codigo, texto in SUSTENTOS if sustento_admite(codigo, tipo)]


def tipo_id_admite(tipo, tipo_id_ats_):
    """True si el tipo de comprobante admite el tipo de identificación del ATS del proveedor (Tabla 4)."""
    return (tipo_id_ats_ or '') in TIPO_ID_POR_COMPROBANTE.get(tipo or '', set())


def tarifa_iva_general(fecha):
    """Tarifa general del IVA (Decimal) vigente en `fecha` (Tabla 12)."""
    if fecha >= INICIO_IVA_15:
        return Decimal('15')
    if INICIO_IVA_14 <= fecha <= FIN_IVA_14:
        return Decimal('14')
    return Decimal('12')


def nombre(catalogo, codigo):
    """Nombre visible de un código del catálogo, o el propio código si no figura."""
    return dict(catalogo).get(codigo, codigo)
