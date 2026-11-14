"""GET /contabilidad/api/inicio/[?empresa=<id>]: inicio contable (C1 del contrato contable v9). Solo API: su pantalla la
conecta la interfaz.

Lo abre quien tiene `view_kardex`, `view_revision` o `view_cuenta` (basta uno): Propietario, Administrador, Contador y
Consulta. Devuelve qué puede usar (`capacidades` y, con su explicación, `acceso`), en qué etapa está la puesta en marcha
(`etapas`) y qué tiene pendiente en lo que puede consultar (`pendientes`). La sesión, la empresa de la pestaña y el permiso
los comprueba api.ApiContable antes de llegar aquí; el complemento y el plan, PlanMiddleware (vencido: se consulta)."""
from django.http import JsonResponse

from core.contabilidad import api, inicio


class InicioApi(api.ApiContable):
    permisos = {'GET': inicio.PERMISOS}

    def get(self, request):
        return JsonResponse(inicio.datos(request))
