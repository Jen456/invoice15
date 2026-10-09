#!/usr/bin/env python3
"""Reconstruye static/lib desde los paquetes oficiales de npm.

El repositorio original nunca incluyó static/lib (lo ocultaba una regla del
.gitignore). Este guion descarga cada paquete en su versión exacta, comprueba
la huella `integrity` (sha512) que publica el registro de npm, extrae solo los
archivos listados y escribe static/lib/MANIFIESTO.json con origen, licencia y
sha256 de cada archivo.

Uso (desde la raíz del proyecto):  python3 deploy/scripts/recuperar_static_lib.py
No sobrescribe los archivos propios (FormValidation compatible y spanish.js).
"""
import base64
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from pathlib import Path, PurePosixPath

REGISTRY = 'https://registry.npmjs.org'
DESTINO = Path('static/lib')

DT = 'datatables-1.10.25'
PAQUETES = [
    ('admin-lte', '3.2.0', {'dist/css/adminlte.css': 'adminlte-3.2.0/css/adminlte.css',
                            'dist/js/adminlte.min.js': 'adminlte-3.2.0/js/adminlte.min.js'}),
    ('fastclick', '1.0.6', {'lib/fastclick.js': 'adminlte-3.2.0/plugins/fastclick/fastclick.js'}),
    ('bootstrap', '4.6.0', {'dist/css/bootstrap.min.css': 'bootstrap-4.6.0/css/bootstrap.min.css',
                            'dist/js/bootstrap.min.js': 'bootstrap-4.6.0/js/bootstrap.min.js'}),
    ('jquery', '3.5.1', {'dist/jquery.min.js': 'bootstrap-4.6.0/js/jquery.min.js'}),
    ('popper.js', '1.16.1', {'dist/umd/popper.min.js': 'bootstrap-4.6.0/js/popper.min.js'}),
    ('daterangepicker', '3.1.0', {'daterangepicker.css': 'bootstrap-daterangepicker-3.1/css/daterangepicker.css',
                                  'daterangepicker.js': 'bootstrap-daterangepicker-3.1/js/daterangepicker.js'}),
    ('moment', '2.29.1', {'min/moment.min.js': 'bootstrap-daterangepicker-3.1/js/moment.min.js',
                          'min/moment-with-locales.js': 'bootstrap-daterangepicker-3.1/js/moment-with-locales.js',
                          'locale/es.js': 'bootstrap-daterangepicker-3.1/js/moment-locale-es.js'}),
    ('bootstrap-touchspin', '4.2.5', {
        'dist/jquery.bootstrap-touchspin.css': 'bootstrap-touchspin-4.2.5/css/jquery.bootstrap-touchspin.css',
        'dist/jquery.bootstrap-touchspin.js': 'bootstrap-touchspin-4.2.5/js/jquery.bootstrap-touchspin.js'}),
    ('datatables.net', '1.10.25', {'js/jquery.dataTables.js': f'{DT}/js/jquery.dataTables.js'}),
    ('datatables.net-bs4', '1.10.25', {'css/dataTables.bootstrap4.min.css': f'{DT}/css/dataTables.bootstrap4.min.css',
                                       'js/dataTables.bootstrap4.min.js': f'{DT}/js/dataTables.bootstrap4.min.js'}),
    ('datatables.net-buttons', '1.7.1', {
        'js/dataTables.buttons.min.js': f'{DT}/plugins/buttons-1.7.1/js/dataTables.buttons.min.js',
        'js/buttons.html5.min.js': f'{DT}/plugins/buttons-1.7.1/js/buttons.html5.min.js'}),
    ('datatables.net-buttons-bs4', '1.7.1', {
        'css/buttons.bootstrap4.min.css': f'{DT}/plugins/buttons-1.7.1/css/buttons.bootstrap.min.css'}),
    # jszip 2.5.0 no publicó dist/ en npm; Buttons 1.7.1 admite JSZip 3. Se conserva la ruta
    # que usan las plantillas (jszip-2.5.0/) y el manifiesto registra la versión real.
    ('jszip', '3.10.1', {'dist/jszip.min.js': f'{DT}/plugins/jszip-2.5.0/jszip.min.js'}),
    ('pdfmake', '0.1.36', {'build/pdfmake.min.js': f'{DT}/plugins/pdfmake-0.1.36/pdfmake.min.js',
                           'build/vfs_fonts.js': f'{DT}/plugins/pdfmake-0.1.36/vfs_fonts.js'}),
    ('datatables.net-responsive', '2.2.9', {
        'js/dataTables.responsive.min.js': f'{DT}/plugins/responsive-2.2.9/js/dataTables.responsive.min.js'}),
    ('datatables.net-responsive-bs4', '2.2.9', {
        'css/responsive.bootstrap4.min.css': f'{DT}/plugins/responsive-2.2.9/css/responsive.bootstrap4.min.css',
        'js/responsive.bootstrap4.min.js': f'{DT}/plugins/responsive-2.2.9/js/responsive.bootstrap4.min.js'}),
    ('@fortawesome/fontawesome-free', '6.1.1', {'css/all.min.css': 'fontawesome-6.1.1/css/all.min.css',
                                                'webfonts/': 'fontawesome-6.1.1/webfonts/'}),
    ('es6-shim', '0.35.6', {'es6-shim.min.js': 'formvalidation-1.9.0/js/es6-shim.min.js'}),
    ('zxcvbn', '4.4.2', {'dist/zxcvbn.js': 'formvalidation-1.9.0/js/zxcvbn.js'}),
    ('highcharts', '9.1.1', {'highcharts.js': 'highcharts-9.1.1/highcharts.js',
                             'highcharts-3d.js': 'highcharts-9.1.1/highcharts-3d.js',
                             'modules/data.js': 'highcharts-9.1.1/modules/data.js',
                             'modules/drilldown.js': 'highcharts-9.1.1/modules/drilldown.js',
                             'modules/exporting.js': 'highcharts-9.1.1/modules/exporting.js'}),
    ('jquery-confirm', '3.3.4', {'dist/jquery-confirm.min.css': 'jquery-confirm-3.3.4/css/jquery-confirm.min.css',
                                 'dist/jquery-confirm.min.js': 'jquery-confirm-3.3.4/js/jquery-confirm.min.js'}),
    ('gasparesganga-jquery-loading-overlay', '2.1.7', {
        'dist/loadingoverlay.min.js': 'jquery-loading-overlay-2.1.7/js/loadingoverlay.min.js'}),
    ('jquery-ui-dist', '1.12.1', {'jquery-ui.css': 'jquery-ui-1.12.1/jquery-ui.css',
                                  'jquery-ui.min.js': 'jquery-ui-1.12.1/jquery-ui.min.js',
                                  'images/': 'jquery-ui-1.12.1/images/'}),
    ('select2', '4.0.13', {'dist/css/select2.min.css': 'select2-4.0.13/css/select2.min.css',
                           'dist/js/select2.min.js': 'select2-4.0.13/js/select2.min.js',
                           'dist/js/i18n/es.js': 'select2-4.0.13/js/i18n/es.js'}),
    ('@ttskch/select2-bootstrap4-theme', '1.5.2', {
        'dist/select2-bootstrap4.min.css': 'select2-4.0.13/css/select2-bootstrap4.min.css'}),
    ('sweetalert2', '11.0.16', {'dist/sweetalert2.min.css': 'sweetalert2-11.0.16/css/sweetalert2.min.css',
                                'dist/sweetalert2.all.min.js': 'sweetalert2-11.0.16/js/sweetalert2.all.min.js'}),
    ('tempusdominus-bootstrap', '5.37.0', {
        'build/css/tempusdominus-bootstrap.css': 'tempusdominus-bootstrap-4.5.37.0/css/tempusdominus-bootstrap.css',
        'build/js/tempusdominus-bootstrap.js': 'tempusdominus-bootstrap-4.5.37.0/js/tempusdominus-bootstrap.js'}),
]


def get(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def destino_seguro(relativa):
    ruta = PurePosixPath(relativa)
    if ruta.is_absolute() or '..' in ruta.parts:
        raise ValueError(f'ruta de destino no válida: {relativa}')
    return DESTINO.joinpath(*ruta.parts)


def recuperar(nombre, version, mapa):
    meta = json.loads(get(f'{REGISTRY}/{nombre.replace("/", "%2F")}/{version}'))
    dist = meta['dist']
    datos = get(dist['tarball'])
    algoritmo, esperado = dist['integrity'].split('-', 1)
    if algoritmo != 'sha512':
        raise ValueError(f'{nombre}: integridad {algoritmo} no admitida')
    calculado = base64.b64encode(hashlib.sha512(datos).digest()).decode()
    if calculado != esperado:
        raise ValueError(f'{nombre}@{version}: la huella sha512 no coincide con la del registro')
    archivos = []
    with tarfile.open(fileobj=io.BytesIO(datos), mode='r:gz') as tar:
        miembros = [m for m in tar.getmembers() if m.isfile()]
        raiz = miembros[0].name.split('/', 1)[0]
        por_nombre = {m.name[len(raiz) + 1:]: m for m in miembros}
        for origen, destino in mapa.items():
            if origen.endswith('/'):
                seleccion = {k[len(origen):]: m for k, m in por_nombre.items() if k.startswith(origen)}
                if not seleccion:
                    raise FileNotFoundError(f'{nombre}: carpeta {origen} vacía o inexistente')
                pares = [(m, destino + resto) for resto, m in seleccion.items()]
            else:
                if origen not in por_nombre:
                    cercanos = [k for k in por_nombre if k.endswith(PurePosixPath(origen).name)]
                    raise FileNotFoundError(f'{nombre}: no existe {origen}; parecidos: {cercanos[:5]}')
                pares = [(por_nombre[origen], destino)]
            for miembro, relativa in pares:
                contenido = tar.extractfile(miembro).read()
                ruta = destino_seguro(relativa)
                ruta.parent.mkdir(parents=True, exist_ok=True)
                ruta.write_bytes(contenido)
                archivos.append({'archivo': relativa, 'sha256': hashlib.sha256(contenido).hexdigest(),
                                 'bytes': len(contenido)})
    return {'paquete': nombre, 'version': version, 'tarball': dist['tarball'], 'integrity': dist['integrity'],
            'licencia': meta.get('license'), 'archivos': archivos}


SPANISH_ETIQUETAS = """
/* Botones del selector de fechas en español (se aplica cuando jQuery está listo,
   porque en algunas plantillas este archivo se carga antes que daterangepicker.js). */
(function ($) {
    if (!$) { return; }
    $(function () {
        if (!$.fn.daterangepicker || $.fn.daterangepicker.fpaEspanol) { return; }
        var original = $.fn.daterangepicker;
        var etiquetas = {applyLabel: 'Aplicar', cancelLabel: 'Cancelar', fromLabel: 'Desde', toLabel: 'Hasta',
                         customRangeLabel: 'Personalizado', weekLabel: 'S', firstDay: 1};
        $.fn.daterangepicker = function (options, callback) {
            options = $.extend(true, {}, options || {});
            options.locale = $.extend({}, etiquetas, options.locale || {});
            return original.call(this, options, callback);
        };
        $.fn.daterangepicker.fpaEspanol = true;
    });
})(window.jQuery);
"""


def construir_spanish():
    """spanish.js = configuración regional española oficial de moment (MIT) + etiquetas propias."""
    base = DESTINO / 'bootstrap-daterangepicker-3.1/js'
    locale = (base / 'moment-locale-es.js').read_text()
    contenido = ('/* FacturaPorAquí — selector de fechas en español.\n'
                 ' * Incluye moment/locale/es.js de moment 2.29.1 (MIT) y etiquetas propias. */\n'
                 '(function () {\n'
                 '    if (window.moment && window.moment.locales().indexOf("es") !== -1) { window.moment.locale("es"); return; }\n'
                 + locale + '\n}).call(window);\n'
                 'if (window.moment) { window.moment.locale("es"); }\n' + SPANISH_ETIQUETAS)
    (base / 'spanish.js').write_text(contenido)
    print('OK spanish.js generado')


def main():
    if not Path('manage.py').is_file():
        sys.exit('Ejecútalo desde la raíz del proyecto.')
    manifiesto = []
    for nombre, version, mapa in PAQUETES:
        entrada = recuperar(nombre, version, mapa)
        manifiesto.append(entrada)
        print(f'OK {nombre}@{version}: {len(entrada["archivos"])} archivo(s), licencia {entrada["licencia"]}')
    construir_spanish()
    (DESTINO / 'MANIFIESTO.json').write_text(json.dumps(manifiesto, indent=1, ensure_ascii=False) + '\n')
    print(f'{sum(len(e["archivos"]) for e in manifiesto)} archivos en {DESTINO}; manifiesto en {DESTINO}/MANIFIESTO.json')


if __name__ == '__main__':
    main()
