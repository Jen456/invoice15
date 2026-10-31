"""Reglas del respaldo del cobro (ver models.py). Todo se valida en el servidor; el navegador no decide autor, empresa,
fecha, estado ni saldo.

Relación con el saldo de la factura:
- Factura a crédito: registrar(...) crea el abono con cxc.registrar_cobro (el saldo baja en ese momento, como en «Cuentas
  por cobrar») y el respaldo ligado a ese abono. La revisión del respaldo (revisado / rechazado) no mueve el saldo: si un
  cobro resultó falso, quien tiene el permiso de eliminar cobros lo elimina (cxc.eliminar_cobro) y el saldo vuelve; el
  respaldo queda con su historial («cobro eliminado»). Un respaldo pendiente no retiene ni condiciona el saldo.
- Factura al contado: no hay cuenta por cobrar; el respaldo documenta el cobro de la factura (importe = total salvo que
  se indique otro) y tampoco cambia nada del comprobante.
"""
import hashlib
import uuid
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.cobros.models import RespaldoCobro, RespaldoCobroCambio
from core.pos import cxc
from core.pos.choices import MEDIOS_DE_PAGO
from core.security.session import get_group
from core.tenancy.models import audit

MB = 1024 * 1024
MAX_BYTES = 5 * MB
MAX_NOTA = 500
MAX_REFERENCIA = 100
# Extensión → (tipo guardado, tipo MIME al servir, cabeceras válidas del contenido)
TIPOS = {
    '.pdf': ('pdf', 'application/pdf', (b'%PDF-',)),
    '.jpg': ('jpg', 'image/jpeg', (b'\xff\xd8\xff',)),
    '.jpeg': ('jpg', 'image/jpeg', (b'\xff\xd8\xff',)),
    '.png': ('png', 'image/png', (b'\x89PNG\r\n\x1a\n',)),
}
MIME = {'pdf': 'application/pdf', 'jpg': 'image/jpeg', 'png': 'image/png'}
PERMISO_VER, PERMISO_REGISTRAR, PERMISO_EDITAR, PERMISO_REVISAR = (
    'view_respaldocobro', 'add_respaldocobro', 'change_respaldocobro', 'change_revision_respaldocobro')
ESTADOS_REVISION = ('pendiente', 'revisado', 'rechazado')

# Mensajes exactos (documentados en HANDOFF para el frontend).
MENSAJES = {
    'sin_permiso': 'Tu perfil no puede registrar respaldos de cobro.',
    'sin_permiso_editar': 'Solo quien registró el respaldo (mientras está pendiente) o un rol con permiso de cambio puede modificarlo.',
    'sin_permiso_revisar': 'Tu perfil no puede revisar respaldos de cobro.',
    'respaldo_requerido': 'Adjunta el comprobante del cobro o escribe una nota interna (o ambos).',
    'clave': 'Falta la clave del envío: vuelve a abrir el formulario.',
    'importe': 'Escribe el importe cobrado, mayor que cero y con hasta dos decimales.',
    'medio': 'Elige el medio de cobro.',
    'nota_larga': f'La nota admite hasta {MAX_NOTA} caracteres.',
    'referencia_larga': f'La referencia admite hasta {MAX_REFERENCIA} caracteres.',
    'referencia_tarjeta': 'No escribas el número completo de la tarjeta: usa el número de voucher o de autorización.',
    'archivo_grande': f'El archivo supera {MAX_BYTES // MB} MB.',
    'archivo_vacio': 'El archivo está vacío.',
    'archivo_tipo': 'Adjunta un PDF, JPG o PNG.',
    'archivo_contenido': 'El contenido del archivo no corresponde a un PDF, JPG o PNG válido.',
    'credito_sin_abono': 'Una factura a crédito se respalda al registrar cada cobro, no al emitirla.',
    'estado': 'Elige una revisión válida: pendiente, revisado o rechazado.',
    'motivo_rechazo': 'Escribe el motivo del rechazo.',
    'nada_que_cambiar': 'No hay cambios que guardar.',
    'factura_anulada': 'Esta factura está anulada en el SRI: no se registran cobros.',
}


class ErrorCobro(Exception):
    """Mensaje para el usuario (texto de MENSAJES[codigo])."""

    def __init__(self, codigo, **datos):
        super().__init__(MENSAJES[codigo].format(**datos))
        self.codigo = codigo


class _Repetido(Exception):
    """Ya existe un respaldo con esa clave (envío duplicado): deshace la transacción y devuelve el existente."""


# ---------------------------------------------------------------- permisos (rol de la membresía en la empresa activa)

def _tiene(request, codigo):
    grupo = get_group(request)
    return grupo is not None and grupo.permissions.filter(codename=codigo).exists()


def puede_ver(request):
    return _tiene(request, PERMISO_VER)


def puede_registrar(request):
    return _tiene(request, PERMISO_REGISTRAR)


def puede_revisar(request):
    return _tiene(request, PERMISO_REVISAR)


def puede_editar(request, respaldo):
    """Quien lo registró puede corregirlo mientras está pendiente; con el permiso de cambio, cualquiera; un respaldo
    revisado lo cambia solo quien revisa (y vuelve a pendiente)."""
    if respaldo.estado == 'revisado':
        return puede_revisar(request)
    if _tiene(request, PERMISO_EDITAR):
        return True
    return puede_registrar(request) and respaldo.registrado_por_id == request.user.pk and respaldo.estado == 'pendiente'


def capacidades(request, respaldo=None):
    datos = {'puede_ver': puede_ver(request), 'puede_registrar': puede_registrar(request), 'puede_revisar': puede_revisar(request),
             'puede_eliminar_cobros': cxc.puede_eliminar_cobros(request)}
    if respaldo is not None:
        datos['puede_editar'] = puede_editar(request, respaldo)
    return datos


# ---------------------------------------------------------------- archivo

def validar_archivo(archivo):
    """(tipo, sha256) de un archivo subido válido: extensión, tamaño, cabecera y, en imágenes, que Pillow lo abra.
    ErrorCobro con el código del problema."""
    if archivo.size > MAX_BYTES:
        raise ErrorCobro('archivo_grande')
    if archivo.size == 0:
        raise ErrorCobro('archivo_vacio')
    nombre = (archivo.name or '').lower()
    extension = next((e for e in TIPOS if nombre.endswith(e)), None)
    if extension is None:
        raise ErrorCobro('archivo_tipo')
    tipo, _, cabeceras = TIPOS[extension]
    archivo.seek(0)
    cabecera = archivo.read(16)
    archivo.seek(0)
    if not any(cabecera.startswith(c) for c in cabeceras):
        raise ErrorCobro('archivo_contenido')
    if tipo in ('jpg', 'png'):
        from PIL import Image, UnidentifiedImageError
        try:
            with Image.open(archivo) as imagen:
                formato = imagen.format
                imagen.verify()
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
            raise ErrorCobro('archivo_contenido')
        if (formato or '').upper() != {'jpg': 'JPEG', 'png': 'PNG'}[tipo]:
            raise ErrorCobro('archivo_contenido')
        archivo.seek(0)
    resumen = hashlib.sha256()
    for trozo in archivo.chunks():
        resumen.update(trozo)
    archivo.seek(0)
    return tipo, resumen.hexdigest()


def _nombre_seguro(nombre):
    nombre = (nombre or '').replace('\\', '/').rsplit('/', 1)[-1]
    return ' '.join(nombre.split())[:150]


def _guardar_archivo(respaldo, archivo, tipo, sha256):
    respaldo.archivo_nombre, respaldo.archivo_tipo, respaldo.archivo_bytes, respaldo.archivo_sha256 = (
        _nombre_seguro(archivo.name), tipo, archivo.size, sha256)
    respaldo.archivo.save(f'respaldo.{tipo}', archivo, save=False)


# ---------------------------------------------------------------- datos del cobro

def _nota(texto):
    texto = ' '.join((texto or '').split())
    if len(texto) > MAX_NOTA:
        raise ErrorCobro('nota_larga')
    return texto


def _referencia(texto):
    texto = ' '.join((texto or '').split())
    if len(texto) > MAX_REFERENCIA:
        raise ErrorCobro('referencia_larga')
    digitos = ''.join(c for c in texto if c.isdigit())
    if len(digitos) >= 13 and len(digitos) <= 19 and digitos == ''.join(c for c in texto if c.isalnum()):
        raise ErrorCobro('referencia_tarjeta')   # 13–19 dígitos seguidos: parece un número de tarjeta
    return texto


def _importe(valor, por_defecto=None):
    if valor in (None, '') and por_defecto is not None:
        return cxc.redondear(por_defecto)
    try:
        importe = Decimal(str(valor).strip().replace(',', '.'))
    except (InvalidOperation, ValueError, AttributeError):
        raise ErrorCobro('importe')
    if not importe.is_finite() or importe <= 0 or importe != importe.quantize(Decimal('0.01')):
        raise ErrorCobro('importe')
    return cxc.redondear(importe)


def _medio(valor):
    if valor not in dict(MEDIOS_DE_PAGO):
        raise ErrorCobro('medio')
    return valor


def _clave(valor):
    valor = (valor or '').strip()
    if not 8 <= len(valor) <= 40 or not all(c.isalnum() or c in '-_' for c in valor):
        raise ErrorCobro('clave')
    return valor


def _cambio(respaldo, usuario, accion, **detalle):
    RespaldoCobroCambio.objects.create(respaldo=respaldo, usuario=usuario if usuario and usuario.is_authenticated else None,
                                       accion=accion, detalle=detalle)


# ---------------------------------------------------------------- registrar

def registrar(request, venta, *, clave, medio, importe=None, referencia='', nota='', archivo=None, fecha=None):
    """Cobro con respaldo sobre `venta` (de la empresa activa).

    Factura a crédito (con cuenta por cobrar): crea el abono (cxc.registrar_cobro: valor, fecha, medio, referencia y
    validaciones de saldo) y su respaldo. Al contado: respaldo del cobro de la factura (importe = total si no se indica).
    Exige archivo o nota. Devuelve (respaldo, repetido): con una `clave` ya registrada no crea nada y devuelve el existente.
    """
    if not puede_registrar(request):
        raise ErrorCobro('sin_permiso')
    clave = _clave(clave)
    nota, referencia = _nota(nota), _referencia(referencia)
    if not nota and archivo is None:
        raise ErrorCobro('respaldo_requerido')
    tipo = sha256 = None
    if archivo is not None:
        tipo, sha256 = validar_archivo(archivo)
    existente = RespaldoCobro.objects.filter(clave=clave).first()
    if existente is not None:
        return existente, True
    usuario, company = request.user, request.company
    try:
        with transaction.atomic():
            from core.pos.models import Sale
            venta = Sale.objects.select_for_update(of=('self',)).get(pk=venta.pk)   # orden: venta → CxC → abono
            if venta.anulado_sri_fecha is not None:
                raise ErrorCobro('factura_anulada')
            cuenta = cxc.cxc_de_factura(venta, bloquear=True)
            if cuenta is not None:
                abono = cxc.registrar_cobro(company, usuario, cuenta.pk, fecha or timezone.localdate(), importe, medio, referencia,
                                            nota or 'Cobro con respaldo')
                origen, importe = 'abono', abono.valor
            else:
                abono, origen, importe, medio = None, 'contado', _importe(importe, venta.total), _medio(medio)
            respaldo = RespaldoCobro(company=company, sale=venta, abono=abono, origen=origen, clave=clave, importe=importe,
                                     medio=medio, referencia=referencia, nota=nota, registrado_por=usuario)
            if archivo is not None:
                _guardar_archivo(respaldo, archivo, tipo, sha256)
            try:
                with transaction.atomic():
                    respaldo.save()
            except IntegrityError:
                raise _Repetido
            _cambio(respaldo, usuario, 'registro', importe=str(importe), medio=medio, referencia=referencia, nota=bool(nota),
                    archivo=respaldo.archivo_nombre, abono=abono.pk if abono else None)
    except _Repetido:
        return RespaldoCobro.objects.get(clave=clave), True
    audit(request, 'cobro_respaldo_registro', company=company, factura=venta.voucher_number_full, respaldo=respaldo.pk,
          abono=abono.pk if abono else None, origen=origen, importe=str(importe), medio=medio, archivo=bool(archivo), nota=bool(nota))
    return respaldo, False


def registrar_al_emitir(request, venta, medio, referencia='', nota='', archivo=None):
    """Respaldo del cobro al contado dentro de la transacción de la venta (SaleCreateView): sin abono, importe = total.
    Si falla, la venta entera se deshace: nada sale al SRI."""
    nota, referencia = _nota(nota), _referencia(referencia)
    if not nota and archivo is None:
        raise ErrorCobro('respaldo_requerido')
    tipo, sha256 = validar_archivo(archivo) if archivo is not None else (None, None)
    respaldo = RespaldoCobro(company=request.company, sale=venta, abono=None, origen='contado', clave=f'venta-{venta.pk}',
                             importe=cxc.redondear(venta.total), medio=_medio(medio), referencia=referencia, nota=nota,
                             registrado_por=request.user)
    if archivo is not None:
        _guardar_archivo(respaldo, archivo, tipo, sha256)
    respaldo.save()
    _cambio(respaldo, request.user, 'registro', importe=str(respaldo.importe), medio=medio, referencia=referencia, nota=bool(nota),
            archivo=respaldo.archivo_nombre, abono=None)
    audit(request, 'cobro_respaldo_registro', company=request.company, factura=venta.voucher_number_full, respaldo=respaldo.pk,
          abono=None, origen='contado', importe=str(respaldo.importe), medio=medio, archivo=bool(archivo), nota=bool(nota))
    return respaldo


# ---------------------------------------------------------------- editar y revisar

def editar(request, respaldo, *, nota=None, referencia=None, archivo=None):
    """Corrige nota, referencia o archivo con historial (lo anterior queda en RespaldoCobroCambio; el archivo anterior no se
    borra). Un respaldo revisado vuelve a pendiente al cambiarlo."""
    if not puede_editar(request, respaldo):
        raise ErrorCobro('sin_permiso_editar')
    cambios = []
    if nota is not None:
        nota = _nota(nota)
        if nota != respaldo.nota:
            cambios.append(('nota', {'antes': respaldo.nota, 'despues': nota}))
    if referencia is not None:
        referencia = _referencia(referencia)
        if referencia != respaldo.referencia:
            cambios.append(('referencia', {'antes': respaldo.referencia, 'despues': referencia}))
    tipo = sha256 = None
    if archivo is not None:
        tipo, sha256 = validar_archivo(archivo)
        cambios.append(('archivo', {'antes': respaldo.archivo.name if respaldo.archivo else '', 'antes_nombre': respaldo.archivo_nombre,
                                    'despues_nombre': _nombre_seguro(archivo.name)}))
    if not cambios:
        raise ErrorCobro('nada_que_cambiar')
    nota_final = nota if nota is not None else respaldo.nota
    archivo_final = archivo is not None or bool(respaldo.archivo)
    if not nota_final and not archivo_final:
        raise ErrorCobro('respaldo_requerido')
    with transaction.atomic():
        respaldo = RespaldoCobro.objects.select_for_update(of=('self',)).get(pk=respaldo.pk)
        if nota is not None:
            respaldo.nota = nota
        if referencia is not None:
            respaldo.referencia = referencia
        if archivo is not None:
            _guardar_archivo(respaldo, archivo, tipo, sha256)
        volvio = respaldo.estado == 'revisado'
        if volvio:
            respaldo.estado, respaldo.revisado_por, respaldo.revisado_en, respaldo.motivo_revision = 'pendiente', None, None, ''
        respaldo.save()
        for accion, detalle in cambios:
            _cambio(respaldo, request.user, accion, **detalle, vuelve_a_pendiente=volvio)
    audit(request, 'cobro_respaldo_cambio', company=request.company, respaldo=respaldo.pk, factura=respaldo.sale.voucher_number_full,
          cambios=[c for c, _ in cambios], vuelve_a_pendiente=volvio)
    return respaldo


def revisar(request, respaldo, estado, motivo=''):
    """Marca la revisión (pendiente / revisado / rechazado) con responsable, fecha y motivo. No toca abonos ni saldos."""
    if not puede_revisar(request):
        raise ErrorCobro('sin_permiso_revisar')
    if estado not in ESTADOS_REVISION:
        raise ErrorCobro('estado')
    motivo = ' '.join((motivo or '').split())[:300]
    if estado == 'rechazado' and not motivo:
        raise ErrorCobro('motivo_rechazo')
    with transaction.atomic():
        respaldo = RespaldoCobro.objects.select_for_update(of=('self',)).get(pk=respaldo.pk)
        anterior = (respaldo.estado, respaldo.motivo_revision)
        if anterior == (estado, motivo):
            raise ErrorCobro('nada_que_cambiar')
        if estado == 'pendiente':
            respaldo.revisado_por, respaldo.revisado_en, respaldo.motivo_revision = None, None, ''
        else:
            respaldo.revisado_por, respaldo.revisado_en, respaldo.motivo_revision = request.user, timezone.now(), motivo
        respaldo.estado = estado
        respaldo.save(update_fields=['estado', 'revisado_por', 'revisado_en', 'motivo_revision', 'actualizado_en'])
        _cambio(respaldo, request.user, 'revision', antes=anterior[0], despues=estado, motivo=motivo)
    audit(request, 'cobro_respaldo_revision', company=request.company, respaldo=respaldo.pk, factura=respaldo.sale.voucher_number_full,
          antes=anterior[0], despues=estado, motivo=motivo)
    return respaldo


def al_eliminar_cobro(abono, request=None):
    """Lo llama cxc.eliminar_cobro antes de borrar un cobro: sus respaldos quedan sin abono (SET_NULL) y con historial."""
    usuario = getattr(request, 'user', None) if request is not None else None
    for respaldo in RespaldoCobro.objects.filter(abono=abono):
        _cambio(respaldo, usuario, 'cobro_eliminado', abono=abono.pk, valor=str(abono.valor), fecha=abono.date_joined.isoformat())


# ---------------------------------------------------------------- consultas (JSON)

def _usuario(u):
    return None if u is None else {'id': u.pk, 'username': u.username, 'nombre': u.names}


def respaldo_json(respaldo, request=None, historial=False):
    item = {
        'id': respaldo.pk, 'factura_id': respaldo.sale_id, 'abono_id': respaldo.abono_id, 'origen': respaldo.origen,
        'importe': f'{respaldo.importe:.2f}', 'medio': {'id': respaldo.medio, 'nombre': respaldo.get_medio_display()},
        'referencia': respaldo.referencia, 'nota': respaldo.nota,
        'archivo': ({'nombre': respaldo.archivo_nombre, 'tipo': respaldo.archivo_tipo, 'bytes': respaldo.archivo_bytes,
                     'sha256': respaldo.archivo_sha256, 'url': f'/cobros/respaldo/{respaldo.pk}/archivo/'} if respaldo.archivo else None),
        'registrado_por': _usuario(respaldo.registrado_por), 'registrado_en': respaldo.registrado_en.isoformat(),
        'actualizado_en': respaldo.actualizado_en.isoformat() if respaldo.actualizado_en else None,
        'estado': {'id': respaldo.estado, 'nombre': respaldo.get_estado_display()},
        'revisado_por': _usuario(respaldo.revisado_por),
        'revisado_en': respaldo.revisado_en.isoformat() if respaldo.revisado_en else None,
        'motivo_revision': respaldo.motivo_revision,
    }
    if request is not None:
        item['puede_editar'] = puede_editar(request, respaldo)
    if historial:
        item['historial'] = [{'fecha': c.fecha.isoformat(), 'usuario': _usuario(c.usuario), 'accion': c.accion,
                              'accion_nombre': c.get_accion_display(), 'detalle': c.detalle}
                             for c in respaldo.cambios.select_related('usuario')]
    return item


def factura_json(request, venta):
    """Cobros de una factura: condición, medio, saldo (solo a crédito), abonos con su respaldo, respaldos y capacidades."""
    cuenta = cxc.cxc_de_factura(venta)
    respaldos = list(RespaldoCobro.objects.filter(sale=venta).select_related('registrado_por', 'revisado_por').order_by('id'))
    por_abono = {r.abono_id: r for r in respaldos if r.abono_id}
    abonos = []
    if cuenta is not None:
        for a in cxc.abonos(cuenta.pk):
            r = por_abono.get(a.pk)
            abonos.append({**a.toJSON(), 'respaldo': respaldo_json(r, request) if r else None})
    return {
        'factura': {'id': venta.pk, 'numero': venta.voucher_number_full, 'total': f'{venta.total:.2f}',
                    'condicion': {'id': venta.payment_type, 'nombre': venta.get_payment_type_display()},
                    'medio_cobro': ({'id': venta.medio_cobro, 'nombre': venta.get_medio_cobro_display()} if venta.medio_cobro else None),
                    'efectivo': f'{venta.cash:.2f}', 'cambio': f'{venta.change:.2f}',
                    'anulada_sri': venta.anulado_sri_fecha is not None},
        'cuenta_por_cobrar': ({'id': cuenta.pk, 'deuda': f'{cuenta.debt:.2f}', 'saldo': f'{cuenta.saldo_actual():.2f}',
                               'estado': cuenta.estado()} if cuenta is not None else None),
        'abonos': abonos,
        'respaldos': [respaldo_json(r, request) for r in respaldos],
        'capacidades': capacidades(request),
        'medios': [{'id': m, 'nombre': n} for m, n in MEDIOS_DE_PAGO],
        'clave_sugerida': uuid.uuid4().hex,
    }


# ---------------------------------------------------------------- efectivo y cambio (venta al contado en efectivo)

def efectivo_recibido(valor):
    """«Efectivo recibido» del formulario de venta, solo cuando el medio es efectivo (Decimal, 2 decimales)."""
    try:
        efectivo = Decimal(str(valor if valor not in (None, '') else '0').strip().replace(',', '.'))
    except (InvalidOperation, ValueError):
        raise ValueError('Escribe el efectivo recibido.')
    if not efectivo.is_finite() or efectivo < 0:
        raise ValueError('Escribe el efectivo recibido.')
    return cxc.redondear(efectivo)


def cambio(efectivo, total):
    """Cambio = efectivo − total, calculado en el servidor; el efectivo no puede ser menor que el total."""
    efectivo, total = cxc.redondear(efectivo), cxc.redondear(total)
    if efectivo < total:
        raise ValueError(f'El efectivo recibido ({efectivo:.2f}) es menor que el total a pagar ({total:.2f}).')
    return cxc.redondear(efectivo - total)
