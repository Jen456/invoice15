from crum import get_current_request
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect

from config import settings


class GroupPermissionMixin(LoginRequiredMixin, object):
    redirect_field_name = settings.LOGIN_REDIRECT_URL
    permission_required = None

    def get_permissions(self):
        permissions = []
        if isinstance(self.permission_required, str):
            permissions.append(self.permission_required)
        else:
            permissions = list(self.permission_required)
        return permissions

    def get_last_url(self):
        request = get_current_request()
        if 'url_last' in request.session:
            if request.session['url_last'] != request.path:
                return request.session['url_last']
        return settings.LOGIN_REDIRECT_URL

    def get(self, request, *args, **kwargs):
        if 'group' not in request.session:
            return HttpResponseRedirect(settings.LOGIN_REDIRECT_URL)
        request.session['module'] = None
        group = request.session['group']
        permission_list = self.get_permissions()
        queryset = group.permissions.filter(codename__in=permission_list)
        if queryset.count() == len(permission_list):
            group_module = group.groupmodule_set.filter(module__permissions__codename__in=[permission_list[0]]).first()
            if group_module:
                request.session['url_last'] = request.path
                request.session['module'] = group_module.module
            return super().get(request, *args, **kwargs)
        messages.error(request, 'Tu perfil no cuenta con el permiso necesario para ingresar')
        return HttpResponseRedirect(self.get_last_url())


class GroupModuleMixin(LoginRequiredMixin, object):
    redirect_field_name = settings.LOGIN_REDIRECT_URL

    def get_last_url(self):
        request = get_current_request()
        if 'url_last' in request.session:
            if request.session['url_last'] != request.path:
                return request.session['url_last']
        return settings.LOGIN_REDIRECT_URL

    def get(self, request, *args, **kwargs):
        if 'group' not in request.session:
            return HttpResponseRedirect(settings.LOGIN_REDIRECT_URL)
        request.session['module'] = None
        group = request.session['group']
        group_module = group.groupmodule_set.filter(module__url=request.path).first()
        if group_module:
            request.session['url_last'] = request.path
            request.session['module'] = group_module.module
            return super().get(request, *args, **kwargs)
        messages.error(request, 'Tu perfil no cuenta con el permiso necesario para ingresar')
        return HttpResponseRedirect(self.get_last_url())
