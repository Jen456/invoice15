"""Marca «Anulado en el SRI» de los seis comprobantes emitidos (Etapa 2, O2), servicio core/pos/anulados.py: requisitos
comunes, plazo del día 7 (confirmación obligatoria), señal anulado_en_sri dentro de la transacción, auditoría serializable
y los efectos e impedimentos de cada tipo. Sin SRI, sin correo y sin cupo. Las pantallas (permisos, plan, confirmación
del número) se prueban con su vista en el paso siguiente."""
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from core.comprobantes import guias as sg
from core.comprobantes import liquidaciones as sl
from core.comprobantes import notas_debito as snd
from core.comprobantes import retenciones as sv
from core.comprobantes import retenciones_recibidas as rr
from core.comprobantes.models import CodigoRetencion, GuiaRemision, LiquidacionCompra, NotaDebito, Retencion
from core.configuracion import servicios as cfg
from core.pos import anulados, cxc, notas_credito
from core.pos.clientes import consumidor_final
from core.pos.models import (Category, CreditNote, CtasCollect, PaymentsCtaCollect, Product, Provider, Purchase,
                             PurchaseDetail, Receipt, Sale, SaleDetail)
from core.pos.senales_comprobantes import anulado_en_sri
from core.pos.utilities.sri import SRI
from core.suscripciones.models import SubscriptionPeriod
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog
from tests.ayudas_ventas import (cxc_de, factura_autorizada, nota_credito_autorizada, nota_debito_autorizada,
                                 retencion_datos)
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, producto, sri  # noqa: F401

pytestmark = pytest.mark.django_db
HOY = timezone.localdate()
EMITIDA = HOY - timedelta(days=3)
MOTIVO = 'Anulada en SRI en línea: error en el valor'
SLUGS = ('factura', 'nota-credito', 'retencion', 'liquidacion', 'nota-debito', 'guia')


@pytest.fixture
def senales():
    recibidas = []

    def receptor(sender, instance, usuario, fecha, **kwargs):
        recibidas.append((sender, instance.pk, usuario, fecha, instance.anulado_sri_fecha))
    anulado_en_sri.connect(receptor, weak=False, dispatch_uid='prueba_o2_anulado')
    yield recibidas
    anulado_en_sri.disconnect(dispatch_uid='prueba_o2_anulado')


def marcar(empresa, usuario, slug, doc, fecha=None, motivo=MOTIVO, **extra):
    with company_context(empresa):
        return anulados.marcar(empresa, usuario, slug, doc, fecha or HOY, motivo, **extra)


def error_de(funcion):
    with pytest.raises(anulados.ErrorAnulacion) as error:
        funcion()
    return error.value.codigo, str(error.value)


def recargar(doc):
    with company_context(doc.company):
        return type(doc).objects.get(pk=doc.pk)


def stock(empresa, producto):
    return leer(empresa, lambda: Product.objects.get(pk=producto.pk).stock)


def nueva_compra(empresa, ruc='0990000001001', numero='501'):
    with company_context(empresa):
        proveedor = Provider.objects.create(name=f'PROVEEDOR FICTICIO {numero}', ruc=ruc, mobile='0990000009',
                                            email=f'proveedor{numero}@example.com', address='Av. Quito 100')
        compra = Purchase.objects.create(number=numero, provider=proveedor, subtotal=Decimal('0'))
        categoria = Category.objects.get_or_create(name='Compras de prueba')[0]
        item = Product.objects.create(name=f'Insumo {numero}', code=f'INS-{numero}', category=categoria, price=Decimal('50.00'),
                                      pvp=Decimal('50.00'), stock=0, with_tax=False, inventoried=False)
        PurchaseDetail.objects.create(purchase=compra, product=item, cant=2, price=Decimal('50.00'), subtotal=Decimal('100.00'))
        compra.calculate_invoice()
        return compra


def autorizar(doc):
    """Comprobante adicional autorizado sin pasar por el SRI (estas pruebas son de la marca, no de la emisión)."""
    with company_context(doc.company):
        type(doc).objects.filter(pk=doc.pk).update(status='authorized', emission_date=EMITIDA, access_code='1' * 49)
        return type(doc).objects.get(pk=doc.pk)


def retencion_emitida(empresa, usuario, compra, **cambios):
    with company_context(empresa):
        if not Receipt.objects.filter(voucher_type='07').exists():
            cfg.configurar_otro_documento(empresa, '07', 'otro_sistema', '001-002-000000040', True)
        datos = {'num_doc_sustento': '001-001-000000123', 'aut_doc_sustento': '1' * 49, 'base_0': '0', 'base_iva': '100.00',
                 'tarifa_iva': '15.00', 'cod_sustento': '01', 'forma_pago': '20', 'fecha_doc_sustento': EMITIDA}
        datos.update(cambios)
        codigo = CodigoRetencion.objects.get(impuesto='1', codigo='312')
        with transaction.atomic():
            ret = sv.crear(empresa, usuario, compra, datos, [(codigo.pk, None, None)])
    return autorizar(ret)


def liquidacion_emitida(empresa, usuario, compra):
    with company_context(empresa):
        cfg.configurar_otro_documento(empresa, '03', 'otro_sistema', '001-002-000000007', True)
        with transaction.atomic():
            liq = sl.crear(empresa, usuario, compra, {}, {})
    return autorizar(liq)


def guia_emitida(empresa, usuario, venta):
    with company_context(empresa):
        if not Receipt.objects.filter(voucher_type='06').exists():
            cfg.configurar_otro_documento(empresa, '06', 'otro_sistema', '001-002-000000009', True)
        detalle = SaleDetail.objects.get(sale=venta)
        datos = {'transportista_tipo_identificacion': '04', 'transportista_identificacion': '0912345600001',
                 'transportista_razon_social': 'TRANSPORTES FICTICIOS', 'placa': 'GBA-1234', 'dir_partida': 'Av. Ficticia 1',
                 'direccion': 'Km 5 vía a Daule', 'motivo': 'Venta', 'fecha_inicio': HOY, 'fecha_fin': HOY + timedelta(days=1)}
        with transaction.atomic():
            guia = sg.crear(empresa, usuario, venta, datos, {detalle.pk: detalle.cant})
    return autorizar(guia)


@pytest.fixture
def crear(empresa, dueno, comprador, producto, sri):  # noqa: F811
    """crear(slug) → comprobante autorizado de ese tipo, emitido hace 3 días."""
    def _crear(slug):
        if slug == 'factura':
            return factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=EMITIDA)
        if slug == 'nota-credito':
            venta = factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=EMITIDA)
            return nota_credito_autorizada(venta, sri=sri)
        if slug == 'nota-debito':
            venta = factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=EMITIDA)
            return nota_debito_autorizada(venta, '5.00', dueno, sri=sri)
        if slug == 'retencion':
            return retencion_emitida(empresa, dueno, nueva_compra(empresa))
        if slug == 'liquidacion':
            return liquidacion_emitida(empresa, dueno, nueva_compra(empresa, ruc='0912345675', numero='777'))
        if slug == 'guia':
            return guia_emitida(empresa, dueno, factura_autorizada(empresa, comprador, dueno, producto, fecha=EMITIDA))
        raise AssertionError(slug)
    return _crear


# ---------------------------------------------------------------- comunes a los seis tipos

class TestComunes:

    @pytest.mark.parametrize('slug', SLUGS)
    def test_marca_correcta(self, empresa, dueno, crear, slug, senales, sri):  # noqa: F811
        doc = crear(slug)
        recepciones, consultas, correos = len(sri.recepciones), len(sri.consultas), len(mail.outbox)
        usados = SubscriptionPeriod.objects.get(company=empresa, status='activa').documents_used
        resultado = marcar(empresa, dueno, slug, doc, fecha=HOY)
        doc = recargar(doc)
        assert (doc.anulado_sri_fecha, doc.anulado_sri_motivo, doc.anulado_sri_por) == (HOY, MOTIVO, dueno)
        assert doc.anulado_sri_registrado_en is not None and doc.anulado_en_sri and anulados.esta_anulado(doc)
        assert doc.status == 'authorized'                                             # el status no cambia
        assert senales == [(type(doc), doc.pk, dueno, HOY, HOY)]
        registro = AuditLog.objects.get(action='comprobante_anulado_sri')
        json.dumps(registro.detail)
        assert registro.detail['modelo'] == slug and registro.detail['id'] == doc.pk and registro.user == dueno
        assert registro.detail['fecha'] == HOY.isoformat() and registro.detail['motivo'] == MOTIVO
        assert registro.detail['numero'] == doc.voucher_number_full and registro.detail['confirmo_plazo'] is False
        assert registro.detail['efectos'] == resultado['efectos']
        # Ni SRI, ni correo, ni cupo
        assert (len(sri.recepciones), len(sri.consultas), len(mail.outbox)) == (recepciones, consultas, correos)
        assert SubscriptionPeriod.objects.get(company=empresa, status='activa').documents_used == usados
        assert error_de(lambda: marcar(empresa, dueno, slug, doc))[0] == 'ya_anulado'

    @pytest.mark.parametrize('slug', SLUGS)
    def test_requisitos(self, empresa, dueno, crear, slug):  # noqa: F811
        doc = crear(slug)
        assert error_de(lambda: marcar(empresa, dueno, slug, doc, motivo='corto'))[0] == 'motivo'
        assert error_de(lambda: marcar(empresa, dueno, slug, doc, motivo='x' * 301))[0] == 'motivo'
        assert error_de(lambda: marcar(empresa, dueno, slug, doc, fecha=HOY + timedelta(days=1))) == (
            'fecha_futura', 'La fecha de anulación no puede ser futura.')
        emitida = anulados.fecha_emision(doc)            # NC y ND pasan por la emisión real: emitidas hoy
        assert error_de(lambda: marcar(empresa, dueno, slug, doc, fecha=emitida - timedelta(days=1))) == (
            'fecha_anterior', f'La fecha de anulación no puede ser anterior a la emisión ({emitida:%d/%m/%Y}).')
        leer(empresa, lambda: type(doc).objects.filter(pk=doc.pk).update(status='returned'))
        assert error_de(lambda: marcar(empresa, dueno, slug, doc))[0] == 'no_autorizado'
        assert recargar(doc).anulado_sri_fecha is None and not AuditLog.objects.filter(action='comprobante_anulado_sri').exists()

    @pytest.mark.parametrize('slug', SLUGS)
    def test_receptor_que_falla_deshace_la_marca(self, empresa, dueno, crear, slug):  # noqa: F811
        doc = crear(slug)

        def falla(sender, **kwargs):
            raise RuntimeError('cuenta por pagar desalineada')
        anulado_en_sri.connect(falla, weak=False, dispatch_uid='prueba_o2_falla')
        try:
            with pytest.raises(RuntimeError, match='desalineada'):
                marcar(empresa, dueno, slug, doc)
        finally:
            anulado_en_sri.disconnect(dispatch_uid='prueba_o2_falla')
        assert recargar(doc).anulado_sri_fecha is None
        assert not AuditLog.objects.filter(action='comprobante_anulado_sri').exists()
        assert not leer(empresa, lambda: PaymentsCtaCollect.objects.filter(tipo='anulacion').exists())

    def test_plazo_del_dia_7(self, empresa, dueno, comprador, producto):  # noqa: F811
        venta = factura_autorizada(empresa, comprador, dueno, producto, fecha=date(2026, 9, 15))
        assert anulados.limite_plazo_sri(date(2026, 9, 15)) == date(2026, 10, 7)
        assert anulados.limite_plazo_sri(date(2026, 12, 20)) == date(2027, 1, 7)
        with company_context(empresa):
            assert anulados.revisar(venta, date(2026, 10, 7))['pide_confirmar_plazo'] is False
            revision = anulados.revisar(venta, '2026-10-08')
        assert revision['pide_confirmar_plazo'] is True and revision['limite_plazo'] == date(2026, 10, 7)
        assert error_de(lambda: marcar(empresa, dueno, 'factura', venta, fecha=date(2026, 10, 8))) == (
            'plazo_sin_confirmar', 'La fecha pasa del plazo del SRI (07/10/2026): confirma que el SRI aceptó la anulación.')
        marcar(empresa, dueno, 'factura', venta, fecha=date(2026, 10, 8), confirmo_plazo=True)
        assert AuditLog.objects.get(action='comprobante_anulado_sri').detail['confirmo_plazo'] is True

    def test_dentro_del_plazo_sin_casilla(self, empresa, dueno, comprador, producto):  # noqa: F811
        venta = factura_autorizada(empresa, comprador, dueno, producto, fecha=date(2026, 9, 15))
        marcar(empresa, dueno, 'factura', venta, fecha=date(2026, 10, 7))
        assert recargar(venta).anulado_sri_fecha == date(2026, 10, 7)

    def test_ticket_otra_empresa_y_slug_invalido(self, empresa, dueno, comprador, producto, empresa_b):  # noqa: F811
        ticket = factura_autorizada(empresa, comprador, dueno, producto, tipo='08', fecha=EMITIDA)
        assert error_de(lambda: marcar(empresa, dueno, 'factura', ticket)) == (
            'ticket', 'El ticket de venta no es un comprobante del SRI: no se anula en el SRI.')
        venta = factura_autorizada(empresa, comprador, dueno, producto, fecha=EMITIDA)
        with company_context(empresa):
            assert anulados.obtener('factura', venta.pk).pk == venta.pk
            with pytest.raises(Http404):
                anulados.obtener('boleta', venta.pk)
        with company_context(empresa_b), pytest.raises(Http404):
            anulados.obtener('factura', venta.pk)
        with pytest.raises(Http404):
            anulados.permiso('boleta')
        assert [anulados.permiso(s) for s in SLUGS] == ['change_anulado_sri_sale', 'change_anulado_sri_creditnote',
                                                        'change_anulado_sri_retencion', 'change_anulado_sri_liquidacioncompra',
                                                        'change_anulado_sri_notadebito', 'change_anulado_sri_guiaremision']
        with pytest.raises(Http404):
            marcar(empresa, dueno, 'nota-credito', venta)                     # el documento no es de ese tipo


# ---------------------------------------------------------------- factura

class TestFactura:

    def test_consumidor_final_desde_2026(self, empresa, dueno, producto):  # noqa: F811
        with company_context(empresa):
            cf = consumidor_final(empresa)
        nueva = factura_autorizada(empresa, cf, dueno, producto, fecha=date(2026, 1, 5))
        assert error_de(lambda: marcar(empresa, dueno, 'factura', nueva, confirmo_plazo=True)) == (
            'consumidor_final', 'El SRI no permite anular facturas emitidas a consumidor final (Res. NAC-DGERCGC25-00000014, '
                                'desde el 01/01/2026).')
        antigua = factura_autorizada(empresa, cf, dueno, producto, fecha=date(2025, 12, 20))
        marcar(empresa, dueno, 'factura', antigua, confirmo_plazo=True)
        assert recargar(antigua).anulado_en_sri

    def test_impedimentos_por_notas_retencion_y_cobros(self, empresa, dueno, comprador, producto, sri):  # noqa: F811
        def factura():
            return factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=EMITIDA)
        uno = factura()
        nota = nota_credito_autorizada(uno, sri=sri, lineas=[(leer(empresa, lambda: SaleDetail.objects.get(sale=uno).pk), 1)])
        assert error_de(lambda: marcar(empresa, dueno, 'factura', uno)) == (
            'nc_vigente', f'Primero marca como anulada la nota de crédito {nota.voucher_number_full}: modifica esta factura.')
        dos = factura()
        nota = nota_credito_autorizada(dos, sri=sri, autorizar=False)
        assert nota.status == 'in_process' and error_de(lambda: marcar(empresa, dueno, 'factura', dos))[0] == 'nc_en_proceso'
        tres = factura()
        sri.respuestas_recepcion = [('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])]
        nota = nota_credito_autorizada(tres, sri=sri, autorizar=False)
        assert nota.status == 'returned' and error_de(lambda: marcar(empresa, dueno, 'factura', tres)) == (
            'nc_sin_enviar', f'Elimina antes la nota de crédito {nota.voucher_number_full}, que el SRI no autorizó o no se envió.')
        cuatro = factura()
        nd = nota_debito_autorizada(cuatro, '5.00', dueno, sri=sri)
        assert error_de(lambda: marcar(empresa, dueno, 'factura', cuatro)) == (
            'nd_vigente', f'Primero marca como anulada la nota de débito {nd.voucher_number_full}.')
        cinco = factura()
        with company_context(empresa), transaction.atomic():
            ret = rr.registrar(empresa, dueno, cinco, retencion_datos())
        assert error_de(lambda: marcar(empresa, dueno, 'factura', cinco)) == (
            'retencion_recibida', f'Primero anula el registro de la retención {ret.numero} que te hizo el cliente.')
        seis = factura()
        with company_context(empresa):
            cxc.registrar_cobro(empresa, dueno, cxc_de(seis).pk, HOY, '5.00', 'efectivo')
            assert anulados.revisar(seis)['impedimentos'] == [
                'La cuenta por cobrar tiene cobros por $5,00. Elimínalos o regístralos en el comprobante que la reemplace antes '
                'de marcarla como anulada.']
        assert error_de(lambda: marcar(empresa, dueno, 'factura', seis))[0] == 'cobros'

    def test_abono_de_anulacion_y_cxc_anulada(self, empresa, dueno, crear):  # noqa: F811
        venta = crear('factura')
        with company_context(empresa):
            assert 'Se registrará un abono de anulación de $23,00 en la cuenta por cobrar.' in anulados.revisar(venta)['efectos']
        resultado = marcar(empresa, dueno, 'factura', venta)
        assert 'Abono de anulación de $23,00 en la cuenta por cobrar.' in resultado['efectos']
        with company_context(empresa):
            cuenta = CtasCollect.objects.get(sale=venta)
            [abono] = PaymentsCtaCollect.objects.filter(ctas_collect=cuenta)
            assert (abono.tipo, abono.valor, abono.date_joined, abono.registrado_por) == ('anulacion', Decimal('23.00'), HOY, dueno)
            assert cuenta.saldo == 0 and cuenta.state is False and cuenta.estado() == 'anulada'
            assert cxc.listado().get(pk=cuenta.pk).toJSON()['estado']['name'] == 'Anulada en el SRI'
            with pytest.raises(cxc.ErrorCxC) as error:
                cxc.registrar_cobro(empresa, dueno, cuenta.pk, HOY, '1.00', 'efectivo')
            assert error.value.codigo == 'cxc_anulada'

    def test_inventario(self, empresa, dueno, comprador, producto, sri):  # noqa: F811
        con = factura_autorizada(empresa, comprador, dueno, producto, fecha=EMITIDA)
        assert stock(empresa, producto) == 98
        with company_context(empresa):
            revision = anulados.revisar(con)
        assert [(p.pk, n) for p, n in revision['stock']] == [(producto.pk, 2)]
        marcar(empresa, dueno, 'factura', con, ajustar_stock=True)
        assert stock(empresa, producto) == 100 and recargar(con).anulado_sri_stock is True
        sin = factura_autorizada(empresa, comprador, dueno, producto, fecha=EMITIDA)
        marcar(empresa, dueno, 'factura', sin)
        assert stock(empresa, producto) == 98 and recargar(sin).anulado_sri_stock is False
        # NC de 1 unidad anulada SIN ajuste: esa unidad siguió devuelta; al anular la factura solo vuelve la otra
        con_nc = factura_autorizada(empresa, comprador, dueno, producto, fecha=EMITIDA)          # 96
        nota = nota_credito_autorizada(con_nc, sri=sri, lineas=[(leer(empresa, lambda: SaleDetail.objects.get(sale=con_nc).pk), 1)])
        assert stock(empresa, producto) == 97
        marcar(empresa, dueno, 'nota-credito', nota)
        assert stock(empresa, producto) == 97
        marcar(empresa, dueno, 'factura', con_nc, ajustar_stock=True)
        assert stock(empresa, producto) == 98

    def test_aviso_de_guias(self, empresa, dueno, comprador, producto):  # noqa: F811
        venta = factura_autorizada(empresa, comprador, dueno, producto, fecha=EMITIDA)
        guia = guia_emitida(empresa, dueno, venta)
        resultado = marcar(empresa, dueno, 'factura', venta)
        assert resultado['avisos'] == [f'La factura tiene guías de remisión autorizadas ({guia.voucher_number_full}): anúlalas '
                                       'también en SRI en línea si corresponde.']

    def test_despues_no_admite_documentos_nuevos_ni_correo(self, empresa, dueno, comprador, producto):  # noqa: F811
        venta = factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=EMITIDA)
        marcar(empresa, dueno, 'factura', venta)
        with company_context(empresa):
            venta = Sale.objects.get(pk=venta.pk)
            mensaje = f'La factura {venta.voucher_number_full} está anulada en el SRI.'
            with pytest.raises(notas_credito.ErrorNotaCredito, match=mensaje):
                notas_credito.validar_factura(venta, empresa)
            with pytest.raises(snd.ErrorNotaDebito, match=mensaje):
                snd.validar_factura(venta, empresa)
            with pytest.raises(sg.ErrorGuia, match=mensaje):
                sg.validar_factura(venta, empresa)
            with pytest.raises(rr.ErrorRetencionRecibida) as error:
                rr.calcular(venta, retencion_datos())
            assert error.value.codigo == 'factura_anulada'
            assert SRI().notify_by_email(instance=venta, company=empresa, client=venta.client) == {
                'resp': False, 'error': 'El comprobante está anulado en el SRI: no se envía por correo.'}
        assert mail.outbox == []


# ---------------------------------------------------------------- nota de crédito, nota de débito y comprobantes de compras

class TestNotaCredito:

    def test_revierte_abono_factura_stock_y_cantidades(self, empresa, dueno, comprador, producto, sri):  # noqa: F811
        venta = factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=EMITIDA)
        nota = nota_credito_autorizada(venta, sri=sri)                              # las 2 unidades: cubre la factura
        assert recargar(venta).status == 'canceled' and nota.cxc_ajuste == 'aplicada' and stock(empresa, producto) == 100
        with company_context(empresa):
            efectos = anulados.revisar(nota)['efectos']
        assert f'La factura {venta.voucher_number_full} volverá a «Autorizada»: deja de estar cubierta por notas de crédito.' in efectos
        resultado = marcar(empresa, dueno, 'nota-credito', nota, ajustar_stock=True)
        assert f'La factura {venta.voucher_number_full} volvió a «Autorizada».' in resultado['efectos']
        nota, venta = recargar(nota), recargar(venta)
        assert venta.status == 'authorized' and nota.cxc_ajuste == 'revertida' and nota.anulado_sri_stock is True
        assert stock(empresa, producto) == 98                                       # se deshizo la devolución
        with company_context(empresa):
            abono = PaymentsCtaCollect.objects.get(pk=nota.abono_cxc_id)
            assert abono.anulado_en is not None and CtasCollect.objects.get(sale=venta).saldo == Decimal('23.00')
            assert notas_credito.acreditado_por_detalle(venta) == {}                # sus cantidades se acreditan otra vez
            assert CreditNote.objects.get(pk=nota.pk).toJSON()['anulado_sri'] == {'fecha': HOY.isoformat()}

    def test_stock_negativo_se_avisa(self, empresa, dueno, comprador, producto, sri):  # noqa: F811
        venta = factura_autorizada(empresa, comprador, dueno, producto, fecha=EMITIDA)
        nota = nota_credito_autorizada(venta, sri=sri)
        leer(empresa, lambda: Product.objects.filter(pk=producto.pk).update(stock=1))
        resultado = marcar(empresa, dueno, 'nota-credito', nota, ajustar_stock=True)
        assert resultado['avisos'] == [f'El inventario de {producto.name} quedará en -1.'] and stock(empresa, producto) == -1


class TestNotaDebito:

    def test_cobros_impiden_y_sin_ellos_anula_su_cxc(self, empresa, dueno, crear):  # noqa: F811
        nota = crear('nota-debito')
        with company_context(empresa):
            cobro = cxc.registrar_cobro(empresa, dueno, nota.cuenta_por_cobrar_id, HOY, '2.00', 'efectivo')
        assert error_de(lambda: marcar(empresa, dueno, 'nota-debito', nota)) == (
            'cobros', 'La cuenta por cobrar tiene cobros por $2,00. Elimínalos o regístralos en el comprobante que la reemplace '
                      'antes de marcarla como anulada.')
        with company_context(empresa):
            PaymentsCtaCollect.objects.filter(pk=cobro.pk).delete()
            cxc.recalcular(CtasCollect.objects.get(pk=nota.cuenta_por_cobrar_id))
        marcar(empresa, dueno, 'nota-debito', nota)
        with company_context(empresa):
            nota = NotaDebito.objects.get(pk=nota.pk)
            cuenta = nota.cuenta_por_cobrar
            assert nota.cxc_ajuste == 'revertida' and cuenta.estado() == 'anulada' and cuenta.saldo == 0
            assert PaymentsCtaCollect.objects.get(ctas_collect=cuenta, tipo='anulacion').valor == Decimal('5.00')


class TestComprasYGuias:

    def test_retencion_emitida_deja_de_contar(self, empresa, dueno):  # noqa: F811
        compra = nueva_compra(empresa)
        ret = retencion_emitida(empresa, dueno, compra)
        with company_context(empresa):
            assert sv.retencion_vigente(compra) == ret and list(sv.retenciones_autorizadas(compra)) == [ret]
        resultado = marcar(empresa, dueno, 'retencion', ret)
        assert resultado['efectos'] == [] and AuditLog.objects.get(action='comprobante_anulado_sri').detail['modelo'] == 'retencion'
        with company_context(empresa):
            assert sv.retencion_vigente(compra) is None and not sv.retenciones_autorizadas(compra).exists()
            assert Retencion.objects.get(pk=ret.pk).toJSON()['anulado_sri'] == {'fecha': HOY.isoformat()}

    def test_liquidacion_con_retencion_sobre_ella(self, empresa, dueno):  # noqa: F811
        compra = nueva_compra(empresa, ruc='0912345675', numero='778')
        liq = liquidacion_emitida(empresa, dueno, compra)
        ret = retencion_emitida(empresa, dueno, compra, cod_doc_sustento='03', num_doc_sustento=liq.voucher_number_full,
                                cod_sustento='02')
        assert error_de(lambda: marcar(empresa, dueno, 'liquidacion', liq)) == (
            'retencion_sobre_liquidacion', f'Primero marca como anulada la retención {ret.voucher_number_full} emitida sobre '
                                           'esta liquidación.')
        marcar(empresa, dueno, 'retencion', ret)
        marcar(empresa, dueno, 'liquidacion', liq)
        with company_context(empresa):
            assert sl.liquidacion_vigente(compra) is None
            assert LiquidacionCompra.objects.get(pk=liq.pk).anulado_en_sri

    def test_guia_deja_de_trasladar(self, empresa, dueno, comprador, producto):  # noqa: F811
        venta = factura_autorizada(empresa, comprador, dueno, producto, fecha=EMITIDA)
        guia = guia_emitida(empresa, dueno, venta)
        with company_context(empresa):
            assert sum(sg.trasladado_por_detalle(venta).values()) == 2
        marcar(empresa, dueno, 'guia', guia)
        with company_context(empresa):
            assert sg.trasladado_por_detalle(venta) == {}
            assert GuiaRemision.objects.get(pk=guia.pk).anulado_en_sri


def test_revisar_muestra_impedimentos_sin_escribir(empresa, dueno, comprador, producto, sri):  # noqa: F811
    venta = factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=EMITIDA)
    leer(empresa, lambda: Sale.objects.filter(pk=venta.pk).update(status='in_process'))
    with company_context(empresa):
        revision = anulados.revisar(Sale.objects.get(pk=venta.pk), HOY + timedelta(days=1))
    assert revision['impedimentos'][:2] == ['Solo se marca como anulado un comprobante autorizado por el SRI.',
                                            'La fecha de anulación no puede ser futura.']
    assert not leer(empresa, lambda: PaymentsCtaCollect.objects.exists())
