"""Punta a punta del 07 importado, sin dobles (integración Compras ↔ Ventas). Datos ficticios.

Compras importa un XML 07 v2.0.0 autorizado (crear_lote) que retiene sobre facturas de la empresa y lo lee
(recibidos.retencion_recibida_de dentro de registrar_en_retenciones_recibidas, con la indirección _servicio_registro
real); Ventas lo registra (retenciones_recibidas.registrar_desde_importacion): una RetencionRecibida por sustento, el
abono de la cuenta por cobrar y el documento incorporado. Repetir no duplica; anular la última retención desmarca el
documento y la CxC vuelve a su saldo. Dos sustentos de facturas distintas registran ambos; dos de la misma factura se
rechazan (sustento_repetido) sin registrar nada. Corre igual en SQLite y en PostgreSQL (sin transaction=True; las
lecturas van dentro de company_context por la seguridad por filas).
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.comprobantes import retenciones_recibidas as rr
from core.comprobantes.models import RetencionRecibida
from core.importacion import recibidos, servicios as sv
from core.importacion.models import DocumentoImportado, EventoImportacion
from core.pos.models import Client, CtasCollect, PaymentsCtaCollect
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_OWNER, AuditLog
from tests import fabricas_recibidos as r, helpers
from tests.ayudas_ventas import cxc_de, factura_autorizada
from tests.test_importacion_recibidos import entorno  # noqa: F401 (MEDIA_ROOT temporal y SRI simulado)

pytestmark = pytest.mark.django_db
HOY = timezone.localdate()
FECHA_FACTURAS = HOY - timedelta(days=3)
FECHA_07 = HOY - timedelta(days=1)
RENTA = ('1', '312', '20.00', '2.00', '0.40')     # sobre el subtotal de una factura de $23 (2 × $10 + IVA)
IVA = ('2', '1', '3.00', '30.00', '0.90')         # 30 % de su IVA
MOTIVO = 'El cliente anuló la retención en el SRI'


def leer(empresa, consulta):
    with company_context(empresa):
        return consulta()


@pytest.fixture
def empresa(db, entorno):  # noqa: F811
    return helpers.crear_empresa('SUJETO RETENIDO', ruc=r.RUC_RECEPTOR, environment_type=2)


@pytest.fixture
def dueno(empresa):
    return helpers.crear_usuario('dueno.integracion07', empresa, ROLE_OWNER)


@pytest.fixture
def agente(empresa):
    """Cliente con RUC, agente de retención: emite el 07 a la empresa."""
    cliente = helpers.crear_cliente('cliente.agente07', empresa, r.RUC_AGENTE, '0990000007')
    leer(empresa, lambda: Client.objects.filter(pk=cliente.pk).update(identification_type='04'))
    cliente.identification_type = '04'
    return cliente


@pytest.fixture
def facturas(empresa, agente, dueno):
    """Dos facturas a crédito de PRODUCCIÓN, autorizadas, de $23 cada una."""
    producto = helpers.crear_producto(empresa, 'P07', pvp='10.00')
    return [factura_autorizada(empresa, agente, dueno, producto, credito=True, fecha=FECHA_FACTURAS) for _ in range(2)]


def sustento(venta, retenciones=(RENTA, IVA)):
    return r.sustento(numero=venta.voucher_number_full.replace('-', ''), fecha=venta.emission_date,
                      retenciones=retenciones, total_sin='20.00', importe='23.00')


def importar_07(empresa, usuario, sustentos, secuencial='000000010'):
    """Importa el XML autorizado por Compras (crear_lote) y lo deja verificado en el SRI, como tras «Verificar»."""
    xml = r.retencion_v2(sustentos=sustentos, receptor_id=empresa.ruc, fecha=FECHA_07, secuencial=secuencial)
    with company_context(empresa):
        documento = sv.crear_lote(empresa, usuario, [('07.xml', r.autorizacion(
            xml, fecha=f'{FECHA_07.isoformat()}T10:15:22-05:00').encode())]).documentos.get()
        assert (documento.cod_doc, documento.clasificacion, documento.estado_procesamiento, documento.estado_revision) == (
            '07', 'recibido', 'procesado', 'pendiente')
        DocumentoImportado.objects.filter(pk=documento.pk).update(estado_verificacion='verificada_sri')
        documento.refresh_from_db()
        return documento


def registrar(empresa, usuario, documento):
    with company_context(empresa):
        return recibidos.registrar_en_retenciones_recibidas(empresa, usuario, DocumentoImportado.objects.get(pk=documento.pk))


def documento_de(empresa, documento):
    return leer(empresa, lambda: DocumentoImportado.objects.get(pk=documento.pk))


def saldo(empresa, venta):
    return leer(empresa, lambda: CtasCollect.objects.get(pk=cxc_de(venta).pk).saldo)


def conteos(empresa):
    return leer(empresa, lambda: (RetencionRecibida.objects.count(), PaymentsCtaCollect.objects.filter(tipo='retencion').count(),
                                  AuditLog.objects.filter(action='retencion_recibida_registro').count()))


def eventos(empresa, documento):
    return leer(empresa, lambda: list(EventoImportacion.objects.filter(documento_id=documento.pk, tipo__in=(
        'incorporado', 'desincorporado')).order_by('pk').values_list('tipo', flat=True)))


def test_el_registro_usa_el_servicio_de_ventas():
    assert recibidos._servicio_registro() == (rr.registrar_desde_importacion, rr.ErrorRetencionRecibida)


def test_un_sustento_registra_abona_e_incorpora_y_anular_lo_revierte(empresa, dueno, facturas):
    venta = facturas[0]
    documento = importar_07(empresa, dueno, [sustento(venta)])
    leida = leer(empresa, lambda: recibidos.retencion_recibida_de(documento))
    assert (leida.agente_ruc, leida.numero, leida.total_retenido) == (r.RUC_AGENTE, '001-001-000000010', Decimal('1.30'))

    [ret] = registrar(empresa, dueno, documento)
    assert (ret.venta_id, ret.origen, ret.documento_importado_id, ret.estado, ret.cxc_estado) == (
        venta.pk, 'importado', documento.pk, 'registrada', 'aplicada')
    assert (ret.numero, ret.clave_acceso, ret.total_retenido, ret.verificacion) == (
        '001-001-000000010', documento.clave_acceso, Decimal('1.30'), 'verificada_sri')
    assert saldo(empresa, venta) == Decimal('21.70') and saldo(empresa, facturas[1]) == Decimal('23.00')
    abono = leer(empresa, lambda: PaymentsCtaCollect.objects.get(tipo='retencion'))
    assert (abono.pk, abono.valor) == (ret.abono_id, Decimal('1.30'))
    assert documento_de(empresa, documento).estado_revision == 'vinculado' and eventos(empresa, documento) == ['incorporado']
    assert AuditLog.objects.get(action='retencion_recibida_registro').detail['documento'] == documento.pk

    # Repetir no duplica: Compras lo bloquea (ya registrada) y el servicio de Ventas devuelve las mismas filas
    antes = conteos(empresa)
    with pytest.raises(sv.ErrorImportacion) as error:
        registrar(empresa, dueno, documento)
    assert error.value.codigo == 'ya_registrada'
    with company_context(empresa):
        otra_vez = rr.registrar_desde_importacion(empresa, dueno, DocumentoImportado.objects.get(pk=documento.pk), leida)
    assert [x.pk for x in otra_vez] == [ret.pk]
    assert conteos(empresa) == antes == (1, 1, 1) and saldo(empresa, venta) == Decimal('21.70')
    assert eventos(empresa, documento) == ['incorporado']

    # Anular la última: el documento vuelve a pendiente y la CxC a su saldo
    with company_context(empresa):
        anulada = rr.anular(empresa, dueno, RetencionRecibida.objects.get(pk=ret.pk), MOTIVO)
    assert (anulada.estado, anulada.cxc_estado) == ('anulada', 'revertida')
    assert saldo(empresa, venta) == Decimal('23.00')
    assert documento_de(empresa, documento).estado_revision == 'pendiente'
    assert eventos(empresa, documento) == ['incorporado', 'desincorporado']
    assert AuditLog.objects.get(action='retencion_recibida_anulacion').detail['documento_desmarcado'] is True


def test_dos_sustentos_de_facturas_distintas_registran_ambos(empresa, dueno, facturas):
    documento = importar_07(empresa, dueno, [sustento(facturas[0]), sustento(facturas[1], retenciones=(RENTA,))],
                            secuencial='000000011')
    primera, segunda = registrar(empresa, dueno, documento)
    assert [primera.venta_id, segunda.venta_id] == [v.pk for v in facturas]
    assert (primera.total_retenido, segunda.total_retenido) == (Decimal('1.30'), Decimal('0.40'))
    assert [saldo(empresa, v) for v in facturas] == [Decimal('21.70'), Decimal('22.60')]
    assert documento_de(empresa, documento).estado_revision == 'vinculado' and eventos(empresa, documento) == ['incorporado']
    assert conteos(empresa) == (2, 2, 2)

    with company_context(empresa):
        rr.anular(empresa, dueno, RetencionRecibida.objects.get(pk=primera.pk), MOTIVO)
    assert documento_de(empresa, documento).estado_revision == 'vinculado'      # le queda una registrada
    with company_context(empresa):
        rr.anular(empresa, dueno, RetencionRecibida.objects.get(pk=segunda.pk), MOTIVO)
    assert documento_de(empresa, documento).estado_revision == 'pendiente'
    assert [saldo(empresa, v) for v in facturas] == [Decimal('23.00')] * 2


def test_dos_sustentos_de_la_misma_factura_se_rechazan(empresa, dueno, facturas):
    venta = facturas[0]
    documento = importar_07(empresa, dueno, [sustento(venta, retenciones=(RENTA,)), sustento(venta, retenciones=(IVA,))],
                            secuencial='000000012')
    with pytest.raises(sv.ErrorImportacion) as error:
        registrar(empresa, dueno, documento)
    assert error.value.codigo == 'sustento_repetido'
    assert str(error.value) == (f'Sustento {venta.voucher_number_full}: La factura {venta.voucher_number_full} aparece en '
                                'varios sustentos de esta retención: regístrala a mano con todas sus líneas.')
    assert conteos(empresa) == (0, 0, 0) and saldo(empresa, venta) == Decimal('23.00')
    assert documento_de(empresa, documento).estado_revision == 'pendiente' and eventos(empresa, documento) == []
