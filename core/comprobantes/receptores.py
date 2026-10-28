"""Receptores de comprobante_autorizado (Etapa 2, O2): la nota de crédito autorizada abona la cuenta por cobrar de su
factura y la nota de débito autorizada crea la suya (core/pos/cxc.py).

No atrapan excepciones: la emisión los llama con send_robust, registra el error en «Errores de comprobantes» y el estado
autorizado nunca cambia; el documento queda en cxc_ajuste='pendiente' para la orden aplicar_ajustes_cxc. Son idempotentes
(la emisión vuelve a enviar la señal al reenviar o consultar un comprobante ya autorizado) y abren su propia transacción.
Corren en el contexto de empresa que ya fijan la vista o consultar_pendientes; si no hay uno (o es otro), usan el de la
empresa del propio comprobante.
"""
from django.dispatch import receiver

from core.comprobantes.models import NotaDebito
from core.pos import cxc
from core.pos.models import CreditNote
from core.pos.senales_comprobantes import comprobante_autorizado
from core.tenancy.context import company_context, current_company_id


def _en_su_empresa(comprobante, funcion):
    if current_company_id() == comprobante.company_id:
        return funcion(comprobante.pk)
    with company_context(comprobante.company):
        return funcion(comprobante.pk)


@receiver(comprobante_autorizado, sender=CreditNote, dispatch_uid='o2_cxc_nc')
def _nc_autorizada(sender, comprobante, **kwargs):
    _en_su_empresa(comprobante, cxc.aplicar_nota_credito)


@receiver(comprobante_autorizado, sender=NotaDebito, dispatch_uid='o2_cxc_nd')
def _nd_autorizada(sender, comprobante, **kwargs):
    _en_su_empresa(comprobante, cxc.aplicar_nota_debito)
