"""Apertura contable (bloque 2 del cierre contable, Partes B a F de contable/bloque-2-especificacion.md; C6-A): la apertura
con sus líneas, archivos y ajustes, el detalle que explica cada saldo (auxiliares, partidas de banco), lo que se aplica
sobre los saldos iniciales, los documentos históricos destinados, la cobertura declarada por mes y la historia.

Todas las tablas del bloque nacen en el corte 1; las de las Partes C a F quedan vacías hasta que el corte 2 añada su
código. Aquí solo está lo que la base garantiza por sí sola; las reglas son de los servicios (`apertura.py`,
`apertura_importar.py`, `auxiliares.py`, `cartera_inicial.py`, `historico.py`, `cobertura.py`).

Nada se borra: lo que deja de valer se anula (con autor, fecha y motivo), se sustituye o se reversa. Las líneas de la
apertura tampoco se borran: sus auxiliares las referencian con `PROTECT`.

Referencias a la operación (decisión común 16): un cliente, un proveedor, un producto, una cuenta por cobrar o por pagar
o un documento importado se guardan como entero sin restricción más la copia de su número, identificación o nombre,
validados al escribir con `objects`. Que el destino ya no exista es un estado visible (`vinculo_roto`), nunca un cambio de
lo confirmado. Las únicas FK hacia fuera de estas tablas van a `company` y a `contabilidad_movimientomanual` (el kardex)."""
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django_cleanup import cleanup

from core.contabilidad.modelos_libro import IMPORTE, TOTAL, SoloInsercion, autor
from core.importacion.models import RutaPrivada
from core.tenancy.models_base import TenantModel

__all__ = ['Apertura', 'LineaApertura', 'ImportacionApertura', 'RespaldoApertura', 'AjusteApertura', 'AuxiliarApertura',
           'PartidaBancoApertura', 'AplicacionAuxiliar', 'VinculoHistorico', 'CoberturaPeriodo', 'EventoApertura']

CARPETA = 'apertura'   # privado/empresas/<uuid>/apertura/…: solo sale por las vistas de la apertura

FUENTES = (('balance_comprobacion', 'Balance de comprobación'), ('estado_situacion', 'Estado de situación'),
           ('captura_manual', 'Captura manual'), ('sistema_anterior', 'Sistema anterior'),
           ('inicio_actividades', 'Inicio de actividades'))
BORRADOR, EN_REVISION, CONFIRMADA = 'borrador', 'en_revision', 'confirmada'
SUSTITUIDA, REVERSADA, DESCARTADA = 'sustituida', 'reversada', 'descartada'
ESTADOS_APERTURA = ((BORRADOR, 'Borrador'), (EN_REVISION, 'En revisión'), (CONFIRMADA, 'Confirmada'),
                    (SUSTITUIDA, 'Sustituida'), (REVERSADA, 'Reversada'), (DESCARTADA, 'Descartada'))
EN_PREPARACION = (BORRADOR, EN_REVISION)
CON_CONFIRMACION = (CONFIRMADA, SUSTITUIDA, REVERSADA)   # pasaron por confirmar
RESULTADOS_EJERCICIO = (('', 'Sin declarar'), ('no_aplica', 'No aplica'),
                        ('en_cuentas_nominales', 'En cuentas de resultados'), ('en_patrimonio', 'En patrimonio'))
MODOS_INVENTARIO = (('solo_conciliar', 'Solo conciliar con el kardex'), ('reiniciar_kardex', 'Reiniciar el kardex'))
TIPOS_IMPORTACION = (('saldos', 'Saldos'), ('auxiliares', 'Auxiliares'))
ESTADOS_IMPORTACION = (('vista_previa', 'Vista previa'), ('aplicado', 'Aplicado'), ('descartado', 'Descartado'))
VIGENTE, ANULADO = 'vigente', 'anulado'
ESTADOS_VIGENCIA = ((VIGENTE, 'Vigente'), (ANULADO, 'Anulado'))
ES_VIGENTE = Q(estado=VIGENTE)
ESTADOS_AJUSTE = ((VIGENTE, 'Vigente'), ('reversado', 'Reversado'))
NATURALEZAS = (('cliente', 'Clientes'), ('proveedor', 'Proveedores'), ('inventario', 'Inventario'), ('banco', 'Bancos'),
               ('activo', 'Activos'), ('tributario', 'Tributario'))
DE_TERCERO = ('cliente', 'proveedor')
CONCEPTOS_TRIBUTARIOS = (('credito_iva_adquisiciones', 'Crédito tributario de IVA por adquisiciones'),
                         ('credito_iva_retenciones', 'Crédito tributario de IVA por retenciones'),
                         ('retenciones_renta_por_compensar', 'Retenciones de renta por compensar'),
                         ('iva_por_pagar', 'IVA por pagar'), ('retenciones_por_pagar', 'Retenciones por pagar'),
                         ('otro', 'Otro'))
TIPOS_PARTIDA = (('deposito_transito', 'Depósito en tránsito'), ('cheque_pendiente', 'Cheque pendiente de cobro'),
                 ('otra', 'Otra'))
SENTIDOS = (('ingreso', 'Ingreso'), ('egreso', 'Egreso'))
ESTADOS_PARTIDA = (('pendiente', 'Pendiente'), ('conciliada', 'Conciliada'), ('anulada', 'Anulada'))
DESTINOS = (('consulta', 'Consulta'), ('auxiliar_apertura', 'Auxiliar de la apertura'), ('reconstruccion', 'Reconstrucción'))
COINCIDENCIAS = (('', 'Sin coincidencia'), ('clave_acceso', 'Por clave de acceso'), ('revisada', 'Revisada'))
AMBITOS = (('contabilidad', 'Contabilidad'), ('documentos', 'Documentos'), ('cartera', 'Cartera'),
           ('inventario', 'Inventario'), ('bancos', 'Bancos'))
ESTADOS_COBERTURA = (('pendiente', 'Pendiente'), ('parcial', 'Parcial'), ('conciliada', 'Conciliada'))


# ---------------------------------------------------------------- apertura

class Apertura(TenantModel):
    """Apertura contable de la empresa: `borrador → en_revision → confirmada → sustituida | reversada`, `en_revision →
    borrador` y `borrador | en_revision → descartada`. Solo el borrador se edita. Como mucho una confirmada y una en
    preparación por empresa. La que empieza sin saldos lo declara (`sin_saldos`, fuente `inicio_actividades` con su
    detalle) y se confirma sin asiento. Totales nulos mientras no se confirma: el borrador calcula los suyos."""
    fecha_corte = models.DateField(verbose_name='Fecha de corte')
    moneda = models.CharField(max_length=3, default='USD', verbose_name='Moneda')
    fuente = models.CharField(max_length=24, choices=FUENTES, verbose_name='Fuente')
    fuente_detalle = models.CharField(max_length=300, blank=True, default='', verbose_name='Detalle de la fuente')
    sin_saldos = models.BooleanField(default=False, verbose_name='Empieza sin saldos (declaración expresa)')
    estado = models.CharField(max_length=12, choices=ESTADOS_APERTURA, default=BORRADOR, verbose_name='Estado')
    version = models.PositiveIntegerField(default=1, verbose_name='Versión')
    resultado_ejercicio = models.CharField(max_length=24, blank=True, default='', choices=RESULTADOS_EJERCICIO,
                                           verbose_name='Resultado del ejercicio')
    resultado_acumulado = models.DecimalField(**TOTAL, null=True, blank=True, verbose_name='Resultado acumulado declarado')
    inventario_modo = models.CharField(max_length=16, choices=MODOS_INVENTARIO, default='solo_conciliar',
                                       verbose_name='Inventario inicial')
    # [{ambito, nota}]: declaración expresa de que un ámbito no aplica; se congela al confirmar.
    ambitos_no_aplican = models.JSONField(default=list, blank=True, encoder=DjangoJSONEncoder, verbose_name='Ámbitos que no aplican')
    total_debe = models.DecimalField(**TOTAL, null=True, blank=True, verbose_name='Total debe confirmado')
    total_haber = models.DecimalField(**TOTAL, null=True, blank=True, verbose_name='Total haber confirmado')
    sustituye = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                  verbose_name='Sustituye a la apertura')
    asiento = models.ForeignKey('Asiento', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                verbose_name='Asiento de apertura')
    asiento_reverso = models.ForeignKey('Asiento', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                        verbose_name='Reverso del asiento de apertura')
    clave = models.CharField(max_length=40, verbose_name='Clave del envío')
    clave_confirmacion = models.CharField(max_length=40, null=True, blank=True, verbose_name='Clave de la confirmación')
    clave_reverso = models.CharField(max_length=40, null=True, blank=True, verbose_name='Clave del reverso')
    enviado_por_id, enviado_por_nombre = autor('Enviada a revisión por')
    enviado_en = models.DateTimeField(null=True, blank=True, verbose_name='Enviada a revisión el')
    revisado_por_id, revisado_por_nombre = autor('Revisada por')
    revisado_en = models.DateTimeField(null=True, blank=True, verbose_name='Revisada el')
    nota_revision = models.CharField(max_length=500, blank=True, default='', verbose_name='Nota de la revisión')
    confirmado_por_id, confirmado_por_nombre = autor('Confirmada por')
    confirmado_en = models.DateTimeField(null=True, blank=True, verbose_name='Confirmada el')
    cerrado_por_id, cerrado_por_nombre = autor('Cerrada por')   # sustituida, reversada o descartada
    cerrado_en = models.DateTimeField(null=True, blank=True, verbose_name='Cerrada el')
    motivo = models.CharField(max_length=300, blank=True, default='', verbose_name='Motivo')
    creado_por_id, creado_por_nombre = autor('Creada por')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Creada el')

    class Meta:
        verbose_name = 'Apertura contable'
        verbose_name_plural = 'Aperturas contables'
        ordering = ('-id',)
        default_permissions = ('add',)
        permissions = (('view_apertura', 'Puede ver la apertura contable'),
                       ('change_confirmacion_apertura', 'Puede confirmar, ajustar, sustituir o reversar la apertura'))
        constraints = [
            models.UniqueConstraint(fields=('company', 'clave'), name='apertura_clave_unica'),
            models.UniqueConstraint(fields=('company', 'clave_confirmacion'), condition=Q(clave_confirmacion__isnull=False),
                                    name='apertura_clave_confirmacion_unica'),
            models.UniqueConstraint(fields=('company',), condition=Q(estado=CONFIRMADA), name='apertura_una_confirmada'),
            models.UniqueConstraint(fields=('company',), condition=Q(estado__in=EN_PREPARACION), name='apertura_una_en_preparacion'),
            # Una sustituta viva por apertura: la descartada libera el lugar para volver a sustituir.
            models.UniqueConstraint(fields=('sustituye',), condition=Q(sustituye__isnull=False) & ~Q(estado=DESCARTADA),
                                    name='apertura_una_sustituta'),
            models.CheckConstraint(condition=Q(moneda='USD'), name='apertura_moneda_usd'),
            # Los IS NOT NULL de los totales no están en la especificación: sin ellos unos totales nulos pasarían el CHECK.
            models.CheckConstraint(condition=~Q(estado__in=CON_CONFIRMACION) | (Q(confirmado_en__isnull=False) & (
                Q(sin_saldos=True) | Q(asiento__isnull=False, total_debe__isnull=False, total_haber__isnull=False,
                                       total_debe=F('total_haber'), total_debe__gt=0))),
                name='apertura_confirmada_completa'),
            models.CheckConstraint(condition=Q(sin_saldos=False) | (Q(fuente='inicio_actividades') & ~Q(fuente_detalle='')),
                                   name='apertura_sin_saldos_declarada'),
            models.CheckConstraint(condition=~Q(estado__in=(SUSTITUIDA, REVERSADA)) | Q(sin_saldos=True)
                                   | Q(asiento_reverso__isnull=False), name='apertura_cerrada_con_reverso'),
            models.CheckConstraint(condition=~Q(estado__in=(SUSTITUIDA, REVERSADA, DESCARTADA)) | ~Q(motivo=''),
                                   name='apertura_cierre_con_motivo'),
        ]

    def __str__(self):
        return f'Apertura {self.pk} al {self.fecha_corte:%d/%m/%Y} ({self.get_estado_display()})'


class LineaApertura(TenantModel):
    """Una cuenta de la apertura con su saldo. Importes nulos = desconocido (nunca cero). `detalle` es la copia de
    `cuenta.auxiliar` al escribir la línea. Una línea quitada del borrador que tiene auxiliares anulados queda `retirada`
    (importes nulos): fuera de totales, validación y asiento, y volver a incluir su cuenta la reutiliza."""
    apertura = models.ForeignKey(Apertura, on_delete=models.PROTECT, related_name='lineas', verbose_name='Apertura')
    orden = models.PositiveIntegerField(verbose_name='Orden')
    cuenta = models.ForeignKey('Cuenta', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                               verbose_name='Cuenta')   # nula: sin mapear
    codigo_origen = models.CharField(max_length=60, blank=True, default='', verbose_name='Código en la fuente')
    rubro_origen = models.CharField(max_length=200, blank=True, default='', verbose_name='Rubro en la fuente')
    debe = models.DecimalField(**IMPORTE, null=True, blank=True, verbose_name='Debe')
    haber = models.DecimalField(**IMPORTE, null=True, blank=True, verbose_name='Haber')
    detalle = models.CharField(max_length=12, blank=True, default='', verbose_name='Detalle (auxiliar de la cuenta)')
    es_resultado_ejercicio = models.BooleanField(default=False, verbose_name='Es el resultado del ejercicio')
    incompleto_aceptado = models.BooleanField(default=False, verbose_name='Detalle incompleto aceptado')
    retirada = models.BooleanField(default=False, verbose_name='Retirada del borrador')
    lote = models.ForeignKey('ImportacionApertura', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                             verbose_name='Importación de la que sale')
    filas_origen = models.JSONField(default=list, blank=True, encoder=DjangoJSONEncoder, verbose_name='Filas de la fuente')
    nota = models.CharField(max_length=300, blank=True, default='', verbose_name='Nota')

    class Meta:
        verbose_name = 'Línea de la apertura'
        verbose_name_plural = 'Líneas de la apertura'
        ordering = ('apertura', 'orden')
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=('apertura', 'orden'), name='linea_apertura_orden_unico'),
            models.UniqueConstraint(fields=('apertura', 'cuenta'), condition=Q(cuenta__isnull=False),
                                    name='linea_apertura_cuenta_unica'),
            models.CheckConstraint(condition=Q(debe__isnull=True) | Q(debe__gte=0), name='linea_apertura_debe_no_negativo'),
            models.CheckConstraint(condition=Q(haber__isnull=True) | Q(haber__gte=0), name='linea_apertura_haber_no_negativo'),
            models.CheckConstraint(condition=~Q(debe__gt=0, haber__gt=0), name='linea_apertura_un_lado'),
            models.CheckConstraint(condition=Q(retirada=False) | Q(debe__isnull=True, haber__isnull=True),
                                   name='linea_apertura_retirada_sin_importes'),
        ]
        indexes = [models.Index(fields=('company', 'apertura'), name='linea_apertura_por_apertura')]

    def __str__(self):
        return f'Línea {self.orden} de la apertura {self.apertura_id}'


@cleanup.ignore   # el archivo se conserva siempre: django_cleanup no debe borrarlo del disco
class ImportacionApertura(TenantModel):
    """Lote importado (saldos o auxiliares de una línea): el archivo privado con su huella, lo leído de él, el mapeo y el
    resumen. Nada se escribe en las líneas hasta `mapear`. No se borra."""
    apertura = models.ForeignKey(Apertura, on_delete=models.PROTECT, related_name='+', verbose_name='Apertura')
    tipo = models.CharField(max_length=10, choices=TIPOS_IMPORTACION, verbose_name='Tipo')
    naturaleza = models.CharField(max_length=12, blank=True, default='', verbose_name='Naturaleza de los auxiliares')
    linea = models.ForeignKey(LineaApertura, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                              verbose_name='Línea de los auxiliares')
    archivo = models.FileField(upload_to=RutaPrivada(CARPETA), max_length=255, verbose_name='Archivo')
    nombre = models.CharField(max_length=255, verbose_name='Nombre original')
    tamano = models.PositiveIntegerField(verbose_name='Tamaño (bytes)')
    sha256 = models.CharField(max_length=64, verbose_name='SHA-256')
    encabezados = models.JSONField(default=list, blank=True, verbose_name='Encabezados')
    filas = models.JSONField(default=list, blank=True, encoder=DjangoJSONEncoder, verbose_name='Filas leídas')
    mapeo = models.JSONField(default=dict, blank=True, verbose_name='Columnas elegidas')
    resumen = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder, verbose_name='Resumen')
    estado = models.CharField(max_length=12, choices=ESTADOS_IMPORTACION, default='vista_previa', verbose_name='Estado')
    clave = models.CharField(max_length=40, verbose_name='Clave de la subida')
    creado_por_id, creado_por_nombre = autor('Subido por')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Subido el')
    aplicado_por_id, aplicado_por_nombre = autor('Aplicado por')
    aplicado_en = models.DateTimeField(null=True, blank=True, verbose_name='Aplicado el')

    class Meta:
        verbose_name = 'Importación de la apertura'
        verbose_name_plural = 'Importaciones de la apertura'
        ordering = ('-id',)
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=('company', 'clave'), name='importacion_apertura_clave_unica')]

    def __str__(self):
        return f'{self.nombre} ({self.get_estado_display()})'


@cleanup.ignore
class RespaldoApertura(TenantModel):
    """Archivo de respaldo de la apertura (PDF, imagen, XLSX o CSV validados por contenido). Un PDF respalda; nunca
    alimenta líneas. Se anula (marca con motivo); el archivo se conserva."""
    apertura = models.ForeignKey(Apertura, on_delete=models.PROTECT, related_name='+', verbose_name='Apertura')
    archivo = models.FileField(upload_to=RutaPrivada(CARPETA), max_length=255, verbose_name='Archivo')
    nombre = models.CharField(max_length=255, verbose_name='Nombre original')
    tipo_mime = models.CharField(max_length=100, verbose_name='Tipo')
    tamano = models.PositiveIntegerField(verbose_name='Tamaño (bytes)')
    sha256 = models.CharField(max_length=64, verbose_name='SHA-256')
    descripcion = models.CharField(max_length=200, blank=True, default='', verbose_name='Descripción')
    clave = models.CharField(max_length=40, verbose_name='Clave de la subida')
    subido_por_id, subido_por_nombre = autor('Subido por')
    subido_en = models.DateTimeField(default=timezone.now, verbose_name='Subido el')
    anulado_por_id, anulado_por_nombre = autor('Anulado por')
    anulado_en = models.DateTimeField(null=True, blank=True, verbose_name='Anulado el')
    motivo_anulacion = models.CharField(max_length=300, blank=True, default='', verbose_name='Motivo de la anulación')

    class Meta:
        verbose_name = 'Respaldo de la apertura'
        verbose_name_plural = 'Respaldos de la apertura'
        ordering = ('-id',)
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=('company', 'clave'), name='respaldo_apertura_clave_unica')]

    def __str__(self):
        return self.nombre


class AjusteApertura(TenantModel):
    """Corrección de una apertura confirmada sin tocar su asiento ni los períodos cerrados: un asiento de tipo `ajuste` en
    un período abierto y los auxiliares que cambian (`resumen`). Se numeran 1, 2, 3… por apertura; solo el último vigente
    se reversa."""
    apertura = models.ForeignKey(Apertura, on_delete=models.PROTECT, related_name='ajustes', verbose_name='Apertura')
    numero = models.PositiveIntegerField(verbose_name='Número')
    fecha = models.DateField(verbose_name='Fecha del asiento de ajuste')
    motivo = models.CharField(max_length=300, verbose_name='Motivo')
    asiento = models.ForeignKey('Asiento', on_delete=models.PROTECT, related_name='+', verbose_name='Asiento de ajuste')
    asiento_reverso = models.ForeignKey('Asiento', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                        verbose_name='Reverso del asiento de ajuste')
    estado = models.CharField(max_length=10, choices=ESTADOS_AJUSTE, default=VIGENTE, verbose_name='Estado')
    resumen = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder, verbose_name='Resumen')
    clave = models.CharField(max_length=40, verbose_name='Clave del envío')
    clave_reverso = models.CharField(max_length=40, null=True, blank=True, verbose_name='Clave del reverso')
    creado_por_id, creado_por_nombre = autor('Ajustado por')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Ajustado el')
    reversado_por_id, reversado_por_nombre = autor('Reversado por')
    reversado_en = models.DateTimeField(null=True, blank=True, verbose_name='Reversado el')
    motivo_reverso = models.CharField(max_length=300, blank=True, default='', verbose_name='Motivo del reverso')

    class Meta:
        verbose_name = 'Ajuste de la apertura'
        verbose_name_plural = 'Ajustes de la apertura'
        ordering = ('apertura', 'numero')
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=('apertura', 'numero'), name='ajuste_apertura_numero_unico'),
            models.UniqueConstraint(fields=('company', 'clave'), name='ajuste_apertura_clave_unica'),
            models.CheckConstraint(condition=~Q(motivo=''), name='ajuste_apertura_con_motivo'),
            models.CheckConstraint(condition=Q(estado='reversado', asiento_reverso__isnull=False)
                                   | (~Q(estado='reversado') & Q(asiento_reverso__isnull=True)),
                                   name='ajuste_apertura_reverso_coherente'),
        ]
        indexes = [models.Index(fields=('company', 'apertura', 'estado'), name='ajuste_apertura_estado')]

    def __str__(self):
        return f'Ajuste {self.numero} de la apertura {self.apertura_id}'


class AuxiliarApertura(TenantModel):
    """Detalle que explica el saldo de una línea (una tabla con discriminador `naturaleza`): un documento de cartera, un
    producto del inventario, una cuenta bancaria, un activo o un saldo tributario. Explica, no contabiliza.

    Nunca cambian sus importes, su tercero ni su naturaleza: un cambio de importe es un sucesor (`antecesor`, misma `raiz`)
    y el anterior queda anulado. Todo enlace externo a un auxiliar va por la raíz de su linaje (`raiz` nula = es raíz). Lo
    único que cambia en un auxiliar confirmado es un campo de identificación vacío que se completa y su vínculo con la
    cuenta operativa (`cxc_id`, `cxp_id`), cada cambio con su `EventoApertura`."""
    apertura = models.ForeignKey(Apertura, on_delete=models.PROTECT, related_name='auxiliares', verbose_name='Apertura')
    linea = models.ForeignKey(LineaApertura, on_delete=models.PROTECT, related_name='auxiliares', verbose_name='Línea')
    cuenta = models.ForeignKey('Cuenta', on_delete=models.PROTECT, related_name='+', verbose_name='Cuenta (copia de la línea)')
    naturaleza = models.CharField(max_length=12, choices=NATURALEZAS, verbose_name='Naturaleza')
    saldo_inicial = models.DecimalField(**IMPORTE, verbose_name='Saldo inicial')
    estado = models.CharField(max_length=8, choices=ESTADOS_VIGENCIA, default=VIGENTE, verbose_name='Estado')
    nota = models.CharField(max_length=300, blank=True, default='', verbose_name='Nota')
    ajuste = models.ForeignKey(AjusteApertura, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                               verbose_name='Creado por el ajuste')
    anulado_por_ajuste = models.ForeignKey(AjusteApertura, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                           verbose_name='Anulado por el ajuste')
    creado_por_id, creado_por_nombre = autor('Creado por')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Creado el')
    anulado_por_id, anulado_por_nombre = autor('Anulado por')
    anulado_en = models.DateTimeField(null=True, blank=True, verbose_name='Anulado el')
    motivo_anulacion = models.CharField(max_length=300, blank=True, default='', verbose_name='Motivo de la anulación')
    # Linaje
    antecesor = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                  verbose_name='Antecesor')
    raiz = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                             verbose_name='Raíz del linaje')
    # Tercero (copia propia; los id se anotan solo si ya existen por identificación)
    tercero_tipo_identificacion = models.CharField(max_length=2, blank=True, default='', verbose_name='Tipo de identificación')
    tercero_identificacion = models.CharField(max_length=20, blank=True, default='', verbose_name='Identificación')
    tercero_nombre = models.CharField(max_length=300, blank=True, default='', verbose_name='Nombre del tercero')
    cliente_id = models.BigIntegerField(null=True, blank=True, verbose_name='Id del cliente')
    proveedor_id = models.BigIntegerField(null=True, blank=True, verbose_name='Id del proveedor')
    # Documento
    documento_tipo = models.CharField(max_length=2, blank=True, default='', verbose_name='Tipo de documento')
    documento_numero = models.CharField(max_length=40, blank=True, default='', verbose_name='Número de documento')
    documento_fecha = models.DateField(null=True, blank=True, verbose_name='Fecha del documento')
    vencimiento = models.DateField(null=True, blank=True, verbose_name='Vencimiento')
    clave_acceso = models.CharField(max_length=49, blank=True, default='', verbose_name='Clave de acceso')
    documento_total = models.DecimalField(**IMPORTE, null=True, blank=True, verbose_name='Total del documento')
    distinto_de_operativo = models.BooleanField(default=False, verbose_name='Declarado distinto del documento de la aplicación')
    # Vínculos con la operación (enteros sin restricción) y su copia al vincular
    cxc_id = models.BigIntegerField(null=True, blank=True, verbose_name='Id de la cuenta por cobrar')
    cxp_id = models.BigIntegerField(null=True, blank=True, verbose_name='Id de la cuenta por pagar')
    documento_importado_id = models.BigIntegerField(null=True, blank=True, verbose_name='Id del documento importado')
    vinculo_numero = models.CharField(max_length=60, blank=True, default='', verbose_name='Número de lo vinculado')
    vinculo_saldo_corte = models.DecimalField(**IMPORTE, null=True, blank=True, verbose_name='Saldo operativo al corte al vincular')
    # Inventario
    producto_id = models.BigIntegerField(null=True, blank=True, verbose_name='Id del producto')
    producto_codigo = models.CharField(max_length=20, blank=True, default='', verbose_name='Código del producto')
    producto_nombre = models.CharField(max_length=150, blank=True, default='', verbose_name='Nombre del producto')
    almacen = models.CharField(max_length=60, default='principal', verbose_name='Almacén (etiqueta)')
    cantidad = models.PositiveIntegerField(null=True, blank=True, verbose_name='Cantidad')
    costo_unitario = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True, verbose_name='Costo unitario')
    movimiento_kardex = models.ForeignKey('MovimientoManual', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                          verbose_name='Saldo inicial del kardex')
    # Banco
    banco_nombre = models.CharField(max_length=80, blank=True, default='', verbose_name='Banco')
    banco_numero = models.CharField(max_length=30, blank=True, default='', verbose_name='Número de cuenta bancaria')
    saldo_extracto = models.DecimalField(**IMPORTE, null=True, blank=True, verbose_name='Saldo según el extracto')
    fecha_extracto = models.DateField(null=True, blank=True, verbose_name='Fecha del extracto')
    # Activo
    descripcion = models.CharField(max_length=200, blank=True, default='', verbose_name='Descripción')
    fecha_adquisicion = models.DateField(null=True, blank=True, verbose_name='Fecha de adquisición')
    costo = models.DecimalField(**IMPORTE, null=True, blank=True, verbose_name='Costo')
    depreciacion_acumulada = models.DecimalField(**IMPORTE, null=True, blank=True, verbose_name='Depreciación acumulada')
    vida_util_meses = models.PositiveIntegerField(null=True, blank=True, verbose_name='Vida útil (meses)')
    # Tributario
    # 40 y no 30 como dice la especificación: `retenciones_renta_por_compensar`, uno de sus valores, tiene 31 caracteres.
    concepto = models.CharField(max_length=40, blank=True, default='', choices=CONCEPTOS_TRIBUTARIOS, verbose_name='Concepto')
    periodo = models.DateField(null=True, blank=True, verbose_name='Período de origen (primer día del mes)')
    formulario = models.CharField(max_length=4, blank=True, default='', verbose_name='Formulario')
    casillero = models.CharField(max_length=6, blank=True, default='', verbose_name='Casillero')
    fuente_texto = models.CharField(max_length=200, blank=True, default='', verbose_name='Fuente')

    class Meta:
        verbose_name = 'Auxiliar de la apertura'
        verbose_name_plural = 'Auxiliares de la apertura'
        ordering = ('apertura', 'linea', 'id')
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=Q(saldo_inicial__gt=0), name='auxiliar_apertura_saldo_positivo'),
            models.CheckConstraint(condition=Q(estado=ANULADO, anulado_en__isnull=False)
                                   | (~Q(estado=ANULADO) & Q(anulado_en__isnull=True)), name='auxiliar_apertura_anulado_con_fecha'),
            models.CheckConstraint(condition=~Q(estado=ANULADO) | ~Q(motivo_anulacion=''), name='auxiliar_apertura_anulado_con_motivo'),
            models.CheckConstraint(condition=~Q(naturaleza__in=DE_TERCERO) | ~Q(tercero_nombre=''),
                                   name='auxiliar_apertura_tercero_con_nombre'),
            # Los IS NOT NULL no están en la especificación: sin ellos una cantidad o un costo nulos pasarían el CHECK.
            models.CheckConstraint(condition=~Q(naturaleza='inventario') | Q(
                producto_id__isnull=False, cantidad__isnull=False, cantidad__gt=0, costo_unitario__isnull=False,
                costo_unitario__gte=0), name='auxiliar_apertura_inventario_completo'),
            models.CheckConstraint(condition=~Q(naturaleza='tributario') | (~Q(concepto='') & Q(periodo__isnull=False)),
                                   name='auxiliar_apertura_tributario_completo'),
            models.CheckConstraint(condition=Q(cxc_id__isnull=True) | Q(naturaleza='cliente'), name='auxiliar_apertura_cxc_de_cliente'),
            models.CheckConstraint(condition=Q(cxp_id__isnull=True) | Q(naturaleza='proveedor'),
                                   name='auxiliar_apertura_cxp_de_proveedor'),
            # Unicidad entre los vigentes: los anulados (y los de borradores descartados) no cuentan.
            models.UniqueConstraint(fields=('apertura', 'naturaleza', 'tercero_identificacion', 'documento_tipo', 'documento_numero'),
                                    condition=ES_VIGENTE & Q(naturaleza__in=DE_TERCERO) & ~Q(documento_numero=''),
                                    name='auxiliar_apertura_documento_unico'),
            models.UniqueConstraint(fields=('apertura', 'clave_acceso'), condition=ES_VIGENTE & ~Q(clave_acceso=''),
                                    name='auxiliar_apertura_clave_acceso_unica'),
            models.UniqueConstraint(fields=('apertura', 'producto_id', 'almacen'), condition=ES_VIGENTE,
                                    name='auxiliar_apertura_producto_unico'),
            models.UniqueConstraint(fields=('apertura', 'linea', 'banco_nombre', 'banco_numero'), condition=ES_VIGENTE & Q(naturaleza='banco'),
                                    name='auxiliar_apertura_banco_unico'),
            models.UniqueConstraint(fields=('apertura', 'concepto', 'periodo', 'casillero'), condition=ES_VIGENTE & Q(naturaleza='tributario'),
                                    name='auxiliar_apertura_tributario_unico'),
            models.UniqueConstraint(fields=('apertura', 'cxc_id'), condition=ES_VIGENTE & Q(cxc_id__isnull=False),
                                    name='auxiliar_apertura_cxc_unico'),
            models.UniqueConstraint(fields=('apertura', 'cxp_id'), condition=ES_VIGENTE & Q(cxp_id__isnull=False),
                                    name='auxiliar_apertura_cxp_unico'),
            models.UniqueConstraint(fields=('apertura', 'documento_importado_id'), condition=ES_VIGENTE & Q(documento_importado_id__isnull=False),
                                    name='auxiliar_apertura_importado_unico'),
            # Un sucesor vivo por fila.
            models.UniqueConstraint(fields=('antecesor',), condition=Q(antecesor__isnull=False) & ES_VIGENTE,
                                    name='auxiliar_apertura_un_sucesor'),
        ]
        indexes = [
            models.Index(fields=('company', 'apertura', 'naturaleza', 'estado'), name='aux_apertura_naturaleza'),
            models.Index(fields=('company', 'linea', 'estado'), name='aux_apertura_linea'),
            models.Index(fields=('company', 'raiz'), name='aux_apertura_raiz'),
            models.Index(fields=('company', 'tercero_identificacion'), name='aux_apertura_tercero'),
            models.Index(fields=('company', 'cxc_id'), condition=Q(cxc_id__isnull=False), name='aux_apertura_cxc'),
            models.Index(fields=('company', 'cxp_id'), condition=Q(cxp_id__isnull=False), name='aux_apertura_cxp'),
            models.Index(fields=('company', 'producto_id'), condition=Q(producto_id__isnull=False), name='aux_apertura_producto'),
            models.Index(fields=('company', 'documento_importado_id'), condition=Q(documento_importado_id__isnull=False),
                         name='aux_apertura_importado'),
        ]

    def __str__(self):
        return f'Auxiliar {self.pk} ({self.get_naturaleza_display()}) de la línea {self.linea_id}'


class PartidaBancoApertura(TenantModel):
    """Partida que explica la diferencia entre el saldo en libros de un banco al corte y su extracto (depósitos en
    tránsito, cheques pendientes). No suma al saldo en libros; el bloque 4 la empareja."""
    auxiliar = models.ForeignKey(AuxiliarApertura, on_delete=models.PROTECT, related_name='partidas',
                                 verbose_name='Auxiliar de banco')
    tipo = models.CharField(max_length=20, choices=TIPOS_PARTIDA, verbose_name='Tipo')
    sentido = models.CharField(max_length=8, choices=SENTIDOS, verbose_name='Sentido')
    fecha = models.DateField(null=True, blank=True, verbose_name='Fecha')
    referencia = models.CharField(max_length=100, blank=True, default='', verbose_name='Referencia')
    descripcion = models.CharField(max_length=200, blank=True, default='', verbose_name='Descripción')
    importe = models.DecimalField(**IMPORTE, verbose_name='Importe')
    estado = models.CharField(max_length=10, choices=ESTADOS_PARTIDA, default='pendiente', verbose_name='Estado')
    creado_por_id, creado_por_nombre = autor('Registrada por')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Registrada el')
    anulado_por_id, anulado_por_nombre = autor('Anulada por')
    anulado_en = models.DateTimeField(null=True, blank=True, verbose_name='Anulada el')
    motivo_anulacion = models.CharField(max_length=300, blank=True, default='', verbose_name='Motivo de la anulación')

    class Meta:
        verbose_name = 'Partida de banco de la apertura'
        verbose_name_plural = 'Partidas de banco de la apertura'
        ordering = ('auxiliar', 'id')
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=Q(importe__gt=0), name='partida_banco_apertura_importe_positivo')]
        indexes = [models.Index(fields=('company', 'auxiliar', 'estado'), name='partida_banco_ap_estado')]

    def __str__(self):
        return f'{self.get_tipo_display()} {self.importe} del auxiliar {self.auxiliar_id}'


@cleanup.ignore
class AplicacionAuxiliar(TenantModel):
    """Cobro, pago u otro descargo registrado sobre un saldo inicial propio. `raiz` es la raíz del linaje del auxiliar y no
    cambia: el saldo de un documento es su saldo inicial menos lo aplicado a todo su linaje. Su asiento va por su
    expediente (`Contabilizacion`, origen `aplicacion_auxiliar`). `tipo` y `subtipo` son vocabularios que crecen (decisión
    común 14): sin `choices` ni CHECK cerrado, los valida el servicio."""
    auxiliar = models.ForeignKey(AuxiliarApertura, on_delete=models.PROTECT, related_name='aplicaciones',
                                 verbose_name='Auxiliar sobre el que se registró')
    raiz = models.ForeignKey(AuxiliarApertura, on_delete=models.PROTECT, related_name='+', verbose_name='Raíz del linaje')
    tipo = models.CharField(max_length=20, verbose_name='Tipo')                      # cobro | pago | otro_descargo
    subtipo = models.CharField(max_length=20, blank=True, default='', verbose_name='Subtipo')
    fecha = models.DateField(verbose_name='Fecha')
    importe = models.DecimalField(**IMPORTE, verbose_name='Importe')
    medio = models.CharField(max_length=15, blank=True, default='', verbose_name='Medio de pago')   # MEDIOS_DE_PAGO de pos
    referencia = models.CharField(max_length=100, blank=True, default='', verbose_name='Referencia')
    nota = models.TextField(blank=True, default='', verbose_name='Nota')
    archivo = models.FileField(upload_to=RutaPrivada(CARPETA), max_length=255, blank=True, default='', verbose_name='Respaldo')
    archivo_nombre = models.CharField(max_length=255, blank=True, default='', verbose_name='Nombre original del respaldo')
    archivo_tipo = models.CharField(max_length=100, blank=True, default='', verbose_name='Tipo del respaldo')
    archivo_bytes = models.PositiveIntegerField(null=True, blank=True, verbose_name='Tamaño del respaldo (bytes)')
    archivo_sha256 = models.CharField(max_length=64, blank=True, default='', verbose_name='SHA-256 del respaldo')
    # Tesorería en cobros y pagos; la que elija el contador en un descargo. Sin ella el expediente queda con excepción.
    cuenta_contrapartida = models.ForeignKey('Cuenta', null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                             verbose_name='Cuenta de contrapartida')
    clave = models.CharField(max_length=40, verbose_name='Clave del envío')
    estado = models.CharField(max_length=8, choices=ESTADOS_VIGENCIA, default=VIGENTE, verbose_name='Estado')
    registrado_por_id, registrado_por_nombre = autor('Registrado por')
    registrado_en = models.DateTimeField(default=timezone.now, verbose_name='Registrado el')
    anulado_por_id, anulado_por_nombre = autor('Anulado por')
    anulado_en = models.DateTimeField(null=True, blank=True, verbose_name='Anulado el')
    motivo_anulacion = models.CharField(max_length=300, blank=True, default='', verbose_name='Motivo de la anulación')

    class Meta:
        verbose_name = 'Aplicación sobre un saldo inicial'
        verbose_name_plural = 'Aplicaciones sobre saldos iniciales'
        ordering = ('fecha', 'id')
        default_permissions = ('add', 'change')
        constraints = [
            models.UniqueConstraint(fields=('company', 'clave'), name='aplicacion_auxiliar_clave_unica'),
            models.CheckConstraint(condition=Q(importe__gt=0), name='aplicacion_auxiliar_importe_positivo'),
            # Un descargo no es tesorería: sin medio de pago, con subtipo y con motivo.
            models.CheckConstraint(condition=~Q(tipo='otro_descargo') | (Q(medio='') & ~Q(subtipo='') & ~Q(nota='')),
                                   name='aplicacion_auxiliar_descargo_completo'),
            models.CheckConstraint(condition=Q(estado=ANULADO, anulado_en__isnull=False)
                                   | (~Q(estado=ANULADO) & Q(anulado_en__isnull=True)), name='aplicacion_auxiliar_anulada_con_fecha'),
            models.CheckConstraint(condition=~Q(estado=ANULADO) | ~Q(motivo_anulacion=''), name='aplicacion_auxiliar_anulada_con_motivo'),
        ]
        indexes = [
            models.Index(fields=('company', 'raiz', 'estado'), name='aplicacion_aux_raiz'),
            models.Index(fields=('company', 'fecha'), name='aplicacion_aux_fecha'),
        ]

    def __str__(self):
        return f'{self.tipo} {self.importe} sobre el auxiliar {self.auxiliar_id}'


class VinculoHistorico(TenantModel):
    """Destino que se dio a un documento importado anterior al corte: consulta, completar un auxiliar o reconstrucción.
    Vive en contabilidad: la tabla de la importación no cambia ni recibe restricciones (el documento es un entero con la
    copia de su clave, tipo, número y fecha)."""
    documento_importado_id = models.BigIntegerField(verbose_name='Id del documento importado')
    clave_acceso = models.CharField(max_length=49, blank=True, default='', verbose_name='Clave de acceso')
    documento_tipo = models.CharField(max_length=2, blank=True, default='', verbose_name='Tipo de documento')
    documento_numero = models.CharField(max_length=40, blank=True, default='', verbose_name='Número de documento')
    fecha_emision = models.DateField(null=True, blank=True, verbose_name='Fecha de emisión')
    destino = models.CharField(max_length=20, choices=DESTINOS, verbose_name='Destino')
    auxiliar = models.ForeignKey(AuxiliarApertura, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                 verbose_name='Auxiliar')
    apertura = models.ForeignKey(Apertura, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                 verbose_name='Apertura')
    coincidencia = models.CharField(max_length=14, blank=True, default='', choices=COINCIDENCIAS, verbose_name='Coincidencia')
    estado = models.CharField(max_length=8, choices=ESTADOS_VIGENCIA, default=VIGENTE, verbose_name='Estado')
    nota = models.CharField(max_length=300, blank=True, default='', verbose_name='Nota')
    clave = models.CharField(max_length=40, verbose_name='Clave del envío')
    decidido_por_id, decidido_por_nombre = autor('Decidido por')
    decidido_en = models.DateTimeField(default=timezone.now, verbose_name='Decidido el')
    anulado_por_id, anulado_por_nombre = autor('Anulado por')
    anulado_en = models.DateTimeField(null=True, blank=True, verbose_name='Anulado el')
    motivo_anulacion = models.CharField(max_length=300, blank=True, default='', verbose_name='Motivo de la anulación')

    class Meta:
        verbose_name = 'Destino de un documento histórico'
        verbose_name_plural = 'Destinos de documentos históricos'
        ordering = ('-id',)
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=('company', 'documento_importado_id'), condition=Q(estado=VIGENTE),
                                    name='vinculo_historico_documento_unico'),
            models.UniqueConstraint(fields=('auxiliar',), condition=Q(estado=VIGENTE, auxiliar__isnull=False),
                                    name='vinculo_historico_auxiliar_unico'),
            models.UniqueConstraint(fields=('company', 'clave'), name='vinculo_historico_clave_unica'),
            models.CheckConstraint(condition=Q(destino='auxiliar_apertura', auxiliar__isnull=False)
                                   | (~Q(destino='auxiliar_apertura') & Q(auxiliar__isnull=True)),
                                   name='vinculo_historico_destino_auxiliar'),
        ]

    def __str__(self):
        return f'Documento importado {self.documento_importado_id} → {self.get_destino_display()}'


class CoberturaPeriodo(TenantModel):
    """Lo declarado sobre un mes y un ámbito (un mes sin fila es `sin_cobertura`). `documentos` es la cobertura de los
    comprobantes del mes (libros, ATS, 104 y 103), no el ámbito tributario de la apertura. `fuente_tipo` es un
    vocabulario que crece (decisión común 14): sin `choices`, lo valida el servicio."""
    ambito = models.CharField(max_length=14, choices=AMBITOS, verbose_name='Ámbito')
    anio = models.PositiveSmallIntegerField(verbose_name='Año')
    mes = models.PositiveSmallIntegerField(verbose_name='Mes')
    estado = models.CharField(max_length=10, choices=ESTADOS_COBERTURA, verbose_name='Estado')
    fuente_tipo = models.CharField(max_length=24, verbose_name='Tipo de fuente')
    fuente = models.CharField(max_length=200, blank=True, default='', verbose_name='Fuente')
    causas = models.JSONField(default=list, blank=True, encoder=DjangoJSONEncoder, verbose_name='Causas')
    version = models.PositiveIntegerField(default=1, verbose_name='Versión')
    declarado_por_id, declarado_por_nombre = autor('Declarado por')
    declarado_en = models.DateTimeField(default=timezone.now, verbose_name='Declarado el')

    class Meta:
        verbose_name = 'Cobertura declarada de un mes'
        verbose_name_plural = 'Coberturas declaradas por mes'
        ordering = ('anio', 'mes', 'ambito')
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=('company', 'ambito', 'anio', 'mes'), name='cobertura_periodo_unica')]

    def __str__(self):
        return f'{self.get_ambito_display()} {self.anio}-{self.mes:02d}: {self.get_estado_display()}'


class EventoApertura(SoloInsercion):
    """Historia de la apertura y de su inicio (`apertura` nula), de solo inserción (como RespaldoCobroCambio). En los
    cambios de un auxiliar confirmado, `detalle` = `{auxiliar_id, campo, anterior, nuevo}`."""
    apertura = models.ForeignKey(Apertura, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
                                 verbose_name='Apertura')
    accion = models.CharField(max_length=30, verbose_name='Acción')
    de_estado = models.CharField(max_length=20, blank=True, default='', verbose_name='Estado anterior')
    a_estado = models.CharField(max_length=20, blank=True, default='', verbose_name='Estado nuevo')
    detalle = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder, verbose_name='Detalle')
    usuario_id = models.BigIntegerField(null=True, blank=True, verbose_name='Id del usuario')
    usuario_nombre = models.CharField(max_length=150, blank=True, default='', verbose_name='Usuario')
    creado_en = models.DateTimeField(default=timezone.now, verbose_name='Fecha')

    class Meta:
        verbose_name = 'Evento de la apertura'
        verbose_name_plural = 'Eventos de la apertura'
        ordering = ('id',)
        default_permissions = ()
        indexes = [models.Index(fields=('company', 'apertura', 'id'), name='evento_apertura_historia')]

    def __str__(self):
        return f'{self.accion} · apertura {self.apertura_id}'
