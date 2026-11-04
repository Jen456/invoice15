"""Regenerar el RIDE A4 guardado (manage.py regenerar_ride): ensayo por defecto, solo si el PDF nuevo es fiel al XML
autorizado, y al aplicar nunca sobrescribe: archivo nuevo, el anterior intacto y copiado, registro en la auditoría."""
import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from core.comprobantes.fidelidad import _dinero, datos_autorizados, diferencias
from core.pos.models import CreditNote, Sale, SaleDetail
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


class TestNotasDeCredito:
    """El RIDE A4 de las notas de crédito también se regenera con fidelidad al XML (infoNotaCredito)."""

    @pytest.fixture
    def nota(self, web, empresa, factura, sri):  # noqa: F811
        sri.respuestas_autorizacion = ['AUTORIZADO']
        detalle = leer(empresa, lambda: SaleDetail.objects.filter(sale=factura).first())
        r = web.post('/pos/credit/note/admin/add/', {
            'action': 'add', 'sale': factura.pk, 'motive': 'Devolución ficticia de prueba', 'create_electronic_invoice': 'on',
            'products': json.dumps([{'id': detalle.pk, 'quantity': 1, 'price': '0.01', 'dscto': 0}])}).json()
        assert r.get('resp') is True, r
        nota = leer(empresa, lambda: CreditNote.objects.get(sale=factura))
        assert nota.xml_authorized and nota.pdf_authorized
        return nota

    def test_el_ride_de_la_nota_es_fiel_a_su_xml(self, nota):
        xml, pdf = contenido(nota.xml_authorized), contenido(nota.pdf_authorized)
        campos = {c for c, _ in datos_autorizados(xml)}
        assert {'documento modificado', 'fecha del documento modificado', 'motivo', 'valor de la modificación',
                'detalle 1: código', 'detalle 1: descripción'} <= campos and 'importe total' not in campos
        assert diferencias(pdf, xml) == []

    def test_ensayo_y_aplicar_solo_las_notas(self, empresa, factura, nota, tmp_path):  # noqa: F811
        factura_antes = leer(empresa, lambda: Sale.objects.get(pk=factura.pk).pdf_authorized.name)
        salida = regenerar(empresa, '--tipo', 'nota_credito', '--salida', str(tmp_path / 'ensayo'))
        assert 'ENSAYO (no se cambió nada): fieles 1, con diferencias 0, aplicadas 0' in salida
        assert f'nota de crédito {nota.voucher_number_full}' in salida
        assert Path(tmp_path, 'ensayo', f'nc-{nota.voucher_number_full}-nuevo.pdf').read_bytes()[:5] == b'%PDF-'
        anterior_nombre, anterior = nota.pdf_authorized.name, contenido(nota.pdf_authorized)
        salida = regenerar(empresa, '--tipo', 'nota_credito', '--aplicar', '--respaldo', str(tmp_path / 'respaldo'))
        assert 'APLICADO: fieles 1, con diferencias 0, aplicadas 1' in salida
        nueva = leer(empresa, lambda: CreditNote.objects.get(pk=nota.pk))
        assert nueva.pdf_authorized.name != anterior_nombre and nueva.pdf_authorized.storage.exists(anterior_nombre)
        assert Path(tmp_path, 'respaldo', Path(anterior_nombre).name).read_bytes() == anterior
        assert (nueva.status, nueva.access_code, nueva.xml_authorized.name) == (nota.status, nota.access_code, nota.xml_authorized.name)
        registro = AuditLog.objects.get(action='ride_regenerado')
        assert registro.detail == {'comprobante': nota.voucher_number_full, 'anterior': anterior_nombre,
                                   'nuevo': nueva.pdf_authorized.name, 'tipo': 'nota_credito'}
        assert leer(empresa, lambda: Sale.objects.get(pk=factura.pk).pdf_authorized.name) == factura_antes   # solo las notas
