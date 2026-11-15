"""Plan de cuentas por empresa (C2 del contrato contable v9): la lista con búsqueda, el alta y los cambios de una cuenta.
Todo ocurre en la empresa activa (`Cuenta.objects` solo ve sus filas: una cuenta de otra empresa no existe, 404).

Reglas, todas comprobadas aquí, en el servidor:

- el código es único en la empresa sin distinguir mayúsculas y no cambia después del alta;
- el padre es un grupo de la misma empresa y el árbol no tiene ciclos; una cuenta con hijas sigue siendo grupo;
- nada se borra: se desactiva, y un grupo no se desactiva mientras tenga hijas activas;
- un grupo no recibe movimientos, y una cuenta con movimientos ni pasa a grupo ni se desactiva: `tiene_movimientos` es
  el único punto que lo decide (líneas de asiento y líneas vivas de una apertura).

Clase y auxiliar (bloque 2, Parte A de contable/bloque-2-especificacion.md): los declara una persona, nunca se deducen del
código. La clase dice dónde va la cuenta en los estados (balance o resultados) y el auxiliar, qué detalle explica su saldo
en la apertura (solo en cuentas de movimiento). Lo ya validado no cambia por reclasificar: con líneas en el libro, un cambio
de clase que cruce entre balance y resultados no se admite si la cuenta tiene líneas en un ejercicio cerrado o está en la
apertura confirmada, y el auxiliar no cambia mientras haya detalle que dependa de él. `clasificar` fija una clase en una
cuenta y, si se pide, en sus descendientes sin clase (nunca pisa una ya puesta).

Sin duplicados ni cambios pisados:

- el alta lleva su `clave`: repetirla con el mismo contenido devuelve la misma cuenta (`repetido`); con otro contenido,
  409 `clave_usada`. Se compara con la cuenta como está ahora: si alguien la cambió después del alta, el envío repetido
  ya no coincide y recibe ese 409 con la cuenta actual, nunca una segunda cuenta;
- cada cambio sube `version`. Quien edita manda la que leyó; si ya no es la vigente, 409 `version` con la cuenta actual.

Concurrencia: toda escritura del plan de una empresa pasa por `serializar(empresa)` y, además, bloquea la fila que cambia
y la del padre bajo el que cuelga algo. Las que bloquean más de una cuenta (`modificar`: la cuenta y después el padre; la
importación: todas) toman las que cambian con FOR NO KEY UPDATE, que excluye a cualquier otro escritor de la cuenta pero no
el FOR KEY SHARE con que PostgreSQL comprueba, al confirmar, las FK diferidas de las filas nuevas que apuntan a ella (líneas
de un asiento o de la apertura, acumulados): así no retienen una cuenta que el libro necesita mientras esperan otra (C2A-1).
El padre (`_grupo_bloqueado`) y la cuenta que se clasifica siguen con FOR UPDATE: son la última cuenta que se bloquea y solo
pueden hacer esperar. Lo que depende del libro (tipo, activa, clase y auxiliar) toma antes el candado del libro si la
empresa tiene inicio contable (paso 1 del orden de bloqueos, decisión común 4): así no se cruza con un asiento
que se contabiliza ni con una apertura que se confirma. La cola por empresa es lo que impide el ciclo cruzado (A bajo una hija de B
mientras B pasa bajo una hija de A: cada movimiento, mirado solo, es válido); las filas bloqueadas y las restricciones
únicas siguen valiendo para quien escriba sin pasar por ella.

El plan pagado y el complemento los decide PlanMiddleware antes de llegar aquí. Con el plan vencido solo se consulta: los
envíos los corta el middleware y, por si llegan como un formulario que él toma por consulta, también api.ApiContable."""
import re
import unicodedata
from collections import Counter, defaultdict

from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.utils import timezone

from core.contabilidad import api, candado
from core.contabilidad.models import (AUXILIARES_CUENTA, CLASES_CUENTA, CODIGO_CUENTA_MAX, NOMBRE_CUENTA_MAX, TIPOS_CUENTA,
                                      Cuenta, norma_codigo)
from core.tenancy.models import audit

VER, CREAR, EDITAR = 'view_cuenta', 'add_cuenta', 'change_cuenta'
GRUPO, MOVIMIENTO = 'grupo', 'movimiento'
TIPOS = tuple(tipo for tipo, _ in TIPOS_CUENTA)
CLASES = tuple(clase for clase, _ in CLASES_CUENTA)            # con '' (sin clase)
AUXILIARES = tuple(auxiliar for auxiliar, _ in AUXILIARES_CUENTA)
BALANCE, RESULTADOS = ('activo', 'pasivo', 'patrimonio'), ('ingreso', 'costo', 'gasto')
# Lo que cambia algo que el libro ya usó: con inicio contable, va con el candado del libro. `auxiliar` también por la
# apertura: confirmarla lee el auxiliar de cada cuenta y lo fija en sus líneas con el candado tomado (apertura._fijar_detalle).
CON_EL_LIBRO = ('tipo', 'activa', 'clase', 'auxiliar')
BLOQUEO_PLAN = 0x43544153   # 'CTAS': clase del bloqueo consultivo de PostgreSQL que pone en cola las escrituras por empresa
BUSQUEDA_MAX = 200
POR_TANDA = 500   # cuentas por sentencia al clasificar descendientes
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
    'clase': 'Elige la clase: activo, pasivo, patrimonio, ingreso, costo o gasto.',
    'clase_vacia': 'Elige la clase: activo, pasivo, patrimonio, ingreso, costo o gasto (o vacío, sin clase).',
    'auxiliar': 'Elige el auxiliar: clientes, proveedores, inventario, bancos, activos o tributario (o vacío, sin auxiliar).',
    'auxiliar_movimiento': 'Solo las cuentas de movimiento llevan auxiliar.',
    'incluir_descendientes': 'Indica si se clasifican también sus cuentas descendientes sin clase: verdadero o falso.',
    'cuenta_id': 'Indica la cuenta que se clasifica.',
    'ejercicio_cerrado': 'La cuenta tiene movimientos en un ejercicio cerrado: su clase no puede pasar entre balance y '
                         'resultados.',
    'apertura_confirmada': 'La cuenta está en la apertura confirmada, que se validó con su clase: no puede pasar entre '
                           'balance y resultados. Corrige la apertura con un ajuste o una sustitución.',
    'cuenta_con_detalle': 'La cuenta tiene detalle que depende de su auxiliar (auxiliares de la apertura o líneas con tercero): '
                          'el auxiliar no se cambia.',
}
_NUMEROS = re.compile(r'(\d+)')


def tiene_movimientos(cuenta):
    """Punto único que dice si una cuenta ya tiene movimientos contables: líneas en el libro (`LineaAsiento`) o una línea no
    retirada de una apertura en borrador, en revisión o confirmada. Las reglas que lo consultan: no pasa a grupo y no se
    desactiva. Dos consultas `exists`."""
    from core.contabilidad.modelos_apertura import BORRADOR, CONFIRMADA, EN_REVISION
    from core.contabilidad.models import LineaApertura, LineaAsiento
    if LineaAsiento.objects.filter(cuenta_id=cuenta.pk).exists():
        return True
    return LineaApertura.objects.filter(cuenta_id=cuenta.pk, retirada=False,
                                        apertura__estado__in=(BORRADOR, EN_REVISION, CONFIRMADA)).exists()


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
            'activa': cuenta.activa, 'clase': cuenta.clase, 'auxiliar': cuenta.auxiliar, 'hijas': hijas,
            'version': cuenta.version}


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
    filas = list(Cuenta.objects.order_by().values('id', 'codigo', 'nombre', 'padre_id', 'tipo', 'activa', 'clase', 'auxiliar',
                                                  'version'))
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
             'activa': f['activa'], 'clase': f['clase'], 'auxiliar': f['auxiliar'], 'hijas': hijas.get(f['id'], 0),
             'version': f['version']} for f in filas]


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
            if 'codigo' not in errores and _codigo_repetido(codigo, errores):
                # Quien escriba el plan sin esperar en la cola pudo guardar este mismo envío después de la lectura por
                # clave de arriba: ese «ya existe» sería su propia cuenta. Se mira la clave otra vez antes de rechazarlo.
                existente = Cuenta.objects.filter(clave=clave).first()
                if existente is not None:
                    del errores['codigo']
                    return _repetida(existente, pedido, errores)
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
    for campo, valores, texto in (('clase', CLASES, 'clase_vacia'), ('auxiliar', AUXILIARES, 'auxiliar')):
        if campo in datos:
            valor = _declarado(datos.get(campo), valores)
            if valor is None:
                errores.agregar(campo, TEXTOS[texto])
            elif valor != getattr(cuenta, campo):
                cambios[campo] = valor
    # Solo las cuentas de movimiento llevan auxiliar (CHECK cuenta_auxiliar_solo_movimiento): vale para la que lo recibe
    # y para la que lo tiene y pasa a grupo.
    if ('auxiliar' in cambios or 'tipo' in cambios) and 'auxiliar' not in errores and 'tipo' not in errores \
            and cambios.get('auxiliar', cuenta.auxiliar) and cambios.get('tipo', cuenta.tipo) != MOVIMIENTO:
        errores.agregar('auxiliar', TEXTOS['auxiliar_movimiento'])

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


def _declarado(valor, valores):
    """La clase o el auxiliar pedido (de `valores`, con '' = sin declarar), o None si no es uno de ellos."""
    if valor is None:
        return ''
    if not isinstance(valor, str) or valor.strip() not in valores:
        return None
    return valor.strip()


def _grupo_de_clase(clase):
    return 'balance' if clase in BALANCE else 'resultados' if clase in RESULTADOS else None


def cruza(antes, despues):
    """El cambio de clase pasa una cuenta declarada entre balance y resultados (o le quita la clase). Declarar la primera
    clase no cruza nada: no había nada validado con ella."""
    return _grupo_de_clase(antes) is not None and _grupo_de_clase(antes) != _grupo_de_clase(despues)


def exigir_que_no_cambie_lo_validado(cuenta, clase=None, auxiliar=None):
    """Lo ya validado no cambia por reclasificar (409, antes que la validación del envío). `clase`/`auxiliar`: los valores
    nuevos que se piden (None: ese dato no cambia).

    - clase que cruza entre balance y resultados: `ejercicio_cerrado` `{"ejercicios": [años]}` si la cuenta tiene líneas en
      un ejercicio cerrado; `apertura_confirmada` si es cuenta de una línea de la apertura confirmada (su resultado del
      ejercicio se validó con esa clase);
    - auxiliar: no cambia mientras haya auxiliares vigentes en una línea de esa cuenta o líneas de asiento con tercero en
      ella: `cuenta_con_detalle` `{"auxiliares": n, "lineas_con_tercero": n}`."""
    from core.contabilidad.modelos_apertura import CONFIRMADA, VIGENTE
    from core.contabilidad.modelos_libro import CERRADO
    from core.contabilidad.models import AuxiliarApertura, EjercicioContable, LineaApertura, LineaAsiento
    if clase is not None and cruza(cuenta.clase, clase):
        cerrados = EjercicioContable.objects.filter(estado=CERRADO).values('anio')
        anios = sorted(set(LineaAsiento.objects.filter(cuenta_id=cuenta.pk, anio__in=cerrados).order_by()
                           .values_list('anio', flat=True).distinct()))
        if anios:
            raise api.ErrorApi('ejercicio_cerrado', TEXTOS['ejercicio_cerrado'], 409, ejercicios=anios,
                               cuenta=dict_cuenta(cuenta))
        if LineaApertura.objects.filter(cuenta_id=cuenta.pk, retirada=False, apertura__estado=CONFIRMADA).exists():
            raise api.ErrorApi('apertura_confirmada', TEXTOS['apertura_confirmada'], 409, cuenta=dict_cuenta(cuenta))
    if auxiliar is not None and auxiliar != cuenta.auxiliar:
        auxiliares = AuxiliarApertura.objects.filter(linea__cuenta_id=cuenta.pk, estado=VIGENTE).count()
        con_tercero = LineaAsiento.objects.filter(cuenta_id=cuenta.pk).exclude(tercero_tipo='').count()
        if auxiliares or con_tercero:
            raise api.ErrorApi('cuenta_con_detalle', TEXTOS['cuenta_con_detalle'], 409, auxiliares=auxiliares,
                               lineas_con_tercero=con_tercero, cuenta=dict_cuenta(cuenta))


def modificar(request, pk, datos):
    """Cambia una cuenta: `{version, nombre?, padre_id?, tipo?, activa?, clase?, auxiliar?}` (solo lo que venga). Devuelve
    la cuenta como queda. Si nada cambia, no sube la versión ni deja registro."""
    api.exigir_permiso(request, EDITAR)
    with transaction.atomic():
        if any(campo in datos for campo in CON_EL_LIBRO):
            candado.tomar_si_existe()   # antes que la cola del plan y que la cuenta (orden global de bloqueos)
        serializar(request.company)
        # FOR NO KEY UPDATE: un cambio de la cuenta nunca toca lo que es clave (id, código), así que no excluye el FOR KEY
        # SHARE con que una línea nueva apunta a ella. Con FOR UPDATE, moverla bajo una cuenta a la que un asiento o una
        # apertura apuntaban antes que a esta cerraba un interbloqueo: el cambio esperaba al libro por el padre y el libro
        # al cambio por esta cuenta.
        cuenta = Cuenta.objects.select_for_update(no_key=True).filter(pk=pk).first()
        if cuenta is None:
            raise api.ErrorApi('cuenta', TEXTOS['cuenta'], 404)
        errores = api.Errores()
        version = _version(datos, errores)
        # Antes que el resto de la validación: con una versión vieja, los demás errores hablarían de un estado que ya no
        # es el que tiene delante quien edita.
        if version is not None and version != cuenta.version:
            raise api.ErrorApi('version', TEXTOS['version'], 409, cuenta=dict_cuenta(cuenta))
        cambios = _cambios(cuenta, datos, errores)
        exigir_que_no_cambie_lo_validado(cuenta, cambios.get('clase'), cambios.get('auxiliar'))
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


# ---------------------------------------------------------------- clasificar

def _descendientes(cuenta_id):
    """Los ids de las cuentas que cuelgan de `cuenta_id` a cualquier profundidad. Una consulta: el árbol cabe en memoria."""
    hijas = defaultdict(list)
    for pk, padre_id in Cuenta.objects.order_by().values_list('pk', 'padre_id'):
        if padre_id is not None:
            hijas[padre_id].append(pk)
    encontradas, pendientes, vistas = [], list(hijas.get(cuenta_id, ())), {cuenta_id}
    while pendientes:
        pk = pendientes.pop()
        if pk in vistas:
            continue
        vistas.add(pk)
        encontradas.append(pk)
        pendientes.extend(hijas.get(pk, ()))
    return sorted(encontradas)


def clasificar(request, datos):
    """Fija una clase en una cuenta y, con `incluir_descendientes`, en sus descendientes que todavía no tienen clase: nunca
    pisa una clase ya puesta (decisión expresa por lote). `{cuenta_id, version, clase, incluir_descendientes}`. Devuelve
    `(cuenta, clasificadas)`: la cuenta como queda y cuántas cuentas recibieron la clase (ella incluida si cambió).

    La cuenta pedida sigue las reglas de reclasificar (`exigir_que_no_cambie_lo_validado`) y lleva `version`; cada cuenta
    que cambia sube la suya. Si ninguna cambia, no hay registro de auditoría."""
    api.exigir_permiso(request, EDITAR)
    errores = api.Errores()
    cuenta_id = _entero(datos.get('cuenta_id'))
    if cuenta_id is None:
        errores.agregar('cuenta_id', TEXTOS['cuenta_id'])
    version = _version(datos, errores)
    clase = _declarado(datos.get('clase'), CLASES) or None   # clasificar es declarar una clase: vacía no vale
    if clase is None:
        errores.agregar('clase', TEXTOS['clase'])
    incluir = datos.get('incluir_descendientes', False)
    if not isinstance(incluir, bool):
        errores.agregar('incluir_descendientes', TEXTOS['incluir_descendientes'])
        incluir = False
    with transaction.atomic():
        candado.tomar_si_existe()   # antes que la cola del plan y que las cuentas (orden global de bloqueos)
        serializar(request.company)
        cuenta = Cuenta.objects.select_for_update().filter(pk=cuenta_id).first() if cuenta_id is not None else None
        if cuenta_id is not None and cuenta is None:
            raise api.ErrorApi('cuenta', TEXTOS['cuenta'], 404)
        if cuenta is not None and version is not None and version != cuenta.version:
            raise api.ErrorApi('version', TEXTOS['version'], 409, cuenta=dict_cuenta(cuenta))
        if cuenta is not None and clase is not None:
            exigir_que_no_cambie_lo_validado(cuenta, clase)
        errores.comprobar()
        ahora, usuario, antes = timezone.now(), _usuario(request), cuenta.clase
        clasificadas = descendientes = 0
        if cuenta.clase != clase:
            cuenta.clase, cuenta.version, cuenta.actualizada_por, cuenta.actualizada_en = clase, cuenta.version + 1, usuario, ahora
            cuenta.save(update_fields=['clase', 'version', 'actualizada_por', 'actualizada_en'])
            clasificadas = 1
        if incluir:
            ids = _descendientes(cuenta.pk)
            for desde in range(0, len(ids), POR_TANDA):
                # `clase=''` en la misma sentencia: una clase puesta entre la lectura y la escritura tampoco se pisa.
                descendientes += Cuenta.objects.filter(pk__in=ids[desde:desde + POR_TANDA], clase='').update(
                    clase=clase, version=F('version') + 1, actualizada_por=usuario, actualizada_en=ahora)
            clasificadas += descendientes
        if clasificadas:
            audit(request, 'cuentas_clasificadas', company=request.company, cuenta=cuenta.pk, codigo=cuenta.codigo,
                  clase=[antes, clase], incluir_descendientes=incluir, descendientes=descendientes, clasificadas=clasificadas)
    return cuenta, clasificadas
