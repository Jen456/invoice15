import json
import random
import secrets
import string
from datetime import date
from os.path import basename

from django.contrib.auth.models import Group
from django.core.files import File
from django.core.management import BaseCommand, CommandError

from config import settings
from core.pos.choices import IDENTIFICATION_TYPE, VOUCHER_TYPE
from core.pos.models import Category, Client, Company, Product, Provider, Purchase, PurchaseDetail, Receipt
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_CLIENT, Membership
from core.user.models import User


class Command(BaseCommand):
    help = (
        'Crea una empresa FICTICIA de demostración con productos, proveedores, compras y clientes. '
        'No incluye firma electrónica ni credenciales de correo. Nunca en producción.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--confirmar-datos-ficticios', action='store_true',
                            help='Obligatorio: confirma que se cargan datos ficticios.')
        parser.add_argument('--ruc', default='0990000000001', help='RUC ficticio de la empresa (13 dígitos).')
        parser.add_argument('--nombre', default='DEMOSTRACIÓN', help='Nombre comercial ficticio.')
        parser.add_argument('--propietario', help='Crea además un usuario Propietario con este nombre de usuario.')
        parser.add_argument('--archivo-credenciales', help='Ruta nueva (0600) donde se guarda la contraseña del propietario.')

    def handle(self, *args, **options):
        if not options['confirmar_datos_ficticios']:
            raise CommandError('Indica --confirmar-datos-ficticios para cargar datos de demostración.')
        if getattr(settings, 'FPA_ENTORNO', '') == 'produccion':
            raise CommandError('No se cargan datos de demostración en producción.')
        if Company.objects.filter(ruc=options['ruc']).exists():
            raise CommandError(f'Ya existe una empresa con RUC {options["ruc"]}.')
        nombre = options['nombre'].upper()
        company = Company.objects.create(
            business_name=f'{nombre} S.A.', tradename=nombre, ruc=options['ruc'],
            establishment_code='001', issuing_point_code='001', special_taxpayer='000',
            main_address='AV. FICTICIA 123, GUAYAQUIL', establishment_address='AV. FICTICIA 123, GUAYAQUIL',
            mobile='0990000000', phone='042000000', email='demo@example.com', website='https://example.com',
            description='DATOS FICTICIOS PARA PRUEBAS.', iva=15.00,
            electronic_signature_key='', email_host_user='', email_host_password='',
        )
        with company_context(company):
            self.load(company)
        self.stdout.write(f'Empresa ficticia {company.tradename} (id {company.id}) creada.')
        if options['propietario']:
            self.crear_propietario(company, options['propietario'], options['archivo_credenciales'])

    def crear_propietario(self, company, username, ruta):
        import os
        from core.tenancy.models import ROLE_OWNER
        if not ruta:
            raise CommandError('Indica --archivo-credenciales para guardar la contraseña del propietario.')
        clave = secrets.token_urlsafe(15)
        user = User.objects.create(username=username, names=f'Propietario {company.tradename}',
                                   email=f'{username}@example.com')
        user.set_password(clave)
        user.save()
        Membership.objects.create(user=user, company=company, group=Group.objects.get(name=ROLE_OWNER))
        fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(f'Usuario: {username}\nContraseña: {clave}\n')
        self.stdout.write(f'Propietario {username} creado; contraseña en {ruta}')

    def load(self, company):
        image_path = f'{settings.BASE_DIR}{settings.STATIC_URL}img/default/logo.png'
        company.image.save(basename(image_path), content=File(open(image_path, 'rb')), save=False)
        company.save()

        numbers = list(string.digits)
        for item in VOUCHER_TYPE:
            sequence = 1 if item[0] == VOUCHER_TYPE[-1][0] else int(''.join(random.choices(numbers, k=7)))
            Receipt.objects.create(voucher_type=item[0], establishment_code=company.establishment_code,
                                   issuing_point_code=company.issuing_point_code, sequence=sequence)

        with open(f'{settings.BASE_DIR}/deploy/json/products.json', encoding='utf8') as json_file:
            for item in json.load(json_file):
                Product.objects.create(
                    name=item['name'], code=item['code'],
                    category=Category.objects.get_or_create(name=item['category'])[0],
                    price=float(item['price']), pvp=float(item['pvp']))
        category = Category.objects.create(name='SERVICIOS')
        Product.objects.create(name='FORMATEO DE COMPUTADORAS', category=category, inventoried=False, with_tax=False,
                               pvp=15.00, code='FORMATEO85451')

        with open(f'{settings.BASE_DIR}/deploy/json/customers.json', encoding='utf8') as json_file:
            for item in json.load(json_file)[0:20]:
                Provider.objects.create(name=item['company'].upper(), ruc=''.join(random.choices(numbers, k=13)),
                                        mobile=''.join(random.choices(numbers, k=10)), address=item['country'],
                                        email=item['email'])

        provider_ids = list(Provider.objects.values_list('id', flat=True))
        product_ids = list(Product.objects.filter(inventoried=True).values_list('id', flat=True))
        for _ in range(1, 10):
            purchase = Purchase.objects.create(number=''.join(random.choices(numbers, k=8)),
                                               provider_id=random.choice(provider_ids))
            for product_id in random.sample(product_ids, 4):
                detail = PurchaseDetail.objects.create(purchase=purchase, product_id=product_id,
                                                       cant=random.randint(1, 50))
                detail.price = detail.product.pvp
                detail.subtotal = float(detail.price) * detail.cant
                detail.save()
                detail.product.stock += detail.cant
                detail.product.save()
            purchase.calculate_invoice()

        client_role = Group.objects.get(name=ROLE_CLIENT)
        suffix = company.ruc[-5:-3]
        clients = [
            ('Consumidor Final', 'consumidor.final@example.com', '9999999999999', '9999999999', IDENTIFICATION_TYPE[3][0]),
            ('Cliente Ficticio Uno', f'cliente.uno.{suffix}@example.com', f'09000000{suffix}', f'09900000{suffix}', IDENTIFICATION_TYPE[0][0]),
            ('COMERCIAL FICTICIA S.A.', f'comercial.{suffix}@example.com', f'09900000{suffix}001', f'09910000{suffix}', IDENTIFICATION_TYPE[1][0]),
        ]
        for names, email, username, mobile, identification_type in clients:
            user, created = User.objects.get_or_create(username=username, defaults={'names': names, 'email': email})
            if created:
                user.set_password(secrets.token_urlsafe(18))
                user.save()
            Membership.objects.get_or_create(user=user, company=company, defaults={'group': client_role})
            Client.objects.create(user=user, dni=username, mobile=mobile, birthdate=date(1990, 1, 1),
                                  address='Guayaquil', identification_type=identification_type,
                                  send_email_invoice=False)
