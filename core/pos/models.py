import base64
import math
import tempfile
import time
import unicodedata
from datetime import datetime
from io import BytesIO
from xml.etree import ElementTree

import barcode
from barcode import writer
from django.contrib.contenttypes.models import ContentType
from django.core.files import File
from django.core.files.base import ContentFile
from django.db import models
from django.db.models import FloatField
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.forms import model_to_dict

from config import settings
from core.pos.choices import *
from core.pos.utilities import printer
from core.pos.utilities.sri import SRI
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
    image = models.ImageField(null=True, blank=True, upload_to='company/%Y/%m/%d', verbose_name='Logotipo de la empresa')
    environment_type = models.PositiveIntegerField(choices=ENVIRONMENT_TYPE, default=1, verbose_name='Tipo de Ambiente')
    emission_type = models.PositiveIntegerField(choices=EMISSION_TYPE, default=1, verbose_name='Tipo de Emisión')
    retention_agent = models.CharField(max_length=2, choices=RETENTION_AGENT, default=RETENTION_AGENT[1][0], verbose_name='Agente de Retención')
    mobile = models.CharField(max_length=10, verbose_name='Teléfono celular')
    phone = models.CharField(max_length=9, verbose_name='Teléfono convencional')
    email = models.CharField(max_length=50, verbose_name='Email')
    website = models.CharField(max_length=250, verbose_name='Dirección de página web')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Descripción')
    iva = models.DecimalField(default=0.00, decimal_places=2, max_digits=9, verbose_name='IVA')
    vat_percentage = models.IntegerField(choices=VAT_PERCENTAGE, default=VAT_PERCENTAGE[3][0], verbose_name='Porcentaje del IVA')
    electronic_signature = models.FileField(null=True, blank=True, upload_to='company/%Y/%m/%d', verbose_name='Firma electrónica (Archivo P12)')
    electronic_signature_key = models.CharField(max_length=100, verbose_name='Clave de firma electrónica')
    email_host = models.CharField(max_length=30, default='smtp.gmail.com', verbose_name='Servidor de correo')
    email_port = models.IntegerField(default=587, verbose_name='Puerto del servidor de correo')
    email_host_user = models.CharField(max_length=100, verbose_name='Username del servidor de correo')
    email_host_password = models.CharField(max_length=30, verbose_name='Password del servidor de correo')

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

    def toJSON(self):
        item = model_to_dict(self)
        item['image'] = self.get_image()
        item['electronic_signature'] = self.get_electronic_signature()
        item['iva'] = float(self.iva)
        return item

    class Meta:
        verbose_name = 'Empresa'
        verbose_name_plural = 'Empresas'
        default_permissions = ()
        permissions = (
            ('change_company', 'Can change Empresa'),
        )


class Provider(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name='Razón Social')
    ruc = models.CharField(max_length=13, unique=True, verbose_name='Número de RUC')
    mobile = models.CharField(max_length=10, unique=True, verbose_name='Teléfono celular')
    email = models.CharField(max_length=50, unique=True, verbose_name='Email')
    address = models.CharField(max_length=500, null=True, blank=True, verbose_name='Dirección')

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return f'{self.name} ({self.ruc})'

    def toJSON(self):
        item = model_to_dict(self)
        item['text'] = self.get_full_name()
        return item

    class Meta:
        verbose_name = 'Proveedor'
        verbose_name_plural = 'Proveedores'


class Category(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name='Nombre')

    def __str__(self):
        return self.name

    def toJSON(self):
        item = model_to_dict(self)
        return item

    class Meta:
        verbose_name = 'Categoria'
        verbose_name_plural = 'Categorias'


class Product(models.Model):
    name = models.CharField(max_length=150, verbose_name='Nombre')
    code = models.CharField(max_length=20, unique=True, verbose_name='Código')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Descripción')
    category = models.ForeignKey(Category, on_delete=models.PROTECT, verbose_name='Categoría')
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Precio de Compra')
    pvp = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Precio de Venta')
    image = models.ImageField(upload_to='product/%Y/%m/%d', null=True, blank=True, verbose_name='Imagen')
    barcode = models.ImageField(upload_to='barcode/%Y/%m/%d', null=True, blank=True, verbose_name='Código de barra')
    inventoried = models.BooleanField(default=True, verbose_name='¿Es inventariado?')
    stock = models.IntegerField(default=0)
    with_tax = models.BooleanField(default=True, verbose_name='¿Se cobra impuesto?')

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
        return item

    def save(self, force_insert=False, force_update=False, using=None,
             update_fields=None):
        self.generate_barcode()
        super(Product, self).save()

    class Meta:
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


class Purchase(models.Model):
    number = models.CharField(max_length=8, unique=True, verbose_name='Número de factura')
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, verbose_name='Proveedor')
    payment_type = models.CharField(choices=PAYMENT_TYPE, max_length=50, default=PAYMENT_TYPE[0][0], verbose_name='Tipo de pago')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de registro')
    end_credit = models.DateField(default=datetime.now, verbose_name='Fecha de plazo de credito')
    subtotal = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)

    def __str__(self):
        return self.provider.name

    def calculate_invoice(self):
        subtotal = 0.00
        for i in self.purchasedetail_set.all():
            subtotal += float(i.price) * int(i.cant)
        self.subtotal = subtotal
        self.save()

    def delete(self, using=None, keep_parents=False):
        try:
            for i in self.purchasedetail_set.all():
                i.product.stock -= i.cant
                i.product.save()
                i.delete()
        except:
            pass
        super(Purchase, self).delete()

    def toJSON(self):
        item = model_to_dict(self)
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['end_credit'] = self.end_credit.strftime('%Y-%m-%d')
        item['provider'] = self.provider.toJSON()
        item['payment_type'] = {'id': self.payment_type, 'name': self.get_payment_type_display()}
        item['subtotal'] = float(self.subtotal)
        return item

    class Meta:
        verbose_name = 'Compra'
        verbose_name_plural = 'Compras'
        default_permissions = ()
        permissions = (
            ('view_purchase', 'Can view Compra'),
            ('add_purchase', 'Can add Compra'),
            ('delete_purchase', 'Can delete Compra'),
        )


class PurchaseDetail(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    cant = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    subtotal = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)

    def __str__(self):
        return self.product.name

    def toJSON(self):
        item = model_to_dict(self, exclude=['purchase'])
        item['product'] = self.product.toJSON()
        item['price'] = float(self.price)
        item['dscto'] = float(self.dscto)
        item['subtotal'] = float(self.subtotal)
        return item

    class Meta:
        verbose_name = 'Detalle de Compra'
        verbose_name_plural = 'Detalle de Compras'
        default_permissions = ()


class Client(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    dni = models.CharField(max_length=13, unique=True, verbose_name='Número de cedula o ruc')
    mobile = models.CharField(max_length=10, unique=True, verbose_name='Teléfono')
    birthdate = models.DateField(default=datetime.now, verbose_name='Fecha de nacimiento')
    address = models.CharField(max_length=500, verbose_name='Dirección')
    identification_type = models.CharField(max_length=30, choices=IDENTIFICATION_TYPE, default=IDENTIFICATION_TYPE[0][0], verbose_name='Tipo de identificación')
    send_email_invoice = models.BooleanField(default=True, verbose_name='¿Enviar email de factura?')

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return f'{self.user.names} ({self.dni})'

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
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'


class Receipt(models.Model):
    voucher_type = models.CharField(max_length=10, choices=VOUCHER_TYPE, verbose_name='Tipo de Comprobante')
    establishment_code = models.CharField(max_length=3, verbose_name='Código del Establecimiento Emisor')
    issuing_point_code = models.CharField(max_length=3, verbose_name='Código del Punto de Emisión')
    sequence = models.PositiveIntegerField(default=1, verbose_name='Secuencia actual')

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

    def toJSON(self):
        item = model_to_dict(self)
        item['name'] = self.name
        item['voucher_type'] = {'id': self.voucher_type, 'name': self.get_voucher_type_display()}
        return item

    class Meta:
        verbose_name = 'Comprobante'
        verbose_name_plural = 'Comprobantes'


class Sale(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT, verbose_name='Compañia')
    client = models.ForeignKey(Client, on_delete=models.PROTECT, verbose_name='Cliente')
    receipt = models.ForeignKey(Receipt, on_delete=models.PROTECT, limit_choices_to={'voucher_type__in': [VOUCHER_TYPE[0][0], VOUCHER_TYPE[-1][0]]}, verbose_name='Tipo de comprobante')
    voucher_number = models.CharField(max_length=9, verbose_name='Número de comprobante')
    voucher_number_full = models.CharField(max_length=20, verbose_name='Número de comprobante completo')
    employee = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name='Empleado')
    payment_type = models.CharField(choices=PAYMENT_TYPE, max_length=50, default=PAYMENT_TYPE[0][0], verbose_name='Tipo de pago')
    payment_method = models.CharField(choices=PAYMENT_METHOD, max_length=50, default=PAYMENT_METHOD[5][0], verbose_name='Método de pago')
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
    xml_authorized = models.FileField(null=True, blank=True, verbose_name='XML Autorizado')
    pdf_authorized = models.FileField(upload_to='pdf_authorized/%Y/%m/%d', null=True, blank=True, verbose_name='PDF Autorizado')
    create_electronic_invoice = models.BooleanField(default=True, verbose_name='Crear factura electrónica')
    status = models.CharField(max_length=50, choices=INVOICE_STATUS, default=INVOICE_STATUS[0][0], verbose_name='Estado')

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
        if isinstance(self.receipt.sequence, str):
            self.receipt.sequence = int(self.receipt.sequence)
        number = self.receipt.sequence + 1 if increase else self.receipt.sequence
        return f'{number:09d}'

    def generate_voucher_number_full(self):
        if self.receipt_id is None:
            self.company = Company.objects.first()
            self.receipt = Receipt.objects.get(voucher_type=VOUCHER_TYPE[0][0], establishment_code=self.company.establishment_code, issuing_point_code=self.company.issuing_point_code)
        self.voucher_number = self.generate_voucher_number()
        return self.get_voucher_number_full()

    def generate_pdf_authorized(self):
        rv = BytesIO()
        barcode.Code128(self.access_code, writer=barcode.writer.ImageWriter()).write(rv, options={'text_distance': 3.0, 'font_size': 6})
        file = base64.b64encode(rv.getvalue()).decode("ascii")
        context = {'sale': self, 'access_code_barcode': f"data:image/png;base64,{file}"}
        pdf_file = printer.create_pdf(context=context, template_name='sale/format/invoice.html')
        with tempfile.NamedTemporaryFile(delete=True) as file_temp:
            file_temp.write(pdf_file)
            file_temp.flush()
            self.pdf_authorized.save(name=f'{self.receipt.get_name_xml()}_{self.access_code}.pdf', content=File(file_temp))

    def generate_xml(self):
        access_key = SRI().create_access_key(self)
        root = ElementTree.Element('factura', id="comprobante", version="1.0.0")
        # infoTributaria
        xml_tax_info = ElementTree.SubElement(root, 'infoTributaria')
        ElementTree.SubElement(xml_tax_info, 'ambiente').text = str(self.company.environment_type)
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
        # infoFactura
        xml_info_invoice = ElementTree.SubElement(root, 'infoFactura')
        ElementTree.SubElement(xml_info_invoice, 'fechaEmision').text = datetime.now().strftime('%d/%m/%Y')
        ElementTree.SubElement(xml_info_invoice, 'dirEstablecimiento').text = self.company.establishment_address
        ElementTree.SubElement(xml_info_invoice, 'obligadoContabilidad').text = self.company.obligated_accounting
        ElementTree.SubElement(xml_info_invoice, 'tipoIdentificacionComprador').text = self.client.identification_type
        ElementTree.SubElement(xml_info_invoice, 'razonSocialComprador').text = self.client.user.names
        ElementTree.SubElement(xml_info_invoice, 'identificacionComprador').text = self.client.dni
        ElementTree.SubElement(xml_info_invoice, 'direccionComprador').text = self.client.address
        ElementTree.SubElement(xml_info_invoice, 'totalSinImpuestos').text = f'{self.get_full_subtotal():.2f}'
        ElementTree.SubElement(xml_info_invoice, 'totalDescuento').text = f'{self.total_dscto:.2f}'
        # totalConImpuestos
        xml_total_with_taxes = ElementTree.SubElement(xml_info_invoice, 'totalConImpuestos')
        # totalImpuesto
        if self.subtotal_0 != 0.0000:
            xml_total_tax_0 = ElementTree.SubElement(xml_total_with_taxes, 'totalImpuesto')
            ElementTree.SubElement(xml_total_tax_0, 'codigo').text = str(TAX_CODES[0][0])
            ElementTree.SubElement(xml_total_tax_0, 'codigoPorcentaje').text = '0'
            ElementTree.SubElement(xml_total_tax_0, 'baseImponible').text = f'{self.subtotal_0:.2f}'
            ElementTree.SubElement(xml_total_tax_0, 'valor').text = '0.00'
        if self.subtotal_12 != 0.0000:
            xml_total_tax12 = ElementTree.SubElement(xml_total_with_taxes, 'totalImpuesto')
            ElementTree.SubElement(xml_total_tax12, 'codigo').text = str(TAX_CODES[0][0])
            ElementTree.SubElement(xml_total_tax12, 'codigoPorcentaje').text = str(self.company.vat_percentage)
            ElementTree.SubElement(xml_total_tax12, 'baseImponible').text = f'{self.subtotal_12:.2f}'
            ElementTree.SubElement(xml_total_tax12, 'valor').text = f'{self.total_iva:.2f}'
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
        for detail in self.saledetail_set.all():
            xml_detail = ElementTree.SubElement(xml_details, 'detalle')
            ElementTree.SubElement(xml_detail, 'codigoPrincipal').text = detail.product.code
            ElementTree.SubElement(xml_detail, 'descripcion').text = detail.product.name
            ElementTree.SubElement(xml_detail, 'cantidad').text = f'{detail.cant:.2f}'
            ElementTree.SubElement(xml_detail, 'precioUnitario').text = f'{detail.price:.2f}'
            ElementTree.SubElement(xml_detail, 'descuento').text = f'{detail.total_dscto:.2f}'
            ElementTree.SubElement(xml_detail, 'precioTotalSinImpuesto').text = f'{detail.total:.2f}'
            xml_taxes = ElementTree.SubElement(xml_detail, 'impuestos')
            xml_tax = ElementTree.SubElement(xml_taxes, 'impuesto')
            ElementTree.SubElement(xml_tax, 'codigo').text = str(TAX_CODES[0][0])
            if detail.product.with_tax:
                ElementTree.SubElement(xml_tax, 'codigoPorcentaje').text = str(self.company.vat_percentage)
                ElementTree.SubElement(xml_tax, 'tarifa').text = f'{detail.iva * 100:.2f}'
                ElementTree.SubElement(xml_tax, 'baseImponible').text = f'{detail.total:.2f}'
                ElementTree.SubElement(xml_tax, 'valor').text = f'{detail.total_iva:.2f}'
            else:
                ElementTree.SubElement(xml_tax, 'codigoPorcentaje').text = "0"
                ElementTree.SubElement(xml_tax, 'tarifa').text = "0"
                ElementTree.SubElement(xml_tax, 'baseImponible').text = f'{detail.total:.2f}'
                ElementTree.SubElement(xml_tax, 'valor').text = "0"
        # infoAdicional
        if len(self.additional_info):
            xml_additional_info = ElementTree.SubElement(root, 'infoAdicional')
            for additional_info in self.additional_info:
                ElementTree.SubElement(xml_additional_info, 'campoAdicional', nombre=additional_info['name']).text = additional_info['value']
        return ElementTree.tostring(root, xml_declaration=True, encoding='utf-8').decode('utf-8').replace("'", '"'), access_key

    def is_invoice(self):
        return self.receipt.voucher_type == VOUCHER_TYPE[0][0]

    def toJSON(self):
        item = model_to_dict(self)
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
        for detail in self.saledetail_set.filter():
            detail.price = float(detail.price)
            detail.iva = float(self.iva)
            detail.price_with_vat = detail.price + (detail.price * detail.iva)
            detail.subtotal = detail.price * detail.cant
            detail.total_dscto = detail.subtotal * float(detail.dscto)
            detail.total_iva = (detail.subtotal - detail.total_dscto) * detail.iva
            detail.total = detail.subtotal - detail.total_dscto
            detail.save()

    def calculate_invoice(self):
        self.subtotal_0 = float(self.saledetail_set.filter(product__with_tax=False).aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField()))['result'])
        self.subtotal_12 = float(self.saledetail_set.filter(product__with_tax=True).aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField()))['result'])
        self.total_iva = float(self.saledetail_set.filter(product__with_tax=True).aggregate(result=Coalesce(Sum('total_iva'), 0.00, output_field=FloatField()))['result'])
        self.total_dscto = float(self.saledetail_set.filter().aggregate(result=Coalesce(Sum('total_dscto'), 0.00, output_field=FloatField()))['result'])
        self.total = float(self.get_full_subtotal()) + float(self.total_iva)
        self.save()

    def edit(self):
        super(Sale, self).save()

    def save(self, force_insert=False, force_update=False, using=None,
             update_fields=None):
        if self.pk is None:
            self.receipt.sequence = int(self.voucher_number)
            self.receipt.save()
        super(Sale, self).save()

    def delete(self, using=None, keep_parents=False):
        try:
            for i in self.saledetail_set.filter(product__inventoried=True):
                i.product.stock += i.cant
                i.product.save()
                i.delete()
        except:
            pass
        super(Sale, self).delete()

    def generate_electronic_invoice(self):
        sri = SRI()
        result = sri.create_xml(self)
        if result['resp']:
            result = sri.firm_xml(instance=self, xml=result['xml'])
            if result['resp']:
                result = sri.validate_xml(instance=self, xml=result['xml'])
                if result['resp']:
                    result = sri.authorize_xml(instance=self)
                    index = 1
                    while not result['resp'] and index < 3:
                        time.sleep(1)
                        result = sri.authorize_xml(instance=self)
                        index += 1
                    if result['resp']:
                        result['print_url'] = self.get_pdf_authorized()
                    return result
        return result

    class Meta:
        verbose_name = 'Venta'
        verbose_name_plural = 'Ventas'
        default_permissions = ()
        permissions = (
            ('view_sale', 'Can view Venta'),
            ('add_sale', 'Can add Venta'),
            ('delete_sale', 'Can delete Venta'),
            ('view_sale_client', 'Can view_sale_client Venta'),
        )


class SaleDetail(models.Model):
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
        item['iva'] = float(self.subtotal)
        item['total_iva'] = float(self.subtotal)
        item['dscto'] = float(self.dscto) * 100
        item['total_dscto'] = float(self.total_dscto)
        item['total'] = float(self.total)
        if args is not None:
            item.update(args)
        return item

    class Meta:
        verbose_name = 'Detalle de Venta'
        verbose_name_plural = 'Detalle de Ventas'
        default_permissions = ()


class CtasCollect(models.Model):
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


class PaymentsCtaCollect(models.Model):
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


class DebtsPay(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT)
    date_joined = models.DateField(default=datetime.now)
    end_date = models.DateField(default=datetime.now)
    debt = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    saldo = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    state = models.BooleanField(default=True)

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return f"{self.purchase.provider.name} ({self.purchase.number}) / {self.date_joined.strftime('%Y-%m-%d')} / ${f'{self.debt:.2f}'}"

    def validate_debt(self):
        try:
            saldo = self.paymentsdebtspay_set.aggregate(result=Coalesce(Sum('valor'), 0.00, output_field=FloatField()))['result']
            self.saldo = float(self.debt) - float(saldo)
            self.state = self.saldo > 0.00
            self.save()
        except:
            pass

    def toJSON(self):
        item = model_to_dict(self)
        item['purchase'] = self.purchase.toJSON()
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['end_date'] = self.end_date.strftime('%Y-%m-%d')
        item['debt'] = float(self.debt)
        item['saldo'] = float(self.saldo)
        return item

    class Meta:
        verbose_name = 'Cuenta por pagar'
        verbose_name_plural = 'Cuentas por pagar'
        default_permissions = ()
        permissions = (
            ('view_debts_pay', 'Can view Cuenta por pagar'),
            ('add_debts_pay', 'Can add Cuenta por pagar'),
            ('delete_debts_pay', 'Can delete Cuenta por pagar'),
        )


class PaymentsDebtsPay(models.Model):
    debts_pay = models.ForeignKey(DebtsPay, on_delete=models.CASCADE, verbose_name='Cuenta por pagar')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de registro')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Detalles')
    valor = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor')

    def __str__(self):
        return self.debts_pay.id

    def toJSON(self):
        item = model_to_dict(self, exclude=['debts_pay'])
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['valor'] = float(self.valor)
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


class TypeExpense(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name='Nombre')

    def __str__(self):
        return self.name

    def toJSON(self):
        item = model_to_dict(self)
        return item

    class Meta:
        verbose_name = 'Tipo de Gasto'
        verbose_name_plural = 'Tipos de Gastos'
        default_permissions = ()
        permissions = (
            ('view_type_expense', 'Can view Tipo de Gasto'),
            ('add_type_expense', 'Can add Tipo de Gasto'),
            ('change_type_expense', 'Can change Tipo de Gasto'),
            ('delete_type_expense', 'Can delete Tipo de Gasto'),
        )


class Expenses(models.Model):
    type_expense = models.ForeignKey(TypeExpense, on_delete=models.PROTECT, verbose_name='Tipo de Gasto')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Descripción')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de Registro')
    valor = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor')

    def __str__(self):
        return self.description

    def toJSON(self):
        item = model_to_dict(self)
        item['type_expense'] = self.type_expense.toJSON()
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['valor'] = float(self.valor)
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


class Promotions(models.Model):
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


class PromotionsDetail(models.Model):
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


class VoucherErrors(models.Model):
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


class CreditNote(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT, verbose_name='Compañia')
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
    xml_authorized = models.FileField(null=True, blank=True, verbose_name='XML Autorizado')
    pdf_authorized = models.FileField(upload_to='pdf_authorized/%Y/%m/%d', null=True, blank=True, verbose_name='PDF Autorizado')
    create_electronic_invoice = models.BooleanField(default=True, verbose_name='Crear factura electrónica')
    status = models.CharField(max_length=50, choices=INVOICE_STATUS, default=INVOICE_STATUS[0][0], verbose_name='Estado')

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
        number = int(self.receipt.get_sequence()) + 1
        return f'{number:09d}'

    def generate_voucher_number_full(self):
        self.company = Company.objects.first()
        self.receipt = Receipt.objects.get(voucher_type=VOUCHER_TYPE[1][0], establishment_code=self.company.establishment_code, issuing_point_code=self.company.issuing_point_code)
        self.voucher_number = self.generate_voucher_number()
        return self.get_voucher_number_full()

    def generate_pdf_authorized(self):
        rv = BytesIO()
        barcode.Code128(self.access_code, writer=barcode.writer.ImageWriter()).write(rv, options={'text_distance': 3.0, 'font_size': 6})
        file = base64.b64encode(rv.getvalue()).decode("ascii")
        context = {'credit_note': self, 'access_code_barcode': f"data:image/png;base64,{file}"}
        pdf_file = printer.create_pdf(context=context, template_name='credit_note/format/invoice.html')
        with tempfile.NamedTemporaryFile(delete=True) as file_temp:
            file_temp.write(pdf_file)
            file_temp.flush()
            self.pdf_authorized.save(name=f'{self.receipt.get_name_xml()}_{self.access_code}.pdf', content=File(file_temp))

    def generate_xml(self):
        access_key = SRI().create_access_key(self)
        root = ElementTree.Element('notaCredito', id="comprobante", version="1.1.0")
        # infoTributaria
        xml_tax_info = ElementTree.SubElement(root, 'infoTributaria')
        ElementTree.SubElement(xml_tax_info, 'ambiente').text = str(self.company.environment_type)
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
        if self.company.retention_agent == RETENTION_AGENT[0][0]:
            ElementTree.SubElement(xml_tax_info, 'agenteRetencion').text = '1'
        # infoNotaCredito
        xml_info_invoice = ElementTree.SubElement(root, 'infoNotaCredito')
        ElementTree.SubElement(xml_info_invoice, 'fechaEmision').text = datetime.now().strftime('%d/%m/%Y')
        ElementTree.SubElement(xml_info_invoice, 'dirEstablecimiento').text = self.company.establishment_address
        ElementTree.SubElement(xml_info_invoice, 'tipoIdentificacionComprador').text = self.sale.client.identification_type
        ElementTree.SubElement(xml_info_invoice, 'razonSocialComprador').text = self.sale.client.user.names
        ElementTree.SubElement(xml_info_invoice, 'identificacionComprador').text = self.sale.client.dni
        if not self.company.special_taxpayer == '000':
            ElementTree.SubElement(xml_info_invoice, 'contribuyenteEspecial').text = self.company.special_taxpayer
        ElementTree.SubElement(xml_info_invoice, 'obligadoContabilidad').text = self.company.obligated_accounting
        ElementTree.SubElement(xml_info_invoice, 'rise').text = 'Contribuyente Régimen Simplificado RISE'
        ElementTree.SubElement(xml_info_invoice, 'codDocModificado').text = self.sale.receipt.voucher_type
        ElementTree.SubElement(xml_info_invoice, 'numDocModificado').text = self.sale.voucher_number_full
        ElementTree.SubElement(xml_info_invoice, 'fechaEmisionDocSustento').text = self.sale.date_joined.strftime('%d/%m/%Y')
        ElementTree.SubElement(xml_info_invoice, 'totalSinImpuestos').text = f'{self.get_full_subtotal():.2f}'
        ElementTree.SubElement(xml_info_invoice, 'valorModificacion').text = f'{self.total:.2f}'
        ElementTree.SubElement(xml_info_invoice, 'moneda').text = 'DOLAR'
        # totalConImpuestos
        xml_total_with_taxes = ElementTree.SubElement(xml_info_invoice, 'totalConImpuestos')
        # totalImpuesto
        if self.subtotal_0 != 0.0000:
            xml_total_tax = ElementTree.SubElement(xml_total_with_taxes, 'totalImpuesto')
            ElementTree.SubElement(xml_total_tax, 'codigo').text = str(TAX_CODES[0][0])
            ElementTree.SubElement(xml_total_tax, 'codigoPorcentaje').text = '0'
            ElementTree.SubElement(xml_total_tax, 'baseImponible').text = f'{self.subtotal_0:.2f}'
            ElementTree.SubElement(xml_total_tax, 'valor').text = f'{0:.2f}'
        if self.subtotal_12 != 0.0000:
            xml_total_tax2 = ElementTree.SubElement(xml_total_with_taxes, 'totalImpuesto')
            ElementTree.SubElement(xml_total_tax2, 'codigo').text = str(TAX_CODES[0][0])
            ElementTree.SubElement(xml_total_tax2, 'codigoPorcentaje').text = str(self.company.vat_percentage)
            ElementTree.SubElement(xml_total_tax2, 'baseImponible').text = f'{self.subtotal_12:.2f}'
            ElementTree.SubElement(xml_total_tax2, 'valor').text = f'{self.total_iva:.2f}'
        ElementTree.SubElement(xml_info_invoice, 'motivo').text = self.motive
        # detalles
        xml_details = ElementTree.SubElement(root, 'detalles')
        for detail in self.creditnotedetail_set.all():
            xml_detail = ElementTree.SubElement(xml_details, 'detalle')
            ElementTree.SubElement(xml_detail, 'codigoInterno').text = detail.product.code
            ElementTree.SubElement(xml_detail, 'descripcion').text = detail.product.name
            ElementTree.SubElement(xml_detail, 'cantidad').text = f'{detail.cant:.2f}'
            ElementTree.SubElement(xml_detail, 'precioUnitario').text = f'{detail.price:.2f}'
            ElementTree.SubElement(xml_detail, 'descuento').text = f'{detail.total_dscto:.2f}'
            ElementTree.SubElement(xml_detail, 'precioTotalSinImpuesto').text = f'{detail.total:.2f}'
            xml_taxes = ElementTree.SubElement(xml_detail, 'impuestos')
            xml_tax = ElementTree.SubElement(xml_taxes, 'impuesto')
            ElementTree.SubElement(xml_tax, 'codigo').text = str(TAX_CODES[0][0])
            if detail.product.with_tax:
                ElementTree.SubElement(xml_tax, 'codigoPorcentaje').text = str(self.company.vat_percentage)
                ElementTree.SubElement(xml_tax, 'tarifa').text = f'{detail.iva * 100:.2f}'
                ElementTree.SubElement(xml_tax, 'baseImponible').text = f'{detail.total:.2f}'
                ElementTree.SubElement(xml_tax, 'valor').text = f'{detail.total_iva:.2f}'
            else:
                ElementTree.SubElement(xml_tax, 'codigoPorcentaje').text = "0"
                ElementTree.SubElement(xml_tax, 'tarifa').text = "0"
                ElementTree.SubElement(xml_tax, 'baseImponible').text = f'{detail.total:.2f}'
                ElementTree.SubElement(xml_tax, 'valor').text = "0"
        # infoAdicional
        xml_additional_info = ElementTree.SubElement(root, 'infoAdicional')
        ElementTree.SubElement(xml_additional_info, 'campoAdicional', nombre='dirCliente').text = self.sale.client.address
        ElementTree.SubElement(xml_additional_info, 'campoAdicional', nombre='telfCliente').text = self.sale.client.mobile
        ElementTree.SubElement(xml_additional_info, 'campoAdicional', nombre='Observacion').text = f'NOTA_CREDITO # {self.voucher_number}'
        return ElementTree.tostring(root, xml_declaration=True, encoding='UTF-8').decode('UTF-8').replace("'", '"'), access_key

    def toJSON(self):
        item = model_to_dict(self)
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
        sri = SRI()
        result = sri.create_xml(self)
        if result['resp']:
            result = sri.firm_xml(instance=self, xml=result['xml'])
            if result['resp']:
                result = sri.validate_xml(instance=self, xml=result['xml'])
                if result['resp']:
                    return sri.authorize_xml(instance=self)
        return result

    def calculate_detail(self):
        for detail in self.creditnotedetail_set.filter():
            detail.price = float(detail.price)
            detail.iva = float(self.iva)
            detail.price_with_vat = detail.price + (detail.price * detail.iva)
            detail.subtotal = detail.price * detail.cant
            detail.total_dscto = detail.subtotal * float(detail.dscto)
            detail.total_iva = (detail.subtotal - detail.total_dscto) * detail.iva
            detail.total = detail.subtotal - detail.total_dscto
            detail.save()

    def calculate_invoice(self):
        self.subtotal_0 = float(self.creditnotedetail_set.filter(product__with_tax=False).aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField()))['result'])
        self.subtotal_12 = float(self.creditnotedetail_set.filter(product__with_tax=True).aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField()))['result'])
        self.total_iva = float(self.creditnotedetail_set.filter(product__with_tax=True).aggregate(result=Coalesce(Sum('total_iva'), 0.00, output_field=FloatField()))['result'])
        self.total_dscto = float(self.creditnotedetail_set.filter().aggregate(result=Coalesce(Sum('total_dscto'), 0.00, output_field=FloatField()))['result'])
        self.total = float(self.get_full_subtotal()) + float(self.total_iva)
        self.save()

    def edit(self):
        super(CreditNote, self).save()

    def save(self, force_insert=False, force_update=False, using=None,
             update_fields=None):
        if self.motive is None:
            self.motive = 'Sin detalles'
        if self.pk is None:
            self.receipt.sequence = int(self.voucher_number)
            self.receipt.save()
        super(CreditNote, self).save()

    def delete(self, using=None, keep_parents=False):
        try:
            for i in self.creditnotedetail_set.filter(product__inventoried=True):
                i.product.stock += i.cant
                i.product.save()
                i.delete()
        except:
            pass
        super(CreditNote, self).delete()

    class Meta:
        verbose_name = 'Nota de Credito'
        verbose_name_plural = 'Notas de Credito'
        default_permissions = ()
        permissions = (
            ('view_credit_note', 'Can view Nota de Credito'),
            ('add_credit_note', 'Can add Nota de Credito'),
            ('delete_credit_note', 'Can delete Nota de Credito'),
            ('view_credit_note_client', 'Can view_credit_note_client Nota de Credito'),
        )


class CreditNoteDetail(models.Model):
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
        item['iva'] = float(self.subtotal)
        item['total_iva'] = float(self.subtotal)
        item['dscto'] = float(self.dscto)
        item['total_dscto'] = float(self.total_dscto)
        item['total'] = float(self.total)
        return item

    class Meta:
        verbose_name = 'Detalle Devolución Ventas'
        verbose_name_plural = 'Detalle Devoluciones Ventas'
        default_permissions = ()
