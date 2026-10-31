"""Respaldo del cobro: /cobros/… (JSON y descarga privada). Permisos del rol en la empresa activa; los datos de otra
empresa no existen para la petición (gestor de empresa y seguridad por filas)."""
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from core.cobros import servicios as sv
from core.cobros.models import RespaldoCobro
from core.pos import cxc
from core.pos.models import Sale
from core.security.mixins import GroupPermissionMixin


def _error(e, estado=400):
    return JsonResponse({'error': str(e), 'codigo': getattr(e, 'codigo', '')}, status=estado)


def _venta(pk):
    return get_object_or_404(Sale.objects.select_related('client__user', 'receipt'), pk=pk)


def _respaldo(pk):
    return get_object_or_404(RespaldoCobro.objects.select_related('sale', 'registrado_por', 'revisado_por'), pk=pk)


class FacturaCobrosView(GroupPermissionMixin, View):
    """GET /cobros/factura/<venta>/: condición, medio, saldo, abonos con su respaldo, respaldos y capacidades."""
    permission_required = sv.PERMISO_VER

    def get(self, request, venta):
        return JsonResponse(sv.factura_json(request, _venta(venta)))


class RegistrarView(GroupPermissionMixin, View):
    """POST multipart /cobros/factura/<venta>/registrar/: clave, medio, importe (crédito: obligatorio; contado: total si falta),
    referencia, nota, archivo (PDF/JPG/PNG ≤ 5 MB), fecha (crédito). Exige archivo o nota. 201 con el respaldo; con una
    clave ya registrada, 200 y `repetido: true` sin crear nada."""
    permission_required = sv.PERMISO_REGISTRAR

    def post(self, request, venta):
        venta = _venta(venta)
        try:
            respaldo, repetido = sv.registrar(
                request, venta, clave=request.POST.get('clave', ''), medio=request.POST.get('medio', ''),
                importe=request.POST.get('importe') or None, referencia=request.POST.get('referencia', ''),
                nota=request.POST.get('nota', ''), archivo=request.FILES.get('archivo'), fecha=request.POST.get('fecha') or None)
        except (sv.ErrorCobro, cxc.ErrorCxC) as e:
            return _error(e)
        datos = sv.factura_json(request, venta)
        datos.update(respaldo=sv.respaldo_json(respaldo, request), repetido=repetido)
        return JsonResponse(datos, status=200 if repetido else 201)


class RespaldoView(GroupPermissionMixin, View):
    """GET /cobros/respaldo/<id>/: el respaldo con su historial."""
    permission_required = sv.PERMISO_VER

    def get(self, request, pk):
        return JsonResponse(sv.respaldo_json(_respaldo(pk), request, historial=True))


class EditarView(GroupPermissionMixin, View):
    """POST multipart /cobros/respaldo/<id>/editar/: nota, referencia y/o archivo (solo los enviados). Historial y, si estaba
    revisado, vuelve a pendiente."""
    permission_required = sv.PERMISO_REGISTRAR

    def post(self, request, pk):
        respaldo = _respaldo(pk)
        try:
            respaldo = sv.editar(request, respaldo, nota=request.POST.get('nota'), referencia=request.POST.get('referencia'),
                                 archivo=request.FILES.get('archivo'))
        except sv.ErrorCobro as e:
            return _error(e, 403 if e.codigo == 'sin_permiso_editar' else 400)
        return JsonResponse(sv.respaldo_json(respaldo, request, historial=True))


class RevisarView(GroupPermissionMixin, View):
    """POST /cobros/respaldo/<id>/revisar/: estado (pendiente | revisado | rechazado) y motivo (obligatorio al rechazar).
    No cambia abonos ni saldos."""
    permission_required = sv.PERMISO_REVISAR

    def post(self, request, pk):
        respaldo = _respaldo(pk)
        try:
            respaldo = sv.revisar(request, respaldo, request.POST.get('estado', ''), request.POST.get('motivo', ''))
        except sv.ErrorCobro as e:
            return _error(e)
        return JsonResponse(sv.respaldo_json(respaldo, request, historial=True))


class ArchivoView(GroupPermissionMixin, View):
    """GET /cobros/respaldo/<id>/archivo/: único acceso al comprobante (carpeta privada): empresa activa y permiso de ver."""
    permission_required = sv.PERMISO_VER

    def get(self, request, pk):
        respaldo = _respaldo(pk)
        if not respaldo.archivo:
            raise Http404
        respuesta = FileResponse(respaldo.archivo.open('rb'), content_type=sv.MIME.get(respaldo.archivo_tipo, 'application/octet-stream'),
                                 as_attachment=request.GET.get('descargar') == '1',
                                 filename=respaldo.archivo_nombre or f'respaldo-{respaldo.pk}.{respaldo.archivo_tipo}')
        respuesta['Cache-Control'] = 'private, no-store'
        respuesta['X-Content-Type-Options'] = 'nosniff'
        respuesta['Content-Security-Policy'] = "sandbox; default-src 'none'; img-src 'self'"
        return respuesta
