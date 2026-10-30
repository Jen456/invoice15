"""Señales comunes de los comprobantes electrónicos emitidos (fase contable, commit B0).

Los módulos que ajustan cuentas al cambiar un comprobante (cuentas por cobrar y por pagar, compras de una liquidación…)
se conectan aquí sin editar la emisión. El `sender` es la clase del comprobante (Sale, CreditNote, Retencion,
LiquidacionCompra, NotaDebito o GuiaRemision); cada receptor lo filtra con `sender=` y un `dispatch_uid`.

- comprobante_autorizado (kwarg `comprobante`): la emite core/pos/emision._despues_de_autorizar con `send_robust`
  cuando el SRI autoriza el comprobante, después del RIDE (y de actualizar la factura en la nota de crédito) y antes
  del correo, fuera de la transacción de la emisión. La reciben O1 (cuentas por pagar y compra de la liquidación) y O2
  (cuenta por cobrar de la nota de crédito y de débito). El error de un receptor queda en «Errores de comprobantes» y
  nunca cambia el estado autorizado. Se vuelve a emitir cuando se reenvía o consulta un comprobante que ya estaba
  autorizado: los receptores son idempotentes y abren su propia transacción.
- anulado_en_sri (kwargs `instance`, `usuario`, `fecha`): la emite core/pos/anulados.marcar (O2) con `send`, dentro de
  la transacción que marca el comprobante como «Anulado en el SRI»; si un receptor falla, la marca se deshace. La
  reciben O1 (retención emitida → cuenta por pagar; liquidación → compra) y, si la propietaria lo decide, Proformas
  (factura → libera la proforma).
"""
from django.dispatch import Signal

comprobante_autorizado = Signal()   # kwargs: comprobante
anulado_en_sri = Signal()           # kwargs: instance, usuario, fecha (date de la anulación en el SRI)
