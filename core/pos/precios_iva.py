"""Precios con IVA incluido: cálculo de una línea (contrato común «precios con IVA», §1) y descripción de la línea.

El precio que se escribe (catálogo, factura, proforma) es el precio CON IVA y el total de la línea con IVA es exacto: la
base y el IVA se derivan. Todo con enteros (centavos) y mitad hacia arriba, igual en el servidor y en la pantalla:

    medio_arriba(a, b) = floor((2a + b) / (2b))
    bruto = P × q;  desc = medio_arriba(bruto × d, 100);  T = bruto − desc
    base = medio_arriba(T × 100, 100 + t);  iva = T − base

Solo el servidor (XML y RIDE) calcula además el subtotal y el descuento sin IVA y el precio unitario sin IVA con hasta 6
decimales (factura y nota de crédito 1.1.0), de modo que `cantidad × precioUnitario − descuento = precioTotalSinImpuesto`
al centavo. Las líneas guardadas antes de este cambio (sin precio con IVA) siguen con calcular_linea_iva
(core/pos/models.py): ningún comprobante ya emitido cambia.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import unicodedata

from core.pos.choices import PORCENTAJE_IVA

CENTAVO = Decimal('0.01')
MICRO = Decimal('0.000001')
MAX_DESCRIPCION = 300

# Textos para la usuaria (también en entregas/facturaporaqui/CONTRATO-PRECIOS-CON-IVA.md).
PANTALLA_CAMBIO = 'La pantalla de venta cambió: recarga la página y vuelve a intentarlo.'
PANTALLA_CAMBIO_PROFORMA = 'La pantalla de la proforma cambió: recarga la página y vuelve a intentarlo.'
DESCRIPCION_LARGA = 'La descripción admite hasta 300 caracteres.'
DESCRIPCION_CONTROL = 'La descripción no admite saltos de línea, tabuladores ni otros caracteres de control.'
DESCRIPCION_INVALIDA = 'La descripción debe ser un texto.'

# Caracteres que no van en la descripción: de control (incluidos \t, \n y \r: el XSD del SRI exige [^\n]*), sustitutos
# sueltos (no se codifican en UTF-8), separadores de línea y de párrafo y los dos no caracteres que XML 1.0 no admite.
_CATEGORIAS_PROHIBIDAS = ('Cc', 'Cs', 'Zl', 'Zp')
_PROHIBIDOS = ('￾', '￿')


def medio_arriba(a, b):
    """a / b redondeado a la mitad hacia arriba, con enteros (a ≥ 0, b > 0)."""
    return (2 * a + b) // (2 * b)


def a_centavos(valor):
    """Importe con hasta 2 decimales → centavos (entero). ValueError si tiene más decimales o no es un número."""
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        raise ValueError(f'Importe no válido: {valor!r}') from None
    centavos = numero * 100
    if not numero.is_finite() or centavos != centavos.to_integral_value():
        raise ValueError(f'Importe no válido: {valor!r}')
    return int(centavos)


def de_centavos(centavos):
    return (Decimal(int(centavos)) / 100).quantize(CENTAVO)


def tarifa_de_codigo(codigo):
    """Porcentaje entero de IVA del código de la tabla 17 (15, 5, 0…); exento, no objeto y códigos desconocidos = 0."""
    return int(PORCENTAJE_IVA.get(str(codigo or ''), Decimal('0')))


def base_unitaria(precio_con_iva, tarifa):
    """Precio sin IVA a centavos de un precio con IVA: medio_arriba(P × 100, 100 + t). Es el `pvp` del catálogo."""
    return de_centavos(medio_arriba(a_centavos(precio_con_iva) * 100, 100 + int(tarifa)))


def con_iva(precio_sin_iva, tarifa):
    """Precio con IVA a centavos de un precio sin IVA: medio_arriba(pvp × (100 + t), 100) (migración del catálogo y líneas
    anteriores al cambio). base_unitaria(con_iva(x, t), t) == x para todo x y t ≥ 0."""
    return de_centavos(medio_arriba(a_centavos(precio_sin_iva) * (100 + int(tarifa)), 100))


def precio_unitario(subtotal_centavos, cant):
    """(precio unitario sin IVA con 6 decimales, exacto) tal que round_half_up(cant × precio, 2) = subtotal.

    Se parte de subtotal / cant a 6 decimales y se ajusta lo justo si hace falta. Con cant ≤ 10000 siempre existe; con
    más unidades puede no existir ningún precio de 6 decimales que dé ese subtotal: entonces se devuelve el más cercano a
    subtotal / cant y exacto=False (caso documentado en CONTRATO-PRECIOS-CON-IVA.md)."""
    q = int(cant)
    micro = int(subtotal_centavos) * 10000            # subtotal en millonésimas de dólar
    k0 = medio_arriba(micro, q)                       # subtotal / q a 6 decimales
    # round_half_up(q·k/10^6, 2) = subtotal  ⇔  micro − 5000 ≤ q·k < micro + 5000
    minimo = -((5000 - micro) // q)                   # ceil((micro − 5000) / q)
    maximo = -((-(micro + 5000)) // q) - 1            # ceil((micro + 5000) / q) − 1
    if minimo <= maximo:
        k, exacto = min(max(k0, minimo, 0), maximo), True
    else:
        k, exacto = k0, False
    return (Decimal(k) / 1000000).quantize(MICRO), exacto


@dataclass(frozen=True)
class LineaConIva:
    """Importes de una línea con precio con IVA. Dinero en Decimal con 2 decimales; precio_unitario con 6."""
    precio_con_iva: Decimal
    cant: int
    dscto: int                  # porcentaje entero
    tarifa: int                 # porcentaje entero de IVA
    bruto: Decimal              # P × q, con IVA
    descuento_con_iva: Decimal
    total_con_iva: Decimal      # T: lo que paga el cliente
    base: Decimal               # precioTotalSinImpuesto y baseImponible
    iva: Decimal                # T − base
    subtotal_sin_iva: Decimal   # cantidad × precioUnitario, a centavos
    descuento_sin_iva: Decimal  # descuento del XML (≥ 0)
    precio_unitario: Decimal    # sin IVA, 6 decimales
    exacto: bool                # round_half_up(cant × precio_unitario, 2) == subtotal_sin_iva


def calcular(precio_con_iva, cant, dscto, tarifa):
    """Contrato §1. `precio_con_iva` con hasta 2 decimales, `cant` y `dscto` (porcentaje) enteros, `tarifa` porcentaje."""
    p, q, d, t = a_centavos(precio_con_iva), int(cant), int(dscto), int(tarifa)
    if p < 0 or q < 1 or not 0 <= d <= 100 or t < 0:
        raise ValueError('Línea fuera de rango')
    bruto = p * q
    descuento = medio_arriba(bruto * d, 100)
    total = bruto - descuento
    base = medio_arriba(total * 100, 100 + t)
    subtotal = medio_arriba(bruto * 100, 100 + t)
    unitario, exacto = precio_unitario(subtotal, q)
    return LineaConIva(precio_con_iva=de_centavos(p), cant=q, dscto=d, tarifa=t, bruto=de_centavos(bruto),
                       descuento_con_iva=de_centavos(descuento), total_con_iva=de_centavos(total), base=de_centavos(base),
                       iva=de_centavos(total - base), subtotal_sin_iva=de_centavos(subtotal),
                       descuento_sin_iva=de_centavos(subtotal - base), precio_unitario=unitario, exacto=exacto)


def dscto_entero(fraccion):
    """Descuento guardado como fracción (0.10) → porcentaje entero (10)."""
    return int((Decimal(str(fraccion)) * 100).to_integral_value(ROUND_HALF_UP))


def texto_decimal(valor, minimo=2, maximo=6):
    """Número para el XML 1.1.0 (precioUnitario, cantidad): con `minimo` decimales y hasta `maximo`, sin ceros de más
    («869.57», «8.695652», «3.00»). El XSD los define como xsd:decimal con fractionDigits 6 y totalDigits 18."""
    texto = f'{Decimal(str(valor)).quantize(Decimal(1).scaleb(-maximo), ROUND_HALF_UP):f}'
    entero, _, decimales = texto.partition('.')
    return f'{entero}.{decimales.rstrip("0").ljust(minimo, "0")}'


def limpiar_descripcion(texto, nombre):
    """(descripción, error) de una línea: sin espacios de más; vacía → `nombre` (el del producto); más de 300 caracteres
    o con caracteres de control → (None, texto del error). No cambia el catálogo."""
    if texto is None:
        texto = ''
    if not isinstance(texto, str):
        return None, DESCRIPCION_INVALIDA
    if any(c in _PROHIBIDOS or unicodedata.category(c) in _CATEGORIAS_PROHIBIDAS for c in texto):
        return None, DESCRIPCION_CONTROL
    limpia = ' '.join(texto.split())
    if len(limpia) > MAX_DESCRIPCION:
        return None, DESCRIPCION_LARGA
    return (limpia or ' '.join(str(nombre or '').split())[:MAX_DESCRIPCION]), None
