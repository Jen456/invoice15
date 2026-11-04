"""Recibos y notas guardados ahora para completar después (captura rápida de gastos).

Reglas (contrato en HANDOFF, «captura rápida de gastos»):
- Guardar exige un archivo (PDF, JPG, PNG o WEBP, 8 MB, contenido comprobado) o una nota (≤ 500), o ambos. No pide importe,
  categoría, proveedor ni medio de pago, y no crea gasto, compra, pago, cuenta por pagar, asiento ni crédito tributario.
  Empresa, autor y fecha salen del servidor; el archivo queda en la carpeta privada de la empresa.
- `clave` (la genera el navegador por formulario) hace idempotente el guardado: un doble clic o un reintento con la misma
  clave y el mismo contenido devuelven la captura existente; con otro contenido, error `clave_usada` (no se pisa nada).
- Completar como gasto (ExpensesForm, sus mismas validaciones) o como compra (pantalla de Compras), o vincular a una compra,
  un gasto o un pago existentes: en una transacción se bloquea la captura y, si ya no está pendiente, no se crea nada
  (`captura_usada`, 409). El adjunto que nace reutiliza el archivo físico de la captura (no se copia ni se sube otra vez).
- Si el archivo ya estaba adjunto a ese documento (misma huella), no se duplica: la respuesta lo indica (`ya_adjunto`).
- Borrar el documento después devuelve la captura a pendiente (servicios.al_eliminar_documento → liberar).
- Todo queda auditado (captura_registro, captura_completada, captura_vinculada, captura_descartada, captura_nota,
  captura_liberada).

Permisos (roles.py): ver `view_captura`; guardar `add_captura`; completar, vincular y descartar `change_captura`. Quien no
tiene `view_adjunto` (Vendedor) solo ve y gestiona las capturas que guardó. Vincular exige además subir adjuntos en el
documento (servicios.permisos). Completar como gasto exige el plan pagado vigente (regla de /pos/expenses/); como compra,
`add_purchase`. Guardar no exige plan (como Compras).
"""
import uuid
from datetime import datetime

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.forms import ModelForm
from django.utils import timezone

from core.adjuntos import archivos, servicios as sv
from core.adjuntos.documentos import DOCUMENTOS, describir, obtener
from core.adjuntos.models import CLASES, FORMATOS, MOTIVO_MAX, NOTA_MAX, Adjunto, Captura
from core.suscripciones import reglas
from core.suscripciones.servicios import estado_de_peticion
from core.tenancy.models import audit

VER, REGISTRAR, GESTIONAR = 'view_captura', 'add_captura', 'change_captura'
ESTADOS_FILTRO = ('pendiente', 'completada', 'vinculada', 'descartada', 'todas')
MAX_LISTA = 300
CLASE_RECIBO = 'recibo'

# Textos exactos (documentados en HANDOFF para el frontend).
MENSAJES = {
    'sin_permiso': 'Tu perfil no puede guardar recibos ni notas.',
    'sin_permiso_ver': 'Tu perfil no puede ver los recibos por completar.',
    'sin_permiso_gestionar': 'Tu perfil no puede completar, vincular ni descartar recibos.',
    'respaldo_requerido': sv.RESPALDO_REQUERIDO,
    'clave': 'Falta la clave del envío: vuelve a abrir el formulario.',
    'clave_usada': 'Esta clave ya se usó para guardar otro recibo o nota: vuelve a abrir el formulario e inténtalo de nuevo.',
    'nota_larga': f'La nota admite hasta {NOTA_MAX} caracteres.',
    'motivo_largo': f'El motivo admite hasta {MOTIVO_MAX} caracteres.',
    'captura': 'El recibo no existe o es de otra empresa.',
    'tipo': 'Elige si es una compra, un gasto o un pago a proveedor.',
    'documento': 'El documento no existe o es de otra empresa.',
    'datos': 'Revisa los datos del gasto.',
    'valor': 'Escribe el valor del gasto, mayor que cero.',
    'sin_permiso_compra': 'Tu perfil no puede registrar compras.',
    'nada_que_cambiar': 'No hay cambios que guardar.',
}


class ErrorCaptura(sv.ErrorAdjunto):
    """Error para la persona (texto de MENSAJES salvo `mensaje`), con la captura afectada si la hay."""

    def __init__(self, codigo, mensaje=None, estado=400, captura=None, errores=None):
        super().__init__(mensaje or MENSAJES[codigo], codigo, estado)
        self.captura, self.errores = captura, errores


# ---------------------------------------------------------------- permisos

def _codigos(request):
    if not hasattr(request, '_fpa_codigos_capturas'):
        request._fpa_codigos_capturas = sv._codigos(request)
    return request._fpa_codigos_capturas


def ve_todas(request):
    """Con `view_adjunto` (Propietario, Administrador, Contador, Consulta) se ven todas las capturas de la empresa; sin él
    (Vendedor), solo las propias."""
    return 'view_adjunto' in _codigos(request)


def _bloqueo_gasto(request):
    """Mensaje si el plan no permite registrar gastos (gratuito o vencido), o None."""
    if not reglas.requiere_plan(DOCUMENTOS['gasto'].modulo):
        return None
    estado = estado_de_peticion(request)
    if estado is None or not (estado.gratuito or estado.vencido):
        return None
    from core.suscripciones.middleware import mensaje_de_bloqueo
    return mensaje_de_bloqueo(estado)


def capacidades(request, captura=None):
    """Qué puede hacer el rol activo (con `captura`, ya cruzado con su estado y su autor)."""
    codigos = _codigos(request)
    gestionar = GESTIONAR in codigos
    bloqueo_gasto = _bloqueo_gasto(request)
    permisos = {t: sv.permisos(request, t) for t in DOCUMENTOS}
    datos = {
        'ver': VER in codigos, 'ver_todas': ve_todas(request), 'registrar': REGISTRAR in codigos, 'gestionar': gestionar,
        'completar_gasto': gestionar and bloqueo_gasto is None,
        'registrar_compra': gestionar and 'add_purchase' in codigos and permisos['compra']['bloqueo'] is None,
        'vincular': {t: gestionar and permisos[t]['subir'] for t in DOCUMENTOS},
        'descartar': gestionar, 'editar_nota': gestionar or REGISTRAR in codigos,
        'bloqueos': {'gasto': bloqueo_gasto, 'compra': permisos['compra']['bloqueo'], 'pago': permisos['pago']['bloqueo']},
    }
    if captura is not None:
        pendiente = captura.estado == 'pendiente'
        propia = captura.creado_por_id == getattr(request.user, 'pk', None)
        for clave in ('completar_gasto', 'registrar_compra', 'descartar'):
            datos[clave] = datos[clave] and pendiente
        datos['vincular'] = {t: v and pendiente for t, v in datos['vincular'].items()}
        datos['editar_nota'] = pendiente and (gestionar or (REGISTRAR in codigos and propia))
    return datos


def _exigir(request, codigo, error):
    if codigo not in _codigos(request):
        raise ErrorCaptura(error, estado=403)


# ---------------------------------------------------------------- validaciones

def _nota(valor):
    return sv.texto(valor, NOTA_MAX, 'nota_larga', MENSAJES['nota_larga'])


def _clave(valor):
    valor = (valor or '').strip()
    if not 8 <= len(valor) <= 40 or not all(c.isalnum() or c in '-_' for c in valor):
        raise ErrorCaptura('clave')
    return valor


def clave_sugerida():
    return uuid.uuid4().hex


# ---------------------------------------------------------------- consultas

def _visibles(request):
    consulta = Captura.objects.select_related('creado_por', 'completado_por')
    if request is not None and not ve_todas(request):
        consulta = consulta.filter(creado_por_id=request.user.pk)
    return consulta


def listar(request, estado='pendiente'):
    consulta = _visibles(request)
    if estado in ESTADOS_FILTRO and estado != 'todas':
        consulta = consulta.filter(estado=estado)
    elif estado not in ESTADOS_FILTRO:
        consulta = consulta.filter(estado='pendiente')
    return list(consulta.order_by('-creado_en', '-id')[:MAX_LISTA])


def obtener_visible(request, pk):
    captura = _visibles(request).filter(pk=pk).first()
    if captura is None:
        raise ErrorCaptura('captura', estado=404)
    return captura


def contar_pendientes(request=None):
    if request is not None and VER not in _codigos(request):
        return 0
    return _visibles(request).filter(estado='pendiente').count()


def _usuario(u):
    return u.username if u is not None else ''


def _local(momento):
    return timezone.localtime(momento).strftime('%Y-%m-%d %H:%M') if momento else ''


def _documento(captura):
    if not captura.documento_tipo or captura.documento_id is None:
        return None
    tipo = captura.documento_tipo
    nombre = DOCUMENTOS[tipo].nombre if tipo in DOCUMENTOS else tipo
    documento = obtener(tipo, captura.documento_id) if tipo in DOCUMENTOS else None
    if documento is None:
        return {'tipo': tipo, 'tipo_nombre': nombre, 'id': captura.documento_id, 'titulo': '', 'existe': False, 'url_adjuntos': ''}
    return {'tipo': tipo, 'tipo_nombre': nombre, 'id': documento.pk, 'titulo': describir(tipo, documento)['titulo'], 'existe': True,
            'url_adjuntos': f'/adjuntos/api/{tipo}/{documento.pk}/'}


def _archivo(captura):
    if not captura.archivo:
        return None
    url = f'/adjuntos/capturas/{captura.pk}/archivo/'
    return {'nombre': captura.nombre, 'tipo_mime': captura.tipo_mime, 'extension': captura.extension, 'tamano': captura.tamano,
            'tamano_texto': sv._texto_tamano(captura.tamano), 'sha256': captura.sha256, 'url': url, 'url_descarga': url + '?descargar=1'}


def _mismo_archivo(captura, limite=5):
    """Otras capturas pendientes y adjuntos vigentes de la empresa con el mismo archivo (aviso, nunca bloqueo)."""
    if not captura.sha256:
        return []
    resultado = [{'tipo': 'captura', 'id': c.pk, 'titulo': f'Recibo C-{c.pk} ({c.get_estado_display().lower()})'}
                 for c in Captura.objects.filter(sha256=captura.sha256, estado='pendiente').exclude(pk=captura.pk).order_by('id')[:limite]]
    for adjunto in (Adjunto.objects.filter(sha256=captura.sha256, eliminado_en__isnull=True, documento_tipo__in=list(DOCUMENTOS))
                    .exclude(captura=captura).order_by('id')[:limite]):
        documento = obtener(adjunto.documento_tipo, adjunto.documento_id)
        if documento is not None:
            resultado.append({'tipo': adjunto.documento_tipo, 'id': adjunto.documento_id,
                              'titulo': describir(adjunto.documento_tipo, documento)['titulo']})
    return resultado[:limite]


def dict_captura(captura, request=None, detalle=False):
    datos = {
        'id': captura.pk, 'numero': f'C-{captura.pk}', 'clave': captura.clave,
        'estado': {'id': captura.estado, 'name': captura.get_estado_display()},
        'archivo': _archivo(captura), 'nota': captura.nota,
        'creado_por': _usuario(captura.creado_por), 'creado_en': _local(captura.creado_en),
        'fecha': timezone.localtime(captura.creado_en).date().isoformat(),
        'completado_por': _usuario(captura.completado_por), 'completado_en': _local(captura.completado_en),
        'motivo': captura.motivo, 'documento': _documento(captura),
        'adjuntos': [a.pk for a in captura.adjuntos.all()] if captura.pk else [],
    }
    if detalle:
        datos['mismo_archivo'] = _mismo_archivo(captura)
    if request is not None:
        datos['capacidades'] = capacidades(request, captura)
    return datos


def opciones_gasto():
    """Datos para el formulario de completar como gasto: categorías (tipos de gasto de la empresa) y medios de pago."""
    from core.pos.choices import MEDIOS_DE_PAGO
    from core.pos.models import TypeExpense
    return {'categorias': [{'id': t.pk, 'nombre': t.name} for t in TypeExpense.objects.order_by('name')],
            'medios': [{'id': m, 'nombre': n} for m, n in MEDIOS_DE_PAGO], 'hoy': timezone.localdate().isoformat()}


def sugerencias_gasto(captura):
    """Valores iniciales al completar: fecha del día en que se guardó y la nota como descripción (la persona los cambia)."""
    return {'date_joined': timezone.localtime(captura.creado_en).date().isoformat(), 'description': captura.nota[:500]}


def filas_del_mes(inicio, request=None):
    """Capturas pendientes guardadas en el mes (fecha local de guardado), como filas de la consulta mensual: mismas claves que
    las de documentos más `pendiente_completar: true` y `_captura` (objeto, para el ZIP)."""
    if request is not None and VER not in _codigos(request):
        return []
    fin = sv._siguiente_mes(inicio)
    desde = timezone.make_aware(datetime(inicio.year, inicio.month, 1))
    hasta = timezone.make_aware(datetime(fin.year, fin.month, 1))
    filas = []
    for captura in _visibles(request).filter(estado='pendiente', creado_en__gte=desde, creado_en__lt=hasta).order_by('creado_en', 'id'):
        archivo = _archivo(captura)
        detalle = (captura.nota or captura.nombre)[:60]
        respaldo = {
            'id': captura.pk, 'origen': 'adjuntos',
            'clase': {'id': CLASE_RECIBO, 'name': 'Recibo'} if archivo else {'id': 'nota', 'name': 'Nota'},
            'nombre': captura.nombre, 'tipo_mime': captura.tipo_mime, 'extension': captura.extension, 'tamano': captura.tamano,
            'tamano_texto': archivo['tamano_texto'] if archivo else '', 'sha256': captura.sha256, 'referencia': '', 'fecha': '',
            'importe': '', 'descripcion': captura.nota, 'subido_por': _usuario(captura.creado_por), 'subido_en': _local(captura.creado_en),
            'url': archivo['url'] if archivo else '', 'url_descarga': archivo['url_descarga'] if archivo else '',
            'nota': not archivo, 'revision': None, 'captura': captura.pk,
            'eliminado': False, 'eliminado_en': '', 'eliminado_por': '', 'eliminado_motivo': '',
        }
        filas.append({
            'tipo': 'captura', 'tipo_nombre': 'Recibo por completar', 'id': captura.pk, 'numero': f'C-{captura.pk}',
            'titulo': f'Recibo C-{captura.pk}', 'tercero': detalle, 'identificacion': '',
            'fecha': timezone.localtime(captura.creado_en).date().isoformat(), 'importe': '', 'medio_id': '', 'medio': 'Sin dato',
            'contado': False, 'requiere': False, 'falta': False, 'origen': 'adjuntos', 'url_cobros': '',
            'url_captura': f'/adjuntos/capturas/?captura={captura.pk}', 'con_nota': not archivo and bool(captura.nota),
            'pendientes_revision': 0, 'rechazados': 0, 'pendiente_completar': True, 'adjuntos': [respaldo], '_captura': captura,
        })
    return filas


def documentos_para_vincular(request, tipo, q='', limite=20):
    """Compras, gastos o pagos recientes de la empresa a los que el rol puede adjuntar, para elegir dónde vincular un recibo
    (busca por proveedor, RUC, número, referencia, descripción o número de gasto). Lista de dict_documento."""
    from django.db.models import Q

    from core.pos.models import Expenses, PaymentsDebtsPay, Purchase
    if tipo not in DOCUMENTOS:
        raise ErrorCaptura('tipo')
    permisos = sv.permisos(request, tipo)
    if not permisos['subir']:
        raise ErrorCaptura('permiso', permisos['bloqueo'] or 'Tu perfil no puede adjuntar respaldos a este documento.', 403)
    q = ' '.join((q or '').split())[:60]
    if tipo == 'compra':
        consulta = Purchase.objects.select_related('provider').exclude(tipo_comprobante__in=('04', '05'))
        if q:
            consulta = consulta.filter(Q(provider__name__icontains=q) | Q(provider__ruc__icontains=q) | Q(secuencial__icontains=q)
                                       | Q(number__icontains=q))
    elif tipo == 'gasto':
        consulta = Expenses.objects.select_related('type_expense')
        if q:
            filtro = Q(description__icontains=q) | Q(type_expense__name__icontains=q) | Q(referencia__icontains=q)
            if q.lstrip('#').isascii() and q.lstrip('#').isdigit():
                filtro |= Q(pk=int(q.lstrip('#')))
            consulta = consulta.filter(filtro)
    else:
        consulta = PaymentsDebtsPay.objects.select_related('debts_pay__purchase__provider')
        if q:
            consulta = consulta.filter(Q(debts_pay__purchase__provider__name__icontains=q) | Q(referencia__icontains=q)
                                       | Q(debts_pay__purchase__secuencial__icontains=q))
    return [sv.dict_documento(tipo, d) for d in consulta.order_by('-date_joined', '-pk')[:limite]]


def pendientes_para_vincular(request, limite=50):
    return [dict_captura(c) for c in _visibles(request).filter(estado='pendiente').order_by('-creado_en', '-id')[:limite]]


# ---------------------------------------------------------------- guardar

def _repetida(existente, sha256, nota):
    """Misma clave: el mismo envío (doble clic, reintento) devuelve la captura existente; otro contenido es un error."""
    if existente.sha256 == (sha256 or '') and existente.nota == nota:
        return existente, True
    raise ErrorCaptura('clave_usada', estado=409, captura=existente)


def registrar(request, *, clave, archivo=None, nota=''):
    """Guarda un recibo y/o una nota pendientes de completar. Devuelve (captura, repetida)."""
    _exigir(request, REGISTRAR, 'sin_permiso')
    clave, nota = _clave(clave), _nota(nota)
    if archivo is None and not nota:
        raise ErrorCaptura('respaldo_requerido')
    contenido = nombre = tipo_mime = sha256 = None
    if archivo is not None:
        if getattr(archivo, 'size', 0) > archivos.MAX_BYTES:
            raise ErrorCaptura('tamano', f'El archivo pesa más de {archivos.MAX_BYTES // archivos.MB} MB. Comprime el PDF o reduce la foto.')
        contenido = archivo.read()
        try:
            nombre, tipo_mime, sha256 = archivos.validar(getattr(archivo, 'name', ''), contenido)
        except archivos.ArchivoInvalido as e:
            raise ErrorCaptura('archivo', str(e))
    existente = Captura.objects.filter(clave=clave).first()
    if existente is not None:
        return _repetida(existente, sha256, nota)
    captura = Captura(company=request.company, clave=clave, nota=nota, creado_por=request.user)
    guardado = None
    try:
        with transaction.atomic():
            if contenido is not None:
                captura.nombre, captura.tipo_mime, captura.tamano, captura.sha256 = nombre, tipo_mime, len(contenido), sha256
                captura.archivo.save(f'recibo.{FORMATOS[tipo_mime]}', ContentFile(contenido), save=False)
                guardado = captura.archivo.name
            captura.save()
    except IntegrityError:
        if guardado:
            captura.archivo.storage.delete(guardado)
        existente = Captura.objects.filter(clave=clave).first()
        if existente is None:
            raise
        return _repetida(existente, sha256, nota)
    except Exception:
        if guardado:
            captura.archivo.storage.delete(guardado)
        raise
    audit(request, 'captura_registro', company=request.company, captura=captura.pk, archivo=bool(contenido), nota=bool(nota))
    return captura, False


# ---------------------------------------------------------------- transiciones (siempre con la captura bloqueada)

def _texto_usada(captura):
    fecha = timezone.localtime(captura.completado_en).strftime('%d/%m/%Y %H:%M') if captura.completado_en else ''
    quien = _usuario(captura.completado_por) or 'otra persona'
    if captura.estado == 'descartada':
        motivo = f' Motivo: {captura.motivo}' if captura.motivo else ''
        return f'Este recibo se descartó el {fecha} ({quien}): no se puede completar ni vincular.{motivo}'
    documento = _documento(captura)
    titulo = documento['titulo'] if documento and documento['titulo'] else 'otro documento'
    return f'Este recibo ya se registró como {titulo} ({quien}, {fecha}). No se creó otro registro.'


def bloquear(request, pk):
    """La captura visible para el usuario con su fila bloqueada hasta el final de la transacción; si ya no está pendiente,
    ErrorCaptura `captura_usada` (409) ANTES de crear o cambiar nada."""
    consulta = Captura.objects.select_for_update(of=('self',)).filter(pk=pk)
    if not ve_todas(request):
        consulta = consulta.filter(creado_por_id=request.user.pk)
    captura = consulta.first()
    if captura is None:
        raise ErrorCaptura('captura', estado=404)
    if captura.estado != 'pendiente':
        raise ErrorCaptura('captura_usada', _texto_usada(captura), 409, captura=captura)
    return captura


def _cerrar(captura, estado, usuario, tipo='', documento_id=None, motivo=''):
    captura.estado, captura.documento_tipo, captura.documento_id = estado, tipo, documento_id
    captura.completado_por = usuario if getattr(usuario, 'pk', None) else None
    captura.completado_en, captura.motivo = timezone.now(), motivo
    captura.save(update_fields=['estado', 'documento_tipo', 'documento_id', 'completado_por', 'completado_en', 'motivo'])


def adjuntar_desde_captura(captura, tipo, documento, *, clase='', referencia='', fecha=None, importe=None):
    """Adjunto del documento que nace de la captura, con el MISMO archivo físico (sin copiarlo ni escribir en disco) y la nota
    como descripción; si la captura es solo nota, una nota de respaldo. Autor y fecha: los de la captura. Si el archivo ya
    estaba adjunto al documento, no se duplica y se devuelve ese adjunto como `ya_adjunto` (la nota, si la hay, se añade).
    Dentro de la transacción de quien llama, con el documento bloqueado. Devuelve (creados, ya_adjunto)."""
    creados, ya_adjunto = [], None
    if captura.archivo:
        ya_adjunto = sv.listar(tipo, documento.pk).filter(sha256=captura.sha256).exclude(sha256='').first()
        if ya_adjunto is None:
            sv.comprobar_cupo(tipo, documento.pk)
            creados.append(Adjunto.objects.create(
                company=captura.company, documento_tipo=tipo, documento_id=documento.pk,
                clase=clase if clase in dict(CLASES) else CLASE_RECIBO, archivo=captura.archivo.name, nombre=captura.nombre,
                tipo_mime=captura.tipo_mime, tamano=captura.tamano, sha256=captura.sha256,
                referencia=' '.join((referencia or '').split())[:100], fecha=fecha, importe=importe, descripcion=captura.nota,
                captura=captura, subido_por=captura.creado_por, subido_en=captura.creado_en))
        elif captura.nota and not sv.listar(tipo, documento.pk).filter(archivo='', descripcion=captura.nota).exists():
            creados.append(sv.crear_nota(captura.company, None, tipo, documento.pk, captura.nota, captura=captura,
                                         subido_por=captura.creado_por, subido_en=captura.creado_en))
    elif not sv.listar(tipo, documento.pk).filter(archivo='', descripcion=captura.nota).exists():
        creados.append(sv.crear_nota(captura.company, None, tipo, documento.pk, captura.nota, captura=captura,
                                     subido_por=captura.creado_por, subido_en=captura.creado_en))
    return creados, ya_adjunto


def completar_gasto(request, pk, datos):
    """Registra el gasto con los datos que faltaban (mismas validaciones que «Nuevo gasto») y le deja como respaldo el recibo
    o la nota de la captura, sin volver a subirlo. Devuelve (captura, gasto, creados)."""
    from core.pos.forms import ExpensesForm
    _exigir(request, GESTIONAR, 'sin_permiso_gestionar')
    bloqueo = _bloqueo_gasto(request)
    if bloqueo:
        raise ErrorCaptura('plan', bloqueo, 403)
    form = ExpensesForm(datos)
    if not form.is_valid():
        if set(form.errors) == {'valor'} and form.has_error('valor', 'no_positivo'):   # código propio del contrato de la API
            raise ErrorCaptura('valor', estado=400, errores={'valor': [MENSAJES['valor']]})
        raise ErrorCaptura('datos', estado=400, errores={campo: [str(m) for m in mensajes] for campo, mensajes in form.errors.items()})
    if form.cleaned_data['valor'] is None or form.cleaned_data['valor'] <= 0:
        raise ErrorCaptura('valor', estado=400, errores={'valor': [MENSAJES['valor']]})
    with transaction.atomic():
        captura = bloquear(request, pk)
        gasto = ModelForm.save(form)       # INSERT del gasto (ExpensesForm.save atrapa errores: aquí deben propagarse)
        creados, _ = adjuntar_desde_captura(captura, 'gasto', gasto, referencia=gasto.referencia, fecha=gasto.date_joined,
                                            importe=gasto.valor)
        _cerrar(captura, 'completada', request.user, 'gasto', gasto.pk)
    audit(request, 'captura_completada', company=request.company, captura=captura.pk, tipo='gasto', documento=gasto.pk,
          adjuntos=[a.pk for a in creados])
    return captura, gasto, creados


def completar_compra(request, pk, crear):
    """Registra la compra con `crear()` (compras.crear_compra con los datos del formulario de Compras) en la misma transacción
    que bloquea la captura; el archivo de la captura queda como respaldo de la compra. Devuelve (captura, compra, creados)."""
    _exigir(request, GESTIONAR, 'sin_permiso_gestionar')
    if 'add_purchase' not in _codigos(request):
        raise ErrorCaptura('sin_permiso_compra', estado=403)
    with transaction.atomic():
        captura = bloquear(request, pk)
        compra = crear()
        creados, _ = adjuntar_desde_captura(captura, 'compra', compra)
        _cerrar(captura, 'completada', request.user, 'compra', compra.pk)
    audit(request, 'captura_completada', company=request.company, captura=captura.pk, tipo='compra', documento=compra.pk,
          adjuntos=[a.pk for a in creados])
    return captura, compra, creados


def vincular(request, pk, tipo, documento_id):
    """Deja la captura como respaldo de una compra, un gasto o un pago ya registrados. Devuelve (captura, documento, creados,
    ya_adjunto)."""
    _exigir(request, GESTIONAR, 'sin_permiso_gestionar')
    if tipo not in DOCUMENTOS:
        raise ErrorCaptura('tipo')
    permisos = sv.permisos(request, tipo)
    if not permisos['subir']:
        raise ErrorCaptura('permiso', permisos['bloqueo'] or 'Tu perfil no puede adjuntar respaldos a este documento.', 403)
    try:
        documento_id = int(documento_id)
    except (TypeError, ValueError):
        raise ErrorCaptura('documento', estado=404)
    with transaction.atomic():
        captura = bloquear(request, pk)
        try:
            sv.bloquear_documento(tipo, documento_id)
        except sv.ErrorAdjunto:
            raise ErrorCaptura('documento', estado=404)
        documento = obtener(tipo, documento_id)
        creados, ya_adjunto = adjuntar_desde_captura(captura, tipo, documento)
        _cerrar(captura, 'vinculada', request.user, tipo, documento.pk)
    audit(request, 'captura_vinculada', company=request.company, captura=captura.pk, tipo=tipo, documento=documento.pk,
          adjuntos=[a.pk for a in creados], ya_adjunto=ya_adjunto.pk if ya_adjunto else None)
    return captura, documento, creados, ya_adjunto


def descartar(request, pk, motivo=''):
    _exigir(request, GESTIONAR, 'sin_permiso_gestionar')
    motivo = sv.texto(motivo, MOTIVO_MAX, 'motivo_largo', MENSAJES['motivo_largo'])
    with transaction.atomic():
        captura = bloquear(request, pk)
        _cerrar(captura, 'descartada', request.user, motivo=motivo)
    audit(request, 'captura_descartada', company=request.company, captura=captura.pk, motivo=motivo)
    return captura


def editar_nota(request, pk, nota):
    """Corrige la nota de una captura pendiente (quien la guardó o quien gestiona). El archivo no se cambia."""
    codigos = _codigos(request)
    if GESTIONAR not in codigos and REGISTRAR not in codigos:
        raise ErrorCaptura('sin_permiso', estado=403)
    nota = _nota(nota)
    with transaction.atomic():
        captura = bloquear(request, pk)
        if GESTIONAR not in codigos and captura.creado_por_id != request.user.pk:
            raise ErrorCaptura('sin_permiso_gestionar', estado=403)
        if nota == captura.nota:
            raise ErrorCaptura('nada_que_cambiar')
        if not nota and not captura.archivo:
            raise ErrorCaptura('respaldo_requerido')
        anterior = captura.nota
        captura.nota = nota
        captura.save(update_fields=['nota'])
    audit(request, 'captura_nota', company=request.company, captura=captura.pk, antes=anterior, despues=nota)
    return captura


def liberar(tipo, documento_id, usuario=None, request=None):
    """Al borrar el documento: sus capturas completadas o vinculadas vuelven a estar pendientes (el archivo se conserva)."""
    for captura in Captura.objects.select_for_update(of=('self',)).filter(documento_tipo=tipo, documento_id=documento_id,
                                                                         estado__in=('completada', 'vinculada')):
        anterior = {'estado': captura.estado, 'completado_por': _usuario(captura.completado_por),
                    'completado_en': _local(captura.completado_en)}
        captura.estado, captura.documento_tipo, captura.documento_id = 'pendiente', '', None
        captura.completado_por, captura.completado_en = None, None
        captura.save(update_fields=['estado', 'documento_tipo', 'documento_id', 'completado_por', 'completado_en'])
        audit(request, 'captura_liberada', company=captura.company, captura=captura.pk, tipo=tipo, documento=documento_id,
              por=_usuario(usuario), **anterior)


def para_formulario(request, pk):
    """(captura JSON, aviso) para prellenar «Nueva compra» con `?captura=<id>`: solo si es visible, pendiente y el rol puede
    gestionarla; si no, (None, motivo)."""
    if not pk:
        return None, ''
    try:
        captura = obtener_visible(request, int(pk))
    except (ErrorCaptura, ValueError, TypeError):
        return None, MENSAJES['captura']
    if GESTIONAR not in _codigos(request):
        return None, MENSAJES['sin_permiso_gestionar']
    if captura.estado != 'pendiente':
        return None, _texto_usada(captura)
    return dict_captura(captura), ''
