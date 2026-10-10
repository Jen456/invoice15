from crum import get_current_request
from django import forms
from django.contrib.auth import password_validation, update_session_auth_hash
from django.contrib.auth.models import Group
from django.db import transaction

from core.tenancy.models import Membership, audit
from core.tenancy.users import assignable_roles, can_manage_identity
from .models import User


class UserForm(forms.ModelForm):
    """Usuario de la empresa activa: identidad + membresía (rol y estado)."""
    groups = forms.ModelChoiceField(queryset=Group.objects.none(), label='Rol en la empresa',
                                    widget=forms.Select(attrs={'class': 'select2', 'style': 'width:100%'}))
    is_active = forms.BooleanField(required=False, initial=True, label='Activo en la empresa',
                                   widget=forms.CheckboxInput(attrs={'class': 'form-control-checkbox'}))
    password = forms.CharField(required=False, label='Contraseña', strip=False,
                               widget=forms.PasswordInput(render_value=False, attrs={'placeholder': 'Ingrese un password'}))

    IDENTITY_FIELDS = ('names', 'username', 'password', 'email', 'image')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = get_current_request()
        self.company = self.request.company
        self.fields['groups'].queryset = assignable_roles(self.request)
        self.membership = None
        if self.instance.pk is not None:
            self.membership = Membership.objects.filter(user=self.instance, company=self.company).first()
            if self.membership is not None:
                self.fields['groups'].initial = self.membership.group_id
                self.fields['is_active'].initial = self.membership.is_active
            self.fields['password'].help_text = 'Déjala vacía para no cambiarla.'
        self.manage_identity = can_manage_identity(self.instance, self.company)
        if not self.manage_identity:
            for name in self.IDENTITY_FIELDS:
                self.fields[name].disabled = True
                self.fields[name].required = False
            self.fields['groups'].help_text = 'Usuario compartido con otras empresas: aquí solo se cambia su rol y estado.'
        self.fields['names'].widget.attrs['autofocus'] = True

    field_order = ['names', 'username', 'password', 'email', 'groups', 'image', 'is_active']

    class Meta:
        model = User
        # La contraseña no es campo del modelo aquí: se fija con set_password solo si se escribe.
        fields = 'names', 'username', 'email', 'image'
        widgets = {
            'names': forms.TextInput(attrs={'placeholder': 'Ingrese sus nombres'}),
            'username': forms.TextInput(attrs={'placeholder': 'Ingrese un username'}),
            'email': forms.TextInput(attrs={'placeholder': 'Ingrese su correo electrónico'}),
        }

    def clean_password(self):
        password = self.cleaned_data.get('password') or ''
        if not self.manage_identity:
            return ''
        if self.instance.pk is None and not password:
            raise forms.ValidationError('La contraseña es obligatoria para un usuario nuevo.')
        if password:
            password_validation.validate_password(password, self.instance)
        return password

    def update_session(self, user):
        request = get_current_request()
        if user == request.user:
            update_session_auth_hash(request, user)

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                with transaction.atomic():
                    user = self.instance
                    if self.manage_identity:
                        user = super().save(commit=False)
                        password = self.cleaned_data['password']
                        if password:
                            user.set_password(password)
                        user.save()
                    created = self.membership is None
                    Membership.objects.update_or_create(
                        user=user, company=self.company,
                        defaults={'group': self.cleaned_data['groups'], 'is_active': self.cleaned_data['is_active']})
                    audit(self.request, 'membership_add' if created else 'membership_change', company=self.company,
                          usuario=user.username, rol=self.cleaned_data['groups'].name,
                          activo=self.cleaned_data['is_active'])
                    self.update_session(user)
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data


class ProfileForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['names'].widget.attrs['autofocus'] = True

    class Meta:
        model = User
        fields = 'names', 'username', 'email', 'image'
        widgets = {
            'names': forms.TextInput(attrs={'placeholder': 'Ingrese sus nombres'}),
            'username': forms.TextInput(attrs={'placeholder': 'Ingrese un username'}),
            'email': forms.TextInput(attrs={'placeholder': 'Ingrese su correo electrónico'}),
        }
        exclude = ['is_change_password', 'is_active', 'is_staff', 'user_permissions', 'password', 'date_joined', 'last_login', 'is_superuser', 'groups', 'email_reset_token']

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
