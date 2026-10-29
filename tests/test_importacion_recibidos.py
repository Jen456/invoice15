"""Importación de comprobantes recibidos distintos de la factura (espec-etapa2-compras §3.5, §3.7, §6.H y §6.J): lectura
de notas de crédito (04), notas de débito (05) y comprobantes de retención 07 (v1.0.0 y v2.0.0); clasificación; lectura
del 07 para «Retenciones recibidas» (RetencionLeida); marca idempotente del documento; pantalla «Registrar retención
recibida» con el servicio de Ventas (O2) sustituido; propuesta contable y filtro por tipo. Documentos ficticios."""
from datetime import date
from decimal import Decimal

import pytest

from core.importacion.xml_sri import procesar_xml_sri
from tests import fabricas_recibidos as r


def procesar(xml):
    return procesar_xml_sri(r.autorizacion(xml).encode())


def codigos(lista):
    return [m.codigo for m in lista]


class TestLectura:

    def test_factura_con_detalles_y_su_iva(self):
        lineas = (r.linea('P0', 'Producto con IVA', cantidad='2', precio='50.00', descuento='5.00'),
                  r.linea('T1', 'Turismo en feriado', precio='40.00', iva='8', tarifa='8'))
        res = procesar(r.factura(lineas=lineas))
        assert res.aceptado and res.advertencias == [], res.advertencias
        d0, d1 = res.comprobante.detalles
        assert d0['codigo_principal'] == 'P0' and d0['cantidad'] == Decimal('2') and d0['descuento'] == Decimal('5.00')
        assert d0['precio_total_sin_impuesto'] == Decimal('95.00') and d0['iva']['valor'] == Decimal('14.25')
        assert d1['iva'] == {'codigo_porcentaje': '8', 'tarifa': Decimal('8.00'), 'base_imponible': Decimal('40.00'),
                             'valor': Decimal('3.20')}
        assert res.to_dict()['comprobante']['detalles'][0]['precio_total_sin_impuesto'] == '95.00'   # texto en el JSON

    def test_nota_de_credito_recibida(self):
        res = procesar(r.nota_credito())
        assert res.aceptado and res.advertencias == [], res.advertencias
        c = res.comprobante
        assert c.cod_doc == '04' and c.tipo_documento == 'Nota de crédito' and c.numero == '001-002-000000050'
        assert c.receptor_identificacion == r.RUC_RECEPTOR and c.total_sin_impuestos == Decimal('20.00')
        assert c.valor_modificacion == c.importe_total == Decimal('23.00') and c.total_iva == Decimal('3.00')
        assert c.doc_modificado == {'cod_doc': '01', 'numero': '001-002-000000271', 'fecha_emision': date(2026, 10, 10),
                                    'motivo': 'Devolución de mercadería'}
        assert c.detalles[0]['codigo_principal'] == 'P0' and len(c.impuestos) == 1

    def test_nota_de_debito_recibida_y_motivos_descuadrados(self):
        res = procesar(r.nota_debito(motivos=(('Intereses por mora', '10.00'), ('Gastos de cobranza', '5.00'))))
        assert res.aceptado and res.advertencias == [], res.advertencias
        c = res.comprobante
        assert c.cod_doc == '05' and c.importe_total == Decimal('17.25') and c.total_iva == Decimal('2.25')
        assert c.motivos == [{'razon': 'Intereses por mora', 'valor': Decimal('10.00')},
                             {'razon': 'Gastos de cobranza', 'valor': Decimal('5.00')}]
        assert c.doc_modificado['numero'] == '001-002-000000271' and c.pagos[0]['forma_pago'] == '20'
        descuadrada = procesar(r.nota_debito(motivos=(('Intereses', '10.00'),), total_sin='12.00'))
        assert descuadrada.aceptado and 'motivos_descuadrados' in codigos(descuadrada.advertencias)

    def test_retencion_v2_con_dos_sustentos(self):
        sustentos = [r.sustento(), r.sustento(numero='001001000000124', fecha=date(2026, 10, 2),
                                              retenciones=(('1', '312', '50.00', '1.75', '0.88'),), total_sin='50.00',
                                              importe='57.50')]
        res = procesar(r.retencion_v2(sustentos=sustentos))
        assert res.aceptado and res.advertencias == [], res.advertencias
        c = res.comprobante
        assert c.cod_doc == '07' and c.emisor_ruc == r.RUC_AGENTE and c.receptor_identificacion == r.RUC_RECEPTOR
        assert c.total_sin_impuestos == c.total_iva == Decimal('0.00') and c.impuestos == []
        assert c.importe_total == Decimal('7.13')                       # 1,75 + 4,50 + 0,88: lo retenido
        ret = c.retencion
        assert ret['version'] == '2.0.0' and ret['periodo_fiscal'] == '10/2026' and ret['parte_rel'] == 'NO'
        assert [s['num_doc_sustento'] for s in ret['docs_sustento']] == ['001001000000123', '001001000000124']
        assert ret['docs_sustento'][0]['retenciones'][1] == {'codigo': '2', 'codigo_retencion': '725',
                                                            'base_imponible': Decimal('15.00'),
                                                            'porcentaje_retener': Decimal('30.00'),
                                                            'valor_retenido': Decimal('4.50')}

    def test_retencion_v1_agrupa_por_documento_sustento(self):
        lineas = r.LINEAS_RETENCION_V1 + (('1', '303', '200.00', '10.00', '20.00', '01', '001001000000200', date(2026, 10, 3)),)
        res = procesar(r.retencion_v1(lineas=lineas))
        assert res.aceptado and res.advertencias == [], res.advertencias
        ret = res.comprobante.retencion
        assert ret['version'] == '1.0.0' and len(ret['docs_sustento']) == 2
        primero = ret['docs_sustento'][0]
        assert primero['num_doc_sustento'] == '001001000000123' and len(primero['retenciones']) == 2
        assert primero['cod_sustento'] == '' and primero['num_aut_doc_sustento'] == ''
        assert res.comprobante.importe_total == Decimal('26.25')

    def test_retencion_descuadrada(self):
        res = procesar(r.retencion_v2(sustentos=[r.sustento(retenciones=(('1', '312', '100.00', '1.75', '2.75'),))]))
        assert res.aceptado and codigos(res.advertencias) == ['retencion_descuadrada']

    def test_coherencia_de_la_clave_en_todos_los_tipos(self):
        for xml in (r.nota_credito(clave_acceso=r.clave(cod_doc='04', secuencial='000000999')),
                    r.retencion_v2(clave_acceso=r.clave(cod_doc='07', ruc=r.RUC_AGENTE, pto='001', secuencial='000000999'))):
            res = procesar(xml)
            assert not res.aceptado and codigos(res.errores) == ['clave_incoherente']
