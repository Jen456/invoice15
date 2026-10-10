from django.apps import AppConfig


class SuscripcionesConfig(AppConfig):
    name = 'core.suscripciones'
    verbose_name = 'Planes, suscripciones y pagos'

    def ready(self):
        from core.suscripciones import senales  # noqa: F401 (límites del plan gratuito y reservas)
