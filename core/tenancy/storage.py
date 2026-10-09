import os
import uuid

from django.utils import timezone
from django.utils.deconstruct import deconstructible

from core.tenancy.context import require_company

TENANT_ROOT = 'empresas'
# Archivos de la plataforma (no son de ninguna empresa): visibles con sesión.
GLOBAL_PREFIXES = ('users', 'dashboard', 'module')


@deconstructible
class CompanyPath:
    """upload_to: empresas/<uuid de la empresa>/<carpeta>/<año>/<mes>/<aleatorio>.<ext>

    El nombre aleatorio evita que una ruta se pueda adivinar y la carpeta de la
    empresa permite comprobar a quién pertenece el archivo al entregarlo.
    """

    def __init__(self, folder):
        self.folder = folder

    def __call__(self, instance, filename):
        from core.pos.models import Company
        if isinstance(instance, Company):
            company = instance
        elif getattr(instance, 'company_id', None) is not None:
            company = instance.company
        else:
            company = require_company()
        extension = os.path.splitext(filename)[1].lower()[:10]
        return f'{TENANT_ROOT}/{company.uuid}/{self.folder}/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}'

    def __eq__(self, other):
        return isinstance(other, CompanyPath) and other.folder == self.folder
