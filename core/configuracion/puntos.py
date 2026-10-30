"""Locales y puntos de emisión por usuario: quién puede emitir desde qué punto y desde cuál emite ahora.

Dos locales del mismo RUC facturan a la vez sin cambiarse el punto ni mezclar numeraciones:
- cada usuario elige su punto (PuntoSeleccionado, por usuario y empresa); el punto predeterminado de la empresa y la
  selección de los demás no cambian;
- cada formulario de emisión lleva el punto con el que se abrió (campo `punto`) y el servidor lo vuelve a validar al
  emitir: pertenencia a la empresa, activo, autorizado para el usuario y numeración confirmada en el ambiente actual;
  si otra pestaña cambió la selección, el documento en curso no se reasigna;
- la numeración sigue en Receipt (una secuencia por empresa, ambiente, punto y tipo) y se reserva con bloqueo de fila
  (Receipt.reservar_numero), así que dos emisiones simultáneas sobre el mismo punto no repiten número.
Todo se valida en el servidor; el identificador que envía el navegador solo indica cuál se pide.
"""
from django.db import transaction
from django.utils import timezone

from core.configuracion import servicios as sv
from core.configuracion.models import PuntoAutorizado, PuntoSeleccionado
from core.pos.choices import ENVIRONMENT_TYPE
from core.pos.models import EmissionPoint, Establishment, Receipt
from core.tenancy.models import ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, Membership, audit

URL = '/configuracion/puntos/'
URL_SELECCIONAR = URL + 'seleccionar/'
ADMINISTRAN = (ROLE_OWNER, ROLE_ADMIN)
# Documentos con numeración por punto, en el orden de la ficha del punto.
TIPOS_POR_PUNTO = sv.DOCUMENTOS + ((sv.TICKET, 'Ticket de venta'),) + sv.OTROS_DOCUMENTOS
CONFIGURABLES = tuple(t for t, _ in sv.DOCUMENTOS + sv.OTROS_DOCUMENTOS)   # el ticket se confirma con la factura

# Mensajes exactos (documentados en HANDOFF para el frontend).
MENSAJES = {
    'elige_punto': 'Elige el punto de emisión desde el que emites (arriba, junto al nombre de la empresa).',
    'punto_desconocido': 'Ese punto de emisión no existe en esta empresa.',
    'punto_inactivo': 'El punto de emisión {punto} está inactivo; elige otro.',
    'punto_no_autorizado': 'No estás autorizado para emitir desde el punto {punto}; elige otro o pide autorización.',
    'sin_membresia': 'Solo los usuarios con un rol en la empresa pueden elegir un punto de emisión.',
    'usuario_ajeno': 'Ese usuario no tiene un rol en esta empresa.',
    'usuario_administra': 'Propietario y Administrador pueden usar todos los puntos; no hace falta autorizarlos.',
    'setup_pendiente': 'Primero completa y confirma la configuración de facturación (pasos 1 a 5).',
    'tipo_no_configurable': 'Ese documento no se configura aquí.',
    'confirmar': 'Marca la confirmación de la numeración indicada.',
    'punto_activado': 'Punto de emisión {punto} activado.',
    'punto_desactivado': 'Punto de emisión {punto} desactivado.',
}


class ErrorPunto(Exception):
    """El punto pedido no se puede usar (mensaje para el usuario)."""


# ---------------------------------------------------------------- quién puede usar qué

def rol_de(user, company):
    """Rol del usuario en la empresa (nombre del grupo) o None si no es miembro; un superusuario actúa como Propietario."""
    if user is None or not user.is_authenticated:
        return None
    membresia = Membership.objects.active().filter(user=user, company=company).select_related('group').first()
    if membresia is not None:
        return membresia.group.name
    return ROLE_OWNER if user.is_superuser else None


def administra(user, company):
    return rol_de(user, company) in ADMINISTRAN


def puntos_activos(company):
    """Puntos activos de establecimientos activos, en el orden de sus códigos."""
    return list(EmissionPoint.all_companies.filter(company=company, is_active=True, establishment__is_active=True)
                .select_related('establishment').order_by('establishment__code', 'code'))


def autorizados_ids(user, company):
    return set(PuntoAutorizado.all_companies.filter(company=company, user=user).values_list('emission_point_id', flat=True))


def elegibles(user, company):
    """Puntos desde los que `user` puede emitir en `company`: los activos; con autorizaciones registradas, solo esas
    (Propietario y Administrador, todos; sin rol en la empresa o rol Cliente, ninguno)."""
    rol = rol_de(user, company)
    if rol is None or rol == ROLE_CLIENT:
        return []
    activos = puntos_activos(company)
    if rol in ADMINISTRAN:
        return activos
    ids = autorizados_ids(user, company)
    return [p for p in activos if p.pk in ids] if ids else activos


def seleccionado(user, company, candidatos=None):
    """Punto elegido por el usuario, si sigue siendo elegible; si no, None."""
    seleccion = PuntoSeleccionado.all_companies.filter(company=company, user=user).first()
    if seleccion is None:
        return None
    candidatos = elegibles(user, company) if candidatos is None else candidatos
    return next((p for p in candidatos if p.pk == seleccion.emission_point_id), None)


def punto_activo(user, company, candidatos=None):
    """Punto desde el que el usuario emite ahora: el elegido; si no hay, el único elegible, o el predeterminado de la
    empresa si es elegible; None si debe elegir."""
    candidatos = elegibles(user, company) if candidatos is None else candidatos
    punto = seleccionado(user, company, candidatos)
    if punto is not None:
        return punto
    if len(candidatos) == 1:
        return candidatos[0]
    return next((p for p in candidatos if p.is_default), None)


def punto_del_formulario(user, company, punto_id):
    """Punto que fijó el formulario (`punto` del POST), validado para el usuario ahora mismo.

    Sin `punto` (formularios y acciones sin selector): el punto activo del usuario; si hay varios elegibles y ninguno
    elegido, ErrorPunto; si la empresa no tiene puntos elegibles, None (servicios.receipt_para_emitir explica qué
    falta configurar, como siempre).
    """
    if punto_id in (None, ''):
        candidatos = elegibles(user, company)
        punto = punto_activo(user, company, candidatos)
        if punto is None and len(candidatos) > 1:
            raise ErrorPunto(MENSAJES['elige_punto'])
        return punto
    try:
        pk = int(punto_id)
    except (TypeError, ValueError):
        raise ErrorPunto(MENSAJES['punto_desconocido'])
    punto = EmissionPoint.all_companies.filter(company=company, pk=pk).select_related('establishment').first()
    if punto is None:
        raise ErrorPunto(MENSAJES['punto_desconocido'])
    if not (punto.is_active and punto.establishment.is_active):
        raise ErrorPunto(MENSAJES['punto_inactivo'].format(punto=punto.full_code))
    if punto.pk not in {p.pk for p in elegibles(user, company)}:
        raise ErrorPunto(MENSAJES['punto_no_autorizado'].format(punto=punto.full_code))
    return punto


def receipt_para_emitir(request, tipo, electronica, punto_id=None):
    """Secuencia con la que se emite `tipo` desde el punto del formulario (o el activo del usuario).

    ErrorPunto si el punto no se puede usar; ConfiguracionPendiente si falta numeración, configuración o firma.
    """
    punto = punto_del_formulario(request.user, request.company, punto_id)
    return sv.receipt_para_emitir(request.company, tipo, electronica, punto=punto)


def contexto_formulario(request, tipo, punto_id=None):
    """Contexto de las pantallas de emisión: el punto fijado al formulario, los elegibles y el próximo número (sin
    reservarlo). `punto_aviso` explica qué falta cuando no se puede emitir desde ese punto."""
    company = request.company
    candidatos = elegibles(request.user, company)
    aviso, punto = None, None
    try:
        punto = punto_del_formulario(request.user, company, punto_id)
    except ErrorPunto as e:
        aviso = str(e)
    proximo = ''
    if punto is not None:
        r = sv.secuencia_configurada(company, tipo, punto=punto)
        if r is not None:
            proximo = r.next_number_full()
        else:
            faltan = sv.requisitos_de_emision(company, tipo, electronica=False, punto=punto)
            aviso = faltan[0]['mensaje'] if faltan else aviso
    return {'punto': punto, 'puntos_elegibles': candidatos, 'punto_proximo': proximo, 'punto_aviso': aviso,
            'punto_ambiente': sv.AMBIENTES.get(company.environment_type)}


def punto_json(punto, company=None):
    """Datos de un punto para el navegador."""
    est = punto.establishment
    item = {'id': punto.pk, 'codigo': punto.code, 'codigo_completo': punto.full_code, 'descripcion': punto.description,
            'activo': punto.is_active and est.is_active, 'predeterminado': punto.is_default,
            'local': {'id': est.pk, 'codigo': est.code, 'nombre': est.name, 'direccion': est.address, 'activo': est.is_active},
            'etiqueta': etiqueta(punto)}
    if company is not None:
        item['listo'] = sv.secuencia_configurada(company, sv.FACTURA, punto=punto) is not None
        # Por qué no se puede emitir desde aquí (None si se puede): inactivo o sin numeración de facturas confirmada.
        if not item['activo']:
            item['bloqueo'] = 'Punto inactivo.'
        elif not item['listo']:
            faltan = sv.requisitos_de_emision(company, sv.FACTURA, electronica=False, punto=punto)
            item['bloqueo'] = faltan[0]['mensaje'] if faltan else None
        else:
            item['bloqueo'] = None
    return item


def etiqueta(punto):
    """«Local Norte · Caja principal · 002-001» (nombre del local o su dirección; descripción del punto o «Punto <código>»)."""
    est = punto.establishment
    return f'{est.name or est.address} · {punto.description or f"Punto {punto.code}"} · {punto.full_code}'


# ---------------------------------------------------------------- selección (cualquier usuario con rol)

def seleccionar(request, punto_id):
    """Guarda el punto elegido por el usuario para la empresa activa. Devuelve el punto."""
    user, company = request.user, request.company
    rol = rol_de(user, company)
    if rol is None or rol == ROLE_CLIENT:
        raise ErrorPunto(MENSAJES['sin_membresia'])
    if punto_id in (None, ''):
        raise ErrorPunto(MENSAJES['punto_desconocido'])
    punto = punto_del_formulario(user, company, punto_id)
    anterior = seleccionado(user, company)
    if anterior is not None and anterior.pk == punto.pk:
        return punto
    PuntoSeleccionado.objects.update_or_create(user=user, defaults={'emission_point': punto})
    audit(request, 'punto_seleccionado', company=company, punto=punto.full_code,
          anterior=anterior.full_code if anterior else None)
    return punto


def seleccion_json(request):
    """Para el selector del frontend: el punto activo, los elegibles y si el usuario administra los puntos."""
    user, company = request.user, request.company
    candidatos = elegibles(user, company)
    activo = punto_activo(user, company, candidatos)
    return {
        'seleccionado': punto_json(activo, company) if activo else None,
        'elegido_por_el_usuario': seleccionado(user, company, candidatos) is not None,
        'elegibles': [punto_json(p, company) for p in candidatos],
        'puede_administrar': rol_de(user, company) in ADMINISTRAN,
        'ambiente': {'codigo': company.environment_type, 'nombre': sv.AMBIENTES.get(company.environment_type)},
        'url_seleccionar': URL_SELECCIONAR,
    }


# ---------------------------------------------------------------- administración (Propietario y Administrador)

def miembros(company):
    """Usuarios con rol de personal en la empresa (sin clientes), con su rol."""
    filas = (Membership.objects.active().filter(company=company).exclude(group__name=ROLE_CLIENT)
             .select_related('user', 'group').order_by('user__names', 'user__username'))
    return [(m.user, m.group.name) for m in filas]


def _miembro(company, usuario_id):
    try:
        pk = int(usuario_id)
    except (TypeError, ValueError):
        raise ErrorPunto(MENSAJES['usuario_ajeno'])
    m = Membership.objects.active().filter(company=company, user_id=pk).exclude(group__name=ROLE_CLIENT) \
        .select_related('user', 'group').first()
    if m is None:
        raise ErrorPunto(MENSAJES['usuario_ajeno'])
    return m.user, m.group.name


def _punto_de_la_empresa(company, punto_id, activo=True):
    try:
        pk = int(punto_id)
    except (TypeError, ValueError):
        raise ErrorPunto(MENSAJES['punto_desconocido'])
    punto = EmissionPoint.all_companies.filter(company=company, pk=pk).select_related('establishment').first()
    if punto is None:
        raise ErrorPunto(MENSAJES['punto_desconocido'])
    if activo and not (punto.is_active and punto.establishment.is_active):
        raise ErrorPunto(MENSAJES['punto_inactivo'].format(punto=punto.full_code))
    return punto


def autorizar(request, usuario_id, punto_id):
    company = request.company
    usuario, rol = _miembro(company, usuario_id)
    if rol in ADMINISTRAN:
        raise ErrorPunto(MENSAJES['usuario_administra'])
    punto = _punto_de_la_empresa(company, punto_id)
    _, creado = PuntoAutorizado.objects.get_or_create(user=usuario, emission_point=punto,
                                                      defaults={'created_by': request.user})
    if creado:
        audit(request, 'punto_autorizado', company=company, usuario=usuario.username, punto=punto.full_code, accion='autorizar')
    return usuario, punto


def quitar_autorizacion(request, usuario_id, punto_id):
    company = request.company
    usuario, _ = _miembro(company, usuario_id)
    punto = _punto_de_la_empresa(company, punto_id, activo=False)
    borrados, _ = PuntoAutorizado.objects.filter(user=usuario, emission_point=punto).delete()
    if borrados:
        audit(request, 'punto_autorizado', company=company, usuario=usuario.username, punto=punto.full_code, accion='quitar')
    return usuario, punto


def activar_punto(request, punto_id, activo):
    """Activa o desactiva un punto (desactivar: misma regla del asistente, sin numeración usada ni predeterminado)."""
    company = request.company
    punto = _punto_de_la_empresa(company, punto_id, activo=False)
    if not activo and (punto.is_default or any(r.is_used for r in punto.sequences.all())):
        raise ErrorPunto(sv.MENSAJES['punto_en_uso'])
    if punto.is_active != activo:
        punto.is_active = activo
        punto.save(update_fields=['is_active'])
        audit(request, 'billing_point_change', company=company, punto=punto.full_code,
              accion='activar' if activo else 'desactivar')
    return punto


def configurar_numeracion(request, punto_id, tipo, ambiente, modo, ultimo_texto='', confirmado=False):
    """Configura y confirma en un solo paso la numeración de `tipo` en `ambiente` para un punto cualquiera de la
    empresa (el asistente sigue configurando el punto predeterminado). Con la factura se confirma también el ticket.
    Nunca retrocede ni reinicia una numeración usada (servicios.configurar_secuencia)."""
    company = request.company
    if sv.obtener_setup(company).completed_at is None:
        raise sv.ErrorConfiguracion(MENSAJES['setup_pendiente'])
    if tipo not in CONFIGURABLES:
        raise sv.ErrorConfiguracion(MENSAJES['tipo_no_configurable'])
    if ambiente not in dict(ENVIRONMENT_TYPE):
        raise sv.ErrorConfiguracion(MENSAJES['tipo_no_configurable'])
    if not confirmado:
        raise sv.ErrorConfiguracion(MENSAJES['confirmar'])
    punto = _punto_de_la_empresa(company, punto_id)
    ahora = timezone.now()
    with transaction.atomic():
        r = sv.configurar_secuencia(company, punto, ambiente, tipo, modo, ultimo_texto, confirmado, request.user, request)
        r.confirmed_at, r.confirmed_by = ahora, request.user
        r.save(update_fields=['confirmed_at', 'confirmed_by'])
        if tipo == sv.FACTURA:
            ticket = sv.secuencia(company, punto, ambiente, sv.TICKET)
            if ticket is None:   # tickets internos (no SRI): empiezan en 1
                ticket = Receipt(company=company, environment_type=ambiente, voucher_type=sv.TICKET,
                                 establishment_code=punto.establishment.code, issuing_point_code=punto.code,
                                 emission_point=punto, sequence=0, origin='nuevo')
            if ticket.confirmed_at is None:
                ticket.confirmed_at, ticket.confirmed_by = ahora, request.user
                ticket.save()
    audit(request, 'billing_setup_confirm', company=company, tipo=tipo, punto=punto.full_code, ambiente=ambiente,
          proximo=r.next_number_full())
    return r


# ---------------------------------------------------------------- estado (catálogo para las pantallas)

def _usadas(company):
    """Secuencias con comprobantes registrados (una consulta por tipo de comprobante)."""
    ids = set()
    for modelo in Receipt.modelos_con_numero():
        ids.update(modelo.all_companies.filter(company=company).values_list('receipt_id', flat=True).distinct())
    return ids


def numeracion_de(company, punto, secuencias, usadas):
    """{ambiente: [{tipo, nombre, existe, ultimo, ultimo_completo, proximo, proximo_completo, confirmado, utilizada,
    origen}]} de un punto; nunca reserva números."""
    filas = {}
    for ambiente, _ in ENVIRONMENT_TYPE:
        filas[ambiente] = []
        for tipo, nombre in TIPOS_POR_PUNTO:
            r = secuencias.get((punto.establishment.code, punto.code, ambiente, tipo))
            filas[ambiente].append({
                'tipo': tipo, 'nombre': nombre, 'existe': r is not None,
                'ultimo': r.sequence if r else None, 'ultimo_completo': r.last_number_full() if r else '',
                'proximo': r.next_number if r else None, 'proximo_completo': r.next_number_full() if r else '',
                'confirmado': bool(r and r.confirmed_at), 'utilizada': bool(r and r.pk in usadas),
                'origen': r.origin if r else None,
            })
    return filas


def estado(request):
    """Catálogo completo: locales con sus puntos (estado, numeración por ambiente y usuarios autorizados), usuarios con
    sus autorizaciones y selección, y la selección del usuario actual."""
    user, company = request.user, request.company
    ambiente = company.environment_type
    secuencias = {(r.establishment_code, r.issuing_point_code, r.environment_type, r.voucher_type): r
                  for r in Receipt.all_companies.filter(company=company)}
    usadas = _usadas(company)
    autorizaciones = {}
    for pa in PuntoAutorizado.all_companies.filter(company=company).select_related('user'):
        autorizaciones.setdefault(pa.emission_point_id, []).append(pa.user)
    personal = miembros(company)
    roles = {u.pk: rol for u, rol in personal}
    selecciones = {s.user_id: s.emission_point_id for s in PuntoSeleccionado.all_companies.filter(company=company)}
    locales = []
    establecimientos = (EmissionPoint.all_companies.filter(company=company).select_related('establishment')
                        .order_by('establishment__code', 'code'))
    por_local = {}
    for punto in establecimientos:
        por_local.setdefault(punto.establishment, []).append(punto)
    for est in Establishment.all_companies.filter(company=company).order_by('code'):
        puntos = []
        for punto in por_local.get(est, []):
            numeracion = numeracion_de(company, punto, secuencias, usadas)
            documentos = [f['tipo'] for f in numeracion[ambiente] if f['confirmado']]
            puntos.append({
                'id': punto.pk, 'codigo': punto.code, 'codigo_completo': punto.full_code, 'descripcion': punto.description,
                'etiqueta': etiqueta(punto), 'activo': punto.is_active and est.is_active, 'predeterminado': punto.is_default,
                'listo': sv.FACTURA in documentos, 'documentos': documentos, 'numeracion': numeracion,
                'usada': any(r.pk in usadas for r in punto.sequences.all()),
                'usuarios_autorizados': [{'id': u.pk, 'username': u.username, 'nombre': u.names, 'rol': roles.get(u.pk)}
                                         for u in autorizaciones.get(punto.pk, [])],
            })
        locales.append({'id': est.pk, 'codigo': est.code, 'nombre': est.name, 'direccion': est.address, 'activo': est.is_active,
                        'puntos': puntos})
    usuarios = []
    for u, rol in personal:
        ids = sorted(p.pk for p in puntos_activos(company)) if rol in ADMINISTRAN else \
            sorted(pa_id for pa_id, users in autorizaciones.items() if u in users)
        usuarios.append({'id': u.pk, 'username': u.username, 'nombre': u.names, 'rol': rol, 'administra': rol in ADMINISTRAN,
                         'autorizados': ids, 'todos': rol in ADMINISTRAN or not ids, 'seleccionado': selecciones.get(u.pk)})
    return {
        'setup_completo': sv.obtener_setup(company).completed_at is not None,
        'ambiente': {'codigo': ambiente, 'nombre': sv.AMBIENTES.get(ambiente)},
        'locales': locales, 'usuarios': usuarios, 'seleccion': seleccion_json(request),
        'tipos': [{'tipo': t, 'nombre': n, 'configurable': t in CONFIGURABLES} for t, n in TIPOS_POR_PUNTO],
        'mensajes': MENSAJES,
    }
