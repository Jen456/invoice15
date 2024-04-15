from django.urls import path

from core.pos.views.category.views import *
from core.pos.views.client.views import *
from core.pos.views.company.views import CompanyUpdateView
from core.pos.views.credit_note.views import *
from core.pos.views.ctas_collect.views import *
from core.pos.views.debts_pay.views import *
from core.pos.views.expenses.views import *
from core.pos.views.product.views import *
from core.pos.views.promotions.views import *
from core.pos.views.provider.views import *
from core.pos.views.purchase.views import *
from core.pos.views.voucher_errors.views import *
from core.pos.views.receipt.views import *
from core.pos.views.sale.views import *
from core.pos.views.type_expense.views import *

urlpatterns = [
    # company
    path('company/update/', CompanyUpdateView.as_view(), name='company_update'),
    # provider
    path('provider/', ProviderListView.as_view(), name='provider_list'),
    path('provider/add/', ProviderCreateView.as_view(), name='provider_create'),
    path('provider/update/<int:pk>/', ProviderUpdateView.as_view(), name='provider_update'),
    path('provider/delete/<int:pk>/', ProviderDeleteView.as_view(), name='provider_delete'),
    # receipt
    path('receipt/', ReceiptListView.as_view(), name='receipt_list'),
    path('receipt/add/', ReceiptCreateView.as_view(), name='receipt_create'),
    path('receipt/update/<int:pk>/', ReceiptUpdateView.as_view(), name='receipt_update'),
    path('receipt/delete/<int:pk>/', ReceiptDeleteView.as_view(), name='receipt_delete'),
    # category
    path('category/', CategoryListView.as_view(), name='category_list'),
    path('category/add/', CategoryCreateView.as_view(), name='category_create'),
    path('category/update/<int:pk>/', CategoryUpdateView.as_view(), name='category_update'),
    path('category/delete/<int:pk>/', CategoryDeleteView.as_view(), name='category_delete'),
    # product
    path('product/', ProductListView.as_view(), name='product_list'),
    path('product/add/', ProductCreateView.as_view(), name='product_create'),
    path('product/update/<int:pk>/', ProductUpdateView.as_view(), name='product_update'),
    path('product/delete/<int:pk>/', ProductDeleteView.as_view(), name='product_delete'),
    path('product/stock/adjustment/', ProductStockAdjustmentView.as_view(), name='product_stock_adjustment'),
    path('product/export/excel/', ProductExportExcelView.as_view(), name='product_export_excel'),
    # purchase
    path('purchase/', PurchaseListView.as_view(), name='purchase_list'),
    path('purchase/add/', PurchaseCreateView.as_view(), name='purchase_create'),
    path('purchase/delete/<int:pk>/', PurchaseDeleteView.as_view(), name='purchase_delete'),
    # type_expense
    path('type/expense/', TypeExpenseListView.as_view(), name='type_expense_list'),
    path('type/expense/add/', TypeExpenseCreateView.as_view(), name='type_expense_create'),
    path('type/expense/update/<int:pk>/', TypeExpenseUpdateView.as_view(), name='type_expense_update'),
    path('type/expense/delete/<int:pk>/', TypeExpenseDeleteView.as_view(), name='type_expense_delete'),
    # expenses
    path('expenses/', ExpensesListView.as_view(), name='expenses_list'),
    path('expenses/add/', ExpensesCreateView.as_view(), name='expenses_create'),
    path('expenses/update/<int:pk>/', ExpensesUpdateView.as_view(), name='expenses_update'),
    path('expenses/delete/<int:pk>/', ExpensesDeleteView.as_view(), name='expenses_delete'),
    # debts_pay
    path('debts/pay/', DebtsPayListView.as_view(), name='debts_pay_list'),
    path('debts/pay/add/', DebtsPayCreateView.as_view(), name='debts_pay_create'),
    path('debts/pay/delete/<int:pk>/', DebtsPayDeleteView.as_view(), name='debts_pay_delete'),
    # ctas_collect
    path('ctas/collect/', CtasCollectListView.as_view(), name='ctas_collect_list'),
    path('ctas/collect/add/', CtasCollectCreateView.as_view(), name='ctas_collect_create'),
    path('ctas/collect/delete/<int:pk>/', CtasCollectDeleteView.as_view(), name='ctas_collect_delete'),
    # promotions
    path('promotions/', PromotionsListView.as_view(), name='promotions_list'),
    path('promotions/add/', PromotionsCreateView.as_view(), name='promotions_create'),
    path('promotions/update/<int:pk>/', PromotionsUpdateView.as_view(), name='promotions_update'),
    path('promotions/delete/<int:pk>/', PromotionsDeleteView.as_view(), name='promotions_delete'),
    # client
    path('client/', ClientListView.as_view(), name='client_list'),
    path('client/add/', ClientCreateView.as_view(), name='client_create'),
    path('client/update/<int:pk>/', ClientUpdateView.as_view(), name='client_update'),
    path('client/delete/<int:pk>/', ClientDeleteView.as_view(), name='client_delete'),
    path('client/update/profile/', ClientUpdateProfileView.as_view(), name='client_update_profile'),
    # sale/admin
    path('sale/admin/', SaleListView.as_view(), name='sale_admin_list'),
    path('sale/admin/add/', SaleCreateView.as_view(), name='sale_admin_create'),
    path('sale/admin/delete/<int:pk>/', SaleDeleteView.as_view(), name='sale_admin_delete'),
    path('sale/admin/print/invoice/<int:pk>/', SalePrintInvoiceView.as_view(), name='sale_admin_print_invoice'),
    path('sale/client/', SaleClientListView.as_view(), name='sale_client_list'),
    path('sale/client/print/invoice/<int:pk>/', SalePrintInvoiceView.as_view(), name='sale_client_print_invoice'),
    # credit_note
    path('credit/note/admin/', CreditNoteListView.as_view(), name='credit_note_admin_list'),
    path('credit/note/admin/add/', CreditNoteCreateView.as_view(), name='credit_note_admin_create'),
    path('credit/note/admin/delete/<int:pk>/', CreditNoteDeleteView.as_view(), name='credit_note_admin_delete'),
    path('credit/note/client/', CreditNoteClientListView.as_view(), name='credit_note_client_list'),
    # voucher_errors
    path('voucher/errors/', VoucherErrorsListView.as_view(), name='voucher_errors_list'),
    path('voucher/errors/delete/<int:pk>/', VoucherErrorsDeleteView.as_view(), name='voucher_errors_delete'),
]
