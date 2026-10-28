"""Receptores de Compras para los comprobantes emitidos sobre una compra (espec-etapa2-compras §3.4).

No se usa post_save para la autorización: la emisión cambia el estado con QuerySet.update(), que no emite post_save.
Se usan las señales de B0 (core/pos/senales_comprobantes.py):
- comprobante_autorizado llega fuera de la transacción de la emisión y se repite al reenviar o consultar un comprobante
  ya autorizado: cada receptor es idempotente y abre su propia transacción (recalcular_de_compra, al_autorizar_liquidacion).
- anulado_en_sri llega dentro de la transacción que marca el comprobante anulado (O2): el recálculo queda en ella.
Escriben con update() filtrado por empresa; en PostgreSQL corren con la empresa del comprobante fijada (la vista o
consultar_pendientes con company_context).
"""
from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.comprobantes.models import LiquidacionCompra, Retencion
from core.pos import compras, cuentas_por_pagar
from core.pos.senales_comprobantes import anulado_en_sri, comprobante_autorizado


@receiver(comprobante_autorizado, sender=Retencion, dispatch_uid='fpa_cxp_retencion_autorizada')
@receiver(anulado_en_sri, sender=Retencion, dispatch_uid='fpa_cxp_retencion_anulada')
def retencion_cambia(sender, **kwargs):
    c = kwargs.get('comprobante') or kwargs['instance']
    cuentas_por_pagar.recalcular_de_compra(c.purchase_id, c.company_id)


@receiver(post_delete, sender=Retencion, dispatch_uid='fpa_cxp_retencion_borrada')     # delete() sí emite la señal
def retencion_borrada(sender, instance, **kwargs):
    cuentas_por_pagar.recalcular_de_compra(instance.purchase_id, instance.company_id)


@receiver(comprobante_autorizado, sender=LiquidacionCompra, dispatch_uid='fpa_compra_liquidacion_autorizada')
def liquidacion_autorizada(sender, comprobante, **kwargs):
    compras.al_autorizar_liquidacion(comprobante)


@receiver(anulado_en_sri, sender=LiquidacionCompra, dispatch_uid='fpa_compra_liquidacion_anulada')
def liquidacion_anulada(sender, instance, **kwargs):
    compras.al_anular_liquidacion(instance)
