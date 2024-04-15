from datetime import *

from crum import get_current_request
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.forms.models import model_to_dict

from config import settings
from core.security.choices import *
from core.user.models import User


class Dashboard(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name='Nombre')
    author = models.CharField(max_length=120, verbose_name='Autor')
    image = models.ImageField(upload_to='dashboard/%Y/%m/%d', null=True, blank=True, verbose_name='Logo')
    icon = models.CharField(max_length=500, verbose_name='Icono FontAwesome')
    layout = models.IntegerField(choices=LAYOUT_OPTIONS, default=LAYOUT_OPTIONS[0][0], verbose_name='Diseño')
    card = models.CharField(max_length=50, choices=CARD, default=CARD[0][0], verbose_name='Card')
    navbar = models.CharField(max_length=50, choices=NAVBAR, default=NAVBAR[0][0], verbose_name='Navbar')
    brand_logo = models.CharField(max_length=50, choices=BRAND_LOGO, default=BRAND_LOGO[0][0], verbose_name='Brand Logo')
    sidebar = models.CharField(max_length=50, choices=SIDEBAR, default=SIDEBAR[0][0], verbose_name='Sidebar')

    def __str__(self):
        return self.name

    def get_template_from_layout(self):
        if self.layout == LAYOUT_OPTIONS[0][0]:
            return 'vtc_body.html'
        return 'hzt_body.html'

    def get_icon(self):
        if self.icon:
            return self.icon
        return 'fa fa-cubes'

    def get_image(self):
        if self.image:
            return f'{settings.MEDIA_URL}{self.image}'
        return f'{settings.STATIC_URL}img/default/empty.png'

    def toJSON(self):
        item = model_to_dict(self)
        return item

    class Meta:
        verbose_name = 'Dashboard'
        verbose_name_plural = 'Dashboards'
        default_permissions = ()
        permissions = (
            ('view_dashboard', 'Can view Dashboard'),
        )


class ModuleType(models.Model):
    name = models.CharField(max_length=150, unique=True, verbose_name='Nombre')
    icon = models.CharField(max_length=30, unique=True, verbose_name='Icono')

    def __str__(self):
        return self.name

    def toJSON(self):
        item = model_to_dict(self)
        item['icon'] = self.get_icon()
        return item

    def get_icon(self):
        if self.icon:
            return self.icon
        return 'fa fa-times'

    def get_session_modules(self):
        queryset = []
        request = get_current_request()
        if 'group' in request.session:
            group = request.session['group']
            module_ids = list(group.groupmodule_set.filter(module__module_type=self).values_list('module_id', flat=True))
            queryset = Module.objects.filter(id__in=module_ids).order_by('name')
        return queryset

    class Meta:
        verbose_name = 'Tipo de Módulo'
        verbose_name_plural = 'Tipos de Módulos'
        default_permissions = ()
        permissions = (
            ('view_module_type', 'Can view Tipo de Módulo'),
            ('add_module_type', 'Can add Tipo de Módulo'),
            ('change_module_type', 'Can change Tipo de Módulo'),
            ('delete_module_type', 'Can delete Tipo de Módulo'),
        )


class Module(models.Model):
    url = models.CharField(max_length=250, verbose_name='URL')
    name = models.CharField(max_length=100, verbose_name='Nombre')
    module_type = models.ForeignKey(ModuleType, null=True, blank=True, on_delete=models.PROTECT, verbose_name='Tipo de Módulo')
    description = models.CharField(max_length=200, null=True, blank=True, verbose_name='Descripción')
    icon = models.CharField(max_length=30, null=True, blank=True, verbose_name='Icono')
    image = models.ImageField(upload_to='module/%Y/%m/%d', null=True, blank=True, verbose_name='Imagen')
    permissions = models.ManyToManyField(Permission, blank=True, verbose_name='Permisos')

    def __str__(self):
        return f'{self.name} / {self.url}'

    def toJSON(self):
        item = model_to_dict(self)
        item['icon'] = self.get_icon()
        item['module_type'] = {} if self.module_type is None else self.module_type.toJSON()
        item['icon'] = self.get_icon()
        item['image'] = self.get_image()
        item['permissions'] = [model_to_dict(i, exclude=['content_type']) for i in self.permissions.all()]
        return item

    def get_icon(self):
        if self.icon:
            return self.icon
        return 'fa fa-times'

    def get_image(self):
        if self.image:
            return f'{settings.MEDIA_URL}{self.image}'
        return f'{settings.STATIC_URL}img/default/empty.png'

    def get_image_icon(self):
        if self.image:
            return self.get_image()
        if self.icon:
            return self.get_icon()
        return f'{settings.STATIC_URL}img/default/empty.png'

    class Meta:
        verbose_name = 'Módulo'
        verbose_name_plural = 'Módulos'


class GroupModule(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE)
    module = models.ForeignKey(Module, on_delete=models.CASCADE)

    def __str__(self):
        return self.module.name

    class Meta:
        verbose_name = 'Grupo Módulo'
        verbose_name_plural = 'Grupo Módulos'
        default_permissions = ()


class DatabaseBackups(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date_joined = models.DateField(default=datetime.now)
    hour = models.TimeField(default=datetime.now)
    remote_addr = models.CharField(max_length=100, null=True, blank=True)
    http_user_agent = models.CharField(max_length=150, null=True, blank=True)
    archive = models.FileField(upload_to='backup/%Y/%m/%d')

    def __str__(self):
        return self.remote_addr

    def toJSON(self):
        item = model_to_dict(self)
        item['user'] = self.user.toJSON()
        item['date_joined'] = self.date_joined.strftime('%d-%m-%Y')
        item['hour'] = self.hour.strftime('%H:%M %p')
        item['archive'] = self.get_archive()
        return item

    def save(self, force_insert=False, force_update=False, using=None,
             update_fields=None):
        try:
            request = get_current_request()
            self.http_user_agent = str(request.user_agent)
            self.remote_addr = request.META.get('REMOTE_ADDR', None)
        except:
            pass
        super(DatabaseBackups, self).save()

    def get_archive(self):
        if self.archive:
            return f'{settings.MEDIA_URL}{self.archive}'
        return ''

    class Meta:
        verbose_name_plural = 'Respaldo de BD'
        verbose_name = 'Respaldos de BD'
        default_permissions = ()
        permissions = (
            ('view_database_backups', 'Can view Respaldo de BD'),
            ('add_database_backups', 'Can add Respaldo de BD'),
            ('delete_database_backups', 'Can delete Respaldo de BD'),
        )


class UserAccess(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date_joined = models.DateField(default=datetime.now)
    hour = models.TimeField(default=datetime.now)
    remote_addr = models.CharField(max_length=100, null=True, blank=True)
    http_user_agent = models.CharField(max_length=150, null=True, blank=True)

    def __str__(self):
        return self.remote_addr

    def toJSON(self):
        item = model_to_dict(self)
        item['user'] = self.user.toJSON()
        item['date_joined'] = self.date_joined.strftime('%d-%m-%Y')
        item['hour'] = self.hour.strftime('%H:%M %p')
        return item

    def save(self, force_insert=False, force_update=False, using=None,
             update_fields=None):
        try:
            request = get_current_request()
            self.http_user_agent = str(request.user_agent)
            self.remote_addr = request.META.get('REMOTE_ADDR', None)
        except:
            pass
        super(UserAccess, self).save()

    class Meta:
        verbose_name = 'Acceso de Usuario'
        verbose_name_plural = 'Acceso de Usuarios'
        default_permissions = ()
        permissions = (
            ('view_user_access', 'Can view Acceso del usuario'),
            ('delete_user_access', 'Can delete Acceso del usuario'),
        )


def get_session_module_types(self):
    ids = list(self.groupmodule_set.all().values_list('module__module_type_id', flat=True).distinct())
    return ModuleType.objects.filter(id__in=ids).order_by('name')


def get_session_modules(self):
    ids = list(self.groupmodule_set.filter(module__module_type__isnull=True).values_list('module_id', flat=True).distinct())
    return Module.objects.filter(id__in=ids).order_by('name')


Group.add_to_class('get_session_module_types', get_session_module_types)
Group.add_to_class('get_session_modules', get_session_modules)