"""Notas de crédito y débito del proveedor (04/05) e inventario. Regla vigente: se registran con líneas de gasto y no mueven
stock (compras._preparar, la importación y «Completar datos» lo imponen). Aquí: la defensa dentro de la transacción de
crear_compra, el vínculo de un XML 04 con una compra antigua con productos, la captura completada como compra y el aviso
calculado del kardex para las notas sobre compras de un producto (el tratamiento de la devolución sigue pendiente)."""
from datetime import timedelta

import json

import pytest
from django.utils import timezone

from core.adjuntos.models import Captura
from core.contabilidad import kardex as kx
from core.importacion import servicios as sv
from core.importacion.models import DocumentoImportado
from core.pos import compras
from core.pos.models import Product, Purchase
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER
from tests import ayuda_compras as ayuda, fabricas_recibidos as r, helpers
from tests.test_importacion_compras import archivos_temporales, crear, importar  # noqa: F401

pytestmark = pytest.mark.django_db
HOY = timezone.localdate


@pytest.fixture
def empresa():
    return helpers.crear_empresa('RECEPTORA DE NOTAS', ruc=r.RUC_RECEPTOR)


@pytest.fixture
def dueno(empresa):
    return helpers.crear_usuario('dueno.notas.proveedor', empresa, ROLE_OWNER)


@pytest.fixture
def proveedor(empresa):
    return ayuda.crear_proveedor(empresa, tipo='04', ruc=r.RUC_EMISOR, nombre='PROVEEDOR FICTICIO S.A.')


def stock(empresa, producto):
    with company_context(empresa):
        return Product.objects.get(pk=producto.pk).stock


def datos_nota(proveedor, factura, secuencial):
    """Cabecera de una nota de crédito del proveedor sobre `factura` (como tests/test_compras_completas.py)."""
    return ayuda.datos_compra(proveedor, tipo_comprobante='04', secuencial=str(secuencial), tipo_doc_modificado='01',
                              num_doc_modificado='001-002-000000500', aut_doc_modificado='1234567890',
                              fecha_doc_modificado=factura.fecha_emision.isoformat(), compra_modificada=factura.pk)


def test_nota_con_productos_se_rechaza_sin_efectos(empresa, dueno, proveedor):
    producto = ayuda.crear_producto(empresa, codigo='NC-1', stock=10)
    with company_context(empresa):
        factura = compras.crear_compra(empresa, dueno, ayuda.datos_compra(proveedor, secuencial='80'), [ayuda.linea_gasto()])
        with pytest.raises(compras.ErrorCompra, match='líneas de gasto'):
            compras.crear_compra(empresa, dueno, datos_nota(proveedor, factura, 81), [ayuda.linea_producto(producto, cant=3)])
        assert Purchase.objects.filter(tipo_comprobante='04').count() == 0
    assert stock(empresa, producto) == 10


def test_defensa_dentro_de_la_transaccion(empresa, dueno, proveedor, monkeypatch):
    """Si una ruta futura saltara la regla de _preparar, crear_compra igual deshace todo antes de tocar el stock."""
    producto = ayuda.crear_producto(empresa, codigo='NC-2', stock=10)
    original = compras._preparar

    def como_nota(*args, **kwargs):
        plan = original(*args, **kwargs)
        plan.campos['tipo_comprobante'] = '04'
        return plan
    monkeypatch.setattr(compras, '_preparar', como_nota)
    with company_context(empresa):
        with pytest.raises(compras.ErrorCompra, match='no mueven stock'):
            compras.crear_compra(empresa, dueno, ayuda.datos_compra(proveedor, secuencial='82'), [ayuda.linea_producto(producto, cant=4)])
        assert not Purchase.objects.exists()
    assert stock(empresa, producto) == 10


def test_xml_de_nota_no_se_vincula_con_una_compra_antigua_con_productos(empresa, dueno, proveedor):
    producto = ayuda.crear_producto(empresa, codigo='NC-3', stock=0)
    antigua = ayuda.compra_antigua(empresa, proveedor, '20.00', producto=producto, cantidad=2)
    nota = importar(empresa, dueno, r.nota_credito())
    with company_context(empresa):
        with pytest.raises(sv.ErrorImportacion, match='tiene productos y movió el stock'):
            sv.revisar(DocumentoImportado.objects.get(pk=nota.pk), dueno, 'vincular_compra', {'id': antigua.pk})
        documento = DocumentoImportado.objects.get(pk=nota.pk)
        assert documento.compra_id is None and documento.estado_revision == 'pendiente'


def test_nota_importada_no_mueve_stock_y_el_kardex_avisa(empresa, dueno, proveedor):
    producto = ayuda.crear_producto(empresa, codigo='NC-4', stock=0)
    factura_xml = importar(empresa, dueno, r.factura())
    factura = crear(empresa, factura_xml, dueno, payment_type='credito', end_credit=(HOY() + timedelta(days=30)).isoformat(),
                    lineas=[{'indice': 0, 'modo': 'producto', 'product': producto.pk}])
    antes = stock(empresa, producto)
    nota = crear(empresa, importar(empresa, dueno, r.nota_credito()), dueno)
    with company_context(empresa):
        nota.refresh_from_db()
        assert (nota.tipo_comprobante, nota.compra_modificada_id) == ('04', factura.pk)
        assert not nota.purchasedetail_set.filter(product__isnull=False).exists()   # líneas de gasto
        k = kx.kardex(Product.objects.get(pk=producto.pk), HOY() - timedelta(days=40), HOY())
    assert stock(empresa, producto) == antes and k['diferencia_stock'] == 0
    aviso = next(a for a in k['advertencias'] if a['codigo'] == 'nc_proveedor_por_revisar')
    assert [d['id'] for d in aviso['documentos']] == [nota.pk] and 'pendiente de decisión' in aviso['texto']


def test_captura_completada_como_nota_con_producto_queda_pendiente(client, empresa, dueno, proveedor):
    producto = ayuda.crear_producto(empresa, codigo='NC-5', stock=5)
    helpers.iniciar_sesion(client, dueno, empresa=empresa)
    guardada = client.post('/adjuntos/api/capturas/', {'clave': 'captura-nota-prov-1', 'nota': 'Nota de crédito del proveedor'})
    captura_id = guardada.json()['captura']['id']
    with company_context(empresa):
        factura = compras.crear_compra(empresa, dueno, ayuda.datos_compra(proveedor, secuencial='90'), [ayuda.linea_gasto()])
    datos = {**datos_nota(proveedor, factura, 91), 'action': 'add', 'captura': captura_id,
             'lineas': json.dumps([ayuda.linea_producto(producto, cant=2)])}
    respuesta = client.post('/pos/purchase/add/', datos)
    assert 'líneas de gasto' in respuesta.json()['error']
    with company_context(empresa):
        assert Captura.objects.get(pk=captura_id).estado == 'pendiente'
        assert not Purchase.objects.filter(tipo_comprobante='04').exists()
    assert stock(empresa, producto) == 5
