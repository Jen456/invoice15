"""Inicio contable y apertura en preparación (Parte B de contable/bloque-2-especificacion.md; C6-A). Solo API: sus pantallas
las conecta la interfaz.

- GET   /contabilidad/api/apertura/?empresa=                  `view_apertura`  configuración, apertura, vigente, cobertura,
                                                                               capacidades y acceso (200 también sin
                                                                               configurar, con todo en null)
- POST  /contabilidad/api/apertura/                           `add_apertura`   configuración y borrador con `clave`: 201;
                                                                               repetido, 200 con `repetido: true`
- GET   /contabilidad/api/apertura/<id>/                      `view_apertura`  la apertura, sus archivos, ajustes e historial
- PATCH /contabilidad/api/apertura/<id>/                      `add_apertura`   encabezado del borrador con `version` (JSON)
- POST  /contabilidad/api/apertura/<id>/importar/             `add_apertura`   multipart `archivo`, `clave`, `tipo`: lote en
                                                                               vista previa
- GET   /contabilidad/api/apertura/importar/<lote>/           `view_apertura`  el lote con su vista previa de ahora
- POST  /contabilidad/api/apertura/<id>/mapear/               `add_apertura`   líneas (captura directa o desde un lote)
- GET   /contabilidad/api/apertura/<id>/lineas/?pagina=       `view_apertura`  las líneas, paginadas
- POST  /contabilidad/api/apertura/<id>/respaldos/            `add_apertura`   multipart `archivo`, `descripcion`, `clave`
- GET   /contabilidad/api/apertura/respaldos/<id>/descargar/  `view_apertura`  el archivo, como adjunto
- POST  /contabilidad/api/apertura/respaldos/<id>/anular/     `add_apertura`   `{motivo}`
- POST  /contabilidad/api/apertura/<id>/descartar/            `add_apertura`   `{version, motivo}`
- POST  /contabilidad/api/apertura/<id>/validar/              `add_apertura`   `{version}`: bloqueos, advertencias, cobertura
                                                                               y reportes; no escribe nada
- POST  /contabilidad/api/apertura/<id>/enviar/               `add_apertura`   `{version}`: a revisión, solo sin bloqueos
- POST  /contabilidad/api/apertura/<id>/devolver/             `change_confirmacion_apertura`  `{version, motivo}`: a borrador
- POST  /contabilidad/api/apertura/<id>/confirmar/            `change_confirmacion_apertura`  `{version, clave, revisado,
                                                                               nota, incompletos_aceptados}`: el asiento
                                                                               inicial; la misma clave, `repetido`

Ver: Propietario, Administrador, Contador y Consulta. Preparar, devolver y confirmar: Propietario, Administrador y
Contador. La sesión, la
empresa de la pestaña (`?empresa=` o el envío), que el plan deje guardar y el permiso los comprueba api.ApiContable antes
de llegar aquí; cada servicio vuelve a exigir su permiso. Las reglas están en apertura.py, apertura_importar.py e
inicio_contable.py."""
from django.http import FileResponse, JsonResponse

from core.adjuntos.views import CABECERAS_ARCHIVO
from core.contabilidad import api, apertura, apertura_importar, inicio_contable, paginacion

TEXTOS = {'archivo': 'El archivo del respaldo no está disponible.'}


class AperturaApi(api.ApiContable):
    permisos = {'GET': apertura.VER, 'POST': apertura.PREPARAR}

    def get(self, request):
        return JsonResponse(apertura.datos_de_la_empresa(request))

    def post(self, request):
        inicio, creada, repetido = apertura.crear(request, api.cuerpo(request))
        return JsonResponse({'configuracion': inicio_contable.dict_configuracion(inicio),
                             'apertura': apertura.dict_apertura(creada), 'repetido': repetido},
                            status=200 if repetido else 201)


class AperturaDetalleApi(api.ApiContable):
    permisos = {'GET': apertura.VER, 'PATCH': apertura.PREPARAR}

    def get(self, request, pk):
        return JsonResponse(apertura.detalle(request, pk))

    def patch(self, request, pk):
        cambiada, inicio = apertura.editar(request, pk, api.cuerpo(request))
        return JsonResponse({'apertura': apertura.dict_apertura(cambiada),
                             'configuracion': inicio_contable.dict_configuracion(inicio)})


class ImportarApi(api.ApiContable):
    permisos = {'POST': apertura.PREPARAR}

    def post(self, request, pk):
        lote, repetido = apertura_importar.subir(request, pk, request.FILES.get('archivo'), api.cuerpo(request))
        return JsonResponse({'lote': apertura_importar.dict_lote(lote), 'repetido': repetido})


class LoteApi(api.ApiContable):
    permisos = {'GET': apertura.VER}

    def get(self, request, pk):
        return JsonResponse({'lote': apertura_importar.dict_lote(apertura_importar.consultar(request, pk))})


class MapearApi(api.ApiContable):
    permisos = {'POST': apertura.PREPARAR}

    def post(self, request, pk):
        mapeada, resumen, retiradas = apertura.mapear(request, pk, api.cuerpo(request))
        return JsonResponse({'apertura': apertura.dict_corto(mapeada, resumen), 'lineas': apertura.lineas(mapeada),
                             'retiradas': retiradas})


class LineasApi(api.ApiContable):
    permisos = {'GET': apertura.VER}

    def get(self, request, pk):
        errores = api.Errores()
        pagina, por_pagina = paginacion.pedida(request.GET, errores)
        errores.comprobar()
        consultada = apertura.obtener(pk)
        resumen = apertura.resumen(consultada)
        total = consultada.lineas.count()
        tramo = paginacion.tramo(pagina, por_pagina)
        return JsonResponse({'apertura': apertura.dict_corto(consultada, resumen),
                             'lineas': apertura.lineas(consultada, tramo.start, tramo.stop),
                             'paginacion': paginacion.datos(pagina, por_pagina, total)})


class RespaldosApi(api.ApiContable):
    permisos = {'POST': apertura.PREPARAR}

    def post(self, request, pk):
        respaldo, repetido = apertura.subir_respaldo(request, pk, request.FILES.get('archivo'), api.cuerpo(request))
        return JsonResponse({'respaldo': apertura.dict_respaldo(respaldo), 'repetido': repetido},
                            status=200 if repetido else 201)


class DescargarRespaldoApi(api.ApiContable):
    """El archivo privado del respaldo como adjunto, con las cabeceras de aislamiento de los comprobantes
    (core/adjuntos/views.py). Otra empresa: 404 JSON. Un respaldo anulado se sigue descargando: el archivo se conserva."""
    permisos = {'GET': apertura.VER}

    def get(self, request, pk):
        respaldo = apertura.obtener_respaldo(pk)
        try:
            contenido = respaldo.archivo.open('rb')
        except (FileNotFoundError, OSError, ValueError):
            raise api.ErrorApi('no_existe', TEXTOS['archivo'], 404) from None
        respuesta = FileResponse(contenido, content_type=respaldo.tipo_mime or 'application/octet-stream', as_attachment=True,
                                 filename=respaldo.nombre)
        for clave, valor in CABECERAS_ARCHIVO.items():
            respuesta[clave] = valor
        return respuesta


class AnularRespaldoApi(api.ApiContable):
    permisos = {'POST': apertura.PREPARAR}

    def post(self, request, pk):
        return JsonResponse({'respaldo': apertura.dict_respaldo(apertura.anular_respaldo(request, pk, api.cuerpo(request)))})


class DescartarApi(api.ApiContable):
    permisos = {'POST': apertura.PREPARAR}

    def post(self, request, pk):
        return JsonResponse({'apertura': apertura.dict_apertura(apertura.descartar(request, pk, api.cuerpo(request)))})


class ValidarApi(api.ApiContable):
    permisos = {'POST': apertura.PREPARAR}

    def post(self, request, pk):
        return JsonResponse(apertura.validar(request, pk, api.cuerpo(request)))


class EnviarApi(api.ApiContable):
    permisos = {'POST': apertura.PREPARAR}

    def post(self, request, pk):
        return JsonResponse({'apertura': apertura.dict_apertura(apertura.enviar(request, pk, api.cuerpo(request)))})


class DevolverApi(api.ApiContable):
    permisos = {'POST': apertura.CONFIRMAR}

    def post(self, request, pk):
        return JsonResponse({'apertura': apertura.dict_apertura(apertura.devolver(request, pk, api.cuerpo(request)))})


class ConfirmarApi(api.ApiContable):
    permisos = {'POST': apertura.CONFIRMAR}

    def post(self, request, pk):
        confirmada, repetido = apertura.confirmar(request, pk, api.cuerpo(request))
        return JsonResponse(apertura.respuesta_de_confirmar(request, confirmada, repetido))
