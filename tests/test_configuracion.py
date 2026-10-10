"""Coherencia entre la configuración de Django y la unidad systemd del servicio."""
from pathlib import Path

from django.conf import settings

UNIDAD = Path(settings.BASE_DIR) / 'deploy/systemd/facturaporaqui@.service'


def test_subidas_sin_bits_especiales_porque_el_servicio_los_bloquea():
    assert 'RestrictSUIDSGID=true' in UNIDAD.read_text()
    assert settings.FILE_UPLOAD_PERMISSIONS & 0o7000 == 0
    assert settings.FILE_UPLOAD_DIRECTORY_PERMISSIONS & 0o7000 == 0
