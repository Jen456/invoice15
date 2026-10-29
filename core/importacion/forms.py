"""Formularios de las pantallas de importación que tienen formulario de servidor."""
from django import forms


class RetencionRecibidaDesdeDocumentoForm(forms.Form):
    """«Registrar retención recibida» desde un 07 importado (espec-etapa2-compras §6.J): solo la confirmación explícita
    de registrar un documento que no está verificado en el SRI (cuando la regla de importación lo exige)."""
    confirmar_sin_verificar = forms.BooleanField(label='Registrar aunque el documento no esté verificado en el SRI', required=False)
