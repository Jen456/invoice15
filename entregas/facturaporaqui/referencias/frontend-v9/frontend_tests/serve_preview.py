from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
from urllib.parse import urlsplit, unquote

parser = argparse.ArgumentParser(description='Vista local de interfaz: todos los POST están deshabilitados.')
parser.add_argument('--runtime', type=Path, default=Path('/tmp/facturacion15-preview'))
parser.add_argument('--vendor-root', type=Path, default=Path(__file__).resolve().parents[1] / 'static/lib')
parser.add_argument('--port', type=int, default=8766)
args = parser.parse_args()
REPO = Path(__file__).resolve().parents[1]
RUNTIME = args.runtime.resolve()

class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        route = unquote(urlsplit(path).path)
        if route == '/sale/add/':
            return str(RUNTIME / 'site/factura.html')
        choices = [('/static/lib/', args.vendor_root.resolve()),
                   ('/static/sale/admin/', REPO / 'core/pos/static/sale/admin'),
                   ('/static/', REPO / 'static'),
                   ('/propuesta/', REPO / 'entregas/facturaporaqui/propuestas/ux-v9'),
                   ('/manuales/', REPO / 'entregas/facturaporaqui/manuales'),
                   ('/', RUNTIME / 'site')]
        for prefix, root in choices:
            if route.startswith(prefix):
                dest = (root / route[len(prefix):]).resolve()
                if dest.is_relative_to(root.resolve()):
                    return str(dest)
        return '/does-not-exist'

    def do_POST(self):
        self.send_error(405, 'Vista de prueba: no guarda ni emite documentos')

ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
