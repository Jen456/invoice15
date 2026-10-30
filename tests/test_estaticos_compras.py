"""Escape del texto en las pantallas de Compras (espec-etapa2-compras §3, regla común, y §7): DataTables 1.10 inserta cada
dato como HTML y la razón social o las descripciones pueden venir del XML de un tercero.

- En los JS de compras, proveedores, cuentas por pagar, gastos, tipos de gasto y sus reportes, toda columna con un dato de
  texto libre usa `render: $.fn.dataTable.render.text()`.
- Ninguna plantilla de esas pantallas ni de importación usa `|safe`; los datos al JS van con json_script.
Prueba estática: no necesita base de datos."""
import re
from pathlib import Path

from django.conf import settings

RAIZ = Path(settings.BASE_DIR)
JS = [
    'core/pos/static/purchase/js/list.js', 'core/pos/static/purchase/js/form.js',
    'core/pos/static/provider/js/list.js', 'core/pos/static/provider/js/form.js',
    'core/pos/static/debts_pay/js/list.js', 'core/pos/static/debts_pay/js/form.js',
    'core/pos/static/expenses/js/list.js', 'core/pos/static/expenses/js/form.js',
    'core/pos/static/type_expense/js/list.js', 'core/pos/static/type_expense/js/form.js',
    'core/reports/static/purchase_report/js/report.js', 'core/reports/static/debts_pay_report/js/report.js',
    'core/reports/static/expenses_report/js/report.js',
]
CARPETAS_DE_PLANTILLAS = [
    'core/pos/templates/purchase', 'core/pos/templates/provider', 'core/pos/templates/debts_pay',
    'core/pos/templates/expenses', 'core/pos/templates/type_expense', 'core/reports/templates/purchase_report',
    'core/reports/templates/debts_pay_report', 'core/reports/templates/expenses_report', 'core/importacion/templates/importacion',
]
# Datos de texto libre (§3, «Escape de texto en pantallas»); una ruta como purchase.provider.name también cuenta.
SENSIBLES = ('provider.name', 'provider.ruc', 'number', 'numero_comprobante', 'description', 'descripcion', 'codigo_proveedor',
             'referencia', 'motivo', 'nombre')
COLUMNA = re.compile(r'\{\s*"?data"?\s*:\s*["\']([^"\']+)["\']')
RENDER_TEXTO = 'render: $.fn.dataTable.render.text()'


def objeto(texto, inicio):
    """Texto del objeto literal que abre en `inicio` (cuenta llaves; los JS de estas pantallas no las ponen en cadenas)."""
    nivel = 0
    for i in range(inicio, len(texto)):
        if texto[i] == '{':
            nivel += 1
        elif texto[i] == '}':
            nivel -= 1
            if nivel == 0:
                return texto[inicio:i + 1]
    raise AssertionError(f'Objeto sin cerrar en la posición {inicio}')


def columnas_sensibles():
    for ruta in JS:
        texto = RAIZ.joinpath(ruta).read_text()
        for m in COLUMNA.finditer(texto):
            dato = m.group(1)
            if any(dato == s or dato.endswith('.' + s) for s in SENSIBLES):
                yield ruta, dato, objeto(texto, m.start())


def test_los_js_existen():
    faltan = [ruta for ruta in JS if not RAIZ.joinpath(ruta).is_file()]
    assert not faltan, faltan


def test_columnas_de_texto_con_render_text():
    encontradas = list(columnas_sensibles())
    assert len(encontradas) >= 15, encontradas
    sin_escape = [(ruta, dato) for ruta, dato, columna in encontradas if RENDER_TEXTO not in columna]
    assert not sin_escape, sin_escape
    datos = {dato for _, dato, _ in encontradas}
    assert {'provider.name', 'purchase.provider.name', 'referencia', 'description'} <= datos


def test_las_columnas_de_texto_no_se_reescriben_con_columndefs():
    """Un columnDefs con su propio render sobre una columna de texto anularía el escape: estas pantallas no lo usan."""
    for ruta in JS:
        texto = RAIZ.joinpath(ruta).read_text()
        for m in re.finditer(r'columnDefs\s*:', texto):
            bloque = texto[m.end():m.end() + 2000]
            assert not re.search(r'\b(row|data)\.(provider|descripcion|description|referencia|motivo)\b', bloque), (ruta, bloque[:200])


def test_plantillas_sin_safe():
    con_safe = []
    for carpeta in CARPETAS_DE_PLANTILLAS:
        for plantilla in RAIZ.joinpath(carpeta).rglob('*.html'):
            if re.search(r'\|\s*safe\b', plantilla.read_text()):
                con_safe.append(str(plantilla.relative_to(RAIZ)))
    assert not con_safe, con_safe


def test_los_datos_al_js_van_con_json_script():
    for plantilla in ('core/pos/templates/purchase/create.html', 'core/pos/templates/purchase/list.html',
                      'core/pos/templates/debts_pay/list.html', 'core/pos/templates/type_expense/create.html'):
        assert 'json_script' in RAIZ.joinpath(plantilla).read_text(), plantilla
