"""Catálogo de retenciones en el panel de la plataforma (los porcentajes cambian por resolución del SRI).

Un cambio de porcentaje no edita la fila: «Nueva vigencia» cierra la fila abierta y crea la siguiente, siempre después
de hoy. Las filas cuya vigencia ya empezó no cambian de código, concepto, porcentaje, fechas ni fuente (lo emitido
guarda su propia copia, pero el catálogo conserva el rastro de cada valor). Ni el alta ni la edición de una vigencia
que aún no empieza escriben el pasado de un código que ya tiene filas: lo retroactivo va por migración, como 0015.
"""
from django import forms
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.utils import timezone

from core.comprobantes.models import CodigoRetencion, exigir_inicio_futuro
from core.tenancy.admin import plataforma
from core.tenancy.models import audit


class NuevaVigenciaForm(forms.Form):
    desde = forms.DateField(label='Vigente desde', widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                            help_text='Después de hoy. La fila abierta se cierra el día anterior. Lo ya emitido no cambia.')
    porcentaje = forms.DecimalField(label='Porcentaje', min_value=0, max_value=100, decimal_places=2, max_digits=5)
    porcentaje_editable = forms.BooleanField(label='Porcentaje variable (el emisor puede escribirlo)', required=False)
    fuente = forms.CharField(label='Fuente (resolución o tabla del SRI)', max_length=300,
                             widget=forms.TextInput(attrs={'size': 100}))
    ayuda = forms.CharField(label='Ayuda para el emisor', max_length=500, required=False,
                            widget=forms.Textarea(attrs={'rows': 4, 'cols': 100}))

    def clean_desde(self):
        exigir_inicio_futuro(self.cleaned_data['desde'])
        return self.cleaned_data['desde']


class CodigoRetencionForm(forms.ModelForm):
    """Alta y edición en el panel. En las filas cuya vigencia ya empezó las fechas son de solo lectura; en las demás
    (altas y vigencias que aún no empiezan) ninguna fecha reescribe lo que ya rigió."""

    class Meta:
        model = CodigoRetencion
        fields = '__all__'

    def clean(self):
        datos = super().clean()
        if self.instance.pk is not None and self.instance.vigencia_empezada:
            return datos   # fechas de solo lectura (get_readonly_fields)
        otras = (CodigoRetencion.objects.filter(impuesto=datos.get('impuesto'), codigo=datos.get('codigo'))
                 .exclude(pk=self.instance.pk))
        if otras.exists():   # otra vigencia de un código existente: como «Nueva vigencia», empieza después de hoy
            try:
                exigir_inicio_futuro(datos.get('vigente_desde'))
            except ValidationError as e:
                self.add_error('vigente_desde', e)
        hoy, hasta = timezone.localdate(), datos.get('vigente_hasta')
        if hasta is not None and hasta < hoy:
            self.add_error('vigente_hasta', f'La vigencia no puede terminar antes de hoy ({hoy:%d/%m/%Y}): '
                                            'el pasado del catálogo no se reescribe.')
        return datos


@admin.register(CodigoRetencion, site=plataforma)
class CodigoRetencionAdmin(admin.ModelAdmin):
    list_display = ('impuesto', 'codigo', 'concepto', 'porcentaje', 'porcentaje_editable', 'vigente_desde', 'vigente_hasta',
                    'comun', 'activo')
    list_filter = ('impuesto', 'activo', 'comun')
    list_editable = ('activo', 'comun')
    search_fields = ('codigo', 'concepto')
    actions = ('nueva_vigencia',)
    form = CodigoRetencionForm

    def get_readonly_fields(self, request, obj=None):
        # Ya pudo usarse al emitir: lo que cambia el cálculo o su rastro se corrige con «Nueva vigencia» (que es la que
        # cierra la fila, y queda en la auditoría), no editando la fila. Siguen editables la ayuda, el orden, el uso
        # común y «Disponible».
        if obj is not None and obj.vigencia_empezada:
            return ('impuesto', 'codigo', 'concepto', 'porcentaje', 'porcentaje_editable', 'vigente_desde', 'vigente_hasta',
                    'fuente')
        return ()

    def has_delete_permission(self, request, obj=None):
        return False   # se desactiva (activo = no) para conservar el histórico de lo ya emitido

    @admin.action(description='Nueva vigencia del código seleccionado (cierra la fila abierta)')
    def nueva_vigencia(self, request, queryset):
        codigos = set(queryset.values_list('impuesto', 'codigo'))
        if len(codigos) != 1:
            self.message_user(request, 'Elige filas de un solo código.', messages.ERROR)
            return None
        impuesto, codigo = codigos.pop()
        abierta = CodigoRetencion.objects.filter(impuesto=impuesto, codigo=codigo, vigente_hasta__isnull=True).first()
        if abierta is None:
            self.message_user(request, f'El código {codigo} no tiene una vigencia abierta.', messages.ERROR)
            return None
        form = NuevaVigenciaForm(request.POST if 'aplicar' in request.POST else None, initial={
            'porcentaje': abierta.porcentaje, 'porcentaje_editable': abierta.porcentaje_editable, 'fuente': abierta.fuente,
            'ayuda': abierta.ayuda})
        if form.is_bound and form.is_valid():
            datos = form.cleaned_data
            try:
                nueva = abierta.nueva_vigencia(**datos)
            except ValidationError as e:
                form.add_error(None, ' '.join(e.messages))
            else:
                audit(request, 'catalogo_vigencia_nueva', company=None, impuesto=impuesto, codigo=codigo, cerrada=abierta.pk,
                      nueva=nueva.pk, desde=datos['desde'].isoformat(), porcentaje=str(nueva.porcentaje),
                      porcentaje_editable=nueva.porcentaje_editable, porcentaje_anterior=str(abierta.porcentaje),
                      fuente=nueva.fuente)
                self.message_user(request, f'Código {codigo}: nueva vigencia desde el {nueva.vigente_desde:%d/%m/%Y} '
                                           f'({nueva.porcentaje} %); la anterior queda hasta el {abierta.vigente_hasta:%d/%m/%Y}.',
                                  messages.SUCCESS)
                return None
        return render(request, 'comprobantes/admin_nueva_vigencia.html', {
            **self.admin_site.each_context(request), 'title': f'Nueva vigencia del código {codigo}', 'form': form,
            'abierta': abierta, 'opts': self.model._meta, 'seleccion': queryset.values_list('pk', flat=True),
            'casilla': helpers.ACTION_CHECKBOX_NAME,
        })
