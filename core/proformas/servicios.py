"""Servicios de Proformas: numeración, validación, cálculo, estados, PDF, correo, conversión en factura y JSON de las
pantallas.

Reglas comunes:
- importes en Decimal, cuantizados a centavos (HALF_UP) antes de guardar; en el JSON, texto con 2 decimales;
- toda lectura pasa por `objects` (TenantManager), que falla cerrado sin empresa activa; nunca bulk_create;
- las funciones que escriben van en transaction.atomic() y las que cambian estado bloquean la fila con
  select_for_update(of=('self',)) SIN select_related (en PostgreSQL FOR UPDATE no admite el lado anulable de un join
  externo y, sin `of`, un join interno bloquearía también la otra tabla). En SQLite no tiene efecto;
- el `detail` de AuditLog solo lleva str, int, bool o listas de ellos (el campo no tiene encoder);
- ningún texto escrito por el usuario va a los `messages` de Django (se insertan en un literal JS).
Una proforma no usa Receipt, reservar_numero, cupo, stock, cuentas por cobrar ni el SRI: al facturarla, todo eso lo
hace la venta (SaleCreateView), en cuya transacción la proforma se bloquea antes que la secuencia y se marca al final.
«Convertir en factura» crea o reabre la factura en borrador de la proforma (BorradorFactura, una por proforma), que
tampoco usa nada de eso: solo «Emitir factura» firma y envía (primera-entrega/convertir-en-factura.md).
"""
import json
import logging
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from types import SimpleNamespace

from django.core.exceptions import ObjectDoesNotExist
from django.core.mail import EmailMessage
from django.db import IntegrityError, connection, transaction
from django.db.models import Case, Max, Prefetch, Q, Value, When
from django.template.loader import render_to_string
from django.utils import timezone

from core.pos.choices import (FORMA_PAGO_SRI_DE_MEDIO, NOMBRE_TARIFA_IVA, PAYMENT_METHOD, PAYMENT_TYPE, PORCENTAJE_IVA,
                              TARIFAS_IVA)
from core.pos.clientes import correo_valido, separar_correos, unir_correos
from core.proformas.models import MEDIOS_PAGO_PROFORMA, BorradorFactura, ContadorProforma, Proforma, ProformaDetalle
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
BLOQUEO_ENVIOS = 0x50524F46       # 'PROF': clase del bloqueo consultivo de PostgreSQL que serializa los envíos por empresa
MAX_MENSAJE = 1000
MAX_MOTIVO = 300
MAX_CONDICIONES = 2000
MAX_BUSQUEDA = 100
MAX_FILAS = 1000
MAX_ENTERO = 999999999999   # ids y cantidades recibidos: nunca desbordan una columna de la base
MAX_INFO_ADICIONAL = 15     # campos de <infoAdicional> (informacion_adicional en core/pos/models.py)
MAX_TEXTO_ADICIONAL = 300   # caracteres por campo (XSD del SRI)
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
    'enviada_cambio': ('Proforma {numero} enviada a {destinatarios}, pero mientras salía el correo quedó {estado}: el envío '
                       'se registró y su estado no cambió.'),
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
    # Factura en borrador («Convertir en factura»)
    'con_borrador': ('La proforma {numero} tiene una factura en borrador sin emitir: emítela o descártala antes de '
                     '{accion}.'),
    'sin_borrador': 'La proforma {numero} no tiene una factura en borrador.',
    'borrador_no_existe': 'La factura en borrador ya no existe: se emitió o se descartó. Vuelve a la proforma.',
    'borrador_creado': ('Se creó la factura en borrador de la proforma {numero}. Revísala y pulsa «Emitir factura» para '
                        'enviarla al SRI.'),
    'borrador_abierto': 'La proforma {numero} ya tiene una factura en borrador: se abre esa misma.',
    'borrador_guardado': 'Factura en borrador guardada. No se envió nada al SRI.',
    'borrador_descartado': 'Se descartó la factura en borrador de la proforma {numero}: sigue {estado}.',
    'info_adicional': 'La información adicional admite hasta 15 campos de 300 caracteres como máximo.',
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
    'medio_pago_sugerido': 'Elige un medio de pago de la lista.',
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

# Avisos (duplicar y la precarga de la venta).
AVISOS = {
    'emitir': 'Al guardar se emite la factura y se envía al SRI. Revisa el cliente, los productos y la forma de pago.',
    'producto_eliminado': 'La línea «{descripcion}» no se cargó: el producto ya no existe.',
    'sin_stock': 'No se cargó «{nombre}»: no tiene stock (la proforma pedía {cant}).',
    'stock_parcial': '«{nombre}»: hay {stock} en stock y la proforma pedía {cant}; se cargaron {stock}.',
    'tarifa_cambiada': '«{nombre}»: el IVA cambió de {antes} a {ahora}; la factura usa la tarifa actual.',
    'precio_distinto': '«{nombre}»: se usa el precio de la proforma (USD {precio}) y no el actual (USD {actual}).',
    'descripcion': 'La factura usa el nombre de cada producto, no la descripción escrita en la proforma.',
    'prospecto': 'La proforma es para un prospecto: registra al cliente antes de emitir.',
    'pruebas': ('La empresa está en PRUEBAS: la factura no tendrá validez tributaria y la proforma quedará facturada con '
                'ella. Para volver a cotizar, duplícala.'),
    # Factura en borrador
    'borrador': ('Factura en borrador: todavía no se envió nada al SRI ni se usó número, cupo o stock. Revisa los datos y '
                 'pulsa «Emitir factura» para emitirla.'),
    'notas_recortadas': ('Las condiciones de la proforma pasan a «Notas» en la información adicional, que admite 300 '
                         'caracteres: revisa el texto recortado.'),
    'stock_borrador': '«{nombre}»: el borrador tiene {cant} y hay {stock} en stock. Corrige la cantidad antes de emitir.',
    'tarifa_revisada': '«{nombre}»: esta factura usa IVA {elegida}; el catálogo tiene {catalogo} y no cambia.',
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
                     'eliminar': 'delete_proforma', 'descartar_borrador': 'change_proforma'}
ACCIONES_DE_CONSULTA = ('ver', 'pdf')
# Con una factura en borrador la proforma no se edita, rechaza ni anula (el borrador quedaría desfasado o sin proforma
# facturable): primero se emite o se descarta. Sí se ve, se descarga, se duplica y se reenvía.
BLOQUEADAS_POR_BORRADOR = ('editar', 'rechazar', 'anular')

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
    p = (Proforma.objects.select_related('venta', 'vendedor', 'creada_por', 'origen', 'company',
                                         'borrador_factura__actualizado_por')
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
    if p.venta_id is None and borrador_de(p) is not None:
        acciones = [a for a in acciones if a not in BLOQUEADAS_POR_BORRADOR] + ['descartar_borrador']
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
    medio = _texto(datos, 'medio_pago_sugerido').strip()
    if medio and medio not in dict(MEDIOS_PAGO_PROFORMA):
        campos['medio_pago_sugerido'] = CAMPOS['medio_pago_sugerido']
    elif medio in FORMA_PAGO_SRI_DE_MEDIO:
        forma_pago = FORMA_PAGO_SRI_DE_MEDIO[medio]   # la forma del SRI sale del medio: transferencia → 20
        campos.pop('forma_pago_sugerida', None)
    condiciones = _texto(datos, 'condiciones').replace('\r\n', '\n').strip()
    if len(condiciones) > MAX_CONDICIONES:
        campos['condiciones'] = CAMPOS['condiciones']
    lineas = _validar_lineas(datos, campos)
    if campos:
        raise ErrorProforma(MENSAJES['revisa'], campos=campos)
    cabecera.update(fecha=fecha, valida_hasta=valida_hasta, forma_pago_sugerida=forma_pago, medio_pago_sugerido=medio,
                    condiciones=condiciones, ocultar_vendedor=_si(datos.get('ocultar_vendedor')))
    return cabecera, lineas


def _si(valor):
    """Casilla de un formulario: marcada si llega 'on' (FormData), '1' o 'true'; sin el campo, no marcada."""
    return str(valor if valor is not None else '').strip().lower() in ('on', '1', 'true', 'si', 'sí')


IMPORTES = ('subtotal_gravado', 'subtotal_cero', 'total_iva', 'total_descuento', 'total')   # los que asigna calcular()


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
    _exigir_sin_borrador(p, 'editar')
    cabecera, lineas = validar(datos, p)
    for campo, valor in cabecera.items():
        setattr(p, campo, valor)
    calcular(p, lineas)
    vuelve = p.estado == 'enviada'
    if vuelve:
        p.estado = 'borrador'
    # Solo lo que cambia la edición: nunca venta, facturada_* ni las demás fechas de estado (defensa además del bloqueo:
    # sin él, la CHECK «facturada ⇔ con venta» rechazaría escribir «borrador» sobre una proforma ya facturada).
    p.save(update_fields=[*cabecera, *IMPORTES, 'estado', 'actualizada_en'])
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
                     condiciones=original.condiciones, forma_pago_sugerida=original.forma_pago_sugerida,
                     medio_pago_sugerido=original.medio_pago_sugerido, ocultar_vendedor=original.ocultar_vendedor,
                     origen=original, vendedor=usuario, creada_por=usuario, **datos_cliente)
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
    if accion in BLOQUEADAS_POR_BORRADOR:
        _exigir_sin_borrador(p, accion)
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
            'forma_pago': nombre_forma_pago(proforma),
            # «Ocultar el vendedor en el PDF»: solo aquí (también en la copia del correo); la ficha y la auditoría lo
            # conservan. El emisor es siempre la empresa de la proforma, nunca el nombre del usuario que la preparó.
            'vendedor': _nombre_usuario(proforma.vendedor) if proforma.vendedor_id and not proforma.ocultar_vendedor else '',
            'factura': venta.voucher_number_full if venta else '',
            'factura_pruebas': venta is not None and venta.environment_type != emision.PRODUCCION}


def nombre_forma_pago(proforma):
    """Cómo se lee la forma de pago en la proforma: el medio («Transferencia bancaria») o, sin él, la forma del SRI."""
    if proforma.medio_pago_sugerido and proforma.medio_pago_sugerido != 'otro':
        return proforma.get_medio_pago_sugerido_display()
    if proforma.forma_pago_sugerida:
        return proforma.get_forma_pago_sugerida_display()
    return proforma.get_medio_pago_sugerido_display() if proforma.medio_pago_sugerido else ''


def generar_pdf(proforma):
    from core.pos.utilities import printer
    return printer.create_pdf(contexto_pdf(proforma), 'proformas/pdf.html')


def _nombre_empresa(empresa):
    return empresa.tradename or empresa.business_name


def _envios_de_la_ultima_hora(empresa):
    from core.tenancy.models import AuditLog
    return AuditLog.objects.filter(company=empresa, action='proforma_enviada',
                                   created_at__gte=timezone.now() - timedelta(hours=1)).count()


def _serializar_envios(empresa):
    """Dentro de transaction.atomic(). En PostgreSQL, un bloqueo consultivo por empresa (se suelta al terminar la
    transacción) hace atómicos el conteo del límite por hora, el envío y su registro: un segundo envío simultáneo espera
    y cuenta el primero. Solo espera a otro envío de la misma empresa (no toca la numeración ni las proformas). En
    SQLite no hace nada."""
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s, %s)', [BLOQUEO_ENVIOS, int(empresa.pk) % 2147483648])


def _error_de_correo(p, e):
    logger.warning('No se pudo enviar la proforma %s: %s', p.numero_completo, e.__class__.__name__)
    return ErrorProforma(MENSAJES['correo_fallo'].format(numero=p.numero_completo,
                                                         detalle=f'{e.__class__.__name__}: {str(e)[:200]}'),
                         estado_http=502)


def enviar_por_correo(proforma_id, usuario, destinatarios='', mensaje='', request=None):
    """Envía el PDF por correo (SMTP de la empresa o de la plataforma). borrador → enviada; enviada y aceptada no cambian
    de estado. Si el envío falla no cambia nada. No es un comprobante: no toca VoucherErrors.

    El límite por hora se vuelve a contar, el correo sale y el envío se registra con el bloqueo de envíos de la empresa
    tomado (_serializar_envios): dos envíos simultáneos no pasan juntos el último cupo. La proforma no se bloquea mientras
    sale el correo; si entretanto otra persona la anuló, rechazó o facturó, el envío se registra igual (el correo salió)
    sin tocar su estado y `p.aviso_envio` lo explica (None si no hubo cambio)."""
    from core.pos.utilities.sri import SRI
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
    empresa = p.company
    if _envios_de_la_ultima_hora(empresa) >= LIMITE_ENVIOS_POR_HORA:   # rechazo rápido, sin generar el PDF
        raise ErrorProforma(MENSAJES['limite_envios'], estado_http=409)
    try:
        pdf = generar_pdf(p)
        conexion, remitente, responder = SRI()._correo_saliente(empresa)
        cuerpo = render_to_string('proformas/correo.txt', {
            'proforma': p, 'empresa': _nombre_empresa(empresa), 'total': _dinero(p.total),
            'valida_hasta': _fecha_texto(p.valida_hasta), 'mensaje': mensaje})
        correo = EmailMessage(subject=' '.join(f'Proforma {p.numero_completo} - {_nombre_empresa(empresa)}'.split()),
                              body=cuerpo, from_email=remitente, to=lista, reply_to=responder, connection=conexion)
        correo.attach(f'{p.numero_completo}.pdf', pdf, 'application/pdf')
    except Exception as e:  # noqa: BLE001 - el mensaje explica qué revisar; nada cambió
        raise _error_de_correo(p, e)
    enviada_a = unir_correos(lista, 500)
    with transaction.atomic():
        _serializar_envios(empresa)
        if _envios_de_la_ultima_hora(empresa) >= LIMITE_ENVIOS_POR_HORA:   # el conteo que vale, con el bloqueo tomado
            raise ErrorProforma(MENSAJES['limite_envios'], estado_http=409)
        try:
            correo.send()
        except Exception as e:  # noqa: BLE001 - el mensaje explica qué revisar; nada cambió
            raise _error_de_correo(p, e)
        p = bloquear(p.pk)
        aviso = None
        if p.estado == 'borrador':
            p.estado = 'enviada'
        elif p.estado not in ('enviada', 'aceptada'):   # cambió mientras salía el correo: se registra sin tocar el estado
            aviso = MENSAJES['enviada_cambio'].format(numero=p.numero_completo, destinatarios=enviada_a,
                                                      estado=_estado_guardado(p))
        p.enviada_en = timezone.now()
        p.enviada_a = enviada_a
        p.envios += 1
        p.save(update_fields=['estado', 'enviada_en', 'enviada_a', 'envios', 'actualizada_en'])
        _auditar(request, usuario, 'proforma_enviada', p, destinatarios=len(lista), envio=int(p.envios))
    p.aviso_envio = aviso
    return p


# ---------------------------------------------------------------- conversión en factura (§3.4–§3.6)

def _url_ver(pk):
    return f'{URL_LISTA}ver/{pk}/'


def _error_ya_facturada(p):
    from core.pos.models import Sale
    factura = Sale.all_companies.filter(pk=p.venta_id).values_list('voucher_number_full', flat=True).first() or ''
    return ErrorProforma(MENSAJES['ya_facturada'].format(numero=p.numero_completo, factura=factura), estado_http=409,
                         url=_url_ver(p.pk))


def _error_no_facturable(p, hoy=None):
    if p.esta_vencida(hoy):
        return ErrorProforma(MENSAJES['vencida'].format(numero=p.numero_completo, fecha=_fecha_texto(p.valida_hasta),
                                                        accion=VERBOS['facturar']), estado_http=409, url=_url_ver(p.pk))
    return ErrorProforma(MENSAJES['no_facturable'].format(numero=p.numero_completo, estado=_estado_en_texto(p, hoy)),
                         estado_http=409, url=_url_ver(p.pk))


def _exigir_facturable(p, hoy=None):
    """Sin factura vinculada y «aceptada» o «enviada» vigente. El ambiente no cuenta: en PRUEBAS se factura igual
    (decisión de la propietaria del 28/10/2026) y la pantalla avisa que esa factura no tiene validez tributaria."""
    if p.venta_id is not None:
        raise _error_ya_facturada(p)
    if not (p.estado == 'aceptada' or (p.estado == 'enviada' and not p.esta_vencida(hoy))):
        raise _error_no_facturable(p, hoy)


def _fila_del_pos(producto, cant, linea):
    """Línea en el formato del POS (sale/admin/js/form.js calcula con números): precio y descuento de la proforma."""
    item = producto.toJSON()
    item.update({'cant': int(cant), 'price_current': float(linea.price), 'dscto': float(linea.dscto * 100),
                 'total_dscto': 0.0, 'pvp': float(producto.pvp), 'value': producto.get_full_name()})
    return item


def precarga_para_venta(proforma_id, hoy=None):
    """Datos para abrir la pantalla de venta precargada con la proforma. SOLO LECTURA: no reserva número, cupo ni stock.
    Lanza ErrorProforma con `url` (lista o ficha) si no se puede facturar."""
    from core.pos import emision
    hoy = hoy or _hoy()
    p = Proforma.objects.select_related('cliente__user').filter(pk=_id(proforma_id)).first()
    if p is None:
        raise ErrorProforma(MENSAJES['no_existe'], estado_http=404, url=URL_LISTA)
    _exigir_facturable(p, hoy)
    avisos = [AVISOS['emitir']]
    if require_company().environment_type != emision.PRODUCCION:
        avisos.append(AVISOS['pruebas'])
    lineas, descripcion_distinta = [], False
    for linea in p.detalles.select_related('product__category'):
        producto = linea.product if linea.product_id else None
        if producto is None:
            avisos.append(AVISOS['producto_eliminado'].format(descripcion=linea.descripcion))
            continue
        cant = linea.cant
        if producto.inventoried and producto.stock <= 0:   # como en la venta: no se vende sin stock
            avisos.append(AVISOS['sin_stock'].format(nombre=producto.name, cant=linea.cant))
            continue
        if producto.inventoried and producto.stock < cant:
            cant = producto.stock
            avisos.append(AVISOS['stock_parcial'].format(nombre=producto.name, stock=producto.stock, cant=linea.cant))
        tarifa = tarifa_de_producto(producto)
        if tarifa != linea.codigo_porcentaje:
            avisos.append(AVISOS['tarifa_cambiada'].format(
                nombre=producto.name, antes=NOMBRE_TARIFA_IVA.get(linea.codigo_porcentaje, linea.codigo_porcentaje),
                ahora=NOMBRE_TARIFA_IVA.get(tarifa, tarifa)))
        actual = _cuantizar(producto.get_price_current())
        if linea.price != actual:
            avisos.append(AVISOS['precio_distinto'].format(nombre=producto.name, precio=_dinero(linea.price),
                                                           actual=_dinero(actual)))
        descripcion_distinta = descripcion_distinta or linea.descripcion != producto.name
        lineas.append(_fila_del_pos(producto, cant, linea))
    if not lineas:
        raise ErrorProforma(MENSAJES['sin_lineas_facturables'].format(numero=p.numero_completo), estado_http=409,
                            url=_url_ver(p.pk))
    if descripcion_distinta:
        avisos.append(AVISOS['descripcion'])
    prospecto = None
    if p.cliente_id is None:
        prospecto = {'nombre': p.cliente_nombre, 'identificacion': p.cliente_identificacion, 'correo': p.cliente_correo,
                     'telefono': p.cliente_telefono, 'direccion': p.cliente_direccion}
        avisos.append(AVISOS['prospecto'])
    return {'proforma': {'id': int(p.pk), 'numero': p.numero_completo, 'total': _dinero(p.total),
                         'valida_hasta': p.valida_hasta.isoformat(), 'url_ver': _url_ver(p.pk)},
            'cliente': p.cliente.toJSON() if p.cliente_id else None, 'prospecto': prospecto, 'lineas': lineas,
            'forma_pago': p.forma_pago_sugerida, 'info_adicional': [{'name': 'Proforma', 'value': p.numero_completo}],
            'avisos': avisos}


def bloquear_para_facturar(proforma_id, tipo_comprobante):
    """Dentro de la transacción de la venta y ANTES de reservar su número (orden fijo de bloqueos: proforma → secuencia).
    Una segunda conversión espera aquí, ve la venta vinculada y falla sin gastar número."""
    if str(tipo_comprobante) != '01':
        raise ErrorProforma(MENSAJES['solo_factura'])
    p = bloquear(proforma_id)
    _exigir_facturable(p)
    return p


def _mismas_lineas(proforma, venta):
    def clave(linea):
        return (linea.product_id or 0, int(linea.cant), _cuantizar(linea.price), _cuantizar(linea.dscto))
    return (sorted(clave(l) for l in proforma.detalles.all())
            == sorted(clave(d) for d in venta.saledetail_set.all()))


@transaction.atomic
def marcar_facturada(proforma, venta, usuario, request=None, borrador=None):
    """Vincula la venta y deja la proforma «facturada» con un UPDATE condicional (sin venta y en un estado facturable),
    que no depende del bloqueo (SQLite no bloquea filas) ni de que el objeto en memoria esté al día. Si no actualiza
    exactamente 1 fila lanza ErrorProforma: dentro de la transacción de la venta, eso la deshace entera.

    La factura en borrador de la proforma, si la había, se borra en la misma transacción: ya es esta factura (y si la venta
    se deshace, vuelve con ella). `borrador` es el que se emitió: la auditoría añade su id y las tarifas revisadas."""
    from core.pos.notas_credito import es_consumidor_final
    ahora, hoy = timezone.now(), _hoy()
    cambios = dict(venta=venta, estado='facturada', facturada_en=ahora, facturada_por=usuario, actualizada_en=ahora)
    if proforma.cliente_id is None and not es_consumidor_final(venta.client):
        # El prospecto queda ligado al cliente de la factura (las copias cliente_* no cambian). Facturado a consumidor
        # final sigue como prospecto: un duplicado para volver a cotizar conserva sus datos (misma regla que la venta).
        cambios['cliente_id'] = venta.client_id
    filas = (Proforma.objects.filter(pk=proforma.pk, venta__isnull=True)
             .filter(Q(estado='aceptada') | Q(estado='enviada', valida_hasta__gte=hoy))
             .update(**cambios))
    if filas != 1:
        actual = Proforma.objects.filter(pk=proforma.pk).first()
        if actual is None:
            raise ErrorProforma(MENSAJES['no_existe'], estado_http=404, url=URL_LISTA)
        raise _error_ya_facturada(actual) if actual.venta_id is not None else _error_no_facturable(actual, hoy)
    proforma.refresh_from_db(fields=['venta', 'estado', 'cliente', 'facturada_en', 'facturada_por', 'actualizada_en'])
    BorradorFactura.objects.filter(proforma_id=proforma.pk).delete()
    total_proforma, total_factura = _dinero(proforma.total), _dinero(venta.total)
    extra = {}
    if borrador is not None:
        extra = {'borrador_id': int(borrador.pk), 'tarifas_revisadas': _tarifas_revisadas(venta)}
    _auditar(request, usuario, 'proforma_facturada', proforma, venta_id=int(venta.pk), factura=venta.voucher_number_full,
             total_proforma=total_proforma, total_factura=total_factura,
             coincide=total_proforma == total_factura and _mismas_lineas(proforma, venta),
             ambiente=int(venta.environment_type), **extra)


def _tarifas_revisadas(venta):
    """Líneas de la factura con una tarifa distinta de la del catálogo: ['P0: 15 % → 0 %', …] (texto, para AuditLog)."""
    from core.pos.models import codigo_de_linea
    revisadas = []
    for d in venta.saledetail_set.select_related('product'):
        catalogo, usada = tarifa_de_producto(d.product), codigo_de_linea(d)
        if usada != catalogo:
            revisadas.append(f'{d.product.code}: {NOMBRE_TARIFA_IVA.get(catalogo, catalogo)} → '
                             f'{NOMBRE_TARIFA_IVA.get(usada, usada)}')
    return revisadas


def liberar_por_venta_eliminada(venta):
    """Receptor de pre_delete de la venta (senales.py): la proforma vuelve a «aceptada» si alguna vez se aceptó y si no a
    «enviada», en un solo UPDATE y antes del SET NULL del borrado, así la CHECK «facturada ⇔ con venta» nunca se viola.
    Si el borrado falla después, se deshace con él."""
    import crum

    from core.tenancy.models import audit
    proformas = Proforma.all_companies.filter(company_id=venta.company_id, venta_id=venta.pk)
    filas = list(proformas.values_list('pk', 'numero_completo', 'aceptada_en'))
    if not filas:
        return
    proformas.update(venta=None, facturada_en=None, facturada_por=None, actualizada_en=timezone.now(),
                     estado=Case(When(aceptada_en__isnull=False, then=Value('aceptada')), default=Value('enviada')))
    request = crum.get_current_request()
    for pk, numero, aceptada_en in filas:
        audit(request, 'proforma_venta_eliminada', company=venta.company, proforma=numero, proforma_id=int(pk),
              venta_id=int(venta.pk), factura=venta.voucher_number_full,
              estado='aceptada' if aceptada_en is not None else 'enviada')


# ---------------------------------------------------------------- factura en borrador («Convertir en factura»)

def borrador_de(proforma):
    """Factura en borrador de la proforma, o None. Usa la de select_related('borrador_factura') si se pidió."""
    try:
        return proforma.borrador_factura
    except ObjectDoesNotExist:
        return None


def url_borrador(borrador_id):
    return f'{URL_VENTAS}add/?borrador={int(borrador_id)}'


def _borrador_guardado(proforma_pk):
    return BorradorFactura.objects.filter(proforma_id=proforma_pk).first()


def borrador_de_proforma(proforma_id):
    """Borrador de la proforma `proforma_id` (sin bloqueo), o None. ErrorProforma 404 si el id no es válido."""
    return _borrador_guardado(_id(proforma_id))


def _exigir_sin_borrador(p, accion):
    if _borrador_guardado(p.pk) is not None:
        raise ErrorProforma(MENSAJES['con_borrador'].format(numero=p.numero_completo, accion=VERBOS[accion]),
                            estado_http=409, url=_url_ver(p.pk))


def _info_adicional_inicial(p):
    """«Proforma: PRO-…» (decisión 3: se puede quitar) y las condiciones como «Notas», en un campo de hasta 300 caracteres
    sin saltos de línea (lo que admite <campoAdicional>). Devuelve (campos, avisos)."""
    info, avisos = [{'name': 'Proforma', 'value': p.numero_completo}], []
    notas = ' '.join(p.condiciones.split())
    if notas:
        if len(notas) > MAX_TEXTO_ADICIONAL:
            avisos.append(AVISOS['notas_recortadas'])
        info.append({'name': 'Notas', 'value': notas[:MAX_TEXTO_ADICIONAL]})
    return info, avisos


@transaction.atomic
def convertir(proforma_id, usuario, request=None):
    """«Convertir en factura» → (borrador, creado). Crea la factura en borrador de la proforma con su cliente, líneas
    (cantidad, precio y descuento de la proforma, tarifa de IVA actual del producto), forma y medio de pago, «Proforma» y
    las condiciones como «Notas»; o devuelve la que ya tiene. No reserva número, cupo ni stock, no crea la venta y no firma
    ni envía nada: eso lo hace solo «Emitir factura».

    La proforma se bloquea primero (orden fijo proforma → borrador → secuencia): dos conversiones a la vez (doble clic,
    dos pestañas) se ordenan y la segunda recibe el mismo borrador. Donde no hay bloqueo de filas (SQLite) lo garantiza la
    restricción OneToOne: el INSERT perdedor falla y se devuelve el que ganó."""
    p = bloquear(proforma_id)
    _exigir_facturable(p)
    existente = _borrador_guardado(p.pk)
    if existente is not None:
        return existente, False
    precarga = precarga_para_venta(p.pk)   # las reglas de siempre: sin productos eliminados, stock, tarifa actual
    lineas = [{'product': int(l['id']), 'nombre': l['name'], 'cant': int(l['cant']), 'price': _dinero(l['price_current']),
               'dscto': int(round(l['dscto'])), 'codigo_porcentaje': l['tarifa_iva']} for l in precarga['lineas']]
    info, avisos_notas = _info_adicional_inicial(p)
    propios = (AVISOS['emitir'], AVISOS['pruebas'], AVISOS['prospecto'])   # se calculan al abrir el borrador
    borrador = BorradorFactura(proforma=p, cliente_id=p.cliente_id, payment_type=PAYMENT_TYPE[0][0],
                               payment_method=p.forma_pago_sugerida, medio_cobro=p.medio_pago_sugerido, lineas=lineas,
                               info_adicional=info, avisos=[a for a in precarga['avisos'] if a not in propios] + avisos_notas,
                               creado_por=usuario, actualizado_por=usuario)
    try:
        with transaction.atomic():
            borrador.save()
    except IntegrityError:   # otra conversión lo creó a la vez: se devuelve ese
        return _borrador_guardado(p.pk), False
    _auditar(request, usuario, 'proforma_convertida', p, borrador_id=int(borrador.pk), lineas=len(lineas))
    return borrador, True


def obtener_borrador(borrador_id):
    b = BorradorFactura.objects.select_related('proforma', 'cliente__user').filter(pk=_id(borrador_id)).first()
    if b is None:
        raise ErrorProforma(MENSAJES['borrador_no_existe'], estado_http=404, url=URL_LISTA)
    return b


def tarifas_guardadas(borrador):
    """{producto: tarifa} de las líneas guardadas en el borrador (las que revisó quien podía revisarlas)."""
    return {l['product']: l['codigo_porcentaje'] for l in borrador.lineas}


def _fila_de_borrador(producto, linea):
    """Línea del borrador en el formato del POS, con la tarifa elegida para esta factura (la del catálogo se informa).
    fp_base: el POS no recorta en silencio una cantidad mayor que el stock; avisa y el servidor la valida al emitir."""
    codigo, catalogo = linea['codigo_porcentaje'], tarifa_de_producto(producto)
    item = producto.toJSON()
    item.update({'cant': int(linea['cant']), 'price_current': float(Decimal(linea['price'])), 'dscto': float(linea['dscto']),
                 'total_dscto': 0.0, 'pvp': float(producto.pvp), 'value': producto.get_full_name(),
                 'codigo_porcentaje': codigo, 'tarifa_iva': codigo, 'tarifa': float(PORCENTAJE_IVA.get(codigo, 0)),
                 'nombre_tarifa': NOMBRE_TARIFA_IVA.get(codigo, codigo), 'tarifa_catalogo': catalogo,
                 'nombre_tarifa_catalogo': NOMBRE_TARIFA_IVA.get(catalogo, catalogo), 'fp_base': True})
    return item


def totales_de_borrador(lineas):
    """Importes del borrador con calcular_linea_iva y totales_de_lineas: los mismos que guardará la venta y llevará el XML
    (misma tarifa por línea, cantidad y descuento)."""
    from core.pos.models import calcular_linea_iva, totales_de_lineas
    calculadas = []
    for l in lineas:
        linea = SimpleNamespace(price=Decimal(l['price']), cant=int(l['cant']), dscto=(Decimal(int(l['dscto'])) / 100),
                                product_id=l['product'])
        calcular_linea_iva(linea, l['codigo_porcentaje'])
        calculadas.append(linea)
    gravado, cero, iva, descuento = totales_de_lineas(calculadas)
    return {'subtotal_gravado': _dinero(gravado), 'subtotal_cero': _dinero(cero), 'total_descuento': _dinero(descuento),
            'total_iva': _dinero(iva), 'total': _dinero(gravado + cero + iva), 'impuestos_por_tarifa': impuestos_json(calculadas)}


def precarga_de_borrador(borrador_id, hoy=None):
    """Datos para abrir la venta con la factura en borrador. SOLO LECTURA: no reserva número, cupo ni stock. Mismo formato
    que precarga_para_venta, con la tarifa de cada línea, el pago guardado y `borrador` (id, url y totales calculados como
    los calculará la venta). ErrorProforma con `url` si el borrador ya no existe o la proforma ya no se puede facturar."""
    from core.pos import emision
    from core.pos.models import Product
    hoy = hoy or _hoy()
    b = obtener_borrador(borrador_id)
    p = b.proforma
    _exigir_facturable(p, hoy)
    avisos = [AVISOS['borrador']]
    if require_company().environment_type != emision.PRODUCCION:
        avisos.append(AVISOS['pruebas'])
    avisos += [str(a) for a in (b.avisos or [])]
    ids = [l['product'] for l in b.lineas]
    productos = {x.pk: x for x in Product.objects.select_related('category').filter(pk__in=ids)}
    filas, vigentes = [], []
    for linea in b.lineas:
        producto = productos.get(linea['product'])
        if producto is None:
            avisos.append(AVISOS['producto_eliminado'].format(descripcion=linea.get('nombre', '')))
            continue
        if producto.inventoried and producto.stock < linea['cant']:
            avisos.append(AVISOS['stock_borrador'].format(nombre=producto.name, cant=linea['cant'], stock=producto.stock))
        catalogo = tarifa_de_producto(producto)
        if linea['codigo_porcentaje'] != catalogo:
            avisos.append(AVISOS['tarifa_revisada'].format(
                nombre=producto.name, elegida=NOMBRE_TARIFA_IVA.get(linea['codigo_porcentaje'], linea['codigo_porcentaje']),
                catalogo=NOMBRE_TARIFA_IVA.get(catalogo, catalogo)))
        filas.append(_fila_de_borrador(producto, linea))
        vigentes.append(linea)
    if not filas:
        raise ErrorProforma(MENSAJES['sin_lineas_facturables'].format(numero=p.numero_completo), estado_http=409,
                            url=_url_ver(p.pk))
    prospecto = None
    if b.cliente_id is None and p.cliente_id is None:
        prospecto = {'nombre': p.cliente_nombre, 'identificacion': p.cliente_identificacion, 'correo': p.cliente_correo,
                     'telefono': p.cliente_telefono, 'direccion': p.cliente_direccion}
        avisos.append(AVISOS['prospecto'])
    cliente = b.cliente if b.cliente_id else None
    return {'proforma': {'id': int(p.pk), 'numero': p.numero_completo, 'total': _dinero(p.total),
                         'valida_hasta': p.valida_hasta.isoformat(), 'url_ver': _url_ver(p.pk)},
            'cliente': cliente.toJSON() if cliente is not None else None, 'prospecto': prospecto, 'lineas': filas,
            'forma_pago': b.payment_method, 'medio_cobro': b.medio_cobro, 'condicion_pago': b.payment_type,
            'info_adicional': list(b.info_adicional or []), 'avisos': avisos,
            'tarifas': [{'codigo': c, 'nombre': NOMBRE_TARIFA_IVA.get(c, n), 'tarifa': float(PORCENTAJE_IVA.get(c, 0))}
                        for c, n in TARIFAS_IVA],
            'borrador': {'id': int(b.pk), 'url': url_borrador(b.pk), 'url_ver': _url_ver(p.pk),
                         'actualizado': _momento(b.actualizado_en), 'totales': totales_de_borrador(vigentes)}}


def _borrador_para_cambiar(borrador_id):
    """(proforma bloqueada, borrador), en el orden fijo proforma → borrador; ErrorProforma si el borrador ya no existe."""
    pk = _id(borrador_id)
    proforma_id = BorradorFactura.objects.filter(pk=pk).values_list('proforma_id', flat=True).first()
    if proforma_id is None:
        raise ErrorProforma(MENSAJES['borrador_no_existe'], estado_http=404, url=URL_LISTA)
    p = bloquear(proforma_id)
    b = BorradorFactura.objects.filter(pk=pk, proforma_id=p.pk).first()
    if b is None:
        raise ErrorProforma(MENSAJES['borrador_no_existe'], estado_http=404, url=_url_ver(p.pk))
    return p, b


def _info_adicional(crudo):
    """[{name, value}] de la pantalla de venta: textos de hasta 300 caracteres, como mucho 15 campos; se omiten los vacíos."""
    if isinstance(crudo, str):
        try:
            crudo = json.loads(crudo) if crudo.strip() else []
        except ValueError:
            crudo = None
    if not isinstance(crudo, list):
        raise ErrorProforma(MENSAJES['info_adicional'])
    campos = []
    for item in crudo:
        if not isinstance(item, dict):
            raise ErrorProforma(MENSAJES['info_adicional'])
        nombre, valor = (' '.join(str(item.get(k) or '').split()) for k in ('name', 'value'))
        if not nombre or not valor:
            continue
        if len(nombre) > MAX_TEXTO_ADICIONAL or len(valor) > MAX_TEXTO_ADICIONAL:
            raise ErrorProforma(MENSAJES['info_adicional'])
        campos.append({'name': nombre, 'value': valor})
    if len(campos) > MAX_INFO_ADICIONAL:
        raise ErrorProforma(MENSAJES['info_adicional'])
    return campos


@transaction.atomic
def guardar_borrador(borrador_id, datos, request, usuario):
    """«Guardar borrador» en la venta: cliente, líneas con su tarifa de IVA, pago e información adicional tal como están en
    la pantalla, con las validaciones de la venta (lineas_venta: precio y tarifa distintos del catálogo exigen permiso o
    venir de la proforma o del borrador). No toca número, cupo, stock, el SRI ni el producto del catálogo."""
    from core.pos import lineas_venta
    from core.pos.choices import MEDIOS_DE_PAGO
    from core.pos.models import Client
    p, b = _borrador_para_cambiar(borrador_id)
    lineas = lineas_venta.validar(datos.get('products', ''), tarifas=True)
    lineas_venta.comprobar_precios(request, lineas, p)
    lineas_venta.comprobar_tarifas(request, lineas, tarifas_guardadas(b))
    texto_cliente = str(datos.get('client') or '').strip()
    cliente = None
    if texto_cliente:
        numero = _entero(texto_cliente)
        cliente = Client.objects.filter(pk=numero).first() if numero is not None else None
        if cliente is None:
            raise ErrorProforma(CAMPOS['cliente'])
    condicion = str(datos.get('payment_type') or '').strip()
    forma = str(datos.get('payment_method') or '').strip()
    medio = str(datos.get('medio_cobro') or '').strip()
    if condicion not in dict(PAYMENT_TYPE):
        raise ErrorProforma('Elige la condición de pago: contado o crédito.')
    if forma and forma not in dict(PAYMENT_METHOD):
        raise ErrorProforma('Elige la forma de pago del SRI.')
    if medio and medio not in dict(MEDIOS_DE_PAGO):
        raise ErrorProforma('Elige el medio de cobro.')
    b.cliente, b.payment_type, b.payment_method, b.medio_cobro = cliente, condicion, forma, medio
    b.lineas = [{'product': int(l['producto'].pk), 'nombre': l['producto'].name, 'cant': int(l['cant']),
                 'price': _dinero(l['precio']), 'dscto': int((l['dscto'] * 100).to_integral_value()),
                 'codigo_porcentaje': l['tarifa']} for l in lineas]
    b.info_adicional = _info_adicional(datos.get('additional_info', '[]'))
    b.avisos = []   # los de la conversión ya se revisaron; los de stock y tarifa se recalculan al abrirlo
    b.actualizado_por = usuario
    b.save()
    return b


@transaction.atomic
def descartar_borrador(proforma_id, usuario, request=None):
    """Borra la factura en borrador: la proforma queda como estaba (nunca cambió de estado) y se puede editar, anular o
    convertir de nuevo. Nada que deshacer en número, cupo, stock o SRI, porque el borrador no los usó."""
    p = bloquear(proforma_id)
    b = _borrador_guardado(p.pk)
    if b is None:
        raise ErrorProforma(MENSAJES['sin_borrador'].format(numero=p.numero_completo), estado_http=409, url=_url_ver(p.pk))
    borrador_id = int(b.pk)
    b.delete()
    _auditar(request, usuario, 'proforma_borrador_descartado', p, borrador_id=borrador_id)
    return p


def descartar_borrador_por_id(borrador_id, usuario, request=None):
    proforma_id = BorradorFactura.objects.filter(pk=_id(borrador_id)).values_list('proforma_id', flat=True).first()
    if proforma_id is None:
        raise ErrorProforma(MENSAJES['borrador_no_existe'], estado_http=404, url=URL_LISTA)
    return descartar_borrador(proforma_id, usuario, request)


def borrador_para_emitir(proforma, borrador_id):
    """Dentro de la transacción de la venta, con la proforma ya bloqueada: el borrador que se emite, de ESA proforma."""
    b = BorradorFactura.objects.filter(pk=_id(borrador_id), proforma_id=proforma.pk).first()
    if b is None:
        raise ErrorProforma(MENSAJES['borrador_no_existe'], estado_http=409, url=_url_ver(proforma.pk))
    return b


def _borrador_json(b):
    if b is None:
        return None
    return {'id': int(b.pk), 'url': url_borrador(b.pk), 'actualizado': _momento(b.actualizado_en),
            'actualizado_por': _nombre_usuario(b.actualizado_por) if b.actualizado_por_id else ''}


# ---------------------------------------------------------------- consultas y JSON de las pantallas

def consultar(estado='', desde='', hasta='', q='', hoy=None):
    """Proformas de la lista (como mucho MAX_FILAS, las más recientes primero), sin consultas por fila."""
    hoy = hoy or _hoy()
    qs = Proforma.objects.select_related('venta', 'vendedor', 'borrador_factura')
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
            # «Ya facturada»: enlace directo a esa factura (su RIDE si está autorizada; si no, su comprobante impreso).
            'url_factura': (f'{URL_VENTAS}print/a4/{venta.pk}/' if venta.status in ESTADOS_RIDE
                            else f'{URL_VENTAS}print/invoice/{venta.pk}/'),
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
        'medio_pago_sugerido': ({'id': p.medio_pago_sugerido, 'nombre': p.get_medio_pago_sugerido_display()}
                                if p.medio_pago_sugerido else None),
        'forma_pago': nombre_forma_pago(p),   # como se lee en el PDF
        'ocultar_vendedor': p.ocultar_vendedor,
        'borrador_factura': _borrador_json(borrador_de(p)) if p.venta_id is None else None,
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
            'max_destinatarios': MAX_DESTINATARIOS, 'forma_sri_de_medio': dict(FORMA_PAGO_SRI_DE_MEDIO)}
