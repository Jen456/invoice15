"""Retención sobre una compra (RetencionCrearView, integración con Compras). Datos ficticios; SRI falso.

- O1-F12: la compra sobre la que no se emite retención (compras.admite_retencion falso: nota de crédito del proveedor,
  04) se rechaza en GET y en POST con un mensaje claro, sin reservar número ni emitir nada.
- O1-F11: el primer return de iniciales() usa compras.datos_sustento_retencion y pasa sus advertencias al contexto
  (`avisos_sustento`), que la pantalla muestra como alertas con `data-advertencia="<código>"`.
- X-R1: «Completar datos» no pasa a 04 una compra sin tipo que ya tiene una retención vigente, y retenciones.crear() no
  guarda una retención sobre una 04 aunque la llamen sin pasar por la vista.
"""
from decimal import Decimal

import pytest
from django.contrib.messages import get_messages
from django.db import transaction
from django.utils import timezone

from core.comprobantes import retenciones as sv
from core.comprobantes.models import Retencion
from core.pos import compras
from core.pos.models import Purchase, Receipt
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, AuditLog
from tests import ayuda_compras as ayuda, helpers
from tests.test_retenciones import (codigos, compra, emitir, empresa, formulario, leer, numeracion, p12, sri,  # noqa: F401
                                    web)

pytestmark = pytest.mark.django_db
URL = '/comprobantes/retenciones/nueva/{}/'
AUTORIZACION = '1' * 37   # autorización de un comprobante anterior a la clave de acceso


@pytest.fixture
def usuario(empresa):  # noqa: F811
    return helpers.crear_usuario('compras.retenedora', empresa, ROLE_OWNER)


@pytest.fixture
def proveedor(empresa):  # noqa: F811
    return ayuda.crear_proveedor(empresa, tipo='04')


def nueva_compra(empresa, usuario, proveedor, lineas, **cambios):  # noqa: F811
    with company_context(empresa):
        return compras.crear_compra(empresa, usuario, ayuda.datos_compra(proveedor, autorizacion=AUTORIZACION, **cambios), lineas)


@pytest.fixture
def factura(empresa, usuario, proveedor):  # noqa: F811
    return nueva_compra(empresa, usuario, proveedor, [ayuda.linea_gasto(price='100.00')], secuencial='820')


@pytest.fixture
def nota(empresa, usuario, proveedor, factura):  # noqa: F811
    return nueva_compra(empresa, usuario, proveedor, [ayuda.linea_gasto(price='20.00')], secuencial='821',
                        tipo_comprobante='04', tipo_doc_modificado='01', num_doc_modificado='001002000000820',
                        aut_doc_modificado=AUTORIZACION, fecha_doc_modificado=factura.fecha_emision.isoformat(),
                        compra_modificada=factura.pk)


def mensajes(respuesta):
    return [str(m) for m in get_messages(respuesta.wsgi_request)]


def secuencia_07(empresa):  # noqa: F811
    return leer(empresa, lambda: list(Receipt.objects.filter(voucher_type='07').values_list('sequence', flat=True)))


class TestNotaDeCreditoDelProveedor:
    """O1-F12: /comprobantes/retenciones/nueva/<id de una 04>/ ya no se acepta."""

    def test_get_redirige_a_compras_con_el_motivo(self, web, empresa, nota, numeracion):  # noqa: F811
        assert not compras.admite_retencion(nota)
        respuesta = web.get(URL.format(nota.pk))
        assert respuesta.status_code == 302 and respuesta['Location'] == '/pos/purchase/'
        assert mensajes(respuesta) == [f'La compra #{nota.pk} es una nota de crédito del proveedor (04): sobre ella no se '
                                       'emite comprobante de retención. No se emitió nada.']

    def test_post_revisar_y_emitir_no_guardan_ni_reservan_numero(self, web, empresa, nota, codigos, numeracion,  # noqa: F811
                                                                  sri):  # noqa: F811
        antes = secuencia_07(empresa)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        lineas = [(codigos['bienes'], '', '')]
        revision = web.post(URL.format(nota.pk), {**formulario(lineas), 'action': 'calcular'})
        assert revision.status_code == 302 and revision['Location'] == '/pos/purchase/'
        assert 'no se emite comprobante de retención' in mensajes(revision)[0]
        respuesta = web.post(URL.format(nota.pk), {**formulario(lineas), 'action': 'emitir', 'huella': 'x' * 64})
        assert respuesta.status_code == 302 and respuesta['Location'] == '/pos/purchase/'
        assert 'No se emitió nada.' in mensajes(respuesta)[0]
        assert not leer(empresa, lambda: Retencion.objects.exists())
        assert secuencia_07(empresa) == antes and sri.recepciones == []

    def test_la_factura_que_modifica_si_admite_retencion(self, web, empresa, factura, nota, codigos, numeracion,  # noqa: F811
                                                         sri):  # noqa: F811
        assert web.get(URL.format(factura.pk)).status_code == 200
        sri.respuestas_autorizacion = ['AUTORIZADO']
        lineas = [(codigos['bienes'], '', '')]
        post = formulario(lineas, num_doc_sustento='001-002-000000820', aut_doc_sustento=AUTORIZACION)
        emitir(web, URL.format(factura.pk), post)
        ret = leer(empresa, lambda: Retencion.objects.get())
        assert ret.purchase_id == factura.pk and ret.status in ('authorized', 'authorized_and_sent_by_email')


class TestAvisosDelSustento:
    """O1-F11: iniciales() toma el documento sustento de compras.datos_sustento_retencion y el contexto trae sus avisos."""

    def test_factura_de_una_tarifa_precarga_sin_avisos(self, web, empresa, factura):  # noqa: F811
        respuesta = web.get(URL.format(factura.pk))
        assert respuesta.status_code == 200 and respuesta.context['avisos_sustento'] == []
        inicial = respuesta.context['form'].initial
        assert (inicial['cod_doc_sustento'], inicial['num_doc_sustento'], inicial['aut_doc_sustento']) == \
            ('01', '001002000000820', AUTORIZACION)
        assert inicial['tarifa_iva'] == '15.00' and inicial['base_iva'] == factura.base_gravada
        html = respuesta.content.decode()
        assert 'value="001002000000820"' in html and 'data-advertencia="sustento_' not in html

    def test_factura_con_varias_tarifas_avisa(self, web, empresa, usuario, proveedor):  # noqa: F811
        mixta = nueva_compra(empresa, usuario, proveedor, [ayuda.linea_gasto(price='100.00'),
                                                           ayuda.linea_gasto('Transporte', price='30.00', codigo='5')],
                             secuencial='822')
        respuesta = web.get(URL.format(mixta.pk))
        assert respuesta.status_code == 200
        assert [a['codigo'] for a in respuesta.context['avisos_sustento']] == ['sustento_varias_tarifas']
        assert not {'base_0', 'base_iva', 'tarifa_iva', 'valor_iva'} & set(respuesta.context['form'].initial)
        html = respuesta.content.decode()   # la pantalla lo muestra: sin él, las bases vacías no se explican
        assert ('<div class="alert alert-warning" role="alert" data-advertencia="sustento_varias_tarifas">La factura tiene '
                'varias tarifas o bases exentas o no objeto: el comprobante de retención actual admite una sola tarifa. '
                'Revisa las bases.</div>') in html
        assert respuesta.context['form'].initial['num_doc_sustento'] == '001002000000822'

    def test_compra_anterior_sin_tipo_como_antes(self, web, empresa, compra):  # noqa: F811
        compra = leer(empresa, lambda: Purchase.objects.get(pk=compra.pk))
        respuesta = web.get(URL.format(compra.pk))
        assert respuesta.status_code == 200 and respuesta.context['avisos_sustento'] == []
        assert respuesta.context['form'].initial == {'fecha_doc_sustento': compra.date_joined, 'base_iva': compra.subtotal}


class TestRetencionVigenteYNotaDeCredito:
    """X-R1: una compra sin tipo, de contado y solo con líneas de gasto («Completar después») admite retención; con la
    retención vigente, «Completar datos» no la convierte en nota de crédito del proveedor (04). Nada se anula ni se cambia."""

    @pytest.fixture
    def sin_tipo(self, empresa, usuario, proveedor):  # noqa: F811
        datos = {'provider': proveedor.pk, 'modo_comprobante': 'despues', 'date_joined': timezone.localdate().isoformat(),
                 'payment_type': 'efectivo'}
        with company_context(empresa):
            compra = compras.crear_compra(empresa, usuario, datos, [ayuda.linea_gasto(price='100.00')])
        assert compra.tipo_comprobante == '' and compras.admite_retencion(compra)
        return compra

    @pytest.fixture
    def modificada(self, empresa, usuario, proveedor):  # noqa: F811
        return nueva_compra(empresa, usuario, proveedor, [ayuda.linea_gasto(price='100.00')], secuencial='830')

    @staticmethod
    def retener(empresa, usuario, compra, codigos):  # noqa: F811
        datos = {'cod_doc_sustento': '01', 'num_doc_sustento': '001-002-000000831', 'aut_doc_sustento': AUTORIZACION,
                 'fecha_doc_sustento': timezone.localdate(), 'base_0': Decimal('0'), 'base_iva': Decimal('100.00'),
                 'tarifa_iva': '15.00', 'valor_iva': Decimal('15.00'), 'cod_sustento': '01', 'forma_pago': '20'}
        with company_context(empresa), transaction.atomic():
            return sv.crear(empresa, usuario, Purchase.objects.get(pk=compra.pk), datos, [(codigos['bienes'].pk, None, None)],
                            huella_revisada=sv.SIN_REVISION)

    @staticmethod
    def como_04(factura):
        return {'tipo_comprobante': '04', 'cod_sustento': '01', 'estab': '001', 'pto_emi': '002', 'secuencial': '831',
                'autorizacion': AUTORIZACION, 'fecha_emision': factura.fecha_emision.isoformat(), 'tipo_doc_modificado': '01',
                'num_doc_modificado': '001002000000830', 'aut_doc_modificado': AUTORIZACION,
                'fecha_doc_modificado': factura.fecha_emision.isoformat(), 'compra_modificada': factura.pk,
                'parte_relacionada': 'no', 'pago_loc_ext': '01'}

    def test_completar_datos_no_la_convierte_en_04(self, empresa, usuario, sin_tipo, modificada, codigos,  # noqa: F811
                                                   numeracion):  # noqa: F811
        ret = self.retener(empresa, usuario, sin_tipo, codigos)
        with company_context(empresa):
            assert sv.retencion_vigente(sin_tipo) == ret
        antes = AuditLog.objects.filter(action='purchase_complete').count()
        esperado = (f'Esta compra tiene la retención {ret.voucher_number_full} vigente y sobre una nota de crédito del '
                    'proveedor (04) no se emite comprobante de retención: no se puede registrar como 04. No se guardó ningún '
                    'cambio.')
        with company_context(empresa):
            compra = Purchase.objects.select_related('provider').get(pk=sin_tipo.pk)
            for intento in (compras.revisar_datos, lambda c, d: compras.completar_datos(c, usuario, d)):
                with pytest.raises(compras.ErrorCompra) as error:
                    intento(compra, self.como_04(modificada))
                assert (str(error.value), error.value.codigo) == (esperado, 'retencion_vigente')
            guardada = Purchase.objects.get(pk=sin_tipo.pk)
            assert (guardada.tipo_comprobante, guardada.compra_modificada_id) == ('', None)
            assert Retencion.objects.get(pk=ret.pk).status == ret.status and sv.retencion_vigente(guardada) == ret
        assert AuditLog.objects.filter(action='purchase_complete').count() == antes

    def test_con_la_retencion_vigente_si_se_completa_como_factura(self, empresa, usuario, sin_tipo, codigos,  # noqa: F811
                                                                  numeracion):  # noqa: F811
        self.retener(empresa, usuario, sin_tipo, codigos)
        datos = {'tipo_comprobante': '01', 'cod_sustento': '01', 'estab': '001', 'pto_emi': '002', 'secuencial': '831',
                 'autorizacion': AUTORIZACION, 'fecha_emision': timezone.localdate().isoformat()}
        with company_context(empresa):
            compras.completar_datos(Purchase.objects.select_related('provider').get(pk=sin_tipo.pk), usuario, datos)
            assert Purchase.objects.get(pk=sin_tipo.pk).tipo_comprobante == '01'

    def test_crear_rechaza_la_04_aunque_no_pase_por_la_vista(self, empresa, usuario, nota, codigos,  # noqa: F811
                                                             numeracion):  # noqa: F811
        antes = secuencia_07(empresa)
        with pytest.raises(sv.ErrorRetencion) as error:
            self.retener(empresa, usuario, nota, codigos)
        assert str(error.value) == (f'La compra #{nota.pk} es una nota de crédito del proveedor (04): sobre ella no se '
                                    'emite comprobante de retención. No se emitió nada.')
        assert not leer(empresa, lambda: Retencion.objects.exists()) and secuencia_07(empresa) == antes
