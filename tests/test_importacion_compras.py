"""Crear la compra desde un XML recibido (espec-etapa2-compras §3.6, §3.8 y §6.G): propuesta con equivalencias y
sugerencias sin preseleccionar, importes del XML (DC4), datos del ATS, forma de pago del XML, stock una sola vez,
actualización condicionada del documento, bloqueos, proveedor nuevo, permisos y plan, reapertura, documentos anteriores
y notas de crédito y débito del proveedor. Documentos ficticios (tests/fabricas_recibidos.py)."""
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.importacion import compras as ic, servicios as sv, sri_autorizacion
from core.importacion.models import DocumentoImportado, EquivalenciaProducto, EventoImportacion
from core.pos import compras, emision
from core.pos.models import DebtsPay, Product, Provider, Purchase, PurchaseDetail
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_ACCOUNTANT, ROLE_OWNER
from tests import ayuda_compras as ayuda, fabricas_recibidos as r, helpers
from tests.test_importacion_xml_pdf import SRISimulado

pytestmark = pytest.mark.django_db
HOY = timezone.localdate


@pytest.fixture(autouse=True)
def archivos_temporales(settings, tmp_path, monkeypatch):
    settings.MEDIA_ROOT = str(tmp_path / 'media')
    monkeypatch.setattr(sri_autorizacion, 'PAUSA_REINTENTO', 0)
    monkeypatch.setattr(emision, '_cliente', SRISimulado())


@pytest.fixture
def empresa():
    return helpers.crear_empresa('RECEPTORA DE COMPRAS', ruc=r.RUC_RECEPTOR)


@pytest.fixture
def dueno(empresa):
    return helpers.crear_usuario('dueno.compra.xml', empresa, ROLE_OWNER)


@pytest.fixture
def proveedor(empresa):
    return ayuda.crear_proveedor(empresa, tipo='04', ruc=r.RUC_EMISOR, nombre='PROVEEDOR FICTICIO S.A.')


@pytest.fixture
def web(client, dueno, empresa):
    helpers.iniciar_sesion(client, dueno, empresa=empresa)
    return client


def importar(empresa, usuario, xml, verificado=True):
    with company_context(empresa):
        documento = sv.crear_lote(empresa, usuario, [('doc.xml', r.autorizacion(xml).encode())]).documentos.get()
        if verificado:
            DocumentoImportado.objects.filter(pk=documento.pk).update(estado_verificacion='verificada_sri')
            documento.refresh_from_db()
        return documento


def crear(empresa, documento, usuario, **datos):
    base = {'cod_sustento': '06', 'parte_relacionada': 'no'}
    base.update(datos)
    with company_context(empresa):
        return ic.crear_compra_desde_documento(documento, usuario, base)


def propuesta(empresa, documento):
    with company_context(empresa):
        return ic.propuesta_compra(DocumentoImportado.objects.get(pk=documento.pk))


def leer(empresa, funcion):
    with company_context(empresa):
        return funcion()


class TestPropuesta:

    def test_detalles_del_xml_en_el_documento(self, empresa, dueno):
        documento = importar(empresa, dueno, r.factura())
        detalles = documento.datos['comprobante']['detalles']
        assert [d['codigo_principal'] for d in detalles] == ['P0', 'P1']
        assert detalles[0]['iva'] == {'codigo_porcentaje': '4', 'tarifa': '15.00', 'base_imponible': '100.00', 'valor': '15.00'}

    def test_equivalencia_y_mismo_codigo_sin_preseleccionar(self, empresa, dueno, proveedor):
        recordado = ayuda.crear_producto(empresa, codigo='INT-1')
        mismo = ayuda.crear_producto(empresa, codigo='P1')
        with company_context(empresa):
            EquivalenciaProducto.objects.create(proveedor=proveedor, codigo_proveedor='P0', producto=recordado)
        p = propuesta(empresa, importar(empresa, dueno, r.factura()))
        uno, dos = p['lineas']
        assert (uno['origen_sugerencia'], uno['modo_sugerido'], uno['producto_sugerido']['id']) == ('equivalencia', 'producto',
                                                                                                    recordado.pk)
        assert (dos['origen_sugerencia'], dos['modo_sugerido'], dos['producto_sugerido']['id']) == ('mismo_codigo', 'gasto', mismo.pk)
        assert p['bloqueos'] == [] and {a['codigo'] for a in p['advertencias']} >= {'sin_equivalencia'}

    def test_sustento_sugerido_sin_preseleccionar(self, web, empresa, dueno, proveedor):
        documento = importar(empresa, dueno, r.factura())
        with company_context(empresa):
            sv.ReglaImportacion.objects.filter(pk=sv.reglas_de(empresa).pk).update(naturaleza_compra='inventario')
        api = web.get(f'/importacion/api/documentos/{documento.pk}/compra/').json()
        assert api['puede_crear'] and api['propuesta']['cod_sustento_sugerido'] == '06'
        assert api['propuesta']['forma_pago_del_xml'] == '20' and api['propuesta']['payment_type_sugerido'] == 'efectivo'
        assert api['propuesta']['importes']['total'] == '135.00' and api['propuesta']['parte_relacionada'] is False
        html = web.get(f'/importacion/documentos/{documento.pk}/compra/').content.decode()
        assert 'Usar sugerencia' in html and 'data-valor="06"' in html
        seleccionado = html.split('name="cod_sustento"', 1)[1].split('</select>', 1)[0]
        assert '<option value="" selected>' in seleccionado and '<option value="06" selected>' not in seleccionado

    def test_plazo_del_xml_sugiere_credito(self, empresa, dueno, proveedor):
        p = propuesta(empresa, importar(empresa, dueno, r.factura(plazo=45)))
        assert p['payment_type_sugerido'] == 'credito' and p['end_credit_sugerido'] == (HOY() + timedelta(days=45)).isoformat()

    def test_documento_anterior_sin_detalles_se_relee_sin_modificarse(self, empresa, dueno, proveedor):
        documento = importar(empresa, dueno, r.factura())
        with company_context(empresa):
            datos = documento.datos
            del datos['comprobante']['detalles']
            DocumentoImportado.objects.filter(pk=documento.pk).update(datos=datos)
        p = propuesta(empresa, documento)
        assert [l['codigo_principal'] for l in p['lineas']] == ['P0', 'P1']
        assert 'detalles' not in leer(empresa, lambda: DocumentoImportado.objects.get(pk=documento.pk).datos['comprobante'])

    def test_comprobante_ya_registrado_bloquea(self, empresa, dueno, proveedor):
        documento = importar(empresa, dueno, r.factura())
        with company_context(empresa):
            existente = compras.crear_compra(empresa, dueno, ayuda.datos_compra(proveedor, secuencial='271'), [ayuda.linea_gasto()])
        p = propuesta(empresa, documento)
        assert [(b['codigo'], b['compra_id']) for b in p['bloqueos']] == [('comprobante_registrado', existente.pk)]
        assert 'vincúlala en lugar de crear otra' in p['bloqueos'][0]['texto']
        with pytest.raises(sv.ErrorImportacion, match=f'compra #{existente.pk}'):
            crear(empresa, documento, dueno)

    def test_discrepancia_y_pruebas_bloquean(self, empresa, dueno, proveedor):
        documento = importar(empresa, dueno, r.factura())
        leer(empresa, lambda: DocumentoImportado.objects.filter(pk=documento.pk).update(estado_verificacion='discrepancia_sri'))
        assert [b['codigo'] for b in propuesta(empresa, documento)['bloqueos']] == ['verificacion']
        pruebas = importar(empresa, dueno, r.factura(ambiente=1, secuencial='000000900'))
        assert 'ambiente_pruebas' in [b['codigo'] for b in propuesta(empresa, pruebas)['bloqueos']]

    def test_retencion_no_crea_compra(self, empresa, dueno):
        documento = importar(empresa, dueno, r.retencion_v2())
        assert [b['codigo'] for b in propuesta(empresa, documento)['bloqueos']] == ['tipo_no_admitido']


class TestCrearCompra:

    def test_importes_del_xml_mandan_y_datos_del_ats(self, empresa, dueno, proveedor):
        lineas = (r.linea('P0', 'Tres unidades', cantidad='3', precio='33.333333', total='100.00'),
                  r.linea('P1', 'Con ICE', precio='10.00', ice='1.50'), r.linea('P2', 'Sin IVA', precio='20.00', iva='0'))
        documento = importar(empresa, dueno, r.factura(lineas=lineas, propina='2.00'))
        compra = crear(empresa, documento, dueno, forma_pago='20')
        with company_context(empresa):
            compra.refresh_from_db()
            documento.refresh_from_db()
            assert (compra.base_gravada, compra.base_0, compra.total_iva, compra.total_ice, compra.propina, compra.total) == (
                Decimal('111.50'), Decimal('20.00'), Decimal('16.73'), Decimal('1.50'), Decimal('2.00'), documento.importe_total)
            assert compra.subtotal == documento.total_sin_impuestos == Decimal('130.00')
            assert (compra.tipo_comprobante, compra.estab, compra.pto_emi, compra.secuencial, compra.autorizacion) == (
                '01', '001', '002', '000000271', documento.clave_acceso)
            assert (compra.fecha_emision, compra.origen, compra.version_datos, compra.pago_loc_ext) == (
                date(2026, 10, 10), 'importacion', 2, '01')
            assert compra.datos_incompletos is False and compra.faltantes() == []
            linea = PurchaseDetail.objects.filter(purchase=compra).order_by('id').first()
            assert (linea.cant, linea.price, linea.total, linea.total_iva) == (1, Decimal('100.00'), Decimal('100.00'), Decimal('15.00'))
            assert 'cant. 3 × 33,333333' in linea.descripcion

    def test_iva_diferenciado_con_su_tarifa(self, empresa, dueno, proveedor):
        documento = importar(empresa, dueno, r.factura(lineas=(r.linea('T1', 'Hospedaje en feriado', precio='50.00', iva='8',
                                                                       tarifa='8'),)))
        compra = crear(empresa, documento, dueno, cod_sustento='01')
        with company_context(empresa):
            linea = PurchaseDetail.objects.get(purchase=compra)
            assert (linea.codigo_porcentaje, linea.tarifa, linea.total_iva) == ('8', Decimal('8.00'), Decimal('4.00'))
            resumen = compras.resumen_por_tarifa([linea])
            assert resumen == [{'codigo': '8', 'nombre': 'IVA diferenciado 8 %', 'tarifa': Decimal('8.00'), 'base': Decimal('50.00'),
                                'valor': Decimal('4.00')}]
            compra.refresh_from_db()
            assert compra.base_gravada == Decimal('50.00') and compra.total_iva == resumen[0]['valor']

    def test_forma_de_pago_del_xml(self, empresa, dueno, proveedor):
        sin_pagos = importar(empresa, dueno, r.factura(pagos=()))
        assert propuesta(empresa, sin_pagos)['forma_pago_del_xml'] is None
        compra = crear(empresa, sin_pagos, dueno)
        assert compra.forma_pago == '' and ('forma_pago', 'Falta la forma de pago (ATS)') in leer(empresa, compra.faltantes)
        con_pagos = importar(empresa, dueno, r.factura(secuencial='000000272', pagos=(('01', '35.00'), ('19', '100.00'))))
        assert propuesta(empresa, con_pagos)['forma_pago_del_xml'] == '19'
        assert crear(empresa, con_pagos, dueno).forma_pago == '19'

    def test_vincula_el_documento_y_mueve_el_stock_una_vez(self, empresa, dueno, proveedor):
        producto = ayuda.crear_producto(empresa, codigo='INT-7', stock=0)
        documento = importar(empresa, dueno, r.factura(lineas=(r.linea('P0', 'Caja', cantidad='4', precio='25.00'),), plazo=30))
        compra = crear(empresa, documento, dueno, lineas=[{'indice': 0, 'modo': 'producto', 'product': producto.pk}])
        with company_context(empresa):
            documento.refresh_from_db()
            assert (documento.estado_revision, documento.compra_id, documento.proveedor_id) == ('vinculado', compra.pk, proveedor.pk)
            assert documento.estado_contable == 'propuesta' and documento.propuesta_contable['cuadra']
            assert Product.objects.get(pk=producto.pk).stock == 4
            deuda = DebtsPay.objects.get(purchase=compra)
            assert (deuda.base_calculo, deuda.debt, deuda.saldo) == ('total', Decimal('115.00'), Decimal('115.00'))
            assert EventoImportacion.objects.filter(documento=documento, tipo='compra_creada').count() == 1
        with pytest.raises(sv.ErrorImportacion, match=f'Ya se creó la compra #{compra.pk}'):
            crear(empresa, documento, dueno, lineas=[{'indice': 0, 'modo': 'producto', 'product': producto.pk}])
        assert leer(empresa, lambda: (Purchase.objects.count(), Product.objects.get(pk=producto.pk).stock)) == (1, 4)

    def test_actualizacion_condicionada_deshace_todo(self, empresa, dueno, proveedor, monkeypatch):
        producto = ayuda.crear_producto(empresa, codigo='INT-8', stock=0)
        documento = importar(empresa, dueno, r.factura(lineas=(r.linea('P0', 'Caja', cantidad='2', precio='50.00'),), plazo=30))
        original = compras.crear_compra

        def otro_proceso_vincula_antes(*args, **kwargs):
            compra = original(*args, **kwargs)
            DocumentoImportado.objects.filter(pk=documento.pk).update(estado_revision='aprobado')   # simulado
            return compra

        monkeypatch.setattr(compras, 'crear_compra', otro_proceso_vincula_antes)
        with pytest.raises(sv.ErrorImportacion, match='Ya se creó una compra desde este documento'):
            crear(empresa, documento, dueno, lineas=[{'indice': 0, 'modo': 'producto', 'product': producto.pk}])
        with company_context(empresa):
            assert Purchase.objects.count() == 0 and DebtsPay.objects.count() == 0
            assert Product.objects.get(pk=producto.pk).stock == 0
            assert DocumentoImportado.objects.get(pk=documento.pk).estado_revision == 'pendiente'

    def test_duplicado_detectado_en_el_insert(self, empresa, dueno, proveedor, monkeypatch):
        documento = importar(empresa, dueno, r.factura())
        with company_context(empresa):
            existente = compras.crear_compra(empresa, dueno, ayuda.datos_compra(proveedor, secuencial='271'), [ayuda.linea_gasto()])
        real, llamadas = compras._comprobante_registrado, []

        def ciego_la_primera_vez(*args, **kwargs):     # otra petición registró el comprobante justo antes del INSERT
            llamadas.append(1)
            return None if len(llamadas) == 1 else real(*args, **kwargs)

        monkeypatch.setattr(compras, 'comprobante_registrado', lambda *a, **k: None)
        monkeypatch.setattr(compras, '_comprobante_registrado', ciego_la_primera_vez)
        with pytest.raises(sv.ErrorImportacion, match=f'Ya registraste factura 001-002-000000271 .*compra #{existente.pk}'):
            crear(empresa, documento, dueno)
        with company_context(empresa):
            assert Purchase.objects.count() == 1 and DocumentoImportado.objects.get(pk=documento.pk).compra_id is None

    def test_cantidad_fraccionaria_solo_como_gasto(self, empresa, dueno, proveedor):
        producto = ayuda.crear_producto(empresa, codigo='INT-9', stock=0)
        documento = importar(empresa, dueno, r.factura(lineas=(r.linea('KG', 'Harina', cantidad='2.5', precio='4.000000'),)))
        assert propuesta(empresa, documento)['lineas'][0]['cantidad_entera'] is False
        with pytest.raises(sv.ErrorImportacion, match='tiene cantidad 2,5: regístrala como gasto'):
            crear(empresa, documento, dueno, lineas=[{'indice': 0, 'modo': 'producto', 'product': producto.pk}])
        compra = crear(empresa, documento, dueno, lineas=[{'indice': 0, 'modo': 'gasto'}])
        with company_context(empresa):
            linea = PurchaseDetail.objects.get(purchase=compra)
            assert linea.product_id is None and linea.cant == 1 and linea.total == Decimal('10.00')
            assert linea.descripcion == 'Harina (cant. 2,5 × 4,000000)'
            assert Product.objects.get(pk=producto.pk).stock == 0

    def test_agrupar_por_tarifa(self, empresa, dueno, proveedor):
        lineas = tuple(r.linea(f'L{i}', f'Línea {i}', precio='10.00') for i in range(3)) + (r.linea('Z', 'Sin IVA', precio='5.00', iva='0'),)
        documento = importar(empresa, dueno, r.factura(lineas=lineas))
        tipo = ayuda.crear_tipo_gasto(empresa, 'MERCADERÍA VARIA')
        compra = crear(empresa, documento, dueno, agrupar_por_tarifa=True, type_expense=tipo.pk)
        with company_context(empresa):
            filas = list(PurchaseDetail.objects.filter(purchase=compra).order_by('id').values_list(
                'descripcion', 'total', 'total_iva', 'codigo_porcentaje', 'type_expense_id', 'product_id'))
        assert filas == [('Factura 001-002-000000271 (4 líneas) · 15 %', Decimal('30.00'), Decimal('4.50'), '4', tipo.pk, None),
                         ('Factura 001-002-000000271 (4 líneas) · 0 %', Decimal('5.00'), Decimal('0.00'), '0', tipo.pk, None)]

    def test_recordar_guarda_la_equivalencia(self, empresa, dueno, proveedor):
        producto = ayuda.crear_producto(empresa, codigo='INT-10', stock=0)
        documento = importar(empresa, dueno, r.factura())
        crear(empresa, documento, dueno, lineas=[{'indice': 0, 'modo': 'producto', 'product': producto.pk, 'recordar': True},
                                                 {'indice': 1, 'modo': 'gasto'}])
        with company_context(empresa):
            equivalencia = EquivalenciaProducto.objects.get()
            assert (equivalencia.proveedor_id, equivalencia.codigo_proveedor, equivalencia.producto_id) == (proveedor.pk, 'P0',
                                                                                                         producto.pk)
            assert EventoImportacion.objects.filter(tipo='equivalencia_guardada').count() == 1
        siguiente = importar(empresa, dueno, r.factura(secuencial='000000280'))
        assert propuesta(empresa, siguiente)['lineas'][0]['origen_sugerencia'] == 'equivalencia'

    def test_sin_verificar_exige_confirmar(self, empresa, dueno, proveedor):
        documento = importar(empresa, dueno, r.factura(), verificado=False)
        assert propuesta(empresa, documento)['exige_confirmar_sin_verificar'] is True
        with pytest.raises(sv.ErrorImportacion, match='no está verificado'):
            crear(empresa, documento, dueno)
        assert crear(empresa, documento, dueno, confirmar_sin_verificar=True).pk

    def test_sustento_obligatorio_y_proveedor_nuevo_en_la_misma_transaccion(self, empresa, dueno):
        documento = importar(empresa, dueno, r.factura())
        nuevo = {'mobile': '0990001234', 'email': 'proveedor.nuevo@example.com', 'parte_relacionada': 'no'}
        with pytest.raises(sv.ErrorImportacion, match='Elige el sustento tributario'):
            crear(empresa, documento, dueno, cod_sustento='', proveedor_nuevo=nuevo)
        assert leer(empresa, lambda: Provider.objects.count()) == 0          # se deshizo con la compra
        compra = crear(empresa, documento, dueno, proveedor_nuevo=nuevo)
        with company_context(empresa):
            prov = Provider.objects.get()
            assert (prov.ruc, prov.tipo_identificacion, prov.tipo_sujeto, prov.parte_relacionada) == (r.RUC_EMISOR, '04', '02', False)
            assert compra.provider_id == prov.pk and compra.parte_relacionada is False

    def test_vincular_compra_de_otro_tipo(self, empresa, dueno, proveedor):
        documento = importar(empresa, dueno, r.nota_debito())
        with company_context(empresa):
            factura = compras.crear_compra(empresa, dueno, ayuda.datos_compra(proveedor, secuencial='60'), [ayuda.linea_gasto()])
            with pytest.raises(sv.ErrorImportacion, match='otro tipo de comprobante'):
                sv.revisar(documento, dueno, 'vincular_compra', {'id': factura.pk})

    def test_candidato_exacto_por_comprobante(self, empresa, dueno, proveedor):
        documento = importar(empresa, dueno, r.factura())
        with company_context(empresa):
            mismo = compras.crear_compra(empresa, dueno, ayuda.datos_compra(proveedor, secuencial='271'), [ayuda.linea_gasto()])
            compras.crear_compra(empresa, dueno, ayuda.datos_compra(proveedor, secuencial='272'), [ayuda.linea_gasto(price='120.00')])
            candidatos = sv.candidatos_conciliacion(DocumentoImportado.objects.get(pk=documento.pk))
        assert [(c['id'], c['razones'], c['exacto']) for c in candidatos] == [(mismo.pk, ['mismo comprobante'], True)]

    def test_reabrir_bloqueado_si_la_compra_salio_del_documento(self, empresa, dueno, proveedor):
        documento = importar(empresa, dueno, r.factura())
        compra = crear(empresa, documento, dueno)
        with company_context(empresa):
            documento.refresh_from_db()
            from core.importacion.views import acciones_posibles
            assert 'reabrir' not in acciones_posibles(documento)
            with pytest.raises(sv.ErrorImportacion, match=f'La compra #{compra.pk} se creó desde este documento: elimínala'):
                sv.revisar(documento, dueno, 'reabrir')
            compras.eliminar_compra(compra, dueno)
            documento.refresh_from_db()
            assert documento.estado_revision == 'pendiente' and 'crear_compra' in acciones_posibles(documento)


class TestNotasDelProveedor:

    def factura_a_credito(self, empresa, dueno):
        documento = importar(empresa, dueno, r.factura())
        return crear(empresa, documento, dueno, payment_type='credito', end_credit=(HOY() + timedelta(days=30)).isoformat())

    def test_nota_de_credito_enlazada_abona_la_cuenta_original(self, empresa, dueno, proveedor):
        factura = self.factura_a_credito(empresa, dueno)
        nota = importar(empresa, dueno, r.nota_credito())
        p = propuesta(empresa, nota)
        assert p['compra_modificada']['id'] == factura.pk and p['cod_sustento_sugerido'] == '06' and p['agrupar_obligatorio']
        compra = crear(empresa, nota, dueno)
        with company_context(empresa):
            compra.refresh_from_db()
            assert (compra.tipo_comprobante, compra.compra_modificada_id, compra.payment_type, compra.total) == (
                '04', factura.pk, 'efectivo', Decimal('23.00'))
            assert (compra.tipo_doc_modificado, compra.num_doc_modificado, compra.aut_doc_modificado) == (
                '01', '001002000000271', factura.autorizacion)
            assert compra.faltantes() == [] and not DebtsPay.objects.filter(purchase=compra).exists()
            linea = PurchaseDetail.objects.get(purchase=compra)
            assert linea.product_id is None and linea.descripcion == 'Devolución de mercadería'
            assert DebtsPay.objects.get(purchase=factura).saldo == Decimal('112.00')     # 135 − 23

    def test_nota_de_credito_sin_compra_queda_incompleta(self, empresa, dueno, proveedor):
        nota = importar(empresa, dueno, r.nota_credito())
        assert 'doc_modificado_sin_compra' in [a['codigo'] for a in propuesta(empresa, nota)['advertencias']]
        compra = crear(empresa, nota, dueno)
        assert compra.compra_modificada_id is None and 'doc_modificado' in [c for c, _ in leer(empresa, compra.faltantes)]

    def test_nota_de_debito_a_credito_crea_su_cuenta(self, empresa, dueno, proveedor):
        self.factura_a_credito(empresa, dueno)
        nota = importar(empresa, dueno, r.nota_debito(plazo=15))
        compra = crear(empresa, nota, dueno)
        with company_context(empresa):
            compra.refresh_from_db()
            assert (compra.tipo_comprobante, compra.payment_type, compra.total, compra.forma_pago) == (
                '05', 'credito', Decimal('11.50'), '20')
            deuda = DebtsPay.objects.get(purchase=compra)
            assert (deuda.debt, deuda.base_calculo, deuda.end_date) == (Decimal('11.50'), 'total', HOY() + timedelta(days=15))
            assert PurchaseDetail.objects.get(purchase=compra).descripcion == 'Intereses por mora'


class TestPantallaYPermisos:

    def test_pagina_crea_la_compra(self, web, empresa, dueno, proveedor):
        producto = ayuda.crear_producto(empresa, codigo='INT-20', stock=0)
        documento = importar(empresa, dueno, r.factura(razon='<img src=x onerror=alert(1)> S.A.'))
        url = f'/importacion/documentos/{documento.pk}/compra/'
        pagina = web.get(url)
        assert pagina.status_code == 200 and '<img src=x' not in pagina.content.decode()
        assert 'Los importes son los del XML autorizado.' in pagina.content.decode()
        datos = {'action': 'crear', 'cod_sustento': '06', 'payment_type': 'efectivo', 'forma_pago': '20', 'parte_relacionada': 'no',
                 'date_joined': HOY().isoformat(), 'lineas-TOTAL_FORMS': '2', 'lineas-INITIAL_FORMS': '2',
                 'lineas-MIN_NUM_FORMS': '0', 'lineas-MAX_NUM_FORMS': '1000', 'lineas-0-indice': '0', 'lineas-0-modo': 'producto',
                 'lineas-0-product': str(producto.pk), 'lineas-0-recordar': 'on', 'lineas-1-indice': '1', 'lineas-1-modo': 'gasto'}
        respuesta = web.post(url, datos)
        assert respuesta.status_code == 302 and respuesta.url == '/pos/purchase/'
        with company_context(empresa):
            compra = Purchase.objects.get()
            assert Product.objects.get(pk=producto.pk).stock == 1 and EquivalenciaProducto.objects.count() == 1
        assert f'Compra #{compra.pk} creada desde el XML' in [str(m) for m in respuesta.wsgi_request._messages]

    def test_api_crea_la_compra(self, web, empresa, dueno, proveedor):
        documento = importar(empresa, dueno, r.factura())
        detalle = web.get(f'/importacion/api/documentos/{documento.pk}/').json()['documento']
        assert 'crear_compra' in detalle['acciones'] and detalle['urls']['compra'] == f'/importacion/documentos/{documento.pk}/compra/'
        cuerpo = {'cod_sustento': '06', 'parte_relacionada': 'no', 'lineas': [{'indice': 0, 'modo': 'gasto'}]}
        r1 = web.post(f'/importacion/api/documentos/{documento.pk}/compra/', json.dumps(cuerpo), content_type='application/json')
        assert r1.status_code == 201 and r1.json()['compra']['numero'] == '001-002-000000271'
        assert r1.json()['documento']['estados']['revision']['id'] == 'vinculado'
        r2 = web.post(f'/importacion/api/documentos/{documento.pk}/compra/', json.dumps(cuerpo), content_type='application/json')
        assert r2.status_code == 400 and 'Ya se creó la compra' in r2.json()['error']

    def test_contador_no_crea_compras(self, client, empresa, dueno, proveedor):
        documento = importar(empresa, dueno, r.factura())
        helpers.iniciar_sesion(client, helpers.crear_usuario('contador.compra.xml', empresa, ROLE_ACCOUNTANT), empresa=empresa)
        assert client.get(f'/importacion/api/documentos/{documento.pk}/compra/').status_code == 403
        assert client.post(f'/importacion/api/documentos/{documento.pk}/compra/', '{}', content_type='application/json').status_code == 403
        assert client.get(f'/importacion/documentos/{documento.pk}/compra/').status_code == 302
        assert leer(empresa, lambda: Purchase.objects.count()) == 0

    def test_plan_1000_recibe_403(self, client):
        empresa = helpers.crear_empresa('PLAN MIL COMPRAS', plan='plan-1000', ruc='0990000077001')
        helpers.iniciar_sesion(client, helpers.crear_usuario('dueno.mil.compras', empresa, ROLE_OWNER), empresa=empresa)
        respuesta = client.post('/importacion/api/documentos/1/compra/', '{}', content_type='application/json')
        assert respuesta.status_code == 403 and 'Ilimitado y Multiempresa' in respuesta.json()['error']
        assert client.get('/importacion/documentos/1/compra/').status_code == 302

    def test_otra_empresa_no_ve_el_documento(self, client, empresa, dueno, proveedor):
        documento = importar(empresa, dueno, r.factura())
        otra = helpers.crear_empresa('OTRA COMPRADORA')
        helpers.iniciar_sesion(client, helpers.crear_usuario('dueno.otra.compra', otra, ROLE_OWNER), empresa=otra)
        assert client.get(f'/importacion/api/documentos/{documento.pk}/compra/').status_code == 404
        assert client.get(f'/importacion/documentos/{documento.pk}/compra/').status_code == 404
