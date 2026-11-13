"""«Verificar en el SRI» de los XML importados (primera entrega, entregas/facturaporaqui/primera-entrega/verificar-sri.md).

Cuatro resultados que no se confunden: autorización confirmada, rechazo confirmado, autorización solo declarada en el XML
y consulta fallida (tiempo agotado, red, SOAP, HTTP, fuera de rango, respuesta inesperada). La pantalla separa lo que
declara el XML, lo que respondió el SRI y la revisión interna del comercio, y muestra el último intento (fecha, usuario,
resultado y mensaje). Reintentar actualiza el mismo documento: ni otro documento ni una compra o venta, y dos consultas a
la vez del mismo documento no llegan al SRI dos veces. SRI simulado, sin red; datos ficticios."""
import importlib
import socket
import urllib.error
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.db import connection
from django.utils import timezone
from lxml import html as lxml_html

from core.importacion import compras as desde_xml, limites, servicios as sv, sri_autorizacion
from core.importacion.models import ArchivoImportado, DocumentoImportado, EventoImportacion
from core.pos import emision
from core.pos.models import Purchase, Sale
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER
from tests import fabricas_sri as f, helpers
from tests.test_importacion_xml_pdf import SRISimulado

pytestmark = pytest.mark.django_db


def leer(empresa, consulta):
    with company_context(empresa):
        return consulta()


class SRILento(SRISimulado):
    """SRISimulado que además puede fallar con una excepción dada (tiempo agotado, error SOAP…)."""

    def __init__(self, *args, error=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.error = error

    def autorizacionComprobante(self, clave):
        if self.error is not None:
            raise self.error
        return super().autorizacionComprobante(clave)


@pytest.fixture(autouse=True)
def archivos_temporales(settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path / 'media')
    monkeypatch.setattr(sri_autorizacion, 'PAUSA_REINTENTO', 0)


@pytest.fixture
def sri(monkeypatch):
    simulado = SRILento()
    monkeypatch.setattr(emision, '_cliente', simulado)
    return simulado


@pytest.fixture
def empresa():
    return helpers.crear_empresa('RECEPTORA VERIFICA', ruc=f.RUC_RECEPTOR)


@pytest.fixture
def dueno(empresa):
    return helpers.crear_usuario('dueno.verifica', empresa, ROLE_OWNER)


@pytest.fixture
def web(client, dueno, empresa):
    helpers.iniciar_sesion(client, dueno, empresa=empresa)
    return client


@pytest.fixture
def documento(empresa, dueno, sri):
    """Factura recibida importada desde un XML que DECLARA su autorización (todavía sin consultar al SRI)."""
    with company_context(empresa):
        sv.crear_lote(empresa, dueno, [('f.xml', f.autorizacion(f.factura()).encode())])
        return DocumentoImportado.objects.get()


def verificar(empresa, documento, usuario):
    with company_context(empresa):
        return sv.verificar_en_sri(documento, usuario)


def conteos(empresa):
    return leer(empresa, lambda: (DocumentoImportado.objects.count(), Purchase.objects.count(), Sale.objects.count(),
                                  ArchivoImportado.objects.count()))


def eventos(empresa, documento, tipo='verificacion'):
    return leer(empresa, lambda: list(EventoImportacion.objects.filter(documento=documento, tipo=tipo).order_by('pk')))


class TestConsultaFallida:
    """Cada falla técnica del cliente SOAP es «no se pudo verificar» con su motivo, nunca un rechazo."""

    @pytest.mark.parametrize('error, motivo', [
        (TimeoutError('timed out'), 'tiempo_agotado'),
        (socket.timeout('timed out'), 'tiempo_agotado'),
        (urllib.error.URLError(socket.timeout('timed out')), 'tiempo_agotado'),
        (urllib.error.URLError(ConnectionRefusedError(111, 'Connection refused')), 'sin_conexion'),
        (ConnectionResetError(104, 'reset'), 'sin_conexion'),
        ('webfault', 'error_sri'),
        ('transport', 'servicio_no_disponible'),
        (ValueError('respuesta ilegible'), 'respuesta_inesperada'),
    ])
    def test_motivo_de_cada_falla(self, monkeypatch, error, motivo):
        from suds import WebFault
        from suds.transport import TransportError
        error = {'webfault': WebFault(SimpleNamespace(faultstring='Error interno del servicio'), None),
                 'transport': TransportError('Service Unavailable', 503)}.get(error, error) if isinstance(error, str) else error
        caido = SRILento(error=error)
        monkeypatch.setattr(sri_autorizacion, 'PAUSA_REINTENTO', 0)
        monkeypatch.setattr(emision, '_cliente', caido)
        consulta = sri_autorizacion.consultar_autorizacion(f.clave())
        assert (consulta.estado, consulta.motivo) == ('no_disponible', motivo)
        assert consulta.intentos == 1 + limites.SRI_REINTENTOS == len(caido.llamadas)
        esperados = [f'Intento {n}: {error.__class__.__name__}' for n in range(1, 2 + limites.SRI_REINTENTOS)]
        assert [m.split(' (')[0] for m in consulta.mensajes] == esperados

    @pytest.mark.parametrize('estado', ['RECHAZADA', 'DEVUELTA', 'ESTADO NUEVO'])
    def test_estado_no_concluyente_es_respuesta_inesperada(self, monkeypatch, estado):
        monkeypatch.setattr(emision, '_cliente', SRILento({f.clave(): f.factura()}, estado=estado))
        consulta = sri_autorizacion.consultar_autorizacion(f.clave())
        assert (consulta.estado, consulta.motivo) == ('no_disponible', 'respuesta_inesperada')

    def test_fuera_de_rango_por_el_texto_del_mensaje(self, monkeypatch):
        motivo = SimpleNamespace(identificador='80', mensaje='FECHA DE EMISION FUERA DEL RANGO PERMITIDO', informacionAdicional='')
        respuesta = SimpleNamespace(claveAccesoConsultada=f.clave(), autorizaciones=SimpleNamespace(autorizacion=[
            SimpleNamespace(estado='RECHAZADA', mensajes=SimpleNamespace(mensaje=[motivo]))]))
        monkeypatch.setattr(emision, '_cliente', lambda *a: SimpleNamespace(service=SimpleNamespace(autorizacionComprobante=lambda c: respuesta)))
        assert sri_autorizacion.consultar_autorizacion(f.clave()).estado == 'fuera_de_rango'


class TestCuatroResultados:
    """Prueba de aceptación (§12): XML autorizado, rechazo confirmado y tiempo de espera agotado."""

    def test_xml_autorizado_queda_confirmado_con_el_intento(self, empresa, dueno, documento, sri):
        assert documento.estado_verificacion == 'declarada_en_archivo' and documento.verificado_en is None
        assert leer(empresa, lambda: sv.autorizacion_del_xml(documento))['id'] == 'declarada'
        sri.comprobantes[f.clave()] = f.factura()
        documento = verificar(empresa, documento, dueno)
        assert documento.estado_verificacion == 'verificada_sri' and documento.ultima_consulta_resultado == 'autorizado'
        assert documento.ultima_consulta_por == dueno and documento.verificado_en and documento.respuesta_sri_en
        assert documento.ultima_consulta_mensaje == 'Coincide con el comprobante autorizado en el SRI.'
        assert documento.consulta_en_curso is None
        assert documento.estado_revision == 'pendiente' and documento.clasificacion == 'recibido'   # la revisión es aparte
        assert leer(empresa, lambda: sv.autorizacion_del_xml(documento))['id'] == 'declarada'   # el XML sigue diciendo lo suyo
        assert leer(empresa, lambda: desde_xml.propuesta_compra(documento))['exige_confirmar_sin_verificar'] is False

    def test_rechazo_confirmado_bloquea_la_compra(self, empresa, dueno, documento, sri):
        sri.comprobantes[f.clave()], sri.estado = f.factura(), 'NO AUTORIZADO'
        documento = verificar(empresa, documento, dueno)
        assert (documento.estado_verificacion, documento.ultima_consulta_resultado) == ('no_autorizada_sri', 'no_autorizado')
        assert documento.get_estado_verificacion_display() == 'Rechazo confirmado por el SRI (NO AUTORIZADO)'
        assert 'Rechazo confirmado' in documento.ultima_consulta_mensaje and '[56] ERROR' in documento.ultima_consulta_mensaje
        assert documento.respuesta_sri_en is not None
        with company_context(empresa):
            propuesta = desde_xml.propuesta_compra(documento)
            assert 'verificacion' in [b['codigo'] for b in propuesta['bloqueos']]
            with pytest.raises(sv.ErrorImportacion, match=r'No se puede incorporar: rechazo confirmado por el SRI \(NO AUTORIZADO\)'):
                sv.revisar(documento, dueno, 'aprobar', {'confirmar_sin_verificar': True})

    def test_tiempo_agotado_no_es_rechazo_y_el_reintento_no_duplica(self, empresa, dueno, documento, sri):
        antes = conteos(empresa)
        sri.error = TimeoutError('timed out')
        documento = verificar(empresa, documento, dueno)
        assert (documento.estado_verificacion, documento.ultima_consulta_resultado) == ('sri_no_disponible', 'tiempo_agotado')
        assert documento.ultima_consulta_mensaje == ('No se pudo verificar en el SRI: el SRI no respondió a tiempo (tiempo de espera '
                                                     'agotado). Puedes reintentar. Detalle: Intento 1: TimeoutError (timed out); '
                                                     'Intento 2: TimeoutError (timed out).')
        assert documento.estado_verificacion not in DocumentoImportado.VERIFICACION_BLOQUEA and documento.respuesta_sri_en is None
        assert leer(empresa, lambda: sv.autorizacion_del_xml(documento))['id'] == 'declarada'   # declarada, sin confirmar
        with company_context(empresa):
            propuesta = desde_xml.propuesta_compra(documento)                   # no bloquea: pide confirmar sin verificar
            assert 'verificacion' not in [b['codigo'] for b in propuesta['bloqueos']] and propuesta['exige_confirmar_sin_verificar']
            with pytest.raises(sv.ErrorImportacion, match='no está verificado'):
                sv.revisar(documento, dueno, 'aprobar')
        primero = documento.verificado_en
        sri.error, sri.comprobantes[f.clave()] = None, f.factura()              # el SRI vuelve: reintento
        reintento = verificar(empresa, documento, dueno)
        assert reintento.pk == documento.pk and reintento.estado_verificacion == 'verificada_sri'
        assert reintento.verificado_en > primero and reintento.ultima_consulta_resultado == 'autorizado'
        assert conteos(empresa) == antes                                       # ni documento, ni compra, ni venta, ni archivo
        assert [e.datos['resultado'] for e in eventos(empresa, documento)] == ['tiempo_agotado', 'autorizado']

    def test_sin_la_clave_en_el_sri_es_no_autorizada_pero_no_rechazo(self, empresa, dueno, documento, sri):
        documento = verificar(empresa, documento, dueno)
        assert (documento.estado_verificacion, documento.ultima_consulta_resultado) == ('no_encontrada_sri', 'no_encontrado')
        assert documento.estado_verificacion in DocumentoImportado.VERIFICACION_BLOQUEA
        assert 'Rechazo' not in documento.get_estado_verificacion_display()
        assert 'reintenta más tarde' in documento.ultima_consulta_mensaje

    def test_en_proceso_no_bloquea_ni_confirma(self, empresa, dueno, documento, sri):
        sri.comprobantes[f.clave()], sri.estado = f.factura(), 'EN PROCESO'
        documento = verificar(empresa, documento, dueno)
        assert (documento.estado_verificacion, documento.ultima_consulta_resultado) == ('en_proceso_sri', 'en_proceso')
        assert documento.estado_verificacion not in DocumentoImportado.VERIFICACION_BLOQUEA

    def test_xml_del_sri_que_no_valida_es_fallo_y_no_discrepancia(self, empresa, dueno, documento, sri):
        sri.comprobantes[f.clave()] = '<factura><roto>'
        documento = verificar(empresa, documento, dueno)
        assert (documento.estado_verificacion, documento.ultima_consulta_resultado) == ('sri_no_disponible', 'respuesta_inesperada')
        assert documento.clasificacion == 'recibido'                           # no pasa a revisión manual

    def test_un_fallo_posterior_no_borra_la_respuesta_concluyente(self, empresa, dueno, documento, sri):
        sri.comprobantes[f.clave()] = f.factura()
        confirmado = verificar(empresa, documento, dueno)
        respuesta = confirmado.respuesta_sri_en
        sri.error = urllib.error.URLError(socket.timeout('timed out'))
        documento = verificar(empresa, documento, dueno)
        assert documento.estado_verificacion == 'verificada_sri' and documento.respuesta_sri_en == respuesta
        assert documento.ultima_consulta_resultado == 'tiempo_agotado' and documento.verificado_en > respuesta
        assert eventos(empresa, documento)[-1].datos['conservado'] is True
        # igual con un rechazo confirmado: una consulta fuera de rango no lo convierte en «no se pudo verificar»
        sri.error, sri.estado = None, 'NO AUTORIZADO'
        assert verificar(empresa, documento, dueno).estado_verificacion == 'no_autorizada_sri'
        sri.estado = 'RECHAZADA'
        documento = verificar(empresa, documento, dueno)
        assert (documento.estado_verificacion, documento.ultima_consulta_resultado) == ('no_autorizada_sri', 'respuesta_inesperada')


class TestReintentoSinDuplicar:

    def test_consulta_en_curso_no_llega_al_sri_otra_vez(self, empresa, dueno, documento, sri):
        sri.comprobantes[f.clave()] = f.factura()
        leer(empresa, lambda: DocumentoImportado.objects.filter(pk=documento.pk).update(consulta_en_curso=timezone.now()))
        with pytest.raises(sv.ErrorImportacion) as e:
            verificar(empresa, documento, dueno)
        assert e.value.codigo == 'consulta_en_curso' and sri.llamadas == []
        viejo = timezone.now() - timedelta(seconds=limites.SRI_CONSULTA_EN_CURSO_SEGUNDOS + 1)   # proceso cortado: caduca
        leer(empresa, lambda: DocumentoImportado.objects.filter(pk=documento.pk).update(consulta_en_curso=viejo))
        assert verificar(empresa, documento, dueno).estado_verificacion == 'verificada_sri' and len(sri.llamadas) == 1
        assert leer(empresa, lambda: DocumentoImportado.objects.get(pk=documento.pk).consulta_en_curso) is None

    def test_un_error_inesperado_libera_la_consulta(self, empresa, dueno, documento, monkeypatch):
        def falla(clave):
            raise RuntimeError('fallo interno')
        monkeypatch.setattr(sv, 'consultar_autorizacion', falla)
        with pytest.raises(RuntimeError):
            verificar(empresa, documento, dueno)
        assert leer(empresa, lambda: DocumentoImportado.objects.get(pk=documento.pk).consulta_en_curso) is None

    def test_reintentos_por_la_pagina_y_la_api_actualizan_el_mismo_documento(self, web, empresa, dueno, documento, sri):
        antes = conteos(empresa)
        sri.error = TimeoutError('timed out')
        for _ in range(2):
            assert web.post(f'/importacion/documentos/{documento.pk}/', {'accion': 'verificar'}).status_code == 302
        r = web.post(f'/importacion/api/documentos/{documento.pk}/verificar/')
        assert r.status_code == 200 and r.json()['documento']['id'] == documento.pk
        ultima = r.json()['documento']['verificacion_sri']['ultima_consulta']
        assert ultima['resultado']['id'] == 'tiempo_agotado' and ultima['fallida'] and ultima['usuario'] == dueno.names
        assert conteos(empresa) == antes and len(eventos(empresa, documento)) == 3
        leer(empresa, lambda: DocumentoImportado.objects.filter(pk=documento.pk).update(consulta_en_curso=timezone.now()))
        r = web.post(f'/importacion/api/documentos/{documento.pk}/verificar/')
        assert r.status_code == 409 and r.json()['codigo'] == 'consulta_en_curso'
        r = web.post(f'/importacion/documentos/{documento.pk}/', {'accion': 'verificar'}, follow=True)
        assert 'Ya hay una consulta al SRI en curso' in r.content.decode() and len(eventos(empresa, documento)) == 3

    def test_el_lote_salta_el_documento_que_ya_se_esta_consultando(self, empresa, dueno, sri):
        with company_context(empresa):
            lote = sv.crear_lote(empresa, dueno, [('f.xml', f.autorizacion(f.factura()).encode())])
            DocumentoImportado.objects.update(consulta_en_curso=timezone.now())
            sv.procesar_lote(lote, dueno)
        assert sri.llamadas == []


class TestSinXmlYSubidas:

    def registrar(self, empresa, dueno):
        with company_context(empresa):
            documento, _ = sv.registrar_clave(empresa, dueno, f.clave(), origen='manual')
            return documento

    def test_recuperar_el_xml_registra_el_intento(self, empresa, dueno, sri):
        documento = self.registrar(empresa, dueno)
        assert leer(empresa, lambda: sv.autorizacion_del_xml(documento))['id'] == 'sin_xml'
        sri.comprobantes[f.clave()] = f.factura()
        documento = verificar(empresa, documento, dueno)
        assert documento.estado_procesamiento == 'procesado' and documento.estado_verificacion == 'verificada_sri'
        assert documento.ultima_consulta_resultado == 'autorizado' and documento.ultima_consulta_por == dueno
        assert leer(empresa, lambda: sv.autorizacion_del_xml(documento))['id'] == 'del_sri'
        assert leer(empresa, lambda: DocumentoImportado.objects.count()) == 1

    def test_subir_el_xml_no_borra_un_rechazo_del_sri(self, empresa, dueno, sri):
        documento = self.registrar(empresa, dueno)
        sri.comprobantes[f.clave()], sri.estado = f.factura(), 'NO AUTORIZADO'
        assert verificar(empresa, documento, dueno).estado_verificacion == 'no_autorizada_sri'
        with company_context(empresa):
            sv.crear_lote(empresa, dueno, [('f.xml', f.autorizacion(f.factura()).encode())])   # el XML declara AUTORIZADO
            documento = DocumentoImportado.objects.get()
        assert documento.estado_procesamiento == 'procesado' and documento.estado_verificacion == 'no_autorizada_sri'
        assert leer(empresa, lambda: sv.autorizacion_del_xml(documento))['id'] == 'declarada'

    def test_la_tarea_programada_no_reintenta_lo_que_no_cambiaria(self, empresa, dueno, sri):
        from django.core.management import call_command
        documento = self.registrar(empresa, dueno)
        hace_rato = timezone.now() - timedelta(minutes=30)
        with company_context(empresa):
            DocumentoImportado.objects.filter(pk=documento.pk).update(
                estado_verificacion='sri_no_disponible', ultima_consulta_resultado='fuera_de_rango', verificado_en=hace_rato)
        call_command('procesar_importaciones')
        assert sri.llamadas == []
        leer(empresa, lambda: DocumentoImportado.objects.filter(pk=documento.pk).update(ultima_consulta_resultado='sin_conexion'))
        call_command('procesar_importaciones')
        assert len(sri.llamadas) == 1


class TestPantalla:

    def test_el_boton_es_un_formulario_que_envia_a_la_pagina(self, web, documento):
        arbol = lxml_html.fromstring(web.get(f'/importacion/documentos/{documento.pk}/').content)
        formularios = arbol.xpath('//form[.//input[@name="accion"][@value="verificar"]]')
        assert len(formularios) == 1                                           # un solo botón «Verificar en el SRI»
        form = formularios[0]
        assert form.get('method') == 'post' and not form.get('action')         # envía a la misma página
        assert 'fp-import-verificar' in form.get('class') and 'fp-import-action' not in form.get('class')
        assert form.xpath('.//input[@name="csrfmiddlewaretoken"]')
        assert form.xpath('.//button[@type="submit"]')[0].text_content().strip() == 'Verificar en el SRI'
        assert 'Todavía no se ha consultado al SRI.' in arbol.text_content()
        codigo = (Path(__file__).resolve().parent.parent / 'static/js/importacion.js').read_text()
        assert ".fp-import-verificar" in codigo and "form.dataset.enviando" in codigo

    def test_pantalla_separa_xml_sri_y_revision_y_muestra_el_ultimo_intento(self, web, empresa, dueno, documento, sri):
        sri.error = TimeoutError('timed out')
        r = web.post(f'/importacion/documentos/{documento.pk}/', {'accion': 'verificar'}, follow=True)
        assert r.status_code == 200
        arbol = lxml_html.fromstring(r.content)
        texto = ' '.join(arbol.text_content().split())
        documento = leer(empresa, lambda: DocumentoImportado.objects.get(pk=documento.pk))
        hora = timezone.localtime(documento.verificado_en).strftime('%d/%m/%Y %H:%M:%S')
        assert f'Resultado de la consulta al SRI ({hora}): No se pudo verificar: tiempo de espera agotado.' in texto
        panel = ' '.join(arbol.xpath('//section[@id="fp-import-verificacion"]')[0].text_content().split())
        for rotulo in ('Respuesta del SRI', 'No se pudo verificar en el SRI', 'no es un rechazo',
                       'Autorización declarada en el XML', 'El XML declara la autorización (AUTORIZADO)',
                       'Última consulta al SRI', hora, f'por {dueno.names}', 'No se pudo verificar: tiempo de espera agotado',
                       'Revisión interna del comercio', 'Pendiente de revisión', 'Volver a verificar en el SRI'):
            assert rotulo in panel, rotulo
        assert 'Rechazo confirmado' not in panel
        assert arbol.xpath('//section[@id="fp-import-verificacion"]//strong[@data-resultado="tiempo_agotado"]')

    def test_fuera_de_rango_enlaza_el_portal_y_no_es_rechazo(self, web, empresa, documento, monkeypatch):
        monkeypatch.setattr(sv, 'consultar_autorizacion', lambda clave: sri_autorizacion.ResultadoConsulta(
            'fuera_de_rango', clave, mensajes=['[80] ERROR (fecha fuera del rango)'], intentos=1, estados_sri=['RECHAZADA']))
        html = web.post(f'/importacion/documentos/{documento.pk}/', {'accion': 'verificar'}, follow=True).content.decode()
        assert 'portal oficial del SRI' in html and 'Rechazo confirmado' not in html
        bandeja = web.get('/importacion/api/documentos/?bandeja=todos').json()['documentos'][0]
        assert bandeja['estados']['verificacion'] == {'id': 'sri_no_disponible', 'nombre': 'No se pudo verificar en el SRI',
                                                      'en': bandeja['estados']['verificacion']['en'],
                                                      'resultado': 'fuera_de_rango', 'concluyente': False}


class TestMigracion0009:
    """La migración de datos (0009) con los modelos históricos: estados de antes → resultado del último intento, y vuelta."""

    def test_estados_anteriores_y_vuelta(self, empresa, dueno, sri):
        from django.db.migrations.executor import MigrationExecutor
        migracion = importlib.import_module('core.importacion.migrations.0009_verificacion_sri_ultimo_intento')
        apps_historicas = MigrationExecutor(connection).loader.project_state(
            ('importacion', '0009_verificacion_sri_ultimo_intento')).apps
        casos = {   # secuencial: (estado de antes, mensaje del último evento, pendiente de XML)
            '000000301': ('fuera_rango_sri', 'La fecha de emisión está fuera del rango.', False),
            '000000302': ('sri_no_disponible', 'El SRI no respondió; se puede reintentar más tarde.', False),
            '000000303': ('no_autorizada_sri', 'El SRI responde que la clave NO está autorizada.', False),
            '000000304': ('no_encontrada_sri', 'La clave no es válida.', False),
            '000000305': ('no_encontrada_sri', 'El SRI no tiene un comprobante autorizado con esa clave.', False),
            '000000306': ('discrepancia_sri', 'El XML que devolvió el SRI no se pudo validar.', False),
            '000000307': ('discrepancia_sri', 'El archivo importado difiere de lo autorizado en el SRI: importe_total.', False),
            '000000308': ('verificada_sri', 'Coincide con el comprobante autorizado en el SRI.', False),
            '000000309': ('en_proceso_sri', 'El SRI todavía está procesando el comprobante.', False),
            '000000310': ('declarada_en_archivo', '', False),
            '000000311': ('discrepancia_sri', 'El SRI devolvió un XML que no se pudo validar: x', True),
        }
        hace_rato = timezone.now() - timedelta(days=2)
        with company_context(empresa):
            sv.crear_lote(empresa, dueno, [(f'{s}.xml', f.autorizacion(f.factura(secuencial=s)).encode()) for s in casos])
            for secuencial, (estado, mensaje, pendiente) in casos.items():
                documento = DocumentoImportado.objects.get(secuencial=secuencial)
                DocumentoImportado.objects.filter(pk=documento.pk).update(
                    estado_verificacion=estado, verificado_en=None if estado == 'declarada_en_archivo' else hace_rato,
                    ultima_consulta_resultado='', estado_procesamiento='pendiente_xml' if pendiente else 'procesado')
                if mensaje:
                    sv.evento('verificacion', mensaje, documento=documento, usuario=dueno,
                              mensajes=['[80] ERROR'] if estado == 'no_autorizada_sri' else [])
            migracion.adelante(apps_historicas, SimpleNamespace(connection=connection))
            ida = {d.secuencial: (d.estado_verificacion, d.ultima_consulta_resultado, d.ultima_consulta_por_id,
                                  d.respuesta_sri_en is not None) for d in DocumentoImportado.objects.all()}
            rechazo = DocumentoImportado.objects.get(secuencial='000000303')
            assert 'Vuelve a verificar' in rechazo.ultima_consulta_mensaje and '[80] ERROR' in rechazo.ultima_consulta_mensaje
            assert rechazo.get_estado_verificacion_display() == 'El SRI no la autorizó (consulta anterior: vuelve a verificar)'
            assert rechazo.estado_verificacion in DocumentoImportado.VERIFICACION_BLOQUEA   # sigue sin poder incorporarse
            from core.importacion.views import verificacion_dict
            panel = verificacion_dict(rechazo)
            assert 'vuelve a verificar' in panel['sri']['explicacion'] and not panel['ultima_consulta']['conserva_respuesta_anterior']
        assert ida == {
            '000000301': ('sri_no_disponible', 'fuera_de_rango', dueno.pk, False),
            '000000302': ('sri_no_disponible', 'sin_respuesta', dueno.pk, False),
            '000000303': ('no_autorizada_sri', 'rechazo_anterior', dueno.pk, True),
            '000000304': ('sri_no_disponible', 'clave_invalida', dueno.pk, False),
            '000000305': ('no_encontrada_sri', 'no_encontrado', dueno.pk, True),
            '000000306': ('sri_no_disponible', 'respuesta_inesperada', dueno.pk, False),
            '000000307': ('discrepancia_sri', 'discrepancia', dueno.pk, True),
            '000000308': ('verificada_sri', 'autorizado', dueno.pk, True),
            '000000309': ('en_proceso_sri', 'en_proceso', dueno.pk, False),
            '000000310': ('declarada_en_archivo', '', None, False),
            '000000311': ('sri_no_disponible', 'respuesta_inesperada', dueno.pk, False),
        }
        with company_context(empresa):
            migracion.atras(apps_historicas, SimpleNamespace(connection=connection))
            vuelta = dict(DocumentoImportado.objects.values_list('secuencial', 'estado_verificacion'))
        assert vuelta['000000301'] == 'fuera_rango_sri' and vuelta['000000304'] == 'no_encontrada_sri'
        assert {s: e for s, e in vuelta.items() if s not in ('000000301', '000000304')} == {
            s: v[0] for s, v in ida.items() if s not in ('000000301', '000000304')}
        if connection.vendor == 'postgresql':   # la migración restauró app.platform
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('app.platform', true)")
                assert cursor.fetchone()[0] != 'on'
