from django.apps import AppConfig


class ProformasConfig(AppConfig):
    name = 'core.proformas'
    label = 'proformas'
    verbose_name = 'Proformas'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        from core.proformas import senales  # noqa: F401 - conecta pre_delete de la venta
