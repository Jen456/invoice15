import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from crum import get_current_request
from django.contrib.staticfiles import finders
from django.http import Http404
from django.template.loader import get_template
from weasyprint import CSS
from weasyprint import HTML
from weasyprint.urls import URLFetcher, URLFetcherResponse

from config import settings
from core.security.views.files import resolve_media_path


def _allowed_roots():
    roots = [settings.BASE_DIR / 'static', settings.STATIC_ROOT, settings.MEDIA_ROOT]
    return [os.path.realpath(r) for r in roots if r]


def _local_file(url_path, scheme='http'):
    """Ruta local de un recurso /static/ o /media/, o None si no corresponde."""
    if scheme == 'file':
        # Rutas absolutas del disco que genera el propio código (p. ej. logos por defecto).
        real = os.path.realpath(url_path)
        if os.path.isfile(real) and Path(real).suffix.lower() not in {'.p12', '.pfx', '.key', '.pem'} \
                and any(real.startswith(root + os.sep) for root in _allowed_roots()):
            return real
    if url_path.startswith(settings.STATIC_URL):
        relative = url_path[len(settings.STATIC_URL):]
        found = finders.find(relative)
        if found:
            return found
        candidate = Path(settings.STATIC_ROOT) / relative
        return str(candidate) if candidate.is_file() else None
    if url_path.startswith(settings.MEDIA_URL):
        try:
            return resolve_media_path(url_path[len(settings.MEDIA_URL):])[1]
        except Http404:
            return None
    return None


class LocalOnlyURLFetcher(URLFetcher):
    """Resuelve en disco los recursos estáticos y subidos que cita la plantilla.

    No hace peticiones HTTP: generar un PDF no depende de que el propio sitio
    responda a través de Cloudflare, los archivos protegidos se leen sin sesión
    y una plantilla no puede hacer que el servidor consulte direcciones ajenas.
    """

    def fetch(self, url, headers=None):
        if url.startswith('data:'):
            return super().fetch(url, headers)
        parsed = urlparse(url)
        if parsed.scheme in ('file', 'http', 'https'):
            path = _local_file(unquote(parsed.path), parsed.scheme)
            if path:
                mime_type = mimetypes.guess_type(path)[0] or 'application/octet-stream'
                return URLFetcherResponse(Path(path).as_uri(), body=open(path, 'rb'), headers={'Content-Type': mime_type})
        raise ValueError(f'Recurso no permitido en el PDF: {url[:120]}')


def create_pdf(context, template_name):
    request = get_current_request()
    template = get_template(template_name)
    html_template = template.render(context).encode(encoding="UTF-8")
    fetcher = LocalOnlyURLFetcher()
    if request is not None:
        pdf_file = HTML(string=html_template, base_url=request.build_absolute_uri(), url_fetcher=fetcher).write_pdf(presentational_hints=True)
    else:
        path_css = f'{settings.BASE_DIR}{settings.STATIC_URL}lib/bootstrap-4.6.0/css/bootstrap.min.css'
        stylesheets = [CSS(filename=path_css)] if os.path.isfile(path_css) else []
        pdf_file = HTML(string=html_template, base_url='file:///', url_fetcher=fetcher).write_pdf(stylesheets=stylesheets, presentational_hints=True)
    return pdf_file
