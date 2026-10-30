"""Importación de comprobantes electrónicos recibidos o emitidos fuera del sistema (XML del SRI o RIDE en PDF).

Etapas separadas: importación (lote, archivo, entrada) → validación y verificación (documento y su verificación en el SRI)
→ clasificación (emitido / recibido / ajeno / revisión manual) → revisión → vinculación con compras o ventas existentes →
propuesta contable (el sistema todavía no tiene libro mayor: nada se presenta como contabilizado).
Todo pertenece a una empresa (TenantModel + seguridad por filas). Los archivos van a una carpeta privada.
"""
import os
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.deconstruct import deconstructible

from core.tenancy.models_base import TenantModel

IMPORTE = dict(max_digits=16, decimal_places=2, default=0)
CARPETA_PRIVADA = 'privado'


@deconstructible
class RutaPrivada:
    """privado/empresas/<uuid de la empresa>/<carpeta>/<año>/<mes>/<aleatorio>.<ext>

    La descarga general de archivos (core.security.views.files) no entrega nada bajo «privado/»: estos archivos solo salen
    por la vista de la importación, que exige el permiso del módulo.
    """

    def __init__(self, carpeta):
        self.carpeta = carpeta

    def __call__(self, instance, filename):
        extension = os.path.splitext(filename)[1].lower()[:10]
        return (f'{CARPETA_PRIVADA}/empresas/{instance.company.uuid}/{self.carpeta}/{timezone.now():%Y/%m}/'
                f'{uuid.uuid4().hex}{extension}')

    def __eq__(self, other):
        return isinstance(other, RutaPrivada) and other.carpeta == self.carpeta


class LoteImportacion(TenantModel):
    ESTADOS = (('procesando', 'Procesando'), ('terminado', 'Terminado'), ('con_errores', 'Terminado con errores'))

    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+', verbose_name='Importado por')
    estado = models.CharField(max_length=20, choices=ESTADOS, default='procesando', verbose_name='Estado')
    total_archivos = models.PositiveIntegerField(default=0, verbose_name='Archivos')
    creado = models.DateTimeField(default=timezone.now, verbose_name='Creado')
    terminado = models.DateTimeField(null=True, blank=True, verbose_name='Terminado')

    class Meta:
        verbose_name = 'Lote de importación'
        verbose_name_plural = 'Lotes de importación'
        ordering = ('-id',)
        default_permissions = ()


class ArchivoImportado(TenantModel):
    """Un archivo subido, guardado una sola vez por empresa (mismo SHA-256 = mismo archivo)."""
    TIPOS = (('xml', 'XML'), ('pdf', 'PDF'))
    ORIGENES = (('subido', 'Subido por el usuario'), ('sri', 'Recuperado del SRI'))

    sha256 = models.CharField(max_length=64, verbose_name='SHA-256')
    tipo = models.CharField(max_length=4, choices=TIPOS, verbose_name='Tipo')
    origen = models.CharField(max_length=10, choices=ORIGENES, default='subido', verbose_name='Origen')
    tamano = models.PositiveIntegerField(verbose_name='Tamaño (bytes)')
    nombre_original = models.CharField(max_length=255, blank=True, verbose_name='Nombre original')
    archivo = models.FileField(upload_to=RutaPrivada('importados'), max_length=255, verbose_name='Archivo')
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+', verbose_name='Subido por')
    creado = models.DateTimeField(default=timezone.now, verbose_name='Creado')

    class Meta:
        verbose_name = 'Archivo importado'
        verbose_name_plural = 'Archivos importados'
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['company', 'sha256'], name='archivo_importado_unico_por_empresa')]


class DocumentoImportado(TenantModel):
    """Comprobante identificado por su clave de acceso: uno por empresa, ambiente y clave (idempotencia)."""
    ORIGENES = (('xml', 'Archivo XML'), ('pdf', 'RIDE en PDF'), ('sri', 'Consulta al SRI'), ('manual', 'Clave escrita a mano'))
    PROCESAMIENTO = (('pendiente_xml', 'Pendiente del XML autorizado'), ('procesado', 'Procesado'))
    VERIFICACION = (('sin_autorizacion', 'El archivo no trae autorización'),
                    ('declarada_en_archivo', 'Autorización declarada en el archivo (sin verificar)'),
                    ('verificada_sri', 'Verificada en el SRI'),
                    ('discrepancia_sri', 'Difiere de lo autorizado en el SRI'),
                    ('no_autorizada_sri', 'El SRI no la autoriza'),
                    ('no_encontrada_sri', 'El SRI no tiene esa clave'),
                    ('sri_no_disponible', 'El SRI no respondió'))
    CLASIFICACION = (('pendiente', 'Sin clasificar'), ('emitido', 'Emitido por la empresa (venta)'),
                     ('recibido', 'Recibido por la empresa (compra o gasto)'), ('ajeno', 'Documento ajeno a la empresa'),
                     ('revision_manual', 'Requiere revisión manual'))
    REVISION = (('pendiente', 'Pendiente de revisión'), ('aprobado', 'Aprobado'), ('vinculado', 'Vinculado a un registro'),
                ('descartado', 'Descartado'))
    CONTABLE = (('sin_propuesta', 'Sin propuesta'), ('propuesta', 'Propuesta contable (no contabilizada)'))

    lote = models.ForeignKey(LoteImportacion, null=True, blank=True, on_delete=models.SET_NULL, related_name='documentos')
    importado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+', verbose_name='Importado por')
    origen = models.CharField(max_length=10, choices=ORIGENES, verbose_name='Origen')
    archivo_xml = models.ForeignKey(ArchivoImportado, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    archivo_pdf = models.ForeignKey(ArchivoImportado, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    # Identificación del comprobante
    clave_acceso = models.CharField(max_length=49, verbose_name='Clave de acceso')
    cod_doc = models.CharField(max_length=2, verbose_name='Tipo de comprobante')
    version = models.CharField(max_length=10, blank=True, verbose_name='Versión')
    ambiente = models.PositiveSmallIntegerField(verbose_name='Ambiente')
    estab = models.CharField(max_length=3, verbose_name='Establecimiento')
    pto_emi = models.CharField(max_length=3, verbose_name='Punto de emisión')
    secuencial = models.CharField(max_length=9, verbose_name='Secuencial')
    numero = models.CharField(max_length=17, verbose_name='Número')
    fecha_emision = models.DateField(null=True, blank=True, verbose_name='Fecha de emisión')
    numero_autorizacion = models.CharField(max_length=49, blank=True, verbose_name='Número de autorización')
    fecha_autorizacion = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de autorización')
    # Emisor y receptor (tal como vienen: no se recortan identificaciones)
    emisor_ruc = models.CharField(max_length=13, verbose_name='RUC del emisor')
    emisor_razon_social = models.CharField(max_length=300, blank=True, verbose_name='Emisor')
    emisor_nombre_comercial = models.CharField(max_length=300, blank=True, verbose_name='Nombre comercial del emisor')
    receptor_tipo_identificacion = models.CharField(max_length=2, blank=True, verbose_name='Tipo de identificación del receptor')
    receptor_identificacion = models.CharField(max_length=20, blank=True, verbose_name='Identificación del receptor')
    receptor_razon_social = models.CharField(max_length=300, blank=True, verbose_name='Receptor')
    moneda = models.CharField(max_length=15, blank=True, verbose_name='Moneda')
    # Importes
    total_sin_impuestos = models.DecimalField(verbose_name='Total sin impuestos', **IMPORTE)
    total_descuento = models.DecimalField(verbose_name='Total descuento', **IMPORTE)
    propina = models.DecimalField(verbose_name='Propina', **IMPORTE)
    total_iva = models.DecimalField(verbose_name='IVA', **IMPORTE)
    total_ice = models.DecimalField(verbose_name='ICE', **IMPORTE)
    total_irbpnr = models.DecimalField(verbose_name='IRBPNR', **IMPORTE)
    importe_total = models.DecimalField(verbose_name='Importe total', **IMPORTE)
    # Estados (uno por etapa)
    estado_procesamiento = models.CharField(max_length=20, choices=PROCESAMIENTO, default='procesado', verbose_name='Procesamiento')
    estado_verificacion = models.CharField(max_length=25, choices=VERIFICACION, default='sin_autorizacion', verbose_name='Verificación')
    verificado_en = models.DateTimeField(null=True, blank=True, verbose_name='Verificado en el SRI el')
    clasificacion = models.CharField(max_length=20, choices=CLASIFICACION, default='pendiente', verbose_name='Clasificación')
    estado_revision = models.CharField(max_length=15, choices=REVISION, default='pendiente', verbose_name='Revisión')
    estado_contable = models.CharField(max_length=15, choices=CONTABLE, default='sin_propuesta', verbose_name='Contabilidad')
    # Contraparte y vínculos (registros existentes de la misma empresa)
    proveedor = models.ForeignKey('pos.Provider', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    cliente = models.ForeignKey('pos.Client', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    compra = models.ForeignKey('pos.Purchase', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    venta = models.ForeignKey('pos.Sale', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    # Resultado completo del análisis (importes como texto), avisos y propuesta contable
    datos = models.JSONField(default=dict, blank=True)
    advertencias = models.JSONField(default=list, blank=True)
    errores = models.JSONField(default=list, blank=True)
    propuesta_contable = models.JSONField(null=True, blank=True)
    revisado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    revisado_en = models.DateTimeField(null=True, blank=True)
    nota_revision = models.CharField(max_length=300, blank=True)
    creado = models.DateTimeField(default=timezone.now, verbose_name='Importado el')
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Documento importado'
        verbose_name_plural = 'Documentos importados'
        ordering = ('-id',)
        default_permissions = ()
        permissions = (('view_documentoimportado', 'Puede ver documentos importados'),
                       ('add_documentoimportado', 'Puede importar XML y RIDE'),
                       ('change_documentoimportado', 'Puede revisar, clasificar y vincular documentos importados'))
        constraints = [models.UniqueConstraint(fields=['company', 'ambiente', 'clave_acceso'], name='documento_importado_unico')]
        indexes = [models.Index(fields=['company', 'estado_revision'], name='docimp_revision'),
                   models.Index(fields=['company', 'clasificacion'], name='docimp_clasificacion'),
                   models.Index(fields=['company', 'emisor_ruc'], name='docimp_emisor')]

    def __str__(self):
        return f'{self.get_cod_doc_display()} {self.numero} · {self.emisor_razon_social}'

    def get_cod_doc_display(self):
        from core.importacion.xml_sri import NOMBRES
        return NOMBRES.get(self.cod_doc, self.cod_doc)


class ImpuestoImportado(TenantModel):
    """Desglose original por código de impuesto y código de porcentaje (no se reinterpreta la tarifa)."""
    documento = models.ForeignKey(DocumentoImportado, on_delete=models.CASCADE, related_name='impuestos')
    codigo = models.CharField(max_length=2, verbose_name='Código de impuesto')
    codigo_porcentaje = models.CharField(max_length=4, verbose_name='Código de porcentaje')
    impuesto = models.CharField(max_length=20, verbose_name='Impuesto')
    categoria = models.CharField(max_length=20, verbose_name='Categoría')   # iva_tarifa, iva_0, iva_exento, iva_no_objeto…
    tarifa = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name='Tarifa')
    base_imponible = models.DecimalField(verbose_name='Base imponible', **IMPORTE)
    valor = models.DecimalField(verbose_name='Valor', **IMPORTE)
    descuento_adicional = models.DecimalField(verbose_name='Descuento adicional', **IMPORTE)
    valor_devolucion_iva = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ('id',)
        default_permissions = ()


class EntradaLote(TenantModel):
    """Cada archivo de un lote y lo que pasó con él (el mismo archivo puede repetirse en otro lote: queda como duplicado)."""
    ESTADOS = (('en_cola', 'En cola'), ('procesando', 'Procesando'), ('procesado', 'Procesado'), ('duplicado', 'Duplicado'),
               ('pendiente_xml', 'Clave encontrada: falta el XML autorizado'),
               ('pendiente_clave', 'Sin clave legible: escríbela o sube el XML'), ('rechazado', 'Rechazado'))

    lote = models.ForeignKey(LoteImportacion, on_delete=models.CASCADE, related_name='entradas')
    archivo = models.ForeignKey(ArchivoImportado, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    nombre = models.CharField(max_length=255, verbose_name='Nombre del archivo')
    tamano = models.PositiveIntegerField(default=0)
    tipo = models.CharField(max_length=12, blank=True, verbose_name='Tipo detectado')
    orden = models.PositiveIntegerField(default=0)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='en_cola', verbose_name='Estado')
    documento = models.ForeignKey(DocumentoImportado, null=True, blank=True, on_delete=models.SET_NULL, related_name='entradas')
    errores = models.JSONField(default=list, blank=True)
    advertencias = models.JSONField(default=list, blank=True)
    candidatas = models.JSONField(default=list, blank=True)
    intentos = models.PositiveSmallIntegerField(default=0)
    procesado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('lote', 'orden', 'id')
        default_permissions = ()


class EventoImportacion(TenantModel):
    """Bitácora de cada paso (procesado, duplicado, verificado, clasificado, revisado, vinculado…)."""
    documento = models.ForeignKey(DocumentoImportado, null=True, blank=True, on_delete=models.CASCADE, related_name='eventos')
    lote = models.ForeignKey(LoteImportacion, null=True, blank=True, on_delete=models.CASCADE, related_name='eventos')
    entrada = models.ForeignKey(EntradaLote, null=True, blank=True, on_delete=models.SET_NULL, related_name='eventos')
    tipo = models.CharField(max_length=30, verbose_name='Tipo')
    mensaje = models.CharField(max_length=500, verbose_name='Mensaje')
    datos = models.JSONField(default=dict, blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    creado = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ('id',)
        default_permissions = ()


class ReglaImportacion(TenantModel):
    """Reglas de importación y contabilización de la empresa (una por empresa). Las cuentas son códigos del plan de
    cuentas del contador: el sistema solo las usa para la propuesta contable revisable."""
    NATURALEZAS = (('gasto', 'Gasto'), ('inventario', 'Inventario'), ('activo_fijo', 'Activo fijo'))
    TRATAMIENTOS_IVA = (('credito_tributario', 'Crédito tributario'), ('costo_gasto', 'Mayor valor del costo o gasto'))

    verificar_con_sri = models.BooleanField(default=True, verbose_name='Verificar cada documento en el SRI al procesar el lote')
    exigir_verificacion = models.BooleanField(default=True, verbose_name='Exigir verificación en el SRI para aprobar')
    naturaleza_compra = models.CharField(max_length=15, choices=NATURALEZAS, default='gasto', verbose_name='Naturaleza de las compras')
    tratamiento_iva = models.CharField(max_length=20, choices=TRATAMIENTOS_IVA, default='credito_tributario',
                                       verbose_name='Tratamiento del IVA en compras')
    cuenta_gasto = models.CharField(max_length=30, blank=True, verbose_name='Cuenta de gasto')
    cuenta_inventario = models.CharField(max_length=30, blank=True, verbose_name='Cuenta de inventario')
    cuenta_activo_fijo = models.CharField(max_length=30, blank=True, verbose_name='Cuenta de activo fijo')
    cuenta_iva_compras = models.CharField(max_length=30, blank=True, verbose_name='Cuenta de IVA en compras (crédito tributario)')
    cuenta_proveedores = models.CharField(max_length=30, blank=True, verbose_name='Cuenta de proveedores')
    cuenta_retencion_renta = models.CharField(max_length=30, blank=True, verbose_name='Cuenta de retenciones de renta por pagar')
    cuenta_retencion_iva = models.CharField(max_length=30, blank=True, verbose_name='Cuenta de retenciones de IVA por pagar')
    cuenta_ventas = models.CharField(max_length=30, blank=True, verbose_name='Cuenta de ventas')
    cuenta_iva_ventas = models.CharField(max_length=30, blank=True, verbose_name='Cuenta de IVA en ventas')
    cuenta_clientes = models.CharField(max_length=30, blank=True, verbose_name='Cuenta de clientes')
    actualizado = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')

    class Meta:
        verbose_name = 'Reglas de importación y contabilización'
        verbose_name_plural = 'Reglas de importación y contabilización'
        default_permissions = ()
        permissions = (('view_reglaimportacion', 'Puede ver las reglas de importación'),
                       ('change_reglaimportacion', 'Puede cambiar las reglas de importación'))
        constraints = [models.UniqueConstraint(fields=['company'], name='regla_importacion_unica_por_empresa')]


class EquivalenciaProducto(TenantModel):
    """Código del proveedor → producto propio. Solo se guarda cuando el usuario marca «Recordar» al crear una compra desde
    un XML (DC8): el emparejamiento es una decisión del usuario, no se adivina."""
    proveedor = models.ForeignKey('pos.Provider', on_delete=models.CASCADE, related_name='+')
    codigo_proveedor = models.CharField(max_length=25, verbose_name='Código del proveedor')
    producto = models.ForeignKey('pos.Product', on_delete=models.CASCADE, related_name='+')
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creado = models.DateTimeField(default=timezone.now)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Equivalencia de producto del proveedor'
        verbose_name_plural = 'Equivalencias de productos de proveedores'
        default_permissions = ()
        ordering = ('proveedor', 'codigo_proveedor')
        constraints = [models.UniqueConstraint(fields=['company', 'proveedor', 'codigo_proveedor'],
                                               name='equivalencia_producto_unica')]

    def __str__(self):
        return f'{self.codigo_proveedor} → {self.producto_id}'
