"""Restore public frontend assets at the legacy paths used by templates.
Run with Python 3 from the checkout. Private FormValidation assets are not included.
"""
from pathlib import Path
from urllib.request import urlopen
from concurrent.futures import ThreadPoolExecutor
ROOT = Path(__file__).resolve().parents[2] / 'static' / 'lib'
assets = {}
def add(local, package, files):
    for target, source in files.items():
        assets[local + '/' + target] = 'https://cdn.jsdelivr.net/npm/' + package + '/' + source
add('bootstrap-4.6.0', 'bootstrap@4.6.0', {'css/bootstrap.min.css':'dist/css/bootstrap.min.css','js/bootstrap.min.js':'dist/js/bootstrap.min.js'})
add('bootstrap-4.6.0', 'jquery@3.6.0', {'js/jquery.min.js':'dist/jquery.min.js'})
add('bootstrap-4.6.0', 'popper.js@1.16.1', {'js/popper.min.js':'dist/umd/popper.min.js'})
add('adminlte-3.2.0','admin-lte@3.2.0',{'css/adminlte.css':'dist/css/adminlte.min.css','js/adminlte.min.js':'dist/js/adminlte.min.js'})
add('adminlte-3.2.0','fastclick@1.0.6',{'plugins/fastclick/fastclick.js':'lib/fastclick.js'})
add('fontawesome-6.1.1','@fortawesome/fontawesome-free@6.1.1',dict({'css/all.min.css':'css/all.min.css'},**{'webfonts/'+f:'webfonts/'+f for f in ['fa-solid-900.woff2','fa-solid-900.ttf','fa-regular-400.woff2','fa-regular-400.ttf','fa-brands-400.woff2','fa-brands-400.ttf']}))
add('jquery-ui-1.12.1','jquery-ui-dist@1.12.1',{'jquery-ui.css':'jquery-ui.min.css','jquery-ui.min.js':'jquery-ui.min.js'})
add('bootstrap-daterangepicker-3.1','moment@2.29.4',{'js/moment.min.js':'min/moment.min.js','js/moment-with-locales.js':'min/moment-with-locales.min.js'})
add('jquery-confirm-3.3.4','jquery-confirm@3.3.4',{'css/jquery-confirm.min.css':'dist/jquery-confirm.min.css','js/jquery-confirm.min.js':'dist/jquery-confirm.min.js'})
add('sweetalert2-11.0.16','sweetalert2@11.0.16',{'css/sweetalert2.min.css':'dist/sweetalert2.min.css','js/sweetalert2.all.min.js':'dist/sweetalert2.all.min.js'})
add('jquery-loading-overlay-2.1.7','gasparesganga-jquery-loading-overlay@2.1.7',{'js/loadingoverlay.min.js':'dist/loadingoverlay.min.js'})
add('highcharts-9.1.1','highcharts@9.1.1',{p:p for p in ['highcharts.js','highcharts-3d.js','modules/exporting.js','modules/data.js','modules/drilldown.js']})
add('datatables-1.10.25','datatables.net@1.10.25',{'js/jquery.dataTables.js':'js/jquery.dataTables.min.js'})
add('datatables-1.10.25','datatables.net-bs4@1.10.25',{'js/dataTables.bootstrap4.min.js':'js/dataTables.bootstrap4.min.js','css/dataTables.bootstrap4.min.css':'css/dataTables.bootstrap4.min.css'})
add('datatables-1.10.25/plugins/responsive-2.2.9','datatables.net-responsive@2.2.9',{'js/dataTables.responsive.min.js':'js/dataTables.responsive.min.js'})
add('datatables-1.10.25/plugins/responsive-2.2.9','datatables.net-responsive-bs4@2.2.9',{'js/responsive.bootstrap4.min.js':'js/responsive.bootstrap4.min.js','css/responsive.bootstrap4.min.css':'css/responsive.bootstrap4.min.css'})
add('select2-4.0.13','select2@4.0.13',{'css/select2.min.css':'dist/css/select2.min.css','js/select2.min.js':'dist/js/select2.min.js','js/i18n/es.js':'dist/js/i18n/es.js'})
add('bootstrap-touchspin-4.2.5','bootstrap-touchspin@4.2.5',{'css/jquery.bootstrap-touchspin.css':'dist/jquery.bootstrap-touchspin.min.css','js/jquery.bootstrap-touchspin.js':'dist/jquery.bootstrap-touchspin.min.js'})
add('select2-4.0.13','@ttskch/select2-bootstrap4-theme@1.5.2',{'css/select2-bootstrap4.min.css':'dist/select2-bootstrap4.min.css'})
def fetch(item):
    local, url = item
    destination=ROOT/local
    if destination.exists(): return
    with urlopen(url, timeout=45) as response: data=response.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=6) as pool: list(pool.map(fetch, assets.items()))
    print(f'Prepared {len(assets)} public assets. Licensed FormValidation files remain required for form validation.')
