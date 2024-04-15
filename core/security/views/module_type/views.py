import json

from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import TemplateView, CreateView, UpdateView, DeleteView

from core.security.forms import ModuleTypeForm, ModuleType
from core.security.mixins import GroupPermissionMixin


class ModuleTypeListView(GroupPermissionMixin, TemplateView):
    template_name = 'module_type/list.html'
    permission_required = 'view_module_type'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                for i in ModuleType.objects.all():
                    data.append(i.toJSON())
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Tipos de Módulos'
        context['create_url'] = reverse_lazy('module_type_create')
        return context


class ModuleTypeCreateView(GroupPermissionMixin, CreateView):
    model = ModuleType
    template_name = 'module_type/create.html'
    form_class = ModuleTypeForm
    success_url = reverse_lazy('module_type_list')
    permission_required = 'add_module_type'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'add':
                data = self.get_form().save()
            elif action == 'validate_data':
                data = {'valid': True}
                queryset = ModuleType.objects.all()
                pattern = request.POST['pattern']
                parameter = request.POST['parameter'].strip()
                if pattern == 'name':
                    data['valid'] = not queryset.filter(name__iexact=parameter).exists()
                elif pattern == 'icon':
                    data['valid'] = not queryset.filter(icon__iexact=parameter).exists()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Nuevo registro de un Tipo de Módulo'
        context['list_url'] = self.success_url
        context['action'] = 'add'
        return context


class ModuleTypeUpdateView(GroupPermissionMixin, UpdateView):
    model = ModuleType
    template_name = 'module_type/create.html'
    form_class = ModuleTypeForm
    success_url = reverse_lazy('module_type_list')
    permission_required = 'change_module_type'

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'edit':
                data = self.get_form().save()
            elif action == 'validate_data':
                data = {'valid': True}
                queryset = ModuleType.objects.all().exclude(id=self.object.id)
                pattern = request.POST['pattern']
                parameter = request.POST['parameter'].strip()
                if pattern == 'name':
                    data['valid'] = not queryset.filter(name__iexact=parameter).exists()
                elif pattern == 'icon':
                    data['valid'] = not queryset.filter(icon__iexact=parameter).exists()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Edición de un Tipo de Módulo'
        context['list_url'] = self.success_url
        context['action'] = 'edit'
        return context


class ModuleTypeDeleteView(GroupPermissionMixin, DeleteView):
    model = ModuleType
    template_name = 'delete.html'
    success_url = reverse_lazy('module_type_list')
    permission_required = 'delete_module_type'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            self.get_object().delete()
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Notificación de eliminación'
        context['list_url'] = self.success_url
        return context
