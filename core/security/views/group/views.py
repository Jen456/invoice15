import json

from django.db import transaction
from django.forms import model_to_dict
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView, TemplateView

from core.security.forms import GroupForm, Group, GroupModule, Module, Permission
from core.security.mixins import GroupPermissionMixin


class GroupListView(GroupPermissionMixin, TemplateView):
    template_name = 'group/list.html'
    permission_required = 'view_group'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                for i in Group.objects.all():
                    data.append(model_to_dict(i, exclude=['permissions']))
            elif action == 'search_permissions':
                data = []
                group = Group.objects.get(pk=request.POST['id'])
                for i in group.permissions.all():
                    data.append(model_to_dict(i))
            elif action == 'search_modules':
                data = []
                group = Group.objects.get(pk=request.POST['id'])
                for i in group.groupmodule_set.all():
                    data.append(i.module.toJSON())
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Grupos'
        context['create_url'] = reverse_lazy('group_create')
        return context


class GroupCreateView(GroupPermissionMixin, CreateView):
    model = Group
    template_name = 'group/create.html'
    form_class = GroupForm
    success_url = reverse_lazy('group_list')
    permission_required = 'add_group'

    def post(self, request, *args, **kwargs):
        action = request.POST['action']
        data = {}
        try:
            if action == 'add':
                with transaction.atomic():
                    group = Group()
                    group.name = request.POST['name']
                    group.save()
                    for module in json.loads(request.POST['items']):
                        GroupModule.objects.get_or_create(group_id=group.id, module_id=int(module['id']))
                        for permission in module['permissions']:
                            group.permissions.add(Permission.objects.get(pk=int(permission['id'])))
            elif action == 'search_permissions':
                data = []
                for module in Module.objects.all():
                    item = module.toJSON()
                    item['checked'] = 0
                    for permission in item['permissions']:
                        permission['checked'] = 0
                    data.append(item)
            elif action == 'validate_data':
                data = {'valid': True}
                queryset = Group.objects.all()
                pattern = request.POST['pattern']
                parameter = request.POST['parameter'].strip()
                if pattern == 'name':
                    data['valid'] = not queryset.filter(name__iexact=parameter).exists()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Nuevo registro de un Grupo'
        context['list_url'] = self.success_url
        context['action'] = 'add'
        return context


class GroupUpdateView(GroupPermissionMixin, UpdateView):
    model = Group
    template_name = 'group/create.html'
    form_class = GroupForm
    success_url = reverse_lazy('group_list')
    permission_required = 'change_group'

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        action = request.POST['action']
        data = {}
        try:
            if action == 'edit':
                with transaction.atomic():
                    group = self.object
                    group.name = request.POST['name']
                    group.save()
                    group.groupmodule_set.all().delete()
                    group.permissions.clear()
                    for module in json.loads(request.POST['items']):
                        GroupModule.objects.get_or_create(group_id=group.id, module_id=int(module['id']))
                        for permission in module['permissions']:
                            group.permissions.add(Permission.objects.get(pk=int(permission['id'])))
            elif action == 'search_permissions':
                group = self.object
                data = []
                for module in Module.objects.all():
                    item = module.toJSON()
                    item['checked'] = 1 if group.groupmodule_set.filter(module_id=module.id).exists() else 0
                    for permission in item['permissions']:
                        permission['checked'] = 1 if group.permissions.filter(id=int(permission['id'])).exists() else 0
                    data.append(item)
            elif action == 'validate_data':
                data = {'valid': True}
                queryset = Group.objects.all().exclude(id=self.object.id)
                pattern = request.POST['pattern']
                parameter = request.POST['parameter'].strip()
                if pattern == 'name':
                    data['valid'] = not queryset.filter(name__iexact=parameter).exists()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Edición de un Grupo'
        context['list_url'] = self.success_url
        context['action'] = 'edit'
        return context


class GroupDeleteView(GroupPermissionMixin, DeleteView):
    model = Group
    template_name = 'delete.html'
    success_url = reverse_lazy('group_list')
    permission_required = 'delete_group'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            object = self.get_object()
            object.groupmodule_set.all().delete()
            object.permissions.clear()
            object.delete()
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Notificación de eliminación'
        context['list_url'] = self.success_url
        return context
