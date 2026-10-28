from django.apps import AppConfig


class PosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.pos'

    def ready(self):
        from core.pos import senales  # noqa: F401 (archivos de los productos borrados)
        from core.pos import senales_compras  # noqa: F401 (cuentas por pagar y compras al autorizar o anular comprobantes)
