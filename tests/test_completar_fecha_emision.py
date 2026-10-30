"""Orden completar_fecha_emision (Etapa 2, O2): ensayo por defecto; --aplicar exige --decision; lee fechaEmision del XML
autorizado (CDATA de <comprobante>) o del firmado con el analizador seguro, nunca sobrescribe y audita."""
import csv
import json
from datetime import date

import pytest
from django.core.files.base import ContentFile
from django.core.management import CommandError, call_command

from core.pos.management.commands.completar_fecha_emision import fecha_emision_del_xml
from core.pos.models import CreditNote, Receipt, Sale
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog
from tests.ayudas_ventas import factura_autorizada
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, producto  # noqa: F401

pytestmark = pytest.mark.django_db
FACTURA = ('<?xml version="1.0" encoding="UTF-8"?><factura id="comprobante" version="1.0.0"><infoTributaria><codDoc>01'
           '</codDoc></infoTributaria><infoFactura><fechaEmision>{fecha}</fechaEmision></infoFactura></factura>')
NOTA = ('<notaCredito id="comprobante" version="1.1.0"><infoTributaria><codDoc>04</codDoc></infoTributaria><infoNotaCredito>'
        '<fechaEmision>{fecha}</fechaEmision></infoNotaCredito></notaCredito>')
AUTORIZADO = ('<?xml version="1.0" encoding="UTF-8"?><autorizacion><estado>AUTORIZADO</estado><numeroAutorizacion>{clave}'
              '</numeroAutorizacion><fechaAutorizacion>01/10/2026 10:00:00</fechaAutorizacion><ambiente>PRODUCCIÓN</ambiente>'
              '<comprobante><![CDATA[{comprobante}]]></comprobante></autorizacion>')


def test_lectura_segura_del_xml():
    assert fecha_emision_del_xml(FACTURA.format(fecha='30/09/2026').encode()) == date(2026, 9, 30)
    autorizado = AUTORIZADO.format(clave='1' * 49, comprobante=NOTA.format(fecha='02/09/2026'))
    assert fecha_emision_del_xml(autorizado.encode()) == date(2026, 9, 2)
    assert fecha_emision_del_xml(b'') is None and fecha_emision_del_xml(b'no es xml') is None
    assert fecha_emision_del_xml(b'<!DOCTYPE x [<!ENTITY e "x">]><factura/>') is None          # DTD rechazada
    assert fecha_emision_del_xml(AUTORIZADO.replace('AUTORIZADO', 'NO AUTORIZADO').format(
        clave='1', comprobante=FACTURA.format(fecha='30/09/2026')).encode()) is None


def test_ensayo_decision_y_sin_sobrescribir(empresa, dueno, comprador, producto, tmp_path, capsys):  # noqa: F811
    autorizada = factura_autorizada(empresa, comprador, dueno, producto, fecha=date(2026, 10, 3), emitida=None,
                                    autorizada=date(2026, 10, 3))
    firmada = factura_autorizada(empresa, comprador, dueno, producto, fecha=date(2026, 10, 4), emitida=None, estado='canceled')
    sin_xml = factura_autorizada(empresa, comprador, dueno, producto, fecha=date(2026, 10, 5), emitida=None)
    con_fecha = factura_autorizada(empresa, comprador, dueno, producto, fecha=date(2026, 10, 6))
    with company_context(empresa):
        venta = Sale.objects.get(pk=autorizada.pk)
        venta.xml_authorized.save('autorizado.xml', ContentFile(AUTORIZADO.format(
            clave='1' * 49, comprobante=FACTURA.format(fecha='30/09/2026')).encode()), save=False)
        Sale.objects.filter(pk=venta.pk).update(xml_authorized=venta.xml_authorized.name)
        Sale.objects.filter(pk=firmada.pk).update(xml_signed=FACTURA.format(fecha='29/09/2026'))
        receipt = Receipt.objects.get_or_create(voucher_type='04', environment_type=2, establishment_code='001',
                                                issuing_point_code='002', defaults={'sequence': 0})[0]
        nota = CreditNote(sale=venta, receipt=receipt, voucher_number='000000099', voucher_number_full='001-002-000000099',
                          motive='Devolución', environment_type=2, status='authorized', xml_signed=NOTA.format(fecha='01/10/2026'))
        nota.save()
    informe = tmp_path / 'fechas.csv'
    call_command('completar_fecha_emision', '--empresa', empresa.ruc, '--informe', str(informe))
    salida = capsys.readouterr().out
    assert 'ENSAYO (no se cambió nada): documentos 4, sin fecha en el XML 1, completados 0' in salida
    assert f'sale {sin_xml.voucher_number_full}: registro 2026-10-05, XML — (sin XML)' in salida
    with open(informe, encoding='utf-8') as archivo:
        filas = {f['numero']: f for f in csv.DictReader(archivo)}
    assert (filas[autorizada.voucher_number_full]['fecha_xml'], filas[autorizada.voucher_number_full]['origen_xml']) == (
        '2026-09-30', 'autorizado')
    assert filas[firmada.voucher_number_full]['origen_xml'] == 'firmado' and con_fecha.voucher_number_full not in filas
    assert leer(empresa, lambda: Sale.objects.get(pk=autorizada.pk).emission_date) is None
    with pytest.raises(CommandError, match='--decision'):
        call_command('completar_fecha_emision', '--empresa', empresa.ruc, '--aplicar')
    call_command('completar_fecha_emision', '--empresa', empresa.ruc, '--aplicar', '--decision', 'Decisión de prueba')
    assert 'APLICADO: documentos 4, sin fecha en el XML 1, completados 3' in capsys.readouterr().out
    with company_context(empresa):
        assert Sale.objects.get(pk=autorizada.pk).emission_date == date(2026, 9, 30)
        assert Sale.objects.get(pk=firmada.pk).emission_date == date(2026, 9, 29)
        assert Sale.objects.get(pk=sin_xml.pk).emission_date is None
        assert Sale.objects.get(pk=con_fecha.pk).emission_date == date(2026, 10, 6)
        assert CreditNote.objects.get(pk=nota.pk).emission_date == date(2026, 10, 1)
    registro = AuditLog.objects.get(action='regularizacion_datos_origen')
    json.dumps(registro.detail)
    assert registro.detail['orden'] == 'completar_fecha_emision' and registro.detail['decision'] == 'Decisión de prueba'
    assert {d['numero']: d['fecha'] for d in registro.detail['documentos']} == {
        autorizada.voucher_number_full: '2026-09-30', firmada.voucher_number_full: '2026-09-29', '001-002-000000099': '2026-10-01'}
    call_command('completar_fecha_emision', '--empresa', empresa.ruc)
    assert 'documentos 1, sin fecha en el XML 1' in capsys.readouterr().out
