from django import template

from core.suscripciones.reglas import (requiere_complemento as _requiere_complemento, requiere_ilimitado as _requiere_ilimitado,
                                      requiere_plan as _requiere_plan)

register = template.Library()


@register.filter
def bloqueado_por_plan(url, estado):
    """El módulo no se abre con el plan actual (para mostrar el candado en el menú)."""
    url = url or ''
    return estado is not None and (estado.gratuito and _requiere_plan(url) or _requiere_ilimitado(url) and not estado.ilimitado
                                   or _requiere_complemento(url) and not estado.complemento)


@register.filter
def es_complemento_contable(url):
    """El módulo es del Complemento Contable (para que el menú diga «por anunciar» en vez de «requiere plan»)."""
    return _requiere_complemento(url or '')


@register.filter
def dolares(centavos):
    return f'${int(centavos) / 100:,.2f}'
