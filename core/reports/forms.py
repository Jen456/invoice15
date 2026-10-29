from django import forms

from core.pos.consultas import ALCANCES
from core.pos.models import Product, Receipt


class ReportForm(forms.Form):
    date_range = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'autocomplete': 'off'
    }), label='Buscar por rango de fechas')

    sale = forms.ChoiceField(widget=forms.Select(attrs={
        'class': 'form-control select2',
        'style': 'width: 100%;'
    }), label='Venta')

    product = forms.ModelChoiceField(widget=forms.SelectMultiple(attrs={
        'class': 'form-control select2',
    }), queryset=Product.objects.all(), label='Producto')

    receipt = forms.ModelChoiceField(widget=forms.Select(attrs={
        'class': 'form-control select2',
        'style': 'width: 100%;'
    }), queryset=Receipt.objects.all().order_by('id'), label='Comprobante')

    # Etapa 2 (O2): qué comprobantes muestran los reportes de ventas, cuentas por cobrar y resultados (core/pos/consultas.py).
    alcance = forms.ChoiceField(choices=ALCANCES, required=False, initial='declarables', label='Comprobantes',
                                widget=forms.Select(attrs={'class': 'form-control', 'style': 'width: 100%;'}))
