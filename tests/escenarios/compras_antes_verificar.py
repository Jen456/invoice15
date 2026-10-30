"""Comprueba que las compras, pagos y gastos anteriores a la Etapa 2 migraron sin cambios y marcados como incompletos."""
import json

from core.pos.models import (Company, DebtsPay, Expenses, PaymentsDebtsPay, Product, Provider, Purchase, PurchaseDetail,
                             TypeExpense)
from core.tenancy.context import platform_scope

with platform_scope():
    empresa = Company.objects.get(ruc='0991234567001')
    de = dict(company=empresa)
    resultado = {
        'conteos': [M.all_companies.filter(**de).count() for M in (Purchase, PurchaseDetail, DebtsPay, PaymentsDebtsPay,
                                                                    Provider, Expenses, TypeExpense)],
        'compras': [[c.number, str(c.subtotal), c.payment_type, c.version_datos, c.datos_incompletos, c.fuera_plazo_ats,
                     c.origen, c.tipo_comprobante, c.secuencial, c.forma_pago, c.parte_relacionada]
                    + [getattr(c, campo) for campo in ('base_0', 'base_gravada', 'base_5', 'base_no_objeto', 'base_exenta',
                                                        'total_descuento', 'total_iva', 'total_ice', 'total_irbpnr', 'propina',
                                                        'total')]
                    for c in Purchase.all_companies.filter(**de).order_by('number')],
        'lineas': [[d.cant, str(d.price), str(d.subtotal), d.product_id is not None, d.codigo_porcentaje, d.tarifa, d.total,
                    d.total_iva, str(d.total_dscto), d.descripcion]
                   for d in PurchaseDetail.all_companies.filter(**de).order_by('id')],
        'deudas': [[str(d.debt), str(d.saldo), d.state, d.base_calculo] for d in DebtsPay.all_companies.filter(**de)],
        'pagos': [[str(p.valor), p.medio_pago, p.referencia, p.registrado_por_id, p.registrado_en]
                  for p in PaymentsDebtsPay.all_companies.filter(**de)],
        'gastos': [[str(g.valor), g.medio_pago, g.referencia] for g in Expenses.all_companies.filter(**de)],
        'tipos_gasto': [[t.name, t.cod_sustento, t.cuenta_contable] for t in TypeExpense.all_companies.filter(**de)],
        'proveedores': [[p.ruc, p.tipo_identificacion, p.tipo_sujeto, p.parte_relacionada]
                        for p in Provider.all_companies.filter(**de)],
        'stock': Product.all_companies.get(company=empresa, code='HA-1').stock,
    }
print('RESULTADO=' + json.dumps(resultado, ensure_ascii=False, default=str))
