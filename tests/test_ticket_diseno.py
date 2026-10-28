"""PDF térmico: legibilidad, contenido y área imprimible con datos ficticios.

Se usa create_pdf_continuo, incluidos su cálculo de alto y sus recursos locales.
Los objetos de estas pruebas están en memoria: no hay emisiones ni base real.
"""
from datetime import date
from decimal import Decimal
import io
import math
import re
from unittest.mock import patch

import pypdfium2 as pdfium
import pytest
from django.test import RequestFactory
from PIL import Image

from core.pos.utilities.printer import create_pdf_continuo
from tests.test_ride_diseno import CLAVE_DEMO, PROVEEDOR_DEMO, contexto_demo


MM = 72 / 25.4
TICKET = 'sale/format/ticket.html'


def contexto_ticket(cantidad=5, largo=False, factura=True, credito=False):
    contexto = contexto_demo('factura', cantidad)
    sale = contexto['sale']
    sale.is_invoice = factura
    sale.voucher_number = '000000123'
    sale.company.phone = '042000000'
    sale.company.get_obligated_accounting_display = 'Sí'
    sale.company.image = False
    sale.payment_type = 'credito' if credito else 'efectivo'
    sale.get_end_credit = '28/11/2026'
    # Registrada el 20 y firmada el 21, con la numeración de un local distinto del que la empresa usa ahora.
    sale.emission_date = date(2026, 10, 21)
    sale.receipt.establishment_address = 'Local de la numeración de la venta, dirección ficticia 300'
    for i, detail in enumerate(sale.saledetail_set, 1):
        detail.product.name = f'Artículo ficticio {i:03d}'
        if largo:
            detail.product.name += (
                ' — Servicio de mantenimiento preventivo y correctivo de equipos de cómputo'
                f' con repuestos y revisión completa, terminación FIN-{i:03d}'
            )
        detail.cant = (i % 3) + 1
        detail.price = Decimal('10.00') + Decimal(i) * Decimal('1.03')
        detail.total_dscto = Decimal('0.31') if i % 2 else Decimal('0.00')
        detail.total = detail.price * detail.cant - detail.total_dscto
    for i, impuesto in enumerate(sale.impuestos_por_tarifa):
        impuesto.base = sum((d.total for j, d in enumerate(sale.saledetail_set) if j % 5 == i), Decimal('0'))
        impuesto.valor = (impuesto.base * impuesto.tarifa / 100).quantize(Decimal('.01'))
    # El método actual del backend devuelve el bruto antes del descuento.
    # Reproducir su contrato; el rediseño no debe recalcular ni corregir montos.
    sale.get_subtotal_without_taxes = sum((d.price * d.cant for d in sale.saledetail_set), Decimal('0'))
    sale.total_dscto = sum((d.total_dscto for d in sale.saledetail_set), Decimal('0'))
    sale.total = sum(d.total for d in sale.saledetail_set) + sum(t.valor for t in sale.impuestos_por_tarifa)
    sale.cash = sale.total + Decimal('10.00')
    sale.change = Decimal('10.00')
    return contexto


def render_ticket(contexto, con_peticion=True):
    request = RequestFactory().get('/pos/sale/admin/print/invoice/123/') if con_peticion else None
    with patch('core.pos.utilities.printer.get_current_request', return_value=request):
        return create_pdf_continuo(contexto, TICKET)


def compacto(texto):
    return ''.join(texto.split()).replace('\u00ad', '')


def importe(valor):
    return f'{valor:.2f}'.replace('.', ',')


def inspeccionar_ticket(contenido, contexto):
    """Medidas reales del PDF y contenido: utilizable también por la captura externa."""
    with pdfium.PdfDocument(contenido) as pdf:
        pagina = pdf[0]
        ancho, alto = pagina.get_size()
        textpage = pagina.get_textpage()
        texto = textpage.get_text_range()
        caracteres = [textpage.get_charbox(i) for i in range(textpage.count_chars())
                      if textpage.get_text_range(i, 1).strip()]
        objetos = []
        for obj in pagina.get_objects():
            if not isinstance(obj, pdfium.PdfTextObj):
                continue
            limites = obj.get_bounds()
            fragmento = textpage.get_text_bounded(*limites)
            matrix = obj.get_matrix()
            objetos.append({
                'texto': fragmento, 'limites': limites,
                'pt': obj.get_font_size() * math.hypot(matrix.c, matrix.d),
                'fuente': obj.get_font().get_base_name(),
            })
        return {
            'paginas': len(pdf), 'ancho_mm': ancho / MM, 'alto_mm': alto / MM,
            'blanco_final_mm': min(c[1] for c in caracteres) / MM,
            'izquierda_mm': min(c[0] for c in caracteres) / MM,
            'derecha_mm': max(c[2] for c in caracteres) / MM,
            'texto': texto, 'objetos': objetos,
        }


def verificar_contenido(datos, contexto):
    sale = contexto['sale']
    texto = compacto(datos['texto'])
    posiciones = []
    for detail in sale.saledetail_set:
        descripcion = compacto(detail.product.name)
        assert descripcion in texto, detail.product.name
        posiciones.append(texto.index(descripcion))
    assert posiciones == sorted(posiciones), 'Las líneas deben conservar el orden recibido.'
    # Cada descripción mantiene sus valores, no basta con hallar el total en otra línea.
    for i, detail in enumerate(sale.saledetail_set):
        inicio = posiciones[i] + len(compacto(detail.product.name))
        # La última línea se cierra antes del resumen: sus valores no pueden hallarse en los totales ni en el cobro.
        fin = posiciones[i + 1] if i + 1 < len(posiciones) else texto.index('Subtotalsinimpuestos', inicio)
        bloque = texto[inicio:fin]
        assert compacto(f'{detail.cant} × ${importe(detail.price)}') in bloque
        for valor in (detail.price, detail.total_dscto, detail.total):
            assert importe(valor) in bloque, (detail.product.name, valor, bloque)
    assert importe(sale.total) in texto
    assert importe(sale.get_subtotal_without_taxes) in texto
    assert importe(sale.total_dscto) in texto
    assert sale.get_subtotal_without_taxes - sum(d.total for d in sale.saledetail_set) == sale.total_dscto
    assert '0998888888001' in texto
    # dirMatriz y dirEstablecimiento del XML: el local es el de la numeración de la venta, no el actual de la empresa.
    assert compacto('Dirección matriz: ' + sale.company.main_address) in texto
    assert compacto('Establecimiento: ' + sale.receipt.establishment_address) in texto
    assert compacto(sale.company.establishment_address) not in texto
    if sale.is_invoice:
        assert compacto(f'Fecha de emisión: {sale.emission_date:%Y-%m-%d}') in texto   # fechaEmision, no la de registro
        for valor in (CLAVE_DEMO, *PROVEEDOR_DEMO.values()):
            assert compacto(valor) in texto
        for impuesto in sale.impuestos_por_tarifa:
            assert compacto('Subtotal ' + impuesto.nombre) in texto
            assert importe(impuesto.base) in texto
            if impuesto.tarifa:
                assert compacto('IVA ' + impuesto.nombre) in texto
                assert importe(impuesto.valor) in texto


@pytest.mark.parametrize('cantidad,largo', [(1, False), (5, False), (40, False), (1, True), (5, True), (40, True)])
def test_ticket_diseno_conserva_lineas_y_area_de_impresion(cantidad, largo):
    contexto = contexto_ticket(cantidad, largo)
    datos = inspeccionar_ticket(render_ticket(contexto), contexto)
    assert datos['paginas'] == 1
    assert datos['ancho_mm'] == pytest.approx(58, abs=.02)
    assert 0 < datos['blanco_final_mm'] < 12
    # Térmica de 58 mm: texto dentro de los 48 mm centrales, tolerancia de raster/tipografía.
    assert datos['izquierda_mm'] >= 4.8
    assert datos['derecha_mm'] <= 53.2
    verificar_contenido(datos, contexto)


def test_ticket_tipografia_legible_y_pie_en_cursiva():
    contexto = contexto_ticket()
    datos = inspeccionar_ticket(render_ticket(contexto), contexto)
    objetos = datos['objetos']
    productos = [o for o in objetos if 'Artículo ficticio' in o['texto']]
    assert productos and min(o['pt'] for o in productos) >= 8.99
    assert min(o['pt'] for o in objetos if o['texto'].strip()) >= 7.99
    proveedor = [o for o in objetos if 'FacturaPorAquí' in o['texto'] or 'soporte@example.test' in o['texto']]
    assert proveedor and all(re.search('italic|oblique', o['fuente'], re.I) for o in proveedor)
    # El proveedor queda después del último dato de cobro, sin superponer bloques.
    cambio = [o for o in objetos if 'Cambio' in o['texto']]
    assert cambio and min(o['limites'][1] for o in cambio) > max(o['limites'][3] for o in proveedor)


def test_ticket_no_electronico_y_pago_a_credito_conservan_sus_datos():
    contexto = contexto_ticket(factura=False, credito=True)
    datos = inspeccionar_ticket(render_ticket(contexto), contexto)
    texto = datos['texto']
    assert 'Ticket' in texto and '000000123' in texto
    assert '28/11/2026' in texto
    assert CLAVE_DEMO not in compacto(texto)
    assert 'Cambio' not in texto and 'Efectivo' not in texto
    verificar_contenido(datos, contexto)


def test_ticket_sin_peticion_conserva_tamano_y_contenido():
    contexto = contexto_ticket()
    con = inspeccionar_ticket(render_ticket(contexto, True), contexto)
    sin = inspeccionar_ticket(render_ticket(contexto, False), contexto)
    assert sin['texto'] == con['texto']
    # Sin petición el generador añade Bootstrap: puede variar el redondeo del alto,
    # pero conserva el contenido, el ancho térmico y la terminación sin papel sobrante.
    assert sin['alto_mm'] == pytest.approx(con['alto_mm'], abs=1)
    assert sin['ancho_mm'] == pytest.approx(58, abs=.02)
    assert 0 < sin['blanco_final_mm'] < 12


@pytest.mark.parametrize('precio,descuento,tarifa', [
    ('123456.78', '0.31', '.15'), ('9999999.99', '0.00', '0'),
])
def test_ticket_importe_grande_no_separa_los_centavos(precio, descuento, tarifa):
    contexto = contexto_ticket(1)
    sale = contexto['sale']
    detail = sale.saledetail_set[0]
    detail.cant, detail.price, detail.total_dscto = 1, Decimal(precio), Decimal(descuento)
    detail.total = detail.price - detail.total_dscto
    sale.get_subtotal_without_taxes = detail.price * detail.cant
    sale.total_dscto = detail.total_dscto
    for impuesto in sale.impuestos_por_tarifa:
        impuesto.base = impuesto.valor = Decimal('0')
    impuesto = sale.impuestos_por_tarifa[0 if Decimal(tarifa) else 4]
    impuesto.base = detail.total
    impuesto.valor = (detail.total * Decimal(tarifa)).quantize(Decimal('.01'))
    sale.total = detail.total + impuesto.valor
    sale.cash, sale.change = sale.total, Decimal('0')
    datos = inspeccionar_ticket(render_ticket(contexto), contexto)
    # Cada importe sale varias veces (precio, importe, subtotales, total, efectivo): basta con que una aparición se
    # parta (141974, + salto de línea + 94) para fallar. Sin compactar deben contarse las mismas que compactado.
    texto = datos['texto']
    importes = {detail.price, detail.total_dscto, detail.total, sale.get_subtotal_without_taxes, impuesto.base,
                impuesto.valor, sale.total, sale.cash}
    for valor in sorted(v for v in importes if v):
        cifra = importe(valor)
        assert texto.count(cifra) == compacto(texto).count(cifra) > 0, (cifra, texto)
    assert datos['izquierda_mm'] >= 4.8 and datos['derecha_mm'] <= 53.2


def test_ticket_nombre_y_correo_sin_espacios_no_salen_del_papel():
    contexto = contexto_ticket(1)
    sale = contexto['sale']
    sale.company.tradename = 'DISTRIBUCIONESDEMOIMPORTACIONES'
    sale.company.email = 'consultasdelcomprobante.facturacion@example.test'
    datos = inspeccionar_ticket(render_ticket(contexto), contexto)
    texto = compacto(datos['texto'])
    assert sale.company.tradename in texto
    assert sale.company.email in texto
    assert datos['izquierda_mm'] >= 4.8 and datos['derecha_mm'] <= 53.2


def logo_png(ancho=120, alto=40):
    """Logo ficticio pequeño (3:1), como el que sube un emisor."""
    contenido = io.BytesIO()
    Image.new('RGB', (ancho, alto), (22, 59, 80)).save(contenido, 'PNG')
    return contenido.getvalue()


def contexto_con_logo(settings, tmp_path, existe=True):
    """Ticket de una empresa con logo en MEDIA; si no existe, el archivo registrado ya no está o no se puede leer."""
    settings.MEDIA_ROOT = str(tmp_path)
    nombre = 'empresas/00000000-0000-0000-0000-000000000000/logo/2026/10/logo-ficticio.png'
    if existe:
        ruta = tmp_path / nombre
        ruta.parent.mkdir(parents=True)
        ruta.write_bytes(logo_png())
    contexto = contexto_ticket(1)
    contexto['sale'].company.image = nombre
    contexto['sale'].company.get_image = f'{settings.MEDIA_URL}{nombre}'   # como Company.get_image
    return contexto


def imagenes_mm(contenido):
    """Límites (izquierda, abajo, derecha, arriba) en mm de cada imagen dibujada en la hoja."""
    with pdfium.PdfDocument(contenido) as pdf:
        imagenes = [obj for obj in pdf[0].get_objects() if isinstance(obj, pdfium.PdfImage)]
        return [tuple(v / MM for v in obj.get_bounds()) for obj in imagenes]


def test_ticket_logo_del_emisor_pequeno_dentro_del_area(settings, tmp_path):
    contexto = contexto_con_logo(settings, tmp_path)
    contenido = render_ticket(contexto)
    datos = inspeccionar_ticket(contenido, contexto)
    imagenes = imagenes_mm(contenido)
    assert len(imagenes) == 2, imagenes   # logo del emisor y colibrí del pie
    logo = max(imagenes, key=lambda limites: limites[3])
    assert 4.8 <= logo[0] and logo[2] <= 53.2
    assert logo[2] - logo[0] <= 22.1 and logo[3] - logo[1] <= 12.1   # proporcionado dentro de su caja de 22 × 12 mm
    nombre = [o for o in datos['objetos'] if 'COMERCIAL DEMO' in o['texto']]
    assert nombre and logo[1] >= max(o['limites'][3] for o in nombre) / MM   # sobre el nombre, sin superponerse
    assert 'Logotipo' not in datos['texto']
    assert datos['paginas'] == 1 and 0 < datos['blanco_final_mm'] < 12


@pytest.mark.parametrize('con_peticion', [True, False])
def test_ticket_logo_inexistente_no_imprime_texto_alternativo(settings, tmp_path, con_peticion):
    contexto = contexto_con_logo(settings, tmp_path, existe=False)
    contenido = render_ticket(contexto, con_peticion)
    datos = inspeccionar_ticket(contenido, contexto)
    assert len(imagenes_mm(contenido)) == 1   # solo el colibrí del pie
    texto = compacto(datos['texto'])
    # Ningún texto alternativo, con cualquier redacción: lo primero que se imprime es el nombre del emisor.
    assert 'Logotipo' not in texto and texto.startswith(compacto(contexto['sale'].company.tradename)), texto[:80]
    assert datos['paginas'] == 1 and 0 < datos['blanco_final_mm'] < 12
