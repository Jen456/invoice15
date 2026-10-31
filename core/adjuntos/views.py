"""Comprobantes de pago adjuntos: API JSON por documento, archivo protegido y página «Comprobantes de pago» del mes."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from core.adjuntos import archivos, servicios as sv
from core.adjuntos.documentos import DOCUMENTOS, describir, obtener
from core.adjuntos.models import CLASES, Adjunto
from core.security.mixins import GroupPermissionMixin

VER, SUBIR, QUITAR = 'view_adjunto', 'add_adjunto', 'delete_adjunto'
SIN_PERMISO = 'Tu perfil no cuenta con el permiso necesario.'


def error(mensaje, estado=400, **extra):
    return JsonResponse({'error': mensaje, **extra}, status=estado)


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
        return JsonResponse({
            'documento': sv.dict_documento(tipo, documento),
            'adjuntos': [sv.dict_adjunto(a) for a in vigentes],
            'permisos': {'subir': permisos['subir'], 'quitar': permisos['quitar']}, 'bloqueo': permisos['bloqueo'],
            'clases': [{'id': c, 'name': n} for c, n in CLASES],
            'limites': {'max_bytes': archivos.MAX_BYTES, 'max_por_documento': archivos.MAX_POR_DOCUMENTO, 'formatos': archivos.FORMATOS_TEXTO},
        })

    def post(self, request, tipo, documento_id):
        documento, permisos, fallo = _documento_o_error(request, tipo, documento_id)
        if fallo:
            return fallo
        if not permisos['subir']:
            return error(permisos['bloqueo'] or 'Tu perfil no puede adjuntar comprobantes de pago.', 403)
        archivo = request.FILES.get('archivo')
        if archivo is None:
            return error('Elige el archivo del comprobante.')
        try:
            adjunto = sv.adjuntar(request.company, request.user, tipo, documento, archivo, clase=request.POST.get('clase', ''),
                                  referencia=request.POST.get('referencia', ''), fecha=request.POST.get('fecha', ''),
                                  importe=request.POST.get('importe', ''), descripcion=request.POST.get('descripcion', ''))
        except sv.ErrorAdjunto as e:
            return error(str(e), e.estado, codigo=e.codigo)
        return JsonResponse({'adjunto': sv.dict_adjunto(adjunto), 'tambien_en': sv.tambien_en(adjunto),
                             'adjuntos': [sv.dict_adjunto(a) for a in sv.listar(tipo, documento.pk, eliminados=True)]}, status=201)


class QuitarAdjunto(Api):

    def post(self, request, pk):
        adjunto = Adjunto.objects.filter(pk=pk).first()
        if adjunto is None:
            return error('El comprobante no existe o es de otra empresa.', 404)
        permisos = sv.permisos(request, adjunto.documento_tipo)
        if not permisos['ver']:
            return error(permisos['bloqueo'] or SIN_PERMISO, 403)
        if not permisos['quitar']:
            return error(permisos['bloqueo'] or 'Tu perfil no puede quitar comprobantes de pago.', 403)
        try:
            sv.quitar(request.user, adjunto, request.POST.get('motivo', ''))
        except sv.ErrorAdjunto as e:
            return error(str(e), e.estado, codigo=e.codigo)
        return JsonResponse({'adjunto': sv.dict_adjunto(adjunto)})


class ArchivoAdjunto(LoginRequiredMixin, View):
    """Único acceso al archivo (carpeta privada): empresa activa y permiso de ver el documento. Imágenes y PDF se muestran en
    el navegador dentro de un documento aislado (CSP sandbox); con ?descargar=1 se descargan."""

    def get(self, request, pk):
        if getattr(request, 'company', None) is None:
            raise Http404
        adjunto = get_object_or_404(Adjunto, pk=pk)
        if not sv.permisos(request, adjunto.documento_tipo)['ver']:
            raise Http404
        descargar = request.GET.get('descargar') == '1'
        try:
            archivo = adjunto.archivo.open('rb')
        except (FileNotFoundError, OSError):
            raise Http404
        respuesta = FileResponse(archivo, content_type=adjunto.tipo_mime, as_attachment=descargar, filename=adjunto.nombre)
        respuesta['Cache-Control'] = 'private, no-store'
        respuesta['X-Content-Type-Options'] = 'nosniff'
        respuesta['Content-Security-Policy'] = "sandbox; default-src 'none'; img-src 'self'"
        return respuesta


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
        resumen = sv.resumen_mes(inicio)
        anterior = (inicio.replace(day=1) - timezone.timedelta(days=1)).replace(day=1)
        siguiente = sv._siguiente_mes(inicio)
        context.update({'title': 'Comprobantes de pago', 'mes': inicio, 'mes_valor': f'{inicio:%Y-%m}', 'anterior': f'{anterior:%Y-%m}',
                        'siguiente': f'{siguiente:%Y-%m}' if siguiente <= hoy else '', 'resumen': resumen, 'tipos': DOCUMENTOS,
                        'clases': CLASES, 'limites': {'max_mb': archivos.MAX_BYTES // archivos.MB, 'formatos': archivos.FORMATOS_TEXTO}})
        return context


class ZipDelMes(GroupPermissionMixin, View):
    permission_required = VER

    def get(self, request):
        try:
            inicio = sv.primer_dia(request.GET.get('mes') or f'{timezone.localdate():%Y-%m}')
        except ValueError:
            raise Http404
        try:
            contenido = sv.zip_mes(inicio)
        except sv.ErrorAdjunto as e:
            return HttpResponse(str(e), status=413, content_type='text/plain; charset=utf-8')
        respuesta = HttpResponse(contenido, content_type='application/zip')
        respuesta['Content-Disposition'] = f'attachment; filename="comprobantes-de-pago-{inicio:%Y-%m}.zip"'
        respuesta['Cache-Control'] = 'private, no-store'
        return respuesta


__all__ = ['AdjuntosDocumento', 'QuitarAdjunto', 'ArchivoAdjunto', 'ComprobantesDelMes', 'ZipDelMes', 'describir']
