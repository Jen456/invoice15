"""Liquidación de compra (03, XML 1.1.0) desde Compras: cálculo y validaciones en el servidor, XML válido contra el XSD
oficial del SRI, numeración en «Otros comprobantes», emisión en dos fases, cupo, permisos, correo y la retención que la
toma como documento sustento."""
from decimal import Decimal
from pathlib import Path

import pytest
from django.core import mail
from django.core.management import call_command
from django.db import transaction
from lxml import etree

from core.comprobantes import liquidaciones as sl
from core.comprobantes.models import LiquidacionCompra, Retencion
from core.configuracion import servicios as cfg
from core.pos import emision
from core.pos.models import Category, Product, Provider, Purchase, PurchaseDetail
from core.suscripciones.models import SubscriptionPeriod
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_OWNER, ROLE_SELLER
from tests import helpers
from tests.test_retenciones import empresa, leer, p12, sri  # noqa: F401 (fixtures compartidos)

pytestmark = pytest.mark.django_db
XSD = Path(__file__).parent / 'xsd' / 'liquidacion' / 'LiquidacionCompra_V1.1.0.xsd'
XSD_RETENCION = Path(__file__).parent / 'xsd' / 'retencion' / 'ComprobanteRetencion_V2.0.0.xsd'
LISTA = '/comprobantes/liquidaciones/'
CEDULA = '0912345600'


def valido(xml, xsd):
    parser = etree.XMLParser(no_network=True, load_dtd=True, resolve_entities=True)
    esquema = etree.XMLSchema(etree.parse(str(xsd), parser))
    documento = etree.fromstring(xml.encode())
    return esquema.validate(documento), [str(e) for e in esquema.error_log], documento


@pytest.fixture
def numeracion(empresa):  # noqa: F811
    """Numeración de liquidaciones confirmada en «Otros comprobantes»: continúa desde la 7 de otro sistema."""
    with company_context(empresa):
        return cfg.configurar_otro_documento(empresa, '03', 'otro_sistema', '001-002-000000007', True)


def nueva_compra(empresa, identificacion=CEDULA, numero='501', lineas=(('CACAO-01', 'Cacao en grano', False, 2, '50.00'),
                                                                        ('FLETE-01', 'Transporte de la cosecha', True, 1, '20.00'))):  # noqa: F811
    with company_context(empresa):
        proveedor = Provider.objects.create(name=f"MARÍA D'AGRICULTORA {numero}", ruc=identificacion, mobile=f'09{numero:0>8}'[:10],
                                            email=f'productora{numero}@example.com', address='Recinto La Unión, Milagro')
        compra = Purchase.objects.create(number=numero, provider=proveedor, subtotal=Decimal('0'))
        categoria = Category.objects.get_or_create(name='Compras agrícolas')[0]
        for codigo, nombre, con_iva, cantidad, precio in lineas:
            producto = Product.objects.create(name=nombre, code=f'{codigo}-{numero}', category=categoria, price=Decimal(precio),
                                              pvp=Decimal(precio), stock=0, with_tax=con_iva, inventoried=False)
            PurchaseDetail.objects.create(purchase=compra, product=producto, cant=cantidad, price=Decimal(precio),
                                          subtotal=Decimal(precio) * cantidad)
        compra.calculate_invoice()
        return compra


@pytest.fixture
def compra(empresa):  # noqa: F811
    return nueva_compra(empresa)


@pytest.fixture
def web(client, empresa):  # noqa: F811
    helpers.iniciar_sesion(client, helpers.crear_usuario('dueno.liquidadora', empresa, ROLE_OWNER), empresa=empresa)
    return client


def formulario(compra, tarifas=None, **cambios):
    """POST del formulario: proveedor y pago + una línea por detalle de la compra con su tarifa."""
    with company_context(compra.company):
        detalles = [(d.pk, d.product.with_tax) for d in compra.purchasedetail_set.select_related('product').order_by('pk')]
    post = {'tipo_identificacion': '05', 'direccion': 'Recinto La Unión, Milagro', 'forma_pago': '01', 'concepto': 'Compra de cacao',
            'lineas-TOTAL_FORMS': str(len(detalles)), 'lineas-INITIAL_FORMS': str(len(detalles)),
            'lineas-MIN_NUM_FORMS': '0', 'lineas-MAX_NUM_FORMS': '1000'}
    for i, (pk, con_iva) in enumerate(detalles):
        tarifa = (tarifas or {}).get(i, '15.00' if con_iva else '0.00')
        post.update({f'lineas-{i}-detalle': pk, f'lineas-{i}-descripcion': '', f'lineas-{i}-tarifa': tarifa})
    post.update(cambios)
    return post


class TestCalculo:

    def test_tarifas_sugeridas_y_totales_por_tarifa(self, empresa, compra):  # noqa: F811
        with company_context(empresa):
            doc, detalle, totales = sl.calcular(compra, {'tipo_identificacion': '05', 'forma_pago': '01'}, {})
        assert doc['identificacion'] == CEDULA and doc['tipo_identificacion'] == '05'
        assert [(d['base'], d['tarifa'], d['iva']) for d in detalle] == [
            (Decimal('100.00'), Decimal('0.00'), Decimal('0.00')), (Decimal('20.00'), Decimal('15.00'), Decimal('3.00'))]
        assert totales['total_sin_impuestos'] == Decimal('120.00') and totales['total_iva'] == Decimal('3.00')
        assert totales['importe_total'] == Decimal('123.00')
        assert totales['por_tarifa'] == [(Decimal('15.00'), Decimal('20.00'), Decimal('3.00')), (Decimal('0.00'), Decimal('100.00'), Decimal('0.00'))]

    def test_el_emisor_elige_tarifa_y_descripcion(self, empresa, compra):  # noqa: F811
        with company_context(empresa):
            primera = compra.purchasedetail_set.order_by('pk').first()
            _, detalle, totales = sl.calcular(compra, {'tipo_identificacion': '05'}, {primera.pk: ('5.00', 'Cacao  fino de aroma')})
        assert detalle[0]['descripcion'] == 'Cacao fino de aroma' and detalle[0]['iva'] == Decimal('5.00')
        assert totales['importe_total'] == Decimal('128.00')

    @pytest.mark.parametrize('numero, tipo', [('0912345600', '05'), ('0912345600001', '04'), ('AB123456', '06')])
    def test_tipo_sugerido(self, numero, tipo):
        assert sl.tipo_sugerido(numero) == tipo

    def test_con_ruc_exige_confirmar_que_esta_suspendido(self, empresa):  # noqa: F811
        compra = nueva_compra(empresa, identificacion=CEDULA + '001', numero='502')
        with company_context(empresa):
            with pytest.raises(sl.ErrorLiquidacion, match='RUC está suspendido'):
                sl.calcular(compra, {'tipo_identificacion': '04'}, {})
            doc, _, _ = sl.calcular(compra, {'tipo_identificacion': '04', 'confirma_sin_ruc': True}, {})
        assert doc['identificacion'] == CEDULA + '001'

    @pytest.mark.parametrize('identificacion, tipo, mensaje', [
        ('0912345678', '05', 'cédula del proveedor no es válida'),
        ('0912345678001', '04', 'RUC del proveedor no es válido'),
        ('X1', '06', 'entre 3 y 20 caracteres'),
    ])
    def test_identificacion_invalida(self, empresa, identificacion, tipo, mensaje):  # noqa: F811
        compra = nueva_compra(empresa, identificacion=identificacion, numero='503')
        with company_context(empresa):
            with pytest.raises(sl.ErrorLiquidacion, match=mensaje):
                sl.calcular(compra, {'tipo_identificacion': tipo, 'confirma_sin_ruc': True}, {})

    def test_compra_sin_productos_y_tarifa_invalida(self, empresa, compra):  # noqa: F811
        vacia = nueva_compra(empresa, identificacion='PAS504', numero='504', lineas=())
        with company_context(empresa):
            with pytest.raises(sl.ErrorLiquidacion, match='no tiene productos'):
                sl.calcular(vacia, {'tipo_identificacion': '06'}, {})
            primera = compra.purchasedetail_set.order_by('pk').first()
            with pytest.raises(sl.ErrorLiquidacion, match='tarifa de IVA válida'):
                sl.calcular(compra, {'tipo_identificacion': '05'}, {primera.pk: ('12.00', '')})


class TestNumeracion:

    def test_sin_numeracion_explica_donde_configurarla(self, web, compra, sri):
        respuesta = web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario(compra), 'action': 'emitir'})
        assert 'Otros comprobantes' in respuesta.content.decode() and not leer(compra.company, lambda: LiquidacionCompra.objects.exists())

    def test_otros_comprobantes_muestra_la_liquidacion(self, web, empresa):  # noqa: F811
        html = web.get('/configuracion/facturacion/otros/').content.decode()
        assert 'Liquidación de compra' in html and 'name="tipo" value="03"' in html


class TestEmision:

    def test_revisar_no_guarda_y_emitir_autoriza(self, web, empresa, compra, numeracion, sri):  # noqa: F811
        html = web.get(f'{LISTA}nueva/{compra.pk}/').content.decode()
        assert 'Cacao en grano' in html and 'value="05" selected' in html
        revision = web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario(compra), 'action': 'calcular'}).content.decode()
        assert 'Revisa antes de emitir' in revision and '$123,00' in revision and not leer(empresa, lambda: LiquidacionCompra.objects.exists())
        sri.respuestas_autorizacion = ['AUTORIZADO']
        respuesta = web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario(compra), 'action': 'emitir'}, follow=True)
        liq = leer(empresa, lambda: LiquidacionCompra.objects.get())
        assert liq.voucher_number_full == '001-002-000000008' and liq.status == 'authorized_and_sent_by_email'
        assert liq.importe_total == Decimal('123.00') and 'autorizada por el SRI' in respuesta.content.decode()
        assert '<codDoc>03</codDoc>' in liq.xml_signed and '<campoAdicional nombre="RUC Proveedor">0941609729001</campoAdicional>' in liq.xml_signed
        assert "MARÍA D'AGRICULTORA" in liq.xml_signed and liq.xml_authorized and liq.pdf_authorized
        assert SubscriptionPeriod.objects.get(company=empresa, status='activa').documents_used == 1   # cuenta 1 del cupo
        assert mail.outbox[0].to == ['productora501@example.com'] and 'Total: USD 123.00' in mail.outbox[0].body

    def test_xml_firmado_valido_contra_el_xsd_oficial(self, empresa, compra, numeracion):  # noqa: F811
        empresa.retention_agent, empresa.special_taxpayer = 'SI', '12345'
        empresa.save()
        with company_context(empresa):
            primera = compra.purchasedetail_set.order_by('pk').first()
            with transaction.atomic():
                liq = sl.crear(empresa, helpers.crear_usuario('firmante.liq', empresa), compra,
                               {'tipo_identificacion': '05', 'forma_pago': '01', 'concepto': 'Compra de cacao'},
                               {primera.pk: ('5.00', '')})
                emision.preparar(liq)
            liq.refresh_from_db()
        ok, errores, documento = valido(liq.xml_signed, XSD)
        assert ok, errores
        assert documento.get('version') == '1.1.0' and documento.findtext('infoTributaria/agenteRetencion') == '1'
        assert documento.findtext('infoLiquidacionCompra/tipoIdentificacionProveedor') == '05'
        assert [(t.findtext('codigoPorcentaje'), t.findtext('baseImponible'), t.findtext('valor'))
                for t in documento.iter('totalImpuesto')] == [('5', '100.00', '5.00'), ('4', '20.00', '3.00')]
        assert documento.findtext('detalles/detalle/cantidad') == '2.000000' and documento.findtext('infoLiquidacionCompra/importeTotal') == '128.00'

    def test_una_liquidacion_por_compra(self, web, empresa, compra, numeracion, sri):  # noqa: F811
        web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario(compra), 'action': 'emitir'})   # queda en proceso
        html = web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario(compra), 'action': 'emitir'}).content.decode()
        assert 'ya tiene la liquidación' in html and '001-002-000000008' in html
        assert leer(empresa, lambda: LiquidacionCompra.objects.count()) == 1

    def test_en_proceso_no_se_borra_y_la_tarea_la_autoriza(self, web, empresa, compra, numeracion, sri):  # noqa: F811
        web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario(compra), 'action': 'emitir'})
        liq = leer(empresa, lambda: LiquidacionCompra.objects.get())
        assert liq.status == 'in_process'
        respuesta = web.post(LISTA, {'action': 'delete', 'id': liq.pk}, follow=True)
        assert 'no se puede eliminar' in respuesta.content.decode()
        assert leer(empresa, lambda: LiquidacionCompra.objects.filter(pk=liq.pk).exists())
        sri.respuestas_autorizacion = ['AUTORIZADO']
        call_command('consultar_sri')
        assert leer(empresa, lambda: LiquidacionCompra.objects.get(pk=liq.pk).status) in emision.AUTORIZADOS


class TestRetencionSobreLaLiquidacion:

    @pytest.fixture
    def autorizada(self, web, empresa, compra, numeracion, sri):  # noqa: F811
        sri.respuestas_autorizacion = ['AUTORIZADO']
        web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario(compra), 'action': 'emitir'})
        with company_context(empresa):
            cfg.configurar_otro_documento(empresa, '07', 'otro_sistema', '001-002-000000040', True)
            return LiquidacionCompra.objects.get()

    def test_la_retencion_toma_la_liquidacion_y_sugiere_100_iva_y_311(self, web, empresa, compra, autorizada, sri):  # noqa: F811
        html = web.get(f'/comprobantes/retenciones/nueva/{compra.pk}/').content.decode()
        assert 'liquidación de compra <strong>001-002-000000008</strong>' in html
        assert 'value="03" selected' in html and 'value="001-002-000000008"' in html and autorizada.access_code in html
        assert 'selected>Renta · 311 ·' in html and 'selected>IVA · 3 ·' in html

    def test_retencion_emitida_con_sustento_03_valida_contra_el_xsd(self, web, empresa, compra, autorizada, sri):  # noqa: F811
        from core.comprobantes.models import CodigoRetencion
        with company_context(empresa):
            r311 = CodigoRetencion.objects.get(impuesto='1', codigo='311')
            iva3 = CodigoRetencion.objects.get(impuesto='2', codigo='3')
        post = {'cod_doc_sustento': '03', 'num_doc_sustento': autorizada.voucher_number_full, 'aut_doc_sustento': autorizada.access_code,
                'fecha_doc_sustento': autorizada.emission_date.isoformat(), 'base_0': '100.00', 'base_iva': '20.00',
                'tarifa_iva': '15.00', 'valor_iva': '3.00', 'cod_sustento': '02', 'forma_pago': '01',
                'lineas-TOTAL_FORMS': '2', 'lineas-INITIAL_FORMS': '0', 'lineas-MIN_NUM_FORMS': '0', 'lineas-MAX_NUM_FORMS': '10',
                'lineas-0-codigo': r311.pk, 'lineas-1-codigo': iva3.pk, 'action': 'emitir'}
        sri.respuestas_autorizacion = ['AUTORIZADO']
        web.post(f'/comprobantes/retenciones/nueva/{compra.pk}/', post)
        ret = leer(empresa, lambda: Retencion.objects.get())
        assert ret.cod_doc_sustento == '03' and ret.total_retenido == Decimal('6.60')   # 120 × 3 % + 3.00 × 100 %
        ok, errores, documento = valido(ret.xml_signed, XSD_RETENCION)
        assert ok, errores
        assert documento.findtext('docsSustento/docSustento/codDocSustento') == '03'
        assert documento.findtext('docsSustento/docSustento/numDocSustento') == '001002000000008'

    def test_sustento_09_no_admite_liquidacion(self, empresa, compra):  # noqa: F811
        from datetime import timedelta

        from django.utils import timezone

        from core.comprobantes import retenciones as sv
        from core.comprobantes.models import CodigoRetencion
        with company_context(empresa):
            r311 = CodigoRetencion.objects.get(impuesto='1', codigo='311')
            with pytest.raises(sv.ErrorRetencion, match='sustento 09'):
                sv.calcular({'cod_doc_sustento': '03', 'cod_sustento': '09', 'num_doc_sustento': '001-002-000000008',
                             'aut_doc_sustento': '1' * 49, 'fecha_doc_sustento': timezone.localdate() - timedelta(days=1),
                             'base_iva': '20.00'}, [(r311.pk, None, None)])


class TestPermisos:

    def test_contador_consulta_pero_no_emite_y_vendedor_no_entra(self, client, empresa, compra):  # noqa: F811
        helpers.iniciar_sesion(client, helpers.crear_usuario('contador.liq', empresa, ROLE_ACCOUNTANT), empresa=empresa)
        assert client.get(LISTA).status_code == 200
        assert client.get(f'{LISTA}nueva/{compra.pk}/').status_code in (302, 403)
        client.logout()
        helpers.iniciar_sesion(client, helpers.crear_usuario('vendedor.liq', empresa, ROLE_SELLER), empresa=empresa)
        assert client.get(LISTA).status_code in (302, 403)

    def test_otra_empresa_no_ve_ni_usa_la_compra(self, client, compra):
        otra = helpers.crear_empresa('AJENA LIQ', plan='ilimitado')
        helpers.iniciar_sesion(client, helpers.crear_usuario('dueno.ajena.liq', otra, ROLE_OWNER), empresa=otra)
        assert client.get(f'{LISTA}nueva/{compra.pk}/').status_code == 404
