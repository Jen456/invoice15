"""Comprobantes recibidos ficticios para las pruebas de importación (espec-etapa2-compras §7): factura con líneas y su IVA
por línea, nota de crédito (04, v1.1.0), nota de débito (05, v1.0.0), comprobante de retención 07 v1.0.0 y v2.0.0 (con
uno o varios documentos sustento) y tipos todavía no soportados (03, 06). Ningún documento real: RUC y claves de
tests/fabricas_sri.py; los XML siguen el orden de los XSD del repo (tests/xsd/).

Cada función devuelve el XML del comprobante sin autorización; las pruebas lo envuelven con `autorizacion(...)`.
Ventas (O2) y el integrador pueden importarla.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from xml.sax.saxutils import escape

from tests.fabricas_sri import RUC_EMISOR, RUC_RECEPTOR, autorizacion, clave

RUC_AGENTE = '0990000005001'          # cliente que retiene (emisor del 07)
TARIFAS = {'4': Decimal('15'), '2': Decimal('12'), '5': Decimal('5'), '0': Decimal('0'), '6': Decimal('0'), '7': Decimal('0')}
__all__ = ['RUC_AGENTE', 'RUC_EMISOR', 'RUC_RECEPTOR', 'autorizacion', 'clave', 'factura', 'linea', 'nota_credito',
           'nota_debito', 'retencion_v1', 'retencion_v2', 'sustento', 'no_soportado']


def _centavos(valor):
    return Decimal(valor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def linea(codigo='P0', descripcion='Producto ficticio', cantidad='1', precio='100.00', descuento='0.00', iva='4', tarifa=None,
          total=None, valor_iva=None, ice=None, auxiliar=''):
    """Línea de factura o de nota de crédito. `total` (precioTotalSinImpuesto) y `valor_iva` sustituyen al cálculo, para
    probar que mandan los importes del XML; `tarifa` es obligatoria con el código 8 (IVA diferenciado)."""
    tarifa = Decimal(tarifa) if tarifa is not None else TARIFAS[iva]
    total = _centavos(total if total is not None else Decimal(cantidad) * Decimal(precio) - Decimal(descuento))
    ice = _centavos(ice) if ice else None
    base_iva = total + (ice or Decimal('0'))
    valor = _centavos(valor_iva if valor_iva is not None else base_iva * tarifa / 100)
    return {'codigo': codigo, 'auxiliar': auxiliar, 'descripcion': descripcion, 'cantidad': cantidad, 'precio': precio,
            'descuento': descuento, 'iva': iva, 'tarifa': tarifa, 'total': total, 'base_iva': base_iva, 'valor_iva': valor,
            'ice': ice}


LINEAS_FACTURA = (linea('P0', 'Producto con IVA', precio='100.00'), linea('P1', 'Producto sin IVA', precio='20.00', iva='0'))


def _info_tributaria(cod_doc, ruc, razon, ambiente, estab, pto, secuencial, clave_acceso):
    return (f'<infoTributaria><ambiente>{ambiente}</ambiente><tipoEmision>1</tipoEmision><razonSocial>{escape(razon)}</razonSocial>'
            f'<nombreComercial>FICTICIO</nombreComercial><ruc>{ruc}</ruc><claveAcceso>{clave_acceso}</claveAcceso>'
            f'<codDoc>{cod_doc}</codDoc><estab>{estab}</estab><ptoEmi>{pto}</ptoEmi><secuencial>{secuencial}</secuencial>'
            f'<dirMatriz>Av. Ficticia 1</dirMatriz></infoTributaria>')


def _comprador(tipo, identificacion, nombre):
    return (f'<tipoIdentificacionComprador>{tipo}</tipoIdentificacionComprador>'
            f'<razonSocialComprador>{escape(nombre)}</razonSocialComprador>'
            f'<identificacionComprador>{identificacion}</identificacionComprador>')


def _impuesto_linea(codigo, porcentaje, tarifa, base, valor):
    """<impuesto> de un detalle (y del 05): codigo, codigoPorcentaje, tarifa, baseImponible, valor."""
    return (f'<impuesto><codigo>{codigo}</codigo><codigoPorcentaje>{porcentaje}</codigoPorcentaje><tarifa>{Decimal(tarifa):.2f}</tarifa>'
            f'<baseImponible>{base}</baseImponible><valor>{valor}</valor></impuesto>')


def _total_impuesto(codigo, porcentaje, tarifa, base, valor, factura=True):
    """<totalImpuesto>: en la factura lleva descuentoAdicional y tarifa; en la nota de crédito, solo base y valor."""
    if factura:
        return (f'<totalImpuesto><codigo>{codigo}</codigo><codigoPorcentaje>{porcentaje}</codigoPorcentaje>'
                f'<descuentoAdicional>0.00</descuentoAdicional><baseImponible>{base}</baseImponible>'
                f'<tarifa>{Decimal(tarifa):.2f}</tarifa><valor>{valor}</valor></totalImpuesto>')
    return (f'<totalImpuesto><codigo>{codigo}</codigo><codigoPorcentaje>{porcentaje}</codigoPorcentaje>'
            f'<baseImponible>{base}</baseImponible><valor>{valor}</valor></totalImpuesto>')


def _por_tarifa(lineas):
    """([(código, tarifa, base, valor)] sumados por código y tarifa, ICE total)."""
    grupos, ice = {}, Decimal('0.00')
    for item in lineas:
        base, valor = grupos.get((item['iva'], item['tarifa']), (Decimal('0.00'), Decimal('0.00')))
        grupos[(item['iva'], item['tarifa'])] = (base + item['base_iva'], valor + item['valor_iva'])
        ice += item['ice'] or Decimal('0.00')
    return [(c, t, b, v) for (c, t), (b, v) in grupos.items()], ice


def _detalles(lineas, principal='codigoPrincipal', auxiliar='codigoAuxiliar'):
    partes = []
    for item in lineas:
        impuestos = _impuesto_linea('2', item['iva'], item['tarifa'], item['base_iva'], item['valor_iva'])
        if item['ice']:
            impuestos += _impuesto_linea('3', '3051', '0', item['total'], item['ice'])
        codigo_aux = f'<{auxiliar}>{escape(item["auxiliar"])}</{auxiliar}>' if item['auxiliar'] else ''
        partes.append(f'<detalle><{principal}>{escape(item["codigo"])}</{principal}>{codigo_aux}'
                      f'<descripcion>{escape(item["descripcion"])}</descripcion><cantidad>{item["cantidad"]}</cantidad>'
                      f'<precioUnitario>{item["precio"]}</precioUnitario><descuento>{item["descuento"]}</descuento>'
                      f'<precioTotalSinImpuesto>{item["total"]}</precioTotalSinImpuesto><impuestos>{impuestos}</impuestos>'
                      f'</detalle>')
    return f'<detalles>{"".join(partes)}</detalles>'


def _pagos(pagos):
    """pagos: ((forma, total[, plazo[, unidad]]), …)."""
    partes = []
    for p in pagos:
        plazo = f'<plazo>{p[2]}</plazo><unidadTiempo>{p[3] if len(p) > 3 else "dias"}</unidadTiempo>' if len(p) > 2 and p[2] else ''
        partes.append(f'<pago><formaPago>{p[0]}</formaPago><total>{_centavos(p[1]):.2f}</total>{plazo}</pago>')
    return f'<pagos>{"".join(partes)}</pagos>'


def factura(lineas=LINEAS_FACTURA, ruc=RUC_EMISOR, razon='PROVEEDOR FICTICIO S.A.', receptor_tipo='04', receptor_id=RUC_RECEPTOR,
            receptor_nombre='EMPRESA RECEPTORA S.A.', fecha=date(2026, 10, 10), ambiente=2, estab='001', pto='002',
            secuencial='000000271', propina='0.00', importe=None, pagos=None, plazo=None, clave_acceso=None):
    """Factura (01, v2.1.0) con líneas y su IVA por línea. pagos=None: un pago 20 por el total (con `plazo` en días si se
    indica); pagos=(): sin pagos. `importe` sustituye al importe total calculado."""
    lineas = list(lineas)
    grupos, ice = _por_tarifa(lineas)
    total_sin = sum((item['total'] for item in lineas), Decimal('0.00'))
    descuento = sum((Decimal(item['descuento']) for item in lineas), Decimal('0.00'))
    calculado = total_sin + ice + sum((v for *_, v in grupos), Decimal('0.00')) + Decimal(propina)
    total = _centavos(importe) if importe is not None else calculado
    if pagos is None:
        pagos = (('20', total, plazo),)
    clave_acceso = clave_acceso or clave(fecha, '01', ruc, ambiente, estab, pto, secuencial)
    totales = ''.join(_total_impuesto('2', c, t, b, v) for c, t, b, v in grupos)
    if ice:
        totales += _total_impuesto('3', '3051', '0', total_sin, ice)
    return (f'<?xml version="1.0" encoding="UTF-8"?><factura id="comprobante" version="2.1.0">'
            f'{_info_tributaria("01", ruc, razon, ambiente, estab, pto, secuencial, clave_acceso)}'
            f'<infoFactura><fechaEmision>{fecha:%d/%m/%Y}</fechaEmision><dirEstablecimiento>Av. Ficticia 1</dirEstablecimiento>'
            f'<obligadoContabilidad>SI</obligadoContabilidad>{_comprador(receptor_tipo, receptor_id, receptor_nombre)}'
            f'<totalSinImpuestos>{total_sin:.2f}</totalSinImpuestos><totalDescuento>{descuento:.2f}</totalDescuento>'
            f'<totalConImpuestos>{totales}</totalConImpuestos><propina>{propina}</propina><importeTotal>{total:.2f}</importeTotal>'
            f'<moneda>DOLAR</moneda>{_pagos(pagos) if pagos else ""}</infoFactura>{_detalles(lineas)}'
            f'<infoAdicional><campoAdicional nombre="Email">compras@example.com</campoAdicional></infoAdicional></factura>')


def nota_credito(lineas=(linea('P0', 'Devolución de producto', precio='20.00'),), ruc=RUC_EMISOR, razon='PROVEEDOR FICTICIO S.A.',
                 receptor_id=RUC_RECEPTOR, fecha=date(2026, 10, 15), ambiente=2, estab='001', pto='002', secuencial='000000050',
                 cod_doc_modificado='01', doc_modificado='001-002-000000271', fecha_doc=date(2026, 10, 10),
                 motivo='Devolución de mercadería', valor=None, clave_acceso=None):
    """Nota de crédito (04, v1.1.0) del proveedor sobre el comprobante `doc_modificado`."""
    lineas = list(lineas)
    grupos, _ = _por_tarifa(lineas)
    total_sin = sum((item['total'] for item in lineas), Decimal('0.00'))
    total = _centavos(valor) if valor is not None else total_sin + sum((v for *_, v in grupos), Decimal('0.00'))
    clave_acceso = clave_acceso or clave(fecha, '04', ruc, ambiente, estab, pto, secuencial)
    totales = ''.join(_total_impuesto('2', c, t, b, v, factura=False) for c, t, b, v in grupos)
    return (f'<?xml version="1.0" encoding="UTF-8"?><notaCredito id="comprobante" version="1.1.0">'
            f'{_info_tributaria("04", ruc, razon, ambiente, estab, pto, secuencial, clave_acceso)}'
            f'<infoNotaCredito><fechaEmision>{fecha:%d/%m/%Y}</fechaEmision><dirEstablecimiento>Av. Ficticia 1</dirEstablecimiento>'
            f'{_comprador("04", receptor_id, "EMPRESA RECEPTORA S.A.")}<obligadoContabilidad>SI</obligadoContabilidad>'
            f'<codDocModificado>{cod_doc_modificado}</codDocModificado><numDocModificado>{doc_modificado}</numDocModificado>'
            f'<fechaEmisionDocSustento>{fecha_doc:%d/%m/%Y}</fechaEmisionDocSustento>'
            f'<totalSinImpuestos>{total_sin:.2f}</totalSinImpuestos><valorModificacion>{total:.2f}</valorModificacion>'
            f'<moneda>DOLAR</moneda><totalConImpuestos>{totales}</totalConImpuestos><motivo>{escape(motivo)}</motivo>'
            f'</infoNotaCredito>{_detalles(lineas, "codigoInterno", "codigoAdicional")}</notaCredito>')


def nota_debito(motivos=(('Intereses por mora', '10.00'),), iva='4', tarifa=None, ruc=RUC_EMISOR, razon='PROVEEDOR FICTICIO S.A.',
                receptor_id=RUC_RECEPTOR, fecha=date(2026, 10, 20), ambiente=2, estab='001', pto='002', secuencial='000000060',
                cod_doc_modificado='01', doc_modificado='001-002-000000271', fecha_doc=date(2026, 10, 10), total_sin=None,
                pagos=None, plazo=None, clave_acceso=None):
    """Nota de débito (05, v1.0.0): motivos (razón, valor), un impuesto de IVA sobre el total sin impuestos (por defecto la
    suma de los motivos) y un pago por el total (con `plazo` en días si se indica; pagos=() sin pagos)."""
    tarifa = Decimal(tarifa) if tarifa is not None else TARIFAS[iva]
    suma = sum((Decimal(v) for _, v in motivos), Decimal('0.00'))
    total_sin = _centavos(total_sin) if total_sin is not None else suma
    valor_iva = _centavos(total_sin * tarifa / 100)
    total = total_sin + valor_iva
    if pagos is None:
        pagos = (('20', total, plazo),)
    clave_acceso = clave_acceso or clave(fecha, '05', ruc, ambiente, estab, pto, secuencial)
    razones = ''.join(f'<motivo><razon>{escape(r)}</razon><valor>{v}</valor></motivo>' for r, v in motivos)
    return (f'<?xml version="1.0" encoding="UTF-8"?><notaDebito id="comprobante" version="1.0.0">'
            f'{_info_tributaria("05", ruc, razon, ambiente, estab, pto, secuencial, clave_acceso)}'
            f'<infoNotaDebito><fechaEmision>{fecha:%d/%m/%Y}</fechaEmision><dirEstablecimiento>Av. Ficticia 1</dirEstablecimiento>'
            f'{_comprador("04", receptor_id, "EMPRESA RECEPTORA S.A.")}<obligadoContabilidad>SI</obligadoContabilidad>'
            f'<codDocModificado>{cod_doc_modificado}</codDocModificado><numDocModificado>{doc_modificado}</numDocModificado>'
            f'<fechaEmisionDocSustento>{fecha_doc:%d/%m/%Y}</fechaEmisionDocSustento><totalSinImpuestos>{total_sin:.2f}</totalSinImpuestos>'
            f'<impuestos>{_impuesto_linea("2", iva, tarifa, f"{total_sin:.2f}", f"{valor_iva:.2f}")}</impuestos>'
            f'<valorTotal>{total:.2f}</valorTotal>{_pagos(pagos) if pagos else ""}</infoNotaDebito>'
            f'<motivos>{razones}</motivos></notaDebito>')


def _sujeto_retenido(receptor_id, nombre, tipo='04', tipo_sujeto=None, parte_rel=None):
    return (f'<tipoIdentificacionSujetoRetenido>{tipo}</tipoIdentificacionSujetoRetenido>'
            + (f'<tipoSujetoRetenido>{tipo_sujeto}</tipoSujetoRetenido>' if tipo_sujeto else '')
            + (f'<parteRel>{parte_rel}</parteRel>' if parte_rel else '')
            + f'<razonSocialSujetoRetenido>{escape(nombre)}</razonSocialSujetoRetenido>'
              f'<identificacionSujetoRetenido>{receptor_id}</identificacionSujetoRetenido>')


def sustento(numero='001001000000123', fecha=date(2026, 10, 1), autorizacion_='', cod_sustento='01', cod_doc='01',
             retenciones=(('1', '312', '100.00', '1.75', '1.75'), ('2', '725', '15.00', '30.00', '4.50')),
             total_sin='100.00', importe='115.00'):
    """Documento sustento de un 07 v2.0.0. retenciones = ((código de impuesto, código de retención, base, %, valor), …)."""
    return {'numero': numero, 'fecha': fecha, 'autorizacion': autorizacion_, 'cod_sustento': cod_sustento, 'cod_doc': cod_doc,
            'retenciones': tuple(retenciones), 'total_sin': total_sin, 'importe': importe}


def _cabecera_07(version, ruc, razon, ambiente, estab, pto, secuencial, clave_acceso, fecha, periodo, sujeto):
    return (f'<?xml version="1.0" encoding="UTF-8"?><comprobanteRetencion id="comprobante" version="{version}">'
            f'{_info_tributaria("07", ruc, razon, ambiente, estab, pto, secuencial, clave_acceso)}'
            f'<infoCompRetencion><fechaEmision>{fecha:%d/%m/%Y}</fechaEmision><dirEstablecimiento>Av. Ficticia 2</dirEstablecimiento>'
            f'<obligadoContabilidad>SI</obligadoContabilidad>{sujeto}<periodoFiscal>{periodo or f"{fecha:%m/%Y}"}</periodoFiscal>'
            f'</infoCompRetencion>')


def retencion_v2(sustentos=None, ruc=RUC_AGENTE, razon='CLIENTE AGENTE DE RETENCION S.A.', receptor_id=RUC_RECEPTOR,
                 receptor_nombre='EMPRESA RECEPTORA S.A.', fecha=date(2026, 10, 5), ambiente=2, estab='001', pto='001',
                 secuencial='000000010', periodo=None, parte_rel='NO', clave_acceso=None):
    """Comprobante de retención 07 v2.0.0 que recibe la empresa (sujeto retenido) de su cliente (agente de retención), con
    uno o varios documentos sustento (`sustento(...)`)."""
    sustentos = sustentos if sustentos is not None else [sustento()]
    clave_acceso = clave_acceso or clave(fecha, '07', ruc, ambiente, estab, pto, secuencial)
    docs = ''
    for s in sustentos:
        retenciones = ''.join(f'<retencion><codigo>{c}</codigo><codigoRetencion>{r}</codigoRetencion><baseImponible>{b}</baseImponible>'
                              f'<porcentajeRetener>{p}</porcentajeRetener><valorRetenido>{v}</valorRetenido></retencion>'
                              for c, r, b, p, v in s['retenciones'])
        autorizacion_doc = f'<numAutDocSustento>{s["autorizacion"]}</numAutDocSustento>' if s['autorizacion'] else ''
        docs += (f'<docSustento><codSustento>{s["cod_sustento"]}</codSustento><codDocSustento>{s["cod_doc"]}</codDocSustento>'
                 f'<numDocSustento>{s["numero"]}</numDocSustento><fechaEmisionDocSustento>{s["fecha"]:%d/%m/%Y}</fechaEmisionDocSustento>'
                 f'{autorizacion_doc}<pagoLocExt>01</pagoLocExt><totalSinImpuestos>{s["total_sin"]}</totalSinImpuestos>'
                 f'<importeTotal>{s["importe"]}</importeTotal><impuestosDocSustento><impuestoDocSustento>'
                 f'<codImpuestoDocSustento>2</codImpuestoDocSustento><codigoPorcentaje>4</codigoPorcentaje>'
                 f'<baseImponible>{s["total_sin"]}</baseImponible><tarifa>15.00</tarifa><valorImpuesto>15.00</valorImpuesto>'
                 f'</impuestoDocSustento></impuestosDocSustento><retenciones>{retenciones}</retenciones>'
                 f'<pagos><pago><formaPago>20</formaPago><total>{s["importe"]}</total></pago></pagos></docSustento>')
    sujeto = _sujeto_retenido(receptor_id, receptor_nombre, tipo_sujeto='02', parte_rel=parte_rel)
    return (_cabecera_07('2.0.0', ruc, razon, ambiente, estab, pto, secuencial, clave_acceso, fecha, periodo, sujeto)
            + f'<docsSustento>{docs}</docsSustento></comprobanteRetencion>')


LINEAS_RETENCION_V1 = (('1', '312', '100.00', '1.75', '1.75', '01', '001001000000123', date(2026, 10, 1)),
                       ('2', '725', '15.00', '30.00', '4.50', '01', '001001000000123', date(2026, 10, 1)))


def retencion_v1(lineas=LINEAS_RETENCION_V1, ruc=RUC_AGENTE, razon='CLIENTE AGENTE DE RETENCION S.A.', receptor_id=RUC_RECEPTOR,
                 receptor_nombre='EMPRESA RECEPTORA S.A.', fecha=date(2026, 10, 5), ambiente=2, estab='001', pto='001',
                 secuencial='000000011', periodo=None, clave_acceso=None):
    """Comprobante de retención 07 v1.0.0: una lista de impuestos con el documento sustento en cada línea
    ((código, código de retención, base, %, valor, codDocSustento, numDocSustento, fecha), …)."""
    clave_acceso = clave_acceso or clave(fecha, '07', ruc, ambiente, estab, pto, secuencial)
    impuestos = ''.join(f'<impuesto><codigo>{c}</codigo><codigoRetencion>{r}</codigoRetencion><baseImponible>{b}</baseImponible>'
                        f'<porcentajeRetener>{p}</porcentajeRetener><valorRetenido>{v}</valorRetenido>'
                        f'<codDocSustento>{cd}</codDocSustento><numDocSustento>{n}</numDocSustento>'
                        f'<fechaEmisionDocSustento>{fs:%d/%m/%Y}</fechaEmisionDocSustento></impuesto>'
                        for c, r, b, p, v, cd, n, fs in lineas)
    sujeto = _sujeto_retenido(receptor_id, receptor_nombre)
    return (_cabecera_07('1.0.0', ruc, razon, ambiente, estab, pto, secuencial, clave_acceso, fecha, periodo, sujeto)
            + f'<impuestos>{impuestos}</impuestos></comprobanteRetencion>')


def no_soportado(cod_doc='03', ruc=RUC_EMISOR, fecha=date(2026, 10, 10), secuencial='000000077'):
    """Liquidación de compra (03) o guía de remisión (06) mínima: se rechaza como «tipo no soportado» antes de leerla."""
    raiz = {'03': 'liquidacionCompra', '06': 'guiaRemision'}[cod_doc]
    clave_acceso = clave(fecha, cod_doc, ruc, 2, '001', '002', secuencial)
    return (f'<?xml version="1.0" encoding="UTF-8"?><{raiz} id="comprobante" version="1.1.0">'
            f'{_info_tributaria(cod_doc, ruc, "PROVEEDOR FICTICIO S.A.", 2, "001", "002", secuencial, clave_acceso)}</{raiz}>')
