"""Diseño de factura v2: conservación de lo emitido y flujo fiscal. Datos FICTICIOS, SRI simulado
(SRIFalso), firma con el .p12 de prueba; sin red, sin correos reales, sin pagos.

1) Emisión con copia v2: la primera firma fija {id, version 2, primary, secondary, fuente, encabezado, pie_comercial};
   un reintento (DEVUELTA, NO AUTORIZADO, EN PROCESO) después de cambiar el diseño no la cambia; el XML firmado no lleva
   nada del diseño; clave, fecha, secuencial, XML (sin la firma) y cupo iguales sin diseño, con v1 y con v2.
2) regenerar_ride / fidelidad con textos comerciales que imitan datos fiscales.
3) SalePrintA4View y el correo entregan los bytes guardados (pdf_authorized) de una factura con copia v2.
"""
import re

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.core.management import call_command
from io import StringIO
from lxml import etree
from pathlib import Path

from core.comprobantes import ride_styles
from core.comprobantes.fidelidad import diferencias, texto_del_pdf
from core.configuracion import diseno as dz
from core.configuracion.models import DisenoFactura
from core.pos.models import Client, Company, Sale
from core.pos.utilities import printer
from core.pos.utilities.sri import SRI
from core.suscripciones.models import QuotaReservation
from core.tenancy.context import company_context
from core.user.models import User
from tests import helpers
from tests.test_emision_sri import (CLAVE, RUC_PROVEEDOR, accion, comprador, dueno, leer, p12, periodo,  # noqa: F401
                                    producto, refrescar, sri, vender, venta_de, web)

pytestmark = pytest.mark.django_db
URL = '/configuracion/diseno-factura/'
A4 = '/pos/sale/admin/print/a4/{}/'
FACTURA = 'sale/format/invoice.html'
DS = '{http://www.w3.org/2000/09/xmldsig#}Signature'
RUC_FIJO = ride_styles.PROVEEDOR_FIJO['ruc']
V2_A = {'style': 'banda', 'primary': '#112233', 'secondary': '#DDEEFF', 'fuente': 'dejavu-serif',
        'encabezado': 'Encabezado comercial A', 'pie_comercial': 'Pie comercial A'}
V2_B = {'style': 'compacto', 'primary': '#000000', 'secondary': '#FFFFFF', 'fuente': 'liberation-serif',
        'encabezado': 'Encabezado comercial B', 'pie_comercial': 'Pie comercial B'}
V1_A = {'style': 'banda', 'primary': '#112233', 'secondary': '#DDEEFF'}
V1_B = {'style': 'compacto', 'primary': '#000000', 'secondary': '#FFFFFF'}
RESULTADOS = {}


@pytest.fixture
def piloto(settings):
    settings.FPA_DISENO_FACTURA_PILOTO = ['*']


@pytest.fixture
def empresa(settings, p12, monkeypatch):  # noqa: F811 — misma que test_emision_sri, con RUC fijo y número de clave fijo
    settings.FPA_RUC_PROVEEDOR = RUC_PROVEEDOR
    monkeypatch.setattr(SRI, 'generate_number', lambda self, amount=8: '12345678')
    empresa = helpers.crear_empresa('EMISORA', environment_type=2, ruc='0990000777001')
    helpers.configurar_facturacion(empresa, estab='001', punto='002', ultimo_factura=270, ultimo_nota=4, ambiente=2)
    empresa.electronic_signature.save('firma.p12', ContentFile(p12), save=False)
    empresa.electronic_signature_key = CLAVE
    empresa.save()
    return empresa


@pytest.fixture
def contextos(monkeypatch):
    vistos = []
    original = printer.create_pdf

    def anotar(context, template_name):
        vistos.append((template_name, context))
        return original(context=context, template_name=template_name)

    monkeypatch.setattr(printer, 'create_pdf', anotar)
    return vistos


def guardar_diseno(web, empresa, datos):  # noqa: F811
    r = web.post(URL, {'empresa': empresa.pk, **datos})
    assert r.status_code == 302, r.status_code
    return leer(empresa, lambda: DisenoFactura.objects.get(company=empresa))


def copia_esperada(datos):
    copia = {'id': datos['style'], 'version': 1, 'primary': datos['primary'], 'secondary': datos['secondary']}
    if 'fuente' in datos:
        copia.update(version=2, fuente=datos['fuente'], encabezado=datos['encabezado'], pie_comercial=datos['pie_comercial'])
    return copia


def xml_sin_firma(xml):
    raiz = etree.fromstring(xml.encode('utf-8'))
    for firma in raiz.iter(DS):
        firma.getparent().remove(firma)
    return etree.tostring(raiz, method='c14n')


def contenido(campo):
    with campo.open('rb') as f:
        return f.read()


def cupo(empresa):  # noqa: F811
    p = periodo(empresa)
    estados = sorted(QuotaReservation.objects.filter(company=empresa).values_list('status', flat=True))
    return p.documents_used, p.documents_reserved, estados


# ---------------------------------------------------------------- 1) emisión: copia en la primera firma y flujo fiscal

FLUJOS = {
    # flujo: (respuestas de la primera emisión, estado tras la primera emisión)
    'autorizado': (([], ['AUTORIZADO']), 'authorized'),
    'devuelta': (([('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])], []), 'returned'),
    'no-autorizado': (([], ['NO AUTORIZADO']), 'not_authorized'),
    'en-proceso': (([], []), 'in_process'),
}
ESCENARIOS = {'sin-diseno': (None, None), 'v1': (V1_A, V1_B), 'v2': (V2_A, V2_B)}


@pytest.mark.parametrize('escenario', ESCENARIOS)
@pytest.mark.parametrize('flujo', FLUJOS)
def test_copia_en_la_primera_firma_y_flujo_fiscal_igual(piloto, web, empresa, comprador, producto, sri, contextos,  # noqa: F811
                                                       flujo, escenario):
    primero, despues = ESCENARIOS[escenario]
    (recepcion, autorizacion), estado1 = FLUJOS[flujo]
    if primero:
        diseno = guardar_diseno(web, empresa, primero)
        assert diseno.version == (2 if escenario == 'v2' else 1)
    sri.respuestas_recepcion, sri.respuestas_autorizacion = list(recepcion), list(autorizacion)
    vender(web, comprador, producto)
    venta = venta_de(empresa, 271)
    assert venta.status == estado1, venta.status
    esperada = copia_esperada(primero) if primero else None
    assert venta.ride_diseno == esperada
    firmado1, clave1, fecha1 = venta.xml_signed, venta.access_code, venta.emission_date
    cupo1 = cupo(empresa)
    if despues:   # el comercio cambia su diseño antes del reintento
        guardar_diseno(web, empresa, despues)
    if estado1 != 'authorized':
        sri.respuestas_autorizacion = ['AUTORIZADO']
        accion(web, 'generate_invoice', venta)
        refrescar(venta)
    assert venta.status == 'authorized' and venta.pdf_authorized and venta.xml_authorized
    assert venta.ride_diseno == esperada                       # el reintento no cambia la copia
    assert venta.access_code == clave1 and venta.emission_date == fecha1
    estilos = [c.get('ride_style') for p, c in contextos if p == FACTURA]
    assert estilos == [ride_styles.context_from_copy(esperada) if esperada else None]   # RIDE con la copia de la 1.ª firma
    xmls = [firmado1, venta.xml_signed, contenido(venta.xml_authorized).decode('utf-8')]
    for valor in [v for d in (primero or {}, despues or {}) for v in d.values()] + ['ride', 'fuente', 'encabezado']:
        for xml in xmls:
            assert valor not in xml, (valor, flujo, escenario)
    texto = re.sub(r'\s+', ' ', texto_del_pdf(contenido(venta.pdf_authorized)))
    if escenario == 'v2':
        assert 'Encabezado comercial A' in texto and 'Pie comercial A' in texto and 'comercial B' not in texto
    # la siguiente factura: siguiente secuencial y, con diseño, el diseño nuevo
    sri.respuestas_recepcion, sri.respuestas_autorizacion = [], ['AUTORIZADO']
    vender(web, comprador, producto)
    otra = venta_de(empresa, 272)
    assert otra.ride_diseno == (copia_esperada(despues) if despues else None)
    RESULTADOS[(flujo, escenario)] = {
        'clave': venta.access_code, 'fecha': venta.emission_date, 'secuencial': venta.voucher_number,
        'xml_sin_firma': xml_sin_firma(venta.xml_signed), 'xml_sin_firma_primera': xml_sin_firma(firmado1),
        'recepciones': len(sri.recepciones), 'cupo_tras_primera': cupo1, 'cupo_final': cupo(empresa),
        'siguiente': (otra.voucher_number, otra.access_code, xml_sin_firma(otra.xml_signed)),
        'texto_fiscal': texto.replace('Encabezado comercial A', '').replace('Pie comercial A', ''),
    }


def test_zz_clave_fecha_secuencial_xml_y_cupo_iguales_con_y_sin_diseno():
    if not RESULTADOS:
        pytest.skip('compara lo que dejan las pruebas de arriba: no corre sola')
    assert len(RESULTADOS) == len(FLUJOS) * len(ESCENARIOS), sorted(RESULTADOS)
    for flujo in FLUJOS:
        base = RESULTADOS[(flujo, 'sin-diseno')]
        for escenario in ('v1', 'v2'):
            otro = RESULTADOS[(flujo, escenario)]
            for campo in ('clave', 'fecha', 'secuencial', 'xml_sin_firma', 'xml_sin_firma_primera', 'recepciones',
                          'cupo_tras_primera', 'cupo_final', 'siguiente'):
                assert otro[campo] == base[campo], (flujo, escenario, campo)


# ---------------------------------------------------------------- 2) regenerar_ride y fidelidad con textos comerciales

def regenerar(empresa, *args):  # noqa: F811
    salida = StringIO()
    call_command('regenerar_ride', '--empresa', empresa.ruc, *args, stdout=salida)
    return salida.getvalue()


def emitir_con(web, empresa, comprador, producto, sri, datos):  # noqa: F811
    User.objects.filter(pk=comprador.user_id).update(names='IMPORTADORA ORIGINAL S.A.')
    if datos:
        guardar_diseno(web, empresa, datos)
    sri.respuestas_autorizacion = ['AUTORIZADO']
    vender(web, comprador, producto, cantidad=3)
    venta = venta_de(empresa, 271)
    assert venta.status == 'authorized' and venta.pdf_authorized
    return venta


FISCALES = {
    'style': 'clasico', 'primary': '#CA462C', 'secondary': '#E5F1F6', 'fuente': 'original',
    'encabezado': 'RUC 0999999999001 · AUTORIZACIÓN ' + '1' * 49,
    'pie_comercial': 'TOTAL 0,01 · OTRA EMPRESA DE PRUEBA S.A. · FACTURA 001-001-000000999 · IVA 0,00',
}


def test_textos_fiscales_se_aceptan_y_salen_en_el_ride(settings, piloto, web, empresa, comprador, producto, sri):  # noqa: F811
    settings.FPA_RUC_PROVEEDOR = RUC_FIJO      # como en producción: el RUC del XML es el del pie fijo
    venta = emitir_con(web, empresa, comprador, producto, sri, FISCALES)
    assert venta.ride_diseno['encabezado'] == FISCALES['encabezado']
    texto = re.sub(r'\s+', ' ', texto_del_pdf(contenido(venta.pdf_authorized)))
    assert FISCALES['encabezado'] in texto and FISCALES['pie_comercial'] in texto
    # sin cambios de datos: la comprobación de fidelidad no da falsos positivos
    assert diferencias(contenido(venta.pdf_authorized), contenido(venta.xml_authorized)) == []
    assert 'fieles 1, con diferencias 0' in regenerar(empresa)


@pytest.mark.parametrize('con_texto', [False, True])
def test_texto_comercial_no_oculta_un_cambio_posterior(settings, piloto, web, empresa, comprador,  # noqa: F811
                                                       producto, sri, tmp_path, con_texto):
    """El comercio pone sus propios datos en el pie (lo habitual). Después de autorizar cambia su razón social: el RIDE
    regenerado ya no coincide con el XML autorizado, y el texto comercial no debe esconderlo."""
    settings.FPA_RUC_PROVEEDOR = RUC_FIJO
    datos = {**V2_A, 'pie_comercial': f'{empresa.business_name} · Matriz: {empresa.main_address}' if con_texto else ''}
    venta = emitir_con(web, empresa, comprador, producto, sri, datos)
    leer(empresa, lambda: Company.objects.filter(pk=empresa.pk).update(business_name='RAZON SOCIAL NUEVA S.A.',
                                                                      main_address='Dirección nueva 999'))
    salida = regenerar(empresa, '--aplicar', '--respaldo', str(tmp_path))
    nueva = leer(empresa, lambda: Sale.objects.get(pk=venta.pk))
    assert 'no coincide razón social del emisor' in salida, salida
    assert 'fieles 0, con diferencias 1, aplicadas 0' in salida, salida
    assert nueva.pdf_authorized.name == venta.pdf_authorized.name


# ---------------------------------------------------------------- 3) A4 y correo: los bytes guardados

def test_a4_y_correo_entregan_los_bytes_guardados_con_copia_v2(piloto, web, empresa, comprador, producto, sri,  # noqa: F811
                                                              contextos):
    leer(empresa, lambda: Client.objects.filter(pk=comprador.pk).update(send_email_invoice=True))
    User.objects.filter(pk=comprador.user_id).update(email='comprador@example.com')
    guardar_diseno(web, empresa, V2_A)
    sri.respuestas_autorizacion = ['AUTORIZADO']
    vender(web, comprador, producto)
    venta = venta_de(empresa, 271)
    assert venta.status == 'authorized_and_sent_by_email' and venta.ride_diseno == copia_esperada(V2_A)
    guardado = contenido(venta.pdf_authorized)
    adjuntos = [c for nombre, c, _ in mail.outbox[0].attachments if nombre.endswith('.pdf')]
    assert adjuntos == [guardado]
    guardar_diseno(web, empresa, V2_B)   # cambiar el diseño no toca el PDF guardado
    contextos.clear()
    for _ in range(2):
        r = web.get(A4.format(venta.pk))
        assert r.status_code == 302 and r['Location'] == venta.get_pdf_authorized()
        descarga = web.get(r['Location'])
        cuerpo = b''.join(descarga.streaming_content) if descarga.streaming else descarga.content
        assert descarga['Content-Type'] == 'application/pdf' and cuerpo == guardado
    assert contextos == []   # no se regeneró nada
    # reenvío del correo desde el listado (si existe la acción) o directo: mismos bytes
    mail.outbox.clear()
    with company_context(empresa):
        fresca = Sale.objects.get(pk=venta.pk)
        SRI().notify_by_email(instance=fresca, company=fresca.company, client=fresca.client)
    assert len(mail.outbox) == 1 and [c for n, c, _ in mail.outbox[0].attachments if n.endswith('.pdf')] == [guardado]
    # si faltara el archivo, la A4 lo genera con la COPIA (no con el diseño actual)
    venta.pdf_authorized.storage.delete(venta.pdf_authorized.name)
    contextos.clear()
    r = web.get(A4.format(venta.pk))
    assert r.status_code == 302
    assert [c['ride_style'] for p, c in contextos if p == FACTURA] == [ride_styles.context_from_copy(copia_esperada(V2_A))]


def test_disenos_v1_migrados_siguen_dando_copias_v1(piloto, empresa):  # noqa: F811
    """Fila guardada con la v1 (antes de 0006): la migración le pone los valores por defecto y version sigue en 1."""
    with company_context(empresa):
        DisenoFactura.objects.create(company=empresa, estilo='banda', color_principal='#112233',
                                     color_secundario='#DDEEFF')
        assert dz.diseno_efectivo(empresa) == {'id': 'banda', 'version': 1, 'primary': '#112233', 'secondary': '#DDEEFF'}


# ---------------------------------------------------------------- textos, marca de agua y aviso de la pantalla

@pytest.mark.parametrize('caracter', ['\n', '\x7f', '\u0085', '\u009b', '\u2028', '\u2029', '\u202e', '\u2066'])
def test_textos_comerciales_en_una_sola_linea(caracter):
    for campo in ('encabezado', 'pie_comercial'):
        datos, error = dz.validar('banda', '#112233', '#445566', personalizacion={campo: f'a{caracter}b'})
        assert datos is None and error
        assert ride_styles.opciones_personalizacion(**{campo: f'a{caracter}b'})[campo] == 'a b'


def test_la_marca_de_la_muestra_no_hereda_la_tipografia():
    css = (Path(__file__).resolve().parent.parent / 'static/css/ride_personalizado.css').read_text(encoding='utf-8')
    assert re.search(r'\.fp-ride-muestra\s*\{\s*font-family: Arial', css)


def test_aviso_mientras_el_comercio_sigue_en_el_diseno_anterior(piloto, web, empresa):  # noqa: F811
    aviso = 'versión anterior de este diseño'
    assert aviso not in web.get(URL).content.decode()      # sin diseño guardado
    guardar_diseno(web, empresa, V1_A)
    assert aviso in web.get(URL).content.decode()
    guardar_diseno(web, empresa, V2_A)
    assert aviso not in web.get(URL).content.decode()
