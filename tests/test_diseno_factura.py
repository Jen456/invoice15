"""«Configuración → Diseño de factura» (piloto): cinco plantillas de FacturaPorAquí, colores por comercio, vista previa con
una factura de MUESTRA en memoria y copia del diseño en cada factura nueva (Sale.ride_diseno) en su primera firma.

Comercios, compradores, claves y firmas ficticios: el SRI va simulado (SRIFalso de test_emision_sri, sin red) y la firma usa
el .p12 de prueba que genera test_firma_sri. El piloto (FPA_DISENO_FACTURA_PILOTO) está apagado en conftest: las pruebas que
lo necesitan lo encienden con el fixture `piloto`.
"""
import hashlib
import importlib
import re
from datetime import date
from pathlib import Path

import pypdfium2 as pdfium
import pytest
import zxingcpp
from django.conf import settings as ajustes
from django.contrib.auth.models import Group
from django.contrib.messages import get_messages
from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.template import engines
from django.template.loader import get_template, render_to_string
from django.test import Client as Navegador

from core.comprobantes import ride_muestra, ride_styles
from core.configuracion import diseno as dz
from core.configuracion.models import DisenoFactura
from core.pos.models import Client, Receipt, Sale
from core.pos.utilities import printer
from core.pos.utilities.sri import SRI
from core.security.models import Module
from core.suscripciones.models import QuotaReservation, SubscriptionPeriod
from core.tenancy.context import company_context
from core.tenancy.models import (ROLE_ACCOUNTANT, ROLE_ADMIN, ROLE_OWNER, ROLE_READONLY, ROLE_SELLER, AuditLog,
                                 Membership)
from core.tenancy.pestanas import EMPRESA_CAMBIADA
from core.user.models import User
from tests import helpers
from tests.fabricas_sri import clave as clave_sri
from tests.test_emision_sri import (accion, comprador, dueno, empresa, leer, p12, producto, refrescar, sri,  # noqa: F401
                                    vender, venta_de, web)
from tests.test_ride_diseno import CLAVE_DEMO, PROVEEDOR_DEMO, TEMPLATES, contexto_demo

pytestmark = pytest.mark.django_db
URL = '/configuracion/diseno-factura/'
MUESTRA = URL + 'muestra.pdf'
A4 = '/pos/sale/admin/print/a4/{}/'
FACTURA = TEMPLATES['factura']
# sha256 de core/pos/templates/sale/format/invoice.html en 9584308 (producción antes del diseño de factura).
HASH_PLANTILLA_PRODUCCION = 'a06b18a3e075ca0f96b825d01355bf402247bbef729fe2e29f31336f8dc2a9f9'
MARCA = 'MUESTRA · SIN VALIDEZ TRIBUTARIA'
COMBINACIONES = ((None, None), ('#FFFFFF', '#000000'), ('#000000', '#FFFFFF'))   # paleta de la plantilla, claro/oscuro
INVALIDOS = (
    ('desconocido', '#CA462C', '#E5F1F6'),
    ('', '#CA462C', '#E5F1F6'),
    (None, '#CA462C', '#E5F1F6'),
    ('clasico', '#12345', '#E5F1F6'),
    ('clasico', 'red', '#E5F1F6'),
    ('clasico', '#GGGGGG', '#E5F1F6'),
    ('clasico', '#000000;}body{', '#E5F1F6'),
    ('banda', '#603D80', '#000000;}body{display:none}'),
    ('banda', '#603D80', '#ECDCF8\n'),
    ('banda', '#603D80', None),
)


@pytest.fixture
def piloto(settings):
    settings.FPA_DISENO_FACTURA_PILOTO = ['*']   # «*» vale solo en local y en las pruebas automáticas


@pytest.fixture
def rojo(db):
    return helpers.crear_empresa('COMERCIO ROJO')


@pytest.fixture
def azul(db):
    return helpers.crear_empresa('COMERCIO AZUL')


def entrar(usuario, empresa):
    navegador = Navegador()
    helpers.iniciar_sesion(navegador, usuario, empresa=empresa)
    return navegador


def guardado(empresa):
    return leer(empresa, lambda: DisenoFactura.objects.filter(company=empresa).first())


def enviar(navegador, empresa, estilo, principal, secundario, **extra):
    datos = {'empresa': empresa.pk, **extra}
    for nombre, valor in (('style', estilo), ('primary', principal), ('secondary', secundario)):
        if valor is not None:
            datos[nombre] = valor
    return navegador.post(URL, datos)


def disenar(empresa, estilo='banda', principal='#112233', secundario='#DDEEFF'):
    with company_context(empresa):
        DisenoFactura.objects.update_or_create(company=empresa, defaults={
            'estilo': estilo, 'color_principal': principal, 'color_secundario': secundario})


def plano(texto):
    return ' '.join(texto.split())


def textos_pdf(contenido):
    with pdfium.PdfDocument(contenido) as documento:
        return [plano(pagina.get_textpage().get_text_range()) for pagina in documento]


def claves_leidas(contenido):
    with pdfium.PdfDocument(contenido) as documento:
        imagen = documento[0].render(scale=300 / 72, no_smoothimage=True).to_pil()
    return [c.text for c in zxingcpp.read_barcodes(imagen)]


def sin_pie(textos):
    """Texto de todas las páginas sin el pie (proveedor del sistema y «n / m»), que se repite en cada página."""
    salida = []
    for texto in textos:
        for dato in ('Sistema de facturación electrónica:', 'RUC Proveedor:', ' · ', *PROVEEDOR_DEMO.values()):
            texto = texto.replace(dato, ' ')
        salida.append(re.sub(r'(?<!\S)\d+ / \d+(?!\S)', ' ', texto))
    return plano(' '.join(salida))


def fuente_sin_diseno():
    """Fuente de la plantilla de la factura sin lo que añadió el diseño de factura (todo bajo ride_style / ride_muestra)."""
    fuente = Path(get_template(FACTURA).origin.name).read_text(encoding='utf-8')
    fuente = re.sub(r'\{% comment %\}.*?\{% endcomment %\}', '', fuente, flags=re.S)
    return re.sub(r'\{% if ride_(?:style|muestra) %\}.*?\{% endif %\}', '', fuente, flags=re.S)


@pytest.fixture
def contextos(monkeypatch):
    """Contextos con que se arma cada PDF (plantilla, ride_style), sin dejar de generarlo."""
    vistos = []
    original = printer.create_pdf

    def anotar(context, template_name):
        vistos.append((template_name, context))
        return original(context=context, template_name=template_name)

    monkeypatch.setattr(printer, 'create_pdf', anotar)
    return vistos


# ---------------------------------------------------------------- estilos, validación y clave ficticia

class TestEstilos:

    def test_cinco_estilos_y_lecturas_normalizadas(self):
        assert list(ride_styles.STYLES) == ['clasico', 'corporativo', 'minimalista', 'banda', 'compacto']
        assert [s['id'] for s in ride_styles.catalog()] == list(ride_styles.STYLES)
        assert ride_styles.normalize('banda', '#abcdef', 'red') == {'id': 'banda', 'version': 1, 'primary': '#ABCDEF',
                                                                     'secondary': '#ECDCF8'}
        assert ride_styles.normalize('<script>')['id'] == 'clasico'
        copia = {'id': 'compacto', 'version': 1, 'primary': '#000000;}body{', 'secondary': '#FFFFFF'}
        assert ride_styles.context_from_copy(copia) == ride_styles.template_context('compacto', None, '#FFFFFF')
        assert ride_styles.context_from_copy('no es una copia') is None

    @pytest.mark.parametrize('estilo, principal, secundario', INVALIDOS)
    def test_validar_rechaza_sin_corregir(self, estilo, principal, secundario):
        datos, error = dz.validar(estilo, principal, secundario)
        assert datos is None and error

    def test_validar_acepta_y_guarda_en_mayusculas(self):
        assert dz.validar('banda', '#abcdef', '#123456') == (
            {'estilo': 'banda', 'color_principal': '#ABCDEF', 'color_secundario': '#123456'}, None)

    def test_clave_ficticia_de_49_digitos_con_modulo_11(self):
        clave = ride_muestra.clave_ficticia('0999999999001', date(2026, 11, 8), '002', '003')
        assert len(clave) == 49 and clave.isdigit() and clave[-1] == SRI().compute_mod11(clave[:48])
        assert clave == clave_sri(fecha=date(2026, 11, 8), cod_doc='01', ruc='0999999999001', ambiente=1, estab='002',
                                  pto='003', secuencial='000000001', codigo='12345678', tipo_emision='1')
        assert ride_muestra.clave_ficticia('RUC-RARO', date(2026, 11, 8), '001', '001')[10:23] == '9999999999999'


# ---------------------------------------------------------------- plantilla del RIDE

class TestPlantilla:

    def test_sin_estilo_es_la_plantilla_de_produccion_byte_a_byte(self):
        fuente = fuente_sin_diseno()
        assert hashlib.sha256(fuente.encode('utf-8')).hexdigest() == HASH_PLANTILLA_PRODUCCION
        contexto = contexto_demo('factura')
        original = engines['django'].from_string(fuente).render(contexto)
        assert render_to_string(FACTURA, contexto) == original
        assert render_to_string(FACTURA, {**contexto, 'ride_style': None, 'ride_muestra': False}) == original
        for marca in ('ride_variants', '--ride-', 'ride-custom', 'MUESTRA', '<style>\n        body.fp-ride'):
            assert marca not in original

    def test_con_estilo_carga_la_hoja_y_los_colores_validados(self):
        contexto = {**contexto_demo('factura'), 'ride_style': ride_styles.template_context('banda', '#112233', '#445566')}
        html = render_to_string(FACTURA, contexto)
        assert 'css/ride_variants.css' in html and '--ride-primary: #112233;' in html and '--ride-secondary: #445566;' in html
        assert '<body class="fp-ride ride-custom ride-banda">' in html and MARCA not in html

    def test_las_otras_plantillas_no_cambian(self):
        for tipo, plantilla in TEMPLATES.items():
            if tipo == 'factura':
                continue
            contexto = {**contexto_demo(tipo), 'ride_style': ride_styles.template_context('banda'), 'ride_muestra': True}
            html = render_to_string(plantilla, contexto)
            assert 'ride_variants' not in html and 'ride-custom' not in html and MARCA not in html, tipo
            assert html == render_to_string(plantilla, contexto_demo(tipo)), tipo

    def test_cinco_estilos_claro_y_oscuro_mismo_texto_fiscal_y_clave_legible(self):
        original = create_pdf_demo()
        texto_original = textos_pdf(original)
        assert len(texto_original) == 1
        pdfs = set()
        for estilo in ride_styles.STYLES:
            for principal, secundario in COMBINACIONES:
                pdf = create_pdf_demo(ride_style=ride_styles.template_context(estilo, principal, secundario))
                assert textos_pdf(pdf) == texto_original, (estilo, principal, secundario)
                assert CLAVE_DEMO in claves_leidas(pdf), (estilo, principal, secundario)
                pdfs.add(pdf)
        assert len(pdfs) == 15

    def test_62_lineas_en_varias_paginas_con_cada_estilo(self):
        original = create_pdf_demo(cantidad=62, largo=True)
        paginas = textos_pdf(original)
        assert len(paginas) > 1 and 'P062' in ' '.join(paginas)
        for estilo in ride_styles.STYLES:
            pdf = create_pdf_demo(cantidad=62, largo=True, ride_style=ride_styles.template_context(estilo))
            textos = textos_pdf(pdf)
            assert len(textos) > 1, estilo
            assert sin_pie(textos) == sin_pie(paginas), estilo
            assert all(PROVEEDOR_DEMO['ruc'] in t for t in textos), estilo   # el pie del proveedor sigue en cada página
            assert CLAVE_DEMO in claves_leidas(pdf), estilo

    def test_la_marca_de_muestra_sale_en_cada_pagina_sin_tapar_la_clave(self):
        pdf = create_pdf_demo(cantidad=62, ride_style=ride_styles.template_context('corporativo'), ride_muestra=True)
        textos = textos_pdf(pdf)
        assert len(textos) > 1 and all(MARCA in t for t in textos)
        assert CLAVE_DEMO in claves_leidas(pdf) and all(CLAVE_DEMO in t for t in textos[:1])


def create_pdf_demo(cantidad=5, largo=False, **extra):
    return printer.create_pdf(context={**contexto_demo('factura', cantidad, largo=largo), **extra}, template_name=FACTURA)


# ---------------------------------------------------------------- piloto y menú

class TestPiloto:

    def test_regla_de_la_lista(self, settings, rojo, azul):
        settings.FPA_DISENO_FACTURA_PILOTO = []
        assert not dz.diseno_habilitado(rojo) and dz.diseno_efectivo(rojo) is None
        settings.FPA_DISENO_FACTURA_PILOTO = [f' {rojo.ruc} ']
        assert dz.diseno_habilitado(rojo) and not dz.diseno_habilitado(azul) and not dz.diseno_habilitado(None)
        assert dz.diseno_efectivo(rojo) is None   # en el piloto, sin diseño guardado: sin personalización
        disenar(rojo, 'minimalista', '#102030', '#A0B0C0')
        with company_context(rojo):
            assert dz.diseno_efectivo(rojo) == {'id': 'minimalista', 'version': 1, 'primary': '#102030', 'secondary': '#A0B0C0'}
        helpers.crear_empresa('COPIA DEL RUC', ruc=rojo.ruc)   # un RUC compartido no habilita
        assert not dz.diseno_habilitado(rojo)
        settings.FPA_DISENO_FACTURA_PILOTO = ['*']
        settings.FPA_ENTORNO = 'produccion'
        assert not dz.diseno_habilitado(azul)                 # «*» no vale en un despliegue
        settings.FPA_ENTORNO = 'pruebas_automaticas'
        assert dz.diseno_habilitado(azul)

    def test_conftest_lo_deja_apagado(self):
        # tests/conftest.py (diseno_piloto_apagado) lo apaga aunque el entorno exporte FPA_DISENO_FACTURA_PILOTO.
        assert ajustes.FPA_DISENO_FACTURA_PILOTO == []

    def test_apagado_oculta_el_menu_y_bloquea_las_urls(self, settings, rojo):
        settings.FPA_DISENO_FACTURA_PILOTO = []
        navegador = entrar(helpers.crear_usuario('duena.apagado', rojo, ROLE_OWNER), rojo)
        assert URL not in navegador.get('/dashboard/').content.decode()
        r = navegador.get(URL)
        assert r.status_code == 302 and r['Location'] == '/dashboard/'
        assert dz.MENSAJE_NO_DISPONIBLE in [str(m) for m in get_messages(r.wsgi_request)]
        assert enviar(navegador, rojo, 'banda', '#112233', '#445566').status_code == 404
        assert navegador.get(MUESTRA).status_code == 404
        assert guardado(rojo) is None and not AuditLog.objects.filter(action='diseno_factura_guardado').exists()
        settings.FPA_DISENO_FACTURA_PILOTO = [rojo.ruc]
        assert f'href="{URL}"' in navegador.get('/dashboard/').content.decode()
        assert navegador.get(URL).status_code == 200


# ---------------------------------------------------------------- acceso por rol y comercio

class TestAcceso:

    @pytest.mark.parametrize('rol', [ROLE_OWNER, ROLE_ADMIN])
    def test_propietario_y_administrador_editan(self, piloto, rojo, rol):
        usuario = helpers.crear_usuario(f'disena.{rol.lower()}', rojo, rol)
        navegador = entrar(usuario, rojo)
        assert f'href="{URL}"' in navegador.get('/dashboard/').content.decode()
        r = navegador.get(URL)
        assert r.status_code == 200 and r['X-Frame-Options'] == 'DENY'   # solo la muestra se deja enmarcar
        assert r.context['styles'] == ride_styles.catalog() and r.context['current'] == {**ride_styles.normalize('clasico'), **ride_styles.opciones_personalizacion()}
        assert r.context['form_error'] is None
        assert '%23CA462C' in r.context['preview_url'] and '#' not in r.context['preview_url']
        html = r.content.decode()
        for texto in ('plantillas de FacturaPorAquí', 'facturas <strong>nuevas</strong>', 'Abrir la muestra en PDF',
                      'target="_blank" rel="noopener"', f'name="empresa" value="{rojo.pk}"',
                      'id="fp-diseno-abrir" class="btn btn-outline-primary'):   # botón visible: en móviles no hay iframe
            assert texto in html, texto
        hoja = (Path(ajustes.BASE_DIR) / 'static/css/diseno_factura.css').read_text(encoding='utf-8')
        movil = re.search(r'@media \(max-width: 850px\) \{(.*?)\n\}', hoja, flags=re.S)
        assert movil and re.search(r'\.fp-diseno iframe \{ display: none; \}', movil.group(1))
        r = enviar(navegador, rojo, 'corporativo', '#102030', '#a0b0c0')
        assert r.status_code == 302 and r['Location'] == URL
        d = guardado(rojo)
        assert (d.estilo, d.color_principal, d.color_secundario, d.version, d.actualizado_por_id) == (
            'corporativo', '#102030', '#A0B0C0', 1, usuario.pk)
        assert navegador.get(URL).context['current'] == {
            **ride_styles.normalize('corporativo', '#102030', '#A0B0C0'), **ride_styles.opciones_personalizacion()}
        assert navegador.get(MUESTRA, {'style': 'corporativo'}).status_code == 200

    @pytest.mark.parametrize('rol', [ROLE_READONLY, ROLE_ACCOUNTANT, ROLE_SELLER])
    def test_consulta_contador_y_vendedor_no(self, piloto, rojo, rol):
        navegador = entrar(helpers.crear_usuario(f'sin.diseno.{rol.lower()}', rojo, rol), rojo)
        assert URL not in navegador.get('/dashboard/').content.decode()
        r = navegador.get(URL)
        assert r.status_code == 302 and r['Location'] != URL
        assert enviar(navegador, rojo, 'banda', '#112233', '#445566').status_code == 403
        assert navegador.get(MUESTRA).status_code == 403
        assert guardado(rojo) is None

    def test_cambio_de_comercio_en_la_misma_sesion(self, piloto, rojo, azul):
        usuario = helpers.crear_usuario('duena.de.dos', rojo, ROLE_OWNER)
        Membership.objects.create(user=usuario, company=azul, group=Group.objects.get(name=ROLE_OWNER))
        navegador = entrar(usuario, rojo)
        assert enviar(navegador, rojo, 'banda', '#AA0000', '#FFEEEE').status_code == 302
        navegador.post('/empresas/cambiar/', {'company': azul.id})
        assert navegador.session['company_id'] == azul.id
        assert navegador.get(URL).context['current'] == {**ride_styles.normalize('clasico'), **ride_styles.opciones_personalizacion()}
        # Un id de empresa en el formulario se ignora: se guarda en la empresa de la sesión.
        r = enviar(navegador, azul, 'minimalista', '#0000AA', '#EEEEFF', company=rojo.pk, company_id=rojo.pk)
        assert r.status_code == 302
        assert (guardado(rojo).estilo, guardado(azul).estilo) == ('banda', 'minimalista')
        # Pestaña que se abrió con rojo, sin guardar nada en ninguna. El formulario normal vuelve a la pantalla con el aviso
        # (no una página con JSON); fetch/XHR recibe 409 JSON; la vista previa (iframe o pestaña nueva), 409 con el aviso en
        # texto, y en JSON si lo pide.
        r = enviar(navegador, rojo, 'compacto', '#000000', '#FFFFFF')
        assert r.status_code == 302 and r['Location'] == URL
        assert EMPRESA_CAMBIADA in [str(m) for m in get_messages(r.wsgi_request)]
        assert EMPRESA_CAMBIADA in navegador.get(URL).content.decode()
        for cabecera in ({'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}, {'HTTP_ACCEPT': 'application/json'}):
            r = navegador.post(URL, {'empresa': rojo.pk, 'style': 'compacto', 'primary': '#000000',
                                     'secondary': '#FFFFFF'}, **cabecera)
            assert r.status_code == 409 and r.json()['codigo'] == 'empresa_cambiada'
        r = navegador.get(MUESTRA, {'empresa': rojo.pk, 'style': 'compacto'})
        assert r.status_code == 409 and r['Content-Type'].startswith('text/plain')
        assert r.content.decode() == EMPRESA_CAMBIADA and r['X-Frame-Options'] == 'SAMEORIGIN'
        r = navegador.get(MUESTRA, {'empresa': rojo.pk}, HTTP_ACCEPT='application/json')
        assert r.status_code == 409 and r.json()['codigo'] == 'empresa_cambiada'
        assert (guardado(rojo).estilo, guardado(azul).estilo) == ('banda', 'minimalista')
        assert guardado(azul).color_principal == '#0000AA' and guardado(rojo).color_principal == '#AA0000'
        texto = ' '.join(textos_pdf(navegador.get(MUESTRA).content))
        assert azul.business_name in texto and rojo.business_name not in texto
        navegador.post('/empresas/cambiar/', {'company': rojo.id})
        assert navegador.get(URL).context['current']['id'] == 'banda'
        texto = ' '.join(textos_pdf(navegador.get(MUESTRA).content))
        assert rojo.business_name in texto and azul.business_name not in texto

    def test_cada_empresa_ve_solo_su_diseno(self, rojo, azul):
        disenar(rojo)
        with company_context(azul):
            assert not DisenoFactura.objects.exists()
            visibles = DisenoFactura.all_companies.filter(company=rojo).count()
        assert visibles == (0 if connection.vendor == 'postgresql' else 1)   # en PostgreSQL además rige la RLS


# ---------------------------------------------------------------- guardado

class TestGuardado:

    @pytest.mark.parametrize('estilo, principal, secundario', INVALIDOS)
    def test_post_invalido_no_guarda_nada(self, piloto, rojo, estilo, principal, secundario):
        navegador = entrar(helpers.crear_usuario('duena.invalida', rojo, ROLE_OWNER), rojo)
        assert enviar(navegador, rojo, 'compacto', '#21635D', '#D6EAE7').status_code == 302
        antes = (guardado(rojo).estilo, guardado(rojo).color_principal, guardado(rojo).color_secundario)
        registros = AuditLog.objects.filter(action='diseno_factura_guardado').count()
        r = enviar(navegador, rojo, estilo, principal, secundario)
        assert r.status_code == 400 and r.context['form_error'] and r.context['form_error'] in r.content.decode()
        assert (guardado(rojo).estilo, guardado(rojo).color_principal, guardado(rojo).color_secundario) == antes
        assert AuditLog.objects.filter(action='diseno_factura_guardado').count() == registros
        assert ';' not in r.context['preview_url'] and '{' not in r.content.decode().split('fp-diseno-grid')[1].split('</form>')[0]

    def test_post_invalido_sin_diseno_previo_no_crea_fila(self, piloto, rojo):
        navegador = entrar(helpers.crear_usuario('duena.sin.fila', rojo, ROLE_OWNER), rojo)
        assert enviar(navegador, rojo, 'clasico', '#12345', '#E5F1F6').status_code == 400
        assert guardado(rojo) is None

    def test_personalizacion_se_guarda_por_empresa_y_llega_a_la_copia(self, piloto, rojo, azul):
        navegador = entrar(helpers.crear_usuario('duena.personaliza', rojo, ROLE_OWNER), rojo)
        textos = {'fuente': 'dejavu-serif', 'encabezado': 'Tecnología y soluciones', 'pie_comercial': 'Gracias por tu compra'}
        r = enviar(navegador, rojo, 'banda', '#112233', '#445566', **textos)
        assert r.status_code == 302
        assert guardado(rojo).version == 2 and guardado(azul) is None
        assert all(navegador.get(URL).context['current'][campo] == valor for campo, valor in textos.items())
        with company_context(rojo):
            assert dz.diseno_efectivo(rojo) == {**ride_styles.normalize('banda', '#112233', '#445566'),
                                               'version': 2, **textos}
        for invalido in ({'fuente': 'url(otro)'}, {'encabezado': 'a' * 101}, {'pie_comercial': 'primera\nsegunda'}):
            assert enviar(navegador, rojo, 'banda', '#112233', '#445566', **invalido).status_code == 400
        assert guardado(rojo).pie_comercial == textos['pie_comercial']

    def test_cada_guardado_queda_en_la_auditoria(self, piloto, rojo):
        navegador = entrar(helpers.crear_usuario('duena.auditada', rojo, ROLE_OWNER), rojo)
        enviar(navegador, rojo, 'banda', '#603d80', '#ECDCF8')
        enviar(navegador, rojo, 'compacto', '#000000', '#FFFFFF')
        registros = AuditLog.objects.filter(action='diseno_factura_guardado', company=rojo).order_by('pk')
        base = {'version': 1, **ride_styles.opciones_personalizacion()}
        banda = {**base, 'estilo': 'banda', 'color_principal': '#603D80', 'color_secundario': '#ECDCF8'}
        assert [r.detail for r in registros] == [
            {'antes': None, 'despues': banda},
            {'antes': banda, 'despues': {**base, 'estilo': 'compacto', 'color_principal': '#000000', 'color_secundario': '#FFFFFF'}}]
        assert leer(rojo, lambda: DisenoFactura.objects.filter(company=rojo).count()) == 1   # uno por empresa


# ---------------------------------------------------------------- vista previa

class TestMuestra:

    def test_pdf_con_cabeceras_marca_y_sin_crear_nada(self, piloto, rojo):
        helpers.configurar_facturacion(rojo, estab='002', punto='003', ultimo_factura=40)
        navegador = entrar(helpers.crear_usuario('duena.muestra', rojo, ROLE_OWNER), rojo)

        def estado():
            with company_context(rojo):
                return (Sale.objects.count(), sorted(Receipt.objects.values_list('pk', 'sequence')),
                        QuotaReservation.objects.count(), DisenoFactura.objects.count(),
                        list(SubscriptionPeriod.objects.filter(company=rojo).values_list('documents_used', 'documents_reserved')),
                        sorted(str(p) for p in Path(ajustes.MEDIA_ROOT).rglob('*')))

        antes = estado()
        r = navegador.get(MUESTRA, {'style': 'banda', 'primary': '#112233', 'secondary': '#445566'})
        assert r.status_code == 200 and r['Content-Type'] == 'application/pdf'
        assert r['Content-Disposition'].startswith('inline') and r['Cache-Control'] == 'private, no-store'
        assert r['X-Frame-Options'] == 'SAMEORIGIN'
        textos = textos_pdf(r.content)
        assert all(MARCA in t for t in textos)
        texto = ' '.join(textos)
        for dato in (rojo.business_name, rojo.ruc, rojo.main_address, '002-003-000000001', 'PRUEBAS',
                     'COMPRADOR FICTICIO DE MUESTRA', 'Pendiente de autorización'):
            assert dato in texto, dato
        claves = claves_leidas(r.content)
        assert len(claves) == 1 and len(claves[0]) == 49 and claves[0] in texto and claves[0][23] == '1'
        assert estado() == antes
        # Parámetros dañados: se normalizan (solo lectura), nunca llegan al CSS.
        for consulta in ({'style': '<script>', 'primary': '#000000;}body{', 'secondary': 'red'}, {}):
            r = navegador.get(MUESTRA, consulta)
            assert r.status_code == 200 and r.content[:5] == b'%PDF-'
        assert estado() == antes

    def test_cinco_muestras_con_textos_y_pie_fijo(self, piloto, rojo):
        navegador = entrar(helpers.crear_usuario('duena.textos', rojo, ROLE_OWNER), rojo)
        for estilo in ride_styles.STYLES:
            r = navegador.get(MUESTRA, {'style': estilo, 'fuente': 'dejavu-serif',
                                        'encabezado': 'Marca de muestra', 'pie_comercial': 'Gracias por su compra',
                                        'proveedor_fijo': 'No debe aparecer'})
            assert r.status_code == 200
            texto = ' '.join(textos_pdf(r.content))
            assert 'Marca de muestra' in texto and 'Gracias por su compra' in texto
            assert 'FACTURAPORAQUI · RUC Proveedor: 0941609729001' in texto
            assert 'soporte@facturaporaqui.com · Milagro, Manta y Rumiñahui' in texto
            assert 'No debe aparecer' not in texto

    def test_la_muestra_usa_el_estilo_pedido(self, piloto, rojo, contextos):
        navegador = entrar(helpers.crear_usuario('duena.estilo', rojo, ROLE_OWNER), rojo)
        navegador.get(MUESTRA, {'style': 'compacto', 'primary': '#ABCDEF', 'secondary': '#000000;}'})
        plantilla, contexto = contextos[-1]
        assert plantilla == FACTURA and contexto['ride_muestra'] is True
        assert contexto['ride_style'] == ride_styles.context_from_copy({
            **ride_styles.normalize('compacto', '#ABCDEF', None), 'version': 2})


# ---------------------------------------------------------------- copia del diseño en la factura

class TestCopiaEnLaFactura:

    def test_fuera_del_piloto_preparar_no_fija_copia(self, web, empresa, comprador, producto, sri, contextos):
        disenar(empresa)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto)
        venta = venta_de(empresa, 271)
        assert venta.status == 'authorized' and venta.ride_diseno is None and venta.pdf_authorized
        assert [c.get('ride_style') for p, c in contextos if p == FACTURA] == [None]   # RIDE original

    def test_en_el_piloto_sin_diseno_no_hay_copia(self, piloto, web, empresa, comprador, producto, sri):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto)
        assert venta_de(empresa, 271).ride_diseno is None

    def test_copia_en_la_primera_firma_y_estable_en_el_reintento(self, piloto, web, empresa, comprador, producto, sri,
                                                                  contextos):
        disenar(empresa, 'banda', '#112233', '#DDEEFF')
        sri.respuestas_recepcion = [('DEVUELTA', [('35', 'ARCHIVO NO CUMPLE ESTRUCTURA XML')])]
        vender(web, comprador, producto)
        venta = venta_de(empresa, 271)
        copia = {'id': 'banda', 'version': 1, 'primary': '#112233', 'secondary': '#DDEEFF'}
        assert venta.status == 'returned' and venta.ride_diseno == copia and venta.signed_at is not None
        for valor in ('#112233', '#DDEEFF', 'banda', 'ride'):
            assert valor not in venta.xml_signed   # solo presentación: nada en el XML firmado
        clave = venta.access_code
        disenar(empresa, 'compacto', '#000000', '#FFFFFF')   # el comercio cambia su diseño antes del reintento
        sri.respuestas_autorizacion = ['AUTORIZADO']
        assert accion(web, 'generate_invoice', venta)['resp'] is True
        refrescar(venta)
        assert venta.status == 'authorized' and venta.access_code == clave and venta.ride_diseno == copia
        estilos = [c['ride_style'] for p, c in contextos if p == FACTURA]
        assert estilos == [ride_styles.template_context('banda', '#112233', '#DDEEFF')]
        # La siguiente factura sí toma el diseño nuevo.
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto)
        assert venta_de(empresa, 272).ride_diseno == {'id': 'compacto', 'version': 1, 'primary': '#000000',
                                                      'secondary': '#FFFFFF'}

    def test_historica_sin_copia_mismo_html_que_hoy(self, piloto, web, empresa, comprador, producto, sri, contextos):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto)
        venta = venta_de(empresa, 271)
        assert venta.ride_diseno is None
        disenar(empresa)   # diseñar después no cambia las ya emitidas
        contextos.clear()
        with company_context(empresa):
            pdf = venta.ride_pdf()
            plantilla, contexto = contextos[-1]
            assert plantilla == FACTURA and contexto['ride_style'] is None
            html = render_to_string(FACTURA, contexto)
            assert html == engines['django'].from_string(fuente_sin_diseno()).render(contexto)
        assert 'ride_variants' not in html and pdf[:5] == b'%PDF-'

    def test_ride_pdf_con_copia_usa_el_estilo_y_el_mismo_texto(self, piloto, web, empresa, comprador, producto, sri):
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto)
        venta = venta_de(empresa, 271)
        with company_context(empresa):
            original = venta.ride_pdf()
            venta.ride_diseno = {'id': 'minimalista', 'version': 1, 'primary': '#000000', 'secondary': '#FFFFFF'}
            con_estilo = venta.ride_pdf()
        assert textos_pdf(con_estilo) == textos_pdf(original) and con_estilo != original
        assert venta.access_code in claves_leidas(con_estilo)


# ---------------------------------------------------------------- archivo guardado: descarga, correo y regeneración

class TestArchivoGuardado:

    def test_descarga_a4_y_correo_son_los_bytes_guardados(self, piloto, web, empresa, comprador, producto, sri):
        leer(empresa, lambda: Client.objects.filter(pk=comprador.pk).update(send_email_invoice=True))
        User.objects.filter(pk=comprador.user_id).update(email='comprador@example.com')
        disenar(empresa, 'corporativo', '#174886', '#C8DDF4')
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto)
        venta = venta_de(empresa, 271)
        assert venta.status == 'authorized_and_sent_by_email' and venta.ride_diseno['id'] == 'corporativo'
        with venta.pdf_authorized.open('rb') as archivo:
            guardado_bytes = archivo.read()
        adjuntos = [contenido for nombre, contenido, _ in mail.outbox[0].attachments if nombre.endswith('.pdf')]
        assert adjuntos == [guardado_bytes]
        disenar(empresa, 'compacto', '#000000', '#FFFFFF')   # cambiar el diseño no toca el PDF guardado
        for _ in range(2):
            r = web.get(A4.format(venta.pk))
            assert r.status_code == 302 and r['Location'] == venta.get_pdf_authorized()
            descarga = web.get(r['Location'])
            cuerpo = b''.join(descarga.streaming_content) if descarga.streaming else descarga.content
            assert descarga['Content-Type'] == 'application/pdf' and cuerpo == guardado_bytes
        assert leer(empresa, lambda: Sale.objects.get(pk=venta.pk).pdf_authorized.name) == venta.pdf_authorized.name

    def test_regenerar_ride_en_ensayo_con_copia_es_fiel(self, piloto, web, empresa, comprador, producto, sri, contextos,
                                                        tmp_path):
        from io import StringIO
        User.objects.filter(pk=comprador.user_id).update(names='IMPORTADORA ORIGINAL S.A.')
        disenar(empresa, 'banda', '#603D80', '#ECDCF8')
        sri.respuestas_autorizacion = ['AUTORIZADO']
        vender(web, comprador, producto, cantidad=3)
        venta = venta_de(empresa, 271)
        disenar(empresa, 'minimalista', '#000000', '#FFFFFF')
        contextos.clear()
        salida = StringIO()
        call_command('regenerar_ride', '--empresa', empresa.ruc, '--tipo', 'factura', '--salida', str(tmp_path), stdout=salida)
        assert 'ENSAYO (no se cambió nada): fieles 1, con diferencias 0, aplicadas 0' in salida.getvalue()
        assert [c['ride_style']['id'] for p, c in contextos if p == FACTURA] == ['banda']   # la copia, no el diseño actual
        assert leer(empresa, lambda: Sale.objects.get(pk=venta.pk).pdf_authorized.name) == venta.pdf_authorized.name


# ---------------------------------------------------------------- menú y migración

class TestMenu:

    def test_modulo_en_configuracion_y_migracion_reversible(self, db):
        from tests.test_b0_contratos import estado_menu
        instalado = estado_menu()
        modulo = Module.objects.get(url=URL)
        assert (modulo.module_type.name, modulo.orden, modulo.name, modulo.icon) == (
            'Configuración', 3, 'Diseño de factura', 'fas fa-palette')
        assert set(modulo.permissions.values_list('codename', flat=True)) == {'view_disenofactura', 'change_disenofactura'}
        assert Module.objects.get(url='/configuracion/facturacion/').orden == 2
        assert Module.objects.get(url='/configuracion/puntos/').orden == 4
        for rol, tiene in ((ROLE_OWNER, True), (ROLE_ADMIN, True), (ROLE_READONLY, False), (ROLE_ACCOUNTANT, False),
                           (ROLE_SELLER, False)):
            assert (URL in instalado[2][rol][0]) == tiene, rol
            assert ('change_disenofactura' in instalado[2][rol][1]) == tiene, rol
        migracion = importlib.import_module('core.configuracion.migrations.0005_modulo_diseno_factura')
        apps_hist = MigrationExecutor(connection).loader.project_state(('configuracion', '0005_modulo_diseno_factura')).apps
        migracion.backwards(apps_hist, None)
        _, modulos, grupos = estado_menu()
        assert URL not in modulos and modulos['/configuracion/puntos/'][3] == 3 and modulos['/pos/receipt/'][3] == 5
        assert not any(c.endswith('_disenofactura') for _, codigos in grupos.values() for c in codigos)
        assert 'view_puntoautorizado' in grupos[ROLE_OWNER][1]   # los permisos de los puntos siguen
        migracion.forwards(apps_hist, None)
        assert estado_menu() == instalado
