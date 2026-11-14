"""Reproductores de revisión sobre 10d75f0. Solo datos ficticios, SQLite temporal y sin emisión/SRI.

Expresan el comportamiento esperado: en esta candidata fallan y señalan lo pendiente.
"""
from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from core.pos.models import Product
from core.tenancy.context import company_context
from tests import test_proformas_borrador as bf
from tests.test_proformas_borrador import aceptada, productos, empresa, dueno, comprador, web, p12  # noqa: F401

pytestmark = pytest.mark.django_db


def test_codigo_anterior_puede_importar_con_la_base_expandida(empresa, dueno):
    """Modelo de producción (0007) escribiendo sobre el esquema nuevo (0009), necesario durante un cambio sin pausa."""
    state = MigrationLoader(connection).project_state([('importacion', '0007_lotes_de_claves')])
    OldDocumento = state.apps.get_model('importacion', 'DocumentoImportado')
    with company_context(empresa), transaction.atomic():
        doc = OldDocumento.objects.create(
            company_id=empresa.pk, importado_por_id=dueno.pk, ambiente=1,
            clave_acceso='1' * 49, origen='xml', cod_doc='01', estab='001', pto_emi='001',
            secuencial='000000001', numero='001-001-000000001', emisor_razon_social='EMISOR FICTICIO',
        )
    assert doc.pk


@pytest.mark.parametrize('stock_disponible', [0, 1])
def test_convertir_conserva_cantidad_cotizada_aunque_falte_stock(empresa, aceptada, productos, web, stock_disponible):
    """La proforma tiene 3 unidades de P15. Convertir debe conservar las 3 y advertir/bloquear emisión, no recortarlas."""
    product = productos['4']
    with company_context(empresa):
        Product.objects.filter(pk=product.pk).update(stock=stock_disponible, inventoried=True)
    respuesta = bf.convertir(web, aceptada)
    assert respuesta.status_code == 200, respuesta.content
    draft = bf.borrador(empresa, aceptada)
    linea = next((l for l in draft.lineas if l['product'] == product.pk), None)
    assert linea is not None, 'La conversión omitió la línea sin existencias'
    assert linea['cant'] == 3, f"Se cotizaron 3 unidades, pero el borrador guardó {linea['cant']}"


def test_guardar_borrador_conserva_el_vencimiento_del_credito(empresa, aceptada, comprador, web):
    conversion = bf.convertir(web, aceptada).json()
    datos = bf.precarga(web, conversion['url'])
    vencimiento = (timezone.localdate() + timedelta(days=90)).isoformat()
    resultado = bf.guardar(web, datos, comprador, payment_type='credito', medio_cobro='transferencia',
                          payment_method='20', time_limit='90', end_credit=vencimiento)
    assert not resultado.get('error'), resultado
    reabierta = web.get(conversion['url'])
    assert reabierta.status_code == 200
    valor_formulario = reabierta.context['form']['end_credit'].value()
    valor_precarga = reabierta.context['proforma_precarga'].get('end_credit')
    assert vencimiento in (str(valor_formulario), valor_precarga), (
        f'Guardar respondió éxito pero se perdió el vencimiento {vencimiento}; '
        f'formulario={valor_formulario!r}, precarga={valor_precarga!r}'
    )
