"""Correcciones de la integración del RIDE B (revisión del 24/10/2026): «RUC Proveedor» también en «Información adicional»
(Anexo 26 de la ficha técnica, ejemplo 2), PDF liviano, código de barras con módulos de píxeles enteros, hoja con huella
que aún no está en STATIC_ROOT, hora de autorización de la NC en hora de Ecuador y columnas de la liquidación."""
import base64
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace as NS

import pypdfium2 as pdfium
import pytest
import zxingcpp
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from lxml import html
from PIL import Image

from core.comprobantes.ride import codigo_de_barras
from core.pos.utilities import printer
from core.pos.utilities.printer import create_pdf
from tests.test_ride_diseno import CLAVE_DEMO, PROVEEDOR_DEMO, TEMPLATES, contexto_demo


def informacion_adicional(contenido_html):
    pagina = html.fromstring(contenido_html)
    tablas = pagina.xpath('//table[thead/tr/th[normalize-space()="Información adicional"]]')
    assert len(tablas) == 1
    return {' '.join(fila.xpath('string(td[1])').split()): ' '.join(fila.xpath('string(td[2])').split())
            for fila in tablas[0].xpath('.//tbody/tr')}


@pytest.mark.parametrize('tipo', TEMPLATES)
def test_ruc_proveedor_en_informacion_adicional_y_en_el_pie(tipo):
    contenido = render_to_string(TEMPLATES[tipo], contexto_demo(tipo))
    assert informacion_adicional(contenido)['RUC Proveedor'] == PROVEEDOR_DEMO['ruc']
    pie = ' '.join(html.fromstring(contenido).xpath('string(//footer)').split())
    assert f'RUC Proveedor: {PROVEEDOR_DEMO["ruc"]}' in pie


def test_nota_de_credito_con_la_informacion_adicional_de_su_xml():
    filas = informacion_adicional(render_to_string(TEMPLATES['credito'], contexto_demo('credito')))
    assert filas['Observación'] == 'NOTA_CREDITO # 000000123'
    assert filas['Dirección'] == 'Calle del comprador 300, Ciudad ficticia'


def test_sin_ruc_proveedor_no_hay_fila():
    contexto = contexto_demo('factura')
    contexto['sale'].get_proveedor = None
    assert 'RUC Proveedor' not in informacion_adicional(render_to_string(TEMPLATES['factura'], contexto))
    contexto = contexto_demo('guia')
    contexto['proveedor'], contexto['c'].correo = None, ''
    assert 'Información adicional' not in render_to_string(TEMPLATES['guia'], contexto)


@pytest.mark.parametrize('tipo', TEMPLATES)
def test_pdf_liviano_con_el_isotipo_del_pie_a_su_tamano(tipo):
    contenido = create_pdf(contexto_demo(tipo), TEMPLATES[tipo])
    assert len(contenido) < 120_000   # con el isotipo original (1374×1145 px) pesaba unos 440 KB
    imagen = Image.open(finders.find('img/brand/isotipo-pie.png'))
    assert imagen.size == (166, 138)


def test_codigo_de_barras_con_modulos_de_tres_pixeles():
    imagen = Image.open(BytesIO(base64.b64decode(codigo_de_barras(CLAVE_DEMO).split(',', 1)[1])))
    assert imagen.width == 321 * 3 + 2 * 30   # 321 módulos de 3 px y zona libre de 10 módulos por lado
    assert CLAVE_DEMO in [c.text for c in zxingcpp.read_barcodes(imagen)]


@pytest.mark.parametrize('tipo', ['factura', 'credito', 'retencion', 'guia'])
def test_codigo_de_barras_se_lee_rasterizado(tipo):
    contenido = create_pdf(contexto_demo(tipo), TEMPLATES[tipo])
    with pdfium.PdfDocument(contenido) as documento:
        for opciones in ({'scale': 200 / 72}, {'scale': 300 / 72}, {'scale': 300 / 72, 'no_smoothimage': True},
                         {'scale': 600 / 72}):
            codigos = zxingcpp.read_barcodes(documento[0].render(**opciones).to_pil())
            assert CLAVE_DEMO in [c.text for c in codigos], opciones


def test_hoja_con_huella_ausente_de_static_root_usa_la_original(settings, tmp_path):
    settings.STATIC_ROOT = str(tmp_path)   # manifiesto cargado, archivos con huella aún no copiados
    assert printer._local_file('/static/css/facturaporaqui-ride.0123456789ab.css') == finders.find('css/facturaporaqui-ride.css')
    assert printer._local_file('/static/img/brand/isotipo-pie.abcdef012345.png') == finders.find('img/brand/isotipo-pie.png')
    assert printer._local_file('/static/css/no-existe.0123456789ab.css') is None


def test_sin_la_hoja_el_ride_sigue_en_a4(monkeypatch):
    original = printer._local_file
    monkeypatch.setattr(printer, '_local_file', lambda ruta, esquema='http': None if ruta.endswith('.css') else original(ruta, esquema))
    contenido = create_pdf(contexto_demo('factura'), TEMPLATES['factura'])
    with pdfium.PdfDocument(contenido) as documento:
        assert documento[0].get_size() == pytest.approx((595.276, 841.89), abs=.02)


def test_hora_de_autorizacion_de_la_nota_de_credito_en_hora_de_ecuador():
    contexto = contexto_demo('credito')
    contexto['credit_note'].authorization_date = datetime(2026, 10, 25, 1, 30, 15, tzinfo=timezone.utc)   # 20:30:15 en Ecuador
    texto = ' '.join(html.fromstring(render_to_string(TEMPLATES['credito'], contexto)).text_content().split())
    assert 'autorización:24/10/2026 20:30:15' in texto.replace(': ', ':')


def test_liquidacion_no_parte_el_encabezado_cantidad():
    contenido = create_pdf(contexto_demo('liquidacion'), TEMPLATES['liquidacion'])
    with pdfium.PdfDocument(contenido) as documento:
        lineas = [linea.strip() for linea in documento[0].get_textpage().get_text_range().splitlines()]
    assert 'Cantidad' in ' '.join(lineas).split() and 'Cantida' not in lineas


def test_factura_no_repite_un_ruc_proveedor_escrito_a_mano():
    contexto = contexto_demo('factura')
    contexto['sale'].additional_info = [*contexto['sale'].additional_info,
                                         NS(name='RUC Proveedor', value='1790012345001'), NS(name='  ', value='sin nombre')]
    contenido = render_to_string(TEMPLATES['factura'], contexto)
    assert informacion_adicional(contenido)['RUC Proveedor'] == PROVEEDOR_DEMO['ruc']
    assert '1790012345001' not in contenido and 'sin nombre' not in contenido
