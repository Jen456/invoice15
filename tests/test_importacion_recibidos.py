"""Importación de comprobantes recibidos distintos de la factura (espec-etapa2-compras §3.5, §3.7, §6.H y §6.J): lectura
de notas de crédito (04), notas de débito (05) y comprobantes de retención 07 (v1.0.0 y v2.0.0); clasificación; lectura
del 07 para «Retenciones recibidas» (RetencionLeida); marca idempotente del documento; pantalla «Registrar retención
recibida» con el servicio de Ventas (O2) sustituido; propuesta contable y filtro por tipo. Documentos ficticios."""
import json
import sys
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group

from core.importacion import recibidos, servicios as sv, sri_autorizacion
from core.importacion.models import DocumentoImportado, EventoImportacion
from core.importacion.views import acciones_posibles
from core.importacion.xml_sri import procesar_xml_sri
from core.pos import emision
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_OWNER
from tests import ayuda_compras as ayuda, fabricas_recibidos as r, helpers
from tests.test_importacion_xml_pdf import SRISimulado


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


# ---------------------------------------------------------------- con base de datos

@pytest.fixture
def entorno(settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path / 'media')
    monkeypatch.setattr(sri_autorizacion, 'PAUSA_REINTENTO', 0)
    monkeypatch.setattr(emision, '_cliente', SRISimulado())


@pytest.fixture
def empresa(db, entorno):
    return helpers.crear_empresa('SUJETO RETENIDO', ruc=r.RUC_RECEPTOR)


@pytest.fixture
def dueno(empresa):
    return helpers.crear_usuario('dueno.recibidos', empresa, ROLE_OWNER)


@pytest.fixture
def con_permiso(db):
    """add_retencionrecibida (permiso de O2) para Propietario, como lo dejará la fusión con Ventas."""
    ayuda.permiso_retencion_recibida(Group.objects.get(name=ROLE_OWNER))


@pytest.fixture
def web(client, dueno, empresa, con_permiso):
    helpers.iniciar_sesion(client, dueno, empresa=empresa)
    return client


def importar(empresa, usuario, xml, verificado=True):
    with company_context(empresa):
        documento = sv.crear_lote(empresa, usuario, [('doc.xml', r.autorizacion(xml).encode())]).documentos.get()
        if verificado:
            DocumentoImportado.objects.filter(pk=documento.pk).update(estado_verificacion='verificada_sri')
            documento.refresh_from_db()
        return documento


def en(empresa, funcion, *args, **kwargs):
    with company_context(empresa):
        return funcion(*args, **kwargs)


class ErrorDeVentas(Exception):
    """Simula core.comprobantes.retenciones_recibidas.ErrorRetencionRecibida (O2), con su código."""

    def __init__(self, mensaje, codigo):
        super().__init__(mensaje)
        self.codigo = codigo


class ServicioDeVentas:
    """Simula registrar_desde_importacion de O2: una retención recibida por sustento y la marca del documento una vez."""

    def __init__(self, error=None):
        self.llamadas, self.error = [], error

    def __call__(self, company, usuario, documento, leida):
        self.llamadas.append((company, usuario, documento.pk, leida))
        if self.error:
            raise self.error
        recibidos.marcar_incorporado(documento, usuario, 'Retenciones recibidas #1 y #2')
        return [object() for _ in leida.sustentos]


@pytest.mark.django_db
class TestClasificacionYAcciones:

    @pytest.mark.parametrize('xml', [r.nota_credito(), r.nota_debito(), r.retencion_v1(), r.retencion_v2()],
                             ids=['04', '05', '07v1', '07v2'])
    def test_recibidos_se_procesan_y_clasifican(self, empresa, dueno, xml):
        documento = importar(empresa, dueno, xml, verificado=False)
        assert (documento.estado_procesamiento, documento.clasificacion) == ('procesado', 'recibido')
        acciones = acciones_posibles(documento)
        if documento.cod_doc == '07':
            assert documento.importe_total == sum(Decimal(rr['valor_retenido']) for s in documento.datos['comprobante']['retencion']
                                                  ['docs_sustento'] for rr in s['retenciones'])
            assert en(empresa, documento.impuestos.count) == 0
            assert 'registrar_retencion' in acciones and 'crear_compra' not in acciones and 'vincular_compra' not in acciones
            assert 'crear_proveedor' not in acciones
        else:
            assert 'crear_compra' in acciones and 'vincular_compra' in acciones

    def test_emitidos_solo_se_aprueban(self, empresa, dueno):
        documento = importar(empresa, dueno, r.nota_credito(ruc=r.RUC_RECEPTOR, receptor_id='0990000009001'))
        assert documento.clasificacion == 'emitido'
        assert acciones_posibles(documento) == ['verificar', 'aprobar', 'descartar']

    def test_propuesta_contable_del_07_y_reverso_del_04(self, empresa, dueno):
        retencion = importar(empresa, dueno, r.retencion_v2())
        nota = importar(empresa, dueno, r.nota_credito())
        with company_context(empresa):
            regla = sv.reglas_de(empresa)
            sv.ReglaImportacion.objects.filter(pk=regla.pk).update(cuenta_gasto='5.1', cuenta_iva_compras='1.1.5',
                                                                   cuenta_proveedores='2.1')
            retencion = sv.revisar(retencion, dueno, 'aprobar')
            nota = sv.revisar(nota, dueno, 'aprobar')
            assert (retencion.propuesta_contable, retencion.estado_contable) == (None, 'sin_propuesta')
            assert 'La retención se contabiliza con la retención recibida.' in EventoImportacion.objects.filter(
                documento=retencion, tipo='aprobar').get().mensaje
        assert [(l['cuenta'], l['debe'], l['haber']) for l in nota.propuesta_contable['lineas']] == [
            ('5.1', '0.00', '20.00'), ('1.1.5', '0.00', '3.00'), ('2.1', '23.00', '0.00')]
        assert nota.propuesta_contable['cuadra']

    def test_filtro_por_tipo(self, client, empresa, dueno):
        importar(empresa, dueno, r.retencion_v2())
        importar(empresa, dueno, r.factura())
        helpers.iniciar_sesion(client, dueno, empresa=empresa)
        datos = client.get('/importacion/api/documentos/?bandeja=todos&cod_doc=07').json()
        assert datos['total'] == 1 and datos['documentos'][0]['cod_doc'] == '07'
        assert client.get('/importacion/api/documentos/?bandeja=todos&cod_doc=03').status_code == 400


@pytest.mark.django_db
class TestRetencionLeida:

    def test_v2_con_dos_sustentos(self, empresa, dueno):
        sustentos = [r.sustento(autorizacion_='1' * 49), r.sustento(numero='001001000000124', cod_sustento='02',
                                                                     retenciones=(('1', '303', '200.00', '10.00', '20.00'),))]
        documento = importar(empresa, dueno, r.retencion_v2(sustentos=sustentos))
        leida = en(empresa, recibidos.retencion_recibida_de, documento)
        assert (leida.documento_id, leida.ambiente, leida.verificado_sri, leida.estado_verificacion) == (
            documento.pk, 2, True, 'verificada_sri')
        assert (leida.numero, leida.agente_ruc, leida.version, leida.periodo_fiscal) == (
            '001-001-000000010', r.RUC_AGENTE, '2.0.0', '10/2026')
        assert leida.total_retenido == Decimal('26.25') and leida.fecha_emision == date(2026, 10, 5)
        uno, dos = leida.sustentos
        assert (uno.num_doc_sustento, uno.numero_con_guiones, uno.num_aut_doc_sustento, uno.cod_sustento) == (
            '001001000000123', '001-001-000000123', '1' * 49, '01')
        assert uno.retenciones[0] == recibidos.RetencionLineaLeida('1', '312', Decimal('100.00'), Decimal('1.75'), Decimal('1.75'))
        assert (dos.cod_sustento, dos.fecha_emision_doc_sustento, len(dos.retenciones)) == ('02', date(2026, 10, 1), 1)

    def test_v1_agrupa_y_sin_verificar(self, empresa, dueno):
        lineas = r.LINEAS_RETENCION_V1 + (('1', '303', '50.00', '10.00', '5.00', '01', '001001000000200', date(2026, 10, 3)),)
        documento = importar(empresa, dueno, r.retencion_v1(lineas=lineas), verificado=False)
        leida = en(empresa, recibidos.retencion_recibida_de, documento)
        assert leida.version == '1.0.0' and leida.verificado_sri is False
        assert leida.estado_verificacion == 'declarada_en_archivo'
        assert [(s.num_doc_sustento, len(s.retenciones), s.cod_sustento, s.num_aut_doc_sustento) for s in leida.sustentos] == [
            ('001001000000123', 2, '', ''), ('001001000000200', 1, '', '')]

    def test_exige_07_recibido_y_verificacion_admisible(self, empresa, dueno):
        factura = importar(empresa, dueno, r.factura())
        with pytest.raises(sv.ErrorImportacion, match='no es un comprobante de retención'):
            en(empresa, recibidos.retencion_recibida_de, factura)
        documento = importar(empresa, dueno, r.retencion_v2())
        en(empresa, lambda: DocumentoImportado.objects.filter(pk=documento.pk).update(estado_verificacion='no_autorizada_sri'))
        en(empresa, documento.refresh_from_db)
        with pytest.raises(sv.ErrorImportacion, match='No se puede registrar') as e:
            en(empresa, recibidos.retencion_recibida_de, documento)
        assert e.value.codigo == 'verificacion'


@pytest.mark.django_db
class TestMarcaDelDocumento:

    def test_marcar_dos_veces_deja_una_marca(self, empresa, dueno):
        documento = importar(empresa, dueno, r.retencion_v2())
        with company_context(empresa):
            recibidos.marcar_incorporado(documento, dueno, 'Retenciones recibidas #12 y #13')
            recibidos.marcar_incorporado(documento, dueno, 'Retenciones recibidas #12 y #13')
            documento.refresh_from_db()
            assert documento.estado_revision == 'vinculado' and documento.revisado_por_id == dueno.pk
            eventos = EventoImportacion.objects.filter(documento=documento, tipo='incorporado')
            assert [e.mensaje for e in eventos] == ['Retenciones recibidas #12 y #13']

    def test_desmarcar_es_idempotente_y_descartado_falla(self, empresa, dueno):
        documento = importar(empresa, dueno, r.retencion_v2())
        with company_context(empresa):
            recibidos.desmarcar_incorporado(documento, dueno, 'Anulada')
            documento.refresh_from_db()
            assert documento.estado_revision == 'pendiente'
            assert not EventoImportacion.objects.filter(documento=documento, tipo='desincorporado').exists()
            recibidos.marcar_incorporado(documento, dueno, 'Retención recibida #1')
            recibidos.desmarcar_incorporado(documento, dueno, 'Se anuló la retención recibida #1')
            recibidos.desmarcar_incorporado(documento, dueno, 'otra vez')
            documento.refresh_from_db()
            assert documento.estado_revision == 'pendiente'
            assert [e.mensaje for e in EventoImportacion.objects.filter(documento=documento, tipo='desincorporado')] == [
                'Se anuló la retención recibida #1']
            sv.revisar(documento, dueno, 'descartar', {'motivo': 'prueba'})
            with pytest.raises(sv.ErrorImportacion, match='descartado: reábrelo antes'):
                recibidos.marcar_incorporado(documento, dueno, 'Retención recibida #2')

    def test_vinculado_no_se_reabre(self, empresa, dueno):
        documento = importar(empresa, dueno, r.retencion_v2())
        with company_context(empresa):
            recibidos.marcar_incorporado(documento, dueno, 'Retención recibida #1')
            documento.refresh_from_db()
            assert 'reabrir' not in acciones_posibles(documento)
            with pytest.raises(sv.ErrorImportacion, match='anula allí el registro de la retención'):
                sv.revisar(documento, dueno, 'reabrir')


@pytest.mark.django_db
class TestPantallaRetencionRecibida:

    def url(self, documento):
        return f'/importacion/documentos/{documento.pk}/retencion-recibida/'

    def test_resumen_y_registro_con_el_servicio_de_ventas(self, web, empresa, dueno, monkeypatch):
        documento = importar(empresa, dueno, r.retencion_v2(sustentos=[r.sustento(), r.sustento(numero='001001000000124')]))
        detalle = web.get(f'/importacion/api/documentos/{documento.pk}/').json()['documento']
        assert detalle['urls']['retencion_recibida'] == self.url(documento) and detalle['urls']['compra'] is None
        pagina = web.get(self.url(documento))
        html = pagina.content.decode()
        assert pagina.status_code == 200 and '001-001-000000123' in html and '001-001-000000124' in html
        assert 'Se registra una retención recibida por cada factura sustento' in html and 'name="action" value="registrar"' in html
        servicio = ServicioDeVentas()
        monkeypatch.setattr(recibidos, '_servicio_registro', lambda: (servicio, ErrorDeVentas))
        respuesta = web.post(self.url(documento), {'action': 'registrar'})
        assert respuesta.status_code == 302 and respuesta.url == f'/importacion/documentos/{documento.pk}/'
        assert len(servicio.llamadas) == 1
        empresa_llamada, usuario, documento_id, leida = servicio.llamadas[0]
        assert (empresa_llamada.pk, usuario.pk, documento_id) == (empresa.pk, dueno.pk, documento.pk)
        assert isinstance(leida, recibidos.RetencionLeida) and len(leida.sustentos) == 2
        assert 'Retención recibida registrada (2 documentos sustento)' in [str(m) for m in respuesta.wsgi_request._messages]
        en(empresa, documento.refresh_from_db)
        assert documento.estado_revision == 'vinculado'
        html = web.get(self.url(documento)).content.decode()
        assert 'Registrada en Retenciones recibidas' in html and 'value="registrar"' not in html

    def test_error_de_ventas_se_muestra_y_el_documento_sigue_pendiente(self, web, empresa, dueno, monkeypatch):
        documento = importar(empresa, dueno, r.retencion_v2())
        servicio = ServicioDeVentas(ErrorDeVentas('La factura sustento 001-001-000000123 no es una venta tuya.',
                                                  'sustento_no_encontrado'))
        monkeypatch.setattr(recibidos, '_servicio_registro', lambda: (servicio, ErrorDeVentas))
        respuesta = web.post(self.url(documento), {'action': 'registrar'})
        assert respuesta.status_code == 200 and 'no es una venta tuya' in respuesta.content.decode()
        en(empresa, documento.refresh_from_db)
        assert documento.estado_revision == 'pendiente'
        with company_context(empresa), pytest.raises(sv.ErrorImportacion) as e:
            recibidos.registrar_en_retenciones_recibidas(empresa, dueno, documento)
        assert e.value.codigo == 'sustento_no_encontrado'

    def test_sin_el_modulo_de_ventas(self, web, empresa, dueno, monkeypatch):
        documento = importar(empresa, dueno, r.retencion_v2())
        monkeypatch.setitem(sys.modules, 'core.comprobantes.retenciones_recibidas', None)   # import → ImportError
        respuesta = web.post(self.url(documento), {'action': 'registrar'})
        assert 'El registro de retenciones recibidas todavía no está disponible' in respuesta.content.decode()

    def test_sin_verificar_exige_confirmar(self, web, empresa, dueno, monkeypatch):
        documento = importar(empresa, dueno, r.retencion_v2(), verificado=False)
        servicio = ServicioDeVentas()
        monkeypatch.setattr(recibidos, '_servicio_registro', lambda: (servicio, ErrorDeVentas))
        assert 'name="confirmar_sin_verificar"' in web.get(self.url(documento)).content.decode()
        respuesta = web.post(self.url(documento), {'action': 'registrar'})
        assert 'no está verificado en el SRI' in respuesta.content.decode() and servicio.llamadas == []
        assert web.post(self.url(documento), {'action': 'registrar', 'confirmar_sin_verificar': 'on'}).status_code == 302
        assert len(servicio.llamadas) == 1

    def test_contador_y_plan_1000(self, client, empresa, dueno, con_permiso):
        documento = importar(empresa, dueno, r.retencion_v2())
        helpers.iniciar_sesion(client, helpers.crear_usuario('contador.recibidos', empresa, ROLE_ACCOUNTANT), empresa=empresa)
        assert client.get(self.url(documento)).status_code == 302
        assert client.post(self.url(documento), {'action': 'registrar'}).status_code == 403
        client.logout()
        mil = helpers.crear_empresa('PLAN MIL RETENCIONES', plan='plan-1000', ruc='0990000088001')
        helpers.iniciar_sesion(client, helpers.crear_usuario('dueno.mil.ret', mil, ROLE_OWNER), empresa=mil)
        respuesta = client.post(self.url(documento), {'action': 'registrar'})
        assert respuesta.status_code == 403 and 'Ilimitado y Multiempresa' in json.loads(respuesta.content)['error']

    def test_documento_de_otra_empresa(self, client, empresa, dueno, con_permiso):
        documento = importar(empresa, dueno, r.retencion_v2())
        otra = helpers.crear_empresa('OTRA RETENIDA')
        helpers.iniciar_sesion(client, helpers.crear_usuario('dueno.otra.ret', otra, ROLE_OWNER), empresa=otra)
        assert client.get(self.url(documento)).status_code == 404

    def test_ficha_del_documento_con_los_datos_nuevos(self, web, empresa, dueno):
        retencion = importar(empresa, dueno, r.retencion_v2())
        html = web.get(f'/importacion/documentos/{retencion.pk}/').content.decode()
        assert f'href="{self.url(retencion)}"' in html and 'Registrar retención recibida' in html
        assert 'Documento sustento 001001000000123' in html and '/compra/' not in html
        en(empresa, recibidos.marcar_incorporado, retencion, dueno, 'Retención recibida #1')
        html = web.get(f'/importacion/documentos/{retencion.pk}/').content.decode()
        assert 'Registrada en Retenciones recibidas' in html and 'Reabrir revisión' not in html
        nota = importar(empresa, dueno, r.nota_credito())
        html = web.get(f'/importacion/documentos/{nota.pk}/').content.decode()
        assert 'Documento modificado' in html and 'Devolución de mercadería' in html and 'Líneas del XML' in html
        assert f'href="/importacion/documentos/{nota.pk}/compra/"' in html and 'name="parte_relacionada"' in html
        debito = importar(empresa, dueno, r.nota_debito())
        assert 'Intereses por mora' in web.get(f'/importacion/documentos/{debito.pk}/').content.decode()
