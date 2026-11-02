"""Libros mensuales (core/tributario): ventas, compras, retenciones efectuadas y recibidas del mes.

Solo comprobantes autorizados en producción y por fecha de emisión; lo de pruebas y lo no autorizado se cuenta aparte; lo
anulado en el SRI se lista y no suma; las notas de crédito restan. Totales contrastados al centavo con los documentos,
enlace a cada documento, exportaciones XLSX/CSV sin fórmulas y registradas con su huella, permisos, plan y aislamiento."""
import csv
import hashlib
import io
import json
from datetime import timedelta
from decimal import Decimal

import openpyxl
import pytest
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone

from core.comprobantes import notas_debito as snd, retenciones as sret, retenciones_recibidas as rr
from core.comprobantes.models import CodigoRetencion, NotaDebito, Retencion
from core.configuracion import servicios as cfg
from core.pos import compras, notas_credito
from core.pos.models import CreditNote, Purchase, Sale
from core.security.models import Module
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER
from core.tributario import exportar, libros as lb
from core.tributario.models import ExportacionLibro
from tests import ayuda_compras, helpers
from tests.ayudas_ventas import factura_autorizada, retencion_datos
from tests.test_emision_sri import empresa, p12  # noqa: F401 - empresa firmada y configurada en producción

pytestmark = pytest.mark.django_db
MES = (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)   # el mes pasado: fechas fijas y no futuras
DIA = MES.replace(day=10)
CERO = Decimal('0.00')


def leer(empresa, funcion):
    with company_context(empresa):
        return funcion()


def autorizar(doc, fecha=DIA, ambiente=2):
    with company_context(doc.company):
        type(doc).objects.filter(pk=doc.pk).update(status='authorized', environment_type=ambiente, emission_date=fecha,
                                                   access_code='1' * 49)
        return type(doc).objects.get(pk=doc.pk)


@pytest.fixture
def produccion(empresa):
    """Empresa con firma de prueba y facturación confirmada en producción (001-002), de test_emision_sri."""
    return empresa


@pytest.fixture
def cliente(produccion):
    return helpers.crear_cliente('cliente.libros', produccion, '0912345678', '0990000001')


@pytest.fixture
def con_iva(produccion):
    return helpers.crear_producto(produccion, 'LIB15', pvp='10.00', con_iva=True)


@pytest.fixture
def sin_iva(produccion):
    return helpers.crear_producto(produccion, 'LIB0', pvp='4.00', con_iva=False)


@pytest.fixture
def ventas(produccion, cliente, admin, con_iva, sin_iva):
    """Facturas del mes (15 % y 0 %), una anulada en el SRI, una de pruebas, una devuelta y una del mes anterior; una NC de
    la primera y una ND (15 %) sobre la segunda."""
    gravada = factura_autorizada(produccion, cliente, admin, con_iva, cantidad=2, fecha=DIA)
    cero = factura_autorizada(produccion, cliente, admin, sin_iva, cantidad=3, fecha=DIA + timedelta(days=1))
    anulada = factura_autorizada(produccion, cliente, admin, con_iva, cantidad=1, fecha=DIA)
    with company_context(produccion):
        Sale.objects.filter(pk=anulada.pk).update(anulado_sri_fecha=DIA + timedelta(days=2), anulado_sri_motivo='Error')
    pruebas = factura_autorizada(produccion, cliente, admin, con_iva, cantidad=1, fecha=DIA, ambiente=1)
    devuelta = factura_autorizada(produccion, cliente, admin, con_iva, cantidad=1, fecha=DIA, estado='returned')
    anterior = factura_autorizada(produccion, cliente, admin, con_iva, cantidad=1, fecha=MES - timedelta(days=3))
    with company_context(produccion):
        with transaction.atomic():
            nota = notas_credito.crear(produccion, gravada.pk, None, 'Devolución de prueba')
        cfg.configurar_otro_documento(produccion, '05', 'otro_sistema', '001-002-000000003', True)
        with transaction.atomic():
            debito = snd.crear(produccion, admin, cero, {'tarifa_iva': '15.00'}, [('Interés por mora', '10.00')])
    return {'gravada': gravada, 'cero': cero, 'anulada': anulada, 'pruebas': pruebas, 'devuelta': devuelta, 'anterior': anterior,
            'nota': autorizar(nota, DIA + timedelta(days=3)), 'debito': autorizar(debito, DIA + timedelta(days=4))}


@pytest.fixture
def proveedor(produccion):
    return ayuda_compras.crear_proveedor(produccion)


@pytest.fixture
def compras_del_mes(produccion, admin, proveedor):
    tipo = ayuda_compras.crear_tipo_gasto(produccion, 'SERVICIOS')
    with company_context(produccion):
        completa = compras.crear_compra(produccion, admin, ayuda_compras.datos_compra(proveedor, fecha_emision=DIA.isoformat(),
                                                                                        date_joined=DIA.isoformat()),
                                        [ayuda_compras.linea_gasto('Mantenimiento', price='100.00', type_expense=tipo)])
    antigua = ayuda_compras.compra_antigua(produccion, proveedor, '50.00', fecha=DIA)      # sin tarifa (Etapa 1)
    with company_context(produccion):
        cfg.configurar_otro_documento(produccion, '07', 'otro_sistema', '001-002-000000040', True)
        datos = {'num_doc_sustento': completa.numero_comprobante, 'aut_doc_sustento': '1' * 49, 'base_0': '0',
                 'base_iva': '100.00', 'tarifa_iva': '15.00', 'cod_sustento': '01', 'forma_pago': '20', 'fecha_doc_sustento': DIA}
        codigo = CodigoRetencion.objects.filter(impuesto='1', codigo='312').first()
        with transaction.atomic():
            retencion = sret.crear(produccion, admin, completa, datos, [(codigo.pk, None, None)], huella_revisada=sret.SIN_REVISION)
    return {'completa': completa, 'antigua': antigua, 'retencion': autorizar(retencion, DIA + timedelta(days=1))}


# ---------------------------------------------------------------- libro de ventas

class TestVentas:

    def test_filas_estados_y_totales_contrastados(self, produccion, ventas):
        libro, totales, columnas = leer(produccion, lambda: lb.construir('ventas', MES))
        filas = {(f['tipo'], f['id']): f for f in libro.filas}
        assert set(filas) == {('factura', ventas['gravada'].pk), ('factura', ventas['cero'].pk), ('factura', ventas['anulada'].pk),
                              ('nota_credito', ventas['nota'].pk), ('nota_debito', ventas['debito'].pk)}
        assert filas[('factura', ventas['anulada'].pk)]['cuenta'] is False and filas[('factura', ventas['anulada'].pk)]['estado'] == 'anulado'
        assert filas[('nota_credito', ventas['nota'].pk)]['signo'] == -1
        assert filas[('nota_credito', ventas['nota'].pk)]['documento_modificado'] == ventas['gravada'].voucher_number_full
        assert libro.excluidos == {'facturas': {'pruebas': 1, 'sin_autorizar': 1}}
        g, c, n, d = ventas['gravada'], ventas['cero'], ventas['nota'], ventas['debito']
        # al centavo: lo que suman los documentos que cuentan, con el signo de cada uno
        assert totales['total'] == Decimal(str(g.total)) + Decimal(str(c.total)) + d.valor_total - Decimal(str(n.total))
        assert totales['bases']['4'] == Decimal('20.00') + d.total_sin_impuestos - Decimal('20.00')   # la NC devuelve las 2 unidades
        assert totales['bases']['0'] == Decimal('12.00') and totales['ivas']['4'] == Decimal('3.00') + d.valor_iva - Decimal('3.00')
        assert (totales['documentos'], totales['cuentan'], totales['no_cuentan']) == (5, 4, 1)
        assert all(f['url'] for f in libro.filas) and filas[('factura', g.pk)]['url'] == f'/pos/sale/admin/print/a4/{g.pk}/'
        assert [c[0] for c in columnas][:3] == ['tipo_nombre', 'numero', 'fecha'] and 'base_4' in [c[0] for c in columnas]

    def test_otra_empresa_no_aparece(self, produccion, ventas, empresa_b, admin):
        helpers.configurar_facturacion(empresa_b, ambiente=2)
        otro = helpers.crear_cliente('cliente.b', empresa_b, '0912345679', '0990000002')
        factura_autorizada(empresa_b, otro, admin, helpers.crear_producto(empresa_b, 'B1'), fecha=DIA)
        libro, _, _ = leer(produccion, lambda: lb.construir('ventas', MES))
        assert len(libro.filas) == 5
        otro_libro, _, _ = leer(empresa_b, lambda: lb.construir('ventas', MES))
        assert len(otro_libro.filas) == 1


# ---------------------------------------------------------------- compras y retenciones

class TestComprasYRetenciones:

    def test_compras_por_tarifa_y_avisos(self, produccion, compras_del_mes):
        libro, totales, columnas = leer(produccion, lambda: lb.construir('compras', MES))
        filas = {f['id']: f for f in libro.filas}
        completa, antigua = compras_del_mes['completa'], compras_del_mes['antigua']
        assert set(filas) == {completa.pk, antigua.pk}
        assert filas[completa.pk]['bases'] == {'4': Decimal('100.00')} and filas[completa.pk]['ivas'] == {'4': Decimal('15.00')}
        assert filas[completa.pk]['retenciones'] == compras_del_mes['retencion'].voucher_number_full
        assert 'sin_tarifa' in filas[antigua.pk]['bases'] and filas[antigua.pk]['ivas'] == {}
        assert {a['codigo'] for a in libro.advertencias} == {'compras_incompletas', 'compras_sin_tarifa'}
        assert totales['bases']['4'] == Decimal('100.00') and totales['ivas']['4'] == Decimal('15.00')
        assert totales['total'] == leer(produccion, lambda: Purchase.objects.get(pk=completa.pk).total) + Decimal('50.00')
        assert 'base_sin_tarifa' in [c[0] for c in columnas]
        with company_context(produccion):
            Purchase.objects.filter(pk=antigua.pk).update(tipo_comprobante='04')   # nota de crédito del proveedor: resta
            _, totales_nc, _ = lb.construir('compras', MES)
        assert totales_nc['total'] == totales['total'] - Decimal('100.00')

    def test_retenciones_efectuadas_por_impuesto(self, produccion, compras_del_mes):
        libro, totales, _ = leer(produccion, lambda: lb.construir('retenciones_efectuadas', MES))
        retencion = compras_del_mes['retencion']
        detalles = leer(produccion, lambda: list(retencion.detalles.all()))
        assert [f['detalle_id'] for f in libro.filas] == [d.pk for d in detalles]
        assert totales['renta'] == sum((d.valor_retenido for d in detalles if d.impuesto == '1'), CERO)
        assert totales['total'] == totales['renta'] + totales['iva']
        with company_context(produccion):
            Retencion.objects.filter(pk=retencion.pk).update(anulado_sri_fecha=DIA + timedelta(days=5))
            libro_anulada, totales_anulada, _ = lb.construir('retenciones_efectuadas', MES)
        assert all(not f['cuenta'] for f in libro_anulada.filas) and totales_anulada['total'] == CERO

    def test_retenciones_recibidas(self, produccion, admin, con_iva):
        agente = helpers.crear_cliente('agente.ruc', produccion, '0991234567001', '0990000009')
        with company_context(produccion):
            type(agente).objects.filter(pk=agente.pk).update(identification_type='04')
        agente.identification_type = '04'
        factura = factura_autorizada(produccion, agente, admin, con_iva, cantidad=2, fecha=DIA)
        with company_context(produccion):
            registrada = rr.registrar(produccion, admin, factura, retencion_datos(fecha_emision=DIA))
            libro, totales, _ = lb.construir('retenciones_recibidas', MES)
        if registrada.ambiente != 2:      # el registro manual toma el ambiente de la venta
            pytest.fail(f'ambiente inesperado {registrada.ambiente}')
        assert [(f['impuesto'], f['codigo'], f['valor']) for f in libro.filas] == [('Renta', '312', Decimal('0.40')), ('IVA', '1', Decimal('0.90'))]
        assert (totales['renta'], totales['iva'], totales['total']) == (Decimal('0.40'), Decimal('0.90'), Decimal('1.30'))
        assert libro.filas[0]['url'] == f'/comprobantes/retenciones-recibidas/{registrada.pk}/'


# ---------------------------------------------------------------- exportación

class TestExportacion:

    def test_xlsx_sin_formulas_y_registro(self, client, produccion, admin, ventas, compras_del_mes):
        with company_context(produccion):
            ventas['cliente_peligroso'] = helpers.crear_cliente('=HYPERLINK("http://ejemplo")', produccion, '0912345680', '0990000003')
        factura_autorizada(produccion, ventas['cliente_peligroso'], admin, helpers.crear_producto(produccion, 'LIBX'), fecha=DIA)
        helpers.iniciar_sesion(client, admin, empresa=produccion)
        respuesta = client.get(f'/tributario/libros/exportar/?mes={MES:%Y-%m}&libro=todos&formato=xlsx')
        assert respuesta.status_code == 200 and 'libros-' in respuesta['Content-Disposition']
        contenido = respuesta.content
        libro = openpyxl.load_workbook(io.BytesIO(contenido))
        assert libro.sheetnames == ['Libro de ventas', 'Libro de compras', 'Retenciones efectuadas', 'Retenciones recibidas']
        hoja = libro['Libro de ventas']
        celdas = [c for fila in hoja.iter_rows() for c in fila if isinstance(c.value, str) and c.value.startswith('=')]
        assert celdas and all(c.data_type == 's' for c in celdas)                  # texto, nunca fórmula
        total = next(fila[1].value for fila in hoja.iter_rows() if fila[0].value == 'Total')
        assert Decimal(str(total)) == leer(produccion, lambda: lb.construir('ventas', MES)[1]['total'])
        registro = leer(produccion, lambda: ExportacionLibro.objects.get())
        assert (registro.libro, registro.formato, registro.mes, registro.generado_por) == ('todos', 'xlsx', MES, admin)
        assert registro.sha256 == hashlib.sha256(contenido).hexdigest()
        assert registro.filas == leer(produccion, lambda: sum(len(lb.construir(c, MES)[0].filas) for c in lb.LIBROS))

    def test_csv(self, client, produccion, admin, ventas):
        helpers.iniciar_sesion(client, admin, empresa=produccion)
        respuesta = client.get(f'/tributario/libros/exportar/?mes={MES:%Y-%m}&libro=ventas&formato=csv')
        texto = respuesta.content.decode('utf-8')
        assert texto.startswith('﻿') and respuesta['Content-Type'].startswith('text/csv')
        filas = list(csv.reader(io.StringIO(texto[1:]), delimiter=';'))
        assert filas[0][:3] == ['Tipo', 'Número', 'Fecha de emisión']
        numeros = [f[1] for f in filas[1:6]]
        assert ventas['gravada'].voucher_number_full in numeros and ventas['pruebas'].voucher_number_full not in numeros
        assert client.get(f'/tributario/libros/exportar/?mes={MES:%Y-%m}&libro=todos&formato=csv').status_code == 404
        assert client.get('/tributario/libros/exportar/?mes=2026-13&libro=ventas').status_code == 404

    def test_texto_seguro(self):
        assert exportar.texto_seguro('=1+1') == "'=1+1" and exportar.texto_seguro('-3') == "'-3" and exportar.texto_seguro('ACME') == 'ACME'


# ---------------------------------------------------------------- pantalla, API, permisos y plan

class TestPantalla:

    def test_pagina_y_api(self, client, produccion, admin, ventas):
        helpers.iniciar_sesion(client, admin, empresa=produccion)
        pagina = client.get(f'/tributario/libros/?mes={MES:%Y-%m}&libro=ventas')
        assert pagina.status_code == 200 and ventas['gravada'].voucher_number_full in pagina.content.decode()
        assert 'Fuera del libro (facturas): 1 en ambiente de pruebas y 1 sin autorizar en el SRI.' in pagina.content.decode()
        datos = client.get(f'/tributario/api/libros/compras/?mes={MES:%Y-%m}').json()
        assert datos['libro'] == 'compras' and datos['mes'] == f'{MES:%Y-%m}' and 'columnas' in datos
        api = client.get(f'/tributario/api/libros/ventas/?mes={MES:%Y-%m}').json()
        assert api['total_filas'] == 5 and api['totales']['documentos'] == 5
        assert api['filas'][0]['celdas'][0] == {'clave': 'tipo_nombre', 'valor': api['filas'][0]['tipo_nombre']}
        assert client.get('/tributario/api/libros/diario/').status_code == 404
        assert client.get('/tributario/libros/?mes=2999-01').context['mes_invalido'] is True   # mes futuro: el actual

    @pytest.mark.parametrize('rol, estado', [(ROLE_OWNER, 200), (ROLE_ADMIN, 200), (ROLE_ACCOUNTANT, 200), (ROLE_READONLY, 200),
                                             (ROLE_SELLER, 302), (ROLE_CLIENT, 302)])
    def test_permisos_por_rol(self, client, produccion, rol, estado):
        usuario = helpers.crear_usuario(f'libros.{rol.lower()}', produccion, rol)
        helpers.iniciar_sesion(client, usuario, empresa=produccion)
        assert client.get('/tributario/libros/').status_code == estado
        assert client.get(f'/tributario/libros/exportar/?mes={MES:%Y-%m}&libro=ventas&formato=csv').status_code == estado

    def test_plan_gratuito(self, client):
        gratuita = helpers.crear_empresa('GRATIS LIBROS', plan=None)
        dueno = helpers.crear_usuario('dueno.libros.gratis', gratuita, ROLE_OWNER)
        helpers.iniciar_sesion(client, dueno, empresa=gratuita)
        respuesta = client.get('/tributario/libros/')
        assert respuesta.status_code == 302 and '/suscripcion/' in respuesta['Location']


def test_modulo_del_menu_y_roles():
    modulo = Module.objects.get(url='/tributario/libros/')
    assert (modulo.name, modulo.module_type.name, modulo.orden) == ('Libros mensuales', 'Tributario', 1)
    assert set(modulo.permissions.values_list('codename', flat=True)) == {'view_libros'}

    def tiene(rol):
        grupo = Group.objects.get(name=rol)
        return grupo.groupmodule_set.filter(module=modulo).exists() and grupo.permissions.filter(codename='view_libros').exists()
    assert tiene(ROLE_OWNER) and tiene(ROLE_ADMIN) and tiene(ROLE_ACCOUNTANT) and tiene(ROLE_READONLY)
    assert not tiene(ROLE_SELLER) and not tiene(ROLE_CLIENT)
