import json

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import Group
from django.http import HttpResponseRedirect, HttpResponse
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView, FormView, View

from config import settings
from core.login.forms import UpdatePasswordForm
from core.security.mixins import GroupPermissionMixin, GroupModuleMixin
from core.user.forms import UserForm, ProfileForm, User


class UserListView(GroupPermissionMixin, FormView):
    template_name = 'user/list.html'
    form_class = UpdatePasswordForm
    permission_required = 'view_user'

    def get_form(self, form_class=None):
        form = UpdatePasswordForm()
        form.fields['password'].label = 'Ingrese su nueva contraseña'
        return form

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                for i in User.objects.all():
                    data.append(i.toJSON())
            elif action == 'reset_password':
                user = User.objects.get(pk=request.POST['id'])
                current_session = user == request.user
                user.create_or_update_password(password=user.username)
                user.save()
                if current_session:
                    update_session_auth_hash(request, user)
            elif action == 'login_with_user':
                from django.contrib.auth import login
                admin = User.objects.get(pk=request.POST['id'])
                login(request, admin)
            elif action == 'update_password':
                user = User.objects.get(pk=request.POST['id'])
                current_session = user == request.user
                user.create_or_update_password(password=request.POST['password'])
                user.save()
                if current_session:
                    update_session_auth_hash(request, user)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Usuarios'
        context['create_url'] = reverse_lazy('user_create')
        return context


class UserCreateView(GroupPermissionMixin, CreateView):
    model = User
    template_name = 'user/create.html'
    form_class = UserForm
    success_url = reverse_lazy('user_list')
    permission_required = 'add_user'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'add':
                data = self.get_form().save()
            elif action == 'validate_data':
                data = {'valid': True}
                queryset = User.objects.all()
                pattern = request.POST['pattern']
                parameter = request.POST['parameter'].strip()
                if pattern == 'username':
                    data['valid'] = not queryset.filter(username=parameter).exists()
                elif pattern == 'email':
                    data['valid'] = not queryset.filter(email=parameter).exists()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Nuevo registro de un Usuario'
        context['list_url'] = self.success_url
        context['action'] = 'add'
        return context


class UserUpdateView(GroupPermissionMixin, UpdateView):
    model = User
    template_name = 'user/create.html'
    form_class = UserForm
    success_url = reverse_lazy('user_list')
    permission_required = 'change_user'

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
                queryset = User.objects.all().exclude(id=self.object.id)
                pattern = request.POST['pattern']
                parameter = request.POST['parameter'].strip()
                if pattern == 'username':
                    data['valid'] = not queryset.filter(username=parameter).exists()
                elif pattern == 'email':
                    data['valid'] = not queryset.filter(email=parameter).exists()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Edición de un Usuario'
        context['list_url'] = self.success_url
        context['action'] = 'edit'
        return context


class UserDeleteView(GroupPermissionMixin, DeleteView):
    model = User
    template_name = 'delete.html'
    success_url = reverse_lazy('user_list')
    permission_required = 'delete_user'

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


class UserUpdateProfileView(GroupModuleMixin, UpdateView):
    model = User
    template_name = 'user/update_profile.html'
    form_class = ProfileForm
    success_url = settings.LOGIN_REDIRECT_URL

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        return self.request.user

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'edit':
                data = self.get_form().save()
            elif action == 'validate_data':
                data = {'valid': True}
                queryset = User.objects.all().exclude(id=request.user.id)
                pattern = request.POST['pattern']
                parameter = request.POST['parameter'].strip()
                if pattern == 'username':
                    data['valid'] = not queryset.filter(username=parameter).exists()
                elif pattern == 'email':
                    data['valid'] = not queryset.filter(email=parameter).exists()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context['title'] = 'Edición del perfil'
        context['list_url'] = self.success_url
        context['action'] = 'edit'
        return context


class UserUpdatePasswordView(GroupModuleMixin, FormView):
    template_name = 'user/update_password.html'
    form_class = PasswordChangeForm
    success_url = settings.LOGIN_REDIRECT_URL

    def get_form(self, form_class=None):
        form = PasswordChangeForm(user=self.request.user)
        for i in form.visible_fields():
            i.field.widget.attrs.update({
                'class': 'form-control',
                'autocomplete': 'off',
                'placeholder': f'Ingrese su {i.label.lower()}'
            })
        return form

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'update_password':
                form = PasswordChangeForm(user=request.user, data=request.POST)
                if form.is_valid():
                    form.save()
                    update_session_auth_hash(request, form.user)
                else:
                    data['error'] = form.errors
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Edición de Contraseña'
        context['list_url'] = self.success_url
        context['action'] = 'update_password'
        return context


class UserChooseProfileView(LoginRequiredMixin, View):

    def get(self, request, *args, **kwargs):
        try:
            group = Group.objects.filter(id=self.kwargs['pk'])
            request.session['group'] = None if not group.exists() else group[0]
        except:
            pass
        return HttpResponseRedirect(settings.LOGIN_REDIRECT_URL)
