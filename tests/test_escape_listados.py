"""Prueba estática del escape de texto de terceros en los listados que toca la Etapa 2 (O2).

DataTables inserta cada dato como HTML: las columnas de nombre de cliente, `description`, `referencia` y `documento`
deben usar $.fn.dataTable.render.text() o un render que pase el dato por la función de escape (fpaTexto, que usa
$('<div>').text(x).html()). Las plantillas que crea o toca O2 no usan |safe y los permisos llegan al JS con json_script.
"""
import re
from pathlib import Path

import pytest
from django.conf import settings

RAIZ = Path(settings.BASE_DIR)
LISTADOS_JS = (
    'core/pos/static/ctas_collect/js/list.js',
    'core/pos/static/sale/admin/js/list.js',
    'core/pos/static/credit_note/admin/js/list.js',
    'core/reports/static/sale_report/js/report.js',
    'core/reports/static/ctas_collect_report/js/report.js',
)
PLANTILLAS_O2 = (
    'core/comprobantes/templates/comprobantes/retencion_recibida/list.html',
    'core/comprobantes/templates/comprobantes/retencion_recibida/buscar.html',
    'core/comprobantes/templates/comprobantes/retencion_recibida/create.html',
    'core/comprobantes/templates/comprobantes/retencion_recibida/detalle.html',
    'core/comprobantes/templates/comprobantes/anulado/marcar.html',
    'core/comprobantes/templates/comprobantes/retencion/list.html',
    'core/comprobantes/templates/comprobantes/liquidacion/list.html',
    'core/comprobantes/templates/comprobantes/notadebito/list.html',
    'core/comprobantes/templates/comprobantes/guia/list.html',
    'core/pos/templates/ctas_collect/list.html',
    'core/pos/templates/ctas_collect/create.html',
    'core/pos/templates/sale/admin/list.html',
    'core/pos/templates/credit_note/admin/list.html',
    'core/pos/templates/company/create.html',
    'core/reports/templates/sale_report/report.html',
    'core/reports/templates/ctas_collect_report/report.html',
    'core/reports/templates/results_report/report.html',
)
SENSIBLE = re.compile(r'(names|description|referencia|^documento)')


def _cierre(texto, inicio, abre='[', cierra=']'):
    """Índice del corchete que cierra el que está en `inicio` (los JS de los listados no tienen corchetes en cadenas)."""
    nivel = 0
    for i in range(inicio, len(texto)):
        if texto[i] == abre:
            nivel += 1
        elif texto[i] == cierra:
            nivel -= 1
            if nivel == 0:
                return i
    raise AssertionError('corchete sin cerrar')


def _bloques(texto, clave):
    for m in re.finditer(clave + r'\s*:\s*\[', texto):
        inicio = m.end() - 1
        yield texto[inicio + 1:_cierre(texto, inicio)]


def _objetos(texto):
    i = 0
    while True:
        i = texto.find('{', i)
        if i < 0:
            return
        fin = _cierre(texto, i, '{', '}')
        yield texto[i + 1:fin]
        i = fin + 1


def tablas(js):
    """[(datos de cada columna, {índice: render seguro})] de cada DataTable del archivo."""
    resultado = []
    columnas_de_tablas = [b for b in _bloques(js, 'columns') if 'data:' in b]   # no las «columns» del pie del PDF
    for columnas, definiciones in zip(columnas_de_tablas, _bloques(js, 'columnDefs')):
        datos = re.findall(r'data:\s*"([^"]*)"', columnas)
        seguros = {}
        for definicion in _objetos(definiciones):
            objetivos = re.search(r'targets:\s*\[([^\]]*)\]', definicion)
            if not objetivos:
                continue
            seguro = 'dataTable.render.text()' in definicion or 'fpaTexto(' in definicion
            for objetivo in objetivos.group(1).split(','):
                indice = int(objetivo.strip())
                indice = indice if indice >= 0 else len(datos) + indice
                seguros[indice] = seguros.get(indice, False) or seguro
        resultado.append((datos, seguros))
    return resultado


@pytest.mark.parametrize('archivo', LISTADOS_JS)
def test_columnas_de_texto_escapadas(archivo):
    js = RAIZ.joinpath(archivo).read_text()
    encontradas = tablas(js)
    assert encontradas, f'{archivo}: no se encontró ninguna tabla'
    revisadas = 0
    for datos, seguros in encontradas:
        for indice, dato in enumerate(datos):
            if SENSIBLE.search(dato):
                revisadas += 1
                assert seguros.get(indice), f'{archivo}: la columna {dato!r} se inserta sin escapar'
    assert revisadas, f'{archivo}: ninguna columna de texto de terceros revisada'


def test_la_funcion_de_escape_usa_text():
    for archivo in LISTADOS_JS:
        js = RAIZ.joinpath(archivo).read_text()
        if 'fpaTexto(' in js:
            assert "return $('<div>').text(" in js, archivo


def test_el_parser_detecta_una_columna_sin_escapar():
    js = '''columns: [{data: "sale.client.user.names"}, {data: "total"}],
            columnDefs: [{targets: [-1], render: function (data) { return '$' + data; }}],'''
    [(datos, seguros)] = tablas(js)
    assert datos == ['sale.client.user.names', 'total'] and not seguros.get(0)


@pytest.mark.parametrize('archivo', PLANTILLAS_O2)
def test_plantillas_sin_safe(archivo):
    html = RAIZ.joinpath(archivo).read_text()
    assert '|safe' not in html and '|safe' not in html.replace(' ', ''), archivo


def test_permisos_al_js_con_json_script():
    for archivo in ('core/pos/templates/sale/admin/list.html', 'core/pos/templates/credit_note/admin/list.html'):
        html = RAIZ.joinpath(archivo).read_text()
        assert "|json_script:'fpa-permisos'" in html, archivo
    for archivo in ('core/pos/static/sale/admin/js/list.js', 'core/pos/static/credit_note/admin/js/list.js'):
        assert "JSON.parse(nodo.textContent)" in RAIZ.joinpath(archivo).read_text(), archivo
