"""Ayudantes comunes de las rutas nuevas de /contabilidad/api/ (contrato contable v9): cuerpo del envío, empresa de la
pestaña, permiso del rol, formato de errores y clave de idempotencia.

Toda negativa de estas rutas es JSON, también en GET, y siempre en el mismo orden:

1. sin sesión → lo de todo el proyecto (302 al inicio de sesión). Con sesión y sin empresa activa también responde el
   proyecto antes de llegar aquí (CompanyMiddleware): a un GET, 302 a /empresas/; a un envío, 403 sin `codigo`. Son las
   dos únicas respuestas que no tienen la forma de esta lista, y el contrato las documenta como excepciones;
2. empresa: `empresa` que no es la activa → 409 `empresa_cambiada`; en un envío (POST, PATCH…) es obligatoria y sin ella
   → 409 `sin_empresa`. Se lee de `?empresa=` o del envío (`"empresa"` del JSON o, en un POST, campo del formulario);
3. licencia → 403 de PlanMiddleware (corre antes que la vista; ante un envío para otra empresa responde primero el 409).
   El del plan vencido lo repite aquí la vista en cada envío (`rechazo_de_licencia`): al middleware se le escapa un
   formulario que lleve un campo `action` de consulta;
4. permiso del rol → 403 `sin_permiso`;
5. datos por completar → 409 `datos_por_completar` (capacidades.rechazo_datos);
6. validación → 400 `{"error", "codigo", "errores": {campo: [textos]}}`, con todos los errores de campo a la vez.

Las rutas que ya existían (kardex, tributario) no usan esto y no cambian."""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views import View

from core.contabilidad import capacidades as cap
from core.contabilidad.servicios import CLAVE
from core.security.session import get_group
from core.tenancy.models import ROLE_CLIENT
from core.tenancy.pestanas import cuerpo_json, rechazo_empresa_cambiada

LECTURA = ('GET', 'HEAD')
# En `permisos` de una vista: no pide un permiso concreto, basta un rol de personal de la empresa (cualquiera menos Cliente).
PERSONAL = object()

SIN_EMPRESA = 'El envío no indica para qué empresa se preparó: vuelve a cargar la página e inténtalo de nuevo.'
TEXTOS = {
    'cuerpo': 'El envío no se pudo leer: debe ser un objeto JSON.',
    'clave': 'Falta la clave del envío: vuelve a cargar la página e inténtalo de nuevo.',
    'validacion': 'Revisa los datos marcados.',
    'metodo': 'Esta ruta no admite ese método.',
}


# ---------------------------------------------------------------- errores

def error(texto, estado=400, codigo=None, errores=None, **extra):
    """Respuesta de error con la forma del contrato: `{"error": texto[, "codigo"][, "errores": {campo: [textos]}], …}`."""
    datos = {'error': texto}
    if codigo:
        datos['codigo'] = codigo
    if errores is not None:
        datos['errores'] = errores
    datos.update(extra)
    return JsonResponse(datos, status=estado)


class ErrorApi(Exception):
    """Negativa que un servicio o una vista lanza y ApiContable convierte en su respuesta JSON. `extra` viaja tal cual en
    el cuerpo (por ejemplo `cuenta={…}` en un 409 `version`)."""

    def __init__(self, codigo, texto=None, estado=400, errores=None, **extra):
        super().__init__(texto or TEXTOS[codigo])
        self.codigo, self.estado, self.errores, self.extra = codigo, estado, errores, extra

    def respuesta(self):
        return error(str(self), self.estado, self.codigo, self.errores, **self.extra)


class Rechazo(ErrorApi):
    """Un rechazo ya armado (los de capacidades: `rechazo_sin_permiso`, `rechazo_datos`) lanzado desde dentro de una vista
    o de un servicio: `raise Rechazo(cap.rechazo_datos(faltan))`."""

    def __init__(self, respuesta):
        Exception.__init__(self, 'rechazo')
        self.codigo, self.estado, self.errores, self.extra = None, respuesta.status_code, None, {}
        self._respuesta = respuesta

    def respuesta(self):
        return self._respuesta


class Errores(dict):
    """Errores de validación por campo, `{campo: [textos]}`. Se juntan todos y se responde una sola vez:

        errores = Errores()
        if not nombre:
            errores.agregar('nombre', 'Escribe el nombre de la cuenta.')
        errores.comprobar()   # 400 `validacion` si hay alguno
    """

    def agregar(self, campo, texto):
        self.setdefault(campo, []).append(texto)

    def comprobar(self, texto=None):
        if self:
            raise ErrorApi('validacion', texto, errores=dict(self))


# ---------------------------------------------------------------- cuerpo, empresa, permiso y clave

def es_json(request):
    return (request.content_type or '').startswith('application/json')


def cuerpo(request):
    """Datos del envío: el objeto JSON del cuerpo o, en un formulario (también multipart), `request.POST`. Un cuerpo JSON
    que no se puede leer o que no es un objeto → 400 `cuerpo`. El formulario solo existe en POST: Django no lee el de un
    PATCH, que llega vacío, y por eso el contrato pide el PATCH siempre en JSON."""
    if es_json(request):
        datos = cuerpo_json(request)
        if datos is None:
            raise ErrorApi('cuerpo')
        return datos
    return request.POST


def rechazo_de_empresa(request):
    """409 si la petición no es para la empresa activa, o None. Se miran la consulta y el envío: basta que una de las dos
    nombre otra empresa (`empresa_cambiada`); un envío que no nombra ninguna no se acepta (`sin_empresa`), porque no hay
    forma de saber para qué empresa se preparó la pantalla que lo manda."""
    pedidas = [request.GET.get('empresa')]
    if request.method not in LECTURA:
        pedidas.append(((cuerpo_json(request) or {}) if es_json(request) else request.POST).get('empresa'))
    pedidas = [str(p).strip() for p in pedidas if p not in (None, '')]
    actual = getattr(request, 'company', None)
    if any(p != str(actual.pk if actual is not None else '') for p in pedidas):
        return rechazo_empresa_cambiada(request)
    if request.method not in LECTURA and not pedidas:
        return error(SIN_EMPRESA, 409, 'sin_empresa')
    return None


def rechazo_de_licencia(request):
    """403 `plan` si es un envío y el plan solo deja consultar (vencido), o None.

    PlanMiddleware ya lo responde antes de llegar a la vista, salvo a un formulario con un campo `action` que empiece por
    `search` o sea de consulta (`send_invoice_by_email`): así buscan por POST las pantallas de ventas, y lo deja pasar.
    Estas rutas no consultan nada por POST, de modo que aquí se repite para todo envío, con la misma función que decide
    la licencia y el mismo cuerpo que el middleware: que el plan solo deje consultar no depende de cómo llegó el envío
    (lo mismo que hace el kardex en servicios.registrar). Sin plan pagado o con el complemento cerrado no hay nada que
    repetir: el middleware no deja pasar ningún envío, lleve lo que lleve."""
    if request.method in LECTURA:
        return None
    licencia = cap.licencia(request)
    if not licencia['solo_consulta']:
        return None
    return JsonResponse({'error': licencia['texto'], 'plan': 'requerido', 'codigo': 'plan', 'causa': 'licencia',
                         'licencia': licencia}, status=403)


def es_personal(request):
    """El usuario tiene en la empresa activa un rol de personal (cualquiera menos Cliente, que es el portal del comprador)."""
    grupo = get_group(request)
    return grupo is not None and grupo.name != ROLE_CLIENT


def exigir_permiso(request, permiso):
    """Lanza el 403 `sin_permiso` si el rol no tiene el permiso (un codename, o una tupla si basta uno). Para lo que una
    vista solo exige en algunos envíos (p. ej. `change_cuenta` al confirmar con `actualizar_nombre`)."""
    if not cap.tiene(request, permiso):
        raise Rechazo(cap.rechazo_sin_permiso(permiso))


def clave_de(datos):
    """La `clave` de idempotencia del envío, con el formato del kardex (8 a 40 letras, cifras, guion o guion bajo). Sin
    ella o mal formada → 400 `clave`."""
    clave = str(datos.get('clave') or '').strip()
    if not CLAVE.match(clave):
        raise ErrorApi('clave', errores={'clave': [TEXTOS['clave']]})
    return clave


# ---------------------------------------------------------------- vista base

class ApiContable(LoginRequiredMixin, View):
    """Base de las vistas nuevas de /contabilidad/api/.

    `permisos`: método HTTP → codename, tupla de codenames (basta uno) o PERSONAL. Un método sin entrada no existe en la
    ruta (405). Antes de llamar a `get`, `post`… ya se comprobaron, en este orden, la sesión, la empresa de la pestaña,
    que el plan deje guardar (solo en los envíos) y el permiso; un ErrorApi lanzado dentro sale como su respuesta JSON. No
    toca el módulo activo de la sesión (lo fija la página, no sus consultas en segundo plano)."""
    permisos = {}

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.method not in self.permisos:
            return self.http_method_not_allowed(request, *args, **kwargs)
        rechazo = rechazo_de_empresa(request)
        if rechazo is None:
            rechazo = rechazo_de_licencia(request)
        if rechazo is None:
            rechazo = self.rechazo_de_permiso(request)
        if rechazo is not None:
            return rechazo
        try:
            return super().dispatch(request, *args, **kwargs)
        except ErrorApi as e:
            return e.respuesta()

    def rechazo_de_permiso(self, request):
        permiso = self.permisos[request.method]
        if permiso is PERSONAL:
            return None if es_personal(request) else cap.rechazo_sin_permiso()
        return None if cap.tiene(request, permiso) else cap.rechazo_sin_permiso(permiso)

    def http_method_not_allowed(self, request, *args, **kwargs):
        respuesta = error(TEXTOS['metodo'], 405, 'metodo')
        respuesta['Allow'] = ', '.join(m for m in self.permisos if hasattr(self, m.lower()))
        return respuesta
