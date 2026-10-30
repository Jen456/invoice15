from core.configuracion import servicios as sv


def configuracion(request):
    """Aviso «Configura tu facturación» para quien puede resolverlo, solo con plan pagado."""
    company = getattr(request, 'company', None)
    if company is None or not request.user.is_authenticated or request.path.startswith(('/plataforma/', sv.URL)):
        return {}
    plan = getattr(request, '_fpa_estado_plan', None)
    if plan is None:
        from core.suscripciones.servicios import estado_de_peticion
        plan = estado_de_peticion(request)
    if plan is None or not plan.pagado:
        return {}
    from core.security.session import get_group
    group = get_group(request)
    if not request.user.is_superuser and (group is None or not group.groupmodule_set.filter(module__url=sv.URL).exists()):
        return {}
    faltan = sv.requisitos_de_emision(company, sv.FACTURA, electronica=True)
    return {'fpa_config_pendiente': faltan[0] if faltan else None}


def puntos(request):
    """Selector del punto de emisión (cabecera): el punto activo del usuario y los que puede elegir."""
    company = getattr(request, 'company', None)
    if company is None or not request.user.is_authenticated or request.path.startswith('/plataforma/'):
        return {}
    from core.configuracion import puntos as pt
    elegibles = pt.elegibles(request.user, company)
    if not elegibles:
        return {}
    return {'fpa_punto': pt.punto_activo(request.user, company, elegibles), 'fpa_puntos': elegibles}
