"""Ayudas de las pruebas de Proformas (datos ficticios; no modifica tests/helpers.py)."""
import json
from datetime import timedelta
from decimal import Decimal
from itertools import count

from django.utils import timezone

from core.pos.models import Category, Product
from core.proformas import servicios
from core.proformas.models import Proforma
from core.tenancy.context import company_context
from tests import helpers

# Anexo B de la especificación: una línea por tarifa. Gravado 51,70; cero 18,25; IVA 5,29; descuento 3,25; total 75,24.
EJEMPLO = (
    ('4', 'P15', '10.00', 3, 10),
    ('5', 'P5', '12.35', 2, 0),
    ('0', 'P0', '8.00', 1, 0),
    ('6', 'PNO', '5.50', 1, 0),
    ('7', 'PEX', '1.25', 4, 5),
)
_usuarios = count(1)


def productos_por_tarifa(empresa):
    """{'4', '5', '0', '6', '7'} → producto con esa tarifa y stock (idempotente por código)."""
    with company_context(empresa):
        categoria, _ = Category.objects.get_or_create(name='CATEGORÍA FICTICIA')
        productos = {}
        for tarifa, codigo, pvp, _, _ in EJEMPLO:
            productos[tarifa] = Product.objects.filter(code=codigo).first() or Product.objects.create(
                name=f'PRODUCTO {codigo}', code=codigo, category=categoria, price=Decimal('1.00'), pvp=Decimal(pvp),
                stock=100, tarifa_iva=tarifa)
        return productos


def lineas_ejemplo(productos):
    return [{'product': productos[tarifa].pk, 'cant': cant, 'price': precio, 'dscto': dscto, 'descripcion': ''}
            for tarifa, _, precio, cant, dscto in EJEMPLO]


def datos_ejemplo(productos, cliente=None, lineas=None, **extra):
    """POST del Anexo B (prospecto si no se da cliente)."""
    hoy = timezone.localdate()
    datos = {'cliente': cliente.pk if cliente is not None else '', 'cliente_nombre': 'PROSPECTO FICTICIO S.A.',
             'cliente_identificacion': '0990000001001', 'cliente_correo': 'compras@example.test',
             'cliente_telefono': '04 200-0000', 'cliente_direccion': 'Av. Ficticia 1',
             'fecha': hoy.isoformat(), 'valida_hasta': (hoy + timedelta(days=15)).isoformat(),
             'forma_pago_sugerida': '20', 'condiciones': 'Entrega inmediata.',
             'lineas': json.dumps(lineas if lineas is not None else lineas_ejemplo(productos))}
    datos.update(extra)
    return datos


FECHA_DE_ESTADO = {'enviada': 'enviada_en', 'aceptada': 'aceptada_en', 'rechazada': 'rechazada_en', 'anulada': 'anulada_en'}


def crear_proforma(empresa, usuario, datos=None, estado=None, valida_hasta=None):
    """servicios.crear en el contexto de la empresa; `estado` y `valida_hasta` se ajustan por .update() para las matrices
    (una validez pasada mueve también la fecha para respetar la CHECK)."""
    with company_context(empresa):
        p = servicios.crear(datos or datos_ejemplo(productos_por_tarifa(empresa)), usuario)
        cambios = {}
        if estado:
            cambios['estado'] = estado
            if estado in FECHA_DE_ESTADO:
                cambios[FECHA_DE_ESTADO[estado]] = timezone.now()
        if valida_hasta is not None:
            cambios['valida_hasta'] = valida_hasta
            cambios['fecha'] = min(p.fecha, valida_hasta)
        if cambios:
            Proforma.objects.filter(pk=p.pk).update(**cambios)
            p.refresh_from_db()
        return p


def web_con_rol(client, empresa, rol):
    """Usuario nuevo con ese rol en la empresa, con la sesión iniciada en ella."""
    nombre = rol if isinstance(rol, str) else rol.name
    usuario = helpers.crear_usuario(f'{nombre.lower()}.{empresa.pk}.{next(_usuarios)}', empresa, rol)
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    return usuario


def leer(empresa, consulta):
    """Lecturas de datos de empresa, dentro de su contexto (en PostgreSQL rige la seguridad por filas)."""
    with company_context(empresa):
        return consulta()


def ayer(dias=1):
    return timezone.localdate() - timedelta(days=dias)
