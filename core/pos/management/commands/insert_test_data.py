import json
import os
import random
import secrets
import string
from os.path import basename

import django
from django.core.management import BaseCommand, CommandError

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.security.models import *
from core.pos.models import *


class Command(BaseCommand):
    help = (
        'Carga datos FICTICIOS de demostración (empresa, productos, proveedores, compras y clientes). '
        'No incluye firma electrónica ni credenciales de correo. Nunca en producción.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--confirmar-datos-ficticios', action='store_true',
                            help='Obligatorio: confirma que se cargan datos ficticios.')

    def handle(self, *args, **options):
        if not options['confirmar_datos_ficticios']:
            raise CommandError('Indica --confirmar-datos-ficticios para cargar datos de demostración.')
        if getattr(settings, 'FPA_ENTORNO', '') == 'produccion':
            raise CommandError('No se cargan datos de demostración en producción.')
        if Company.objects.exists():
            raise CommandError('Ya existe una empresa: no se mezclan datos de demostración con datos reales.')
        company = Company.objects.create(
            business_name='EMPRESA DE DEMOSTRACIÓN S.A.',
            tradename='DEMOSTRACIÓN',
            ruc='0990000000001',
            establishment_code='001',
            issuing_point_code='001',
            special_taxpayer='000',
            main_address='AV. FICTICIA 123, GUAYAQUIL',
            establishment_address='AV. FICTICIA 123, GUAYAQUIL',
            mobile='0990000000',
            phone='042000000',
            email='demo@example.com',
            website='https://example.com',
            description='DATOS FICTICIOS PARA PRUEBAS.',
            iva=15.00,
        )
        image_path = f'{settings.BASE_DIR}{settings.STATIC_URL}img/default/logo.png'
        company.image.save(basename(image_path), content=File(open(image_path, 'rb')), save=False)
        company.save()

        numbers = list(string.digits)
        for item in VOUCHER_TYPE:
            sequence = 1 if item[0] == VOUCHER_TYPE[-1][0] else int(''.join(random.choices(numbers, k=7)))
            Receipt.objects.create(voucher_type=item[0], establishment_code=company.establishment_code, issuing_point_code=company.issuing_point_code, sequence=sequence)

        with open(f'{settings.BASE_DIR}/deploy/json/products.json', encoding='utf8') as json_file:
            for item in json.load(json_file):
                product = Product.objects.create(
                    name=item['name'],
                    code=item['code'],
                    category=Category.objects.get_or_create(name=item['category'])[0],
                    price=float(item['price']),
                    pvp=float(item['pvp'])
                )
                print(f'record inserted product {product.id}')

        category = Category.objects.create(name='SERVICIOS')
        Product.objects.create(name='FORMATEO DE COMPUTADORAS', category=category, inventoried=False, with_tax=False, pvp=15.00, code='FORMATEO85451')

        with open(f'{settings.BASE_DIR}/deploy/json/customers.json', encoding='utf8') as json_file:
            data = json.load(json_file)
            for item in data[0:20]:
                provider = Provider.objects.create(
                    name=item['company'].upper(),
                    ruc=''.join(random.choices(numbers, k=13)),
                    mobile=''.join(random.choices(numbers, k=10)),
                    address=item['country'],
                    email=item['email']
                )
                print(f'record inserted provider {provider.id}')

        provider_id = list(Provider.objects.values_list('id', flat=True))
        product_id = list(Product.objects.filter(inventoried=True).values_list('id', flat=True))
        for i in range(1, 10):
            purchase = Purchase.objects.create(
                number=''.join(random.choices(numbers, k=8)),
                provider_id=random.choice(provider_id)
            )
            print(f'record inserted purchase {purchase.id}')

            for d in range(1, 5):
                detail = PurchaseDetail.objects.create(
                    purchase=purchase,
                    product_id=random.choice(product_id),
                    cant=random.randint(1, 50)
                )
                while purchase.purchasedetail_set.filter(product_id=detail.product_id).exists():
                    detail.product_id = random.choice(product_id)
                detail.price = detail.product.pvp
                detail.subtotal = float(detail.price) * detail.cant
                detail.save()
                detail.product.stock += detail.cant
                detail.product.save()
            purchase.calculate_invoice()

        user_data = [
            {
                'names': 'Consumidor Final',
                'email': 'consumidor.final@example.com',
                'username': '9999999999999',
                'mobile': '9999999999',
                'birthdate': date(1990, 1, 1),
                'address': 'S/N',
                'identification_type': IDENTIFICATION_TYPE[3][0],
                'send_email_invoice': False
            },
            {
                'names': 'Cliente Ficticio Uno',
                'email': 'cliente.uno@example.com',
                'username': '0900000001',
                'mobile': '0990000001',
                'birthdate': date(1990, 1, 1),
                'address': 'Guayaquil',
                'identification_type': IDENTIFICATION_TYPE[0][0],
                'send_email_invoice': False
            },
            {
                'names': 'COMERCIAL FICTICIA S.A.',
                'email': 'comercial.ficticia@example.com',
                'username': '0990000002001',
                'mobile': '0990000002',
                'birthdate': date(1990, 1, 1),
                'address': 'Quito',
                'identification_type': IDENTIFICATION_TYPE[1][0],
                'send_email_invoice': False
            }
        ]

        for data in user_data:
            user = User.objects.create(
                names=data['names'],
                email=data['email'],
                username=data['username'],
                is_active=True,
                is_staff=True
            )
            user.set_password(secrets.token_urlsafe(18))
            user.save()
            user.groups.add(Group.objects.get(pk=settings.GROUPS['client']))

            Client.objects.create(
                user=user,
                dni=user.username,
                mobile=data['mobile'],
                birthdate=data['birthdate'],
                address=data['address'],
                identification_type=data['identification_type'],
                send_email_invoice=data['send_email_invoice']
            )
