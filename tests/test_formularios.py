"""Borradores del 104 y del 103 (core/tributario/formularios.py): casilleros confirmados por la norma del proyecto, con su
fuente y los documentos que los componen; lo que depende de un criterio sin confirmar va «por confirmar», sin casillero;
regla del 103 con sus ejemplos verificados (303→353, 3030→3530, 3480→3980; subtotal país 349/399; 499); vigencia;
exportación XLSX sin fórmulas y registrada; permisos y pestañas abiertas. No se presenta nada al SRI."""
import io
from datetime import date, timedelta
from decimal import Decimal

import openpyxl
import pytest
from django.db import transaction

from core.comprobantes import retenciones as sret, retenciones_recibidas as rr
from core.comprobantes.models import CodigoRetencion
from core.pos import compras
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_CLIENT, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER
from core.tributario import exportar, formularios as fm
from core.tributario.models import ExportacionLibro
from tests import ayuda_compras, helpers
from tests.ayudas_ventas import factura_autorizada, retencion_datos
from tests.test_emision_sri import empresa, p12  # noqa: F401 - empresa firmada y configurada en producción
from tests.test_libros import (DIA, MES, autorizar, cliente, compras_del_mes, con_iva, leer, produccion,  # noqa: F401
                               proveedor, sin_iva, ventas)

pytestmark = pytest.mark.django_db


def casillero(hoja, numero):
    return hoja.casilleros[numero]['valor'] if numero in hoja.casilleros else None


def pendiente(hoja, clave):
    return next((p for p in hoja.por_confirmar if p['clave'] == clave), None)


def suma_documentos(hoja, numero):
    return sum((Decimal(d['importe']) for d in hoja.casilleros[numero]['documentos']), Decimal('0.00'))


def cambiar_codigo(empresa, compras_del_mes, codigo):
    """El detalle de renta de la retención del mes pasa a otro código (datos ficticios de la prueba)."""
    with company_context(empresa):
        detalle = compras_del_mes['retencion'].detalles.get(impuesto='1')
        type(detalle).objects.filter(pk=detalle.pk).update(codigo=codigo)
        return type(detalle).objects.get(pk=detalle.pk)


class Test104:

    def test_ventas_confirmadas_y_por_confirmar(self, produccion, ventas):
        hoja = leer(produccion, lambda: fm.hoja_104(MES))
        d = ventas['debito']
        assert casillero(hoja, '401') == Decimal('20.00') + d.total_sin_impuestos    # bruto: factura al 15 % y ND (no la NC ni la anulada)
        assert casillero(hoja, '411') == d.total_sin_impuestos                        # neto: la NC devuelve las 20.00
        assert casillero(hoja, '421') == d.valor_iva                                  # 3.00 + IVA de la ND − 3.00
        for numero in ('401', '411', '421'):                                          # trazabilidad: cada documento suma su parte
            assert suma_documentos(hoja, numero) == casillero(hoja, numero)
            assert all(x['url'] and x['numero'] for x in hoja.casilleros[numero]['documentos'])
        assert ventas['anulada'].pk not in {x['id'] for x in hoja.casilleros['401']['documentos'] if x['tipo'] == 'factura'}
        cero = pendiente(hoja, 'ventas_0')
        assert cero['valor'] == Decimal('12.00') and cero['casilleros_posibles'] == ['403/413', '405/415', '406/416']
        assert pendiente(hoja, 'ajustes_nc')['valor'] == Decimal('20.00')
        assert pendiente(hoja, 'ventas_contado')['valor'] == Decimal('20.00')        # solo la base gravada de las facturas
        assert not {'403', '413', '423', '480', '481'} & set(hoja.casilleros)        # lo que está por confirmar no tiene casillero
        assert all(c['confirmado'] and c['fuente'] == fm.FUENTE_104 for c in hoja.casilleros.values())
        assert 'presentas tú en el portal del SRI' in hoja.como_dict()['aviso']
        assert {a['codigo'] for a in hoja.advertencias} >= {'activos_fijos', 'excluidos'}
        assert any('605/606' in n for n in hoja.no_calculados)

    def test_compras_retenciones_de_iva_y_609(self, produccion, admin, proveedor, compras_del_mes, con_iva):
        tipo = ayuda_compras.crear_tipo_gasto(produccion, 'ASESORÍA')
        with company_context(produccion):
            otra = compras.crear_compra(produccion, admin, ayuda_compras.datos_compra(proveedor, fecha_emision=DIA.isoformat(),
                                                                                      date_joined=DIA.isoformat()),
                                        [ayuda_compras.linea_gasto('Asesoría', price='200.00', type_expense=tipo)])
            iva_30 = CodigoRetencion.objects.filter(impuesto='2', codigo='1').first()        # Tabla 11: código 1 = 30 %
            datos = {'num_doc_sustento': otra.numero_comprobante, 'aut_doc_sustento': '1' * 49, 'base_0': '0', 'base_iva': '200.00',
                     'tarifa_iva': '15.00', 'cod_sustento': '01', 'forma_pago': '20', 'fecha_doc_sustento': DIA}
            with transaction.atomic():
                ret_iva = sret.crear(produccion, admin, otra, datos, [(iva_30.pk, None, None)], huella_revisada=sret.SIN_REVISION)
        ret_iva = autorizar(ret_iva, DIA + timedelta(days=1))
        agente = helpers.crear_cliente('agente.formularios', produccion, '0991234567001', '0990000019')
        with company_context(produccion):
            type(agente).objects.filter(pk=agente.pk).update(identification_type='04')
        agente.identification_type = '04'
        factura = factura_autorizada(produccion, agente, admin, con_iva, cantidad=2, fecha=DIA)
        with company_context(produccion):
            rr.registrar(produccion, admin, factura, retencion_datos(fecha_emision=DIA))
        hoja = leer(produccion, lambda: fm.hoja_104(MES))
        valor_iva = leer(produccion, lambda: sum(d.valor_retenido for d in ret_iva.detalles.filter(impuesto='2')))
        assert valor_iva > 0 and casillero(hoja, '725') == valor_iva                 # 30 % de IVA retenido como agente
        assert [x['id'] for x in hoja.casilleros['725']['documentos']] == [ret_iva.pk]
        assert casillero(hoja, '609') == Decimal('0.90')                             # IVA que le retuvieron (registro manual)
        gravadas = [p for p in hoja.por_confirmar if p['clave'].startswith('compras_') and p['clave'] != 'compras_sin_tarifa']
        assert [p['valor'] for p in gravadas] == [Decimal('300.00')]                 # 100 + 200 con tarifa 15 %: según sustento
        assert pendiente(hoja, 'compras_sin_tarifa')['valor'] == Decimal('50.00')    # compra antigua sin tarifa
        assert not {'500', '510', '520'} & set(hoja.casilleros)

    def test_otra_empresa_no_aparece(self, produccion, ventas, empresa_b):
        assert dict(leer(empresa_b, lambda: fm.hoja_104(MES)).casilleros) == {}

    def test_vigencia(self, produccion):
        with pytest.raises(fm.SinVigencia):
            leer(produccion, lambda: fm.hoja_104(date(2024, 3, 1)))
        with pytest.raises(fm.SinVigencia):
            leer(produccion, lambda: fm.hoja_103(date(2023, 12, 1)))


class Test103:

    def test_regla_de_casilleros_y_subtotal_pais(self, produccion, compras_del_mes):
        hoja = leer(produccion, lambda: fm.hoja_103(MES))
        detalle = leer(produccion, lambda: compras_del_mes['retencion'].detalles.get(impuesto='1'))
        assert casillero(hoja, '312') == detalle.base_imponible and casillero(hoja, '362') == detalle.valor_retenido
        assert casillero(hoja, '349') == detalle.base_imponible and casillero(hoja, '399') == detalle.valor_retenido
        assert casillero(hoja, '499') == casillero(hoja, '399') and hoja.por_confirmar == []
        assert [x['id'] for x in hoja.casilleros['362']['documentos']] == [compras_del_mes['retencion'].pk]
        assert suma_documentos(hoja, '399') == casillero(hoja, '399')
        assert 'totales_parciales' not in {a['codigo'] for a in hoja.advertencias}

    @pytest.mark.parametrize('codigo, base, valor', [('3440', '3440', '3940'), ('303A', '3030', '3530')])
    def test_cuatro_digitos_y_letra_confirmada(self, produccion, compras_del_mes, codigo, base, valor):
        detalle = cambiar_codigo(produccion, compras_del_mes, codigo)
        hoja = leer(produccion, lambda: fm.hoja_103(MES))
        assert casillero(hoja, base) == detalle.base_imponible and casillero(hoja, valor) == detalle.valor_retenido
        assert casillero(hoja, '399') == detalle.valor_retenido and hoja.por_confirmar == []

    @pytest.mark.parametrize('codigo, motivo', [('343A', fm.MOTIVO_LETRA), ('500', fm.MOTIVO_EXTERIOR)])
    def test_sin_regla_confirmada_va_por_confirmar(self, produccion, compras_del_mes, codigo, motivo):
        detalle = cambiar_codigo(produccion, compras_del_mes, codigo)
        hoja = leer(produccion, lambda: fm.hoja_103(MES))
        assert dict(hoja.casilleros) == {}                                           # ni su casillero, ni el subtotal, ni el 499
        p = pendiente(hoja, f'codigo_{codigo}')
        assert (p['valor'], p['motivo'], p['casilleros_posibles']) == (detalle.valor_retenido, motivo, [])
        assert 'totales_parciales' in {a['codigo'] for a in hoja.advertencias}

    def test_casillero_103(self):
        assert fm.casillero_103('303') == ('303', '353', True)                      # ejemplos verificados de la norma
        assert fm.casillero_103('3480') == ('3480', '3980', True)
        assert fm.casillero_103('303A') == ('3030', '3530', True)
        assert fm.casillero_103('343B') == (None, None, False)                      # letra sin mapa confirmado
        assert fm.casillero_103('500') == (None, None, False) and fm.casillero_103('504A') == (None, None, False)
        assert fm.casillero_103('') == (None, None, False)


class TestPantalla:

    def test_pagina_api_y_exportacion(self, client, produccion, admin, ventas):
        helpers.iniciar_sesion(client, admin, empresa=produccion)
        pagina = client.get(f'/tributario/formularios/?formulario=104&mes={MES:%Y-%m}')
        texto = pagina.content.decode()
        assert pagina.status_code == 200 and 'presentas tú en el portal del SRI' in texto and 'data-casillero="401"' in texto
        datos = client.get(f'/tributario/api/formularios/?formulario=104&mes={MES:%Y-%m}').json()
        assert (datos['formulario'], datos['mes'], datos['vigente_desde']) == ('104', f'{MES:%Y-%m}', '2024-04-01')
        c401 = next(c for c in datos['casilleros'] if c['casillero'] == '401')
        assert c401['confirmado'] is True and c401['fuente'] == fm.FUENTE_104 and c401['documentos']
        assert {p['clave'] for p in datos['por_confirmar']} >= {'ventas_0', 'ajustes_nc'}
        sin = client.get('/tributario/api/formularios/?formulario=104&mes=2023-12')
        assert sin.status_code == 400 and sin.json()['codigo'] == 'sin_vigencia'
        respuesta = client.get(f'/tributario/formularios/exportar/?formulario=104&mes={MES:%Y-%m}&empresa={produccion.pk}')
        assert respuesta.status_code == 200
        assert f'borrador-104-{produccion.ruc}-{MES:%Y-%m}.xlsx' in respuesta['Content-Disposition']
        libro = openpyxl.load_workbook(io.BytesIO(respuesta.content))
        assert libro.sheetnames == ['Borrador 104', 'Por confirmar', 'Documentos']
        assert not [c for h in libro for f in h.iter_rows() for c in f if c.data_type == 'f']   # sin fórmulas
        registro = leer(produccion, lambda: ExportacionLibro.objects.get(libro='f104'))
        assert registro.totales == {c['casillero']: c['valor'] for c in datos['casilleros']}
        assert registro.sha256 == exportar.huella(respuesta.content) and registro.generado_por_id == admin.pk
        assert client.get(f'/tributario/api/formularios/?empresa={produccion.pk + 999}').status_code == 409
        assert client.get(f'/tributario/formularios/exportar/?empresa={produccion.pk + 999}').status_code == 409
        assert client.get('/tributario/formularios/exportar/?formulario=104&mes=2023-12').status_code == 404

    def test_pantalla_del_103(self, client, produccion, admin, compras_del_mes):
        helpers.iniciar_sesion(client, admin, empresa=produccion)
        pagina = client.get(f'/tributario/formularios/?formulario=103&mes={MES:%Y-%m}')
        assert pagina.status_code == 200 and 'data-casillero="362"' in pagina.content.decode()
        datos = client.get(f'/tributario/api/formularios/?formulario=103&mes={MES:%Y-%m}').json()
        assert [c['casillero'] for c in datos['casilleros']] == ['312', '349', '362', '399', '499']
        assert datos['casilleros'][0]['fuente'] == fm.FUENTE_103

    @pytest.mark.parametrize('rol, estado', [(ROLE_OWNER, 200), (ROLE_ADMIN, 200), (ROLE_ACCOUNTANT, 200), (ROLE_READONLY, 200),
                                             (ROLE_SELLER, 302), (ROLE_CLIENT, 302)])
    def test_permisos_por_rol(self, client, produccion, rol, estado):
        usuario = helpers.crear_usuario(f'formularios.{rol.lower()}', produccion, rol)
        helpers.iniciar_sesion(client, usuario, empresa=produccion)
        assert client.get('/tributario/formularios/').status_code == estado
        assert client.get(f'/tributario/formularios/exportar/?formulario=103&mes={MES:%Y-%m}').status_code == estado
