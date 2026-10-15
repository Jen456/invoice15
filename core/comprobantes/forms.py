from decimal import Decimal

from django import forms

from core.comprobantes.models import CodigoRetencion, LiquidacionCompra
from core.pos.choices import PAYMENT_METHOD

# Tabla 5 del catálogo ATS: sustento tributario (los de uso más frecuente; el resto se puede agregar).
SUSTENTOS = (
    ('01', '01 · Crédito tributario para declaración de IVA (servicios y bienes distintos de inventarios y activos fijos)'),
    ('02', '02 · Costo o gasto para declaración de IR (servicios y bienes distintos de inventarios y activos fijos)'),
    ('03', '03 · Activo fijo - Crédito tributario para declaración de IVA'),
    ('04', '04 · Activo fijo - Costo o gasto para declaración de IR'),
    ('05', '05 · Liquidación de gastos de viaje, hospedaje y alimentación (IR a nombre de empleados)'),
    ('06', '06 · Inventario - Crédito tributario para declaración de IVA'),
    ('07', '07 · Inventario - Costo o gasto para declaración de IR'),
    ('08', '08 · Valor pagado para solicitar reembolso de gasto (intermediario)'),
    ('09', '09 · Reembolso por siniestros'),
    ('14', '14 · Valores facturados por socios a operadoras de transporte (que no constituyen gasto de la operadora)'),
    ('15', '15 · Pagos por consumos propios y de terceros de servicios digitales'),
)   # tabla 5 del catálogo ATS: solo los sustentos que admiten una factura (01) como documento sustento
DOCUMENTOS_SUSTENTO = (('01', 'Factura'), ('03', 'Liquidación de compra (emitida por ti)'))
TARIFAS_IVA = (('15.00', '15 %'), ('5.00', '5 %'), ('0.00', '0 % (sin IVA)'))


class CodigoChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        impuesto = 'Renta' if obj.impuesto == '1' else 'IVA'
        porcentaje = f'{obj.porcentaje.normalize():f}'.replace('.', ',')
        return f'{impuesto} · {obj.codigo} · {obj.concepto[:90]} ({porcentaje} %)'


class DocumentoSustentoForm(forms.Form):
    cod_doc_sustento = forms.ChoiceField(label='Documento sustento', choices=DOCUMENTOS_SUSTENTO, initial='01', required=False)
    num_doc_sustento = forms.CharField(label='Número del documento', max_length=17,
                                       help_text='Con establecimiento y punto: 001-001-000000123.')
    aut_doc_sustento = forms.CharField(label='Autorización (clave de acceso)', max_length=49,
                                       help_text='49 dígitos (o 10 / 37 en comprobantes antiguos).')
    fecha_doc_sustento = forms.DateField(label='Fecha de emisión del documento', widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))   # <input type=date> solo acepta ISO
    base_0 = forms.DecimalField(label='Base 0 %', required=False, min_value=0, decimal_places=2, max_digits=12)
    base_iva = forms.DecimalField(label='Base gravada con IVA', required=False, min_value=0, decimal_places=2, max_digits=12)
    tarifa_iva = forms.ChoiceField(label='Tarifa de IVA', choices=TARIFAS_IVA, initial='15.00')
    valor_iva = forms.DecimalField(label='IVA de la factura', required=False, min_value=0, decimal_places=2, max_digits=12,
                                   help_text='Vacío: se calcula con la tarifa.')
    cod_sustento = forms.ChoiceField(label='Sustento tributario', choices=SUSTENTOS, initial='01')
    forma_pago = forms.ChoiceField(label='Forma de pago', choices=PAYMENT_METHOD, initial='20')
    parte_relacionada = forms.BooleanField(label='El proveedor es parte relacionada', required=False)


class LineaRetencionForm(forms.Form):
    codigo = CodigoChoiceField(queryset=CodigoRetencion.objects.filter(activo=True), required=False, label='Retención',
                               empty_label='— Sin retención en esta línea —')
    base = forms.DecimalField(label='Base imponible', required=False, min_value=0, decimal_places=2, max_digits=12,
                              help_text='Vacío: renta sobre la base sin impuestos; IVA sobre el valor del IVA.')
    porcentaje = forms.DecimalField(label='% (solo códigos de porcentaje variable)', required=False, min_value=0,
                                    max_value=100, decimal_places=2, max_digits=5)


LineasRetencionFormSet = forms.formset_factory(LineaRetencionForm, extra=3, max_num=10)


class LiquidacionForm(forms.Form):
    tipo_identificacion = forms.ChoiceField(label='Identificación del proveedor', choices=LiquidacionCompra.TIPO_IDENTIFICACION)
    direccion = forms.CharField(label='Dirección del proveedor', max_length=300, required=False)
    forma_pago = forms.ChoiceField(label='Forma de pago', choices=PAYMENT_METHOD, initial='01')
    concepto = forms.CharField(label='Concepto (opcional)', max_length=300, required=False,
                               help_text='Se imprime en la información adicional, p. ej. «Compra de cacao en grano».')
    confirma_sin_ruc = forms.BooleanField(label='Confirmo que el RUC del proveedor está suspendido y por eso no puede emitirme factura',
                                          required=False)


class LineaLiquidacionForm(forms.Form):
    detalle = forms.IntegerField(widget=forms.HiddenInput)
    descripcion = forms.CharField(label='Descripción', max_length=300, required=False,
                                  help_text='Vacío: el nombre del producto de la compra.')
    tarifa = forms.ChoiceField(label='Tarifa de IVA', choices=TARIFAS_IVA)


LineasLiquidacionFormSet = forms.formset_factory(LineaLiquidacionForm, extra=0)


class NotaDebitoForm(forms.Form):
    tarifa_iva = forms.ChoiceField(label='Tarifa de IVA', help_text='La de la fecha de la factura, o 0 % si el cargo no grava IVA.')
    forma_pago = forms.ChoiceField(label='Forma de pago', choices=PAYMENT_METHOD)

    def __init__(self, *args, tarifas=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tarifa_iva'].choices = [(f'{t:.2f}', f'{t.normalize():f} %'.replace('.', ',')) for t in tarifas]


class MotivoNotaDebitoForm(forms.Form):
    razon = forms.CharField(label='Razón', max_length=300, required=False, help_text='Por ejemplo: «Interés por mora».')
    valor = forms.DecimalField(label='Valor sin IVA', required=False, min_value=Decimal('0.01'), decimal_places=2, max_digits=12)


MotivosNotaDebitoFormSet = forms.formset_factory(MotivoNotaDebitoForm, extra=3, max_num=10)


class GuiaForm(forms.Form):
    transportista_tipo_identificacion = forms.ChoiceField(label='Identificación del transportista',
                                                          choices=(('04', 'RUC'), ('05', 'Cédula'), ('06', 'Pasaporte'),
                                                                   ('08', 'Identificación del exterior')), initial='04')
    transportista_identificacion = forms.CharField(label='Número de identificación', max_length=20)
    transportista_razon_social = forms.CharField(label='Nombre o razón social del transportista', max_length=300)
    placa = forms.CharField(label='Placa del vehículo', max_length=20)
    fecha_inicio = forms.DateField(label='Inicio del transporte', widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    fecha_fin = forms.DateField(label='Fin del transporte', widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    dir_partida = forms.CharField(label='Dirección de partida', max_length=300)
    direccion = forms.CharField(label='Dirección de destino', max_length=300)
    motivo = forms.CharField(label='Motivo del traslado', max_length=300, initial='Venta')
    ruta = forms.CharField(label='Ruta (opcional)', max_length=300, required=False)
    cod_estab_destino = forms.CharField(label='Establecimiento de destino (opcional)', max_length=3, required=False,
                                        help_text='Solo si el destino es un establecimiento del comprador, p. ej. 001.')
    doc_aduanero = forms.CharField(label='Documento aduanero único (opcional)', max_length=20, required=False)


class LineaGuiaForm(forms.Form):
    detalle = forms.IntegerField(widget=forms.HiddenInput)
    cantidad = forms.DecimalField(label='Cantidad a trasladar', required=False, min_value=0, decimal_places=6, max_digits=18)


LineasGuiaFormSet = forms.formset_factory(LineaGuiaForm, extra=0)
