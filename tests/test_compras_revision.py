"""Regresiones de la revisión de O1 (Compras): cada prueba falla sin su corrección (ids O1-F* y O1-T* de la revisión).

Datos ficticios; en PostgreSQL todo se lee dentro de la empresa activa (seguridad por filas).
"""
import csv
import json
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from core.comprobantes import liquidaciones
from core.comprobantes.models import LiquidacionCompra, Retencion
from core.pos import compras
from core.pos.management.commands import _ensayo
from core.pos.models import DebtsPay, Product, Provider, Purchase, Receipt
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER
from tests import ayuda_compras as ayuda, helpers

pytestmark = pytest.mark.django_db
RUC = '0990000001001'


def hoy():
    return timezone.localdate()


def crear(empresa, usuario, datos, lineas, **kw):
    with company_context(empresa):
        return compras.crear_compra(empresa, usuario, datos, lineas, **kw)


def recargar(empresa, compra):
    with company_context(empresa):
        return Purchase.objects.select_related('provider').get(pk=compra.pk)


def completar(empresa, usuario, compra, datos):
    with company_context(empresa):
        return compras.completar_datos(recargar(empresa, compra), usuario, datos)


def error_al_completar(empresa, usuario, compra, datos):
    with pytest.raises(compras.ErrorCompra) as e:
        completar(empresa, usuario, compra, datos)
    return e.value


def saldos(empresa, *facturas):
    """(saldo guardado, saldo recalculado sin guardar) de la cuenta por pagar de cada compra."""
    with company_context(empresa):
        resultado = []
        for factura in facturas:
            deuda = DebtsPay.objects.get(purchase=factura)
            resultado.append((deuda.saldo, DebtsPay.objects.get(pk=deuda.pk).recalcular(guardar=False)))
        return resultado


def codigos(empresa, compra):
    with company_context(empresa):
        return [c for c, _ in compras.faltantes(recargar(empresa, compra))]


def a_credito(proveedor, **cambios):
    return ayuda.datos_compra(proveedor, payment_type='credito', end_credit=(hoy() + timedelta(days=30)).isoformat(), **cambios)


def nota_sobre(factura, **cambios):
    datos = {'tipo_comprobante': '04', 'tipo_doc_modificado': '01',
             'num_doc_modificado': f'{factura.estab}{factura.pto_emi}{factura.secuencial}', 'aut_doc_modificado': '1234567890',
             'fecha_doc_modificado': factura.fecha_emision.isoformat(), 'compra_modificada': factura.pk}
    datos.update(cambios)
    return datos


def receipt(empresa, tipo):
    with company_context(empresa):
        return Receipt.objects.get_or_create(voucher_type=tipo, establishment_code='001', issuing_point_code='001',
                                             defaults={'sequence': 0})[0]


def liquidacion_autorizada(empresa, usuario, compra, ambiente=2, **importes):
    with company_context(empresa):
        return LiquidacionCompra.objects.create(
            company=empresa, receipt=receipt(empresa, '03'), voucher_number='000000001', voucher_number_full='001-001-000000001',
            employee=usuario, environment_type=ambiente, purchase=compra, provider=compra.provider, tipo_identificacion='05',
            identificacion=compra.provider.ruc, razon_social='PRODUCTORA FICTICIA', status='authorized', **importes)


@pytest.fixture
def proveedor(empresa):
    return ayuda.crear_proveedor(empresa, tipo='04', ruc=RUC)


@pytest.fixture
def productora(empresa):
    return ayuda.crear_proveedor(empresa, tipo='05')


def modo_liquidacion(productora, **cambios):
    datos = {'provider': productora.pk, 'modo_comprobante': 'liquidacion', 'cod_sustento': '02', 'forma_pago': '01',
             'parte_relacionada': 'no', 'pago_loc_ext': '01', 'date_joined': hoy().isoformat()}
    datos.update(cambios)
    return datos


# ------------------------------------------------------------------ O1-F5 y O1-F7: la liquidación que completa la compra 03

class TestLiquidacionQueCompleta:

    def test_liquidacion_de_pruebas_no_completa_la_compra(self, empresa, admin, productora):
        compra = crear(empresa, admin, modo_liquidacion(productora), [ayuda.linea_gasto(price='50.00', codigo='0')])
        liquidacion = liquidacion_autorizada(empresa, admin, compra, ambiente=1, total_sin_impuestos=Decimal('50.00'),
                                             importe_total=Decimal('50.00'))
        with company_context(empresa):
            compras.al_autorizar_liquidacion(liquidacion)
            faltan = compras.faltantes(recargar(empresa, compra))
        assert [c for c, _ in faltan] == ['liquidacion_pendiente'] and 'PRUEBAS' in faltan[0][1]
        assert recargar(empresa, compra).datos_incompletos
        with company_context(empresa):
            LiquidacionCompra.objects.filter(pk=liquidacion.pk).update(environment_type=2)
            compras.al_autorizar_liquidacion(LiquidacionCompra.objects.get(pk=liquidacion.pk))
        assert not recargar(empresa, compra).datos_incompletos

    def test_liquidacion_que_no_coincide_deja_la_compra_incompleta(self, empresa, admin, productora):
        compra = crear(empresa, admin, modo_liquidacion(productora), [ayuda.linea_gasto(price='100.00')])
        liquidacion = liquidacion_autorizada(empresa, admin, compra, total_sin_impuestos=Decimal('100.00'),
                                             total_iva=Decimal('0.00'), importe_total=Decimal('100.00'))
        with company_context(empresa):
            compras.al_autorizar_liquidacion(liquidacion)
        assert codigos(empresa, compra) == ['liquidacion_descuadrada'] and recargar(empresa, compra).datos_incompletos

    @pytest.mark.parametrize('linea, cambios, texto', [
        (dict(price='100.00', descuento='10.00'), {}, 'no admite descuentos'),
        (dict(price='50.00', codigo='8', tarifa='8.00'), {}, 'solo admite IVA'),
        (dict(price='50.00', codigo='6'), {}, 'solo admite IVA'),
        (dict(price='50.00'), {'total_ice': '5.00'}, 'ICE ni propina'),
        (dict(price='50.00'), {'iva_factura': '7.00'}, 'deja vacío el IVA'),
    ], ids=['descuento', 'diferenciado', 'no_objeto', 'ice', 'iva_factura'])
    def test_modo_liquidacion_solo_con_lo_que_la_liquidacion_lleva(self, empresa, admin, productora, linea, cambios, texto):
        with pytest.raises(compras.ErrorCompra, match=texto):
            crear(empresa, admin, modo_liquidacion(productora, **cambios), [ayuda.linea_gasto(**linea)])

    def test_lineas_de_la_liquidacion_avisan_la_tarifa_que_no_admite(self, empresa, admin, productora):
        """O1-T3: una compra «después» con IVA diferenciado no se liquida al 0 % sin aviso."""
        datos = {'provider': productora.pk, 'modo_comprobante': 'despues', 'date_joined': hoy().isoformat(), 'payment_type': 'efectivo'}
        compra = crear(empresa, admin, datos, [ayuda.linea_gasto(price='100.00', codigo='8', tarifa='8.00'),
                                              ayuda.linea_gasto('Otro', price='10.00', codigo='0')])
        with company_context(empresa):
            lineas = liquidaciones.lineas_de_compra(recargar(empresa, compra))
        assert '8.00 %' in lineas[0]['aviso'] and lineas[1]['aviso'] == ''
