"""Importación del plan de cuentas con vista previa (C3 del contrato contable v9). Solo API: su pantalla la conecta la
interfaz.

- POST /contabilidad/api/cuentas/importar/                  multipart `archivo`, `clave`, `empresa`: lee el archivo y
                                                            devuelve el lote en vista previa (200; repetida, `repetido: true`)
- GET  /contabilidad/api/cuentas/importar/<id>/             el lote con su vista previa de ahora (para recargar la página)
- POST /contabilidad/api/cuentas/importar/<id>/mapeo/       `{empresa, codigo, nombre, padre, tipo}`: la vista previa recalculada
- POST /contabilidad/api/cuentas/importar/<id>/confirmar/   `{empresa, clave, duplicadas}`: crea las cuentas

Todas piden `add_cuenta` (Propietario, Administrador y Contador); confirmar con `duplicadas: "actualizar_nombre"` pide
además `change_cuenta`. La sesión, la empresa de la pestaña y el permiso los comprueba api.ApiContable antes de llegar
aquí; la lectura, las reglas y la confirmación están en importar_cuentas.py."""
from django.http import JsonResponse

from core.contabilidad import api, cuentas, importar_cuentas


class ImportarCuentasApi(api.ApiContable):
    permisos = {'POST': cuentas.CREAR}

    def post(self, request):
        lote, repetido = importar_cuentas.subir(request, request.FILES.get('archivo'), api.cuerpo(request))
        return JsonResponse({'lote': importar_cuentas.dict_lote(lote), 'repetido': repetido})


class ImportacionApi(api.ApiContable):
    permisos = {'GET': cuentas.CREAR}

    def get(self, request, pk):
        return JsonResponse({'lote': importar_cuentas.dict_lote(importar_cuentas.consultar(request, pk))})


class MapeoApi(api.ApiContable):
    permisos = {'POST': cuentas.CREAR}

    def post(self, request, pk):
        return JsonResponse({'lote': importar_cuentas.dict_lote(importar_cuentas.mapear(request, pk, api.cuerpo(request)))})


class ConfirmarApi(api.ApiContable):
    permisos = {'POST': cuentas.CREAR}

    def post(self, request, pk):
        lote, repetido = importar_cuentas.confirmar(request, pk, api.cuerpo(request))
        return JsonResponse({'lote': importar_cuentas.dict_lote(lote), 'repetido': repetido})
