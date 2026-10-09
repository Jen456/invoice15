from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class FPAStaticStorage(ManifestStaticFilesStorage):
    """Estáticos con la huella del contenido en el nombre (style.3f2a….css).

    Cada versión tiene una URL nueva, así que ni Cloudflare ni los navegadores
    pueden servir un CSS o JS antiguo, y se pueden cachear mucho tiempo. Las
    referencias a archivos que no se publican (mapas de fuente de librerías,
    URLs dentro de comentarios) se dejan tal cual en lugar de abortar.
    """
    manifest_strict = False

    def hashed_name(self, name, content=None, filename=None):
        try:
            return super().hashed_name(name, content, filename)
        except ValueError:
            return name
