"""Compras desde documentos importados (espec-etapa2-compras §3.6): del XML recibido (01, 04 o 05) a la compra.

- En el XML autorizado mandan los importes (DC4): bases por tarifa, IVA, ICE, IRBPNR, propina, total y los de cada línea.
  `price` de la línea es informativo. Este módulo los entrega a compras.crear_compra (importes=…) y a la orden
  compras_incompletas --desde-xml (compras.completar_datos).
- Emparejar una línea con un producto es una decisión del usuario (DC8): la equivalencia «código del proveedor →
  producto» se sugiere y solo se guarda si el usuario marca «Recordar»; el mismo código de producto solo se sugiere.
- Nada que decida el crédito tributario se elige de oficio (DC12): el sustento se sugiere sin preseleccionar; la forma de
  pago solo se precarga si el XML trae pagos.
- Una sola transacción: documento (sin compra) → compra → cuenta por pagar, con la actualización condicionada del
  documento (exactamente una fila) para que dos peticiones nunca creen dos compras ni muevan el stock dos veces.
"""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from core.pos.catalogos_sri import (BASE_POR_CODIGO, CODIGOS_CON_TARIFA_VARIABLE, FORMAS_PAGO, PLAZO_ATS_DIAS, SUSTENTOS,
                                    TARIFA_POR_CODIGO, UMBRAL_BANCARIZACION)
from core.pos.compras import MAX_CANTIDAD, MAX_LINEAS

BASES = ('base_0', 'base_gravada', 'base_5', 'base_no_objeto', 'base_exenta')
CENTAVO = Decimal('0.01')
CERO = Decimal('0.00')
TOLERANCIA = Decimal('0.02')
CODIGOS_DE_COMPRA = ('01', '04', '05')
# Claves que xml_sri escribe desde la Etapa 2 (§1.8); un documento anterior sin ellas se vuelve a leer de su XML
CLAVES_NUEVAS = {'01': ('detalles',), '04': ('detalles', 'doc_modificado'), '05': ('doc_modificado', 'motivos'),
                 '07': ('retencion',)}
VERIFICACIONES_QUE_BLOQUEAN = ('no_autorizada_sri', 'no_encontrada_sri', 'discrepancia_sri')
# Regla de importación (naturaleza, tratamiento del IVA) → sustento sugerido (Tabla 5)
SUSTENTO_SUGERIDO = {('inventario', 'credito_tributario'): '06', ('inventario', 'costo_gasto'): '07',
                     ('gasto', 'credito_tributario'): '01', ('gasto', 'costo_gasto'): '02',
                     ('activo_fijo', 'credito_tributario'): '03', ('activo_fijo', 'costo_gasto'): '04'}
TEXTOS = {
    'importes_del_xml': 'Los importes son los del XML autorizado.',
    'stock': 'El stock solo sube en las líneas que emparejes con un producto inventariado.',
    'notas_sin_stock': 'Las notas de crédito y débito no mueven stock en esta etapa.',
}


class DatoNoReconocido(ValueError):
    """El XML trae un dato que la compra no sabe guardar (p. ej. un código de tarifa desconocido)."""


def _error(mensaje, codigo=''):
    from core.importacion.servicios import ErrorImportacion
    return ErrorImportacion(mensaje, codigo=codigo)


def _decimal(valor, defecto=CERO):
    if valor in (None, ''):
        return defecto
    try:
        return Decimal(str(valor))
    except InvalidOperation:
        return defecto


def _redondear(valor):
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _texto(valor):
    return '' if valor is None else str(valor).strip()


def _fecha_iso(valor):
    if isinstance(valor, date) or valor in (None, ''):
        return valor or None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def _numero_es(valor, decimales=None):
    """Decimal en notación local para las descripciones: 2.500000 → «2,5»; con `decimales`, 4 → «4,000000»."""
    texto = f'{Decimal(valor):.{decimales}f}' if decimales is not None else format(Decimal(valor).normalize(), 'f')
    return texto.replace('.', ',')


# ------------------------------------------------------------------ datos del documento

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


def forma_pago_del_xml(documento, comprobante=None):
    """Forma de pago (Tabla 13) del pago de mayor valor del XML, o '' si el XML no trae pagos (no se elige de oficio)."""
    comprobante = comprobante if comprobante is not None else ((documento.datos or {}).get('comprobante') or {})
    pagos = comprobante.get('pagos') or []
    validos = [p for p in pagos if (p.get('forma_pago') or '') in dict(FORMAS_PAGO)]
    if not validos:
        return ''
    return max(validos, key=lambda p: _decimal(p.get('total')))['forma_pago']


def cabecera_de_documento(documento):
    """Datos del comprobante que trae el documento: tipo, numeración, autorización (clave de acceso), fecha de emisión,
    forma de pago (si el XML trae pagos) y pago a residente (el emisor de un comprobante electrónico tiene RUC)."""
    return {'tipo_comprobante': documento.cod_doc, 'estab': documento.estab, 'pto_emi': documento.pto_emi,
            'secuencial': documento.secuencial, 'autorizacion': documento.clave_acceso,
            'fecha_emision': documento.fecha_emision, 'forma_pago': forma_pago_del_xml(documento), 'pago_loc_ext': '01'}


def comprobante_completo(documento):
    """datos['comprobante'] del documento. Si es anterior a la Etapa 2 y le faltan las claves nuevas (detalles, documento
    modificado, motivos o retención), las vuelve a leer de su XML guardado, SIN modificar el documento."""
    from core.importacion.xml_sri import procesar_xml_sri
    comprobante = dict((documento.datos or {}).get('comprobante') or {})
    if all(clave in comprobante for clave in CLAVES_NUEVAS.get(documento.cod_doc, ())) or documento.archivo_xml_id is None:
        return comprobante
    try:
        with documento.archivo_xml.archivo.open('rb') as archivo:
            contenido = archivo.read()
    except (OSError, ValueError):
        return comprobante
    resultado = procesar_xml_sri(contenido)
    if not resultado.aceptado or resultado.comprobante is None or resultado.comprobante.clave_acceso != documento.clave_acceso:
        return comprobante
    return resultado.to_dict()['comprobante']


def proveedor_del_documento(documento):
    """Proveedor de la empresa con el RUC del emisor (el asignado al importar o uno creado después), o None."""
    from core.pos.models import Provider
    if documento.proveedor_id:
        return documento.proveedor
    return Provider.objects.filter(ruc=documento.emisor_ruc).first()


# ------------------------------------------------------------------ líneas

@dataclass
class LineaPropuesta:
    indice: int
    codigo_principal: str
    codigo_auxiliar: str
    descripcion: str
    cantidad: Decimal
    cantidad_entera: bool
    precio_unitario: Decimal
    descuento: Decimal
    precio_total_sin_impuesto: Decimal
    codigo_porcentaje: str
    tarifa: Decimal | None
    base_iva: Decimal
    iva: Decimal
    ice: Decimal
    producto_sugerido: object = None
    origen_sugerencia: str = ''          # equivalencia | mismo_codigo | ''
    modo_sugerido: str = 'gasto'          # producto (equivalencia y cantidad entera) | gasto
    solo_gasto: bool = False              # notas de crédito y débito: sin producto (DC5)
    advertencias: list = field(default_factory=list)

    @property
    def nombre_tarifa(self):
        from core.pos.models import nombre_tarifa_compra
        return nombre_tarifa_compra(self.codigo_porcentaje, self.tarifa)

    def como_dict(self):
        producto = self.producto_sugerido
        return {'indice': self.indice, 'codigo_principal': self.codigo_principal, 'codigo_auxiliar': self.codigo_auxiliar,
                'descripcion': self.descripcion, 'cantidad': f'{self.cantidad:.6f}', 'cantidad_entera': self.cantidad_entera,
                'precio_unitario': f'{self.precio_unitario:.6f}', 'descuento': f'{self.descuento:.2f}',
                'precio_total_sin_impuesto': f'{self.precio_total_sin_impuesto:.2f}', 'codigo_porcentaje': self.codigo_porcentaje,
                'tarifa': None if self.tarifa is None else f'{self.tarifa:.2f}', 'nombre_tarifa': self.nombre_tarifa,
                'iva': f'{self.iva:.2f}', 'ice': f'{self.ice:.2f}',
                'producto_sugerido': {'id': producto.pk, 'nombre': producto.name, 'codigo': producto.code} if producto else None,
                'origen_sugerencia': self.origen_sugerencia or None, 'modo_sugerido': self.modo_sugerido,
                'solo_gasto': self.solo_gasto}


def _tarifa_de(codigo, tarifa_xml):
    """Tarifa de la línea: la del XML para el IVA diferenciado (8); la fija del código en los demás."""
    if codigo in CODIGOS_CON_TARIFA_VARIABLE:
        return None if tarifa_xml in (None, '') else _redondear(_decimal(tarifa_xml))
    if codigo in TARIFA_POR_CODIGO:
        return _redondear(TARIFA_POR_CODIGO[codigo])
    return None if tarifa_xml in (None, '') else _redondear(_decimal(tarifa_xml))


def _entera(cantidad):
    return cantidad == cantidad.to_integral_value() and 1 <= cantidad <= MAX_CANTIDAD


def lineas_para_compra(documento, comprobante=None, proveedor=None):
    """[LineaPropuesta] del documento: una por detalle del XML (01 y 04) o una por tarifa de IVA (05, que no trae
    detalles). Con equivalencia guardada para el proveedor y el código, el producto se sugiere y se propone «producto»
    si la cantidad es entera; un producto con el mismo código solo se sugiere (no se preselecciona)."""
    from core.importacion.models import EquivalenciaProducto
    from core.pos.models import Product
    comprobante = comprobante if comprobante is not None else comprobante_completo(documento)
    proveedor = proveedor if proveedor is not None else proveedor_del_documento(documento)
    solo_gasto = documento.cod_doc in ('04', '05')
    lineas = []
    if documento.cod_doc == '05' or not comprobante.get('detalles'):
        descripcion = _descripcion_de_nota(documento, comprobante)
        for i, impuesto in enumerate(documento.impuestos.filter(codigo='2').order_by('id')):
            base = _redondear(impuesto.base_imponible)
            lineas.append(LineaPropuesta(
                indice=i, codigo_principal='', codigo_auxiliar='', descripcion=descripcion, cantidad=Decimal('1'),
                cantidad_entera=True, precio_unitario=base, descuento=CERO, precio_total_sin_impuesto=base,
                codigo_porcentaje=impuesto.codigo_porcentaje,
                tarifa=_tarifa_de(impuesto.codigo_porcentaje, impuesto.tarifa), base_iva=base,
                iva=_redondear(impuesto.valor), ice=CERO, solo_gasto=True))
        if lineas and documento.total_ice:
            lineas[0].ice = _redondear(documento.total_ice)
        return lineas
    equivalencias, por_codigo = {}, {}
    codigos = {_texto(d.get('codigo_principal'))[:25] for d in comprobante['detalles']} - {''}
    if codigos and not solo_gasto:
        if proveedor is not None:
            equivalencias = {e.codigo_proveedor: e.producto for e in EquivalenciaProducto.objects.select_related('producto')
                             .filter(proveedor=proveedor, codigo_proveedor__in=codigos)}
        por_codigo = {p.code: p for p in Product.objects.filter(code__in=codigos)}
    for i, d in enumerate(comprobante['detalles']):
        iva = d.get('iva') or {}
        codigo = _texto(iva.get('codigo_porcentaje'))
        cantidad = _decimal(d.get('cantidad'))
        linea = LineaPropuesta(
            indice=i, codigo_principal=_texto(d.get('codigo_principal'))[:25], codigo_auxiliar=_texto(d.get('codigo_auxiliar'))[:25],
            descripcion=_texto(d.get('descripcion'))[:300], cantidad=cantidad, cantidad_entera=_entera(cantidad),
            precio_unitario=_decimal(d.get('precio_unitario')), descuento=_redondear(_decimal(d.get('descuento'))),
            precio_total_sin_impuesto=_redondear(_decimal(d.get('precio_total_sin_impuesto'))), codigo_porcentaje=codigo,
            tarifa=_tarifa_de(codigo, iva.get('tarifa')), base_iva=_redondear(_decimal(iva.get('base_imponible'))),
            iva=_redondear(_decimal(iva.get('valor'))), ice=_redondear(_decimal(d.get('ice'))), solo_gasto=solo_gasto)
        if linea.tarifa is not None and linea.tarifa > 0:
            esperado = _redondear(linea.base_iva * linea.tarifa / 100)
            if abs(esperado - linea.iva) > TOLERANCIA:
                linea.advertencias.append(('iva_linea_descuadrado', f'Línea {i + 1}: el IVA {linea.iva} no coincide con '
                                                                    f'{linea.base_iva} × {linea.tarifa} % = {esperado}.'))
        if not solo_gasto:
            if linea.codigo_principal in equivalencias:
                linea.producto_sugerido, linea.origen_sugerencia = equivalencias[linea.codigo_principal], 'equivalencia'
                linea.modo_sugerido = 'producto' if linea.cantidad_entera else 'gasto'
            elif linea.codigo_principal in por_codigo:
                linea.producto_sugerido, linea.origen_sugerencia = por_codigo[linea.codigo_principal], 'mismo_codigo'
        lineas.append(linea)
    return lineas


def _descripcion_de_nota(documento, comprobante):
    """Descripción de las líneas de una nota de crédito o débito: su motivo (o los motivos de la nota de débito)."""
    from core.importacion.xml_sri import NOMBRES
    motivo = _texto((comprobante.get('doc_modificado') or {}).get('motivo'))
    if not motivo and comprobante.get('motivos'):
        motivo = '; '.join(_texto(m.get('razon')) for m in comprobante['motivos'] if _texto(m.get('razon')))
    return (motivo or f'{NOMBRES.get(documento.cod_doc, "Comprobante")} {documento.numero}')[:300]


def _agrupar(documento, lineas, comprobante):
    """Una línea de gasto por código de IVA (y tarifa) con la suma de las líneas del XML: «Factura 001-002-000000271 (37
    líneas)»; en las notas, el motivo."""
    from core.importacion.xml_sri import NOMBRES
    grupos = {}
    for linea in lineas:
        grupos.setdefault((linea.codigo_porcentaje, linea.tarifa), []).append(linea)
    if documento.cod_doc in ('04', '05'):
        base_texto = _descripcion_de_nota(documento, comprobante)
    else:
        base_texto = f'{NOMBRES.get(documento.cod_doc, "Comprobante")} {documento.numero} ({len(lineas)} líneas)'
    agrupadas = []
    for i, ((codigo, tarifa), del_grupo) in enumerate(grupos.items()):
        total = sum((l.precio_total_sin_impuesto for l in del_grupo), CERO)
        descuento = sum((l.descuento for l in del_grupo), CERO)
        primera = del_grupo[0]
        texto = base_texto if len(grupos) == 1 else f'{base_texto} · {primera.nombre_tarifa}'
        agrupadas.append(LineaPropuesta(
            indice=i, codigo_principal='', codigo_auxiliar='', descripcion=texto[:300], cantidad=Decimal('1'), cantidad_entera=True,
            precio_unitario=total + descuento, descuento=descuento, precio_total_sin_impuesto=total, codigo_porcentaje=codigo,
            tarifa=tarifa, base_iva=sum((l.base_iva for l in del_grupo), CERO), iva=sum((l.iva for l in del_grupo), CERO),
            ice=sum((l.ice for l in del_grupo), CERO), solo_gasto=True))
    return agrupadas


def _linea_de_compra(linea, modo, producto=None, tipo_gasto=None):
    """Línea para compras.crear_compra (importes=…): los importes del XML mandan (DC4); price es informativo."""
    subtotal = linea.precio_total_sin_impuesto + linea.descuento
    if modo == 'producto':
        cant = int(linea.cantidad)
        descripcion = linea.descripcion
    else:
        cant = 1
        descripcion = linea.descripcion or 'Línea del comprobante'
        if linea.cantidad != 1:
            descripcion = f'{descripcion} (cant. {_numero_es(linea.cantidad)} × {_numero_es(linea.precio_unitario, 6)})'
    return {'product': producto.pk if producto is not None else None, 'type_expense': tipo_gasto.pk if tipo_gasto else None,
            'descripcion': descripcion[:300], 'codigo_proveedor': linea.codigo_principal, 'cant': cant,
            'price': _redondear(subtotal / cant), 'total_dscto': linea.descuento, 'codigo_porcentaje': linea.codigo_porcentaje,
            'tarifa': linea.tarifa, 'subtotal': subtotal, 'total': linea.precio_total_sin_impuesto, 'total_iva': linea.iva,
            'total_ice': linea.ice}


# ------------------------------------------------------------------ propuesta (pantalla y API)

def _bloqueos(documento, proveedor, lineas):
    """[{codigo, texto, compra_id}] que impiden crear la compra desde el documento."""
    from core.pos import compras
    bloqueos = []

    def bloqueo(codigo, texto, compra_id=None):
        bloqueos.append({'codigo': codigo, 'texto': texto, 'compra_id': compra_id})

    if documento.estado_procesamiento != 'procesado':
        bloqueo('sin_xml', 'El documento todavía no tiene su XML autorizado.')
    if documento.clasificacion != 'recibido':
        bloqueo('no_recibido', 'Solo se crea una compra desde un documento recibido por la empresa.')
    if documento.cod_doc == '07':
        bloqueo('tipo_no_admitido', 'Un comprobante de retención se registra en «Registrar retención recibida», no como compra.')
    elif documento.cod_doc not in CODIGOS_DE_COMPRA:
        bloqueo('tipo_no_admitido', 'Solo se crean compras desde facturas, notas de crédito y notas de débito.')
    if documento.estado_verificacion in VERIFICACIONES_QUE_BLOQUEAN:
        bloqueo('verificacion', f'No se puede incorporar: {documento.get_estado_verificacion_display().lower()}.')
    if documento.ambiente != 2:
        bloqueo('ambiente_pruebas', 'El documento es del ambiente de PRUEBAS del SRI: no sustenta una compra.')
    if documento.compra_id:
        bloqueo('ya_vinculado', f'Ya se creó o se vinculó la compra #{documento.compra_id} con este documento.',
                documento.compra_id)
    elif documento.estado_revision != 'pendiente':
        bloqueo('revisado', f'El documento ya está «{documento.get_estado_revision_display()}». Reábrelo para crear la compra.')
    if proveedor is not None:
        if not proveedor.tipo_identificacion:
            bloqueo('proveedor_incompleto', 'Completa el tipo de identificación del proveedor en Proveedores antes de crear la '
                                            'compra.')
        existente = compras.comprobante_registrado(proveedor.pk, documento.cod_doc, documento.estab, documento.pto_emi,
                                                   documento.secuencial)
        if existente is not None and existente.pk != documento.compra_id:
            bloqueo('comprobante_registrado', f'Ya está registrada en la compra #{existente.pk}: vincúlala en lugar de crear '
                                              'otra.', existente.pk)
    try:
        importes_de_documento(documento)
    except DatoNoReconocido as e:
        bloqueo('tarifa_desconocida', str(e))
    else:
        if any(l.codigo_porcentaje not in BASE_POR_CODIGO for l in lineas):
            bloqueo('tarifa_desconocida', 'Una línea del XML no trae una tarifa de IVA que la compra pueda guardar.')
    if not lineas and documento.cod_doc in CODIGOS_DE_COMPRA and documento.estado_procesamiento == 'procesado':
        bloqueo('sin_lineas', 'El XML no detalla líneas ni impuestos de IVA para la compra.')
    return bloqueos


def _plazo_dias(pagos):
    dias = 0
    for p in pagos or []:
        try:
            plazo = int(Decimal(str(p.get('plazo') or '0')))
        except (InvalidOperation, ValueError):
            continue
        unidad = _texto(p.get('unidad_tiempo')).lower()
        dias = max(dias, plazo * (30 if unidad.startswith('mes') else 365 if unidad.startswith(('año', 'ano', 'anio')) else 1))
    return dias


def _compra_modificada(documento, proveedor, comprobante):
    """(datos del documento modificado para la compra, compra modificada o None) en notas de crédito y débito."""
    from core.pos.models import Purchase
    if documento.cod_doc not in ('04', '05'):
        return None, None
    mod = comprobante.get('doc_modificado') or {}
    numero = re.sub(r'\D', '', _texto(mod.get('numero')))
    datos = {'tipo_doc_modificado': _texto(mod.get('cod_doc')), 'num_doc_modificado': numero,
             'fecha_doc_modificado': _fecha_iso(mod.get('fecha_emision')), 'aut_doc_modificado': '', 'motivo': _texto(mod.get('motivo'))}
    modificada = None
    if proveedor is not None and len(numero) == 15:
        modificada = (Purchase.objects.filter(provider=proveedor, tipo_comprobante=datos['tipo_doc_modificado'], estab=numero[:3],
                                              pto_emi=numero[3:6], secuencial=numero[6:])
                      .exclude(tipo_comprobante__in=('04', '05')).order_by('pk').first())
    if modificada is not None:
        datos['aut_doc_modificado'] = modificada.autorizacion or ''
    return datos, modificada


def _posibles_duplicadas(documento, proveedor):
    """Compras anteriores a la Etapa 2 (sin secuencial) del proveedor con el mismo número: pueden ser este comprobante."""
    from core.pos import compras
    if proveedor is None or documento.cod_doc not in CODIGOS_DE_COMPRA:
        return []
    return compras.compras_anteriores_mismo_numero(proveedor.pk, documento.estab, documento.pto_emi, documento.secuencial)


def _texto_posible_duplicado(parecidas):
    lista = ', '.join(f'#{c.pk} (número {c.number}, {c.date_joined:%d/%m/%Y})' for c in parecidas)
    return (f'Ya hay una compra registrada antes con el mismo número: {lista}. Si es este comprobante, vincúlala desde el '
            'documento en lugar de crear otra (duplicaría el stock y la cuenta por pagar); si es otra compra, confírmalo.')


def propuesta_compra(documento, *, hoy=None):
    """Lo que la pantalla y la API (§6.G) muestran antes de crear la compra: cabecera del XML, sugerencias (sin
    preseleccionar), importes del XML, líneas con su sugerencia, advertencias y bloqueos."""
    from core.importacion import servicios as sv
    from core.pos import compras
    hoy = hoy or timezone.localdate()
    comprobante = comprobante_completo(documento)
    proveedor = proveedor_del_documento(documento)
    lineas = lineas_para_compra(documento, comprobante, proveedor) if documento.cod_doc in CODIGOS_DE_COMPRA else []
    bloqueos = _bloqueos(documento, proveedor, lineas)
    regla = sv.reglas_de(documento.company)
    doc_mod, modificada = _compra_modificada(documento, proveedor, comprobante)
    forma_pago = '' if documento.cod_doc == '04' else forma_pago_del_xml(documento, comprobante)
    plazo = _plazo_dias(comprobante.get('pagos'))
    a_credito = plazo > 0 and documento.cod_doc != '04'
    sustento = SUSTENTO_SUGERIDO.get((regla.naturaleza_compra, regla.tratamiento_iva), '')
    if modificada is not None and modificada.cod_sustento:
        sustento = modificada.cod_sustento
    try:
        importes = importes_de_documento(documento)
    except DatoNoReconocido:
        importes = None
    advertencias = [dict(a) for a in (documento.advertencias or [])]

    def aviso(codigo, texto):
        if not any(a.get('codigo') == codigo for a in advertencias):
            advertencias.append({'codigo': codigo, 'texto': texto})

    if any(not l.cantidad_entera for l in lineas if not l.solo_gasto):
        aviso('cantidad_fraccionaria', 'Hay líneas con cantidad fraccionaria: regístralas como gasto o ajusta el stock a mano '
                                       '(no hay factor de conversión de unidades).')
    if any(l.origen_sugerencia != 'equivalencia' for l in lineas if not l.solo_gasto):
        aviso('sin_equivalencia', 'Hay líneas sin un producto recordado para este proveedor: elige el producto o regístralas '
                                  'como gasto.')
    if len(lineas) > MAX_LINEAS:
        aviso('muchas_lineas', f'La factura tiene {len(lineas)} líneas: se registra agrupada por tarifa (máximo {MAX_LINEAS} '
                               'líneas por compra).')
    if doc_mod is not None and modificada is None:
        aviso('doc_modificado_sin_compra', 'No se encontró la compra que modifica esta nota: queda sin enlazar y la compra '
                                           'quedará con datos incompletos (autorización del documento modificado).')
    if importes is not None and importes['total'] > UMBRAL_BANCARIZACION and forma_pago == '01':
        aviso('bancarizacion', 'Un pago de más de USD 1.000 sin el sistema financiero no da crédito tributario de IVA ni es '
                               'deducible.')
    for linea in lineas:
        for codigo, texto in linea.advertencias:
            aviso(codigo, texto)
    confirmaciones = []
    if documento.fecha_emision and (hoy - documento.fecha_emision).days > PLAZO_ATS_DIAS:
        confirmaciones.append('confirmar_plazo_ats')
    parecidas = _posibles_duplicadas(documento, proveedor)
    if parecidas:
        aviso('posible_duplicado', _texto_posible_duplicado(parecidas))
        confirmaciones.append('confirmar_no_duplicada')
    return {
        'tipo_comprobante': documento.cod_doc, 'numero': documento.numero, 'estab': documento.estab, 'pto_emi': documento.pto_emi,
        'secuencial': documento.secuencial, 'autorizacion': documento.clave_acceso,
        'fecha_emision': documento.fecha_emision.isoformat() if documento.fecha_emision else None,
        'proveedor': ({'id': proveedor.pk, 'nombre': proveedor.name, 'ruc': proveedor.ruc,
                       'tipo_identificacion': proveedor.tipo_identificacion} if proveedor else None),
        'cod_sustento_sugerido': sustento or None, 'nombre_sustento_sugerido': dict(SUSTENTOS).get(sustento),
        'forma_pago_del_xml': forma_pago or None,
        'payment_type_sugerido': 'credito' if a_credito else 'efectivo',
        'end_credit_sugerido': (hoy + timedelta(days=plazo)).isoformat() if a_credito else None,
        'parte_relacionada': proveedor.parte_relacionada if proveedor else None,
        'doc_modificado': ({k: (v.isoformat() if isinstance(v, date) else v) for k, v in doc_mod.items()} if doc_mod else None),
        'compra_modificada': ({'id': modificada.pk, 'numero': modificada.numero_comprobante,
                               'base_calculo': _base_calculo(modificada)} if modificada else None),
        'importes': {k: f'{v:.2f}' for k, v in importes.items() if k != 'subtotal'} if importes else None,
        'subtotal': f'{importes["subtotal"]:.2f}' if importes else None,
        'lineas': [l.como_dict() for l in lineas],
        'por_tarifa': [{**g, 'tarifa': compras.texto_importe(g['tarifa']), 'base': compras.texto_importe(g['base']),
                        'valor': compras.texto_importe(g['valor'])}
                       for g in compras.resumen_por_tarifa([_linea_de_compra(l, 'gasto') for l in lineas])],
        'agrupar_obligatorio': len(lineas) > MAX_LINEAS or documento.cod_doc in ('04', '05'),
        'exige_confirmar_sin_verificar': (documento.estado_verificacion != 'verificada_sri' and regla.exigir_verificacion),
        'confirmaciones': confirmaciones,
        'advertencias': advertencias, 'bloqueos': bloqueos,
        'textos': [TEXTOS['importes_del_xml'], TEXTOS['notas_sin_stock'] if documento.cod_doc in ('04', '05') else TEXTOS['stock']],
    }


def _base_calculo(compra):
    from core.pos.models import DebtsPay
    deuda = DebtsPay.objects.filter(purchase=compra).order_by('pk').first()
    return deuda.base_calculo if deuda else None


# ------------------------------------------------------------------ crear la compra

def _elecciones(lineas, elegidas):
    """{indice: {modo, product, type_expense, recordar}} validadas contra las líneas del documento."""
    indices = {l.indice for l in lineas}
    elecciones = {}
    for eleccion in elegidas or []:
        if not isinstance(eleccion, dict):
            raise _error('Las líneas de la compra no tienen un formato válido.')
        try:
            indice = int(eleccion.get('indice'))
        except (TypeError, ValueError):
            raise _error('Las líneas de la compra no tienen un formato válido.')
        if indice not in indices or indice in elecciones:
            raise _error('Las líneas elegidas no corresponden a las del documento.')
        modo = _texto(eleccion.get('modo')) or 'gasto'
        if modo not in ('producto', 'gasto'):
            raise _error(f'Línea {indice + 1}: modo no válido.')
        elecciones[indice] = {'modo': modo, 'product': eleccion.get('product'), 'type_expense': eleccion.get('type_expense'),
                              'recordar': _texto(eleccion.get('recordar')).lower() in ('1', 'true', 'on', 'si', 'sí')}
    return elecciones


def _id(valor):
    try:
        return int(valor) if valor not in (None, '') else None
    except (TypeError, ValueError):
        raise _error('Identificador no válido.')


def _lineas_e_importes(documento, lineas, comprobante, datos):
    """(líneas para crear_compra, equivalencias a recordar [(código, producto)])."""
    from core.pos.models import Product, TypeExpense
    agrupar = _texto(datos.get('agrupar_por_tarifa')).lower() in ('1', 'true', 'on', 'si', 'sí')
    if documento.cod_doc in ('04', '05'):
        agrupar = True
    if len(lineas) > MAX_LINEAS and not agrupar:
        raise _error(f'La factura tiene {len(lineas)} líneas: agrúpalas por tarifa (una compra admite hasta {MAX_LINEAS}).')
    if agrupar:
        tipo_gasto_id = _id(datos.get('type_expense'))
        tipo_gasto = TypeExpense.objects.filter(pk=tipo_gasto_id).first() if tipo_gasto_id else None
        if tipo_gasto_id and tipo_gasto is None:
            raise _error('El tipo de gasto no existe.')
        return [_linea_de_compra(l, 'gasto', tipo_gasto=tipo_gasto) for l in _agrupar(documento, lineas, comprobante)], []
    elecciones = _elecciones(lineas, datos.get('lineas'))
    resultado, recordar = [], []
    for linea in lineas:
        eleccion = elecciones.get(linea.indice, {'modo': 'gasto', 'product': None, 'type_expense': None, 'recordar': False})
        tipo_gasto_id = _id(eleccion['type_expense'])
        tipo_gasto = TypeExpense.objects.filter(pk=tipo_gasto_id).first() if tipo_gasto_id else None
        if tipo_gasto_id and tipo_gasto is None:
            raise _error(f'Línea {linea.indice + 1}: el tipo de gasto no existe.')
        if eleccion['modo'] == 'producto':
            if not linea.cantidad_entera:
                raise _error(f'La línea {linea.indice + 1} tiene cantidad {_numero_es(linea.cantidad)}: regístrala como gasto o '
                             'ajusta el stock a mano.')
            producto_id = _id(eleccion['product'])
            producto = Product.objects.filter(pk=producto_id).first() if producto_id else None   # solo de la empresa activa
            if producto is None:
                raise _error(f'Línea {linea.indice + 1}: elige un producto de la empresa.')
            resultado.append(_linea_de_compra(linea, 'producto', producto=producto, tipo_gasto=tipo_gasto))
            if eleccion['recordar'] and linea.codigo_principal:
                recordar.append((linea.codigo_principal, producto))
        else:
            resultado.append(_linea_de_compra(linea, 'gasto', tipo_gasto=tipo_gasto))
    return resultado, recordar


def _si_no(valor):
    if valor is None or isinstance(valor, bool):
        return valor
    texto = _texto(valor).lower()
    return True if texto in ('si', 'sí', 'true', '1') else False if texto in ('no', 'false', '0') else None


def crear_compra_desde_documento(documento, usuario, datos):
    """Crea la compra desde el documento importado (§3.6) en una sola transacción: bloquea el documento sin compra, crea
    el proveedor si hace falta, registra la compra con los importes del XML (el stock se mueve una sola vez, dentro de
    crear_compra) y vincula el documento con una actualización condicionada que debe afectar exactamente una fila."""
    from core.importacion import servicios as sv
    from core.importacion.models import DocumentoImportado, EquivalenciaProducto
    from core.pos import compras
    datos = datos or {}
    regla = sv.reglas_de(documento.company)
    hoy = timezone.localdate()
    with transaction.atomic():
        documento = DocumentoImportado.objects.select_for_update(of=('self',)).filter(pk=documento.pk).first()
        if documento is None:
            raise _error('El documento ya no existe.')
        if documento.compra_id:
            raise _error(f'Ya se creó la compra #{documento.compra_id} desde este documento.', 'ya_vinculado')
        comprobante = comprobante_completo(documento)
        proveedor = proveedor_del_documento(documento)
        lineas = lineas_para_compra(documento, comprobante, proveedor) if documento.cod_doc in CODIGOS_DE_COMPRA else []
        bloqueos = _bloqueos(documento, proveedor, lineas)
        if bloqueos:
            raise _error(bloqueos[0]['texto'], bloqueos[0]['codigo'])
        sv._exigir_revisable(documento, regla, datos)
        parecidas = _posibles_duplicadas(documento, proveedor)
        if parecidas and _si_no(datos.get('confirmar_no_duplicada')) is not True:
            raise _error(_texto_posible_duplicado(parecidas), 'confirmar_no_duplicada')
        if proveedor is None:
            nuevo = dict(datos.get('proveedor_nuevo') or {})
            nuevo.setdefault('parte_relacionada', datos.get('parte_relacionada'))
            proveedor = sv.crear_proveedor_de_documento(documento, nuevo)
        parte = _si_no(datos.get('parte_relacionada')) if _texto(datos.get('parte_relacionada')) else proveedor.parte_relacionada
        doc_mod, modificada = _compra_modificada(documento, proveedor, comprobante)
        pagos = comprobante.get('pagos')
        plazo = _plazo_dias(pagos)
        payment_type = _texto(datos.get('payment_type')) or ('credito' if plazo > 0 else 'efectivo')
        end_credit = _texto(datos.get('end_credit')) or ((hoy + timedelta(days=plazo)).isoformat() if plazo > 0 else '')
        forma_pago = datos.get('forma_pago') if 'forma_pago' in datos else forma_pago_del_xml(documento, comprobante)
        cabecera = {
            'provider': proveedor.pk, 'modo_comprobante': 'si', 'tipo_comprobante': documento.cod_doc,
            'cod_sustento': _texto(datos.get('cod_sustento')), 'estab': documento.estab, 'pto_emi': documento.pto_emi,
            'secuencial': documento.secuencial, 'autorizacion': documento.clave_acceso,
            'fecha_emision': documento.fecha_emision.isoformat() if documento.fecha_emision else '',
            'date_joined': _texto(datos.get('date_joined')) or hoy.isoformat(),
            'parte_relacionada': '' if parte is None else ('si' if parte else 'no'), 'payment_type': payment_type,
            'end_credit': end_credit, 'forma_pago': _texto(forma_pago), 'pago_loc_ext': '01',
            'confirmar_plazo_ats': datos.get('confirmar_plazo_ats'),
        }
        if doc_mod is not None:
            cabecera.update({k: (v.isoformat() if isinstance(v, date) else v) for k, v in doc_mod.items() if k != 'motivo'})
            cabecera['compra_modificada'] = modificada.pk if modificada else None
        lineas_compra, recordar = _lineas_e_importes(documento, lineas, comprobante, datos)
        importes = {**importes_de_documento(documento), 'lineas': lineas_compra}
        try:
            compra = compras.crear_compra(documento.company, usuario, cabecera, [], origen='importacion', importes=importes)
        except compras.ErrorCompra as e:
            raise _error(str(e), e.codigo) from e
        documento.proveedor = proveedor
        documento.compra = compra
        propuesta = sv.propuesta_contable(documento, regla)
        filas = DocumentoImportado.objects.filter(pk=documento.pk, compra__isnull=True, estado_revision='pendiente').update(
            compra=compra, proveedor=proveedor, estado_revision='vinculado', revisado_por=usuario, revisado_en=timezone.now(),
            propuesta_contable=propuesta, estado_contable='propuesta' if propuesta else 'sin_propuesta')
        if filas != 1:
            raise _error('Ya se creó una compra desde este documento.', 'ya_vinculado')
        for codigo, producto in recordar:
            EquivalenciaProducto.objects.update_or_create(
                proveedor=proveedor, codigo_proveedor=codigo, defaults={'producto': producto, 'creado_por': usuario})
            sv.evento('equivalencia_guardada', f'Código {codigo} del proveedor recordado como {producto.name}.',
                      documento=documento, usuario=usuario, codigo=codigo, producto=producto.pk)
        sv.evento('compra_creada', f'Compra #{compra.pk} creada desde el XML.', documento=documento, usuario=usuario,
                  compra=compra.pk)
    documento.refresh_from_db()
    compra.documento = documento
    return compra
