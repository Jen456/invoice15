"""Compras completas (core/pos/compras.py): tarifas, IVA y descuento por línea, totales por base, cuenta por pagar sobre el
total con IVA, unicidad del comprobante, modos «liquidación» y «completar después», notas de crédito y débito del
proveedor, eliminación auditada y valores por defecto que fallan cerrados. Datos ficticios; SRI simulado (SRIFalso)."""
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.comprobantes import liquidaciones as sl
from core.comprobantes.models import LiquidacionCompra, Retencion
from core.configuracion import servicios as cfg
from core.importacion.models import DocumentoImportado, EventoImportacion
from core.pos import compras, cuentas_por_pagar, emision
from core.pos.models import DebtsPay, Product, Purchase, PurchaseDetail, Receipt
from core.pos.senales_comprobantes import anulado_en_sri
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog
from tests import ayuda_compras as ayuda, fabricas_sri, helpers
from tests.test_firma_sri import CLAVE
from tests.test_retenciones import p12, sri  # noqa: F401 (fixtures compartidos)

pytestmark = pytest.mark.django_db
RUC = '0990000001001'
XSS = '<img src=x onerror=alert(1)>'


def hoy():
    return timezone.localdate()


def crear(empresa, usuario, datos, lineas, **kwargs):
    with company_context(empresa):
        return compras.crear_compra(empresa, usuario, datos, lineas, **kwargs)


def calcular(empresa, datos, lineas):
    with company_context(empresa):
        return compras.calcular(empresa, datos, lineas)


def error(empresa, usuario, datos, lineas, **kwargs):
    with pytest.raises(compras.ErrorCompra) as e:
        crear(empresa, usuario, datos, lineas, **kwargs)
    return e.value


def recargar(empresa, compra):
    with company_context(empresa):
        return Purchase.objects.select_related('provider').get(pk=compra.pk)


def codigos(empresa, compra):
    with company_context(empresa):
        return [c for c, _ in compras.faltantes(recargar(empresa, compra))]


@pytest.fixture
def proveedor(empresa):
    return ayuda.crear_proveedor(empresa, tipo='04', ruc=RUC)


@pytest.fixture
def producto(empresa):
    return ayuda.crear_producto(empresa, codigo='INV-1')


class TestCalculo:

    def test_tarifas_descuento_y_redondeo_half_up(self, empresa, admin, proveedor, producto):
        lineas = [ayuda.linea_producto(producto, cant=3, price='10.00', descuento='1.00'),     # 29,00 → IVA 4,35
                  ayuda.linea_gasto('Servicio técnico', price='10.30'),                         # 1,545 → 1,55 (HALF_UP)
                  ayuda.linea_gasto('Alimentos', price='100.00', codigo='5'),
                  ayuda.linea_gasto('Libros', price='20.00', codigo='0'),
                  ayuda.linea_gasto('Tasa municipal', price='10.00', codigo='6'),
                  ayuda.linea_gasto('Servicio de salud', price='5.00', codigo='7')]
        datos = ayuda.datos_compra(proveedor)
        r = calcular(empresa, datos, lineas)
        assert [l['total_iva'] for l in r['lineas']] == ['4.35', '1.55', '5.00', '0.00', '0.00', '0.00']
        assert (r['base_gravada'], r['base_5'], r['base_0'], r['base_no_objeto'], r['base_exenta']) == (
            '39.30', '100.00', '20.00', '10.00', '5.00')
        assert r['total_descuento'] == '1.00' and r['total_iva'] == r['total_iva_calculado'] == '10.90'
        assert r['subtotal'] == '174.30' and r['total'] == '185.20' and r['advertencias'] == [] and r['confirmaciones'] == []
        assert [g['codigo'] for g in r['por_tarifa']] == ['4', '5', '0', '6', '7']
        compra = crear(empresa, admin, datos, lineas)
        compra = recargar(empresa, compra)
        assert compra.version_datos == 2 and compra.origen == 'manual' and not compra.datos_incompletos
        assert compra.numero_comprobante == compra.number == f'001-002-{int(datos["secuencial"]):09d}'
        assert (compra.base_gravada, compra.total_iva, compra.total, compra.subtotal) == (
            Decimal('39.30'), Decimal('10.90'), Decimal('185.20'), Decimal('174.30'))
        assert compra.completada_en is not None and compra.completada_por_id == admin.pk
        with company_context(empresa):
            assert list(compra.purchasedetail_set.values_list('codigo_porcentaje', 'tarifa', 'total', 'total_iva')) == [
                ('4', Decimal('15.00'), Decimal('29.00'), Decimal('4.35')), ('4', Decimal('15.00'), Decimal('10.30'), Decimal('1.55')),
                ('5', Decimal('5.00'), Decimal('100.00'), Decimal('5.00')), ('0', Decimal('0.00'), Decimal('20.00'), Decimal('0.00')),
                ('6', Decimal('0.00'), Decimal('10.00'), Decimal('0.00')), ('7', Decimal('0.00'), Decimal('5.00'), Decimal('0.00'))]

    def test_iva_diferenciado_con_tarifa_de_la_factura(self, empresa, admin, proveedor):
        datos = ayuda.datos_compra(proveedor, cod_sustento='01')
        linea = ayuda.linea_gasto('Hospedaje en feriado', price='50.00', codigo='8', tarifa='8.00')
        r = calcular(empresa, datos, [linea])
        assert r['base_gravada'] == '50.00' and r['total_iva'] == '4.00' and r['total'] == '54.00'
        assert r['por_tarifa'] == [{'codigo': '8', 'nombre': 'IVA diferenciado 8 %', 'tarifa': '8.00', 'base': '50.00', 'valor': '4.00'}]
        assert 'Escribe la tarifa del IVA diferenciado' in str(error(empresa, admin, datos, [{**linea, 'tarifa': ''}]))
        compra = crear(empresa, admin, datos, [linea])
        with company_context(empresa):
            resumen = compras.resumen_por_tarifa(compra.purchasedetail_set.all())
            assert compra.purchasedetail_set.get().toJSON()['nombre_tarifa'] == 'IVA diferenciado 8 %'
        assert resumen == [{'codigo': '8', 'nombre': 'IVA diferenciado 8 %', 'tarifa': Decimal('8.00'), 'base': Decimal('50.00'),
                            'valor': Decimal('4.00')}]

    def test_nota_de_venta_no_discrimina_iva(self, empresa, admin, proveedor):
        datos = ayuda.datos_compra(proveedor, tipo_comprobante='02', cod_sustento='02')
        assert 'no discrimina IVA' in str(error(empresa, admin, datos, [ayuda.linea_gasto(codigo='4')]))
        assert 'no discrimina IVA' in str(error(empresa, admin, dict(datos, iva_factura='1.00'), [ayuda.linea_gasto(codigo='0')]))
        compra = crear(empresa, admin, datos, [ayuda.linea_gasto(price='40.00', codigo='0')])
        assert compra.total_iva == Decimal('0.00') and compra.base_0 == Decimal('40.00') and compra.total == Decimal('40.00')

    @pytest.mark.parametrize('precio, forma, aviso', [('1500.00', '01', True), ('900.00', '01', False), ('1500.00', '20', False)])
    def test_bancarizacion_avisa_sin_bloquear(self, empresa, proveedor, precio, forma, aviso):
        r = calcular(empresa, ayuda.datos_compra(proveedor, forma_pago=forma), [ayuda.linea_gasto(price=precio, codigo='0')])
        assert ('bancarizacion' in [a['codigo'] for a in r['advertencias']]) is aviso

    def test_iva_de_la_factura_distinto_exige_confirmar(self, empresa, admin, proveedor):
        datos, lineas = ayuda.datos_compra(proveedor), [ayuda.linea_gasto(price='100.00')]
        assert calcular(empresa, dict(datos, iva_factura='15.04'), lineas)['confirmaciones'] == []
        assert calcular(empresa, dict(datos, iva_factura='15.10'), lineas)['confirmaciones'] == ['confirmar_iva']
        assert error(empresa, admin, dict(datos, iva_factura='15.10'), lineas).codigo == 'confirmar_iva'
        assert not ayuda.en(empresa, Purchase.objects.exists)
        compra = crear(empresa, admin, dict(datos, iva_factura='15.10', confirmar_iva='1'), lineas)
        assert compra.total_iva == Decimal('15.10') and compra.total == Decimal('115.10')


class TestRegistro:

    def test_credito_con_cuenta_por_pagar_sobre_el_total_y_contado_sin_ella(self, empresa, admin, proveedor):
        plazo = (hoy() + timedelta(days=30)).isoformat()
        credito = crear(empresa, admin, ayuda.datos_compra(proveedor, payment_type='credito', end_credit=plazo),
                        [ayuda.linea_gasto(price='100.00')])
        contado = crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(price='100.00')])
        with company_context(empresa):
            deuda = DebtsPay.objects.get()
            assert deuda.purchase_id == credito.pk and deuda.base_calculo == 'total' and deuda.state
            assert (deuda.debt, deuda.saldo) == (Decimal('115.00'), Decimal('115.00'))
            assert not DebtsPay.objects.filter(purchase=contado).exists()
        assert 'plazo del crédito' in str(error(empresa, admin, ayuda.datos_compra(proveedor, payment_type='credito'),
                                                 [ayuda.linea_gasto()]))

    def test_stock_solo_en_lineas_con_producto_inventariado(self, empresa, admin, proveedor, producto):
        servicio = ayuda.crear_producto(empresa, codigo='SERV-1', inventariado=False)
        crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_producto(producto, cant=3), ayuda.linea_producto(servicio, cant=2),
                                                             ayuda.linea_producto(producto, cant=1), ayuda.linea_gasto()])
        with company_context(empresa):
            assert Product.objects.get(pk=producto.pk).stock == 104 and Product.objects.get(pk=servicio.pk).stock == 100

    def test_duplicado_del_mismo_proveedor_y_mismo_numero_de_otro(self, empresa, admin, proveedor, monkeypatch):
        primera = crear(empresa, admin, ayuda.datos_compra(proveedor, secuencial='271'), [ayuda.linea_gasto()])
        mensaje = str(error(empresa, admin, ayuda.datos_compra(proveedor, secuencial='000000271'), [ayuda.linea_gasto()]))
        assert mensaje == f'Ya registraste factura 001-002-000000271 de {proveedor.name} (compra #{primera.pk}).'
        otro = ayuda.crear_proveedor(empresa, tipo='04')
        assert crear(empresa, admin, ayuda.datos_compra(otro, secuencial='271'), [ayuda.linea_gasto()]).pk
        # El choque detectado en el INSERT (otra petición ganó la carrera) sale del savepoint: la transacción sigue usable.
        real, llamadas = compras._comprobante_registrado, []

        def sin_ver_la_primera_vez(*args, **kwargs):
            llamadas.append(args)
            return None if len(llamadas) == 1 else real(*args, **kwargs)

        monkeypatch.setattr(compras, '_comprobante_registrado', sin_ver_la_primera_vez)
        with transaction.atomic():
            with pytest.raises(compras.ErrorCompra, match=f'compra #{primera.pk}'):
                crear(empresa, admin, ayuda.datos_compra(proveedor, secuencial='271'), [ayuda.linea_gasto()])
            assert ayuda.en(empresa, Purchase.objects.count) == 2 and len(llamadas) == 2

    def test_modo_despues_queda_incompleta_con_sus_faltantes(self, empresa, admin, proveedor):
        datos = {'provider': proveedor.pk, 'modo_comprobante': 'despues', 'date_joined': hoy().isoformat()}
        compra = crear(empresa, admin, datos, [ayuda.linea_gasto(price='10.00', codigo='0')])
        assert compra.datos_incompletos and compra.version_datos == 2 and compra.total == Decimal('10.00')
        assert codigos(empresa, compra) == ['tipo_comprobante', 'cod_sustento', 'estab', 'pto_emi', 'secuencial', 'autorizacion',
                                            'fecha_emision', 'forma_pago', 'parte_relacionada', 'pago_loc_ext']
        assert 'tres dígitos' in str(error(empresa, admin, dict(datos, estab='000'), [ayuda.linea_gasto()]))   # lo que llega se valida
        sin_tipo = ayuda.crear_proveedor(empresa, tipo='')
        assert crear(empresa, admin, dict(datos, provider=sin_tipo.pk), [ayuda.linea_gasto()]).datos_incompletos

    @pytest.mark.parametrize('cambios, mensaje', [
        ({'cod_sustento': '10'}, 'El sustento 10 no admite el tipo de comprobante «Factura»'),
        ({'tipo_comprobante': '03'}, 'modo «Liquidación»'),
        ({'tipo_comprobante': ''}, 'Elige el tipo de comprobante'),
        ({'cod_sustento': ''}, 'Elige el sustento tributario'),
        ({'secuencial': '0'}, 'mayor que cero'),
        ({'autorizacion': '12345'}, '49 dígitos'),
        ({'fecha_emision': (timezone.localdate() + timedelta(days=1)).isoformat()}, 'no puede ser futura'),
        ({'date_joined': (timezone.localdate() - timedelta(days=5)).isoformat()}, 'posterior a la fecha de registro'),
        ({'forma_pago': ''}, 'Elige la forma de pago'),
        ({'parte_relacionada': ''}, 'Indica si el proveedor es parte relacionada'),
        ({'pago_loc_ext': ''}, 'residente'),
    ])
    def test_validaciones_de_la_cabecera(self, empresa, admin, proveedor, cambios, mensaje):
        assert mensaje in str(error(empresa, admin, ayuda.datos_compra(proveedor, **cambios), [ayuda.linea_gasto()]))
        assert not ayuda.en(empresa, Purchase.objects.exists)

    def test_proveedor_sin_tipo_o_con_cedula(self, empresa, admin):
        sin_tipo = ayuda.crear_proveedor(empresa, tipo='')
        assert 'Completa el tipo de identificación del proveedor' in str(
            error(empresa, admin, ayuda.datos_compra(sin_tipo), [ayuda.linea_gasto()]))
        con_cedula = ayuda.crear_proveedor(empresa, tipo='05')
        assert str(error(empresa, admin, ayuda.datos_compra(con_cedula), [ayuda.linea_gasto()])) == \
            'Una factura solo se registra con un proveedor con RUC.'

    @pytest.mark.parametrize('clave, mensaje', [
        (dict(ruc='0990000002001'), 'no coincide el RUC del proveedor'),
        (dict(secuencial='000000999'), 'no coincide el secuencial'),
        (dict(fecha_menos=3), 'no coincide la fecha de emisión'),
        (dict(cod_doc='04'), 'no coincide el tipo de comprobante'),
        (dict(ambiente=1), 'PRUEBAS'),
        (dict(), None),
    ])
    def test_autorizacion_electronica_coherente(self, empresa, admin, proveedor, clave, mensaje):
        fecha, clave = hoy() - timedelta(days=2), dict(clave)
        partes = dict(fecha=fecha - timedelta(days=clave.pop('fecha_menos', 0)), cod_doc='01', ruc=RUC, ambiente=2, estab='001',
                      pto='002', secuencial='000000271')
        partes.update(clave)
        datos = ayuda.datos_compra(proveedor, secuencial='271', fecha_emision=fecha.isoformat(),
                                   autorizacion=fabricas_sri.clave(**partes))
        if mensaje is None:
            assert crear(empresa, admin, datos, [ayuda.linea_gasto()]).autorizacion == fabricas_sri.clave(**partes)
        else:
            assert mensaje in str(error(empresa, admin, datos, [ayuda.linea_gasto()]))

    @pytest.mark.parametrize('fecha, codigo, mensaje', [
        ('2024-03-15', '4', 'La tarifa del 15 % rige desde el 01/04/2024'),
        (None, '2', 'La tarifa del 12 % ya no rige'),
    ])
    def test_tarifas_segun_la_fecha_de_emision(self, empresa, admin, proveedor, fecha, codigo, mensaje):
        datos = ayuda.datos_compra(proveedor, **({'fecha_emision': fecha} if fecha else {}))
        assert mensaje in str(error(empresa, admin, datos, [ayuda.linea_gasto(codigo=codigo)]))

    def test_mas_de_un_anio_exige_confirmar_y_queda_fuera_del_plazo_del_ats(self, empresa, admin, proveedor, producto):
        datos = ayuda.datos_compra(proveedor, fecha_emision=(hoy() - timedelta(days=400)).isoformat(), payment_type='credito',
                                   end_credit=(hoy() + timedelta(days=30)).isoformat())
        lineas = [ayuda.linea_producto(producto, cant=2)]
        assert error(empresa, admin, datos, lineas).codigo == 'confirmar_plazo_ats'
        assert not ayuda.en(empresa, Purchase.objects.exists)
        compra = crear(empresa, admin, dict(datos, confirmar_plazo_ats='1'), lineas)
        assert compra.fuera_plazo_ats and compra.datos_incompletos and codigos(empresa, compra) == ['fuera_plazo_ats']
        with company_context(empresa):
            assert Product.objects.get(pk=producto.pk).stock == 102 and DebtsPay.objects.get().debt == Decimal('23.00')

    def test_limite_del_plan_gratuito(self, monkeypatch):
        gratuita = helpers.crear_empresa('GRATUITA', plan=None)
        usuario = helpers.crear_usuario('dueno.gratuita', gratuita)
        proveedor = ayuda.crear_proveedor(gratuita, tipo='04')
        from core.suscripciones import servicios
        monkeypatch.setattr(servicios, 'limites_gratuito', lambda: {'purchase_limit_month': 0})
        e = error(gratuita, usuario, ayuda.datos_compra(proveedor), [ayuda.linea_gasto()])
        assert e.codigo == 'limite_plan' and 'El plan gratuito permite hasta 0 compras por mes' in str(e)


class TestNotasDelProveedor:

    @pytest.fixture
    def factura(self, empresa, admin, proveedor):
        return crear(empresa, admin, ayuda.datos_compra(proveedor, secuencial='500', payment_type='credito',
                                                       end_credit=(hoy() + timedelta(days=30)).isoformat()),
                     [ayuda.linea_gasto(price='100.00')])

    def datos_nota(self, proveedor, factura, tipo='04', **cambios):
        return ayuda.datos_compra(proveedor, tipo_comprobante=tipo, secuencial=str(cambios.pop('secuencial', 77)),
                                  tipo_doc_modificado='01', num_doc_modificado='001-002-000000500', aut_doc_modificado='1234567890',
                                  fecha_doc_modificado=factura.fecha_emision.isoformat(), compra_modificada=factura.pk, **cambios)

    def saldo(self, empresa, compra):
        with company_context(empresa):
            return DebtsPay.objects.get(purchase=compra).saldo

    def test_nota_de_credito_exige_documento_modificado_y_lineas_de_gasto(self, empresa, admin, proveedor, factura, producto):
        assert 'documento modificado' in str(error(empresa, admin, ayuda.datos_compra(proveedor, tipo_comprobante='04'),
                                                   [ayuda.linea_gasto()]))
        assert 'líneas de gasto' in str(error(empresa, admin, self.datos_nota(proveedor, factura), [ayuda.linea_producto(producto)]))

    def test_nota_de_credito_abona_la_cuenta_por_pagar_de_la_factura(self, empresa, admin, proveedor, factura):
        nota = crear(empresa, admin, self.datos_nota(proveedor, factura, payment_type='credito', forma_pago='20'),
                     [ayuda.linea_gasto('Devolución', price='20.00')])
        assert nota.total == Decimal('23.00') and nota.payment_type == 'efectivo' and nota.forma_pago == ''
        assert nota.signo == -1 and not nota.datos_incompletos
        assert self.saldo(empresa, factura) == Decimal('92.00')
        with company_context(empresa):
            assert not DebtsPay.objects.filter(purchase=nota).exists()
            abonos = DebtsPay.objects.get(purchase=factura).toJSON(detalle=True)['abonos']
        assert [(a['tipo'], a['id'], a['valor']) for a in abonos] == [('nota_credito', nota.pk, '23.00')]
        # Borrarla devuelve el saldo de la factura; la factura con notas no se puede borrar.
        with company_context(empresa):
            with pytest.raises(compras.ErrorCompra, match='notas de crédito o débito'):
                compras.eliminar_compra(factura, admin)
            compras.eliminar_compra(nota, admin)
        assert self.saldo(empresa, factura) == Decimal('115.00')

    def test_nota_de_credito_no_abona_una_cuenta_calculada_sin_iva(self, empresa, admin, proveedor):
        antigua = ayuda.compra_antigua(empresa, proveedor, '100.00', credito=True)
        datos = ayuda.datos_compra(proveedor, tipo_comprobante='04', tipo_doc_modificado='01', num_doc_modificado='001001000000123',
                                   aut_doc_modificado='1234567890', fecha_doc_modificado=antigua.date_joined.isoformat(),
                                   compra_modificada=antigua.pk)
        crear(empresa, admin, datos, [ayuda.linea_gasto(price='20.00')])
        assert self.saldo(empresa, antigua) == Decimal('100.00')

    def test_nota_de_debito_a_credito_crea_su_cuenta_por_pagar(self, empresa, admin, proveedor, factura):
        nota = crear(empresa, admin, self.datos_nota(proveedor, factura, tipo='05', payment_type='credito',
                                                     end_credit=(hoy() + timedelta(days=10)).isoformat()),
                     [ayuda.linea_gasto('Intereses de mora', price='10.00', codigo='0')])
        assert self.saldo(empresa, nota) == Decimal('10.00') and self.saldo(empresa, factura) == Decimal('115.00')


class TestLiquidacion:
    """Modo «liquidación»: la compra se registra antes de emitir; al autorizarse la liquidación queda completa."""

    @pytest.fixture
    def emisora(self, settings, p12):  # noqa: F811
        settings.FPA_RUC_PROVEEDOR = '0941609729001'
        empresa = helpers.crear_empresa('LIQUIDADORA', plan='plan-1000', environment_type=2)
        helpers.configurar_facturacion(empresa, estab='001', punto='002', ambiente=2)
        empresa.electronic_signature.save('firma.p12', ContentFile(p12), save=False)
        empresa.electronic_signature_key = CLAVE
        empresa.save()
        with company_context(empresa):
            cfg.configurar_otro_documento(empresa, '03', 'otro_sistema', '001-002-000000007', True)
        return empresa

    @pytest.fixture
    def productora(self, emisora):
        return ayuda.crear_proveedor(emisora, tipo='05', correo='sin-correo-productora')   # sin correo: queda «Autorizada»

    def emitir(self, empresa, compra, usuario):
        with company_context(empresa):
            with transaction.atomic():
                liquidacion = sl.crear(empresa, usuario, compra, {'tipo_identificacion': '05', 'forma_pago': '01'}, {})
                emision.preparar(liquidacion)
            return liquidacion, emision.emitir(liquidacion)

    def test_registrada_antes_y_completa_al_autorizarse_idempotente(self, emisora, productora, sri, monkeypatch):  # noqa: F811
        usuario = helpers.crear_usuario('dueno.liquidadora', emisora)
        datos = {'provider': productora.pk, 'modo_comprobante': 'liquidacion', 'cod_sustento': '02', 'forma_pago': '01',
                 'parte_relacionada': 'no', 'pago_loc_ext': '01', 'date_joined': hoy().isoformat()}
        assert 'deja vacíos el número' in str(error(emisora, usuario, dict(datos, secuencial='5'), [ayuda.linea_gasto()]))
        compra = crear(emisora, usuario, datos, [ayuda.linea_gasto('Cacao en grano', price='100.00', codigo='0')])
        assert compra.tipo_comprobante == '03' and codigos(emisora, compra) == ['liquidacion_pendiente']
        sri.respuestas_autorizacion = ['AUTORIZADO']
        liquidacion, resultado = self.emitir(emisora, compra, usuario)
        assert resultado['resp'] is True and resultado['estado'] == 'authorized'
        compra = recargar(emisora, compra)
        assert not compra.datos_incompletos and compra.completada_en is not None
        completada = compra.completada_en
        with company_context(emisora):
            assert emision.emitir(liquidacion)['mensaje'] == 'Ya estaba autorizada por el SRI.'    # la señal se repite
        compra = recargar(emisora, compra)
        assert compra.completada_en == completada and not compra.datos_incompletos and compra.tipo_comprobante == '03'
        # Anulada en el SRI (O2 añade el filtro a liquidacion_vigente; aquí se simula): vuelve a faltar la liquidación.
        monkeypatch.setattr(sl, 'liquidacion_vigente', lambda compra: None)
        with company_context(emisora):
            anulado_en_sri.send(sender=LiquidacionCompra, instance=liquidacion, usuario=usuario, fecha=hoy())
        compra = recargar(emisora, compra)
        assert compra.datos_incompletos and compra.tipo_comprobante == '03'
        assert codigos(emisora, compra) == ['liquidacion_pendiente']

    def test_compra_anterior_pasa_a_tipo_03_al_autorizarse(self, emisora, productora, sri):  # noqa: F811
        usuario = helpers.crear_usuario('dueno.liquidadora2', emisora)
        producto = ayuda.crear_producto(emisora, inventariado=False, tarifa='0')
        antigua = ayuda.compra_antigua(emisora, productora, '50.00', producto=producto)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        self.emitir(emisora, antigua, usuario)
        antigua = recargar(emisora, antigua)
        assert antigua.tipo_comprobante == '03' and antigua.datos_incompletos and antigua.version_datos == 1
        assert 'liquidacion_pendiente' not in codigos(emisora, antigua) and 'importes' in codigos(emisora, antigua)


class TestEliminar:

    @pytest.fixture
    def compra(self, empresa, admin, proveedor, producto):
        return crear(empresa, admin, ayuda.datos_compra(proveedor, secuencial='321', payment_type='credito',
                                                       end_credit=(hoy() + timedelta(days=30)).isoformat()),
                     [ayuda.linea_producto(producto, cant=3, price='10.00'), ayuda.linea_gasto(price='4.00', codigo='0')])

    def eliminar(self, empresa, compra, usuario):
        with company_context(empresa):
            compras.eliminar_compra(compra, usuario)

    def test_revierte_stock_borra_la_cuenta_sin_pagos_y_audita(self, empresa, admin, compra, producto):
        assert ayuda.en(empresa, lambda: Product.objects.get(pk=producto.pk).stock) == 103
        self.eliminar(empresa, compra, admin)
        with company_context(empresa):
            assert Product.objects.get(pk=producto.pk).stock == 100
            assert not Purchase.objects.exists() and not PurchaseDetail.objects.exists() and not DebtsPay.objects.exists()
        registro = AuditLog.objects.get(action='purchase_delete', company=empresa)
        assert registro.detail == {'compra': compra.pk, 'numero': '001-002-000000321', 'total': '38.50', 'origen': 'manual',
                                   'usuario': admin.pk}

    def test_con_pagos_retencion_liquidacion_o_ajustes_no_se_borra(self, empresa, admin, compra):
        with company_context(empresa):
            pago = cuentas_por_pagar.registrar_pago(DebtsPay.objects.get(purchase=compra).pk, admin, fecha=hoy(), valor='5.00',
                                                    medio_pago='efectivo')
        with pytest.raises(compras.ErrorCompra, match='Tiene pagos registrados'):
            self.eliminar(empresa, compra, admin)
        with company_context(empresa):
            pago.delete()
            receipt, _ = Receipt.objects.get_or_create(voucher_type='07', establishment_code='001', issuing_point_code='001',
                                                       defaults={'sequence': 0})
            retencion = Retencion.objects.create(
                company=empresa, receipt=receipt, voucher_number='000000001', voucher_number_full='001-001-000000001',
                employee=admin, environment_type=1, purchase=compra, provider=compra.provider, tipo_identificacion='04',
                identificacion=RUC, razon_social='X', num_doc_sustento='001002000000321', fecha_doc_sustento=hoy(),
                aut_doc_sustento='1' * 49)
        with pytest.raises(compras.ErrorCompra, match='retención'):
            self.eliminar(empresa, compra, admin)
        with company_context(empresa):
            retencion.delete()
            receipt, _ = Receipt.objects.get_or_create(voucher_type='03', establishment_code='001', issuing_point_code='001',
                                                       defaults={'sequence': 0})
            liquidacion = LiquidacionCompra.objects.create(
                company=empresa, receipt=receipt, voucher_number='000000001', voucher_number_full='001-001-000000001',
                employee=admin, environment_type=1, purchase=compra, provider=compra.provider, tipo_identificacion='05',
                identificacion='0912345675', razon_social='X')
        with pytest.raises(compras.ErrorCompra, match='liquidación'):
            self.eliminar(empresa, compra, admin)
        with company_context(empresa):
            liquidacion.delete()
            assert Purchase.objects.filter(pk=compra.pk).exists() and DebtsPay.objects.filter(purchase=compra).exists()

    def test_devuelve_el_documento_importado_a_pendiente(self, empresa, admin, compra, proveedor):
        with company_context(empresa):
            documento = DocumentoImportado.objects.create(
                importado_por=admin, origen='xml', clave_acceso=fabricas_sri.clave(secuencial='000000321'), cod_doc='01',
                ambiente=2, estab='001', pto_emi='002', secuencial='000000321', numero='001-002-000000321', emisor_ruc=RUC,
                clasificacion='recibido', estado_revision='vinculado', estado_contable='propuesta',
                propuesta_contable={'lineas': []}, compra=compra, proveedor=proveedor)
        self.eliminar(empresa, compra, admin)
        with company_context(empresa):
            documento.refresh_from_db()
            assert (documento.estado_revision, documento.compra_id, documento.estado_contable, documento.propuesta_contable) == (
                'pendiente', None, 'sin_propuesta', None)
            assert EventoImportacion.objects.filter(documento=documento, tipo='compra_eliminada').count() == 1


class TestValoresQueFallanCerrados:

    def test_alta_por_orm_queda_anterior_e_incompleta(self, empresa, proveedor):
        with company_context(empresa):
            compra = Purchase.objects.create(provider=proveedor)
            assert (compra.version_datos, compra.datos_incompletos, compra.origen, compra.total) == (1, True, 'manual', None)
            assert compra.faltantes()[0] == ('importes', 'Faltan los importes de la factura (bases, IVA y total)')
            assert compras.actualizar_marca(compra) is True
            deuda = DebtsPay.objects.create(purchase=compra, debt=Decimal('10.00'), saldo=Decimal('10.00'))
            assert deuda.base_calculo == 'subtotal' and deuda.abonos() == []

    @pytest.mark.parametrize('cambios', [{'datos_incompletos': False}, {'version_datos': 2}])
    def test_la_base_impide_marcar_completa_una_compra_sin_totales(self, empresa, proveedor, cambios):
        with company_context(empresa):
            compra = Purchase.objects.create(provider=proveedor)
            with pytest.raises(IntegrityError), transaction.atomic():
                Purchase.objects.filter(pk=compra.pk).update(**cambios)


class TestJson:

    def test_importes_como_texto_y_texto_sin_interpretar(self, empresa, admin):
        proveedor = ayuda.crear_proveedor(empresa, tipo='04', nombre=XSS)
        compra = crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(XSS, price='10.00')])
        with company_context(empresa):
            item = recargar(empresa, compra).toJSON(detalle=True)
            linea = compra.purchasedetail_set.get().toJSON()
        assert item['total'] == '11.50' and item['base_gravada'] == '10.00' and item['base_5'] == '0.00'
        assert item['tipo_comprobante'] == {'id': '01', 'name': 'Factura'} and item['signo'] == 1 and item['doc_modificado'] is None
        assert item['fecha_emision'] == (hoy() - timedelta(days=2)).isoformat() and item['clase'] == 'gasto'
        assert item['faltantes'] == [] and item['datos_incompletos'] is False and item['subtotal'] == 10.0
        assert item['provider']['name'] == XSS and linea['descripcion'] == XSS and linea['tipo'] == 'gasto'
        assert XSS in json.dumps(item, ensure_ascii=False) and linea['product'] is None and linea['total_iva'] == '1.50'

    def test_compra_anterior_en_json(self, empresa, proveedor, producto):
        antigua = ayuda.compra_antigua(empresa, proveedor, '30.00', producto=producto, cantidad=3)
        with company_context(empresa):
            item = recargar(empresa, antigua).toJSON(detalle=True)
            linea = antigua.purchasedetail_set.get().toJSON()
        assert item['version_datos'] == 1 and item['datos_incompletos'] is True and item['total'] is None
        assert item['total_iva'] is None and item['numero_comprobante'] == antigua.number and item['clase'] == 'inventario'
        assert item['faltantes'][0]['codigo'] == 'importes'
        assert linea['codigo_porcentaje'] == '' and linea['nombre_tarifa'] == '—' and linea['total'] is None


# ---------------------------------------------------------------- pantallas (paso 2: §4 y §6.A–§6.B)

def entrar(client, empresa, rol=None, usuario=None):
    from core.tenancy.models import ROLE_OWNER
    usuario = usuario or helpers.crear_usuario(f'usuario.compras.{rol or "dueno"}'.lower().replace(' ', '.'), empresa,
                                               rol or ROLE_OWNER)
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    return usuario


def post_json(client, url, datos):
    respuesta = client.post(url, datos)
    return respuesta.status_code, json.loads(respuesta.content)


def formulario(datos, lineas, accion='add', **extra):
    return {**{k: v for k, v in datos.items() if v is not None}, 'action': accion, 'lineas': json.dumps(lineas), **extra}


class TestPantallaNuevaCompra:
    URL = '/pos/purchase/add/'

    def test_formulario_sin_valores_de_oficio(self, client, empresa, admin):
        entrar(client, empresa, usuario=admin)
        respuesta = client.get(self.URL)
        assert respuesta.status_code == 200
        form = respuesta.context['form']
        assert type(form).__name__ == 'CompraForm' and respuesta.context['tipo_inicial'] == 'inventario'
        assert form['forma_pago'].value() in (None, '') and form['cod_sustento'].value() in (None, '')
        assert form['parte_relacionada'].value() in (None, '') and form['modo_comprobante'].value() == 'si'
        opciones = respuesta.context['opciones']
        assert [t['codigo'] for t in opciones['tarifas']] == ['4', '5', '0', '6', '7', '2', '8']
        assert next(t for t in opciones['tarifas'] if t['codigo'] == '8')['tarifa_variable'] is True
        contenido = respuesta.content.decode()
        assert 'id="fp-compra-opciones"' in contenido and 'validate_purchase' not in contenido
        assert '03' not in [c[0] for c in form.fields['tipo_comprobante'].choices]

    def test_calcular_y_registrar_por_la_vista(self, client, empresa, admin, proveedor, producto):
        entrar(client, empresa, usuario=admin)
        datos = ayuda.datos_compra(proveedor, secuencial='77', payment_type='credito',
                                   end_credit=(hoy() + timedelta(days=30)).isoformat())
        lineas = [ayuda.linea_producto(producto, cant=2, price='10.00'), ayuda.linea_gasto('Flete', price='5.00', codigo='0')]
        estado, resumen = post_json(client, self.URL, formulario(datos, lineas, 'calcular'))
        assert estado == 200 and 'error' not in resumen, resumen
        assert (resumen['base_gravada'], resumen['base_0'], resumen['total_iva'], resumen['total']) == (
            '20.00', '5.00', '3.00', '28.00')
        assert [g['nombre'] for g in resumen['por_tarifa']] == ['15 %', '0 %'] and resumen['faltantes'] == []
        assert ayuda.en(empresa, Purchase.objects.count) == 0
        estado, data = post_json(client, self.URL, formulario(datos, lineas))
        assert estado == 200 and 'error' not in data, data
        with company_context(empresa):
            compra = Purchase.objects.get(pk=data['id'])
            assert (compra.version_datos, compra.datos_incompletos, compra.total) == (2, False, Decimal('28.00'))
            assert DebtsPay.objects.get(purchase=compra).base_calculo == 'total'
            assert Product.objects.get(pk=producto.pk).stock == 102

    def test_confirmacion_pendiente_devuelve_su_codigo(self, client, empresa, admin, proveedor):
        entrar(client, empresa, usuario=admin)
        datos = ayuda.datos_compra(proveedor, iva_factura='14.00')
        lineas = [ayuda.linea_gasto(price='100.00')]
        estado, data = post_json(client, self.URL, formulario(datos, lineas))
        assert estado == 200 and data['confirmacion'] == 'confirmar_iva' and '$1.00' in data['error']
        estado, data = post_json(client, self.URL, formulario(datos, lineas, confirmar_iva='on'))
        assert 'error' not in data and ayuda.en(empresa, lambda: Purchase.objects.get(pk=data['id']).total_iva) == Decimal('14.00')

    def test_errores_de_formato_y_de_negocio(self, client, empresa, admin, proveedor):
        entrar(client, empresa, usuario=admin)
        _, data = post_json(client, self.URL, formulario(ayuda.datos_compra(proveedor, fecha_emision='2026-13-45'), []))
        assert data['error'].startswith('Fecha de emisión del comprobante:')
        _, data = post_json(client, self.URL, {**formulario(ayuda.datos_compra(proveedor), []), 'lineas': '{x'})
        assert data['error'] == 'Las líneas de la compra no tienen un formato válido.'
        _, data = post_json(client, self.URL, formulario(ayuda.datos_compra(proveedor, forma_pago=''), [ayuda.linea_gasto()]))
        assert data['error'] == 'Elige la forma de pago del comprobante (ATS).'

    def test_validar_comprobante_y_xml_importado(self, client, empresa, admin, proveedor):
        entrar(client, empresa, usuario=admin)
        compra = crear(empresa, admin, ayuda.datos_compra(proveedor, secuencial='55'), [ayuda.linea_gasto()])
        consulta = {'action': 'validate_comprobante', 'provider': proveedor.pk, 'tipo_comprobante': '01', 'estab': '001',
                    'pto_emi': '002', 'secuencial': '55'}
        _, data = post_json(client, self.URL, consulta)
        assert (data['valid'], data['compra_id'], data['documento_importado']) == (False, compra.pk, None)
        with company_context(empresa):
            documento = DocumentoImportado.objects.create(
                importado_por=admin, origen='xml', clave_acceso=fabricas_sri.clave(secuencial='000000056'), cod_doc='01',
                ambiente=2, estab='001', pto_emi='002', secuencial='000000056', numero='001-002-000000056', emisor_ruc=RUC,
                clasificacion='recibido')
        _, data = post_json(client, self.URL, {**consulta, 'secuencial': '56'})
        assert data['valid'] is True and data['documento_importado'] == {
            'id': documento.pk, 'url': f'/importacion/documentos/{documento.pk}/',
            'url_compra': f'/importacion/documentos/{documento.pk}/compra/'}
        _, data = post_json(client, self.URL, {**consulta, 'secuencial': '57'})
        assert data == {'valid': True, 'compra_id': None, 'mensaje': '', 'documento_importado': None}

    def test_busquedas_de_tipo_de_gasto_y_compra_modificada(self, client, empresa, admin, proveedor):
        entrar(client, empresa, usuario=admin)
        tipo = ayuda.crear_tipo_gasto(empresa, 'SERVICIOS BÁSICOS', cod_sustento='02')
        factura = crear(empresa, admin, ayuda.datos_compra(proveedor, secuencial='90'), [ayuda.linea_gasto()])
        _, data = post_json(client, self.URL, {'action': 'search_type_expense', 'term': 'servicios'})
        assert data == [{'id': tipo.pk, 'text': 'SERVICIOS BÁSICOS', 'cod_sustento': '02'}]
        _, data = post_json(client, self.URL, {'action': 'search_compra_modificada', 'provider': proveedor.pk, 'term': '90'})
        assert [d['id'] for d in data] == [factura.pk] and '001-002-000000090' in data[0]['text']
        otro = ayuda.crear_proveedor(empresa, tipo='04')
        _, data = post_json(client, self.URL, {'action': 'search_compra_modificada', 'provider': otro.pk, 'term': ''})
        assert data == []

    @pytest.mark.parametrize('rol', ['Vendedor', 'Consulta', 'Contador'])
    def test_sin_permiso_de_registrar(self, client, empresa, proveedor, rol):
        from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_READONLY, ROLE_SELLER
        rol = {'Vendedor': ROLE_SELLER, 'Consulta': ROLE_READONLY, 'Contador': ROLE_ACCOUNTANT}[rol]
        entrar(client, empresa, rol=rol)
        estado, data = post_json(client, self.URL, formulario(ayuda.datos_compra(proveedor), [ayuda.linea_gasto()]))
        assert estado == 403 and 'error' in data
        assert client.get(self.URL).status_code == 302
        assert ayuda.en(empresa, Purchase.objects.count) == 0


class TestPantallaListado:
    URL = '/pos/purchase/'

    @pytest.fixture
    def escenario(self, empresa, admin, proveedor, producto):
        factura = crear(empresa, admin, ayuda.datos_compra(proveedor, secuencial='10', payment_type='credito',
                                                           end_credit=(hoy() + timedelta(days=30)).isoformat()),
                        [ayuda.linea_gasto(price='100.00', codigo='0')])
        nota = crear(empresa, admin, ayuda.datos_compra(
            proveedor, secuencial='11', tipo_comprobante='04', tipo_doc_modificado='01', num_doc_modificado='001002000000010',
            aut_doc_modificado='1234567890', fecha_doc_modificado=factura.fecha_emision.isoformat(), compra_modificada=factura.pk),
            [ayuda.linea_gasto(price='20.00', codigo='0')])
        antigua = ayuda.compra_antigua(empresa, proveedor, '30.00', producto=producto, cantidad=3)
        despues = crear(empresa, admin, ayuda.datos_compra(proveedor, modo_comprobante='despues', tipo_comprobante='',
                                                           secuencial='', autorizacion='', fecha_emision='', forma_pago=''),
                        [ayuda.linea_gasto(price='7.00', codigo='0')])
        return factura, nota, antigua, despues

    def buscar(self, client, **filtros):
        _, data = post_json(client, self.URL, {'action': 'search', 'start_date': '', 'end_date': '', **filtros})
        return data

    def test_filtros_por_fecha_de_emision_e_incompletas(self, client, empresa, admin, escenario):
        factura, nota, antigua, despues = escenario
        entrar(client, empresa, usuario=admin)
        assert sorted(c['id'] for c in self.buscar(client)) == sorted(c.pk for c in escenario)
        assert sorted(c['id'] for c in self.buscar(client, fecha='emision')) == sorted([factura.pk, nota.pk])
        assert sorted(c['id'] for c in self.buscar(client, incompletas='1')) == sorted([antigua.pk, despues.pk])
        hace_diez = (hoy() - timedelta(days=10)).isoformat()
        assert [c['id'] for c in self.buscar(client, start_date=hace_diez, end_date=hace_diez)] == [antigua.pk]
        fila = next(c for c in self.buscar(client) if c['id'] == antigua.pk)
        assert (fila['version_datos'], fila['datos_incompletos'], fila['total']) == (1, True, None)
        assert 'faltantes' not in fila

    def test_totales_las_notas_restan_y_las_incompletas_aparte(self, client, empresa, admin, escenario):
        entrar(client, empresa, usuario=admin)
        _, data = post_json(client, self.URL, {'action': 'totales', 'start_date': '', 'end_date': ''})
        assert data == {'completas': {'cantidad': 2, 'total': '80.00'}, 'incompletas': {'cantidad': 2, 'subtotal': '37.00'}}

    def test_detalle_de_una_compra(self, client, empresa, admin, escenario):
        factura, nota, antigua, despues = escenario
        entrar(client, empresa, usuario=admin)
        _, data = post_json(client, self.URL, {'action': 'detalle', 'id': factura.pk})
        assert data['compra']['faltantes'] == [] and data['compra']['clase'] == 'gasto'
        assert data['cuenta_por_pagar']['base_calculo']['id'] == 'total' and data['cuenta_por_pagar']['saldo'] == '80.00'
        assert data['cuenta_por_pagar']['abonos'][0]['tipo'] == 'nota_credito' and data['cuenta_por_pagar']['abonos'][0]['valor'] == '20.00'
        assert data['por_tarifa'] == [{'codigo': '0', 'nombre': '0 %', 'tarifa': '0.00', 'base': '100.00', 'valor': '0.00'}]
        assert (data['retencion'], data['liquidacion'], data['documento_importado']) == (None, None, None)
        _, data = post_json(client, self.URL, {'action': 'detalle', 'id': antigua.pk})
        assert data['compra']['faltantes'][0]['codigo'] == 'importes' and data['cuenta_por_pagar'] is None
        assert data['por_tarifa'][0]['valor'] is None and data['lineas'][0]['total'] is None
        _, data = post_json(client, self.URL, {'action': 'detalle', 'id': 999999})
        assert data == {'error': 'La compra no existe.'}

    def test_contexto_por_permisos_y_texto_sin_interpretar(self, client, empresa, admin):
        from core.tenancy.models import ROLE_ACCOUNTANT
        proveedor = ayuda.crear_proveedor(empresa, tipo='04', nombre=XSS)
        crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(XSS, price='10.00')])
        entrar(client, empresa, usuario=admin)
        contexto = client.get(self.URL).context
        assert (contexto['puede_crear'], contexto['puede_completar'], contexto['puede_eliminar']) == (True, True, True)
        assert contexto['url_gasto'] == '/pos/purchase/add/?tipo=gasto'
        respuesta = client.post(self.URL, {'action': 'search', 'start_date': '', 'end_date': ''})
        assert json.loads(respuesta.content)[0]['provider']['name'] == XSS
        client.logout()
        entrar(client, empresa, rol=ROLE_ACCOUNTANT)
        contexto = client.get(self.URL).context
        assert (contexto['puede_crear'], contexto['puede_completar'], contexto['puede_eliminar']) == (False, False, False)


class TestPantallaEliminar:

    def test_eliminar_por_la_vista_audita_y_rechaza_con_pagos(self, client, empresa, admin, proveedor, producto):
        credito = {'payment_type': 'credito', 'end_credit': (hoy() + timedelta(days=30)).isoformat()}
        compra = crear(empresa, admin, ayuda.datos_compra(proveedor, secuencial='31', **credito),
                       [ayuda.linea_producto(producto, cant=2)])
        con_pago = crear(empresa, admin, ayuda.datos_compra(proveedor, secuencial='32', **credito), [ayuda.linea_gasto()])
        with company_context(empresa):
            cuentas_por_pagar.registrar_pago(DebtsPay.objects.get(purchase=con_pago).pk, admin, fecha=hoy(), valor='1.00',
                                             medio_pago='efectivo')
        entrar(client, empresa, usuario=admin)
        _, data = post_json(client, f'/pos/purchase/delete/{con_pago.pk}/', {})
        assert data == {'error': 'Tiene pagos registrados: elimínalos primero en Cuentas por pagar.'}
        _, data = post_json(client, f'/pos/purchase/delete/{compra.pk}/', {})
        assert data == {}
        with company_context(empresa):
            assert not Purchase.objects.filter(pk=compra.pk).exists() and Product.objects.get(pk=producto.pk).stock == 100
        registro = AuditLog.objects.get(action='purchase_delete', company=empresa)
        assert registro.detail['compra'] == compra.pk and registro.user_id == admin.pk
