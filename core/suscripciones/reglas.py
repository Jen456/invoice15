"""Qué módulos exige un plan pagado y qué se puede usar gratis.

Sin plan pagado la empresa usa el inventario (productos, categorías,
proveedores, compras y cuentas por pagar a proveedores) con los límites del
plan «gratuito», además de usuarios, perfil y datos de la empresa. Ventas,
facturación electrónica, clientes y el resto de reportes exigen un plan pagado.
"""
import calendar

PLAN_GRATUITO = 'gratuito'
URL_SUSCRIPCION = '/suscripcion/'

# Módulos de facturación y ventas: sin plan pagado no se abren.
RUTAS_DE_PAGO = (
    '/pos/sale/', '/pos/credit/note/', '/pos/client/', '/pos/receipt/', '/pos/voucher/errors/',
    '/pos/promotions/', '/pos/ctas/collect/', '/pos/expenses/', '/pos/type/expense/',
    '/reports/sale/', '/reports/expenses/', '/reports/ctas/collect/', '/reports/results/', '/reports/earnings/',
)

# Con el plan vencido o el cupo agotado se puede consultar, pero no emitir.
RUTAS_DE_EMISION = ('/pos/sale/admin/add/', '/pos/credit/note/admin/add/')
ACCIONES_DE_EMISION = ('generate_invoice', 'create_credit_note')

# Límites del plan gratuito si la plataforma no ha definido el plan (falla cerrado).
LIMITES_GRATUITO_POR_DEFECTO = {'product_limit': 50, 'provider_limit': 10, 'purchase_limit_month': 30}

# Avisos previos.
DIAS_AVISO_VENCIMIENTO = 30
PORCENTAJE_AVISO_CUPO = 10

# Un formulario de pago de PayPhone dura 10 minutos; damos margen antes de darlo por vencido.
MINUTOS_PAGO_PENDIENTE = 15


def requiere_plan(path):
    return path.startswith(RUTAS_DE_PAGO)


def es_emision(request):
    if request.path.startswith(RUTAS_DE_EMISION):
        return True
    return request.method == 'POST' and request.POST.get('action') in ACCIONES_DE_EMISION


def sumar_meses(fecha, meses):
    """Misma fecha y hora `meses` después; el 29-31 pasa al último día del mes si no existe."""
    mes = fecha.month - 1 + meses
    anio = fecha.year + mes // 12
    mes = mes % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return fecha.replace(year=anio, month=mes, day=dia)
