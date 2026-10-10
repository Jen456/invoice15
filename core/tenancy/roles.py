"""Roles de empresa (grupos plantilla) y sus módulos.

Se usa desde la instalación base y desde la migración que convierte una
instalación existente: recibe los modelos para poder trabajar con los modelos
históricos de una migración.
"""
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER

# Módulos de la plataforma: solo superusuarios (panel /plataforma/), nunca en roles de empresa.
PLATFORM_URLS = {'/security/module/type/', '/security/module/', '/security/group/', '/security/dashboard/update/',
                 '/security/user/access/', '/security/database/backups/'}
PROFILE_URLS = {'/user/update/password/', '/user/update/profile/'}
CLIENT_URLS = {'/pos/client/update/profile/', '/pos/sale/client/', '/pos/credit/note/client/', '/user/update/password/'}
REPORT_URLS = {'/reports/sale/', '/reports/purchase/', '/reports/expenses/', '/reports/debts/pay/',
               '/reports/ctas/collect/', '/reports/results/', '/reports/earnings/'}
SELLER_URLS = {'/pos/client/', '/pos/sale/admin/', '/pos/credit/note/admin/', '/pos/product/', '/pos/promotions/',
               '/reports/sale/'} | PROFILE_URLS
ACCOUNTANT_URLS = REPORT_URLS | {'/pos/sale/admin/', '/pos/credit/note/admin/', '/pos/purchase/', '/pos/expenses/',
                                 '/pos/ctas/collect/', '/pos/debts/pay/', '/pos/voucher/errors/', '/pos/client/',
                                 '/pos/provider/'} | PROFILE_URLS
# Permisos que un rol de solo lectura nunca recibe aunque el módulo esté en su menú.
WRITE_PREFIXES = ('add_', 'change_', 'delete_', 'adjust_')
SELLER_WRITE = {'add_client', 'change_client', 'add_sale', 'add_credit_note'}


def role_modules(role, modules):
    """(módulos, permite_escritura) de un rol a partir de todos los módulos."""
    staff = [m for m in modules if m.url not in PLATFORM_URLS and m.url not in CLIENT_URLS - PROFILE_URLS]
    if role in (ROLE_OWNER, ROLE_ADMIN):
        return staff, True
    if role == ROLE_READONLY:
        return [m for m in staff if m.url not in {'/pos/product/stock/adjustment/', '/user/', '/pos/company/update/',
                                                  '/suscripcion/'}], False
    if role == ROLE_ACCOUNTANT:
        return [m for m in staff if m.url in ACCOUNTANT_URLS], False
    if role == ROLE_SELLER:
        return [m for m in staff if m.url in SELLER_URLS], 'seller'
    if role == ROLE_CLIENT:
        return [m for m in modules if m.url in CLIENT_URLS], True
    return [], False


def sync_roles(Group, Module, GroupModule):
    """Crea o actualiza los seis roles de empresa con sus módulos y permisos."""
    modules = list(Module.objects.all())
    for role in (ROLE_OWNER, ROLE_ADMIN, ROLE_ACCOUNTANT, ROLE_SELLER, ROLE_READONLY, ROLE_CLIENT):
        group, _ = Group.objects.get_or_create(name=role)
        selected, write = role_modules(role, modules)
        GroupModule.objects.filter(group=group).exclude(module__in=selected).delete()
        permissions = set()
        for module in selected:
            GroupModule.objects.get_or_create(group=group, module=module)
            for permission in module.permissions.all():
                is_write = permission.codename.startswith(WRITE_PREFIXES)
                if write is True or not is_write or (write == 'seller' and permission.codename in SELLER_WRITE):
                    permissions.add(permission)
        group.permissions.set(permissions)


def strip_platform_modules(Group, GroupModule):
    """Ningún grupo que no sea de la plataforma conserva módulos de la plataforma
    (grupos, módulos, configuración global...), que afectan a todas las empresas."""
    GroupModule.objects.filter(module__url__in=PLATFORM_URLS).delete()
