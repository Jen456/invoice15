"""Vigencias del catálogo de retenciones (D0, Fase A): hoy cada resultado es el de 8d2eead, el catálogo guarda su
historial por fecha (310 y 332E cortados el 01/08/2026 por la Res. NAC-DGERCGC26-00000028), lo emitido no cambia,
«Emitir» solo emite lo revisado (huella) y el panel abre vigencias en vez de editar porcentajes.

Todo el archivo corre el 28/10/2026 a mediodía (Guayaquil), el día de la línea base; cada prueba viaja desde ahí.
La ida y vuelta de las migraciones está en test_zzz_vigencias_migraciones.py (necesita transacciones reales).
"""
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import time_machine
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client
from lxml import etree

from core.comprobantes import retenciones as sv
from core.comprobantes.admin import CodigoRetencionAdmin
from core.comprobantes.forms import LineaRetencionForm
from core.comprobantes.models import CodigoRetencion, Retencion
from core.pos import emision
from core.pos.models import Provider, Purchase
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog
from tests import helpers
from tests.test_firma_sri import generar_p12
from tests.test_retenciones import (LISTA, compra, emitir, empresa, formulario, huella, leer,  # noqa: F401 (fixtures)
                                    numeracion, sri, web)

pytestmark = pytest.mark.django_db
GYE = ZoneInfo('America/Guayaquil')
HOY = datetime(2026, 10, 28, 12, 0, tzinfo=GYE)
CORTE = date(2026, 8, 1)            # inicio de la vigencia de la Res. 28 en el catálogo (duda D0-a abierta)
VISPERA = date(2026, 7, 31)
ADMIN = '/plataforma/comprobantes/codigoretencion/'
DATOS = {'num_doc_sustento': '001-001-000000123', 'aut_doc_sustento': '1' * 49, 'base_iva': '100.00',
         'fecha_doc_sustento': date(2026, 7, 30)}


@pytest.fixture(autouse=True)
def reloj():
    with time_machine.travel(HOY, tick=True):
        yield


@pytest.fixture
def p12(reloj):
    """Firma ficticia vigente en la fecha simulada (la de test_retenciones se genera con la fecha real)."""
    return generar_p12()[0]


def fila(codigo, desde=None, impuesto='1'):
    """Fila del catálogo por su inicio (None: la que cargó 0004)."""
    return CodigoRetencion.objects.get(impuesto=impuesto, codigo=codigo, vigente_desde=desde)


def calcular(pk, porcentaje=None, fecha=None):
    """(%, valor retenido, fila usada) de una línea sobre una base de 100,00."""
    _, detalle, total = sv.calcular(DATOS, [(pk, None, porcentaje)], fecha)
    assert total == detalle[0]['valor_retenido']
    return detalle[0]['porcentaje'], detalle[0]['valor_retenido'], detalle[0]['codigo_obj'].pk


def otra_compra(empresa, numero):  # noqa: F811
    with company_context(empresa):
        proveedor = Provider.objects.create(name=f'TRANSPORTES {numero} S.A.', ruc=f'09900000{numero:0>2}001', mobile='0990000001',
                                            email=f'transportes{numero}@example.com', address='Av. Quito 200')
        return Purchase.objects.create(number=str(numero), provider=proveedor, subtotal=Decimal('100.00'))


def foto(empresa, ret):  # noqa: F811
    """Lo emitido: detalles, total y XML firmado."""
    with company_context(empresa):
        ret = Retencion.objects.get(pk=ret.pk)
        detalles = [(d.impuesto, d.codigo, d.concepto, d.base_imponible, d.porcentaje, d.valor_retenido, d.codigo_catalogo_id)
                    for d in ret.detalles.all()]
        return detalles, ret.total_retenido, ret.xml_signed


def editar_en_panel(cliente, codigo, **cambios):
    """POST del formulario de cambio del panel con los valores actuales y `cambios` (los de solo lectura se ignoran)."""
    valores = {'impuesto': codigo.impuesto, 'codigo': codigo.codigo, 'concepto': codigo.concepto, 'porcentaje': str(codigo.porcentaje),
               'porcentaje_editable': codigo.porcentaje_editable, 'comun': codigo.comun, 'activo': codigo.activo,
               'fuente': codigo.fuente, 'orden': codigo.orden, 'ayuda': codigo.ayuda,
               'vigente_desde': codigo.vigente_desde.isoformat() if codigo.vigente_desde else '',
               'vigente_hasta': codigo.vigente_hasta.isoformat() if codigo.vigente_hasta else ''}
    valores.update(cambios)
    return cliente.post(f'{ADMIN}{codigo.pk}/change/', {k: ('on' if v is True else v) for k, v in valores.items() if v is not False})


def volver_a_entrar(cliente, empresa):  # noqa: F811
    """La sesión dura 8 horas: tras viajar en el tiempo el dueño vuelve a entrar."""
    from core.user.models import User
    helpers.iniciar_sesion(cliente, User.objects.get(username='dueno.retenedora'), empresa=empresa)


@pytest.fixture
def plataforma(db):
    """Superusuario en /plataforma/, con su propio navegador (el de `web` es el del dueño de la empresa)."""
    cliente = Client()
    helpers.iniciar_sesion(cliente, helpers.crear_usuario('plataforma.vigencias', superusuario=True))
    return cliente


class TestRegresion:
    """Resultados de calcular() el 28/10/2026 en 8d2eead, registrados antes del cambio (base 100,00)."""

    @pytest.mark.parametrize('codigo, porcentaje, esperado', [
        ('310', None, '1.00'), ('310', '0', '0.00'), ('332E', None, '0.00'), ('332E', '1', '1.00'),
        ('312', None, '2.00'), ('312', '0', '2.00'), ('3440', None, '3.00'), ('3440', '9', '3.00'),
    ])
    def test_hoy_igual_que_antes_de_las_vigencias(self, db, codigo, porcentaje, esperado):
        hoy = CodigoRetencion.vigente('1', codigo, HOY.date())
        for elegida in CodigoRetencion.objects.filter(impuesto='1', codigo=codigo):   # cualquier vigencia del código
            assert calcular(elegida.pk, porcentaje) == (Decimal(esperado), Decimal(esperado), hoy.pk)

    def test_emitida_hoy_igual_y_con_su_fila(self, web, empresa, compra, numeracion, sri):  # noqa: F811
        sri.respuestas_autorizacion = ['AUTORIZADO']
        emitir(web, f'{LISTA}nueva/{compra.pk}/', formulario([(fila('310', CORTE), '', '0'), (fila('312'), '', '')]))
        detalles, total, _ = foto(empresa, leer(empresa, lambda: Retencion.objects.get()))
        assert [(d[1], d[4], d[5], d[6]) for d in detalles] == [('310', Decimal('0.00'), Decimal('0.00'), fila('310', CORTE).pk),
                                                                ('312', Decimal('2.00'), Decimal('2.00'), fila('312').pk)]
        assert total == Decimal('2.00')


class TestCorteDeLaRes28:

    def test_310_fijo_hasta_el_31_07_y_editable_desde_el_01_08(self, db):
        r310 = fila('310', CORTE).pk
        assert calcular(r310, '0', VISPERA) == (Decimal('1.00'), Decimal('1.00'), fila('310').pk)   # el «0» se ignora
        assert calcular(r310, None, VISPERA)[0] == Decimal('1.00')
        assert calcular(fila('310').pk, '0', CORTE) == (Decimal('0.00'), Decimal('0.00'), r310)
        assert calcular(r310, None, CORTE)[0] == Decimal('1.00')

    def test_332E_igual_antes_y_despues(self, db):
        for fecha in (VISPERA, CORTE):
            assert calcular(fila('332E').pk, None, fecha)[0] == Decimal('0.00')
            assert calcular(fila('332E').pk, '1', fecha)[0] == Decimal('1.00')

    @pytest.mark.parametrize('fecha', [VISPERA, CORTE, date(2026, 8, 6), HOY.date()])
    def test_312_y_3440_sin_cambios(self, db, fecha):
        assert calcular(fila('312').pk, None, fecha)[:2] == (Decimal('2.00'), Decimal('2.00'))
        assert calcular(fila('3440').pk, '9', fecha)[:2] == (Decimal('3.00'), Decimal('3.00'))

    def test_crear_toma_la_vigencia_del_dia(self, empresa, compra, numeracion):  # noqa: F811
        usuario = helpers.crear_usuario('emisor.vigencias', empresa)
        hechas = []
        for momento, de_compra in ((datetime(2026, 7, 31, 12, 0, tzinfo=GYE), compra), (datetime(2026, 8, 1, 12, 0, tzinfo=GYE),
                                                                                       otra_compra(empresa, 2))):
            with time_machine.travel(momento, tick=False), company_context(empresa), transaction.atomic():
                ret = sv.crear(empresa, usuario, de_compra, DATOS, [(fila('310', CORTE).pk, None, '0')])
                detalle = ret.detalles.get()
                hechas.append((ret.date_joined, detalle.porcentaje, detalle.codigo_catalogo_id))
        assert hechas == [(VISPERA, Decimal('1.00'), fila('310').pk), (CORTE, Decimal('0.00'), fila('310', CORTE).pk)]

    def test_codigo_sin_vigencia_en_la_fecha(self, db):
        CodigoRetencion.objects.filter(pk=fila('310').pk).update(activo=False)
        with pytest.raises(sv.ErrorRetencion, match='El código 310 no está vigente el 15/07/2026'):
            calcular(fila('310', CORTE).pk, None, date(2026, 7, 15))


class TestCatalogoMigrado:

    def test_310_y_332E_con_dos_vigencias(self, db):
        a, b = fila('310'), fila('310', CORTE)
        assert (a.vigente_hasta, a.porcentaje, a.porcentaje_editable) == (VISPERA, Decimal('1.00'), False)   # DIMM «N»
        assert (b.vigente_hasta, b.porcentaje, b.porcentaje_editable) == (None, Decimal('1.00'), True)
        assert (b.concepto, b.orden, b.comun, b.activo) == (a.concepto, a.orden, a.comun, True)
        assert '"1 /0 según resolución NAC-DGERCGC26-00000028"' in b.fuente and 'RO 5S 339, 03/08/2026' in b.fuente
        c, d = fila('332E'), fila('332E', CORTE)
        assert (c.vigente_hasta, c.porcentaje, c.porcentaje_editable) == (VISPERA, Decimal('0.00'), True)
        assert (d.vigente_hasta, d.porcentaje, d.porcentaje_editable, d.comun) == (None, Decimal('0.00'), True, False)
        assert '"0 /1 según resolución NAC-DGERCGC26-00000028"' in d.fuente
        for nueva in (b, d):
            assert len(nueva.ayuda) <= 500 and all(t in nueva.ayuda for t in ('NAC-DGERCGC26-00000028', '31/12/2026', 'contador'))
        assert not a.ayuda and not c.ayuda

    def test_el_resto_sin_fechas_inventadas(self, db):
        con_fechas = CodigoRetencion.objects.exclude(vigente_desde__isnull=True, vigente_hasta__isnull=True)
        assert sorted(con_fechas.values_list('codigo', flat=True)) == ['310', '310', '332E', '332E']
        r3440 = CodigoRetencion.objects.get(impuesto='1', codigo='3440')   # una sola fila, sin partir
        assert r3440.fuente.endswith('; concepto según bloque 06/08/2026') and r3440.porcentaje == Decimal('3.00')

    def test_vigentes_por_fecha_cada_codigo_una_vez(self, db):
        for fecha, esperada in ((VISPERA, fila('310')), (CORTE, fila('310', CORTE)), (HOY.date(), fila('310', CORTE))):
            claves = list(CodigoRetencion.objects.vigentes(fecha).values_list('impuesto', 'codigo'))
            assert len(claves) == len(set(claves)) == CodigoRetencion.objects.filter(activo=True).count() - 2
            assert CodigoRetencion.objects.vigentes(fecha).get(impuesto='1', codigo='310') == esperada
            assert CodigoRetencion.vigente('1', '310', fecha) == esperada


class TestRestricciones:

    def nueva(self, **campos):
        datos = dict(impuesto='1', codigo='310', concepto='Prueba', porcentaje=Decimal('1.00'), fuente='Prueba')
        datos.update(campos)
        return CodigoRetencion(**datos)

    @pytest.mark.parametrize('campos', [
        {'vigente_desde': date(2027, 1, 1)},                                            # otra fila abierta del 310
        {'codigo': '312', 'vigente_hasta': date(2025, 12, 31)},                         # otra fila sin inicio del 312
        {'vigente_desde': CORTE, 'vigente_hasta': date(2026, 9, 30)},                   # mismo inicio del 310
        {'codigo': 'X99', 'vigente_desde': date(2027, 2, 1), 'vigente_hasta': date(2027, 1, 31)},   # termina antes de empezar
    ])
    def test_la_base_de_datos_rechaza(self, db, campos):
        with pytest.raises(IntegrityError), transaction.atomic():
            self.nueva(**campos).save()

    def test_clean_rechaza_solapes(self, db):
        with pytest.raises(ValidationError, match='se solapa con la del código 310 \\(sin inicio – 31/07/2026\\)'):
            self.nueva(vigente_desde=date(2026, 7, 1), vigente_hasta=date(2026, 7, 15)).clean()
        with pytest.raises(ValidationError, match='se solapa'):
            self.nueva(codigo='312', vigente_desde=date(2027, 1, 1), vigente_hasta=date(2027, 12, 31)).clean()
        with pytest.raises(ValidationError, match='terminar antes de empezar'):
            self.nueva(codigo='X99', vigente_desde=date(2027, 2, 1), vigente_hasta=date(2027, 1, 31)).clean()
        self.nueva(codigo='X99', vigente_desde=date(2027, 1, 1)).clean()   # código sin otras filas

    def test_nueva_vigencia_cierra_la_abierta(self, db):
        abierta = fila('310', CORTE)
        nueva = abierta.nueva_vigencia(desde=date(2027, 1, 1), porcentaje=Decimal('0.00'), porcentaje_editable=False, fuente='Prueba')
        abierta.refresh_from_db()
        assert abierta.vigente_hasta == date(2026, 12, 31) and nueva.vigente_hasta is None and nueva.concepto == abierta.concepto
        assert CodigoRetencion.vigente('1', '310', date(2026, 12, 31)) == abierta
        assert CodigoRetencion.vigente('1', '310', date(2027, 1, 1)) == nueva
        with pytest.raises(ValidationError, match='ya está cerrada'):
            abierta.nueva_vigencia(desde=date(2027, 6, 1), porcentaje=Decimal('1.00'), porcentaje_editable=True, fuente='X')
        with pytest.raises(ValidationError, match='después del 01/01/2027'):
            nueva.nueva_vigencia(desde=date(2027, 1, 1), porcentaje=Decimal('1.00'), porcentaje_editable=True, fuente='X')
        assert CodigoRetencion.objects.filter(impuesto='1', codigo='310').count() == 3


class TestFormulario:

    def test_cada_codigo_una_vez_con_su_ayuda(self, db):
        for fecha, esperada in ((VISPERA, fila('310')), (HOY.date(), fila('310', CORTE))):
            form = LineaRetencionForm(fecha=fecha)
            etiquetas = [str(etiqueta) for valor, etiqueta in form.fields['codigo'].choices if valor]
            assert len(etiquetas) == len(set(etiquetas)) == CodigoRetencion.objects.vigentes(fecha).count()
            opciones = [(str(v), e) for v, e in form.fields['codigo'].choices if str(e).startswith('Renta · 310 ·')]
            assert opciones == [(str(esperada.pk), 'Renta · 310 · Servicio de transporte privado de pasajeros o transporte público '
                                                   'o privado de carga (1 %)')]
            assert ('data-ayuda="Desde el 01/08/2026' in str(form['codigo'])) is bool(esperada.ayuda)

    def test_la_pagina_muestra_la_ayuda(self, web, compra):  # noqa: F811
        html = web.get(f'{LISTA}nueva/{compra.pk}/').content.decode()
        assert html.count('>Renta · 310 ·') == 4   # 3 líneas + la plantilla de línea nueva, una vez en cada lista
        assert 'data-ayuda="Desde el 01/08/2026 el Catálogo ATS admite 1 % o 0 %' in html and 'fp-retencion-ayuda' in html
        revision = web.post(f'{LISTA}nueva/{compra.pk}/', {**formulario([(fila('310', CORTE), '', '')]), 'action': 'calcular'})
        assert '<small class="d-block text-muted">Desde el 01/08/2026' in revision.content.decode()   # sin JavaScript


class TestHuella:

    def test_cambio_de_vigencia_a_medianoche_vuelve_a_revisar(self, web, empresa, compra, numeracion, sri):  # noqa: F811
        url, abierta = f'{LISTA}nueva/{compra.pk}/', fila('310', CORTE)
        post = formulario([(abierta, '', '')])
        nueva = abierta.nueva_vigencia(desde=date(2027, 1, 1), porcentaje=Decimal('0.00'), porcentaje_editable=False, fuente='Prueba')
        with time_machine.travel(datetime(2026, 12, 31, 23, 59, tzinfo=GYE), tick=False):
            volver_a_entrar(web, empresa)
            revision = web.post(url, {**post, 'action': 'calcular'}).content.decode()
        assert 'Revisa antes de emitir' in revision and huella(revision)
        with time_machine.travel(datetime(2027, 1, 1, 0, 1, tzinfo=GYE), tick=False):
            html = web.post(url, {**post, 'action': 'emitir', 'huella': huella(revision)}).content.decode()
            assert 'ya no es el que revisaste' in html and 'Revisa antes de emitir' in html and huella(html) != huella(revision)
            assert not leer(empresa, lambda: Retencion.objects.exists()) and not sri.recepciones
            assert f'value="{nueva.pk}" selected' in html   # la línea ya apunta a la vigencia de 2027
            sri.respuestas_autorizacion = ['AUTORIZADO']
            web.post(url, {**post, 'lineas-0-codigo': nueva.pk, 'action': 'emitir', 'huella': huella(html)})
        detalles, total, _ = foto(empresa, leer(empresa, lambda: Retencion.objects.get()))
        assert [(d[1], d[4], d[6]) for d in detalles] == [('310', Decimal('0.00'), nueva.pk)] and total == Decimal('0.00')

    def test_sin_cambio_de_vigencia_la_medianoche_no_estorba(self, web, empresa, compra, numeracion, sri):  # noqa: F811
        url, post = f'{LISTA}nueva/{compra.pk}/', formulario([(fila('310', CORTE), '', '')])
        with time_machine.travel(datetime(2026, 12, 31, 23, 59, tzinfo=GYE), tick=False):
            volver_a_entrar(web, empresa)
            revision = web.post(url, {**post, 'action': 'calcular'}).content.decode()
        with time_machine.travel(datetime(2027, 1, 1, 0, 1, tzinfo=GYE), tick=False):
            web.post(url, {**post, 'action': 'emitir', 'huella': huella(revision)})
        detalles, total, _ = foto(empresa, leer(empresa, lambda: Retencion.objects.get()))
        assert [(d[1], d[4]) for d in detalles] == [('310', Decimal('1.00'))] and total == Decimal('1.00')


class TestLoEmitidoNoCambia:

    def test_autorizada_y_en_proceso_tras_nueva_vigencia_y_edicion_en_el_panel(self, web, plataforma, empresa, compra,  # noqa: F811
                                                                                numeracion, sri):
        r310 = fila('310', CORTE)
        sri.respuestas_autorizacion = ['AUTORIZADO']
        emitir(web, f'{LISTA}nueva/{compra.pk}/', formulario([(r310, '', '')]))
        en_proceso = otra_compra(empresa, 3)
        emitir(web, f'{LISTA}nueva/{en_proceso.pk}/', formulario([(r310, '', '')]))   # el SRI aún no responde
        autorizada, pendiente = leer(empresa, lambda: list(Retencion.objects.order_by('pk')))
        assert autorizada.status in emision.AUTORIZADOS and pendiente.status == 'in_process'
        antes = {r.pk: foto(empresa, r) for r in (autorizada, pendiente)}
        assert all(d[4] == Decimal('1.00') for detalles, _, _ in antes.values() for d in detalles)

        futura = r310.nueva_vigencia(desde=date(2027, 1, 1), porcentaje=Decimal('0.00'), porcentaje_editable=False, fuente='Prueba')
        assert editar_en_panel(plataforma, futura, porcentaje='0.50').status_code == 302   # aún no empieza: se edita
        r310.refresh_from_db()
        assert editar_en_panel(plataforma, r310, porcentaje='0.00', ayuda='Otra ayuda').status_code == 302
        r310.refresh_from_db()
        assert (r310.porcentaje, r310.ayuda) == (Decimal('1.00'), 'Otra ayuda')   # el % de una vigencia empezada no cambia

        with time_machine.travel(datetime(2027, 1, 2, 9, 0, tzinfo=GYE), tick=False):
            assert CodigoRetencion.vigente('1', '310', date(2027, 1, 2)).porcentaje == Decimal('0.50')
            for ret in (autorizada, pendiente):
                assert foto(empresa, ret) == antes[ret.pk]   # detalle, total y XML firmado byte a byte
                with company_context(empresa):
                    xml, _ = Retencion.objects.get(pk=ret.pk).generate_xml()
                documento = etree.fromstring(xml.encode() if isinstance(xml, str) else xml)
                assert [e.text for e in documento.iter('porcentajeRetener')] == ['1.00']
            sri.respuestas_autorizacion = ['AUTORIZADO']
            call_command('consultar_sri')
        assert leer(empresa, lambda: Retencion.objects.get(pk=pendiente.pk).status) in emision.AUTORIZADOS
        assert foto(empresa, pendiente) == antes[pendiente.pk] and sri.recepciones[-1] == antes[pendiente.pk][2]


class TestPanel:

    def test_sin_porcentaje_en_la_lista_y_vigencias_empezadas_de_solo_lectura(self, plataforma):
        assert 'porcentaje' not in CodigoRetencionAdmin.list_editable and plataforma.get(ADMIN).status_code == 200
        html = plataforma.get(f'{ADMIN}{fila("310", CORTE).pk}/change/').content.decode()
        assert all(f'name="{campo}"' not in html for campo in ('porcentaje', 'concepto', 'vigente_desde', 'codigo'))
        assert 'name="ayuda"' in html and 'name="vigente_hasta"' in html
        futura = fila('310', CORTE).nueva_vigencia(desde=date(2027, 1, 1), porcentaje=Decimal('0.00'), porcentaje_editable=False,
                                                   fuente='Prueba')
        html = plataforma.get(f'{ADMIN}{futura.pk}/change/').content.decode()
        assert 'name="porcentaje"' in html and 'name="vigente_desde"' in html

    def test_accion_nueva_vigencia_cierra_crea_y_audita(self, plataforma):
        abierta = fila('310', CORTE)
        base = {'action': 'nueva_vigencia', '_selected_action': [fila('310').pk, abierta.pk]}
        pagina = plataforma.post(ADMIN, base).content.decode()
        assert 'Nueva vigencia del código 310' in pagina and 'name="desde"' in pagina
        campos = {'aplicar': '1', 'porcentaje': '0.00', 'fuente': 'Resolución de prueba', 'ayuda': 'Ayuda 2027'}
        mala = plataforma.post(ADMIN, {**base, **campos, 'desde': '2026-08-01'}).content.decode()
        assert 'debe empezar después del 01/08/2026' in mala
        assert CodigoRetencion.objects.filter(impuesto='1', codigo='310').count() == 2 and not AuditLog.objects.filter(
            action='catalogo_vigencia_nueva').exists()
        assert plataforma.post(ADMIN, {**base, **campos, 'desde': '2027-01-01'}).status_code == 302
        abierta.refresh_from_db()
        nueva = fila('310', date(2027, 1, 1))
        assert abierta.vigente_hasta == date(2026, 12, 31)
        assert (nueva.porcentaje, nueva.porcentaje_editable, nueva.fuente, nueva.ayuda) == (Decimal('0.00'), False,
                                                                                            'Resolución de prueba', 'Ayuda 2027')
        registro = AuditLog.objects.get(action='catalogo_vigencia_nueva')
        assert registro.company is None and registro.user.username == 'plataforma.vigencias'
        assert {k: registro.detail[k] for k in ('codigo', 'cerrada', 'nueva', 'desde', 'porcentaje', 'porcentaje_anterior')} == {
            'codigo': '310', 'cerrada': abierta.pk, 'nueva': nueva.pk, 'desde': '2027-01-01', 'porcentaje': '0.00',
            'porcentaje_anterior': '1.00'}

    def test_accion_con_dos_codigos_no_hace_nada(self, plataforma):
        respuesta = plataforma.post(ADMIN, {'action': 'nueva_vigencia', '_selected_action': [fila('310').pk, fila('312').pk]},
                                    follow=True)
        assert 'Elige filas de un solo código' in respuesta.content.decode()
        assert CodigoRetencion.objects.count() == CodigoRetencion.objects.filter(vigente_desde__isnull=True).count() + 2
