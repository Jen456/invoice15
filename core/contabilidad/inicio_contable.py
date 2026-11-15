"""Inicio contable de la empresa (Parte B de contable/bloque-2-especificacion.md, reglas 1 a 3): la modalidad, el corte y
desde cuándo se contabiliza. Lo fijan la creación de la apertura (POST /contabilidad/api/apertura/) y sus cambios en
borrador (PATCH …/apertura/<id>/); aquí están las reglas y la escritura, que siempre ocurren con el candado del libro.

Reglas:

1. Elegir la modalidad no da por completo ningún rango.
   - `saldos`: `contabilidad_desde = operaciones_desde = fecha_corte + 1`, sin fechas de historial;
   - `historial`: el rango `historial_desde`–`historial_hasta` (hasta ayer como mucho); `fecha_corte = historial_desde − 1`,
     `contabilidad_desde = historial_desde` y `operaciones_desde = historial_hasta + 1`. La apertura es el saldo anterior al
     rango.
   El corte no puede ser futuro (confirmar exige además el día del corte terminado: es de la confirmación).
2. Sin saldo anterior no se supone cero: eso lo dicen la cobertura (cobertura.py) y los reportes, no esta tabla.
3. Solapamiento bloqueado: no se fija ni se mueve un corte igual o posterior a la fecha de un asiento ordinario o de una
   aplicación vigente sobre un saldo inicial (409 `rango_solapado` con cuántos y la primera fecha). Con una apertura
   confirmada, la configuración solo cambia por sustitución (409 `apertura_confirmada`).

Concurrencia: la fila `InicioContable` es el candado del libro (decisión común 3). Toda escritura de la configuración la
toma primero, y por eso nunca se cruzan dos configuraciones ni una configuración con un asiento."""
from contextlib import contextmanager
from datetime import date, timedelta

from django.db.models import Count, Min, Q
from django.utils import timezone

from core.contabilidad import api, candado
from core.contabilidad import capacidades as cap
from core.contabilidad.modelos_apertura import CONFIRMADA, EN_REVISION, VIGENTE
from core.contabilidad.models import AplicacionAuxiliar, Apertura, Asiento, InicioContable
from core.tenancy.models import audit

SALDOS, HISTORIAL = 'saldos', 'historial'
MODALIDADES = (SALDOS, HISTORIAL)
FECHA_MINIMA = date(2000, 1, 1)   # los ejercicios van de 2000 a 2100 (EjercicioContable)
# Campos de la configuración que deciden qué entra al libro (lo que se compara, se audita y se devuelve).
CAMPOS = ('modalidad', 'fecha_corte', 'contabilidad_desde', 'operaciones_desde', 'historial_desde', 'historial_hasta')
# Asientos que no son ordinarios a efectos del corte: la apertura y su reverso (la regla de la fecha de corte del cierre
# del ejercicio del corte es del bloque 6, que la añade aquí cuando cree ese asiento).
NO_ORDINARIOS = Q(tipo='apertura') | Q(tipo='reverso', reversa_de__tipo='apertura')

TEXTOS = {
    'inicio_sin_configurar': 'Configura primero el inicio contable: la modalidad y la fecha de corte de la apertura.',
    'modalidad': 'Elige la modalidad: por saldos de apertura o por historial detallado.',
    'fecha': 'Escribe la fecha como AAAA-MM-DD.',
    'fecha_corte': 'Escribe la fecha de corte de la apertura.',
    'corte_futuro': 'La fecha de corte no puede ser futura.',
    'corte_antiguo': 'La fecha de corte debe ser del año 2000 en adelante.',
    'historial_desde': 'Escribe desde qué día empieza el historial.',
    'historial_hasta': 'Escribe hasta qué día llega el historial.',
    'hasta_futuro': 'El historial llega como mucho hasta ayer.',
    'hasta_antes': 'El historial no puede terminar antes de empezar.',
    'corte_historial': 'En la modalidad por historial el corte es el día anterior al inicio del historial.',
    'solo_historial': 'Solo la modalidad por historial lleva rango de historial.',
    'version': 'Otra persona cambió la configuración mientras la editabas: revisa cómo quedó y vuelve a intentarlo.',
    'apertura_confirmada': 'La apertura ya está confirmada: la configuración solo cambia sustituyendo la apertura.',
    'rango_solapado': 'Ya hay movimientos contabilizados en la fecha de corte o antes: el corte debe ser anterior a todos ellos.',
}


# ---------------------------------------------------------------- candado

@contextmanager
def libro(crear=None):
    """El candado del libro (`candado.libro`, decisión común 3) tal como lo usan la configuración y la apertura: abre
    `transaction.atomic()`, bloquea la fila `InicioContable` de la empresa, deja la marca de contexto que exigen el diario
    y los períodos, y devuelve la fila. Sin fila, 409 `datos_por_completar` (`inicio_sin_configurar`), salvo con `crear`
    (los campos de la fila; solo la configuración lo pasa), que la crea con el patrón de carrera de `reglas_de`
    (core/importacion/servicios.py:53-61) con esos campos tal cual: `creada()` lo reconoce por `creado_en`. Un solo nombre
    para quienes lo toman desde aquí (tests/test_apertura_preparar.py::TestCandado lo espía)."""
    with candado.libro(crear=crear) as inicio:
        yield inicio


# ---------------------------------------------------------------- lectura de un envío

def hoy():
    return timezone.localdate()


def fecha_de(valor):
    """Una fecha `AAAA-MM-DD` escrita como texto; None si no lo es."""
    if not isinstance(valor, str) or len(valor.strip()) != 10:
        return None
    try:
        return date.fromisoformat(valor.strip())
    except ValueError:
        return None


def _fecha(datos, campo, errores, falta):
    valor = datos.get(campo)
    if valor in (None, ''):
        errores.agregar(campo, TEXTOS[falta])
        return None
    fecha = fecha_de(valor)
    if fecha is None:
        errores.agregar(campo, TEXTOS['fecha'])
    return fecha


def fechas(modalidad, fecha_corte, historial_desde=None, historial_hasta=None):
    """Los seis campos de la configuración que salen de la modalidad y sus fechas (regla 1)."""
    if modalidad == SALDOS:
        siguiente = fecha_corte + timedelta(days=1)
        return {'modalidad': SALDOS, 'fecha_corte': fecha_corte, 'contabilidad_desde': siguiente,
                'operaciones_desde': siguiente, 'historial_desde': None, 'historial_hasta': None}
    return {'modalidad': HISTORIAL, 'fecha_corte': historial_desde - timedelta(days=1), 'contabilidad_desde': historial_desde,
            'operaciones_desde': historial_hasta + timedelta(days=1), 'historial_desde': historial_desde,
            'historial_hasta': historial_hasta}


def _comprobar_corte(corte, errores, campo='fecha_corte'):
    if corte is None:
        return
    if corte > hoy():
        errores.agregar(campo, TEXTOS['corte_futuro'])
    elif corte < FECHA_MINIMA:
        errores.agregar(campo, TEXTOS['corte_antiguo'])


def _comprobar_historial(desde, hasta, errores, campo_desde='historial_desde'):
    if hasta is not None and hasta >= hoy():
        errores.agregar('historial_hasta', TEXTOS['hasta_futuro'])
    if desde is not None and hasta is not None and hasta < desde:
        errores.agregar('historial_hasta', TEXTOS['hasta_antes'])
    if desde is not None:
        _comprobar_corte(desde - timedelta(days=1), errores, campo_desde)


def leer(datos, errores):
    """La configuración pedida al crear la apertura: `{modalidad, fecha_corte | (historial_desde, historial_hasta)}` →
    los seis campos (`fechas`), o None con sus errores en `errores`."""
    modalidad = datos.get('modalidad')
    if modalidad not in MODALIDADES:
        errores.agregar('modalidad', TEXTOS['modalidad'])
        return None
    if modalidad == SALDOS:
        corte = _fecha(datos, 'fecha_corte', errores, 'fecha_corte')
        for campo in ('historial_desde', 'historial_hasta'):
            if datos.get(campo) not in (None, ''):
                errores.agregar(campo, TEXTOS['solo_historial'])
        _comprobar_corte(corte, errores)
        return fechas(SALDOS, corte) if corte is not None and 'fecha_corte' not in errores else None
    desde = _fecha(datos, 'historial_desde', errores, 'historial_desde')
    hasta = _fecha(datos, 'historial_hasta', errores, 'historial_hasta')
    _comprobar_historial(desde, hasta, errores)
    if desde is not None and datos.get('fecha_corte') not in (None, ''):
        if fecha_de(datos.get('fecha_corte')) != desde - timedelta(days=1):
            errores.agregar('fecha_corte', TEXTOS['corte_historial'])
    if desde is None or hasta is None or any(c in errores for c in ('historial_desde', 'historial_hasta', 'fecha_corte')):
        return None
    return fechas(HISTORIAL, None, desde, hasta)


def cambiar(inicio, datos, errores):
    """La configuración que resulta de un cambio en borrador (`fecha_corte?`, `historial_hasta?`) sobre la actual, o None
    si el envío no la toca o tiene errores. En historial, mover el corte mueve el inicio del historial (corte + 1)."""
    if 'fecha_corte' not in datos and 'historial_hasta' not in datos:
        return None
    propios = api.Errores()   # los de otros campos del envío no deciden si la configuración se puede calcular
    corte = fecha_de(datos['fecha_corte']) if 'fecha_corte' in datos else inicio.fecha_corte
    if 'fecha_corte' in datos and corte is None:
        propios.agregar('fecha_corte', TEXTOS['fecha'] if datos['fecha_corte'] not in (None, '') else TEXTOS['fecha_corte'])
    if inicio.modalidad == SALDOS:
        if 'historial_hasta' in datos:
            propios.agregar('historial_hasta', TEXTOS['solo_historial'])
        _comprobar_corte(corte, propios)
        config = fechas(SALDOS, corte) if not propios else None
    else:
        hasta = fecha_de(datos['historial_hasta']) if 'historial_hasta' in datos else inicio.historial_hasta
        if 'historial_hasta' in datos and hasta is None:
            propios.agregar('historial_hasta', TEXTOS['fecha'] if datos['historial_hasta'] not in (None, '')
                            else TEXTOS['historial_hasta'])
        desde = corte + timedelta(days=1) if corte is not None else None
        _comprobar_historial(desde, hasta, propios, campo_desde='fecha_corte')
        config = fechas(HISTORIAL, None, desde, hasta) if not propios else None
    for campo, textos in propios.items():
        for texto in textos:
            errores.agregar(campo, texto)
    return config


# ---------------------------------------------------------------- reglas con el candado

def solapamiento(fecha_corte):
    """Lo que ya está contabilizado o aplicado en `fecha_corte` o antes (regla 3): `{"asientos", "aplicaciones",
    "primera_fecha"}`, con una consulta agregada por tabla. Ordinario es todo asiento salvo la apertura y su reverso."""
    asientos = Asiento.objects.filter(fecha__lte=fecha_corte).exclude(NO_ORDINARIOS).aggregate(n=Count('id'), primera=Min('fecha'))
    aplicaciones = AplicacionAuxiliar.objects.filter(estado=VIGENTE, fecha__lte=fecha_corte).aggregate(
        n=Count('id'), primera=Min('fecha'))
    primeras = [f for f in (asientos['primera'], aplicaciones['primera']) if f is not None]
    return {'asientos': asientos['n'], 'aplicaciones': aplicaciones['n'],
            'primera_fecha': min(primeras).isoformat() if primeras else None}


def hay_confirmada():
    return Apertura.objects.filter(estado=CONFIRMADA).exists()


def exigir_configurable(inicio, config, version=None):
    """Con el candado tomado: lo que impide guardar `config` aunque esté bien escrita, en el orden de la decisión común 6
    (versión → estado → conflicto). 409 `version`, `apertura_confirmada` o `rango_solapado`."""
    if version is not None and inicio is not None and version != inicio.version:
        raise api.ErrorApi('version', TEXTOS['version'], 409, configuracion=dict_configuracion(inicio))
    if hay_confirmada():
        raise api.ErrorApi('apertura_confirmada', TEXTOS['apertura_confirmada'], 409)
    solape = solapamiento(config['fecha_corte'])
    if solape['asientos'] or solape['aplicaciones']:
        raise api.ErrorApi('rango_solapado', TEXTOS['rango_solapado'], 409, **solape)


def autor(request):
    """`(id, nombre)` del usuario de la petición, como lo guardan los autores del bloque (decisión común 16)."""
    usuario = getattr(request, 'user', None)
    if usuario is None or not usuario.is_authenticated:
        return None, ''
    return usuario.pk, usuario.get_username()


def fila_nueva(request, config, ahora):
    """Los campos con que `libro(crear=…)` crea la fila. `creado_en = ahora` identifica después, sin otra consulta, que la
    creó esta misma petición (`creada`)."""
    por_id, por_nombre = autor(request)
    return {**config, 'creado_por_id': por_id, 'creado_por_nombre': por_nombre, 'creado_en': ahora,
            'actualizado_por_id': por_id, 'actualizado_por_nombre': por_nombre, 'actualizado_en': ahora}


def creada(inicio, ahora):
    return inicio.version == 1 and inicio.creado_en == ahora


def guardar(request, inicio, config, *, nueva=False, apertura=None):
    """Con el candado tomado y `exigir_configurable` ya pasado: escribe `config` en la fila (sube `version` si algo
    cambia) y deja su evento y su auditoría dentro de la transacción. `nueva`: la fila la acaba de crear `libro(crear=…)`
    con `config`. Devuelve `{campo: [antes, después]}` (vacío si nada cambió: entonces no deja registro)."""
    from core.contabilidad.apertura import evento   # apertura.py usa este módulo: se importa al usarlo
    if nueva:
        cambios = {campo: [None, _texto(getattr(inicio, campo))] for campo in CAMPOS}
    else:
        cambios = {campo: [_texto(getattr(inicio, campo)), _texto(config[campo])] for campo in CAMPOS
                   if getattr(inicio, campo) != config[campo]}
        if not cambios:
            return {}
        for campo in CAMPOS:
            setattr(inicio, campo, config[campo])
        inicio.version += 1
        inicio.actualizado_por_id, inicio.actualizado_por_nombre = autor(request)
        inicio.actualizado_en = timezone.now()
        inicio.save(update_fields=[*CAMPOS, 'version', 'actualizado_por_id', 'actualizado_por_nombre', 'actualizado_en'])
    evento(request, None, 'inicio_configurado', detalle={'version': inicio.version, 'cambios': cambios,
                                                         'apertura_id': apertura.pk if apertura is not None else None})
    audit(request, 'inicio_contable_configurado', company=request.company, inicio=inicio.pk, version=inicio.version,
          modalidad=inicio.modalidad, fecha_corte=inicio.fecha_corte.isoformat(), cambios=cambios)
    return cambios


def configurar(request, inicio, config, *, version=None, nueva=False, apertura=None):
    """`inicio_contable.configurar` de la especificación, dentro de `libro(…)`: comprueba (versión, apertura confirmada,
    solapamiento) y guarda. Devuelve los cambios."""
    if not nueva:
        exigir_configurable(inicio, config, version)
    return guardar(request, inicio, config, nueva=nueva, apertura=apertura)


def _texto(valor):
    return valor.isoformat() if isinstance(valor, date) else valor


# ---------------------------------------------------------------- respuestas

def dict_configuracion(inicio):
    if inicio is None:
        return None
    return {'version': inicio.version, 'modalidad': inicio.modalidad, 'fecha_corte': inicio.fecha_corte.isoformat(),
            'contabilidad_desde': inicio.contabilidad_desde.isoformat(), 'operaciones_desde': inicio.operaciones_desde.isoformat(),
            'historial_desde': _texto(inicio.historial_desde), 'historial_hasta': _texto(inicio.historial_hasta),
            'guarda_importacion': inicio.guarda_importacion}


SIN_CONFIGURAR, PENDIENTE_DE_CONFIRMAR, EN_REVISION_ETAPA, CONFIRMADA_ETAPA = 'sin_configurar', 'pendiente', 'en_revision', 'confirmada'


def etapa(acceso):
    """`etapas.apertura` del inicio contable (C1): `sin_configurar | pendiente | en_revision | confirmada` con `fecha` = el
    corte. A quien no puede ver la apertura (sin licencia o sin permiso) no se le dice en qué etapa está: `no_disponible`
    con la causa del contrato de capacidades. Con el plan de cuentas vacío la apertura no se puede preparar, pero la etapa
    se informa igual (sin configurar). Dos consultas."""
    funcion = acceso['funciones']['apertura']
    base = {'estado': 'no_disponible', 'fecha': None, 'causa': None}
    if funcion['estado'] not in (cap.DISPONIBLE, cap.DATOS_POR_COMPLETAR):
        return {**base, 'causa': funcion['texto']}
    inicio = InicioContable.objects.first()
    if inicio is None:
        return {**base, 'estado': SIN_CONFIGURAR}
    estados = Apertura.objects.aggregate(confirmada=Count('id', filter=Q(estado=CONFIRMADA)),
                                         en_revision=Count('id', filter=Q(estado=EN_REVISION)))
    estado = CONFIRMADA_ETAPA if estados['confirmada'] else (EN_REVISION_ETAPA if estados['en_revision'] else PENDIENTE_DE_CONFIRMAR)
    return {**base, 'estado': estado, 'fecha': inicio.fecha_corte.isoformat()}
