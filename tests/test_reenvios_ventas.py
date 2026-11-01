"""Reenvíos inconsistentes de la revisión (DECISION-ENTREGA-COMERCIAL-2026-10-31.md, entrega 1), lado ventas: una nota de
crédito o una guía de remisión devuelta no se reenvía si otra vigente ya acreditó o trasladó esas líneas (la devuelta no
cuenta como vigente, así que se pudo emitir otra), ni si su factura se anuló en el SRI. Las que siguen siendo coherentes
sí se reenvían. Nada se anula ni se cambia; SRI simulado y datos ficticios."""
import pytest
from django.db import transaction
from django.utils import timezone

from core.comprobantes import guias as sg
from core.comprobantes.models import GuiaRemision
from core.pos import emision
from core.pos.models import CreditNote, Sale
from core.tenancy.context import company_context
from tests.ayudas_ventas import nota_credito_autorizada
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, producto, sri, vender, venta_de, web  # noqa: F401
from tests.test_guias import datos as datos_guia, detalle_de, numeracion as numeracion_guia  # noqa: F401

pytestmark = pytest.mark.django_db
DEVUELTA = ('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])


@pytest.fixture
def factura(web, empresa, comprador, producto, sri):  # noqa: F811
    sri.respuestas_autorizacion = ['AUTORIZADO']
    vender(web, comprador, producto, cantidad=2)
    return venta_de(empresa, 271)


def nota_devuelta(factura, sri):  # noqa: F811
    sri.respuestas_recepcion = [DEVUELTA]
    nota = nota_credito_autorizada(factura, None, sri=sri, autorizar=False)   # todas las líneas (2 unidades)
    assert nota.status == 'returned'
    return nota


def reenviar(empresa, modelo, pk, sri):  # noqa: F811
    enviados = len(sri.recepciones)
    sri.respuestas_autorizacion = ['AUTORIZADO']
    with company_context(empresa):
        resultado = emision.emitir(modelo.objects.get(pk=pk))
    return resultado, len(sri.recepciones) - enviados


class TestNotaDeCredito:

    def test_devuelta_no_se_reenvia_si_otra_ya_acredito_las_lineas(self, empresa, factura, sri):  # noqa: F811
        primera = nota_devuelta(factura, sri)
        segunda = nota_credito_autorizada(factura, None, sri=sri)   # la devuelta no cuenta: se puede emitir otra por todo
        assert segunda.status in emision.AUTORIZADOS
        resultado, envios = reenviar(empresa, CreditNote, primera.pk, sri)
        assert (resultado['resp'], resultado['estado'], envios) == (False, 'returned', 0)
        assert 'Otra nota de crédito vigente ya acreditó' in resultado['error'] and 'la acreditaría dos veces' in resultado['error']
        assert resultado['error'].endswith('No se anuló ni se cambió nada.')
        assert leer(empresa, lambda: CreditNote.objects.get(pk=primera.pk).status) == 'returned'

    def test_devuelta_no_se_reenvia_si_la_factura_se_anulo_en_el_sri(self, empresa, factura, sri):  # noqa: F811
        nota = nota_devuelta(factura, sri)
        with company_context(empresa):
            Sale.objects.filter(pk=factura.pk).update(anulado_sri_fecha=timezone.localdate())
        resultado, envios = reenviar(empresa, CreditNote, nota.pk, sri)
        assert resultado['resp'] is False and envios == 0
        assert f'La factura {factura.voucher_number_full} está anulada en el SRI' in resultado['error']

    def test_control_devuelta_sin_otra_vigente_si_se_reenvia(self, empresa, factura, sri):  # noqa: F811
        nota = nota_devuelta(factura, sri)
        resultado, envios = reenviar(empresa, CreditNote, nota.pk, sri)
        assert resultado['resp'] is True and envios == 1
        assert leer(empresa, lambda: CreditNote.objects.get(pk=nota.pk).status) in emision.AUTORIZADOS


class TestGuiaDeRemision:

    def guia(self, empresa, dueno, factura, cantidad, sri, autorizar):  # noqa: F811
        if not autorizar:
            sri.respuestas_recepcion = [DEVUELTA]
        else:
            sri.respuestas_autorizacion = ['AUTORIZADO']
        with company_context(empresa):
            with transaction.atomic():
                guia = sg.crear(empresa, dueno, Sale.objects.get(pk=factura.pk), datos_guia(), {detalle_de(factura).pk: cantidad})
                emision.preparar(guia)
            emision.emitir(guia)
            guia.refresh_from_db()
        return guia

    def test_devuelta_no_se_reenvia_si_otra_ya_traslado_las_cantidades(self, empresa, dueno, factura, numeracion_guia, sri):  # noqa: F811
        primera = self.guia(empresa, dueno, factura, '2', sri, autorizar=False)
        assert primera.status == 'returned'
        segunda = self.guia(empresa, dueno, factura, '2', sri, autorizar=True)   # la devuelta no cuenta: se traslada todo con otra
        assert segunda.status in emision.AUTORIZADOS
        resultado, envios = reenviar(empresa, GuiaRemision, primera.pk, sri)
        assert (resultado['resp'], envios) == (False, 0)
        assert 'Otra guía vigente ya trasladó' in resultado['error'] and 'ampararía dos veces' in resultado['error']
        assert leer(empresa, lambda: GuiaRemision.objects.get(pk=primera.pk).status) == 'returned'

    def test_devuelta_parcial_si_se_reenvia_si_queda_pendiente(self, empresa, dueno, factura, numeracion_guia, sri):  # noqa: F811
        primera = self.guia(empresa, dueno, factura, '1', sri, autorizar=False)
        self.guia(empresa, dueno, factura, '1', sri, autorizar=True)   # queda 1 pendiente: la devuelta por 1 sí cabe
        resultado, envios = reenviar(empresa, GuiaRemision, primera.pk, sri)
        assert resultado['resp'] is True and envios == 1
