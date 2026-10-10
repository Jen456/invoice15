"""Entrega de archivos subidos (MEDIA) solo a usuarios autenticados.

Django comprueba la sesión y entrega el archivo; nginx no tiene acceso a los
datos. Si se define FPA_X_ACCEL_PREFIX, se delega la entrega a una ubicación
`internal` de nginx (exige que nginx pueda leer la carpeta).
Las firmas electrónicas y los respaldos nunca se entregan por esta vía.
"""
import mimetypes
import os
from pathlib import PurePosixPath
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse

from core.tenancy.storage import GLOBAL_PREFIXES, TENANT_ROOT

BLOCKED_SUFFIXES = {'.p12', '.pfx', '.key', '.pem'}
BLOCKED_PREFIXES = ('backup/',)
# Tipos que el navegador podría ejecutar como documento: se aíslan con CSP sandbox.
ACTIVE_TYPES = {'image/svg+xml', 'text/html', 'application/xhtml+xml', 'text/xml', 'application/xml'}


def resolve_media_path(path):
    """Devuelve (ruta relativa, ruta absoluta) o lanza Http404."""
    relative = PurePosixPath(path)
    if not relative.parts or relative.is_absolute() or '..' in relative.parts:
        raise Http404
    if relative.suffix.lower() in BLOCKED_SUFFIXES or relative.as_posix().startswith(BLOCKED_PREFIXES):
        raise Http404
    root = os.path.realpath(settings.MEDIA_ROOT)
    absolute = os.path.realpath(os.path.join(root, *relative.parts))
    if not absolute.startswith(root + os.sep) or not os.path.isfile(absolute):
        raise Http404
    return relative, absolute


def can_access(request, relative):
    """Archivos de empresa: solo los de la empresa activa. Globales: con sesión."""
    parts = relative.parts
    if parts[0] == TENANT_ROOT:
        company = getattr(request, 'company', None)
        return company is not None and len(parts) > 2 and parts[1] == str(company.uuid)
    return parts[0] in GLOBAL_PREFIXES


@login_required
def protected_media(request, path):
    relative, absolute = resolve_media_path(path)
    if not can_access(request, relative):
        raise Http404
    content_type = mimetypes.guess_type(absolute)[0] or 'application/octet-stream'
    if settings.FPA_X_ACCEL_PREFIX:
        response = HttpResponse(content_type=content_type)
        response['X-Accel-Redirect'] = f'{settings.FPA_X_ACCEL_PREFIX.rstrip("/")}/{quote(relative.as_posix())}'
    else:
        response = FileResponse(open(absolute, 'rb'), content_type=content_type)
    response['Cache-Control'] = 'private, max-age=3600'
    if content_type in ACTIVE_TYPES:
        response['Content-Security-Policy'] = "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    return response
