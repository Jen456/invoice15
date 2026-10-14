from django import forms

from core.comprobantes.models import CodigoRetencion
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
TARIFAS_IVA = (('15.00', '15 %'), ('5.00', '5 %'), ('0.00', '0 % (sin IVA)'))


class CodigoChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        impuesto = 'Renta' if obj.impuesto == '1' else 'IVA'
        porcentaje = f'{obj.porcentaje.normalize():f}'.replace('.', ',')
        return f'{impuesto} · {obj.codigo} · {obj.concepto[:90]} ({porcentaje} %)'


class DocumentoSustentoForm(forms.Form):
    num_doc_sustento = forms.CharField(label='Número de la factura del proveedor', max_length=17,
                                       help_text='Con establecimiento y punto: 001-001-000000123.')
    aut_doc_sustento = forms.CharField(label='Autorización de la factura (clave de acceso)', max_length=49,
                                       help_text='49 dígitos (o 10 / 37 en comprobantes antiguos).')
    fecha_doc_sustento = forms.DateField(label='Fecha de emisión de la factura', widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))   # <input type=date> solo acepta ISO
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
