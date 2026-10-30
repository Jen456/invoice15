"""Auditoría de la Etapa 2 · ventas (O2): cada código de acción se registra desde su servicio, que maneja importes
Decimal y fechas reales, y el detalle guardado solo tiene texto, enteros, booleanos (y None donde el contrato lo admite):
AuditLog.detail aún no tiene DjangoJSONEncoder y un Decimal o una fecha deshacían la transacción entera."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from core.comprobantes import retenciones_recibidas as rr
from core.pos import anulados, cxc
from core.pos.models import CreditNote, Sale
from core.tenancy.context import company_context
from core.tenancy.models import AuditLog
from tests.ayudas_ventas import cxc_de, factura_autorizada, nota_credito_autorizada, peticion, retencion_datos
from tests.test_emision_sri import comprador, dueno, empresa, leer, p12, producto, sri  # noqa: F401

pytestmark = pytest.mark.django_db
HOY = timezone.localdate()
CODIGOS = ('comprobante_anulado_sri', 'retencion_recibida_registro', 'retencion_recibida_anulacion', 'cxc_cobro_eliminado',
           'regularizacion_datos_origen')


def solo_tipos_json(valor):
    if isinstance(valor, dict):
        return all(isinstance(k, str) and solo_tipos_json(v) for k, v in valor.items())
    if isinstance(valor, list):
        return all(solo_tipos_json(v) for v in valor)
    return valor is None or isinstance(valor, (str, int, bool))


def test_cada_codigo_con_detalle_serializable(empresa, dueno, comprador, producto, sri, tmp_path):  # noqa: F811
    venta = factura_autorizada(empresa, comprador, dueno, producto, credito=True, fecha=HOY - timedelta(days=2))
    with company_context(empresa):
        cobro = cxc.registrar_cobro(empresa, dueno, cxc_de(venta).pk, HOY - timedelta(days=1), Decimal('2.50'), 'efectivo')
        cxc.eliminar_cobro(peticion(dueno, empresa), cobro.pk)
        with transaction.atomic():
            ret = rr.registrar(empresa, dueno, venta, retencion_datos(), request=peticion(dueno, empresa))
        rr.anular(empresa, dueno, ret, 'El cliente anuló la retención en el SRI', request=peticion(dueno, empresa))
        anulados.marcar(empresa, dueno, 'factura', Sale.objects.get(pk=venta.pk), HOY, 'Anulada en SRI en línea por error',
                        request=peticion(dueno, empresa))
    # Regularización: una NC histórica (no_aplica) sobre otra factura a crédito
    otra = factura_autorizada(empresa, comprador, dueno, producto, credito=True)
    nota = nota_credito_autorizada(otra, sri=sri, autorizar=False)
    leer(empresa, lambda: CreditNote.objects.filter(pk=nota.pk).update(cxc_ajuste='no_aplica', status='authorized'))
    call_command('regularizar_cxc_historico', '--empresa', empresa.ruc, '--aplicar', '--decision', 'Prueba de auditoría',
                 '--informe', str(tmp_path / 'informe.csv'))
    registros = {r.action: r for r in AuditLog.objects.filter(action__in=CODIGOS)}
    assert set(registros) == set(CODIGOS)
    for codigo, registro in registros.items():
        registro.refresh_from_db()
        assert solo_tipos_json(registro.detail), (codigo, registro.detail)
        assert registro.company_id == empresa.pk
    assert registros['cxc_cobro_eliminado'].detail['valor'] == '2.50'
    assert registros['cxc_cobro_eliminado'].detail['fecha'] == (HOY - timedelta(days=1)).isoformat()
    assert registros['retencion_recibida_registro'].detail['total'] == '1.30'
    assert registros['retencion_recibida_anulacion'].detail['abono_revertido'] == '1.30'
    assert registros['comprobante_anulado_sri'].detail['fecha'] == HOY.isoformat()
    assert registros['regularizacion_datos_origen'].detail['documentos'][0]['valor'] == '23.00'
    assert all(r.user == dueno and r.ip == '127.0.0.1' for c, r in registros.items() if c != 'regularizacion_datos_origen')
