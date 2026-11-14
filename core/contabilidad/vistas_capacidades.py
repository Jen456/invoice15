"""GET /contabilidad/api/capacidades/[?empresa=<id>]: qué puede usar el usuario del Complemento Contable en la empresa
activa y, si no puede, por qué (licencia, permiso, módulo pendiente o datos por completar). Es la ruta que explica el
bloqueo, así que responde también con el complemento cerrado, sin plan o con el plan vencido
(reglas.RUTAS_DE_CAPACIDADES); por eso mismo no devuelve ningún dato contable."""
from django.http import JsonResponse

from core.contabilidad import api, capacidades


class CapacidadesApi(api.ApiContable):
    """Cualquier rol de personal de la empresa; el rol Cliente (portal del comprador), 403 `sin_permiso`."""
    permisos = {'GET': api.PERSONAL}

    def get(self, request):
        return JsonResponse(capacidades.capacidades(request))
