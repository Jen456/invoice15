"""Plan de cuentas por empresa (C2 del contrato contable v9). Solo API: su pantalla la conecta la interfaz.

- GET   /contabilidad/api/cuentas/?q=&empresa=   `view_cuenta`    lista (con `q`: coincidencias y sus antepasadas) y capacidades
- POST  /contabilidad/api/cuentas/               `add_cuenta`     alta con `clave`: 201; repetida, 200 con `repetido: true`
- PATCH /contabilidad/api/cuentas/<id>/          `change_cuenta`  cambios con `version`: 200; 409 `version`; 404

Ver: Propietario, Administrador, Contador y Consulta. Crear y editar: Propietario, Administrador y Contador. La sesión, la
empresa de la pestaña, que el plan deje guardar y el permiso los comprueba api.ApiContable antes de llegar aquí; las reglas
están en cuentas.py."""
from django.http import JsonResponse

from core.contabilidad import api, capacidades, cuentas


class CuentasApi(api.ApiContable):
    permisos = {'GET': cuentas.VER, 'POST': cuentas.CREAR}

    def get(self, request):
        puede = capacidades.acciones(request, 'plan_cuentas')   # ya con la licencia: plan vencido, solo consulta
        return JsonResponse({
            'cuentas': cuentas.listar(request.GET.get('q', '')),
            # Importar el plan crea cuentas: lo puede quien puede crearlas.
            'capacidades': {'crear': puede['crear'], 'editar': puede['editar'], 'importar': puede['crear']},
        })

    def post(self, request):
        cuenta, repetido = cuentas.crear(request, api.cuerpo(request))
        return JsonResponse({'cuenta': cuentas.dict_cuenta(cuenta, hijas=None if repetido else 0), 'repetido': repetido},
                            status=200 if repetido else 201)


class CuentaApi(api.ApiContable):
    """No hay DELETE: una cuenta no se borra, se desactiva (`activa: false`)."""
    permisos = {'PATCH': cuentas.EDITAR}

    def patch(self, request, pk):
        return JsonResponse({'cuenta': cuentas.dict_cuenta(cuentas.modificar(request, pk, api.cuerpo(request)))})
