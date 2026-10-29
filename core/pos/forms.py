from django import forms

from .models import *
from core.pos.clientes import correo_valido, separar_correos, validar_identificacion


class ProviderForm(forms.ModelForm):
    """Proveedor con los datos del ATS (espec-etapa2-compras §1.2 y §6.D). Las reglas están en
    core.pos.proveedores.validar_proveedor: número según el tipo, tipo de sujeto derivado con RUC o cédula y elegido con
    pasaporte o identificación del exterior. La parte relacionada no tiene valor inicial en un proveedor nuevo (DC12)."""
    parte_relacionada = forms.TypedChoiceField(
        label='Parte relacionada', required=False, choices=(('', 'Elige si o no'), ('no', 'No'), ('si', 'Sí')),
        coerce=lambda valor: valor == 'si', empty_value=None,
        widget=forms.Select(attrs={'class': 'form-control'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for i in self.visible_fields():
            if type(i.field) in [forms.CharField]:
                i.field.widget.attrs.update({
                    'class': 'form-control',
                    'autocomplete': 'off'
                })
        self.fields['name'].widget.attrs['autofocus'] = True
        self.fields['tipo_identificacion'].choices = [('', 'Elige el tipo de identificación')] + list(TIPOS_IDENTIFICACION_PROVEEDOR)
        self.fields['tipo_sujeto'].choices = [('', 'Según la identificación')] + list(TIPOS_SUJETO)
        self.fields['tipo_sujeto'].help_text = 'Con RUC o cédula se calcula solo; con pasaporte o identificación del exterior, elígelo.'
        valor = self.instance.parte_relacionada if self.instance.pk else None
        self.initial['parte_relacionada'] = '' if valor is None else ('si' if valor else 'no')
        self.advertencias = []

    class Meta:
        model = Provider
        fields = ('name', 'tipo_identificacion', 'ruc', 'tipo_sujeto', 'parte_relacionada', 'mobile', 'email', 'address')
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre'}),
            'tipo_identificacion': forms.Select(attrs={'class': 'form-control'}),
            'ruc': forms.TextInput(attrs={'placeholder': 'RUC, cédula, pasaporte o identificación del exterior'}),
            'tipo_sujeto': forms.Select(attrs={'class': 'form-control'}),
            'mobile': forms.TextInput(attrs={'placeholder': 'Ingrese un teléfono celular'}),
            'address': forms.TextInput(attrs={'placeholder': 'Ingrese una dirección'}),
            'email': forms.TextInput(attrs={'placeholder': 'Ingrese un email'}),
        }

    def clean(self):
        from core.pos.proveedores import validar_proveedor
        datos = super().clean()
        numero, sujeto, errores, advertencias = validar_proveedor(
            datos.get('tipo_identificacion'), datos.get('ruc', self.data.get('ruc')), datos.get('tipo_sujeto'),
            datos.get('parte_relacionada'))
        for campo, mensaje in errores:
            if campo not in self.errors:
                self.add_error(campo, mensaje)
        if 'ruc' in datos:
            datos['ruc'] = numero
        datos['tipo_sujeto'] = sujeto
        self.advertencias = [{'codigo': codigo, 'texto': texto} for codigo, texto in advertencias]
        return datos

    def save(self, commit=True):
        from django.db import transaction
        from core.pos import compras
        data = {}
        try:
            if self.is_valid():
                with transaction.atomic():   # los datos del proveedor cuentan en la marca de sus compras (DC2)
                    instace = super().save()
                    compras.actualizar_marcas_de_proveedor(instace, getattr(self, 'usuario', None))
                data = instace.toJSON()
                data['advertencias'] = self.advertencias
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data


class CategoryForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['autofocus'] = True

    class Meta:
        model = Category
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre'}),
        }

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data


class ProductForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['autofocus'] = True
        # La tarifa de IVA reemplaza a «¿Se cobra impuesto?» (que el modelo mantiene sincronizado).
        self.fields['tarifa_iva'].required = True
        self.fields['tarifa_iva'].choices = TARIFAS_IVA
        if not self.instance.tarifa_iva:
            self.initial['tarifa_iva'] = '0' if self.instance.pk and not self.instance.with_tax else '4'

    class Meta:
        model = Product
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre'}),
            'code': forms.TextInput(attrs={'placeholder': 'Ingrese un código'}),
            'description': forms.Textarea(attrs={'placeholder': 'Ingrese una descripción', 'rows': 3, 'cols': 3}),
            'category': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'price': forms.TextInput(),
            'pvp': forms.TextInput(),
            'tarifa_iva': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
        }
        exclude = ['stock', 'barcode', 'with_tax']

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data


class PurchaseForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['provider'].queryset = Provider.objects.none()

    class Meta:
        model = Purchase
        fields = '__all__'
        widgets = {
            'number': forms.TextInput(attrs={'placeholder': 'Ingrese un número de factura', 'class': 'form-control', 'autocomplete': 'off'}),
            'provider': forms.Select(attrs={'class': 'custom-select select2'}),
            'payment_type': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'date_joined': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'date_joined',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#date_joined'
            }),
            'end_credit': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'end_credit',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#end_credit'
            }),
            'subtotal': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
        }


class TypeExpenseForm(forms.ModelForm):
    """Tipo de gasto con cuenta contable y sustento tributario opcional, sin valor inicial (DC12: la sugerencia
    compras.sustento_gasto_sugerido solo se muestra como texto)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['autofocus'] = True
        self.fields['cod_sustento'].required = False
        self.fields['cod_sustento'].choices = [('', 'Sin indicar')] + list(SUSTENTOS)
        self.fields['cod_sustento'].help_text = '01 da crédito tributario de IVA; 02 no. Confírmalo con tu contador.'
        self.fields['cuenta_contable'].help_text = 'Código del plan de cuentas de tu contador (opcional).'

    class Meta:
        model = TypeExpense
        fields = ('name', 'cuenta_contable', 'cod_sustento')
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre'}),
            'cuenta_contable': forms.TextInput(attrs={'placeholder': 'Ej.: 5.2.01.03', 'autocomplete': 'off'}),
            'cod_sustento': forms.Select(),
        }

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data


class ExpensesForm(forms.ModelForm):
    """Gasto sin comprobante: medio de pago obligatorio y sin valor inicial (MEDIOS_DE_PAGO, DC13); referencia obligatoria
    con cheque. Con factura, el gasto se registra en Compras como compra de gasto."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['type_expense'].widget.attrs['autofocus'] = True
        self.fields['medio_pago'].required = True
        self.fields['medio_pago'].choices = [('', 'Elige el medio de pago')] + list(MEDIOS_DE_PAGO)
        self.fields['medio_pago'].error_messages['required'] = 'Elige el medio de pago'

    class Meta:
        model = Expenses
        fields = ('type_expense', 'description', 'date_joined', 'valor', 'medio_pago', 'referencia')
        widgets = {
            'type_expense': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'description': forms.Textarea(attrs={'placeholder': 'Ingrese una descripción', 'rows': 3, 'cols': '3'}),
            'date_joined': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'date_joined',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#date_joined'
            }),
            'valor': forms.TextInput(),
            'medio_pago': forms.Select(attrs={'class': 'form-control'}),
            'referencia': forms.TextInput(attrs={'placeholder': 'N.º de transferencia, cheque o comprobante', 'autocomplete': 'off'}),
        }

    def clean(self):
        datos = super().clean()
        referencia = ' '.join((datos.get('referencia') or '').split())
        datos['referencia'] = referencia
        if datos.get('medio_pago') == 'cheque' and not referencia:
            self.add_error('referencia', 'Escribe el número del cheque')
        return datos

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data


class PaymentsDebtsPayForm(forms.ModelForm):
    """Pantalla «Registrar pago» de cuentas por pagar. El registro lo hace cuentas_por_pagar.registrar_pago; el medio de pago
    es obligatorio y sin valor inicial; la referencia, obligatoria con cheque."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['valor'].widget.attrs['autofocus'] = True
        self.fields['debts_pay'].queryset = DebtsPay.objects.none()
        self.fields['medio_pago'].required = True
        self.fields['medio_pago'].choices = [('', 'Elige el medio de pago')] + list(MEDIOS_DE_PAGO)

    class Meta:
        model = PaymentsDebtsPay
        fields = ('debts_pay', 'date_joined', 'valor', 'medio_pago', 'referencia', 'description')
        widgets = {
            'debts_pay': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'date_joined': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'date_joined',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#date_joined'
            }),
            'valor': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off',
            }),
            'medio_pago': forms.Select(attrs={'class': 'form-control'}),
            'referencia': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off',
                'placeholder': 'N.º de transferencia, cheque o comprobante',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'autocomplete': 'off',
                'rows': 3,
                'cols': 3,
                'placeholder': 'Ingrese una descripción'
            }),
        }


class IdentificacionField(forms.CharField):
    """Espacios repetidos en uno antes de medir el largo (ClientForm.clean normaliza el número según su tipo)."""

    def to_python(self, value):
        return ' '.join(super().to_python(value).split())


class ClientForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean_extra_emails(self):
        correos = separar_correos(self.cleaned_data.get('extra_emails'))
        invalidos = [c for c in correos if not correo_valido(c)]
        if invalidos:
            raise forms.ValidationError(f'Correo no válido: {", ".join(invalidos)}')
        texto = ', '.join(correos)
        if len(texto) > 500:
            raise forms.ValidationError('Los correos adicionales no pueden pasar de 500 caracteres.')
        return texto

    def clean(self):
        """La identificación debe corresponder a su tipo (tabla 6 de la ficha técnica del SRI)."""
        datos = super().clean()
        dni, errores = validar_identificacion(datos.get('identification_type'), datos.get('dni'))
        for campo, mensaje in errores:
            self.add_error(campo, mensaje)
        datos['dni'] = dni
        return datos

    class Meta:
        model = Client
        fields = '__all__'
        widgets = {
            'dni': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off',
                'placeholder': 'Ingrese un número de cedula o ruc',
            }),
            'mobile': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off',
                'placeholder': 'Ingrese un número de teléfono',
            }),
            'birthdate': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'birthdate',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#birthdate'
            }),
            'address': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off',
                'placeholder': 'Ingrese una dirección'
            }),
            'identification_type': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'extra_emails': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off',
                'placeholder': 'Ej.: contabilidad@empresa.com, compras@empresa.com',
            }),
        }
        field_classes = {'dni': IdentificacionField}
        exclude = ['user']


class ClientUserForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for i in self.visible_fields():
            if type(i.field) in [forms.CharField, forms.ImageField, forms.FileField, forms.EmailField]:
                i.field.widget.attrs.update({
                    'class': 'form-control',
                    'autocomplete': 'off'
                })
        self.fields['names'].widget.attrs['autofocus'] = True

    class Meta:
        model = User
        fields = 'names', 'email', 'image'
        widgets = {
            'names': forms.TextInput(attrs={'placeholder': 'Ingrese sus nombres'}),
            'email': forms.TextInput(attrs={'placeholder': 'Ingrese su correo electrónico'}),
        }
        exclude = ['username', 'groups', 'is_active', 'is_change_password', 'is_staff', 'user_permissions', 'date_joined', 'last_login', 'is_superuser', 'email_reset_token']


class SaleForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].queryset = Client.objects.none()
        self.fields['receipt'].choices = tuple((code, label) for code, label in VOUCHER_TYPE if code in ('01', '08'))

    class Meta:
        model = Sale
        fields = '__all__'
        widgets = {
            'client': forms.Select(attrs={'class': 'custom-select select2'}),
            'receipt': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'voucher_number': forms.TextInput(attrs={'class': 'form-control', 'disabled': True}),
            'payment_type': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'payment_method': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'date_joined': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'date_joined',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#date_joined'
            }),
            'time_limit': forms.TextInput(attrs={
                'class': 'form-control',
            }),
            'create_electronic_invoice': forms.CheckboxInput(attrs={
                'class': 'form-control-checkbox',
            }),
            'end_credit': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'end_credit',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#end_credit'
            }),
            'subtotal_0': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'disabled': True
            }),
            'subtotal_12': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'disabled': True
            }),
            'iva': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'disabled': True
            }),
            'total_iva': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'disabled': True
            }),
            'total_dscto': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'total': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'cash': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'change': forms.TextInput(attrs={
                'class': 'form-control',
                'readonly': True
            }),
        }


class PaymentsCtaCollectForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['valor'].widget.attrs['autofocus'] = True
        self.fields['ctas_collect'].queryset = PaymentsCtaCollect.objects.none()

    class Meta:
        model = PaymentsCtaCollect
        fields = '__all__'
        widgets = {
            'ctas_collect': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'date_joined': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'date_joined',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#date_joined'
            }),
            'valor': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'autocomplete': 'off',
                'rows': 3,
                'cols': 3,
                'placeholder': 'Ingrese una descripción'
            }),
        }


class CompanyForm(forms.ModelForm):
    # Se pueden guardar los datos de la empresa sin firma ni correo propio;
    # la firma (.p12) solo se acepta con un plan pagado vigente.
    OPCIONALES = ('electronic_signature', 'electronic_signature_key', 'email_host_user', 'email_host_password')
    # Claves guardadas: nunca se devuelven al navegador y un campo vacío conserva la anterior.
    SECRETOS = ('electronic_signature_key', 'email_host_password')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['business_name'].widget.attrs['autofocus'] = True
        for name in self.OPCIONALES:
            self.fields[name].required = False
        for name in self.SECRETOS:
            if self.instance.pk is not None and getattr(self.instance, name):
                self.fields[name].widget.attrs['placeholder'] = 'Guardada. Déjala vacía para conservarla'
                self.fields[name].help_text = 'Por seguridad no se muestra. Escribe una nueva solo si quieres cambiarla.'
        for i in self.visible_fields():
            if type(i.field) in [forms.CharField, forms.ImageField, forms.FileField, forms.IntegerField]:
                i.field.widget.attrs.update({
                    'class': 'form-control',
                    'autocomplete': 'off'
                })

    class Meta:
        model = Company
        # Establecimiento, punto de emisión, su dirección y ambiente se configuran solo en el asistente
        # de facturación (fuente única, junto con la numeración); aquí se muestran en solo lectura.
        exclude = ('is_active', 'establishment_code', 'issuing_point_code', 'establishment_address', 'environment_type')
        widgets = {
            'ruc': forms.TextInput(attrs={'placeholder': 'Ingrese un ruc'}),
            'business_name': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre de razón social'}),
            'tradename': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre comercial'}),
            'main_address': forms.TextInput(attrs={'placeholder': 'Ingrese una dirección principal'}),
            'establishment_address': forms.TextInput(attrs={'placeholder': 'Ingrese una dirección establecimiento'}),
            'issuing_point_code': forms.TextInput(attrs={'placeholder': 'Ingrese un código de punto de emisión'}),
            'establishment_code': forms.TextInput(attrs={'placeholder': 'Ingrese un código de establecimiento'}),
            'special_taxpayer': forms.TextInput(attrs={'placeholder': 'Ingrese un número de resolución'}),
            'obligated_accounting': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'environment_type': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'emission_type': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'retention_agent': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'mobile': forms.TextInput(attrs={'placeholder': 'Ingrese un teléfono celular'}),
            'phone': forms.TextInput(attrs={'placeholder': 'Ingrese un teléfono convencional'}),
            'email': forms.TextInput(attrs={'placeholder': 'Ingrese un email'}),
            'website': forms.TextInput(attrs={'placeholder': 'Ingrese una dirección web'}),
            'description': forms.TextInput(attrs={'placeholder': 'Ingrese una descripción'}),
            'iva': forms.TextInput(),
            'vat_percentage': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'electronic_signature_key': forms.PasswordInput(render_value=False, attrs={'placeholder': 'Ingrese la clave de la firma electrónica'}),
            'email_host': forms.TextInput(attrs={'placeholder': 'Ingrese el servidor de correo'}),
            'email_port': forms.TextInput(attrs={'placeholder': 'Ingrese el puerto de servidor de correo'}),
            'email_host_user': forms.TextInput(attrs={'placeholder': 'Ingrese el username del servidor de correo'}),
            'email_host_password': forms.PasswordInput(render_value=False, attrs={'placeholder': 'Ingrese el password del servidor de correo'}),
        }

    def _conservar_secreto(self, name):
        valor = self.cleaned_data.get(name) or ''
        if not valor and self.instance.pk is not None:
            actual = getattr(self.instance, name)
            return '' if actual is None else actual   # conserva también una clave guardada que no se pudo descifrar
        return valor

    def clean_electronic_signature_key(self):
        return self._conservar_secreto('electronic_signature_key')

    def clean_email_host_password(self):
        return self._conservar_secreto('email_host_password')

    def clean_electronic_signature(self):
        archivo = self.cleaned_data.get('electronic_signature')
        if 'electronic_signature' in self.changed_data and archivo:
            from core.suscripciones.servicios import tiene_plan
            if self.instance.pk is None or not tiene_plan(self.instance):
                raise forms.ValidationError('Para subir tu firma electrónica (.p12) primero activa un plan en «Plan y pagos».')
        return archivo

    def clean(self):
        cleaned = super().clean()
        for name in self.OPCIONALES[1:]:
            if cleaned.get(name) is None:
                cleaned[name] = ''
        return cleaned

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data


class PromotionsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['end_date'].widget.attrs['autofocus'] = True

    class Meta:
        model = Promotions
        fields = '__all__'
        widgets = {
            'start_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'start_date',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#start_date'
            }),
            'end_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'end_date',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#end_date'
            }),
        }
        exclude = ['state']

    date_range = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'autocomplete': 'off'
    }), label='Fecha de inicio y finalización')


class ReceiptForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['voucher_type'].widget.attrs['autofocus'] = True

    class Meta:
        model = Receipt
        fields = '__all__'
        widgets = {
            'voucher_type': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'establishment_code': forms.TextInput(attrs={'placeholder': 'Ingrese un número'}),
            'issuing_point_code': forms.TextInput(attrs={'placeholder': 'Ingrese un número'}),
            'sequence': forms.TextInput(attrs={'placeholder': 'Ingrese un número de secuencia'}),
        }

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data


class CreditNoteForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['sale'].queryset = Sale.objects.none()

    class Meta:
        model = CreditNote
        fields = '__all__'
        widgets = {
            'sale': forms.Select(attrs={'class': 'custom-select select2'}),
            'motive': forms.Textarea(attrs={
                'placeholder': 'Ingrese un motivo',
                'class': 'form-control',
                'autocomplete': 'off',
                'rows': 3,
                'cols': 3,
            }),
            'voucher_number_full': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'date_joined': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'date_joined',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#date_joined'
            }),
            'create_electronic_invoice': forms.CheckboxInput(attrs={
                'class': 'form-control-checkbox',
            }),
            'subtotal_0': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'disabled': True
            }),
            'subtotal_12': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'disabled': True
            }),
            'iva': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'disabled': True
            }),
            'total_iva': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'disabled': True
            }),
            'total_dscto': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'total': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'cash': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'change': forms.TextInput(attrs={
                'class': 'form-control',
                'readonly': True
            }),
        }


# ---------------------------------------------------------------- Compras completas (Etapa 2, O1: espec-etapa2-compras §4)

OPCIONES_SI_NO = (('', 'Elige si o no'), ('no', 'No'), ('si', 'Sí'))
MODOS_COMPROBANTE_COMPRA = (('si', 'Tengo el comprobante del proveedor'), ('liquidacion', 'Emitiré una liquidación de compra'),
                            ('despues', 'Completar después'))
TIPOS_DOC_MODIFICADO = (('', 'Elige el documento'), ('01', 'Factura'), ('02', 'Nota o boleta de venta'),
                        ('03', 'Liquidación de compra'))
IMPORTES_DE_LA_FACTURA = ('base_0', 'base_gravada', 'base_5', 'base_no_objeto', 'base_exenta', 'total_descuento', 'total_iva',
                          'total_ice', 'total_irbpnr', 'propina')


def _fecha_compra(id_campo):
    return forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control datetimepicker-input', 'id': id_campo,
                                                      'data-toggle': 'datetimepicker', 'data-target': f'#{id_campo}',
                                                      'autocomplete': 'off', 'placeholder': 'AAAA-MM-DD'})


def _importe(etiqueta, requerido=False):
    return forms.DecimalField(label=etiqueta, required=requerido, min_value=0, max_digits=12, decimal_places=2,
                              widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off',
                                                            'inputmode': 'decimal', 'placeholder': '0.00'}))


def _texto_corto(etiqueta, largo, ayuda=''):
    return forms.CharField(label=etiqueta, required=False, max_length=largo, help_text=ayuda,
                           widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}))


def _selector(etiqueta, opciones, vacio):
    return forms.ChoiceField(label=etiqueta, required=False, choices=[('', vacio)] + [tuple(o) for o in opciones if o[0]],
                             widget=forms.Select(attrs={'class': 'form-control'}))


class _CabeceraCompra(forms.Form):
    """Datos del comprobante del proveedor (detalleCompras del ATS). Solo tipos y formatos: las reglas de negocio están en
    core.pos.compras. Forma de pago y sustento empiezan vacíos (DC12)."""
    tipo_comprobante = _selector('Tipo de comprobante', TIPOS_COMPROBANTE_COMPRA, 'Elige el tipo de comprobante')
    cod_sustento = _selector('Sustento tributario', SUSTENTOS, 'Elige el sustento tributario')
    estab = _texto_corto('Establecimiento', 3, 'Tres dígitos, por ejemplo 001.')
    pto_emi = _texto_corto('Punto de emisión', 3, 'Tres dígitos, por ejemplo 002.')
    secuencial = _texto_corto('Secuencial', 9)
    autorizacion = _texto_corto('Autorización', 49, 'Clave de acceso de 49 dígitos, o la autorización del comprobante físico.')
    fecha_emision = forms.DateField(label='Fecha de emisión del comprobante', required=False, widget=_fecha_compra('fecha_emision'))
    forma_pago = _selector('Forma de pago (ATS)', FORMAS_PAGO, 'Elige la forma de pago')
    parte_relacionada = forms.ChoiceField(label='Parte relacionada', required=False, choices=OPCIONES_SI_NO,
                                          widget=forms.Select(attrs={'class': 'form-control'}))
    pago_loc_ext = _selector('Pago a residente o no residente', PAGO_LOC_EXT, 'Elige')
    tipo_doc_modificado = forms.ChoiceField(label='Tipo del documento modificado', required=False, choices=TIPOS_DOC_MODIFICADO,
                                            widget=forms.Select(attrs={'class': 'form-control'}))
    num_doc_modificado = _texto_corto('Número del documento modificado', 17, 'Por ejemplo 001-001-000000123.')
    aut_doc_modificado = _texto_corto('Autorización del documento modificado', 49)
    fecha_doc_modificado = forms.DateField(label='Fecha del documento modificado', required=False,
                                           widget=_fecha_compra('fecha_doc_modificado'))

    def datos(self):
        """Datos para core.pos.compras: los campos deshabilitados no se envían (el servicio conserva lo guardado)."""
        return {campo: valor for campo, valor in self.cleaned_data.items() if not self.fields[campo].disabled}


class CompraForm(_CabeceraCompra):
    """Cabecera de una compra nueva (§6.B): sustituye a PurchaseForm en la pantalla «Nueva compra». `lineas` llega en JSON."""
    provider = forms.IntegerField(label='Proveedor', required=False,
                                  widget=forms.Select(attrs={'class': 'custom-select select2', 'style': 'width: 100%;'}))
    modo_comprobante = forms.ChoiceField(label='Comprobante del proveedor', choices=MODOS_COMPROBANTE_COMPRA, initial='si',
                                         widget=forms.RadioSelect)
    date_joined = forms.DateField(label='Fecha de registro', required=False, initial=timezone.localdate,
                                  widget=_fecha_compra('date_joined'))
    payment_type = forms.ChoiceField(label='Tipo de pago', choices=PAYMENT_TYPE, initial=PAYMENT_TYPE[0][0],
                                     widget=forms.Select(attrs={'class': 'form-control'}))
    end_credit = forms.DateField(label='Fecha de plazo del crédito', required=False, widget=_fecha_compra('end_credit'))
    compra_modificada = forms.IntegerField(label='Compra que modifica', required=False,
                                           widget=forms.Select(attrs={'class': 'custom-select', 'style': 'width: 100%;'}))
    total_ice = _importe('ICE')
    propina = _importe('Propina')
    iva_factura = _importe('IVA que figura en la factura')
    confirmar_iva = forms.BooleanField(label='Confirmo el IVA de la factura aunque difiere del calculado por líneas',
                                       required=False)
    confirmar_plazo_ats = forms.BooleanField(label='Confirmo registrar la factura aunque tiene más de un año (fuera del ATS)',
                                             required=False)
    lineas = forms.CharField(required=False, widget=forms.HiddenInput)

    field_order = ('provider', 'date_joined', 'payment_type', 'end_credit', 'modo_comprobante', 'tipo_comprobante',
                   'cod_sustento', 'estab', 'pto_emi', 'secuencial', 'autorizacion', 'fecha_emision', 'forma_pago',
                   'parte_relacionada', 'pago_loc_ext')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # La liquidación de compra (03) se registra con el modo «Liquidación», no como tipo de comprobante.
        self.fields['tipo_comprobante'].choices = [c for c in self.fields['tipo_comprobante'].choices if c[0] != '03']
        self.fields['iva_factura'].help_text = 'Opcional: si lo escribes, manda el de la factura (se confirma si difiere).'

    def clean_lineas(self):
        import json
        texto = self.cleaned_data.get('lineas') or '[]'
        try:
            lineas = json.loads(texto)
        except ValueError:
            raise forms.ValidationError('Las líneas de la compra no tienen un formato válido.')
        if not isinstance(lineas, list) or not all(isinstance(linea, dict) for linea in lineas):
            raise forms.ValidationError('Las líneas de la compra no tienen un formato válido.')
        return lineas

    def datos(self):
        datos = super().datos()
        datos.pop('lineas', None)
        return datos


class CompletarCompraForm(_CabeceraCompra):
    """«Completar datos» de una compra (§6.C). Proveedor y fecha de registro no se cambian. Los importes solo existen en
    las compras anteriores (version_datos=1); los campos bloqueados (XML, retención o liquidación) se muestran
    deshabilitados y no se envían al servicio."""
    compra_modificada = forms.ChoiceField(label='Compra que modifica', required=False, choices=(),
                                          widget=forms.Select(attrs={'class': 'form-control'}))
    base_0 = _importe('Base 0 %')
    base_gravada = _importe('Base gravada (15 % o 12 %)')
    base_5 = _importe('Base 5 %')
    base_no_objeto = _importe('Base no objeto de IVA')
    base_exenta = _importe('Base exenta de IVA')
    total_descuento = _importe('Total descuento')
    total_iva = _importe('IVA')
    total_ice = _importe('ICE')
    total_irbpnr = _importe('IRBPNR')
    propina = _importe('Propina')
    confirmar_diferencia = forms.BooleanField(label='Confirmo los importes aunque no suman el subtotal registrado',
                                              required=False)
    confirmar_iva = forms.BooleanField(label='Confirmo el IVA aunque no corresponde a la tarifa general', required=False)
    confirmar_plazo_ats = forms.BooleanField(label='Confirmo que la factura tiene más de un año (queda fuera del ATS)',
                                             required=False)
    ajustar_cxp = forms.BooleanField(label='Ajustar la cuenta por pagar al total con IVA', required=False)

    def __init__(self, *args, compra, bloqueados=(), puede_ajustar_cxp=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.compra = compra
        if compra.version_datos != 1:
            for campo in IMPORTES_DE_LA_FACTURA:
                del self.fields[campo]
        if not puede_ajustar_cxp:
            del self.fields['ajustar_cxp']
        opciones = [('', 'Sin enlazar a una compra registrada')]
        candidatas = (Purchase.objects.filter(provider_id=compra.provider_id).exclude(pk=compra.pk)
                      .exclude(tipo_comprobante__in=('04', '05')).order_by('-date_joined', '-pk')[:200])
        ids = set()
        for otra in candidatas:
            ids.add(otra.pk)
            opciones.append((str(otra.pk), f'#{otra.pk} · {otra.numero_comprobante} · {otra.date_joined:%d/%m/%Y}'))
        if compra.compra_modificada_id and compra.compra_modificada_id not in ids:
            opciones.append((str(compra.compra_modificada_id), f'#{compra.compra_modificada_id}'))
        self.fields['compra_modificada'].choices = opciones
        if not self.is_bound:
            self.initial.update(self.iniciales(compra))
        for campo in bloqueados:
            if campo in self.fields:
                self.fields[campo].disabled = True
                self.fields[campo].initial = self.iniciales(compra).get(campo)

    @staticmethod
    def iniciales(compra):
        valores = {campo: getattr(compra, campo) for campo in (
            'tipo_comprobante', 'cod_sustento', 'estab', 'pto_emi', 'secuencial', 'autorizacion', 'fecha_emision', 'forma_pago',
            'pago_loc_ext', 'tipo_doc_modificado', 'num_doc_modificado', 'aut_doc_modificado', 'fecha_doc_modificado')}
        valores['parte_relacionada'] = '' if compra.parte_relacionada is None else ('si' if compra.parte_relacionada else 'no')
        valores['compra_modificada'] = str(compra.compra_modificada_id or '')
        for campo in IMPORTES_DE_LA_FACTURA:
            valor = getattr(compra, campo)
            valores[campo] = '' if valor is None else f'{valor:.2f}'
        return valores


# ---------------------------------------------------------------- Compra desde un XML importado (O1: espec §3.6 y §6.G)

MODOS_LINEA_IMPORTADA = (('gasto', 'Gasto (sin producto)'), ('producto', 'Producto del inventario'))


class CompraDesdeDocumentoForm(forms.Form):
    """Cabecera de la compra que se crea desde un documento importado (§6.G). Lo que trae el XML (numeración,
    autorización, fecha e importes) no se edita; el sustento empieza vacío (la sugerencia es solo texto, DC12) y la
    forma de pago solo se precarga si el XML trae pagos. Celular, correo y parte relacionada crean el proveedor cuando
    el documento no lo tiene."""
    cod_sustento = _selector('Sustento tributario', SUSTENTOS, 'Elige el sustento tributario')
    date_joined = forms.DateField(label='Fecha de registro', required=False, widget=_fecha_compra('date_joined'))
    payment_type = forms.ChoiceField(label='Tipo de pago', choices=PAYMENT_TYPE, widget=forms.Select(attrs={'class': 'form-control'}))
    end_credit = forms.DateField(label='Fecha de plazo del crédito', required=False, widget=_fecha_compra('end_credit'))
    forma_pago = _selector('Forma de pago (ATS)', FORMAS_PAGO, 'Sin forma de pago (completar después)')
    parte_relacionada = forms.ChoiceField(label='Parte relacionada', required=False, choices=OPCIONES_SI_NO,
                                          widget=forms.Select(attrs={'class': 'form-control'}))
    agrupar_por_tarifa = forms.BooleanField(label='Registrar una línea de gasto por tarifa de IVA (sin productos)', required=False)
    type_expense = forms.ChoiceField(label='Tipo de gasto de las líneas agrupadas', required=False, choices=(),
                                     widget=forms.Select(attrs={'class': 'form-control'}))
    confirmar_sin_verificar = forms.BooleanField(label='Crear la compra aunque el documento no esté verificado en el SRI',
                                                 required=False)
    confirmar_plazo_ats = forms.BooleanField(label='Confirmo registrar la factura aunque tiene más de un año (fuera del ATS)',
                                             required=False)
    mobile = forms.CharField(label='Celular del proveedor', required=False, max_length=10,
                             widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}))
    email = forms.EmailField(label='Correo del proveedor', required=False, max_length=50,
                             widget=forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'off'}))

    def __init__(self, *args, tipos_gasto=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['type_expense'].choices = [('', 'Sin tipo de gasto')] + [(str(t.pk), t.name) for t in tipos_gasto]

    def datos(self):
        """Datos para importacion.compras.crear_compra_desde_documento (las fechas como texto ISO)."""
        datos = {}
        for campo, valor in self.cleaned_data.items():
            if campo in ('mobile', 'email'):
                continue
            datos[campo] = valor.isoformat() if hasattr(valor, 'isoformat') else valor
        datos['proveedor_nuevo'] = {'mobile': self.cleaned_data.get('mobile') or '', 'email': self.cleaned_data.get('email') or '',
                                    'parte_relacionada': self.cleaned_data.get('parte_relacionada') or ''}
        return datos


class LineaCompraForm(forms.Form):
    """Elección del usuario para una línea del XML: gasto o producto (con «Recordar» la equivalencia del proveedor)."""
    indice = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    modo = forms.ChoiceField(label='Registrar como', choices=MODOS_LINEA_IMPORTADA, initial='gasto',
                             widget=forms.Select(attrs={'class': 'form-control form-control-sm'}))
    product = forms.ChoiceField(label='Producto', required=False, choices=(),
                                widget=forms.Select(attrs={'class': 'form-control form-control-sm'}))
    type_expense = forms.ChoiceField(label='Tipo de gasto', required=False, choices=(),
                                     widget=forms.Select(attrs={'class': 'form-control form-control-sm'}))
    recordar = forms.BooleanField(label='Recordar este producto para el código del proveedor', required=False)

    def __init__(self, *args, productos=(), tipos_gasto=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].choices = [('', 'Elige el producto')] + [(str(p.pk), f'{p.code} · {p.name}') for p in productos]
        self.fields['type_expense'].choices = [('', 'Sin tipo de gasto')] + [(str(t.pk), t.name) for t in tipos_gasto]

    def eleccion(self):
        datos = self.cleaned_data
        return {'indice': datos['indice'], 'modo': datos.get('modo') or 'gasto', 'product': datos.get('product') or None,
                'type_expense': datos.get('type_expense') or None, 'recordar': bool(datos.get('recordar'))}


LineasCompraFormSet = forms.formset_factory(LineaCompraForm, extra=0)
