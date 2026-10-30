"""Comprobante de retención (07) emitido sobre una compra: reglas en el servidor.

- Datos del sujeto retenido tomados del proveedor de la compra (copiados al emitir).
- Documento sustento: la factura del proveedor (01) o la liquidación de compra que emitió la empresa (03); número de 15 dígitos (001-001-000000123), autorización de 10, 37 o 49 dígitos,
  fecha no futura, bases e IVA de la factura del proveedor.
- Retenciones con la fila del catálogo (CodigoRetencion) vigente en la fecha de la retención: renta sobre la base sin
  impuestos e IVA sobre el valor del IVA; el porcentaje sale del catálogo salvo los códigos de porcentaje variable;
  valor = base × % (HALF_UP).
- Emitir solo lo que se revisó: la huella de lo revisado (documento sustento y, por línea, código, fila del catálogo,
  base, % y valor) debe coincidir con el cálculo al emitir.
- Una compra tiene a lo sumo una retención vigente (las devueltas o no autorizadas no cuentan).
"""
import hashlib
import re
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from core.comprobantes.models import CodigoRetencion, Retencion, RetencionDetalle, redondear
from core.pos.emision import AUTORIZADOS

NO_CUENTAN = ('returned', 'not_authorized', 'sequential_registered_error')
MAX_LINEAS = 10
TIPO_RETENCION = '07'


class ErrorRetencion(Exception):
    """Mensaje para el usuario."""


class RevisionDesactualizada(ErrorRetencion):
    """El cálculo al emitir no es el revisado (se cambiaron datos tras revisar, cambió la vigencia o se editó el catálogo) o
    falta la revisión: lleva el cálculo nuevo."""

    def __init__(self, doc, detalle, total):
        super().__init__('El cálculo ya no es el que revisaste (cambiaron los datos, la vigencia o el catálogo de retenciones). '
                         'Revisa el nuevo cálculo y vuelve a emitir.')
        self.doc, self.detalle, self.total = doc, detalle, total


# Para crear() sin el paso «Revisar» (usos internos que calculan y guardan a la vez, como las pruebas): explícito, para
# que ningún llamador nuevo emita sin revisar por olvido.
SIN_REVISION = object()


def numero_documento(texto):
    digitos = re.sub(r'\D', '', texto or '')
    if len(digitos) != 15 or digitos[:3] == '000' or digitos[3:6] == '000' or int(digitos[6:]) == 0:
        raise ErrorRetencion('Escribe el número de la factura del proveedor con establecimiento, punto y secuencial: 001-001-000000123.')
    return digitos


def autorizacion(texto):
    digitos = re.sub(r'\D', '', texto or '')
    if len(digitos) not in (10, 37, 49):
        raise ErrorRetencion('La autorización de la factura del proveedor tiene 49 dígitos (clave de acceso), o 10 o 37 en '
                             'comprobantes antiguos.')
    return digitos


def tipo_identificacion(identificacion):
    numero = re.sub(r'\s', '', identificacion or '')
    if re.fullmatch(r'\d{13}', numero):
        return '04'
    if re.fullmatch(r'\d{10}', numero):
        return '05'
    return '06'


def retencion_vigente(compra):
    # Etapa 2 (O2): una retención anulada en el SRI deja de contar y la compra admite una nueva.
    return Retencion.objects.filter(purchase=compra, anulado_sri_fecha__isnull=True).exclude(status__in=NO_CUENTAN).first()


def retenciones_autorizadas(compra):
    """Retenciones emitidas sobre la compra que autorizó el SRI: las que abonan a su cuenta por pagar.

    Es la única regla de «retención que cuenta» (Compras no filtra el estado por su cuenta); O2 le añade el filtro de
    las anuladas en el SRI.
    """
    return Retencion.objects.filter(purchase=compra, status__in=AUTORIZADOS, anulado_sri_fecha__isnull=True)


# Fuera de este módulo (Compras, Ventas) el catálogo se consulta solo con estas dos funciones: hay una fila por
# vigencia de cada (impuesto, código), y la que vale es la que cubre `fecha`.

def codigo_retencion_vigente(impuesto, codigo, fecha, incluir_inactivos=False):
    """Fila del catálogo de la pareja (impuesto, código) vigente en `fecha`, o None.

    incluir_inactivos=True también devuelve los códigos que ya no se ofrecen para emitir (p. ej. los que usa un cliente
    al retenernos).
    """
    return CodigoRetencion.vigente(impuesto, codigo, fecha, incluir_inactivos=incluir_inactivos)


def codigos_retencion_vigentes(fecha, incluir_inactivos=False):
    """Una fila por pareja (impuesto, código) vigente en `fecha`, con el orden del catálogo."""
    return CodigoRetencion.objects.vigentes(fecha, incluir_inactivos=incluir_inactivos)


def _decimal(valor, campo):
    try:
        numero = Decimal(str(valor if valor not in (None, '') else '0'))
    except InvalidOperation:
        raise ErrorRetencion(f'{campo}: escribe un valor numérico.')
    if numero < 0:
        raise ErrorRetencion(f'{campo}: no puede ser negativo.')
    return redondear(numero)


def calcular(datos, lineas, fecha=None):
    """Valida y calcula sin guardar. datos: campos del documento sustento; lineas: [(id de código, base o None, % o None)].

    Cada código se toma de la fila del catálogo vigente en `fecha` (por defecto hoy), aunque el id recibido sea el de
    otra vigencia del mismo código. Devuelve (documento normalizado, [detalle calculado], total retenido).
    """
    fecha = fecha or timezone.localdate()
    doc = {
        'num_doc_sustento': numero_documento(datos.get('num_doc_sustento')),
        'aut_doc_sustento': autorizacion(datos.get('aut_doc_sustento')),
        'fecha_doc_sustento': datos.get('fecha_doc_sustento'),
        'base_0': _decimal(datos.get('base_0'), 'Base 0 %'),
        'base_iva': _decimal(datos.get('base_iva'), 'Base gravada'),
        'tarifa_iva': _decimal(datos.get('tarifa_iva') or '15', 'Tarifa de IVA'),
        'cod_sustento': datos.get('cod_sustento') or '01',
        'cod_doc_sustento': datos.get('cod_doc_sustento') or '01',
        'forma_pago': datos.get('forma_pago') or '20',
        'parte_relacionada': bool(datos.get('parte_relacionada')),
    }
    if doc['cod_doc_sustento'] not in ('01', '03'):
        raise ErrorRetencion('El documento sustento debe ser una factura o una liquidación de compra.')
    if doc['cod_doc_sustento'] == '03' and doc['cod_sustento'] == '09':
        raise ErrorRetencion('El sustento 09 (reembolso por siniestros) no admite una liquidación de compra como documento sustento.')
    if doc['fecha_doc_sustento'] is None or doc['fecha_doc_sustento'] > timezone.localdate():
        raise ErrorRetencion('La fecha de emisión de la factura del proveedor no puede ser futura.')
    valor_iva = datos.get('valor_iva')
    doc['valor_iva'] = _decimal(valor_iva, 'Valor del IVA') if valor_iva not in (None, '') else \
        redondear(doc['base_iva'] * doc['tarifa_iva'] / 100)
    if doc['base_0'] + doc['base_iva'] <= 0:
        raise ErrorRetencion('Escribe las bases de la factura del proveedor (0 % y/o gravada con IVA).')
    total_sin_impuestos = doc['base_0'] + doc['base_iva']
    lineas = [linea for linea in lineas if linea and linea[0]]
    if not lineas:
        raise ErrorRetencion('Agrega al menos una retención (renta o IVA).')
    if len(lineas) > MAX_LINEAS:
        raise ErrorRetencion(f'Una retención admite hasta {MAX_LINEAS} líneas.')
    elegidos = {str(c.pk): c for c in CodigoRetencion.objects.filter(pk__in=[linea[0] for linea in lineas])}
    detalle, usados = [], set()
    for codigo_id, base, porcentaje in lineas:
        elegido = elegidos.get(str(codigo_id))
        if elegido is None:
            raise ErrorRetencion('Uno de los códigos de retención no existe o ya no está disponible.')
        codigo = CodigoRetencion.vigente(elegido.impuesto, elegido.codigo, fecha)
        if codigo is None:
            raise ErrorRetencion(f'El código {elegido.codigo} no está vigente el {fecha:%d/%m/%Y}.')
        if (codigo.impuesto, codigo.codigo) in usados:
            raise ErrorRetencion(f'El código {codigo.codigo} está repetido.')
        usados.add((codigo.impuesto, codigo.codigo))
        tope = total_sin_impuestos if codigo.impuesto == '1' else doc['valor_iva']
        base = _decimal(base, f'Base del código {codigo.codigo}') if base not in (None, '') else tope
        if base <= 0:
            raise ErrorRetencion(f'La base del código {codigo.codigo} debe ser mayor que cero'
                                 + (' (la factura no tiene IVA).' if codigo.impuesto == '2' else '.'))
        if base > tope:
            raise ErrorRetencion(f'La base del código {codigo.codigo} ({base}) supera '
                                 + ('la base sin impuestos' if codigo.impuesto == '1' else 'el IVA') + f' de la factura ({tope}).')
        if codigo.porcentaje_editable and porcentaje not in (None, ''):
            pct = _decimal(porcentaje, f'Porcentaje del código {codigo.codigo}')
            if pct > 100:
                raise ErrorRetencion(f'El porcentaje del código {codigo.codigo} no puede superar 100.')
        else:
            pct = codigo.porcentaje
        detalle.append({'codigo_obj': codigo, 'impuesto': codigo.impuesto, 'codigo': codigo.codigo, 'concepto': codigo.concepto,
                        'base_imponible': base, 'porcentaje': pct, 'valor_retenido': redondear(base * pct / 100)})
    total = redondear(sum(d['valor_retenido'] for d in detalle))
    return doc, detalle, total


def huella(doc, detalle):
    """Resumen de lo revisado que viaja con «Emitir»: el documento sustento normalizado (número, autorización, fecha,
    bases, IVA, sustento, forma de pago) y, por línea, impuesto, código, fila del catálogo, base, % y valor retenido."""
    texto = '|'.join([';'.join(f'{campo}={doc[campo]}' for campo in sorted(doc))] + [
        f"{d['impuesto']}:{d['codigo']}:{d['codigo_obj'].pk}:{redondear(d['base_imponible'])}:{redondear(d['porcentaje'])}:"
        f"{redondear(d['valor_retenido'])}" for d in detalle])
    return hashlib.sha256(texto.encode()).hexdigest()[:32]


def crear(company, usuario, compra, datos, lineas, *, huella_revisada):
    """Retención guardada (aún sin firmar) para `compra`. Llamar dentro de una transacción; la vista firma después.

    `huella_revisada` es obligatoria: la de «Revisar» (si el cálculo de ahora es otro, o viene vacía, lanza
    RevisionDesactualizada y no guarda) o SIN_REVISION para los usos internos que no pasan por «Revisar».
    """
    from core.configuracion.servicios import receipt_para_emitir
    from core.pos.models import Purchase
    compra = Purchase.objects.select_for_update().select_related('provider').get(pk=compra.pk)   # una retención a la vez
    vigente = retencion_vigente(compra)
    if vigente is not None:
        raise ErrorRetencion(f'Esta compra ya tiene la retención {vigente.voucher_number_full} ({vigente.get_status_display()}).')
    # Fecha de la retención, fijada una vez: elige la vigencia del catálogo (hoy, como siempre: el catálogo se lee el día
    # de la emisión). La regla legal es el momento del pago o crédito en cuenta (Res. NAC-DGERCGC26-00000009, art. 8);
    # cómo obtener esa fecha es la duda D0-d (Fase B): por eso calcular() ya la recibe como parámetro.
    fecha = timezone.localdate()
    doc, detalle, total = calcular(datos, lineas, fecha)
    if huella_revisada is not SIN_REVISION and huella_revisada != huella(doc, detalle):
        raise RevisionDesactualizada(doc, detalle, total)
    proveedor = compra.provider
    receipt = receipt_para_emitir(company, TIPO_RETENCION, electronica=True)
    numero = receipt.reservar_numero()
    ret = Retencion(
        company=company, receipt=receipt, voucher_number=numero,
        voucher_number_full=f'{receipt.establishment_code}-{receipt.issuing_point_code}-{numero}',
        # La misma fecha para el catálogo, date_joined y la fecha de emisión (preparar() respeta una ya fijada): una
        # medianoche entre crear() y preparar() no fecha el documento un día y lo calcula con la vigencia del anterior.
        employee=usuario, environment_type=company.environment_type, date_joined=fecha, emission_date=fecha,
        purchase=compra, provider=proveedor, tipo_identificacion=tipo_identificacion(proveedor.ruc),
        identificacion=re.sub(r'\s', '', proveedor.ruc), razon_social=proveedor.name.strip(),
        tipo_sujeto='02' if len(proveedor.ruc.strip()) == 13 and proveedor.ruc.strip()[2] in '69' else '01',
        correo=(proveedor.email or '').strip() if '@' in (proveedor.email or '') else '',
        total_retenido=total, **{k: v for k, v in doc.items()})
    ret.save()
    for d in detalle:
        RetencionDetalle.objects.create(retencion=ret, impuesto=d['impuesto'], codigo=d['codigo'], concepto=d['concepto'][:300],
                                        base_imponible=d['base_imponible'], porcentaje=d['porcentaje'],
                                        valor_retenido=d['valor_retenido'], codigo_catalogo=d['codigo_obj'])
    return ret
