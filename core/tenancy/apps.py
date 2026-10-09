from django.apps import AppConfig


class TenancyConfig(AppConfig):
    name = 'core.tenancy'
    verbose_name = 'Plataforma multiempresa'

    def ready(self):
        from core.tenancy import checks  # noqa: F401  (registra la comprobación de modelos)
