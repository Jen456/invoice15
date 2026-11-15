"""Importación de los saldos de la apertura con vista previa y respaldos de la apertura (bloque 2, Parte B, primera mitad):
core/contabilidad/apertura_importar.py, lectura_tabular.py, respaldos.py y sus rutas.

POST /contabilidad/api/apertura/<id>/importar/, GET …/importar/<lote>/ y POST …/<id>/mapear/ desde un lote: CSV con `;` y
`,`, con BOM, y XLSX; columnas por encabezado (código, rubro, debe y haber, o una sola de saldo); filas válidas, sin cuenta,
de grupo, duplicadas, omitidas y con error; nada escrito en las líneas antes de mapear; agrupar y omitir con su motivo;
límites (2 MB y 5 000 filas) y archivos ilegibles; archivo privado con su huella; clave repetida; solo en borrador; lote de
otra apertura o de otra empresa; 5 000 filas sin consultas por fila.

POST …/<id>/respaldos/, GET …/respaldos/<id>/descargar/ y POST …/respaldos/<id>/anular/: PDF, JPG, PNG, XLSX y CSV
validados por su contenido; WEBP y un ZIP que no es XLSX rechazados; cabeceras de la descarga; anular conserva el archivo.

El lector es el común (lectura_tabular.py), con las defensas del bloque 1 que prueba entero tests/test_cuentas_importacion.py:
aquí, que valen también por la ruta de la apertura y para sus respaldos (partes en bzip2 o lzma, entidades XML y un logo
SVG). Datos ficticios."""
import csv
import functools
import hashlib
import io
import json
import struct
import tracemalloc
import zipfile
import zlib

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from PIL import Image

from core.contabilidad import api, apertura_importar, lectura_tabular, respaldos
from core.contabilidad.models import Apertura, ImportacionApertura, LineaApertura, RespaldoApertura
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog
from tests import ayudas_contables as ayudas
from tests import helpers
from tests.test_apertura_preparar import (API, creada, en, enviar, errores, eventos, leer, plan_grande, rechazo,
                                          servicio_descartar)
from tests.test_cuentas_importacion import SVG, partes_de, retocar, xlsx_con

pytestmark = pytest.mark.django_db

TI = apertura_importar.TEXTOS
TL = apertura_importar.TEXTOS_LECTOR
SALDOS = (('Código', 'Nombre', 'Debe', 'Haber'), ('1.1.01', 'Caja', '10000.00', ''), ('3.1.01', 'Capital social', '', '10000.00'))


# ---------------------------------------------------------------- ayudas

def csv_de(*filas, separador=';', bom=False):
    salida = io.StringIO()
    csv.writer(salida, delimiter=separador, lineterminator='\r\n').writerows(filas)
    return (b'\xef\xbb\xbf' if bom else b'') + salida.getvalue().encode('utf-8')


def xlsx_de(*filas):
    libro = openpyxl.Workbook()
    for fila in filas:
        libro.active.append(fila)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def imagen(formato):
    salida = io.BytesIO()
    Image.new('RGB', (4, 4), (200, 10, 10)).save(salida, formato)
    return salida.getvalue()


PDF = b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n'
MB = lectura_tabular.MB


def saldos_con_entidad():
    """Los saldos de siempre en un XLSX cuyo rubro de la fila 2 no está escrito: sale de una entidad XML declarada en la hoja
    (`&a;&a;`, que el lector de XML expande a «CajaCaja»). Es la forma de que unos kilobytes ocupen gigas al abrirlos."""
    partes = partes_de(xlsx_de(*SALDOS))
    caja = '<c r="B2" t="inlineStr"><is><t>Caja</t></is></c>'
    hoja = partes['xl/worksheets/sheet1.xml'].decode()
    assert hoja.count(caja) == 1
    partes['xl/worksheets/sheet1.xml'] = ('<!DOCTYPE worksheet [<!ENTITY a "Caja">]>' + hoja.replace(
        caja, '<c r="B2" t="inlineStr"><is><t>&a;&a;</t></is></c>')).encode()
    return xlsx_con(partes)


@functools.lru_cache(maxsize=None)
def saldos_con_relleno(parte, metodo, relleno=32):
    """Los saldos de siempre con `parte` comprimida con `metodo` y `relleno` MB de espacios detrás de su contenido. El
    directorio del ZIP declara solo el contenido (su tamaño y su suma). Una parte que no es del libro trae 1 KB."""
    partes = partes_de(xlsx_de(*SALDOS))
    contenido = partes.pop(parte, b'x' * 1024)
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, 'w', zipfile.ZIP_DEFLATED) as comprimido:
        for nombre, datos in partes.items():
            comprimido.writestr(nombre, datos)
        info = zipfile.ZipInfo(parte)
        info.compress_type = metodo
        with comprimido.open(info, 'w') as destino:
            destino.write(contenido)
            for _ in range(relleno):
                destino.write(b' ' * MB)
    datos = bytearray(salida.getvalue())
    entrada = datos.rindex(b'PK\x01\x02')   # la última del directorio del ZIP: ahí se declaran su suma y su tamaño
    struct.pack_into('<L', datos, entrada + 16, zlib.crc32(contenido))
    struct.pack_into('<L', datos, entrada + 24, len(contenido))
    return bytes(datos)


def saldos_con_logo_svg():
    partes = partes_de(xlsx_de(*SALDOS))
    partes['xl/media/image1.svg'] = SVG.encode()
    retocar(partes, '[Content_Types].xml', '<Default Extension="rels"',
            '<Default Extension="svg" ContentType="image/svg+xml"/><Default Extension="rels"')
    return xlsx_con(partes)


def subir(client, empresa, apertura_id, contenido, nombre='saldos.csv', clave=None, tipo='saldos'):
    datos = {'empresa': empresa.pk, 'clave': clave or ayudas.clave('importar'), 'tipo': tipo}
    if contenido is not None:
        datos['archivo'] = SimpleUploadedFile(nombre, contenido)
    return client.post(f'{API}{apertura_id}/importar/?empresa={empresa.pk}', datos)


def subido(client, empresa, apertura_id, contenido, **extra):
    respuesta = subir(client, empresa, apertura_id, contenido, **extra)
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()['lote']


def mapear_lote(client, empresa, apertura, lote, version=None, **datos):
    return enviar(client, f'{API}{apertura["id"]}/mapear/', empresa,
                  {'version': version if version is not None else apertura['version'], 'lote_id': lote['id'], **datos})


def version(client, empresa, apertura):
    return leer(client, f'{API}{apertura["id"]}/', empresa)['apertura']['version']


@pytest.fixture
def cuentas(empresa):
    return ayudas.plan_minimo(empresa)


@pytest.fixture
def web(client, empresa, admin, cuentas):
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    return client


@pytest.fixture
def apertura(web, empresa):
    return creada(web, empresa)


def cuenta(c):
    return {'id': c.pk, 'codigo': c.codigo, 'nombre': c.nombre, 'tipo': c.tipo}


# ---------------------------------------------------------------- subir y vista previa

class TestSubir:

    def test_csv_con_punto_y_coma_y_bom(self, web, empresa, cuentas, apertura, admin):
        contenido = csv_de(*SALDOS, bom=True)
        respuesta = subir(web, empresa, apertura['id'], contenido, nombre='balance 2025.csv', clave='importar-saldos-1')
        assert respuesta.status_code == 200, respuesta.content
        assert respuesta.json()['repetido'] is False
        lote = respuesta.json()['lote']
        assert list(lote) == ['id', 'apertura_id', 'estado', 'tipo', 'archivo', 'tamano', 'sha256', 'encabezados', 'columnas',
                              'decisiones', 'muestra', 'filas', 'resumen', 'subido_por', 'subido_en', 'aplicado_por',
                              'aplicado_en']
        assert (lote['apertura_id'], lote['estado'], lote['tipo'], lote['archivo'], lote['tamano']) == (
            apertura['id'], 'vista_previa', 'saldos', 'balance 2025.csv', len(contenido))
        assert lote['sha256'] == hashlib.sha256(contenido).hexdigest()
        assert lote['encabezados'] == ['Código', 'Nombre', 'Debe', 'Haber']
        assert lote['columnas'] == {'codigo': 'Código', 'rubro': 'Nombre', 'debe': 'Debe', 'haber': 'Haber', 'saldo': None}
        assert lote['filas'] == [
            {'fila': 2, 'codigo': '1.1.01', 'rubro': 'Caja', 'debe': '10000.00', 'haber': '0.00', 'cuenta': cuenta(cuentas['caja']),
             'estado': 'valida', 'errores': []},
            {'fila': 3, 'codigo': '3.1.01', 'rubro': 'Capital social', 'debe': '0.00', 'haber': '10000.00',
             'cuenta': cuenta(cuentas['capital']), 'estado': 'valida', 'errores': []}]
        assert lote['resumen'] == {'validas': 2, 'sin_cuenta': 0, 'de_grupo': 0, 'duplicadas': 0, 'con_error': 0, 'omitidas': 0,
                                   'debe': '10000.00', 'haber': '10000.00', 'diferencia': '0.00', 'faltan_columnas': []}
        assert (lote['subido_por'], lote['aplicado_por'], lote['aplicado_en'], lote['decisiones']) == ('propietario.a', None, None, [])
        # nada escrito en las líneas hasta mapear
        assert en(empresa, LineaApertura.objects.count) == 0
        assert version(web, empresa, apertura) == 1
        # el archivo, privado y tal como llegó
        guardado = en(empresa, lambda: ImportacionApertura.objects.get(pk=lote['id']))
        assert guardado.archivo.name.startswith(f'privado/empresas/{empresa.uuid}/apertura/')
        with guardado.archivo.open('rb') as archivo:
            assert archivo.read() == contenido
        assert (guardado.creado_por_id, guardado.clave) == (admin.pk, 'importar-saldos-1')
        assert eventos(empresa, apertura['id'])[-1] == ('importada', '', '')
        assert list(AuditLog.objects.filter(action='apertura_importada').values_list('detail', flat=True)) == [
            {'apertura': apertura['id'], 'lote': lote['id'], 'archivo': 'balance 2025.csv', 'sha256': lote['sha256'], 'filas': 2}]
        assert leer(web, f'{API}importar/{lote["id"]}/', empresa)['lote'] == lote   # recarga
        archivos = leer(web, f'{API}{apertura["id"]}/', empresa)['archivos']
        assert [(a['clase'], a['id'], a['sha256']) for a in archivos] == [('importacion', lote['id'], lote['sha256'])]

    def test_csv_con_coma_y_xlsx_leen_lo_mismo(self, web, empresa, apertura):
        con_coma = subido(web, empresa, apertura['id'], csv_de(*SALDOS, separador=','))
        hoja = subido(web, empresa, apertura['id'], xlsx_de(('Código', 'Nombre', 'Debe', 'Haber'), ('1.1.01', 'Caja', 10000, None),
                                                            ('3.1.01', 'Capital social', None, 10000.0)), nombre='saldos.xlsx')
        assert con_coma['filas'] == hoja['filas'] and con_coma['resumen'] == hoja['resumen']

    def test_una_sola_columna_de_saldo(self, web, empresa, cuentas, apertura):
        lote = subido(web, empresa, apertura['id'], csv_de(('Cuenta', 'Descripción', 'Saldo'), ('1.1.01', 'Caja', '1.250,50'),
                                                            ('2.1.01', 'Proveedores', '-1250.50')))
        assert lote['columnas'] == {'codigo': 'Cuenta', 'rubro': 'Descripción', 'debe': None, 'haber': None, 'saldo': 'Saldo'}
        assert [(f['debe'], f['haber']) for f in lote['filas']] == [('1250.50', '0.00'), ('0.00', '1250.50')]   # positivo = deudor

    def test_cada_estado_de_fila(self, web, empresa, cuentas, apertura):
        lote = subido(web, empresa, apertura['id'], csv_de(
            ('Código', 'Nombre', 'Debe', 'Haber'),
            ('1.1.01', 'Caja', '100.00', ''),                # 2 válida
            ('1.9.99', 'Caja chica sin cuenta', '5.00', ''), # 3 sin cuenta en el plan
            ('1', 'ACTIVO', '105.00', ''),                    # 4 grupo (subtotal)
            ('1.1.01', 'Caja otra vez', '1.00', ''),         # 5 duplicada
            ('1.1.02', 'Bancos', 'abc', ''),                 # 6 error
            ('1.1.03', 'Clientes', '', ''),                  # 7 importe desconocido: válida, sin sumar
        ))
        assert [(f['fila'], f['estado']) for f in lote['filas']] == [(2, 'valida'), (3, 'sin_cuenta'), (4, 'de_grupo'),
                                                                     (5, 'duplicada'), (6, 'error'), (7, 'valida')]
        filas = {f['fila']: f for f in lote['filas']}
        assert filas[3]['cuenta'] is None and filas[4]['cuenta'] == cuenta(cuentas['activo'])
        assert filas[4]['errores'] == [TI['de_grupo'].format(codigo='1')]
        assert filas[5]['errores'] == [TI['duplicada'].format(codigo='1.1.01', fila=2)]
        assert filas[6]['errores'] == [ayudas_textos('importe')]
        assert (filas[7]['debe'], filas[7]['haber']) == (None, None)
        assert lote['resumen'] == {'validas': 2, 'sin_cuenta': 1, 'de_grupo': 1, 'duplicadas': 1, 'con_error': 1, 'omitidas': 0,
                                   'debe': None, 'haber': None, 'diferencia': None, 'faltan_columnas': []}

    def test_sin_columnas_de_importe(self, web, empresa, apertura):
        lote = subido(web, empresa, apertura['id'], csv_de(('Código', 'Nombre', 'Valor'), ('1.1.01', 'Caja', '1')))
        assert lote['filas'] == [] and lote['resumen']['faltan_columnas'] == [TI['faltan_importes']]
        assert lote['muestra'] == [['1.1.01', 'Caja', '1']]   # para elegir las columnas a mano

    def test_misma_clave(self, web, empresa, apertura):
        primero = subir(web, empresa, apertura['id'], csv_de(*SALDOS), clave='importar-repetido-1')
        otra_vez = subir(web, empresa, apertura['id'], csv_de(*SALDOS), clave='importar-repetido-1')
        assert otra_vez.json()['repetido'] is True and otra_vez.json()['lote']['id'] == primero.json()['lote']['id']
        rechazo(subir(web, empresa, apertura['id'], csv_de(*SALDOS[:2]), clave='importar-repetido-1'), 409, 'clave_usada')
        assert en(empresa, ImportacionApertura.objects.count) == 1

    def test_solo_en_borrador(self, web, empresa, apertura):
        en(empresa, lambda: Apertura.objects.filter(pk=apertura['id']).update(estado='en_revision'))
        datos = rechazo(subir(web, empresa, apertura['id'], csv_de(*SALDOS)), 409, 'estado')
        assert (datos['estado'], datos['permitidos']) == ('en_revision', ['borrador'])
        # el estado va antes que la validación del archivo
        rechazo(subir(web, empresa, apertura['id'], b'%PDF-1.4 no es una tabla'), 409, 'estado')
        assert en(empresa, ImportacionApertura.objects.count) == 0

    def test_limites_y_archivos_ilegibles(self, web, empresa, apertura):
        grande = b'x' * (lectura_tabular.MAX_BYTES + 1)
        assert rechazo(subir(web, empresa, apertura['id'], grande), 400, 'archivo_grande')['error'] == TL['archivo_grande']
        filas = [('Código', 'Nombre', 'Debe', 'Haber')] + [(f'9.{i}', f'Cuenta {i}', '1.00', '') for i in range(5001)]
        assert rechazo(subir(web, empresa, apertura['id'], csv_de(*filas)), 400, 'demasiadas_filas')['error'] == TL['demasiadas_filas']
        rechazo(subir(web, empresa, apertura['id'], PDF, nombre='saldos.pdf'), 400, 'formato')   # un PDF respalda, no alimenta
        assert rechazo(subir(web, empresa, apertura['id'], csv_de(SALDOS[0])), 400, 'formato')['error'] == TL['sin_filas']
        assert errores(subir(web, empresa, apertura['id'], csv_de(*SALDOS), tipo='auxiliares')) == {'tipo': [TI['tipo_auxiliares']]}
        assert errores(subir(web, empresa, apertura['id'], None)) == {'archivo': [TI['archivo']]}
        assert en(empresa, ImportacionApertura.objects.count) == 0

    def test_el_lector_es_el_de_c3_con_los_textos_de_la_apertura(self):
        """El lector común es el del plan de cuentas (importar_cuentas.leer lo llama con sus textos): las mismas defensas y
        los mismos límites. Cada importación solo cambia los textos que hablan de lo que trae la tabla."""
        from core.contabilidad import importar_cuentas
        assert (lectura_tabular.MAX_BYTES, lectura_tabular.MAX_FILAS) == (2 * 1024 * 1024, 5000)
        assert (importar_cuentas.MAX_BYTES, importar_cuentas.MAX_FILAS) == (lectura_tabular.MAX_BYTES, lectura_tabular.MAX_FILAS)
        assert lectura_tabular.leer(csv_de(*SALDOS)) == importar_cuentas.leer(csv_de(*SALDOS))
        assert set(TL) <= set(lectura_tabular.CASOS) and set(lectura_tabular.CASOS) <= set(importar_cuentas.TEXTOS)
        lectores = ((lectura_tabular.leer, lectura_tabular.TEXTOS), (importar_cuentas.leer, importar_cuentas.TEXTOS),
                    (lambda datos: lectura_tabular.leer(datos, TL), TL))
        for lector, textos in lectores:
            with pytest.raises(api.ErrorApi) as error:
                lector(csv_de(SALDOS[0]))
            assert str(error.value) == textos['sin_filas']
        assert importar_cuentas.TEXTOS['sin_filas'] != lectura_tabular.TEXTOS['sin_filas'] != TL['sin_filas']


class TestLectorComun:
    """Las defensas que el bloque 1 puso en el lector después de que la apertura empezara a usarlo (191a5c9 y cd23065)
    están en lectura_tabular.py y valen por la ruta de la apertura igual que por la del plan de cuentas, donde
    tests/test_cuentas_importacion.py las prueba enteras: una parte en bzip2 o lzma no se abre, ninguna parte XML declara
    entidades y las imágenes llegan vacías al lector."""

    @pytest.mark.parametrize('parte', ['xl/media/relleno.bin', 'xl/worksheets/sheet1.xml'])
    @pytest.mark.parametrize('metodo', [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA], ids=['bzip2', 'lzma'])
    def test_xlsx_con_una_parte_comprimida_de_otra_forma(self, web, empresa, apertura, parte, metodo):
        """Unos kilobytes que declaran 1 KB y traen 32 MB de relleno en bzip2 o lzma: `ZipFile` los descomprimiría de una
        vez. Se rechazan antes de abrir la parte, sin que suba la memoria, y no queda lote."""
        datos = saldos_con_relleno(parte, metodo)
        assert len(datos) < 100_000
        tracemalloc.start()
        try:
            with pytest.raises(api.ErrorApi) as negativa:
                lectura_tabular.leer(datos, TL)
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert (negativa.value.codigo, str(negativa.value)) == ('formato', lectura_tabular.TEXTOS['formato'])
        assert pico < 16 * MB, f'{pico / MB:.0f} MB'
        respuesta = subir(web, empresa, apertura['id'], datos, nombre='saldos.xlsx')
        assert rechazo(respuesta, 400, 'formato')['error'] == lectura_tabular.TEXTOS['formato']
        assert en(empresa, ImportacionApertura.objects.count) == 0

    def test_xlsx_con_entidades_xml(self, web, empresa, apertura):
        datos = saldos_con_entidad()
        libro = openpyxl.load_workbook(io.BytesIO(datos), read_only=True)   # leído tal cual, la entidad se expande
        try:
            assert list(libro.worksheets[0].iter_rows(min_row=2, max_row=2, values_only=True))[0][:2] == ('1.1.01', 'CajaCaja')
        finally:
            libro.close()
        respuesta = subir(web, empresa, apertura['id'], datos, nombre='saldos.xlsx')
        assert rechazo(respuesta, 400, 'formato')['error'] == lectura_tabular.TEXTOS['xlsx_declaraciones']
        assert en(empresa, ImportacionApertura.objects.count) == 0

    def test_xlsx_con_un_logo_svg(self, web, empresa, apertura):
        """El DOCTYPE de un logo SVG en xl/media no rechaza el archivo: esa parte no es XML del libro y llega vacía."""
        lote = subido(web, empresa, apertura['id'], saldos_con_logo_svg(), nombre='saldos.xlsx')
        assert [(f['codigo'], f['estado']) for f in lote['filas']] == [('1.1.01', 'valida'), ('3.1.01', 'valida')]


def ayudas_textos(clave):
    from core.contabilidad.apertura import TEXTOS
    return TEXTOS[clave]


# ---------------------------------------------------------------- mapear desde el lote

class TestMapearDesdeElLote:

    BALANCE = (('Código', 'Nombre', 'Debe', 'Haber'),
               ('1', 'ACTIVO', '10500.00', ''),              # 2 subtotal: se omite
               ('1.1.01', 'Caja', '10000.00', ''),           # 3
               ('1.1.01', 'Caja chica', '500.00', ''),       # 4 agrupada con la 3
               ('X-1', 'Fondo sin cuenta', '', ''),           # 5 sin cuenta: línea sin mapear
               ('3.1.01', 'Capital social', '', '10500.00'))  # 6

    DECISIONES = [{'fila': 2, 'omitir': True, 'motivo': 'Subtotal del grupo'}, {'fila': 4, 'agrupar': True}]

    def test_lleva_las_filas_a_las_lineas(self, web, empresa, cuentas, apertura):
        lote = subido(web, empresa, apertura['id'], csv_de(*self.BALANCE))
        respuesta = mapear_lote(web, empresa, apertura, lote, decisiones=self.DECISIONES)
        assert respuesta.status_code == 200, respuesta.content
        datos = respuesta.json()
        assert (datos['apertura']['debe'], datos['apertura']['haber'], datos['apertura']['pendientes']) == (
            None, None, {'sin_cuenta': 1, 'importe_pendiente': 1, 'de_grupo': 0, 'sin_clase': 0})
        caja, sin_cuenta, capital = datos['lineas']
        assert (caja['cuenta']['codigo'], caja['debe'], caja['codigo_origen'], caja['rubro']) == ('1.1.01', '10500.00', '1.1.01', 'Caja')
        assert caja['filas_origen'] == [{'fila': 3, 'codigo': '1.1.01', 'rubro': 'Caja', 'debe': '10000.00', 'haber': '0.00'},
                                        {'fila': 4, 'codigo': '1.1.01', 'rubro': 'Caja chica', 'debe': '500.00', 'haber': '0.00'}]
        assert (sin_cuenta['cuenta'], sin_cuenta['codigo_origen'], sin_cuenta['debe']) == (None, 'X-1', None)
        assert capital['haber'] == '10500.00'
        with company_context(empresa):
            assert set(LineaApertura.objects.values_list('lote_id', flat=True)) == {lote['id']}
            guardado = ImportacionApertura.objects.get(pk=lote['id'])
            assert guardado.estado == 'aplicado' and guardado.aplicado_por_nombre == 'propietario.a'
        recargado = leer(web, f'{API}importar/{lote["id"]}/', empresa)['lote']
        assert recargado['estado'] == 'aplicado' and recargado['decisiones'] == [
            {'fila': 2, 'cuenta_id': None, 'omitir': True, 'motivo': 'Subtotal del grupo', 'agrupar': False,
             'es_resultado_ejercicio': False},
            {'fila': 4, 'cuenta_id': None, 'omitir': False, 'motivo': '', 'agrupar': True, 'es_resultado_ejercicio': False}]
        assert [f['estado'] for f in recargado['filas']] == ['omitida', 'valida', 'valida', 'sin_cuenta', 'valida']
        detalle = en(empresa, lambda: AuditLog.objects.filter(action='apertura_modificada').get().detail)
        assert detalle == {'apertura': apertura['id'], 'version': 2, 'accion': 'mapear', 'altas': 3, 'cambios': 0, 'retiradas': 0,
                           'lote_id': lote['id'], 'omitidas': 1, 'agrupadas': 1}
        # la fila sin cuenta se asigna con una decisión; las demás líneas conservan su id
        mapeada = mapear_lote(web, empresa, datos['apertura'], lote, decisiones=[
            *self.DECISIONES, {'fila': 5, 'cuenta_id': cuentas['bancos'].pk}]).json()
        assert [l['id'] for l in mapeada['lineas'] if not l['retirada'] and l['cuenta']['codigo'] != '1.1.02'] == [caja['id'], capital['id']]
        assert mapeada['retiradas'] == 1   # la línea sin cuenta, que ya no viene
        bancos = next(l for l in mapeada['lineas'] if l['cuenta'] and l['cuenta']['codigo'] == '1.1.02')
        assert (bancos['debe'], bancos['detalle']) == (None, 'banco')

    def test_errores_por_fila_y_por_decision(self, web, empresa, cuentas, apertura):
        lote = subido(web, empresa, apertura['id'], csv_de(*self.BALANCE, ('1.1.02', 'Bancos', '1.001', '')))
        assert errores(mapear_lote(web, empresa, apertura, lote), 'cuenta_de_grupo') == {
            'filas.2.cuenta': [TI['de_grupo'].format(codigo='1')], 'filas.4.cuenta': [TI['duplicada'].format(codigo='1.1.01', fila=3)],
            'filas.7.debe': [ayudas_textos('decimales')]}
        assert errores(mapear_lote(web, empresa, apertura, lote, decisiones=[
            {'fila': 2, 'omitir': True}, {'fila': 99}, {'fila': 4, 'agrupar': True}, {'fila': 4}, 'x',
            {'fila': 7, 'cuenta_id': cuentas['activo'].pk}]), 'cuenta_de_grupo') == {
            'decisiones.0.motivo': [TI['motivo_omitir']], 'decisiones.1.fila': [TI['fila']],
            'decisiones.3.fila': [TI['fila_repetida'].format(fila=4)], 'decisiones.4': [TI['decision']],
            'decisiones.5.cuenta_id': [TI['de_grupo'].format(codigo='1')], 'filas.7.debe': [ayudas_textos('decimales')]}
        assert en(empresa, LineaApertura.objects.count) == 0 and version(web, empresa, apertura) == 1

    def test_importes_que_no_son_importes(self, web, empresa, cuentas, apertura):
        """D1: lo que una hoja de cálculo escribe en un CSV para un número de 12 cifras («1,23457E+11») y otros textos que
        Decimal() lee pero no son un importe («1e3», «1_000», «１２３») son un error de su fila, no un importe redondeado."""
        lote = subido(web, empresa, apertura['id'], csv_de(
            ('Código', 'Nombre', 'Debe', 'Haber'), ('1.1.01', 'Caja', '1,23457E+11', ''), ('1.1.02', 'Bancos', '1e3', ''),
            ('1.1.03', 'Clientes', '1_000', ''), ('1.1.04', 'Inventario', '１２３', ''), ('3.1.01', 'Capital', '', '1000,00')))
        importe = ayudas_textos('importe')
        assert [(f['estado'], f['errores']) for f in lote['filas']] == [('error', [importe])] * 4 + [('valida', [])]
        assert errores(mapear_lote(web, empresa, apertura, lote)) == {f'filas.{n}.debe': [importe] for n in (2, 3, 4, 5)}
        assert en(empresa, LineaApertura.objects.count) == 0

    def test_celdas_numericas_del_xlsx(self, web, empresa, cuentas, apertura):
        """D1 no cambia el camino de las celdas numéricas: el lector las pasa a texto con repr(), y su ruido de coma
        flotante se redondea, también el de una fórmula que da cero, que repr() escribe en notación científica."""
        ruido_cero = 0.1 + 0.2 - 0.3
        assert repr(ruido_cero) == '5.551115123125783e-17'
        lote = subido(web, empresa, apertura['id'], xlsx_de(
            ('Código', 'Nombre', 'Debe', 'Haber'), ('1.1.01', 'Caja', 1234.5600000000002, ruido_cero),
            ('1.1.02', 'Bancos', 765, None), ('3.1.01', 'Capital', ruido_cero, 1999.56)))
        assert [f['estado'] for f in lote['filas']] == ['valida'] * 3
        datos = mapear_lote(web, empresa, apertura, lote).json()
        assert [(l['debe'], l['haber']) for l in datos['lineas']] == [('1234.56', '0.00'), ('765.00', '0.00'), ('0.00', '1999.56')]

    def test_las_columnas_se_eligen_al_mapear(self, web, empresa, cuentas, apertura):
        lote = subido(web, empresa, apertura['id'], csv_de(('Cta', 'Detalle', 'Valor'), ('1.1.01', 'Caja', '7.00'),
                                                            ('3.1.01', 'Capital', '-7.00')))
        assert lote['resumen']['faltan_columnas'] == [TI['faltan_importes']]   # «Detalle» sí se reconoce como el rubro
        assert errores(mapear_lote(web, empresa, apertura, lote, columnas={'codigo': 'Otra', 'debe': 'Valor', 'saldo': 'Valor'})) == {
            'columnas.codigo': [TI['columna']], 'columnas.saldo': [TI['columna_repetida']], 'columnas': [TI['faltan_cuentas']]}
        assert errores(mapear_lote(web, empresa, apertura, lote, columnas={'codigo': 'Cta', 'debe': 'Valor', 'saldo': 'Detalle'})) == {
            'columnas': [TI['importes_dobles']]}
        datos = mapear_lote(web, empresa, apertura, lote, columnas={'codigo': 'Cta', 'rubro': 'Detalle', 'saldo': 'Valor'}).json()
        assert [(l['cuenta']['codigo'], l['debe'], l['haber']) for l in datos['lineas']] == [('1.1.01', '7.00', '0.00'),
                                                                                            ('3.1.01', '0.00', '7.00')]
        assert leer(web, f'{API}importar/{lote["id"]}/', empresa)['lote']['columnas']['saldo'] == 'Valor'

    def test_lote_de_otra_apertura_o_de_otra_empresa(self, web, client, empresa, empresa_b, cuentas, apertura):
        lote = subido(web, empresa, apertura['id'], csv_de(*SALDOS))
        servicio_descartar(web, empresa, apertura)
        otra = creada(web, empresa)
        assert rechazo(mapear_lote(web, empresa, otra, lote), 404, 'no_existe')['error'] == TI['lote']
        ayudas.plan_minimo(empresa_b)
        with company_context(empresa_b):
            ajena = ImportacionApertura.objects.create(apertura=ayudas.apertura_directa(empresa_b), tipo='saldos', archivo='x.csv',
                                                       nombre='x.csv', tamano=1, sha256='0' * 64, clave=ayudas.clave('ajena'),
                                                       creado_por_nombre='x')
        rechazo(web.get(f'{API}importar/{ajena.pk}/?empresa={empresa.pk}'), 404, 'no_existe')
        rechazo(mapear_lote(web, empresa, otra, {'id': ajena.pk}), 404, 'no_existe')

    def test_5000_filas_sin_consultas_por_fila(self, web, empresa, apertura):
        ids = plan_grande(empresa, 5000)
        filas = [('Código', 'Nombre', 'Debe', 'Haber')] + [(f'9.{i:05d}', f'Cuenta {i}', '1.00', '') for i in range(5000)]

        def contar(funcion):
            with CaptureQueriesContext(connection) as capturadas:
                resultado = funcion()
            return len(capturadas), resultado
        n_pocas, _ = contar(lambda: subido(web, empresa, apertura['id'], csv_de(*filas[:11])))
        n_todas, lote = contar(lambda: subido(web, empresa, apertura['id'], csv_de(*filas)))
        assert lote['resumen']['validas'] == 5000 and len(ids) == 5000
        assert n_todas == n_pocas, (n_pocas, n_todas)
        n_recarga, _ = contar(lambda: leer(web, f'{API}importar/{lote["id"]}/', empresa))
        assert n_recarga <= 10
        n_mapear, respuesta = contar(lambda: mapear_lote(web, empresa, apertura, lote))
        assert respuesta.status_code == 200 and respuesta.json()['apertura']['debe'] == '5000.00'
        lotes = 5 if connection.vendor == 'postgresql' else 5000 * 16 // 999 + 5
        assert n_mapear <= 25 + lotes, n_mapear


# ---------------------------------------------------------------- respaldos

def subir_respaldo(client, empresa, apertura_id, contenido, nombre, clave=None, descripcion='Balance firmado'):
    return client.post(f'{API}{apertura_id}/respaldos/?empresa={empresa.pk}',
                       {'empresa': empresa.pk, 'clave': clave or ayudas.clave('respaldo'), 'descripcion': descripcion,
                        'archivo': SimpleUploadedFile(nombre, contenido)})


class TestRespaldos:

    @pytest.mark.parametrize('nombre, contenido, tipo', [
        ('balance.pdf', PDF, 'application/pdf'),
        ('foto.png', None, 'image/png'),
        ('foto.jpeg', None, 'image/jpeg'),
        ('balance.xlsx', None, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
        ('balance.csv', None, 'text/csv'),
    ])
    def test_formatos_admitidos(self, web, empresa, apertura, nombre, contenido, tipo):
        contenido = contenido or {'foto.png': lambda: imagen('PNG'), 'foto.jpeg': lambda: imagen('JPEG'),
                                  'balance.xlsx': lambda: xlsx_de(*SALDOS), 'balance.csv': lambda: csv_de(*SALDOS)}[nombre]()
        respuesta = subir_respaldo(web, empresa, apertura['id'], contenido, nombre)
        assert respuesta.status_code == 201, respuesta.content
        respaldo = respuesta.json()['respaldo']
        assert respuesta.json()['repetido'] is False
        assert respaldo == {'id': respaldo['id'], 'nombre': nombre.replace('.jpeg', '.jpg'), 'tipo': tipo, 'tamano': len(contenido),
                            'sha256': hashlib.sha256(contenido).hexdigest(), 'descripcion': 'Balance firmado',
                            'subido_por': 'propietario.a', 'subido_en': respaldo['subido_en'], 'estado': 'vigente',
                            'anulado_por': None, 'anulado_en': None, 'motivo_anulacion': '', 'url': None,
                            'recurso': {'tipo': 'respaldo_apertura', 'id': respaldo['id'],
                                        'api': f'/contabilidad/api/apertura/respaldos/{respaldo["id"]}/descargar/'}}
        descarga = web.get(f'{respaldo["recurso"]["api"]}?empresa={empresa.pk}')
        assert descarga.status_code == 200 and b''.join(descarga.streaming_content) == contenido
        assert descarga['Content-Type'] == tipo and descarga['Content-Disposition'].startswith('attachment')
        assert (descarga['Cache-Control'], descarga['X-Content-Type-Options']) == ('private, no-store', 'nosniff')
        assert descarga['Content-Security-Policy'] == "sandbox; default-src 'none'; img-src 'self'"
        assert en(empresa, lambda: RespaldoApertura.objects.get(pk=respaldo['id']).archivo.name).startswith(
            f'privado/empresas/{empresa.uuid}/apertura/')

    def test_rechazados_por_su_contenido(self, web, empresa, apertura):
        webp = b'RIFF\x24\x00\x00\x00WEBPVP8 ' + b'\x00' * 24
        zip_ = io.BytesIO()
        with zipfile.ZipFile(zip_, 'w') as comprimido:
            comprimido.writestr('documento.txt', 'no es un libro')
        for nombre, contenido, texto in (
                ('foto.webp', webp, 'WEBP'), ('libro.xlsx', zip_.getvalue(), 'Solo se admiten'),
                ('foto.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * 20, 'imagen'), ('pagina.csv', b'<html><body>x</body></html>', 'Solo'),
                ('binario.csv', b'a;b\x00\x01\x02', 'Solo'), ('vacio.pdf', b'', 'vacío')):
            respuesta = subir_respaldo(web, empresa, apertura['id'], contenido, nombre)
            assert texto in errores(respuesta)['archivo'][0], nombre
        grande = subir_respaldo(web, empresa, apertura['id'], PDF + b'0' * respaldos.MAX_BYTES, 'grande.pdf')
        rechazo(grande, 400, 'archivo_grande')
        assert en(empresa, RespaldoApertura.objects.count) == 0

    def test_misma_clave_y_estado(self, web, empresa, apertura):
        primero = subir_respaldo(web, empresa, apertura['id'], PDF, 'a.pdf', clave='respaldo-repetido-1')
        otra_vez = subir_respaldo(web, empresa, apertura['id'], PDF, 'a.pdf', clave='respaldo-repetido-1')
        assert otra_vez.status_code == 200 and otra_vez.json()['repetido'] is True
        assert otra_vez.json()['respaldo']['id'] == primero.json()['respaldo']['id']
        rechazo(subir_respaldo(web, empresa, apertura['id'], PDF + b' ', 'a.pdf', clave='respaldo-repetido-1'), 409, 'clave_usada')
        en(empresa, lambda: Apertura.objects.filter(pk=apertura['id']).update(estado='descartada', motivo='prueba'))
        rechazo(subir_respaldo(web, empresa, apertura['id'], PDF, 'b.pdf'), 409, 'estado')
        assert en(empresa, RespaldoApertura.objects.count) == 1

    def test_la_misma_clave_en_otra_apertura(self, web, empresa, apertura):
        """B2-AP-5: la apertura de la ruta es parte del envío (decisión común 5a), como en la importación de saldos: la
        misma clave con el mismo archivo en otra apertura es otro envío, 409 `clave_usada` con el respaldo que ya existe.
        Antes respondía 200 `repetido` con el respaldo de la primera y la segunda se quedaba sin el suyo."""
        primero = subir_respaldo(web, empresa, apertura['id'], PDF, 'balance.pdf', clave='respaldo-clave-0001')
        assert primero.status_code == 201, primero.content
        servicio_descartar(web, empresa, apertura)
        otra = creada(web, empresa)
        cuerpo = rechazo(subir_respaldo(web, empresa, otra['id'], PDF, 'balance.pdf', clave='respaldo-clave-0001'), 409,
                         'clave_usada')
        assert cuerpo['respaldo']['id'] == primero.json()['respaldo']['id']
        assert en(empresa, lambda: list(RespaldoApertura.objects.values_list('apertura_id', flat=True))) == [apertura['id']]
        # en su apertura, el mismo envío sigue siendo `repetido`
        otra_vez = subir_respaldo(web, empresa, apertura['id'], PDF, 'balance.pdf', clave='respaldo-clave-0001')
        assert otra_vez.status_code == 200 and otra_vez.json()['repetido'] is True

    def test_anular_conserva_el_archivo(self, web, empresa, apertura):
        respaldo = subir_respaldo(web, empresa, apertura['id'], PDF, 'balance.pdf').json()['respaldo']
        ruta = f'{API}respaldos/{respaldo["id"]}/anular/'
        assert errores(enviar(web, ruta, empresa, {})) == {'motivo': [ayudas_textos('motivo')]}
        anulado = enviar(web, ruta, empresa, {'motivo': 'Se subió el del año anterior.'}).json()['respaldo']
        assert (anulado['estado'], anulado['anulado_por'], anulado['motivo_anulacion']) == (
            'anulado', 'propietario.a', 'Se subió el del año anterior.')
        rechazo(enviar(web, ruta, empresa, {'motivo': 'Otra vez.'}), 409, 'ya_anulado')
        descarga = web.get(f'{respaldo["recurso"]["api"]}?empresa={empresa.pk}')
        assert b''.join(descarga.streaming_content) == PDF   # el archivo se conserva
        assert [e[0] for e in eventos(empresa, apertura['id'])][-2:] == ['respaldo_subido', 'respaldo_anulado']
        assert [d['accion'] for d in AuditLog.objects.filter(action='apertura_respaldo').order_by('id').values_list('detail', flat=True)] == [
            'subido', 'anulado']

    def test_de_otra_empresa_no_existe(self, web, empresa, empresa_b):
        with company_context(empresa_b):
            ajeno = RespaldoApertura.objects.create(apertura=ayudas.apertura_directa(empresa_b), archivo='x.pdf', nombre='x.pdf',
                                                    tipo_mime='application/pdf', tamano=1, sha256='0' * 64,
                                                    clave=ayudas.clave('ajeno'), subido_por_nombre='x')
        rechazo(web.get(f'{API}respaldos/{ajeno.pk}/descargar/?empresa={empresa.pk}'), 404, 'no_existe')
        rechazo(enviar(web, f'{API}respaldos/{ajeno.pk}/anular/', empresa, {'motivo': 'x'}), 404, 'no_existe')
        assert en(empresa_b, lambda: RespaldoApertura.objects.get(pk=ajeno.pk).anulado_en) is None


class TestValidarRespaldo:

    def test_xlsx_con_declaraciones_no_pasa(self):
        partes = {}
        with zipfile.ZipFile(io.BytesIO(xlsx_de(*SALDOS))) as libro:
            for parte in libro.infolist():
                partes[parte.filename] = libro.read(parte)
        partes['xl/worksheets/sheet1.xml'] = b'<!DOCTYPE x [<!ENTITY a "b">]>' + partes['xl/worksheets/sheet1.xml']
        salida = io.BytesIO()
        with zipfile.ZipFile(salida, 'w') as libro:
            for nombre, contenido in partes.items():
                libro.writestr(nombre, contenido)
        with pytest.raises(respaldos.ArchivoInvalido):
            respaldos.validar('libro.xlsx', salida.getvalue())

    @pytest.mark.parametrize('metodo', [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA], ids=['bzip2', 'lzma'])
    def test_xlsx_con_una_parte_comprimida_de_otra_forma_no_pasa(self, metodo):
        """El respaldo se valida con el mismo revisor de partes que la importación (lectura_tabular.es_xlsx)."""
        with pytest.raises(respaldos.ArchivoInvalido):
            respaldos.validar('balance.xlsx', saldos_con_relleno('xl/media/relleno.bin', metodo))

    def test_xlsx_con_un_logo_svg_pasa(self):
        datos = saldos_con_logo_svg()
        assert respaldos.validar('balance.xlsx', datos) == ('balance.xlsx', respaldos.TIPOS[respaldos.XLSX],
                                                            hashlib.sha256(datos).hexdigest())

    def test_csv_en_windows_1252_y_nombre_saneado(self):
        nombre, tipo, sha256 = respaldos.validar('C:\\docs\\Año 2025\x07.txt', 'Código;Año\n1;añejo\n'.encode('cp1252'))
        assert (nombre, tipo) == ('Año 2025.csv', 'text/csv')
        assert sha256 == hashlib.sha256('Código;Año\n1;añejo\n'.encode('cp1252')).hexdigest()

    def test_solo_los_admitidos(self):
        with pytest.raises(respaldos.ArchivoInvalido) as error:
            respaldos.validar('a.csv', b'a;b\n', admitidos=(respaldos.PDF,))
        assert 'Solo se admiten respaldos en PDF' in str(error.value)
