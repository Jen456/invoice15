from django.apps import apps
from django.core import checks

# Aplicaciones cuyos modelos son datos de empresa. Excepciones explícitas: la
# propia empresa (es el inquilino).
TENANT_APPS = ('pos', 'comprobantes', 'importacion')
NOT_TENANT = {'pos.Company', 'comprobantes.CodigoRetencion'}


@checks.register()
def tenant_models_check(app_configs, **kwargs):
    from core.tenancy.models_base import TenantModel
    errors = []
    for model in apps.get_models():
        if model._meta.app_label in TENANT_APPS and model._meta.label not in NOT_TENANT \
                and not issubclass(model, TenantModel):
            errors.append(checks.Error(
                f'{model._meta.label} es un dato de empresa y no hereda de TenantModel',
                hint='Hereda de core.tenancy.models_base.TenantModel para aislarlo por empresa.',
                id='fpa.E001'))
    return errors


@checks.register()
def llaves_de_cifrado_check(app_configs, **kwargs):
    """Sin FPA_CLAVES_CIFRADO válidas el servidor no arranca (desplegar.sh se detiene en `check`); en desarrollo, aviso."""
    from django.conf import settings

    from core.tenancy import cifrado
    if not [k for k in getattr(settings, 'FPA_CLAVES_CIFRADO', []) if k.strip()]:
        if settings.DEBUG:
            return [checks.Warning('Sin FPA_CLAVES_CIFRADO: en desarrollo se usa una llave derivada de SECRET_KEY.', id='fpa.W002')]
        return [checks.Error('Falta FPA_CLAVES_CIFRADO: la clave de la firma electrónica se guarda cifrada con esa llave.',
                             hint='Genera una con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"',
                             id='fpa.E002')]
    try:
        cifrado.descifrar(cifrado.cifrar('comprobación'))
    except Exception:  # noqa: BLE001 - llave con formato inválido
        return [checks.Error('FPA_CLAVES_CIFRADO tiene una llave que no es Fernet válida (32 bytes en base64 url-safe).', id='fpa.E003')]
    return []
