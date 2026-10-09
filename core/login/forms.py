from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from core.user.models import User


class ResetPasswordForm(forms.Form):
    username = forms.CharField(widget=forms.TextInput(attrs={
        'placeholder': 'Tu usuario',
        'class': 'form-control',
        'autocomplete': 'username',
        'autocapitalize': 'none',
        'autofocus': True,
    }), label='Usuario')

    def clean(self):
        cleaned = super().clean()
        user = User.objects.filter(username=cleaned['username']).first()
        if user is None:
            raise forms.ValidationError('El username no existe')
        return cleaned

    def get_user(self):
        username = self.cleaned_data['username']
        return User.objects.get(username=username)


class UpdatePasswordForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Nueva contraseña',
        'class': 'form-control',
        'autocomplete': 'new-password'
    }), label='Nueva contraseña')

    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Repite la contraseña',
        'class': 'form-control',
        'autocomplete': 'new-password'
    }), label='Repite la contraseña')

    def clean(self):
        cleaned = super().clean()
        password = cleaned['password']
        confirm_password = cleaned['confirm_password']
        if password != confirm_password:
            raise forms.ValidationError('Las contraseñas deben ser iguales')
        # Mismas reglas que el resto de la aplicación (longitud mínima, comunes, numéricas).
        password_validation.validate_password(password)
        return cleaned


class IdentifierAuthenticationForm(AuthenticationForm):
    """Login con usuario, correo o RUC/cédula (ver core/login/backends.py)."""
    error_messages = {
        'invalid_login': 'Los datos de acceso no coinciden. Revisa tu usuario, correo o RUC/cédula y la contraseña.',
        'inactive': 'Esta cuenta está desactivada. Comunícate con el propietario de tu empresa.',
        'pending': 'Tu cuenta aún no está confirmada. Abre el enlace que te enviamos por correo o pide uno nuevo.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Usuario, correo o RUC/cédula'

    def confirm_login_allowed(self, user):
        if not user.is_active:
            if registro_pendiente(user):
                raise forms.ValidationError(self.error_messages['pending'], code='pending')
            raise forms.ValidationError(self.error_messages['inactive'], code='inactive')


def registro_pendiente(user):
    """¿Cuenta creada por registro propio que aún no confirmó su correo?"""
    from core.tenancy.models import AuditLog
    return not user.is_active and user.email_verified_at is None \
        and AuditLog.objects.filter(user=user, action='signup').exists()


ATTRS = {'class': 'form-control'}


class RegistroForm(forms.Form):
    nombre = forms.CharField(label='Nombre o razón social', max_length=50, widget=forms.TextInput(attrs={
        **ATTRS, 'autocomplete': 'organization', 'placeholder': 'Como figura en el SRI'}))
    identificacion = forms.CharField(label='RUC o cédula', max_length=13, widget=forms.TextInput(attrs={
        **ATTRS, 'inputmode': 'numeric', 'autocomplete': 'off', 'placeholder': '10 o 13 dígitos'}))
    email = forms.EmailField(label='Correo electrónico', max_length=100, widget=forms.EmailInput(attrs={
        **ATTRS, 'autocomplete': 'email', 'placeholder': 'nombre@empresa.com'}))
    celular = forms.CharField(label='Celular', max_length=20, widget=forms.TextInput(attrs={
        **ATTRS, 'inputmode': 'tel', 'autocomplete': 'tel', 'placeholder': '09XXXXXXXX'}))
    username = forms.CharField(label='Nombre de usuario', max_length=30, widget=forms.TextInput(attrs={
        **ATTRS, 'autocomplete': 'username', 'autocapitalize': 'none', 'spellcheck': 'false',
        'placeholder': 'Para ingresar al sistema'}))
    password = forms.CharField(label='Contraseña', strip=False, widget=forms.PasswordInput(attrs={
        **ATTRS, 'autocomplete': 'new-password', 'placeholder': 'Mínimo 10 caracteres'}))
    password2 = forms.CharField(label='Repite la contraseña', strip=False, widget=forms.PasswordInput(attrs={
        **ATTRS, 'autocomplete': 'new-password', 'placeholder': 'Repite la contraseña'}))
    acepto = forms.BooleanField(label='Acepto que FacturaPorAquí use estos datos para crear y administrar mi cuenta.')
    # Campo trampa: invisible para las personas; los robots suelen rellenarlo.
    sitio_web = forms.CharField(required=False, widget=forms.TextInput(attrs={'tabindex': '-1', 'autocomplete': 'off'}))

    def clean_identificacion(self):
        from core.login.identificacion import solo_digitos, tipo_identificacion
        from core.pos.models import Company
        numero = solo_digitos(self.cleaned_data['identificacion'])
        if tipo_identificacion(numero) is None:
            raise forms.ValidationError('Escribe una cédula (10 dígitos) o un RUC (13 dígitos) válido.')
        if Company.objects.filter(ruc=numero).exists():
            raise forms.ValidationError('Ya existe una empresa con este RUC o cédula. Pide acceso a su propietario.')
        return numero

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Ya existe una cuenta con este correo. Si es tuya, ingresa o recupera el acceso.')
        return email

    def clean_celular(self):
        from core.login.identificacion import normalizar_celular
        celular = normalizar_celular(self.cleaned_data['celular'])
        if celular is None:
            raise forms.ValidationError('Escribe un celular de Ecuador: 09 seguido de 8 dígitos.')
        return celular

    def clean_username(self):
        import re
        username = self.cleaned_data['username'].strip()
        if not re.fullmatch(r'(?=.*[A-Za-z])[A-Za-z0-9._-]{4,30}', username):
            raise forms.ValidationError('Usa de 4 a 30 caracteres: letras (al menos una), números, punto, guion o guion bajo.')
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Ese nombre de usuario ya está en uso.')
        return username

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('sitio_web'):
            raise forms.ValidationError('No se pudo completar el registro.')
        password, password2 = cleaned.get('password'), cleaned.get('password2')
        if password and password2 and password != password2:
            self.add_error('password2', 'Las contraseñas no coinciden.')
        elif password:
            candidato = User(username=cleaned.get('username') or '', email=cleaned.get('email') or '',
                             names=cleaned.get('nombre') or '')
            try:
                password_validation.validate_password(password, candidato)
            except forms.ValidationError as error:
                self.add_error('password', error)
        return cleaned


class ReenviarConfirmacionForm(forms.Form):
    email = forms.EmailField(label='Correo electrónico', max_length=100, widget=forms.EmailInput(attrs={
        **ATTRS, 'autocomplete': 'email', 'placeholder': 'El correo con el que te registraste'}))
