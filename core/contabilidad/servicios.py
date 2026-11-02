"""Movimientos manuales del kardex (saldo inicial, entradas y salidas con su documento de respaldo) y registro de los
ajustes de stock. Los movimientos manuales no cambian el stock: completan la historia que no está en el sistema.

- Sin duplicados: cada envío lleva su `clave`. Repetirlo con el mismo contenido devuelve el mismo movimiento; con otro
  contenido, 409 `clave_usada`. Anular bloquea la fila (`select_for_update`): dos anulaciones a la vez dejan una sola.
- Nada se borra: anular conserva el movimiento con quién, cuándo y por qué, y el kardex deja de contarlo.
"""
import re
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.contabilidad.kardex import SEIS, fecha_de
from core.contabilidad.models import (CON_COSTO, DOCUMENTO_MAX, MOTIVO_MAX, NOTA_MAX, TIPOS_MANUALES, AjusteInventario,
                                      MovimientoManual)
from core.security.session import get_group
from core.tenancy.models import audit

VER, REGISTRAR, ANULAR = 'view_kardex', 'add_movimientomanual', 'change_movimientomanual'
CLAVE = re.compile(r'^[A-Za-z0-9_-]{8,40}$')
COSTO_MAX = Decimal('100000000')
CANTIDAD_MAX = 1000000000
MENSAJES = {
    'sin_permiso': 'Tu perfil no puede registrar movimientos del kardex.',
    'sin_permiso_anular': 'Tu perfil no puede anular movimientos del kardex.',
    'clave': 'Falta la clave del envío: vuelve a abrir el formulario.',
    'clave_usada': 'Esta clave ya se usó para otro movimiento: vuelve a abrir el formulario e inténtalo de nuevo.',
    'producto': 'El producto no existe, es de otra empresa o no es inventariado.',
    'tipo': 'Elige saldo inicial, entrada o salida.',
    'fecha': 'Escribe una fecha válida (AAAA-MM-DD) que no sea futura.',
    'cantidad': 'La cantidad debe ser un número entero mayor que cero.',
    'costo': 'Escribe el costo unitario sin IVA: cero o más, con hasta 6 decimales.',
    'costo_salida': 'La salida manual sale al costo promedio: no lleva costo.',
    'documento': f'Indica el documento de respaldo (hasta {DOCUMENTO_MAX} caracteres).',
    'nota_larga': f'La nota admite hasta {NOTA_MAX} caracteres.',
    'motivo': f'Indica el motivo de la anulación (hasta {MOTIVO_MAX} caracteres).',
    'movimiento': 'El movimiento no existe o es de otra empresa.',
    'ya_anulado': 'Este movimiento ya estaba anulado: no se cambió nada.',
}


class ErrorKardex(Exception):
    def __init__(self, codigo, mensaje=None, estado=400, movimiento=None, errores=None):
        super().__init__(mensaje or MENSAJES[codigo])
        self.codigo, self.estado, self.movimiento, self.errores = codigo, estado, movimiento, errores or {}


def codigos(request):
    grupo = get_group(request)
    return set(grupo.permissions.values_list('codename', flat=True)) if grupo is not None else set()


def capacidades(request):
    tiene = codigos(request)
    return {'ver': VER in tiene, 'registrar': VER in tiene and REGISTRAR in tiene, 'anular': VER in tiene and ANULAR in tiene}


def _costo(texto):
    texto = str(texto if texto is not None else '').strip().replace(',', '.')
    if not texto:
        return None
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        raise ErrorKardex('costo', errores={'costo_unitario': MENSAJES['costo']})
    if not valor.is_finite() or valor < 0 or valor >= COSTO_MAX or valor != valor.quantize(SEIS):
        raise ErrorKardex('costo', errores={'costo_unitario': MENSAJES['costo']})
    return valor.quantize(SEIS)


def _cantidad(texto):
    try:
        valor = int(str(texto).strip())
    except (TypeError, ValueError):
        raise ErrorKardex('cantidad', errores={'cantidad': MENSAJES['cantidad']})
    if valor <= 0 or valor > CANTIDAD_MAX:
        raise ErrorKardex('cantidad', errores={'cantidad': MENSAJES['cantidad']})
    return valor


def dict_movimiento(m):
    return {'id': m.pk, 'clave': m.clave, 'producto': {'id': m.producto_id, 'codigo': m.producto.code, 'nombre': m.producto.name},
            'tipo': {'id': m.tipo, 'name': m.get_tipo_display()}, 'fecha': m.fecha.isoformat(), 'cantidad': m.cantidad,
            'costo_unitario': f'{m.costo_unitario:.6f}' if m.costo_unitario is not None else None, 'documento': m.documento,
            'nota': m.nota, 'creado_por': m.creado_por.username if m.creado_por_id else '',
            'creado_en': timezone.localtime(m.creado_en).strftime('%Y-%m-%d %H:%M'), 'anulado': m.anulado_en is not None,
            'anulado_en': timezone.localtime(m.anulado_en).strftime('%Y-%m-%d %H:%M') if m.anulado_en else '',
            'anulado_por': m.anulado_por.username if m.anulado_por_id else '', 'motivo_anulacion': m.motivo_anulacion}


def _validar(datos):
    from core.pos.models import Product
    errores = {}
    tipo = str(datos.get('tipo') or '').strip()
    if tipo not in dict(TIPOS_MANUALES):
        raise ErrorKardex('tipo', errores={'tipo': MENSAJES['tipo']})
    try:
        producto_id = int(str(datos.get('producto') or '').strip())
    except ValueError:
        producto_id = None
    producto = Product.objects.filter(pk=producto_id, inventoried=True).first() if producto_id else None
    if producto is None:
        raise ErrorKardex('producto', estado=404)
    fecha, valida = fecha_de(datos.get('fecha'))
    if not valida:
        raise ErrorKardex('fecha', errores={'fecha': MENSAJES['fecha']})
    cantidad = _cantidad(datos.get('cantidad'))
    costo = _costo(datos.get('costo_unitario'))
    if tipo in CON_COSTO and costo is None:
        raise ErrorKardex('costo', errores={'costo_unitario': MENSAJES['costo']})
    if tipo == 'salida' and costo is not None:
        raise ErrorKardex('costo_salida', errores={'costo_unitario': MENSAJES['costo_salida']})
    documento = ' '.join(str(datos.get('documento') or '').split())
    if not documento or len(documento) > DOCUMENTO_MAX:
        errores['documento'] = MENSAJES['documento']
        raise ErrorKardex('documento', errores=errores)
    nota = str(datos.get('nota') or '').strip()
    if len(nota) > NOTA_MAX:
        raise ErrorKardex('nota_larga', errores={'nota': MENSAJES['nota_larga']})
    return {'producto': producto, 'tipo': tipo, 'fecha': fecha, 'cantidad': cantidad, 'costo_unitario': costo,
            'documento': documento, 'nota': nota}


def _igual(m, d):
    return (m.producto_id, m.tipo, m.fecha, m.cantidad, m.costo_unitario, m.documento, m.nota) == (
        d['producto'].pk, d['tipo'], d['fecha'], d['cantidad'], d['costo_unitario'], d['documento'], d['nota'])


def _repetido(existente, datos):
    if _igual(existente, datos):
        return existente, True
    raise ErrorKardex('clave_usada', estado=409, movimiento=existente)


def registrar(request, datos):
    """Registra un movimiento manual. Devuelve (movimiento, repetido)."""
    if REGISTRAR not in codigos(request) or VER not in codigos(request):
        raise ErrorKardex('sin_permiso', estado=403)
    clave = str(datos.get('clave') or '').strip()
    if not CLAVE.match(clave):
        raise ErrorKardex('clave')
    limpios = _validar(datos)
    existente = MovimientoManual.objects.filter(clave=clave).select_related('producto').first()
    if existente is not None:
        return _repetido(existente, limpios)
    movimiento = MovimientoManual(company=request.company, clave=clave, creado_por=request.user, **limpios)
    try:
        with transaction.atomic():
            movimiento.save()
    except IntegrityError:
        existente = MovimientoManual.objects.filter(clave=clave).select_related('producto').first()
        if existente is None:
            raise
        return _repetido(existente, limpios)
    audit(request, 'kardex_movimiento', company=request.company, movimiento=movimiento.pk, producto=movimiento.producto_id,
          tipo=movimiento.tipo, cantidad=movimiento.cantidad)
    return movimiento, False


def anular(request, pk, motivo):
    if ANULAR not in codigos(request) or VER not in codigos(request):
        raise ErrorKardex('sin_permiso_anular', estado=403)
    motivo = ' '.join(str(motivo or '').split())
    if not motivo or len(motivo) > MOTIVO_MAX:
        raise ErrorKardex('motivo', errores={'motivo': MENSAJES['motivo']})
    with transaction.atomic():
        movimiento = MovimientoManual.objects.select_for_update(of=('self',)).filter(pk=pk).first()
        if movimiento is None:
            raise ErrorKardex('movimiento', estado=404)
        if movimiento.anulado_en is not None:
            raise ErrorKardex('ya_anulado', estado=409, movimiento=movimiento)
        movimiento.anulado_en, movimiento.anulado_por, movimiento.motivo_anulacion = timezone.now(), request.user, motivo
        movimiento.save(update_fields=['anulado_en', 'anulado_por', 'motivo_anulacion'])
    audit(request, 'kardex_movimiento_anulado', company=request.company, movimiento=movimiento.pk, motivo=motivo)
    return movimiento


def registrar_ajuste(producto, anterior, nuevo, usuario, origen='ajuste'):
    """Deja constancia de un cambio de stock hecho a mano (pantalla de ajuste o importación desde Excel)."""
    if anterior != nuevo:
        AjusteInventario.objects.create(company_id=producto.company_id, producto=producto, anterior=anterior, nuevo=nuevo, origen=origen,
                                        creado_por=usuario if getattr(usuario, 'is_authenticated', False) else None)


def ajustar_stock(producto_id, nuevo, usuario):
    """Pantalla «Ajuste de stock»: fija el stock con la fila bloqueada y deja registrado el cambio para el kardex. Dos
    ajustes simultáneos del mismo producto quedan encadenados (el segundo parte del stock que dejó el primero)."""
    from core.pos.models import Product
    with transaction.atomic():
        producto = Product.objects.select_for_update().get(pk=producto_id)
        anterior = producto.stock
        producto.stock = nuevo
        producto.save()
        registrar_ajuste(producto, anterior, nuevo, usuario)
    return producto
