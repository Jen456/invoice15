"""Cada recurso de static/ que citan las plantillas y el JavaScript existe."""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders

RAIZ = Path(settings.BASE_DIR)
PATRON = re.compile(r"\{%\s*static\s+'([^']+)'\s*%\}|\blib/[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+\.(?:js|css)")


def referencias():
    encontradas = set()
    for archivo in list(RAIZ.joinpath('templates').rglob('*.html')) + list(RAIZ.joinpath('core').rglob('*.html')) \
            + list(RAIZ.joinpath('core').rglob('*.js')):
        for m in PATRON.finditer(archivo.read_text(errors='ignore')):
            encontradas.add(m.group(1) or m.group(0))
    return encontradas


def test_todos_los_estaticos_citados_existen():
    refs = referencias()
    assert len(refs) > 50
    faltan = sorted(r for r in refs if not finders.find(r))
    assert not faltan, faltan


def test_manifiesto_de_static_lib():
    import json
    manifiesto = json.loads(RAIZ.joinpath('static/lib/MANIFIESTO.json').read_text())
    for paquete in manifiesto:
        assert paquete['integrity'].startswith('sha512-')
        for archivo in paquete['archivos']:
            assert RAIZ.joinpath('static/lib', archivo['archivo']).is_file(), archivo['archivo']
