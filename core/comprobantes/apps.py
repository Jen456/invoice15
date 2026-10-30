from django.apps import AppConfig


class ComprobantesConfig(AppConfig):
    name = 'core.comprobantes'
    label = 'comprobantes'
    verbose_name = 'Comprobantes electrónicos adicionales'

    def ready(self):
        from core.comprobantes import receptores  # noqa: F401  (Etapa 2, O2: cuentas por cobrar de NC y ND)
