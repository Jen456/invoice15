"""Recorrido de todas las pantallas sin parámetros con el administrador."""
import pytest
from django.urls import URLPattern, URLResolver, get_resolver

from tests import helpers

# Fallos que ya existían en el código original con la base vacía; se corrigen
# en la etapa 2 (contexto de empresa). Si dejan de fallar, la prueba avisa.
CONOCIDOS = {}
# Respuestas esperadas distintas de 200/302.
ESPERADOS = {
    '/empresas/cambiar/': 405,   # solo POST (cambio de empresa con CSRF)
    '/suscripcion/pagar/': 405,  # solo POST (inicia el cobro en PayPhone)
}


def rutas_simples():
    def recorrer(patrones, prefijo=''):
        for p in patrones:
            if isinstance(p, URLResolver):
                yield from recorrer(p.url_patterns, prefijo + str(p.pattern))
            elif isinstance(p, URLPattern):
                yield prefijo + str(p.pattern), p.name
    for ruta, nombre in sorted(set(recorrer(get_resolver().url_patterns))):
        if '<' in ruta or nombre in ('logout',) or ruta.startswith(('plataforma/', 'media/')):
            continue
        yield '/' + ruta


@pytest.mark.django_db
def test_todas_las_pantallas_responden(client, admin):
    helpers.iniciar_sesion(client, admin)
    fallos, conocidos_ok = [], []
    for url in rutas_simples():
        try:
            estado = client.get(url).status_code
        except Exception as e:  # noqa: BLE001 - se registra y se sigue
            estado = type(e).__name__
        if url in CONOCIDOS:
            if estado in (200, 302):
                conocidos_ok.append(url)
            continue
        if url in ESPERADOS:
            if estado != ESPERADOS[url]:
                fallos.append((url, estado))
            continue
        if estado not in (200, 302):
            fallos.append((url, estado))
    assert not fallos, fallos
    assert not conocidos_ok, f'ya no fallan, retirar de CONOCIDOS: {conocidos_ok}'
