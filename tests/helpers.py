"""Utilidades para crear datos ficticios en las pruebas."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import Group, Permission

from core.pos.models import Category, Client, Company, Product, Receipt, Sale, SaleDetail
from core.user.models import User

CLAVE = 'Clave-de-prueba-123'


def crear_usuario(username, grupos=(), superusuario=False, clave=CLAVE):
    user = User.objects.create(username=username, names=username, email=f'{username}@example.com',
                               is_superuser=superusuario, is_staff=superusuario)
    user.set_password(clave)
    user.save()
    for g in grupos:
        user.groups.add(g)
    return user


def crear_grupo(nombre, codigos=()):
    grupo = Group.objects.create(name=nombre)
    for codigo in codigos:
        grupo.permissions.add(Permission.objects.get(codename=codigo))
    return grupo


def iniciar_sesion(client, user, clave=CLAVE):
    """Entra por el formulario real para que la sesión tenga el perfil activo."""
    respuesta = client.post('/login/', {'username': user.username, 'password': clave})
    assert '_auth_user_id' in client.session, f'no se pudo iniciar sesión (HTTP {respuesta.status_code})'
    return respuesta


def crear_empresa(**extra):
    datos = dict(ruc='0990000000001', business_name='EMPRESA FICTICIA S.A.', tradename='FICTICIA',
                 main_address='Av. Ficticia 1', establishment_address='Av. Ficticia 1',
                 establishment_code='001', issuing_point_code='001', special_taxpayer='000',
                 mobile='0990000000', phone='042000000', email='empresa@example.com',
                 website='https://example.com', iva=Decimal('15.00'),
                 electronic_signature_key='', email_host_user='', email_host_password='')
    datos.update(extra)
    return Company.objects.create(**datos)


def crear_cliente(username, grupo_cliente, dni, movil):
    user = crear_usuario(username, grupos=[grupo_cliente])
    return Client.objects.create(user=user, dni=dni, mobile=movil, birthdate=date(1990, 1, 1),
                                 address='Guayaquil', send_email_invoice=False)


def crear_producto(codigo='P001', pvp='10.00', con_iva=True):
    categoria, _ = Category.objects.get_or_create(name='CATEGORÍA FICTICIA')
    return Product.objects.create(name=f'PRODUCTO {codigo}', code=codigo, category=categoria,
                                  price=Decimal('5.00'), pvp=Decimal(pvp), stock=100, with_tax=con_iva)


def crear_venta(empresa, cliente, empleado, producto, cantidad=2):
    receipt, _ = Receipt.objects.get_or_create(voucher_type='01', establishment_code='001',
                                               issuing_point_code='001', defaults={'sequence': 0})
    numero = f'{receipt.sequence + 1:09d}'
    venta = Sale(company=empresa, client=cliente, receipt=receipt, employee=empleado,
                 voucher_number=numero, voucher_number_full=f'001-001-{numero}',
                 iva=Decimal('15.00'), create_electronic_invoice=False)
    venta.save()
    SaleDetail.objects.create(sale=venta, product=producto, cant=cantidad, price=producto.pvp,
                              price_with_vat=producto.pvp * Decimal('1.15'),
                              subtotal=producto.pvp * cantidad, total=producto.pvp * cantidad)
    venta.calculate_invoice()
    return venta
