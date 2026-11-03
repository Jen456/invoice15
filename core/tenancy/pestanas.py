"""Pestañas abiertas con otra empresa: la página manda para qué empresa se armó (`empresa=<id>` en la consulta o en el
envío) y, si ya no es la activa (se cambió en otra pestaña), el servidor responde 409 `empresa_cambiada` sin crear ni
mostrar nada de la empresa nueva."""
EMPRESA_CAMBIADA = ('La empresa activa cambió en otra pestaña: vuelve a cargar la página para ver los datos de la empresa '
                    'que tienes abierta ahora.')


def empresa_cambiada(request):
    """True si el enlace o el formulario se armó para otra empresa que ya no es la activa."""
    pedida = request.GET.get('empresa') or (request.POST.get('empresa') if request.method == 'POST' else None)
    actual = getattr(request, 'company', None)
    return bool(pedida) and str(actual.pk if actual is not None else '') != str(pedida).strip()
