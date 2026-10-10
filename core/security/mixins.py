from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseRedirect, JsonResponse

from config import settings
from core.security.session import get_group, set_module
from core.tenancy.roles import PLATFORM_URLS

PLATFORM_PATHS = tuple(sorted(PLATFORM_URLS))

PERMISSION_DENIED_MESSAGE = 'Tu perfil no cuenta con el permiso necesario para ingresar'


class SessionGroupMixin(LoginRequiredMixin):
    """Base de los mixins de permisos.

    La comprobación se hace en dispatch(), así que cubre GET, POST y cualquier
    otro método: las acciones AJAX por POST exigen el mismo permiso que la
    pantalla que las contiene.
    """

    def get_last_url(self):
        url_last = self.request.session.get('url_last')
        if url_last and url_last != self.request.path:
            return url_last
        return settings.LOGIN_REDIRECT_URL

    def deny(self, request):
        if request.method == 'GET':
            messages.error(request, PERMISSION_DENIED_MESSAGE)
            return HttpResponseRedirect(self.get_last_url())
        return JsonResponse({'error': PERMISSION_DENIED_MESSAGE}, status=403)

    def get_group_module(self, group):
        raise NotImplementedError

    def has_access(self, group):
        raise NotImplementedError

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.path.startswith(PLATFORM_PATHS) and not request.user.is_superuser:
            # Grupos, módulos y configuración global afectan a todas las empresas.
            return self.deny(request)
        group = get_group(request)
        if group is None:
            if request.method == 'GET':
                return HttpResponseRedirect(settings.LOGIN_REDIRECT_URL)
            return JsonResponse({'error': PERMISSION_DENIED_MESSAGE}, status=403)
        if not self.has_access(group):
            return self.deny(request)
        if request.method == 'GET':
            group_module = self.get_group_module(group)
            set_module(request, group_module.module if group_module else None)
            if group_module:
                request.session['url_last'] = request.path
        return super().dispatch(request, *args, **kwargs)


class GroupPermissionMixin(SessionGroupMixin):
    permission_required = None

    def get_permissions(self):
        if isinstance(self.permission_required, str):
            return [self.permission_required]
        return list(self.permission_required)

    def has_access(self, group):
        permission_list = self.get_permissions()
        return group.permissions.filter(codename__in=permission_list).count() == len(set(permission_list))

    def get_group_module(self, group):
        return group.groupmodule_set.filter(module__permissions__codename__in=[self.get_permissions()[0]]).first()


class GroupModuleMixin(SessionGroupMixin):

    def has_access(self, group):
        return self.get_group_module(group) is not None

    def get_group_module(self, group):
        return group.groupmodule_set.filter(module__url=self.request.path).first()
