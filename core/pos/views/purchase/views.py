"""Compras: listado, compra nueva con los datos del comprobante (ATS), completar datos y eliminar (espec-etapa2-compras §4,
§6.A–§6.C). Las reglas de negocio están en core.pos.compras; aquí solo se leen los datos de la petición y se responde.

Respuestas JSON como el resto de pos: {} o {"error": "…"} con estado 200; 403 cuando falta un permiso (lo da el mixin).
Importes nuevos como texto ("135.00") o null."""
import json

from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import DeleteView, FormView, TemplateView

from core.pos import compras
from core.pos.catalogos_sri import SUSTENTOS, nombre
from core.pos.forms import (IMPORTES_DE_LA_FACTURA, CompletarCompraForm, CompraForm, DebtsPay, Product, Provider,
                            ProviderForm, Purchase, PurchaseDetail, TypeExpense)
from core.reports.forms import ReportForm
from core.security.mixins import GroupPermissionMixin
from core.security.session import get_group

URL_GASTO = '/pos/purchase/add/?tipo=gasto'
CAMPOS_CABECERA_COMPLETAR = ('tipo_comprobante', 'cod_sustento', 'estab', 'pto_emi', 'secuencial', 'autorizacion',
                             'fecha_emision', 'forma_pago', 'parte_relacionada', 'pago_loc_ext', 'tipo_doc_modificado',
                             'num_doc_modificado', 'aut_doc_modificado', 'fecha_doc_modificado', 'compra_modificada')
CONFIRMACIONES_COMPLETAR = ('confirmar_diferencia', 'confirmar_iva', 'confirmar_plazo_ats')


def respuesta(data, status=200):
    return HttpResponse(json.dumps(data), content_type='application/json', status=status)


def permisos(request, *codigos):
    """{codigo: bool} según los permisos del perfil en la empresa activa."""
    grupo = get_group(request)
    tiene = set(grupo.permissions.filter(codename__in=codigos).values_list('codename', flat=True)) if grupo else set()
    return {codigo: codigo in tiene for codigo in codigos}


def _importe(valor):
    return compras.texto_importe(valor)


def detalle_de_compra(compra):
    """Acción `detalle` (una compra): cabecera con faltantes y clase, líneas, resumen por tarifa, cuenta por pagar con sus
    abonos, retención y liquidación vigentes y el XML importado del que salió."""
    from core.comprobantes import liquidaciones, retenciones
    from core.importacion.models import DocumentoImportado
    lineas = list(PurchaseDetail.objects.filter(purchase=compra).select_related('product__category', 'type_expense'))
    deuda = DebtsPay.objects.filter(purchase=compra).order_by('pk').first()
    cuenta = None
    if deuda is not None:
        abonos = deuda.abonos()
        cuenta = {'id': deuda.pk, 'debt': _importe(deuda.debt), 'saldo': _importe(deuda.saldo),
                  'pagado': _importe(deuda.pagado()),
                  'base_calculo': {'id': deuda.base_calculo, 'name': deuda.get_base_calculo_display()},
                  'abonos': [{**a, 'valor': _importe(a['valor'])} for a in abonos]}
    retencion = retenciones.retencion_vigente(compra)
    liquidacion = liquidaciones.liquidacion_vigente(compra)
    documento = DocumentoImportado.objects.filter(compra=compra).order_by('pk').first()
    return {
        'compra': compra.toJSON(detalle=True),
        'lineas': [linea.toJSON() for linea in lineas],
        'por_tarifa': [{**g, 'tarifa': _importe(g['tarifa']), 'base': _importe(g['base']), 'valor': _importe(g['valor'])}
                       for g in compras.resumen_por_tarifa(lineas)],
        'cuenta_por_pagar': cuenta,
        'retencion': {'id': retencion.pk, 'numero': retencion.voucher_number_full,
                      'estado': retencion.get_status_display()} if retencion else None,
        'liquidacion': {'id': liquidacion.pk, 'numero': liquidacion.voucher_number_full,
                        'estado': liquidacion.get_status_display()} if liquidacion else None,
        'documento_importado': {'id': documento.pk, 'url': reverse('importacion_documento', args=[documento.pk])}
        if documento else None,
    }


class PurchaseListView(GroupPermissionMixin, FormView):
    template_name = 'purchase/list.html'
    form_class = ReportForm
    permission_required = 'view_purchase'

    def compras_filtradas(self):
        post = self.request.POST
        return compras.filtrar_listado(Purchase.objects.select_related('provider'), inicio=post.get('start_date', ''),
                                       fin=post.get('end_date', ''), fecha=post.get('fecha') or 'registro',
                                       incompletas=post.get('incompletas') == '1')

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST.get('action', '')
        try:
            if action == 'search':
                data = [compra.toJSON() for compra in self.compras_filtradas().order_by('id')]
            elif action == 'totales':
                data = compras.totales_listado(self.compras_filtradas())
            elif action == 'search_detail_products':
                data = [linea.toJSON() for linea in PurchaseDetail.objects.filter(
                    purchase_id=request.POST['id']).select_related('product__category', 'type_expense')]
            elif action == 'detalle':
                compra = Purchase.objects.select_related('provider').filter(pk=request.POST.get('id') or 0).first()
                data = detalle_de_compra(compra) if compra else {'error': 'La compra no existe.'}
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data = {'error': str(e)}
        return respuesta(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tiene = permisos(self.request, 'add_purchase', 'change_purchase', 'delete_purchase')
        context.update({
            'title': 'Listado de Compras', 'create_url': reverse_lazy('purchase_create'), 'url_gasto': URL_GASTO,
            'puede_crear': tiene['add_purchase'], 'puede_completar': tiene['change_purchase'],
            'puede_eliminar': tiene['delete_purchase'],
            'permisos_listado': {'puede_crear': tiene['add_purchase'], 'puede_completar': tiene['change_purchase'],
                                 'puede_eliminar': tiene['delete_purchase']},
        })
        return context


def _texto_compra(compra):
    total = compra.total if compra.total is not None else compra.subtotal
    return f'#{compra.pk} · {compra.numero_comprobante} · {compra.date_joined:%d/%m/%Y} · ${total:.2f}'


class PurchaseCreateView(GroupPermissionMixin, TemplateView):
    """Nueva compra (§6.B): cabecera del comprobante, líneas de producto o de gasto con su tarifa y resumen calculado en el
    servidor. `?tipo=gasto` abre el formulario para una factura de gasto."""
    template_name = 'purchase/create.html'
    permission_required = 'add_purchase'
    success_url = reverse_lazy('purchase_list')

    def datos_de_la_peticion(self):
        form = CompraForm(self.request.POST)
        if not form.is_valid():
            campo, errores = next(iter(form.errors.items()))
            etiqueta = form.fields[campo].label if campo in form.fields else ''
            raise compras.ErrorCompra(f'{etiqueta}: {errores[0]}' if etiqueta else errores[0])
        return form.datos(), form.cleaned_data['lineas']

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', '')
        data = {}
        try:
            if action == 'calcular':
                datos, lineas = self.datos_de_la_peticion()
                data = compras.calcular(request.company, datos, lineas)
            elif action == 'add':
                datos, lineas = self.datos_de_la_peticion()
                compra = compras.crear_compra(request.company, request.user, datos, lineas)
                messages.success(request, f'Compra #{compra.pk} registrada.')
                data = {'id': compra.pk, 'advertencias': [{'codigo': c, 'texto': t} for c, t in compra.advertencias]}
            elif action == 'validate_comprobante':
                data = self.validar_comprobante(request.POST)
            elif action == 'search_product':
                data = []
                ids = json.loads(request.POST.get('ids') or '[]')
                term = request.POST.get('term', '')
                queryset = Product.objects.filter(inventoried=True).exclude(id__in=ids).select_related('category').order_by('name')
                if len(term):
                    queryset = queryset.filter(Q(name__icontains=term) | Q(code__icontains=term))
                    queryset = queryset[0:10]
                for i in queryset:
                    item = i.toJSON()
                    item['value'] = i.get_full_name()
                    data.append(item)
            elif action == 'search_provider':
                term = request.POST.get('term', '')
                data = [p.toJSON() for p in Provider.objects.filter(Q(name__icontains=term) | Q(ruc__icontains=term))
                        .order_by('name')[0:10]]
            elif action == 'validate_provider':
                data = {'valid': True}
                queryset = Provider.objects.all()
                pattern = request.POST.get('pattern', '')
                parameter = request.POST.get('parameter', '').strip()
                if pattern == 'name':
                    data['valid'] = not queryset.filter(name__iexact=parameter).exists()
                elif pattern == 'ruc':
                    data['valid'] = not queryset.filter(ruc=parameter).exists()
                elif pattern == 'mobile':
                    data['valid'] = not queryset.filter(mobile=parameter).exists()
                elif pattern == 'email':
                    data['valid'] = not queryset.filter(email=parameter).exists()
            elif action == 'create_provider':
                data = ProviderForm(request.POST).save()
            elif action == 'search_type_expense':
                term = request.POST.get('term', '')
                data = [{'id': t.pk, 'text': t.name, 'cod_sustento': t.cod_sustento}
                        for t in TypeExpense.objects.filter(name__icontains=term).order_by('name')[0:20]]
            elif action == 'search_compra_modificada':
                term = request.POST.get('term', '').strip()
                queryset = (Purchase.objects.filter(provider_id=request.POST.get('provider') or 0)
                            .exclude(tipo_comprobante__in=('04', '05')).order_by('-date_joined', '-pk'))
                if term:
                    queryset = queryset.filter(Q(secuencial__icontains=term) | Q(number__icontains=term))
                data = [{'id': c.pk, 'text': _texto_compra(c)} for c in queryset[0:20]]
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except compras.ErrorCompra as e:
            data = {'error': str(e)}
            if e.codigo in ('confirmar_iva', 'confirmar_plazo_ats'):
                data['confirmacion'] = e.codigo
        except Exception as e:
            data = {'error': str(e)}
        return respuesta(data)

    def validar_comprobante(self, post):
        """¿Ya está registrado ese comprobante del proveedor? Si hay un XML importado pendiente con ese número, se sugiere
        crear la compra desde Importación."""
        proveedor = Provider.objects.filter(pk=post.get('provider') or 0).first()
        tipo, estab, pto_emi, secuencial = (post.get(c, '').strip() for c in ('tipo_comprobante', 'estab', 'pto_emi', 'secuencial'))
        resultado = {'valid': True, 'compra_id': None, 'mensaje': '', 'documento_importado': None}
        if proveedor is None or not tipo:
            return resultado
        existente = compras.comprobante_registrado(proveedor.pk, tipo, estab, pto_emi, secuencial)
        if existente is not None:
            resultado.update({'valid': False, 'compra_id': existente.pk,
                              'mensaje': f'Ya registraste este comprobante (compra #{existente.pk}).'})
            return resultado
        documento = compras.documento_importado_pendiente(proveedor, tipo, estab, pto_emi, secuencial)
        if documento is not None:
            resultado.update({'mensaje': 'Este comprobante ya está en Importación: puedes crear la compra desde su XML.',
                              'documento_importado': {'id': documento.pk,
                                                      'url': reverse('importacion_documento', args=[documento.pk]),
                                                      'url_compra': reverse('importacion_compra', args=[documento.pk])}})
        return resultado

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tipo_inicial = 'gasto' if self.request.GET.get('tipo') == 'gasto' else 'inventario'
        sugerido = compras.sustento_gasto_sugerido(self.request.company)
        context.update({
            'title': 'Nueva compra de gasto' if tipo_inicial == 'gasto' else 'Nuevo registro de una Compra',
            'list_url': self.success_url, 'action': 'add', 'form': CompraForm(), 'frmProvider': ProviderForm(auto_id='fp_proveedor_%s'),
            'tipo_inicial': tipo_inicial, 'opciones': compras.opciones_formulario(),
            'sustento_gasto_sugerido': sugerido, 'nombre_sustento_sugerido': nombre(SUSTENTOS, sugerido),
            'hoy': timezone.localdate().isoformat(),
        })
        return context


class PurchaseCompleteView(GroupPermissionMixin, TemplateView):
    """Completar (o corregir) los datos del comprobante de una compra (§6.C): `revisar` muestra los cambios sin guardar;
    `completar` guarda con compras.completar_datos (auditado). Las líneas, el stock y el subtotal no cambian."""
    template_name = 'purchase/complete.html'
    permission_required = 'change_purchase'

    def get_compra(self):
        return get_object_or_404(Purchase.objects.select_related('provider'), pk=self.kwargs['pk'])

    def preparar(self, compra, datos=None):
        bloqueados, motivo, _ = compras.bloqueos_de(compra)
        deuda = DebtsPay.objects.filter(purchase=compra).order_by('pk').first()
        puede_ajustar = deuda is not None and deuda.base_calculo == 'subtotal'
        form = CompletarCompraForm(datos, compra=compra, bloqueados=bloqueados, puede_ajustar_cxp=puede_ajustar)
        return form, bloqueados, motivo, deuda, puede_ajustar

    def contexto(self, compra, form, bloqueados, motivo, deuda, puede_ajustar, resumen=None, codigo_error=''):
        lineas = list(PurchaseDetail.objects.filter(purchase=compra).select_related('product__category', 'type_expense'))
        cuenta = None
        if deuda is not None:
            cuenta = {'id': deuda.pk, 'debt': _importe(deuda.debt), 'saldo': _importe(deuda.saldo),
                      'pagado': _importe(deuda.pagado()),
                      'base_calculo': {'id': deuda.base_calculo, 'name': deuda.get_base_calculo_display()}}
        total_nuevo = (resumen or {}).get('total') or _importe(compra.total)
        confirmaciones = set((resumen or {}).get('confirmaciones') or [])
        confirmaciones.update(c for c in CONFIRMACIONES_COMPLETAR if c == codigo_error or (form.is_bound and form.data.get(c)))
        return self.get_context_data(
            campos_cabecera=CAMPOS_CABECERA_COMPLETAR, campos_importes=IMPORTES_DE_LA_FACTURA,
            campos_importes_visibles=compra.version_datos == 1, confirmaciones_visibles=sorted(confirmaciones),
            textos_confirmacion=(resumen or {}).get('textos_confirmacion') or {},
            title='Completar datos de la compra', compra=compra.toJSON(),
            lineas=[linea.toJSON() for linea in lineas], form=form, bloqueados=bloqueados, motivo_bloqueo=motivo,
            faltantes=[{'codigo': c, 'texto': t} for c, t in compras.faltantes(compra)], cuenta_por_pagar=cuenta,
            puede_ajustar_cxp=puede_ajustar, resumen=resumen, total_con_iva=total_nuevo,
            list_url=reverse('purchase_list'))

    def get(self, request, *args, **kwargs):
        compra = self.get_compra()
        return self.render_to_response(self.contexto(compra, *self.preparar(compra)))

    def post(self, request, *args, **kwargs):
        compra = self.get_compra()
        form, bloqueados, motivo, deuda, puede_ajustar = self.preparar(compra, request.POST)
        resumen, codigo_error = None, ''
        if form.is_valid():
            datos = form.datos()
            try:
                if request.POST.get('action') == 'completar':
                    compras.completar_datos(compra, request.user, datos, request=request)
                    messages.success(request, 'Datos de la compra guardados')
                    return HttpResponseRedirect(reverse('purchase_list'))
                resumen = compras.revisar_datos(compra, datos)
            except compras.ErrorCompra as e:
                form.add_error(None, str(e))
                codigo_error = e.codigo
        return self.render_to_response(self.contexto(compra, form, bloqueados, motivo, deuda, puede_ajustar, resumen,
                                                     codigo_error))


class PurchaseDeleteView(GroupPermissionMixin, DeleteView):
    """Elimina la compra con compras.eliminar_compra: revierte el stock, borra la cuenta por pagar sin pagos, devuelve a
    pendiente el XML importado y queda auditado. Rechaza si tiene pagos, retención, liquidación o notas que la modifican."""
    model = Purchase
    template_name = 'delete.html'
    success_url = reverse_lazy('purchase_list')
    permission_required = 'delete_purchase'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            compra = self.get_object()
        except Http404:                      # id de otra empresa o inexistente (§6: un id ajeno = 404)
            return respuesta({'error': 'La compra no existe.'}, status=404)
        try:
            compras.eliminar_compra(compra, request.user, request=request)
        except Exception as e:
            data['error'] = str(e)
        return respuesta(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Notificación de eliminación'
        context['list_url'] = self.success_url
        return context
