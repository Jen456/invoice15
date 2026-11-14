"""Importación del plan de cuentas con vista previa (C3 del contrato contable v9): core/contabilidad/importar_cuentas.py y
vistas_importar_cuentas.py.

POST /contabilidad/api/cuentas/importar/ (subida), GET …/<id>/, POST …/<id>/mapeo/ y POST …/<id>/confirmar/: lectura de CSV
(`;` y `,`, con y sin BOM, comillas) y de XLSX; columnas por encabezado y mapeo a mano; jerarquía por los puntos del código
y por columna padre; tipos escritos y deducidos; filas válidas, duplicadas y con error (todos sus errores); límites;
confirmación idempotente y recalculada; nada creado antes de confirmar; archivo privado con su huella; permisos, empresa de
la pestaña y licencia; auditoría; 5 000 filas; seguridad por filas (PostgreSQL). La concurrencia real va en
tests/test_zz_cuentas_concurrencia_pg.py."""
import csv
import hashlib
import io
import json
import os
import struct
import time
import tracemalloc
import zipfile
import zlib
from datetime import date, timedelta
from itertools import count
from types import SimpleNamespace

import openpyxl
import pytest
from django.conf import settings as configuracion
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.contabilidad import api, capacidades, cuentas, importar_cuentas
from core.contabilidad.models import Cuenta, ImportacionCuentas
from core.tenancy import pestanas
from core.tenancy.context import company_context
from core.tenancy.models import (ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog,
                                 Membership)
from tests import helpers

pytestmark = pytest.mark.django_db

API = '/contabilidad/api/cuentas/importar/'
CUENTAS = '/contabilidad/api/cuentas/'
T = importar_cuentas.TEXTOS
_claves = count(1)
PLAN = (('Código', 'Nombre'), ('1', 'Activo'), ('1.1', 'Activo corriente'), ('1.1.01', 'Caja'), ('1.1.02', 'Bancos'),
        ('2', 'Pasivo'))


# ---------------------------------------------------------------- ayudas

def en(empresa, funcion):
    with company_context(empresa):
        return funcion()


def csv_de(*filas, separador=';', bom=False):
    salida = io.StringIO()
    csv.writer(salida, delimiter=separador, lineterminator='\r\n').writerows(filas)
    return (b'\xef\xbb\xbf' if bom else b'') + salida.getvalue().encode('utf-8')


def xlsx_de(*filas, otra_hoja=()):
    libro = openpyxl.Workbook()
    for fila in filas:
        libro.active.append(fila)
    if otra_hoja:
        hoja = libro.create_sheet('Otra')
        for fila in otra_hoja:
            hoja.append(fila)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def partes_de(xlsx):
    """Las partes de un XLSX (es un ZIP): {nombre: contenido}."""
    with zipfile.ZipFile(io.BytesIO(xlsx)) as comprimido:
        return {parte.filename: comprimido.read(parte) for parte in comprimido.infolist()}


def xlsx_con(partes):
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, 'w', zipfile.ZIP_DEFLATED) as comprimido:
        for nombre, contenido in partes.items():
            comprimido.writestr(nombre, contenido)
    return salida.getvalue()


def xlsx_con_entidad(donde, codificacion=None):
    """El plan de siempre en un XLSX donde el nombre de la cuenta 1 no está escrito: sale de una entidad XML declarada en
    la hoja o en las cadenas compartidas (`&a;&a;`, que el lector expande a «ActivoActivo»). Es la forma de que unos
    kilobytes ocupen gigas al abrirlos: una entidad larga citada millones de veces."""
    partes = partes_de(xlsx_de(*PLAN))
    hoja = partes['xl/worksheets/sheet1.xml'].decode()
    activo = '<c r="B2" t="inlineStr"><is><t>Activo</t></is></c>'
    assert hoja.count(activo) == 1
    if donde == 'hoja':
        hoja = '<!DOCTYPE worksheet [<!ENTITY a "Activo">]>' + hoja.replace(activo, '<c r="B2" t="inlineStr"><is><t>&a;&a;</t></is></c>')
        retocada = 'xl/worksheets/sheet1.xml'
    else:
        hoja = hoja.replace(activo, '<c r="B2" t="s"><v>0</v></c>')
        partes['xl/sharedStrings.xml'] = (
            '<!DOCTYPE sst [<!ENTITY a "Activo">]>'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1">'
            '<si><t>&a;&a;</t></si></sst>')
        tipos = partes['[Content_Types].xml'].decode()
        assert tipos.endswith('</Types>')
        partes['[Content_Types].xml'] = tipos[:-len('</Types>')] + (
            '<Override PartName="/xl/sharedStrings.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
        retocada = 'xl/sharedStrings.xml'
    partes['xl/worksheets/sheet1.xml'] = hoja
    if codificacion:   # la misma parte en otra codificación que el lector de XML también entiende
        declarada = 'UTF-16' if codificacion.startswith('utf-16') else codificacion
        partes[retocada] = (f'<?xml version="1.0" encoding="{declarada}"?>' + partes[retocada]).encode(codificacion)
    return xlsx_con(partes)


def archivo(contenido, nombre='plan.csv'):
    return SimpleUploadedFile(nombre, contenido, content_type='application/octet-stream')


def subir(client, empresa, contenido, nombre='plan.csv', **extra):
    datos = {'empresa': empresa.pk, 'clave': f'subida-plan-{next(_claves):05d}', 'archivo': archivo(contenido, nombre)}
    datos.update(extra)
    return client.post(API, {campo: valor for campo, valor in datos.items() if valor is not None})


def lote_de(client, empresa, *filas, **extra):
    """Sube un CSV con esas filas y devuelve el lote en vista previa."""
    respuesta = subir(client, empresa, csv_de(*filas), **extra)
    assert respuesta.status_code == 200, respuesta.content
    return respuesta.json()['lote']


def enviar(client, url, datos):
    return client.post(url, json.dumps(datos), content_type='application/json')


def mapear(client, empresa, lote, **columnas):
    return enviar(client, f'{API}{lote["id"]}/mapeo/', {'empresa': empresa.pk, **columnas})


def confirmar(client, empresa, lote, duplicadas='omitir', **extra):
    datos = {'empresa': empresa.pk, 'clave': f'confirma-plan-{next(_claves):05d}', 'duplicadas': duplicadas}
    datos.update(extra)
    return enviar(client, f'{API}{lote["id"]}/confirmar/', datos)


def por_codigo(lote):
    return {fila['codigo']: fila for fila in lote['filas']}


def errores_por_fila(lote):
    return {fila['fila']: fila['errores'] for fila in lote['filas'] if fila['errores']}


def plan(empresa):
    """Las cuentas guardadas de la empresa: {código: (nombre, tipo, código del padre)}."""
    return en(empresa, lambda: {c.codigo: (c.nombre, c.tipo, c.padre.codigo if c.padre_id else None)
                                for c in Cuenta.objects.select_related('padre')})


def cuantas(empresa):
    return en(empresa, Cuenta.objects.count)


def lotes(empresa):
    return en(empresa, lambda: list(ImportacionCuentas.objects.order_by('id')))


def sembrar(empresa, codigo, nombre=None, tipo='movimiento', padre=None):
    return en(empresa, lambda: Cuenta.objects.create(codigo=codigo, nombre=nombre or f'Cuenta {codigo}', tipo=tipo, padre=padre))


def vencer(empresa):
    from core.suscripciones.models import SubscriptionPeriod
    SubscriptionPeriod.objects.filter(company=empresa).update(ends_at=timezone.now() - timedelta(days=1))


def sin_permiso(respuesta, codename):
    return respuesta.status_code == 403 and respuesta.json() == {
        'error': capacidades.TEXTO_SIN_PERMISO, 'codigo': 'sin_permiso', 'causa': 'permiso', 'permisos': [codename]}


def rechazo(respuesta, estado, codigo):
    return respuesta.status_code == estado and respuesta.json()['codigo'] == codigo


@pytest.fixture
def entrar(client, empresa, admin):
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    return client


# ---------------------------------------------------------------- lectura

class TestLectura:

    @pytest.mark.parametrize('separador, bom', [(';', False), (';', True), (',', False), (',', True)])
    def test_csv(self, entrar, empresa, separador, bom):
        respuesta = subir(entrar, empresa, csv_de(*PLAN, separador=separador, bom=bom), 'Plan de cuentas.csv')
        assert respuesta.status_code == 200
        lote = respuesta.json()['lote']
        assert respuesta.json() == {'repetido': False, 'lote': {
            'id': lote['id'], 'estado': 'vista_previa', 'archivo': 'Plan de cuentas.csv',
            'columnas': {'codigo': 'Código', 'nombre': 'Nombre', 'padre': None, 'tipo': None},
            'encabezados': ['Código', 'Nombre'],
            'muestra': [['1', 'Activo'], ['1.1', 'Activo corriente'], ['1.1.01', 'Caja'], ['1.1.02', 'Bancos'], ['2', 'Pasivo']],
            'filas': [
                {'fila': 2, 'codigo': '1', 'nombre': 'Activo', 'padre': None, 'tipo': 'grupo', 'estado': 'valida', 'errores': []},
                {'fila': 3, 'codigo': '1.1', 'nombre': 'Activo corriente', 'padre': '1', 'tipo': 'grupo', 'estado': 'valida', 'errores': []},
                {'fila': 4, 'codigo': '1.1.01', 'nombre': 'Caja', 'padre': '1.1', 'tipo': 'movimiento', 'estado': 'valida', 'errores': []},
                {'fila': 5, 'codigo': '1.1.02', 'nombre': 'Bancos', 'padre': '1.1', 'tipo': 'movimiento', 'estado': 'valida', 'errores': []},
                {'fila': 6, 'codigo': '2', 'nombre': 'Pasivo', 'padre': None, 'tipo': 'movimiento', 'estado': 'valida', 'errores': []}],
            'resumen': {'validas': 5, 'con_error': 0, 'duplicadas': 0, 'faltan_columnas': [], 'texto': None}}}
        assert cuantas(empresa) == 0   # nada se crea hasta confirmar

    def test_csv_con_comillas_y_el_separador_dentro_del_texto(self, entrar, empresa):
        contenido = ('Código;Nombre\r\n'
                     '1;"Caja; bancos, y ""otros"""\r\n'
                     '2;"Cuentas por cobrar,\r\nclientes"\r\n'      # un salto de línea dentro de las comillas
                     '3;  Con   espacios  \r\n').encode()
        lote = subir(entrar, empresa, contenido).json()['lote']
        assert [(f['fila'], f['codigo'], f['nombre']) for f in lote['filas']] == [
            (2, '1', 'Caja; bancos, y "otros"'), (3, '2', 'Cuentas por cobrar, clientes'), (4, '3', 'Con espacios')]
        assert lote['resumen']['validas'] == 3

    @pytest.mark.parametrize('contenido, fila', [
        # Una comilla que se abre y no se cierra: el lector se tragaba las filas siguientes dentro de ese nombre, la fila
        # salía válida y al confirmar se creaba una cuenta «Bancos locales 1.1.03;Inversiones 2;Pasivo 2.1;Proveedores».
        ('Código;Nombre\r\n1;Activo\r\n1.1;Activo corriente\r\n1.1.01;Caja\r\n1.1.02;"Bancos locales\r\n1.1.03;Inversiones\r\n'
         '2;Pasivo\r\n2.1;Proveedores\r\n', 5),
        ('Código,Nombre\n1,"Activo\n2,Pasivo\n3,Patrimonio\n', 2),
        ('Código;Nombre\r\n1;Activo\r\n\r\n2;"Pasivo', 4),             # la fila en blanco también cuenta, como en la hoja
        # La cierra, sin querer, la comilla con que empieza otro nombre más abajo: las filas de en medio desaparecían.
        ('Código;Nombre\r\n1;"Activo\r\n2;Pasivo\r\n3;"Patrimonio"\r\n4;Ingresos\r\n', 2),
        # Texto pegado después de cerrar las comillas: se leía «Otros ingresos», sin las comillas y sin avisar.
        ('Código;Nombre\r\n1;Activo\r\n4;"Otros" ingresos\r\n', 3),
    ], ids=['sin_cerrar', 'sin_cerrar_con_comas', 'sin_cerrar_al_final', 'la_cierra_otra_fila', 'texto_tras_cerrarlas'])
    def test_csv_con_comillas_mal_cerradas(self, entrar, empresa, contenido, fila):
        """No se adivina dónde terminaba el texto: se rechaza el archivo diciendo la fila, en vez de importar otra cosa."""
        respuesta = subir(entrar, empresa, contenido.encode())
        assert respuesta.status_code == 400, respuesta.content
        assert respuesta.json() == {'error': T['comillas'].format(fila=fila), 'codigo': 'formato'}
        assert f'fila {fila}:' in respuesta.json()['error'] and lotes(empresa) == []

    def test_el_separador_no_se_decide_contando_comas(self, entrar, empresa):
        """Con `;`, unos nombres llenos de comas no hacen leer el archivo como si fuera de comas (y al revés)."""
        con_punto_y_coma = lote_de(entrar, empresa, ('Código', 'Nombre'), ('1', 'Caja, bancos, y otros, varios'),
                                   ('2', 'Clientes, empleados, socios, y otros'))
        assert con_punto_y_coma['encabezados'] == ['Código', 'Nombre'] and con_punto_y_coma['resumen']['validas'] == 2
        con_coma = subir(entrar, empresa, csv_de(('Código', 'Nombre'), ('1', 'Caja; bancos; y otros; varios'),
                                                 ('2', 'Clientes; empleados; socios'), separador=',')).json()['lote']
        assert con_coma['encabezados'] == ['Código', 'Nombre']
        assert [f['nombre'] for f in con_coma['filas']] == ['Caja; bancos; y otros; varios', 'Clientes; empleados; socios']

    def test_xlsx(self, entrar, empresa):
        """Primera hoja; los códigos que la hoja guardó como número se leen como texto, sin `.0`."""
        contenido = xlsx_de(('Código', 'Nombre', 'Tipo'), (1101, 'Caja', 'M'), (1102.0, 'Bancos', None), ('1.1', 'Corriente', 'G'),
                            (1.2, 'No corriente', 'G'), ('  2  ', '  Pasivo   total ', None), (3, 2026, None),
                            otra_hoja=(('Código', 'Nombre'), ('9', 'De otra hoja')))
        respuesta = subir(entrar, empresa, contenido, 'plan.xlsx')
        assert respuesta.status_code == 200
        lote = respuesta.json()['lote']
        assert lote['columnas'] == {'codigo': 'Código', 'nombre': 'Nombre', 'padre': None, 'tipo': 'Tipo'}
        assert [(f['fila'], f['codigo'], f['nombre'], f['tipo']) for f in lote['filas']] == [
            (2, '1101', 'Caja', 'movimiento'), (3, '1102', 'Bancos', 'movimiento'), (4, '1.1', 'Corriente', 'grupo'),
            (5, '1.2', 'No corriente', 'grupo'), (6, '2', 'Pasivo total', 'movimiento'), (7, '3', '2026', 'movimiento')]
        assert lote['resumen'] == {'validas': 6, 'con_error': 0, 'duplicadas': 0, 'faltan_columnas': [], 'texto': None}
        assert confirmar(entrar, empresa, lote).json()['lote']['creadas'] == 6
        assert set(plan(empresa)) == {'1101', '1102', '1.1', '1.2', '2', '3'}

    def test_xlsx_que_declara_mal_su_tamano(self, entrar, empresa):
        """Hay programas que escriben mal el tamaño de la hoja (aquí, «A1»): se lee entera igual."""
        original, retocado = xlsx_de(*PLAN), io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as entrada, zipfile.ZipFile(retocado, 'w', zipfile.ZIP_DEFLATED) as salida:
            for parte in entrada.infolist():
                datos = entrada.read(parte.filename)
                if parte.filename == 'xl/worksheets/sheet1.xml':
                    assert b'<dimension ref="A1:B6"' in datos
                    datos = datos.replace(b'<dimension ref="A1:B6"', b'<dimension ref="A1"')
                salida.writestr(parte, datos)
        lote = subir(entrar, empresa, retocado.getvalue(), 'plan.xlsx').json()['lote']
        assert [f['codigo'] for f in lote['filas']] == ['1', '1.1', '1.1.01', '1.1.02', '2']

    def test_celdas_que_la_hoja_de_calculo_altero(self, entrar, empresa):
        """Un código que la hoja convirtió en fecha, o un número de más de 15 cifras, ya no dice lo que se escribió: la
        fila queda en error en vez de guardar un código inventado. En el nombre no importa."""
        contenido = xlsx_de(('Código', 'Nombre', 'Padre'), (date(2001, 1, 1), 'Caja', None), (1.2345678901234568e+19, 'Bancos', None),
                            ('1', date(2026, 1, 31), None), ('1.1', 'Corriente', date(2001, 1, 1)))
        lote = subir(entrar, empresa, contenido, 'plan.xlsx').json()['lote']
        assert errores_por_fila(lote) == {2: [T['alterada'].format(dato='el código')], 3: [T['alterada'].format(dato='el código')],
                                          5: [T['alterada'].format(dato='el padre')]}
        assert lote['filas'][2]['nombre'].startswith('2026-01-31') and lote['filas'][2]['estado'] == 'valida'

    @pytest.mark.parametrize('encabezados, columnas', [
        (('CÓDIGO', 'DESCRIPCIÓN', 'CUENTA PADRE', 'TIPO'), ('CÓDIGO', 'DESCRIPCIÓN', 'CUENTA PADRE', 'TIPO')),
        (('codigo', 'nombre', 'padre', 'tipo'), ('codigo', 'nombre', 'padre', 'tipo')),
        (('Code', 'Name', 'Parent', 'Type'), ('Code', 'Name', 'Parent', 'Type')),
        (('Cuenta', 'Detalle', 'Observación', 'Nivel'), ('Cuenta', 'Detalle', None, None)),
        (('  Código  ', 'Descripcion', 'Saldo', 'Padre'), ('Código', 'Descripcion', 'Padre', None)),
        # «Cuenta» es el código salvo que otra columna ya lo sea: entonces es el nombre
        (('Código', 'Cuenta', 'Tipo', 'x'), ('Código', 'Cuenta', None, 'Tipo')),
        (('Nombre', 'Cuenta', 'a', 'b'), ('Cuenta', 'Nombre', None, None)),
    ])
    def test_columnas_por_encabezado_sin_distinguir_mayusculas_ni_tildes(self, entrar, empresa, encabezados, columnas):
        lote = lote_de(entrar, empresa, encabezados, ('1', '1', '', ''))
        assert lote['columnas'] == dict(zip(('codigo', 'nombre', 'padre', 'tipo'), columnas))

    def test_filas_en_blanco_y_numero_de_fila_del_archivo(self, entrar, empresa):
        contenido = '\r\n\r\nCódigo;Nombre\r\n1;Activo\r\n;\r\n\r\n   ;  \r\n2;Pasivo\r\n\r\n'.encode()
        lote = subir(entrar, empresa, contenido).json()['lote']
        assert [(f['fila'], f['codigo']) for f in lote['filas']] == [(4, '1'), (8, '2')]   # como las numera la hoja de cálculo
        hoja = subir(entrar, empresa, xlsx_de(('Código', 'Nombre'), (None, None), ('1', 'Activo'), (None, '  '), ('2', 'Pasivo')),
                     'plan.xlsx').json()['lote']
        assert [(f['fila'], f['codigo']) for f in hoja['filas']] == [(3, '1'), (5, '2')]

    def test_encabezados_vacios_o_repetidos_quedan_con_nombre_unico(self, entrar, empresa):
        lote = lote_de(entrar, empresa, ('Código', '', 'Nombre', 'Nombre', 'Columna 2'), ('1', 'x', 'Activo', 'Otro', 'y'))
        assert lote['encabezados'] == ['Código', 'Columna 2', 'Nombre', 'Nombre (2)', 'Columna 2 (2)']
        assert lote['columnas']['nombre'] == 'Nombre'
        cambiado = mapear(entrar, empresa, lote, codigo='Código', nombre='Nombre (2)').json()['lote']
        assert cambiado['filas'][0]['nombre'] == 'Otro'

    @pytest.mark.parametrize('contenido, texto', [
        (b'%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n', 'formato'),
        (b'<?xml version="1.0"?><Workbook></Workbook>', 'formato'),
        (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\x00' * 64, 'xls'),
        ('Código;Nombre\r\n1;Años anteriores\r\n'.encode('cp1252'), 'codificacion'),
        ('Código;Nombre\r\n1;Activo\r\n'.encode('utf-16'), 'formato'),
        (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + bytes(range(256)), 'formato'),
        (b'PK\x03\x04 esto no es un zip', 'formato'),
        (b'', 'vacio'), (b'\r\n \r\n;;\r\n', 'vacio'),
        ('Código;Nombre\r\n'.encode(), 'sin_filas'),
        (';'.join(f'c{n}' for n in range(41)).encode() + b'\r\n1;x\r\n', 'demasiadas_columnas'),
    ])
    def test_archivos_que_no_se_pueden_leer(self, entrar, empresa, contenido, texto):
        respuesta = subir(entrar, empresa, contenido)
        assert respuesta.status_code == 400 and respuesta.json() == {'error': T[texto], 'codigo': 'formato'}
        assert lotes(empresa) == []   # ni lote ni archivo guardado

    def test_xlsx_que_no_es_un_libro(self, entrar, empresa):
        otro_zip = io.BytesIO()
        with zipfile.ZipFile(otro_zip, 'w') as comprimido:
            comprimido.writestr('plan.csv', 'Código;Nombre\n1;Activo\n')
        assert rechazo(subir(entrar, empresa, otro_zip.getvalue(), 'plan.xlsx'), 400, 'formato')
        roto = xlsx_de(*PLAN)
        assert rechazo(subir(entrar, empresa, roto[:len(roto) // 2], 'plan.xlsx'), 400, 'formato')
        assert lotes(empresa) == []

    def test_limite_de_tamano(self, entrar, empresa):
        justo = csv_de(('Código', 'Nombre'), ('1', 'Activo'))
        justo += b'\r\n' * ((importar_cuentas.MAX_BYTES - len(justo)) // 2)
        assert len(justo) == importar_cuentas.MAX_BYTES and subir(entrar, empresa, justo).status_code == 200
        grande = subir(entrar, empresa, justo + b'\r\n')
        assert grande.status_code == 400 and grande.json() == {'error': T['archivo_grande'], 'codigo': 'archivo_grande'}
        assert '2 MB' in T['archivo_grande'] and len(lotes(empresa)) == 1

    def test_xlsx_que_ocupa_demasiado_al_descomprimirlo(self, entrar, empresa):
        """Unos kilobytes comprimidos que al abrirse serían decenas de megas: se rechaza por lo que declara el ZIP, sin abrirlo."""
        original, bomba = xlsx_de(*PLAN), io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as entrada, zipfile.ZipFile(bomba, 'w', zipfile.ZIP_DEFLATED) as salida:
            for parte in entrada.infolist():
                salida.writestr(parte, entrada.read(parte.filename))
            salida.writestr('xl/media/relleno.bin', b'\x00' * (importar_cuentas.MAX_DESCOMPRIMIDO + 1))
        assert len(bomba.getvalue()) < 100_000
        respuesta = subir(entrar, empresa, bomba.getvalue(), 'plan.xlsx')
        assert respuesta.status_code == 400 and respuesta.json() == {'error': T['descomprimido'], 'codigo': 'archivo_grande'}
        assert lotes(empresa) == []

    @pytest.mark.parametrize('donde', ['hoja', 'cadenas'])
    @pytest.mark.parametrize('codificacion', [None, 'iso-8859-1', 'utf-16', 'utf-16-le', 'utf-16-be'])
    def test_xlsx_con_entidades_xml(self, entrar, empresa, donde, codificacion):
        """Un XLSX que declara entidades XML (DOCTYPE) no se abre. Con una entidad de 270 caracteres citada millones de
        veces, un archivo de 25 KB que cumple el tope de 20 MB descomprimidos ocupaba 4 GB de memoria al leerlo. Ninguna
        hoja de cálculo las escribe, así que se rechaza antes de dárselo al lector, esté en la codificación que esté."""
        respuesta = subir(entrar, empresa, xlsx_con_entidad(donde, codificacion), 'plan.xlsx')
        assert respuesta.status_code == 400, respuesta.content
        assert respuesta.json() == {'error': T['xlsx_declaraciones'], 'codigo': 'formato'}
        assert lotes(empresa) == []

    @pytest.mark.parametrize('falla', ['crc', 'cifrada'])
    def test_xlsx_con_una_parte_que_no_se_puede_leer(self, entrar, empresa, falla):
        """Antes de abrir el libro se lee cada parte del ZIP: una dañada o cifrada es 400 `formato`, no un error del servidor."""
        relleno = b'RELLENO-QUE-NADIE-LEE' * 4
        salida = io.BytesIO()
        with zipfile.ZipFile(salida, 'w', zipfile.ZIP_STORED) as comprimido:
            for nombre, contenido in partes_de(xlsx_de(*PLAN)).items():
                comprimido.writestr(nombre, contenido)
            comprimido.writestr('xl/media/relleno.bin', relleno)
        datos = bytearray(salida.getvalue())
        if falla == 'crc':   # el contenido ya no es el que dice su suma de comprobación
            datos[datos.index(relleno)] ^= 0xFF
        else:                # la marca de «cifrada» en la entrada del directorio del ZIP
            entrada = datos.rindex(b'PK\x01\x02', 0, datos.rindex(b'xl/media/relleno.bin'))
            datos[entrada + 8] |= 1
        with zipfile.ZipFile(io.BytesIO(bytes(datos))) as comprimido, pytest.raises((zipfile.BadZipFile, RuntimeError)):
            comprimido.read('xl/media/relleno.bin')
        assert rechazo(subir(entrar, empresa, bytes(datos), 'plan.xlsx'), 400, 'formato')
        assert lotes(empresa) == []

    def test_xlsx_con_una_parte_que_trae_mas_de_lo_que_declara(self):
        """El tope descomprimido se comprueba con lo que declara el ZIP, pero `ZipFile.read` descomprime de una vez todo lo
        que trae la entrada y solo después lo recorta: una parte que declara 1 KB y trae cientos de megas ocupaba esa
        memoria al abrir el libro (300 KB de archivo, 600 MB). Se lee a trozos y hasta lo declarado, y el lector recibe
        una copia cuyas partes ocupan lo que dicen. Aquí son 64 MB de relleno detrás de `[Content_Types].xml`, la primera
        parte que el lector abre; el libro, por lo demás, es el de siempre y se lee igual."""
        partes = partes_de(xlsx_de(*PLAN))
        tipos = partes.pop('[Content_Types].xml')
        salida = io.BytesIO()
        with zipfile.ZipFile(salida, 'w', zipfile.ZIP_DEFLATED) as comprimido:
            for nombre, contenido in partes.items():
                comprimido.writestr(nombre, contenido)
            with comprimido.open('[Content_Types].xml', 'w') as parte:
                parte.write(tipos)
                for _ in range(64):
                    parte.write(b' ' * importar_cuentas.MB)
        datos = bytearray(salida.getvalue())
        entrada = datos.rindex(b'PK\x01\x02')   # la última del directorio del ZIP: ahí se declaran su suma y su tamaño
        struct.pack_into('<L', datos, entrada + 16, zlib.crc32(tipos))
        struct.pack_into('<L', datos, entrada + 24, len(tipos))
        datos = bytes(datos)
        with zipfile.ZipFile(io.BytesIO(datos)) as comprimido:
            assert sum(parte.file_size for parte in comprimido.infolist()) < 20_000 and len(datos) < 100_000
        tracemalloc.start()
        try:
            extension, encabezados, filas = importar_cuentas.leer(datos)
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert (extension, encabezados, [fila['c'][0] for fila in filas]) == ('xlsx', ['Código', 'Nombre'], ['1', '1.1', '1.1.01', '1.1.02', '2'])
        assert pico < 16 * importar_cuentas.MB, f'{pico / importar_cuentas.MB:.0f} MB'

    def test_hoja_con_una_celda_perdida_muy_lejos(self, entrar, empresa):
        """Una celda con formato en la última fila de la hoja no obliga a recorrer un millón de filas con contenido: las
        vacías no cuentan para el límite de 5 000 ni cambian la numeración."""
        libro = openpyxl.Workbook()
        for fila in PLAN:
            libro.active.append(fila)
        libro.active.cell(row=1_048_576, column=1, value='  ')
        salida = io.BytesIO()
        libro.save(salida)
        lote = subir(entrar, empresa, salida.getvalue(), 'plan.xlsx').json()['lote']
        assert [f['fila'] for f in lote['filas']] == [2, 3, 4, 5, 6]

    def test_demasiadas_celdas(self, entrar, empresa, monkeypatch):
        monkeypatch.setattr(importar_cuentas, 'MAX_CELDAS', 11)
        assert subir(entrar, empresa, csv_de(*PLAN)).status_code == 400   # 12 celdas
        monkeypatch.setattr(importar_cuentas, 'MAX_CELDAS', 12)
        assert subir(entrar, empresa, csv_de(*PLAN)).status_code == 200

    def test_demasiado_texto_en_la_tabla(self, entrar, empresa):
        """Los topes de filas, de columnas y de caracteres por celda se multiplicaban entre sí: 5 000 filas de 40 columnas
        de 300 caracteres son 60 millones de caracteres guardados en el lote (hasta 352 MB de JSON), y un XLSX los trae en
        32 KB porque sus celdas citan la misma cadena. El texto que se guarda de un archivo tiene su propio tope."""
        columnas, celda = importar_cuentas.MAX_COLUMNAS, 'N' * importar_cuentas.CELDA_MAX
        encabezados = ['Código', 'Nombre', *(f'Columna {n}' for n in range(3, columnas + 1))]
        caben = importar_cuentas.MAX_CARACTERES // (columnas * len(celda))   # filas llenas que entran en el tope: 174
        filas = [[celda] * columnas] * (caben + 1)
        pasado = xlsx_de(encabezados, *filas)
        assert len(pasado) < importar_cuentas.MAX_BYTES // 10 and len(filas) < importar_cuentas.MAX_FILAS // 10
        respuesta = subir(entrar, empresa, pasado, 'plan.xlsx')
        assert respuesta.status_code == 400, respuesta.content[:300]
        assert respuesta.json() == {'error': T['demasiado_texto'], 'codigo': 'archivo_grande'}
        assert lotes(empresa) == []
        justo = subir(entrar, empresa, xlsx_de(encabezados, *filas[:caben]), 'plan.xlsx')
        assert justo.status_code == 200 and len(justo.json()['lote']['filas']) == caben
        guardado, = lotes(empresa)
        assert sum(len(texto) for fila in guardado.filas for texto in fila['c']) == caben * columnas * len(celda)

    def test_el_tope_de_texto_no_alcanza_a_un_csv_que_cabe(self, entrar, empresa):
        """Un CSV no puede traer más caracteres que bytes: el más denso que pasa el límite de 2 MB pasa también este."""
        encabezado = 'Código;Nombre;Notas\r\n'
        fila = '{:04d};' + 'N' * 200 + ';' + 'N' * importar_cuentas.CELDA_MAX + '\r\n'
        cuantas_filas = (importar_cuentas.MAX_BYTES - len(encabezado.encode())) // len(fila.format(0))
        contenido = (encabezado + ''.join(fila.format(n) for n in range(cuantas_filas))).encode()
        assert importar_cuentas.MAX_BYTES - len(fila.format(0)) < len(contenido) <= importar_cuentas.MAX_BYTES
        lote = subir(entrar, empresa, contenido).json()['lote']
        assert lote['resumen'] == {'validas': cuantas_filas, 'con_error': 0, 'duplicadas': 0, 'faltan_columnas': [], 'texto': None}

    def test_sin_archivo_o_sin_clave(self, entrar, empresa):
        sin_archivo = entrar.post(API, {'empresa': empresa.pk, 'clave': 'subida-sin-archivo'})
        assert sin_archivo.status_code == 400 and sin_archivo.json()['errores'] == {'archivo': [T['archivo']]}
        en_json = enviar(entrar, API, {'empresa': empresa.pk, 'clave': 'subida-en-json-1', 'archivo': 'plan.csv'})
        assert en_json.status_code == 400 and en_json.json()['errores'] == {'archivo': [T['archivo']]}
        for clave in (None, 'corta', 'con espacios 12'):
            assert rechazo(subir(entrar, empresa, csv_de(*PLAN), clave=clave), 400, 'clave')
        assert lotes(empresa) == []


# ---------------------------------------------------------------- columnas y mapeo

class TestMapeo:

    def test_sin_columna_de_codigo_o_de_nombre_se_pide_el_mapeo(self, entrar, empresa):
        lote = lote_de(entrar, empresa, ('Cta', 'Glosa', 'Mayor'), ('1', 'Activo', ''), ('1.1', 'Corriente', '1'))
        assert lote['columnas'] == {'codigo': None, 'nombre': None, 'padre': None, 'tipo': None}
        assert lote['encabezados'] == ['Cta', 'Glosa', 'Mayor'] and lote['muestra'] == [['1', 'Activo', ''], ['1.1', 'Corriente', '1']]
        assert lote['filas'] == [] and lote['resumen'] == {
            'validas': 0, 'con_error': 0, 'duplicadas': 0, 'faltan_columnas': ['codigo', 'nombre'],
            'texto': 'Elige qué columna del archivo trae el código y el nombre de cada cuenta.'}
        sin_columnas = confirmar(entrar, empresa, lote)
        assert rechazo(sin_columnas, 400, 'faltan_columnas') and sin_columnas.json()['resumen'] == lote['resumen']
        solo_codigo = mapear(entrar, empresa, lote, codigo='Cta').json()['lote']
        assert solo_codigo['resumen']['faltan_columnas'] == ['nombre'] and solo_codigo['filas'] == []
        completo = mapear(entrar, empresa, lote, codigo='Cta', nombre='Glosa', padre='Mayor')
        assert completo.status_code == 200 and completo.json()['lote']['columnas'] == {
            'codigo': 'Cta', 'nombre': 'Glosa', 'padre': 'Mayor', 'tipo': None}
        assert [(f['codigo'], f['padre'], f['tipo'], f['estado']) for f in completo.json()['lote']['filas']] == [
            ('1', None, 'grupo', 'valida'), ('1.1', '1', 'movimiento', 'valida')]
        assert cuantas(empresa) == 0
        assert confirmar(entrar, empresa, lote).json()['lote']['creadas'] == 2

    def test_cambiar_las_columnas_recalcula_la_vista_previa(self, entrar, empresa):
        lote = lote_de(entrar, empresa, ('Código', 'Nombre', 'Nombre corto', 'Padre'),
                       ('1', 'Activo', 'ACT', ''), ('1.1', 'Activo corriente', 'ACT-C', ''), ('1.1.01', 'Caja', 'CAJ', '1'))
        assert por_codigo(lote)['1.1.01']['padre'] == '1' and por_codigo(lote)['1.1']['padre'] is None   # manda la columna padre
        cambiado = mapear(entrar, empresa, lote, codigo='Código', nombre='Nombre corto', padre=None, tipo='').json()['lote']
        assert cambiado['columnas'] == {'codigo': 'Código', 'nombre': 'Nombre corto', 'padre': None, 'tipo': None}
        assert [(f['nombre'], f['padre']) for f in cambiado['filas']] == [('ACT', None), ('ACT-C', '1'), ('CAJ', '1.1')]   # por los puntos
        # lo que no viene queda sin columna, y el mapeo se conserva al volver a pedir el lote
        assert mapear(entrar, empresa, lote, codigo='Código', nombre='Nombre').json()['lote']['columnas']['padre'] is None
        recargado = entrar.get(f'{API}{lote["id"]}/?empresa={empresa.pk}')
        assert recargado.status_code == 200 and recargado.json()['lote']['columnas']['nombre'] == 'Nombre'
        assert recargado.json()['lote']['filas'][2]['padre'] == '1.1'

    def test_columnas_que_no_valen(self, entrar, empresa):
        lote = lote_de(entrar, empresa, ('Código', 'Nombre', 'Padre'), ('1', 'Activo', ''))
        respuesta = mapear(entrar, empresa, lote, codigo='No existe', nombre='código', padre=3, tipo='Nombre')
        assert respuesta.status_code == 400 and respuesta.json()['codigo'] == 'validacion'
        assert respuesta.json()['errores'] == {'codigo': [T['columna']], 'nombre': [T['columna']], 'padre': [T['columna']]}
        repetida = mapear(entrar, empresa, lote, codigo='Código', nombre='Nombre', padre='Código', tipo='Nombre')
        assert repetida.json()['errores'] == {'padre': [T['columna_repetida']], 'tipo': [T['columna_repetida']]}
        actual = entrar.get(f'{API}{lote["id"]}/').json()['lote']
        assert actual['columnas'] == lote['columnas']   # un mapeo rechazado no cambia nada

    def test_un_lote_confirmado_ya_no_cambia(self, entrar, empresa):
        lote = lote_de(entrar, empresa, *PLAN)
        confirmado = confirmar(entrar, empresa, lote).json()['lote']
        respuesta = mapear(entrar, empresa, lote, codigo='Nombre', nombre='Código')
        assert respuesta.status_code == 409
        assert respuesta.json() == {'error': T['lote_confirmado'], 'codigo': 'lote_confirmado', 'lote': confirmado}
        assert plan(empresa)['1.1.01'] == ('Caja', 'movimiento', '1.1')


# ---------------------------------------------------------------- jerarquía y tipos

class TestJerarquiaYTipos:

    def test_jerarquia_por_los_puntos_del_codigo(self, entrar, empresa):
        """El padre es el prefijo más largo que exista, en el archivo o en la empresa; si no hay ninguno, es raíz."""
        activo = sembrar(empresa, '1', 'Activo', 'grupo')
        sembrar(empresa, '1.2', 'No corriente', 'grupo', activo)
        lote = lote_de(entrar, empresa, ('Código', 'Nombre'), ('1.1', 'Corriente'), ('1.1.01.001', 'Caja general'),
                       ('1.2.05', 'Vehículos'), ('3.1.01', 'Capital'), ('4', 'Ingresos'), ('4.1.', 'Ventas'), ('4.1.01.', 'Bienes'),
                       ('5.', 'Gastos'), ('5.1.01', 'Sueldos'), ('6.1', 'Otros'), ('61', 'No cuelga de 6'))
        assert {f['codigo']: f['padre'] for f in lote['filas']} == {
            '1.1': '1',                # de una cuenta que ya existe en la empresa
            '1.1.01.001': '1.1',       # 1.1.01 no existe: el prefijo más largo que sí
            '1.2.05': '1.2', '3.1.01': None, '4': None,
            '4.1.': '4', '4.1.01.': '4.1.',   # con el punto al final de cada nivel también
            '5.': None, '5.1.01': '5.', '6.1': None, '61': None}
        assert lote['resumen']['validas'] == 11
        assert confirmar(entrar, empresa, lote).json()['lote']['creadas'] == 11
        guardado = plan(empresa)
        assert {codigo: padre for codigo, (_, _, padre) in guardado.items()} == {
            '1': None, '1.2': '1', **{f['codigo']: f['padre'] for f in lote['filas']}}
        assert guardado['1.1'][1] == 'grupo' and guardado['1.1.01.001'][1] == 'movimiento' and guardado['4.1.'][1] == 'grupo'

    def test_jerarquia_por_la_columna_padre(self, entrar, empresa):
        sembrar(empresa, 'ACT', 'Activo', 'grupo')
        lote = lote_de(entrar, empresa, ('Código', 'Nombre', 'Padre'), ('1101', 'Caja', 'cor'), ('COR', 'Corriente', 'act'),
                       ('1.1', 'Sin padre aunque tenga punto', ''), ('1', 'Uno', ''), ('1201', 'Terrenos', '1.9'),
                       ('1202', 'Edificios', ' COR '))
        assert [(f['codigo'], f['padre'], f['tipo'], f['estado']) for f in lote['filas']] == [
            ('1101', 'COR', 'movimiento', 'valida'),   # el padre está más abajo en el archivo, sin distinguir mayúsculas
            ('COR', 'ACT', 'grupo', 'valida'),         # el padre ya existe en la empresa
            ('1.1', None, 'movimiento', 'valida'),     # con columna padre, vacía es raíz: los puntos no cuentan
            ('1', None, 'movimiento', 'valida'),
            ('1201', '1.9', 'movimiento', 'error'),    # se muestra lo que trae la columna
            ('1202', 'COR', 'movimiento', 'valida')]
        assert errores_por_fila(lote) == {6: ['El padre 1.9 no existe.']}
        assert rechazo(confirmar(entrar, empresa, lote), 400, 'filas_con_error')

    def test_tipos_escritos_y_deducidos(self, entrar, empresa):
        lote = lote_de(entrar, empresa, ('Código', 'Nombre', 'Tipo'), ('1', 'Activo', ''), ('1.1', 'Caja', ''), ('2', 'Pasivo', 'G'),
                       ('3', 'Patrimonio', 'grupo'), ('4', 'Ingresos', 'GRUPO'), ('5', 'Costos', 'm'), ('6', 'Gastos', 'Movimiento'),
                       ('7', 'Otros', ' Detalle '), ('8', 'Raro', 'Título'), ('9', 'Con hijas', 'M'), ('9.1', 'Hija', 'detalle'))
        assert [(f['codigo'], f['tipo']) for f in lote['filas']] == [
            ('1', 'grupo'), ('1.1', 'movimiento'),   # sin tipo: grupo si tiene hijas, movimiento si no
            ('2', 'grupo'), ('3', 'grupo'), ('4', 'grupo'), ('5', 'movimiento'), ('6', 'movimiento'), ('7', 'movimiento'),
            ('8', None), ('9', 'movimiento'), ('9.1', 'movimiento')]
        assert errores_por_fila(lote) == {10: [T['tipo'].format(valor='Título')], 11: [T['movimiento_con_hijas']]}
        assert lote['resumen'] == {'validas': 9, 'con_error': 2, 'duplicadas': 0, 'faltan_columnas': [], 'texto': None}

    def test_un_grupo_escrito_sin_hijas_se_crea_como_grupo(self, entrar, empresa):
        lote = lote_de(entrar, empresa, ('Código', 'Nombre', 'Tipo'), ('1', 'Activo', 'G'), ('2', 'Pasivo', 'M'))
        confirmar(entrar, empresa, lote)
        assert plan(empresa) == {'1': ('Activo', 'grupo', None), '2': ('Pasivo', 'movimiento', None)}


# ---------------------------------------------------------------- errores por fila

class TestErroresPorFila:

    def test_cada_fila_con_todos_sus_errores(self, entrar, empresa):
        sembrar(empresa, 'MOV', 'Cuenta de movimiento que ya existe', 'movimiento')
        sembrar(empresa, 'GRU', 'Grupo que ya existe', 'grupo')
        lote = lote_de(
            entrar, empresa, ('Código', 'Nombre', 'Padre', 'Tipo'),
            ('1', 'Activo', '', 'G'),                        # 2
            ('', 'Sin código', '', ''),                      # 3
            ('2', '', '', ''),                               # 4
            ('x' * 31, 'n' * 201, '', ''),                   # 5
            ('1.1.01A', 'Caja', '1', ''),                    # 6
            ('1.1.01a', 'Caja repetida', '1', ''),           # 7: repetido sin distinguir mayúsculas
            (' 1.1.01A ', 'Otra vez', '1', ''),              # 8: y cita siempre la primera
            ('3', 'Sin padre', '1.9', ''),                   # 9
            ('4', 'Bajo una de movimiento', 'mov', ''),      # 10
            ('5', 'Bajo un grupo que existe', 'gru', ''),    # 11: válida
            ('A', 'Ciclo A', 'B', ''),                       # 12
            ('B', 'Ciclo B', 'C', ''),                       # 13
            ('C', 'Ciclo C', 'A', ''),                       # 14
            ('D', 'De sí misma', 'd', ''),                   # 15
            ('E', 'Bajo un ciclo', 'A', ''),                 # 16: su padre está en un ciclo, ella no
            ('6', 'Tipo raro', '', 'auxiliar'),              # 17
            ('7', 'Movimiento con hijas', '', 'M'),          # 18
            ('7.1', 'Hija', '7', ''),                        # 19
            ('', '', '9', 'zzz'),                            # 20: varios a la vez
            ('8', 'Con\x07control', '', ''),                 # 21
            ('9', 'Sobra una celda', '', '', 'extra'),       # 22
        )
        C = cuentas.TEXTOS
        assert errores_por_fila(lote) == {
            3: ['Falta el código.'], 4: ['Falta el nombre.'],
            5: [C['codigo_largo'], C['nombre_largo']],
            7: [T['repetido'].format(codigo='1.1.01a', fila=6)], 8: [T['repetido'].format(codigo='1.1.01A', fila=6)],
            9: ['El padre 1.9 no existe.'],
            10: [T['padre_movimiento'].format(codigo='MOV')],
            12: [C['ciclo']], 13: [C['ciclo']], 14: [C['ciclo']], 15: [C['ciclo']],
            17: [T['tipo'].format(valor='auxiliar')], 18: [T['movimiento_con_hijas']],
            20: ['Falta el código.', 'Falta el nombre.', T['tipo'].format(valor='zzz')],
            21: [C['nombre_caracteres']], 22: [T['sobran']]}
        estados = {f['fila']: f['estado'] for f in lote['filas']}
        assert {n for n, estado in estados.items() if estado == 'valida'} == {2, 6, 11, 16, 19}
        assert lote['resumen'] == {'validas': 5, 'con_error': 16, 'duplicadas': 0, 'faltan_columnas': [], 'texto': None}
        assert [f['fila'] for f in lote['filas']] == list(range(2, 23))   # todas las filas, cada una con su número

    def test_con_filas_en_error_no_se_crea_nada(self, entrar, empresa):
        lote = lote_de(entrar, empresa, ('Código', 'Nombre'), ('1', 'Activo'), ('1.1', 'Corriente'), ('1.1', 'Repetida'))
        respuesta = confirmar(entrar, empresa, lote)
        assert respuesta.status_code == 400 and respuesta.json() == {
            'error': T['filas_con_error'], 'codigo': 'filas_con_error',
            'resumen': {'validas': 2, 'con_error': 1, 'duplicadas': 0, 'faltan_columnas': [], 'texto': None}}
        assert cuantas(empresa) == 0 and entrar.get(f'{API}{lote["id"]}/').json()['lote']['estado'] == 'vista_previa'
        assert not AuditLog.objects.filter(action='cuentas_importadas').exists()

    def test_el_alta_y_la_importacion_rechazan_lo_mismo(self, entrar, empresa):
        """Una sola regla para la forma del código y del nombre: lo que el alta de C2 no admite, la fila tampoco."""
        casos = [('x' * 31, 'Largo'), ('1\u200b.1', 'Invisible'), ('1', 'n' * 201), ('2', 'Con\x07control'), ('x' * 31, 'Con\x07control'),
                 ('x' * 30, 'n' * 200)]
        lote = lote_de(entrar, empresa, ('Código', 'Nombre'), *casos)
        for (codigo, nombre), fila in zip(casos, lote['filas']):
            if fila['fila'] == 6:
                continue   # repite el código de la fila 2: se mira aparte
            alta = enviar(entrar, CUENTAS, {'empresa': empresa.pk, 'clave': f'alta-igual-{fila["fila"]:04d}', 'codigo': codigo,
                                           'nombre': nombre, 'tipo': 'movimiento'})
            del_alta = [texto for textos in alta.json().get('errores', {}).values() for texto in textos]
            assert fila['errores'] == del_alta and (alta.status_code == 201) is (not fila['errores']), fila
        assert [bool(f['errores']) for f in lote['filas']] == [True, True, True, True, True, False]
        C = cuentas.TEXTOS
        assert lote['filas'][4]['errores'] == [C['codigo_largo'], C['nombre_caracteres'], T['repetido'].format(codigo='x' * 31, fila=2)]


# ---------------------------------------------------------------- duplicadas

@pytest.fixture
def con_plan(entrar, empresa):
    """La empresa ya tiene 1 Activo ▸ 1.1 Activo corriente ▸ 1.1.01 Caja, y el archivo las trae con otros nombres más dos nuevas."""
    activo = sembrar(empresa, '1', 'Activo', 'grupo')
    corriente = sembrar(empresa, '1.1', 'Activo corriente', 'grupo', activo)
    sembrar(empresa, '1.1.01', 'Caja', 'movimiento', corriente)
    return lote_de(entrar, empresa, ('Código', 'Nombre', 'Tipo'), ('1', 'ACTIVO', 'M'), ('1.1', 'Activo corriente', ''),
                   ('1.1.01', 'Caja general', ''), ('1.1.02', 'Bancos', ''), ('2', 'Pasivo', ''))


class TestDuplicadas:

    def test_vista_previa(self, con_plan):
        assert [(f['codigo'], f['estado']) for f in con_plan['filas']] == [
            ('1', 'duplicada'), ('1.1', 'duplicada'), ('1.1.01', 'duplicada'), ('1.1.02', 'valida'), ('2', 'valida')]
        assert con_plan['resumen'] == {'validas': 2, 'con_error': 0, 'duplicadas': 3, 'faltan_columnas': [], 'texto': None}
        # a una duplicada no se le aplican las reglas del árbol: «1» viene como movimiento con hijas y no es un error,
        # porque ni su tipo ni su padre se van a tocar
        assert por_codigo(con_plan)['1']['errores'] == [] and por_codigo(con_plan)['1.1.02']['padre'] == '1.1'

    def test_omitir(self, entrar, empresa, con_plan):
        respuesta = confirmar(entrar, empresa, con_plan, 'omitir')
        assert respuesta.status_code == 200
        assert {k: respuesta.json()['lote'][k] for k in ('creadas', 'actualizadas', 'omitidas', 'duplicadas')} == {
            'creadas': 2, 'actualizadas': 0, 'omitidas': 3, 'duplicadas': 'omitir'}
        assert plan(empresa) == {'1': ('Activo', 'grupo', None), '1.1': ('Activo corriente', 'grupo', '1'),
                                 '1.1.01': ('Caja', 'movimiento', '1.1'), '1.1.02': ('Bancos', 'movimiento', '1.1'),
                                 '2': ('Pasivo', 'movimiento', None)}
        assert en(empresa, lambda: set(Cuenta.objects.values_list('version', flat=True))) == {1}

    def test_actualizar_nombre(self, entrar, empresa, admin, con_plan):
        antes = en(empresa, lambda: {c.codigo: c for c in Cuenta.objects.all()})
        respuesta = confirmar(entrar, empresa, con_plan, 'actualizar_nombre')
        assert respuesta.status_code == 200
        assert {k: respuesta.json()['lote'][k] for k in ('creadas', 'actualizadas', 'omitidas', 'duplicadas')} == {
            'creadas': 2, 'actualizadas': 2, 'omitidas': 1, 'duplicadas': 'actualizar_nombre'}   # 1.1 ya se llamaba igual
        # solo el nombre: ni el tipo ni el padre de las que ya existían
        assert plan(empresa) == {'1': ('ACTIVO', 'grupo', None), '1.1': ('Activo corriente', 'grupo', '1'),
                                 '1.1.01': ('Caja general', 'movimiento', '1.1'), '1.1.02': ('Bancos', 'movimiento', '1.1'),
                                 '2': ('Pasivo', 'movimiento', None)}
        ahora = en(empresa, lambda: {c.codigo: c for c in Cuenta.objects.all()})
        assert {codigo: c.version for codigo, c in ahora.items()} == {'1': 2, '1.1': 1, '1.1.01': 2, '1.1.02': 1, '2': 1}
        assert ahora['1'].actualizada_por == admin and ahora['1'].actualizada_en > antes['1'].actualizada_en
        assert ahora['1.1'].actualizada_en == antes['1.1'].actualizada_en and ahora['1'].lote_id is None
        # el nombre anterior no se pierde: queda en el lote
        lote = lotes(empresa)[0]
        assert lote.resultado['renombradas'] == [[antes['1'].pk, 'Activo', 'ACTIVO'], [antes['1.1.01'].pk, 'Caja', 'Caja general']]
        # y quien tenía abierta la cuenta con la versión anterior recibe el 409 de siempre
        viejo = entrar.patch(f'{CUENTAS}{antes["1"].pk}/', json.dumps({'empresa': empresa.pk, 'version': 1, 'nombre': 'Activos'}),
                             content_type='application/json')
        assert rechazo(viejo, 409, 'version') and viejo.json()['cuenta']['nombre'] == 'ACTIVO'

    def test_actualizar_nombre_pide_ademas_el_permiso_de_editar(self, client, empresa):
        sembrar(empresa, '1', 'Activo', 'grupo')
        solo_crea = helpers.crear_grupo('Solo crea cuentas', ('view_cuenta', 'add_cuenta'))
        helpers.iniciar_sesion(client, helpers.crear_usuario('importa.sin.editar', empresa, solo_crea), empresa=empresa)
        lote = lote_de(client, empresa, ('Código', 'Nombre'), ('1', 'ACTIVO'), ('2', 'Pasivo'))
        assert sin_permiso(confirmar(client, empresa, lote, 'actualizar_nombre'), 'change_cuenta')
        assert plan(empresa) == {'1': ('Activo', 'grupo', None)}
        acciones = client.get('/contabilidad/api/capacidades/').json()['funciones']['importar_cuentas']['acciones']
        assert acciones == {'ver': True, 'importar': True, 'actualizar_nombre': False}
        assert confirmar(client, empresa, lote, 'omitir').json()['lote']['creadas'] == 1   # omitir no lo pide
        assert plan(empresa)['1'] == ('Activo', 'grupo', None)

    def test_duplicada_sin_distinguir_mayusculas(self, entrar, empresa):
        sembrar(empresa, 'Caja-1', 'Caja')
        lote = lote_de(entrar, empresa, ('Código', 'Nombre'), ('CAJA-1', 'Caja'), (' caja-1 ', 'Otra'), ('Caja-2', 'Bancos'))
        assert [f['estado'] for f in lote['filas']] == ['duplicada', 'error', 'valida']
        assert errores_por_fila(lote) == {3: [T['repetido'].format(codigo='caja-1', fila=2)]}

    def test_las_nuevas_cuelgan_de_la_cuenta_que_ya_existe(self, entrar, empresa):
        """Si el padre está en el archivo y también en la empresa, manda la de la empresa, con el tipo que tiene."""
        sembrar(empresa, '1', 'Activo', 'movimiento')
        lote = lote_de(entrar, empresa, ('Código', 'Nombre', 'Tipo'), ('1', 'Activo', 'G'), ('1.1', 'Corriente', ''))
        assert errores_por_fila(lote) == {3: [T['padre_movimiento'].format(codigo='1')]}
        cuenta = en(empresa, lambda: Cuenta.objects.get(codigo='1'))
        entrar.patch(f'{CUENTAS}{cuenta.pk}/', json.dumps({'empresa': empresa.pk, 'version': 1, 'tipo': 'grupo'}),
                     content_type='application/json')
        ahora = entrar.get(f'{API}{lote["id"]}/').json()['lote']   # la vista previa se calcula contra el plan de ahora
        assert ahora['resumen'] == {'validas': 1, 'con_error': 0, 'duplicadas': 1, 'faltan_columnas': [], 'texto': None}
        assert confirmar(entrar, empresa, lote).json()['lote']['creadas'] == 1
        assert plan(empresa)['1.1'] == ('Corriente', 'movimiento', '1')

    def test_reimportar_un_plan_que_se_reorganizo_a_mano(self, entrar, empresa):
        """El mismo archivo otra vez, después de mover cuentas en la aplicación: todo son duplicadas y nada se deshace."""
        primero = lote_de(entrar, empresa, *PLAN)
        confirmar(entrar, empresa, primero)
        ids = en(empresa, lambda: dict(Cuenta.objects.values_list('codigo', 'pk')))
        for pk, cambio in ((ids['2'], {'tipo': 'grupo'}), (ids['1.1.02'], {'padre_id': ids['2']}), (ids['1.1.01'], {'padre_id': None})):
            cuenta = en(empresa, lambda: Cuenta.objects.get(pk=pk))
            assert entrar.patch(f'{CUENTAS}{pk}/', json.dumps({'empresa': empresa.pk, 'version': cuenta.version, **cambio}),
                                content_type='application/json').status_code == 200
        antes = plan(empresa)
        segundo = lote_de(entrar, empresa, *PLAN)
        assert segundo['resumen'] == {'validas': 0, 'con_error': 0, 'duplicadas': 5, 'faltan_columnas': [], 'texto': None}
        resultado = confirmar(entrar, empresa, segundo, 'actualizar_nombre').json()['lote']
        assert (resultado['creadas'], resultado['actualizadas'], resultado['omitidas']) == (0, 0, 5)
        assert plan(empresa) == antes and len(lotes(empresa)) == 2


# ---------------------------------------------------------------- confirmar

class TestConfirmar:

    def test_crea_las_cuentas_por_niveles(self, entrar, empresa, admin):
        lote = lote_de(entrar, empresa, ('Código', 'Nombre'), ('1.1.01', 'Caja'), ('1.1', 'Activo corriente'), ('2', 'Pasivo'),
                       ('1', 'Activo'), ('1.1.02', 'Bancos'))   # las hijas antes que sus padres: el orden del archivo no importa
        respuesta = confirmar(entrar, empresa, lote)
        assert respuesta.status_code == 200 and respuesta.json() == {'repetido': False, 'lote': {
            'id': lote['id'], 'estado': 'confirmado', 'archivo': 'plan.csv', 'duplicadas': 'omitir', 'creadas': 5, 'actualizadas': 0,
            'omitidas': 0, 'confirmado_en': timezone.localdate().isoformat()}}
        assert plan(empresa) == {'1': ('Activo', 'grupo', None), '1.1': ('Activo corriente', 'grupo', '1'),
                                 '1.1.01': ('Caja', 'movimiento', '1.1'), '1.1.02': ('Bancos', 'movimiento', '1.1'),
                                 '2': ('Pasivo', 'movimiento', None)}
        guardado = lotes(empresa)[0]
        for cuenta in en(empresa, lambda: list(Cuenta.objects.all())):
            assert (cuenta.company_id, cuenta.lote_id, cuenta.version, cuenta.clave, cuenta.activa) == (empresa.pk, lote['id'], 1, None, True)
            assert cuenta.creada_por == admin and cuenta.actualizada_por == admin and cuenta.codigo_norm == cuenta.codigo.casefold()
            assert cuenta.creada_en == guardado.confirmado_en
        assert (guardado.estado, guardado.confirmado_por, guardado.duplicadas) == ('confirmado', admin, 'omitir')
        # el plan se ve y se edita por C2 como cualquier otro
        lista = entrar.get(CUENTAS).json()['cuentas']
        assert [(c['codigo'], c['hijas'], c['version']) for c in lista] == [
            ('1', 1, 1), ('1.1', 2, 1), ('1.1.01', 0, 1), ('1.1.02', 0, 1), ('2', 0, 1)]
        assert entrar.get(f'{API}{lote["id"]}/').json()['lote'] == respuesta.json()['lote']   # al recargar: el resultado

    def test_idempotente(self, entrar, empresa):
        lote = lote_de(entrar, empresa, *PLAN)
        primera = confirmar(entrar, empresa, lote, clave='confirma-una-vez')
        assert primera.status_code == 200 and primera.json()['repetido'] is False
        otra_vez = confirmar(entrar, empresa, lote, clave='confirma-una-vez')
        assert otra_vez.status_code == 200 and otra_vez.json() == {'lote': primera.json()['lote'], 'repetido': True}
        otra_clave = confirmar(entrar, empresa, lote, clave='confirma-otra-vez')
        assert otra_clave.status_code == 409 and otra_clave.json() == {
            'error': T['lote_confirmado'], 'codigo': 'lote_confirmado', 'lote': primera.json()['lote']}
        otra_opcion = confirmar(entrar, empresa, lote, 'actualizar_nombre', clave='confirma-una-vez')
        assert otra_opcion.status_code == 409 and otra_opcion.json()['codigo'] == 'clave_usada'
        assert cuantas(empresa) == 5 and AuditLog.objects.filter(action='cuentas_importadas').count() == 1

    def test_se_recalcula_contra_las_cuentas_de_ese_momento(self, entrar, empresa):
        lote = lote_de(entrar, empresa, *PLAN)
        assert lote['resumen']['validas'] == 5
        # entre la vista previa y la confirmación alguien da de alta dos de esas cuentas
        for codigo, nombre, tipo in (('1', 'Activos', 'grupo'), ('2', 'Pasivos', 'movimiento')):
            assert enviar(entrar, CUENTAS, {'empresa': empresa.pk, 'clave': f'alta-entre-medias-{codigo}', 'codigo': codigo,
                                           'nombre': nombre, 'tipo': tipo}).status_code == 201
        resultado = confirmar(entrar, empresa, lote).json()['lote']
        assert (resultado['creadas'], resultado['omitidas']) == (3, 2)
        assert plan(empresa)['1'] == ('Activos', 'grupo', None) and plan(empresa)['1.1'] == ('Activo corriente', 'grupo', '1')

    def test_si_el_plan_cambia_bajo_la_confirmacion_no_se_crea_nada(self, entrar, empresa, monkeypatch):
        """Quien escriba el plan sin pasar por la cola puede adelantarse entre la revisión y la inserción: decide la
        restricción única, se deshace todo y se puede repetir."""
        lote = lote_de(entrar, empresa, *PLAN)
        sembrar(empresa, '1.1.02', 'Bancos de otro')
        monkeypatch.setattr(importar_cuentas, 'cuentas_de_la_empresa', lambda bloqueadas=False: {})   # la revisión no la vio
        respuesta = confirmar(entrar, empresa, lote)
        assert respuesta.status_code == 409 and respuesta.json() == {'error': T['plan_cambiado'], 'codigo': 'plan_cambiado'}
        assert plan(empresa) == {'1.1.02': ('Bancos de otro', 'movimiento', None)}
        assert lotes(empresa)[0].estado == 'vista_previa' and not AuditLog.objects.filter(action='cuentas_importadas').exists()
        monkeypatch.undo()
        assert confirmar(entrar, empresa, lote).json()['lote'] == {**confirmar_resultado(lote), 'creadas': 4, 'omitidas': 1}

    @pytest.mark.parametrize('duplicadas', [None, '', 'borrar', 'OMITIR', True, ['omitir']])
    def test_hay_que_decir_que_hacer_con_las_duplicadas(self, entrar, empresa, duplicadas):
        lote = lote_de(entrar, empresa, *PLAN)
        respuesta = confirmar(entrar, empresa, lote, duplicadas)
        assert respuesta.status_code == 400 and respuesta.json()['errores'] == {'duplicadas': [T['duplicadas']]}
        assert cuantas(empresa) == 0

    def test_clave_obligatoria(self, entrar, empresa):
        lote = lote_de(entrar, empresa, *PLAN)
        for clave in (None, 'corta', 'x' * 41):
            assert rechazo(confirmar(entrar, empresa, lote, clave=clave), 400, 'clave')
        assert cuantas(empresa) == 0

    def test_nada_se_crea_antes_de_confirmar(self, entrar, empresa):
        lote = lote_de(entrar, empresa, ('Código', 'Nombre', 'Padre'), ('1', 'Activo', ''), ('1.1', 'Corriente', '1'))
        mapear(entrar, empresa, lote, codigo='Código', nombre='Nombre')
        entrar.get(f'{API}{lote["id"]}/')
        subir(entrar, empresa, csv_de(*PLAN))
        assert cuantas(empresa) == 0 and len(lotes(empresa)) == 2
        assert not AuditLog.objects.filter(action__in=('cuentas_importadas', 'cuenta_creada')).exists()
        assert entrar.get(CUENTAS).json()['cuentas'] == []

    def test_lo_creado_cumple_las_reglas_del_plan(self, entrar, empresa):
        """Lo que deja la importación es un árbol válido para C2: padres que son grupos de la misma empresa, sin ciclos,
        códigos únicos sin distinguir mayúsculas."""
        raiz = sembrar(empresa, 'R', 'Raíz', 'grupo')
        sembrar(empresa, 'R.1', 'Existente', 'grupo', raiz)
        filas = [('Código', 'Nombre', 'Padre')] + [(f'N{n}', f'Nivel {n}', f'n{n - 1}' if n else 'r.1') for n in range(40)]
        filas += [(f'H{n}', f'Hoja {n}', f'N{n % 40}') for n in range(200)]
        lote = lote_de(entrar, empresa, *filas)
        assert confirmar(entrar, empresa, lote).json()['lote']['creadas'] == 240
        todas = en(empresa, lambda: list(Cuenta.objects.select_related('padre')))
        assert len({c.codigo_norm for c in todas}) == len(todas) == 242
        padres = {c.pk: c.padre_id for c in todas}
        for cuenta in todas:
            if cuenta.padre_id:
                assert cuenta.padre.tipo == 'grupo' and cuenta.padre.company_id == empresa.pk
            assert not cuentas.cuelga_de(padres, cuenta.padre_id, cuenta.pk)
        niveles = {c.codigo: c for c in todas}
        assert niveles['N39'].padre.codigo == 'N38' and niveles['N0'].padre.codigo == 'R.1' and niveles['N39'].tipo == 'grupo'

    def test_una_cadena_mas_profunda_que_la_pila_de_python(self, entrar, empresa):
        """Los niveles los pone el archivo: 1 100 cuentas, cada una hija de la anterior, se revisan y se crean sin recursión
        (el límite de Python es 1 000 llamadas anidadas)."""
        filas = [('Código', 'Nombre', 'Padre')] + [(f'N{n}', f'Nivel {n}', f'N{n - 1}' if n else '') for n in reversed(range(1100))]
        lote = lote_de(entrar, empresa, *filas)
        assert lote['resumen']['validas'] == 1100
        assert confirmar(entrar, empresa, lote).json()['lote']['creadas'] == 1100
        guardado = plan(empresa)
        assert guardado['N0'] == ('Nivel 0', 'grupo', None) and guardado['N1099'] == ('Nivel 1099', 'movimiento', 'N1098')
        assert all(guardado[f'N{n}'][2] == f'N{n - 1}' for n in range(1, 1100))


def confirmar_resultado(lote):
    return {'id': lote['id'], 'estado': 'confirmado', 'archivo': lote['archivo'], 'duplicadas': 'omitir', 'creadas': 5,
            'actualizadas': 0, 'omitidas': 0, 'confirmado_en': timezone.localdate().isoformat()}


# ---------------------------------------------------------------- el archivo y la clave de la subida

class TestArchivo:

    def test_queda_privado_y_con_su_huella(self, entrar, empresa, admin):
        contenido = csv_de(*PLAN, bom=True)
        lote_de_api = subir(entrar, empresa, contenido, 'Plan 2026 (definitivo).csv').json()['lote']
        lote = lotes(empresa)[0]
        assert (lote.pk, lote.nombre_original, lote.tamano, lote.sha256) == (
            lote_de_api['id'], 'Plan 2026 (definitivo).csv', len(contenido), hashlib.sha256(contenido).hexdigest())
        assert (lote.estado, lote.creado_por, lote.company_id, lote.confirmado_en) == ('vista_previa', admin, empresa.pk, None)
        assert lote.archivo.name.startswith(f'privado/empresas/{empresa.uuid}/plan-cuentas/') and lote.archivo.name.endswith('.csv')
        with lote.archivo.open('rb') as guardado:
            assert guardado.read() == contenido   # tal como llegó
        assert entrar.get('/media/' + lote.archivo.name).status_code == 404   # privado/: nunca por /media/
        assert lote.encabezados == ['Código', 'Nombre'] and lote.filas[0] == {'n': 2, 'c': ['1', 'Activo']}
        assert lote.mapeo == {'codigo': 'Código', 'nombre': 'Nombre', 'padre': None, 'tipo': None}
        hoja = subir(entrar, empresa, xlsx_de(*PLAN), 'plan.XLSX').json()['lote']
        assert lotes(empresa)[1].archivo.name.endswith('.xlsx') and hoja['archivo'] == 'plan.XLSX'

    def test_la_extension_la_decide_el_contenido(self, entrar, empresa):
        assert subir(entrar, empresa, xlsx_de(*PLAN), 'plan.csv').json()['lote']['resumen']['validas'] == 5
        assert subir(entrar, empresa, csv_de(*PLAN), 'plan.xlsx').json()['lote']['resumen']['validas'] == 5
        assert [lote.archivo.name.rsplit('.', 1)[1] for lote in lotes(empresa)] == ['xlsx', 'csv']

    def test_subida_idempotente(self, entrar, empresa):
        contenido = csv_de(*PLAN)
        primera = subir(entrar, empresa, contenido, clave='subida-repetida-1')
        assert primera.status_code == 200 and primera.json()['repetido'] is False
        otra_vez = subir(entrar, empresa, contenido, 'otro nombre.csv', clave='subida-repetida-1')
        assert otra_vez.status_code == 200 and otra_vez.json() == {'lote': primera.json()['lote'], 'repetido': True}
        otro_archivo = subir(entrar, empresa, csv_de(*PLAN, ('3', 'Patrimonio')), clave='subida-repetida-1')
        assert otro_archivo.status_code == 409 and otro_archivo.json() == {'error': T['clave_usada'], 'codigo': 'clave_usada'}
        ilegible = subir(entrar, empresa, b'%PDF-1.4', clave='subida-repetida-1')   # la clave ya dice que es otro archivo
        assert rechazo(ilegible, 409, 'clave_usada')
        assert len(lotes(empresa)) == 1
        carpeta = os.path.dirname(os.path.join(configuracion.MEDIA_ROOT, lotes(empresa)[0].archivo.name))
        assert len(os.listdir(carpeta)) == 1   # el reintento no dejó otro archivo
        # el mismo archivo con otra clave es otra importación
        assert subir(entrar, empresa, contenido, clave='subida-repetida-2').json()['lote']['id'] != primera.json()['lote']['id']
        # y repetir la subida de un lote ya confirmado devuelve su resultado
        confirmado = confirmar(entrar, empresa, primera.json()['lote']).json()['lote']
        assert subir(entrar, empresa, contenido, clave='subida-repetida-1').json() == {'lote': confirmado, 'repetido': True}


# ---------------------------------------------------------------- permisos, empresa y licencia

ROLES = [(ROLE_OWNER, True), (ROLE_ADMIN, True), (ROLE_ACCOUNTANT, True), (ROLE_READONLY, False), (ROLE_SELLER, False),
         (ROLE_CLIENT, False)]


class TestPermisos:

    @pytest.mark.parametrize('rol, importa', ROLES)
    def test_por_rol(self, client, empresa, admin, rol, importa):
        sembrar(empresa, '1', 'Activo', 'grupo')
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        ajeno = lote_de(client, empresa, ('Código', 'Nombre'), ('1', 'ACTIVO'), ('9', 'Otra'))   # un lote que subió el propietario
        client.logout()
        helpers.iniciar_sesion(client, helpers.crear_usuario(f'importa.{rol.lower()}', empresa, rol), empresa=empresa)
        subida = subir(client, empresa, csv_de(*PLAN))
        consulta = client.get(f'{API}{ajeno["id"]}/?empresa={empresa.pk}')
        mapeo = mapear(client, empresa, ajeno, codigo='Código', nombre='Nombre')
        if importa:
            assert subida.status_code == consulta.status_code == mapeo.status_code == 200
            assert confirmar(client, empresa, ajeno, 'actualizar_nombre').json()['lote']['actualizadas'] == 1
            assert confirmar(client, empresa, subida.json()['lote']).json()['lote']['creadas'] == 4
            assert cuantas(empresa) == 6
        else:
            for respuesta in (subida, consulta, mapeo, confirmar(client, empresa, ajeno),
                              confirmar(client, empresa, ajeno, 'actualizar_nombre')):
                assert sin_permiso(respuesta, 'add_cuenta')
            assert cuantas(empresa) == 1 and len(lotes(empresa)) == 1
        if rol != ROLE_CLIENT:   # el rol Cliente no consulta las capacidades
            funcion = client.get('/contabilidad/api/capacidades/').json()['funciones']['importar_cuentas']
            assert funcion['estado'] == ('disponible' if importa else 'sin_permiso')
            assert funcion['acciones'] == {'ver': importa, 'importar': importa, 'actualizar_nombre': importa}
            if rol != ROLE_SELLER:   # el Vendedor tampoco ve el plan
                assert client.get(CUENTAS).json()['capacidades']['importar'] is importa

    def test_el_servicio_tambien_exige_el_permiso(self, empresa):
        lector = helpers.crear_usuario('importa.servicio', empresa, ROLE_READONLY)
        peticion = SimpleNamespace(user=lector, company=empresa, membership=Membership.objects.get(user=lector, company=empresa),
                                   META={}, method='POST')
        with company_context(empresa):
            lote = ImportacionCuentas.objects.create(clave='lote-de-servicio', nombre_original='plan.csv', tamano=1, sha256='0' * 64,
                                                     encabezados=['Código', 'Nombre'], filas=[{'n': 2, 'c': ['1', 'Activo']}],
                                                     mapeo={'codigo': 'Código', 'nombre': 'Nombre'})
            for intento in (lambda: importar_cuentas.subir(peticion, archivo(csv_de(*PLAN)), {'clave': 'servicio-0001'}),
                            lambda: importar_cuentas.consultar(peticion, lote.pk),
                            lambda: importar_cuentas.mapear(peticion, lote.pk, {'codigo': 'Nombre', 'nombre': 'Código'}),
                            lambda: importar_cuentas.confirmar(peticion, lote.pk, {'clave': 'servicio-0002', 'duplicadas': 'omitir'})):
                with pytest.raises(api.Rechazo) as negado:
                    intento()
                assert negado.value.estado == 403
        assert cuantas(empresa) == 0 and len(lotes(empresa)) == 1 and lotes(empresa)[0].mapeo['codigo'] == 'Código'

    def test_sin_sesion_y_metodos(self, client, entrar, empresa):
        lote = lote_de(entrar, empresa, *PLAN)
        assert entrar.get(API).status_code == 405 and entrar.get(API).json()['codigo'] == 'metodo'
        assert entrar.post(f'{API}{lote["id"]}/', {'empresa': empresa.pk}).status_code == 405
        assert entrar.get(f'{API}{lote["id"]}/mapeo/').status_code == entrar.get(f'{API}{lote["id"]}/confirmar/').status_code == 405
        assert entrar.delete(f'{API}{lote["id"]}/?empresa={empresa.pk}').status_code == 405   # un lote no se borra
        entrar.logout()
        for respuesta in (subir(client, empresa, csv_de(*PLAN)), client.get(f'{API}{lote["id"]}/'), mapear(client, empresa, lote),
                          confirmar(client, empresa, lote)):
            assert respuesta.status_code == 302 and respuesta['Location'].startswith('/login/')
        assert cuantas(empresa) == 0 and len(lotes(empresa)) == 1


class TestEmpresa:

    def test_envios_sin_empresa_o_para_otra(self, entrar, empresa, empresa_b):
        lote = lote_de(entrar, empresa, *PLAN)
        sin_empresa = (entrar.post(API, {'clave': 'subida-sin-empresa', 'archivo': archivo(csv_de(*PLAN))}),
                       enviar(entrar, f'{API}{lote["id"]}/mapeo/', {'codigo': 'Nombre'}),
                       enviar(entrar, f'{API}{lote["id"]}/confirmar/', {'clave': 'confirma-sin-empresa', 'duplicadas': 'omitir'}))
        for respuesta in sin_empresa:
            assert rechazo(respuesta, 409, 'sin_empresa')
        para_otra = (subir(entrar, empresa_b, csv_de(*PLAN)), mapear(entrar, empresa_b, lote, codigo='Nombre'),
                     confirmar(entrar, empresa_b, lote), entrar.get(f'{API}{lote["id"]}/?empresa={empresa_b.pk}'))
        for respuesta in para_otra:
            assert respuesta.status_code == 409 and respuesta.json() == {'error': pestanas.EMPRESA_CAMBIADA, 'codigo': 'empresa_cambiada'}
        assert cuantas(empresa) == 0 and len(lotes(empresa)) == 1 and lotes(empresa)[0].mapeo['codigo'] == 'Código'

    def test_el_lote_de_otra_empresa_no_existe(self, entrar, empresa, empresa_b, admin):
        Membership.objects.create(user=admin, company=empresa_b, group=Group.objects.get(name=ROLE_OWNER))
        lote = lote_de(entrar, empresa, *PLAN)
        entrar.post('/empresas/cambiar/', {'company': empresa_b.pk})
        for respuesta in (entrar.get(f'{API}{lote["id"]}/'), mapear(entrar, empresa_b, lote, codigo='Nombre', nombre='Código'),
                          confirmar(entrar, empresa_b, lote)):
            assert respuesta.status_code == 404 and respuesta.json() == {'error': T['lote'], 'codigo': 'lote'}
        assert rechazo(entrar.get(f'{API}999999/'), 404, 'lote')
        assert (cuantas(empresa), cuantas(empresa_b)) == (0, 0) and lotes(empresa)[0].estado == 'vista_previa'
        # la misma clave de subida y los mismos códigos en cada empresa no chocan
        en_b = subir(entrar, empresa_b, csv_de(*PLAN), clave='misma-clave-a-y-b')
        confirmar(entrar, empresa_b, en_b.json()['lote'])
        entrar.post('/empresas/cambiar/', {'company': empresa.pk})
        en_a = subir(entrar, empresa, csv_de(*PLAN), clave='misma-clave-a-y-b')
        assert en_a.json()['repetido'] is False and en_a.json()['lote']['resumen']['validas'] == 5   # las de B no son duplicadas aquí
        assert confirmar(entrar, empresa, lote).json()['lote']['creadas'] == 5
        assert (cuantas(empresa), cuantas(empresa_b)) == (5, 5)
        assert en(empresa, lambda: set(Cuenta.objects.values_list('lote_id', flat=True))) == {lote['id']}


class TestLicencia:

    def test_complemento_cerrado(self, entrar, empresa, settings):
        lote = lote_de(entrar, empresa, *PLAN)
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = []
        for respuesta in (subir(entrar, empresa, csv_de(*PLAN)), entrar.get(f'{API}{lote["id"]}/'),
                          mapear(entrar, empresa, lote, codigo='Nombre'), confirmar(entrar, empresa, lote)):
            assert respuesta.status_code == 403
            cuerpo = respuesta.json()
            assert (cuerpo['codigo'], cuerpo['plan'], cuerpo['causa']) == ('complemento_pendiente', 'complemento_contable', 'licencia')
            assert 'lote' not in cuerpo
        assert cuantas(empresa) == 0 and len(lotes(empresa)) == 1
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [empresa.ruc]
        assert confirmar(entrar, empresa, lote).status_code == 200

    def test_plan_vencido_consulta_si_envios_no(self, entrar, empresa):
        lote = lote_de(entrar, empresa, *PLAN)
        vencer(empresa)
        assert entrar.get(f'{API}{lote["id"]}/?empresa={empresa.pk}').json()['lote']['resumen']['validas'] == 5
        for respuesta in (subir(entrar, empresa, csv_de(*PLAN)), mapear(entrar, empresa, lote, codigo='Nombre'),
                          confirmar(entrar, empresa, lote)):
            assert respuesta.status_code == 403
            cuerpo = respuesta.json()
            assert (cuerpo['codigo'], cuerpo['causa'], cuerpo['licencia']['estado']) == ('plan', 'licencia', 'plan_vencido')
        assert cuantas(empresa) == 0 and len(lotes(empresa)) == 1
        funcion = entrar.get('/contabilidad/api/capacidades/').json()['funciones']['importar_cuentas']
        assert funcion['estado'] == 'disponible' and funcion['acciones'] == {'ver': True, 'importar': False, 'actualizar_nombre': False}

    @pytest.mark.parametrize('accion', ['search', 'search_x', 'send_invoice_by_email'])
    def test_plan_vencido_tampoco_guarda_con_action_de_consulta(self, entrar, empresa, settings, accion):
        """PlanMiddleware toma por consulta un formulario con ese `action` y lo deja pasar con el plan vencido. Ni la
        subida (que es un formulario por fuerza) ni el mapeo ni la confirmación guardan nada."""
        settings.FPA_COMPLEMENTO_CONTABLE_REVISION = [empresa.ruc]   # en la lista de revisión, no por el «*» de las pruebas
        sembrar(empresa, '1', 'Viejo', 'grupo')
        lote = lote_de(entrar, empresa, *PLAN)
        vencer(empresa)
        formulario = {'empresa': empresa.pk, 'action': accion}
        for respuesta in (subir(entrar, empresa, csv_de(*PLAN), action=accion),
                          entrar.post(f'{API}{lote["id"]}/mapeo/', {**formulario, 'codigo': 'Nombre', 'nombre': 'Código'}),
                          entrar.post(f'{API}{lote["id"]}/confirmar/', {**formulario, 'clave': 'confirma-con-action',
                                                                         'duplicadas': 'actualizar_nombre'})):
            assert respuesta.status_code == 403, respuesta.content
            cuerpo = respuesta.json()
            assert (cuerpo['codigo'], cuerpo['plan'], cuerpo['causa'], cuerpo['licencia']['estado']) == (
                'plan', 'requerido', 'licencia', 'plan_vencido')
        guardado, = lotes(empresa)   # un solo lote, y sigue como se subió
        assert guardado.estado == 'vista_previa'
        assert guardado.mapeo == {'codigo': 'Código', 'nombre': 'Nombre', 'padre': None, 'tipo': None}
        assert plan(empresa) == {'1': ('Viejo', 'grupo', None)}   # ni cuentas nuevas ni el nombre cambiado
        assert not AuditLog.objects.filter(action='cuentas_importadas').exists()

    def test_sin_plan_pagado(self, client):
        gratuita = helpers.crear_empresa('GRATIS IMPORTA', plan=None)
        helpers.iniciar_sesion(client, helpers.crear_usuario('dueno.importa.gratis', gratuita, ROLE_OWNER), empresa=gratuita)
        respuesta = subir(client, gratuita, csv_de(*PLAN))
        assert respuesta.status_code == 403 and respuesta.json()['plan'] == 'requerido' and respuesta.json()['causa'] == 'licencia'
        assert lotes(gratuita) == []

    def test_la_funcion_esta_disponible_en_el_contrato_de_capacidades(self, entrar):
        funcion = capacidades.funcion_de('importar_cuentas')
        assert funcion.construccion == capacidades.DISPONIBLE and funcion.ruta == API and not funcion.que_falta
        anunciada = entrar.get('/contabilidad/api/capacidades/').json()['funciones']['importar_cuentas']
        assert anunciada == {'nombre': 'Importación del plan de cuentas', 'ambito': 'contabilidad', 'estado': 'disponible', 'causa': None,
                             'texto': None, 'acciones': {'ver': True, 'importar': True, 'actualizar_nombre': True}, 'faltan': []}


# ---------------------------------------------------------------- auditoría

class TestAuditoria:

    def test_una_entrada_por_importacion_confirmada(self, entrar, empresa, admin, con_plan):
        confirmar(entrar, empresa, con_plan, 'actualizar_nombre')
        registro = AuditLog.objects.get(action='cuentas_importadas')
        lote = lotes(empresa)[0]
        assert (registro.user, registro.company) == (admin, empresa)
        assert registro.detail == {'lote': lote.pk, 'creadas': 2, 'actualizadas': 2, 'omitidas': 1, 'duplicadas': 'actualizar_nombre',
                                   'archivo': 'plan.csv', 'sha256': lote.sha256}
        assert registro.get_action_display() == 'Plan de cuentas: importación confirmada'
        # ni una entrada por cuenta, ni las del alta y el cambio a mano
        assert not AuditLog.objects.filter(action__in=('cuenta_creada', 'cuenta_modificada')).exists()


# ---------------------------------------------------------------- 5 000 filas

def plan_grande(filas=5000):
    """`filas` cuentas en cuatro niveles: 1 ▸ 1.NN ▸ 1.NN.MM ▸ 1.NN.MM.KKK."""
    cuentas_del_plan = [('1', 'Activo')]
    for grupo in range(1, 11):
        cuentas_del_plan.append((f'1.{grupo:02d}', f'Grupo {grupo}'))
        for subgrupo in range(1, 11):
            cuentas_del_plan.append((f'1.{grupo:02d}.{subgrupo:02d}', f'Subgrupo {grupo}-{subgrupo}'))
    hojas = 0
    while len(cuentas_del_plan) < filas:
        grupo, subgrupo = hojas % 10 + 1, hojas // 10 % 10 + 1
        cuentas_del_plan.append((f'1.{grupo:02d}.{subgrupo:02d}.{hojas // 100 + 1:03d}', f'Cuenta de detalle número {hojas + 1}'))
        hojas += 1
    return [('Código', 'Nombre'), *cuentas_del_plan[:filas]]


class TestCincoMilFilas:

    @pytest.mark.parametrize('formato', ['csv', 'xlsx'])
    def test_se_importan_holgadamente_en_una_peticion(self, entrar, empresa, formato):
        """gunicorn corta a los 60 s. Lo que de verdad lo garantiza es el número de consultas: no crece con las filas."""
        filas = plan_grande()
        contenido = csv_de(*filas) if formato == 'csv' else xlsx_de(*filas)
        assert len(contenido) < importar_cuentas.MAX_BYTES
        inicio = time.monotonic()
        subida = subir(entrar, empresa, contenido, f'plan.{formato}')
        tras_subir = time.monotonic()
        lote = subida.json()['lote']
        assert lote['resumen'] == {'validas': 5000, 'con_error': 0, 'duplicadas': 0, 'faltan_columnas': [], 'texto': None}
        assert cuantas(empresa) == 0
        with CaptureQueriesContext(connection) as consultas:
            antes = time.monotonic()
            respuesta = confirmar(entrar, empresa, lote)
            tras_confirmar = time.monotonic()
        assert respuesta.status_code == 200 and respuesta.json()['lote']['creadas'] == 5000
        print(f'\n5 000 filas ({formato}, {connection.vendor}): subir y vista previa {tras_subir - inicio:.2f} s; '
              f'confirmar {tras_confirmar - antes:.2f} s con {len(consultas)} consultas')
        assert tras_subir - inicio < 20 and tras_confirmar - antes < 20
        # SQLite parte cada inserción en sentencias de pocas filas (999 parámetros); PostgreSQL usa 500 cuentas por sentencia
        assert len(consultas) < (60 if connection.vendor == 'postgresql' else 140)
        assert cuantas(empresa) == 5000
        guardado = plan(empresa)
        assert guardado['1'] == ('Activo', 'grupo', None) and guardado['1.03.07'] == ('Subgrupo 3-7', 'grupo', '1.03')
        assert guardado['1.03.07.049'][1:] == ('movimiento', '1.03.07')
        # y repetirlo entero con otro lote: 5 000 duplicadas, sus nombres actualizados sin una consulta por cuenta
        otro = [filas[0]] + [(codigo, nombre.upper()) for codigo, nombre in filas[1:]]
        segundo = subir(entrar, empresa, csv_de(*otro)).json()['lote']
        assert segundo['resumen']['duplicadas'] == 5000
        with CaptureQueriesContext(connection) as consultas:
            antes = time.monotonic()
            resultado = confirmar(entrar, empresa, segundo, 'actualizar_nombre').json()['lote']
            duracion = time.monotonic() - antes
        print(f'5 000 nombres actualizados ({connection.vendor}): {duracion:.2f} s con {len(consultas)} consultas')
        assert (resultado['creadas'], resultado['actualizadas'], resultado['omitidas']) == (0, 5000, 0)
        assert duracion < 20 and len(consultas) < 60
        assert plan(empresa)['1.03.07.049'][0].startswith('CUENTA DE DETALLE') and cuantas(empresa) == 5000
        assert en(empresa, lambda: set(Cuenta.objects.values_list('version', flat=True))) == {2}

    def test_una_fila_mas_no_entra(self, entrar, empresa):
        respuesta = subir(entrar, empresa, csv_de(*plan_grande(5001)))
        assert respuesta.status_code == 400 and respuesta.json() == {'error': T['demasiadas_filas'], 'codigo': 'demasiadas_filas'}
        assert '5 000' in T['demasiadas_filas'] and lotes(empresa) == []
        hoja = subir(entrar, empresa, xlsx_de(*plan_grande(5001)), 'plan.xlsx')
        assert rechazo(hoja, 400, 'demasiadas_filas') and lotes(empresa) == []


# ---------------------------------------------------------------- seguridad por filas (PostgreSQL)

@pytest.mark.skipif(connection.vendor != 'postgresql', reason='La seguridad por filas es de PostgreSQL')
class TestSeguridadPorFilas:
    TABLA = 'contabilidad_importacioncuentas'

    def contar(self, tabla=None):
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM {tabla or self.TABLA}')   # sin filtro de empresa a propósito
            return cursor.fetchone()[0]

    def test_politica_activa_y_forzada(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s', [self.TABLA])
            assert cursor.fetchone() == (True, True)
            cursor.execute('SELECT polname FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid WHERE c.relname = %s', [self.TABLA])
            assert [fila[0] for fila in cursor.fetchall()] == ['fpa_empresa']

    def test_cada_empresa_solo_ve_y_solo_escribe_lo_suyo(self, entrar, empresa, empresa_b):
        lote = lote_de(entrar, empresa, *PLAN)
        confirmar(entrar, empresa, lote)
        with company_context(empresa):
            assert (self.contar(), self.contar('contabilidad_cuenta')) == (1, 5)
        with company_context(empresa_b):
            assert (self.contar(), self.contar('contabilidad_cuenta')) == (0, 0)
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE {self.TABLA} SET estado = 'vista_previa', confirmado_en = NULL WHERE id = %s", [lote['id']])
                assert cursor.rowcount == 0
            # ni un lote ni una cuenta a nombre de la otra empresa, aunque se fije su id a mano (como haría una inserción por lotes)
            with pytest.raises(DatabaseError), transaction.atomic():
                ImportacionCuentas.all_companies.bulk_create([ImportacionCuentas(
                    company=empresa, clave='lote-intruso-01', nombre_original='x.csv', tamano=1, sha256='0' * 64)])
            with pytest.raises(DatabaseError), transaction.atomic():
                Cuenta.objects.bulk_create([Cuenta(company=empresa, codigo='X', codigo_norm='x', nombre='Intrusa', tipo='grupo')])
        assert lotes(empresa)[0].estado == 'confirmado' and cuantas(empresa) == 5
