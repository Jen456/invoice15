"""Plan de cuentas por empresa (C2 del contrato contable v9): la lista con búsqueda, el alta y los cambios de una cuenta.
Todo ocurre en la empresa activa (`Cuenta.objects` solo ve sus filas: una cuenta de otra empresa no existe, 404).

Reglas, todas comprobadas aquí, en el servidor:

- el código es único en la empresa sin distinguir mayúsculas y no cambia después del alta;
- el padre es un grupo de la misma empresa y el árbol no tiene ciclos; una cuenta con hijas sigue siendo grupo;
- nada se borra: se desactiva, y un grupo no se desactiva mientras tenga hijas activas;
- un grupo no recibe movimientos, y una cuenta con movimientos ni pasa a grupo ni se desactiva: `tiene_movimientos` es
  el único punto que lo decide (hoy nada los registra; lo completan los bloques de apertura y de asientos).

Sin duplicados ni cambios pisados:

- el alta lleva su `clave`: repetirla con el mismo contenido devuelve la misma cuenta (`repetido`); con otro contenido,
  409 `clave_usada`. Se compara con la cuenta como está ahora: si alguien la cambió después del alta, el envío repetido
  ya no coincide y recibe ese 409 con la cuenta actual, nunca una segunda cuenta;
- cada cambio sube `version`. Quien edita manda la que leyó; si ya no es la vigente, 409 `version` con la cuenta actual.

Concurrencia: toda escritura del plan de una empresa pasa por `serializar(empresa)` y, además, bloquea la fila que cambia
y la del padre bajo el que cuelga algo. La cola por empresa es lo que impide el ciclo cruzado (A bajo una hija de B
mientras B pasa bajo una hija de A: cada movimiento, mirado solo, es válido); las filas bloqueadas y las restricciones
únicas siguen valiendo para quien escriba sin pasar por ella.

El plan pagado y el complemento los decide PlanMiddleware antes de llegar aquí. Con el plan vencido solo se consulta: los
envíos los corta el middleware y, por si llegan como un formulario que él toma por consulta, también api.ApiContable."""
import re
import unicodedata
from collections import Counter

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from core.contabilidad import api
from core.contabilidad.models import CODIGO_CUENTA_MAX, NOMBRE_CUENTA_MAX, TIPOS_CUENTA, Cuenta, norma_codigo
from core.tenancy.models import audit

VER, CREAR, EDITAR = 'view_cuenta', 'add_cuenta', 'change_cuenta'
GRUPO, MOVIMIENTO = 'grupo', 'movimiento'
TIPOS = tuple(tipo for tipo, _ in TIPOS_CUENTA)
BLOQUEO_PLAN = 0x43544153   # 'CTAS': clase del bloqueo consultivo de PostgreSQL que pone en cola las escrituras por empresa
BUSQUEDA_MAX = 200
ID_MAX = 2 ** 63 - 1   # lo que cabe en un id de la base
TEXTOS = {
    'codigo': 'Escribe el código de la cuenta.',
    'codigo_largo': f'El código admite hasta {CODIGO_CUENTA_MAX} caracteres.',
    'codigo_caracteres': 'El código tiene caracteres que no se pueden guardar.',
    'codigo_repetido': 'Ya existe la cuenta {codigo} en esta empresa.',
    'codigo_fijo': 'El código de una cuenta no se cambia: crea otra cuenta y desactiva esta.',
    'nombre': 'Escribe el nombre de la cuenta.',
    'nombre_largo': f'El nombre admite hasta {NOMBRE_CUENTA_MAX} caracteres.',
    'nombre_caracteres': 'El nombre tiene caracteres que no se pueden guardar.',
    'tipo': 'Elige grupo o movimiento.',
    'padre': 'El padre debe ser un grupo de esta empresa.',
    'ciclo': 'Crearía un ciclo.',
    'con_hijas': 'Tiene cuentas hijas: debe seguir siendo grupo.',
    'hijas_activas': 'Desactiva primero sus cuentas hijas.',
    'con_movimientos_grupo': 'Tiene movimientos: no puede pasar a grupo.',
    'con_movimientos_desactivar': 'Tiene movimientos: no se puede desactivar.',
    'activa': 'Indica si la cuenta queda activa: verdadero o falso.',
    'version_falta': 'Falta la versión de la cuenta que estás editando: vuelve a cargarla e inténtalo de nuevo.',
    'version': 'Otra persona cambió esta cuenta mientras la editabas: revisa cómo quedó y vuelve a intentarlo.',
    'clave_usada': 'Esta clave ya se usó para otra cuenta: vuelve a cargar la página e inténtalo de nuevo.',
    'cuenta': 'La cuenta no existe o es de otra empresa.',
}
_NUMEROS = re.compile(r'(\d+)')


def tiene_movimientos(cuenta):
    """Punto único que dice si una cuenta ya tiene movimientos contables (saldos de apertura, líneas de asiento). Hoy
    ninguna tabla los guarda y siempre es falso; los bloques de apertura y de asientos lo completan aquí y con eso
    quedan vigentes las reglas que ya lo consultan (no pasa a grupo, no se desactiva)."""
    return False


def serializar(empresa):
    """Dentro de transaction.atomic(). Pone en cola las escrituras del plan de cuentas de la empresa (alta, cambio,
    confirmación de una importación) con un bloqueo consultivo de PostgreSQL que se suelta al terminar la transacción,
    como los envíos de proformas. Solo espera a otra escritura del plan de la misma empresa. En SQLite no hace nada."""
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s, %s)', [BLOQUEO_PLAN, int(empresa.pk) % 2147483648])


# ---------------------------------------------------------------- lectura

def dict_cuenta(cuenta, hijas=None):
    """La cuenta con la forma del contrato. `hijas`: cuántas cuelgan directamente de ella (activas o no); si no se pasa,
    se cuentan."""
    if hijas is None:
        hijas = Cuenta.objects.filter(padre_id=cuenta.pk).count()
    return {'id': cuenta.pk, 'codigo': cuenta.codigo, 'nombre': cuenta.nombre, 'padre_id': cuenta.padre_id, 'tipo': cuenta.tipo,
            'activa': cuenta.activa, 'hijas': hijas, 'version': cuenta.version}


def orden_natural(codigo):
    """Clave para ordenar códigos como los lee una persona: los tramos de cifras por su valor (1.2 antes que 1.10) y el
    resto como texto, sin distinguir mayúsculas. Termina en el propio código comparable, que es único en la empresa: dos
    códigos que valen lo mismo (1.01 y 1.1) quedan siempre en el mismo orden."""
    norma = norma_codigo(codigo)
    tramos = _NUMEROS.split(norma)   # en las posiciones impares quedan las cifras
    return tuple((0, int(tramo), '') if i % 2 else (1, 0, tramo) for i, tramo in enumerate(tramos) if tramo), norma


def _plano(texto):
    """Texto para buscar: sin distinguir mayúsculas ni tildes."""
    sin_marcas = ''.join(c for c in unicodedata.normalize('NFKD', str(texto)) if not unicodedata.combining(c))
    return sin_marcas.casefold()


def listar(q=''):
    """Las cuentas de la empresa activa ordenadas por código (orden natural). Con `q`, las que lo contienen en el código
    o en el nombre y todas sus antepasadas, para que el árbol se pueda dibujar. Una sola consulta, también con 5 000
    cuentas: las hijas, la búsqueda (sin distinguir mayúsculas ni tildes) y el orden se resuelven en memoria."""
    filas = list(Cuenta.objects.order_by().values('id', 'codigo', 'nombre', 'padre_id', 'tipo', 'activa', 'version'))
    hijas = Counter(f['padre_id'] for f in filas if f['padre_id'] is not None)
    buscado = _plano(' '.join(str(q or '')[:BUSQUEDA_MAX].split()))
    if buscado:
        por_id = {f['id']: f for f in filas}
        visibles = set()
        for fila in filas:
            if buscado in _plano(fila['codigo']) or buscado in _plano(fila['nombre']):
                while fila is not None and fila['id'] not in visibles:   # sube hasta la raíz o hasta lo ya incluido
                    visibles.add(fila['id'])
                    fila = por_id.get(fila['padre_id'])
        filas = [f for f in filas if f['id'] in visibles]
    filas.sort(key=lambda f: orden_natural(f['codigo']))
    return [{'id': f['id'], 'codigo': f['codigo'], 'nombre': f['nombre'], 'padre_id': f['padre_id'], 'tipo': f['tipo'],
             'activa': f['activa'], 'hijas': hijas.get(f['id'], 0), 'version': f['version']} for f in filas]


# ---------------------------------------------------------------- campos de un envío

def _texto(valor):
    """El texto de un campo sin espacios sobrantes; '' si no vino y None si no es texto. Un entero vale como texto (el
    código 1101 escrito sin comillas); un número con decimales no, porque ya perdió sus ceros (1.10 llega como 1.1)."""
    if valor is None:
        return ''
    if isinstance(valor, int) and not isinstance(valor, bool):
        valor = str(valor)
    if not isinstance(valor, str):
        return None
    return ' '.join(valor.split())


def falla_del_codigo(codigo):
    """Por qué no se puede guardar ese código (ya sin espacios sobrantes): la entrada de TEXTOS que lo dice, o None si
    vale. La misma regla para el alta y para cada fila de una importación del plan."""
    if not codigo:
        return 'codigo'
    if len(codigo) > CODIGO_CUENTA_MAX:
        return 'codigo_largo'
    if not codigo.isprintable():   # caracteres de control o invisibles: dos códigos distintos que se verían iguales
        return 'codigo_caracteres'
    return None


def falla_del_nombre(nombre):
    """Lo mismo que `falla_del_codigo`, para el nombre."""
    if not nombre:
        return 'nombre'
    if len(nombre) > NOMBRE_CUENTA_MAX:
        return 'nombre_largo'
    if not nombre.isprintable():
        return 'nombre_caracteres'
    return None


def _codigo(datos, errores):
    codigo = _texto(datos.get('codigo'))
    falla = falla_del_codigo(codigo)
    if falla:
        errores.agregar('codigo', TEXTOS[falla])
    return codigo or ''


def _nombre(datos, errores):
    nombre = _texto(datos.get('nombre'))
    falla = falla_del_nombre(nombre)
    if falla:
        errores.agregar('nombre', TEXTOS[falla])
    return nombre or ''


def _tipo(datos, errores):
    tipo = datos.get('tipo')
    if not isinstance(tipo, str) or tipo.strip() not in TIPOS:
        errores.agregar('tipo', TEXTOS['tipo'])
        return ''
    return tipo.strip()


def _entero(valor):
    """Un entero mayor que cero que llegó como número o como texto de cifras; None si no lo es (tampoco un booleano, ni
    un número que no cabe en un id)."""
    if isinstance(valor, str):
        valor = valor.strip()
        if not (valor.isascii() and valor.isdigit() and len(valor) <= 19):
            return None
        valor = int(valor)
    if not isinstance(valor, int) or isinstance(valor, bool) or not 0 < valor <= ID_MAX:
        return None
    return valor


def _padre_id(datos, errores):
    """El id del padre pedido, None si la cuenta va en la raíz (no viene, nulo o vacío)."""
    valor = datos.get('padre_id')
    if valor is None or valor == '':
        return None
    padre_id = _entero(valor)
    if padre_id is None:
        errores.agregar('padre_id', TEXTOS['padre'])
    return padre_id


def _usuario(request):
    usuario = getattr(request, 'user', None)
    return usuario if usuario is not None and usuario.is_authenticated else None


def _grupo_bloqueado(padre_id):
    """El padre pedido, con su fila bloqueada, si es un grupo de la empresa activa; si no, None. Bloqueado: mientras se
    cuelga algo de él no puede pasar a cuenta de movimiento en otra transacción."""
    padre = Cuenta.objects.select_for_update().filter(pk=padre_id).first()
    return padre if padre is not None and padre.tipo == GRUPO else None


# ---------------------------------------------------------------- alta

def _repetida(existente, pedido, errores):
    if not errores and pedido == (existente.codigo, existente.nombre, existente.tipo, existente.padre_id):
        return existente, True
    raise api.ErrorApi('clave_usada', TEXTOS['clave_usada'], 409, cuenta=dict_cuenta(existente))


def _codigo_repetido(codigo, errores):
    otra = Cuenta.objects.filter(codigo_norm=norma_codigo(codigo)).first()
    if otra is not None:
        errores.agregar('codigo', TEXTOS['codigo_repetido'].format(codigo=otra.codigo))   # el código como está guardado
    return otra is not None


def crear(request, datos):
    """Crea una cuenta: `{clave, codigo, nombre, tipo, padre_id}`. Devuelve (cuenta, repetido)."""
    api.exigir_permiso(request, CREAR)
    clave = api.clave_de(datos)
    errores = api.Errores()
    pedido = (_codigo(datos, errores), _nombre(datos, errores), _tipo(datos, errores), _padre_id(datos, errores))
    codigo, nombre, tipo, padre_id = pedido
    try:
        with transaction.atomic():
            serializar(request.company)
            # Antes que el código repetido: el envío que se repite encontraría «ya existe» su propia cuenta.
            existente = Cuenta.objects.filter(clave=clave).first()
            if existente is not None:
                return _repetida(existente, pedido, errores)
            if padre_id is not None and _grupo_bloqueado(padre_id) is None:
                errores.agregar('padre_id', TEXTOS['padre'])
            if 'codigo' not in errores:
                _codigo_repetido(codigo, errores)
            errores.comprobar()
            cuenta = Cuenta(company=request.company, clave=clave, codigo=codigo, nombre=nombre, tipo=tipo, padre_id=padre_id,
                            creada_por=_usuario(request), actualizada_por=_usuario(request))
            cuenta.save()
            audit(request, 'cuenta_creada', company=request.company, cuenta=cuenta.pk, codigo=cuenta.codigo,
                  nombre=cuenta.nombre, tipo=cuenta.tipo, padre=cuenta.padre_id)
            return cuenta, False
    except IntegrityError:
        # Otra transacción guardó antes la misma clave o el mismo código sin esperar en la cola: decide la restricción única.
        existente = Cuenta.objects.filter(clave=clave).first()
        if existente is not None:
            return _repetida(existente, pedido, errores)
        if not _codigo_repetido(codigo, errores):
            raise
        raise api.ErrorApi('validacion', errores=dict(errores)) from None


# ---------------------------------------------------------------- cambios

def _version(datos, errores):
    """La versión que leyó quien edita (entero desde 1), o None con su error si falta o no es un número."""
    version = _entero(datos.get('version'))
    if version is None:
        errores.agregar('version', TEXTOS['version_falta'])
    return version


def cuelga_de(padres, posible_descendiente, cuenta):
    """True si `posible_descendiente` es la propia `cuenta` o cuelga de ella (a cualquier profundidad) en el árbol
    `padres` (`{cuenta: su padre, o None en la raíz}`). Es la regla «sin ciclos»: una cuenta no puede pasar bajo algo que
    cuelga de ella. Vale para ids de cuentas guardadas y para los códigos de un archivo que todavía no se importó."""
    vistos, actual = set(), posible_descendiente
    while actual is not None and actual not in vistos:
        if actual == cuenta:
            return True
        vistos.add(actual)
        actual = padres.get(actual)
    return False


def _desciende(posible_descendiente_id, cuenta_id):
    """`cuelga_de` sobre las cuentas guardadas de la empresa. Una consulta: el árbol cabe en memoria y la profundidad no
    añade consultas."""
    return cuelga_de(dict(Cuenta.objects.order_by().values_list('pk', 'padre_id')), posible_descendiente_id, cuenta_id)


def _cambios(cuenta, datos, errores):
    """Qué cambia de la cuenta con este envío (`{campo: valor nuevo}`; solo los campos que vienen y son distintos), con
    todos los errores de una vez. Las reglas del árbol se aplican a lo que cambia: corregir el nombre de una cuenta no
    se rechaza por cómo está el resto."""
    cambios = {}
    if 'codigo' in datos and _texto(datos.get('codigo')) != cuenta.codigo:
        errores.agregar('codigo', TEXTOS['codigo_fijo'])
    if 'nombre' in datos:
        nombre = _nombre(datos, errores)
        if 'nombre' not in errores and nombre != cuenta.nombre:
            cambios['nombre'] = nombre
    if 'tipo' in datos:
        tipo = _tipo(datos, errores)
        if 'tipo' not in errores and tipo != cuenta.tipo:
            cambios['tipo'] = tipo
    if 'activa' in datos:
        if not isinstance(datos.get('activa'), bool):
            errores.agregar('activa', TEXTOS['activa'])
        elif datos.get('activa') != cuenta.activa:
            cambios['activa'] = datos.get('activa')
    if 'padre_id' in datos:
        padre_id = _padre_id(datos, errores)
        if 'padre_id' not in errores and padre_id != cuenta.padre_id:
            cambios['padre_id'] = padre_id   # None: pasa a la raíz

    if 'tipo' in cambios or cambios.get('activa') is False:
        hijas = list(Cuenta.objects.filter(padre_id=cuenta.pk).values_list('activa', flat=True))
        con_movimientos = tiene_movimientos(cuenta)
        if cambios.get('tipo') == MOVIMIENTO and hijas:
            errores.agregar('tipo', TEXTOS['con_hijas'])
        if cambios.get('tipo') == GRUPO and con_movimientos:
            errores.agregar('tipo', TEXTOS['con_movimientos_grupo'])
        if cambios.get('activa') is False:
            if any(hijas):
                errores.agregar('activa', TEXTOS['hijas_activas'])
            if con_movimientos:
                errores.agregar('activa', TEXTOS['con_movimientos_desactivar'])
    if cambios.get('padre_id') is not None:
        if _desciende(cambios['padre_id'], cuenta.pk):
            errores.agregar('padre_id', TEXTOS['ciclo'])
        elif _grupo_bloqueado(cambios['padre_id']) is None:
            errores.agregar('padre_id', TEXTOS['padre'])
    return cambios


def modificar(request, pk, datos):
    """Cambia una cuenta: `{version, nombre?, padre_id?, tipo?, activa?}` (solo lo que venga). Devuelve la cuenta como
    queda. Si nada cambia, no sube la versión ni deja registro."""
    api.exigir_permiso(request, EDITAR)
    with transaction.atomic():
        serializar(request.company)
        cuenta = Cuenta.objects.select_for_update().filter(pk=pk).first()
        if cuenta is None:
            raise api.ErrorApi('cuenta', TEXTOS['cuenta'], 404)
        errores = api.Errores()
        version = _version(datos, errores)
        # Antes que el resto de la validación: con una versión vieja, los demás errores hablarían de un estado que ya no
        # es el que tiene delante quien edita.
        if version is not None and version != cuenta.version:
            raise api.ErrorApi('version', TEXTOS['version'], 409, cuenta=dict_cuenta(cuenta))
        cambios = _cambios(cuenta, datos, errores)
        errores.comprobar()
        if cambios:
            antes = {campo: getattr(cuenta, campo) for campo in cambios}
            for campo, valor in cambios.items():
                setattr(cuenta, campo, valor)
            cuenta.version += 1
            cuenta.actualizada_por, cuenta.actualizada_en = _usuario(request), timezone.now()
            cuenta.save(update_fields=[*cambios, 'version', 'actualizada_por', 'actualizada_en'])
            audit(request, 'cuenta_modificada', company=request.company, cuenta=cuenta.pk, codigo=cuenta.codigo,
                  version=cuenta.version, cambios={campo: [antes[campo], cambios[campo]] for campo in cambios})
    return cuenta
