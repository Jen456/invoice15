import os
import secrets
from os.path import basename

import django
from django.core.management import BaseCommand, CommandError

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.security.models import *
from django.contrib.auth.models import Permission
from core.pos.models import *
from core.tenancy.roles import strip_platform_modules, sync_roles


class Command(BaseCommand):
    help = (
        'Instalación base: módulos, perfiles Administrador y Cliente, y el usuario administrador. '
        'La contraseña del administrador se genera al azar y solo se escribe en --archivo-credenciales (0600).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--admin-usuario', default='admin')
        parser.add_argument('--admin-nombre', default='Administrador')
        parser.add_argument('--admin-correo', required=True)
        parser.add_argument('--archivo-credenciales', required=True,
                            help='Ruta nueva donde se guarda la contraseña generada (no debe existir).')

    def write_credentials(self, path, username, password):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(f'Usuario: {username}\nContraseña: {password}\n')

    def handle(self, *args, **options):
        if Dashboard.objects.exists() or Module.objects.exists():
            raise CommandError('La instalación base ya existe: no se vuelve a ejecutar.')
        if os.path.exists(options['archivo_credenciales']):
            raise CommandError('El archivo de credenciales ya existe: indica una ruta nueva.')
        dashboard = Dashboard.objects.create(
            name='FacturaPorAquí',
            author='FacturaPorAquí',
            icon='fas fa-shopping-cart',
            layout=1,
            navbar='navbar-dark navbar-navy',
            sidebar='sidebar-dark-navy'
        )
        image_path = f'{settings.BASE_DIR}{settings.STATIC_URL}img/default/logo.png'
        dashboard.image.save(basename(image_path), content=File(open(image_path, 'rb')), save=False)
        dashboard.save()

        moduletype = ModuleType.objects.create(name='Seguridad', icon='fas fa-lock')
        print(f'insertado {moduletype.name}')

        modules_data = [
            {
                'name': 'Tipos de Módulos',
                'url': '/security/module/type/',
                'icon': 'fas fa-door-open',
                'description': 'Permite administrar los tipos de módulos del sistema',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=ModuleType._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Módulos',
                'url': '/security/module/',
                'icon': 'fas fa-th-large',
                'description': 'Permite administrar los módulos del sistema',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=Module._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Grupos',
                'url': '/security/group/',
                'icon': 'fas fa-users',
                'description': 'Permite administrar los grupos de usuarios del sistema',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=Group._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Conf. Dashboard',
                'url': '/security/dashboard/update/',
                'icon': 'fas fa-tools',
                'description': 'Permite configurar los datos de la plantilla',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=Dashboard._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Accesos',
                'url': '/security/user/access/',
                'icon': 'fas fa-user-secret',
                'description': 'Permite administrar los accesos de los usuarios',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=UserAccess._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Usuarios',
                'url': '/user/',
                'icon': 'fas fa-user',
                'description': 'Permite administrar a los administradores del sistema',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=User._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Cambiar password',
                'url': '/user/update/password/',
                'icon': 'fas fa-key',
                'description': 'Permite cambiar tu password de tu cuenta',
                'moduletype': None,
                'permissions': None
            },
            {
                'name': 'Editar perfil',
                'url': '/user/update/profile/',
                'icon': 'fas fa-user',
                'description': 'Permite cambiar la información de tu cuenta',
                'moduletype': None,
                'permissions': None
            }
        ]

        moduletype = ModuleType.objects.create(name='Bodega', icon='fas fa-boxes')
        print(f'insertado {moduletype.name}')

        modules_data.extend([
            {
                'name': 'Proveedores',
                'url': '/pos/provider/',
                'icon': 'fas fa-truck',
                'description': 'Permite administrar a los proveedores de las compras',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=Provider._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Categorías',
                'url': '/pos/category/',
                'icon': 'fas fa-truck-loading',
                'description': 'Permite administrar las categorías de los productos',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=Category._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Productos',
                'url': '/pos/product/',
                'icon': 'fas fa-box',
                'description': 'Permite administrar los productos del sistema',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=Product._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Compras',
                'url': '/pos/purchase/',
                'icon': 'fas fa-dolly-flatbed',
                'description': 'Permite administrar las compras de los productos',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=Purchase._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Ajuste de Stock',
                'url': '/pos/product/stock/adjustment/',
                'icon': 'fas fa-sliders-h',
                'description': 'Permite administrar los ajustes de stock de productos',
                'moduletype': moduletype,
                'permissions': [Permission.objects.get(codename='adjust_product_stock')]
            }
        ])

        moduletype = ModuleType.objects.create(name='Administrativo', icon='fas fa-hand-holding-usd')
        print(f'insertado {moduletype.name}')

        modules_data.extend([
            {
                'name': 'Tipos de Gastos',
                'url': '/pos/type/expense/',
                'icon': 'fas fa-comments-dollar',
                'description': 'Permite administrar los tipos de gastos',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=TypeExpense._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Gastos',
                'url': '/pos/expenses/',
                'icon': 'fas fa-file-invoice-dollar',
                'description': 'Permite administrar los gastos de la compañia',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=Expenses._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Cuentas por cobrar',
                'url': '/pos/ctas/collect/',
                'icon': 'fas fa-funnel-dollar',
                'description': 'Permite administrar las cuentas por cobrar de los clientes',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=CtasCollect._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Cuentas por pagar',
                'url': '/pos/debts/pay/',
                'icon': 'fas fa-money-check-alt',
                'description': 'Permite administrar las cuentas por pagar de los proveedores',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=DebtsPay._meta.label.split('.')[1].lower()))
            }
        ])

        moduletype = ModuleType.objects.create(name='Facturación', icon='fas fa-calculator')
        print(f'insertado {moduletype.name}')

        modules_data.extend([
            {
                'name': 'Comprobantes',
                'url': '/pos/receipt/',
                'icon': 'fas fa-file-export',
                'description': 'Permite administrar los tipos de comprobantes para la facturación',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=Receipt._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Clientes',
                'url': '/pos/client/',
                'icon': 'fas fa-user-friends',
                'description': 'Permite administrar los clientes del sistema',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=Client._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Ventas',
                'url': '/pos/sale/admin/',
                'icon': 'fas fa-shopping-cart',
                'description': 'Permite administrar las ventas de los productos',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=Sale._meta.label.split('.')[1].lower()).exclude(codename='view_sale_client'))
            },
            {
                'name': 'Notas de Credito',
                'url': '/pos/credit/note/admin/',
                'icon': 'fa-solid fa-boxes-packing',
                'description': 'Permite administrar las notas de créditos de las ventas',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=CreditNote._meta.label.split('.')[1].lower()).exclude(codename='view_credit_note_client'))
            },
            {
                'name': 'Ventas',
                'url': '/pos/sale/client/',
                'icon': 'fas fa-shopping-cart',
                'description': 'Permite administrar las ventas de los productos',
                'moduletype': None,
                'permissions': [Permission.objects.get(codename='view_sale_client')]
            },
            {
                'name': 'Notas de Credito',
                'url': '/pos/credit/note/client/',
                'icon': 'fa-solid fa-boxes-packing',
                'description': 'Permite administrar las notas de crédito de las ventas',
                'moduletype': None,
                'permissions': [Permission.objects.get(codename='view_credit_note_client')]
            },
            {
                'name': 'Promociones',
                'url': '/pos/promotions/',
                'icon': 'far fa-calendar-check',
                'description': 'Permite administrar las promociones de los productos',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=Promotions._meta.label.split('.')[1].lower()))
            },
            {
                'name': 'Errores de Comprob.',
                'url': '/pos/voucher/errors/',
                'icon': 'fas fa-file-archive',
                'description': 'Permite administrar los errores de los comprobantes de las facturas',
                'moduletype': moduletype,
                'permissions': list(Permission.objects.filter(content_type__model=VoucherErrors._meta.label.split('.')[1].lower()))
            }
        ])

        moduletype = ModuleType.objects.create(name='Reportes', icon='fas fa-chart-pie')
        print(f'insertado {moduletype.name}')

        modules_data.extend([
            {
                'name': 'Ventas',
                'url': '/reports/sale/',
                'icon': 'fas fa-chart-bar',
                'description': 'Permite ver los reportes de las ventas',
                'moduletype': moduletype,
                'permissions': None,
            },
            {
                'name': 'Compras',
                'url': '/reports/purchase/',
                'icon': 'fas fa-chart-bar',
                'description': 'Permite ver los reportes de las compras',
                'moduletype': moduletype,
                'permissions': None,
            },
            {
                'name': 'Gastos',
                'url': '/reports/expenses/',
                'icon': 'fas fa-chart-bar',
                'description': 'Permite ver los reportes de los gastos',
                'moduletype': moduletype,
                'permissions': None,
            },
            {
                'name': 'Cuentas por Pagar',
                'url': '/reports/debts/pay/',
                'icon': 'fas fa-chart-bar',
                'description': 'Permite ver los reportes de las cuentas por pagar',
                'moduletype': moduletype,
                'permissions': None,
            },
            {
                'name': 'Cuentas por Cobrar',
                'url': '/reports/ctas/collect/',
                'icon': 'fas fa-chart-bar',
                'description': 'Permite ver los reportes de las cuentas por cobrar',
                'moduletype': moduletype,
                'permissions': None,
            },
            {
                'name': 'Resultados',
                'url': '/reports/results/',
                'icon': 'fas fa-chart-bar',
                'description': 'Permite ver los reportes de pérdidas y ganancias',
                'moduletype': moduletype,
                'permissions': None,
            },
            {
                'name': 'Ganancias',
                'url': '/reports/earnings/',
                'icon': 'fas fa-chart-bar',
                'description': 'Permite ver los reportes de las ganancias',
                'moduletype': moduletype,
                'permissions': None,
            },
            {
                'name': 'Editar perfil',
                'url': '/pos/client/update/profile/',
                'icon': 'fas fa-user',
                'description': 'Permite cambiar la información de tu cuenta',
                'moduletype': None,
                'permissions': None,
            },
            {
                'name': 'Compañia',
                'url': '/pos/company/update/',
                'icon': 'fas fa-building',
                'description': 'Permite gestionar la información de la compañia',
                'moduletype': None,
                'permissions': [Permission.objects.get(codename='change_company')]
            },
        ])

        for module_data in modules_data:
            module = Module.objects.create(
                module_type=module_data['moduletype'],
                name=module_data['name'],
                url=module_data['url'],
                icon=module_data['icon'],
                description=module_data['description']
            )
            if module_data['permissions']:
                for permission in module_data['permissions']:
                    module.permissions.add(permission)
            print(f'insertado {module.name}')

        group = Group.objects.create(name='Administrador')
        print(f'insertado {group.name}')

        for module in Module.objects.filter().exclude(url__in=['/pos/client/update/profile/', '/pos/sale/client/', '/pos/credit/note/client/']):
            GroupModule.objects.create(module=module, group=group)
            for permission in module.permissions.all():
                group.permissions.add(permission)

        password = secrets.token_urlsafe(18)
        user = User.objects.create(
            names=options['admin_nombre'],
            username=options['admin_usuario'],
            email=options['admin_correo'],
            is_active=True,
            is_superuser=True,
            is_staff=True
        )
        user.set_password(password)
        user.save()
        user.groups.add(group)
        self.write_credentials(options['archivo_credenciales'], user.username, password)
        print(f'Administrador {user.username} creado; contraseña en {options["archivo_credenciales"]}')

        group = Group.objects.create(name='Cliente')
        print(f'insertado {group.name}')

        for module in Module.objects.filter(url__in=['/pos/client/update/profile/', '/pos/sale/client/', '/pos/credit/note/client/', '/user/update/password/']):
            GroupModule.objects.create(module=module, group=group)
            for permission in module.permissions.all():
                group.permissions.add(permission)

        # Roles de empresa sobre los módulos recién creados; los de la plataforma
        # (grupos, módulos, configuración global) solo para superusuarios.
        sync_roles(Group, Module, GroupModule)
        strip_platform_modules(Group, GroupModule)
        print('roles de empresa sincronizados')
