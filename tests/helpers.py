"""Utilidades para crear datos ficticios en las pruebas."""
from datetime import date, timedelta
from decimal import Decimal
from itertools import count

from django.contrib.auth.models import Group, Permission

from core.pos.models import Category, Client, Company, Product, Receipt, Sale, SaleDetail
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_CLIENT, ROLE_OWNER, Membership
from core.user.models import User

CLAVE = 'Clave-de-prueba-123'
_secuencia = count(1)


def crear_empresa(nombre='FICTICIA', plan='ilimitado', **extra):
    """Empresa ficticia; por defecto con un plan pagado vigente (plan=None = plan gratuito)."""
    n = next(_secuencia)
    datos = dict(ruc=f'09{n:08d}001', business_name=f'{nombre} S.A.', tradename=nombre,
                 main_address='Av. Ficticia 1', establishment_address='Av. Ficticia 1',
                 establishment_code='001', issuing_point_code='001', special_taxpayer='000',
                 mobile='0990000000', phone='042000000', email='empresa@example.com',
                 website='https://example.com', iva=Decimal('15.00'),
                 electronic_signature_key='', email_host_user='', email_host_password='')
    datos.update(extra)
    empresa = Company.objects.create(**datos)
    if plan:
        dar_plan(empresa, plan)
    return empresa


def dar_plan(empresa, codigo='ilimitado', inicio=None, meses=12, **extra):
    """Período pagado vigente sin pasar por PayPhone."""
    from django.utils import timezone

    from core.suscripciones.models import Plan, SubscriptionPeriod
    from core.suscripciones.reglas import sumar_meses
    plan = Plan.objects.get(code=codigo)
    inicio = inicio or timezone.now() - timedelta(days=1)
    datos = dict(company=empresa, plan=plan, status='activa', starts_at=inicio, ends_at=sumar_meses(inicio, meses),
                 document_limit=plan.document_limit)
    datos.update(extra)
    return SubscriptionPeriod.objects.create(**datos)


def crear_usuario(username, empresa=None, rol=ROLE_OWNER, superusuario=False, clave=CLAVE, activa=True):
    """Usuario con membresía en `empresa` y el rol indicado (nombre o Group)."""
    user = User.objects.create(username=username, names=username, email=f'{username}@example.com',
                               is_superuser=superusuario, is_staff=superusuario)
    user.set_password(clave)
    user.save()
    if empresa is not None:
        grupo = rol if isinstance(rol, Group) else Group.objects.get(name=rol)
        Membership.objects.create(user=user, company=empresa, group=grupo, is_active=activa)
    return user


def crear_grupo(nombre, codigos=()):
    grupo = Group.objects.create(name=nombre)
    for codigo in codigos:
        grupo.permissions.add(Permission.objects.get(codename=codigo))
    return grupo


def iniciar_sesion(client, user, clave=CLAVE, empresa=None):
    """Entra por el formulario real; si se indica, selecciona la empresa."""
    respuesta = client.post('/login/', {'username': user.username, 'password': clave})
    assert '_auth_user_id' in client.session, f'no se pudo iniciar sesión (HTTP {respuesta.status_code})'
    if empresa is not None:
        client.post('/empresas/cambiar/', {'company': empresa.id})
        assert client.session.get('company_id') == empresa.id
    return respuesta


def crear_cliente(username, empresa, dni, movil):
    user = User.objects.filter(username=username).first() or crear_usuario(username)
    Membership.objects.get_or_create(user=user, company=empresa, defaults={'group': Group.objects.get(name=ROLE_CLIENT)})
    with company_context(empresa):
        return Client.objects.create(user=user, dni=dni, mobile=movil, birthdate=date(1990, 1, 1),
                                     address='Guayaquil', send_email_invoice=False)


def crear_producto(empresa, codigo='P001', pvp='10.00', con_iva=True):
    with company_context(empresa):
        categoria, _ = Category.objects.get_or_create(name='CATEGORÍA FICTICIA')
        return Product.objects.create(name=f'PRODUCTO {codigo}', code=codigo, category=categoria,
                                      price=Decimal('5.00'), pvp=Decimal(pvp), stock=100, with_tax=con_iva)


def crear_venta(empresa, cliente, empleado, producto, cantidad=2):
    with company_context(empresa):
        receipt, _ = Receipt.objects.get_or_create(voucher_type='01', establishment_code='001',
                                                   issuing_point_code='001', defaults={'sequence': 0})
        numero = f'{receipt.sequence + 1:09d}'
        venta = Sale(client=cliente, receipt=receipt, employee=empleado, voucher_number=numero,
                     voucher_number_full=f'001-001-{numero}', iva=Decimal('15.00'), create_electronic_invoice=False)
        venta.save()
        SaleDetail.objects.create(sale=venta, product=producto, cant=cantidad, price=producto.pvp,
                                  price_with_vat=producto.pvp * Decimal('1.15'),
                                  subtotal=producto.pvp * cantidad, total=producto.pvp * cantidad)
        venta.calculate_invoice()
        return venta
