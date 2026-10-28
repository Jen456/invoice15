"""Ayudas de las pruebas de Compras (espec-etapa2-compras §7): proveedores, compras anteriores y datos de compra ficticios.

Todo es ficticio (RUC de prueba, correos @example.com). No se toca tests/helpers.py.
"""
from datetime import timedelta
from decimal import Decimal
from itertools import count

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from django.utils import timezone

from core.pos.models import Category, DebtsPay, Product, Provider, Purchase, PurchaseDetail, TypeExpense
from core.tenancy.context import company_context

_n = count(1)
_secuencial = count(101)


def cedula(n):
    """Cédula ficticia válida (provincia 09, dígito verificador módulo 10)."""
    base = f'091{n % 1000000:06d}'
    total = 0
    for i, coeficiente in enumerate((2, 1, 2, 1, 2, 1, 2, 1, 2)):
        producto = int(base[i]) * coeficiente
        total += producto - 9 if producto > 9 else producto
    return base + str((10 - total % 10) % 10)


def en(empresa, funcion, *args, **kwargs):
    with company_context(empresa):
        return funcion(*args, **kwargs)


def crear_proveedor(empresa, tipo='04', ruc=None, parte_relacionada=False, tipo_sujeto=None, nombre=None, correo=None):
    """Proveedor con los datos del ATS completos (tipo '' = proveedor anterior, sin datos del ATS)."""
    n = next(_n)
    if ruc is None:
        ruc = {'04': f'099{n:07d}001', '05': cedula(n), '06': f'PA{n:07d}', '08': f'EXT-{n:07d}', '': f'099{n:07d}001'}[tipo]
    if tipo_sujeto is None:
        tipo_sujeto = {'04': '02' if ruc[2] in '69' else '01', '05': '01'}.get(tipo, '01' if tipo else '')
    with company_context(empresa):
        return Provider.objects.create(name=nombre or f'PROVEEDOR FICTICIO {n} S.A.', ruc=ruc, mobile=f'09{n:08d}',
                                       email=correo or f'proveedor{n}@example.com', address='Av. Ficticia 100',
                                       tipo_identificacion=tipo, tipo_sujeto=tipo_sujeto if tipo else '',
                                       parte_relacionada=parte_relacionada if tipo else None)


def crear_producto(empresa, codigo=None, inventariado=True, tarifa='4', stock=100):
    with company_context(empresa):
        categoria, _ = Category.objects.get_or_create(name='CATEGORÍA DE COMPRAS')
        codigo = codigo or f'C{next(_n):05d}'
        return Product.objects.create(name=f'PRODUCTO {codigo}', code=codigo, category=categoria, price=Decimal('5.00'),
                                      pvp=Decimal('10.00'), stock=stock, inventoried=inventariado, tarifa_iva=tarifa)


def crear_tipo_gasto(empresa, nombre=None, cod_sustento=''):
    with company_context(empresa):
        return TypeExpense.objects.create(name=nombre or f'GASTO {next(_n)}', cod_sustento=cod_sustento)


def compra_antigua(empresa, proveedor, subtotal, credito=False, producto=None, cantidad=1, fecha=None):
    """Compra registrada como antes de la Etapa 2 (Purchase.objects.create: version_datos=1 e incompleta por defecto)."""
    subtotal = Decimal(subtotal)
    fecha = fecha or timezone.localdate() - timedelta(days=10)
    with company_context(empresa):
        compra = Purchase.objects.create(number=f'{next(_n):08d}', provider=proveedor, subtotal=subtotal, date_joined=fecha,
                                         end_credit=fecha + timedelta(days=30),
                                         payment_type='credito' if credito else 'efectivo')
        if producto is not None:
            PurchaseDetail.objects.create(purchase=compra, product=producto, cant=cantidad, price=subtotal / cantidad,
                                          subtotal=subtotal)
        if credito:
            DebtsPay.objects.create(purchase=compra, date_joined=fecha, end_date=fecha + timedelta(days=30), debt=subtotal,
                                    saldo=subtotal)
        return compra


def datos_compra(proveedor, **cambios):
    """Cabecera de una factura completa (modo «si»), con la forma de pago y el sustento elegidos expresamente."""
    hoy = timezone.localdate()
    datos = {'provider': proveedor.pk, 'modo_comprobante': 'si', 'tipo_comprobante': '01', 'cod_sustento': '06',
             'estab': '001', 'pto_emi': '002', 'secuencial': str(next(_secuencial)), 'autorizacion': '1234567890',
             'fecha_emision': (hoy - timedelta(days=2)).isoformat(), 'date_joined': hoy.isoformat(), 'parte_relacionada': 'no',
             'payment_type': 'efectivo', 'end_credit': '', 'forma_pago': '20', 'pago_loc_ext': '01'}
    datos.update(cambios)
    return datos


def linea_producto(producto, cant=1, price='10.00', codigo='4', descuento='0.00'):
    return {'tipo': 'producto', 'product': producto.pk, 'cant': cant, 'price': price, 'descuento': descuento,
            'codigo_porcentaje': codigo}


def linea_gasto(descripcion='Mantenimiento de equipos', price='100.00', codigo='4', tarifa=None, type_expense=None, cant=1,
                descuento='0.00'):
    linea = {'tipo': 'gasto', 'descripcion': descripcion, 'cant': cant, 'price': price, 'descuento': descuento,
             'codigo_porcentaje': codigo, 'type_expense': type_expense.pk if type_expense else None}
    if tarifa is not None:
        linea['tarifa'] = tarifa
    return linea


def peticion(usuario, empresa):
    """Petición con el usuario y su membresía en la empresa (lo que deja el middleware), para servicios que miran el perfil."""
    from core.tenancy.models import Membership
    request = RequestFactory().post('/')
    request.user = usuario
    request.company = empresa
    request.membership = Membership.objects.filter(user=usuario, company=empresa).select_related('group').first()
    return request


def permiso_retencion_recibida(grupo):
    """add_retencionrecibida (permiso que crea O2): lo crea si todavía no existe en la rama y lo añade al grupo."""
    tipo, _ = ContentType.objects.get_or_create(app_label='comprobantes', model='retencionrecibida')
    permiso, _ = Permission.objects.get_or_create(codename='add_retencionrecibida', content_type=tipo,
                                                  defaults={'name': 'Puede registrar retenciones recibidas'})
    grupo.permissions.add(permiso)
    return permiso
