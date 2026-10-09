"""Carga datos al estilo del código original (sin empresa) usando el esquema histórico."""
from datetime import date

from django.db import connection
from django.db.migrations.loader import MigrationLoader

apps = MigrationLoader(connection).project_state(('pos', '0002_initial')).apps
Company = apps.get_model('pos', 'Company')
Category = apps.get_model('pos', 'Category')
Product = apps.get_model('pos', 'Product')
Client = apps.get_model('pos', 'Client')
Group = apps.get_model('auth', 'Group')
User = apps.get_model('user', 'User')

Company.objects.create(ruc='0991234567001', business_name='EMPRESA ORIGINAL S.A.', tradename='ORIGINAL',
                       main_address='X', establishment_address='X', establishment_code='001',
                       issuing_point_code='001', special_taxpayer='000', mobile='0990000000', phone='042000000',
                       email='o@example.com', website='', electronic_signature_key='', email_host_user='',
                       email_host_password='')
categoria = Category.objects.create(name='BEBIDAS')
Product.objects.create(name='AGUA', code='AG-1', category=categoria, price=1, pvp=1.5)
admin_group = Group.objects.create(name='Administrador')
cajero_group = Group.objects.create(name='Cajero')
User.objects.create(username='jefe', names='Jefe', is_superuser=True, password='!')
User.objects.create(username='admin.local', names='Admin', password='!').groups.add(admin_group)
User.objects.create(username='cajero', names='Cajero', password='!').groups.add(cajero_group)
cliente_user = User.objects.create(username='0912345678', names='Cliente', password='!')
Client.objects.create(user=cliente_user, dni='0912345678', mobile='0991234567', birthdate=date(1990, 1, 1),
                      address='Guayaquil')
print('legado cargado')
