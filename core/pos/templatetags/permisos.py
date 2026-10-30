"""{% permisos_de 'change_anulado_sri_sale' 'add_retencionrecibida' as fpa_permisos %} → {codename: bool} del rol activo.

Para pasar permisos al JavaScript de los listados sin |safe: {{ fpa_permisos|json_script:'fpa-permisos' }} y, en el JS,
JSON.parse(document.getElementById('fpa-permisos').textContent). El servidor vuelve a comprobar cada permiso.
"""
from django import template

from core.security.session import get_group

register = template.Library()


@register.simple_tag(takes_context=True)
def permisos_de(context, *codigos):
    request = context.get('request')
    grupo = get_group(request) if request is not None else None
    if grupo is None:
        return {codigo: False for codigo in codigos}
    tiene = set(grupo.permissions.filter(codename__in=codigos).values_list('codename', flat=True))
    return {codigo: codigo in tiene for codigo in codigos}
