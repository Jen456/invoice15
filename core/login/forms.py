from django import forms
from django.contrib.auth import password_validation

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
