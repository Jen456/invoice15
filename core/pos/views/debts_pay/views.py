"""Cuentas por pagar (espec-etapa2-compras §4 y §6.E): listado sin consultas por fila, pagos con medio de pago y
referencia, abonos por retención y nota de crédito, y borrados que exigen delete_debts_pay (403 sin él) y quedan
auditados. Las reglas están en core.pos.cuentas_por_pagar."""
import json

from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, FormView

from core.adjuntos import registro as adjuntos
from core.pos import cuentas_por_pagar
from core.pos.forms import DebtsPay, PaymentsDebtsPay, PaymentsDebtsPayForm
from core.reports.forms import ReportForm
from core.security.mixins import GroupPermissionMixin

TIPOS_DE_ABONO = {'retencion': 'Retención emitida', 'nota_credito': 'Nota de crédito del proveedor'}


def respuesta(data, status=200):
    return HttpResponse(json.dumps(data), content_type='application/json', status=status)


def movimientos(request, deuda):
    """Acción search_pays: pagos (borrables solo con delete_debts_pay) y abonos calculados (retenciones que cuentan y notas
    de crédito del proveedor), que no se borran desde aquí. Importes como texto."""
    puede = cuentas_por_pagar.puede_eliminar(request)
    filas = []
    for pago in PaymentsDebtsPay.objects.filter(debts_pay=deuda).order_by('id'):
        filas.append({'tipo': 'pago', 'id': pago.pk, 'date_joined': pago.date_joined.strftime('%Y-%m-%d'),
                      'valor': f'{pago.valor:.2f}',
                      'medio_pago': {'id': pago.medio_pago, 'name': pago.get_medio_pago_display() if pago.medio_pago else 'Sin dato'},
                      'referencia': pago.referencia, 'description': pago.description or '', 'puede_borrar': puede})
    for abono in deuda.abonos():
        filas.append({'tipo': abono['tipo'], 'id': abono['id'], 'date_joined': abono['fecha'], 'valor': f"{abono['valor']:.2f}",
                      'medio_pago': {'id': '', 'name': 'No aplica'}, 'referencia': abono['numero'],
                      'description': TIPOS_DE_ABONO[abono['tipo']], 'puede_borrar': False})
    for indice, fila in enumerate(filas, start=1):
        fila['index'] = indice
    return filas


class DebtsPayListView(GroupPermissionMixin, FormView):
    template_name = 'debts_pay/list.html'
    form_class = ReportForm
    permission_required = 'view_debts_pay'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST.get('action', '')
        try:
            if action == 'search':
                queryset = DebtsPay.con_pagado(DebtsPay.objects.select_related('purchase__provider'))
                start_date = request.POST.get('start_date', '')
                end_date = request.POST.get('end_date', '')
                if len(start_date) and len(end_date):
                    queryset = queryset.filter(date_joined__range=[start_date, end_date])
                data = [deuda.toJSON() for deuda in queryset.order_by('id')]
            elif action == 'search_pays':
                deuda = DebtsPay.objects.select_related('purchase__provider').filter(pk=request.POST.get('id') or 0).first()
                data = movimientos(request, deuda) if deuda else {'error': 'La cuenta por pagar no existe.'}
            elif action == 'delete_pay':
                cuentas_por_pagar.eliminar_pago(request, request.POST.get('id') or 0)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except cuentas_por_pagar.SinPermiso as e:
            return respuesta({'error': str(e)}, status=403)
        except Exception as e:
            data = {'error': str(e)}
        return respuesta(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Cuentas por Pagar'
        context['create_url'] = reverse_lazy('debts_pay_create')
        context['puede_borrar'] = cuentas_por_pagar.puede_eliminar(self.request)
        return context


class DebtsPayCreateView(GroupPermissionMixin, CreateView):
    model = DebtsPay
    template_name = 'debts_pay/create.html'
    form_class = PaymentsDebtsPayForm
    success_url = reverse_lazy('debts_pay_list')
    permission_required = 'add_debts_pay'

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', '')
        data = {}
        try:
            if action == 'search_debts_pay':
                term = request.POST.get('term', '')
                queryset = (DebtsPay.objects.select_related('purchase__provider')
                            .filter(Q(purchase__provider__name__icontains=term) | Q(purchase__number__icontains=term)
                                    | Q(purchase__secuencial__icontains=term))
                            .exclude(state=False).order_by('end_date', 'id'))
                data = []
                for deuda in DebtsPay.con_pagado(queryset)[0:10]:
                    item = deuda.toJSON()
                    item['text'] = deuda.get_full_name()
                    data.append(item)
            elif action == 'add':
                if request.POST.get('cuenta_bancaria'):
                    raise cuentas_por_pagar.ErrorPago('Las cuentas bancarias llegan en la Etapa 3.')
                try:
                    deuda_id = int(request.POST.get('debts_pay') or 0)
                except ValueError:
                    deuda_id = 0
                with transaction.atomic():   # el comprobante adjunto (opcional) va en la misma transacción que el pago
                    pago = cuentas_por_pagar.registrar_pago(
                        deuda_id, request.user, fecha=request.POST.get('date_joined'), valor=request.POST.get('valor'),
                        medio_pago=request.POST.get('medio_pago'), referencia=request.POST.get('referencia', ''),
                        descripcion=request.POST.get('description', ''))
                    adjuntos.adjuntar_al_registrar(request, 'pago', pago)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data = {'error': str(e)}
        return respuesta(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Nuevo registro de un Pago'
        context['list_url'] = self.success_url
        context['action'] = 'add'
        context.update(adjuntos.contexto())
        return context


class DebtsPayDeleteView(GroupPermissionMixin, DeleteView):
    """Elimina una cuenta por pagar sin pagos ni abonos (cuentas_por_pagar.eliminar_deuda, auditado). Antes se borraba en
    cascada con sus pagos y sin registro."""
    model = DebtsPay
    template_name = 'delete.html'
    success_url = reverse_lazy('debts_pay_list')
    permission_required = 'delete_debts_pay'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            deuda = self.get_object()
        except Http404:                      # id de otra empresa o inexistente (§6: un id ajeno = 404)
            return respuesta({'error': 'La cuenta por pagar no existe.'}, status=404)
        try:
            cuentas_por_pagar.eliminar_deuda(request, deuda.pk)
        except cuentas_por_pagar.SinPermiso as e:
            return respuesta({'error': str(e)}, status=403)
        except Exception as e:
            data['error'] = str(e)
        return respuesta(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Notificación de eliminación'
        context['list_url'] = self.success_url
        return context
