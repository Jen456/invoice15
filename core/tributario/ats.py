"""ATS (Anexo Transaccional Simplificado) del mes: XML validado contra el esquema oficial del SRI (entrega D).

Qué genera (NORMA-CONTABLE-TRIBUTARIA-2026-10.md §3 y PLAN §3.6):
- Cabecera: tipo e identificación del informante, razón social, año, mes, número de establecimientos activos y código
  operativo IVA.
- Compras (`detalleCompras`): las compras REGISTRADAS en el mes (fechaRegistro = fecha de registro; el DIMM rechaza
  registros a más de un año de la emisión), con sus datos del ATS completos (Etapa 2: sustento, proveedor, comprobante,
  autorización, forma de pago, parte relacionada). Una compra con datos por completar no se inventa: queda fuera, con su
  motivo y su enlace.
- Retenciones: la norma del proyecto registra que, desde 2018, las retenciones electrónicas no se reportan en compras; las
  que emite esta aplicación son electrónicas, así que los valores retenidos van en 0.00 y sin `air`. Queda como advertencia
  para que el contador lo confirme.

Qué NO incluye, por reglas sin confirmar en la ficha técnica (PLAN §3.6): ventas electrónicas en `ventasEstablecimiento` y
`totalVentas`, y anulados electrónicos. El esquema las admite como opcionales; se informan como advertencias. Tampoco los
pagos al exterior, cuyos datos (régimen, país) la aplicación todavía no registra: esas compras quedan fuera con su motivo.

La validación contra el XSD es técnica: no equivale a la aceptación del SRI ni del DIMM. Se registran la fuente, la fecha y
la huella SHA-256 del esquema usado.
"""
import hashlib
import io
import re
import unicodedata
import zipfile
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from lxml import etree

from core.tributario import libros as lb

ESQUEMA = Path(__file__).resolve().parent / 'esquemas' / 'ats.xsd'
FUENTE_ESQUEMA = {
    'archivo': 'core/tributario/esquemas/ats.xsd',
    'url': 'https://descargas.sri.gob.ec/download/anexos/ats/ats.xsd',
    'publicado': '02/12/2020 (página de descargas del SRI; NORMA-CONTABLE-TRIBUTARIA-2026-10.md, fuente 4)',
    'descargado': '2026-11-02',
    'sha256': '4756fe58c139aff5073137ca3b2e66f7a6a55b096861c682b007d5f99b276a9a',
}
GRAVADAS = ('4', '5', '2', '3', '10', '8')
ADVERTENCIAS_FIJAS = [
    {'codigo': 'retenciones_electronicas', 'texto': 'Las retenciones que emite la aplicación son electrónicas: según la norma registrada '
     'en el proyecto, desde 2018 no se reportan en compras. Los valores retenidos van en 0.00 y sin el detalle «air». Confírmalo con tu '
     'contador antes de presentar.'},
    {'codigo': 'ventas_sin_confirmar', 'texto': 'No se incluyen ventas, ventas por establecimiento ni total de ventas: las ventas '
     'electrónicas no van en el detalle de ventas (Res. NAC-DGERCGC16-00000092) y falta confirmar si deben ir en «ventasEstablecimiento» '
     'y «totalVentas». Pendiente de verificar con la ficha técnica y el DIMM 1.19.0.'},
    {'codigo': 'anulados_sin_confirmar', 'texto': 'No se incluyen comprobantes anulados: falta confirmar cómo se reportan los anulados '
     'electrónicos. Pendiente de verificar con la ficha técnica.'},
    {'codigo': 'validacion_tecnica', 'texto': 'La validación contra el esquema es técnica: no equivale a la aceptación del SRI ni del '
     'DIMM. Revisa el archivo con tu contador antes de presentarlo.'},
]


class ErrorEsquema(RuntimeError):
    pass


@lru_cache(maxsize=1)
def esquema():
    contenido = ESQUEMA.read_bytes()
    if hashlib.sha256(contenido).hexdigest() != FUENTE_ESQUEMA['sha256']:
        raise ErrorEsquema('El esquema del ATS guardado no coincide con su huella registrada: no se valida con un esquema alterado.')
    return etree.XMLSchema(etree.fromstring(contenido, parser=etree.XMLParser(resolve_entities=False, no_network=True)))


def texto_ats(texto, maximo=300):
    """Solo letras, números y espacios (patrón del XSD para razón social y denominación): sin tildes ni signos."""
    texto = unicodedata.normalize('NFKD', str(texto or ''))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r'[^A-Za-z0-9\s]+', ' ', texto)
    return ' '.join(texto.split()).upper()[:maximo]


def _fecha(valor):
    return valor.strftime('%d/%m/%Y')


def _m(valor):
    return f'{Decimal(str(valor or 0)):.2f}'


def _sub(padre, nombre, texto):
    nodo = etree.SubElement(padre, nombre)
    nodo.text = str(texto)
    return nodo


def _partes(numero):
    """'001-002-000000123' (o 15 dígitos) → ('001', '002', '000000123'), o None."""
    digitos = re.sub(r'\D', '', numero or '')
    if len(digitos) != 15:
        return None
    return digitos[:3], digitos[3:6], digitos[6:]


def _motivos_compra(compra, grupos):
    """Lo que impide incluir la compra (texto por motivo); vacío = se incluye."""
    motivos = [texto for _, texto in compra.faltantes()]
    if any(not g['codigo'] for g in grupos) or not grupos:
        motivos.append('Sus líneas no tienen la tarifa de IVA (compra antigua): completa sus datos.')
    if compra.pago_loc_ext == '02':
        motivos.append('Pago al exterior: la aplicación todavía no registra el régimen y el país del pago que exige el ATS.')
    if compra.tipo_comprobante in ('04', '05'):
        if _partes(compra.num_doc_modificado) is None:
            motivos.append('Falta el número completo del comprobante que modifica (establecimiento, punto y secuencial).')
        if not compra.tipo_doc_modificado or not compra.aut_doc_modificado:
            motivos.append('Faltan el tipo o la autorización del comprobante que modifica.')
    if compra.provider.tipo_id_ats == '03' and not compra.provider.tipo_sujeto:
        motivos.append('El proveedor con pasaporte o identificación del exterior necesita el tipo de sujeto (persona natural o sociedad).')
    if not texto_ats(compra.provider.name) and compra.provider.tipo_id_ats == '03':
        motivos.append('La razón social del proveedor no tiene letras ni números válidos para el ATS.')
    return motivos


def _detalle_compra(padre, compra, grupos):
    bases = {}
    for g in grupos:
        bases[g['codigo']] = bases.get(g['codigo'], Decimal('0')) + Decimal(str(g['base']))
    iva = sum((Decimal(str(g['valor'])) for g in grupos if g['valor'] is not None and g['codigo'] in GRAVADAS), Decimal('0'))
    proveedor = compra.provider
    d = etree.SubElement(padre, 'detalleCompras')
    _sub(d, 'codSustento', compra.cod_sustento)
    _sub(d, 'tpIdProv', proveedor.tipo_id_ats)
    _sub(d, 'idProv', proveedor.ruc)
    _sub(d, 'tipoComprobante', compra.tipo_comprobante)
    if proveedor.tipo_id_ats == '03':
        _sub(d, 'tipoProv', proveedor.tipo_sujeto)
        _sub(d, 'denoProv', texto_ats(proveedor.name, 500))
    if compra.parte_relacionada is not None:
        _sub(d, 'parteRel', 'SI' if compra.parte_relacionada else 'NO')
    _sub(d, 'fechaRegistro', _fecha(compra.date_joined))
    _sub(d, 'establecimiento', compra.estab)
    _sub(d, 'puntoEmision', compra.pto_emi)
    _sub(d, 'secuencial', int(compra.secuencial))
    _sub(d, 'fechaEmision', _fecha(compra.fecha_emision))
    _sub(d, 'autorizacion', compra.autorizacion)
    _sub(d, 'baseNoGraIva', _m(bases.get('6')))
    _sub(d, 'baseImponible', _m(bases.get('0')))
    _sub(d, 'baseImpGrav', _m(sum((bases.get(c, Decimal('0')) for c in GRAVADAS), Decimal('0'))))
    _sub(d, 'baseImpExe', _m(bases.get('7')))
    _sub(d, 'montoIce', _m(compra.total_ice))
    _sub(d, 'montoIva', _m(iva))
    for campo in ('valRetBien10', 'valRetServ20', 'valorRetBienes', 'valRetServ50', 'valorRetServicios', 'valRetServ100'):
        _sub(d, campo, '0.00')   # retenciones electrónicas: no se reportan en compras (ADVERTENCIAS_FIJAS)
    _sub(d, 'totbasesImpReemb', '0.00')
    exterior = etree.SubElement(d, 'pagoExterior')
    _sub(exterior, 'pagoLocExt', '01')
    _sub(exterior, 'paisEfecPago', 'NA')
    _sub(exterior, 'aplicConvDobTrib', 'NA')
    _sub(exterior, 'pagExtSujRetNorLeg', 'NA')
    if compra.forma_pago:
        _sub(etree.SubElement(d, 'formasDePago'), 'formaPago', compra.forma_pago)
    if compra.tipo_comprobante in ('04', '05'):
        estab, punto, secuencial = _partes(compra.num_doc_modificado)
        _sub(d, 'docModificado', compra.tipo_doc_modificado)
        _sub(d, 'estabModificado', estab)
        _sub(d, 'ptoEmiModificado', punto)
        _sub(d, 'secModificado', secuencial)
        _sub(d, 'autModificado', compra.aut_doc_modificado)
    return d


def generar(inicio, company):
    """{xml, valido, errores_xsd, excluidas, incluidas, advertencias, esquema, nombre} del mes de la empresa activa."""
    from core.pos.compras import resumen_por_tarifa
    from core.pos.models import Establishment, Purchase
    raiz = etree.Element('iva')
    _sub(raiz, 'TipoIDInformante', 'R')
    _sub(raiz, 'IdInformante', company.ruc)
    _sub(raiz, 'razonSocial', texto_ats(company.business_name, 500))
    _sub(raiz, 'Anio', inicio.year)
    _sub(raiz, 'Mes', f'{inicio.month:02d}')
    establecimientos = Establishment.objects.filter(is_active=True).count()
    if establecimientos:
        _sub(raiz, 'numEstabRuc', f'{min(establecimientos, 999):03d}')
    _sub(raiz, 'codigoOperativo', 'IVA')
    incluidas, excluidas = [], []
    compras_nodo = etree.Element('compras')
    for compra in (Purchase.objects.select_related('provider').prefetch_related('purchasedetail_set')
                   .filter(lb._en_mes(inicio, 'date_joined')).order_by('date_joined', 'id')):
        grupos = resumen_por_tarifa(list(compra.purchasedetail_set.all()))
        referencia = {'id': compra.pk, 'numero': compra.numero_comprobante, 'proveedor': compra.provider.name,
                      'fecha_registro': compra.date_joined.isoformat(), 'url': f'/pos/purchase/complete/{compra.pk}/'}
        motivos = _motivos_compra(compra, grupos)
        if motivos:
            excluidas.append({**referencia, 'motivos': motivos})
            continue
        _detalle_compra(compras_nodo, compra, grupos)
        incluidas.append(referencia)
    if incluidas:
        raiz.append(compras_nodo)
    xml = etree.tostring(raiz, xml_declaration=True, encoding='UTF-8', standalone=False)
    try:
        validador = esquema()
        valido = validador.validate(etree.fromstring(xml))
        errores_xsd = [{'linea': e.line, 'mensaje': e.message} for e in validador.error_log]
    except ErrorEsquema as e:
        valido, errores_xsd = False, [{'linea': 0, 'mensaje': str(e)}]
    advertencias = list(ADVERTENCIAS_FIJAS)
    if getattr(company, 'rimpe', ''):
        advertencias.append({'codigo': 'rimpe', 'texto': 'La empresa está en el RIMPE: su ATS es semestral. Revisa el período antes de presentarlo.'})
    if excluidas:
        advertencias.append({'codigo': 'compras_excluidas', 'texto': f'{len(excluidas)} compras del mes quedaron fuera porque les faltan '
                             'datos del ATS: complétalas y vuelve a generar el archivo.'})
    return {'mes': f'{inicio:%Y-%m}', 'nombre': f'AT{inicio:%m%Y}', 'xml': xml, 'valido': valido, 'errores_xsd': errores_xsd,
            'incluidas': incluidas, 'excluidas': excluidas, 'advertencias': advertencias, 'esquema': FUENTE_ESQUEMA}


def comprimido(resultado):
    """ATmmaaaa.zip con ATmmaaaa.xml dentro (formato de entrega del ATS)."""
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'{resultado["nombre"]}.xml', resultado['xml'])
    return salida.getvalue()


def informe(resultado):
    """El resultado sin el XML (para la API y la pantalla)."""
    return {k: v for k, v in resultado.items() if k != 'xml'}
