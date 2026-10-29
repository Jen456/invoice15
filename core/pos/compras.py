"""Compras completas (Etapa 2, datos de origen): validación, cálculo y registro en el servidor (espec-etapa2-compras §3.1).

- Una compra nueva guarda los datos del comprobante para el ATS, la tarifa, el IVA y el descuento de cada línea y los
  totales por base; su cuenta por pagar es el total con IVA. Lo hace solo crear_compra (version_datos=2).
- Las compras anteriores quedan marcadas como incompletas, sin recalcular (D8): sus importes se escriben a mano con
  completar_datos, que nunca cambia líneas, stock ni subtotal, y solo ajusta la cuenta por pagar con decisión explícita.
- Nada que decida el crédito tributario se elige de oficio (DC12): forma de pago, sustento y parte relacionada llegan
  del usuario o del documento.
- Importes en Decimal (HALF_UP a 0,01). Bloqueos con select_for_update(of=('self',)) y sin select_related, en el orden
  Purchase (antes la compra modificada) → DebtsPay. La auditoría recibe solo tipos JSON (para_auditoria).
"""
import copy
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Case, DecimalField, F, Model, Q, When
from django.utils import timezone

from core.pos import catalogos_sri as cat
from core.pos.choices import NOMBRE_TARIFA_IVA, PAYMENT_TYPE

CENTAVO = Decimal('0.01')
CERO = Decimal('0.00')
TOLERANCIA_BASES = Decimal('0.02')
TOLERANCIA_IVA = Decimal('0.05')
MAX_SUBTOTAL = Decimal('9999999.99')       # Purchase.subtotal y DebtsPay.debt (9 dígitos, 2 decimales)
MAX_CANTIDAD = 10_000_000
MAX_LINEAS = 500
MODOS_COMPROBANTE = ('si', 'liquidacion', 'despues')
BASES = ('base_0', 'base_gravada', 'base_5', 'base_no_objeto', 'base_exenta')
IMPORTES_EDITABLES = BASES + ('total_descuento', 'total_iva', 'total_ice', 'propina')
CAMPOS_CABECERA = ('tipo_comprobante', 'cod_sustento', 'estab', 'pto_emi', 'secuencial', 'autorizacion', 'fecha_emision',
                   'forma_pago', 'parte_relacionada', 'pago_loc_ext', 'tipo_doc_modificado', 'num_doc_modificado',
                   'aut_doc_modificado', 'fecha_doc_modificado', 'compra_modificada')
CAMPOS_NUMERACION = ('estab', 'pto_emi', 'secuencial', 'autorizacion', 'fecha_emision')
CAMPOS_DOC_MODIFICADO = ('tipo_doc_modificado', 'num_doc_modificado', 'aut_doc_modificado', 'fecha_doc_modificado')
TIPOS_DOC_MODIFICABLES = ('01', '02', '03')
CODIGOS_IVA_LIQUIDACION = ('4', '5', '0')   # tarifas que admite la liquidación que se emite (core.comprobantes.liquidaciones)
ORDEN_RESUMEN = ('4', '10', '3', '2', '8', '5', '0', '6', '7', '')
ETIQUETAS = {
    'tipo_comprobante': 'Tipo de comprobante', 'cod_sustento': 'Sustento tributario', 'estab': 'Establecimiento',
    'pto_emi': 'Punto de emisión', 'secuencial': 'Secuencial', 'autorizacion': 'Autorización',
    'fecha_emision': 'Fecha de emisión', 'forma_pago': 'Forma de pago (ATS)', 'parte_relacionada': 'Parte relacionada',
    'pago_loc_ext': 'Pago a residente o no residente', 'tipo_doc_modificado': 'Tipo del documento modificado',
    'num_doc_modificado': 'Número del documento modificado', 'aut_doc_modificado': 'Autorización del documento modificado',
    'fecha_doc_modificado': 'Fecha del documento modificado', 'compra_modificada': 'Compra que modifica',
    'base_0': 'Base 0 %', 'base_gravada': 'Base gravada', 'base_5': 'Base 5 %', 'base_no_objeto': 'Base no objeto de IVA',
    'base_exenta': 'Base exenta de IVA', 'total_descuento': 'Total descuento', 'total_iva': 'IVA', 'total_ice': 'ICE',
    'total_irbpnr': 'IRBPNR', 'propina': 'Propina', 'total': 'Total', 'fuera_plazo_ats': 'Fuera del plazo del ATS',
}
TEXTOS_FALTANTES = {
    'importes': 'Faltan los importes de la factura (bases, IVA y total)',
    'tipo_comprobante': 'Falta el tipo de comprobante',
    'cod_sustento': 'Falta el sustento tributario',
    'estab': 'Falta el establecimiento del comprobante',
    'pto_emi': 'Falta el punto de emisión del comprobante',
    'secuencial': 'Falta el secuencial del comprobante',
    'autorizacion': 'Falta la autorización del comprobante',
    'fecha_emision': 'Falta la fecha de emisión del comprobante',
    'forma_pago': 'Falta la forma de pago (ATS)',
    'parte_relacionada': 'Indica si el proveedor es parte relacionada',
    'pago_loc_ext': 'Indica si el pago es a residente o a no residente',
    'pago_exterior_pendiente': 'Los datos del pago al exterior se completan en la Etapa 4',
    'doc_modificado': 'Faltan datos del documento modificado (tipo, número, autorización y fecha)',
    'liquidacion_pendiente': 'Falta emitir la liquidación de compra y que el SRI la autorice',
    'liquidacion_descuadrada': 'La liquidación autorizada no coincide con los importes de la compra',
    'fuera_plazo_ats': 'Registrada más de un año después de su emisión: el ATS no la admite',
}


class ErrorCompra(Exception):
    """Mensaje para el usuario. `codigo` identifica una confirmación pendiente (confirmar_iva, confirmar_plazo_ats,
    confirmar_diferencia) o el caso de error."""

    def __init__(self, mensaje, codigo=''):
        super().__init__(mensaje)
        self.codigo = codigo


# ------------------------------------------------------------------ utilidades

def redondear(valor):
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def texto_importe(valor):
    return None if valor is None else f'{Decimal(valor):.2f}'


def dinero(valor):
    return f'${Decimal(valor):.2f}'


def para_auditoria(valor):
    """Valor apto para AuditLog.detail (JSONField sin encoder): importes → '0.00', fechas → ISO, registros → id."""
    if valor is None or isinstance(valor, (bool, int, str)):
        return valor
    if isinstance(valor, Decimal):
        return f'{valor:.2f}'
    if isinstance(valor, float):
        return f'{Decimal(str(valor)):.2f}'
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    if isinstance(valor, Model):
        return int(valor.pk) if valor.pk is not None else None
    if isinstance(valor, dict):
        return {str(k): para_auditoria(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set)):
        return [para_auditoria(v) for v in valor]
    return str(valor)


def _auditar(request, accion, company, usuario=None, **detalle):
    from core.tenancy.models import audit
    if request is None and usuario is not None:
        detalle.setdefault('usuario', usuario.pk)
    audit(request, accion, company, **{k: para_auditoria(v) for k, v in detalle.items()})


def _texto(valor):
    return '' if valor is None else str(valor).strip()


def _decimal(valor, etiqueta, *, obligatorio=False, minimo=CERO, defecto=None, decimales=2):
    texto = _texto(valor)
    if texto == '':
        if obligatorio:
            raise ErrorCompra(f'{etiqueta}: escribe un valor.')
        return defecto
    if isinstance(valor, Decimal):
        numero = valor
    else:
        if ',' in texto and '.' not in texto:
            texto = texto.replace(',', '.')
        try:
            numero = Decimal(texto)
        except InvalidOperation:
            raise ErrorCompra(f'{etiqueta}: escribe un valor numérico.')
    if not numero.is_finite():
        raise ErrorCompra(f'{etiqueta}: escribe un valor numérico.')
    if minimo is not None and numero < minimo:
        raise ErrorCompra(f'{etiqueta}: no puede ser negativo.' if minimo == 0 else f'{etiqueta}: debe ser mayor que {minimo}.')
    return numero.quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP)


def _fecha(valor, etiqueta):
    if valor in (None, ''):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(_texto(valor)[:10])
    except ValueError:
        raise ErrorCompra(f'{etiqueta}: escribe una fecha válida (AAAA-MM-DD).')


def _booleano(valor):
    if valor is None or isinstance(valor, bool):
        return valor
    texto = _texto(valor).lower()
    if texto in ('si', 'sí', 'true', '1', 'on', 'yes'):
        return True
    if texto in ('no', 'false', '0', 'off'):
        return False
    return None


def _confirmado(valor):
    return _booleano(valor) is True


def _id(valor):
    if valor in (None, ''):
        return None
    if isinstance(valor, Model):
        return valor.pk
    try:
        return int(_texto(valor))
    except ValueError:
        raise ErrorCompra('Identificador no válido.')


def _codigo(valor, catalogo, mensaje):
    texto = _texto(valor)
    if texto and texto not in dict(catalogo):
        raise ErrorCompra(mensaje)
    return texto


def _nombre_tipo(tipo):
    return cat.nombre(cat.TIPOS_COMPROBANTE_COMPRA, tipo)


def _numero(estab, pto_emi, secuencial):
    return f'{estab}-{pto_emi}-{secuencial}' if secuencial else ''


# ------------------------------------------------------------------ líneas

def calcular_linea(linea, fecha_emision, tipo_comprobante=''):
    """Valida y calcula una línea: {tipo: 'producto'|'gasto', product, type_expense, descripcion, codigo_proveedor, cant,
    price, descuento (dólares), codigo_porcentaje, tarifa (solo código 8)}. Devuelve la línea normalizada con subtotal,
    total (base = subtotal − descuento) y total_iva (base × tarifa, HALF_UP), más sus advertencias."""
    from core.pos.models import Product, TypeExpense
    producto_id, tipo_gasto_id = _id(linea.get('product')), _id(linea.get('type_expense'))
    tipo = _texto(linea.get('tipo')) or ('producto' if producto_id else 'gasto')
    if tipo not in ('producto', 'gasto'):
        raise ErrorCompra('Tipo de línea no válido.')
    producto = tipo_gasto = None
    descripcion = ' '.join(_texto(linea.get('descripcion')).split())
    if tipo == 'producto':
        producto = Product.objects.filter(pk=producto_id).first() if producto_id else None   # solo de la empresa activa
        if producto is None:
            raise ErrorCompra('Elige un producto de la empresa.')
    else:
        if not descripcion:
            raise ErrorCompra('Escribe la descripción de la línea de gasto.')
    if len(descripcion) > 300:
        raise ErrorCompra('La descripción admite hasta 300 caracteres.')
    if tipo_gasto_id:
        tipo_gasto = TypeExpense.objects.filter(pk=tipo_gasto_id).first()
        if tipo_gasto is None:
            raise ErrorCompra('El tipo de gasto no existe.')
    try:
        cant = int(_texto(linea.get('cant')))
    except ValueError:
        cant = 0
    if not 1 <= cant <= MAX_CANTIDAD:
        raise ErrorCompra('La cantidad debe ser un número entero entre 1 y 10.000.000.')
    precio = _decimal(linea.get('price'), 'Precio', obligatorio=True)
    descuento = _decimal(linea.get('descuento'), 'Descuento', defecto=CERO)
    codigo = _texto(linea.get('codigo_porcentaje'))
    if codigo not in cat.CODIGOS_IVA_COMPRA:
        raise ErrorCompra('Elige la tarifa de IVA de la línea.')
    advertencias = []
    if codigo in cat.CODIGOS_CON_TARIFA_VARIABLE:
        tarifa = _decimal(linea.get('tarifa'), 'Tarifa del IVA diferenciado')
        if tarifa is None or not CERO < tarifa < 100:
            raise ErrorCompra('Escribe la tarifa del IVA diferenciado que figura en la factura.')
    else:
        tarifa = redondear(cat.TARIFA_POR_CODIGO[codigo])
    if fecha_emision is not None:
        if codigo == '4' and fecha_emision < cat.INICIO_IVA_15:
            raise ErrorCompra('La tarifa del 15 % rige desde el 01/04/2024: este comprobante es anterior.')
        if codigo == '2' and fecha_emision >= cat.INICIO_IVA_15:
            raise ErrorCompra('La tarifa del 12 % ya no rige para comprobantes desde el 01/04/2024.')
        if codigo == '5' and fecha_emision < cat.INICIO_IVA_15:
            advertencias.append(('tarifa_5_anterior', 'La tarifa del 5 % se aplica desde el 01/04/2024: revisa la tarifa de '
                                                      'este comprobante, que es anterior.'))
    elif codigo == '2':
        advertencias.append(('tarifa_12_sin_fecha', 'La tarifa del 12 % solo rige para comprobantes anteriores al 01/04/2024: '
                                                    'se revisará al completar la fecha de emisión.'))
    if tipo_comprobante in cat.TIPOS_SIN_IVA_DISCRIMINADO and codigo not in cat.CODIGOS_IVA_NOTA_VENTA:
        raise ErrorCompra('Una nota de venta no discrimina IVA: registra sus valores con tarifa 0 %.')
    subtotal = redondear(precio * cant)
    if subtotal > MAX_SUBTOTAL:
        raise ErrorCompra('El subtotal de la línea supera el máximo admitido ($9999999.99).')
    if descuento > subtotal:
        raise ErrorCompra('El descuento no puede ser mayor que el subtotal de la línea.')
    total = subtotal - descuento
    total_iva = redondear(total * tarifa / 100)
    return {'tipo': tipo, 'product': producto, 'type_expense': tipo_gasto, 'descripcion': descripcion,
            'codigo_proveedor': _texto(linea.get('codigo_proveedor'))[:25], 'cant': cant, 'price': precio,
            'descuento': descuento, 'codigo_porcentaje': codigo, 'tarifa': tarifa, 'subtotal': subtotal, 'total': total,
            'total_iva': total_iva, 'total_ice': CERO, 'advertencias': advertencias}


def _valor_linea(linea, campo):
    valor = linea.get(campo) if isinstance(linea, dict) else getattr(linea, campo)
    return None if valor is None else Decimal(valor)


def resumen_por_tarifa(lineas):
    """[{codigo, nombre, tarifa, base, valor}] por (código, tarifa), en el orden 15 %, 12 %, diferenciado, 5 %, 0 %, no
    objeto, exento. Suma la base y el IVA guardado (o calculado) de cada línea; no usa PORCENTAJE_IVA (no tiene el 8).
    Las líneas anteriores a la Etapa 2 (sin tarifa) van aparte, con IVA desconocido (None)."""
    grupos = {}
    for linea in lineas:
        codigo = (linea.get('codigo_porcentaje') if isinstance(linea, dict) else linea.codigo_porcentaje) or ''
        tarifa = _valor_linea(linea, 'tarifa')
        base = _valor_linea(linea, 'total')
        if base is None:   # línea antigua: subtotal − descuento
            base = (_valor_linea(linea, 'subtotal') or CERO) - (_valor_linea(linea, 'total_dscto') or CERO)
        iva = _valor_linea(linea, 'total_iva')
        clave = (codigo, tarifa)
        suma_base, suma_iva = grupos.get(clave, (CERO, CERO if codigo else None))
        grupos[clave] = (suma_base + base, None if suma_iva is None or iva is None else suma_iva + iva)
    orden = sorted(grupos, key=lambda c: (ORDEN_RESUMEN.index(c[0]) if c[0] in ORDEN_RESUMEN else 50, -(c[1] or 0)))
    from core.pos.models import nombre_tarifa_compra
    return [{'codigo': c, 'nombre': nombre_tarifa_compra(c, t) if c else 'Sin tarifa registrada', 'tarifa': t,
             'base': redondear(grupos[(c, t)][0]),
             'valor': None if grupos[(c, t)][1] is None else redondear(grupos[(c, t)][1])} for c, t in orden]


# ------------------------------------------------------------------ cabecera

def _autorizacion(texto, tipo, etiqueta='La autorización'):
    digitos = re.sub(r'\s', '', _texto(texto))
    if not digitos:
        return ''
    if not digitos.isdigit():
        raise ErrorCompra(f'{etiqueta} solo admite dígitos.')
    if tipo in ('01', '04', '05'):
        if len(digitos) not in (10, 37, 49):
            raise ErrorCompra(f'{etiqueta} tiene 49 dígitos (clave de acceso), o 10 o 37 en comprobantes antiguos.')
    elif not 3 <= len(digitos) <= 49:
        raise ErrorCompra(f'{etiqueta} tiene de 3 a 49 dígitos.')
    return digitos


def _coherencia_clave(digitos, tipo, proveedor, estab, pto_emi, secuencial, fecha, etiqueta='La autorización'):
    """Con 49 dígitos, la clave de acceso debe corresponder al comprobante (tipo, RUC, número y fecha) y ser de producción."""
    from core.importacion.clave_acceso import ClaveInvalida, analizar
    if len(digitos) != 49:
        return
    try:
        clave = analizar(digitos)
    except ClaveInvalida as e:
        raise ErrorCompra(f'{etiqueta}: {e}')
    if clave.ambiente == 1:
        raise ErrorCompra(f'{etiqueta} es de un comprobante de PRUEBAS: no sustenta.')
    diferencias = []
    if tipo and clave.cod_doc != tipo:
        diferencias.append('el tipo de comprobante')
    if proveedor is not None and proveedor.tipo_identificacion == '04' and clave.ruc != re.sub(r'\s', '', proveedor.ruc):
        diferencias.append('el RUC del proveedor')
    if estab and clave.estab != estab:
        diferencias.append('el establecimiento')
    if pto_emi and clave.pto_emi != pto_emi:
        diferencias.append('el punto de emisión')
    if secuencial and clave.secuencial != secuencial:
        diferencias.append('el secuencial')
    if fecha and clave.fecha_emision != fecha:
        diferencias.append('la fecha de emisión')
    if diferencias:
        raise ErrorCompra(f'{etiqueta} no corresponde a este comprobante: no coincide {", ".join(diferencias)}.')


def _normalizar_cabecera(valores, proveedor):
    """Formatos de cada dato que llegó (vacío = sin dato). No exige nada: las reglas obligatorias van aparte."""
    n = {}
    n['tipo_comprobante'] = _codigo(valores.get('tipo_comprobante'), cat.TIPOS_COMPROBANTE_COMPRA, 'Tipo de comprobante no válido.')
    n['cod_sustento'] = _codigo(valores.get('cod_sustento'), cat.SUSTENTOS, 'Sustento tributario no válido.')
    for campo, nombre in (('estab', 'establecimiento'), ('pto_emi', 'punto de emisión')):
        texto = _texto(valores.get(campo))
        if texto and not re.fullmatch(r'(?!000)\d{3}', texto):
            raise ErrorCompra(f'El {nombre} del comprobante tiene tres dígitos, por ejemplo 001 (000 no es válido).')
        n[campo] = texto
    secuencial = _texto(valores.get('secuencial'))
    if secuencial:
        if not re.fullmatch(r'\d{1,9}', secuencial) or int(secuencial) == 0:
            raise ErrorCompra('El secuencial del comprobante tiene de 1 a 9 dígitos y es mayor que cero.')
        secuencial = secuencial.zfill(9)
    n['secuencial'] = secuencial
    n['autorizacion'] = _autorizacion(valores.get('autorizacion'), n['tipo_comprobante'])
    n['fecha_emision'] = _fecha(valores.get('fecha_emision'), 'Fecha de emisión')
    n['forma_pago'] = _codigo(valores.get('forma_pago'), cat.FORMAS_PAGO, 'Forma de pago no válida.')
    n['parte_relacionada'] = _booleano(valores.get('parte_relacionada'))
    n['pago_loc_ext'] = _codigo(valores.get('pago_loc_ext'), cat.PAGO_LOC_EXT, 'Pago a residente o no residente: valor no válido.')
    tipo_mod = _texto(valores.get('tipo_doc_modificado'))
    if tipo_mod and tipo_mod not in TIPOS_DOC_MODIFICABLES:
        raise ErrorCompra('El documento modificado debe ser una factura, una nota de venta o una liquidación de compra.')
    n['tipo_doc_modificado'] = tipo_mod
    num_mod = re.sub(r'[\s-]', '', _texto(valores.get('num_doc_modificado')))
    if num_mod and (not re.fullmatch(r'\d{15}', num_mod) or num_mod[:3] == '000' or num_mod[3:6] == '000' or int(num_mod[6:]) == 0):
        raise ErrorCompra('Escribe el número del documento modificado con establecimiento, punto y secuencial: 001-001-000000123.')
    n['num_doc_modificado'] = num_mod
    n['aut_doc_modificado'] = _autorizacion(valores.get('aut_doc_modificado'), tipo_mod or '01',
                                            'La autorización del documento modificado')
    n['fecha_doc_modificado'] = _fecha(valores.get('fecha_doc_modificado'), 'Fecha del documento modificado')
    n['compra_modificada'] = _id(valores.get('compra_modificada'))
    return n


def _validar_cabecera(n, proveedor, *, modo, origen, parcial, date_joined, compra_id=None):
    """Reglas de la cabecera sobre los datos normalizados `n` (los corrige en el sitio). Devuelve (advertencias,
    confirmaciones). `parcial`: solo se valida lo que llegó y los cruces cuando están los dos datos (modo «despues» y
    completar datos)."""
    from core.pos.models import Purchase
    advertencias, confirmaciones = [], []
    hoy = timezone.localdate()
    tipo = n['tipo_comprobante']
    if modo == 'liquidacion':
        tipo = n['tipo_comprobante'] = '03'
        if any(n[c] for c in ('estab', 'pto_emi', 'secuencial', 'autorizacion')):
            raise ErrorCompra('En una liquidación de compra la numeración y la autorización las da la liquidación que emitirás: '
                              'deja vacíos el número y la autorización.')
        n['fecha_emision'] = None          # la fecha de emisión es la de la liquidación
        if proveedor.tipo_identificacion == '04':
            advertencias.append(('liquidacion_con_ruc', 'El catálogo ATS solo admite liquidaciones con cédula o pasaporte; con '
                                                        'RUC, la liquidación solo procede si está suspendido.'))
    elif tipo == '03':
        raise ErrorCompra('La liquidación de compra (03) se registra con el modo «Liquidación».')
    if not parcial:
        if modo == 'si' and not tipo:
            raise ErrorCompra('Elige el tipo de comprobante.')
        if not n['cod_sustento']:
            raise ErrorCompra('Elige el sustento tributario.')
    if tipo and n['cod_sustento'] and not cat.sustento_admite(n['cod_sustento'], tipo):
        raise ErrorCompra(f'El sustento {n["cod_sustento"]} no admite el tipo de comprobante «{_nombre_tipo(tipo)}».')
    if tipo and tipo != '03' and proveedor.tipo_id_ats and not cat.tipo_id_admite(tipo, proveedor.tipo_id_ats):
        if tipo == '01':
            raise ErrorCompra('Una factura solo se registra con un proveedor con RUC.')
        raise ErrorCompra(f'El tipo de comprobante «{_nombre_tipo(tipo)}» no admite un proveedor con '
                          f'{cat.nombre(cat.TIPO_ID_COMPRA, proveedor.tipo_id_ats).lower()}.')
    # numeración y fecha (no aplican a la liquidación)
    if tipo != '03':
        if not parcial:
            for campo, mensaje in (('estab', 'Escribe el establecimiento del comprobante (tres dígitos).'),
                                   ('pto_emi', 'Escribe el punto de emisión del comprobante (tres dígitos).'),
                                   ('secuencial', 'Escribe el secuencial del comprobante.'),
                                   ('autorizacion', 'Escribe la autorización del comprobante.')):
                if not n[campo]:
                    raise ErrorCompra(mensaje)
            if n['fecha_emision'] is None:
                raise ErrorCompra('Escribe la fecha de emisión del comprobante.')
        if n['autorizacion'] and tipo:
            n['autorizacion'] = _autorizacion(n['autorizacion'], tipo)
            _coherencia_clave(n['autorizacion'], tipo, proveedor, n['estab'], n['pto_emi'], n['secuencial'], n['fecha_emision'])
    fecha = n['fecha_emision']
    if fecha is not None:
        if fecha > hoy:
            raise ErrorCompra('La fecha de emisión del comprobante no puede ser futura.')
        if date_joined is not None and fecha > date_joined:
            raise ErrorCompra('La fecha de emisión del comprobante no puede ser posterior a la fecha de registro.')
        if date_joined is not None and (date_joined - fecha).days > cat.PLAZO_ATS_DIAS:
            confirmaciones.append('confirmar_plazo_ats')
    # forma de pago, parte relacionada y pago local o al exterior
    if tipo in cat.TIPOS_SIN_FORMA_PAGO:
        n['forma_pago'] = ''
    elif not parcial and not n['forma_pago'] and origen != 'importacion':
        raise ErrorCompra('Elige la forma de pago del comprobante (ATS).')
    if not parcial and n['parte_relacionada'] is None:
        raise ErrorCompra('Indica si el proveedor es parte relacionada.')
    if not parcial and not n['pago_loc_ext']:
        raise ErrorCompra('Indica si el pago es a residente o a no residente.')
    # documento modificado (notas de crédito y débito del proveedor)
    if tipo in cat.TIPOS_CON_DOC_MODIFICADO:
        if not parcial:
            requeridos = CAMPOS_DOC_MODIFICADO if origen != 'importacion' else CAMPOS_DOC_MODIFICADO[:2] + CAMPOS_DOC_MODIFICADO[3:]
            if any(not n[c] for c in requeridos):
                raise ErrorCompra('Escribe los datos del documento modificado: tipo, número, autorización y fecha.')
        if n['fecha_doc_modificado'] and fecha and n['fecha_doc_modificado'] > fecha:
            raise ErrorCompra('La fecha del documento modificado no puede ser posterior a la del comprobante.')
        if n['aut_doc_modificado'] and n['tipo_doc_modificado']:
            numero = n['num_doc_modificado']
            _coherencia_clave(n['aut_doc_modificado'], n['tipo_doc_modificado'], proveedor, numero[:3], numero[3:6], numero[6:],
                              n['fecha_doc_modificado'], 'La autorización del documento modificado')
        if n['compra_modificada']:
            modificada = Purchase.objects.filter(pk=n['compra_modificada']).first()
            if modificada is None or modificada.pk == compra_id:
                raise ErrorCompra('La compra que modifica no existe.')
            if modificada.provider_id != proveedor.pk:
                raise ErrorCompra('La compra que modifica es de otro proveedor.')
            if modificada.tipo_comprobante in cat.TIPOS_CON_DOC_MODIFICADO:
                raise ErrorCompra('Una nota de crédito o débito no modifica otra nota: elige la factura.')
            if modificada.version_datos == 2 and n['tipo_doc_modificado'] and modificada.tipo_comprobante != n['tipo_doc_modificado']:
                raise ErrorCompra('La compra que modifica es de otro tipo de comprobante que el documento modificado.')
    else:
        for c in CAMPOS_DOC_MODIFICADO:
            n[c] = None if c == 'fecha_doc_modificado' else ''
        n['compra_modificada'] = None
    return advertencias, confirmaciones


# ------------------------------------------------------------------ cálculo y registro

@dataclass
class _Plan:
    proveedor: object
    campos: dict
    lineas: list
    totales: dict
    advertencias: list = field(default_factory=list)
    confirmaciones: list = field(default_factory=list)
    pendientes: list = field(default_factory=list)
    iva_calculado: Decimal = CERO
    compra_modificada_id: int | None = None


def _texto_confirmacion(codigo, plan):
    if codigo == 'confirmar_iva':
        diferencia = abs(plan.totales['total_iva'] - plan.iva_calculado)
        return f'El IVA de la factura difiere del calculado por líneas en {dinero(diferencia)}: confírmalo.'
    if codigo == 'confirmar_plazo_ats':
        return 'La factura tiene más de un año: el ATS no la admitirá en este período. Confírmalo para registrarla.'
    return 'Confirma la operación.'


def _lineas_importadas(lineas):
    """Líneas ya calculadas desde el XML (DC4): se validan producto, tipo de gasto y descripción; los importes mandan."""
    from core.pos.models import Product, TypeExpense
    resultado = []
    for i, linea in enumerate(lineas, start=1):
        producto_id, tipo_gasto_id = _id(linea.get('product')), _id(linea.get('type_expense'))
        producto = Product.objects.filter(pk=producto_id).first() if producto_id else None
        if producto_id and producto is None:
            raise ErrorCompra(f'Línea {i}: elige un producto de la empresa.')
        tipo_gasto = TypeExpense.objects.filter(pk=tipo_gasto_id).first() if tipo_gasto_id else None
        if tipo_gasto_id and tipo_gasto is None:
            raise ErrorCompra(f'Línea {i}: el tipo de gasto no existe.')
        descripcion = ' '.join(_texto(linea.get('descripcion')).split())[:300]
        if producto is None and not descripcion:
            raise ErrorCompra(f'Línea {i}: escribe la descripción de la línea de gasto.')
        cant = int(linea.get('cant') or 1)
        if not 1 <= cant <= MAX_CANTIDAD:
            raise ErrorCompra(f'Línea {i}: la cantidad debe ser un número entero entre 1 y 10.000.000.')
        codigo = _texto(linea.get('codigo_porcentaje'))
        tarifa = linea.get('tarifa')
        resultado.append({
            'tipo': 'producto' if producto else 'gasto', 'product': producto, 'type_expense': tipo_gasto, 'descripcion': descripcion,
            'codigo_proveedor': _texto(linea.get('codigo_proveedor'))[:25], 'cant': cant,
            'price': redondear(linea.get('price') or 0), 'descuento': redondear(linea.get('total_dscto') or linea.get('descuento') or 0),
            'codigo_porcentaje': codigo, 'tarifa': None if tarifa in (None, '') else redondear(tarifa),
            'subtotal': redondear(linea.get('subtotal') or 0), 'total': redondear(linea.get('total') or 0),
            'total_iva': redondear(linea.get('total_iva') or 0), 'total_ice': redondear(linea.get('total_ice') or 0),
            'advertencias': []})
    return resultado


def _validar_lineas_liquidacion(lineas, importes):
    """La liquidación que se emite sobre la compra (core.comprobantes.liquidaciones.calcular) toma cantidad × precio, sin
    descuento, con IVA del 15 %, 5 % o 0 % y sin ICE ni propina: la compra debe poder liquidarse con sus mismos importes.
    `lineas`: [(codigo_porcentaje, descuento)]."""
    for i, (codigo, descuento) in enumerate(lineas, start=1):
        if codigo not in CODIGOS_IVA_LIQUIDACION:
            raise ErrorCompra(f'Línea {i}: la liquidación de compra solo admite IVA del 15 %, del 5 % o del 0 %.')
        if descuento:
            raise ErrorCompra(f'Línea {i}: la liquidación de compra no admite descuentos: registra el precio ya rebajado.')
    if importes.get('total_ice') or importes.get('propina'):
        raise ErrorCompra('La liquidación de compra que emite el sistema no incluye ICE ni propina: déjalos en 0.')


def _preparar(company, datos, lineas, *, origen='manual', importes=None):
    """Valida cabecera y líneas y calcula los totales, sin guardar."""
    from core.pos.models import Provider
    datos = datos or {}
    proveedor_id = _id(datos.get('provider'))
    proveedor = Provider.objects.filter(pk=proveedor_id).first() if proveedor_id else None
    if proveedor is None:
        raise ErrorCompra('Elige el proveedor.')
    modo = _texto(datos.get('modo_comprobante')) or 'si'
    if modo not in MODOS_COMPROBANTE:
        raise ErrorCompra('Modo del comprobante no válido.')
    if modo in ('si', 'liquidacion') and not proveedor.tipo_identificacion:
        raise ErrorCompra('Completa el tipo de identificación del proveedor antes de registrar el comprobante.')
    hoy = timezone.localdate()
    date_joined = _fecha(datos.get('date_joined'), 'Fecha de registro')
    if date_joined is None:
        raise ErrorCompra('Escribe la fecha de registro.')
    if date_joined > hoy:
        raise ErrorCompra('La fecha de registro no puede ser futura.')
    n = _normalizar_cabecera(datos, proveedor)
    advertencias, confirmaciones = _validar_cabecera(n, proveedor, modo=modo, origen=origen, parcial=(modo == 'despues'),
                                                     date_joined=date_joined)
    tipo = n['tipo_comprobante']
    payment_type = _texto(datos.get('payment_type')) or PAYMENT_TYPE[0][0]
    if payment_type not in dict(PAYMENT_TYPE):
        raise ErrorCompra('Tipo de pago no válido.')
    if tipo == '04':
        payment_type = 'efectivo'      # la nota de crédito se aplica a la compra que modifica: sin cuenta por pagar propia
    end_credit = _fecha(datos.get('end_credit'), 'Fecha de plazo del crédito')
    if payment_type == 'credito':
        if end_credit is None:
            raise ErrorCompra('Escribe la fecha de plazo del crédito.')
        if end_credit < date_joined:
            raise ErrorCompra('La fecha de plazo del crédito no puede ser anterior a la fecha de registro.')
    else:
        end_credit = date_joined
    # líneas
    if importes is not None and importes.get('lineas') is not None:
        calculadas = _lineas_importadas(importes['lineas'])
    else:
        lineas = list(lineas or [])
        if not lineas:
            raise ErrorCompra('Agrega al menos una línea a la compra.')
        if len(lineas) > MAX_LINEAS:
            raise ErrorCompra(f'Una compra admite hasta {MAX_LINEAS} líneas.')
        fecha_tarifas = n['fecha_emision'] or (date_joined if modo == 'liquidacion' else None)
        calculadas = []
        for i, linea in enumerate(lineas, start=1):
            try:
                calculadas.append(calcular_linea(linea, fecha_tarifas, tipo))
            except ErrorCompra as e:
                raise ErrorCompra(f'Línea {i}: {e}')
    if not calculadas:
        raise ErrorCompra('Agrega al menos una línea a la compra.')
    if tipo in cat.TIPOS_CON_DOC_MODIFICADO and any(l['product'] is not None for l in calculadas):
        raise ErrorCompra('Las notas de crédito y débito del proveedor se registran con líneas de gasto (sin producto): '
                          'no mueven stock en esta etapa.')
    for linea in calculadas:
        advertencias.extend(a for a in linea['advertencias'] if a not in advertencias)
    # totales
    totales = {b: CERO for b in BASES}
    for linea in calculadas:
        campo = cat.BASE_POR_CODIGO.get(linea['codigo_porcentaje'])
        if campo is None:
            raise ErrorCompra('Una línea tiene una tarifa de IVA desconocida.')
        totales[campo] += linea['total']
    iva_calculado = redondear(sum((l['total_iva'] for l in calculadas), CERO))
    if importes is not None:
        for campo in BASES + ('total_descuento', 'total_iva', 'total_ice', 'total_irbpnr', 'propina', 'total'):
            totales[campo] = redondear(importes.get(campo) or 0)
        subtotal = redondear(importes.get('subtotal') if importes.get('subtotal') is not None else sum(totales[b] for b in BASES))
    else:
        totales['total_descuento'] = redondear(sum((l['descuento'] for l in calculadas), CERO))
        totales['total_ice'] = _decimal(datos.get('total_ice'), 'ICE', defecto=CERO)
        totales['propina'] = _decimal(datos.get('propina'), 'Propina', defecto=CERO)
        totales['total_irbpnr'] = CERO
        iva_factura = _decimal(datos.get('iva_factura'), 'IVA de la factura')
        if modo == 'liquidacion' and iva_factura is not None and iva_factura != iva_calculado:
            raise ErrorCompra('En una liquidación de compra el IVA es el de sus líneas: deja vacío el IVA de la factura.')
        if iva_factura is not None and tipo in cat.TIPOS_SIN_IVA_DISCRIMINADO and iva_factura != 0:
            raise ErrorCompra('Una nota de venta no discrimina IVA: el IVA de la factura es 0.')
        totales['total_iva'] = iva_factura if iva_factura is not None else iva_calculado
        if iva_factura is not None and abs(iva_factura - iva_calculado) > TOLERANCIA_IVA:
            confirmaciones.append('confirmar_iva')
        subtotal = redondear(sum(totales[b] for b in BASES))
        totales['total'] = redondear(subtotal + totales['total_ice'] + totales['total_iva'] + totales['total_irbpnr']
                                     + totales['propina'])
    for b in BASES:
        totales[b] = redondear(totales[b])
    if modo == 'liquidacion':
        _validar_lineas_liquidacion([(l['codigo_porcentaje'], l['descuento']) for l in calculadas], totales)
    if totales['total'] <= 0:
        raise ErrorCompra('La compra debe tener un total mayor que cero.')
    if subtotal > MAX_SUBTOTAL or (payment_type == 'credito' and totales['total'] > MAX_SUBTOTAL):
        raise ErrorCompra('El total de la compra supera el máximo admitido ($9999999.99).')
    if totales['total'] > cat.UMBRAL_BANCARIZACION and n['forma_pago'] == '01':
        advertencias.append(('bancarizacion', 'Un pago de más de USD 1.000 sin el sistema financiero no da crédito tributario '
                                              'de IVA ni es deducible.'))
    confirmados = {c for c in ('confirmar_iva', 'confirmar_plazo_ats') if _confirmado(datos.get(c))}
    fuera_plazo = 'confirmar_plazo_ats' in confirmaciones
    campos = dict(n, provider=proveedor, payment_type=payment_type, date_joined=date_joined, end_credit=end_credit,
                  subtotal=subtotal, number=_numero(n['estab'], n['pto_emi'], n['secuencial']), fuera_plazo_ats=fuera_plazo,
                  **totales)
    compra_modificada_id = campos.pop('compra_modificada')
    campos['compra_modificada_id'] = compra_modificada_id
    return _Plan(proveedor=proveedor, campos=campos, lineas=calculadas, totales=totales, advertencias=advertencias,
                 confirmaciones=confirmaciones, pendientes=[c for c in confirmaciones if c not in confirmados],
                 iva_calculado=iva_calculado, compra_modificada_id=compra_modificada_id)


def calcular(company, datos, lineas):
    """Valida y calcula sin guardar: resumen para la pantalla con los importes como texto."""
    from core.pos.models import Purchase, nombre_tarifa_compra
    plan = _preparar(company, datos, lineas)
    borrador = Purchase(company=company, version_datos=2, **plan.campos)
    t = plan.totales
    return {
        'lineas': [{'tipo': l['tipo'], 'product': l['product'].pk if l['product'] else None,
                    'type_expense': l['type_expense'].pk if l['type_expense'] else None, 'descripcion': l['descripcion'],
                    'codigo_proveedor': l['codigo_proveedor'], 'cant': l['cant'], 'price': texto_importe(l['price']),
                    'descuento': texto_importe(l['descuento']), 'codigo_porcentaje': l['codigo_porcentaje'],
                    'tarifa': texto_importe(l['tarifa']), 'nombre_tarifa': nombre_tarifa_compra(l['codigo_porcentaje'], l['tarifa']),
                    'subtotal': texto_importe(l['subtotal']), 'total': texto_importe(l['total']),
                    'total_iva': texto_importe(l['total_iva'])} for l in plan.lineas],
        'por_tarifa': [{**g, 'tarifa': texto_importe(g['tarifa']), 'base': texto_importe(g['base']),
                        'valor': texto_importe(g['valor'])} for g in resumen_por_tarifa(plan.lineas)],
        **{campo: texto_importe(t[campo]) for campo in BASES + ('total_descuento', 'total_iva', 'total_ice', 'propina', 'total')},
        'total_iva_calculado': texto_importe(plan.iva_calculado),
        'subtotal': texto_importe(plan.campos['subtotal']),
        'advertencias': [{'codigo': c, 'texto': x} for c, x in plan.advertencias],
        'faltantes': [{'codigo': c, 'texto': x} for c, x in faltantes(borrador)],
        'confirmaciones': plan.confirmaciones,
    }


def _comprobante_registrado(proveedor_id, tipo, estab, pto_emi, secuencial, excluir=None):
    from core.pos.models import Purchase
    if not secuencial:
        return None
    consulta = Purchase.objects.filter(provider_id=proveedor_id, tipo_comprobante=tipo, estab=estab, pto_emi=pto_emi,
                                       secuencial=secuencial)
    if excluir:
        consulta = consulta.exclude(pk=excluir)
    return consulta.order_by('pk').first()


def _error_duplicado(existente, proveedor):
    return ErrorCompra(f'Ya registraste {_nombre_tipo(existente.tipo_comprobante).lower()} {existente.numero_comprobante} de '
                       f'{proveedor.name} (compra #{existente.pk}).', codigo='duplicado')


def crear_compra(company, usuario, datos, lineas, *, origen='manual', importes=None):
    """Registra la compra (version_datos=2), sus líneas, el stock de las líneas con producto inventariado y, a crédito, su
    cuenta por pagar sobre el total con IVA (base 'total'). `importes` (solo desde XML) sustituye el cálculo (DC4)."""
    from core.pos import cuentas_por_pagar
    from core.pos.models import DebtsPay, Product, Purchase, PurchaseDetail
    from core.suscripciones.senales import LimitePlanGratuito
    plan = _preparar(company, datos, lineas, origen=origen, importes=importes)
    if plan.pendientes:
        codigo = plan.pendientes[0]
        raise ErrorCompra(_texto_confirmacion(codigo, plan), codigo=codigo)
    c = plan.campos
    with transaction.atomic():
        if plan.compra_modificada_id:
            # Purchase → DebtsPay: un borrado simultáneo de la compra modificada espera y luego ve el ajuste.
            if not Purchase.objects.select_for_update(of=('self',)).filter(pk=plan.compra_modificada_id).exists():
                raise ErrorCompra('La compra que modifica ya no existe.')
        existente = _comprobante_registrado(plan.proveedor.pk, c['tipo_comprobante'], c['estab'], c['pto_emi'], c['secuencial'])
        if existente is not None:
            raise _error_duplicado(existente, plan.proveedor)
        compra = Purchase(company=company, version_datos=2, origen=origen, **c)
        try:
            with transaction.atomic():
                compra.save()
        except IntegrityError:
            existente = _comprobante_registrado(plan.proveedor.pk, c['tipo_comprobante'], c['estab'], c['pto_emi'], c['secuencial'])
            if existente is not None:
                raise _error_duplicado(existente, plan.proveedor)
            raise
        except LimitePlanGratuito as e:
            raise ErrorCompra(str(e), codigo='limite_plan')
        PurchaseDetail.objects.bulk_create([PurchaseDetail(
            company=company, purchase=compra, product=l['product'], type_expense=l['type_expense'], descripcion=l['descripcion'],
            codigo_proveedor=l['codigo_proveedor'], cant=l['cant'], price=l['price'], subtotal=l['subtotal'],
            total_dscto=l['descuento'], total=l['total'], total_iva=l['total_iva'], total_ice=l['total_ice'],
            codigo_porcentaje=l['codigo_porcentaje'], tarifa=l['tarifa']) for l in plan.lineas])
        stock = {}
        for l in plan.lineas:
            if l['product'] is not None and l['product'].inventoried:
                stock[l['product'].pk] = stock.get(l['product'].pk, 0) + l['cant']
        for producto_id in sorted(stock):
            Product.objects.filter(pk=producto_id).update(stock=F('stock') + stock[producto_id])
        if compra.payment_type == 'credito':
            DebtsPay(company=company, purchase=compra, debt=compra.total, saldo=compra.total, base_calculo='total',
                     date_joined=compra.date_joined, end_date=compra.end_credit, state=compra.total > 0).save()
        if compra.tipo_comprobante == '04' and plan.compra_modificada_id:
            cuentas_por_pagar.recalcular_de_compra(plan.compra_modificada_id, company.pk)
        if not actualizar_marca(compra):
            _marcar_completada(compra, usuario)
    compra.advertencias = plan.advertencias
    return compra


# ------------------------------------------------------------------ datos incompletos

def faltantes(compra):
    """[(código, texto)] de lo que le falta a la compra para el ATS, en el orden de la especificación (§3.1)."""
    from core.comprobantes import liquidaciones
    from core.pos.emision import AUTORIZADOS
    faltan = []

    def falta(codigo, texto=None):
        faltan.append((codigo, texto or TEXTOS_FALTANTES[codigo]))

    tipo = compra.tipo_comprobante
    proveedor = compra.provider
    if compra.total is None:
        falta('importes')
    if not tipo:
        falta('tipo_comprobante')
    if not compra.cod_sustento:
        falta('cod_sustento')
    if tipo and compra.cod_sustento and not cat.sustento_admite(compra.cod_sustento, tipo):
        falta('sustento_no_admitido', f'El sustento {compra.cod_sustento} no admite el tipo de comprobante «{_nombre_tipo(tipo)}»')
    del_proveedor = proveedor.faltantes_ats()
    if del_proveedor:
        falta('proveedor_incompleto', 'Faltan datos del proveedor: ' + '; '.join(t for _, t in del_proveedor).lower())
    if tipo and proveedor.tipo_id_ats and not cat.tipo_id_admite(tipo, proveedor.tipo_id_ats):
        falta('tipo_id_no_admitido', f'«{_nombre_tipo(tipo)}» no admite un proveedor con '
                                     f'{cat.nombre(cat.TIPO_ID_COMPRA, proveedor.tipo_id_ats).lower()}')
    if tipo != '03':
        for campo in ('estab', 'pto_emi', 'secuencial', 'autorizacion'):
            if not getattr(compra, campo):
                falta(campo)
        if compra.fecha_emision is None:
            falta('fecha_emision')
    if tipo not in cat.TIPOS_SIN_FORMA_PAGO and not compra.forma_pago:
        falta('forma_pago')
    if compra.parte_relacionada is None:
        falta('parte_relacionada')
    if not compra.pago_loc_ext:
        falta('pago_loc_ext')
    if compra.pago_loc_ext == '02':
        falta('pago_exterior_pendiente')
    if tipo in cat.TIPOS_CON_DOC_MODIFICADO and not all(getattr(compra, c) for c in CAMPOS_DOC_MODIFICADO):
        falta('doc_modificado')
    if tipo == '03':
        vigente = liquidaciones.liquidacion_vigente(compra) if compra.pk else None
        if vigente is None or vigente.status not in AUTORIZADOS:
            falta('liquidacion_pendiente')
        elif vigente.environment_type != 2:
            falta('liquidacion_pendiente', f'La liquidación {vigente.voucher_number_full} se autorizó en el ambiente de PRUEBAS '
                                           'del SRI: no sustenta la compra')
        elif compra.total is not None:
            diferencias = _descuadre_liquidacion(compra, vigente)
            if diferencias:
                falta('liquidacion_descuadrada', f'La liquidación {vigente.voucher_number_full} no coincide con la compra '
                                                 f'({"; ".join(diferencias)}): anúlala y emítela con los valores de la compra')
    if compra.fuera_plazo_ats:
        falta('fuera_plazo_ats')
    return faltan


def _descuadre_liquidacion(compra, liquidacion):
    """Diferencias (texto) entre la compra y su liquidación autorizada, al centavo; vacío si coinciden."""
    bases = redondear(sum((getattr(compra, b) or CERO for b in BASES), CERO))
    pares = (('sin impuestos', bases, liquidacion.total_sin_impuestos), ('IVA', compra.total_iva or CERO, liquidacion.total_iva),
             ('total', compra.total, liquidacion.importe_total))
    return [f'{nombre}: {dinero(a)} en la compra y {dinero(b)} en la liquidación' for nombre, a, b in pares
            if redondear(a) != redondear(b)]


def actualizar_marca(compra, *, guardar=True):
    """datos_incompletos = bool(faltantes). La única vía que baja la marca. Devuelve True si quedó incompleta."""
    from core.pos.models import Purchase
    incompleta = bool(faltantes(compra))
    compra.datos_incompletos = incompleta
    if guardar:
        Purchase.all_companies.filter(pk=compra.pk, company_id=compra.company_id).update(datos_incompletos=incompleta)
    return incompleta


def _marcar_completada(compra, usuario):
    from core.pos.models import Purchase
    compra.completada_en = timezone.now()
    compra.completada_por = usuario if usuario is not None and getattr(usuario, 'pk', None) else None
    Purchase.all_companies.filter(pk=compra.pk, company_id=compra.company_id).update(
        completada_en=compra.completada_en, completada_por=compra.completada_por)


# ------------------------------------------------------------------ completar datos

def bloqueos_de(compra):
    """(campos bloqueados, motivo, ignorar). Las compras creadas desde un XML conservan su numeración, autorización y fecha
    (ignorar=True: lo que llegue en esos campos se descarta). Con una retención o liquidación vigente, la numeración ya llena
    no cambia (ignorar=False: cambiarla es un error) y los datos vacíos sí se pueden llenar."""
    from core.comprobantes import liquidaciones, retenciones
    if compra.origen == 'importacion':
        return (['tipo_comprobante', *CAMPOS_NUMERACION],
                'El tipo de comprobante, la numeración, la autorización y la fecha de emisión vienen del XML autorizado.', True)
    retencion = retenciones.retencion_vigente(compra)
    if retencion is not None:
        llenos = [c for c in ('tipo_comprobante', *CAMPOS_NUMERACION) if getattr(compra, c)]
        return llenos, f'La retención {retencion.voucher_number_full} usa este número: anúlala antes de cambiarlo.', False
    liquidacion = liquidaciones.liquidacion_vigente(compra)
    if liquidacion is not None:   # el tipo lo da la liquidación (03 al autorizarse), aunque todavía esté vacío
        llenos = ['tipo_comprobante'] + [c for c in CAMPOS_NUMERACION if getattr(compra, c)]
        return llenos, f'La liquidación {liquidacion.voucher_number_full} usa este número: anúlala antes de cambiarlo.', False
    return [], '', False


@dataclass
class _PlanCompletar:
    nuevos: dict
    cambios: dict
    advertencias: list
    confirmaciones: list
    pendientes: list
    ajustar: object = None       # DebtsPay a ajustar al total con IVA


def _reglas_del_tipo(compra, n, importes, deudas):
    """Reglas de crear_compra que dependen de las líneas y del pago, aplicadas al tipo y a la fecha de emisión que resultan
    de completar_datos (que no cambia líneas, stock ni cuenta por pagar). Devuelve advertencias."""
    tipo, fecha = n['tipo_comprobante'], n['fecha_emision']
    detalles = list(compra.purchasedetail_set.order_by('pk').values_list('product_id', 'codigo_porcentaje', 'total_dscto'))
    if tipo in cat.TIPOS_CON_DOC_MODIFICADO and any(producto for producto, _, _ in detalles):
        raise ErrorCompra('Las notas de crédito y débito del proveedor se registran con líneas de gasto (sin producto): esta '
                          'compra tiene productos y movió el stock. Elimínala y regístrala de nuevo como nota.')
    if tipo == '04' and (compra.payment_type == 'credito' or deudas):
        raise ErrorCompra('Una nota de crédito del proveedor no tiene cuenta por pagar propia y esta compra se registró a '
                          'crédito: elimínala y regístrala de nuevo como nota de crédito.')
    if tipo in cat.TIPOS_SIN_IVA_DISCRIMINADO and (any(c and c not in cat.CODIGOS_IVA_NOTA_VENTA for _, c, _ in detalles)
                                                   or (importes.get('total_iva') or CERO) != 0):
        raise ErrorCompra('Una nota de venta no discrimina IVA y esta compra tiene IVA: elimínala y regístrala de nuevo con '
                          'tarifa 0 %.')
    if tipo == '03' and compra.version_datos == 2:
        _validar_lineas_liquidacion([(c, d) for _, c, d in detalles], importes)
    advertencias = []
    codigos = {c for _, c, _ in detalles if c}
    if fecha is not None:
        if '4' in codigos and fecha < cat.INICIO_IVA_15:
            raise ErrorCompra('Las líneas de esta compra tienen IVA del 15 %, que rige desde el 01/04/2024: la fecha de emisión '
                              'es anterior. Revisa la fecha.')
        if '2' in codigos and fecha >= cat.INICIO_IVA_15:
            raise ErrorCompra('Las líneas de esta compra tienen IVA del 12 %, que no rige para comprobantes desde el 01/04/2024: '
                              'revisa la fecha de emisión.')
        if '5' in codigos and fecha < cat.INICIO_IVA_15:
            advertencias.append(('tarifa_5_anterior', 'La tarifa del 5 % se aplica desde el 01/04/2024: revisa la tarifa de '
                                                      'este comprobante, que es anterior.'))
    return advertencias


def _plan_completar(compra, datos, deudas):
    from core.pos.models import IMPORTES_COMPRA
    datos = datos or {}
    actuales = {c: getattr(compra, c) for c in CAMPOS_CABECERA if c != 'compra_modificada'}
    actuales['compra_modificada'] = compra.compra_modificada_id
    entrada = dict(actuales)
    bloqueados, motivo, ignorar = bloqueos_de(compra)
    for campo in CAMPOS_CABECERA:
        if campo in datos:
            entrada[campo] = datos[campo]
    for campo in bloqueados:
        if campo not in datos or ignorar:
            entrada[campo] = actuales[campo]
    n = _normalizar_cabecera(entrada, compra.provider)
    for campo in bloqueados:
        if not ignorar and n[campo] in ('', None):
            n[campo] = actuales[campo]           # campo deshabilitado en el formulario: se conserva
        elif not ignorar and n[campo] != actuales[campo]:
            raise ErrorCompra(motivo, codigo='bloqueado')
    modo = 'liquidacion' if n['tipo_comprobante'] == '03' else 'si'
    advertencias, confirmaciones = _validar_cabecera(n, compra.provider, modo=modo, origen=compra.origen, parcial=True,
                                                     date_joined=compra.date_joined, compra_id=compra.pk)
    nuevos = dict(n)
    # importes: solo en compras anteriores (version_datos=1), todos o ninguno
    importes = {c: getattr(compra, c) for c in IMPORTES_COMPRA}
    if compra.version_datos == 1:
        llegados = {c: _texto(datos.get(c)) for c in IMPORTES_EDITABLES + ('total_irbpnr',) if c in datos}
        con_valor = [c for c in IMPORTES_EDITABLES if llegados.get(c, '') != '']
        if con_valor:
            if len(con_valor) != len(IMPORTES_EDITABLES):
                raise ErrorCompra('Escribe todos los importes de la factura (usa 0 donde no haya valor).')
            for c in IMPORTES_EDITABLES:
                importes[c] = _decimal(datos.get(c), ETIQUETAS[c], obligatorio=True)
            importes['total_irbpnr'] = _decimal(datos.get('total_irbpnr'), ETIQUETAS['total_irbpnr'], defecto=CERO)
            importes['total'] = redondear(sum(importes[b] for b in BASES) + importes['total_ice'] + importes['total_iva']
                                          + importes['total_irbpnr'] + importes['propina'])
            suma_bases = redondear(sum(importes[b] for b in BASES))
            if abs(suma_bases - Decimal(compra.subtotal)) > TOLERANCIA_BASES:
                confirmaciones.append('confirmar_diferencia')
            fecha_tarifa = n['fecha_emision'] or compra.date_joined
            esperado = importes['base_gravada'] * cat.tarifa_iva_general(fecha_tarifa) / 100 + importes['base_5'] * Decimal('0.05')
            if abs(importes['total_iva'] - esperado) > TOLERANCIA_IVA:
                confirmaciones.append('confirmar_iva')
        nuevos.update(importes)
    advertencias.extend(a for a in _reglas_del_tipo(compra, n, importes, deudas) if a not in advertencias)
    nuevos['fuera_plazo_ats'] = 'confirmar_plazo_ats' in confirmaciones
    if importes['total'] is not None and importes['total'] > cat.UMBRAL_BANCARIZACION and nuevos['forma_pago'] == '01':
        advertencias.append(('bancarizacion', 'Un pago de más de USD 1.000 sin el sistema financiero no da crédito tributario '
                                              'de IVA ni es deducible.'))
    # cuenta por pagar: solo con la casilla y sobre una cuenta calculada sin IVA
    ajustar = None
    if _confirmado(datos.get('ajustar_cxp')):
        candidatas = [d for d in deudas if d.base_calculo == 'subtotal']
        if not candidatas:
            raise ErrorCompra('Esta compra no tiene una cuenta por pagar calculada sin IVA para ajustar.')
        if importes['total'] is None:
            raise ErrorCompra('Escribe los importes de la factura antes de ajustar la cuenta por pagar.')
        ajustar = candidatas[0]
        pagado = ajustar.pagado()
        if pagado > importes['total']:
            raise ErrorCompra(f'Los pagos registrados ({dinero(pagado)}) superan el total con IVA ({dinero(importes["total"])}): '
                              'revisa los pagos antes de ajustar.')
        if importes['total'] > MAX_SUBTOTAL:
            raise ErrorCompra('El total de la compra supera el máximo admitido ($9999999.99).')
    antes = dict(actuales, **{c: getattr(compra, c) for c in IMPORTES_COMPRA}, fuera_plazo_ats=compra.fuera_plazo_ats)
    cambios = {c: [antes[c], nuevos[c]] for c in nuevos if c in antes and antes[c] != nuevos[c]}
    confirmados = {c for c in ('confirmar_iva', 'confirmar_plazo_ats', 'confirmar_diferencia') if _confirmado(datos.get(c))}
    return _PlanCompletar(nuevos=nuevos, cambios=cambios, advertencias=advertencias, confirmaciones=confirmaciones,
                          pendientes=[c for c in confirmaciones if c not in confirmados], ajustar=ajustar)


def _texto_confirmacion_completar(codigo, compra, plan):
    if codigo == 'confirmar_diferencia':
        suma = redondear(sum(plan.nuevos[b] for b in BASES))
        return (f'La factura suma {dinero(suma)} sin impuestos y la compra registró {dinero(compra.subtotal)}. No se cambian '
                'las líneas ni el stock: solo se guardan los importes de la factura para los formularios.')
    if codigo == 'confirmar_iva':
        return 'El IVA escrito no corresponde a la tarifa general sobre la base gravada (más el 5 % de la base 5 %): confírmalo.'
    if codigo == 'confirmar_plazo_ats':
        return 'La factura tiene más de un año: el ATS no la admitirá en este período. Confírmalo para guardarla.'
    return 'Confirma la operación.'


def revisar_datos(compra, datos):
    """Vista previa de completar_datos (sin guardar): {cambios, advertencias, confirmaciones, faltantes, total}."""
    from core.pos.models import DebtsPay
    deudas = list(DebtsPay.objects.filter(purchase=compra))
    plan = _plan_completar(compra, datos, deudas)
    copia = copy.copy(compra)
    for campo, valor in plan.nuevos.items():
        setattr(copia, 'compra_modificada_id' if campo == 'compra_modificada' else campo, valor)
    return {'cambios': [{'campo': c, 'etiqueta': ETIQUETAS.get(c, c), 'antes': para_auditoria(a), 'despues': para_auditoria(d)}
                        for c, (a, d) in plan.cambios.items()],
            'advertencias': [{'codigo': c, 'texto': t} for c, t in plan.advertencias],
            'confirmaciones': plan.confirmaciones,
            'textos_confirmacion': {c: _texto_confirmacion_completar(c, compra, plan) for c in plan.confirmaciones},
            'faltantes': [{'codigo': c, 'texto': t} for c, t in faltantes(copia)],
            'total': texto_importe(plan.nuevos.get('total', compra.total))}


def completar_datos(compra, usuario, datos, *, request=None, origen='formulario', decision='', informe=''):
    """Completa (o corrige) la cabecera ATS y, en compras anteriores, los importes de la factura. Nunca cambia líneas, stock,
    subtotal, proveedor ni fecha de registro; la cuenta por pagar solo con `ajustar_cxp`. Auditado (purchase_complete)."""
    from core.pos.models import DebtsPay, Purchase
    if origen == 'orden' and not _texto(decision):
        raise ErrorCompra('Completar compras con una orden exige la decisión escrita (--decision).')
    with transaction.atomic():
        compra = Purchase.objects.select_for_update(of=('self',)).get(pk=compra.pk)
        deudas = list(DebtsPay.objects.select_for_update(of=('self',)).filter(purchase=compra).order_by('pk'))
        plan = _plan_completar(compra, datos, deudas)
        if plan.pendientes:
            codigo = plan.pendientes[0]
            raise ErrorCompra(_texto_confirmacion_completar(codigo, compra, plan), codigo=codigo)
        era_incompleta = compra.datos_incompletos
        for campo, valor in plan.nuevos.items():
            setattr(compra, 'compra_modificada_id' if campo == 'compra_modificada' else campo, valor)
        campos = list(plan.nuevos)
        try:
            with transaction.atomic():
                compra.save(update_fields=campos)
        except IntegrityError:
            existente = _comprobante_registrado(compra.provider_id, compra.tipo_comprobante, compra.estab, compra.pto_emi,
                                                compra.secuencial, excluir=compra.pk)
            if existente is not None:
                raise _error_duplicado(existente, compra.provider)
            raise
        if plan.ajustar is not None:
            deuda = plan.ajustar
            deuda_antes, saldo_antes = Decimal(deuda.debt), Decimal(deuda.saldo)
            DebtsPay.all_companies.filter(pk=deuda.pk).update(debt=compra.total, base_calculo='total')
            deuda.debt, deuda.base_calculo = compra.total, 'total'
            deuda.recalcular()
            _auditar(request, 'purchase_debt_adjust', compra.company, usuario, compra=compra.pk, deuda_antes=deuda_antes,
                     deuda_despues=Decimal(compra.total), saldo_antes=saldo_antes, saldo_despues=Decimal(deuda.saldo))
        if not actualizar_marca(compra) and (era_incompleta or compra.completada_en is None):
            _marcar_completada(compra, usuario)
        if plan.cambios:
            extra = {'decision': decision, 'informe': informe} if origen == 'orden' else {}
            _auditar(request, 'purchase_complete', compra.company, usuario, compra=compra.pk, origen=origen,
                     version_datos=compra.version_datos, cambios=plan.cambios, **extra)
    compra.advertencias = plan.advertencias
    return compra


# ------------------------------------------------------------------ eliminar

def eliminar_compra(compra, usuario, *, request=None):
    """Borra la compra (stock revertido) si no tiene pagos, retención, liquidación ni notas que la modifiquen; devuelve a
    «pendiente» el documento importado que la referencia. Todo en una transacción y auditado (purchase_delete)."""
    from core.comprobantes.models import LiquidacionCompra, Retencion
    from core.importacion.models import DocumentoImportado
    from core.importacion.servicios import evento
    from core.pos import cuentas_por_pagar
    from core.pos.models import DebtsPay, PaymentsDebtsPay, Purchase
    with transaction.atomic():
        compra = Purchase.objects.select_for_update(of=('self',)).filter(pk=compra.pk).first()
        if compra is None:
            raise ErrorCompra('La compra ya no existe.')
        deudas = list(DebtsPay.objects.select_for_update(of=('self',)).filter(purchase=compra).order_by('pk'))
        if Retencion.objects.filter(purchase=compra).exists():
            raise ErrorCompra('La compra tiene un comprobante de retención: no se puede eliminar.')
        if LiquidacionCompra.objects.filter(purchase=compra).exists():
            raise ErrorCompra('La compra tiene una liquidación de compra: no se puede eliminar.')
        if Purchase.objects.filter(compra_modificada=compra).exists():
            raise ErrorCompra('La compra tiene notas de crédito o débito que la modifican: elimínalas primero.')
        if PaymentsDebtsPay.objects.filter(debts_pay__in=[d.pk for d in deudas]).exists():
            raise ErrorCompra('Tiene pagos registrados: elimínalos primero en Cuentas por pagar.')
        DebtsPay.objects.filter(pk__in=[d.pk for d in deudas]).delete()
        documentos = list(DocumentoImportado.objects.filter(compra=compra).values_list('pk', flat=True))
        if documentos:
            DocumentoImportado.objects.filter(pk__in=documentos).update(
                estado_revision='pendiente', compra=None, estado_contable='sin_propuesta', propuesta_contable=None)
            for documento in DocumentoImportado.objects.filter(pk__in=documentos):
                evento('compra_eliminada', f'Se eliminó la compra #{compra.pk}: el documento vuelve a estar pendiente.',
                       documento=documento, usuario=usuario if getattr(usuario, 'pk', None) else None, compra=compra.pk)
        detalle = {'compra': compra.pk, 'numero': compra.numero_comprobante, 'total': compra.total, 'origen': compra.origen}
        modificada_id = compra.compra_modificada_id if compra.tipo_comprobante == '04' else None
        company = compra.company
        compra.delete()
        if modificada_id:
            cuentas_por_pagar.recalcular_de_compra(modificada_id, company.pk)
        _auditar(request, 'purchase_delete', company, usuario, **detalle)


# ------------------------------------------------------------------ retención y liquidación

def datos_sustento_retencion(compra):
    """(iniciales del formulario del documento sustento, advertencias). El comprobante de retención actual admite una sola
    base gravada y una tarifa: las bases se precargan solo con una tarifa distinta de 0 y sin bases exentas o no objeto."""
    iniciales = {'fecha_doc_sustento': compra.date_joined, 'base_iva': compra.subtotal}
    advertencias = []
    con_numero = compra.tipo_comprobante == '01' and compra.secuencial
    if con_numero:
        iniciales.update({'cod_doc_sustento': '01', 'num_doc_sustento': f'{compra.estab}{compra.pto_emi}{compra.secuencial}',
                          'aut_doc_sustento': compra.autorizacion})
        if compra.fecha_emision:
            iniciales['fecha_doc_sustento'] = compra.fecha_emision
    if compra.total is None or compra.tipo_comprobante != '01':
        return iniciales, advertencias
    if compra.cod_sustento:
        iniciales['cod_sustento'] = compra.cod_sustento
    if compra.forma_pago:
        iniciales['forma_pago'] = compra.forma_pago
    if compra.parte_relacionada is not None:
        iniciales['parte_relacionada'] = compra.parte_relacionada
    for campo in ('base_0', 'base_iva', 'tarifa_iva', 'valor_iva'):
        iniciales.pop(campo, None)
    tarifas = set()
    for codigo, tarifa in compra.purchasedetail_set.values_list('codigo_porcentaje', 'tarifa'):
        if codigo in ('4', '2', '3', '10', '5', '8'):
            tarifas.add(redondear(tarifa if tarifa is not None else cat.TARIFA_POR_CODIGO[codigo]))
        elif codigo == '':
            tarifas.add(None)            # línea sin tarifa (compra anterior con importes completados)
    sin_otras = not (compra.base_no_objeto or compra.base_exenta)
    gravadas = (compra.base_gravada or CERO) + (compra.base_5 or CERO)
    if sin_otras and None not in tarifas and len(tarifas) == 1:
        iniciales.update({'base_0': compra.base_0 or CERO, 'base_iva': gravadas, 'tarifa_iva': f'{tarifas.pop():.2f}',
                          'valor_iva': compra.total_iva or CERO})
    elif sin_otras and not tarifas and not gravadas and compra.purchasedetail_set.exists():
        iniciales.update({'base_0': compra.base_0 or CERO, 'base_iva': CERO, 'valor_iva': CERO})
    else:
        advertencias.append({'codigo': 'sustento_varias_tarifas',
                             'texto': 'La factura tiene varias tarifas o bases exentas o no objeto: el comprobante de retención '
                                      'actual admite una sola tarifa. Revisa las bases.'})
    return iniciales, advertencias


def al_autorizar_liquidacion(liquidacion):
    """Receptor de comprobante_autorizado (LiquidacionCompra): la compra sin tipo pasa a 03 y se actualiza su marca.
    Idempotente (se repite al reenviar o consultar un comprobante ya autorizado); transacción propia."""
    from core.pos.emision import AUTORIZADOS
    from core.pos.models import Purchase
    with transaction.atomic():
        if liquidacion.status in AUTORIZADOS:
            Purchase.all_companies.filter(pk=liquidacion.purchase_id, company_id=liquidacion.company_id,
                                          tipo_comprobante='').update(tipo_comprobante='03')
        compra = Purchase.all_companies.select_related('provider').filter(
            pk=liquidacion.purchase_id, company_id=liquidacion.company_id).first()
        if compra is not None and not actualizar_marca(compra) and compra.completada_en is None:
            _marcar_completada(compra, liquidacion.employee)


def al_anular_liquidacion(liquidacion):
    """Receptor de anulado_en_sri (LiquidacionCompra): la compra sigue siendo 03 y vuelve a mostrar liquidacion_pendiente."""
    from core.pos.models import Purchase
    compra = Purchase.all_companies.select_related('provider').filter(
        pk=liquidacion.purchase_id, company_id=liquidacion.company_id).first()
    if compra is not None:
        actualizar_marca(compra)


# ------------------------------------------------------------------ sugerencias y expresiones

def sustento_gasto_sugerido(company):
    """'01' si la empresa vende con IVA (productos con tarifa 15 % o 5 %, o sin tarifa y con impuesto); si no, '02'.
    Solo se MUESTRA como sugerencia (DC12): nunca se guarda sola."""
    from core.pos.models import Product
    con_iva = Product.all_companies.filter(company_id=company.pk).filter(
        Q(tarifa_iva__in=('4', '5')) | Q(tarifa_iva='', with_tax=True)).exists()
    return '01' if con_iva else '02'


def subtotal_con_signo():
    """Expresión ORM del subtotal con signo: las notas de crédito del proveedor (04) restan."""
    return Case(When(tipo_comprobante='04', then=-F('subtotal')), default=F('subtotal'),
                output_field=DecimalField(max_digits=12, decimal_places=2))


def total_con_signo():
    """Expresión ORM del total con IVA con signo (NULL en compras sin importes)."""
    return Case(When(tipo_comprobante='04', then=-F('total')), default=F('total'),
                output_field=DecimalField(max_digits=12, decimal_places=2))


# ------------------------------------------------------------------ pantallas (paso 2: §4 y §6)

NOMBRES_TARIFA_FORMULARIO = {'4': '15 %', '5': '5 %', '0': '0 %', '6': 'No objeto de IVA', '7': 'Exento de IVA',
                             '2': '12 % (comprobantes anteriores al 01/04/2024)', '8': 'IVA diferenciado (escribe la tarifa)'}


def opciones_formulario():
    """Catálogos para la pantalla «Nueva compra» (se pasan al navegador con json_script)."""
    return {
        'tipos_comprobante': [list(t) for t in cat.TIPOS_COMPROBANTE_COMPRA],
        'sustentos': [list(s) for s in cat.SUSTENTOS],
        'comprobantes_por_sustento': {c: sorted(t) for c, t in cat.COMPROBANTES_POR_SUSTENTO.items()},
        'tipo_id_por_comprobante': {t: sorted(i) for t, i in cat.TIPO_ID_POR_COMPROBANTE.items()},
        'formas_pago': [list(f) for f in cat.FORMAS_PAGO],
        'tarifas': [{'codigo': c, 'nombre': NOMBRES_TARIFA_FORMULARIO[c],
                     'tarifa': texto_importe(cat.TARIFA_POR_CODIGO[c]) if c in cat.TARIFA_POR_CODIGO else None,
                     'tarifa_variable': c in cat.CODIGOS_CON_TARIFA_VARIABLE} for c in cat.CODIGOS_IVA_COMPRA],
        'pago_loc_ext': [list(p) for p in cat.PAGO_LOC_EXT],
        'tipos_con_doc_modificado': list(cat.TIPOS_CON_DOC_MODIFICADO),
        'tipos_sin_forma_pago': list(cat.TIPOS_SIN_FORMA_PAGO),
        'tipos_sin_iva_discriminado': list(cat.TIPOS_SIN_IVA_DISCRIMINADO),
        'codigos_iva_nota_venta': list(cat.CODIGOS_IVA_NOTA_VENTA),
        'umbral_bancarizacion': texto_importe(cat.UMBRAL_BANCARIZACION),
    }


def comprobante_registrado(proveedor_id, tipo, estab, pto_emi, secuencial, excluir=None):
    """Compra ya registrada con ese comprobante del proveedor (o None). El secuencial se completa con ceros a 9 dígitos."""
    secuencial = _texto(secuencial)
    if not secuencial.isdigit() or int(secuencial) == 0:
        return None
    return _comprobante_registrado(proveedor_id, _texto(tipo), _texto(estab), _texto(pto_emi), secuencial.zfill(9),
                                   excluir=excluir)


def documento_importado_pendiente(proveedor, tipo, estab, pto_emi, secuencial):
    """XML recibido de ese proveedor y con ese número que todavía no tiene compra (pendiente o aprobado), o None."""
    from core.importacion.models import DocumentoImportado
    secuencial = _texto(secuencial)
    if proveedor is None or not secuencial.isdigit() or int(secuencial) == 0:
        return None
    return (DocumentoImportado.objects.filter(emisor_ruc=re.sub(r'\s', '', proveedor.ruc or ''), cod_doc=_texto(tipo),
                                              estab=_texto(estab), pto_emi=_texto(pto_emi), secuencial=secuencial.zfill(9),
                                              clasificacion='recibido', compra__isnull=True,
                                              estado_revision__in=('pendiente', 'aprobado'))
            .order_by('pk').first())


def filtrar_listado(queryset, *, inicio='', fin='', fecha='registro', incompletas=False):
    """Filtros del listado y del reporte de compras. Con fecha de emisión, las compras sin ella (anteriores o «Completar
    después») no aparecen: solo se ven al filtrar por fecha de registro."""
    campo = 'fecha_emision' if fecha == 'emision' else 'date_joined'
    if campo == 'fecha_emision':
        queryset = queryset.filter(fecha_emision__isnull=False)
    if inicio and fin:
        queryset = queryset.filter(**{f'{campo}__range': [inicio, fin]})
    if incompletas:
        queryset = queryset.filter(datos_incompletos=True)
    return queryset


def totales_listado(queryset):
    """Pie del listado y del reporte: total con IVA de las compras completas (las notas de crédito restan) y, aparte, las
    compras con datos incompletos con su subtotal registrado (subtotal_con_signo). Importes como texto."""
    from django.db.models import Count, Sum
    completas = queryset.filter(datos_incompletos=False).aggregate(total=Sum(total_con_signo()), n=Count('id'))
    incompletas = queryset.filter(datos_incompletos=True).aggregate(subtotal=Sum(subtotal_con_signo()), n=Count('id'))
    return {'completas': {'cantidad': completas['n'], 'total': texto_importe(completas['total'] or CERO)},
            'incompletas': {'cantidad': incompletas['n'], 'subtotal': texto_importe(incompletas['subtotal'] or CERO)}}
