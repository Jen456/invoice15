"""Panel de la plataforma (/plataforma/): empresas, usuarios, membresías, roles y auditoría.

Solo superusuarios. El middleware de empresas activa aquí el ámbito de
plataforma (ve todas las empresas, también en PostgreSQL con RLS). El inicio de
sesión pasa por el login de la aplicación, que tiene límite de intentos.
Planes, suscripciones, pagos y consumo se añaden en la etapa 4.
"""
from urllib.parse import quote

from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group
from django.shortcuts import redirect

from core.pos.models import Company
from core.security.models import Dashboard, GroupModule, Module, ModuleType
from core.tenancy.models import AuditLog, Membership, audit
from core.user.models import User


class PlataformaAdminSite(admin.AdminSite):
    site_header = 'FacturaPorAquí · Plataforma'
    site_title = 'Plataforma FacturaPorAquí'
    index_title = 'Gestión de la plataforma'
    site_url = '/empresas/'

    def has_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def login(self, request, extra_context=None):
        return redirect(f'/login/?next={quote(request.get_full_path())}')


plataforma = PlataformaAdminSite(name='plataforma')


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ('user', 'company')
    fields = ('user', 'company', 'group', 'is_active', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(Company, site=plataforma)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('tradename', 'business_name', 'ruc', 'is_active', 'environment_type', 'created_at')
    list_filter = ('is_active', 'environment_type')
    search_fields = ('tradename', 'business_name', 'ruc', 'email')
    readonly_fields = ('uuid', 'created_at')
    inlines = (MembershipInline,)
    actions = ('activar', 'desactivar')
    fieldsets = (
        ('Empresa', {'fields': ('ruc', 'business_name', 'tradename', 'is_active', 'uuid', 'created_at')}),
        ('Datos tributarios', {'fields': ('main_address', 'establishment_address', 'establishment_code',
                                          'issuing_point_code', 'special_taxpayer', 'obligated_accounting',
                                          'retention_agent', 'environment_type', 'emission_type', 'iva',
                                          'vat_percentage')}),
        ('Contacto', {'fields': ('mobile', 'phone', 'email', 'website', 'description', 'image')}),
    )

    def save_model(self, request, obj, form, change):
        for field in ('electronic_signature_key', 'email_host_user', 'email_host_password'):
            if getattr(obj, field) is None:
                setattr(obj, field, '')
        super().save_model(request, obj, form, change)
        audit(request, 'company_change' if change else 'company_create', company=obj,
              campos=list(form.changed_data))

    def save_formset(self, request, form, formset, change):
        instances = formset.save()
        for membership in instances:
            audit(request, 'membership_change', company=membership.company, usuario=membership.user.username,
                  rol=membership.group.name, activo=membership.is_active, origen='plataforma')
        for membership in formset.deleted_objects:
            audit(request, 'membership_remove', company=form.instance, usuario=str(membership.user),
                  origen='plataforma')

    @admin.action(description='Activar empresas seleccionadas')
    def activar(self, request, queryset):
        for company in queryset:
            company.is_active = True
            company.save(update_fields=['is_active'])
            audit(request, 'company_change', company=company, campos=['is_active'], valor=True)

    @admin.action(description='Desactivar empresas seleccionadas (sus usuarios pierden el acceso)')
    def desactivar(self, request, queryset):
        for company in queryset:
            company.is_active = False
            company.save(update_fields=['is_active'])
            audit(request, 'company_change', company=company, campos=['is_active'], valor=False)


@admin.register(Membership, site=plataforma)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'company', 'group', 'is_active', 'created_at')
    list_filter = ('is_active', 'group', 'company')
    search_fields = ('user__username', 'user__names', 'company__tradename', 'company__ruc')
    autocomplete_fields = ('user', 'company')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        audit(request, 'membership_change' if change else 'membership_add', company=obj.company,
              usuario=obj.user.username, rol=obj.group.name, activo=obj.is_active, origen='plataforma')

    def delete_model(self, request, obj):
        audit(request, 'membership_remove', company=obj.company, usuario=obj.user.username, origen='plataforma')
        super().delete_model(request, obj)


@admin.register(User, site=plataforma)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'names', 'email', 'is_active', 'is_superuser', 'last_login')
    list_filter = ('is_active', 'is_superuser')
    search_fields = ('username', 'names', 'email')
    fields = ('username', 'names', 'email', 'is_active', 'is_superuser', 'date_joined', 'last_login')
    readonly_fields = ('date_joined', 'last_login')
    inlines = (MembershipInline,)

    def save_formset(self, request, form, formset, change):
        instances = formset.save()
        for membership in instances:
            audit(request, 'membership_change', company=membership.company, usuario=membership.user.username,
                  rol=membership.group.name, activo=membership.is_active, origen='plataforma')


class GroupModuleInline(admin.TabularInline):
    model = GroupModule
    extra = 0


@admin.register(Group, site=plataforma)
class GroupAdmin(BaseGroupAdmin):
    inlines = (GroupModuleInline,)


@admin.register(AuditLog, site=plataforma)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'action', 'user', 'company', 'ip')
    list_filter = ('action', 'company')
    search_fields = ('user__username', 'company__tradename', 'ip')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


plataforma.register(Module)
plataforma.register(ModuleType)
plataforma.register(Dashboard)
