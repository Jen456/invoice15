import json
import uuid

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import DeleteView, CreateView, FormView

from core.pos import cxc
from core.pos.forms import PaymentsCtaCollectForm, CtasCollect
from core.reports.forms import ReportForm
from core.security.mixins import GroupPermissionMixin


def _json(data, status=200):
    return HttpResponse(json.dumps(data), content_type='application/json', status=status)


class CtasCollectListView(GroupPermissionMixin, FormView):
    template_name = 'ctas_collect/list.html'
    form_class = ReportForm
    permission_required = 'view_ctas_collect'

    def post(self, request, *args, **kwargs):
        # Etapa 2 (O2): listados con cxc.listado / cxc.abonos (consultas constantes) y cobros eliminados con
        # cxc.eliminar_cobro (permiso delete_ctas_collect del rol, auditado; sin él, 403).
        data = {}
        action = request.POST.get('action', '')
        try:
            if action == 'search':
                start_date, end_date = request.POST.get('start_date', ''), request.POST.get('end_date', '')
                data = [i.toJSON() for i in cxc.listado(start_date or None, end_date or None)]
            elif action == 'search_pays':
                data = []
                for count, i in enumerate(cxc.abonos(int(request.POST['id']))):
                    item = i.toJSON()
                    item['index'] = count + 1
                    data.append(item)
            elif action == 'delete_pay':
                cxc.eliminar_cobro(request, int(request.POST['id']))
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except cxc.ErrorCxC as e:
            return _json({'error': str(e)}, status=403 if e.codigo == 'sin_permiso_eliminar' else 200)
        except Exception as e:
            data = {'error': str(e)}
        return _json(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Cuentas por Cobrar'
        context['create_url'] = reverse_lazy('ctas_collect_create')
        return context


class CtasCollectCreateView(GroupPermissionMixin, CreateView):
    model = CtasCollect
    template_name = 'ctas_collect/create.html'
    form_class = PaymentsCtaCollectForm
    success_url = reverse_lazy('ctas_collect_list')
    permission_required = 'add_ctas_collect'

    def post(self, request, *args, **kwargs):
        # Etapa 2 (O2): el cobro lo registra cxc.registrar_cobro (medio de pago, referencia, Decimal y validaciones).
        action = request.POST.get('action', '')
        data = {}
        try:
            if action == 'search_ctas_collect':
                data = []
                term = request.POST.get('term', '').strip()
                cuentas = (cxc.listado().filter(state=True, tiene_anulacion=False)
                           .filter(Q(sale__client__user__names__icontains=term) | Q(sale__client__dni__icontains=term)
                                   | Q(sale__voucher_number_full__icontains=term) | Q(nd_numero__icontains=term))[0:10])
                for i in cuentas:
                    item = i.toJSON()
                    item['text'] = i.get_full_name()
                    data.append(item)
            elif action == 'add':
                cuenta = request.POST.get('ctas_collect', '')
                if not str(cuenta).isdigit():
                    raise ValueError('Elige la cuenta por cobrar.')
                # El cobro y su respaldo (comprobante o nota «Detalles», al menos uno) los registra core/cobros, que llama
                # a cxc.registrar_cobro; `clave` evita duplicados por doble envío (sin ella se genera una por petición).
                from core.cobros import servicios as cobros
                venta = CtasCollect.objects.select_related('sale').get(pk=int(cuenta)).sale
                cobros.registrar(request, venta, clave=request.POST.get('clave') or uuid.uuid4().hex,
                                 medio=request.POST.get('medio_pago', ''), importe=request.POST.get('valor', ''),
                                 referencia=request.POST.get('referencia', ''), nota=request.POST.get('description', ''),
                                 archivo=request.FILES.get('archivo'), fecha=request.POST.get('date_joined', ''))
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except ObjectDoesNotExist:
            data = {'error': 'La cuenta por cobrar no existe: actualiza la página.'}
        except Exception as e:
            data = {'error': str(e)}
        return _json(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Nuevo registro de un Pago'
        context['list_url'] = self.success_url
        context['action'] = 'add'
        context['clave_envio'] = uuid.uuid4().hex   # idempotencia del cobro (core/cobros)
        return context


class CtasCollectDeleteView(GroupPermissionMixin, DeleteView):
    model = CtasCollect
    template_name = 'delete.html'
    success_url = reverse_lazy('ctas_collect_list')
    permission_required = 'delete_ctas_collect'

    def post(self, request, *args, **kwargs):
        # Etapa 2 (O2): no se borra una CxC con cobros (antes caían en cascada sin auditoría) ni con abonos automáticos.
        cuenta = self.get_object()   # de otra empresa → 404
        data = {}
        try:
            cxc.eliminar_cxc(cuenta.pk)
        except Exception as e:
            data['error'] = str(e)
        return _json(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Notificación de eliminación'
        context['list_url'] = self.success_url
        return context
