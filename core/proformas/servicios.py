"""Servicios de Proformas: numeración, validación, cálculo, estados, PDF, correo y JSON de las pantallas.

Reglas comunes:
- importes en Decimal, cuantizados a centavos (HALF_UP) antes de guardar; en el JSON, texto con 2 decimales;
- toda lectura pasa por `objects` (TenantManager), que falla cerrado sin empresa activa; nunca bulk_create;
- las funciones que escriben van en transaction.atomic() y las que cambian estado bloquean la fila con
  select_for_update(of=('self',)) SIN select_related (en PostgreSQL FOR UPDATE no admite el lado anulable de un join
  externo y, sin `of`, un join interno bloquearía también la otra tabla). En SQLite no tiene efecto;
- el `detail` de AuditLog solo lleva str, int, bool o listas de ellos (el campo no tiene encoder);
- ningún texto escrito por el usuario va a los `messages` de Django (se insertan en un literal JS).
Una proforma no usa Receipt, reservar_numero, cupo, stock, cuentas por cobrar ni el SRI.
"""
import json
import logging
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import SimpleNamespace

from django.core.mail import EmailMessage
from django.db import IntegrityError, transaction
from django.db.models import Max, Prefetch, Q
from django.template.loader import render_to_string
from django.utils import timezone

from core.pos.choices import PAYMENT_METHOD, PORCENTAJE_IVA
from core.pos.clientes import correo_valido, separar_correos, unir_correos
from core.proformas.models import ContadorProforma, Proforma, ProformaDetalle
from core.tenancy.context import require_company

logger = logging.getLogger(__name__)

VALIDEZ_POR_DEFECTO = 15          # días
MAX_VALIDEZ = 365                 # días desde la fecha
MAX_LINEAS = 200
MAX_CANTIDAD = 999999
MAX_PRECIO = Decimal('999999.99')
MAX_IMPORTE = Decimal('9999999.99')   # cabe en DecimalField(9,2) de la venta
MAX_DESTINATARIOS = 5
LIMITE_ENVIOS_POR_HORA = 60       # por empresa (cuenta AuditLog 'proforma_enviada' de la última hora)
MAX_MENSAJE = 1000
MAX_MOTIVO = 300
MAX_CONDICIONES = 2000
MAX_BUSQUEDA = 100
MAX_FILAS = 1000
MAX_ENTERO = 999999999999   # ids y cantidades recibidos: nunca desbordan una columna de la base
CENTAVO = Decimal('0.01')
TELEFONO = re.compile(r'[0-9+() -]{7,20}')
FECHA_ISO = re.compile(r'\d{4}-\d{2}-\d{2}')

URL_LISTA = '/proformas/'
URL_VENTAS = '/pos/sale/admin/'


class ErrorProforma(ValueError):
    """Mensaje para el usuario. `campos` = errores por campo; `estado_http` 400/403/404/409/502; `url` adónde volver (GET)."""

    def __init__(self, mensaje, campos=None, estado_http=400, url=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.campos = campos or {}
        self.estado_http = estado_http
        self.url = url


# Textos exactos, publicados también en el contrato de pantallas.
MENSAJES = {
    'no_existe': 'La proforma no existe.',
    'sin_permiso': 'Tu perfil no puede realizar esta acción.',
    'sin_opcion': 'No ha seleccionado ninguna opción',
    'transicion': 'La proforma {numero} está {estado}: no se puede {accion}.',
    'vencida': 'La proforma {numero} venció el {fecha}. Cambia la fecha de validez antes de {accion}.',
    'no_editable': 'La proforma {numero} está {estado} y ya no se puede editar. Puedes duplicarla.',
    'guardada': 'Proforma {numero} guardada.',
    'vuelve_borrador': 'Proforma {numero} guardada. Volvió a borrador: envíala de nuevo a tu cliente.',
    'duplicada': 'Se creó la proforma {numero}, copia de {origen}.',
    'estado_cambiado': 'La proforma {numero} quedó {estado}.',
    'enviada': 'Proforma {numero} enviada a {destinatarios}.',
    'sin_correo': 'Escribe al menos un correo válido para enviar la proforma.',
    'correo_invalido': 'Este correo no es válido: {correo}.',
    'demasiados_correos': 'Puedes enviar la proforma a un máximo de 5 correos.',
    'limite_envios': 'Alcanzaste el límite de 60 envíos de proformas por hora. Inténtalo más tarde.',
    'correo_fallo': 'No se pudo enviar la proforma {numero} ({detalle}). Revisa el correo de la empresa e inténtalo de nuevo.',
    'mensaje_largo': 'El mensaje admite hasta 1000 caracteres.',
    'eliminar_no': 'Solo se elimina un borrador que nunca se envió. Anula la proforma en su lugar.',
    'eliminada': 'Proforma {numero} eliminada.',
    'ya_facturada': 'La proforma {numero} ya se facturó con la factura {factura}.',
    'no_facturable': ('La proforma {numero} está {estado}: solo se facturan las proformas enviadas y vigentes, '
                      'o las aceptadas.'),
    'solo_factura': 'Una proforma se convierte en una factura electrónica (01), no en un ticket.',
    'sin_lineas_facturables': 'Ningún producto de la proforma {numero} se puede facturar ahora (sin stock o eliminado).',
    'facturar_sin_permiso': 'Tu perfil no puede facturar proformas.',
    'total_maximo': 'El total de la proforma supera USD 9.999.999,99.',
    'revisa': 'Revisa los datos marcados.',
    'pdf_fallo': 'No se pudo generar el PDF de la proforma {numero}. Inténtalo de nuevo.',
}

# Errores por campo (en ErrorProforma.campos).
CAMPOS = {
    'cliente': 'El cliente no existe.',
    'cliente_nombre': 'Escribe el nombre del cliente o elige uno registrado.',
    'cliente_identificacion': 'La identificación admite hasta 20 caracteres.',
    'cliente_correo': 'Este correo no es válido: {correo}.',
    'cliente_correos': 'Escribe hasta 5 correos, con 500 caracteres en total como máximo.',
    'cliente_telefono': 'Usa de 7 a 20 dígitos (puede llevar +, espacios, guiones o paréntesis).',
    'cliente_direccion': 'La dirección admite hasta 500 caracteres.',
    'fecha': 'La fecha no es válida o es futura.',
    'valida_hasta': 'La validez debe ir de la fecha de la proforma hasta 365 días después.',
    'forma_pago_sugerida': 'Elige una forma de pago de la lista.',
    'condiciones': 'Las condiciones admiten hasta 2000 caracteres.',
    'lineas': 'Agrega al menos un producto.',
    'lineas_max': 'Una proforma admite hasta 200 líneas.',
}

# Errores por línea: {indice (desde 0, en el orden enviado), campo, texto}.
LINEAS = {
    'product': 'El producto no existe.',
    'product_repetido': 'El producto {nombre} está repetido: suma las cantidades en una sola línea.',
    'cant': 'La cantidad es un número entero de 1 a 999999.',
    'price': 'El precio va de 0 a 999999,99, con hasta 2 decimales.',
    'dscto': 'El descuento es un porcentaje entero de 0 a 100, igual que en la factura.',
    'descripcion': 'La descripción admite hasta 300 caracteres.',
}

# Avisos (duplicar y, en el paso de la conversión, la precarga de la venta).
AVISOS = {
    'emitir': 'Al guardar se emite la factura y se envía al SRI. Revisa el cliente, los productos y la forma de pago.',
    'producto_eliminado': 'La línea «{descripcion}» no se cargó: el producto ya no existe.',
    'sin_stock': 'No se cargó «{nombre}»: no tiene stock (la proforma pedía {cant}).',
    'stock_parcial': '«{nombre}»: hay {stock} en stock y la proforma pedía {cant}; se cargaron {stock}.',
    'tarifa_cambiada': '«{nombre}»: el IVA cambió de {antes} a {ahora}; la factura usa la tarifa actual.',
    'precio_distinto': '«{nombre}»: se usa el precio de la proforma (USD {precio}) y no el actual (USD {actual}).',
    'descripcion': 'La factura usa el nombre de cada producto, no la descripción escrita en la proforma.',
    'prospecto': 'La proforma es para un prospecto: registra al cliente antes de emitir.',
}

AVISO_EDITAR_ENVIADA = 'Al guardar, la proforma vuelve a borrador y tendrás que enviarla de nuevo.'
AVISO_FACTURA_PENDIENTE = ('La factura {numero} está «{estado}»: corrígela o reenvíala desde «Facturas emitidas». Si la '
                           'eliminas, la proforma vuelve a su estado anterior («Aceptada» o «Enviada»).')
AVISO_FACTURA_EN_PROCESO = ('La factura {numero} está «{estado}»: consulta su autorización desde «Facturas emitidas»; '
                            'mientras tanto no se puede eliminar.')
AVISO_FACTURA_PRUEBAS = 'Factura emitida en el ambiente de PRUEBAS: sin validez tributaria.'

# Verbo de cada acción en los mensajes «no se puede …» y «antes de …».
VERBOS = {'editar': 'editar', 'enviar_correo': 'enviar por correo', 'marcar_enviada': 'marcar como enviada',
          'aceptar': 'aceptar', 'rechazar': 'rechazar', 'anular': 'anular', 'facturar': 'facturar', 'eliminar': 'eliminar'}

# Acciones de cada estado visible antes de filtrar por rol y plan (§3.3). «vencida» se separa según el estado guardado.
ACCIONES_POR_ESTADO = {
    'borrador': ('ver', 'pdf', 'editar', 'duplicar', 'enviar_correo', 'marcar_enviada', 'aceptar', 'anular', 'eliminar'),
    'enviada': ('ver', 'pdf', 'editar', 'duplicar', 'enviar_correo', 'aceptar', 'rechazar', 'anular', 'facturar'),
    'vencida_borrador': ('ver', 'pdf', 'editar', 'duplicar', 'anular', 'eliminar'),
    'vencida_enviada': ('ver', 'pdf', 'editar', 'duplicar', 'rechazar', 'anular'),
    'aceptada': ('ver', 'pdf', 'duplicar', 'enviar_correo', 'rechazar', 'anular', 'facturar'),
    'rechazada': ('ver', 'pdf', 'duplicar', 'anular'),
    'facturada': ('ver', 'pdf', 'duplicar'),
    'anulada': ('ver', 'pdf', 'duplicar'),
}
PERMISO_DE_ACCION = {'ver': 'view_proforma', 'pdf': 'view_proforma', 'duplicar': 'add_proforma',
                     'editar': 'change_proforma', 'enviar_correo': 'change_proforma', 'marcar_enviada': 'change_proforma',
                     'aceptar': 'change_proforma', 'rechazar': 'change_proforma', 'anular': 'change_proforma',
                     'eliminar': 'delete_proforma'}
ACCIONES_DE_CONSULTA = ('ver', 'pdf')

# acción: (estados guardados de origen, destino, exige vigente, campo de fecha, código de auditoría)
TRANSICIONES = {
    'marcar_enviada': ({'borrador'}, 'enviada', True, 'enviada_en', 'proforma_marcada_enviada'),
    'aceptar': ({'borrador', 'enviada'}, 'aceptada', True, 'aceptada_en', 'proforma_aceptada'),
    'rechazar': ({'enviada', 'aceptada'}, 'rechazada', False, 'rechazada_en', 'proforma_rechazada'),
    'anular': ({'borrador', 'enviada', 'aceptada', 'rechazada'}, 'anulada', False, 'anulada_en', 'proforma_anulada'),
}

ESTADOS_RIDE = ('authorized', 'authorized_and_sent_by_email', 'canceled')
ESTADOS_CON_AVISO = ('without_authorizing', 'returned', 'not_authorized', 'sequential_registered_error', 'in_process')


# ---------------------------------------------------------------- utilidades

def _hoy():
    return timezone.localdate()


def _cuantizar(valor):
    return Decimal(str(valor)).quantize(CENTAVO, ROUND_HALF_UP)


def _dinero(valor):
    return f'{_cuantizar(valor):.2f}'


def _momento(valor):
    return timezone.localtime(valor).isoformat() if valor else None


def _fecha_texto(valor):
    return valor.strftime('%d/%m/%Y')


def _fecha_iso(texto):
    texto = str(texto or '').strip()
    if not FECHA_ISO.fullmatch(texto):
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def _texto(datos, campo):
    valor = datos.get(campo, '')
    return valor if isinstance(valor, str) else ('' if valor is None else str(valor))


def _entero(valor):
    """Entero desde JSON o texto; None si no es un entero (1.5, '2,0', True…)."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor if 0 <= valor <= MAX_ENTERO else None
    if isinstance(valor, float):
        return int(valor) if valor.is_integer() and 0 <= valor <= MAX_ENTERO else None
    texto = str(valor if valor is not None else '').strip()
    return int(texto) if re.fullmatch(r'[0-9]{1,12}', texto) else None


def _decimal(valor):
    if isinstance(valor, bool) or valor is None:
        return None
    texto = str(valor).strip()
    if not texto or len(texto) > 30:
        return None
    try:
        numero = Decimal(texto)
    except InvalidOperation:
        return None
    return numero if numero.is_finite() else None


def _id(valor):
    numero = _entero(valor)
    if numero is None:
        raise ErrorProforma(MENSAJES['no_existe'], estado_http=404, url=URL_LISTA)
    return numero


def _nombre_usuario(usuario):
    return (usuario.names or usuario.username) if usuario is not None else ''


def _estado_en_texto(p, hoy=None):
    return p.nombre_estado(hoy).lower()


def _estado_guardado(p):
    return dict(Proforma.ESTADOS)[p.estado].lower()


def _auditar(request, usuario, codigo, p, **detalle):
    """AuditLog con la empresa activa. Sin petición (servicio llamado desde una tarea o una prueba) registra al usuario."""
    import crum

    from core.tenancy.models import audit
    if request is None:
        request = crum.get_current_request() or SimpleNamespace(user=usuario, META={})
    audit(request, codigo, company=require_company(), proforma=p.numero_completo, proforma_id=int(p.pk), **detalle)


def tarifa_de_producto(product):
    """Misma regla que Sale.calculate_detail: la tarifa del producto o, sin ella, '4'/'0' según «¿Se cobra impuesto?»."""
    return product.tarifa_iva or ('4' if product.with_tax else '0')


def formatear_numero(numero):
    return f'PRO-{numero:06d}'


def siguiente_numero():
    """Número siguiente de la empresa activa. Exige estar dentro de transaction.atomic(): el bloqueo del contador dura
    hasta el fin de la transacción que guarda la proforma. Los números no se reutilizan."""
    company = require_company()
    try:
        with transaction.atomic():
            ContadorProforma.objects.get_or_create(company=company)
    except IntegrityError:
        pass   # otra transacción lo creó a la vez
    fila = ContadorProforma.objects.select_for_update(of=('self',)).get()
    numero = max(fila.ultimo, Proforma.objects.aggregate(m=Max('numero'))['m'] or 0) + 1
    fila.ultimo = numero
    fila.save(update_fields=['ultimo'])
    return numero


def bloquear(proforma_id):
    p = Proforma.objects.select_for_update(of=('self',)).filter(pk=_id(proforma_id)).first()
    if p is None:
        raise ErrorProforma(MENSAJES['no_existe'], estado_http=404, url=URL_LISTA)
    return p


def obtener(proforma_id):
    """Proforma de la empresa activa con lo que usa `detalle` (sin bloqueo); ErrorProforma 404 si no existe."""
    p = (Proforma.objects.select_related('venta', 'vendedor', 'creada_por', 'origen', 'company')
         .prefetch_related(Prefetch('detalles', ProformaDetalle.objects.select_related('product')))
         .filter(pk=_id(proforma_id)).first())
    if p is None:
        raise ErrorProforma(MENSAJES['no_existe'], estado_http=404, url=URL_LISTA)
    return p


# ---------------------------------------------------------------- permisos y acciones

def permisos_de(request):
    """Codenames del rol en la empresa activa (vacío sin rol). Una vez por petición."""
    if not hasattr(request, '_fpa_permisos_proforma'):
        from core.security.session import get_group
        grupo = get_group(request)
        request._fpa_permisos_proforma = set(grupo.permissions.values_list('codename', flat=True)) if grupo else set()
    return request._fpa_permisos_proforma


def plan_vencido(request):
    from core.suscripciones.servicios import estado_de_peticion
    estado = estado_de_peticion(request)
    return estado is not None and estado.vencido


def puede_facturar(request):
    """(se puede, motivo) para «Facturar». Sin permiso de rol → (False, None): no se muestra el botón. Plan, cupo o
    configuración → (False, motivo): el botón se muestra deshabilitado con ese texto. Se permite en PRUEBAS (decisión
    de la propietaria del 28/10/2026): la factura queda vinculada y la pantalla avisa que no tiene validez tributaria."""
    if not hasattr(request, '_fpa_facturar_proforma'):
        request._fpa_facturar_proforma = _puede_facturar(request)
    return request._fpa_facturar_proforma


def _puede_facturar(request):
    from core.configuracion.servicios import requisitos_de_emision
    from core.suscripciones.middleware import mensaje_de_bloqueo
    from core.suscripciones.servicios import estado_de_peticion
    if not {'change_proforma', 'add_sale'} <= permisos_de(request):
        return False, None
    estado = estado_de_peticion(request)
    if estado is None:
        return False, None
    if not estado.puede_emitir:
        return False, mensaje_de_bloqueo(estado)
    faltan = requisitos_de_emision(request.company, '01', True)
    if faltan:
        return False, faltan[0]['mensaje']
    return True, None


def contexto_de_peticion(request):
    """Lo que `fila` y `detalle` necesitan, calculado una vez por petición."""
    return {'permisos': permisos_de(request), 'facturable': puede_facturar(request), 'plan_vencido': plan_vencido(request),
            'hoy': _hoy()}


def _acciones_de_estado(p, hoy=None):
    visible = p.estado_visible(hoy)
    clave = f'vencida_{p.estado}' if visible == 'vencida' else visible
    acciones = list(ACCIONES_POR_ESTADO[clave])
    if 'eliminar' in acciones and not (p.estado == 'borrador' and p.enviada_en is None and not p.envios):
        acciones.remove('eliminar')
    if 'facturar' in acciones and p.venta_id is not None:
        acciones.remove('facturar')
    return acciones


def acciones_permitidas(proforma, permisos, facturable, plan_vencido, hoy=None):
    """Acciones del estado (§3.3) filtradas por el rol; con el plan vencido, solo ver y pdf."""
    acciones = []
    for accion in _acciones_de_estado(proforma, hoy):
        if accion == 'facturar':
            if facturable[0]:
                acciones.append(accion)
        elif PERMISO_DE_ACCION[accion] in permisos:
            acciones.append(accion)
    if plan_vencido:
        acciones = [a for a in acciones if a in ACCIONES_DE_CONSULTA]
    return acciones


def facturar_bloqueado(proforma, facturable, hoy=None):
    """Motivo para mostrar «Facturar» deshabilitado: solo si el estado lo permitiría y falla el plan, el cupo o la
    configuración (con un rol sin permiso es None y el botón no se muestra)."""
    if facturable[0] or 'facturar' not in _acciones_de_estado(proforma, hoy):
        return None
    return facturable[1]


def _exigir(permisos, accion):
    if PERMISO_DE_ACCION[accion] not in permisos:
        raise ErrorProforma(MENSAJES['sin_permiso'], estado_http=403)


# ---------------------------------------------------------------- validación y cálculo

def _copia_de_cliente(cliente):
    return {'cliente': cliente,
            'cliente_nombre': (' '.join((cliente.user.names or '').split()) or cliente.dni)[:300],
            'cliente_identificacion': (cliente.dni or '')[:20],
            'cliente_correo': unir_correos(cliente.correos(), 500),
            'cliente_telefono': (cliente.mobile or '')[:20],
            'cliente_direccion': (cliente.address or '')[:500]}


def _validar_cliente(datos, campos):
    from core.pos.models import Client
    cliente_id = _texto(datos, 'cliente').strip()
    if cliente_id:
        numero = _entero(cliente_id)
        cliente = Client.objects.select_related('user').filter(pk=numero).first() if numero is not None else None
        if cliente is None:
            campos['cliente'] = CAMPOS['cliente']
            return {}
        return _copia_de_cliente(cliente)   # con cliente se ignoran los cliente_* enviados
    nombre = ' '.join(_texto(datos, 'cliente_nombre').split())
    if not 2 <= len(nombre) <= 300:
        campos['cliente_nombre'] = CAMPOS['cliente_nombre']
    identificacion = _texto(datos, 'cliente_identificacion').strip().upper()
    if len(identificacion) > 20:
        campos['cliente_identificacion'] = CAMPOS['cliente_identificacion']
    correos = separar_correos(_texto(datos, 'cliente_correo'))
    invalido = next((c for c in correos if not correo_valido(c)), None)
    if invalido is not None:
        campos['cliente_correo'] = CAMPOS['cliente_correo'].format(correo=invalido)
    elif len(correos) > MAX_DESTINATARIOS or len(', '.join(correos)) > 500:
        campos['cliente_correo'] = CAMPOS['cliente_correos']
    telefono = _texto(datos, 'cliente_telefono').strip()
    if telefono and not TELEFONO.fullmatch(telefono):
        campos['cliente_telefono'] = CAMPOS['cliente_telefono']
    direccion = ' '.join(_texto(datos, 'cliente_direccion').split())
    if len(direccion) > 500:
        campos['cliente_direccion'] = CAMPOS['cliente_direccion']
    return {'cliente': None, 'cliente_nombre': nombre, 'cliente_identificacion': identificacion,
            'cliente_correo': ', '.join(correos), 'cliente_telefono': telefono, 'cliente_direccion': direccion}


def _validar_lineas(datos, campos):
    from core.pos.models import Product
    crudas = datos.get('lineas', '')
    if isinstance(crudas, str):
        try:
            crudas = json.loads(crudas) if crudas.strip() else []
        except ValueError:
            crudas = None
    if not isinstance(crudas, list) or not crudas:
        campos['lineas'] = CAMPOS['lineas']
        return []
    if len(crudas) > MAX_LINEAS:
        campos['lineas'] = CAMPOS['lineas_max']
        return []
    ids = [_entero(c.get('product')) for c in crudas if isinstance(c, dict)]
    productos = {p.pk: p for p in Product.objects.filter(pk__in=[i for i in ids if i is not None])}
    errores, lineas, vistos = [], [], set()
    for indice, cruda in enumerate(crudas):
        cruda = cruda if isinstance(cruda, dict) else {}
        propios = []
        producto = productos.get(_entero(cruda.get('product')))
        if producto is None:
            propios.append(('product', LINEAS['product']))
        elif producto.pk in vistos:
            propios.append(('product', LINEAS['product_repetido'].format(nombre=producto.name)))
        else:
            vistos.add(producto.pk)
        cant = _entero(cruda.get('cant'))
        if cant is None or not 1 <= cant <= MAX_CANTIDAD:
            propios.append(('cant', LINEAS['cant']))
        precio = _decimal(cruda.get('price'))
        if precio is None or not Decimal('0') <= precio <= MAX_PRECIO or precio != precio.quantize(CENTAVO):
            propios.append(('price', LINEAS['price']))
        dscto = _decimal(cruda.get('dscto') if cruda.get('dscto') not in ('', None) else 0)   # sin descuento = 0
        if dscto is None or dscto != dscto.to_integral_value() or not 0 <= dscto <= 100:
            propios.append(('dscto', LINEAS['dscto']))
        descripcion = ' '.join(str(cruda.get('descripcion') or '').split())
        if len(descripcion) > 300:
            propios.append(('descripcion', LINEAS['descripcion']))
        if propios:
            errores.extend({'indice': indice, 'campo': campo, 'texto': texto} for campo, texto in propios)
            continue
        lineas.append(ProformaDetalle(product=producto, codigo=producto.code[:20], descripcion=descripcion or producto.name[:300],
                                      cant=cant, price=precio.quantize(CENTAVO),
                                      dscto=(dscto / 100).quantize(CENTAVO, ROUND_HALF_UP),
                                      codigo_porcentaje=tarifa_de_producto(producto)))
    if errores:
        campos['lineas'] = errores
    return lineas


def validar(datos, proforma=None):
    """Valida y normaliza la cabecera y las líneas (§4.4). Devuelve (campos de cabecera, líneas SIN guardar) o lanza
    ErrorProforma(MENSAJES['revisa'], campos=...). `proforma` es la que se edita (None al crear)."""
    campos = {}
    hoy = _hoy()
    cabecera = _validar_cliente(datos, campos)
    fecha = _fecha_iso(_texto(datos, 'fecha'))
    if fecha is None or fecha > hoy:
        campos['fecha'] = CAMPOS['fecha']
    valida_hasta = _fecha_iso(_texto(datos, 'valida_hasta'))
    if valida_hasta is None or (fecha is not None and not fecha <= valida_hasta <= fecha + timedelta(days=MAX_VALIDEZ)):
        campos['valida_hasta'] = CAMPOS['valida_hasta']
    forma_pago = _texto(datos, 'forma_pago_sugerida').strip()
    if forma_pago and forma_pago not in dict(PAYMENT_METHOD):
        campos['forma_pago_sugerida'] = CAMPOS['forma_pago_sugerida']
    condiciones = _texto(datos, 'condiciones').replace('\r\n', '\n').strip()
    if len(condiciones) > MAX_CONDICIONES:
        campos['condiciones'] = CAMPOS['condiciones']
    lineas = _validar_lineas(datos, campos)
    if campos:
        raise ErrorProforma(MENSAJES['revisa'], campos=campos)
    cabecera.update(fecha=fecha, valida_hasta=valida_hasta, forma_pago_sugerida=forma_pago, condiciones=condiciones)
    return cabecera, lineas


def calcular(proforma, lineas):
    """Importes de cada línea con su tarifa y totales de la proforma, con las mismas funciones que la factura."""
    from core.pos.models import calcular_linea_iva, totales_de_lineas
    for linea in lineas:
        calcular_linea_iva(linea, linea.codigo_porcentaje)
    gravado, cero, iva, descuento = totales_de_lineas(lineas)
    total = gravado + cero + iva
    importes = [gravado, cero, iva, descuento, total]
    importes += [Decimal(str(v)) for linea in lineas for v in (linea.subtotal, linea.total_dscto, linea.price_with_vat)]
    if max(importes) > MAX_IMPORTE:   # ningún importe desborda DecimalField(9, 2), ni aquí ni en la factura
        raise ErrorProforma(MENSAJES['total_maximo'])
    proforma.subtotal_gravado = _cuantizar(gravado)
    proforma.subtotal_cero = _cuantizar(cero)
    proforma.total_iva = _cuantizar(iva)
    proforma.total_descuento = _cuantizar(descuento)
    proforma.total = _cuantizar(total)


def _guardar_lineas(proforma, lineas):
    for linea in lineas:
        linea.proforma = proforma
        linea.save()


# ---------------------------------------------------------------- crear, editar, duplicar, estados

@transaction.atomic
def crear(datos, usuario):
    cabecera, lineas = validar(datos)
    p = Proforma(estado='borrador', vendedor=usuario, creada_por=usuario, **cabecera)
    calcular(p, lineas)
    p.numero = siguiente_numero()   # al final: el contador queda bloqueado lo menos posible
    p.numero_completo = formatear_numero(p.numero)
    p.save()
    _guardar_lineas(p, lineas)
    return p


@transaction.atomic
def editar(proforma_id, datos, usuario):
    """Reemplaza cabecera y líneas (en el orden recibido). Una enviada vuelve a borrador. Devuelve (proforma, mensaje)."""
    p = bloquear(proforma_id)
    if p.estado not in Proforma.PUEDEN_VENCER:
        raise ErrorProforma(MENSAJES['no_editable'].format(numero=p.numero_completo, estado=_estado_en_texto(p)),
                            estado_http=409, url=f'{URL_LISTA}ver/{p.pk}/')
    cabecera, lineas = validar(datos, p)
    for campo, valor in cabecera.items():
        setattr(p, campo, valor)
    calcular(p, lineas)
    vuelve = p.estado == 'enviada'
    if vuelve:
        p.estado = 'borrador'
    p.save()
    p.detalles.all().delete()
    _guardar_lineas(p, lineas)
    return p, MENSAJES['vuelve_borrador' if vuelve else 'guardada'].format(numero=p.numero_completo)


@transaction.atomic
def duplicar(proforma_id, usuario):
    """Copia en borrador con número nuevo, fecha de hoy y validez por defecto, desde cualquier estado. Las líneas usan la
    tarifa ACTUAL del producto; las de productos eliminados se omiten con aviso. La original no cambia."""
    from core.pos.models import Client
    original = Proforma.objects.filter(pk=_id(proforma_id)).first()
    if original is None:
        raise ErrorProforma(MENSAJES['no_existe'], estado_http=404, url=URL_LISTA)
    avisos, lineas = [], []
    for linea in original.detalles.select_related('product'):
        if linea.product_id is None:
            avisos.append(AVISOS['producto_eliminado'].format(descripcion=linea.descripcion))
            continue
        lineas.append(ProformaDetalle(product=linea.product, codigo=linea.product.code[:20], descripcion=linea.descripcion,
                                      cant=linea.cant, price=linea.price, dscto=linea.dscto,
                                      codigo_porcentaje=tarifa_de_producto(linea.product)))
    if not lineas:
        raise ErrorProforma(MENSAJES['sin_lineas_facturables'].format(numero=original.numero_completo), estado_http=409)
    cliente = Client.objects.select_related('user').filter(pk=original.cliente_id).first() if original.cliente_id else None
    datos_cliente = _copia_de_cliente(cliente) if cliente is not None else {
        'cliente': None, 'cliente_nombre': original.cliente_nombre, 'cliente_identificacion': original.cliente_identificacion,
        'cliente_correo': original.cliente_correo, 'cliente_telefono': original.cliente_telefono,
        'cliente_direccion': original.cliente_direccion}
    hoy = _hoy()
    copia = Proforma(estado='borrador', fecha=hoy, valida_hasta=hoy + timedelta(days=VALIDEZ_POR_DEFECTO),
                     condiciones=original.condiciones, forma_pago_sugerida=original.forma_pago_sugerida, origen=original,
                     vendedor=usuario, creada_por=usuario, **datos_cliente)
    calcular(copia, lineas)
    copia.numero = siguiente_numero()
    copia.numero_completo = formatear_numero(copia.numero)
    copia.save()
    _guardar_lineas(copia, lineas)
    return copia, avisos


@transaction.atomic
def cambiar_estado(proforma_id, accion, usuario, motivo='', request=None):
    if accion not in TRANSICIONES:
        raise ErrorProforma(MENSAJES['sin_opcion'])
    p = bloquear(proforma_id)
    origen, destino, vigente, campo, codigo = TRANSICIONES[accion]
    if p.estado not in origen:
        raise ErrorProforma(MENSAJES['transicion'].format(numero=p.numero_completo, estado=_estado_guardado(p),
                                                          accion=VERBOS[accion]), estado_http=409)
    if vigente and p.esta_vencida():
        raise ErrorProforma(MENSAJES['vencida'].format(numero=p.numero_completo, fecha=_fecha_texto(p.valida_hasta),
                                                       accion=VERBOS[accion]), estado_http=409)
    detalle = {}
    if accion in ('rechazar', 'anular'):
        p.motivo = ' '.join(str(motivo or '').split())[:MAX_MOTIVO]
        detalle['motivo'] = p.motivo
    p.estado = destino
    setattr(p, campo, timezone.now())
    p.save(update_fields=['estado', campo, 'motivo', 'actualizada_en'])
    _auditar(request, usuario, codigo, p, **detalle)
    return p


@transaction.atomic
def eliminar(proforma_id, usuario, request=None):
    """Solo un borrador que nunca se envió. Las líneas caen en cascada; el contador no retrocede."""
    p = bloquear(proforma_id)
    if p.estado != 'borrador' or p.enviada_en is not None or p.envios:
        raise ErrorProforma(MENSAJES['eliminar_no'], estado_http=409)
    numero, pk = p.numero_completo, p.pk
    p.delete()
    p.pk = pk   # para la auditoría
    _auditar(request, usuario, 'proforma_eliminada', p)
    return MENSAJES['eliminada'].format(numero=numero)


# ---------------------------------------------------------------- PDF y correo

def contexto_pdf(proforma):
    from core.configuracion.servicios import punto_predeterminado
    from core.pos import emision
    from core.pos.models import impuestos_por_tarifa
    empresa = proforma.company
    lineas = list(proforma.detalles.select_related('product'))
    punto = punto_predeterminado(empresa)
    venta = proforma.venta if proforma.venta_id else None
    return {'proforma': proforma, 'empresa': empresa, 'lineas': lineas, 'impuestos': impuestos_por_tarifa(lineas),
            'estado': proforma.estado_visible(), 'estado_nombre': proforma.nombre_estado(),
            'establecimiento': (punto.establishment.address if punto else '') or empresa.establishment_address,
            'proveedor': emision.datos_proveedor(),
            'forma_pago': proforma.get_forma_pago_sugerida_display() if proforma.forma_pago_sugerida else '',
            'vendedor': _nombre_usuario(proforma.vendedor) if proforma.vendedor_id else '',
            'factura': venta.voucher_number_full if venta else '',
            'factura_pruebas': venta is not None and venta.environment_type != emision.PRODUCCION}


def generar_pdf(proforma):
    from core.pos.utilities import printer
    return printer.create_pdf(contexto_pdf(proforma), 'proformas/pdf.html')


def _nombre_empresa(empresa):
    return empresa.tradename or empresa.business_name


def enviar_por_correo(proforma_id, usuario, destinatarios='', mensaje='', request=None):
    """Envía el PDF por correo (SMTP de la empresa o de la plataforma). borrador → enviada; enviada y aceptada no cambian
    de estado. Si el envío falla no cambia nada. No es un comprobante: no toca VoucherErrors."""
    from core.pos.utilities.sri import SRI
    from core.tenancy.models import AuditLog
    p = Proforma.objects.select_related('company', 'vendedor').filter(pk=_id(proforma_id)).first()
    if p is None:
        raise ErrorProforma(MENSAJES['no_existe'], estado_http=404, url=URL_LISTA)
    if p.esta_vencida():
        raise ErrorProforma(MENSAJES['vencida'].format(numero=p.numero_completo, fecha=_fecha_texto(p.valida_hasta),
                                                       accion=VERBOS['enviar_correo']), estado_http=409)
    if p.estado not in ('borrador', 'enviada', 'aceptada'):
        raise ErrorProforma(MENSAJES['transicion'].format(numero=p.numero_completo, estado=_estado_guardado(p),
                                                          accion=VERBOS['enviar_correo']), estado_http=409)
    mensaje = str(mensaje or '').replace('\r\n', '\n').strip()
    if len(mensaje) > MAX_MENSAJE:
        raise ErrorProforma(MENSAJES['mensaje_largo'])
    lista = separar_correos(str(destinatarios or '').strip() or p.cliente_correo)
    invalido = next((c for c in lista if not correo_valido(c)), None)
    if invalido is not None:
        raise ErrorProforma(MENSAJES['correo_invalido'].format(correo=invalido))
    if not lista:
        raise ErrorProforma(MENSAJES['sin_correo'])
    if len(lista) > MAX_DESTINATARIOS:
        raise ErrorProforma(MENSAJES['demasiados_correos'])
    hace_una_hora = timezone.now() - timedelta(hours=1)
    if AuditLog.objects.filter(company=p.company, action='proforma_enviada', created_at__gte=hace_una_hora).count() \
            >= LIMITE_ENVIOS_POR_HORA:
        raise ErrorProforma(MENSAJES['limite_envios'], estado_http=409)
    empresa = p.company
    try:
        pdf = generar_pdf(p)
        conexion, remitente, responder = SRI()._correo_saliente(empresa)
        cuerpo = render_to_string('proformas/correo.txt', {
            'proforma': p, 'empresa': _nombre_empresa(empresa), 'total': _dinero(p.total),
            'valida_hasta': _fecha_texto(p.valida_hasta), 'mensaje': mensaje})
        correo = EmailMessage(subject=' '.join(f'Proforma {p.numero_completo} - {_nombre_empresa(empresa)}'.split()),
                              body=cuerpo, from_email=remitente, to=lista, reply_to=responder, connection=conexion)
        correo.attach(f'{p.numero_completo}.pdf', pdf, 'application/pdf')
        correo.send()
    except Exception as e:  # noqa: BLE001 - el mensaje explica qué revisar; nada cambió
        logger.warning('No se pudo enviar la proforma %s: %s', p.numero_completo, e.__class__.__name__)
        raise ErrorProforma(MENSAJES['correo_fallo'].format(numero=p.numero_completo,
                                                            detalle=f'{e.__class__.__name__}: {str(e)[:200]}'),
                            estado_http=502)
    with transaction.atomic():
        p = bloquear(p.pk)
        if p.estado == 'borrador':
            p.estado = 'enviada'
        p.enviada_en = timezone.now()
        p.enviada_a = unir_correos(lista, 500)
        p.envios += 1
        p.save(update_fields=['estado', 'enviada_en', 'enviada_a', 'envios', 'actualizada_en'])
        _auditar(request, usuario, 'proforma_enviada', p, destinatarios=len(lista), envio=int(p.envios))
    return p


# ---------------------------------------------------------------- consultas y JSON de las pantallas

def consultar(estado='', desde='', hasta='', q='', hoy=None):
    """Proformas de la lista (como mucho MAX_FILAS, las más recientes primero), sin consultas por fila."""
    hoy = hoy or _hoy()
    qs = Proforma.objects.select_related('venta', 'vendedor')
    if estado == 'vencida':
        qs = qs.filter(estado__in=Proforma.PUEDEN_VENCER, valida_hasta__lt=hoy)
    elif estado in Proforma.PUEDEN_VENCER:
        qs = qs.filter(estado=estado, valida_hasta__gte=hoy)
    elif estado in dict(Proforma.ESTADOS):
        qs = qs.filter(estado=estado)
    desde, hasta = _fecha_iso(desde), _fecha_iso(hasta)
    if desde:
        qs = qs.filter(fecha__gte=desde)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)
    q = str(q or '').strip()[:MAX_BUSQUEDA]
    if q:
        qs = qs.filter(Q(numero_completo__icontains=q) | Q(cliente_nombre__icontains=q) | Q(cliente_identificacion__icontains=q))
    return qs.order_by('-id')[:MAX_FILAS]


def _venta_json(venta):
    from core.pos import emision
    if venta is None:
        return None
    numero, estado = venta.voucher_number_full, venta.get_status_display()
    aviso = None
    if venta.status == emision.EN_PROCESO:
        aviso = AVISO_FACTURA_EN_PROCESO.format(numero=numero, estado=estado)
    elif venta.status in ESTADOS_CON_AVISO:
        aviso = AVISO_FACTURA_PENDIENTE.format(numero=numero, estado=estado)
    pruebas = venta.environment_type != emision.PRODUCCION
    return {'id': int(venta.pk), 'numero': numero, 'estado': {'id': venta.status, 'nombre': estado},
            'ambiente': {'id': int(venta.environment_type), 'nombre': venta.get_environment_type_display()},
            'sin_validez_tributaria': pruebas, 'aviso_ambiente': AVISO_FACTURA_PRUEBAS if pruebas else None,
            'fecha': (venta.emission_date or venta.date_joined).isoformat(), 'total': _dinero(venta.total),
            'url_lista': URL_VENTAS,
            'url_ride': f'{URL_VENTAS}print/a4/{venta.pk}/' if venta.status in ESTADOS_RIDE else None,
            'aviso': aviso}


def fila(proforma, permisos, facturable, plan_vencido, hoy=None):
    """JSON de una proforma en la lista (§6.1). No consulta líneas; usa venta y vendedor de select_related."""
    p, hoy = proforma, hoy or _hoy()
    acciones = acciones_permitidas(p, permisos, facturable, plan_vencido, hoy)
    base = f'{URL_LISTA}%s/{p.pk}/'
    return {
        'id': int(p.pk), 'numero': p.numero_completo, 'fecha': p.fecha.isoformat(), 'valida_hasta': p.valida_hasta.isoformat(),
        'dias_para_vencer': (p.valida_hasta - hoy).days if p.estado in Proforma.PUEDEN_VENCER else None,
        'estado': {'id': p.estado_visible(hoy), 'nombre': p.nombre_estado(hoy), 'guardado': p.estado},
        'cliente': {'id': p.cliente_id, 'nombre': p.cliente_nombre, 'identificacion': p.cliente_identificacion,
                    'correo': p.cliente_correo, 'telefono': p.cliente_telefono, 'direccion': p.cliente_direccion,
                    'es_prospecto': p.es_prospecto},
        'vendedor': {'id': p.vendedor_id, 'nombre': _nombre_usuario(p.vendedor)} if p.vendedor_id else None,
        'subtotal_gravado': _dinero(p.subtotal_gravado), 'subtotal_cero': _dinero(p.subtotal_cero),
        'total_descuento': _dinero(p.total_descuento), 'total_iva': _dinero(p.total_iva), 'total': _dinero(p.total),
        'venta': _venta_json(p.venta) if p.venta_id else None,
        'envios': int(p.envios), 'enviada_en': _momento(p.enviada_en),
        'acciones': acciones,
        'facturar_bloqueado': facturar_bloqueado(p, facturable, hoy),
        'urls': {'ver': base % 'ver' if 'ver' in acciones else None,
                 'pdf': base % 'pdf' if 'pdf' in acciones else None,
                 'editar': base % 'update' if 'editar' in acciones else None,
                 'facturar': f'{URL_VENTAS}add/?proforma={p.pk}' if 'facturar' in acciones else None,
                 'eliminar': base % 'delete' if 'eliminar' in acciones else None},
    }


def _linea_json(linea):
    producto = linea.product if linea.product_id else None
    return {'id': int(linea.pk), 'product_id': linea.product_id, 'codigo': linea.codigo, 'descripcion': linea.descripcion,
            'cant': int(linea.cant), 'price': _dinero(linea.price), 'dscto': str(int((linea.dscto * 100).to_integral_value())),
            'codigo_porcentaje': linea.codigo_porcentaje,
            'tarifa': f'{PORCENTAJE_IVA.get(linea.codigo_porcentaje, Decimal("0")):.2f}', 'nombre_tarifa': linea.nombre_tarifa,
            'subtotal': _dinero(linea.subtotal), 'total_dscto': _dinero(linea.total_dscto), 'total': _dinero(linea.total),
            'total_iva': _dinero(linea.total_iva), 'producto_eliminado': producto is None,
            # Para el editor: datos actuales del producto (solo se informan).
            'producto': {'nombre': producto.name, 'stock': int(producto.stock), 'inventariado': producto.inventoried,
                         'pvp': _dinero(producto.pvp)} if producto else None}


def impuestos_json(lineas):
    from core.pos.models import impuestos_por_tarifa
    return [{'codigo': t['codigo'], 'nombre': t['nombre'], 'tarifa': f"{t['tarifa']:.2f}", 'base': _dinero(t['base']),
             'valor': _dinero(t['valor'])} for t in impuestos_por_tarifa(lineas)]


def detalle(proforma, permisos, facturable, plan_vencido, hoy=None):
    """`fila` más líneas, impuestos y demás datos de la ficha (§6.4). Conviene leerla con `obtener()`."""
    p = proforma
    lineas = list(p.detalles.all())
    datos = fila(p, permisos, facturable, plan_vencido, hoy)
    empresa = p.company
    datos.update({
        'lineas': [_linea_json(linea) for linea in lineas],
        'impuestos_por_tarifa': impuestos_json(lineas),
        'condiciones': p.condiciones,
        'forma_pago_sugerida': ({'id': p.forma_pago_sugerida, 'nombre': p.get_forma_pago_sugerida_display()}
                                if p.forma_pago_sugerida else None),
        'origen': {'id': int(p.origen_id), 'numero': p.origen.numero_completo} if p.origen_id else None,
        'motivo': p.motivo, 'enviada_a': p.enviada_a,
        'creada_por': _nombre_usuario(p.creada_por) if p.creada_por_id else '',
        'fechas': {'creada': _momento(p.creada_en), 'actualizada': _momento(p.actualizada_en),
                   'enviada': _momento(p.enviada_en), 'aceptada': _momento(p.aceptada_en),
                   'rechazada': _momento(p.rechazada_en), 'anulada': _momento(p.anulada_en),
                   'facturada': _momento(p.facturada_en)},
        'empresa': {'razon_social': empresa.business_name, 'nombre_comercial': empresa.tradename, 'ruc': empresa.ruc},
    })
    return datos


def configuracion_editor(hoy=None):
    hoy = hoy or _hoy()
    return {'hoy': hoy.isoformat(), 'valida_hasta': (hoy + timedelta(days=VALIDEZ_POR_DEFECTO)).isoformat(),
            'validez_por_defecto': VALIDEZ_POR_DEFECTO, 'max_validez': MAX_VALIDEZ, 'max_lineas': MAX_LINEAS,
            'max_destinatarios': MAX_DESTINATARIOS}
