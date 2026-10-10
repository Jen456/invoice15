# Modelos de datos de empresa protegidos con seguridad por filas (tenancy 0002).
# Al añadir un modelo de empresa nuevo, crea también su política en una migración.
TENANT_MODELS_FOR_RLS = [
    'Provider', 'Category', 'Product', 'Purchase', 'PurchaseDetail', 'Client', 'Receipt', 'Sale', 'SaleDetail',
    'CtasCollect', 'PaymentsCtaCollect', 'DebtsPay', 'PaymentsDebtsPay', 'TypeExpense', 'Expenses', 'Promotions',
    'PromotionsDetail', 'VoucherErrors', 'CreditNote', 'CreditNoteDetail',
]
