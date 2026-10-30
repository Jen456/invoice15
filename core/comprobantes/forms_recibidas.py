"""Formularios de las pantallas de la Etapa 2 (O2): retenciones recibidas de clientes y marca «Anulado en el SRI».

Funcionan sin JavaScript. Las reglas de negocio están en los servicios (core/comprobantes/retenciones_recibidas.py y
core/pos/anulados.py); aquí solo se valida la forma de los datos y las confirmaciones de la pantalla.
"""
from datetime import date
from decimal import Decimal

from django import forms
from django.utils import timezone

from core.comprobantes import retenciones as catalogo

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')   # <input type=date> solo acepta ISO


def leer_fecha(valor):
    """Fecha ISO escrita en el formulario, o None si falta o no es válida (para armar las opciones del catálogo)."""
    try:
        return date.fromisoformat(str(valor or '').strip())
    except ValueError:
        return None


def etiqueta_codigo(fila):
    """«Renta · 312 · Bienes muebles (2 %)» o «IVA · 1 · 30 %», con «(no disponible para emitir)» si está inactivo."""
    porcentaje = f'{fila.porcentaje.normalize():f}'.replace('.', ',')
    if fila.impuesto == '1':
        texto = f'Renta · {fila.codigo} · {(fila.concepto or "")[:90]} ({porcentaje} %)'
    else:
        texto = f'IVA · {fila.codigo} · {porcentaje} %'
    if not fila.activo:
        texto += ' (no disponible para emitir)'
    return texto


def opciones_codigo(fecha):
    """Una opción por pareja (impuesto, código), valor 'impuesto:codigo', con la fila vigente en `fecha` (función de B0;
    D0 le programa la vigencia). Si llegaran varias filas de la misma pareja, se queda la primera."""
    opciones, vistas = [('', '— Sin retención en esta línea —')], set()
    for fila in catalogo.codigos_retencion_vigentes(fecha, incluir_inactivos=True):
        pareja = (fila.impuesto, fila.codigo)
        if pareja in vistas:
            continue
        vistas.add(pareja)
        opciones.append((f'{fila.impuesto}:{fila.codigo}', etiqueta_codigo(fila)))
    return opciones


class RetencionRecibidaForm(forms.Form):
    numero = forms.CharField(label='Número de la retención', max_length=17, help_text='001-001-000000123')
    autorizacion = forms.CharField(label='Autorización', max_length=49,
                                   help_text='49 dígitos (clave de acceso), o 10 o 37 en comprobantes antiguos.')
    fecha_emision = forms.DateField(label='Fecha de emisión', widget=FECHA)
    emisor_ruc = forms.CharField(label='RUC del agente de retención', max_length=13, required=False,
                                 help_text='Vacío: el RUC del cliente de la factura.')
    notas = forms.CharField(label='Notas', max_length=300, required=False)

    def __init__(self, *args, pide_emisor_ruc=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not pide_emisor_ruc:   # el cliente se identifica con un RUC válido: el agente es el cliente
            del self.fields['emisor_ruc']


class LineaRecibidaForm(forms.Form):
    codigo = forms.ChoiceField(label='Retención', required=False)
    base_imponible = forms.DecimalField(label='Base imponible', required=False, max_digits=12, decimal_places=2,
                                        min_value=Decimal('0.01'))
    porcentaje = forms.DecimalField(label='%', required=False, max_digits=5, decimal_places=2, min_value=0, max_value=100,
                                    help_text='Vacío: el del catálogo vigente.')
    valor_retenido = forms.DecimalField(label='Valor retenido', required=False, max_digits=12, decimal_places=2,
                                        min_value=0, help_text='Vacío: base × porcentaje.')

    def __init__(self, *args, fecha=None, opciones=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['codigo'].choices = opciones if opciones is not None else opciones_codigo(fecha or timezone.localdate())

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('codigo') and any(cleaned.get(c) is not None for c in ('base_imponible', 'porcentaje',
                                                                                  'valor_retenido')):
            self.add_error('codigo', 'Elige el código de la retención de esta línea.')
        return cleaned

    def linea(self):
        """(impuesto, código, base, porcentaje, valor) de una línea con código, o None si la línea quedó vacía."""
        valor = self.cleaned_data.get('codigo') or ''
        if not valor:
            return None
        impuesto, _, codigo = valor.partition(':')
        return (impuesto, codigo, self.cleaned_data.get('base_imponible'), self.cleaned_data.get('porcentaje'),
                self.cleaned_data.get('valor_retenido'))


class BaseLineasRecibidas(forms.BaseFormSet):
    """Arma las opciones del catálogo una sola vez (con la `fecha` de form_kwargs) para todas las líneas."""

    def __init__(self, *args, form_kwargs=None, **kwargs):
        form_kwargs = dict(form_kwargs or {})
        form_kwargs['opciones'] = opciones_codigo(form_kwargs.pop('fecha', None) or timezone.localdate())
        super().__init__(*args, form_kwargs=form_kwargs, **kwargs)


# absolute_max = max_num: un POST con TOTAL_FORMS alto no arma más de 10 formularios (Django admite hasta 1000 + max_num).
LineasRecibidasFormSet = forms.formset_factory(LineaRecibidaForm, formset=BaseLineasRecibidas, extra=3, max_num=10,
                                               absolute_max=10, validate_max=True)


class AnuladoSRIForm(forms.Form):
    fecha = forms.DateField(label='Fecha de la anulación en el SRI', widget=FECHA)
    motivo = forms.CharField(label='Motivo', min_length=10, max_length=300, widget=forms.Textarea(attrs={'rows': 3}),
                             error_messages={'required': 'Escribe el motivo de la anulación (al menos 10 caracteres).',
                                             'min_length': 'Escribe el motivo de la anulación (al menos 10 caracteres).'})
    ajustar_stock = forms.BooleanField(label='Ajustar el inventario', required=False, initial=True)
    confirmar_numero = forms.CharField(label='Escribe el número del comprobante para confirmar', max_length=20)
    confirmo_sri = forms.BooleanField(
        label='Ya anulé este comprobante en SRI en línea y, si correspondía, el receptor aceptó la anulación',
        required=True, error_messages={'required': 'Confirma que ya lo anulaste en SRI en línea.'})
    confirmo_plazo = forms.BooleanField(required=False)

    def __init__(self, *args, numero, muestra_stock, limite_plazo, **kwargs):
        super().__init__(*args, **kwargs)
        self.numero, self.limite_plazo = numero, limite_plazo
        if not muestra_stock:
            del self.fields['ajustar_stock']
        self.fields['confirmo_plazo'].label = (f'La anulación es posterior al {limite_plazo:%d/%m/%Y}: confirmo que el SRI '
                                               'la aceptó')

    def clean_confirmar_numero(self):
        valor = (self.cleaned_data.get('confirmar_numero') or '').strip()
        if valor != self.numero:
            raise forms.ValidationError(f'Escribe el número {self.numero} para confirmar.')
        return valor

    def clean(self):
        cleaned = super().clean()
        fecha = cleaned.get('fecha')
        if fecha is not None and fecha > self.limite_plazo and not cleaned.get('confirmo_plazo'):
            self.add_error('confirmo_plazo', f'La fecha pasa del plazo del SRI ({self.limite_plazo:%d/%m/%Y}): confirma que '
                                             'el SRI aceptó la anulación.')
        return cleaned


class AnularRetencionRecibidaForm(forms.Form):
    motivo = forms.CharField(label='Motivo de la anulación', min_length=10, max_length=300,
                             widget=forms.Textarea(attrs={'rows': 3}),
                             error_messages={'required': 'Escribe el motivo (al menos 10 caracteres).',
                                             'min_length': 'Escribe el motivo (al menos 10 caracteres).'})
