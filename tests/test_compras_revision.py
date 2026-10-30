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


# ------------------------------------------------------------------ O1-F1 / O1-T1 y O1-F2: completar datos y líneas guardadas

class TestCompletarRespetaLineasYPago:

    def test_factura_a_credito_con_producto_no_pasa_a_nota_de_credito(self, empresa, admin, proveedor):
        producto = ayuda.crear_producto(empresa, stock=0)
        factura = crear(empresa, admin, a_credito(proveedor), [ayuda.linea_producto(producto, cant=2, price='50.00')])
        otra = crear(empresa, admin, a_credito(proveedor), [ayuda.linea_gasto(price='100.00')])
        error = error_al_completar(empresa, admin, factura, nota_sobre(otra, forma_pago=''))
        assert 'líneas de gasto' in str(error)
        assert recargar(empresa, factura).tipo_comprobante == '01'
        assert ayuda.en(empresa, Product.objects.get, pk=producto.pk).stock == 2
        assert saldos(empresa, otra) == [(Decimal('115.00'), Decimal('115.00'))]

    def test_factura_a_credito_sin_producto_no_pasa_a_nota_de_credito(self, empresa, admin, proveedor):
        factura = crear(empresa, admin, a_credito(proveedor), [ayuda.linea_gasto(price='30.00')])
        otra = crear(empresa, admin, a_credito(proveedor), [ayuda.linea_gasto(price='100.00')])
        assert 'cuenta por pagar propia' in str(error_al_completar(empresa, admin, factura, nota_sobre(otra, forma_pago='')))
        assert saldos(empresa, otra) == [(Decimal('115.00'), Decimal('115.00'))]

    def test_factura_con_producto_no_pasa_a_nota_de_debito(self, empresa, admin, proveedor):
        producto = ayuda.crear_producto(empresa, stock=0)
        factura = crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_producto(producto)])
        otra = crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_gasto()])
        assert 'líneas de gasto' in str(error_al_completar(empresa, admin, factura, nota_sobre(otra, tipo_comprobante='05')))

    def test_factura_con_iva_no_pasa_a_nota_de_venta(self, empresa, admin, proveedor):
        factura = crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(price='100.00')])
        error = error_al_completar(empresa, admin, factura, {'tipo_comprobante': '02', 'cod_sustento': '02'})
        assert 'no discrimina IVA' in str(error)
        assert recargar(empresa, factura).tipo_comprobante == '01'
        # con líneas al 0 % sí se corrige el tipo
        sin_iva = crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(price='100.00', codigo='0')])
        completar(empresa, admin, sin_iva, {'tipo_comprobante': '02', 'cod_sustento': '02'})
        assert recargar(empresa, sin_iva).tipo_comprobante == '02'

    def test_compra_anterior_con_iva_no_pasa_a_nota_de_venta(self, empresa, admin, proveedor):
        antigua = ayuda.compra_antigua(empresa, proveedor, '100.00')
        importes = {'base_0': '0', 'base_gravada': '100.00', 'base_5': '0', 'base_no_objeto': '0', 'base_exenta': '0',
                    'total_descuento': '0', 'total_iva': '15.00', 'total_ice': '0', 'propina': '0'}
        assert 'no discrimina IVA' in str(error_al_completar(empresa, admin, antigua, {'tipo_comprobante': '02', **importes}))

    def test_tipo_de_la_compra_importada_no_cambia(self, empresa, admin, proveedor):
        compra = crear(empresa, admin, ayuda.datos_compra(proveedor, cod_sustento='02'), [ayuda.linea_gasto(price='10.00', codigo='0')],
                       origen='importacion')
        assert 'tipo_comprobante' in ayuda.en(empresa, compras.bloqueos_de, recargar(empresa, compra))[0]
        completar(empresa, admin, compra, {'tipo_comprobante': '02'})
        assert recargar(empresa, compra).tipo_comprobante == '01'

    def test_tipo_con_retencion_vigente_no_cambia(self, empresa, admin, proveedor):
        factura = crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(price='10.00', codigo='0')])
        with company_context(empresa):
            Retencion.objects.create(
                company=empresa, receipt=receipt(empresa, '07'), voucher_number='000000001', voucher_number_full='001-001-000000001',
                employee=admin, environment_type=2, purchase=factura, provider=proveedor, tipo_identificacion='04',
                identificacion=RUC, razon_social='X', num_doc_sustento='001002000000101', fecha_doc_sustento=hoy(),
                aut_doc_sustento='1234567890', status='authorized')
        error = error_al_completar(empresa, admin, factura, {'tipo_comprobante': '02', 'cod_sustento': '02'})
        assert error.codigo == 'bloqueado' and recargar(empresa, factura).tipo_comprobante == '01'

    def test_tipo_con_liquidacion_vigente_no_cambia(self, empresa, admin, proveedor):
        despues = crear(empresa, admin, {'provider': proveedor.pk, 'modo_comprobante': 'despues', 'date_joined': hoy().isoformat(),
                                         'payment_type': 'efectivo'}, [ayuda.linea_gasto(price='50.00', codigo='0')])
        liquidacion_autorizada(empresa, admin, despues, total_sin_impuestos=Decimal('50.00'), importe_total=Decimal('50.00'))
        error = error_al_completar(empresa, admin, despues, {'tipo_comprobante': '01', 'cod_sustento': '06'})
        assert error.codigo == 'bloqueado' and recargar(empresa, despues).tipo_comprobante == ''

    def test_fecha_anterior_al_15_con_lineas_al_15_se_rechaza(self, empresa, admin, proveedor):
        compra = crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(price='100.00')])
        error = error_al_completar(empresa, admin, compra, {'fecha_emision': '2024-03-15', 'confirmar_plazo_ats': '1'})
        assert '15 %' in str(error) and recargar(empresa, compra).fecha_emision != date(2024, 3, 15)

    def test_despues_con_12_avisa_y_no_se_completa_con_fecha_de_2026(self, empresa, admin, proveedor):
        datos = {'provider': proveedor.pk, 'modo_comprobante': 'despues', 'date_joined': hoy().isoformat(), 'payment_type': 'efectivo'}
        compra = crear(empresa, admin, datos, [ayuda.linea_gasto(price='100.00', codigo='2')])
        assert 'tarifa_12_sin_fecha' in [c for c, _ in compra.advertencias]
        cabecera = {k: v for k, v in ayuda.datos_compra(proveedor).items()
                    if k not in ('provider', 'modo_comprobante', 'date_joined', 'payment_type', 'end_credit')}
        assert '12 %' in str(error_al_completar(empresa, admin, compra, cabecera))
        assert recargar(empresa, compra).datos_incompletos

    def test_despues_con_descuento_pasa_a_03_solo_sin_el(self, empresa, admin, productora):
        datos = {'provider': productora.pk, 'modo_comprobante': 'despues', 'date_joined': hoy().isoformat(), 'payment_type': 'efectivo'}
        compra = crear(empresa, admin, datos, [ayuda.linea_gasto(price='100.00', descuento='10.00', codigo='0')])
        assert 'no admite descuentos' in str(error_al_completar(empresa, admin, compra, {'tipo_comprobante': '03'}))


# ------------------------------------------------------------------ O1-F3 / O1-T2: saldos de las compras que modifica la nota

class TestCompletarNotaRecalculaCuentas:

    def test_cambiar_la_compra_modificada_recalcula_las_dos(self, empresa, admin, proveedor):
        f1 = crear(empresa, admin, a_credito(proveedor), [ayuda.linea_gasto(price='100.00', codigo='0')])
        f2 = crear(empresa, admin, a_credito(proveedor), [ayuda.linea_gasto(price='100.00', codigo='0')])
        nota = crear(empresa, admin, ayuda.datos_compra(proveedor, **nota_sobre(f1)), [ayuda.linea_gasto('Devolución', price='20.00',
                                                                                                         codigo='0')])
        assert saldos(empresa, f1, f2) == [(Decimal('80.00'),) * 2, (Decimal('100.00'),) * 2]
        completar(empresa, admin, nota, {'num_doc_modificado': f'{f2.estab}{f2.pto_emi}{f2.secuencial}', 'compra_modificada': f2.pk})
        assert saldos(empresa, f1, f2) == [(Decimal('100.00'),) * 2, (Decimal('80.00'),) * 2]

    def test_nota_corregida_a_factura_devuelve_el_saldo(self, empresa, admin, proveedor):
        f1 = crear(empresa, admin, a_credito(proveedor), [ayuda.linea_gasto(price='100.00', codigo='0')])
        nota = crear(empresa, admin, ayuda.datos_compra(proveedor, **nota_sobre(f1)), [ayuda.linea_gasto('Devolución', price='20.00',
                                                                                                         codigo='0')])
        completar(empresa, admin, nota, {'tipo_comprobante': '01', 'forma_pago': '20'})
        assert recargar(empresa, nota).compra_modificada_id is None
        assert saldos(empresa, f1) == [(Decimal('100.00'),) * 2]


# ------------------------------------------------------------------ O1-F4: la marca sigue a los datos del proveedor

class TestMarcaSigueAlProveedor:

    def datos(self, proveedor, **cambios):
        datos = {'action': 'edit', 'name': proveedor.name, 'tipo_identificacion': proveedor.tipo_identificacion,
                 'ruc': proveedor.ruc, 'tipo_sujeto': proveedor.tipo_sujeto, 'parte_relacionada': 'no',
                 'mobile': proveedor.mobile, 'email': proveedor.email, 'address': proveedor.address}
        datos.update(cambios)
        return datos

    def test_editar_el_proveedor_recalcula_sus_compras(self, client, empresa, admin, proveedor):
        compra = crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(price='100.00')])
        completada = recargar(empresa, compra).completada_en
        assert completada is not None and not recargar(empresa, compra).datos_incompletos
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        url = f'/pos/provider/update/{proveedor.pk}/'
        data = json.loads(client.post(url, self.datos(proveedor, tipo_identificacion='05', ruc=ayuda.cedula(4321),
                                                      tipo_sujeto='01')).content)
        assert 'error' not in data, data
        compra = recargar(empresa, compra)
        assert compra.datos_incompletos and 'tipo_id_no_admitido' in codigos(empresa, compra)
        with company_context(empresa):
            assert compras.totales_listado(Purchase.objects.all())['completas']['cantidad'] == 0
        data = json.loads(client.post(url, self.datos(ayuda.en(empresa, Provider.objects.get, pk=proveedor.pk),
                                                      tipo_identificacion='04', ruc=RUC, tipo_sujeto='02')).content)
        assert 'error' not in data, data
        compra = recargar(empresa, compra)
        assert not compra.datos_incompletos and compra.completada_en == completada

    def test_orden_que_llena_el_proveedor_recalcula_sus_compras(self, empresa, admin, proveedor, tmp_path):
        compra = crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(price='100.00')])
        with company_context(empresa):      # proveedor como antes de la Etapa 2
            Provider.objects.filter(pk=proveedor.pk).update(tipo_identificacion='', tipo_sujeto='')
            compras.actualizar_marca(recargar(empresa, compra))
        assert recargar(empresa, compra).datos_incompletos
        call_command('proveedores_incompletos', '--empresa', str(empresa.pk), '--aplicar', '--decision',
                     'Prueba: lo autorizó la propietaria', '--csv', str(tmp_path / 'p.csv'), stdout=StringIO())
        assert ayuda.en(empresa, Provider.objects.get, pk=proveedor.pk).tipo_identificacion == '04'
        assert not recargar(empresa, compra).datos_incompletos


# ------------------------------------------------------------------ O1-F8, O1-F10, O1-F11 y O1-F12

def test_precio_o_descuento_con_mas_de_dos_decimales_se_rechaza(empresa, admin, proveedor):
    """O1-F8: antes 0,125 × 1000 se guardaba como 0,13 × 1000 = 130,00."""
    with company_context(empresa):
        with pytest.raises(compras.ErrorCompra, match='Precio: admite hasta 2 decimales'):
            compras.calcular(empresa, ayuda.datos_compra(proveedor), [ayuda.linea_gasto('Tornillos', price='0.125', cant=1000)])
        with pytest.raises(compras.ErrorCompra, match='Descuento: admite hasta 2 decimales'):
            compras.calcular(empresa, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(price='10.00', descuento='1.005')])
        resultado = compras.calcular(empresa, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(price='0.130', cant=1000)])
    assert resultado['lineas'][0]['subtotal'] == '130.00'


def test_ice_sin_iva_de_la_factura_avisa(empresa, admin, proveedor):
    """O1-F10 (provisional hasta la decisión D7): el IVA de las compras manuales con ICE se calcula sin el ICE."""
    with company_context(empresa):
        sin_iva = compras.calcular(empresa, ayuda.datos_compra(proveedor, total_ice='10.00'), [ayuda.linea_gasto(price='100.00')])
        con_iva = compras.calcular(empresa, ayuda.datos_compra(proveedor, total_ice='10.00', iva_factura='16.50',
                                                                 confirmar_iva='1'), [ayuda.linea_gasto(price='100.00')])
    assert 'ice_sin_iva_factura' in [a['codigo'] for a in sin_iva['advertencias']]
    assert 'ice_sin_iva_factura' not in [a['codigo'] for a in con_iva['advertencias']]


def test_sustento_con_tarifa_que_la_retencion_no_ofrece(empresa, admin, proveedor):
    """O1-F11: una tarifa única del 8 % no se precarga (el formulario de retención solo ofrece 15, 5 y 0)."""
    compra = crear(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(price='100.00', codigo='8', tarifa='8.00')])
    with company_context(empresa):
        iniciales, avisos = compras.datos_sustento_retencion(recargar(empresa, compra))
    assert [a['codigo'] for a in avisos] == ['sustento_tarifa_no_disponible']
    assert not {'base_0', 'base_iva', 'tarifa_iva', 'valor_iva'} & set(iniciales)


def test_admite_retencion_segun_el_tipo(empresa, admin, proveedor):
    """O1-F12: la regla TIPOS_SIN_RETENCION tiene una función de servidor para RetencionCrearView."""
    assert compras.admite_retencion(Purchase(tipo_comprobante='01')) and compras.admite_retencion(Purchase(tipo_comprobante=''))
    assert not compras.admite_retencion(Purchase(tipo_comprobante='04'))


# ------------------------------------------------------------------ O1-T5: id de otra empresa = 404

def test_eliminar_compra_o_cuenta_de_otra_empresa_responde_404(client, empresa, admin, empresa_b):
    dueno_b = helpers.crear_usuario('propietario.b.revision', empresa_b, ROLE_OWNER)
    ajena = crear(empresa_b, dueno_b, a_credito(ayuda.crear_proveedor(empresa_b, tipo='04')), [ayuda.linea_gasto()])
    deuda = ayuda.en(empresa_b, DebtsPay.objects.get, purchase=ajena)
    helpers.iniciar_sesion(client, admin, empresa=empresa)
    respuesta = client.post(f'/pos/purchase/delete/{ajena.pk}/')
    assert (respuesta.status_code, json.loads(respuesta.content)) == (404, {'error': 'La compra no existe.'})
    respuesta = client.post(f'/pos/debts/pay/delete/{deuda.pk}/')
    assert (respuesta.status_code, json.loads(respuesta.content)) == (404, {'error': 'La cuenta por pagar no existe.'})
    assert ayuda.en(empresa_b, Purchase.objects.filter(pk=ajena.pk).exists)
    assert ayuda.en(empresa_b, DebtsPay.objects.filter(pk=deuda.pk).exists)


# ------------------------------------------------------------------ O1-T6: el informe CSV no ejecuta fórmulas

def test_informe_csv_neutraliza_formulas(tmp_path):
    ruta = tmp_path / 'informe.csv'
    informe = _ensayo.Informe(str(ruta), ['nombre', 'diferencia'])
    for nombre in ('=HYPERLINK("http://ejemplo.invalid","x")', '+SUMA(1)', '@A1', '-2+3', 'PROVEEDOR S.A.'):
        informe.agregar({'nombre': nombre, 'diferencia': '-0.01'})
    informe.cerrar()
    filas = list(csv.DictReader(ruta.open(encoding='utf-8')))
    assert [f['nombre'] for f in filas] == ["'=HYPERLINK(\"http://ejemplo.invalid\",\"x\")", "'+SUMA(1)", "'@A1", "'-2+3",
                                            'PROVEEDOR S.A.']
    assert {f['diferencia'] for f in filas} == {'-0.01'}
    assert informe.filas[0]['nombre'].startswith('=')        # en pantalla se muestra tal cual


# ------------------------------------------------------------------ O1-F6 y O1-F9: compra desde el XML

class TestCompraDesdeXml:

    @pytest.fixture
    def receptora(self):
        from tests import fabricas_recibidos as r
        empresa = helpers.crear_empresa('RECEPTORA REVISIÓN', ruc=r.RUC_RECEPTOR)
        dueno = helpers.crear_usuario('dueno.receptora.revision', empresa, ROLE_OWNER)
        proveedor = ayuda.crear_proveedor(empresa, tipo='04', ruc=r.RUC_EMISOR, nombre='PROVEEDOR FICTICIO S.A.')
        return empresa, dueno, proveedor

    def documento(self, empresa, dueno, **fabrica):
        from core.importacion import servicios as sv
        from core.importacion.models import DocumentoImportado
        from tests import fabricas_recibidos as r
        with company_context(empresa):
            documento = sv.crear_lote(empresa, dueno, [('doc.xml', r.autorizacion(r.factura(**fabrica)).encode())]).documentos.get()
            DocumentoImportado.objects.filter(pk=documento.pk).update(estado_verificacion='verificada_sri')
            return DocumentoImportado.objects.get(pk=documento.pk)

    def test_compra_anterior_con_el_mismo_numero_exige_confirmar(self, receptora):
        from core.importacion import compras as desde_xml, servicios as sv
        empresa, dueno, proveedor = receptora
        documento = self.documento(empresa, dueno)
        antigua = ayuda.compra_antigua(empresa, proveedor, documento.total_sin_impuestos, fecha=documento.fecha_emision)
        with company_context(empresa):
            Purchase.objects.filter(pk=antigua.pk).update(number=documento.secuencial.lstrip('0').zfill(8))
            propuesta = desde_xml.propuesta_compra(documento)
            assert 'posible_duplicado' in [a['codigo'] for a in propuesta['advertencias']]
            assert 'confirmar_no_duplicada' in propuesta['confirmaciones'] and propuesta['bloqueos'] == []
            datos = {'cod_sustento': '06', 'parte_relacionada': 'no'}
            with pytest.raises(sv.ErrorImportacion) as e:
                desde_xml.crear_compra_desde_documento(documento, dueno, datos)
            assert e.value.codigo == 'confirmar_no_duplicada' and f'#{antigua.pk}' in str(e.value)
            assert Purchase.objects.count() == 1
            compra = desde_xml.crear_compra_desde_documento(documento, dueno, {**datos, 'confirmar_no_duplicada': True})
            assert compra.pk != antigua.pk and Purchase.objects.count() == 2

    def test_nueva_compra_avisa_la_compra_anterior_con_el_mismo_numero(self, client, empresa, admin, proveedor):
        antigua = ayuda.compra_antigua(empresa, proveedor, '120.00')
        with company_context(empresa):
            Purchase.objects.filter(pk=antigua.pk).update(number='00000271')
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        data = json.loads(client.post('/pos/purchase/add/', {'action': 'validate_comprobante', 'provider': proveedor.pk,
                                                             'tipo_comprobante': '01', 'estab': '001', 'pto_emi': '002',
                                                             'secuencial': '271'}).content)
        assert data['valid'] is True and data['posible_duplicado'] == [antigua.pk] and 'mismo número' in data['mensaje']

    def test_plazo_del_xml_desde_la_fecha_de_registro(self, receptora):
        from core.importacion import compras as desde_xml
        empresa, dueno, _ = receptora
        documento = self.documento(empresa, dueno, plazo=30)
        registro = hoy() - timedelta(days=10)
        with company_context(empresa):
            compra = desde_xml.crear_compra_desde_documento(documento, dueno, {'cod_sustento': '06', 'parte_relacionada': 'no',
                                                                               'date_joined': registro.isoformat()})
        assert (compra.payment_type, compra.date_joined, compra.end_credit) == ('credito', registro, registro + timedelta(days=30))
