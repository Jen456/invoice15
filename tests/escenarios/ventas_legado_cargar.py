"""Carga ventas «de antes» de la Etapa 2 (O2) con los modelos históricos de pos 0019 y comprobantes 0013: empresa del
registro (special_taxpayer=''), cliente, factura autorizada sin emission_date, su CxC con un cobro, una nota de crédito y una
nota de débito autorizadas. Datos ficticios."""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.db.migrations.loader import MigrationLoader

apps = MigrationLoader(connection).project_state([('pos', '0019_orden_de_las_lineas'),
                                                  ('comprobantes', '0013_modulo_guias')]).apps
Company = apps.get_model('pos', 'Company')
User = apps.get_model('user', 'User')
Client = apps.get_model('pos', 'Client')
Receipt = apps.get_model('pos', 'Receipt')
Sale = apps.get_model('pos', 'Sale')
CtasCollect = apps.get_model('pos', 'CtasCollect')
PaymentsCtaCollect = apps.get_model('pos', 'PaymentsCtaCollect')
CreditNote = apps.get_model('pos', 'CreditNote')
NotaDebito = apps.get_model('comprobantes', 'NotaDebito')

empresa = Company.objects.create(ruc='0990000001001', business_name='LEGADO VENTAS S.A.', tradename='LEGADO',
                                 main_address='Av. Ficticia 1', establishment_address='Av. Ficticia 1', establishment_code='001',
                                 issuing_point_code='001', special_taxpayer='', mobile='0990000000', phone='042000000',
                                 email='legado@example.com', website='', electronic_signature_key='', email_host_user='',
                                 email_host_password='', environment_type=2)
vendedor = User.objects.create(username='vendedor.legado', names='Vendedor', password='!')
usuario = User.objects.create(username='cliente.legado', names='CLIENTE LEGADO S.A.', password='!')
cliente = Client.objects.create(company=empresa, user=usuario, dni='0991234567001', identification_type='04', mobile='0990000001',
                                birthdate=date(1990, 1, 1), address='Guayaquil')
facturas = Receipt.objects.create(company=empresa, voucher_type='01', establishment_code='001', issuing_point_code='001',
                                  sequence=10, environment_type=2)
notas = Receipt.objects.create(company=empresa, voucher_type='04', establishment_code='001', issuing_point_code='001',
                               sequence=3, environment_type=2)
debitos = Receipt.objects.create(company=empresa, voucher_type='05', establishment_code='001', issuing_point_code='001',
                                 sequence=2, environment_type=2)
venta = Sale.objects.create(company=empresa, client=cliente, receipt=facturas, voucher_number='000000010',
                            voucher_number_full='001-001-000000010', employee=vendedor, payment_type='credito',
                            date_joined=date(2025, 11, 3), end_credit=date(2025, 12, 3), subtotal_12=Decimal('20.00'),
                            total_iva=Decimal('3.00'), total=Decimal('23.00'), environment_type=2, status='authorized',
                            authorization_date=date(2025, 11, 3), access_code='1' * 49, creation_date=date(2025, 11, 3))
cuenta = CtasCollect.objects.create(company=empresa, sale=venta, date_joined=date(2025, 11, 3), end_date=date(2025, 12, 3),
                                    debt=Decimal('23.00'), saldo=Decimal('13.00'), state=True)
PaymentsCtaCollect.objects.create(company=empresa, ctas_collect=cuenta, date_joined=date(2025, 11, 10), description='Abono',
                                  valor=Decimal('10.00'))
CreditNote.objects.create(company=empresa, sale=venta, receipt=notas, voucher_number='000000003',
                          voucher_number_full='001-001-000000003', motive='Devolución', total=Decimal('5.00'), environment_type=2,
                          status='authorized', date_joined=date(2025, 11, 20))
NotaDebito.objects.create(company=empresa, receipt=debitos, voucher_number='000000002', voucher_number_full='001-001-000000002',
                          employee=vendedor, environment_type=2, status='authorized', sale=venta, tipo_identificacion='04',
                          identificacion='0991234567001', razon_social='CLIENTE LEGADO S.A.', num_doc_modificado='001-001-000000010',
                          fecha_doc_sustento=date(2025, 11, 3), tarifa_iva=Decimal('0'), total_sin_impuestos=Decimal('3.00'),
                          valor_total=Decimal('3.00'), emission_date=date(2025, 11, 25))
print('ventas de antes cargadas')
