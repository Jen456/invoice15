"""Contrato de capacidades del Complemento Contable: el único lugar que decide y explica por qué una función contable o
tributaria se puede usar o no. Separa cuatro causas que el aviso genérico «todavía no está disponible» mezclaba:

- licencia: la empresa no tiene el complemento habilitado, no tiene plan pagado o lo tiene vencido (solo consulta);
- permiso: el rol del usuario en la empresa activa no incluye la función;
- módulo pendiente: la función todavía no está construida (con qué falta y, si la hay, la decisión que espera);
- datos: está construida y permitida, pero antes hay que completar algo (lo que devuelven sus requisitos).

Esto NO cambia quién entra. La puerta sigue siendo PlanMiddleware (plan pagado + `complemento_habilitado`); aquí solo se
calcula la explicación, con las mismas funciones y en el mismo orden que el middleware, para que la respuesta nunca diga
otra cosa que lo que el middleware hace. Tampoco cambia precios, planes ni cobertura."""
from dataclasses import dataclass

from django.http import JsonResponse

from core.security.session import get_group
from core.suscripciones.middleware import mensaje_de_bloqueo, puede_gestionar_plan
from core.suscripciones.reglas import MENSAJE_COMPLEMENTO, URL_SUSCRIPCION
from core.suscripciones.servicios import estado_de_peticion

# Estados de la licencia. Con PLAN_VENCIDO se consulta pero no se guarda nada: el middleware corta los envíos y, como se
# le escapa un formulario con un campo `action` de consulta, api.ApiContable lo repite en los suyos (rechazo_de_licencia).
ACTIVA, PLAN_REQUERIDO, PLAN_VENCIDO, COMPLEMENTO_PENDIENTE = 'activa', 'plan_requerido', 'plan_vencido', 'complemento_pendiente'
SIN_ACCESO = (PLAN_REQUERIDO, COMPLEMENTO_PENDIENTE)   # ni consulta

# Estados de una función y su causa. Precedencia: módulo pendiente → licencia → permiso → datos → disponible.
DISPONIBLE, SIN_LICENCIA, SIN_PERMISO = 'disponible', 'sin_licencia', 'sin_permiso'
MODULO_PENDIENTE, DATOS_POR_COMPLETAR = 'modulo_pendiente', 'datos_por_completar'
CAUSAS = {DISPONIBLE: None, SIN_LICENCIA: 'licencia', SIN_PERMISO: 'permiso', MODULO_PENDIENTE: 'modulo_pendiente',
          DATOS_POR_COMPLETAR: 'datos'}

TRIBUTARIO, CONTABILIDAD = 'tributario', 'contabilidad'
PENDIENTE = 'pendiente'   # construcción de una función: DISPONIBLE o PENDIENTE

TEXTO_SIN_PERMISO = 'Tu perfil no cuenta con el permiso necesario.'
TEXTO_DATOS = 'Faltan datos por completar antes de usar esta función.'


# ---------------------------------------------------------------- licencia

def licencia(request):
    """Licencia del Complemento Contable para la empresa activa:
    `{"estado", "solo_consulta", "texto", "puede_gestionar", "url"}`.

    Mismas condiciones y mismo orden que PlanMiddleware en /tributario/ y /contabilidad/: primero el complemento (sin
    habilitar, ningún plan lo abre), después el plan pagado y, vencido, solo consulta. `texto` es el mensaje que el
    middleware pone en su 403. `url` es dónde lo resuelve quien puede gestionar el plan; el complemento todavía no se
    contrata en ningún sitio (D9), así que cerrado no lleva enlace."""
    estado = estado_de_peticion(request)
    gestiona = puede_gestionar_plan(request)
    if estado is None or not estado.complemento:
        return _licencia(COMPLEMENTO_PENDIENTE, MENSAJE_COMPLEMENTO, gestiona)
    if estado.gratuito:
        return _licencia(PLAN_REQUERIDO, mensaje_de_bloqueo(estado), gestiona, del_plan=True)
    if estado.vencido:
        return _licencia(PLAN_VENCIDO, mensaje_de_bloqueo(estado), gestiona, del_plan=True, solo_consulta=True)
    return _licencia(ACTIVA, None, gestiona)


def _licencia(estado, texto, gestiona, del_plan=False, solo_consulta=False):
    return {'estado': estado, 'solo_consulta': solo_consulta, 'texto': texto, 'puede_gestionar': gestiona,
            'url': URL_SUSCRIPCION if del_plan and gestiona else None}


# ---------------------------------------------------------------- registro de funciones

@dataclass(frozen=True)
class Funcion:
    """Una función del complemento, tal como la ve el contrato.

    `permisos`: acción → codename, o tupla de codenames si basta uno. Toda función tiene la acción `ver`: sin su permiso
    la función entera es `sin_permiso`. Cualquier otra acción guarda algo, así que con el plan vencido queda en falso.
    `requisitos`: funciones `(request) → [dato(...)]` con lo que falta por completar (lista vacía: nada).
    `avisos`: funciones `(request) → [aviso(...)]` con lo pendiente que no impide usarla (decisión común 10 del bloque 2;
    lo que sí lo impide va en `requisitos`). Se consultan, como los requisitos, solo para quien puede usarla.
    `ruta`: la que la sirve; tests/test_capacidades.py vigila que una función disponible la tenga publicada y que una
    pendiente no (quien construya la ruta cambia aquí `construccion`)."""
    codigo: str
    nombre: str
    ambito: str
    permisos: dict
    construccion: str = DISPONIBLE
    que_falta: str = ''    # pendiente: qué falta, en palabras para el usuario
    decision: str = ''     # pendiente: la decisión que espera, si la hay
    requisitos: tuple = ()
    ruta: str = ''
    avisos: tuple = ()

    @property
    def texto_pendiente(self):
        return ' '.join(t for t in (self.que_falta, self.decision) if t)


# Los permisos de un módulo pendiente se fijan al construirlo: hasta entonces su única acción es `ver`, sin codename.
POR_DEFINIR = {'ver': None}


# ---------------------------------------------------------------- requisito y avisos de la apertura (bloque 2, Parte B)
# Se evalúan por petición, en la empresa activa, y solo para quien puede usar la función. Importan los modelos al usarse:
# los módulos de la apertura importan este registro.

def _plan_cuentas_vacio(request):
    """Sin ninguna cuenta de movimiento activa no hay dónde llevar un saldo: crear la apertura lo pide antes."""
    from core.contabilidad.models import Cuenta
    if Cuenta.objects.filter(tipo='movimiento', activa=True).exists():
        return []
    return [dato('plan_cuentas_vacio', 'Crea o importa el plan de cuentas: no tiene ninguna cuenta de movimiento activa.')]


_PLAN = {'tipo': 'plan_cuentas', 'id': None, 'api': '/contabilidad/api/cuentas/'}


def _cuentas_sin_clase(request):
    """Cuentas de movimiento activas sin clase: la apertura no se confirma con una de ellas (`cuenta_sin_clase`) y los
    estados no saben dónde ponerlas. La clase la declara una persona; nunca se deduce del código."""
    from core.contabilidad.models import Cuenta
    n = Cuenta.objects.filter(tipo='movimiento', activa=True, clase='').count()
    return [aviso('cuentas_sin_clase', f'{n} cuenta(s) de movimiento no tienen clase (activo, pasivo, patrimonio, ingreso, '
                  'costo o gasto): decláralas antes de confirmar la apertura.', n, recurso=_PLAN)] if n else []


def _apertura_de_trabajo():
    """`(id, ambitos_no_aplican)` de la apertura en preparación o, si no la hay, de la confirmada (la que muestra GET
    /contabilidad/api/apertura/), o None."""
    from core.contabilidad.models import Apertura
    filas = list(Apertura.objects.filter(estado__in=('borrador', 'en_revision', 'confirmada'))
                 .values_list('id', 'estado', 'ambitos_no_aplican'))
    filas.sort(key=lambda f: f[1] == 'confirmada')   # la que está en preparación primero
    return (filas[0][0], filas[0][2]) if filas else None


def _cuentas_sin_auxiliar(request):
    """Ámbitos de detalle sin ninguna cuenta que lo declare ni declaración de que no aplica: su cobertura queda pendiente
    (`sin_cuenta_declarada`), porque no marcar una cuenta no prueba que no haya cartera."""
    from core.contabilidad.cobertura import DETALLE_DE, NOMBRE
    from core.contabilidad.models import Cuenta
    declarados = set(Cuenta.objects.filter(tipo='movimiento', activa=True).exclude(auxiliar='')
                     .values_list('auxiliar', flat=True).distinct())
    trabajo = _apertura_de_trabajo()
    no_aplican = {d.get('ambito') for d in (trabajo[1] if trabajo else None) or [] if isinstance(d, dict)}
    faltan = [a for a, detalle in DETALLE_DE.items() if detalle not in declarados and a not in no_aplican]
    if not faltan:
        return []
    return [aviso('cuentas_sin_auxiliar', 'Ninguna cuenta está declarada como de ' + ', '.join(NOMBRE[a] for a in faltan)
                  + ': su cobertura queda pendiente hasta declarar la cuenta o que no aplica.', len(faltan), recurso=_PLAN)]


def _auxiliares_incompletos(request):
    """Líneas de la apertura de trabajo con detalle (Cuenta.auxiliar) cuyo saldo no está explicado del todo (o es
    desconocido). Dos consultas: las líneas con detalle y lo detallado por línea."""
    from django.db.models import Sum
    from core.contabilidad.models import AuxiliarApertura, LineaApertura
    trabajo = _apertura_de_trabajo()
    if trabajo is None:
        return []
    detallado = dict(AuxiliarApertura.objects.filter(apertura_id=trabajo[0], estado='vigente').order_by().values('linea')
                     .annotate(total=Sum('saldo_inicial')).values_list('linea', 'total'))
    n = sum(1 for pk, debe, haber in LineaApertura.objects.filter(apertura_id=trabajo[0], retirada=False).exclude(detalle='')
            .values_list('id', 'debe', 'haber')
            if debe is None or haber is None or detallado.get(pk, 0) < debe + haber)
    return [aviso('auxiliares_incompletos', f'{n} cuenta(s) de la apertura tienen su detalle (clientes, proveedores, '
                  'inventario…) incompleto.', n, recurso={'tipo': 'apertura', 'id': trabajo[0],
                                                         'api': f'/contabilidad/api/apertura/{trabajo[0]}/lineas/'})] if n else []


def _vinculos_rotos(request):
    """Auxiliares vigentes de la apertura de trabajo enlazados a una cuenta por cobrar o por pagar, o a un documento
    importado, que ya no existe. Hoy no los crea nada (los vínculos son del corte 2): la consulta ya responde por ellos.
    Es la misma que bloquea validar y confirmar (`vinculo_roto`, cobertura.vinculos_rotos)."""
    from core.contabilidad.cobertura import vinculos_rotos
    trabajo = _apertura_de_trabajo()
    if trabajo is None:
        return []
    n = len(vinculos_rotos(trabajo[0]))
    return [aviso('vinculos_rotos', f'{n} auxiliar(es) de la apertura están vinculados a un documento que ya no existe: '
                  'desvincúlalos con su motivo.', n, recurso={'tipo': 'apertura', 'id': trabajo[0],
                                                              'api': f'/contabilidad/api/apertura/{trabajo[0]}/'})] if n else []

FUNCIONES = (
    Funcion('libros', 'Libros mensuales', TRIBUTARIO, {'ver': 'view_libros'}, ruta='/tributario/libros/'),
    Funcion('revision', 'Revisión del mes', TRIBUTARIO, {'ver': 'view_revision'}, ruta='/tributario/revision/'),
    Funcion('ats', 'ATS del mes', TRIBUTARIO, {'ver': 'view_libros'}, ruta='/tributario/ats/'),
    Funcion('formularios', 'Borradores del 104 y del 103', TRIBUTARIO, {'ver': 'view_libros'}, ruta='/tributario/formularios/'),
    Funcion('kardex', 'Kardex por producto', CONTABILIDAD,
            {'ver': 'view_kardex', 'registrar': 'add_movimientomanual', 'anular': 'change_movimientomanual'},
            ruta='/contabilidad/kardex/'),
    Funcion('inventario', 'Inventario valorizado', CONTABILIDAD, {'ver': 'view_kardex'}, ruta='/contabilidad/inventario/'),
    # Bloque 1 (C2, C3 y C1 del contrato v9).
    Funcion('plan_cuentas', 'Plan de cuentas', CONTABILIDAD,
            # `editar` incluye activar y desactivar: una cuenta no se borra.
            {'ver': 'view_cuenta', 'crear': 'add_cuenta', 'editar': 'change_cuenta'}, ruta='/contabilidad/api/cuentas/'),
    Funcion('importar_cuentas', 'Importación del plan de cuentas', CONTABILIDAD,
            # No hay un permiso de «ver» aparte: la vista previa es de quien puede crear cuentas. Actualizar el nombre
            # de las que ya existen pide además editar.
            {'ver': 'add_cuenta', 'importar': 'add_cuenta', 'actualizar_nombre': 'change_cuenta'},
            ruta='/contabilidad/api/cuentas/importar/'),
    # Lo abre quien ve el kardex, la revisión del mes o el plan de cuentas: basta uno.
    Funcion('inicio', 'Inicio contable', CONTABILIDAD, {'ver': ('view_kardex', 'view_revision', 'view_cuenta')},
            ruta='/contabilidad/api/inicio/'),
    # Bloques siguientes de la orden de cierre. La decisión citada bloquea su regla o su activación, no la construcción.
    Funcion('evidencias', 'Evidencias de presentación', TRIBUTARIO, POR_DEFINIR, construccion=PENDIENTE,
            que_falta='El registro de evidencias de presentación del 104, del 103 y del ATS está en construcción.'),
    # Bloque 2 · Parte B (vistas_apertura.py). `confirmar` (change_confirmacion_apertura) lo añade la parte siguiente del
    # corte 1 al publicar su ruta: nada se anuncia sin ella.
    Funcion('apertura', 'Apertura contable', CONTABILIDAD, {'ver': 'view_apertura', 'preparar': 'add_apertura'},
            requisitos=(_plan_cuentas_vacio,),
            avisos=(_cuentas_sin_clase, _cuentas_sin_auxiliar, _auxiliares_incompletos, _vinculos_rotos),
            ruta='/contabilidad/api/apertura/'),
    Funcion('cartera_inicial', 'Cobros y pagos sobre saldos iniciales', CONTABILIDAD, POR_DEFINIR, construccion=PENDIENTE,
            que_falta='Los cobros, pagos y descargos sobre los saldos iniciales de la apertura están en construcción.'),
    Funcion('historico', 'Documentos anteriores al corte', CONTABILIDAD, POR_DEFINIR, construccion=PENDIENTE,
            que_falta='El destino de los documentos importados anteriores al corte (consulta, completar un auxiliar o '
                      'reconstrucción) está en construcción.'),
    Funcion('asientos', 'Asientos por comprobante', CONTABILIDAD, POR_DEFINIR, construccion=PENDIENTE,
            que_falta='Los asientos por comprobante están en construcción.',
            # D7
            decision='La matriz de asientos está por validar con un contador: una regla sin aprobar quedará como '
                     'excepción, sin contabilizar.'),
    # Bloque 2 (Parte A): el diario y su comprobación de integridad, solo para ver; el bloque 3 añade `exportar`.
    Funcion('diario_mayor', 'Diario, mayor y balance de comprobación', CONTABILIDAD, {'ver': 'view_asiento'},
            ruta='/contabilidad/api/diario/'),
    Funcion('bancos', 'Bancos y conciliación', CONTABILIDAD, POR_DEFINIR, construccion=PENDIENTE,
            que_falta='Bancos y conciliación están en construcción.',
            # D6
            decision='Los formatos de extracto de cada banco esperan muestras reales; un CSV con columnas a elegir no '
                     'depende de ellas.'),
    Funcion('cierre', 'Cierre y reapertura de mes', CONTABILIDAD, POR_DEFINIR, construccion=PENDIENTE,
            que_falta='El cierre y la reapertura de mes están en construcción.',
            # Lista de decisiones n.º 8
            decision='Falta decidir qué impide un mes cerrado y quién puede cerrarlo o reabrirlo.'),
    Funcion('estados_financieros', 'Estados financieros', CONTABILIDAD, POR_DEFINIR, construccion=PENDIENTE,
            que_falta='Los estados financieros están en construcción: salen de la apertura, los asientos y el mayor.',
            # D5
            decision='La correspondencia de las cuentas con el catálogo de la Superintendencia de Compañías está por '
                     'decidir.'),
    Funcion('formulario_101', 'Preparación del formulario 101', TRIBUTARIO, POR_DEFINIR, construccion=PENDIENTE,
            que_falta='La preparación del formulario 101 está en construcción: sale de los estados financieros y de la '
                      'conciliación tributaria.',
            # NORMA-CONTABLE-TRIBUTARIA-2026-10: numeración de casilleros sin confirmar
            decision='La numeración vigente de sus casilleros y la fórmula de la conciliación tributaria están por '
                     'confirmar.'),
)


def funcion_de(codigo):
    """La función registrada con ese código (KeyError si no existe: es un error de programación, no del usuario)."""
    for funcion in FUNCIONES:
        if funcion.codigo == codigo:
            return funcion
    raise KeyError(codigo)


def dato(codigo, texto, url=None):
    """Un dato por completar, con la forma del contrato (lo que devuelve un requisito y lleva `faltan`)."""
    return {'codigo': codigo, 'texto': texto, 'url': url}


def aviso(codigo, texto, cantidad=None, url=None, recurso=None, decision=None):
    """Un aviso (decisión común 10 del bloque 2): algo pendiente que no impide usar la función. `url` solo si hay una
    página que ya existe; si no, `recurso` con su ruta de API. `decision` solo si depende de una decisión de plataforma."""
    return {'codigo': codigo, 'texto': texto, 'cantidad': cantidad, 'url': url, 'recurso': recurso, 'decision': decision}


# ---------------------------------------------------------------- resolución

def codigos(request):
    """Permisos (codenames) del rol del usuario en la empresa activa, leídos una vez por petición."""
    if not hasattr(request, '_fpa_codigos'):
        grupo = get_group(request)
        request._fpa_codigos = frozenset(grupo.permissions.values_list('codename', flat=True)) if grupo is not None else frozenset()
    return request._fpa_codigos


def tiene(request, permiso):
    """El rol tiene el permiso: un codename o, si es una tupla, cualquiera de ellos. Sin codename (por definir), no."""
    if not permiso:
        return False
    if isinstance(permiso, str):
        return permiso in codigos(request)
    return any(p in codigos(request) for p in permiso)


def _resolver(funcion, lic, request):
    acciones = dict.fromkeys(funcion.permisos, False)
    estado, texto, faltan, avisos = DISPONIBLE, None, [], []
    if funcion.construccion == PENDIENTE:
        estado, texto = MODULO_PENDIENTE, funcion.texto_pendiente
    elif lic['estado'] in SIN_ACCESO:
        estado, texto = SIN_LICENCIA, lic['texto']
    elif not tiene(request, funcion.permisos['ver']):
        estado, texto = SIN_PERMISO, TEXTO_SIN_PERMISO
    else:
        # Los requisitos solo se consultan para quien ya puede ver la función: no revelan datos a quien no la tiene.
        faltan = [d for requisito in funcion.requisitos for d in requisito(request)]
        if faltan:
            estado, texto = DATOS_POR_COMPLETAR, TEXTO_DATOS
        else:
            for accion, permiso in funcion.permisos.items():
                acciones[accion] = tiene(request, permiso) and (accion == 'ver' or not lic['solo_consulta'])
            avisos = [a for consulta in funcion.avisos for a in consulta(request)]
    return {'nombre': funcion.nombre, 'ambito': funcion.ambito, 'estado': estado, 'causa': CAUSAS[estado], 'texto': texto,
            'acciones': acciones, 'faltan': faltan, 'avisos': avisos}


def estado_de(request, codigo):
    """Una función resuelta para esta petición: `{"nombre", "ambito", "estado", "causa", "texto", "acciones", "faltan",
    "avisos"}`."""
    return _resolver(funcion_de(codigo), licencia(request), request)


def acciones(request, codigo):
    """Qué puede hacer el usuario en esa función ahora (`{accion: bool}`), ya con licencia, permiso y datos."""
    return estado_de(request, codigo)['acciones']


def faltantes(request, codigo):
    """Datos por completar de esa función para esta empresa (lista vacía: ninguno), sin mirar licencia ni permiso: es lo
    que una vista ya autorizada pasa a `rechazo_datos`."""
    return [d for requisito in funcion_de(codigo).requisitos for d in requisito(request)]


def empresa_de(request):
    empresa = request.company
    return {'id': empresa.pk, 'ruc': empresa.ruc, 'nombre': empresa.business_name}


def capacidades(request):
    """`{"empresa": {"id", "ruc", "nombre"}, "licencia": {…}, "funciones": {codigo: {…}}}` para la empresa activa y el rol
    del usuario. No lleva ningún dato contable: es lo que GET /contabilidad/api/capacidades/ responde también con el
    complemento cerrado."""
    lic = licencia(request)
    return {'empresa': empresa_de(request), 'licencia': lic,
            'funciones': {f.codigo: _resolver(f, lic, request) for f in FUNCIONES}}


# ---------------------------------------------------------------- respuestas para las vistas nuevas

def rechazo_sin_permiso(codename=None, texto=None):
    """403 JSON (también en GET). `permisos`: los codenames que lo habrían permitido (basta uno); vacío si lo que se pide
    es un rol de personal y no un permiso concreto."""
    permisos = [codename] if isinstance(codename, str) else list(codename or ())
    return JsonResponse({'error': texto or TEXTO_SIN_PERMISO, 'codigo': 'sin_permiso', 'causa': 'permiso', 'permisos': permisos},
                        status=403)


def rechazo_datos(faltan, texto=None):
    """409 JSON: la función existe y el usuario puede usarla, pero antes hay que completar `faltan` (`[dato(...)]`)."""
    return JsonResponse({'error': texto or TEXTO_DATOS, 'codigo': 'datos_por_completar', 'causa': 'datos', 'faltan': list(faltan)},
                        status=409)
