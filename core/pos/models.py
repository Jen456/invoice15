import math
import tempfile
import unicodedata
import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO
from xml.etree import ElementTree

import barcode
from barcode import writer
from django.contrib.contenttypes.models import ContentType
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models import FloatField
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.forms import model_to_dict
from django.utils import timezone

from config import settings
from core.pos.choices import *
from core.pos.catalogos_sri import (TIPOS_IDENTIFICACION_PROVEEDOR, TIPOS_SUJETO, TIPOS_COMPROBANTE_COMPRA, SUSTENTOS,
                                    FORMAS_PAGO, PAGO_LOC_EXT)
from core.pos.utilities import printer
from core.pos.utilities.sri import SRI
from core.tenancy.cifrado import ClaveCifrada
from core.tenancy.context import require_company
from core.tenancy.models_base import TenantModel
from core.tenancy.storage import CompanyPath
from core.user.models import User


class Company(models.Model):
    ruc = models.CharField(max_length=13, verbose_name='Número de RUC')
    business_name = models.CharField(max_length=50, verbose_name='Razón social')
    tradename = models.CharField(max_length=50, verbose_name='Nombre Comercial')
    main_address = models.CharField(max_length=200, verbose_name='Dirección del Establecimiento Matriz')
    establishment_address = models.CharField(max_length=200, verbose_name='Dirección del Establecimiento Emisor')
    establishment_code = models.CharField(max_length=3, verbose_name='Código del Establecimiento Emisor')
    issuing_point_code = models.CharField(max_length=3, verbose_name='Código del Punto de Emisión')
    special_taxpayer = models.CharField(max_length=13, verbose_name='Contribuyente Especial (Número de Resolución)')
    obligated_accounting = models.CharField(max_length=2, choices=OBLIGATED_ACCOUNTING, default=OBLIGATED_ACCOUNTING[1][0], verbose_name='Obligado a Llevar Contabilidad')
    image = models.ImageField(null=True, blank=True, upload_to=CompanyPath('logo'), verbose_name='Logotipo de la empresa')
    environment_type = models.PositiveIntegerField(choices=ENVIRONMENT_TYPE, default=1, verbose_name='Tipo de Ambiente')
    emission_type = models.PositiveIntegerField(choices=EMISSION_TYPE, default=1, verbose_name='Tipo de Emisión')
    retention_agent = models.CharField(max_length=2, choices=RETENTION_AGENT, default=RETENTION_AGENT[1][0], verbose_name='Agente de Retención')
    rimpe = models.CharField(max_length=20, choices=RIMPE, default='', blank=True, verbose_name='Régimen RIMPE',
                             help_text='Si la empresa está en el RIMPE, sus comprobantes llevan la leyenda que exige el SRI.')
    mobile = models.CharField(max_length=10, verbose_name='Teléfono celular')
    phone = models.CharField(max_length=9, verbose_name='Teléfono convencional')
    email = models.CharField(max_length=50, verbose_name='Email')
    website = models.CharField(max_length=250, verbose_name='Dirección de página web')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Descripción')
    iva = models.DecimalField(default=0.00, decimal_places=2, max_digits=9, verbose_name='IVA')
    vat_percentage = models.IntegerField(choices=VAT_PERCENTAGE, default=VAT_PERCENTAGE[3][0], verbose_name='Porcentaje del IVA')
    electronic_signature = models.FileField(null=True, blank=True, upload_to=CompanyPath('firma'), verbose_name='Firma electrónica (Archivo P12)')
    electronic_signature_key = ClaveCifrada(verbose_name='Clave de firma electrónica')   # cifrada en la base (FPA_CLAVES_CIFRADO)
    email_host = models.CharField(max_length=30, default='smtp.gmail.com', verbose_name='Servidor de correo')
    email_port = models.IntegerField(default=587, verbose_name='Puerto del servidor de correo')
    email_host_user = models.CharField(max_length=100, verbose_name='Username del servidor de correo')
    email_host_password = models.CharField(max_length=30, verbose_name='Password del servidor de correo')
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True, verbose_name='Activa')
    created_at = models.DateTimeField(default=timezone.now, editable=False, verbose_name='Fecha de alta')


    @property
    def leyenda_rimpe(self):
        return LEYENDAS_RIMPE.get(self.rimpe or '', '')

    def __str__(self):
        return self.business_name

    def get_image(self):
        if self.image:
            return f'{settings.MEDIA_URL}{self.image}'
        return f'{settings.STATIC_URL}img/default/empty.png'

    def get_full_path_image(self):
        if self.image:
            return self.image.path
        return f'{settings.BASE_DIR}{settings.STATIC_URL}img/default/empty.png'

    def get_iva(self):
        return float(self.iva)

    def get_electronic_signature(self):
        if self.electronic_signature:
            return f'{settings.MEDIA_URL}{self.electronic_signature}'
        return None

    # Nunca salen hacia el navegador: toJSON() viaja dentro de ventas y notas de
    # crédito (también en el listado que ven los clientes de la empresa).
    PRIVATE_FIELDS = ('electronic_signature_key', 'email_host', 'email_port', 'email_host_user', 'email_host_password')

    def toJSON(self):
        item = model_to_dict(self, exclude=self.PRIVATE_FIELDS)
        item['image'] = self.get_image()
        item['electronic_signature'] = bool(self.electronic_signature)
        item['iva'] = float(self.iva)
        return item

    class Meta:
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'
        default_permissions = ()
        permissions = (
            ('change_company', 'Can change Empresa'),
        )


class Provider(TenantModel):
    name = models.CharField(max_length=100, verbose_name='Razón Social')
    ruc = models.CharField(max_length=20, verbose_name='Identificación')
    mobile = models.CharField(max_length=10, verbose_name='Teléfono celular')
    email = models.CharField(max_length=50, verbose_name='Email')
    address = models.CharField(max_length=500, null=True, blank=True, verbose_name='Dirección')
    # Datos del proveedor para el ATS (espec-etapa2-compras §1.2). Vacío / NULL = sin indicar (proveedor incompleto).
    tipo_identificacion = models.CharField(max_length=2, choices=TIPOS_IDENTIFICACION_PROVEEDOR, blank=True, default='',
                                           verbose_name='Tipo de identificación')
    tipo_sujeto = models.CharField(max_length=2, choices=TIPOS_SUJETO, blank=True, default='', verbose_name='Tipo de sujeto')
    parte_relacionada = models.BooleanField(null=True, blank=True, default=None, verbose_name='Parte relacionada')

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return f'{self.name} ({self.ruc})'

    @property
    def tipo_id_ats(self):
        """Tipo de identificación de la Tabla 2 del ATS ('01' RUC, '02' cédula, '03' pasaporte/exterior; '' sin tipo)."""
        from core.pos.catalogos_sri import tipo_id_ats
        return tipo_id_ats(self.tipo_identificacion)

    def faltantes_ats(self):
        """[(código, texto)] de lo que le falta al proveedor para el ATS (vacío = completo)."""
        from core.pos.clientes import validar_identificacion
        faltan = []
        if not self.tipo_identificacion:
            faltan.append(('tipo_identificacion', 'Falta el tipo de identificación'))
        elif self.tipo_identificacion in ('06', '08') and not self.tipo_sujeto:
            faltan.append(('tipo_sujeto', 'Elige si es persona natural o sociedad'))
        if self.parte_relacionada is None:
            faltan.append(('parte_relacionada', 'Indica si es parte relacionada'))
        if self.tipo_identificacion:
            _, errores = validar_identificacion(self.tipo_identificacion, self.ruc)
            if errores:
                faltan.append(('identificacion_invalida', errores[0][1]))
        return faltan

    @property
    def datos_completos(self):
        return not self.faltantes_ats()

    def toJSON(self):
        item = model_to_dict(self)
        item['text'] = self.get_full_name()
        faltan = self.faltantes_ats()
        item['tipo_identificacion'] = {'id': self.tipo_identificacion, 'name': self.get_tipo_identificacion_display()}
        item['tipo_sujeto'] = {'id': self.tipo_sujeto, 'name': self.get_tipo_sujeto_display()}
        item['parte_relacionada'] = self.parte_relacionada
        item['tipo_id_ats'] = self.tipo_id_ats
        item['datos_completos'] = not faltan
        item['faltantes'] = [{'codigo': codigo, 'texto': texto} for codigo, texto in faltan]
        return item

    class Meta:
        constraints = [models.UniqueConstraint(fields=['company', 'name'], name='provider_name_por_empresa'), models.UniqueConstraint(fields=['company', 'ruc'], name='provider_ruc_por_empresa'), models.UniqueConstraint(fields=['company', 'mobile'], name='provider_mobile_por_empresa'), models.UniqueConstraint(fields=['company', 'email'], name='provider_email_por_empresa')]
        verbose_name = 'Proveedor'
        verbose_name_plural = 'Proveedores'


class Category(TenantModel):
    name = models.CharField(max_length=50, verbose_name='Nombre')

    def __str__(self):
        return self.name

    def toJSON(self):
        item = model_to_dict(self)
        return item

    class Meta:
        constraints = [models.UniqueConstraint(fields=['company', 'name'], name='category_name_por_empresa')]
        verbose_name = 'Categoria'
        verbose_name_plural = 'Categorias'


class Product(TenantModel):
    name = models.CharField(max_length=150, verbose_name='Nombre')
    code = models.CharField(max_length=20, verbose_name='Código')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Descripción')
    category = models.ForeignKey(Category, on_delete=models.PROTECT, verbose_name='Categoría')
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Precio de Compra')
    pvp = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Precio de Venta')
    image = models.ImageField(upload_to=CompanyPath('productos'), null=True, blank=True, verbose_name='Imagen')
    barcode = models.ImageField(upload_to=CompanyPath('codigos'), null=True, blank=True, verbose_name='Código de barra')
    inventoried = models.BooleanField(default=True, verbose_name='¿Es inventariado?')
    stock = models.IntegerField(default=0)
    with_tax = models.BooleanField(default=True, verbose_name='¿Se cobra impuesto?')
    tarifa_iva = models.CharField(max_length=2, choices=TARIFAS_IVA, default='', blank=True, verbose_name='Tarifa de IVA',
                                  help_text='La que corresponde a este producto: 15 %, 5 %, 0 %, exento o no objeto de IVA.')

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return f'{self.name} ({self.code}) ({self.category.name})'

    def get_short_name(self):
        return f'{self.name} ({self.category.name})'

    def get_inventoried(self):
        if self.inventoried:
            return 'Inventariado'
        return 'No inventariado'

    def get_price_promotion(self):
        promotions = self.promotionsdetail_set.filter(promotion__state=True).first()
        if promotions:
            return promotions.price_final
        return 0.00

    def get_price_current(self):
        price_promotion = self.get_price_promotion()
        if price_promotion > 0:
            return price_promotion
        return self.pvp

    def get_image(self):
        if self.image:
            return f'{settings.MEDIA_URL}{self.image}'
        return f'{settings.STATIC_URL}img/default/empty.png'

    def get_barcode(self):
        if self.barcode:
            return f'{settings.MEDIA_URL}{self.barcode}'
        return f'{settings.STATIC_URL}img/default/empty.png'

    def get_benefit(self):
        benefit = float(self.pvp) - float(self.price)
        return round(benefit, 2)

    def generate_barcode(self):
        image_io = BytesIO()
        barcode.Gs1_128(self.code, writer=barcode.writer.ImageWriter()).write(image_io)
        filename = f'{self.code}.png'
        self.barcode.save(filename, content=ContentFile(image_io.getvalue()), save=False)

    def toJSON(self):
        item = model_to_dict(self)
        item['full_name'] = self.get_full_name()
        item['short_name'] = self.get_short_name()
        item['category'] = self.category.toJSON()
        item['price'] = float(self.price)
        item['price_promotion'] = float(self.get_price_promotion())
        item['price_current'] = float(self.get_price_current())
        item['pvp'] = float(self.pvp)
        item['image'] = self.get_image()
        item['barcode'] = self.get_barcode()
        item['tarifa_iva'] = self.tarifa_iva or ('4' if self.with_tax else '0')
        item['tarifa'] = float(PORCENTAJE_IVA.get(item['tarifa_iva'], 0))
        item['nombre_tarifa'] = NOMBRE_TARIFA_IVA.get(item['tarifa_iva'], '')
        return item

    def save(self, force_insert=False, force_update=False, using=None,
             update_fields=None):
        # La tarifa manda; sin tarifa (código que solo conoce «¿Se cobra impuesto?»), se deriva de with_tax.
        if self.tarifa_iva:
            self.with_tax = PORCENTAJE_IVA.get(self.tarifa_iva, Decimal('0')) > 0
        else:
            self.tarifa_iva = '4' if self.with_tax else '0'
        # La imagen del código de barras se hace al crear el producto, al cambiar su código o si falta el archivo; antes se
        # rehacía en cada guardado (cada venta o compra mueve el stock) y la anterior quedaba huérfana.
        anterior = type(self).all_companies.filter(pk=self.pk).values_list('code', 'barcode').first() if self.pk else None
        if anterior is None or anterior[0] != self.code or not self.barcode or not self.barcode.storage.exists(self.barcode.name):
            reemplazada = anterior[1] if anterior else None
            self.generate_barcode()
            if reemplazada and reemplazada != self.barcode.name:
                almacen = self.barcode.storage
                transaction.on_commit(lambda: almacen.delete(reemplazada))
        super(Product, self).save()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['company', 'code'], name='product_code_por_empresa')]
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'
        default_permissions = ()
        permissions = (
            ('view_product', 'Can view Producto'),
            ('add_product', 'Can add Producto'),
            ('change_product', 'Can change Producto'),
            ('delete_product', 'Can delete Producto'),
            ('adjust_product_stock', 'Can adjust_product_stock Producto'),
        )


# Establecimiento y punto del comprobante del proveedor: tres dígitos, 000 no es válido (igual que codigo_sri, más abajo).
codigo_sri_compra = RegexValidator(r'^(?!000)\d{3}$', 'Usa tres dígitos, por ejemplo 001 (000 no es válido).')
IMPORTES_COMPRA = ('base_0', 'base_gravada', 'base_5', 'base_no_objeto', 'base_exenta', 'total_descuento', 'total_iva',
                   'total_ice', 'total_irbpnr', 'propina', 'total')


def _texto_importe(valor):
    """Importe como texto con dos decimales ("135.00"), o None si no se conoce."""
    return None if valor is None else f'{Decimal(valor):.2f}'


class Purchase(TenantModel):
    """Compra registrada. Los datos del comprobante (ATS) y los importes por base son de la Etapa 2; en las compras anteriores
    los importes quedan NULL (desconocidos, no cero) y la compra marcada con datos incompletos (espec-etapa2-compras §1.3)."""
    VERSIONES = ((1, 'Solo subtotal (sin impuestos por línea)'), (2, 'Con impuestos por línea'))
    ORIGENES = (('manual', 'Registrada a mano'), ('importacion', 'Creada desde un XML importado'))

    number = models.CharField(max_length=20, blank=True, default='', verbose_name='Número del comprobante')
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, verbose_name='Proveedor')
    payment_type = models.CharField(choices=PAYMENT_TYPE, max_length=50, default=PAYMENT_TYPE[0][0], verbose_name='Tipo de pago')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de registro')
    end_credit = models.DateField(default=datetime.now, verbose_name='Fecha de plazo de credito')
    subtotal = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(default=timezone.now, editable=False, verbose_name='Registrada el')
    # Comprobante del proveedor (detalleCompras del ATS)
    tipo_comprobante = models.CharField(max_length=3, choices=TIPOS_COMPROBANTE_COMPRA, blank=True, default='',
                                        verbose_name='Tipo de comprobante')
    cod_sustento = models.CharField(max_length=2, choices=SUSTENTOS, blank=True, default='', verbose_name='Sustento tributario')
    estab = models.CharField(max_length=3, blank=True, default='', validators=[codigo_sri_compra], verbose_name='Establecimiento')
    pto_emi = models.CharField(max_length=3, blank=True, default='', validators=[codigo_sri_compra], verbose_name='Punto de emisión')
    secuencial = models.CharField(max_length=9, blank=True, default='', verbose_name='Secuencial')
    autorizacion = models.CharField(max_length=49, blank=True, default='', verbose_name='Autorización')
    fecha_emision = models.DateField(null=True, blank=True, verbose_name='Fecha de emisión del comprobante')
    forma_pago = models.CharField(max_length=2, choices=FORMAS_PAGO, blank=True, default='', verbose_name='Forma de pago (ATS)')
    parte_relacionada = models.BooleanField(null=True, blank=True, default=None, verbose_name='Parte relacionada')
    pago_loc_ext = models.CharField(max_length=2, choices=PAGO_LOC_EXT, blank=True, default='',
                                    verbose_name='Pago a residente o no residente')
    # Documento modificado (notas de crédito y débito del proveedor)
    tipo_doc_modificado = models.CharField(max_length=3, choices=TIPOS_COMPROBANTE_COMPRA, blank=True, default='',
                                           verbose_name='Tipo del documento modificado')
    num_doc_modificado = models.CharField(max_length=15, blank=True, default='', verbose_name='Número del documento modificado')
    aut_doc_modificado = models.CharField(max_length=49, blank=True, default='', verbose_name='Autorización del documento modificado')
    fecha_doc_modificado = models.DateField(null=True, blank=True, verbose_name='Fecha del documento modificado')
    compra_modificada = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='ajustes',
                                          verbose_name='Compra que modifica')
    # Importes de la factura: NULL en las compras anteriores (desconocidos). base_gravada = tarifa distinta de 0 % y de 5 %.
    base_0 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Base 0 %')
    base_gravada = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Base gravada')
    base_5 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Base 5 %')
    base_no_objeto = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Base no objeto de IVA')
    base_exenta = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Base exenta de IVA')
    total_descuento = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Total descuento')
    total_iva = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='IVA')
    total_ice = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='ICE')
    total_irbpnr = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='IRBPNR')
    propina = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Propina')
    total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Total')
    # Estado de los datos. Los valores por defecto fallan cerrados (DC2): solo compras.crear_compra escribe version_datos=2
    # y solo compras.actualizar_marca baja la marca de datos incompletos.
    version_datos = models.PositiveSmallIntegerField(choices=VERSIONES, default=1, verbose_name='Versión de los datos')
    datos_incompletos = models.BooleanField(default=True, verbose_name='Datos incompletos')
    fuera_plazo_ats = models.BooleanField(default=False, verbose_name='Registrada fuera del plazo del ATS')
    origen = models.CharField(max_length=12, choices=ORIGENES, default='manual', verbose_name='Origen')
    completada_en = models.DateTimeField(null=True, blank=True, editable=False, verbose_name='Datos completados el')
    completada_por = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', editable=False,
                                       verbose_name='Datos completados por')

    def __str__(self):
        return self.provider.name

    @property
    def numero_comprobante(self):
        if self.secuencial:
            return f'{self.estab}-{self.pto_emi}-{self.secuencial}'
        return self.number or 'S/N'

    @property
    def signo(self):
        """-1 en las notas de crédito del proveedor (restan en los totales de los reportes), 1 en lo demás."""
        return -1 if self.tipo_comprobante == '04' else 1

    @property
    def clase(self):
        """inventario (todas las líneas con producto), gasto (ninguna) o mixta."""
        lineas = list(self.purchasedetail_set.values_list('product_id', flat=True))
        con_producto = sum(1 for p in lineas if p is not None)
        if con_producto == len(lineas):
            return 'inventario'
        return 'gasto' if con_producto == 0 else 'mixta'

    def faltantes(self):
        from core.pos import compras
        return compras.faltantes(self)

    def calculate_invoice(self):
        """Compatibilidad con el registro anterior (el flujo de compras.crear_compra no la usa)."""
        subtotal = 0.00
        for i in self.purchasedetail_set.all():
            subtotal += float(i.price) * int(i.cant)
        self.subtotal = subtotal
        self.save()

    def delete(self, using=None, keep_parents=False):
        """Borra las líneas y devuelve el stock de las que tienen producto inventariado (atómico, con F()).
        Las reglas de negocio (pagos, retención, documento importado, auditoría) están en compras.eliminar_compra."""
        from django.db.models import F
        with transaction.atomic():
            lineas = self.purchasedetail_set.filter(product__isnull=False, product__inventoried=True)
            for producto_id, cantidad in lineas.values_list('product_id', 'cant'):
                Product.objects.filter(pk=producto_id).update(stock=F('stock') - cantidad)
            self.purchasedetail_set.all().delete()
            return super(Purchase, self).delete(using=using, keep_parents=keep_parents)

    def toJSON(self, detalle=False):
        """Claves anteriores más los datos del comprobante e importes como texto ("135.00") o null. Sin consultas extra por
        fila (usa datos_incompletos guardado y self.provider); con detalle=True añade clase y faltantes."""
        item = {'id': self.pk, 'number': self.number, 'provider': self.provider.toJSON(),
                'payment_type': {'id': self.payment_type, 'name': self.get_payment_type_display()},
                'date_joined': self.date_joined.strftime('%Y-%m-%d'), 'end_credit': self.end_credit.strftime('%Y-%m-%d'),
                'subtotal': float(self.subtotal)}
        item.update({
            'numero_comprobante': self.numero_comprobante,
            'tipo_comprobante': {'id': self.tipo_comprobante, 'name': self.get_tipo_comprobante_display()},
            'cod_sustento': {'id': self.cod_sustento, 'name': self.get_cod_sustento_display()},
            'estab': self.estab, 'pto_emi': self.pto_emi, 'secuencial': self.secuencial, 'autorizacion': self.autorizacion,
            'fecha_emision': self.fecha_emision.strftime('%Y-%m-%d') if self.fecha_emision else None,
            'forma_pago': {'id': self.forma_pago, 'name': self.get_forma_pago_display()},
            'parte_relacionada': self.parte_relacionada,
            'pago_loc_ext': {'id': self.pago_loc_ext, 'name': self.get_pago_loc_ext_display()},
            'signo': self.signo, 'version_datos': self.version_datos, 'datos_incompletos': self.datos_incompletos,
            'fuera_plazo_ats': self.fuera_plazo_ats, 'origen': {'id': self.origen, 'name': self.get_origen_display()},
        })
        for campo in IMPORTES_COMPRA:
            item[campo] = _texto_importe(getattr(self, campo))
        tiene_doc = (self.tipo_doc_modificado or self.num_doc_modificado or self.aut_doc_modificado
                     or self.fecha_doc_modificado or self.compra_modificada_id)
        item['doc_modificado'] = {
            'tipo': self.tipo_doc_modificado, 'numero': self.num_doc_modificado, 'autorizacion': self.aut_doc_modificado,
            'fecha': self.fecha_doc_modificado.strftime('%Y-%m-%d') if self.fecha_doc_modificado else None,
            'compra_id': self.compra_modificada_id} if tiene_doc else None
        if detalle:
            item['clase'] = self.clase
            item['faltantes'] = [{'codigo': codigo, 'texto': texto} for codigo, texto in self.faltantes()]
        return item

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['company', 'provider', 'tipo_comprobante', 'estab', 'pto_emi', 'secuencial'],
                                    condition=~models.Q(secuencial=''), name='compra_comprobante_unico_por_proveedor'),
            models.CheckConstraint(condition=models.Q(total__isnull=True) | models.Q(total__gte=0), name='compra_total_no_negativo'),
            # Fallan cerrados: una compra sin totales no puede figurar como completa ni como «con impuestos por línea».
            models.CheckConstraint(condition=models.Q(datos_incompletos=True) | models.Q(total__isnull=False),
                                   name='compra_completa_con_totales'),
            models.CheckConstraint(condition=models.Q(version_datos=1) | models.Q(total__isnull=False),
                                   name='compra_v2_con_totales'),
        ]
        indexes = [models.Index(fields=['company', 'datos_incompletos'], name='compra_incompleta'),
                   models.Index(fields=['company', 'fecha_emision'], name='compra_fecha_emision')]
        verbose_name = 'Compra'
        verbose_name_plural = 'Compras'
        default_permissions = ()
        permissions = (
            ('view_purchase', 'Can view Compra'),
            ('add_purchase', 'Can add Compra'),
            ('change_purchase', 'Can change Compra'),     # completar los datos del comprobante
            ('delete_purchase', 'Can delete Compra'),
        )


def nombre_tarifa_compra(codigo, tarifa):
    """Nombre visible de la tarifa de una línea de compra ('IVA diferenciado 8 %' para el código 8; '—' si no se conoce)."""
    if codigo == '8':
        return f'IVA diferenciado {Decimal(tarifa).normalize():f} %' if tarifa is not None else 'IVA diferenciado'
    return NOMBRE_TARIFA_IVA.get(codigo, '—') if codigo else '—'


class PurchaseDetail(TenantModel):
    """Línea de compra: con producto (mueve stock si es inventariado) o de gasto (sin producto, con descripción). Las
    líneas anteriores a la Etapa 2 no tienen tarifa: codigo_porcentaje='' y total/total_iva NULL (desconocidos)."""
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.PROTECT)
    cant = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)   # fracción; sin uso (siempre 0)
    subtotal = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    type_expense = models.ForeignKey('TypeExpense', null=True, blank=True, on_delete=models.PROTECT, verbose_name='Tipo de gasto')
    descripcion = models.CharField(max_length=300, blank=True, default='', verbose_name='Descripción')
    codigo_proveedor = models.CharField(max_length=25, blank=True, default='', verbose_name='Código del proveedor')
    codigo_porcentaje = models.CharField(max_length=2, blank=True, default='', verbose_name='Tarifa de IVA (código)')
    tarifa = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name='Tarifa de IVA aplicada (%)')
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0, verbose_name='Descuento')
    total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Base de la línea')
    total_iva = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='IVA de la línea')
    total_ice = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='ICE de la línea')

    def __str__(self):
        return self.product.name if self.product_id else self.descripcion

    def toJSON(self):
        item = {'id': self.pk, 'product': self.product.toJSON() if self.product_id else None,
                'tipo': 'producto' if self.product_id else 'gasto',
                'descripcion': self.descripcion or (self.product.name if self.product_id else ''),
                'type_expense': {'id': self.type_expense_id, 'name': self.type_expense.name} if self.type_expense_id else None,
                'codigo_proveedor': self.codigo_proveedor, 'codigo_porcentaje': self.codigo_porcentaje,
                'tarifa': _texto_importe(self.tarifa), 'nombre_tarifa': nombre_tarifa_compra(self.codigo_porcentaje, self.tarifa),
                'cant': self.cant, 'price': float(self.price), 'dscto': float(self.dscto), 'subtotal': float(self.subtotal),
                'total_dscto': _texto_importe(self.total_dscto), 'total': _texto_importe(self.total),
                'total_iva': _texto_importe(self.total_iva), 'total_ice': _texto_importe(self.total_ice)}
        return item

    class Meta:
        verbose_name = 'Detalle de Compra'
        verbose_name_plural = 'Detalle de Compras'
        default_permissions = ()
        ordering = ('id',)
        constraints = [models.CheckConstraint(condition=models.Q(product__isnull=False) | ~models.Q(descripcion=''),
                                              name='detalle_compra_producto_o_descripcion')]


class Client(TenantModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='clients', verbose_name='Usuario')
    dni = models.CharField(max_length=20, verbose_name='Número de cedula o ruc')
    # Opcional y repetible: hay compradores sin teléfono y empresas de un mismo grupo que comparten la central.
    mobile = models.CharField(max_length=10, blank=True, default='', verbose_name='Teléfono')
    birthdate = models.DateField(default=datetime.now, verbose_name='Fecha de nacimiento')
    address = models.CharField(max_length=500, verbose_name='Dirección')
    identification_type = models.CharField(max_length=30, choices=IDENTIFICATION_TYPE, default=IDENTIFICATION_TYPE[0][0], verbose_name='Tipo de identificación')
    send_email_invoice = models.BooleanField(default=True, verbose_name='¿Enviar email de factura?')
    extra_emails = models.CharField(max_length=500, blank=True, default='', verbose_name='Otros correos (separados por comas)')

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return f'{self.user.names} ({self.dni})'

    def correos(self):
        """Correo principal y adicionales, sin repetir: todos reciben los comprobantes."""
        from core.pos.clientes import separar_correos
        return separar_correos(self.user.email, self.extra_emails)

    def birthdate_format(self):
        return self.birthdate.strftime('%Y-%m-%d')

    def toJSON(self):
        item = model_to_dict(self)
        item['text'] = self.get_full_name()
        item['user'] = self.user.toJSON()
        item['identification_type'] = {'id': self.identification_type, 'name': self.get_identification_type_display()}
        item['birthdate'] = self.birthdate.strftime('%Y-%m-%d')
        return item

    def delete(self, using=None, keep_parents=False):
        super(Client, self).delete()
        try:
            self.user.delete()
        except:
            pass

    class Meta:
        constraints = [models.UniqueConstraint(fields=['company', 'dni'], name='client_dni_por_empresa')]
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'


# Códigos del SRI: tres dígitos con ceros iniciales (001, 002...). 000 no es válido.
codigo_sri = RegexValidator(r'^(?!000)\d{3}$', 'Usa tres dígitos, por ejemplo 001 (000 no es válido).')
MAX_SECUENCIAL = 999999999


class Establishment(TenantModel):
    """Establecimiento registrado en el SRI (estab del comprobante)."""
    code = models.CharField(max_length=3, validators=[codigo_sri], verbose_name='Código del establecimiento')
    name = models.CharField(max_length=100, blank=True, verbose_name='Nombre del establecimiento')
    address = models.CharField(max_length=200, verbose_name='Dirección del establecimiento')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = 'Establecimiento'
        verbose_name_plural = 'Establecimientos'
        ordering = ('code',)
        constraints = [models.UniqueConstraint(fields=['company', 'code'], name='establecimiento_unico_por_empresa')]

    def __str__(self):
        return f'{self.code} · {self.name or self.address}'


class EmissionPoint(TenantModel):
    """Punto de emisión de un establecimiento (ptoEmi del comprobante)."""
    establishment = models.ForeignKey(Establishment, on_delete=models.PROTECT, related_name='points', verbose_name='Establecimiento')
    code = models.CharField(max_length=3, validators=[codigo_sri], verbose_name='Código del punto de emisión')
    description = models.CharField(max_length=100, blank=True, verbose_name='Descripción')
    is_default = models.BooleanField(default=False, verbose_name='Punto con el que se emite')
    is_active = models.BooleanField(default=True, verbose_name='Activo')
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = 'Punto de emisión'
        verbose_name_plural = 'Puntos de emisión'
        ordering = ('establishment__code', 'code')
        constraints = [
            models.UniqueConstraint(fields=['establishment', 'code'], name='punto_unico_por_establecimiento'),
            models.UniqueConstraint(fields=['company'], condition=models.Q(is_default=True), name='un_punto_predeterminado_por_empresa'),
        ]

    def __str__(self):
        return f'{self.establishment.code}-{self.code}'

    @property
    def full_code(self):
        return f'{self.establishment.code}-{self.code}'


class BillingSetup(TenantModel):
    """Progreso del asistente de configuración de facturación (uno por empresa)."""
    current_step = models.PositiveSmallIntegerField(default=1, verbose_name='Paso actual')
    completed_steps = models.JSONField(default=list, blank=True, verbose_name='Pasos completados')
    production_confirmed = models.BooleanField(default=False, verbose_name='Producción confirmada')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='Configuración confirmada el')
    completed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración de facturación'
        verbose_name_plural = 'Configuraciones de facturación'
        constraints = [models.UniqueConstraint(fields=['company'], name='una_configuracion_por_empresa')]


class Receipt(TenantModel):
    """Secuencia de numeración por empresa, ambiente, establecimiento, punto de emisión y tipo.

    `sequence` es el ÚLTIMO número utilizado: el próximo documento lleva
    sequence + 1 y se reserva con reservar_numero() bajo bloqueo de fila.
    """
    ORIGINS = (('nuevo', 'Empieza en 000000001'), ('otro_sistema', 'Continúa la numeración de otro sistema'),
               ('existente', 'Existente antes del asistente'))
    voucher_type = models.CharField(max_length=10, choices=VOUCHER_TYPE, verbose_name='Tipo de Comprobante')
    establishment_code = models.CharField(max_length=3, verbose_name='Código del Establecimiento Emisor')
    issuing_point_code = models.CharField(max_length=3, verbose_name='Código del Punto de Emisión')
    sequence = models.PositiveIntegerField(default=0, verbose_name='Último número utilizado')
    environment_type = models.PositiveIntegerField(choices=ENVIRONMENT_TYPE, default=1, verbose_name='Ambiente')
    emission_point = models.ForeignKey(EmissionPoint, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name='sequences', verbose_name='Punto de emisión')
    origin = models.CharField(max_length=20, choices=ORIGINS, default='existente', verbose_name='Origen de la numeración')
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name='Numeración confirmada el')
    confirmed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    def __str__(self):
        return f'{self.name} - {self.establishment_code} - {self.issuing_point_code}'

    @property
    def name(self):
        return self.get_voucher_type_display()

    def get_name_xml(self):
        return self.remove_accents(self.name.replace(' ', '_').lower())

    def remove_accents(self, text):
        return ''.join((c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn'))

    def get_sequence(self):
        return f'{self.sequence:09d}'

    @property
    def next_number(self):
        return self.sequence + 1

    def next_number_full(self):
        return f'{self.establishment_code}-{self.issuing_point_code}-{self.next_number:09d}'

    def establishment_address(self):
        """Dirección del establecimiento de esta numeración (dirEstablecimiento del comprobante)."""
        if self.emission_point_id:
            return self.emission_point.establishment.address
        return ''

    def last_number_full(self):
        return f'{self.establishment_code}-{self.issuing_point_code}-{self.sequence:09d}' if self.sequence else ''

    @staticmethod
    def modelos_con_numero():
        """Modelos de comprobante que consumen números de una secuencia."""
        from core.comprobantes.models import GuiaRemision, LiquidacionCompra, NotaDebito, Retencion
        return (Sale, CreditNote, Retencion, LiquidacionCompra, NotaDebito, GuiaRemision)

    def max_used(self):
        """Mayor secuencial ya registrado en esta secuencia (cualquier tipo de comprobante)."""
        numeros = [m.all_companies.filter(receipt_id=self.pk).aggregate(n=models.Max('voucher_number'))['n']
                   for m in self.modelos_con_numero()]
        return max([int(n) for n in numeros if n] or [0])

    @property
    def is_used(self):
        return any(m.all_companies.filter(receipt_id=self.pk).exists() for m in self.modelos_con_numero())

    def reservar_numero(self):
        """Reserva el próximo secuencial de forma atómica (bloqueo de la fila).

        Dentro de la transacción de la venta: el bloqueo dura hasta su fin, así
        dos emisiones simultáneas reciben números distintos y, si la venta se
        deshace, el número vuelve a quedar libre. Nunca reutiliza un número ya
        registrado en esta secuencia.
        """
        with transaction.atomic():
            fila = Receipt.all_companies.select_for_update().get(pk=self.pk)
            numero = fila.sequence + 1
            usados = set()
            for modelo in self.modelos_con_numero():
                usados.update(modelo.all_companies.filter(receipt_id=fila.pk, voucher_number__gte=f'{numero:09d}')
                              .values_list('voucher_number', flat=True))
            while f'{numero:09d}' in usados:
                numero += 1
            if numero > MAX_SECUENCIAL:
                raise ValueError('La numeración de este comprobante llegó a 999999999. Configura un nuevo punto de emisión.')
            fila.sequence = numero
            fila.save(update_fields=['sequence'])
        self.sequence = numero
        return f'{numero:09d}'

    def registrar_usado(self, numero):
        """Tras guardar un comprobante con número dado: la secuencia nunca retrocede."""
        Receipt.all_companies.filter(pk=self.pk, sequence__lt=int(numero)).update(sequence=int(numero))

    def toJSON(self):
        item = model_to_dict(self, exclude=['confirmed_by'])
        item['name'] = self.name
        item['voucher_type'] = {'id': self.voucher_type, 'name': self.get_voucher_type_display()}
        item['environment_type'] = {'id': self.environment_type, 'name': self.get_environment_type_display()}
        item['last_number_full'] = self.last_number_full()
        item['next_number_full'] = self.next_number_full()
        item['confirmed'] = self.confirmed_at is not None
        item['confirmed_at'] = self.confirmed_at.strftime('%Y-%m-%d') if self.confirmed_at else None
        return item

    class Meta:
        verbose_name = 'Comprobante'
        verbose_name_plural = 'Comprobantes'
        constraints = [models.UniqueConstraint(
            fields=['company', 'environment_type', 'voucher_type', 'establishment_code', 'issuing_point_code'],
            name='secuencia_unica_por_ambiente_punto_y_tipo')]


# Campos de la emisión en dos fases que no se envían al navegador en toJSON().
EXCLUIR_DEL_JSON = ('xml_signed', 'signed_at', 'sri_sent_at', 'emission_date')


CENTAVO = Decimal('0.01')


def calcular_linea_iva(detalle, codigo):
    """Importes de una línea de venta o nota de crédito con la tarifa `codigo` (tabla 17). dscto es fracción (0.10 = 10 %).
    IVA de la línea = base × tarifa, HALF_UP; los totales por tarifa suman las líneas."""
    porcentaje = PORCENTAJE_IVA.get(codigo, Decimal('0'))
    precio = Decimal(str(detalle.price))
    subtotal = (precio * Decimal(detalle.cant)).quantize(CENTAVO, ROUND_HALF_UP)
    descuento = (subtotal * Decimal(str(detalle.dscto))).quantize(CENTAVO, ROUND_HALF_UP)
    detalle.codigo_porcentaje = codigo
    detalle.iva = porcentaje / 100
    detalle.price_with_vat = (precio * (1 + porcentaje / 100)).quantize(CENTAVO, ROUND_HALF_UP)
    detalle.subtotal = subtotal
    detalle.total_dscto = descuento
    detalle.total = subtotal - descuento
    detalle.total_iva = ((subtotal - descuento) * porcentaje / 100).quantize(CENTAVO, ROUND_HALF_UP)


def codigo_de_linea(detalle):
    """Tarifa guardada en la línea; las líneas anteriores al cambio se infieren de «¿Se cobra impuesto?»."""
    return detalle.codigo_porcentaje or ('4' if detalle.product_id and detalle.product.with_tax else '0')


def iva_de_linea(detalle, codigo):
    """IVA de la línea; 0 en tarifas sin IVA (las líneas antiguas guardaban un IVA calculado que no se facturaba)."""
    return Decimal(str(detalle.total_iva)) if PORCENTAJE_IVA.get(codigo, Decimal('0')) > 0 else Decimal('0')


def impuestos_por_tarifa(detalles):
    """[{codigo, nombre, tarifa, base, valor}] por código de porcentaje, en el orden del RIDE (15 %, 5 %, 0 %, no objeto, exento)."""
    grupos = {}
    for d in detalles:
        codigo = codigo_de_linea(d)
        base, valor = grupos.get(codigo, (Decimal('0'), Decimal('0')))
        grupos[codigo] = (base + Decimal(str(d.total)), valor + iva_de_linea(d, codigo))
    orden = sorted(grupos, key=lambda c: ORDEN_TARIFAS_IVA.index(c) if c in ORDEN_TARIFAS_IVA else 99)
    return [{'codigo': c, 'nombre': NOMBRE_TARIFA_IVA.get(c, c), 'tarifa': PORCENTAJE_IVA.get(c, Decimal('0')),
             'base': grupos[c][0].quantize(CENTAVO), 'valor': grupos[c][1].quantize(CENTAVO)} for c in orden]


def totales_de_lineas(detalles):
    """(subtotal gravado, subtotal 0 %/exento/no objeto, IVA, descuentos) de las líneas."""
    gravado = cero = iva = descuento = Decimal('0')
    for d in detalles:
        codigo = codigo_de_linea(d)
        if PORCENTAJE_IVA.get(codigo, Decimal('0')) > 0:
            gravado += Decimal(str(d.total))
        else:
            cero += Decimal(str(d.total))
        iva += iva_de_linea(d, codigo)
        descuento += Decimal(str(d.total_dscto))
    return gravado, cero, iva, descuento


def xml_total_con_impuestos(nodo, detalles):
    for grupo in impuestos_por_tarifa(detalles):
        total = ElementTree.SubElement(nodo, 'totalImpuesto')
        ElementTree.SubElement(total, 'codigo').text = str(TAX_CODES[0][0])
        ElementTree.SubElement(total, 'codigoPorcentaje').text = grupo['codigo']
        ElementTree.SubElement(total, 'baseImponible').text = f"{grupo['base']:.2f}"
        ElementTree.SubElement(total, 'valor').text = f"{grupo['valor']:.2f}"


def xml_impuesto_de_linea(nodo, detalle):
    codigo = codigo_de_linea(detalle)
    impuesto = ElementTree.SubElement(ElementTree.SubElement(nodo, 'impuestos'), 'impuesto')
    ElementTree.SubElement(impuesto, 'codigo').text = str(TAX_CODES[0][0])
    ElementTree.SubElement(impuesto, 'codigoPorcentaje').text = codigo
    ElementTree.SubElement(impuesto, 'tarifa').text = f'{PORCENTAJE_IVA.get(codigo, Decimal(0)):.2f}'
    ElementTree.SubElement(impuesto, 'baseImponible').text = f'{Decimal(str(detalle.total)):.2f}'
    ElementTree.SubElement(impuesto, 'valor').text = f'{iva_de_linea(detalle, codigo):.2f}'


def info_tributaria_final(company, info_tributaria):
    """Últimos nodos de <infoTributaria> en todos los comprobantes: agenteRetencion y contribuyenteRimpe (Anexo 22)."""
    if company.retention_agent == RETENTION_AGENT[0][0]:
        ElementTree.SubElement(info_tributaria, 'agenteRetencion').text = '1'
    if company.leyenda_rimpe:
        ElementTree.SubElement(info_tributaria, 'contribuyenteRimpe').text = company.leyenda_rimpe


def informacion_adicional(raiz, pares):
    """<infoAdicional> del comprobante: sin campos vacíos (el XSD exige al menos un carácter), sin saltos de
    línea, hasta 300 caracteres y como máximo 15 campos, incluido el «RUC Proveedor» (Anexo 26 de la ficha)."""
    from core.pos.emision import ruc_proveedor
    campos = []
    for nombre, valor in pares:
        nombre, valor = ' '.join(str(nombre or '').split())[:300], ' '.join(str(valor or '').split())[:300]
        if nombre and valor and nombre != 'RUC Proveedor':
            campos.append((nombre, valor))
    ruc = ruc_proveedor()
    campos = campos[:14] if ruc else campos[:15]
    if ruc:
        campos.append(('RUC Proveedor', ruc))
    if campos:
        nodo = ElementTree.SubElement(raiz, 'infoAdicional')
        for nombre, valor in campos:
            ElementTree.SubElement(nodo, 'campoAdicional', nombre=nombre).text = valor


class Sale(TenantModel):
    client = models.ForeignKey(Client, on_delete=models.PROTECT, verbose_name='Cliente')
    receipt = models.ForeignKey(Receipt, on_delete=models.PROTECT, limit_choices_to={'voucher_type__in': ['01', '08']}, verbose_name='Tipo de comprobante')
    voucher_number = models.CharField(max_length=9, verbose_name='Número de comprobante')
    voucher_number_full = models.CharField(max_length=20, verbose_name='Número de comprobante completo')
    employee = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name='Empleado')
    payment_type = models.CharField(choices=PAYMENT_TYPE, max_length=50, default=PAYMENT_TYPE[0][0], verbose_name='Tipo de pago')
    payment_method = models.CharField(choices=PAYMENT_METHOD, max_length=50, default='20', verbose_name='Método de pago')
    time_limit = models.IntegerField(default=31, verbose_name='Plazo')
    creation_date = models.DateTimeField(default=datetime.now, verbose_name='Fecha y hora de registro')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de registro')
    end_credit = models.DateField(default=datetime.now, verbose_name='Fecha limite de credito')
    additional_info = models.JSONField(default=dict, verbose_name='Información adicional')
    subtotal_12 = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Subtotal')
    subtotal_0 = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Subtotal 0%')
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor del descuento')
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Iva')
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor de iva')
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Total a pagar')
    cash = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Efectivo recibido')
    change = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Cambio')
    environment_type = models.PositiveIntegerField(choices=ENVIRONMENT_TYPE, default=ENVIRONMENT_TYPE[0][0])
    access_code = models.CharField(max_length=49, null=True, blank=True, verbose_name='Clave de acceso')
    authorization_date = models.DateField(null=True, blank=True, verbose_name='Fecha de emisión')
    xml_authorized = models.FileField(upload_to=CompanyPath('comprobantes/xml'), null=True, blank=True, verbose_name='XML Autorizado')
    pdf_authorized = models.FileField(upload_to=CompanyPath('comprobantes/pdf'), null=True, blank=True, verbose_name='PDF Autorizado')
    create_electronic_invoice = models.BooleanField(default=True, verbose_name='Crear factura electrónica')
    status = models.CharField(max_length=50, choices=INVOICE_STATUS, default=INVOICE_STATUS[0][0], verbose_name='Estado')
    # Emisión en dos fases (core/pos/emision.py): fecha y clave fijadas una vez y XML firmado guardado.
    emission_date = models.DateField(null=True, blank=True, verbose_name='Fecha de emisión (SRI)')
    xml_signed = models.TextField(null=True, blank=True, verbose_name='XML firmado')
    signed_at = models.DateTimeField(null=True, blank=True, verbose_name='Firmado el')
    sri_sent_at = models.DateTimeField(null=True, blank=True, verbose_name='Enviado al SRI el')

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return f'{self.voucher_number_full} / {self.client.get_full_name()})'

    def get_iva_percent(self):
        return int(self.iva * 100)

    def get_full_subtotal(self):
        return float(self.subtotal_0) + float(self.subtotal_12)

    def get_subtotal_without_taxes(self):
        return float(self.saledetail_set.filter().aggregate(result=Coalesce(Sum('subtotal'), 0.00, output_field=FloatField()))['result'])

    def get_authorization_date(self):
        if self.authorization_date is None:
            return 'Pendiente de autorización'
        return self.authorization_date.strftime('%Y-%m-%d')

    def get_date_joined(self):
        return (datetime.strptime(self.date_joined, '%Y-%m-%d') if isinstance(self.date_joined, str) else self.date_joined).strftime('%Y-%m-%d')

    def get_end_credit(self):
        return (datetime.strptime(self.end_credit, '%Y-%m-%d') if isinstance(self.end_credit, str) else self.end_credit).strftime('%Y-%m-%d')

    def get_xml_authorized(self):
        if self.xml_authorized:
            return f'{settings.MEDIA_URL}{self.xml_authorized}'
        return None

    def get_pdf_authorized(self):
        if self.pdf_authorized:
            return f'{settings.MEDIA_URL}{self.pdf_authorized}'
        return None

    def get_voucher_number_full(self):
        return f'{self.receipt.establishment_code}-{self.receipt.issuing_point_code}-{self.voucher_number}'

    def generate_voucher_number(self, increase=True):
        """increase=True reserva el próximo número (atómico); False solo muestra el último usado."""
        if increase:
            return self.receipt.reservar_numero()
        return f'{int(self.receipt.sequence):09d}'

    def generate_voucher_number_full(self):
        """Número del próximo documento, sin reservarlo (solo para mostrarlo)."""
        if self.receipt_id is not None:
            return self.receipt.next_number_full()
        from core.configuracion.servicios import secuencia_configurada
        self.company = require_company()
        receipt = secuencia_configurada(self.company, VOUCHER_TYPE[0][0])
        if receipt is None:
            return ''
        self.receipt = receipt
        return receipt.next_number_full()

    def ride_pdf(self):
        """RIDE A4 con la plantilla y los datos actuales, en memoria (no guarda nada)."""
        from core.comprobantes.ride import codigo_de_barras
        context = {'sale': self, 'access_code_barcode': codigo_de_barras(self.access_code)}
        return printer.create_pdf(context=context, template_name='sale/format/invoice.html')

    def generate_pdf_authorized(self):
        pdf_file = self.ride_pdf()
        with tempfile.NamedTemporaryFile(delete=True) as file_temp:
            file_temp.write(pdf_file)
            file_temp.flush()
            self.pdf_authorized.save(name=f'{self.receipt.get_name_xml()}_{self.access_code}.pdf', content=File(file_temp), save=False)

    def generate_xml(self):
        fecha_emision = self.emission_date or timezone.localdate()   # la misma fecha (de Ecuador) para la clave y fechaEmision
        access_key = self.access_code or SRI().create_access_key(self, fecha_emision)
        root = ElementTree.Element('factura', id="comprobante", version="1.0.0")
        # infoTributaria
        xml_tax_info = ElementTree.SubElement(root, 'infoTributaria')
        ElementTree.SubElement(xml_tax_info, 'ambiente').text = str(self.environment_type)
        ElementTree.SubElement(xml_tax_info, 'tipoEmision').text = str(self.company.emission_type)
        ElementTree.SubElement(xml_tax_info, 'razonSocial').text = self.company.business_name
        ElementTree.SubElement(xml_tax_info, 'nombreComercial').text = self.company.tradename
        ElementTree.SubElement(xml_tax_info, 'ruc').text = self.company.ruc
        ElementTree.SubElement(xml_tax_info, 'claveAcceso').text = access_key
        ElementTree.SubElement(xml_tax_info, 'codDoc').text = self.receipt.voucher_type
        ElementTree.SubElement(xml_tax_info, 'estab').text = self.receipt.establishment_code
        ElementTree.SubElement(xml_tax_info, 'ptoEmi').text = self.receipt.issuing_point_code
        ElementTree.SubElement(xml_tax_info, 'secuencial').text = self.voucher_number
        ElementTree.SubElement(xml_tax_info, 'dirMatriz').text = self.company.main_address
        info_tributaria_final(self.company, xml_tax_info)
        # infoFactura
        xml_info_invoice = ElementTree.SubElement(root, 'infoFactura')
        ElementTree.SubElement(xml_info_invoice, 'fechaEmision').text = fecha_emision.strftime('%d/%m/%Y')
        ElementTree.SubElement(xml_info_invoice, 'dirEstablecimiento').text = self.receipt.establishment_address() or self.company.establishment_address
        ElementTree.SubElement(xml_info_invoice, 'obligadoContabilidad').text = self.company.obligated_accounting
        ElementTree.SubElement(xml_info_invoice, 'tipoIdentificacionComprador').text = self.client.identification_type
        ElementTree.SubElement(xml_info_invoice, 'razonSocialComprador').text = self.client.user.names
        ElementTree.SubElement(xml_info_invoice, 'identificacionComprador').text = self.client.dni
        ElementTree.SubElement(xml_info_invoice, 'direccionComprador').text = self.client.address
        ElementTree.SubElement(xml_info_invoice, 'totalSinImpuestos').text = f'{self.get_full_subtotal():.2f}'
        ElementTree.SubElement(xml_info_invoice, 'totalDescuento').text = f'{self.total_dscto:.2f}'
        # totalConImpuestos: un totalImpuesto por tarifa de IVA de las líneas
        xml_total_con_impuestos(ElementTree.SubElement(xml_info_invoice, 'totalConImpuestos'), self.saledetail_set.select_related('product'))
        ElementTree.SubElement(xml_info_invoice, 'propina').text = '0.00'
        ElementTree.SubElement(xml_info_invoice, 'importeTotal').text = f'{self.total:.2f}'
        ElementTree.SubElement(xml_info_invoice, 'moneda').text = 'DOLAR'
        # pagos
        xml_payments = ElementTree.SubElement(xml_info_invoice, 'pagos')
        xml_payment = ElementTree.SubElement(xml_payments, 'pago')
        ElementTree.SubElement(xml_payment, 'formaPago').text = self.payment_method
        ElementTree.SubElement(xml_payment, 'total').text = f'{self.total:.2f}'
        ElementTree.SubElement(xml_payment, 'plazo').text = str(self.time_limit)
        ElementTree.SubElement(xml_payment, 'unidadTiempo').text = 'dias'
        # detalles
        xml_details = ElementTree.SubElement(root, 'detalles')
        for detail in self.saledetail_set.select_related('product'):
            xml_detail = ElementTree.SubElement(xml_details, 'detalle')
            ElementTree.SubElement(xml_detail, 'codigoPrincipal').text = detail.product.code
            ElementTree.SubElement(xml_detail, 'descripcion').text = detail.product.name
            ElementTree.SubElement(xml_detail, 'cantidad').text = f'{detail.cant:.2f}'
            ElementTree.SubElement(xml_detail, 'precioUnitario').text = f'{detail.price:.2f}'
            ElementTree.SubElement(xml_detail, 'descuento').text = f'{detail.total_dscto:.2f}'
            ElementTree.SubElement(xml_detail, 'precioTotalSinImpuesto').text = f'{detail.total:.2f}'
            xml_impuesto_de_linea(xml_detail, detail)
        # infoAdicional
        informacion_adicional(root, [(i.get('name'), i.get('value')) for i in (self.additional_info or [])])
        # Solo la declaración lleva comillas dobles: reemplazar todas las ' alteraba nombres como O'Brien.
        return '<?xml version="1.0" encoding="UTF-8"?>' + ElementTree.tostring(root, encoding='unicode'), access_key

    def is_invoice(self):
        return self.receipt.voucher_type == VOUCHER_TYPE[0][0]

    def toJSON(self):
        # El XML firmado no viaja al navegador (pesa y no hace falta); las fechas nuevas van como texto.
        item = model_to_dict(self, exclude=EXCLUIR_DEL_JSON)
        item['emission_date'] = self.emission_date.strftime('%Y-%m-%d') if self.emission_date else ''
        item['company'] = self.company.toJSON()
        item['client'] = self.client.toJSON()
        item['receipt'] = self.receipt.toJSON()
        item['employee'] = self.employee.toJSON()
        item['payment_type'] = {'id': self.payment_type, 'name': self.get_payment_type_display()}
        item['payment_method'] = {'id': self.payment_method, 'name': self.get_payment_method_display()}
        item['creation_date'] = self.creation_date.strftime('%Y-%m-%d %H:%M:%S')
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['end_credit'] = self.end_credit.strftime('%Y-%m-%d')
        item['subtotal_0'] = float(self.subtotal_0)
        item['subtotal_12'] = float(self.subtotal_12)
        item['subtotal'] = self.get_full_subtotal()
        item['total_dscto'] = float(self.total_dscto)
        item['iva'] = float(self.iva)
        item['total_iva'] = float(self.total_iva)
        item['total'] = float(self.total)
        item['cash'] = float(self.cash)
        item['change'] = float(self.change)
        item['environment_type'] = {'id': self.environment_type, 'name': self.get_environment_type_display()}
        item['authorization_date'] = '' if self.authorization_date is None else self.authorization_date.strftime('%Y-%m-%d')
        item['xml_authorized'] = self.get_xml_authorized()
        item['pdf_authorized'] = self.get_pdf_authorized()
        item['status'] = {'id': self.status, 'name': self.get_status_display()}
        return item

    def calculate_detail(self):
        """Cada línea con la tarifa de su producto, fijada al vender (cambiar el producto después no altera la factura)."""
        for detail in self.saledetail_set.select_related('product'):
            calcular_linea_iva(detail, detail.codigo_porcentaje or detail.product.tarifa_iva or ('4' if detail.product.with_tax else '0'))
            detail.save()

    def calculate_invoice(self):
        gravado, cero, iva, descuento = totales_de_lineas(self.saledetail_set.select_related('product'))
        self.subtotal_12, self.subtotal_0, self.total_iva, self.total_dscto = gravado, cero, iva, descuento
        self.total = gravado + cero + iva
        self.save()

    def impuestos_por_tarifa(self):
        return impuestos_por_tarifa(self.saledetail_set.select_related('product'))

    def edit(self):
        super(Sale, self).save()

    def save(self, force_insert=False, force_update=False, using=None,
             update_fields=None):
        nuevo = self.pk is None
        super(Sale, self).save()
        if nuevo:
            self.receipt.registrar_usado(self.voucher_number)

    def delete(self, using=None, keep_parents=False):
        # Todo o nada: el stock vuelve con F() (suma en la base, sin pisar otra venta a la vez) y, si algo falla (p. ej. la
        # cuenta por cobrar que protege a la venta), nada cambia. SaleDeleteView borra antes la CxC sin abonos.
        with transaction.atomic():
            for i in self.saledetail_set.filter(product__inventoried=True):
                Product.all_companies.filter(pk=i.product_id).update(stock=models.F('stock') + i.cant)
                i.delete()
            super(Sale, self).delete()

    def generate_electronic_invoice(self):
        # Envía el XML firmado guardado o consulta su autorización (core/pos/emision.py); el cupo se
        # reserva al enviar y solo se consume cuando el SRI autoriza (core/suscripciones/cupo.py).
        from core.pos import emision
        return emision.emitir(self)

    def get_ruc_proveedor(self):
        from core.pos.emision import ruc_proveedor
        return ruc_proveedor()

    def get_proveedor(self):
        from core.pos.emision import datos_proveedor
        return datos_proveedor()

    class Meta:
        verbose_name = 'Venta'
        verbose_name_plural = 'Ventas'
        constraints = [models.UniqueConstraint(fields=['receipt', 'voucher_number'], name='venta_numero_unico_por_secuencia')]
        default_permissions = ()
        permissions = (
            ('view_sale', 'Can view Venta'),
            ('add_sale', 'Can add Venta'),
            ('delete_sale', 'Can delete Venta'),
            ('view_sale_client', 'Can view_sale_client Venta'),
        )


class SaleDetail(TenantModel):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    cant = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    price_with_vat = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    subtotal = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    codigo_porcentaje = models.CharField(max_length=2, default='', blank=True, verbose_name='Tarifa de IVA (código)')

    def __str__(self):
        return self.product.name

    def get_iva_percent(self):
        return int(self.iva * 100)

    def toJSON(self, args=None):
        item = model_to_dict(self, exclude=['sale'])
        item['product'] = self.product.toJSON()
        item['price'] = float(self.price)
        item['price_with_vat'] = float(self.price_with_vat)
        item['subtotal'] = float(self.subtotal)
        item['iva'] = float(self.iva)
        item['total_iva'] = float(self.total_iva)
        item['codigo_porcentaje'] = codigo_de_linea(self)
        item['tarifa'] = float(PORCENTAJE_IVA.get(item['codigo_porcentaje'], 0))
        item['dscto'] = float(self.dscto) * 100
        item['total_dscto'] = float(self.total_dscto)
        item['total'] = float(self.total)
        if args is not None:
            item.update(args)
        return item

    class Meta:
        verbose_name = 'Detalle de Venta'
        verbose_name_plural = 'Detalle de Ventas'
        ordering = ('id',)   # las líneas en el orden en que se ingresaron (XML, RIDE y ticket)
        default_permissions = ()


class CtasCollect(TenantModel):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT)
    date_joined = models.DateField(default=datetime.now)
    end_date = models.DateField(default=datetime.now)
    debt = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    saldo = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    state = models.BooleanField(default=True)

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return f"{self.sale.client.user.names} ({self.sale.client.dni}) / {self.date_joined.strftime('%Y-%m-%d')} / ${f'{self.debt:.2f}'}"

    def validate_debt(self):
        try:
            saldo = self.paymentsctacollect_set.aggregate(result=Coalesce(Sum('valor'), 0.00, output_field=FloatField()))['result']
            self.saldo = float(self.debt) - float(saldo)
            self.state = self.saldo > 0.00
            self.save()
        except:
            pass

    def toJSON(self):
        item = model_to_dict(self)
        item['sale'] = self.sale.toJSON()
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['end_date'] = self.end_date.strftime('%Y-%m-%d')
        item['debt'] = float(self.debt)
        item['saldo'] = float(self.saldo)
        return item

    class Meta:
        verbose_name = 'Cuenta por cobrar'
        verbose_name_plural = 'Cuentas por cobrar'
        default_permissions = ()
        permissions = (
            ('view_ctas_collect', 'Can view Cuenta por cobrar'),
            ('add_ctas_collect', 'Can add Cuenta por cobrar'),
            ('delete_ctas_collect', 'Can delete Cuenta por cobrar'),
        )


class PaymentsCtaCollect(TenantModel):
    ctas_collect = models.ForeignKey(CtasCollect, on_delete=models.CASCADE, verbose_name='Cuenta por cobrar')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de registro')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Detalles')
    valor = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor')

    def __str__(self):
        return self.ctas_collect.id

    def toJSON(self):
        item = model_to_dict(self, exclude=['ctas_collect'])
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['valor'] = float(self.valor)
        return item

    def save(self, force_insert=False, force_update=False, using=None,
             update_fields=None):
        if self.description is None:
            self.description = 's/n'
        elif len(self.description) == 0:
            self.description = 's/n'
        super(PaymentsCtaCollect, self).save()

    class Meta:
        verbose_name = 'Pago Cuenta por cobrar'
        verbose_name_plural = 'Pagos Cuentas por cobrar'
        default_permissions = ()


class DebtsPay(TenantModel):
    """Cuenta por pagar de una compra a crédito. saldo = deuda − pagos − abonos (retenciones emitidas autorizadas y notas de
    crédito del proveedor), calculado en Decimal. Las cuentas anteriores a la Etapa 2 (base «subtotal», sin IVA) nunca
    reciben abonos automáticos ni cambian de saldo salvo por sus pagos (DC6)."""
    BASES_CALCULO = (('subtotal', 'Subtotal sin IVA (sin abonos automáticos)'), ('total', 'Total con IVA'))

    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT)
    date_joined = models.DateField(default=datetime.now)
    end_date = models.DateField(default=datetime.now)
    debt = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    saldo = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    state = models.BooleanField(default=True)
    # Falla cerrado (DC2): solo compras.crear_compra escribe 'total'.
    base_calculo = models.CharField(max_length=10, choices=BASES_CALCULO, default='subtotal', verbose_name='Base de cálculo')

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return f"{self.purchase.provider.name} ({self.purchase.numero_comprobante}) / {self.date_joined.strftime('%Y-%m-%d')} / ${f'{self.debt:.2f}'}"

    def abonos(self):
        """[{tipo, id, numero, fecha, valor}] que descuentan del saldo: retenciones emitidas que cuentan (la regla vive solo en
        retenciones.retenciones_autorizadas) y notas de crédito del proveedor sobre la compra. Vacío con base «subtotal»."""
        if self.base_calculo != 'total':
            return []
        from core.comprobantes.retenciones import retenciones_autorizadas
        abonos = [{'tipo': 'retencion', 'id': r.pk, 'numero': r.voucher_number_full,
                   'fecha': (r.emission_date or r.date_joined).isoformat(), 'valor': Decimal(r.total_retenido)}
                  for r in retenciones_autorizadas(self.purchase).order_by('id')]
        notas = Purchase.all_companies.filter(company_id=self.company_id, compra_modificada_id=self.purchase_id,
                                              tipo_comprobante='04', total__isnull=False).order_by('id')
        abonos += [{'tipo': 'nota_credito', 'id': n.pk, 'numero': n.numero_comprobante,
                    'fecha': (n.fecha_emision or n.date_joined).isoformat(), 'valor': Decimal(n.total)} for n in notas]
        return abonos

    def pagado(self):
        return Decimal(PaymentsDebtsPay.all_companies.filter(debts_pay_id=self.pk).aggregate(
            r=Coalesce(Sum('valor'), Decimal('0'), output_field=models.DecimalField()))['r']).quantize(CENTAVO)

    def recalcular(self, guardar=True):
        """saldo = deuda − pagos − abonos, en Decimal a 0,01; state = saldo > 0. Devuelve el saldo."""
        abonado = sum((a['valor'] for a in self.abonos()), Decimal('0'))
        saldo = (Decimal(self.debt) - self.pagado() - abonado).quantize(CENTAVO, ROUND_HALF_UP)
        self.saldo, self.state = saldo, saldo > 0
        if guardar:
            DebtsPay.all_companies.filter(pk=self.pk).update(saldo=saldo, state=self.state)
        return saldo

    def validate_debt(self):
        """Alias de recalcular() para las vistas anteriores."""
        return self.recalcular()

    def toJSON(self, detalle=False):
        """Sin consultas por fila si la vista anota `pagado` (con_pagado) y hace select_related('purchase__provider'):
        abonado = deuda − pagado − saldo (el saldo guardado ya descuenta los abonos). Con detalle=True recalcula los abonos."""
        item = {'id': self.pk, 'purchase': self.purchase.toJSON(), 'date_joined': self.date_joined.strftime('%Y-%m-%d'),
                'end_date': self.end_date.strftime('%Y-%m-%d'), 'debt': float(self.debt), 'saldo': float(self.saldo),
                'state': self.state, 'base_calculo': {'id': self.base_calculo, 'name': self.get_base_calculo_display()}}
        pagado = self.__dict__.get('pagado_anotado')
        pagado = Decimal(pagado).quantize(CENTAVO) if pagado is not None else self.pagado()
        if detalle:
            abonos = self.abonos()
            abonado = sum((a['valor'] for a in abonos), Decimal('0'))
            item['abonos'] = [{**a, 'valor': f"{a['valor']:.2f}"} for a in abonos]
        else:
            abonado = Decimal(self.debt) - pagado - Decimal(self.saldo)
        item.update({'pagado': f'{pagado:.2f}', 'abonado': f'{abonado:.2f}', 'saldo_a_favor': Decimal(self.saldo) < 0})
        return item

    @staticmethod
    def con_pagado(queryset):
        """Anota `pagado_anotado` (suma de los pagos) con una subconsulta: el listado no consulta por fila."""
        from django.db.models import OuterRef, Subquery
        suma = (PaymentsDebtsPay.all_companies.filter(debts_pay_id=OuterRef('pk')).order_by()
                .values('debts_pay_id').annotate(s=Sum('valor')).values('s'))
        return queryset.annotate(pagado_anotado=Coalesce(Subquery(suma, output_field=models.DecimalField()), Decimal('0'),
                                                         output_field=models.DecimalField()))

    class Meta:
        verbose_name = 'Cuenta por pagar'
        verbose_name_plural = 'Cuentas por pagar'
        default_permissions = ()
        permissions = (
            ('view_debts_pay', 'Can view Cuenta por pagar'),
            ('add_debts_pay', 'Can add Cuenta por pagar'),
            ('delete_debts_pay', 'Can delete Cuenta por pagar'),
        )


class PaymentsDebtsPay(TenantModel):
    debts_pay = models.ForeignKey(DebtsPay, on_delete=models.CASCADE, verbose_name='Cuenta por pagar')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de registro')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Detalles')
    valor = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor')
    # Medio del movimiento de tesorería (MEDIOS_DE_PAGO, B0; el mismo de cobros y gastos). '' = sin dato (pagos anteriores).
    medio_pago = models.CharField(max_length=15, choices=MEDIOS_DE_PAGO, blank=True, default='', verbose_name='Medio de pago')
    referencia = models.CharField(max_length=100, blank=True, default='',
                                  verbose_name='Referencia (n.º de transferencia, cheque o comprobante)')
    registrado_por = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', editable=False,
                                       verbose_name='Registrado por')
    registrado_en = models.DateTimeField(null=True, blank=True, editable=False, verbose_name='Registrado el')

    def __str__(self):
        return f'Pago {self.pk} de la cuenta {self.debts_pay_id}'

    def toJSON(self):
        item = model_to_dict(self, exclude=['debts_pay'])
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['valor'] = float(self.valor)
        item['medio_pago'] = {'id': self.medio_pago, 'name': self.get_medio_pago_display() if self.medio_pago else 'Sin dato'}
        return item

    def save(self, force_insert=False, force_update=False, using=None,
             update_fields=None):
        if self.description is None:
            self.description = 's/n'
        elif len(self.description) == 0:
            self.description = 's/n'
        super(PaymentsDebtsPay, self).save()

    class Meta:
        verbose_name = 'Det. Cuenta por pagar'
        verbose_name_plural = 'Det. Cuentas por pagar'
        default_permissions = ()
        ordering = ('id',)


class TypeExpense(TenantModel):
    name = models.CharField(max_length=50, verbose_name='Nombre')
    cuenta_contable = models.CharField(max_length=30, blank=True, default='', verbose_name='Cuenta contable')
    # Sin valor de oficio (DC12): la empresa lo elige; compras.sustento_gasto_sugerido solo se muestra como sugerencia.
    cod_sustento = models.CharField(max_length=2, choices=SUSTENTOS, blank=True, default='',
                                    verbose_name='Sustento tributario del tipo de gasto')

    def __str__(self):
        return self.name

    def toJSON(self):
        item = model_to_dict(self)
        item['nombre_sustento'] = self.get_cod_sustento_display() if self.cod_sustento else 'Sin indicar'
        return item

    class Meta:
        constraints = [models.UniqueConstraint(fields=['company', 'name'], name='typeexpense_name_por_empresa')]
        verbose_name = 'Tipo de Gasto'
        verbose_name_plural = 'Tipos de Gastos'
        default_permissions = ()
        permissions = (
            ('view_type_expense', 'Can view Tipo de Gasto'),
            ('add_type_expense', 'Can add Tipo de Gasto'),
            ('change_type_expense', 'Can change Tipo de Gasto'),
            ('delete_type_expense', 'Can delete Tipo de Gasto'),
        )


class Expenses(TenantModel):
    """Gasto sin comprobante. Con factura, el gasto se registra en Compras (compra de gasto)."""
    type_expense = models.ForeignKey(TypeExpense, on_delete=models.PROTECT, verbose_name='Tipo de Gasto')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Descripción')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de Registro')
    valor = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor')
    medio_pago = models.CharField(max_length=15, choices=MEDIOS_DE_PAGO, blank=True, default='', verbose_name='Medio de pago')
    referencia = models.CharField(max_length=100, blank=True, default='',
                                  verbose_name='Referencia (n.º de transferencia, cheque o comprobante)')

    def __str__(self):
        return self.description

    def toJSON(self):
        item = model_to_dict(self)
        item['type_expense'] = self.type_expense.toJSON()
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['valor'] = float(self.valor)
        item['medio_pago'] = {'id': self.medio_pago, 'name': self.get_medio_pago_display() if self.medio_pago else 'Sin dato'}
        return item

    def save(self, force_insert=False, force_update=False, using=None,
             update_fields=None):
        if self.description is None:
            self.description = 's/n'
        elif len(self.description) == 0:
            self.description = 's/n'
        super(Expenses, self).save()

    class Meta:
        verbose_name = 'Gasto'
        verbose_name_plural = 'Gastos'


class Promotions(TenantModel):
    start_date = models.DateField(default=datetime.now)
    end_date = models.DateField(default=datetime.now)
    state = models.BooleanField(default=True)

    def __str__(self):
        return str(self.id)

    def toJSON(self):
        item = model_to_dict(self)
        item['start_date'] = self.start_date.strftime('%Y-%m-%d')
        item['end_date'] = self.end_date.strftime('%Y-%m-%d')
        return item

    class Meta:
        verbose_name = 'Promoción'
        verbose_name_plural = 'Promociones'


class PromotionsDetail(TenantModel):
    promotion = models.ForeignKey(Promotions, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    price_current = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    price_final = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)

    def __str__(self):
        return self.product.name

    def get_dscto_real(self):
        total_dscto = float(self.price_current) * float(self.dscto)
        n = 2
        return math.floor(total_dscto * 10 ** n) / 10 ** n

    def toJSON(self):
        item = model_to_dict(self, exclude=['promotion'])
        item['product'] = self.product.toJSON()
        item['price_current'] = float(self.price_current)
        item['dscto'] = float(self.dscto)
        item['total_dscto'] = float(self.total_dscto)
        item['price_final'] = float(self.price_final)
        return item

    class Meta:
        verbose_name = 'Detalle Promoción'
        verbose_name_plural = 'Detalle de Promociones'
        default_permissions = ()


class VoucherErrors(TenantModel):
    date_joined = models.DateField(default=datetime.now)
    datetime_joined = models.DateTimeField(default=datetime.now)
    environment_type = models.PositiveIntegerField(choices=ENVIRONMENT_TYPE, default=ENVIRONMENT_TYPE[0][0])
    reference = models.CharField(max_length=20)
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE)
    stage = models.CharField(max_length=20, choices=VOUCHER_STAGE, default=VOUCHER_STAGE[0][0])
    errors = models.JSONField(default=dict)

    def __str__(self):
        return self.stage

    def toJSON(self):
        item = model_to_dict(self)
        item['receipt'] = self.receipt.toJSON()
        item['environment_type'] = {'id': self.environment_type, 'name': self.get_environment_type_display()}
        item['stage'] = {'id': self.stage, 'name': self.get_stage_display()}
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['datetime_joined'] = self.datetime_joined.strftime('%Y-%m-%d %H:%M')
        return item

    class Meta:
        verbose_name = 'Errores del Comprobante'
        verbose_name_plural = 'Errores de los Comprobantes'
        default_permissions = ()
        permissions = (
            ('view_voucher_errors', 'Can view Errores del Comprobante'),
            ('delete_voucher_errors', 'Can delete Errores del Comprobante'),
        )


class CreditNote(TenantModel):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, verbose_name='Venta')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de registro')
    motive = models.CharField(max_length=300, null=True, blank=True, verbose_name='Motivo')
    receipt = models.ForeignKey(Receipt, on_delete=models.PROTECT, verbose_name='Tipo de comprobante')
    voucher_number = models.CharField(max_length=9, verbose_name='Número de comprobante')
    voucher_number_full = models.CharField(max_length=20, verbose_name='Número de comprobante completo')
    subtotal_12 = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Subtotal')
    subtotal_0 = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Subtotal 0%')
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor del descuento')
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Iva')
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor de iva')
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Total a pagar')
    environment_type = models.PositiveIntegerField(choices=ENVIRONMENT_TYPE, default=ENVIRONMENT_TYPE[0][0])
    access_code = models.CharField(max_length=49, null=True, blank=True, verbose_name='Clave de acceso')
    authorization_date = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de autorización')
    xml_authorized = models.FileField(upload_to=CompanyPath('comprobantes/xml'), null=True, blank=True, verbose_name='XML Autorizado')
    pdf_authorized = models.FileField(upload_to=CompanyPath('comprobantes/pdf'), null=True, blank=True, verbose_name='PDF Autorizado')
    create_electronic_invoice = models.BooleanField(default=True, verbose_name='Crear factura electrónica')
    status = models.CharField(max_length=50, choices=INVOICE_STATUS, default=INVOICE_STATUS[0][0], verbose_name='Estado')
    # Emisión en dos fases (core/pos/emision.py): fecha y clave fijadas una vez y XML firmado guardado.
    emission_date = models.DateField(null=True, blank=True, verbose_name='Fecha de emisión (SRI)')
    xml_signed = models.TextField(null=True, blank=True, verbose_name='XML firmado')
    signed_at = models.DateTimeField(null=True, blank=True, verbose_name='Firmado el')
    sri_sent_at = models.DateTimeField(null=True, blank=True, verbose_name='Enviado al SRI el')

    def __str__(self):
        return self.motive

    def get_iva_percent(self):
        return int(self.iva * 100)

    def get_full_subtotal(self):
        return float(self.subtotal_0) + float(self.subtotal_12)

    def get_subtotal_without_taxes(self):
        return float(self.creditnotedetail_set.filter().aggregate(result=Coalesce(Sum('subtotal'), 0.00, output_field=FloatField()))['result'])

    def get_authorization_date(self):
        if self.authorization_date is None:
            return 'Pendiente de autorización'
        return self.authorization_date.strftime('%Y-%m-%d %H:%M:%S')

    def get_date_joined(self):
        return (datetime.strptime(self.date_joined, '%Y-%m-%d') if isinstance(self.date_joined, str) else self.date_joined).strftime('%Y-%m-%d')

    def get_xml_authorized(self):
        if self.xml_authorized:
            return f'{settings.MEDIA_URL}{self.xml_authorized}'
        return None

    def get_pdf_authorized(self):
        if self.pdf_authorized:
            return f'{settings.MEDIA_URL}{self.pdf_authorized}'
        return None

    def get_voucher_number_full(self):
        return f'{self.receipt.establishment_code}-{self.receipt.issuing_point_code}-{self.voucher_number}'

    def generate_voucher_number(self):
        """Reserva el próximo número de nota de crédito (atómico)."""
        return self.receipt.reservar_numero()

    def generate_voucher_number_full(self):
        """Número de la próxima nota de crédito, sin reservarlo (solo para mostrarlo)."""
        from core.configuracion.servicios import secuencia_configurada
        self.company = require_company()
        receipt = secuencia_configurada(self.company, VOUCHER_TYPE[1][0])
        if receipt is None:
            return ''
        self.receipt = receipt
        return receipt.next_number_full()

    def generate_pdf_authorized(self):
        from core.comprobantes.ride import codigo_de_barras
        context = {'credit_note': self, 'access_code_barcode': codigo_de_barras(self.access_code)}
        pdf_file = printer.create_pdf(context=context, template_name='credit_note/format/invoice.html')
        with tempfile.NamedTemporaryFile(delete=True) as file_temp:
            file_temp.write(pdf_file)
            file_temp.flush()
            self.pdf_authorized.save(name=f'{self.receipt.get_name_xml()}_{self.access_code}.pdf', content=File(file_temp), save=False)

    def generate_xml(self):
        fecha_emision = self.emission_date or timezone.localdate()   # la misma fecha (de Ecuador) para la clave y fechaEmision
        access_key = self.access_code or SRI().create_access_key(self, fecha_emision)
        root = ElementTree.Element('notaCredito', id="comprobante", version="1.1.0")
        # infoTributaria
        xml_tax_info = ElementTree.SubElement(root, 'infoTributaria')
        ElementTree.SubElement(xml_tax_info, 'ambiente').text = str(self.environment_type)
        ElementTree.SubElement(xml_tax_info, 'tipoEmision').text = str(self.company.emission_type)
        ElementTree.SubElement(xml_tax_info, 'razonSocial').text = self.company.business_name
        ElementTree.SubElement(xml_tax_info, 'nombreComercial').text = self.company.tradename
        ElementTree.SubElement(xml_tax_info, 'ruc').text = self.company.ruc
        ElementTree.SubElement(xml_tax_info, 'claveAcceso').text = access_key
        ElementTree.SubElement(xml_tax_info, 'codDoc').text = self.receipt.voucher_type
        ElementTree.SubElement(xml_tax_info, 'estab').text = self.receipt.establishment_code
        ElementTree.SubElement(xml_tax_info, 'ptoEmi').text = self.receipt.issuing_point_code
        ElementTree.SubElement(xml_tax_info, 'secuencial').text = self.voucher_number
        ElementTree.SubElement(xml_tax_info, 'dirMatriz').text = self.company.main_address
        info_tributaria_final(self.company, xml_tax_info)
        # infoNotaCredito
        xml_info_invoice = ElementTree.SubElement(root, 'infoNotaCredito')
        ElementTree.SubElement(xml_info_invoice, 'fechaEmision').text = fecha_emision.strftime('%d/%m/%Y')
        ElementTree.SubElement(xml_info_invoice, 'dirEstablecimiento').text = self.receipt.establishment_address() or self.company.establishment_address
        ElementTree.SubElement(xml_info_invoice, 'tipoIdentificacionComprador').text = self.sale.client.identification_type
        ElementTree.SubElement(xml_info_invoice, 'razonSocialComprador').text = self.sale.client.user.names
        ElementTree.SubElement(xml_info_invoice, 'identificacionComprador').text = self.sale.client.dni
        if not self.company.special_taxpayer == '000':
            ElementTree.SubElement(xml_info_invoice, 'contribuyenteEspecial').text = self.company.special_taxpayer
        ElementTree.SubElement(xml_info_invoice, 'obligadoContabilidad').text = self.company.obligated_accounting
        ElementTree.SubElement(xml_info_invoice, 'codDocModificado').text = self.sale.receipt.voucher_type
        ElementTree.SubElement(xml_info_invoice, 'numDocModificado').text = self.sale.voucher_number_full
        ElementTree.SubElement(xml_info_invoice, 'fechaEmisionDocSustento').text = self.sale.date_joined.strftime('%d/%m/%Y')
        ElementTree.SubElement(xml_info_invoice, 'totalSinImpuestos').text = f'{self.get_full_subtotal():.2f}'
        ElementTree.SubElement(xml_info_invoice, 'valorModificacion').text = f'{self.total:.2f}'
        ElementTree.SubElement(xml_info_invoice, 'moneda').text = 'DOLAR'
        # totalConImpuestos: un totalImpuesto por tarifa de IVA de las líneas
        xml_total_con_impuestos(ElementTree.SubElement(xml_info_invoice, 'totalConImpuestos'), self.creditnotedetail_set.select_related('product'))
        ElementTree.SubElement(xml_info_invoice, 'motivo').text = self.motive
        # detalles
        xml_details = ElementTree.SubElement(root, 'detalles')
        for detail in self.creditnotedetail_set.select_related('product', 'sale_detail__product'):
            xml_detail = ElementTree.SubElement(xml_details, 'detalle')
            ElementTree.SubElement(xml_detail, 'codigoInterno').text = detail.product.code
            ElementTree.SubElement(xml_detail, 'descripcion').text = detail.product.name
            ElementTree.SubElement(xml_detail, 'cantidad').text = f'{detail.cant:.2f}'
            ElementTree.SubElement(xml_detail, 'precioUnitario').text = f'{detail.price:.2f}'
            ElementTree.SubElement(xml_detail, 'descuento').text = f'{detail.total_dscto:.2f}'
            ElementTree.SubElement(xml_detail, 'precioTotalSinImpuesto').text = f'{detail.total:.2f}'
            xml_impuesto_de_linea(xml_detail, detail)
        # infoAdicional
        informacion_adicional(root, [('dirCliente', self.sale.client.address), ('telfCliente', self.sale.client.mobile),
                                     ('Observacion', f'NOTA_CREDITO # {self.voucher_number}')])
        return '<?xml version="1.0" encoding="UTF-8"?>' + ElementTree.tostring(root, encoding='unicode'), access_key

    def toJSON(self):
        item = model_to_dict(self, exclude=EXCLUIR_DEL_JSON)
        item['emission_date'] = self.emission_date.strftime('%Y-%m-%d') if self.emission_date else ''
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['sale'] = self.sale.toJSON()
        item['company'] = self.company.toJSON()
        item['receipt'] = self.receipt.toJSON()
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['subtotal_12'] = float(self.subtotal_12)
        item['subtotal_0'] = float(self.subtotal_0)
        item['subtotal'] = self.get_full_subtotal()
        item['total_dscto'] = float(self.total_dscto)
        item['iva'] = float(self.iva)
        item['total_iva'] = float(self.total_iva)
        item['total'] = float(self.total)
        item['environment_type'] = {'id': self.environment_type, 'name': self.get_environment_type_display()}
        item['invoice'] = self.get_voucher_number_full()
        item['authorization_date'] = '' if self.authorization_date is None else self.authorization_date.strftime('%Y-%m-%d')
        item['xml_authorized'] = self.get_xml_authorized()
        item['pdf_authorized'] = self.get_pdf_authorized()
        item['status'] = {'id': self.status, 'name': self.get_status_display()}
        return item

    def generate_electronic_invoice(self):
        from core.pos import emision
        return emision.emitir(self)

    def get_ruc_proveedor(self):
        from core.pos.emision import ruc_proveedor
        return ruc_proveedor()

    def get_proveedor(self):
        from core.pos.emision import datos_proveedor
        return datos_proveedor()

    def calculate_detail(self):
        """Cada línea con la tarifa de la línea de la factura que acredita (no la del producto hoy)."""
        for detail in self.creditnotedetail_set.select_related('product', 'sale_detail__product'):
            calcular_linea_iva(detail, detail.codigo_porcentaje or codigo_de_linea(detail.sale_detail))
            detail.save()

    def calculate_invoice(self):
        gravado, cero, iva, descuento = totales_de_lineas(self.creditnotedetail_set.select_related('product'))
        self.subtotal_12, self.subtotal_0, self.total_iva, self.total_dscto = gravado, cero, iva, descuento
        self.total = gravado + cero + iva
        self.save()

    def impuestos_por_tarifa(self):
        return impuestos_por_tarifa(self.creditnotedetail_set.select_related('product'))

    def edit(self):
        super(CreditNote, self).save()

    def save(self, force_insert=False, force_update=False, using=None,
             update_fields=None):
        if self.motive is None:
            self.motive = 'Sin detalles'
        nuevo = self.pk is None
        super(CreditNote, self).save()
        if nuevo:
            self.receipt.registrar_usado(self.voucher_number)

    def delete(self, using=None, keep_parents=False):
        try:
            for i in self.creditnotedetail_set.filter(product__inventoried=True):
                i.product.stock -= i.cant
                i.product.save()
                i.delete()
        except:
            pass
        super(CreditNote, self).delete()

    class Meta:
        verbose_name = 'Nota de Credito'
        verbose_name_plural = 'Notas de Credito'
        constraints = [models.UniqueConstraint(fields=['receipt', 'voucher_number'], name='nota_numero_unico_por_secuencia')]
        default_permissions = ()
        permissions = (
            ('view_credit_note', 'Can view Nota de Credito'),
            ('add_credit_note', 'Can add Nota de Credito'),
            ('delete_credit_note', 'Can delete Nota de Credito'),
            ('view_credit_note_client', 'Can view_credit_note_client Nota de Credito'),
        )


class CreditNoteDetail(TenantModel):
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE)
    sale_detail = models.ForeignKey(SaleDetail, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, blank=True, null=True, on_delete=models.PROTECT)
    date_joined = models.DateField(default=datetime.now)
    cant = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    price_with_vat = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    subtotal = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    codigo_porcentaje = models.CharField(max_length=2, default='', blank=True, verbose_name='Tarifa de IVA (código)')

    def __str__(self):
        return self.product.name

    def toJSON(self):
        item = model_to_dict(self)
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['sale_detail'] = self.sale_detail.toJSON()
        item['product'] = self.product.toJSON()
        item['price'] = float(self.price)
        item['price_with_vat'] = float(self.price_with_vat)
        item['subtotal'] = float(self.subtotal)
        item['iva'] = float(self.iva)
        item['total_iva'] = float(self.total_iva)
        item['codigo_porcentaje'] = codigo_de_linea(self)
        item['tarifa'] = float(PORCENTAJE_IVA.get(item['codigo_porcentaje'], 0))
        item['dscto'] = float(self.dscto)
        item['total_dscto'] = float(self.total_dscto)
        item['total'] = float(self.total)
        return item

    class Meta:
        verbose_name = 'Detalle Devolución Ventas'
        verbose_name_plural = 'Detalle Devoluciones Ventas'
        ordering = ('id',)   # las líneas en el orden en que se ingresaron (XML, RIDE y ticket)
        default_permissions = ()
