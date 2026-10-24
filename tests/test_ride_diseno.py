"""Regresiones de documentos A4: datos, paginación y lectura de la clave ficticia.

Los contextos son objetos en memoria, sin empresas reales, firma, SRI ni pagos.
Se usa el mismo renderizador y resolvedor local de recursos que la aplicación.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS

import pypdfium2 as pdfium
import pytest
import zxingcpp
from django.template.loader import render_to_string

from core.comprobantes.ride import codigo_de_barras
from core.pos.utilities.printer import create_pdf
from tests.fabricas_sri import clave


CLAVE_DEMO = clave(fecha=date(2026, 10, 20), ruc='0999999999001', ambiente=1,
                   pto='001', secuencial='000000123')
PROVEEDOR_DEMO = {
    'nombre': 'FacturaPorAquí DEMO', 'ruc': '0990000000001',
    'email': 'soporte@example.test', 'direccion': 'Calle de pruebas 123, Ciudad ficticia',
}
TEMPLATES = {
    'factura': 'sale/format/invoice.html',
    'credito': 'credit_note/format/invoice.html',
    'debito': 'comprobantes/notadebito/ride.html',
    'retencion': 'comprobantes/retencion/ride.html',
    'liquidacion': 'comprobantes/liquidacion/ride.html',
    'guia': 'comprobantes/guia/ride.html',
}


class Filas(list):
    def all(self):
        return self


def contexto_demo(tipo, cantidad=5, largo=False):
    empresa = NS(
        business_name='EMISOR FICTICIO DEMOSTRACIÓN S.A.', tradename='COMERCIAL DEMO',
        ruc='0999999999001', main_address='Av. de pruebas 100 y Calle Modelo, Ciudad ficticia',
        establishment_address='Sucursal de pruebas, dirección ficticia 200',
        mobile='0990000000', email='emisor@example.test', obligated_accounting='SI',
        special_taxpayer='DEMO-123', leyenda_rimpe='CONTRIBUYENTE RÉGIMEN RIMPE',
        get_image='/static/img/default/empty.png',
        get_environment_type_display='PRUEBAS', get_emission_type_display='NORMAL',
    )
    cliente = NS(
        user=NS(names='COMPRADOR FICTICIO S.A.', email='comprador@example.test'),
        dni='0998888888001', mobile='', address='Calle del comprador 300, Ciudad ficticia',
        extra_emails='contabilidad@example.test',
    )
    receipt = NS(establishment_address=empresa.establishment_address)
    tarifas = [('4', '15 %', Decimal('15')), ('5', '5 %', Decimal('5')),
               ('0', '0 %', Decimal('0')), ('6', 'no objeto de IVA', Decimal('0')),
               ('7', 'exento de IVA', Decimal('0'))]
    impuestos = []
    for i, (codigo, nombre, tarifa) in enumerate(tarifas):
        base = Decimal(sum(1 for j in range(cantidad) if j % 5 == i)) * 20
        impuestos.append(NS(codigo=codigo, nombre=nombre, tarifa=tarifa, base=base,
                            valor=(base * tarifa / 100).quantize(Decimal('.01'))))
    subtotal = Decimal(cantidad) * 20
    total = subtotal + sum(t.valor for t in impuestos)
    filas = Filas()
    for i in range(cantidad):
        nombre = f'Producto ficticio {i + 1:03d}'
        if largo:
            nombre += ' — descripción completa de ejemplo para comprobar el ajuste del texto sin perder su terminación FIN'
        producto = NS(code=f'P{i + 1:03d}', name=nombre, category=NS(name='Bienes'),
                      get_short_name=f'{nombre} (Bienes)')
        filas.append(NS(
            product=producto, cant=1, price=Decimal('20'), total_dscto=Decimal('0'), total=Decimal('20'),
            codigo=producto.code, descripcion=nombre, cantidad=Decimal('1.000000'),
            precio_unitario=Decimal('20'), descuento=Decimal('0'), precio_total_sin_impuesto=Decimal('20'),
            razon=nombre, valor=Decimal('20'), base_imponible=Decimal('20'),
            get_impuesto_display='Renta', porcentaje=Decimal('1'), valor_retenido=Decimal('.20'),
        ))
    sale = NS(
        company=empresa, client=cliente, receipt=receipt, voucher_number_full='001-001-000000123',
        access_code=CLAVE_DEMO, get_authorization_date='24/10/2026 12:30:00',
        authorization_date=datetime(2026, 10, 24, 12, 30, tzinfo=timezone.utc),
        get_date_joined='20/10/2026', emission_date=date(2026, 10, 20),
        get_environment_type_display='PRUEBAS', get_emission_type_display='NORMAL',
        get_proveedor=PROVEEDOR_DEMO, get_ruc_proveedor=PROVEEDOR_DEMO['ruc'],
        saledetail_set=filas, impuestos_por_tarifa=impuestos,
        get_subtotal_without_taxes=subtotal, total_dscto=Decimal('0'), total=total,
        time_limit=30, get_payment_method_display='OTROS CON UTILIZACIÓN DEL SISTEMA FINANCIERO',
        additional_info=[NS(name='Observación', value='Documento de demostración sin validez tributaria'),
                         NS(name='Email', value='comprador@example.test, contabilidad@example.test')],
    )
    credit = NS(**{k: v for k, v in vars(sale).items() if k not in {'emission_date', 'get_date_joined'}})
    credit.sale = sale
    credit.emission_date = date(2026, 10, 24)
    credit.get_date_joined = '24/10/2026'
    credit.motive = 'Devolución ficticia de productos de demostración'
    credit.creditnotedetail_set = filas
    c = NS(
        company=empresa, receipt=receipt, voucher_number_full='001-001-000000124',
        access_code=CLAVE_DEMO, authorization_date=sale.authorization_date,
        get_environment_type_display='PRUEBAS', emission_date=date(2026, 10, 24),
        razon_social=cliente.user.names, identificacion=cliente.dni,
        get_tipo_identificacion_display='RUC', direccion=cliente.address,
        correo='comprador@example.test, contabilidad@example.test', concepto='Compra ficticia para pruebas de diseño',
        provider=NS(address=cliente.address), detalles=filas, motivos=filas,
        num_doc_modificado='001-001-000000123', fecha_doc_sustento=date(2026, 10, 20),
        num_doc_sustento='001001000000123', num_doc_sustento_formato='001-001-000000123',
        aut_doc_sustento='2' * 49, cod_doc_sustento='01', periodo_fiscal='10/2026',
        total_retenido=Decimal(cantidad) * Decimal('.20'),
        forma_pago='20', tarifa_iva=Decimal('15'), total_sin_impuestos=subtotal,
        valor_iva=subtotal * Decimal('.15'), valor_total=subtotal * Decimal('1.15'),
        importe_total=total, total_descuento=Decimal('0'),
        impuestos_por_tarifa=[(t.tarifa, t.base, t.valor) for t in impuestos[:2]] + [
            (Decimal('0'), sum(t.base for t in impuestos[2:]), Decimal('0'))
        ],
        transportista_identificacion='0997777777001', transportista_razon_social='TRANSPORTISTA FICTICIO',
        placa='DEMO-123', dir_partida=empresa.establishment_address,
        fecha_inicio=date(2026, 10, 24), fecha_fin=date(2026, 10, 25),
        motivo='Traslado de productos de demostración', doc_aduanero='DEMO-ADUANA',
        cod_estab_destino='002', ruta='Origen ficticio — Destino ficticio',
    )
    return {
        'sale': sale, 'credit_note': credit, 'c': c, 'empresa': empresa,
        'company': empresa, 'proveedor': PROVEEDOR_DEMO,
        'forma_pago': sale.get_payment_method_display,
        'access_code_barcode': codigo_de_barras(CLAVE_DEMO),
    }


def textos_pdf(contenido):
    with pdfium.PdfDocument(contenido) as documento:
        return [pagina.get_textpage().get_text_range() for pagina in documento]


@pytest.mark.parametrize('tipo', TEMPLATES)
def test_ride_conserva_datos_y_proveedor_en_a4(tipo):
    contenido = create_pdf(contexto_demo(tipo), TEMPLATES[tipo])
    with pdfium.PdfDocument(contenido) as documento:
        assert len(documento) == 1
        pagina = documento[0]
        assert pagina.get_size() == pytest.approx((595.276, 841.89), abs=.02)
        texto = ' '.join(pagina.get_textpage().get_text_range().split())
        for dato in ['EMISOR FICTICIO DEMOSTRACIÓN S.A.', 'COMPRADOR FICTICIO S.A.',
                     'RÉGIMEN RIMPE', 'DEMO-123', 'RUC Proveedor', *PROVEEDOR_DEMO.values()]:
            assert dato in texto
        assert 'P005' in texto or 'Producto ficticio 005' in texto
        if tipo == 'guia':
            for dato in ['TRANSPORTISTA FICTICIO', 'DEMO-ADUANA', '002', '25/10/2026']:
                assert dato in texto
            assert 'TOTAL USD' not in texto and 'VALOR TOTAL' not in texto
        elif tipo == 'retencion':
            assert 'TOTAL RETENIDO' in texto and '10/2026' in texto
        elif tipo in {'factura', 'credito'}:
            for dato in ['Subtotal 15 %', 'Subtotal 5 %', 'Subtotal 0 %',
                         'Subtotal no objeto de IVA', 'Subtotal exento de IVA', '104,00']:
                assert dato.lower() in texto.lower()


def test_factura_larga_no_repite_encabezados_y_clave_se_puede_leer():
    contenido = create_pdf(contexto_demo('factura', 90, largo=True), TEMPLATES['factura'])
    with pdfium.PdfDocument(contenido) as documento:
        assert len(documento) > 1
        textos = [' '.join(p.get_textpage().get_text_range().split()) for p in documento]
        assert sum(t.count('EMISOR FICTICIO DEMOSTRACIÓN S.A.') for t in textos) == 1
        assert sum(t.lower().count('descripción') for t in textos) == 91  # título + 90 descripciones
        assert 'P090' in ' '.join(textos)
        for texto in textos:
            for dato in PROVEEDOR_DEMO.values():
                assert dato in texto
        # Conservar el patrón de barras al rasterizar: 300 dpi sin suavizado,
        # y 600 dpi con el render predeterminado. No es una prueba de escáner físico.
        for opciones in ({'scale': 300 / 72, 'no_smoothimage': True}, {'scale': 600 / 72}):
            codigos = zxingcpp.read_barcodes(documento[0].render(**opciones).to_pil())
            assert CLAVE_DEMO in [c.text for c in codigos]


def test_nota_credito_distingue_su_fecha_del_documento_modificado():
    from lxml import html
    pagina = html.fromstring(render_to_string(TEMPLATES['credito'], contexto_demo('credito')))
    texto = ' '.join(pagina.text_content().split())
    # El contexto tiene fechas distintas: emisión NC 24/10 y factura modificada 20/10.
    assert '24/10/2026' in texto and '20/10/2026' in texto
    datos = [(p.text_content()) for p in pagina.xpath('//p')]
    assert any('Fecha de emisión' in dato and '24/10/2026' in dato for dato in datos)
    assert any(('modific' in dato.lower() or 'sustento' in dato.lower()) and '20/10/2026' in dato for dato in datos)
