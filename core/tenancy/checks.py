from django.apps import apps
from django.core import checks

# Aplicaciones cuyos modelos son datos de empresa. Excepciones explícitas: la
# propia empresa (es el inquilino).
TENANT_APPS = ('pos',)
NOT_TENANT = {'pos.Company'}


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
