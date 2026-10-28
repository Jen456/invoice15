"""Carga compras, pagos y gastos como antes de la Etapa 2 (esquema histórico de pos 0019), para test_migracion_compras."""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.db.migrations.loader import MigrationLoader

apps = MigrationLoader(connection).project_state(('pos', '0019_orden_de_las_lineas')).apps
Company = apps.get_model('pos', 'Company')
Category = apps.get_model('pos', 'Category')
Product = apps.get_model('pos', 'Product')
Provider = apps.get_model('pos', 'Provider')
Purchase = apps.get_model('pos', 'Purchase')
PurchaseDetail = apps.get_model('pos', 'PurchaseDetail')
DebtsPay = apps.get_model('pos', 'DebtsPay')
PaymentsDebtsPay = apps.get_model('pos', 'PaymentsDebtsPay')
TypeExpense = apps.get_model('pos', 'TypeExpense')
Expenses = apps.get_model('pos', 'Expenses')

empresa = Company.objects.create(ruc='0991234567001', business_name='COMPRAS ANTERIORES S.A.', tradename='ANTERIORES',
                                 main_address='X', establishment_address='X', establishment_code='001', issuing_point_code='001',
                                 special_taxpayer='000', mobile='0990000000', phone='042000000', email='anteriores@example.com',
                                 website='', electronic_signature_key='', email_host_user='', email_host_password='')
categoria = Category.objects.create(company=empresa, name='INSUMOS')
producto = Product.objects.create(company=empresa, name='HARINA', code='HA-1', category=categoria, price=Decimal('1.00'),
                                  pvp=Decimal('2.00'), stock=7)
proveedor = Provider.objects.create(company=empresa, name='MOLINO FICTICIO S.A.', ruc='0990000001001', mobile='0990000001',
                                    email='molino@example.com')
contado = Purchase.objects.create(company=empresa, number='00000123', provider=proveedor, subtotal=Decimal('50.00'),
                                  date_joined=date(2026, 9, 1), end_credit=date(2026, 9, 1))
PurchaseDetail.objects.create(company=empresa, purchase=contado, product=producto, cant=5, price=Decimal('10.00'),
                              subtotal=Decimal('50.00'))
credito = Purchase.objects.create(company=empresa, number='00000124', provider=proveedor, payment_type='credito',
                                  subtotal=Decimal('100.00'), date_joined=date(2026, 9, 2), end_credit=date(2026, 10, 2))
PurchaseDetail.objects.create(company=empresa, purchase=credito, product=producto, cant=10, price=Decimal('10.00'),
                              subtotal=Decimal('100.00'))
deuda = DebtsPay.objects.create(company=empresa, purchase=credito, date_joined=date(2026, 9, 2), end_date=date(2026, 10, 2),
                                debt=Decimal('100.00'), saldo=Decimal('60.00'), state=True)
PaymentsDebtsPay.objects.create(company=empresa, debts_pay=deuda, date_joined=date(2026, 9, 10), valor=Decimal('40.00'),
                                description='Abono')
tipo = TypeExpense.objects.create(company=empresa, name='LUZ ELÉCTRICA')
Expenses.objects.create(company=empresa, type_expense=tipo, description='Planilla de luz', valor=Decimal('25.50'),
                        date_joined=date(2026, 9, 5))
print('compras anteriores cargadas')
