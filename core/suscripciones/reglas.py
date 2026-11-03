"""Qué módulos exige un plan pagado y qué se puede usar gratis.

Sin plan pagado la empresa usa el inventario (productos, categorías,
proveedores, compras y cuentas por pagar a proveedores) con los límites del
plan «gratuito», además de usuarios, perfil y datos de la empresa. Ventas,
facturación electrónica, clientes, proformas y el resto de reportes exigen un plan pagado.
Las proformas no consumen cupo: con el cupo agotado solo se bloquea «Facturar» (la
pantalla de venta está en RUTAS_DE_EMISION).
"""
import calendar

PLAN_GRATUITO = 'gratuito'
URL_SUSCRIPCION = '/suscripcion/'

# Módulos de facturación y ventas: sin plan pagado no se abren.
RUTAS_DE_PAGO = (
    '/pos/sale/', '/pos/credit/note/', '/pos/client/', '/pos/receipt/', '/pos/voucher/errors/',
    '/pos/promotions/', '/pos/ctas/collect/', '/pos/expenses/', '/pos/type/expense/',
    '/reports/sale/', '/reports/expenses/', '/reports/ctas/collect/', '/reports/results/', '/reports/earnings/',
    '/comprobantes/', '/proformas/', '/cobros/', '/tributario/', '/contabilidad/',
)

# Complemento Contable (plan §3.8): libros, revisión del mes, ATS, borradores del 104/103 y kardex. Su precio, vigencia y
# cobertura (D9) no están aprobados: no se habilita comercialmente. Además del plan pagado, la empresa debe estar en
# FPA_COMPLEMENTO_CONTABLE_REVISION (RUC), la lista de revisión que fija la plataforma; vacía, nadie lo abre. «*» (todas)
# vale solo en desarrollo y en las pruebas automáticas, nunca en un despliegue.
RUTAS_COMPLEMENTO_CONTABLE = ('/tributario/', '/contabilidad/')
MENSAJE_COMPLEMENTO = ('El Complemento Contable (libros, revisión del mes, ATS, borradores del 104 y del 103, kardex e '
                       'inventario valorizado) todavía no está disponible: su precio y sus condiciones están por anunciar.')
ENTORNOS_LOCALES = ('desarrollo', 'pruebas_automaticas')


# Incluidos solo en los planes ilimitados (Ilimitado y Multiempresa), por decisión comercial del 15/10/2026.
# No consumen cupo de emisión.
RUTAS_ILIMITADAS = ('/importacion/',)
MENSAJE_SOLO_ILIMITADO = ('La importación de comprobantes recibidos (XML y RIDE) está incluida en los planes Ilimitado y '
                          'Multiempresa.')

# Con el plan vencido o el cupo agotado se puede consultar, pero no emitir.
RUTAS_DE_EMISION = ('/pos/sale/admin/add/', '/pos/credit/note/admin/add/', '/comprobantes/retenciones/nueva/',
                    '/comprobantes/liquidaciones/nueva/', '/comprobantes/notas-debito/nueva/', '/comprobantes/guias/nueva/')
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


def requiere_ilimitado(path):
    return path.startswith(RUTAS_ILIMITADAS)


def requiere_complemento(path):
    return path.startswith(RUTAS_COMPLEMENTO_CONTABLE)


def complemento_habilitado(company):
    """La empresa puede abrir el Complemento Contable: está en la lista de revisión (el plan pagado se exige aparte)."""
    from django.conf import settings
    if company is None:
        return False
    lista = {str(x).strip() for x in getattr(settings, 'FPA_COMPLEMENTO_CONTABLE_REVISION', None) or [] if str(x).strip()}
    if '*' in lista and getattr(settings, 'FPA_ENTORNO', '') in ENTORNOS_LOCALES:
        return True
    if not company.ruc or company.ruc not in lista:
        return False
    from core.pos.models import Company
    # Un RUC de la lista que comparte otra empresa no abre nada (nadie se cubre copiando el RUC de una empresa cubierta).
    return not Company.objects.filter(ruc=company.ruc).exclude(pk=company.pk).exists()


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
