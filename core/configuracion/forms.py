"""Formularios del asistente de configuración de facturación (validación en el servidor)."""
from django import forms

from core.configuracion.servicios import MENSAJES, PRODUCCION
from core.login.identificacion import ruc_valido, solo_digitos
from core.pos.choices import ENVIRONMENT_TYPE
from core.pos.models import Company, Establishment, codigo_sri


class EmpresaForm(forms.ModelForm):
    """Paso 1: datos de la empresa que aparecen en los comprobantes."""

    class Meta:
        model = Company
        fields = ('ruc', 'business_name', 'tradename', 'main_address', 'obligated_accounting', 'special_taxpayer',
                  'retention_agent', 'rimpe', 'mobile', 'phone', 'email')

    def clean_ruc(self):
        ruc = solo_digitos(self.cleaned_data['ruc'])
        if not ruc_valido(ruc):
            raise forms.ValidationError('Ingresa un RUC válido de 13 dígitos.')
        return ruc


class EstablecimientoForm(forms.Form):
    """Paso 2, acción agregar_establecimiento: el establecimiento y, en el mismo envío, su punto de emisión
    (obligatorio en el primero: un punto no puede existir sin establecimiento)."""
    code = forms.CharField(label='Código del establecimiento', max_length=3, validators=[codigo_sri],
                           help_text='Tres dígitos, como figuran en tu RUC (por ejemplo 001).')
    name = forms.CharField(label='Nombre del establecimiento', max_length=100, required=False)
    address = forms.CharField(label='Dirección del establecimiento', max_length=200)
    point_code = forms.CharField(label='Código del punto de emisión', max_length=3, required=False, validators=[codigo_sri],
                                 help_text='Tres dígitos (por ejemplo 002). Puedes agregar más puntos después.')
    point_description = forms.CharField(label='Descripción del punto', max_length=100, required=False)
    field_order = ['code', 'point_code', 'address', 'name', 'point_description']   # los dos códigos juntos, como en 001-002

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        if Establishment.all_companies.filter(company=company, is_active=True).exists():
            self.fields['point_code'].label = 'Código del punto de emisión (opcional)'
        else:
            self.fields['point_code'].required = True
            self.fields['point_code'].error_messages['required'] = MENSAJES['falta_codigo_punto']

    def clean_code(self):
        code = self.cleaned_data['code']
        if Establishment.all_companies.filter(company=self.company, code=code).exists():
            raise forms.ValidationError(MENSAJES['establecimiento_duplicado'].format(codigo=code))
        return code


class PuntoForm(forms.Form):
    """Paso 2, acción agregar_punto."""
    establishment = forms.ModelChoiceField(queryset=Establishment.all_companies.none(), label='Establecimiento',
                                           error_messages={'required': MENSAJES['elige_establecimiento']})
    code = forms.CharField(label='Código del punto de emisión', max_length=3, validators=[codigo_sri],
                           help_text='Tres dígitos (por ejemplo 001).')
    description = forms.CharField(label='Descripción', max_length=100, required=False)

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['establishment'].queryset = Establishment.all_companies.filter(company=company, is_active=True)

    def clean(self):
        datos = super().clean()
        est, code = datos.get('establishment'), datos.get('code')
        if est and code and est.points.filter(code=code).exists():
            raise forms.ValidationError(MENSAJES['punto_duplicado'].format(codigo=code, establecimiento=est.code))
        return datos


class ConfirmarPuntoForm(forms.Form):
    """Paso 2, acción confirmar: punto con el que se emite y confirmación de los códigos."""
    point = forms.ModelChoiceField(queryset=None, label='Punto con el que emites', empty_label=None)
    confirm = forms.BooleanField(label='Confirmo que estos códigos son los que el SRI asignó a mi RUC',
                                 error_messages={'required': MENSAJES['confirmar_codigos']})

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        from core.pos.models import EmissionPoint
        self.fields['point'].queryset = EmissionPoint.all_companies.select_related('establishment').filter(
            company=company, is_active=True, establishment__is_active=True)


class SecuenciaForm(forms.Form):
    """Paso 3: numeración de un tipo de documento (prefijo = código del tipo, 01 o 04)."""
    MODOS = (('nuevo', 'Nunca he emitido este documento: empezar en 000000001'),
             ('otro_sistema', 'Ya emití en otro sistema: indicar el último número usado'),
             ('mantener', 'Mantener la numeración registrada'))
    mode = forms.ChoiceField(choices=MODOS, label='Numeración', widget=forms.RadioSelect(attrs={'class': 'form-check-input'}))
    last_number = forms.CharField(label='Último número utilizado', required=False, max_length=20,
                                  help_text='Por ejemplo 001-002-000000125 (el próximo será 001-002-000000126).')
    confirm = forms.BooleanField(label='Confirmo la numeración indicada', required=False)


class AmbienteFirmaForm(forms.Form):
    """Paso 4: ambiente del SRI y firma electrónica."""
    environment_type = forms.TypedChoiceField(choices=ENVIRONMENT_TYPE, coerce=int, label='Ambiente')
    confirm_production = forms.BooleanField(required=False, label='Entiendo que en Producción los comprobantes tienen validez tributaria')
    electronic_signature = forms.FileField(required=False, label='Firma electrónica (.p12)')
    electronic_signature_key = forms.CharField(required=False, max_length=100, label='Clave de la firma',
                                               widget=forms.PasswordInput(render_value=False))

    def clean(self):
        datos = super().clean()
        if datos.get('environment_type') == PRODUCCION and not datos.get('confirm_production'):
            self.add_error('confirm_production', MENSAJES['confirmar_produccion'])
        archivo = datos.get('electronic_signature')
        if archivo and not archivo.name.lower().endswith('.p12'):
            self.add_error('electronic_signature', 'Sube un archivo con extensión .p12.')
        return datos


class ConfirmacionForm(forms.Form):
    """Paso 5."""
    confirm = forms.BooleanField(label='Confirmo que estos son los números con los que debo continuar',
                                 error_messages={'required': MENSAJES['confirmar_revision']})
