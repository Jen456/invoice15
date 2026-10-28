import math
import mimetypes
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from crum import get_current_request
from django.contrib.staticfiles import finders
from django.http import Http404
from django.template.loader import get_template
from weasyprint import CSS
from weasyprint import HTML
from weasyprint.formatting_structure import boxes
from weasyprint.urls import URLFetcher, URLFetcherResponse

from config import settings
from core.security.views.files import resolve_media_path


# Huella que ManifestStaticFilesStorage añade al nombre: facturaporaqui-ride.529f7e736de5.css
HUELLA = re.compile(r'\.[0-9a-f]{12}(?=\.[^./]+$)')


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
        if candidate.is_file():
            return str(candidate)
        # Con el manifiesto ya cargado pero sin el archivo con huella (collectstatic --clear en curso durante un
        # despliegue), el original de esta misma versión es el mismo archivo: sin él, el RIDE salía sin estilos.
        return finders.find(HUELLA.sub('', relative)) or None
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


def _documento(context, template_name):
    """Documento maquetado (páginas y cajas) de la plantilla con el contexto."""
    request = get_current_request()
    template = get_template(template_name)
    html_template = template.render(context).encode(encoding="UTF-8")
    fetcher = LocalOnlyURLFetcher()
    if request is not None:
        return HTML(string=html_template, base_url=request.build_absolute_uri(), url_fetcher=fetcher).render(presentational_hints=True)
    path_css = f'{settings.BASE_DIR}{settings.STATIC_URL}lib/bootstrap-4.6.0/css/bootstrap.min.css'
    stylesheets = [CSS(filename=path_css)] if os.path.isfile(path_css) else []
    return HTML(string=html_template, base_url='file:///', url_fetcher=fetcher).render(stylesheets=stylesheets, presentational_hints=True)


def create_pdf(context, template_name):
    return _documento(context, template_name).write_pdf()


# Papel continuo (ticket): una hoja tan alta como el contenido. 5000 mm es el límite práctico (el PDF admite 5080 mm).
ALTO_MAXIMO_CONTINUO = '5000mm'
MARGEN_FINAL_PX = 12   # unos 3 mm de papel después del último renglón


def _fondo_del_contenido(documento):
    """Alto (px CSS) hasta el borde inferior del contenido de la primera hoja: todas las cajas con sus rellenos y bordes,
    menos html/body (pueden llevar min-height: 100 % de la hoja) y las cajas de margen de la página."""
    fondo = 0
    for caja in documento.pages[0]._page_box.descendants():
        if isinstance(caja, (boxes.PageBox, boxes.MarginBox)) or getattr(caja, 'element_tag', None) in ('html', 'body'):
            continue
        fondo = max(fondo, caja.position_y + caja.margin_height())
    return fondo


def create_pdf_continuo(context, template_name):
    """PDF de una sola hoja tan alta como su contenido, para impresoras térmicas de papel continuo.

    Contrato con la plantilla: fija el ancho y usa {{ alto_pagina }} como alto en @page (`size: 58mm {{ alto_pagina }}`).
    Primero se maqueta en una hoja de ALTO_MAXIMO_CONTINUO y se mide el contenido; después se genera con ese alto (si aun
    así no cupiera en una hoja, se agranda y se vuelve a maquetar). Así el tamaño de letra, los saltos de línea de las
    descripciones y el número de líneas no cortan el contenido ni dejan papel en blanco. Lo que no quepa en
    ALTO_MAXIMO_CONTINUO sigue en otra hoja (no se pierde).
    """
    medida = _documento({**context, 'alto_pagina': ALTO_MAXIMO_CONTINUO}, template_name)
    if len(medida.pages) > 1:
        return medida.write_pdf()
    alto = math.ceil(_fondo_del_contenido(medida) + MARGEN_FINAL_PX)
    for _ in range(5):
        documento = _documento({**context, 'alto_pagina': f'{alto}px'}, template_name)
        if len(documento.pages) == 1:
            break
        alto += 20
    return documento.write_pdf()
