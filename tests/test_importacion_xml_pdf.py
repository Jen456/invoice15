"""Importación — análisis de archivos (sin base de datos): XML del SRI (envolturas, espacios de nombres, ataques, claves,
tarifas, receptores, tipos no soportados), RIDE en PDF (QR, código de barras, texto, ambigüedad, límites) y la consulta de
autorización al SRI simulada. Todos los documentos son ficticios."""
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.importacion import clave_acceso, limites, ride_pdf, sri_autorizacion
from core.importacion.xml_sri import procesar_xml_sri, procesarXmlSri
from core.pos import emision
from tests import fabricas_sri as f


def procesar(xml):
    return procesar_xml_sri(xml.encode('utf-8') if isinstance(xml, str) else xml)


def codigos(lista):
    return [m.codigo for m in lista]


class TestClave:

    def test_digito_verificador_y_estructura(self):
        clave = f.clave()
        datos = clave_acceso.analizar(clave)
        assert datos.fecha_emision == date(2026, 10, 10) and datos.cod_doc == '01' and datos.ruc == f.RUC_EMISOR
        assert datos.ambiente == 2 and datos.numero == '001-002-000000271'
        malo = clave[:48] + str((int(clave[48]) + 1) % 10)
        with pytest.raises(clave_acceso.ClaveInvalida, match='dígito verificador'):
            clave_acceso.analizar(malo)
        with pytest.raises(clave_acceso.ClaveInvalida, match='49 dígitos'):
            clave_acceso.analizar(clave[:48])

    def test_candidatas_en_texto_y_urls(self):
        clave = f.clave()
        texto = f'https://srienlinea.sri.gob.ec/consulta?clave={clave}&x=1 y otra {clave[:48]}9 y 1234567890'
        assert clave_acceso.candidatas(texto) == [clave]


class TestEnvolturas:

    @pytest.mark.parametrize('nombre, xml', [
        ('cdata', lambda: f.autorizacion(f.factura())),
        ('escapado', lambda: f.autorizacion(f.factura(), modo='escapado')),
        ('hijo', lambda: f.autorizacion(f.factura(), modo='hijo')),
        ('respuesta', lambda: f.respuesta_sri([f.factura()])),
        ('soap', lambda: f.respuesta_sri([f.factura()], soap=True)),
        ('espacio_de_nombres', lambda: f.autorizacion(f.factura(ns='http://www.sri.gob.ec/factura'))),
    ])
    def test_autorizacion_declarada_en_todas_las_envolturas(self, nombre, xml):
        r = procesar(xml())
        assert r.aceptado, r.errores
        assert r.autorizacion_declarada == 'AUTORIZADO' and r.verificacion == 'declarada_en_archivo'
        c = r.comprobante
        assert c.clave_acceso == f.clave() and c.numero == '001-002-000000271' and c.fecha_emision == date(2026, 10, 10)
        assert c.importe_total == Decimal('135.00') and c.total_iva == Decimal('15.00') and c.receptor_tipo_nombre == 'RUC'
        assert r.numero_autorizacion == f.clave() and r.fecha_autorizacion is not None

    def test_comprobante_sin_autorizacion_queda_por_verificar(self):
        r = procesar(f.factura())
        assert r.aceptado and r.autorizacion_declarada is None and r.verificacion == 'sin_autorizacion'
        assert 'sin_autorizacion' in codigos(r.advertencias)

    def test_no_autorizado_se_rechaza(self):
        r = procesar(f.autorizacion(f.factura(), estado='NO AUTORIZADO'))
        assert not r.aceptado and codigos(r.errores) == ['no_autorizado']

    def test_varias_autorizaciones_distintas_son_ambiguas(self):
        r = procesar(f.respuesta_sri([f.factura(), f.factura(secuencial='000000272')]))
        assert not r.aceptado and codigos(r.errores) == ['ambiguo']

    def test_respuesta_sin_autorizaciones(self):
        r = procesar(f.respuesta_sri([]))
        assert not r.aceptado and codigos(r.errores) == ['sin_autorizaciones']

    def test_alias_y_serializacion_json(self):
        r = procesarXmlSri(f.autorizacion(f.factura()).encode())
        texto = json.dumps(r.to_dict())
        datos = json.loads(texto)['comprobante']
        assert datos['importe_total'] == '135.00' and datos['impuestos'][0]['base_imponible'] == '100.00'
        assert datos['fecha_emision'] == '2026-10-10'


class TestSeguridad:

    @pytest.mark.parametrize('xml, codigo', [
        ('<?xml version="1.0"?><!DOCTYPE a [<!ENTITY e SYSTEM "file:///etc/passwd">]><autorizacion><estado>&e;</estado></autorizacion>',
         'dtd_prohibida'),
        ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]><factura>&b;</factura>',
         'dtd_prohibida'),
        ('<?xml version="1.0"?><!doctype x SYSTEM "http://ejemplo.invalid/x.dtd"><factura/>', 'dtd_prohibida'),
        ('<autorizacion><estado>AUTORIZADO</estado>', 'xml_malformado'),
        ('esto no es xml', 'no_es_xml'),
        ('', 'vacio'),
        ('<raiz>' + '<a>' * (limites.MAX_PROFUNDIDAD_XML + 5) + '</a>' * (limites.MAX_PROFUNDIDAD_XML + 5) + '</raiz>', 'xml_excesivo'),
        ('<raiz>' + '<a/>' * (limites.MAX_ELEMENTOS_XML + 10) + '</raiz>', 'xml_excesivo'),
        ('<?xml version="1.0"?><cualquiera><cosa/></cualquiera>', 'estructura_desconocida'),
    ])
    def test_ataques_y_malformados(self, xml, codigo):
        r = procesar(xml)
        assert not r.aceptado and codigo in codigos(r.errores)

    def test_xxe_dentro_del_cdata_tambien_se_rechaza(self):
        interno = '<?xml version="1.0"?><!DOCTYPE f [<!ENTITY x SYSTEM "file:///etc/hostname">]><factura>&x;</factura>'
        r = procesar(f.autorizacion(interno, numero=f.clave()))
        assert not r.aceptado and codigos(r.errores) == ['dtd_prohibida']

    def test_utf16_y_tamano(self):
        assert codigos(procesar(f.factura().encode('utf-16')).errores) == ['codificacion']
        grande = b'<factura>' + b' ' * (limites.MAX_XML_BYTES + 1) + b'</factura>'
        assert codigos(procesar(grande).errores) == ['archivo_grande']

    def test_pdf_disfrazado_de_xml(self):
        assert codigos(procesar(b'%PDF-1.7 ...').errores) == ['no_es_xml']


class TestClaveYCoherencia:

    def test_digito_verificador_invalido(self):
        clave = f.clave()
        r = procesar(f.autorizacion(f.factura(clave_acceso=clave[:48] + str((int(clave[48]) + 1) % 10))))
        assert 'clave_invalida' in codigos(r.errores)

    def test_clave_de_otro_comprobante(self):
        r = procesar(f.autorizacion(f.factura(clave_acceso=f.clave(secuencial='000000999'))))
        assert codigos(r.errores) == ['clave_incoherente'] and 'secuencial' in r.errores[0].texto

    def test_ruc_y_fecha_incoherentes(self):
        r = procesar(f.autorizacion(f.factura(clave_acceso=f.clave(ruc='0990000002001', fecha=date(2026, 10, 9)))))
        assert 'fecha de emisión' in r.errores[0].texto and 'RUC del emisor' in r.errores[0].texto

    def test_numero_de_autorizacion_distinto(self):
        r = procesar(f.autorizacion(f.factura(), numero=f.clave(secuencial='000000555')))
        assert codigos(r.errores) == ['autorizacion_incoherente']


class TestTarifas:

    def test_varias_tarifas_historicas_y_vigentes(self):
        impuestos = (('2', '4', '15.00', '100.00', '15.00'), ('2', '5', '5.00', '40.00', '2.00'), ('2', '2', '12.00', '10.00', '1.20'),
                     ('2', '0', '0.00', '20.00', '0.00'), ('2', '7', '0.00', '5.00', '0.00'), ('2', '6', '0.00', '3.00', '0.00'))
        r = procesar(f.autorizacion(f.factura(impuestos=impuestos, total_sin='178.00', importe='196.20',
                                              lineas=(('A', '178.00'),), pagos=(('20', '196.20'),))))
        assert r.aceptado and r.advertencias == []
        bases = [(b.categoria, b.tarifa, b.base_imponible, b.valor) for b in r.comprobante.bases_por_tarifa]
        assert bases == [('iva_tarifa', Decimal('15.00'), Decimal('100.00'), Decimal('15.00')),
                         ('iva_tarifa', Decimal('12.00'), Decimal('10.00'), Decimal('1.20')),
                         ('iva_tarifa', Decimal('5.00'), Decimal('40.00'), Decimal('2.00')),
                         ('iva_0', Decimal('0.00'), Decimal('20.00'), Decimal('0.00')),
                         ('iva_exento', Decimal('0.00'), Decimal('5.00'), Decimal('0.00')),
                         ('iva_no_objeto', Decimal('0.00'), Decimal('3.00'), Decimal('0.00'))]
        assert r.comprobante.total_iva == Decimal('18.20')
        originales = [(i.codigo, i.codigo_porcentaje) for i in r.comprobante.impuestos]
        assert originales == [('2', '4'), ('2', '5'), ('2', '2'), ('2', '0'), ('2', '7'), ('2', '6')]   # desglose original

    def test_advertencias_de_conciliacion(self):
        r = procesar(f.autorizacion(f.factura(impuestos=(('2', '4', '15.00', '100.00', '14.00'),), total_sin='100.00',
                                              importe='120.00', lineas=(('A', '90.00'),), pagos=(('20', '110.00'),))))
        assert r.aceptado
        assert set(codigos(r.advertencias)) == {'iva_descuadrado', 'total_descuadrado', 'pagos_descuadrados', 'lineas_descuadradas'}

    def test_tarifa_incoherente_con_el_codigo(self):
        r = procesar(f.autorizacion(f.factura(impuestos=(('2', '4', '12.00', '100.00', '12.00'), ('2', '0', '0.00', '20.00', '0.00')),
                                              importe='132.00', pagos=(('20', '132.00'),))))
        assert 'tarifa_incoherente' in codigos(r.advertencias)


class TestReceptores:

    @pytest.mark.parametrize('tipo, identificacion, nombre', [('05', '0912345600', 'Cédula'), ('06', 'AB123456', 'Pasaporte'),
                                                              ('08', 'EXT-998877', 'Identificación del exterior'),
                                                              ('07', '9999999999999', 'Consumidor final')])
    def test_receptor_sin_ruc(self, tipo, identificacion, nombre):
        r = procesar(f.autorizacion(f.factura(receptor_tipo=tipo, receptor_id=identificacion)))
        assert r.aceptado and r.advertencias == []
        assert r.comprobante.receptor_identificacion == identificacion and r.comprobante.receptor_tipo_nombre == nombre

    def test_formato_que_no_corresponde_al_tipo(self):
        r = procesar(f.autorizacion(f.factura(receptor_tipo='04', receptor_id='0912345600')))
        assert r.aceptado and 'identificacion_formato' in codigos(r.advertencias)


class TestTiposNoSoportados:

    @pytest.mark.parametrize('cod_doc, nombre', [('04', 'Nota de crédito'), ('05', 'Nota de débito'), ('07', 'Comprobante de retención')])
    def test_no_se_interpretan_como_facturas(self, cod_doc, nombre):
        r = procesar(f.autorizacion(f.factura(cod_doc=cod_doc)))
        assert not r.aceptado and not r.tipo_soportado and r.comprobante is None
        assert codigos(r.errores) == ['tipo_no_soportado'] and nombre in r.errores[0].texto


class TestRidePdf:

    def test_qr_con_url_no_se_visita(self, monkeypatch):
        import urllib.request
        monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('no se visitan URLs del PDF'))
        clave = f.clave()
        r = ride_pdf.procesar_ride_pdf(f.pdf(('qr', f'https://srienlinea.sri.gob.ec/consulta?clave={clave}')))
        assert r.estado == 'clave_encontrada' and r.clave == clave and r.origen_clave == 'codigo_qr' and r.paginas == 1

    def test_codigo_de_barras(self):
        r = ride_pdf.procesar_ride_pdf(f.pdf(('barras', f.clave())))
        assert r.estado == 'clave_encontrada' and r.origen_clave == 'codigo_barras'

    def test_texto_incrustado_agrupado(self):
        clave = f.clave()
        grupos = ' '.join(clave[i:i + 10] for i in range(0, 49, 10))
        r = ride_pdf.procesar_ride_pdf(f.pdf(texto=f'CLAVE DE ACCESO: {grupos}'))
        assert r.estado == 'clave_encontrada' and r.clave == clave and r.origen_clave == 'texto'

    def test_sin_codigo_permite_clave_manual(self):
        r = ride_pdf.procesar_ride_pdf(f.pdf())
        assert r.estado == 'sin_clave' and r.clave is None and 'sin_clave' in codigos(r.advertencias)

    def test_varias_claves_es_ambiguo(self):
        r = ride_pdf.procesar_ride_pdf(f.pdf(('barras', f.clave()), ('qr', f.clave(secuencial='000000999'))))
        assert r.estado == 'ambigua' and len(r.candidatas) == 2 and r.clave is None

    def test_limites_y_contenido(self):
        assert ride_pdf.procesar_ride_pdf(b'<html></html>').errores[0].codigo == 'no_es_pdf'
        r = ride_pdf.procesar_ride_pdf(f.pdf(paginas=limites.MAX_PDF_PAGINAS + 1))
        assert r.estado == 'rechazado' and r.errores[0].codigo == 'demasiadas_paginas'
        assert ride_pdf.procesar_ride_pdf(b'%PDF-1.4\n' + b'0' * (limites.MAX_PDF_BYTES + 1)).errores[0].codigo == 'archivo_grande'
        assert ride_pdf.procesar_ride_pdf(b'%PDF-1.4\nbasura sin estructura').errores[0].codigo == 'pdf_invalido'

    def test_pdf_protegido(self):
        import io

        from pypdf import PdfReader, PdfWriter
        escritor = PdfWriter(clone_from=PdfReader(io.BytesIO(f.pdf(('barras', f.clave())))))
        escritor.encrypt('secreto')
        salida = io.BytesIO()
        escritor.write(salida)
        assert ride_pdf.procesar_ride_pdf(salida.getvalue()).errores[0].codigo == 'pdf_protegido'

    def test_tiempo_agotado(self, monkeypatch):
        import subprocess
        monkeypatch.setattr(ride_pdf.subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired('x', 1)))
        assert ride_pdf.procesar_ride_pdf(f.pdf()).errores[0].codigo == 'pdf_tiempo'


class SRISimulado:
    """autorizacionComprobante del SRI: comprobantes[clave] = xml; 'caido' lanza; None = sin resultados."""

    def __init__(self, comprobantes=None, caido=False, estado='AUTORIZADO'):
        self.comprobantes, self.caido, self.estado, self.llamadas = comprobantes or {}, caido, estado, []

    def __call__(self, url, timeout):
        self.llamadas.append(url)
        return SimpleNamespace(service=self)

    def autorizacionComprobante(self, clave):
        if self.caido:
            raise ConnectionError('sin red')
        xml = self.comprobantes.get(clave)
        if xml is None:
            return SimpleNamespace(claveAccesoConsultada=clave, numeroComprobantes='0', autorizaciones=None)
        mensajes = None if self.estado == 'AUTORIZADO' else SimpleNamespace(mensaje=[SimpleNamespace(identificador='56', mensaje='ERROR')])
        return SimpleNamespace(autorizaciones=SimpleNamespace(autorizacion=[SimpleNamespace(
            estado=self.estado, numeroAutorizacion=clave, fechaAutorizacion='2026-10-10T10:15:22-05:00', ambiente='PRODUCCIÓN',
            comprobante=xml, mensajes=mensajes)]))


class TestConsultaSri:

    @pytest.fixture(autouse=True)
    def sin_pausa(self, monkeypatch):
        monkeypatch.setattr(sri_autorizacion, 'PAUSA_REINTENTO', 0)

    def test_autorizado_devuelve_xml_procesable(self, monkeypatch):
        sri = SRISimulado({f.clave(): f.factura()})
        monkeypatch.setattr(emision, '_cliente', sri)
        consulta = sri_autorizacion.consultar_autorizacion(f.clave())
        assert consulta.estado == 'autorizado' and 'cel.sri.gob.ec' in sri.llamadas[0] and 'celcer' not in sri.llamadas[0]
        r = procesar_xml_sri(consulta.xml)
        assert r.aceptado and r.comprobante.importe_total == Decimal('135.00') and r.envoltura == 'autorizacion'

    def test_ambiente_de_pruebas_segun_la_clave(self, monkeypatch):
        sri = SRISimulado({f.clave(ambiente=1): f.factura(ambiente=1)})
        monkeypatch.setattr(emision, '_cliente', sri)
        assert sri_autorizacion.consultar_autorizacion(f.clave(ambiente=1)).estado == 'autorizado' and 'celcer' in sri.llamadas[0]

    def test_sin_resultados_no_autorizado_y_caido(self, monkeypatch):
        monkeypatch.setattr(emision, '_cliente', SRISimulado())
        assert sri_autorizacion.consultar_autorizacion(f.clave()).estado == 'sin_resultados'
        monkeypatch.setattr(emision, '_cliente', SRISimulado({f.clave(): f.factura()}, estado='NO AUTORIZADO'))
        consulta = sri_autorizacion.consultar_autorizacion(f.clave())
        assert consulta.estado == 'no_autorizado' and consulta.xml is None and consulta.mensajes
        caido = SRISimulado(caido=True)
        monkeypatch.setattr(emision, '_cliente', caido)
        consulta = sri_autorizacion.consultar_autorizacion(f.clave())
        assert consulta.estado == 'no_disponible' and consulta.intentos == 1 + limites.SRI_REINTENTOS == len(caido.llamadas)

    def test_clave_invalida_no_consulta(self, monkeypatch):
        sri = SRISimulado()
        monkeypatch.setattr(emision, '_cliente', sri)
        assert sri_autorizacion.consultar_autorizacion('123').estado == 'clave_invalida' and sri.llamadas == []
