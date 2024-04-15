import json
import os
import random
import string
from os.path import basename

import django
from django.core.management import BaseCommand

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.security.models import *
from core.pos.models import *


class Command(BaseCommand):
    help = "It allows me to insert test data into the software"

    def handle(self, *args, **options):
        company = Company.objects.create(
            business_name='VELEZ AGUIRRE SIMON EDUARDO',
            tradename='PUNTOHELP',
            ruc='0921637781001',
            establishment_code='003',
            issuing_point_code='003',
            special_taxpayer='000',
            main_address='5 DE OCTUBRE Y 10 DE AGOSTO NARANJITO,GUAYAS',
            establishment_address='5 DE OCTUBRE Y 10 DE AGOSTO NARANJITO,GUAYAS',
            mobile='0996555528',
            phone='2977557',
            email='puntohelpsa@gmail.com',
            website='https://puntohelp.com',
            description='VENTA AL POR MAYOR DE COMPUTADORAS Y EQUIPO PERIFÉRICO.',
            iva=15.00,
            electronic_signature_key='224426rajansn',
            email_host_user='factorapos19@gmail.com',
            email_host_password='nbkqthnfkysfuudn'
        )
        image_path = f'{settings.BASE_DIR}{settings.STATIC_URL}img/default/logo.png'
        company.image.save(basename(image_path), content=File(open(image_path, 'rb')), save=False)
        electronic_signature_path = f'{settings.BASE_DIR}/deploy/files/firma.p12'
        company.electronic_signature.save(basename(electronic_signature_path), content=File(open(electronic_signature_path, 'rb')), save=False)
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
                'email': 'davilawilliam94@gmail.com',
                'username': '9999999999999',
                'password': '9999999999999',
                'mobile': '9999999999',
                'birthdate': date(1994, 10, 19),
                'address': 'Milagro, cdla. Paquisha',
                'identification_type': IDENTIFICATION_TYPE[3][0],
                'send_email_invoice': False
            },
            {
                'names': 'William Jair Dávila Vargas',
                'email': 'wdavilav1994@gmail.com',
                'username': '0928363993',
                'password': '0928363993',
                'mobile': '0979014551',
                'birthdate': date(1994, 10, 19),
                'address': 'Milagro, cdla. Paquisha',
                'identification_type': IDENTIFICATION_TYPE[0][0],
                'send_email_invoice': False
            },
            {
                'names': 'LIBRIMUNDI LIBRERÍA INTERNACIONAL S.A.',
                'email': 'williamjairdavilavargas@gmail.com',
                'username': '1791411293001',
                'password': '1791411293001',
                'mobile': '0979014552',
                'birthdate': date(1994, 10, 19),
                'address': 'Milagro, cdla. Paquisha',
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
            user.set_password(data['password'])
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
