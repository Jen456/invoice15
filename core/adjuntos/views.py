"""Comprobantes de pago adjuntos (compras, gastos y pagos a proveedores): API JSON por documento (archivo o nota), archivo
protegido, página «Comprobantes de pago» del mes (que recoge también los respaldos de cobros de core/cobros y los recibos
por completar) y recibos o notas guardados para completar después (capturas: API, archivo y página)."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from core.adjuntos import archivos, capturas as cp, servicios as sv
from core.adjuntos.documentos import DOCUMENTOS, describir, obtener
from core.adjuntos.models import CLASES, NOTA_MAX, Adjunto
from core.security.mixins import GroupPermissionMixin

VER, SUBIR, QUITAR = 'view_adjunto', 'add_adjunto', 'delete_adjunto'
SIN_PERMISO = 'Tu perfil no cuenta con el permiso necesario.'
CABECERAS_ARCHIVO = {'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                     'Content-Security-Policy': "sandbox; default-src 'none'; img-src 'self'"}


def error(mensaje, estado=400, **extra):
    return JsonResponse({'error': mensaje, **extra}, status=estado)


def error_de(e):
    """JsonResponse de un ErrorAdjunto o ErrorCaptura: {error, codigo} más la captura afectada y los errores por campo."""
    extra = {'codigo': e.codigo}
    if getattr(e, 'captura', None) is not None:
        extra['captura'] = cp.dict_captura(e.captura)
    if getattr(e, 'errores', None):
        extra['errores'] = e.errores
    return error(str(e), e.estado, **extra)


def limites():
    return {'max_bytes': archivos.MAX_BYTES, 'max_por_documento': archivos.MAX_POR_DOCUMENTO, 'formatos': archivos.FORMATOS_TEXTO,
            'nota_max': NOTA_MAX}


def servir(objeto, request):
    """El archivo privado (inline o, con ?descargar=1, adjunto) con las cabeceras de aislamiento. 404 sin archivo."""
    if not objeto.archivo:
        raise Http404
    try:
        contenido = objeto.archivo.open('rb')
    except (FileNotFoundError, OSError, ValueError):
        raise Http404
    respuesta = FileResponse(contenido, content_type=objeto.tipo_mime or 'application/octet-stream',
                             as_attachment=request.GET.get('descargar') == '1', filename=objeto.nombre or f'recibo.{objeto.extension}')
    for clave, valor in CABECERAS_ARCHIVO.items():
        respuesta[clave] = valor
    return respuesta


class Api(View):
    """Siempre JSON: sin sesión o sin empresa activa, 403."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or getattr(request, 'company', None) is None:
            return error(SIN_PERMISO, 403)
        return super().dispatch(request, *args, **kwargs)


def _documento_o_error(request, tipo, documento_id):
    if tipo not in DOCUMENTOS:
        return None, None, error('Tipo de documento desconocido.', 404)
    permisos = sv.permisos(request, tipo)
    if not permisos['ver']:
        return None, None, error(permisos['bloqueo'] or SIN_PERMISO, 403)
    documento = obtener(tipo, documento_id)
    if documento is None:
        return None, None, error('El documento no existe o es de otra empresa.', 404)
    return documento, permisos, None


class AdjuntosDocumento(Api):

    def get(self, request, tipo, documento_id):
        documento, permisos, fallo = _documento_o_error(request, tipo, documento_id)
        if fallo:
            return fallo
        vigentes = sv.listar(tipo, documento.pk, eliminados=True)
        pendientes = []
        if permisos['subir'] and cp.GESTIONAR in cp._codigos(request):
            pendientes = cp.pendientes_para_vincular(request)
        return JsonResponse({
            'documento': sv.dict_documento(tipo, documento),
            'adjuntos': [sv.dict_adjunto(a) for a in vigentes],
            'permisos': {'subir': permisos['subir'], 'quitar': permisos['quitar']}, 'bloqueo': permisos['bloqueo'],
            'clases': [{'id': c, 'name': n} for c, n in CLASES],
            'limites': limites(),
            'capturas_pendientes': pendientes,
        })

    def post(self, request, tipo, documento_id):
        documento, permisos, fallo = _documento_o_error(request, tipo, documento_id)
        if fallo:
            return fallo
        if not permisos['subir']:
            return error(permisos['bloqueo'] or 'Tu perfil no puede adjuntar comprobantes de pago.', 403)
        try:
            adjunto = sv.adjuntar(request.company, request.user, tipo, documento, request.FILES.get('archivo'),
                                  clase=request.POST.get('clase', ''), referencia=request.POST.get('referencia', ''),
                                  fecha=request.POST.get('fecha', ''), importe=request.POST.get('importe', ''),
                                  descripcion=request.POST.get('descripcion', ''), nota=request.POST.get('nota', ''))
        except sv.ErrorAdjunto as e:
            return error_de(e)
        return JsonResponse({'adjunto': sv.dict_adjunto(adjunto), 'tambien_en': sv.tambien_en(adjunto),
                             'adjuntos': [sv.dict_adjunto(a) for a in sv.listar(tipo, documento.pk, eliminados=True)]}, status=201)


class QuitarAdjunto(Api):

    def post(self, request, pk):
        adjunto = Adjunto.objects.filter(pk=pk).first()
        if adjunto is None or adjunto.documento_tipo not in DOCUMENTOS:
            return error('El comprobante no existe o es de otra empresa.', 404)
        permisos = sv.permisos(request, adjunto.documento_tipo)
        if not permisos['ver']:
            return error(permisos['bloqueo'] or SIN_PERMISO, 403)
        if not permisos['quitar']:
            return error(permisos['bloqueo'] or 'Tu perfil no puede quitar comprobantes de pago.', 403)
        try:
            sv.quitar(request.user, adjunto, request.POST.get('motivo', ''))
        except sv.ErrorAdjunto as e:
            return error_de(e)
        return JsonResponse({'adjunto': sv.dict_adjunto(adjunto)})


class ArchivoAdjunto(LoginRequiredMixin, View):
    """Único acceso al archivo (carpeta privada): empresa activa y permiso de ver el documento. Imágenes y PDF se muestran en
    el navegador dentro de un documento aislado (CSP sandbox); con ?descargar=1 se descargan. Una nota no tiene archivo: 404."""

    def get(self, request, pk):
        if getattr(request, 'company', None) is None:
            raise Http404
        adjunto = get_object_or_404(Adjunto, pk=pk)
        if adjunto.documento_tipo not in DOCUMENTOS or not sv.permisos(request, adjunto.documento_tipo)['ver']:
            raise Http404
        return servir(adjunto, request)


# ------------------------------------------------------------------ página del mes

class ComprobantesDelMes(GroupPermissionMixin, TemplateView):
    template_name = 'adjuntos/mes.html'
    permission_required = VER

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hoy = timezone.localdate()
        try:
            inicio = sv.primer_dia(self.request.GET.get('mes') or f'{hoy:%Y-%m}')
        except ValueError:
            inicio = hoy.replace(day=1)
        resumen = sv.resumen_mes(inicio, self.request)   # filas de ambos orígenes según los permisos del rol
        anterior = (inicio.replace(day=1) - timezone.timedelta(days=1)).replace(day=1)
        siguiente = sv._siguiente_mes(inicio)
        context.update({'title': 'Comprobantes de pago', 'mes': inicio, 'mes_valor': f'{inicio:%Y-%m}', 'anterior': f'{anterior:%Y-%m}',
                        'siguiente': f'{siguiente:%Y-%m}' if siguiente <= hoy else '', 'resumen': resumen, 'tipos': DOCUMENTOS,
                        'clases': CLASES, 'limites': {'max_mb': archivos.MAX_BYTES // archivos.MB, 'formatos': archivos.FORMATOS_TEXTO},
                        'url_capturas': '/adjuntos/capturas/'})
        return context


class ZipDelMes(GroupPermissionMixin, View):
    permission_required = VER

    def get(self, request):
        try:
            inicio = sv.primer_dia(request.GET.get('mes') or f'{timezone.localdate():%Y-%m}')
        except ValueError:
            raise Http404
        try:
            contenido = sv.zip_mes(inicio, request=request)
        except sv.ErrorAdjunto as e:
            return HttpResponse(str(e), status=413, content_type='text/plain; charset=utf-8')
        respuesta = HttpResponse(contenido, content_type='application/zip')
        respuesta['Content-Disposition'] = f'attachment; filename="comprobantes-de-pago-{inicio:%Y-%m}.zip"'
        respuesta['Cache-Control'] = 'private, no-store'
        return respuesta


# ------------------------------------------------------------------ recibos y notas por completar (capturas)

class CapturaApiBase(Api):
    """Exige `view_captura` (403 JSON)."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and getattr(request, 'company', None) is not None \
                and cp.VER not in cp._codigos(request):
            return error(cp.MENSAJES['sin_permiso_ver'], 403, codigo='sin_permiso_ver')
        return super().dispatch(request, *args, **kwargs)


class CapturasApi(CapturaApiBase):
    """GET lista (?estado=pendiente|completada|vinculada|descartada|todas); POST multipart guarda un recibo y/o una nota."""

    def get(self, request):
        estado = request.GET.get('estado') or 'pendiente'
        return JsonResponse({'estado': estado if estado in cp.ESTADOS_FILTRO else 'pendiente',
                             'capturas': [cp.dict_captura(c, request) for c in cp.listar(request, estado)],
                             'pendientes': cp.contar_pendientes(request), 'capacidades': cp.capacidades(request),
                             'limites': limites(), 'clave_sugerida': cp.clave_sugerida()})

    def post(self, request):
        try:
            captura, repetida = cp.registrar(request, clave=request.POST.get('clave', ''), archivo=request.FILES.get('archivo'),
                                             nota=request.POST.get('nota', ''))
        except sv.ErrorAdjunto as e:
            respuesta = error_de(e)
            return respuesta
        return JsonResponse({'captura': cp.dict_captura(captura, request, detalle=True), 'repetido': repetida,
                             'clave_sugerida': cp.clave_sugerida()}, status=200 if repetida else 201)


class CapturaApi(CapturaApiBase):
    """GET detalle de una captura visible, con sus capacidades y los datos para completarla como gasto."""

    def get(self, request, pk):
        try:
            captura = cp.obtener_visible(request, pk)
        except sv.ErrorAdjunto as e:
            return error_de(e)
        datos = {'captura': cp.dict_captura(captura, request, detalle=True)}
        if datos['captura']['capacidades']['completar_gasto']:
            datos.update(opciones=cp.opciones_gasto(), sugerencias=cp.sugerencias_gasto(captura))
        return JsonResponse(datos)


class CompletarCaptura(CapturaApiBase):
    """POST: type_expense, date_joined, valor, medio_pago, referencia, description (los de «Nuevo gasto»)."""

    def post(self, request, pk):
        try:
            captura, gasto, creados = cp.completar_gasto(request, pk, request.POST)
        except sv.ErrorAdjunto as e:
            return error_de(e)
        return JsonResponse({'captura': cp.dict_captura(captura, request), 'gasto': {'id': gasto.pk, 'titulo': describir('gasto', gasto)['titulo']},
                             'adjuntos': [sv.dict_adjunto(a) for a in creados]}, status=201)


class VincularCaptura(CapturaApiBase):
    """POST: tipo (compra | gasto | pago) y documento_id."""

    def post(self, request, pk):
        try:
            captura, documento, creados, ya_adjunto = cp.vincular(request, pk, request.POST.get('tipo', ''),
                                                                  request.POST.get('documento_id', ''))
        except sv.ErrorAdjunto as e:
            return error_de(e)
        return JsonResponse({'captura': cp.dict_captura(captura, request), 'adjuntos': [sv.dict_adjunto(a) for a in creados],
                             'ya_adjunto': sv.dict_adjunto(ya_adjunto) if ya_adjunto else None,
                             'tambien_en': sv.tambien_en(creados[0]) if creados else []}, status=201)


class DocumentosParaVincular(CapturaApiBase):
    """GET ?tipo=compra|gasto|pago&q=texto: documentos recientes donde el rol puede dejar el recibo (máximo 20)."""

    def get(self, request):
        try:
            documentos = cp.documentos_para_vincular(request, request.GET.get('tipo', ''), request.GET.get('q', ''))
        except sv.ErrorAdjunto as e:
            return error_de(e)
        return JsonResponse({'documentos': documentos})


class DescartarCaptura(CapturaApiBase):
    """POST: motivo (opcional, ≤ 300)."""

    def post(self, request, pk):
        try:
            captura = cp.descartar(request, pk, request.POST.get('motivo', ''))
        except sv.ErrorAdjunto as e:
            return error_de(e)
        return JsonResponse({'captura': cp.dict_captura(captura, request)})


class NotaCaptura(CapturaApiBase):
    """POST: nota (≤ 500). Solo mientras está pendiente."""

    def post(self, request, pk):
        try:
            captura = cp.editar_nota(request, pk, request.POST.get('nota', ''))
        except sv.ErrorAdjunto as e:
            return error_de(e)
        return JsonResponse({'captura': cp.dict_captura(captura, request)})


class ArchivoCaptura(LoginRequiredMixin, View):
    """Archivo privado de una captura: empresa activa, `view_captura` y visibilidad (propias sin `view_adjunto`)."""

    def get(self, request, pk):
        if getattr(request, 'company', None) is None or cp.VER not in cp._codigos(request):
            raise Http404
        try:
            captura = cp.obtener_visible(request, pk)
        except sv.ErrorAdjunto:
            raise Http404
        return servir(captura, request)


class CapturasPagina(GroupPermissionMixin, TemplateView):
    """Pantalla funcional «Recibos por completar» (el diseño lo hace Codex sobre el contrato de HANDOFF)."""
    template_name = 'adjuntos/capturas.html'
    permission_required = cp.VER

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        estado = self.request.GET.get('estado') or 'pendiente'
        lista = [cp.dict_captura(c, self.request) for c in cp.listar(self.request, estado)]
        capacidades = cp.capacidades(self.request)
        context.update({'title': 'Recibos por completar', 'estado': estado if estado in cp.ESTADOS_FILTRO else 'pendiente',
                        'capturas': lista, 'capacidades': capacidades, 'limites': limites(), 'clave_sugerida': cp.clave_sugerida(),
                        'opciones': cp.opciones_gasto() if capacidades['completar_gasto'] else None,
                        'pendientes': cp.contar_pendientes(self.request), 'seleccionada': self.request.GET.get('captura', '')})
        return context


__all__ = ['AdjuntosDocumento', 'QuitarAdjunto', 'ArchivoAdjunto', 'ComprobantesDelMes', 'ZipDelMes', 'CapturasApi', 'CapturaApi',
           'CompletarCaptura', 'VincularCaptura', 'DocumentosParaVincular', 'DescartarCaptura', 'NotaCaptura', 'ArchivoCaptura', 'CapturasPagina', 'describir']
