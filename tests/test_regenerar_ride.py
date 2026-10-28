"""Regenerar el RIDE A4 guardado (manage.py regenerar_ride): ensayo por defecto, solo si el PDF nuevo es fiel al XML
autorizado, y al aplicar nunca sobrescribe: archivo nuevo, el anterior intacto y copiado, registro en la auditoría."""
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from core.comprobantes.fidelidad import _dinero, datos_autorizados, diferencias
from core.pos.models import Sale
from core.tenancy.models import AuditLog
from core.user.models import User
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, producto, sri, vender, venta_de, web  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def factura(web, empresa, comprador, producto, sri):  # noqa: F811
    User.objects.filter(pk=comprador.user_id).update(names='IMPORTADORA ORIGINAL S.A.')   # que no esté dentro de otro dato
    sri.respuestas_autorizacion = ['AUTORIZADO']
    vender(web, comprador, producto, cantidad=3)
    venta = venta_de(empresa, 271)
    assert venta.xml_authorized and venta.pdf_authorized
    return venta


def regenerar(empresa, *args):  # noqa: F811
    salida = StringIO()
    call_command('regenerar_ride', '--empresa', empresa.ruc, *args, stdout=salida)
    return salida.getvalue()


def contenido(campo):
    with campo.open('rb') as f:
        return f.read()


class TestFidelidad:

    def test_numeros_en_las_formas_de_la_plantilla(self):
        assert _dinero('1440.00') == ['1440,00', '1.440,00', '1440.00']

    def test_el_ride_guardado_es_fiel_a_su_xml(self, factura):
        xml, pdf = contenido(factura.xml_authorized), contenido(factura.pdf_authorized)
        campos = [c for c, _ in datos_autorizados(xml)]
        assert {'número de autorización', 'comprador', 'detalle 1: descripción', 'importe total'} <= set(campos)
        assert diferencias(pdf, xml) == []


class TestRegenerar:

    def test_ensayo_no_cambia_nada(self, empresa, factura, tmp_path):  # noqa: F811
        antes = factura.pdf_authorized.name
        salida = regenerar(empresa, '--salida', str(tmp_path))
        assert 'ENSAYO (no se cambió nada): fieles 1, con diferencias 0, aplicadas 0' in salida
        assert 'nuevo' in salida and 'fiel al XML: sí' in salida
        assert leer(empresa, lambda: Sale.objects.get(pk=factura.pk).pdf_authorized.name) == antes
        assert Path(tmp_path, '001-002-000000271-nuevo.pdf').read_bytes()[:5] == b'%PDF-'

    def test_datos_cambiados_despues_de_autorizar_no_se_regeneran(self, empresa, comprador, factura, tmp_path):  # noqa: F811
        User.objects.filter(pk=comprador.user_id).update(names='OTRO NOMBRE DESPUÉS DE AUTORIZAR')
        antes = factura.pdf_authorized.name
        salida = regenerar(empresa, '--aplicar', '--respaldo', str(tmp_path))
        assert 'no coincide comprador' in salida and 'fieles 0, con diferencias 1, aplicadas 0' in salida
        assert leer(empresa, lambda: Sale.objects.get(pk=factura.pk).pdf_authorized.name) == antes
        assert not AuditLog.objects.filter(action='ride_regenerado').exists()

    def test_aplicar_guarda_un_archivo_nuevo_y_conserva_el_anterior(self, empresa, factura, tmp_path):  # noqa: F811
        anterior_nombre, anterior = factura.pdf_authorized.name, contenido(factura.pdf_authorized)
        salida = regenerar(empresa, '--numero', '001-002-000000271', '--aplicar', '--respaldo', str(tmp_path))
        assert 'APLICADO: fieles 1, con diferencias 0, aplicadas 1' in salida
        venta = leer(empresa, lambda: Sale.objects.get(pk=factura.pk))
        assert venta.pdf_authorized.name != anterior_nombre and contenido(venta.pdf_authorized)[:5] == b'%PDF-'
        assert venta.pdf_authorized.storage.exists(anterior_nombre)                                  # el anterior sigue ahí
        assert Path(tmp_path, Path(anterior_nombre).name).read_bytes() == anterior                   # y copiado
        registro = AuditLog.objects.get(action='ride_regenerado')
        assert registro.detail == {'comprobante': '001-002-000000271', 'anterior': anterior_nombre, 'nuevo': venta.pdf_authorized.name}
        assert (venta.status, venta.access_code, venta.xml_authorized.name) == (factura.status, factura.access_code, factura.xml_authorized.name)

    def test_aplicar_exige_respaldo_y_empresa_existente(self, empresa, factura):  # noqa: F811
        with pytest.raises(CommandError, match='--respaldo'):
            regenerar(empresa, '--aplicar')
        with pytest.raises(CommandError, match='No hay una empresa'):
            call_command('regenerar_ride', '--empresa', '0999999999001', stdout=StringIO())
