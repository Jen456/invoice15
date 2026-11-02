"""Respaldo enviado junto con el formulario de pago a proveedor o de gasto: archivo opcional `comprobante` (con su clase
`comprobante_clase`) y nota de respaldo opcional `nota_respaldo` (≤ 500). Con ambos, un solo adjunto: el archivo con la
nota como descripción. La descripción del gasto (`description`) no es un respaldo y no se copia.

La vista que registra el documento llama a adjuntar_al_registrar dentro de su misma transacción: si el archivo o la nota no
valen, no se registra el pago ni el gasto. Referencia, fecha y valor salen del propio formulario. El cobro de una cuenta por
cobrar ya no pasa por aquí: su respaldo (nota o archivo) lo registra core/cobros con el mismo cobro.
"""
from core.adjuntos import archivos, servicios as sv
from core.adjuntos.documentos import DOCUMENTOS
from core.adjuntos.models import CLASES, NOTA_MAX


def contexto():
    """Variables de plantilla de los formularios con respaldo (gasto y pago a proveedor)."""
    return {'clases_comprobante': CLASES, 'comprobante_max_mb': archivos.MAX_BYTES // archivos.MB,
            'comprobante_formatos': archivos.FORMATOS_TEXTO, 'nota_respaldo_max': NOTA_MAX}


def adjuntar_al_registrar(request, tipo, documento):
    archivo = request.FILES.get('comprobante')
    nota = request.POST.get('nota_respaldo', '')
    if archivo is None and not nota.strip():
        return None
    if tipo not in DOCUMENTOS:
        raise sv.ErrorAdjunto('Este documento se respalda desde el cobro (core/cobros), no con un adjunto genérico.', 'tipo', 400)
    permisos = sv.permisos(request, tipo)
    if not permisos['subir']:
        raise sv.ErrorAdjunto(permisos['bloqueo'] or 'Tu perfil no puede adjuntar comprobantes de pago.', 'permiso', 403)
    return sv.adjuntar(request.company, request.user, tipo, documento, archivo, clase=request.POST.get('comprobante_clase', ''),
                       referencia=request.POST.get('referencia', ''), fecha=request.POST.get('date_joined', ''),
                       importe=request.POST.get('valor', ''), nota=nota)
