from django import forms

from .models import *


class ModuleTypeForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['autofocus'] = True

    class Meta:
        model = ModuleType
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre'}),
            'icon': forms.TextInput(attrs={'placeholder': 'ingrese un icono de font awesone'}),
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


class ModuleForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['url'].widget.attrs['autofocus'] = True

    class Meta:
        model = Module
        fields = '__all__'
        widgets = {
            'url': forms.TextInput(attrs={'placeholder': 'Ingrese una url'}),
            'module_type': forms.Select(attrs={'class': 'form-control select2', 'required': False, 'style': 'width:100%'}),
            'name': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre'}),
            'description': forms.TextInput(attrs={'placeholder': 'Ingrese una descripción'}),
            'icon': forms.TextInput(attrs={'placeholder': 'ingrese un icono de font awesone'}),
            'permissions': forms.SelectMultiple(attrs={'class': 'form-control select2', 'multiple': 'multiple', 'style': 'width:100%'}),
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


class GroupForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['autofocus'] = True

    class Meta:
        model = Group
        fields = 'name',
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre', 'class': 'form-control'}),
        }


class DashboardForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['layout'].widget.attrs['autofocus'] = True

    class Meta:
        model = Dashboard
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre'}),
            'author': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre de autor'}),
            'icon': forms.TextInput(attrs={'placeholder': 'Ingrese un icono de font awesome'}),
            'layout': forms.Select(attrs={'class': 'form-control select2', 'style': 'width:100%'}),
            'navbar': forms.Select(attrs={'class': 'form-control select2', 'style': 'width:100%'}),
            'brand_logo': forms.Select(attrs={'class': 'form-control select2', 'style': 'width:100%'}),
            'card': forms.Select(attrs={'class': 'form-control select2', 'style': 'width:100%'}),
            'sidebar': forms.Select(attrs={'class': 'form-control select2', 'style': 'width:100%'}),
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
