"""Compras anteriores a la Etapa 2 (version_datos=1): quedan marcadas sin recalcular (D8), se completan a mano con
auditoría y sin tocar líneas, stock, subtotal ni la cuenta por pagar salvo decisión explícita (ajustar_cxp), y la orden
compras_incompletas solo completa desde un XML vinculado y verificado, con decisión escrita. Datos ficticios."""
import csv
import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth.models import Group
from django.core.management import CommandError, call_command
from django.db.models import Sum
from django.utils import timezone

from core.comprobantes.models import Retencion
from core.importacion.models import DocumentoImportado, ImpuestoImportado
from core.pos import compras, cuentas_por_pagar
from core.pos.models import DebtsPay, Product, Purchase, PurchaseDetail, Receipt
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog
from tests import ayuda_compras as ayuda, fabricas_sri

pytestmark = pytest.mark.django_db
RUC = '0990000001001'
IMPORTES = {'base_0': '20.00', 'base_gravada': '80.00', 'base_5': '0', 'base_no_objeto': '0', 'base_exenta': '0',
            'total_descuento': '0', 'total_iva': '12.00', 'total_ice': '0', 'propina': '0'}


def hoy():
    return timezone.localdate()


@pytest.fixture
def proveedor(empresa):
    return ayuda.crear_proveedor(empresa, tipo='04', ruc=RUC)


@pytest.fixture
def producto(empresa):
    return ayuda.crear_producto(empresa, codigo='ANT-1')


@pytest.fixture
def antigua(empresa, proveedor, producto):
    """Compra a crédito de $100 sin IVA registrado (antes de la Etapa 2), con 4 unidades que ya subieron el stock a 104."""
    ayuda.en(empresa, lambda: Product.objects.filter(pk=producto.pk).update(stock=104))
    return ayuda.compra_antigua(empresa, proveedor, '100.00', credito=True, producto=producto, cantidad=4,
                                fecha=hoy() - timedelta(days=20))


def cabecera(**cambios):
    datos = {'tipo_comprobante': '01', 'cod_sustento': '06', 'estab': '001', 'pto_emi': '002', 'secuencial': '271',
             'autorizacion': '1234567890', 'fecha_emision': (hoy() - timedelta(days=21)).isoformat(), 'forma_pago': '20',
             'parte_relacionada': 'no', 'pago_loc_ext': '01'}
    datos.update(cambios)
    return datos


def completar(empresa, compra, usuario, datos, **kwargs):
    with company_context(empresa):
        return compras.completar_datos(compra, usuario, datos, **kwargs)


def foto(empresa, compra):
    """Lo que completar_datos nunca cambia: líneas, stock, subtotal y la cuenta por pagar."""
    with company_context(empresa):
        compra = Purchase.objects.get(pk=compra.pk)
        deuda = DebtsPay.objects.filter(purchase=compra).values_list('debt', 'saldo', 'base_calculo').first()
        return (str(compra.subtotal), list(PurchaseDetail.objects.filter(purchase=compra).values_list('cant', 'price', 'subtotal')),
                list(Product.objects.values_list('code', 'stock')), deuda, compra.date_joined, compra.provider_id)


class TestMarcadas:

    def test_quedan_como_estaban_e_incompletas(self, empresa, antigua, producto):
        with company_context(empresa):
            compra = Purchase.objects.select_related('provider').get(pk=antigua.pk)
            item = compra.toJSON()
            detalle = compra.toJSON(detalle=True)
        assert (item['version_datos'], item['datos_incompletos'], item['total'], item['total_iva'], item['subtotal']) == (
            1, True, None, None, 100.0)
        assert 'faltantes' not in item and detalle['faltantes'][0]['codigo'] == 'importes'
        assert ayuda.en(empresa, lambda: Product.objects.get(pk=producto.pk).stock) == 104

    def test_solo_propietario_y_administrador_completan(self):
        con_permiso = set(Group.objects.filter(permissions__codename='change_purchase').values_list('name', flat=True))
        assert {ROLE_OWNER, ROLE_ADMIN} <= con_permiso
        assert not con_permiso & {ROLE_ACCOUNTANT, ROLE_READONLY, ROLE_SELLER}
        assert Group.objects.filter(name=ROLE_ACCOUNTANT, permissions__codename='view_purchase').exists()


class TestCompletarAMano:

    def test_cabecera_e_importes_sin_tocar_lineas_stock_ni_cuenta(self, empresa, admin, antigua):
        antes = foto(empresa, antigua)
        revision = ayuda.en(empresa, compras.revisar_datos, antigua, {**cabecera(), **IMPORTES})
        assert revision['total'] == '112.00' and revision['confirmaciones'] == [] and revision['faltantes'] == []
        assert {'campo': 'base_gravada', 'etiqueta': 'Base gravada', 'antes': None, 'despues': '80.00'} in revision['cambios']
        compra = completar(empresa, antigua, admin, {**cabecera(), **IMPORTES})
        assert not compra.datos_incompletos and compra.total == Decimal('112.00') and compra.version_datos == 1
        assert compra.numero_comprobante == '001-002-000000271' and compra.completada_por_id == admin.pk
        assert foto(empresa, antigua) == antes
        registro = AuditLog.objects.get(action='purchase_complete', company=empresa)
        assert registro.detail['compra'] == antigua.pk and registro.detail['origen'] == 'formulario'
        assert registro.detail['version_datos'] == 1 and 'decision' not in registro.detail
        assert registro.detail['cambios']['total'] == [None, '112.00']
        assert registro.detail['cambios']['fecha_emision'] == [None, (hoy() - timedelta(days=21)).isoformat()]
        assert registro.detail['cambios']['parte_relacionada'] == [None, False]

    def test_por_partes_y_todos_los_importes_o_ninguno(self, empresa, admin, antigua):
        compra = completar(empresa, antigua, admin, {'cod_sustento': '06', 'parte_relacionada': 'no'})
        assert compra.datos_incompletos and compra.cod_sustento == '06' and compra.total is None
        with pytest.raises(compras.ErrorCompra, match='Escribe todos los importes'):
            completar(empresa, antigua, admin, {'base_0': '100.00'})
        with pytest.raises(compras.ErrorCompra, match='El sustento 10 no admite'):
            completar(empresa, antigua, admin, cabecera(cod_sustento='10'))

    def test_diferencia_con_el_subtotal_e_iva_exigen_confirmar(self, empresa, admin, antigua):
        distintos = {**IMPORTES, 'base_0': '30.00'}            # la factura suma 110,00 y la compra registró 100,00
        with pytest.raises(compras.ErrorCompra) as e:
            completar(empresa, antigua, admin, {**cabecera(), **distintos})
        assert e.value.codigo == 'confirmar_diferencia' and '$110.00' in str(e.value) and '$100.00' in str(e.value)
        iva_raro = {**IMPORTES, 'total_iva': '9.00'}           # 80 × 15 % = 12,00
        with pytest.raises(compras.ErrorCompra) as e:
            completar(empresa, antigua, admin, {**cabecera(), **iva_raro})
        assert e.value.codigo == 'confirmar_iva'
        assert ayuda.en(empresa, lambda: Purchase.objects.get(pk=antigua.pk).total) is None
        compra = completar(empresa, antigua, admin, {**cabecera(), **distintos, 'confirmar_diferencia': '1'})
        assert compra.total == Decimal('122.00') and compra.subtotal == Decimal('100.00')

    def test_ajustar_la_cuenta_por_pagar_solo_con_la_casilla(self, empresa, admin, antigua):
        completar(empresa, antigua, admin, {**cabecera(), **IMPORTES})
        assert foto(empresa, antigua)[3] == (Decimal('100.00'), Decimal('100.00'), 'subtotal')
        with company_context(empresa):
            deuda = DebtsPay.objects.get(purchase=antigua)
            cuentas_por_pagar.registrar_pago(deuda.pk, admin, fecha=hoy(), valor='30.00', medio_pago='efectivo')
        completar(empresa, antigua, admin, {'ajustar_cxp': '1'})
        assert foto(empresa, antigua)[3] == (Decimal('112.00'), Decimal('82.00'), 'total')
        registro = AuditLog.objects.get(action='purchase_debt_adjust', company=empresa)
        assert registro.detail == {'compra': antigua.pk, 'deuda_antes': '100.00', 'deuda_despues': '112.00',
                                   'saldo_antes': '70.00', 'saldo_despues': '82.00', 'usuario': admin.pk}
        with pytest.raises(compras.ErrorCompra, match='calculada sin IVA'):
            completar(empresa, antigua, admin, {'ajustar_cxp': '1'})

    def test_no_se_ajusta_si_los_pagos_superan_el_total(self, empresa, admin, antigua):
        with company_context(empresa):
            deuda = DebtsPay.objects.get(purchase=antigua)
            cuentas_por_pagar.registrar_pago(deuda.pk, admin, fecha=hoy(), valor='100.00', medio_pago='efectivo')
        sin_iva = {**IMPORTES, 'base_0': '20.00', 'base_gravada': '0', 'total_iva': '0', 'base_exenta': '70.00'}
        with pytest.raises(compras.ErrorCompra, match=r'Los pagos registrados \(\$100.00\) superan el total con IVA \(\$90.00\)'):
            completar(empresa, antigua, admin, {**cabecera(), **sin_iva, 'confirmar_diferencia': '1', 'ajustar_cxp': 'si'})
        assert foto(empresa, antigua)[3] == (Decimal('100.00'), Decimal('0.00'), 'subtotal')
        assert ayuda.en(empresa, lambda: Purchase.objects.get(pk=antigua.pk).total) is None   # todo o nada

    def test_compra_nueva_no_cambia_sus_importes(self, empresa, admin, proveedor):
        with company_context(empresa):
            nueva = compras.crear_compra(empresa, admin, ayuda.datos_compra(proveedor), [ayuda.linea_gasto(price='50.00')])
        compra = completar(empresa, nueva, admin, {'base_0': '999.00', 'total_iva': '1.00', 'cod_sustento': '01'})
        assert (compra.total, compra.base_0, compra.cod_sustento) == (Decimal('57.50'), Decimal('0.00'), '01')

    def test_numeracion_bloqueada_por_la_retencion_o_el_xml(self, empresa, admin, proveedor, antigua):
        completar(empresa, antigua, admin, cabecera(autorizacion=''))
        with company_context(empresa):
            receipt, _ = Receipt.objects.get_or_create(voucher_type='07', establishment_code='001', issuing_point_code='001',
                                                       defaults={'sequence': 0})
            Retencion.objects.create(company=empresa, receipt=receipt, voucher_number='000000009', voucher_number_full='001-001-000000009',
                                     employee=admin, environment_type=2, purchase=antigua, provider=proveedor,
                                     tipo_identificacion='04', identificacion=RUC, razon_social='X',
                                     num_doc_sustento='001002000000271', fecha_doc_sustento=hoy(), aut_doc_sustento='1' * 10)
        with pytest.raises(compras.ErrorCompra, match='La retención 001-001-000000009 usa este número: anúlala antes de cambiarlo'):
            completar(empresa, antigua, admin, cabecera(secuencial='272'))
        compra = completar(empresa, antigua, admin, cabecera(secuencial='', autorizacion='1234567890'))   # se llena lo vacío
        assert (compra.secuencial, compra.autorizacion) == ('000000271', '1234567890')
        with company_context(empresa):
            desde_xml = compras.crear_compra(empresa, admin, ayuda.datos_compra(proveedor, secuencial='900'), [ayuda.linea_gasto()],
                                             origen='importacion')
        compra = completar(empresa, desde_xml, admin, {'secuencial': '901', 'fecha_emision': hoy().isoformat(), 'cod_sustento': '01'})
        assert (compra.secuencial, compra.cod_sustento) == ('000000900', '01')     # lo del XML se ignora; lo demás sí cambia

    def test_unicidad_al_completar(self, empresa, admin, proveedor, antigua):
        with company_context(empresa):
            otra = compras.crear_compra(empresa, admin, ayuda.datos_compra(proveedor, secuencial='271'), [ayuda.linea_gasto()])
        with pytest.raises(compras.ErrorCompra, match=f'compra #{otra.pk}'):
            completar(empresa, antigua, admin, cabecera())


class TestReporte:

    def test_nota_de_credito_resta_con_subtotal_con_signo(self, empresa, admin, proveedor):
        with company_context(empresa):
            factura = compras.crear_compra(empresa, admin, ayuda.datos_compra(proveedor, secuencial='10'),
                                           [ayuda.linea_gasto(price='100.00', codigo='0')])
            compras.crear_compra(empresa, admin, ayuda.datos_compra(
                proveedor, secuencial='11', tipo_comprobante='04', tipo_doc_modificado='01', num_doc_modificado='001002000000010',
                aut_doc_modificado='1234567890', fecha_doc_modificado=factura.fecha_emision.isoformat(), compra_modificada=factura.pk),
                [ayuda.linea_gasto(price='20.00', codigo='0')])
            assert Purchase.objects.aggregate(s=Sum('subtotal'))['s'] == Decimal('120.00')
            assert Purchase.objects.aggregate(s=Sum(compras.subtotal_con_signo()))['s'] == Decimal('80.00')
            assert Purchase.objects.aggregate(s=Sum(compras.total_con_signo()))['s'] == Decimal('80.00')


class TestOrdenComprasIncompletas:
    """Dos compras anteriores con su factura importada, vinculada y verificada: una cuadra (± 0,02) y otra no."""

    @pytest.fixture
    def escenario(self, empresa, admin, proveedor, antigua):
        fecha = hoy() - timedelta(days=21)
        otra = ayuda.compra_antigua(empresa, proveedor, '50.00', fecha=hoy() - timedelta(days=20))
        sin_xml = ayuda.compra_antigua(empresa, proveedor, '10.00')
        documentos = []
        with company_context(empresa):
            for compra, secuencial, base_15, base_0 in ((antigua, '000000271', '80.01', '20.00'), (otra, '000000272', '40.00', '15.00')):
                base_15, base_0 = Decimal(base_15), Decimal(base_0)
                iva = (base_15 * Decimal('0.15')).quantize(Decimal('0.01'))
                documento = DocumentoImportado.objects.create(
                    importado_por=admin, origen='xml', clave_acceso=fabricas_sri.clave(fecha=fecha, secuencial=secuencial, ruc=RUC),
                    cod_doc='01', ambiente=2, estab='001', pto_emi='002', secuencial=secuencial, numero=f'001-002-{secuencial}',
                    fecha_emision=fecha, emisor_ruc=RUC, total_sin_impuestos=base_15 + base_0, total_iva=iva,
                    importe_total=base_15 + base_0 + iva, estado_verificacion='verificada_sri', clasificacion='recibido',
                    estado_revision='vinculado', compra=compra, proveedor=proveedor,
                    datos={'comprobante': {'pagos': [{'forma_pago': '01', 'total': '1.00'}, {'forma_pago': '20', 'total': '99.00'}]}})
                for codigo, base, valor in (('4', base_15, iva), ('0', base_0, Decimal('0'))):
                    ImpuestoImportado.objects.create(documento=documento, codigo='2', codigo_porcentaje=codigo, impuesto='IVA',
                                                     categoria='iva', base_imponible=base, valor=valor)
                documentos.append(documento)
        return {'cuadra': antigua, 'no_cuadra': otra, 'sin_xml': sin_xml, 'documentos': documentos, 'fecha': fecha}

    def estado(self, empresa):
        with company_context(empresa):
            return sorted(Purchase.objects.values_list('pk', 'total', 'secuencial', 'datos_incompletos', 'subtotal'))

    def test_ensayo_no_escribe_y_muestra_la_diferencia(self, empresa, escenario, tmp_path):
        antes, auditorias = self.estado(empresa), AuditLog.objects.count()
        salida = StringIO()
        call_command('compras_incompletas', '--empresa', str(empresa.pk), '--desde-xml', '--csv', str(tmp_path / 'c.csv'),
                     stdout=salida)
        assert self.estado(empresa) == antes and AuditLog.objects.count() == auditorias
        filas = {int(f['compra']): f for f in csv.DictReader(open(tmp_path / 'c.csv', encoding='utf-8'))}
        assert filas[escenario['cuadra'].pk]['diferencia'] == '0.01' and filas[escenario['cuadra'].pk]['accion'] == 'se completaría'
        assert filas[escenario['no_cuadra'].pk]['diferencia'] == '5.00'
        assert filas[escenario['no_cuadra'].pk]['accion'] == 'no se aplica: difiere más de 0,02'
        assert filas[escenario['sin_xml'].pk]['accion'] == 'sin XML vinculado y verificado'
        assert 'importes' in filas[escenario['sin_xml'].pk]['faltantes'] and 'ensayo: no se cambió nada' in salida.getvalue()

    @pytest.mark.parametrize('argumentos, mensaje', [
        (['--todas', '--aplicar', '--desde-xml', '--csv', 'x.csv'], '--decision'),
        (['--todas', '--aplicar', '--decision', 'Autoriza la propietaria el 28/10', '--csv', 'x.csv'], '--desde-xml'),
        (['--aplicar', '--desde-xml', '--decision', 'Autoriza la propietaria el 28/10', '--csv', 'x.csv'], '--empresa'),
    ])
    def test_aplicar_exige_decision_xml_y_empresa(self, empresa, escenario, argumentos, mensaje):
        antes = self.estado(empresa)
        with pytest.raises(CommandError, match=mensaje):
            call_command('compras_incompletas', *argumentos, stdout=StringIO())
        assert self.estado(empresa) == antes

    def test_aplicar_completa_solo_la_que_cuadra_sin_tocar_la_cuenta(self, empresa, escenario, tmp_path):
        informe = tmp_path / 'compras.csv'
        decision = 'Autoriza la propietaria (prueba ficticia) el 28/10/2026'
        cuadra, no_cuadra = escenario['cuadra'], escenario['no_cuadra']
        antes_cuadra, antes_no = foto(empresa, cuadra), foto(empresa, no_cuadra)
        call_command('compras_incompletas', '--empresa', str(empresa.pk), '--desde-xml', '--aplicar', '--decision', decision,
                     '--csv', str(informe), stdout=StringIO())
        with company_context(empresa):
            completada = Purchase.objects.get(pk=cuadra.pk)
            intacta = Purchase.objects.get(pk=no_cuadra.pk)
        assert (completada.base_gravada, completada.base_0, completada.total_iva, completada.total) == (
            Decimal('80.01'), Decimal('20.00'), Decimal('12.00'), Decimal('112.01'))
        assert (completada.tipo_comprobante, completada.secuencial, completada.fecha_emision, completada.forma_pago) == (
            '01', '000000271', escenario['fecha'], '20')
        assert completada.autorizacion == escenario['documentos'][0].clave_acceso and completada.pago_loc_ext == '01'
        # Sustento y parte relacionada no vienen en el XML: la compra sigue incompleta por eso (nada se elige de oficio).
        assert completada.datos_incompletos and completada.parte_relacionada is None
        assert [c for c, _ in ayuda.en(empresa, compras.faltantes, completada)] == ['cod_sustento', 'parte_relacionada']
        assert foto(empresa, cuadra) == antes_cuadra            # líneas, stock, subtotal y cuenta por pagar intactos
        assert intacta.total is None and foto(empresa, no_cuadra) == antes_no
        registro = AuditLog.objects.get(action='purchase_complete', company=empresa)
        assert registro.detail['origen'] == 'orden' and registro.detail['decision'] == decision
        assert registro.detail['informe'] == str(informe) and registro.detail['compra'] == cuadra.pk
        assert not AuditLog.objects.filter(action='purchase_debt_adjust').exists()
        acciones = {int(f['compra']): f['accion'] for f in csv.DictReader(open(informe, encoding='utf-8'))}
        assert acciones[cuadra.pk] == 'actualizada; sigue incompleta: cod_sustento, parte_relacionada'
        assert acciones[no_cuadra.pk] == 'no se aplica: difiere más de 0,02'

    def test_dato_registrado_distinto_del_xml_es_conflicto(self, empresa, admin, escenario, tmp_path):
        completar(empresa, escenario['cuadra'], admin, {'estab': '003'})
        call_command('compras_incompletas', '--empresa', str(empresa.pk), '--desde-xml', '--aplicar', '--decision',
                     'Autoriza la propietaria el 28/10/2026', '--csv', str(tmp_path / 'c.csv'), stdout=StringIO())
        acciones = {int(f['compra']): f['accion'] for f in csv.DictReader(open(tmp_path / 'c.csv', encoding='utf-8'))}
        assert acciones[escenario['cuadra'].pk] == 'conflicto: difiere del XML estab'
        assert ayuda.en(empresa, lambda: Purchase.objects.get(pk=escenario['cuadra'].pk).total) is None


# ---------------------------------------------------------------- pantallas (paso 2: §6.C y §6.I)

def entrar(client, empresa, rol=ROLE_OWNER, usuario=None):
    from tests import helpers
    usuario = usuario or helpers.crear_usuario(f'usuario.antiguas.{rol}'.lower(), empresa, rol)
    helpers.iniciar_sesion(client, usuario, empresa=empresa)
    return usuario


class TestPantallaCompletar:

    def url(self, compra):
        return f'/pos/purchase/complete/{compra.pk}/'

    def test_revisar_muestra_los_cambios_y_completar_guarda_auditado(self, client, empresa, admin, antigua):
        antes = foto(empresa, antigua)
        entrar(client, empresa, usuario=admin)
        respuesta = client.get(self.url(antigua))
        assert respuesta.status_code == 200
        form = respuesta.context['form']
        assert 'base_gravada' in form.fields and 'ajustar_cxp' in form.fields and respuesta.context['bloqueados'] == []
        assert respuesta.context['faltantes'][0]['codigo'] == 'importes' and respuesta.context['puede_ajustar_cxp'] is True
        assert respuesta.context['cuenta_por_pagar']['base_calculo']['id'] == 'subtotal'
        contenido = respuesta.content.decode()
        assert 'Las líneas, el stock y el subtotal registrado no cambian.' in contenido
        assert 'Cambia la deuda de $100.00 (sin IVA)' in contenido
        datos = {**cabecera(), **IMPORTES}
        respuesta = client.post(self.url(antigua), {**datos, 'action': 'revisar'})
        resumen = respuesta.context['resumen']
        assert respuesta.status_code == 200 and resumen['total'] == '112.00' and resumen['faltantes'] == []
        assert {'campo': 'base_gravada', 'etiqueta': 'Base gravada', 'antes': None, 'despues': '80.00'} in resumen['cambios']
        assert ayuda.en(empresa, lambda: Purchase.objects.get(pk=antigua.pk).total) is None
        respuesta = client.post(self.url(antigua), {**datos, 'action': 'completar'})
        assert respuesta.status_code == 302 and respuesta['Location'] == '/pos/purchase/'
        with company_context(empresa):
            compra = Purchase.objects.get(pk=antigua.pk)
            assert not compra.datos_incompletos and compra.total == Decimal('112.00')
        assert foto(empresa, antigua) == antes
        registro = AuditLog.objects.get(action='purchase_complete', company=empresa)
        assert registro.user_id == admin.pk and registro.detail['cambios']['total'] == [None, '112.00']

    def test_confirmaciones_y_ajuste_de_la_cuenta(self, client, empresa, admin, antigua):
        entrar(client, empresa, usuario=admin)
        distintos = {**cabecera(), **IMPORTES, 'base_0': '30.00'}      # 110,00 sin impuestos frente a 100,00 registrados
        respuesta = client.post(self.url(antigua), {**distintos, 'action': 'completar'})
        assert respuesta.status_code == 200
        assert any('$110.00' in e for e in respuesta.context['form'].non_field_errors())
        assert respuesta.context['confirmaciones_visibles'] == ['confirmar_diferencia']
        respuesta = client.post(self.url(antigua), {**distintos, 'action': 'revisar'})
        assert respuesta.context['resumen']['confirmaciones'] == ['confirmar_diferencia']
        assert '$110.00' in respuesta.context['textos_confirmacion']['confirmar_diferencia']
        respuesta = client.post(self.url(antigua), {**distintos, 'confirmar_diferencia': 'on', 'ajustar_cxp': 'on',
                                                    'action': 'completar'})
        assert respuesta.status_code == 302
        with company_context(empresa):
            deuda = DebtsPay.objects.get(purchase=antigua)
            assert (deuda.debt, deuda.saldo, deuda.base_calculo) == (Decimal('122.00'), Decimal('122.00'), 'total')
        registro = AuditLog.objects.get(action='purchase_debt_adjust', company=empresa)
        assert (registro.detail['deuda_antes'], registro.detail['deuda_despues']) == ('100.00', '122.00')

    def test_compra_nueva_sin_importes_y_numeracion_del_xml_bloqueada(self, client, empresa, admin, proveedor):
        with company_context(empresa):
            compra = compras.crear_compra(empresa, admin, ayuda.datos_compra(proveedor, secuencial='400', cod_sustento='02'),
                                          [ayuda.linea_gasto(price='10.00')], origen='importacion')
        entrar(client, empresa, usuario=admin)
        respuesta = client.get(self.url(compra))
        form = respuesta.context['form']
        assert 'base_gravada' not in form.fields and 'ajustar_cxp' not in form.fields
        assert respuesta.context['bloqueados'] == list(compras.CAMPOS_NUMERACION)
        assert form.fields['secuencial'].disabled and not form.fields['cod_sustento'].disabled
        assert 'vienen del XML autorizado' in respuesta.content.decode()
        datos = {**cabecera(secuencial='999', cod_sustento='06'), 'action': 'completar'}
        respuesta = client.post(self.url(compra), datos)
        assert respuesta.status_code == 302
        with company_context(empresa):
            compra.refresh_from_db()
            assert (compra.secuencial, compra.cod_sustento) == ('000000400', '06')

    @pytest.mark.parametrize('rol, permitido', [(ROLE_ADMIN, True), (ROLE_ACCOUNTANT, False), (ROLE_READONLY, False),
                                                (ROLE_SELLER, False)])
    def test_solo_propietario_y_administrador_entran(self, client, empresa, antigua, rol, permitido):
        entrar(client, empresa, rol=rol)
        respuesta = client.get(self.url(antigua))
        assert respuesta.status_code == (200 if permitido else 302)
        if not permitido:
            respuesta = client.post(self.url(antigua), {**cabecera(), 'action': 'completar'})
            assert respuesta.status_code == 403
            assert ayuda.en(empresa, lambda: Purchase.objects.get(pk=antigua.pk).cod_sustento) == ''

    def test_compra_de_otra_empresa_no_existe(self, client, empresa, admin, empresa_b):
        ajena = ayuda.compra_antigua(empresa_b, ayuda.crear_proveedor(empresa_b), '10.00')
        entrar(client, empresa, usuario=admin)
        assert client.get(self.url(ajena)).status_code == 404
