"""Comprobante enviado junto con el formulario de pago o gasto (campo opcional `comprobante`).

La vista que registra el documento llama a adjuntar_al_registrar dentro de su misma transacción: si el archivo no vale,
no se registra el pago ni el gasto. Referencia, fecha y valor salen del propio formulario.
"""
from core.adjuntos import archivos, servicios as sv
from core.adjuntos.models import CLASES


def contexto():
    """Variables de plantilla de templates/adjuntos/_campo_formulario.html."""
    return {'clases_comprobante': CLASES, 'comprobante_max_mb': archivos.MAX_BYTES // archivos.MB,
            'comprobante_formatos': archivos.FORMATOS_TEXTO}


def adjuntar_al_registrar(request, tipo, documento):
    archivo = request.FILES.get('comprobante')
    if archivo is None:
        return None
    permisos = sv.permisos(request, tipo)
    if not permisos['subir']:
        raise sv.ErrorAdjunto(permisos['bloqueo'] or 'Tu perfil no puede adjuntar comprobantes de pago.', 'permiso', 403)
    return sv.adjuntar(request.company, request.user, tipo, documento, archivo, clase=request.POST.get('comprobante_clase', ''),
                       referencia=request.POST.get('referencia', ''), fecha=request.POST.get('date_joined', ''),
                       importe=request.POST.get('valor', ''))
