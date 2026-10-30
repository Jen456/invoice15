"""Nota de crédito del proveedor (compra tipo 04) en «Resultados» y en el tablero: las compras se suman con
compras.subtotal_con_signo, así que la 04 resta; una compra anterior sin tipo suma como antes. Datos ficticios."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db.models import Sum
from django.utils import timezone

from core.pos import compras
from core.pos.models import Purchase
from core.tenancy.context import company_context
from tests import ayuda_compras as ayuda, helpers

pytestmark = pytest.mark.django_db


@pytest.fixture
def compras_de_hoy(empresa, admin):
    """Anterior sin tipo de $30, factura (01) de $100 y su nota de crédito (04) de $20, todas registradas hoy."""
    proveedor = ayuda.crear_proveedor(empresa)
    anterior = ayuda.compra_antigua(empresa, proveedor, '30.00', fecha=timezone.localdate())
    with company_context(empresa):
        factura = compras.crear_compra(empresa, admin, ayuda.datos_compra(proveedor, secuencial='710'),
                                       [ayuda.linea_gasto(price='100.00', codigo='0')])
        nota = compras.crear_compra(empresa, admin, ayuda.datos_compra(
            proveedor, secuencial='711', tipo_comprobante='04', tipo_doc_modificado='01',
            num_doc_modificado='001002000000710', aut_doc_modificado='1234567890',
            fecha_doc_modificado=factura.fecha_emision.isoformat(), compra_modificada=factura.pk),
            [ayuda.linea_gasto(price='20.00', codigo='0')])
        assert (anterior.tipo_comprobante, factura.tipo_comprobante, nota.tipo_comprobante) == ('', '01', '04')
        assert Purchase.objects.aggregate(s=Sum('subtotal'))['s'] == Decimal('150.00')   # sin signo: la 04 sumaba
    return anterior, factura, nota


def resultados(client, **datos):
    respuesta = client.post('/reports/results/', {'action': 'search_report', 'start_date': '', 'end_date': '', **datos})
    return {fila['name']: fila['y'] for fila in respuesta.json()}


def compras_del_tablero(client):
    series = {serie['name']: serie['data'] for serie in client.post('/dashboard/', {'action': 'get_graph_purchase_vs_sale'}).json()}
    return series['Compras'][timezone.localdate().month - 1]


class TestResultados:

    def test_la_nota_de_credito_del_proveedor_resta(self, client, empresa, admin, compras_de_hoy):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        assert resultados(client)['Compras'] == 110.0                       # 30 + 100 − 20
        hoy = timezone.localdate().isoformat()
        assert resultados(client, start_date=hoy, end_date=hoy, alcance='todos')['Compras'] == 110.0

    def test_las_compras_sin_tipo_no_cambian(self, client, empresa, admin):
        proveedor = ayuda.crear_proveedor(empresa)
        ayuda.compra_antigua(empresa, proveedor, '30.00', fecha=timezone.localdate())
        ayuda.compra_antigua(empresa, proveedor, '12.40', fecha=timezone.localdate())
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        assert resultados(client)['Compras'] == 42.4

    def test_solo_la_nota_de_credito_queda_negativa(self, client, empresa, admin, compras_de_hoy):
        nota = compras_de_hoy[2]
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        dia = nota.date_joined.isoformat()
        with company_context(empresa):
            Purchase.objects.exclude(pk=nota.pk).update(date_joined=nota.date_joined - timedelta(days=400))
        assert resultados(client, start_date=dia, end_date=dia)['Compras'] == -20.0


class TestTablero:

    def test_la_nota_de_credito_del_proveedor_resta(self, client, empresa, admin, compras_de_hoy):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        assert compras_del_tablero(client) == 110.0

    def test_las_compras_sin_tipo_no_cambian(self, client, empresa, admin):
        proveedor = ayuda.crear_proveedor(empresa)
        ayuda.compra_antigua(empresa, proveedor, '30.00', fecha=timezone.localdate())
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        assert compras_del_tablero(client) == 30.0
