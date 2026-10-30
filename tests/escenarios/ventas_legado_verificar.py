"""Comprueba que las ventas «de antes» siguen igual tras las migraciones de la Etapa 2 (O2): nada se recalcula."""
import json

from core.comprobantes.models import NotaDebito
from core.pos.models import Company, CreditNote, CtasCollect, PaymentsCtaCollect, Sale
from core.tenancy.context import company_context

empresa = Company.objects.get(ruc='0990000001001')
with company_context(empresa):
    cuenta = CtasCollect.objects.get()
    resultado = {
        'empresa': [empresa.tipo_contribuyente, empresa.periodicidad_iva, empresa.special_taxpayer],
        'abonos': list(PaymentsCtaCollect.objects.values_list('tipo', 'medio_pago', 'referencia', 'valor', 'description')),
        'abonos_registro': list(PaymentsCtaCollect.objects.values_list('registrado_por', 'registrado_en', 'anulado_en')),
        'cxc': [CtasCollect.objects.count(), str(cuenta.debt), str(cuenta.saldo), cuenta.state],
        'notas_credito': list(CreditNote.objects.values_list('cxc_ajuste', 'abono_cxc', 'anulado_sri_fecha')),
        'notas_debito': list(NotaDebito.objects.values_list('cxc_ajuste', 'cuenta_por_cobrar', 'anulado_sri_fecha')),
        'venta': list(Sale.objects.values_list('emission_date', 'status', 'anulado_sri_fecha', 'anulado_sri_stock')),
    }
print('RESULTADO=' + json.dumps(resultado, default=str, ensure_ascii=False))
