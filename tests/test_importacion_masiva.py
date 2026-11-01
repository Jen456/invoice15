"""Importación masiva de comprobantes recibidos (entrega 1 del orden de trabajo del 31/10/2026): lista de claves pegadas y
reporte del portal del SRI → lote de claves → consulta al SRI simulado por partes → vista previa e incorporación en lote
(compras con los datos tributarios pendientes de revisión, retenciones recibidas, ventas vinculadas). Duplicados, reintentos,
aislamiento por empresa, permisos y plan. Todos los documentos son ficticios y el SRI es simulado."""
import io
import json
from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from core.importacion import clave_acceso, recibidos, reporte_sri, servicios as sv, sri_autorizacion
from core.importacion.models import ArchivoImportado, DocumentoImportado, EntradaLote, LoteImportacion
from core.pos import emision
from core.pos.compras import faltantes
from core.pos.models import Provider, Purchase
from core.tenancy.context import company_context, platform_scope
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_OWNER
from tests import ayuda_compras as ayuda, fabricas_recibidos as r, fabricas_sri as f, helpers
from tests.test_importacion_recibidos import ErrorDeVentas, ServicioDeVentas
from tests.test_importacion_xml_pdf import SRISimulado

pytestmark = pytest.mark.django_db
RUC_EMPRESA = f.RUC_RECEPTOR
RUC_OTRO_PROVEEDOR = '0990000002001'
CABECERA = ('COMPROBANTE\tSERIE_COMPROBANTE\tRUC_EMISOR\tRAZON_SOCIAL_EMISOR\tFECHA_EMISION\tFECHA_AUTORIZACION\tTIPO_EMISION\t'
            'IDENTIFICACION_RECEPTOR\tCLAVE_ACCESO\tNUMERO_AUTORIZACION\tIMPORTE_TOTAL\tIVA\tVALOR_SIN_IMPUESTOS')
A = f.clave()                                       # factura 001-002-000000271 del proveedor ficticio
B = f.clave(secuencial='000000272')
C = f.clave(secuencial='000000273')                 # el SRI no la tiene
D = f.clave(cod_doc='03', secuencial='000000077')   # liquidación: tipo no soportado
NUEVO = f.clave(ruc=RUC_OTRO_PROVEEDOR, secuencial='000000005')
RETENCION = f.clave(fecha=date(2026, 10, 5), cod_doc='07', ruc=r.RUC_AGENTE, pto='001', secuencial='000000010')
PRUEBAS = f.clave(ambiente=1, secuencial='000000300')
EMITIDA = f.clave(ruc=RUC_EMPRESA, secuencial='000000400')
VIEJA = f.clave(fecha=date(2025, 1, 10), secuencial='000000009')


def fila(clave, *, tipo='Factura', ruc=None, razon='PROVEEDOR FICTICIO S.A.', fecha='10/10/2026', receptor=RUC_EMPRESA,
         importe='135.00', iva='15.00', sin='120.00'):
    datos = clave_acceso.analizar(clave)
    return '\t'.join([tipo, datos.numero, ruc or datos.ruc, razon, fecha, '10/10/2026 10:15:22', 'NORMAL', receptor, clave, clave,
                      importe, iva, sin])


def reporte(*filas):
    return ('﻿' + CABECERA + '\r\n' + '\r\n'.join(filas) + '\r\n').encode('utf-8')


@pytest.fixture(autouse=True)
def archivos_temporales(settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path / 'media')
    monkeypatch.setattr(sri_autorizacion, 'PAUSA_REINTENTO', 0)


@pytest.fixture
def sri(monkeypatch):
    simulado = SRISimulado({A: r.factura(), B: r.factura(secuencial='000000272')})
    monkeypatch.setattr(emision, '_cliente', simulado)
    return simulado


@pytest.fixture
def empresa():
    return helpers.crear_empresa('RECEPTORA MASIVA', ruc=RUC_EMPRESA)


@pytest.fixture
def dueno(empresa):
    return helpers.crear_usuario('dueno.masiva', empresa, ROLE_OWNER)


@pytest.fixture
def web(client, dueno, empresa):
    helpers.iniciar_sesion(client, dueno, empresa=empresa)
    return client


def leer(empresa, consulta):
    with company_context(empresa):
        return consulta()


def lote_de_texto(empresa, usuario, texto):
    with company_context(empresa):
        return sv.crear_lote_de_claves(empresa, usuario, reporte_sri.filas_de_texto(texto), 'claves')


def lote_de_reporte(empresa, usuario, datos):
    with company_context(empresa):
        lista = reporte_sri.filas_de_reporte('recibidos.txt', datos)
        archivo, _ = sv.guardar_archivo(empresa, usuario, 'recibidos.txt', datos, 'reporte')
        return sv.crear_lote_de_claves(empresa, usuario, lista, 'reporte', reporte=archivo)


def procesar(empresa, lote, usuario, maximo=50):
    with company_context(empresa):
        lote = sv.procesar_lote(lote, usuario, maximo=maximo, presupuesto=None)
        return lote, list(lote.entradas.select_related('documento').order_by('orden'))


def estados(entradas):
    return [e.estado for e in entradas]


# ---------------------------------------------------------------- lista pegada y reporte (sin base de datos)

class TestListaDeClaves:

    def test_claves_con_ruido_separadores_y_espacios(self):
        texto = f'{A}\nCLAVE DE ACCESO: {B}\n{C[:10]} {C[10:30]}-{C[30:]}\nFacturas de octubre\n'
        lista = reporte_sri.filas_de_texto(texto)
        assert [fila.clave for fila in lista.filas] == [A, B, C] and not any(fila.errores for fila in lista.filas)
        assert lista.omitidas == 1 and lista.formato == 'texto' and lista.resumen()['con_clave'] == 3

    def test_varias_claves_en_una_linea_y_rechazos_con_motivo(self):
        mala = A[:-1] + ('0' if A[-1] != '0' else '1')
        lista = reporte_sri.filas_de_texto(f'{A}, {B}\n1.1020260109900E+48\n{C[:-1]}\n{mala}\n')
        assert [fila.clave for fila in lista.filas[:2]] == [A, B]
        codigos = [fila.errores[0]['codigo'] for fila in lista.filas[2:]]
        assert codigos == ['clave_alterada', 'longitud', 'clave_invalida']
        assert 'notación científica' in lista.filas[2].errores[0]['texto'] and '48 dígitos' in lista.filas[3].errores[0]['texto']
        assert 'dígito verificador' in lista.filas[4].errores[0]['texto']

    def test_limite_de_claves_y_de_texto(self, monkeypatch):
        monkeypatch.setattr(reporte_sri.limites, 'MAX_CLAVES_POR_LOTE', 3)
        with pytest.raises(reporte_sri.ListaInvalida, match='hasta 3 claves'):
            reporte_sri.filas_de_texto('\n'.join(f.clave(secuencial=f'{n:09d}') for n in range(1, 6)))
        monkeypatch.setattr(reporte_sri.limites, 'MAX_TEXTO_CLAVES', 10)
        with pytest.raises(reporte_sri.ListaInvalida, match='caracteres'):
            reporte_sri.filas_de_texto(A)


class TestReporteDelPortal:

    def test_txt_tabulado_del_portal(self):
        lista = reporte_sri.filas_de_reporte('recibidos.txt', reporte(fila(A), fila(RETENCION, tipo='Comprobante de Retención', importe='6.25',
                                                                                   iva='0.00', sin='0.00')))
        assert lista.formato == 'txt' and set(lista.columnas) >= {'clave', 'emisor_ruc', 'emisor_razon_social', 'fecha_emision',
                                                                 'receptor_identificacion', 'importe_total', 'tipo_comprobante', 'numero'}
        primera, segunda = lista.filas
        assert primera.clave == A and not primera.errores
        assert primera.sugerencias['emisor_ruc'] == f.RUC_EMISOR and primera.sugerencias['fecha_emision'] == '2026-10-10'
        assert primera.sugerencias['importe_total'] == '135.00' and primera.sugerencias['tipo_comprobante'] == '01'
        assert primera.sugerencias['numero'] == '001-002-000000271' and primera.sugerencias['receptor_identificacion'] == RUC_EMPRESA
        assert segunda.clave == RETENCION and segunda.sugerencias['tipo_comprobante'] == '07'
        assert lista.resumen()['columnas_texto']['clave'] == 'clave de acceso'

    def test_csv_punto_y_coma_en_cp1252_y_ruc_que_no_coincide(self):
        texto = 'CLAVE_ACCESO;RUC_EMISOR;RAZON_SOCIAL_EMISOR;IMPORTE_TOTAL\n' + f'{A};0999999999001;COMPAÑÍA CON Ñ;1.234,50\n'
        lista = reporte_sri.filas_de_reporte('r.csv', texto.encode('cp1252'))
        assert lista.formato == 'csv' and lista.filas[0].clave == A
        assert lista.filas[0].sugerencias['emisor_razon_social'] == 'COMPAÑÍA CON Ñ' and lista.filas[0].sugerencias['importe_total'] == '1234.50'
        assert lista.filas[0].advertencias[0]['codigo'] == 'ruc_no_coincide'

    def test_xlsx_lee_texto_y_rechaza_celdas_numericas(self):
        libro = openpyxl.Workbook()
        hoja = libro.active
        hoja.append(['CLAVE_ACCESO', 'RUC_EMISOR', 'RAZON_SOCIAL_EMISOR', 'IMPORTE_TOTAL'])
        hoja.append([A, int(f.RUC_EMISOR), 'PROVEEDOR FICTICIO S.A.', 135.0])          # el RUC perdió el cero inicial en la hoja
        hoja.append([int(B), f.RUC_EMISOR, 'OTRO', '20'])                                # la clave quedó como número
        salida = io.BytesIO()
        libro.save(salida)
        lista = reporte_sri.filas_de_reporte('recibidos.xlsx', salida.getvalue())
        assert lista.formato == 'xlsx'
        primera, segunda = lista.filas
        assert primera.clave == A and primera.sugerencias['emisor_ruc'] == '990000001001' and primera.sugerencias['importe_total'] == '135.00'
        assert primera.advertencias[0]['codigo'] == 'identificacion_alterada'
        assert segunda.clave == '' and segunda.errores[0]['codigo'] == 'clave_alterada'

    def test_sin_encabezado_busca_la_clave_en_cada_fila(self):
        lista = reporte_sri.filas_de_reporte('lista.txt', f'Proveedor uno\t{A}\t135.00\nProveedor dos\t{B}\n'.encode())
        assert [fila.clave for fila in lista.filas] == [A, B] and lista.columnas == {}

    def test_formatos_que_no_son_el_reporte(self):
        with pytest.raises(reporte_sri.ListaInvalida, match='XLS antiguo'):
            reporte_sri.filas_de_reporte('viejo.xls', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\x00' * 20)
        with pytest.raises(reporte_sri.ListaInvalida, match='Nueva importación'):
            reporte_sri.filas_de_reporte('f.pdf', b'%PDF-1.4 hola')
        with pytest.raises(reporte_sri.ListaInvalida, match='vacío'):
            reporte_sri.filas_de_reporte('v.txt', b'\n\n')
        with pytest.raises(reporte_sri.ListaInvalida, match='supera'):
            reporte_sri.filas_de_reporte('g.txt', b'x' * (reporte_sri.limites.MAX_REPORTE_BYTES + 1))


# ---------------------------------------------------------------- lote de claves con el SRI simulado

class TestLoteDeClaves:

    def test_lote_consulta_al_sri_por_partes_y_no_repite_claves(self, empresa, dueno, sri):
        lote = lote_de_texto(empresa, dueno, f'{A}\n{B}\n{C}\n{D}\n{A}\n')
        entradas = leer(empresa, lambda: list(lote.entradas.order_by('orden')))
        assert lote.origen == 'claves' and lote.total_archivos == 5 and lote.estado == 'procesando'
        assert estados(entradas) == ['en_cola', 'en_cola', 'en_cola', 'rechazado', 'duplicado']
        assert entradas[3].errores[0]['codigo'] == 'tipo_no_soportado' and entradas[4].advertencias[0]['codigo'] == 'repetida_en_lista'
        assert all(e.tipo == 'clave' and e.archivo_id is None for e in entradas) and entradas[0].clave == A
        lote, entradas = procesar(empresa, lote, dueno, maximo=2)
        assert estados(entradas)[:3] == ['procesado', 'procesado', 'en_cola'] and lote.estado == 'procesando'
        lote, entradas = procesar(empresa, lote, dueno)
        assert estados(entradas) == ['procesado', 'procesado', 'pendiente_xml', 'rechazado', 'duplicado']
        assert lote.estado == 'con_errores' and len(sri.llamadas) == 3     # una consulta por clave; la repetida no consulta
        documento = entradas[0].documento
        assert (documento.origen, documento.estado_verificacion, documento.clasificacion) == ('lista', 'verificada_sri', 'recibido')
        assert documento.importe_total == Decimal('135.00') and leer(empresa, lambda: documento.archivo_xml.origen) == 'sri'
        assert entradas[2].errores == [{'codigo': 'no_encontrada_sri', 'texto': 'Sin XML autorizado: el sri no tiene esa clave.'}]
        assert entradas[2].documento.estado_procesamiento == 'pendiente_xml' and entradas[2].documento.importe_total == 0

    def test_sri_caido_y_en_proceso_se_reintentan_sin_duplicar(self, empresa, dueno, sri):
        sri.caido = True
        lote = lote_de_texto(empresa, dueno, A)
        lote, entradas = procesar(empresa, lote, dueno)
        assert estados(entradas) == ['pendiente_xml'] and entradas[0].errores[0]['codigo'] == 'sri_no_disponible'
        sri.caido, sri.estado = False, 'EN PROCESO'
        assert leer(empresa, lambda: sv.reencolar_pendientes(lote)) == 1
        lote, entradas = procesar(empresa, lote, dueno)
        assert estados(entradas) == ['pendiente_xml'] and entradas[0].errores[0]['codigo'] == 'en_proceso_sri'
        assert leer(empresa, lambda: sv.reintentables(lote)) == 1
        sri.estado = 'AUTORIZADO'
        assert leer(empresa, lambda: sv.reencolar_pendientes(lote)) == 1
        lote, entradas = procesar(empresa, lote, dueno)
        assert estados(entradas) == ['procesado'] and entradas[0].errores == [] and lote.estado == 'terminado'
        assert leer(empresa, lambda: DocumentoImportado.objects.count()) == 1
        assert entradas[0].documento.estado_verificacion == 'verificada_sri' and entradas[0].intentos == 3

    def test_reintento_automatico_cierra_la_entrada(self, empresa, dueno, sri):
        """La tarea programada (o la ficha del documento) recupera el XML: la entrada del lote deja de esperar."""
        sri.caido = True
        lote = lote_de_texto(empresa, dueno, A)
        lote, entradas = procesar(empresa, lote, dueno)
        sri.caido = False
        with company_context(empresa):
            sv.recuperar_xml(entradas[0].documento, dueno)
            entrada = EntradaLote.objects.get(pk=entradas[0].pk)
            lote.refresh_from_db()
        assert entrada.estado == 'procesado' and entrada.errores == [] and lote.estado == 'terminado'

    def test_la_misma_clave_en_otro_lote_es_duplicado_sin_consultar(self, empresa, dueno, sri):
        primero = lote_de_texto(empresa, dueno, A)
        procesar(empresa, primero, dueno)
        llamadas = len(sri.llamadas)
        segundo = lote_de_texto(empresa, dueno, A)
        segundo, entradas = procesar(empresa, segundo, dueno)
        assert estados(entradas) == ['duplicado'] and entradas[0].documento_id is not None and len(sri.llamadas) == llamadas
        assert entradas[0].advertencias[0]['codigo'] == 'ya_importada' and segundo.estado == 'terminado'
        assert leer(empresa, lambda: DocumentoImportado.objects.count()) == 1

    def test_reporte_crea_el_lote_y_compara_con_el_xml(self, empresa, dueno, sri):
        datos = reporte(fila(A, importe='150.00'),                                   # el reporte difiere del XML (135.00)
                        fila(B, receptor='0993333333001'),                             # recibido por otra empresa
                        fila(EMITIDA, ruc=RUC_EMPRESA, receptor='0993333333001'),      # emitido por la propia empresa
                        fila(PRUEBAS))
        lote = lote_de_reporte(empresa, dueno, datos)
        entradas = leer(empresa, lambda: list(lote.entradas.order_by('orden')))
        assert lote.origen == 'reporte' and lote.reporte.tipo == 'reporte' and lote.reporte.nombre_original == 'recibidos.txt'
        assert estados(entradas) == ['en_cola', 'rechazado', 'en_cola', 'en_cola']
        assert entradas[1].errores[0]['codigo'] == 'otra_empresa' and entradas[3].advertencias[0]['codigo'] == 'ambiente_pruebas'
        assert entradas[0].sugerencias['emisor_razon_social'] == 'PROVEEDOR FICTICIO S.A.'
        lote, entradas = procesar(empresa, lote, dueno)
        assert entradas[0].estado == 'procesado' and entradas[0].documento.origen == 'reporte'
        assert entradas[0].sugerencias['comparacion'] == {'coincide': False, 'diferencias': ['importe_total']}
        assert entradas[0].documento.importe_total == Decimal('135.00')      # manda el XML, no el reporte
        assert entradas[2].estado == 'pendiente_xml' and entradas[3].estado == 'pendiente_xml'   # el SRI simulado no las tiene
        with company_context(empresa):
            assert ArchivoImportado.objects.filter(tipo='reporte').count() == 1
            assert lote.reporte.archivo.name.startswith(f'privado/empresas/{empresa.uuid}/importados/')

    def test_aislamiento_entre_empresas(self, empresa, dueno, sri, client):
        otra = helpers.crear_empresa('OTRA RECEPTORA', ruc='0992222222001')
        ajeno = helpers.crear_usuario('dueno.otra', otra, ROLE_OWNER)
        lote = lote_de_texto(empresa, dueno, A)
        procesar(empresa, lote, dueno)
        lote_otra = lote_de_texto(otra, ajeno, A)
        procesar(otra, lote_otra, ajeno)
        with platform_scope():
            assert DocumentoImportado.all_companies.filter(clave_acceso=A).count() == 2   # un documento por empresa
        assert leer(otra, lambda: DocumentoImportado.objects.get().clasificacion) == 'ajeno'   # el XML dice que el receptor es otra
        helpers.iniciar_sesion(client, ajeno, empresa=otra)
        assert client.get(f'/importacion/api/lotes/{lote.pk}/incorporar/').status_code == 404
        assert client.get(f'/importacion/lotes/{lote.pk}/incorporar/').status_code == 404
        assert client.post(f'/importacion/api/lotes/{lote.pk}/incorporar/', json.dumps({'documentos': []}),
                           content_type='application/json').status_code == 404

    def test_api_y_pagina_de_claves(self, web, empresa, sri):
        respuesta = web.post('/importacion/api/lotes/claves/', json.dumps({'texto': f'{A}\n{C[:-1]}'}), content_type='application/json')
        assert respuesta.status_code == 201
        datos = respuesta.json()
        assert datos['lista'] == {**datos['lista'], 'con_clave': 1, 'rechazadas': 1} and datos['lote']['origen']['id'] == 'claves'
        assert datos['lote']['entradas'][0]['clave'] == A and datos['lote']['entradas'][1]['estado']['id'] == 'rechazado'
        assert web.post('/importacion/api/lotes/claves/', {'texto': 'nada'}).json()['error'] == 'No se encontró ninguna clave de acceso.'
        subida = web.post('/importacion/api/lotes/reporte/', {'reporte': io.BytesIO(reporte(fila(B)))})
        assert subida.status_code == 201 and subida.json()['lote']['reporte']['tipo'] == 'reporte'
        assert web.post('/importacion/api/lotes/reporte/', {}).json()['error'].startswith('Sube el reporte')
        pagina = web.get('/importacion/claves/')
        assert pagina.status_code == 200 and 'Importar por claves o reporte del SRI' in pagina.content.decode()
        redireccion = web.post('/importacion/claves/', {'texto': A})
        lote_id = int(redireccion.url.rstrip('/').rsplit('/', 1)[1])
        assert redireccion.status_code == 302 and redireccion.url == f'/importacion/lotes/{lote_id}/'
        html = web.get(redireccion.url).content.decode()
        assert A in html and 'Lista de claves de acceso' in html and 'Procesar los pendientes (1)' in html
        procesado = web.post(f'/importacion/api/lotes/{lote_id}/procesar/', {})
        assert procesado.json()['lote']['pendientes'] == 0 and procesado.json()['reencoladas'] == 0
        html = web.get(redireccion.url).content.decode()
        assert 'Incorporar en lote' in html

    def test_permiso_de_importar_y_plan(self, client, empresa, dueno, sri):
        contador = helpers.crear_usuario('conta.masiva', empresa, ROLE_ACCOUNTANT)
        helpers.iniciar_sesion(client, contador, empresa=empresa)
        assert client.post('/importacion/api/lotes/claves/', {'texto': A}).status_code == 403
        assert client.get('/importacion/claves/').status_code == 302            # la página redirige sin el permiso
        plan_1000 = helpers.crear_empresa('PLAN MIL', plan='plan-1000', ruc='0994444444001')
        usuario = helpers.crear_usuario('dueno.mil', plan_1000, ROLE_OWNER)
        helpers.iniciar_sesion(client, usuario, empresa=plan_1000)
        respuesta = client.post('/importacion/api/lotes/claves/', {'texto': A})
        assert respuesta.status_code == 403 and respuesta.json()['plan'] == 'ilimitado'


# ---------------------------------------------------------------- incorporación en lote

def lote_procesado(empresa, usuario, sri, comprobantes, texto=None):
    sri.comprobantes.update(comprobantes)
    lote = lote_de_texto(empresa, usuario, texto or '\n'.join(comprobantes))
    lote, entradas = procesar(empresa, lote, usuario)
    return lote, {e.clave: e.documento for e in entradas if e.documento_id}


def incorporar(empresa, lote, usuario, documentos, **kw):
    with company_context(empresa):
        return sv.incorporar_lote(lote, usuario, ayuda.peticion(usuario, empresa), documentos, **kw)


def plan_de(empresa, lote, usuario):
    with company_context(empresa):
        return sv.plan_incorporacion(lote, ayuda.peticion(usuario, empresa))


class TestIncorporacion:

    @pytest.fixture
    def proveedor(self, empresa):
        return ayuda.crear_proveedor(empresa, tipo='04', ruc=f.RUC_EMISOR, nombre='PROVEEDOR FICTICIO S.A.')

    def test_plan_de_incorporacion(self, empresa, dueno, sri, proveedor):
        lote, docs = lote_procesado(empresa, dueno, sri, {
            A: r.factura(), NUEVO: r.factura(ruc=RUC_OTRO_PROVEEDOR, razon='PROVEEDOR NUEVO S.A.', secuencial='000000005'),
            RETENCION: r.retencion_v2(), PRUEBAS: r.factura(ambiente=1, secuencial='000000300'),
            EMITIDA: r.factura(ruc=RUC_EMPRESA, receptor_id='0993333333001', secuencial='000000400')}, texto=f'{A}\n{NUEVO}\n{RETENCION}\n{PRUEBAS}\n{EMITIDA}\n{C}')
        plan = plan_de(empresa, lote, dueno)
        por_clave = {i['clave']: i for i in plan['items']}
        assert (por_clave[A]['accion'], por_clave[A]['estado']) == ('crear_compra', 'listo')
        assert por_clave[A]['proveedor']['ruc'] == f.RUC_EMISOR and por_clave[A]['proveedor_nuevo'] is None
        assert [p['codigo'] for p in por_clave[A]['pendientes_revision']] == ['cod_sustento']   # forma de pago y parte relacionada ya se conocen
        assert (por_clave[NUEVO]['estado'], por_clave[NUEVO]['proveedor_nuevo']['ruc']) == ('requiere_datos', RUC_OTRO_PROVEEDOR)
        assert [p['codigo'] for p in por_clave[NUEVO]['pendientes_revision']] == ['cod_sustento', 'parte_relacionada']
        assert (por_clave[RETENCION]['accion'], por_clave[RETENCION]['estado']) == ('registrar_retencion', 'listo')
        assert por_clave[PRUEBAS]['estado'] == 'bloqueado' and por_clave[PRUEBAS]['bloqueos'][0]['codigo'] == 'ambiente_pruebas'
        assert por_clave[EMITIDA]['accion'] == 'vincular_venta' and por_clave[EMITIDA]['bloqueos'][0]['codigo'] == 'sin_venta'
        assert por_clave[C]['estado'] == 'sin_xml' and por_clave[C]['accion'] is None
        assert plan['proveedores_nuevos'] == [{'ruc': RUC_OTRO_PROVEEDOR, 'razon_social': 'PROVEEDOR NUEVO S.A.', 'requiere': ['mobile', 'email'],
                                               'documentos': 1}]
        assert plan['resumen']['incorporables'] == 3 and plan['resumen']['por_estado'] == {'listo': 2, 'requiere_datos': 1, 'bloqueado': 2, 'sin_xml': 1}

    def test_incorporar_crea_compras_con_datos_pendientes_y_repetir_no_duplica(self, empresa, dueno, sri, proveedor):
        lote, docs = lote_procesado(empresa, dueno, sri, {A: r.factura(), NUEVO: r.factura(ruc=RUC_OTRO_PROVEEDOR, secuencial='000000005',
                                                                                           razon='PROVEEDOR NUEVO S.A.', pagos=())})
        ids = [docs[A].pk, docs[NUEVO].pk]
        resultado = incorporar(empresa, lote, dueno, ids, proveedores={RUC_OTRO_PROVEEDOR: {'mobile': '0990000099', 'email': 'nuevo@example.com'}})
        assert [x['resultado'] for x in resultado['resultados']] == ['compra_creada', 'compra_creada'] and resultado['restantes'] == []
        with company_context(empresa):
            compra = Purchase.objects.get(pk=resultado['resultados'][0]['compra_id'])
            nueva = Purchase.objects.get(pk=resultado['resultados'][1]['compra_id'])
            assert (compra.tipo_comprobante, compra.autorizacion, compra.secuencial, compra.origen) == ('01', A, '000000271', 'importacion')
            assert compra.total == Decimal('135.00') and compra.cod_sustento == '' and compra.datos_incompletos
            assert compra.forma_pago == '20' and compra.parte_relacionada is False and compra.fecha_emision == date(2026, 10, 10)
            assert [c for c, _ in faltantes(compra)] == ['cod_sustento']
            assert compra.purchasedetail_set.count() == 2 and all(d.product_id is None for d in compra.purchasedetail_set.all())
            assert nueva.forma_pago == '' and nueva.parte_relacionada is None and nueva.datos_incompletos
            assert {'cod_sustento', 'forma_pago', 'parte_relacionada'} <= {c for c, _ in faltantes(nueva)}
            creado = Provider.objects.get(ruc=RUC_OTRO_PROVEEDOR)
            assert (creado.name, creado.mobile, creado.email, creado.tipo_identificacion) == ('PROVEEDOR NUEVO S.A.', '0990000099', 'nuevo@example.com', '04')
            assert creado.parte_relacionada is None and nueva.provider_id == creado.pk
            docs[A].refresh_from_db()
            assert docs[A].estado_revision == 'vinculado' and docs[A].compra_id == compra.pk
            compras, proveedores = Purchase.objects.count(), Provider.objects.count()
        repetido = incorporar(empresa, lote, dueno, ids, proveedores={RUC_OTRO_PROVEEDOR: {'mobile': '0990000099', 'email': 'nuevo@example.com'}})
        assert [x['resultado'] for x in repetido['resultados']] == ['ya_incorporado', 'ya_incorporado']
        with company_context(empresa):
            assert (Purchase.objects.count(), Provider.objects.count()) == (compras, proveedores)
        plan = plan_de(empresa, lote, dueno)
        assert {i['estado'] for i in plan['items']} == {'ya_incorporado'}

    def test_proveedor_nuevo_sin_celular_ni_correo_queda_pendiente(self, empresa, dueno, sri):
        lote, docs = lote_procesado(empresa, dueno, sri, {NUEVO: r.factura(ruc=RUC_OTRO_PROVEEDOR, secuencial='000000005')})
        resultado = incorporar(empresa, lote, dueno, [docs[NUEVO].pk])
        assert resultado['resultados'][0]['resultado'] == 'error' and 'celular y su correo' in resultado['resultados'][0]['mensaje']
        with company_context(empresa):
            assert Purchase.objects.count() == 0 and Provider.objects.filter(ruc=RUC_OTRO_PROVEEDOR).count() == 0

    def test_retencion_recibida_en_lote(self, empresa, dueno, sri, monkeypatch):
        lote, docs = lote_procesado(empresa, dueno, sri, {RETENCION: r.retencion_v2()})
        servicio = ServicioDeVentas()
        monkeypatch.setattr(recibidos, '_servicio_registro', lambda: (servicio, ErrorDeVentas))
        resultado = incorporar(empresa, lote, dueno, [docs[RETENCION].pk])
        assert resultado['resultados'][0]['resultado'] == 'retencion_registrada' and len(servicio.llamadas) == 1
        assert leer(empresa, lambda: DocumentoImportado.objects.get(pk=docs[RETENCION].pk).estado_revision) == 'vinculado'
        otra_vez = incorporar(empresa, lote, dueno, [docs[RETENCION].pk])
        assert otra_vez['resultados'][0]['resultado'] == 'error' and otra_vez['resultados'][0]['codigo'] == 'ya_registrada'
        assert len(servicio.llamadas) == 1

    def test_confirmaciones_permisos_y_partes(self, empresa, dueno, sri, proveedor):
        lote, docs = lote_procesado(empresa, dueno, sri, {VIEJA: r.factura(fecha=date(2025, 1, 10), secuencial='000000009'), A: r.factura()})
        sin_confirmar = incorporar(empresa, lote, dueno, [docs[VIEJA].pk])
        assert sin_confirmar['resultados'][0] == {**sin_confirmar['resultados'][0], 'resultado': 'error', 'codigo': 'confirmar_plazo_ats'}
        plan = plan_de(empresa, lote, dueno)
        vieja = next(i for i in plan['items'] if i['clave'] == VIEJA)
        assert vieja['estado'] == 'requiere_datos' and vieja['confirmaciones'] == ['confirmar_plazo_ats']
        confirmado = incorporar(empresa, lote, dueno, [docs[VIEJA].pk], opciones={'confirmar_plazo_ats': 'si'})
        assert confirmado['resultados'][0]['resultado'] == 'compra_creada'
        assert leer(empresa, lambda: Purchase.objects.get(pk=confirmado['resultados'][0]['compra_id']).fuera_plazo_ats)
        contador = helpers.crear_usuario('conta.incorpora', empresa, ROLE_ACCOUNTANT)
        denegado = incorporar(empresa, lote, contador, [docs[A].pk])
        assert denegado['resultados'][0]['codigo'] == 'sin_permiso'
        assert leer(empresa, lambda: Purchase.objects.count()) == 1
        por_partes = incorporar(empresa, lote, dueno, [docs[A].pk, docs[VIEJA].pk], maximo=1)
        assert por_partes['tratados'] == 1 and por_partes['restantes'] == [docs[VIEJA].pk]
        with pytest.raises(sv.ErrorImportacion, match='no pertenece a este lote'):
            incorporar(empresa, lote, dueno, [docs[A].pk, 999999])
        with pytest.raises(sv.ErrorImportacion, match='al menos un documento'):
            incorporar(empresa, lote, dueno, [])

    def test_pagina_y_api_de_incorporacion(self, web, empresa, dueno, sri, proveedor):
        lote, docs = lote_procesado(empresa, dueno, sri, {A: r.factura(), NUEVO: r.factura(ruc=RUC_OTRO_PROVEEDOR, secuencial='000000005',
                                                                                           razon='PROVEEDOR NUEVO S.A.')})
        pagina = web.get(f'/importacion/lotes/{lote.pk}/incorporar/')
        html = pagina.content.decode()
        assert pagina.status_code == 200 and 'Incorporar los elegidos' in html and 'PROVEEDOR NUEVO S.A.' in html
        assert f'name="proveedor-{RUC_OTRO_PROVEEDOR}-mobile"' in html and 'Quedará pendiente: Sustento tributario' in html
        plan = web.get(f'/importacion/api/lotes/{lote.pk}/incorporar/').json()
        assert plan['plan']['resumen']['incorporables'] == 2 and 'tipos_gasto' in plan['opciones']
        respuesta = web.post(f'/importacion/lotes/{lote.pk}/incorporar/', {'documentos': [docs[A].pk], 'date_joined': '2026-10-31'})
        assert respuesta.status_code == 302
        assert leer(empresa, lambda: Purchase.objects.get().date_joined) == date(2026, 10, 31)
        api = web.post(f'/importacion/api/lotes/{lote.pk}/incorporar/', json.dumps({
            'documentos': [docs[NUEVO].pk], 'opciones': {},
            'proveedores': {RUC_OTRO_PROVEEDOR: {'mobile': '0990000098', 'email': 'nuevo2@example.com', 'parte_relacionada': 'no'}}}),
            content_type='application/json').json()
        assert api['resultados'][0]['resultado'] == 'compra_creada' and api['plan']['resumen']['por_estado'] == {'ya_incorporado': 2}
        assert leer(empresa, lambda: Provider.objects.get(ruc=RUC_OTRO_PROVEEDOR).parte_relacionada) is False
