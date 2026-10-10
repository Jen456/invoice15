from django import template

from core.suscripciones.reglas import requiere_plan as _requiere_plan

register = template.Library()


@register.filter
def bloqueado_por_plan(url, estado):
    """El módulo no se abre con el plan actual (para mostrar el candado en el menú)."""
    return estado is not None and estado.gratuito and _requiere_plan(url or '')


@register.filter
def dolares(centavos):
    return f'${int(centavos) / 100:,.2f}'
