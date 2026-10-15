from django.apps import AppConfig


class ImportacionConfig(AppConfig):
    name = 'core.importacion'
    label = 'importacion'
    verbose_name = 'Importación de comprobantes'
    default_auto_field = 'django.db.models.BigAutoField'
