"""ATS del mes (core/tributario/ats.py): XML validado contra el esquema oficial guardado con su huella; compras registradas en
el mes con sus datos completos; las incompletas quedan fuera con su motivo (no se inventa nada); advertencias de lo que no
se incluye por reglas sin confirmar; descarga solo si valida; esquema alterado detectado; permisos y pestañas abiertas."""
import hashlib
import io
import zipfile
from datetime import timedelta

import pytest
from django.utils import timezone
from lxml import etree

from core.pos import compras
from core.pos.models import Purchase
from core.tenancy.context import company_context
from core.tenancy.models import ROLE_READONLY, ROLE_SELLER
from core.tributario import ats
from core.tributario.models import ExportacionLibro
from tests import ayuda_compras, helpers

pytestmark = pytest.mark.django_db
MES = (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)
DIA = MES.replace(day=15)


def leer(empresa, funcion):
    with company_context(empresa):
        return funcion()


@pytest.fixture
def completa(empresa, admin):
    proveedor = ayuda_compras.crear_proveedor(empresa)
    tipo = ayuda_compras.crear_tipo_gasto(empresa, 'SERVICIOS')
    datos = ayuda_compras.datos_compra(proveedor, fecha_emision=(DIA - timedelta(days=2)).isoformat(), date_joined=DIA.isoformat())
    with company_context(empresa):
        return compras.crear_compra(empresa, admin, datos, [ayuda_compras.linea_gasto('Mantenimiento', price='100.00', type_expense=tipo)])


def nodo(xml, ruta):
    return etree.fromstring(xml).find(ruta)


class TestGenerar:

    def test_xml_valido_con_la_compra_completa(self, empresa, completa):
        resultado = leer(empresa, lambda: ats.generar(MES, empresa))
        assert resultado['valido'] is True and resultado['errores_xsd'] == [], resultado['errores_xsd']
        assert [c['id'] for c in resultado['incluidas']] == [completa.pk] and resultado['excluidas'] == []
        xml = resultado['xml']
        assert nodo(xml, 'IdInformante').text == empresa.ruc and nodo(xml, 'Mes').text == f'{MES.month:02d}'
        assert nodo(xml, 'Anio').text == str(MES.year) and nodo(xml, 'codigoOperativo').text == 'IVA'
        assert nodo(xml, 'razonSocial').text == ats.texto_ats(empresa.business_name)
        detalle = nodo(xml, 'compras/detalleCompras')
        valores = {hijo.tag: hijo.text for hijo in detalle}
        assert (valores['codSustento'], valores['tpIdProv'], valores['idProv'], valores['tipoComprobante']) == (
            completa.cod_sustento, completa.provider.tipo_id_ats, completa.provider.ruc, '01')
        assert (valores['fechaRegistro'], valores['fechaEmision']) == (f'{DIA:%d/%m/%Y}', f'{DIA - timedelta(days=2):%d/%m/%Y}')
        assert (valores['baseImpGrav'], valores['montoIva'], valores['baseImponible'], valores['valorRetBienes']) == ('100.00', '15.00', '0.00', '0.00')
        assert detalle.find('formasDePago/formaPago').text == completa.forma_pago and detalle.find('pagoExterior/pagoLocExt').text == '01'
        assert {a['codigo'] for a in resultado['advertencias']} >= {'retenciones_electronicas', 'ventas_sin_confirmar',
                                                                     'anulados_sin_confirmar', 'validacion_tecnica'}
        assert resultado['nombre'] == f'AT{MES:%m%Y}' and resultado['esquema']['sha256'] == ats.FUENTE_ESQUEMA['sha256']

    def test_incompletas_quedan_fuera_con_su_motivo(self, empresa, completa):
        antigua = ayuda_compras.compra_antigua(empresa, ayuda_compras.crear_proveedor(empresa), '50.00', fecha=DIA)
        with company_context(empresa):
            nota = Purchase.objects.get(pk=completa.pk)
            Purchase.objects.filter(pk=nota.pk).update(tipo_comprobante='04', num_doc_modificado='', aut_doc_modificado='')
            resultado = ats.generar(MES, empresa)
        excluidas = {c['id']: c['motivos'] for c in resultado['excluidas']}
        assert set(excluidas) == {antigua.pk, completa.pk} and resultado['incluidas'] == []
        assert any('comprobante que modifica' in m for m in excluidas[completa.pk])
        assert any('tarifa de IVA' in m for m in excluidas[antigua.pk])
        assert resultado['valido'] is True and nodo(resultado['xml'], 'compras') is None      # sin compras: solo la cabecera
        assert 'compras_excluidas' in {a['codigo'] for a in resultado['advertencias']}

    def test_compras_de_otro_mes_u_otra_empresa_no_entran(self, empresa, empresa_b, admin, completa):
        ayuda_compras.compra_antigua(empresa_b, ayuda_compras.crear_proveedor(empresa_b), '10.00', fecha=DIA)
        with company_context(empresa):
            Purchase.objects.filter(pk=completa.pk).update(date_joined=MES - timedelta(days=1))
            resultado = ats.generar(MES, empresa)
        assert resultado['incluidas'] == resultado['excluidas'] == []

    def test_texto_ats(self):
        assert ats.texto_ats('Café & Té S.A., Ñandú') == 'CAFE TE S A NANDU'

    def test_esquema_alterado_no_valida(self, empresa, completa, monkeypatch):
        ats.esquema.cache_clear()
        monkeypatch.setitem(ats.FUENTE_ESQUEMA, 'sha256', '0' * 64)
        try:
            resultado = leer(empresa, lambda: ats.generar(MES, empresa))
            assert resultado['valido'] is False and 'huella' in resultado['errores_xsd'][0]['mensaje']
        finally:
            ats.esquema.cache_clear()

    def test_esquema_guardado_es_el_oficial_registrado(self):
        assert hashlib.sha256(ats.ESQUEMA.read_bytes()).hexdigest() == ats.FUENTE_ESQUEMA['sha256']


class TestPantalla:

    def test_descarga_solo_si_valida(self, client, empresa, admin, completa, monkeypatch):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        respuesta = client.get(f'/tributario/ats/descargar/?mes={MES:%Y-%m}&empresa={empresa.pk}')
        assert respuesta.status_code == 200 and f'AT{MES:%m%Y}.zip' in respuesta['Content-Disposition']
        with zipfile.ZipFile(io.BytesIO(respuesta.content)) as zf:
            assert zf.namelist() == [f'AT{MES:%m%Y}.xml']
            assert ats.esquema().validate(etree.fromstring(zf.read(f'AT{MES:%m%Y}.xml')))
        registro = leer(empresa, lambda: ExportacionLibro.objects.get(libro='ats'))
        assert (registro.formato, registro.filas, registro.totales['esquema_sha256']) == ('zip', 1, ats.FUENTE_ESQUEMA['sha256'])
        monkeypatch.setattr(ats, 'generar', lambda inicio, company: {'valido': False, 'errores_xsd': [{'linea': 3, 'mensaje': 'x'}]})
        invalido = client.get(f'/tributario/ats/descargar/?mes={MES:%Y-%m}')
        assert invalido.status_code == 409 and invalido.json()['codigo'] == 'ats_invalido'

    def test_pagina_api_y_pestanas(self, client, empresa, empresa_b, admin, completa):
        helpers.iniciar_sesion(client, admin, empresa=empresa)
        pagina = client.get(f'/tributario/ats/?mes={MES:%Y-%m}')
        assert pagina.status_code == 200 and 'El XML valida contra el esquema' in pagina.content.decode()
        datos = client.get(f'/tributario/api/ats/?mes={MES:%Y-%m}').json()
        assert datos['valido'] is True and 'xml' not in datos and len(datos['incluidas']) == 1
        assert client.get(f'/tributario/api/ats/?empresa={empresa_b.pk}').status_code == 409
        assert client.get(f'/tributario/ats/descargar/?empresa={empresa_b.pk}').status_code == 409

    @pytest.mark.parametrize('rol, estado', [(ROLE_READONLY, 200), (ROLE_SELLER, 302)])
    def test_permisos(self, client, empresa, rol, estado):
        usuario = helpers.crear_usuario(f'ats.{rol.lower()}', empresa, rol)
        helpers.iniciar_sesion(client, usuario, empresa=empresa)
        assert client.get('/tributario/ats/').status_code == estado
