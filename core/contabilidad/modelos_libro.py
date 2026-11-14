"""Libro diario mínimo (bloque 2 del cierre contable, Parte A de contable/bloque-2-especificacion.md): el inicio contable
de la empresa (su fila es el candado del libro), el ejercicio y los períodos, los asientos con sus líneas, los acumulados
por cuenta y mes, el expediente de contabilización y el registro de claves de las acciones repetibles.

Aquí solo está lo que el esquema garantiza por sí solo. Las reglas (fechas, cuadre, numeración, candado, orden de
bloqueos) son de los servicios del bloque (`candado.py`, `diario.py`, `periodos.py`, `registro_clave.py`).

El libro es de solo inserción (decisión común 2), en tres capas:

1. un único escritor, core/contabilidad/diario.py;
2. las guardas de este archivo: `Asiento.save()` solo inserta o cambia el sello y el par del reverso, `delete()` lanza
   `LibroInmutable`, y el QuerySet de sus gestores rechaza `update`, `delete` y `bulk_update` fuera de
   `escritura_interna()`, el contexto que solo abre diario.py. `LineaAsiento` y `EventoApertura` solo se insertan;
3. los disparadores de PostgreSQL de la migración `libro_inmutable`, que rechazan lo mismo aunque se escriba por SQL.

Autores y referencias a filas de la operación (decisión común 16): ninguna ForeignKey hacia el usuario ni hacia una tabla
de la operación. El autor es el par `<rol>_por_id` (entero sin restricción) + `<rol>_por_nombre` (el nombre de usuario
fijado al escribir): borrar al usuario no lanza ningún UPDATE sobre el libro (con la FK `SET_NULL` el colector de Django lo
haría y el disparador lo rechazaría) y la fila conserva quién la escribió. Lo mismo para un documento de origen o un
tercero: entero más copia de su número e identificación; un destino que ya no existe es un estado visible, nunca un
cambio silencioso. Las únicas FK reales van hacia `company` y entre tablas contables, con `PROTECT`."""
import json
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from core.tenancy.models_base import TenantManager, TenantModel

__all__ = ['InicioContable', 'EjercicioContable', 'PeriodoContable', 'Asiento', 'LineaAsiento', 'SaldoCuentaMes',
           'Contabilizacion', 'RegistroClave']

# Importes de una línea o de un documento; totales y acumulados, dos cifras más.
IMPORTE = dict(max_digits=14, decimal_places=2)
TOTAL = dict(max_digits=16, decimal_places=2)
NOMBRE_AUTOR_MAX = 150   # como User.username: es su copia

MODALIDADES = (('saldos', 'Por saldos de apertura'), ('historial', 'Por historial detallado'))
ABIERTO, CERRADO = 'abierto', 'cerrado'
ESTADOS_PERIODO = ((ABIERTO, 'Abierto'), (CERRADO, 'Cerrado'))
TIPOS_ASIENTO = (('apertura', 'Apertura'), ('origen', 'De un documento'), ('manual', 'Manual'), ('ajuste', 'Ajuste'),
                 ('reverso', 'Reverso'), ('cierre', 'Cierre'), ('historico', 'Histórico'))
TIPOS_CON_MOTIVO = ('manual', 'ajuste', 'reverso')        # los escribe una persona: dice por qué
TIPOS_CON_ORIGEN = ('apertura', 'origen', 'cierre')       # salen de un hecho identificado: (tipo, id, evento)
TIPOS_TERCERO = (('', 'Sin tercero'), ('cliente', 'Cliente'), ('proveedor', 'Proveedor'), ('otro', 'Otro'))
CONFIRMADO = 'confirmado'
ESTADOS_EXPEDIENTE = (('pendiente', 'Pendiente'), ('borrador', 'Borrador'), ('con_excepcion', 'Con excepción'),
                      (CONFIRMADO, 'Confirmado'), ('anulado', 'Anulado'), ('sin_efecto', 'Sin efecto'),
                      ('descartado', 'Descartado'))

# Lo único que cambia en un asiento ya insertado: el sello (una vez, false → true) y el par del reverso (una vez, los dos
# juntos). Nombres y atributos, porque `update_fields` admite los dos.
CAMBIOS_DEL_ASIENTO = frozenset({'sellado', 'reversado_por', 'reversado_por_id', 'reversado_en'})
# Lo que un expediente confirmado ya no cambia (la divergencia se escribe aparte: huella_actual, hecho_actual, divergente,
# excepciones). El bloque 3 añade aquí `regla_version`.
CONGELADOS_AL_CONFIRMAR = ('hecho', 'propuesta', 'huella_origen', 'tesoreria_cuenta')


def autor(etiqueta):
    """Los dos campos de un autor según la decisión común 16: `(<rol>_por_id, <rol>_por_nombre)`. Se declaran juntos:

        creado_por_id, creado_por_nombre = autor('Registrado por')

    El id es el del usuario al escribir, sin restricción de base; el nombre, su nombre de usuario en ese momento (lo que se
    muestra, también cuando el usuario ya no existe)."""
    return (models.BigIntegerField(null=True, blank=True, verbose_name=f'{etiqueta} (id del usuario)'),
            models.CharField(max_length=NOMBRE_AUTOR_MAX, blank=True, default='', verbose_name=etiqueta))


# ---------------------------------------------------------------- guardas del libro

class LibroInmutable(Exception):
    """Intento de cambiar o borrar lo que el libro ya guardó. Es un error de programación, no una respuesta para el
    usuario: lo confirmado se corrige con un reverso o un ajuste, nunca editándolo."""


_escritura_interna = ContextVar('fpa_escritura_interna_del_libro', default=False)


@contextmanager
def escritura_interna():
    """Contexto en el que el QuerySet de `Asiento` admite `update` y `bulk_update`. Solo lo abre core/contabilidad/diario.py
    (lo vigila una prueba ast), dentro de la transacción con el candado del libro, para sellar el asiento recién insertado
    y para fijar en el original, en una sola sentencia, el par `reversado_por`/`reversado_en`. Ni dentro de él se cambia
    otra columna, ni se borra un asiento, ni se toca una línea: en PostgreSQL lo rechazaría además el disparador.

    Para lo mismo diario.py también puede usar `asiento.save(update_fields=[...])`, que no necesita este contexto."""
    token = _escritura_interna.set(True)
    try:
        yield
    finally:
        _escritura_interna.reset(token)


def _rechazar(modelo, que):
    raise LibroInmutable(f'{modelo._meta.label}: {que}. El libro es de solo inserción: se corrige con un reverso o un ajuste.')


class AsientoQuerySet(models.QuerySet):
    """Fuera de `escritura_interna()` no hay `update`, `delete` ni `bulk_update`; dentro, `update` y `bulk_update` solo
    del sello y del par del reverso, y `delete` nunca. Insertar (`create`, `bulk_create`) no pasa por aquí: lo restringe
    la prueba ast a diario.py."""

    def _exigir(self, campos, que):
        if not _escritura_interna.get():
            _rechazar(self.model, f'{que} fuera de diario.py')
        otros = set(campos) - CAMBIOS_DEL_ASIENTO
        if otros:
            _rechazar(self.model, f'{que} de {", ".join(sorted(otros))}')

    def update(self, **kwargs):
        self._exigir(kwargs, 'update')
        return super().update(**kwargs)
    update.alters_data = True

    def bulk_update(self, objs, fields, batch_size=None):
        self._exigir(fields, 'bulk_update')
        return super().bulk_update(objs, fields, batch_size=batch_size)
    bulk_update.alters_data = True

    def delete(self):
        _rechazar(self.model, 'delete')
    delete.alters_data = True
    delete.queryset_only = True


class SoloInsercionQuerySet(models.QuerySet):
    """Filas que solo se insertan (líneas de asiento, historia de la apertura): ni `update`, ni `delete`, ni
    `bulk_update`, en ningún contexto."""

    def update(self, **kwargs):
        _rechazar(self.model, 'update')
    update.alters_data = True

    def bulk_update(self, objs, fields, batch_size=None):
        _rechazar(self.model, 'bulk_update')
    bulk_update.alters_data = True

    def delete(self):
        _rechazar(self.model, 'delete')
    delete.alters_data = True
    delete.queryset_only = True


class SoloInsercion(TenantModel):
    """Base de los modelos de solo inserción: `save()` inserta (con `force_insert`, para que un id repetido falle y no
    actualice la fila que ya existe) y nada más; `delete()` lanza."""
    objects = TenantManager.from_queryset(SoloInsercionQuerySet)()
    all_companies = models.Manager.from_queryset(SoloInsercionQuerySet)()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            _rechazar(type(self), 'save de una fila ya guardada')
        if kwargs.get('update_fields') is not None:
            _rechazar(type(self), 'save con update_fields de una fila nueva')
        kwargs['force_insert'] = True
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        _rechazar(type(self), 'delete')


def _normal(valor):
    """El valor como queda guardado en un JSONField con DjangoJSONEncoder: así un Decimal o una fecha recién asignados se
    comparan igual que lo leído de la base."""
    return json.loads(json.dumps(valor, cls=DjangoJSONEncoder, sort_keys=True))


class ExpedienteQuerySet(models.QuerySet):
    """`update` de un campo congelado sobre algún expediente confirmado lanza (la guarda de `Contabilizacion.save` en
    sentencias de lote)."""

    def _exigir(self, campos):
        congelados = {c for c in CONGELADOS_AL_CONFIRMAR for nombre in (c, f'{c}_id') if nombre in set(campos)}
        if congelados and self.filter(estado=CONFIRMADO).exists():
            _rechazar(self.model, f'{", ".join(sorted(congelados))} de un expediente confirmado')

    def update(self, **kwargs):
        self._exigir(kwargs)
        return super().update(**kwargs)
    update.alters_data = True

    def bulk_update(self, objs, fields, batch_size=None):
        self._exigir(fields)
        return super().bulk_update(objs, fields, batch_size=batch_size)
    bulk_update.alters_data = True


# ---------------------------------------------------------------- inicio, ejercicio y períodos

class InicioContable(TenantModel):
    """Configuración del inicio contable: una fila por empresa, y esa fila es el candado del libro (decisión común 3:
    `candado.libro()` la toma con `select_for_update(of=('self',))` antes de cambiar el libro o lo que decide qué entra).

    `contabilidad_desde` es el primer día que admite asientos ordinarios (= corte + 1); `operaciones_desde`, el primero cuya
    operación se contabilizará (saldos: corte + 1; historial: `historial_hasta` + 1). Elegir la modalidad no da por completo
    ningún rango. `guarda_importacion` es la activación por empresa de la guarda de la Parte F: nace apagada."""
    modalidad = models.CharField(max_length=10, choices=MODALIDADES, verbose_name='Modalidad')
    fecha_corte = models.DateField(verbose_name='Fecha de corte')
    contabilidad_desde = models.DateField(verbose_name='Contabilidad desde')
    operaciones_desde = models.DateField(verbose_name='Operaciones desde')
    historial_desde = models.DateField(null=True, blank=True, verbose_name='Historial desde')   # nulos en `saldos`
    historial_hasta = models.DateField(null=True, blank=True, verbose_name='Historial hasta')
    guarda_importacion = models.BooleanField(default=False, verbose_name='Guarda de la importación activa')
    version = models.PositiveIntegerField(default=1, verbose_name='Versión')
    creado_por_id, creado_por_nombre = autor('Configurado por')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Configurado el')
    actualizado_por_id, actualizado_por_nombre = autor('Actualizado por')
    actualizado_en = models.DateTimeField(default=timezone.now, verbose_name='Actualizado el')

    class Meta:
        verbose_name = 'Inicio contable'
        verbose_name_plural = 'Inicios contables'
        default_permissions = ()   # lo gobiernan los permisos de la apertura
        constraints = [
            models.UniqueConstraint(fields=('company',), name='inicio_contable_unico'),
            models.CheckConstraint(condition=Q(contabilidad_desde__gt=F('fecha_corte')), name='inicio_contable_desde_tras_corte'),
            models.CheckConstraint(condition=~Q(modalidad='saldos') | Q(historial_desde__isnull=True, historial_hasta__isnull=True),
                                   name='inicio_contable_saldos_sin_historial'),
            # Los IS NOT NULL no están en la especificación: sin ellos un historial sin fechas pasaría el CHECK (una
            # comparación con NULL no es falsa para PostgreSQL ni para SQLite).
            models.CheckConstraint(condition=~Q(modalidad='historial') | Q(
                historial_desde__isnull=False, historial_hasta__isnull=False,
                historial_desde=F('contabilidad_desde'), historial_hasta__gte=F('historial_desde')),
                name='inicio_contable_historial_coherente'),
        ]

    def __str__(self):
        return f'Inicio contable ({self.get_modalidad_display()}, corte {self.fecha_corte:%d/%m/%Y})'


class EjercicioContable(TenantModel):
    """Ejercicio (año) de la empresa: lleva el correlativo de sus asientos (`ultimo_numero`, sin huecos). Se crea al
    contabilizar el primer asiento del año. Cerrarlo es del bloque 6; sus permisos ya se declaran aquí."""
    anio = models.PositiveSmallIntegerField(verbose_name='Año')
    ultimo_numero = models.PositiveIntegerField(default=0, verbose_name='Último número de asiento')
    estado = models.CharField(max_length=8, choices=ESTADOS_PERIODO, default=ABIERTO, verbose_name='Estado')
    asiento_cierre = models.ForeignKey('Asiento', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                       verbose_name='Asiento de cierre')
    cerrado_por_id, cerrado_por_nombre = autor('Cerrado por')
    cerrado_en = models.DateTimeField(null=True, blank=True, verbose_name='Cerrado el')
    version = models.PositiveIntegerField(default=1, verbose_name='Versión')

    class Meta:
        verbose_name = 'Ejercicio contable'
        verbose_name_plural = 'Ejercicios contables'
        ordering = ('anio',)
        # Declarados para el bloque 6, que los reparte: todavía no cuelgan de ningún módulo.
        default_permissions = ('change',)
        permissions = (('change_reapertura_ejerciciocontable', 'Puede reabrir un ejercicio contable cerrado'),)
        constraints = [
            models.UniqueConstraint(fields=('company', 'anio'), name='ejercicio_anio_unico'),
            models.CheckConstraint(condition=Q(anio__gte=2000, anio__lte=2100), name='ejercicio_anio_valido'),
            models.CheckConstraint(condition=Q(estado=CERRADO, cerrado_en__isnull=False)
                                   | (~Q(estado=CERRADO) & Q(cerrado_en__isnull=True)), name='ejercicio_cerrado_con_fecha'),
        ]

    def __str__(self):
        return f'Ejercicio {self.anio} ({self.get_estado_display()})'


class PeriodoContable(TenantModel):
    """Estado de un mes. Sin fila, el mes está abierto: aquí solo la tabla (y `periodos.exigir_abierto`); cerrar y reabrir
    son del bloque 4, que reparte sus permisos."""
    anio = models.PositiveSmallIntegerField(verbose_name='Año')
    mes = models.PositiveSmallIntegerField(verbose_name='Mes')
    estado = models.CharField(max_length=8, choices=ESTADOS_PERIODO, default=ABIERTO, verbose_name='Estado')
    version = models.PositiveIntegerField(default=1, verbose_name='Versión')
    cerrado_por_id, cerrado_por_nombre = autor('Cerrado por')
    cerrado_en = models.DateTimeField(null=True, blank=True, verbose_name='Cerrado el')

    class Meta:
        verbose_name = 'Período contable'
        verbose_name_plural = 'Períodos contables'
        ordering = ('anio', 'mes')
        default_permissions = ('view', 'change')
        permissions = (('change_reapertura_periodocontable', 'Puede reabrir un período contable cerrado'),)
        constraints = [
            models.UniqueConstraint(fields=('company', 'anio', 'mes'), name='periodo_mes_unico'),
            models.CheckConstraint(condition=Q(mes__gte=1, mes__lte=12), name='periodo_mes_valido'),
        ]

    def __str__(self):
        return f'Período {self.anio}-{self.mes:02d} ({self.get_estado_display()})'


# ---------------------------------------------------------------- asientos

class Asiento(TenantModel):
    """Asiento contabilizado. Solo lo contabilizado: propuestas, borradores y excepciones viven en `Contabilizacion`.

    diario.py lo inserta sin sellar, inserta sus líneas y lo sella en la misma transacción (en PostgreSQL un disparador
    rechaza insertarlo ya sellado, otro diferido rechaza confirmar un asiento sin sellar, y otro, insertar una línea en uno
    sellado). Al reversarlo se fijan
    una sola vez, juntos, `reversado_por` y `reversado_en`. `huella` = SHA-256 del contenido canónico `v1` (empresa, año,
    número, fecha, tipo, origen y líneas ordenadas). `numero` es correlativo por empresa y año, sin huecos."""
    ejercicio = models.ForeignKey(EjercicioContable, on_delete=models.PROTECT, related_name='+', verbose_name='Ejercicio')
    anio = models.PositiveSmallIntegerField(verbose_name='Año')
    mes = models.PositiveSmallIntegerField(verbose_name='Mes')
    numero = models.PositiveIntegerField(verbose_name='Número')
    fecha = models.DateField(verbose_name='Fecha')
    tipo = models.CharField(max_length=10, choices=TIPOS_ASIENTO, verbose_name='Tipo')
    concepto = models.CharField(max_length=300, verbose_name='Concepto')
    # El hecho del que sale: (origen_tipo, origen_id, evento), sin restricción hacia su tabla, más copia de su número y
    # fecha. Vocabulario abierto: lo amplían los bloques siguientes sin migración.
    origen_tipo = models.CharField(max_length=30, blank=True, default='', verbose_name='Tipo de origen')
    origen_id = models.BigIntegerField(null=True, blank=True, verbose_name='Id del origen')
    evento = models.CharField(max_length=30, blank=True, default='', verbose_name='Evento del origen')
    origen_numero = models.CharField(max_length=60, blank=True, default='', verbose_name='Número del origen')
    origen_fecha = models.DateField(null=True, blank=True, verbose_name='Fecha del origen')
    reversa_de = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                   verbose_name='Reversa el asiento')
    reversado_por = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                      verbose_name='Reversado por el asiento')
    reversado_en = models.DateTimeField(null=True, blank=True, verbose_name='Reversado el')
    total_debe = models.DecimalField(**TOTAL, verbose_name='Total debe')
    total_haber = models.DecimalField(**TOTAL, verbose_name='Total haber')
    lineas_n = models.PositiveIntegerField(verbose_name='Número de líneas')
    sellado = models.BooleanField(default=False, verbose_name='Sellado')
    huella = models.CharField(max_length=64, verbose_name='Huella (SHA-256)')
    motivo = models.CharField(max_length=300, blank=True, default='', verbose_name='Motivo')
    clave = models.CharField(max_length=40, null=True, blank=True, verbose_name='Clave del envío')
    creado_por_id, creado_por_nombre = autor('Contabilizado por')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Contabilizado el')

    objects = TenantManager.from_queryset(AsientoQuerySet)()
    all_companies = models.Manager.from_queryset(AsientoQuerySet)()

    class Meta:
        verbose_name = 'Asiento'
        verbose_name_plural = 'Asientos'
        ordering = ('anio', 'numero')
        # add_ y change_ se declaran para el bloque 3 (asiento manual) y change_reverso_ para el reverso desde su ruta;
        # en este bloque solo se reparte view_asiento.
        default_permissions = ('add', 'change')
        permissions = (('view_asiento', 'Puede ver el diario y el mayor'),
                       ('change_reverso_asiento', 'Puede reversar un asiento'))
        constraints = [
            models.UniqueConstraint(fields=('company', 'anio', 'numero'), name='asiento_numero_unico'),
            # Un solo asiento vigente por hecho: el reverso y el reversado no cuentan.
            models.UniqueConstraint(fields=('company', 'origen_tipo', 'origen_id', 'evento'),
                                    condition=Q(origen_id__isnull=False, reversado_por__isnull=True, reversa_de__isnull=True),
                                    name='asiento_origen_vigente_unico'),
            models.UniqueConstraint(fields=('company',), condition=Q(tipo='apertura', reversado_por__isnull=True),
                                    name='asiento_apertura_unica'),
            models.UniqueConstraint(fields=('company', 'reversa_de'), condition=Q(reversa_de__isnull=False),
                                    name='asiento_un_reverso'),
            models.UniqueConstraint(fields=('company', 'clave'), condition=Q(clave__isnull=False), name='asiento_clave_unica'),
            models.CheckConstraint(condition=Q(total_debe=F('total_haber'), total_debe__gt=0, lineas_n__gte=2),
                                   name='asiento_cuadrado'),
            models.CheckConstraint(condition=Q(tipo='reverso', reversa_de__isnull=False)
                                   | (~Q(tipo='reverso') & Q(reversa_de__isnull=True)), name='asiento_reverso_con_original'),
            models.CheckConstraint(condition=Q(reversa_de__isnull=True) | Q(reversado_por__isnull=True),
                                   name='asiento_reverso_no_se_reversa'),
            models.CheckConstraint(condition=Q(reversado_por__isnull=True, reversado_en__isnull=True)
                                   | Q(reversado_por__isnull=False, reversado_en__isnull=False),
                                   name='asiento_reversado_con_fecha'),
            models.CheckConstraint(condition=~Q(tipo__in=TIPOS_CON_MOTIVO) | ~Q(motivo=''), name='asiento_motivo_obligatorio'),
            models.CheckConstraint(condition=~Q(tipo__in=TIPOS_CON_ORIGEN)
                                   | (Q(origen_id__isnull=False) & ~Q(origen_tipo='') & ~Q(evento='')),
                                   name='asiento_origen_obligatorio'),
            models.CheckConstraint(condition=~Q(creado_por_nombre=''), name='asiento_con_autor'),
        ]
        indexes = [
            models.Index(fields=('company', 'fecha', 'numero'), name='asiento_por_fecha'),
            models.Index(fields=('company', 'origen_tipo', 'origen_id'), name='asiento_por_origen'),
            models.Index(fields=('company', 'tipo', 'fecha'), name='asiento_por_tipo'),
        ]

    def save(self, *args, **kwargs):
        campos = kwargs.get('update_fields')
        if self._state.adding:
            if campos is not None:
                _rechazar(type(self), 'save con update_fields de un asiento nuevo')
            # Nace abierto y sin reverso: el sello comprueba que las líneas cuadran, y un asiento insertado ya sellado se
            # lo saltaría (quedaría en el libro sin líneas). El disparador fpa_asiento_nace_abierto dice lo mismo.
            if self.sellado or self.reversado_por_id is not None or self.reversado_en is not None:
                _rechazar(type(self), 'un asiento nuevo nace sin sellar y sin reverso')
            kwargs['force_insert'] = True   # un id repetido falla: nunca actualiza el asiento que ya existe
        elif campos is None or not set(campos) <= CAMBIOS_DEL_ASIENTO:
            _rechazar(type(self), 'save de un asiento ya guardado (solo el sello y el par del reverso)')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        _rechazar(type(self), 'delete')

    @property
    def numero_completo(self):
        """`2025-000001`: el número como lo muestra el contrato."""
        return f'{self.anio}-{self.numero:06d}'

    def __str__(self):
        return f'Asiento {self.numero_completo} ({self.get_tipo_display()})'


class LineaAsiento(SoloInsercion):
    """Línea de un asiento, de solo inserción. `fecha`, `anio` y `mes` son copias del asiento (el mayor no lo une).
    El tercero y el documento son enteros sin restricción más su copia (decisión común 16). `componente` y
    `concepto_tributario` quedan vacíos en este bloque: los llenan los bloques 3 y 5."""
    asiento = models.ForeignKey(Asiento, on_delete=models.PROTECT, related_name='lineas', verbose_name='Asiento')
    orden = models.PositiveIntegerField(verbose_name='Orden')
    cuenta = models.ForeignKey('Cuenta', on_delete=models.PROTECT, related_name='+', verbose_name='Cuenta')
    debe = models.DecimalField(**IMPORTE, verbose_name='Debe')
    haber = models.DecimalField(**IMPORTE, verbose_name='Haber')
    fecha = models.DateField(verbose_name='Fecha')
    anio = models.PositiveSmallIntegerField(verbose_name='Año')
    mes = models.PositiveSmallIntegerField(verbose_name='Mes')
    concepto = models.CharField(max_length=200, blank=True, default='', verbose_name='Concepto')
    tercero_tipo = models.CharField(max_length=10, blank=True, default='', choices=TIPOS_TERCERO, verbose_name='Tipo de tercero')
    tercero_id = models.BigIntegerField(null=True, blank=True, verbose_name='Id del cliente o proveedor')
    tercero_identificacion = models.CharField(max_length=20, blank=True, default='', verbose_name='Identificación del tercero')
    tercero_nombre = models.CharField(max_length=200, blank=True, default='', verbose_name='Nombre del tercero')
    documento_tipo = models.CharField(max_length=30, blank=True, default='', verbose_name='Tipo de documento')
    documento_id = models.BigIntegerField(null=True, blank=True, verbose_name='Id del documento')
    documento_numero = models.CharField(max_length=60, blank=True, default='', verbose_name='Número del documento')
    componente = models.CharField(max_length=40, blank=True, default='', verbose_name='Componente')
    concepto_tributario = models.CharField(max_length=30, blank=True, default='', verbose_name='Concepto tributario')

    class Meta:
        verbose_name = 'Línea de asiento'
        verbose_name_plural = 'Líneas de asiento'
        ordering = ('asiento', 'orden')
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=('asiento', 'orden'), name='linea_asiento_orden_unico'),
            models.CheckConstraint(condition=Q(debe__gt=0, haber=0) | Q(debe=0, haber__gt=0), name='linea_asiento_un_lado'),
            models.CheckConstraint(condition=~Q(tercero_tipo='') | Q(tercero_id__isnull=True), name='linea_asiento_tercero_con_tipo'),
        ]
        indexes = [
            models.Index(fields=('company', 'cuenta', 'fecha', 'id'), name='linea_asiento_mayor'),
            models.Index(fields=('company', 'cuenta', 'tercero_tipo', 'tercero_id'), condition=~Q(tercero_tipo=''),
                         name='linea_asiento_tercero'),
            models.Index(fields=('company', 'documento_tipo', 'documento_id'), condition=Q(documento_id__isnull=False),
                         name='linea_asiento_documento'),
            models.Index(fields=('company', 'concepto_tributario', 'fecha'), condition=~Q(concepto_tributario=''),
                         name='linea_asiento_tributario'),
        ]

    def __str__(self):
        return f'Línea {self.orden} del asiento {self.asiento_id}'


class SaldoCuentaMes(TenantModel):
    """Acumulado por cuenta y mes de todo lo contabilizado (`debe`, `haber`) y, dentro de ello, aparte, lo de los asientos
    de apertura y de cierre y sus reversos. Lo mantiene diario.contabilizar en la misma transacción y con el candado; solo
    crece (un reverso suma al lado contrario, en las mismas columnas que su original). Así el balance muestra la apertura
    en columna propia y el estado de resultados excluye el cierre sin leer líneas."""
    cuenta = models.ForeignKey('Cuenta', on_delete=models.PROTECT, related_name='+', verbose_name='Cuenta')
    anio = models.PositiveSmallIntegerField(verbose_name='Año')
    mes = models.PositiveSmallIntegerField(verbose_name='Mes')
    debe = models.DecimalField(**TOTAL, default=0, verbose_name='Debe')
    haber = models.DecimalField(**TOTAL, default=0, verbose_name='Haber')
    apertura_debe = models.DecimalField(**TOTAL, default=0, verbose_name='Debe de apertura')
    apertura_haber = models.DecimalField(**TOTAL, default=0, verbose_name='Haber de apertura')
    cierre_debe = models.DecimalField(**TOTAL, default=0, verbose_name='Debe de cierre')
    cierre_haber = models.DecimalField(**TOTAL, default=0, verbose_name='Haber de cierre')

    class Meta:
        verbose_name = 'Saldo de cuenta por mes'
        verbose_name_plural = 'Saldos de cuenta por mes'
        ordering = ('anio', 'mes', 'cuenta')
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=('company', 'cuenta', 'anio', 'mes'), name='saldo_cuenta_mes_unico'),
            models.CheckConstraint(condition=Q(debe__gte=0, haber__gte=0, apertura_debe__gte=0, apertura_haber__gte=0,
                                               cierre_debe__gte=0, cierre_haber__gte=0), name='saldo_cuenta_mes_no_negativo'),
            models.CheckConstraint(condition=Q(debe__gte=F('apertura_debe') + F('cierre_debe')),
                                   name='saldo_cuenta_mes_desglose_debe'),
            models.CheckConstraint(condition=Q(haber__gte=F('apertura_haber') + F('cierre_haber')),
                                   name='saldo_cuenta_mes_desglose_haber'),
        ]
        indexes = [models.Index(fields=('company', 'anio', 'mes'), name='saldo_cuenta_mes_periodo')]

    def __str__(self):
        return f'Saldo de la cuenta {self.cuenta_id} en {self.anio}-{self.mes:02d}'


# ---------------------------------------------------------------- expediente y claves

class Contabilizacion(TenantModel):
    """Expediente de contabilización: una fila por hecho contabilizable, con su estado, lo que se contabilizó (huella y
    hecho congelados al confirmar), lo último leído del origen si ya no coincide (`huella_actual`, `hecho_actual`), la
    propuesta de líneas y sus excepciones. En este bloque solo lo usan los cobros, pagos y descargos sobre saldos
    iniciales; la bandeja y el motor son del bloque 3, que le añade `regla_version`.

    Guarda de modelo: confirmado, `hecho`, `propuesta`, `huella_origen` y `tesoreria_cuenta` no cambian (save, update y
    bulk_update lanzan `LibroInmutable`); la divergencia se escribe en `huella_actual`, `hecho_actual`, `divergente` y
    `excepciones`."""
    origen_tipo = models.CharField(max_length=30, verbose_name='Tipo de origen')
    origen_id = models.BigIntegerField(null=True, blank=True, verbose_name='Id del origen')   # nulo solo en manuales (bloque 3)
    evento = models.CharField(max_length=30, verbose_name='Evento')
    estado = models.CharField(max_length=14, choices=ESTADOS_EXPEDIENTE, default='pendiente', verbose_name='Estado')
    fecha_contable = models.DateField(null=True, blank=True, verbose_name='Fecha contable')
    origen_numero = models.CharField(max_length=60, blank=True, default='', verbose_name='Número del origen')
    origen_fecha = models.DateField(null=True, blank=True, verbose_name='Fecha del origen')
    tercero_nombre = models.CharField(max_length=200, blank=True, default='', verbose_name='Tercero')
    importe = models.DecimalField(**IMPORTE, null=True, blank=True, verbose_name='Importe')
    huella_origen = models.CharField(max_length=64, blank=True, default='', verbose_name='Huella del origen contabilizado')
    hecho = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder, verbose_name='Hecho contabilizado')
    # [{linea, cuenta_id | null, concepto, debe, haber, tercero, documento, componente, selector, dimension, clave,
    #   concepto_tributario}]
    propuesta = models.JSONField(default=list, blank=True, encoder=DjangoJSONEncoder, verbose_name='Propuesta de líneas')
    # La cuenta de tesorería con que se evaluó: fuera de la huella.
    tesoreria_cuenta = models.ForeignKey('Cuenta', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                         verbose_name='Cuenta de tesorería')
    huella_actual = models.CharField(max_length=64, blank=True, default='', verbose_name='Huella actual del origen')
    hecho_actual = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder, verbose_name='Hecho actual del origen')
    # [{codigo, texto, linea | null, nivel: bloquea | informa, detalle}]
    excepciones = models.JSONField(default=list, blank=True, encoder=DjangoJSONEncoder, verbose_name='Excepciones')
    codigo_excepcion = models.CharField(max_length=40, blank=True, default='', verbose_name='Excepción principal')
    causa_sin_efecto = models.CharField(max_length=40, blank=True, default='', verbose_name='Causa sin efecto')
    asiento = models.ForeignKey(Asiento, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                verbose_name='Asiento (el vigente o el último)')
    divergente = models.BooleanField(default=False, verbose_name='Divergente')
    anulacion_pendiente = models.BooleanField(default=False, verbose_name='Anulación pendiente')
    sello = models.PositiveIntegerField(default=0, verbose_name='Sello')
    intentos = models.PositiveIntegerField(default=0, verbose_name='Intentos')
    procesado_en = models.DateTimeField(null=True, blank=True, verbose_name='Procesado el')
    verificado_en = models.DateTimeField(null=True, blank=True, verbose_name='Origen verificado el')
    version = models.PositiveIntegerField(default=1, verbose_name='Versión')
    clave = models.CharField(max_length=40, null=True, blank=True, verbose_name='Clave del envío')
    clave_confirmacion = models.CharField(max_length=40, null=True, blank=True, verbose_name='Clave de la confirmación')
    motivo = models.CharField(max_length=300, blank=True, default='', verbose_name='Motivo')
    creado_por_id, creado_por_nombre = autor('Creado por')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Creado el')
    confirmado_por_id, confirmado_por_nombre = autor('Confirmado por')
    confirmado_en = models.DateTimeField(null=True, blank=True, verbose_name='Confirmado el')

    objects = TenantManager.from_queryset(ExpedienteQuerySet)()
    all_companies = models.Manager.from_queryset(ExpedienteQuerySet)()

    class Meta:
        verbose_name = 'Expediente de contabilización'
        verbose_name_plural = 'Expedientes de contabilización'
        ordering = ('-id',)
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=('company', 'origen_tipo', 'origen_id', 'evento'), condition=Q(origen_id__isnull=False),
                                    name='expediente_origen_unico'),
            models.UniqueConstraint(fields=('company', 'clave'), condition=Q(clave__isnull=False), name='expediente_clave_unica'),
            models.UniqueConstraint(fields=('asiento',), condition=Q(asiento__isnull=False), name='expediente_asiento_unico'),
            models.CheckConstraint(condition=Q(estado__in=[e for e, _ in ESTADOS_EXPEDIENTE]), name='expediente_estado_valido'),
            models.CheckConstraint(condition=~Q(estado=CONFIRMADO) | Q(asiento__isnull=False), name='expediente_confirmado_con_asiento'),
            models.CheckConstraint(condition=~Q(estado='sin_efecto') | ~Q(causa_sin_efecto=''), name='expediente_sin_efecto_con_causa'),
        ]
        indexes = [
            models.Index(fields=('company', 'estado', 'fecha_contable'), name='expediente_estado_fecha'),
            models.Index(fields=('company', 'estado', 'evento'), name='expediente_estado_evento'),
            models.Index(fields=('company', 'codigo_excepcion'), condition=Q(estado='con_excepcion'), name='expediente_excepcion'),
            models.Index(fields=('company', 'verificado_en'), name='expediente_verificado'),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk is not None:
            self._exigir_congelados(kwargs.get('update_fields'))
        super().save(*args, **kwargs)

    def _exigir_congelados(self, update_fields):
        """Con la fila confirmada en la base, los campos congelados que este save escribiría deben seguir igual. Se compara
        con lo guardado (una consulta), no con lo leído al cargar: vale también para una instancia armada a mano."""
        campos = set(update_fields) if update_fields is not None else None
        vigilados = [c for c in CONGELADOS_AL_CONFIRMAR if campos is None or c in campos or f'{c}_id' in campos]
        if not vigilados:
            return
        columnas = {c: self._meta.get_field(c).attname for c in vigilados}
        guardado = type(self)._base_manager.filter(pk=self.pk).values('estado', *columnas.values()).first()
        if guardado is None or guardado['estado'] != CONFIRMADO:
            return
        cambiados = [c for c, columna in columnas.items() if _normal(getattr(self, columna)) != _normal(guardado[columna])]
        if cambiados:
            _rechazar(type(self), f'{", ".join(cambiados)} de un expediente confirmado')

    def __str__(self):
        return f'Expediente {self.origen_tipo} {self.origen_id} {self.evento} ({self.get_estado_display()})'


class RegistroClave(TenantModel):
    """Idempotencia de una acción repetible o por lote sobre un recurso que ya existe (decisión común 5c): la clave del
    envío, la acción, el recurso, la huella del contenido normalizado sin la clave y lo necesario para rehacer la
    respuesta. Se inserta en la transacción que tiene el recurso bloqueado."""
    clave = models.CharField(max_length=40, verbose_name='Clave del envío')
    accion = models.CharField(max_length=40, verbose_name='Acción')
    recurso_tipo = models.CharField(max_length=30, verbose_name='Tipo de recurso')
    recurso_id = models.BigIntegerField(null=True, blank=True, verbose_name='Id del recurso')
    huella = models.CharField(max_length=64, verbose_name='Huella del contenido')
    resultado = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder, verbose_name='Resultado')
    creado_por_id, creado_por_nombre = autor('Enviado por')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Enviado el')

    class Meta:
        verbose_name = 'Clave de envío registrada'
        verbose_name_plural = 'Claves de envío registradas'
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=('company', 'clave'), name='registro_clave_unica')]

    def __str__(self):
        return f'{self.accion} · {self.clave}'
